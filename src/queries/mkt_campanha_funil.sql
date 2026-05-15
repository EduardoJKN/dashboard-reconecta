-- =============================================================================
-- Funil POR CAMPANHA (grão `campaign_name` consolidado).
-- =============================================================================
-- 1 linha por `campaign_name_norm` no período, com mídia + funil completo até
-- venda nova. Espelho de `mkt_criativo_funil.sql` — mesmas regras, só muda o
-- grão (campaign_name em vez de ad_name; utm_campaign em vez de utm_content).
-- Alimenta a seção "Funil da campanha selecionada" da página Campanhas.
--
-- Match único viável: `lower(btrim(campanhas.campaign_name)) =
-- lower(btrim(leads.utm_campaign))`. Validado em pgAdmin: `campaign_id` não
-- está populado nos leads (mesma situação do `ad_id`), então não dá pra
-- cruzar por id. Mesma estratégia já em uso em mkt_campanhas_leads_por_utm.sql.
--
-- Granularidade `campaign_name`, NÃO `campaign_id`. Mesma campanha pode ter
-- múltiplos `campaign_id` (cópias, CBO, etc.). Soma mídia (invest/imp/cliques)
-- dos campaign_ids de mesmo nome; leads não inflam porque utm_campaign é o
-- nome.
--
-- Lead → deal: priority `zoho_id > session_id > email` (mesma regra
-- Visão Geral / Growth / Funil criativo).
-- Deal → activity: zoho_activities.what_id = deal_id, activity_type IN
-- ('Consulta','Indicação'), start_datetime na janela. Comparecimento
-- exige status_reuniao='Concluída'.
-- Venda nova: deal stage IN ('Ganho','Fechado Ganho') AND
-- tipo_venda='Novo cliente'.
-- =============================================================================
WITH
-- -----------------------------------------------------------------------------
-- 1) Mídia consolidada por campaign_name (soma os múltiplos campaign_ids).
-- -----------------------------------------------------------------------------
campanhas AS (
    SELECT
        lower(btrim(campaign_name))         AS campaign_name_norm,
        campaign_id,
        campaign_name,
        canal,
        objetivo,
        investimento,
        impressoes,
        cliques,
        alcance
    FROM bi.vw_mkt_campanhas
    WHERE data_ref BETWEEN :data_ini AND :data_fim
      AND campaign_name IS NOT NULL
      AND btrim(campaign_name) <> ''
),
midia_agg AS (
    SELECT
        campaign_name_norm,
        MAX(campaign_name)                       AS campaign_name,
        COUNT(DISTINCT campaign_id)              AS qtd_adids,
        SUM(investimento)::numeric               AS investimento,
        SUM(impressoes)::bigint                  AS impressoes,
        SUM(cliques)::bigint                     AS cliques,
        SUM(alcance)::bigint                     AS alcance
    FROM campanhas
    GROUP BY campaign_name_norm
),
-- "Principal" por campaign_name = a row do campaign_id com maior investimento.
-- Quebra empate por campaign_id pra ser determinístico.
midia_principal AS (
    SELECT DISTINCT ON (campaign_name_norm)
        campaign_name_norm,
        canal                                    AS canal_principal,
        objetivo                                 AS objetivo_principal
    FROM campanhas
    ORDER BY campaign_name_norm, investimento DESC NULLS LAST, campaign_id
),

-- -----------------------------------------------------------------------------
-- 2) Leads — base limpa filtrada por utm_campaign casável com algum campaign_name.
-- -----------------------------------------------------------------------------
leads_clean AS (
    SELECT
        l.id::text                              AS lead_id,
        lower(btrim(l.email))                   AS email_norm,
        NULLIF(btrim(l.zoho_id), '')            AS lead_zoho_id,
        l.session_id                            AS lead_session_id,
        l.classificado,
        l.created_at,
        lower(btrim(l.utm_campaign))            AS utm_campaign_norm
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
      AND l.utm_campaign IS NOT NULL
      AND btrim(l.utm_campaign) <> ''
),
-- 1 linha por (utm_campaign_norm, e-mail) — period-distinct. Permite que o
-- mesmo e-mail conte 1× em CADA campanha onde apareceu.
distinct_email_campanha AS (
    SELECT DISTINCT utm_campaign_norm, email_norm
    FROM leads_clean
),
-- Última classificação POR E-MAIL no período (regra global, igual à
-- Visão Geral). Não depende da campanha — vale pra todas as rows do e-mail.
last_classif AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- Chaves do lead (zoho_id / session_id) pra alimentar o priority match.
email_lead_keys AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        lead_zoho_id,
        lead_session_id
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- Leads por campaign_name (todos os filtros + classificação).
leads_por_campanha AS (
    SELECT
        dec.utm_campaign_norm                                   AS campaign_name_norm,
        COUNT(*)::bigint                                        AS leads_totais,
        COUNT(*) FILTER (
            WHERE c.classif_final ILIKE '%+12%' OR c.classif_final ILIKE '%-12%'
        )::bigint                                               AS leads_qualificados,
        COUNT(*) FILTER (WHERE c.classif_final ILIKE '%+12%')::bigint
                                                                AS leads_mais_12,
        COUNT(*) FILTER (WHERE c.classif_final ILIKE '%-12%')::bigint
                                                                AS leads_menos_12,
        COUNT(*) FILTER (
            WHERE c.classif_final ILIKE '%não atua%'
        )::bigint                                               AS leads_nao_atua
    FROM distinct_email_campanha dec
    LEFT JOIN last_classif c USING (email_norm)
    GROUP BY dec.utm_campaign_norm
),

-- -----------------------------------------------------------------------------
-- 3) Lead → Deal (priority match zoho_id > session_id > email).
-- -----------------------------------------------------------------------------
all_deal_matches AS (
    SELECT elk.email_norm, zd.id AS deal_id, zd.stage AS deal_stage,
           zd.tipo_venda AS deal_tipo_venda, zd.created_at AS deal_created_at,
           1 AS prio
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON elk.lead_zoho_id = zd.id
    WHERE elk.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT elk.email_norm, zd.id, zd.stage, zd.tipo_venda, zd.created_at, 2
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON elk.lead_session_id::text = zd.session_id
    WHERE elk.lead_session_id IS NOT NULL
    UNION ALL
    SELECT elk.email_norm, zd.id, zd.stage, zd.tipo_venda, zd.created_at, 3
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = elk.email_norm
),
leads_with_deal AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        deal_id,
        deal_stage,
        deal_tipo_venda
    FROM all_deal_matches
    ORDER BY email_norm, prio, deal_created_at DESC NULLS LAST
),

-- -----------------------------------------------------------------------------
-- 4) Activities (agendamentos / comparecimentos) — leads únicos por campanha.
-- -----------------------------------------------------------------------------
activities_in_window AS (
    SELECT
        lwd.email_norm,
        za.id            AS activity_id,
        za.status_reuniao
    FROM leads_with_deal lwd
    JOIN zoho_activities za ON za.what_id = lwd.deal_id
    WHERE lwd.deal_id IS NOT NULL
      AND za.activity_type IN ('Consulta', 'Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
),
funil_por_campanha AS (
    SELECT
        dec.utm_campaign_norm                                   AS campaign_name_norm,
        COUNT(DISTINCT a.email_norm)::bigint                    AS agendamentos,
        COUNT(DISTINCT a.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos,
        COUNT(DISTINCT lwd.email_norm) FILTER (
            WHERE lwd.deal_stage IN ('Ganho','Fechado Ganho')
              AND lwd.deal_tipo_venda = 'Novo cliente'
        )::bigint                                               AS vendas_novas
    FROM distinct_email_campanha dec
    LEFT JOIN leads_with_deal lwd USING (email_norm)
    LEFT JOIN activities_in_window a USING (email_norm)
    GROUP BY dec.utm_campaign_norm
),

-- -----------------------------------------------------------------------------
-- 5) Universo: união dos campaign_names — preserva campanhas com invest mas
--    sem leads (funil zerado nas etapas pós-clique).
-- -----------------------------------------------------------------------------
universo AS (
    SELECT campaign_name_norm FROM midia_agg
    UNION
    SELECT campaign_name_norm FROM leads_por_campanha
)

SELECT
    u.campaign_name_norm,
    -- Identificação
    COALESCE(ma.campaign_name, lpc_first_name.campaign_name)    AS campaign_name,
    mp.canal_principal                                          AS canal,
    mp.objetivo_principal                                       AS objetivo,
    COALESCE(ma.qtd_adids, 0)::bigint                           AS qtd_adids,
    -- Mídia
    COALESCE(ma.investimento, 0)::numeric                       AS investimento,
    COALESCE(ma.impressoes, 0)::bigint                          AS impressoes,
    COALESCE(ma.cliques, 0)::bigint                             AS cliques,
    COALESCE(ma.alcance, 0)::bigint                             AS alcance,
    CASE WHEN COALESCE(ma.impressoes, 0) = 0 THEN 0::numeric
         ELSE ma.cliques::numeric / ma.impressoes * 100
    END                                                         AS ctr,
    CASE WHEN COALESCE(ma.cliques, 0) = 0 THEN 0::numeric
         ELSE ma.investimento / ma.cliques
    END                                                         AS cpc,
    -- Leads
    COALESCE(lpc.leads_totais, 0)::bigint                       AS leads_totais,
    COALESCE(lpc.leads_qualificados, 0)::bigint                 AS leads_qualificados,
    COALESCE(lpc.leads_mais_12, 0)::bigint                      AS leads_mais_12,
    COALESCE(lpc.leads_menos_12, 0)::bigint                     AS leads_menos_12,
    COALESCE(lpc.leads_nao_atua, 0)::bigint                     AS leads_nao_atua,
    -- Funil
    COALESCE(fpc.agendamentos, 0)::bigint                       AS agendamentos,
    COALESCE(fpc.comparecimentos, 0)::bigint                    AS comparecimentos,
    COALESCE(fpc.vendas_novas, 0)::bigint                       AS vendas_novas,
    -- Derivadas
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(lpc.leads_qualificados, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_qualificacao,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(lpc.leads_mais_12, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_mais_12,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(fpc.agendamentos, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_agendamento,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(fpc.comparecimentos, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_comparecimento,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(fpc.vendas_novas, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_venda_nova,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / lpc.leads_totais
    END                                                         AS cpl,
    CASE WHEN COALESCE(lpc.leads_mais_12, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / lpc.leads_mais_12
    END                                                         AS cpl_mais_12,
    CASE WHEN COALESCE(fpc.vendas_novas, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / fpc.vendas_novas
    END                                                         AS cac
FROM universo u
LEFT JOIN midia_agg          ma  USING (campaign_name_norm)
LEFT JOIN midia_principal    mp  USING (campaign_name_norm)
LEFT JOIN leads_por_campanha lpc USING (campaign_name_norm)
LEFT JOIN funil_por_campanha fpc USING (campaign_name_norm)
LEFT JOIN LATERAL (SELECT u.campaign_name_norm AS campaign_name) lpc_first_name ON TRUE
ORDER BY investimento DESC NULLS LAST, leads_totais DESC NULLS LAST;
