-- =============================================================================
-- Pre-vendas - serie diaria por SDR (para filtros da Visao Geral).
-- =============================================================================
-- Grao final: 1 linha por (data_ref, sdr)
--
-- Regras:
--   - leads: lead unico por (data_ref, email), atribuido a 1 SDR
--   - agendamentos/comparecimentos: activities do dia
--   - vendas/montante/receita: deals ganhos do dia
--   - resolucao de SDR:
--       1) activity.prevendas
--       2) fallback deal.sdr_ss -> zoho_users
--       3) 'Sem SDR'
--
-- Observacao importante:
--   Esta query existe para o caminho FILTRADO da pagina.
--   Sem filtro ativo, a pagina continua usando `prevendas_overview_diario.sql`
--   para preservar exatamente os totais oficiais atuais.
-- =============================================================================
WITH leads_clean AS (
    SELECT
        l.created_at::date AS data_ref,
        l.created_at,
        lower(btrim(l.email)) AS email_norm,
        NULLIF(btrim(l.zoho_id), '') AS lead_zoho_id,
        l.session_id AS lead_session_id
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
lead_rows AS (
    SELECT DISTINCT ON (data_ref, email_norm)
        data_ref,
        email_norm,
        lead_zoho_id,
        lead_session_id,
        created_at
    FROM leads_clean
    ORDER BY data_ref, email_norm, created_at DESC
),
all_deal_matches AS (
    SELECT
        lr.data_ref,
        lr.email_norm,
        zd.id AS deal_id,
        zd.created_at AS deal_ca,
        1 AS prio
    FROM lead_rows lr
    JOIN zoho_deals zd ON lr.lead_zoho_id = zd.id
    WHERE lr.lead_zoho_id IS NOT NULL

    UNION ALL

    SELECT
        lr.data_ref,
        lr.email_norm,
        zd.id AS deal_id,
        zd.created_at AS deal_ca,
        2 AS prio
    FROM lead_rows lr
    JOIN zoho_deals zd ON lr.lead_session_id::text = zd.session_id
    WHERE lr.lead_session_id IS NOT NULL

    UNION ALL

    SELECT
        lr.data_ref,
        lr.email_norm,
        zd.id AS deal_id,
        zd.created_at AS deal_ca,
        3 AS prio
    FROM lead_rows lr
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = lr.email_norm
),
lead_with_deal AS (
    SELECT DISTINCT ON (data_ref, email_norm)
        data_ref,
        email_norm,
        deal_id
    FROM all_deal_matches
    ORDER BY data_ref, email_norm, prio, deal_ca DESC NULLS LAST
),
acts_periodo AS (
    SELECT
        a.id AS activity_id,
        a.what_id AS deal_id,
        a.start_datetime::date AS data_ref,
        a.start_datetime,
        a.status_reuniao,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) AS sdr
    FROM zoho_activities a
    LEFT JOIN zoho_deals d ON d.id = a.what_id
    LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
deal_sdr_pick AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        sdr
    FROM acts_periodo
    WHERE deal_id IS NOT NULL
    ORDER BY deal_id, start_datetime DESC, activity_id DESC
),
deal_sdr_fallback AS (
    SELECT
        d.id AS deal_id,
        COALESCE(
            dsp.sdr,
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) AS sdr
    FROM zoho_deals d
    LEFT JOIN deal_sdr_pick dsp ON dsp.deal_id = d.id
    LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
),
leads_agg AS (
    SELECT
        lr.data_ref,
        COALESCE(dsf.sdr, 'Sem SDR') AS sdr,
        COUNT(*)::bigint AS leads
    FROM lead_rows lr
    LEFT JOIN lead_with_deal lwd
        ON lwd.data_ref = lr.data_ref
       AND lwd.email_norm = lr.email_norm
    LEFT JOIN deal_sdr_fallback dsf ON dsf.deal_id = lwd.deal_id
    GROUP BY 1, 2
),
acts_agg AS (
    SELECT
        data_ref,
        sdr,
        COUNT(*)::bigint AS agendamentos,
        COUNT(*) FILTER (WHERE status_reuniao = 'Concluída')::bigint AS comparecimentos
    FROM acts_periodo
    GROUP BY 1, 2
),
deals_periodo AS (
    SELECT
        zd.id AS deal_id,
        zd.data_hora_compra::date AS data_ref,
        zd.tipo_venda,
        CASE
            WHEN NULLIF(btrim(zd.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(zd.amount), '[^0-9,.-]', '', 'g'),
                         '.',
                         ''
                     ),
                     ',',
                     '.'
                 )::numeric
        END AS montante,
        CASE
            WHEN NULLIF(btrim(zd.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(zd.receita), '[^0-9,.-]', '', 'g'),
                         '.',
                         ''
                     ),
                     ',',
                     '.'
                 )::numeric
        END AS receita
    FROM zoho_deals zd
    WHERE zd.stage IN ('Ganho', 'Fechado Ganho')
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
vendas_agg AS (
    SELECT
        dp.data_ref,
        COALESCE(dsf.sdr, 'Sem SDR') AS sdr,
        COUNT(DISTINCT dp.deal_id)::bigint AS vendas,
        COUNT(DISTINCT dp.deal_id) FILTER (
            WHERE dp.tipo_venda = 'Novo cliente'
        )::bigint AS vendas_novas,
        SUM(dp.montante)::numeric AS montante,
        SUM(dp.receita)::numeric AS receita
    FROM deals_periodo dp
    LEFT JOIN deal_sdr_fallback dsf ON dsf.deal_id = dp.deal_id
    GROUP BY 1, 2
),
keys AS (
    SELECT data_ref, sdr FROM leads_agg
    UNION
    SELECT data_ref, sdr FROM acts_agg
    UNION
    SELECT data_ref, sdr FROM vendas_agg
)
SELECT
    k.data_ref,
    k.sdr,
    COALESCE(l.leads, 0)::bigint AS leads,
    COALESCE(a.agendamentos, 0)::bigint AS agendamentos,
    COALESCE(a.comparecimentos, 0)::bigint AS comparecimentos,
    COALESCE(v.vendas, 0)::bigint AS vendas,
    COALESCE(v.vendas_novas, 0)::bigint AS vendas_novas,
    COALESCE(v.montante, 0)::numeric AS montante,
    COALESCE(v.receita, 0)::numeric AS receita
FROM keys k
LEFT JOIN leads_agg l USING (data_ref, sdr)
LEFT JOIN acts_agg a USING (data_ref, sdr)
LEFT JOIN vendas_agg v USING (data_ref, sdr)
ORDER BY k.data_ref, k.sdr;
