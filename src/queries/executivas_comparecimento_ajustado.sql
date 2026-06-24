-- =============================================================================
-- Executivas — comparecimento ajustado (teste operacional, 1 linha/activity).
-- =============================================================================
-- Atribuição alinhada ao ranking da view: owner da activity (host).
-- Período: start_datetime::date BETWEEN :data_ini AND :data_fim.
--
-- Flags e KPIs são calculados em Python (`comparecimento_ajustado_aplicar_flags`)
-- para garantir comparação de horário em America/Sao_Paulo.
-- Coluna start_datetime / end_datetime: timestamp WITHOUT time zone (horário de parede BRT).
-- created_time = campo original Zoho; created_at espelha o mesmo instante no DW.
-- fim_reuniao_ref (flags em Python): COALESCE(end_datetime, start_datetime + 1h).
-- =============================================================================
WITH acts AS (
    SELECT
        za.id::text                                                   AS activity_id,
        za.owner::text                                                AS activity_owner_id,
        za.start_datetime                                             AS start_datetime,
        za.end_datetime                                               AS end_datetime,
        COALESCE(za.created_time, za.created_at)                      AS created_time,
        za.start_datetime::date                                       AS data_reuniao,
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
        d.stage                                                       AS deal_stage,
        NULLIF(btrim(d.triagem), '')                                  AS triagem
    FROM zoho_deals d
),
base AS (
    SELECT
        a.activity_id,
        a.start_datetime,
        a.end_datetime,
        a.created_time,
        a.data_reuniao,
        a.status_reuniao,
        a.activity_type,
        a.deal_id,
        d.nome_lead,
        d.email,
        d.deal_stage,
        d.triagem,
        NULLIF(TRIM(uo.first_name || ' ' || uo.last_name), '')        AS owner_activity,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '')        AS closer_deal,
        CASE
            WHEN TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Andrezza Ayuso Serpa%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Hawinne Cristina%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Nathally Pereira dos Santos%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Thaís Cadó%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Thais Cado%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Stefany Campinas%'
                THEN 'Time da Leidianne'
            WHEN TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Leandro Alves%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Leonardo Melo Patriota%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Leonardo Patriota%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Nathan Carloto%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Camile Silveira%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Henrique Gonçalves%'
              OR TRIM(uo.first_name || ' ' || uo.last_name) ILIKE 'Henrique Goncalves%'
                THEN 'Time do Marcelo'
            ELSE 'Sem time definido'
        END                                                           AS time_vendas
    FROM acts a
    LEFT JOIN deals d ON d.deal_id = NULLIF(a.deal_id, '')
    LEFT JOIN zoho_users uo ON uo.id::text = a.activity_owner_id
    LEFT JOIN zoho_users uc ON uc.id::text = d.deal_closer_id
)
SELECT
    activity_id,
    data_reuniao,
    start_datetime,
    end_datetime,
    created_time,
    activity_type,
    COALESCE(owner_activity, 'Sem owner')                             AS executiva,
    COALESCE(closer_deal, 'Sem closer')                               AS closer_deal,
    COALESCE(nome_lead, deal_id, activity_id)                         AS nome_lead,
    email,
    deal_stage,
    triagem,
    status_reuniao,
    time_vendas,
    deal_id
FROM base
ORDER BY start_datetime DESC, executiva;
