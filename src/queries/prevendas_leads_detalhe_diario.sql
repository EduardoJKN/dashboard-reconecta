-- =============================================================================
-- Pré-vendas — detalhe linha a linha da regra legada usada na Visão Geral.
-- =============================================================================
-- Objetivo: auditoria detalhada do mesmo universo que alimenta os contadores
-- agregados de agendamentos / comparecimentos da regra legada.
--
-- Regra:
--   - base principal em zoho_deals
--   - LEFT JOIN ext_reconecta.leads l ON d.id::text = l.zoho_id::text
--   - activities ligadas ao deal por what_id normalizado
--   - activity_type IN ('Consulta', 'Indicação')
--   - status_reuniao IS NOT NULL
-- =============================================================================
WITH base_dados AS (
    SELECT
        d.id::text AS deal_id,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), '')
        ) AS nome_cliente,
        COALESCE(NULLIF(btrim(d.deal_name), ''), NULLIF(btrim(d.email), ''), d.id::text) AS deal_ref,
        d.sdr_ss::text AS sdr_ss_id,
        d.executiva_vendas::text AS closer_id,
        d.data_hora_compra::date AS data_venda,
        d.stage,
        d.tipo_venda,
        CASE
            WHEN NULLIF(btrim(d.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END AS montante,
        CASE
            WHEN NULLIF(btrim(d.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END AS receita,
        l.created_at AS lead_created_at,
        l.email AS lead_email,
        l.classificado,
        COALESCE(
            NULLIF(btrim(d.origem), ''),
            NULLIF(btrim(d.fonte_de_lead), ''),
            NULLIF(btrim(l.utm_source), '')
        ) AS origem_fonte
    FROM zoho_deals d
    LEFT JOIN ext_reconecta.leads l
           ON d.id::text = l.zoho_id::text
),
acts AS (
    SELECT
        a.id::text AS activity_id,
        a.created_time AS created_time,
        a.created_time::date AS data_criacao,
        a.start_datetime AS start_datetime,
        a.start_datetime::date AS data_agendamento,
        a.status_reuniao,
        a.activity_type,
        a.prevendas,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END AS act_deal_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND (
          a.created_time::date BETWEEN :data_ini AND :data_fim
          OR a.start_datetime::date BETWEEN :data_ini AND :data_fim
      )
),
activity_rows AS (
    SELECT
        'Atividade'::text AS tipo_registro_base,
        a.data_agendamento,
        a.data_criacao,
        NULL::date AS data_venda,
        b.nome_cliente,
        b.lead_email AS email_lead,
        b.deal_ref AS nome_deal,
        b.classificado AS classificacao,
        a.status_reuniao,
        b.origem_fonte,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) AS sdr,
        COALESCE(
            NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), ''),
            'Sem Closer'
        ) AS closer,
        b.deal_id,
        a.activity_id,
        NULL::numeric AS montante,
        NULL::numeric AS receita
    FROM acts a
    JOIN base_dados b
      ON a.act_deal_id = b.deal_id
    LEFT JOIN zoho_users u
           ON u.id::text = b.sdr_ss_id
    LEFT JOIN zoho_users uc
           ON uc.id::text = b.closer_id
),
sales_base AS (
    SELECT DISTINCT ON (b.deal_id)
        b.data_venda,
        b.nome_cliente,
        b.lead_email AS email_lead,
        b.deal_ref AS nome_deal,
        b.classificado AS classificacao,
        b.origem_fonte,
        COALESCE(
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) AS sdr,
        COALESCE(
            NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), ''),
            'Sem Closer'
        ) AS closer,
        b.deal_id,
        b.montante,
        b.receita,
        b.lead_created_at
    FROM base_dados b
    LEFT JOIN zoho_users u
           ON u.id::text = b.sdr_ss_id
    LEFT JOIN zoho_users uc
           ON uc.id::text = b.closer_id
    WHERE b.stage = 'Ganho'
      AND b.tipo_venda = 'Novo cliente'
      AND b.data_venda BETWEEN :data_ini AND :data_fim
    ORDER BY b.deal_id, b.lead_created_at DESC NULLS LAST, b.nome_cliente
),
sales_rows AS (
    SELECT
        'Venda'::text AS tipo_registro_base,
        NULL::date AS data_agendamento,
        NULL::date AS data_criacao,
        sb.data_venda,
        sb.nome_cliente,
        sb.email_lead,
        sb.nome_deal,
        sb.classificacao,
        NULL::text AS status_reuniao,
        sb.origem_fonte,
        sb.sdr,
        sb.closer,
        sb.deal_id,
        NULL::text AS activity_id,
        sb.montante,
        sb.receita
    FROM sales_base sb
),
final_rows AS (
    SELECT
        tipo_registro_base,
        a.data_agendamento,
        a.data_criacao,
        data_venda,
        nome_cliente,
        email_lead,
        nome_deal,
        classificacao,
        status_reuniao,
        origem_fonte,
        sdr,
        closer,
        deal_id,
        activity_id,
        montante,
        receita
    FROM activity_rows a

    UNION ALL

    SELECT
        tipo_registro_base,
        data_agendamento,
        data_criacao,
        data_venda,
        nome_cliente,
        email_lead,
        nome_deal,
        classificacao,
        status_reuniao,
        origem_fonte,
        sdr,
        closer,
        deal_id,
        activity_id,
        montante,
        receita
    FROM sales_rows
)
SELECT
    tipo_registro_base,
    data_agendamento,
    data_criacao,
    data_venda,
    nome_cliente,
    email_lead,
    nome_deal,
    classificacao,
    status_reuniao,
    origem_fonte,
    sdr,
    closer,
    deal_id,
    activity_id,
    montante,
    receita
FROM final_rows
ORDER BY COALESCE(data_agendamento, data_criacao, data_venda), deal_id, activity_id NULLS LAST;
