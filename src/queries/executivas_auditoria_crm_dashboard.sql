-- =============================================================================
-- Executivas & Times — auditoria CRM × dashboard (1 linha por activity).
-- =============================================================================
-- Espelha as regras atuais de bi.vw_dashboard_comercial_executivas_rw:
--   agendamentos     : status_reuniao IS NOT NULL AND lower(trim) <> 'vencida'
--                      data_ref = start_datetime::date
--                      atribuição no ranking = za.owner (host da activity)
--   comparecimentos  : status_reuniao IN ('Concluída', 'Concluído')
--   vendas           : deal stage Ganho + tipo_venda Novo cliente +
--                      COALESCE(data_hora_compra, created_at) no período
--                      atribuição = executiva_vendas do deal
--
-- Inclui TODAS as activities Consulta/Indicação com reunião no período,
-- mesmo as excluídas do funil (Vencida, NULL), para expor divergências.
--
-- Parâmetros: :data_ini, :data_fim (date, inclusive).
-- =============================================================================
WITH acts AS (
    SELECT
        za.id::text                                                   AS activity_id,
        za.owner::text                                                AS activity_owner_id,
        za.start_datetime                                             AS start_datetime,
        za.start_datetime::date                                       AS data_reuniao,
        za.created_time::date                                         AS activity_created_at,
        za.status_reuniao,
        za.activity_type,
        CASE
            WHEN za.what_id ~ '^\{.*\}$'
                THEN (za.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(za.what_id, ''), '\D', '', 'g')
        END                                                           AS deal_id
    FROM zoho_activities za
    WHERE za.activity_type IN ('Consulta', 'Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
),
deals AS (
    SELECT
        d.id::text                                                    AS deal_id,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), '')
        )                                                             AS nome_lead,
        NULLIF(btrim(d.email), '')                                    AS email,
        d.executiva_vendas::text                                      AS deal_closer_id,
        d.stage,
        NULLIF(btrim(d.triagem), '')                                  AS triagem,
        d.tipo_venda,
        d.created_at::date                                            AS deal_created_at,
        d.data_hora_compra::date                                      AS data_hora_compra,
        d.ultima_reuniao_agendada::date                               AS ultima_reuniao_agendada,
        d.compromisso_concluido::date                                 AS compromisso_concluido
    FROM zoho_deals d
),
base AS (
    SELECT
        a.*,
        d.nome_lead,
        d.email,
        d.deal_closer_id,
        d.stage,
        d.triagem,
        d.tipo_venda,
        d.deal_created_at,
        d.data_hora_compra,
        d.ultima_reuniao_agendada,
        d.compromisso_concluido,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '')        AS closer_deal,
        NULLIF(TRIM(uo.first_name || ' ' || uo.last_name), '')        AS owner_activity,
        -- Flags canônicas do dashboard (view BI)
        (
            a.status_reuniao IS NOT NULL
            AND lower(btrim(a.status_reuniao)) <> 'vencida'
        )                                                             AS flag_agendamento_dashboard,
        (
            a.status_reuniao IN ('Concluída', 'Concluído')
        )                                                             AS flag_comparecimento_dashboard,
        (
            d.stage = 'Ganho'
            AND d.tipo_venda = 'Novo cliente'
            AND COALESCE(d.data_hora_compra, d.deal_created_at)
                BETWEEN :data_ini AND :data_fim
        )                                                             AS flag_venda_dashboard,
        -- Fallback hipotético (NÃO usado no dashboard hoje — só auditoria)
        (
            NOT (a.status_reuniao IN ('Concluída', 'Concluído'))
            AND d.stage ILIKE '%reuni%conclu%'
        )                                                             AS flag_comparecimento_fallback_stage,
        (
            NOT (a.status_reuniao IN ('Concluída', 'Concluído'))
            AND lower(btrim(COALESCE(d.triagem, ''))) IN (
                'concluída', 'concluida', 'lead qualificado'
            )
        )                                                             AS flag_comparecimento_fallback_triagem,
        (
            a.status_reuniao IN ('Concluída', 'Concluído')
            AND d.deal_closer_id IS NOT NULL
            AND a.activity_owner_id IS NOT NULL
            AND d.deal_closer_id <> a.activity_owner_id
        )                                                             AS flag_closer_owner_divergente,
        (
            NOT (a.status_reuniao IN ('Concluída', 'Concluído'))
            AND d.stage ILIKE '%reuni%conclu%'
        )                                                             AS flag_deal_reuniao_concluida_activity_nao
    FROM acts a
    LEFT JOIN deals d ON d.deal_id = NULLIF(a.deal_id, '')
    LEFT JOIN zoho_users uo ON uo.id::text = a.activity_owner_id
    LEFT JOIN zoho_users uc ON uc.id::text = d.deal_closer_id
),
motivos AS (
    SELECT
        b.*,
        NULLIF(
            array_to_string(
                ARRAY_REMOVE(ARRAY[
                    CASE WHEN NOT b.flag_comparecimento_dashboard
                              AND b.status_reuniao IS NULL
                         THEN 'status_reuniao NULL' END,
                    CASE WHEN NOT b.flag_comparecimento_dashboard
                              AND lower(btrim(COALESCE(b.status_reuniao, ''))) IN ('agendada', 'agendado')
                         THEN 'activity ainda Agendada' END,
                    CASE WHEN NOT b.flag_comparecimento_dashboard
                              AND lower(btrim(COALESCE(b.status_reuniao, ''))) = 'vencida'
                         THEN 'activity Vencida' END,
                    CASE WHEN NOT b.flag_comparecimento_dashboard
                              AND lower(btrim(COALESCE(b.status_reuniao, ''))) IN ('cancelada', 'cancelado')
                         THEN 'activity Cancelada' END,
                    CASE WHEN b.flag_deal_reuniao_concluida_activity_nao
                         THEN 'deal indica Reunião Concluída, mas activity não está Concluída' END,
                    CASE WHEN b.flag_closer_owner_divergente
                         THEN 'activity concluída mas closer do deal diferente do owner da activity' END,
                    CASE WHEN b.deal_id IS NULL
                         THEN 'activity sem deal ligado (what_id)' END
                ], NULL),
                '; '
            ),
            ''
        )                                                             AS motivos_divergencia
    FROM base b
)
SELECT
    activity_id,
    data_reuniao,
    start_datetime,
    activity_type,
    COALESCE(closer_deal, 'Sem closer no deal')                     AS closer_deal,
    deal_closer_id,
    COALESCE(owner_activity, 'Sem owner na activity')               AS owner_activity,
    activity_owner_id,
    COALESCE(nome_lead, deal_id, activity_id)                       AS nome_lead,
    email,
    stage                                                           AS deal_stage,
    triagem,
    status_reuniao,
    ultima_reuniao_agendada,
    compromisso_concluido,
    deal_id,
    deal_created_at,
    data_hora_compra,
    flag_agendamento_dashboard,
    flag_comparecimento_dashboard,
    flag_venda_dashboard,
    flag_comparecimento_fallback_stage,
    flag_comparecimento_fallback_triagem,
    flag_closer_owner_divergente,
    motivos_divergencia,
    -- Atribuição usada pelo ranking da view (owner da activity)
    COALESCE(owner_activity, activity_owner_id, 'SEM_ATRIBUICAO')     AS executiva_ranking_dashboard,
    -- Atribuição pelo closer do deal (visão CRM comum)
    COALESCE(closer_deal, deal_closer_id, 'SEM_CLOSER_DEAL')        AS executiva_deal_crm
FROM motivos
ORDER BY data_reuniao DESC, closer_deal NULLS LAST, nome_lead;
