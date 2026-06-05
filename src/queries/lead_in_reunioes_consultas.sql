-- =============================================================================
-- Lead In & Reuniões — consultas (activities Consulta) no período.
-- =============================================================================
-- Data de referência: COALESCE(start_datetime, created_time)
-- Fonte: zoho_activities · activity_type = 'Consulta'
-- Não usa stage = Churn nem mistura com pós-venda.
-- =============================================================================
WITH consultas AS (
    SELECT
        a.id::text                                              AS activity_id,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END                                                     AS deal_id,
        COALESCE(a.start_datetime, a.created_time)              AS ts_reuniao,
        COALESCE(a.start_datetime, a.created_time)::date        AS data_reuniao,
        a.created_time                                          AS data_criacao_agendamento,
        a.start_datetime                                        AS start_datetime,
        a.end_datetime                                          AS end_datetime,
        a.status_reuniao,
        NULLIF(btrim(a.prevendas), '')                          AS prevendas_raw,
        NULLIF(btrim(a.motivo_cancelamento_e_nao_comparecimento), '') AS motivo_cancelamento,
        a.owner::text                                           AS activity_owner_id,
        NULLIF(TRIM(uo.first_name || ' ' || uo.last_name), '') AS activity_owner_nome
    FROM zoho_activities a
    LEFT JOIN zoho_users uo ON uo.id::text = a.owner::text
    WHERE a.activity_type = 'Consulta'
      AND COALESCE(a.start_datetime, a.created_time)::date BETWEEN :data_ini AND :data_fim
),
deals_info AS (
    SELECT
        c.*,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), '')
        )                                                       AS nome_cliente,
        COALESCE(
            NULLIF(btrim(d.email), ''),
            NULLIF(btrim(lk.email), '')
        )                                                       AS email,
        NULLIF(btrim(d.telefone), '')                           AS telefone,
        d.executiva_vendas::text                                AS closer_id,
        d.sdr_ss::text                                          AS deal_sdr_ss_id,
        COALESCE(
            NULLIF(btrim(d.origem), ''),
            NULLIF(btrim(d.fonte_de_lead), ''),
            NULLIF(btrim(lk.utm_source), '')
        )                                                       AS origem
    FROM consultas c
    LEFT JOIN zoho_deals d ON d.id::text = c.deal_id
    LEFT JOIN LATERAL (
        SELECT l2.utm_source, l2.email
        FROM ext_reconecta.leads l2
        WHERE l2.zoho_id::text = c.deal_id
        ORDER BY l2.timestamp DESC NULLS LAST, l2.id DESC
        LIMIT 1
    ) lk ON TRUE
),
closer_resolved AS (
    SELECT
        uc.id::text                                             AS closer_id,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS closer_nome
    FROM zoho_users uc
),
deal_sdr AS (
    SELECT
        us.id::text                                             AS sdr_ss_id,
        NULLIF(TRIM(us.first_name || ' ' || us.last_name), '') AS deal_sdr_nome
    FROM zoho_users us
)
SELECT
    d.activity_id,
    d.deal_id,
    d.data_reuniao,
    d.ts_reuniao,
    d.data_criacao_agendamento,
    d.start_datetime,
    d.end_datetime,
    d.status_reuniao,
    d.prevendas_raw,
    d.motivo_cancelamento,
    d.nome_cliente,
    d.email,
    lower(btrim(d.email))                                       AS email_norm,
    d.telefone,
    COALESCE(cr.closer_nome, d.activity_owner_nome, 'Sem Closer') AS closer,
    d.deal_sdr_ss_id,
    ds.deal_sdr_nome,
    d.origem,
    CASE
        WHEN d.prevendas_raw IS NOT NULL THEN 'activity.prevendas'
        WHEN ds.deal_sdr_nome IS NOT NULL THEN 'deal.sdr_ss (sem activity.prevendas)'
        ELSE 'sem vínculo pré'
    END                                                         AS fonte_pre_bruta
FROM deals_info d
LEFT JOIN closer_resolved cr ON cr.closer_id = d.closer_id
LEFT JOIN deal_sdr ds ON ds.sdr_ss_id = d.deal_sdr_ss_id
ORDER BY d.data_reuniao DESC, d.ts_reuniao DESC NULLS LAST, d.activity_id;
