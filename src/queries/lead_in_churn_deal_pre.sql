-- =============================================================================
-- Lead In — campos de pré por deal Churn (cascata activity → deal.sdr_ss).
-- =============================================================================
-- Usado para associar clientes cancelados (stage = 'Churn') à pré-venda/SDR
-- com a mesma cascata da página Lead In & Reuniões.
-- =============================================================================
WITH churn_deals AS (
    SELECT d.id::text AS deal_id
    FROM zoho_deals d
    WHERE d.stage = 'Churn'
),
consulta_prevendas AS (
    SELECT DISTINCT ON (deal_id)
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END AS deal_id,
        NULLIF(btrim(a.prevendas), '') AS prevendas_raw
    FROM zoho_activities a
    WHERE a.activity_type = 'Consulta'
      AND a.what_id IS NOT NULL
      AND btrim(a.what_id::text) <> ''
    ORDER BY
        deal_id,
        COALESCE(a.start_datetime, a.created_time) DESC NULLS LAST,
        a.id DESC
),
deal_sdr AS (
    SELECT
        us.id::text AS sdr_ss_id,
        NULLIF(TRIM(us.first_name || ' ' || us.last_name), '') AS deal_sdr_nome
    FROM zoho_users us
)
SELECT
    cd.deal_id,
    cp.prevendas_raw,
    ds.deal_sdr_nome
FROM churn_deals cd
LEFT JOIN consulta_prevendas cp ON cp.deal_id = cd.deal_id
LEFT JOIN zoho_deals d ON d.id::text = cd.deal_id
LEFT JOIN deal_sdr ds ON ds.sdr_ss_id = d.sdr_ss::text
ORDER BY cd.deal_id;
