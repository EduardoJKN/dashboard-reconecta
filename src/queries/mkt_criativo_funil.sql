-- =============================================================================
-- Funil POR CRIATIVO (grão `ad_name` consolidado).
-- =============================================================================
-- 1 linha por `ad_name_norm` no período, com mídia + funil completo até venda
-- nova. Alimenta a seção "Funil do criativo selecionado" da página Criativos.
--
-- Match único viável: `lower(btrim(criativos.ad_name)) =
-- lower(btrim(leads.utm_content))`. Validado em pgAdmin: `ad_id` está vazio
-- em ext_reconecta.leads / zoho_deals / zoho_activities (0 preenchidos
-- em abr/2026), então não dá pra cruzar por id. Fuzzy/normalização extra
-- não compensa — utm_content é token estruturado.
--
-- Granularidade `ad_name`, NÃO `ad_id`. Mesmo criativo replicado em
-- vários ad_ids (CBO/A-B; média 4,9 ad_ids/ad_name em abr/2026, máx 51).
-- Soma mídia (invest/imp/cliques) dos ad_ids de mesmo nome; leads não
-- inflam porque utm_content é o nome.
--
-- Lead → deal: priority `zoho_id > session_id > email` (mesma regra
-- Visão Geral / Growth / Campanhas).
-- Deal → activity: zoho_activities.what_id = deal_id, activity_type IN
-- ('Consulta','Indicação'), start_datetime na janela. Comparecimento
-- exige status_reuniao='Concluída'.
-- Venda nova: deal stage IN ('Ganho','Fechado Ganho') AND
-- tipo_venda='Novo cliente'.
--
-- Validação abr/2026 (cross-checks alvo):
--   2025_SEM50_AD05            invest 16.967 · imp 191k · clk 2410 · qtd 51
--                              leads 155 · +12 55 · agend 49 · compar 29 · novas 4
--   2025_SEM40_AD02_1          leads 101 · +12 16 · agend 30 · compar 23 · novas 2
--   [26][16][AD013_1][AB] - Fazendo tudo sozinha
--                              leads 64  · +12 10 · agend 10 · compar 7  · novas 0
-- =============================================================================
WITH
-- -----------------------------------------------------------------------------
-- 1) Mídia consolidada por ad_name (soma os múltiplos ad_ids do mesmo nome).
-- -----------------------------------------------------------------------------
criativos AS (
    SELECT
        lower(btrim(ad_name))               AS ad_name_norm,
        ad_id,
        ad_name,
        campaign_name,
        adset_name,
        effective_status,
        quality_ranking,
        engagement_ranking,
        conversion_ranking,
        thumbnail_url,
        image_url,
        permalink_url,
        investimento,
        impressoes,
        cliques,
        link_clicks,
        alcance
    FROM bi.vw_mkt_criativos
    WHERE data_ref BETWEEN :data_ini AND :data_fim
      AND ad_name IS NOT NULL
      AND btrim(ad_name) <> ''
),
midia_agg AS (
    SELECT
        ad_name_norm,
        MAX(ad_name)                            AS ad_name,
        COUNT(DISTINCT ad_id)                   AS qtd_adids,
        SUM(investimento)::numeric              AS investimento,
        SUM(impressoes)::bigint                 AS impressoes,
        SUM(cliques)::bigint                    AS cliques,
        SUM(link_clicks)::bigint                AS link_clicks,
        SUM(alcance)::bigint                    AS alcance
    FROM criativos
    GROUP BY ad_name_norm
),
-- "Principal" por ad_name = a row do ad_id com maior investimento. Quebra
-- empate por max(data_ref) só pra ser determinístico.
midia_principal AS (
    SELECT DISTINCT ON (ad_name_norm)
        ad_name_norm,
        campaign_name                            AS campaign_name_principal,
        adset_name                               AS adset_name_principal,
        effective_status                         AS effective_status_principal,
        quality_ranking                          AS quality_ranking_principal,
        engagement_ranking                       AS engagement_ranking_principal,
        conversion_ranking                       AS conversion_ranking_principal,
        thumbnail_url,
        image_url,
        permalink_url
    FROM criativos
    ORDER BY ad_name_norm, investimento DESC NULLS LAST, ad_id
),

-- -----------------------------------------------------------------------------
-- 2) Leads — base limpa filtrada por utm_content casável com algum ad_name.
-- -----------------------------------------------------------------------------
leads_clean AS (
    SELECT
        l.id::text                              AS lead_id,
        lower(btrim(l.email))                   AS email_norm,
        NULLIF(btrim(l.zoho_id), '')            AS lead_zoho_id,
        l.session_id                            AS lead_session_id,
        l.classificado,
        l.created_at,
        lower(btrim(l.utm_content))             AS utm_content_norm
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
      AND l.utm_content IS NOT NULL
      AND btrim(l.utm_content) <> ''
),
-- 1 linha por (utm_content_norm, e-mail) — period-distinct. Permite que o
-- mesmo e-mail conte 1× em CADA criativo onde apareceu.
distinct_email_criativo AS (
    SELECT DISTINCT utm_content_norm, email_norm
    FROM leads_clean
),
-- Última classificação POR E-MAIL no período (regra global, igual à
-- Visão Geral). Não depende do criativo — vale pra todas as rows do e-mail.
last_classif AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- Chaves do lead (zoho_id / session_id) pra alimentar o priority match.
-- Pega a row mais recente por e-mail (consistente com last_classif).
email_lead_keys AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        lead_zoho_id,
        lead_session_id
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- Leads por ad_name (todos os filtros + classificação).
leads_por_criativo AS (
    SELECT
        dec.utm_content_norm                                    AS ad_name_norm,
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
    FROM distinct_email_criativo dec
    LEFT JOIN last_classif c USING (email_norm)
    GROUP BY dec.utm_content_norm
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
    -- 1 deal por e-mail (regra oficial Visão Geral).
    SELECT DISTINCT ON (email_norm)
        email_norm,
        deal_id,
        deal_stage,
        deal_tipo_venda
    FROM all_deal_matches
    ORDER BY email_norm, prio, deal_created_at DESC NULLS LAST
),

-- -----------------------------------------------------------------------------
-- 4) Activities (agendamentos / comparecimentos) — leads únicos por criativo.
-- -----------------------------------------------------------------------------
-- Activities da janela ligadas via deal pareado. Conta leads únicos
-- (não count de activities) — um lead que reagenda conta 1× só.
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
funil_por_criativo AS (
    SELECT
        dec.utm_content_norm                                    AS ad_name_norm,
        COUNT(DISTINCT a.email_norm)::bigint                    AS agendamentos,
        COUNT(DISTINCT a.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos,
        COUNT(DISTINCT lwd.email_norm) FILTER (
            WHERE lwd.deal_stage IN ('Ganho','Fechado Ganho')
              AND lwd.deal_tipo_venda = 'Novo cliente'
        )::bigint                                               AS vendas_novas
    FROM distinct_email_criativo dec
    LEFT JOIN leads_with_deal lwd USING (email_norm)
    LEFT JOIN activities_in_window a USING (email_norm)
    GROUP BY dec.utm_content_norm
),

-- -----------------------------------------------------------------------------
-- 5) Universo: união dos ad_names — preserva criativos com invest mas sem
--    leads (funil zerado nas etapas pós-clique).
-- -----------------------------------------------------------------------------
universo AS (
    SELECT ad_name_norm FROM midia_agg
    UNION
    SELECT ad_name_norm FROM leads_por_criativo
)

SELECT
    u.ad_name_norm,
    -- Identificação
    COALESCE(ma.ad_name, lpc_first_name.ad_name)               AS ad_name,
    mp.campaign_name_principal                                  AS campaign_name,
    mp.adset_name_principal                                     AS adset_name,
    mp.effective_status_principal                               AS effective_status,
    mp.quality_ranking_principal                                AS quality_ranking,
    mp.engagement_ranking_principal                             AS engagement_ranking,
    mp.conversion_ranking_principal                             AS conversion_ranking,
    mp.thumbnail_url                                            AS thumbnail_url,
    mp.image_url                                                AS image_url,
    mp.permalink_url                                            AS permalink_url,
    COALESCE(ma.qtd_adids, 0)::bigint                           AS qtd_adids,
    -- Mídia
    COALESCE(ma.investimento, 0)::numeric                       AS investimento,
    COALESCE(ma.impressoes, 0)::bigint                          AS impressoes,
    COALESCE(ma.cliques, 0)::bigint                             AS cliques,
    COALESCE(ma.link_clicks, 0)::bigint                         AS link_clicks,
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
LEFT JOIN midia_agg          ma  USING (ad_name_norm)
LEFT JOIN midia_principal    mp  USING (ad_name_norm)
LEFT JOIN leads_por_criativo lpc USING (ad_name_norm)
LEFT JOIN funil_por_criativo fpc USING (ad_name_norm)
-- Fallback caso o criativo só apareça no lado leads (ad_name removido entre
-- reportes) — aproveita o próprio utm_content como display name.
LEFT JOIN LATERAL (SELECT u.ad_name_norm AS ad_name) lpc_first_name ON TRUE
ORDER BY investimento DESC NULLS LAST, leads_totais DESC NULLS LAST;
