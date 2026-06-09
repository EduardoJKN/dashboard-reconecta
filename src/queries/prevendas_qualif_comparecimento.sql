-- =============================================================================
-- Pré-vendas — Qualificação × Comparecimento (1 linha por activity).
-- =============================================================================
-- Universo de agendamentos:
--   - zoho_activities.activity_type IN ('Consulta', 'Indicação')
--   - start_datetime::date no período
--   - status_reuniao IS NOT NULL e <> 'Vencida' (case-insensitive)
--   - ligação deal: what_id normalizado → zoho_deals.id
--
-- Dimensões (NÃO excludentes — podem se cruzar):
--   1) Com Pré — SDR híbrida identificada (≠ 'Sem SDR')
--   2) Não Qualificados — stage ATUAL = 'Recepção'
--   3) Interseção — tem_pre AND eh_nao_qualificados
--
-- Comparecimento:
--   status_reuniao IN ('Concluída', 'Concluído')
-- =============================================================================
WITH acts AS (
    SELECT
        a.id::text                                          AS activity_id,
        a.start_datetime,
        a.start_datetime::date                              AS data_reuniao,
        a.created_time                                      AS activity_created_time,
        a.status_reuniao,
        a.activity_type,
        a.owner::text                                       AS activity_owner_id,
        a.what_id::text                                     AS what_id_raw,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id::text, ''), '\D', '', 'g')
        END                                                 AS deal_id,
        NULLIF(btrim(a.prevendas), '')                      AS prevendas_raw
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND lower(btrim(a.status_reuniao)) <> 'vencida'
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
)
SELECT
    ac.activity_id,
    ac.start_datetime,
    ac.data_reuniao,
    ac.activity_created_time,
    ac.status_reuniao,
    ac.activity_type,
    ac.activity_owner_id,
    ac.what_id_raw,
    ac.deal_id,
    (ac.activity_id IS NOT NULL)                            AS existe_em_activities,
    (d.id IS NOT NULL)                                      AS existe_em_deals,
    CASE
        WHEN ac.what_id_raw IS NULL OR btrim(ac.what_id_raw) = ''
            THEN 'what_id vazio'
        WHEN d.id IS NOT NULL
            AND regexp_replace(ac.what_id_raw, '\D', '', 'g') = d.id::text
            THEN 'OK'
        ELSE 'Sem deal ligado'
    END                                                     AS vinculo_activity_deal,
    NULLIF(btrim(d.deal_name), '')                          AS deal_name,
    NULLIF(lower(btrim(d.email)), '')                       AS deal_email,
    NULLIF(lower(btrim(d.email_secundario)), '')            AS deal_email_secundario,
    COALESCE(
        NULLIF(lower(btrim(d.email)), ''),
        NULLIF(lower(btrim(d.email_secundario)), '')
    )                                                       AS email_deal,
    d.created_at                                            AS deal_created_at,
    d.sdr_ss::text                                          AS deal_sdr_ss_id,
    COALESCE(NULLIF(btrim(d.stage), ''), 'Sem etapa')       AS stage,
    CASE
        WHEN btrim(d.stage) = 'Recepção'         THEN 'Não Qualificados'
        WHEN btrim(d.stage) = 'Reunião Agendada' THEN 'Qualificados'
        ELSE NULL
    END                                                     AS classificacao,
    (btrim(d.stage) = 'Recepção')                           AS eh_nao_qualificados,
    ac.prevendas_raw,
    NULLIF(TRIM(u.first_name || ' ' || u.last_name), '')    AS deal_sdr_ss_nome,
    COALESCE(
        ac.prevendas_raw,
        NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
        'Sem SDR'
    )                                                       AS sdr,
    CASE
        WHEN ac.prevendas_raw IS NOT NULL
            THEN 'activity.prevendas'
        WHEN NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') IS NOT NULL
            THEN 'deal.sdr_ss'
        ELSE 'Sem SDR'
    END                                                     AS fonte_sdr,
    (
        COALESCE(
            ac.prevendas_raw,
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) <> 'Sem SDR'
    )                                                       AS tem_pre,
    (
        COALESCE(
            ac.prevendas_raw,
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) <> 'Sem SDR'
        AND btrim(d.stage) = 'Recepção'
    )                                                       AS pre_mais_nao_qualificados,
    NULLIF(TRIM(uo.first_name || ' ' || uo.last_name), '')  AS activity_owner_nome,
    (ac.status_reuniao IN ('Concluída', 'Concluído'))       AS comparecimento
FROM acts ac
LEFT JOIN zoho_deals d ON d.id::text = NULLIF(ac.deal_id, '')
LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
LEFT JOIN zoho_users uo ON uo.id::text = ac.activity_owner_id
ORDER BY ac.data_reuniao DESC, ac.start_datetime DESC, ac.activity_id;
