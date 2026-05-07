-- =============================================================================
-- Comparar páginas / variantes — leads + match com Zoho deals.
-- =============================================================================
-- Retorna 1 row POR LEAD SUBMISSION no período (email-level, NÃO agregado).
-- O Python aplica filtros (campanha/origem/mídia/fuso/dispositivo) e agrega
-- por (page_pathname, lp_variante) na seção "Comparar páginas / variantes"
-- da Growth.
--
-- Fontes:
--   ext_reconecta.leads — base de leads.
--   zoho_deals          — match opcional via prioridade lead.zoho_id >
--                         lead.session_id > lower(email). Usa LEFT JOIN com
--                         OR-predicate + DISTINCT ON (lead_id) pra escolher
--                         exatamente 1 deal por submission, com a regra
--                         oficial de match (mesma adotada na Visão Geral).
--                         Sem filtro de data no deal — um lead "está no CRM"
--                         se há QUALQUER deal pareado, independente de
--                         quando o deal foi criado/fechado.
--
-- Regras (alinhadas com Visão Geral / Campanhas):
--   - Janela do lead: l.created_at::date BETWEEN :data_ini AND :data_fim
--   - Filtros de e-mail: NOT LIKE @teste / teste@ / smarts / reconecta
--   - Classificação canônica: ÚLTIMA row do e-mail no período
--                             (DISTINCT ON (email_norm) ORDER BY created_at DESC)
--   - Normalização: NULL/'' → token explícito ('(sem path)' / '(sem variante)')
--                   só quando isso vira grão de agregação; UTM/IDs ficam NULL
--                   quando vazio pra serem excluídos de COUNT DISTINCT.
--   - flag_tem_deal = (deal_id IS NOT NULL)
--   - flag_ganho    = deal_stage IN ('Ganho', 'Fechado Ganho')
--
-- NÃO é conversão real de página por visitas/sessões — Lead → CRM/Ganho é
-- conversão de lead dentro do funil comercial, não da landing page.
-- =============================================================================
WITH leads_clean AS (
    SELECT
        l.id::text                                                  AS lead_id,
        lower(btrim(l.email))                                       AS email_norm,
        NULLIF(btrim(l.zoho_id), '')                                AS lead_zoho_id,
        l.session_id                                                AS lead_session_id,
        l.created_at,
        l.classificado,
        l.page_url,
        COALESCE(NULLIF(btrim(l.page_pathname), ''), '(sem path)')  AS page_pathname,
        COALESCE(NULLIF(btrim(l.lp_variante), ''),
                 '(sem variante)')                                  AS lp_variante,
        NULLIF(btrim(l.utm_source), '')                             AS utm_source,
        NULLIF(btrim(l.utm_medium), '')                             AS utm_medium,
        NULLIF(btrim(l.utm_campaign), '')                           AS utm_campaign,
        NULLIF(btrim(l.utm_content), '')                            AS utm_content,
        NULLIF(btrim(l.utm_term), '')                               AS utm_term,
        NULLIF(btrim(l.campaign_id::text), '')                      AS campaign_id,
        NULLIF(btrim(l.ad_id::text), '')                            AS ad_id,
        NULLIF(btrim(l.adset_id::text), '')                         AS adset_id,
        NULLIF(btrim(l.timezone), '')                               AS timezone,
        NULLIF(btrim(l.device_type), '')                            AS device_type
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
last_classif AS (
    -- Última classificação POR E-MAIL no período (regra global, independente
    -- dos filtros aplicados depois no Python).
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
all_deal_matches AS (
    -- UNION ALL de 3 JOINs index-friendly (em vez de OR-predicate, que
    -- explode em Cartesian product — zoho_deals tem >20k rows).
    SELECT lc.lead_id, lc.email_norm, zd.id AS deal_id, zd.stage AS deal_stage,
           zd.tipo_venda AS deal_tipo_venda,
           zd.data_hora_compra AS deal_data_hora_compra,
           zd.created_at AS deal_created_at,
           'zoho_id' AS match_tipo, 1 AS prio
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_zoho_id = zd.id
    WHERE lc.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT lc.lead_id, lc.email_norm, zd.id, zd.stage, zd.tipo_venda,
           zd.data_hora_compra, zd.created_at, 'session_id', 2
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_session_id::text = zd.session_id
    WHERE lc.lead_session_id IS NOT NULL
    UNION ALL
    SELECT lc.lead_id, lc.email_norm, zd.id, zd.stage, zd.tipo_venda,
           zd.data_hora_compra, zd.created_at, 'email', 3
    FROM leads_clean lc
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = lc.email_norm
),
leads_with_deal AS (
    -- Match prioritário lead → 1 deal: zoho_id > session_id > email.
    -- Empate dentro da mesma prioridade → deal mais recente por created_at.
    SELECT DISTINCT ON (lead_id)
        lead_id,
        deal_id,
        deal_stage,
        deal_tipo_venda,
        deal_data_hora_compra,
        match_tipo
    FROM all_deal_matches
    ORDER BY lead_id, prio, deal_created_at DESC NULLS LAST
)
SELECT
    lc.email_norm,
    lc.created_at,
    c.classif_final,
    lc.page_url,
    lc.page_pathname,
    lc.lp_variante,
    lc.utm_source,
    lc.utm_medium,
    lc.utm_campaign,
    lc.utm_content,
    lc.utm_term,
    lc.campaign_id,
    lc.ad_id,
    lc.adset_id,
    lc.timezone,
    lc.device_type,
    lc.lead_session_id                              AS session_id,
    -- CRM / Zoho match (opcional — NULL quando lead sem deal pareado)
    lwd.deal_id,
    lwd.deal_stage,
    lwd.deal_tipo_venda,
    lwd.deal_data_hora_compra,
    lwd.match_tipo,
    (lwd.deal_id IS NOT NULL)                       AS flag_tem_deal,
    (lwd.deal_stage IN ('Ganho', 'Fechado Ganho')
     AND lwd.deal_id IS NOT NULL)                   AS flag_ganho
FROM leads_clean lc
LEFT JOIN last_classif c USING (email_norm)
LEFT JOIN leads_with_deal lwd USING (lead_id)
ORDER BY lc.created_at DESC;
