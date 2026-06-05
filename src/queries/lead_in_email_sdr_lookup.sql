-- =============================================================================
-- Lead In & Reuniões — lookup email → SDR/pré-venda.
-- =============================================================================
-- Replica a cascata de `notificacoes_leads_sdr.sql` (base ext_reconecta.leads
-- + match deal zoho_id > session_id > email + SDR via activity.prevendas >
-- deal.sdr_ss). Devolve candidatos (email_norm, ts_vinculo, sdr, fonte) para
-- o Python escolher o vínculo mais recente até a data da reunião.
-- =============================================================================
WITH leads_valid AS (
    SELECT
        lower(btrim(l.email))                 AS email_norm,
        l.created_at                          AS ts_vinculo,
        NULLIF(btrim(l.zoho_id::text), '')   AS lead_zoho_id,
        l.session_id                          AS lead_session_id
    FROM ext_reconecta.leads l
    WHERE l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
      AND l.created_at::date <= :data_fim
      AND l.created_at::date >= (:data_ini - INTERVAL '24 months')::date
),
all_deal_matches AS (
    SELECT
        lv.email_norm,
        lv.ts_vinculo,
        zd.id::text AS deal_id,
        zd.created_at AS deal_created_at,
        1 AS prio
    FROM leads_valid lv
    JOIN zoho_deals zd ON lv.lead_zoho_id = zd.id::text
    WHERE lv.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT
        lv.email_norm,
        lv.ts_vinculo,
        zd.id::text,
        zd.created_at,
        2
    FROM leads_valid lv
    JOIN zoho_deals zd ON lv.lead_session_id::text = zd.session_id
    WHERE lv.lead_session_id IS NOT NULL
    UNION ALL
    SELECT
        lv.email_norm,
        lv.ts_vinculo,
        zd.id::text,
        zd.created_at,
        3
    FROM leads_valid lv
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = lv.email_norm
),
lead_deal AS (
    SELECT DISTINCT ON (email_norm, ts_vinculo)
        email_norm,
        ts_vinculo,
        deal_id
    FROM all_deal_matches
    ORDER BY email_norm, ts_vinculo, prio, deal_created_at DESC NULLS LAST
),
activities_sdr_norm AS (
    SELECT
        CASE
            WHEN a.what_id::text ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id::text, ''), '\D', '', 'g')
        END                                   AS deal_id,
        NULLIF(btrim(a.prevendas), '')        AS prevendas,
        a.start_datetime                      AS act_ts,
        a.id                                  AS activity_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.what_id IS NOT NULL
      AND btrim(a.what_id::text) <> ''
),
deal_sdr_pick AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        prevendas,
        act_ts
    FROM activities_sdr_norm
    WHERE deal_id IS NOT NULL
      AND deal_id <> ''
    ORDER BY
        deal_id,
        act_ts DESC NULLS LAST,
        activity_id DESC
)
SELECT
    ld.email_norm,
    ld.ts_vinculo,
    ld.deal_id,
    COALESCE(
        dsp.prevendas,
        NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
    )                                         AS sdr_nome,
    CASE
        WHEN dsp.prevendas IS NOT NULL
            THEN 'lead_sla_email'
        WHEN NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
            IS NOT NULL
            THEN 'deal.sdr_ss'
        ELSE NULL
    END                                       AS fonte_pre_venda
FROM lead_deal ld
LEFT JOIN deal_sdr_pick dsp ON dsp.deal_id = ld.deal_id
LEFT JOIN zoho_deals zd ON zd.id::text = ld.deal_id
LEFT JOIN zoho_users u_sdr ON u_sdr.id::text = zd.sdr_ss::text
WHERE COALESCE(
    dsp.prevendas,
    NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
) IS NOT NULL
ORDER BY ld.email_norm, ld.ts_vinculo DESC;
