-- =============================================================================
-- Campanhas — leads + CRM/Zoho por campanha (match campaign_name = utm_campaign).
-- =============================================================================
-- Enriquece a tabela "Campanhas ativas" e o bloco "Comparar campanhas" com:
--   * leads / qualificados / +12 / -12 — regra Visão Geral
--   * leads_no_crm / leads_ganhos / vendas_novas — match Zoho
--     (priority zoho_id > session_id > email; mesma regra do funil Growth)
--
-- Match no app:
--   bi.vw_mkt_campanhas.campaign_name = ext_reconecta.leads.utm_campaign
--   (ambos normalizados via LOWER(BTRIM(...)). Sem UTM no lead ⇒ fora.
--
-- Regras de leads (período-distinct, mesma Visão Geral):
--   - Janela: l.created_at::date BETWEEN :data_ini AND :data_fim
--   - Filtros de e-mail: NOT LIKE @teste / teste@ / smarts / reconecta
--   - leads_totais = COUNT(DISTINCT email) por utm_campaign
--   - classificação = última (created_at DESC) por e-mail no período
--
-- Regras de CRM/Zoho (mesma regra do funil Growth):
--   - lead → deal: prioridade zoho_id > session_id > email; tiebreaker
--                  zoho_deals.created_at DESC
--   - leads_no_crm   = COUNT(DISTINCT email) com qualquer deal pareado
--   - leads_ganhos   = COUNT(DISTINCT email) com deal stage IN
--                      ('Ganho','Fechado Ganho')
--   - vendas_novas   = COUNT(DISTINCT email) com deal Ganho/Fechado Ganho
--                      AND tipo_venda = 'Novo cliente' (regra Growth: caminho
--                      de aquisição não conta ascensão/renovação/indicação)
--
-- Validação abril/2026 (period-distinct):
--   leads - aquisição pixel 01  →  84 leads / 67 qualif / +12 4  / -12 63
--   teste sem13_2026_3          →  64 leads / 57 qualif / +12 23 / -12 34
--   teste a/b cbo               →  58 leads / 50 qualif / +12 23 / -12 27
-- =============================================================================
WITH leads_clean AS (
    SELECT
        lower(btrim(l.email))                 AS email_norm,
        l.created_at,
        l.classificado,
        lower(btrim(l.utm_campaign))          AS utm_norm,
        NULLIF(btrim(l.zoho_id), '')          AS lead_zoho_id,
        l.session_id                          AS lead_session_id
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
last_classif AS (
    -- Última classificação POR E-MAIL no período (mesma regra Visão Geral).
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- 1 row por e-mail no período pra alimentar o priority match com zoho_deals.
-- Pega chaves (zoho_id / session_id) do lead row mais recente.
email_lead_keys AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        lead_zoho_id,
        lead_session_id
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
all_deal_matches AS (
    -- UNION ALL de 3 JOINs index-friendly (em vez de OR-predicate, que
    -- explode em Cartesian product — zoho_deals tem >20k rows). Cada
    -- branch usa equality em coluna indexada; depois DISTINCT ON pelo
    -- priority `prio` resolve a hierarquia zoho_id > session_id > email.
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
    -- 1 deal por e-mail via priority match (mesma regra do funil Growth).
    SELECT DISTINCT ON (email_norm)
        email_norm,
        deal_id,
        deal_stage,
        deal_tipo_venda
    FROM all_deal_matches
    ORDER BY email_norm, prio, deal_created_at DESC NULLS LAST
),
distinct_email_utm AS (
    -- 1 linha por (utm_norm, e-mail) — period-distinct.
    -- Um e-mail que aparece em duas campanhas conta 1× em CADA campanha.
    SELECT DISTINCT utm_norm, email_norm
    FROM leads_clean
)
SELECT
    deu.utm_norm                                                    AS campaign_norm,
    COUNT(*)::bigint                                                AS leads_totais,
    COUNT(*) FILTER (
        WHERE c.classif_final ILIKE '%+12%' OR c.classif_final ILIKE '%-12%'
    )::bigint                                                       AS leads_qualificados,
    COUNT(*) FILTER (WHERE c.classif_final ILIKE '%+12%')::bigint   AS leads_mais_12,
    COUNT(*) FILTER (WHERE c.classif_final ILIKE '%-12%')::bigint   AS leads_menos_12,
    COUNT(*) FILTER (
        WHERE c.classif_final ILIKE '%não atua%'
    )::bigint                                                       AS leads_nao_atua,
    -- CRM/Zoho — mesma regra do funil Growth
    COUNT(*) FILTER (WHERE lwd.deal_id IS NOT NULL)::bigint         AS leads_no_crm,
    COUNT(*) FILTER (
        WHERE lwd.deal_stage IN ('Ganho', 'Fechado Ganho')
    )::bigint                                                       AS leads_ganhos,
    COUNT(*) FILTER (
        WHERE lwd.deal_stage IN ('Ganho', 'Fechado Ganho')
          AND lwd.deal_tipo_venda = 'Novo cliente'
    )::bigint                                                       AS vendas_novas
FROM distinct_email_utm deu
LEFT JOIN last_classif c USING (email_norm)
LEFT JOIN leads_with_deal lwd USING (email_norm)
GROUP BY deu.utm_norm
ORDER BY leads_totais DESC;
