-- =============================================================================
-- Lead In & Reuniões — consultas (activities Consulta) no período — v2.
-- =============================================================================
-- Mesma semântica de `lead_in_reunioes_consultas.sql` (v1), com:
--   • filtro de data equivalente a COALESCE(start_datetime, created_time)
--     reescrito para permitir uso de índice em start_datetime quando preenchido;
--   • lookup de ext_reconecta.leads em batch (DISTINCT ON) em vez de JOIN LATERAL
--     por linha (gargalo confirmado no EXPLAIN ANALYZE da v1);
--   • joins diretos em zoho_users (closer / SDR / owner) em vez de CTEs com
--     scan completo da tabela repetido por linha.
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
        a.owner::text                                           AS activity_owner_id
    FROM zoho_activities a
    WHERE a.activity_type = 'Consulta'
      AND (
          (a.start_datetime IS NOT NULL
           AND a.start_datetime::date BETWEEN :data_ini AND :data_fim)
          OR (a.start_datetime IS NULL
              AND a.created_time::date BETWEEN :data_ini AND :data_fim)
      )
),
consulta_deal_ids AS (
    SELECT DISTINCT c.deal_id
    FROM consultas c
    WHERE c.deal_id IS NOT NULL
      AND btrim(c.deal_id) <> ''
),
lead_pick AS (
    SELECT DISTINCT ON (l2.zoho_id::text)
        l2.zoho_id::text                                      AS deal_id,
        l2.utm_source,
        l2.email
    FROM ext_reconecta.leads l2
    INNER JOIN consulta_deal_ids cd ON l2.zoho_id::text = cd.deal_id
    ORDER BY l2.zoho_id::text, l2.timestamp DESC NULLS LAST, l2.id DESC
),
deals_info AS (
    SELECT
        c.activity_id,
        c.deal_id,
        c.data_reuniao,
        c.ts_reuniao,
        c.data_criacao_agendamento,
        c.start_datetime,
        c.end_datetime,
        c.status_reuniao,
        c.prevendas_raw,
        c.motivo_cancelamento,
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
        )                                                       AS origem,
        NULLIF(TRIM(uo.first_name || ' ' || uo.last_name), '') AS activity_owner_nome
    FROM consultas c
    LEFT JOIN zoho_deals d ON d.id::text = c.deal_id
    LEFT JOIN lead_pick lk ON lk.deal_id = c.deal_id
    LEFT JOIN zoho_users uo ON uo.id::text = c.activity_owner_id
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
    COALESCE(
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), ''),
        d.activity_owner_nome,
        'Sem Closer'
    )                                                           AS closer,
    d.deal_sdr_ss_id,
    NULLIF(TRIM(ds.first_name || ' ' || ds.last_name), '')     AS deal_sdr_nome,
    d.origem,
    CASE
        WHEN d.prevendas_raw IS NOT NULL THEN 'activity.prevendas'
        WHEN NULLIF(TRIM(ds.first_name || ' ' || ds.last_name), '') IS NOT NULL
            THEN 'deal.sdr_ss (sem activity.prevendas)'
        ELSE 'sem vínculo pré'
    END                                                         AS fonte_pre_bruta
FROM deals_info d
LEFT JOIN zoho_users uc ON uc.id::text = d.closer_id
LEFT JOIN zoho_users ds ON ds.id::text = d.deal_sdr_ss_id
ORDER BY d.data_reuniao DESC, d.ts_reuniao DESC NULLS LAST, d.activity_id;
