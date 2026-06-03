-- =============================================================================
-- Funil POR CAMPANHA (grão `campaign_name` consolidado).
-- =============================================================================
-- 1 linha por `campaign_name_norm` no período, com mídia + funil completo até
-- venda nova. Espelho de `mkt_criativo_funil.sql` — mesmas regras, só muda o
-- grão (campaign_name em vez de ad_name; utm_campaign em vez de utm_content).
-- Alimenta a seção "Funil da campanha selecionada" da página Campanhas.
--
-- Datas (regra oficial, igual Looker): leads `timestamp::date`; typeform
-- `created_at::date`; atividades `start_datetime::date`; vendas
-- `data_hora_compra::date`. Sem ajuste de -3 horas.
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
-- ────────────────────────────────────────────────────────────────────────────
-- Mai/2026 — REVISÃO da atribuição lead↔deal e vendas deal-centric
-- (espelha mkt_criativo_funil.sql; regra validada na operação 10–16/mai):
--   * Match deal→lead: `email > telefone(>=8 dígitos)`. zoho_id REMOVIDO.
--   * Atribuição CROSS-PERÍODO POR DEAL: para cada deal ganho,
--     `l.timestamp <= d.data_hora_compra` em `leads_atribuicao_vendas`
--     (sem corte inferior — venda pode atribuir a lead de qualquer tempo
--     anterior).
--   * Desempate quando múltiplos leads pareiam: prio_match → origem_util
--     DESC → lead_created_at DESC → lead_id.
--   * Vendas/montante/receita são DEAL-CENTRIC: 1-lead-por-deal via
--     DISTINCT ON.
--   * Bucket sintético `__sem_campanha_identificada__` agrega vendas
--     sem vínculo a lead com utm_campaign. UI exibe como "Sem campanha
--     identificada".
--   * Leads / +12-12-NA / agendamentos / comparecimentos continuam
--     LEAD-CENTRIC — universo do período via `leads_clean`.
--   * Dedup CRÍTICA: agregações de activities NÃO somam montante/receita
--     (essas vêm direto de deals_ganhos, evitando multiplicação por N
--     atividades do mesmo deal).
--
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
-- `leads_clean`: base do PERÍODO. Usada para contagens lead-centric
-- (leads/+12-12-NA/agendamentos/comparecimentos da campanha no período).
-- A partir de mai/2026 NÃO filtra `utm_campaign IS NOT NULL` — leads sem
-- utm_campaign viram o bucket sintético `__sem_campanha_identificada__`
-- via COALESCE em `distinct_email_campanha`. Antes esses leads sumiam do
-- somatório do funil; agora aparecem como cidadãos próprios.
leads_clean AS (
    SELECT
        l.id::text                                              AS lead_id,
        lower(btrim(l.email))                                   AS email_norm,
        NULLIF(btrim(l.zoho_id), '')                            AS lead_zoho_id,
        regexp_replace(COALESCE(l.phone_number, ''), '\D', '', 'g') AS phone_clean,
        l.classificado,
        l.timestamp,
        NULLIF(lower(btrim(l.utm_campaign)), '')                AS utm_campaign_norm
    FROM ext_reconecta.leads l
    WHERE l.timestamp::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
-- `leads_atribuicao_vendas`: base CROSS-PERÍODO (até :data_fim como
-- pré-filtro de performance; restrição precisa `l.timestamp <= d.data_hora_compra`
-- aplicada no JOIN de `deal_lead_matches`).
--
-- Diferença vs `leads_clean`:
--   * Sem corte inferior de período.
--   * SEM filtro `utm_campaign IS NOT NULL` — queremos TODOS os leads pra
--     atribuir vendas. Leads sem utm_campaign acabam no bucket sintético
--     '__sem_campanha_identificada__'; leads com utm_campaign preenchido
--     viram campanhas próprias.
--   * Carrega `origem_util` (regra validada com a operação) e
--     `utm_content_norm`/`utm_campaign_norm` pra desempate / auditoria.
leads_atribuicao_vendas AS (
    SELECT
        l.id::text                                                   AS lead_id,
        l.timestamp                                                AS lead_created_at,
        lower(btrim(l.email))                                        AS email_norm,
        regexp_replace(COALESCE(l.phone_number, ''), '\D', '', 'g')  AS phone_clean,
        lower(btrim(l.utm_campaign))                                 AS utm_campaign_norm,
        lower(btrim(l.utm_content))                                  AS utm_content_norm,
        CASE
            WHEN NULLIF(btrim(l.utm_campaign), '') IS NOT NULL THEN 1
            WHEN NULLIF(btrim(l.utm_content), '')  IS NOT NULL THEN 1
            WHEN lower(btrim(COALESCE(l.utm_content, ''))) = 'link_in_bio' THEN 1
            WHEN lower(COALESCE(l.utm_source, '')) IN ('linkbio','link_in_bio') THEN 1
            WHEN lower(COALESCE(l.utm_medium, '')) = 'social' THEN 1
            ELSE 0
        END                                                          AS origem_util
    FROM ext_reconecta.leads l
    WHERE l.timestamp::date <= :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
-- 1 linha por (utm_campaign_norm, e-mail) — period-distinct. Permite que o
-- mesmo e-mail conte 1× em CADA campanha onde apareceu. Leads sem
-- utm_campaign caem no bucket `__sem_campanha_identificada__` via COALESCE
-- (leads_clean já entrega utm_campaign_norm como NULL quando ausente).
distinct_email_campanha AS (
    SELECT DISTINCT
        COALESCE(utm_campaign_norm, '__sem_campanha_identificada__')
                                                            AS utm_campaign_norm,
        email_norm
    FROM leads_clean
),
-- 1 linha por (utm_campaign_norm, e-mail) — histórico até :data_fim (cross-período).
distinct_email_campanha_hist AS (
    SELECT DISTINCT
        COALESCE(utm_campaign_norm, '__sem_campanha_identificada__')
                                                            AS utm_campaign_norm,
        email_norm
    FROM leads_atribuicao_vendas
),
-- Última classificação POR E-MAIL no período (regra global, igual à
-- Visão Geral). Não depende da campanha — vale pra todas as rows do e-mail.
last_classif AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, timestamp DESC
),
-- Chaves do lead (zoho_id / phone_clean) pra alimentar o priority match.
-- Nota: `session_id` foi REMOVIDO; nova prioridade é `email > zoho_id > phone`.
email_lead_keys AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        lead_zoho_id,
        phone_clean
    FROM leads_clean
    ORDER BY email_norm, timestamp DESC
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
-- 2b) Aplicações (typeform) — dedupe e-mail/dia; totais globais = universo
--     Typeform no período (igual One Page). Por campanha = ∩ leads.
--     Typeform: `created_at::date` (sem −3h).
-- -----------------------------------------------------------------------------
aplicacoes_dedup AS (
    SELECT
        email_norm,
        classificado_norm
    FROM (
        SELECT
            lower(btrim(ta.email))              AS email_norm,
            lower(btrim(ta.classificado))       AS classificado_norm,
            ROW_NUMBER() OVER (
                PARTITION BY lower(btrim(ta.email)),
                             ta.created_at::date
                ORDER BY ta.created_at DESC
            ) AS rn
        FROM fdw_reconecta.typeform_aplicacoes ta
        WHERE ta.created_at::date BETWEEN :data_ini AND :data_fim
          AND ta.dados_completos IS TRUE
          AND ta.email IS NOT NULL
          AND btrim(ta.email) <> ''
          AND lower(btrim(ta.email)) NOT LIKE '%@teste%'
          AND lower(btrim(ta.email)) NOT LIKE '%teste@%'
          AND lower(btrim(ta.email)) NOT LIKE '%smarts%'
          AND lower(btrim(ta.email)) NOT LIKE '%reconecta%'
    ) sub
    WHERE rn = 1
),
-- Aplicações válidas históricas (até :data_fim) — dedupe e-mail/dia.
aplicacoes_dedup_hist AS (
    SELECT
        email_norm,
        classificado_norm
    FROM (
        SELECT
            lower(btrim(ta.email))              AS email_norm,
            lower(btrim(ta.classificado))       AS classificado_norm,
            ROW_NUMBER() OVER (
                PARTITION BY lower(btrim(ta.email)),
                             ta.created_at::date
                ORDER BY ta.created_at DESC
            ) AS rn
        FROM fdw_reconecta.typeform_aplicacoes ta
        WHERE ta.created_at::date <= :data_fim
          AND ta.dados_completos IS TRUE
          AND ta.email IS NOT NULL
          AND btrim(ta.email) <> ''
          AND lower(btrim(ta.email)) NOT LIKE '%@teste%'
          AND lower(btrim(ta.email)) NOT LIKE '%teste@%'
          AND lower(btrim(ta.email)) NOT LIKE '%smarts%'
          AND lower(btrim(ta.email)) NOT LIKE '%reconecta%'
    ) sub
    WHERE rn = 1
),
aplicacoes_email_campanha AS (
    SELECT DISTINCT
        dec.utm_campaign_norm                                   AS campaign_name_norm,
        ad.email_norm,
        ad.classificado_norm
    FROM distinct_email_campanha dec
    INNER JOIN aplicacoes_dedup ad USING (email_norm)
),
aplicacoes_por_campanha AS (
    SELECT
        campaign_name_norm,
        COUNT(DISTINCT email_norm)::bigint                      AS aplicacoes,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua +12', 'atua+12', '+12')
        )::bigint                                               AS aplicacoes_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua -12', 'atua-12', '-12')
        )::bigint                                               AS aplicacoes_menos_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('não atua', 'nao atua')
        )::bigint                                               AS aplicacoes_nao_atua
    FROM aplicacoes_email_campanha
    GROUP BY campaign_name_norm
),
aplicacoes_email_periodo AS (
    SELECT
        email_norm,
        BOOL_OR(classificado_norm IN ('atua +12', 'atua+12', '+12')) AS tem_mais_12,
        BOOL_OR(classificado_norm IN ('atua -12', 'atua-12', '-12')) AS tem_menos_12,
        BOOL_OR(classificado_norm IN ('não atua', 'nao atua'))        AS tem_nao_atua
    FROM aplicacoes_dedup
    GROUP BY email_norm
),
aplicacoes_globais AS (
    SELECT
        COUNT(*)::bigint                                        AS aplicacoes,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint             AS aplicacoes_mais_12,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint            AS aplicacoes_menos_12,
        COUNT(*) FILTER (WHERE tem_nao_atua)::bigint            AS aplicacoes_nao_atua
    FROM aplicacoes_email_periodo
),
aplicacoes_emails_vinculados AS (
    SELECT DISTINCT
        ad.email_norm,
        ad.classificado_norm
    FROM leads_clean lc
    INNER JOIN aplicacoes_dedup ad ON ad.email_norm = lc.email_norm
    WHERE lc.utm_campaign_norm IS NOT NULL
),
aplicacoes_vinculados AS (
    SELECT
        COUNT(DISTINCT email_norm)::bigint                      AS aplicacoes,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua +12', 'atua+12', '+12')
        )::bigint                                               AS aplicacoes_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua -12', 'atua-12', '-12')
        )::bigint                                               AS aplicacoes_menos_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('não atua', 'nao atua')
        )::bigint                                               AS aplicacoes_nao_atua
    FROM aplicacoes_emails_vinculados
),

-- -----------------------------------------------------------------------------
-- 3) Lead → Deal (lead-centric) — usado APENAS por agendamentos/comparecimentos.
--    Nova prioridade `email > zoho_id > phone_clean (>=8 dígitos)`.
-- -----------------------------------------------------------------------------
all_deal_matches AS (
    -- prio 1: email normalizado (chave principal segundo a operação)
    SELECT elk.email_norm, zd.id AS deal_id, zd.stage AS deal_stage,
           zd.tipo_venda AS deal_tipo_venda, zd.created_at AS deal_created_at,
           1 AS prio
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = elk.email_norm
    WHERE elk.email_norm IS NOT NULL AND elk.email_norm <> ''

    UNION ALL

    -- prio 2: zoho_id (fallback)
    SELECT elk.email_norm, zd.id, zd.stage, zd.tipo_venda, zd.created_at, 2
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON zd.id = elk.lead_zoho_id
    WHERE elk.lead_zoho_id IS NOT NULL

    UNION ALL

    -- prio 3: telefone limpo (fallback final; mínimo 8 dígitos)
    SELECT elk.email_norm, zd.id, zd.stage, zd.tipo_venda, zd.created_at, 3
    FROM email_lead_keys elk
    JOIN zoho_deals zd
      ON length(elk.phone_clean) >= 8
     AND regexp_replace(COALESCE(zd.telefone, ''), '\D', '', 'g') = elk.phone_clean
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
-- 4) Activities (agendamentos / comparecimentos) — lead-centric, igual antes.
--    NÃO soma montante/receita aqui — esses valores vêm direto de
--    `deals_ganhos` (deal-centric, sem inflar por múltiplas atividades).
-- -----------------------------------------------------------------------------
activities_in_window AS (
    -- Exclui atividades com `status_reuniao` vencido (qualquer variação
    -- de grafia). Alinha com a regra da view bi.vw_dashboard_comercial_
    -- executivas_rw pós-mai/2026: `agendamentos` é líquido de Vencida.
    -- `status_reuniao = NULL` passa (defensivo). Comparecimento exige
    -- 'Concluída', então vencidos já estariam fora do compar — o filtro
    -- pesa só em `agendamentos`.
    SELECT
        lwd.email_norm,
        za.id            AS activity_id,
        za.status_reuniao
    FROM leads_with_deal lwd
    JOIN zoho_activities za ON za.what_id = lwd.deal_id
    WHERE lwd.deal_id IS NOT NULL
      AND za.activity_type IN ('Consulta', 'Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
      AND COALESCE(za.status_reuniao, '') NOT ILIKE '%vencid%'
),
agend_compar_por_campanha AS (
    SELECT
        dec.utm_campaign_norm                                   AS campaign_name_norm,
        COUNT(DISTINCT a.email_norm)::bigint                    AS agendamentos,
        COUNT(DISTINCT a.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos
    FROM distinct_email_campanha dec
    LEFT JOIN activities_in_window a USING (email_norm)
    GROUP BY dec.utm_campaign_norm
),
agend_compar_aplicacoes AS (
    SELECT
        aec.campaign_name_norm,
        COUNT(DISTINCT aec.email_norm) FILTER (
            WHERE a.activity_id IS NOT NULL
        )::bigint                                               AS agendamentos_apl,
        COUNT(DISTINCT aec.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos_apl
    FROM aplicacoes_email_campanha aec
    LEFT JOIN activities_in_window a ON a.email_norm = aec.email_norm
    GROUP BY aec.campaign_name_norm
),
agend_compar_aplicacoes_globais AS (
    SELECT
        COUNT(DISTINCT ad.email_norm) FILTER (
            WHERE a.activity_id IS NOT NULL
        )::bigint                                               AS agendamentos_apl,
        COUNT(DISTINCT ad.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos_apl
    FROM aplicacoes_dedup ad
    LEFT JOIN activities_in_window a ON a.email_norm = ad.email_norm
),
agend_compar_aplicacoes_vinculados AS (
    SELECT
        COUNT(DISTINCT aev.email_norm) FILTER (
            WHERE a.activity_id IS NOT NULL
        )::bigint                                               AS agendamentos_apl,
        COUNT(DISTINCT aev.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos_apl
    FROM aplicacoes_emails_vinculados aev
    LEFT JOIN activities_in_window a ON a.email_norm = aev.email_norm
),
-- Decomposição Período / Histórico (agend., comp., vendas):
--   - período: e-mail com aplicação Typeform no período (`created_at::date`)
--   - histórico: demais do total (Python fecha histórico = total − período)
-- Decomposição agendamentos: período + histórico = total (cada % sobre o total).
leads_periodo_emails AS (
    SELECT DISTINCT email_norm
    FROM leads_clean
),
aplicacoes_periodo_emails AS (
    SELECT DISTINCT email_norm
    FROM aplicacoes_dedup
),
aplicacoes_email_campanha_hist AS (
    SELECT DISTINCT
        dech.utm_campaign_norm                                  AS campaign_name_norm,
        ad.email_norm
    FROM distinct_email_campanha_hist dech
    INNER JOIN aplicacoes_dedup_hist ad ON ad.email_norm = dech.email_norm
),
emails_agend_leads_campanha AS (
    SELECT dec.utm_campaign_norm                                 AS campaign_name_norm,
           a.email_norm
    FROM distinct_email_campanha dec
    INNER JOIN activities_in_window a ON a.email_norm = dec.email_norm
    UNION
    SELECT dech.utm_campaign_norm, a.email_norm
    FROM distinct_email_campanha_hist dech
    INNER JOIN activities_in_window a ON a.email_norm = dech.email_norm
    WHERE dech.email_norm NOT IN (SELECT email_norm FROM leads_periodo_emails)
),
agend_leads_decomp_por_campanha AS (
    SELECT
        campaign_name_norm,
        COUNT(DISTINCT email_norm)::bigint                      AS agendamentos,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_leads_periodo,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_leads_historico
    FROM emails_agend_leads_campanha
    GROUP BY campaign_name_norm
),
agend_leads_decomp_vinculados AS (
    SELECT
        COUNT(DISTINCT e.email_norm)::bigint                    AS agendamentos,
        COUNT(DISTINCT e.email_norm) FILTER (
            WHERE e.email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_leads_periodo,
        COUNT(DISTINCT e.email_norm) FILTER (
            WHERE e.email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_leads_historico
    FROM emails_agend_leads_campanha e
    WHERE e.campaign_name_norm <> '__sem_campanha_identificada__'
),
emails_comp_leads_campanha AS (
    SELECT dec.utm_campaign_norm AS campaign_name_norm, a.email_norm
    FROM distinct_email_campanha dec
    INNER JOIN activities_in_window a ON a.email_norm = dec.email_norm
    WHERE a.status_reuniao = 'Concluída'
    UNION
    SELECT dech.utm_campaign_norm AS campaign_name_norm, a.email_norm
    FROM distinct_email_campanha_hist dech
    INNER JOIN activities_in_window a ON a.email_norm = dech.email_norm
    WHERE a.status_reuniao = 'Concluída'
      AND dech.email_norm NOT IN (SELECT email_norm FROM leads_periodo_emails)
),
comp_leads_decomp_por_campanha AS (
    SELECT
        campaign_name_norm,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS comparecimentos_leads_periodo,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS comparecimentos_leads_historico
    FROM emails_comp_leads_campanha
    GROUP BY campaign_name_norm
),
comp_leads_decomp_vinculados AS (
    SELECT
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS comparecimentos_leads_periodo,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS comparecimentos_leads_historico
    FROM emails_comp_leads_campanha
    WHERE campaign_name_norm <> '__sem_campanha_identificada__'
),
emails_agend_apl_campanha AS (
    SELECT aec.campaign_name_norm, aec.email_norm
    FROM aplicacoes_email_campanha aec
    INNER JOIN activities_in_window a
        ON a.email_norm = aec.email_norm AND a.activity_id IS NOT NULL
    UNION
    SELECT aeh.campaign_name_norm, aeh.email_norm
    FROM aplicacoes_email_campanha_hist aeh
    INNER JOIN activities_in_window a
        ON a.email_norm = aeh.email_norm AND a.activity_id IS NOT NULL
    WHERE aeh.email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
),
agend_apl_decomp_por_campanha AS (
    SELECT
        campaign_name_norm,
        COUNT(DISTINCT email_norm)::bigint                      AS agendamentos_apl,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_apl_periodo,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_apl_historico
    FROM emails_agend_apl_campanha
    GROUP BY campaign_name_norm
),
emails_agend_apl_globais AS (
    SELECT ad.email_norm
    FROM aplicacoes_dedup ad
    INNER JOIN activities_in_window a
        ON a.email_norm = ad.email_norm AND a.activity_id IS NOT NULL
    UNION
    SELECT ad.email_norm
    FROM aplicacoes_dedup_hist ad
    INNER JOIN activities_in_window a
        ON a.email_norm = ad.email_norm AND a.activity_id IS NOT NULL
    WHERE ad.email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
),
agend_apl_decomp_globais AS (
    SELECT
        COUNT(DISTINCT email_norm)::bigint                      AS agendamentos_apl,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_apl_periodo,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_apl_historico
    FROM emails_agend_apl_globais
),
agend_apl_decomp_vinculados AS (
    SELECT
        COUNT(DISTINCT e.email_norm)::bigint                    AS agendamentos_apl,
        COUNT(DISTINCT e.email_norm) FILTER (
            WHERE e.email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_apl_periodo,
        COUNT(DISTINCT e.email_norm) FILTER (
            WHERE e.email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS agendamentos_apl_historico
    FROM emails_agend_apl_campanha e
    WHERE e.campaign_name_norm <> '__sem_campanha_identificada__'
),

-- -----------------------------------------------------------------------------
-- 5) ✨ VENDAS deal-centric — percorre os deals ganhos no período e atribui
--    cada um a UM lead (DISTINCT ON deal_id, prioridade email > zoho_id >
--    phone, tiebreaker `lead mais antigo`). Deals sem lead pareável → bucket
--    sintético `__sem_campanha_identificada__`.
-- -----------------------------------------------------------------------------
deals_ganhos AS (
    SELECT
        d.id::text                                              AS deal_id,
        d.data_hora_compra                                      AS data_venda_ts,
        d.data_hora_compra::date                                AS data_venda,
        lower(btrim(d.email))                                   AS deal_email_norm,
        regexp_replace(COALESCE(d.telefone, ''), '\D', '', 'g') AS deal_phone_clean
    FROM zoho_deals d
    WHERE d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
deal_lead_matches AS (
    -- Regra validada (mai/2026): email primário, telefone fallback,
    -- restrição cross-período per-deal `l.timestamp <= g.data_venda_ts`.
    -- zoho_id removido. Carrega `tipo_match` e `origem_util` pra desempate.
    --
    -- prio 1: email
    SELECT g.deal_id, l.lead_id, l.utm_campaign_norm,
           l.lead_created_at, l.origem_util,
           1 AS prio_match, 'email'::text AS tipo_match
    FROM deals_ganhos g
    JOIN leads_atribuicao_vendas l
      ON l.email_norm = g.deal_email_norm
     AND g.deal_email_norm <> ''
     AND l.lead_created_at <= g.data_venda_ts

    UNION ALL

    -- prio 2: telefone limpo (>=8 dígitos em ambos os lados)
    SELECT g.deal_id, l.lead_id, l.utm_campaign_norm,
           l.lead_created_at, l.origem_util,
           2 AS prio_match, 'telefone'::text AS tipo_match
    FROM deals_ganhos g
    JOIN leads_atribuicao_vendas l
      ON length(l.phone_clean) >= 8
     AND length(g.deal_phone_clean) >= 8
     AND l.phone_clean = g.deal_phone_clean
     AND l.lead_created_at <= g.data_venda_ts
),
deal_attributed_lead AS (
    -- 1 lead por deal. Ordem:
    --   1. prio_match (email=1 antes de telefone=2)
    --   2. origem_util DESC (leads com utm/link_in_bio/social vencem)
    --   3. lead_created_at DESC (lead MAIS RECENTE antes da venda)
    --   4. lead_id (desempate determinístico final)
    SELECT DISTINCT ON (deal_id)
        deal_id, lead_id, utm_campaign_norm, prio_match, tipo_match,
        origem_util, lead_created_at
    FROM deal_lead_matches
    ORDER BY deal_id, prio_match,
             origem_util DESC,
             lead_created_at DESC,
             lead_id
),
vendas_leads_decomp_por_campanha AS (
    SELECT
        COALESCE(dal.utm_campaign_norm, '__sem_campanha_identificada__')
                                                                AS campaign_name_norm,
        COUNT(DISTINCT g.deal_id) FILTER (
            WHERE lav.email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS vendas_leads_periodo,
        COUNT(DISTINCT g.deal_id) FILTER (
            WHERE lav.email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
             OR lav.email_norm IS NULL OR lav.email_norm = ''
        )::bigint                                               AS vendas_leads_historico
    FROM deals_ganhos g
    LEFT JOIN deal_attributed_lead dal ON dal.deal_id = g.deal_id
    LEFT JOIN leads_atribuicao_vendas lav ON lav.lead_id = dal.lead_id
    GROUP BY 1
),
vendas_leads_decomp_vinculados AS (
    SELECT
        COUNT(DISTINCT g.deal_id) FILTER (
            WHERE lav.email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                               AS vendas_leads_periodo,
        COUNT(DISTINCT g.deal_id) FILTER (
            WHERE lav.email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
             OR lav.email_norm IS NULL OR lav.email_norm = ''
        )::bigint                                               AS vendas_leads_historico
    FROM deals_ganhos g
    LEFT JOIN deal_attributed_lead dal ON dal.deal_id = g.deal_id
    LEFT JOIN leads_atribuicao_vendas lav ON lav.lead_id = dal.lead_id
    WHERE COALESCE(dal.utm_campaign_norm, '__sem_campanha_identificada__')
          <> '__sem_campanha_identificada__'
),
vendas_por_campanha AS (
    SELECT
        COALESCE(dal.utm_campaign_norm, '__sem_campanha_identificada__')
                                                                AS campaign_name_norm,
        COUNT(DISTINCT g.deal_id)::bigint                       AS vendas_novas
    FROM deals_ganhos g
    LEFT JOIN deal_attributed_lead dal USING (deal_id)
    GROUP BY 1
),

vendas_aplicacoes_por_campanha AS (
    SELECT
        aec.campaign_name_norm,
        COUNT(DISTINCT g.deal_id)::bigint                       AS vendas_aplicacoes
    FROM deals_ganhos g
    INNER JOIN deal_attributed_lead dal USING (deal_id)
    INNER JOIN leads_atribuicao_vendas l ON l.lead_id = dal.lead_id
    INNER JOIN aplicacoes_email_campanha aec
        ON aec.email_norm = l.email_norm
       AND aec.campaign_name_norm = COALESCE(
               dal.utm_campaign_norm, '__sem_campanha_identificada__'
           )
    GROUP BY aec.campaign_name_norm
),
vendas_aplicacoes_globais AS (
    SELECT COUNT(DISTINCT g.deal_id)::bigint                    AS vendas_aplicacoes
    FROM deals_ganhos g
    INNER JOIN deal_attributed_lead dal USING (deal_id)
    INNER JOIN leads_atribuicao_vendas l ON l.lead_id = dal.lead_id
    WHERE l.email_norm IN (SELECT email_norm FROM aplicacoes_dedup)
),
vendas_aplicacoes_vinculados AS (
    SELECT COUNT(DISTINCT g.deal_id)::bigint                    AS vendas_aplicacoes
    FROM deals_ganhos g
    INNER JOIN deal_attributed_lead dal USING (deal_id)
    INNER JOIN leads_atribuicao_vendas l ON l.lead_id = dal.lead_id
    WHERE l.email_norm IN (SELECT email_norm FROM aplicacoes_emails_vinculados)
),

-- -----------------------------------------------------------------------------
-- 6) Universo: união dos campaign_names — preserva campanhas com invest mas
--    sem leads e o bucket sintético de vendas sem campanha identificada.
-- -----------------------------------------------------------------------------
universo AS (
    SELECT campaign_name_norm FROM midia_agg
    UNION
    SELECT campaign_name_norm FROM leads_por_campanha
    UNION
    SELECT campaign_name_norm FROM vendas_por_campanha
)

SELECT
    u.campaign_name_norm,
    -- Identificação
    COALESCE(
        ma.campaign_name,
        CASE WHEN u.campaign_name_norm = '__sem_campanha_identificada__'
             THEN 'Sem campanha identificada'
             ELSE u.campaign_name_norm
        END
    )                                                           AS campaign_name,
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
    -- Leads (lead-centric)
    COALESCE(lpc.leads_totais, 0)::bigint                       AS leads_totais,
    COALESCE(lpc.leads_qualificados, 0)::bigint                 AS leads_qualificados,
    COALESCE(lpc.leads_mais_12, 0)::bigint                      AS leads_mais_12,
    COALESCE(lpc.leads_menos_12, 0)::bigint                     AS leads_menos_12,
    COALESCE(lpc.leads_nao_atua, 0)::bigint                     AS leads_nao_atua,
    -- Funil — agend/compar (lead-centric) + vendas (deal-centric)
    COALESCE(ald.agendamentos, acpc.agendamentos, 0)::bigint    AS agendamentos,
    COALESCE(ald.agendamentos_leads_periodo, 0)::bigint           AS agendamentos_leads_periodo,
    COALESCE(ald.agendamentos_leads_historico, 0)::bigint         AS agendamentos_leads_historico,
    COALESCE(acpc.comparecimentos, 0)::bigint                   AS comparecimentos,
    COALESCE(cld.comparecimentos_leads_periodo, 0)::bigint      AS comparecimentos_leads_periodo,
    COALESCE(cld.comparecimentos_leads_historico, 0)::bigint    AS comparecimentos_leads_historico,
    COALESCE(vpc.vendas_novas, 0)::bigint                       AS vendas_novas,
    COALESCE(vld.vendas_leads_periodo, 0)::bigint                 AS vendas_leads_periodo,
    COALESCE(vld.vendas_leads_historico, 0)::bigint               AS vendas_leads_historico,
    -- Funil de aplicações (typeform → subset com agend/compar/venda)
    COALESCE(apc.aplicacoes, 0)::bigint                         AS aplicacoes,
    COALESCE(apc.aplicacoes_mais_12, 0)::bigint                  AS aplicacoes_mais_12,
    COALESCE(apc.aplicacoes_menos_12, 0)::bigint                 AS aplicacoes_menos_12,
    COALESCE(apc.aplicacoes_nao_atua, 0)::bigint                 AS aplicacoes_nao_atua,
    COALESCE(aad.agendamentos_apl, aapl.agendamentos_apl, 0)::bigint
                                                                AS agendamentos_apl,
    COALESCE(aad.agendamentos_apl_periodo, 0)::bigint           AS agendamentos_apl_periodo,
    COALESCE(aad.agendamentos_apl_historico, 0)::bigint         AS agendamentos_apl_historico,
    COALESCE(aapl.comparecimentos_apl, 0)::bigint               AS comparecimentos_apl,
    COALESCE(vapl.vendas_aplicacoes, 0)::bigint                 AS vendas_aplicacoes,
    -- Totais globais de aplicações (repetidos em cada row — UI usa em opções sintéticas)
    ag.aplicacoes::bigint                                       AS aplicacoes_globais,
    ag.aplicacoes_mais_12::bigint                               AS aplicacoes_mais_12_globais,
    ag.aplicacoes_menos_12::bigint                              AS aplicacoes_menos_12_globais,
    ag.aplicacoes_nao_atua::bigint                              AS aplicacoes_nao_atua_globais,
    acag.comparecimentos_apl::bigint                            AS comparecimentos_apl_globais,
    vag.vendas_aplicacoes::bigint                               AS vendas_aplicacoes_globais,
    av.aplicacoes::bigint                                       AS aplicacoes_vinculados,
    av.aplicacoes_mais_12::bigint                               AS aplicacoes_mais_12_vinculados,
    av.aplicacoes_menos_12::bigint                              AS aplicacoes_menos_12_vinculados,
    av.aplicacoes_nao_atua::bigint                              AS aplicacoes_nao_atua_vinculados,
    acav.comparecimentos_apl::bigint                            AS comparecimentos_apl_vinculados,
    vav.vendas_aplicacoes::bigint                               AS vendas_aplicacoes_vinculados,
    alvin.agendamentos::bigint                                  AS agendamentos_vinculados,
    alvin.agendamentos_leads_periodo::bigint                    AS agendamentos_leads_periodo_vinculados,
    alvin.agendamentos_leads_historico::bigint                  AS agendamentos_leads_historico_vinculados,
    clvin.comparecimentos_leads_periodo::bigint                 AS comparecimentos_leads_periodo_vinculados,
    clvin.comparecimentos_leads_historico::bigint               AS comparecimentos_leads_historico_vinculados,
    vldvin.vendas_leads_periodo::bigint                         AS vendas_leads_periodo_vinculados,
    vldvin.vendas_leads_historico::bigint                       AS vendas_leads_historico_vinculados,
    aadg.agendamentos_apl::bigint                               AS agendamentos_apl_globais,
    aadg.agendamentos_apl_periodo::bigint                       AS agendamentos_apl_periodo_globais,
    aadg.agendamentos_apl_historico::bigint                     AS agendamentos_apl_historico_globais,
    aadvin.agendamentos_apl::bigint                             AS agendamentos_apl_vinculados,
    aadvin.agendamentos_apl_periodo::bigint                      AS agendamentos_apl_periodo_vinculados,
    aadvin.agendamentos_apl_historico::bigint                    AS agendamentos_apl_historico_vinculados,
    -- Derivadas
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(lpc.leads_qualificados, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_qualificacao,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(lpc.leads_mais_12, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_mais_12,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(acpc.agendamentos, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_agendamento,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(acpc.comparecimentos, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_comparecimento,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(vpc.vendas_novas, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_venda_nova,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / lpc.leads_totais
    END                                                         AS cpl,
    CASE WHEN COALESCE(lpc.leads_mais_12, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / lpc.leads_mais_12
    END                                                         AS cpl_mais_12,
    CASE WHEN COALESCE(vpc.vendas_novas, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / vpc.vendas_novas
    END                                                         AS cac,
    -- Derivadas — funil de aplicações (denominador = aplicacoes)
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(apc.aplicacoes_mais_12, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_aplicacao_mais_12,
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(aapl.agendamentos_apl, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_apl_agendamento,
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(aapl.comparecimentos_apl, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_apl_comparecimento,
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(vapl.vendas_aplicacoes, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_apl_venda_nova
FROM universo u
CROSS JOIN aplicacoes_globais ag
CROSS JOIN aplicacoes_vinculados av
CROSS JOIN agend_compar_aplicacoes_globais acag
CROSS JOIN agend_compar_aplicacoes_vinculados acav
CROSS JOIN vendas_aplicacoes_globais vag
CROSS JOIN vendas_aplicacoes_vinculados vav
CROSS JOIN agend_leads_decomp_vinculados alvin
CROSS JOIN comp_leads_decomp_vinculados clvin
CROSS JOIN vendas_leads_decomp_vinculados vldvin
CROSS JOIN agend_apl_decomp_globais aadg
CROSS JOIN agend_apl_decomp_vinculados aadvin
LEFT JOIN midia_agg                  ma   USING (campaign_name_norm)
LEFT JOIN midia_principal            mp   USING (campaign_name_norm)
LEFT JOIN leads_por_campanha         lpc  USING (campaign_name_norm)
LEFT JOIN agend_compar_por_campanha  acpc USING (campaign_name_norm)
LEFT JOIN agend_leads_decomp_por_campanha ald USING (campaign_name_norm)
LEFT JOIN comp_leads_decomp_por_campanha cld USING (campaign_name_norm)
LEFT JOIN vendas_por_campanha        vpc  USING (campaign_name_norm)
LEFT JOIN vendas_leads_decomp_por_campanha vld USING (campaign_name_norm)
LEFT JOIN aplicacoes_por_campanha    apc  USING (campaign_name_norm)
LEFT JOIN agend_compar_aplicacoes    aapl USING (campaign_name_norm)
LEFT JOIN agend_apl_decomp_por_campanha aad USING (campaign_name_norm)
LEFT JOIN vendas_aplicacoes_por_campanha vapl USING (campaign_name_norm)
ORDER BY investimento DESC NULLS LAST, vendas_novas DESC NULLS LAST,
         leads_totais DESC NULLS LAST;
