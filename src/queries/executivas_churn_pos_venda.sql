-- =============================================================================
-- Churn por Pós-venda — 1 linha por deal com stage = 'Churn'.
-- =============================================================================
-- Universo: churn real de cliente (NÃO reuniões canceladas do funil).
--
-- Data do churn (ordem de preferência — ver comentário em `data_churn`):
--   1) stage_modified_time  — quando o stage passou a Churn no CRM
--   2) modified_time        — fallback se stage_modified_time nulo
--   3) data_hora_compra     — último recurso (data de compra original)
--
-- Vínculo principal (campos brutos p/ match no Python):
--   executiva_contas → zoho_users → pos_user_nome / pos_user_id
--   + cadastro fdw executivas_pos_vendas (id_crm + tokens)
--
-- Reforços (complementares):
--   zoho_activities (Onboarding, Acompanhamento, …) no mesmo deal
--   zoho_acompanhamentos via cliente_id = deal.id
-- =============================================================================
WITH churn_deals AS (
    SELECT
        d.id::text AS deal_id,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), '')
        ) AS nome_cliente,
        NULLIF(btrim(d.email), '') AS email,
        d.stage,
        d.executiva_contas::text AS executiva_contas_id,
        d.executiva_vendas::text AS closer_id,
        NULLIF(btrim(d.motivo_perda), '') AS motivo_perda,
        -- Data do churn — ver cabeçalho do arquivo.
        COALESCE(
            d.stage_modified_time,
            d.modified_time,
            d.data_hora_compra
        )::timestamp AS ts_churn,
        COALESCE(
            d.stage_modified_time::date,
            d.modified_time::date,
            d.data_hora_compra::date
        ) AS data_churn,
        CASE
            WHEN d.stage_modified_time IS NOT NULL THEN 'stage_modified_time'
            WHEN d.modified_time IS NOT NULL THEN 'modified_time'
            ELSE 'data_hora_compra'
        END AS data_churn_fonte,
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
        END AS receita
    FROM zoho_deals d
    WHERE d.stage = 'Churn'
),
closer_resolved AS (
    -- Nome + time_vendas: mesma regra CASE de prevendas_leads_detalhe_diario /
    -- bi.vw_dashboard_comercial_executivas_rw (filtro TIMES no dashboard).
    SELECT
        cd.deal_id,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS closer_nome,
        CASE
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Andrezza Ayuso Serpa%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Hawinne Cristina%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Nathally Pereira dos Santos%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Thaís Cadó%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Thais Cado%'
                THEN 'Time da Leidianne'
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leandro Alves%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leonardo Melo Patriota%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leonardo Patriota%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Nathan Carloto%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Camile Silveira%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Henrique Gonçalves%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Henrique Goncalves%'
                THEN 'Time do Marcelo'
            ELSE 'Sem time definido'
        END AS time_vendas
    FROM churn_deals cd
    LEFT JOIN zoho_users uc ON uc.id::text = cd.closer_id
),
pos_user AS (
    SELECT
        cd.deal_id,
        cd.executiva_contas_id,
        u.id::text AS pos_user_id,
        NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') AS pos_user_nome
    FROM churn_deals cd
    LEFT JOIN zoho_users u ON u.id::text = cd.executiva_contas_id
),
pos_activities AS (
    SELECT
        CASE
            WHEN za.what_id ~ '^\{.*\}$'
                THEN (za.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(za.what_id, ''), '\D', '', 'g')
        END AS deal_id,
        COUNT(*)::bigint AS qtd_contatos_pos,
        MAX(COALESCE(za.start_datetime, za.created_time)) AS ultimo_contato_pos,
        (ARRAY_AGG(
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), '')
            ORDER BY COALESCE(za.start_datetime, za.created_time) DESC NULLS LAST
        ))[1] AS ultimo_owner_pos_nome
    FROM zoho_activities za
    LEFT JOIN zoho_users u ON u.id::text = za.owner::text
    WHERE za.activity_type IN (
        'Onboarding',
        'Acompanhamento',
        'Onboarding-mastermid-reconecta',
        'Call-asc'
    )
      AND za.what_id IS NOT NULL
      AND btrim(za.what_id::text) <> ''
    GROUP BY 1
),
acompanhamento_pick AS (
    SELECT DISTINCT ON (za.cliente_id)
        za.cliente_id::text AS deal_id,
        NULLIF(btrim(za.executiva_contas_name), '') AS acomp_pos_nome,
        za.created_time AS acomp_created_time
    FROM zoho_acompanhamentos za
    WHERE za.cliente_id IS NOT NULL
      AND btrim(za.cliente_id::text) <> ''
    ORDER BY za.cliente_id, za.created_time DESC NULLS LAST
)
SELECT
    cd.deal_id,
    cd.nome_cliente,
    cd.email,
    cd.stage,
    cd.data_churn,
    cd.ts_churn,
    cd.data_churn_fonte,
    cr.closer_nome,
    cr.time_vendas,
    pu.executiva_contas_id,
    pu.pos_user_id,
    pu.pos_user_nome,
    pa.qtd_contatos_pos,
    pa.ultimo_contato_pos,
    pa.ultimo_owner_pos_nome,
    ap.acomp_pos_nome,
    cd.montante,
    cd.receita,
    cd.motivo_perda
FROM churn_deals cd
LEFT JOIN closer_resolved cr ON cr.deal_id = cd.deal_id
LEFT JOIN pos_user pu ON pu.deal_id = cd.deal_id
LEFT JOIN pos_activities pa ON pa.deal_id = cd.deal_id
LEFT JOIN acompanhamento_pick ap ON ap.deal_id = cd.deal_id
ORDER BY cd.data_churn DESC NULLS LAST, cd.deal_id;
