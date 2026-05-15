-- =============================================================================
-- Cohort de agendamentos por dia de geração — base do bloco "Cohort de
-- agendamentos por dia de geração" na Visão Geral Pré-vendas.
-- =============================================================================
-- Grão devolvido: 1 row por oportunidade (deal criado no período).
-- O Python pivota por (data_geracao, lag_dias_bucket) e acumula D0..D7.
--
-- Universo: deals criados no período (zoho_deals.created_at::date BETWEEN
-- :data_ini AND :data_fim) — alinhado com "Indicadores por Pré-vendas".
--
-- Atribuição de SDR — cascata canônica do projeto:
--   1) activity.prevendas mais recente do deal (Consulta/Indicação)
--   2) deal.sdr_ss → zoho_users
--   3) 'Sem SDR'
--
-- Primeiro agendamento por deal:
--   - activity_type IN ('Consulta','Indicação')
--   - status_reuniao IS NOT NULL
--   - start_datetime IS NOT NULL
--   - dedup por DISTINCT ON (deal_id) ORDER BY start_datetime ASC, id ASC
-- lag_dias = (data_agend - data_geracao). Pode ser NEGATIVO quando a
-- activity foi criada antes do deal (caso real — Zoho às vezes ordena
-- diferente entre activity vs deal); o Python clipa em 0 para o cohort.
--
-- Filtro de e-mails internos no JOIN com ext.leads não se aplica aqui:
-- esta query NÃO toca ext_reconecta.leads. Universo é só zoho_deals +
-- zoho_activities + zoho_users.
-- =============================================================================
WITH deals_periodo AS (
    SELECT
        d.id::text             AS deal_id,
        d.created_at::date     AS data_geracao,
        d.sdr_ss::text         AS sdr_ss_id
    FROM zoho_deals d
    WHERE d.created_at::date BETWEEN :data_ini AND :data_fim
),
sdr_via_activity AS (
    -- SDR primário = activity.prevendas mais recente do deal (com ou sem
    -- status_reuniao — queremos captar SDR mesmo de activity pendente).
    SELECT DISTINCT ON (a.what_id)
        a.what_id::text                  AS deal_id,
        NULLIF(btrim(a.prevendas), '')   AS prevendas
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND NULLIF(btrim(a.prevendas), '') IS NOT NULL
      AND a.what_id IS NOT NULL
    ORDER BY a.what_id, a.created_time DESC NULLS LAST, a.id DESC
),
acts_validas AS (
    -- Universo de agendamentos válidos. Normaliza what_id (json|texto)
    -- igual prevendas_leads_detalhe_diario.sql.
    SELECT
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END                              AS deal_id,
        a.start_datetime::date           AS data_agend,
        a.start_datetime                 AS start_datetime,
        a.id                             AS activity_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND a.start_datetime IS NOT NULL
),
primeiro_agend AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        data_agend
    FROM acts_validas
    WHERE deal_id IS NOT NULL AND deal_id <> ''
    ORDER BY deal_id, start_datetime ASC, activity_id ASC
)
SELECT
    dp.deal_id,
    dp.data_geracao,
    COALESCE(
        sva.prevendas,
        NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
        'Sem SDR'
    )                                    AS sdr,
    pa.data_agend                        AS data_agend,
    CASE
        WHEN pa.data_agend IS NULL THEN NULL
        ELSE (pa.data_agend - dp.data_geracao)::int
    END                                  AS lag_dias
FROM deals_periodo dp
LEFT JOIN sdr_via_activity sva ON sva.deal_id = dp.deal_id
LEFT JOIN zoho_users        u  ON u.id::text  = dp.sdr_ss_id
LEFT JOIN primeiro_agend    pa ON pa.deal_id  = dp.deal_id
ORDER BY dp.data_geracao DESC, dp.deal_id;
