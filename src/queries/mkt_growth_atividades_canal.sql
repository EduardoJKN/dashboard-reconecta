-- =============================================================================
-- Funil Growth — Agendamentos / Comparecimentos como LEADS ÚNICOS por canal.
-- =============================================================================
-- Substitui as etapas 5 e 6 do funil principal da Growth (que vinham de
-- odam.mart_ad_funnel_daily, Meta-only ~30% de cobertura) pela contagem de
-- leads únicos com pelo menos uma activity Zoho no período.
--
-- Por que leads únicos (não COUNT activities):
--   Um mesmo lead pode ter mais de uma reunião (reagendamento, várias
--   sessões). Se contássemos `COUNT(DISTINCT activity_id)`, Agendamentos
--   poderia ficar maior que Leads +12, quebrando a interpretação de funil.
--   Aqui contamos `COUNT(DISTINCT email)` — quantos leads avançaram.
--
-- Caminho:
--   lead → deal → activity
--   - lead: ext_reconecta.leads (período + cleanup de email padrão)
--   - lead → deal: priority match zoho_id > session_id > email (mesma regra
--                  da Visão Geral / Campanhas / paginas_variantes)
--   - deal → activity: zoho_activities.what_id = zoho_deals.id
--   - filtros activity: activity_type IN ('Consulta','Indicação')
--                       AND start_datetime::date dentro do período
--
-- Canal por lead: canal_final via bi_mkt.vw_visao_geral_canal_base
-- (last_row do e-mail no período, mesma regra Visão Geral). Leads sem
-- canal_final caem em 'Sem canal'.
--
-- Performance: o priority match foi reescrito de
-- `LEFT JOIN ... ON (cond1 OR cond2 OR cond3)` para `UNION ALL` de 3
-- INNER JOINs index-friendly, com DISTINCT ON resolvendo a prioridade
-- depois. Mesmo padrão usado em mkt_paginas_variantes / mkt_visao_geral_*
-- / mkt_campanhas_leads_por_utm. Em abr/2026 caiu de ~46s para ~3-4s
-- (≈12× mais rápido) sem mudança no resultado — OR-predicate não usa
-- índice em zoho_deals (>20k rows) e vira nested-loop com `lower(btrim())`
-- por linha.
--
-- Validação abril/2026 (cross-canais):
--   leads_com_agendamento     = 279  (Meta 206 / Organico 65 / Outros 8)
--   leads_com_comparecimento  = 199  (Meta 143 / Organico 49 / Outros 7)
-- =============================================================================
WITH leads_clean AS (
    SELECT
        lower(btrim(l.email))           AS email_norm,
        l.created_at,
        NULLIF(btrim(l.zoho_id), '')    AS lead_zoho_id,
        l.session_id                    AS lead_session_id
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
canal_email AS (
    -- Canal_final canônico (last row do e-mail no período).
    SELECT DISTINCT ON (email_normalizado)
        email_normalizado,
        CASE WHEN canal = 'Orgânico' THEN 'Organico' ELSE canal END AS canal_final
    FROM bi_mkt.vw_visao_geral_canal_base
    WHERE data_ref BETWEEN :data_ini AND :data_fim
    ORDER BY email_normalizado, created_at DESC
),
all_deal_matches AS (
    -- UNION ALL de 3 INNER JOINs index-friendly (em vez de OR-predicate,
    -- que vira nested-loop cartesiano). Cada branch usa equality em coluna
    -- indexada; DISTINCT ON pelo `prio` em leads_with_deal resolve a
    -- prioridade zoho_id > session_id > email.
    SELECT lc.email_norm, zd.id AS deal_id, zd.created_at AS deal_created_at,
           1 AS prio
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_zoho_id = zd.id
    WHERE lc.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT lc.email_norm, zd.id, zd.created_at, 2
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_session_id::text = zd.session_id
    WHERE lc.lead_session_id IS NOT NULL
    UNION ALL
    SELECT lc.email_norm, zd.id, zd.created_at, 3
    FROM leads_clean lc
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = lc.email_norm
),
leads_with_deal AS (
    -- 1 deal por e-mail via priority match. Empate dentro da mesma
    -- prioridade → deal mais recente por created_at.
    SELECT DISTINCT ON (email_norm)
        email_norm,
        deal_id
    FROM all_deal_matches
    ORDER BY email_norm, prio, deal_created_at DESC NULLS LAST
),
activities_in_window AS (
    -- Activities da janela ligadas via deal. Conserva uma row por (e-mail,
    -- activity) — o COUNT DISTINCT abaixo dedupe por e-mail.
    SELECT
        lwd.email_norm,
        za.id            AS activity_id,
        za.status_reuniao
    FROM leads_with_deal lwd
    JOIN zoho_activities za ON za.what_id = lwd.deal_id
    WHERE lwd.deal_id IS NOT NULL
      AND za.activity_type IN ('Consulta', 'Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
)
SELECT
    COALESCE(ce.canal_final, 'Sem canal') AS canal,
    COUNT(DISTINCT a.email_norm)::bigint  AS leads_com_agendamento,
    COUNT(DISTINCT a.email_norm) FILTER (
        WHERE a.status_reuniao = 'Concluída'
    )::bigint                             AS leads_com_comparecimento
FROM activities_in_window a
LEFT JOIN canal_email ce ON ce.email_normalizado = a.email_norm
GROUP BY 1
ORDER BY leads_com_agendamento DESC NULLS LAST;
