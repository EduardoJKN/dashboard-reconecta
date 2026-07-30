-- =============================================================================
-- Executivas — Indicações · Agendamentos criados (regra Looker, só Indicações).
-- =============================================================================
-- Extrato enxuto da métrica Looker `agendamentos_criados`:
--   - activity_type IN ('Consulta', 'Indicação') com start_datetime preenchido
--   - data do card = created_time::date no período
--   - anti-retroativo: start_datetime::date >= created_time::date
--   - 1 deal por dia (DISTINCT ON data_criacao, deal_id — mais recente)
--   - origem Indicações = fonte_de_lead ILIKE '%indic%'
--
-- Closer = executiva_vendas; Pós-vendas = executiva_contas (quem agenda no
-- fluxo de indicação/renovação — separado dos agendamentos de pré-vendas).
-- =============================================================================
WITH atividades AS (
    SELECT
        a.id::text AS activity_id,
        a.created_time AS data_hora_criacao,
        a.created_time::date AS data_criacao,
        a.start_datetime::date AS data_atividade,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END AS deal_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.start_datetime IS NOT NULL
      AND a.created_time::date BETWEEN :data_ini AND :data_fim
      AND a.start_datetime::date >= a.created_time::date
),
deals_indic AS (
    SELECT
        d.id::text AS deal_id,
        d.executiva_vendas::text AS closer_id,
        d.executiva_contas::text AS pos_id,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), ''),
            'Sem nome'
        ) AS nome,
        NULLIF(btrim(d.email), '') AS email
    FROM zoho_deals d
    WHERE d.fonte_de_lead ILIKE '%indic%'
      AND (
          d.email IS NULL
          OR (
              btrim(d.email) <> ''
              AND lower(d.email) NOT LIKE '%@teste%'
              AND lower(d.email) NOT LIKE 'teste@%'
              AND lower(d.email) NOT LIKE '%smarts%'
              AND lower(d.email) NOT LIKE '%reconecta%'
          )
      )
),
raw AS (
    SELECT
        a.data_criacao,
        a.data_hora_criacao,
        a.activity_id,
        d.deal_id,
        d.nome,
        d.email,
        d.closer_id,
        d.pos_id
    FROM atividades a
    JOIN deals_indic d ON d.deal_id = NULLIF(a.deal_id, '')
),
dedup AS (
    -- 1 agendamento criado por deal em cada dia (activity mais recente).
    SELECT DISTINCT ON (data_criacao, deal_id)
        data_criacao,
        activity_id,
        deal_id,
        nome,
        email,
        closer_id,
        pos_id
    FROM raw
    ORDER BY
        data_criacao,
        deal_id,
        data_hora_criacao DESC NULLS LAST,
        activity_id DESC
),
closer_resolved AS (
    SELECT
        uc.id::text AS closer_id,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS executiva,
        CASE
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Andrezza Ayuso Serpa%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Hawinne Cristina%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Nathally Pereira dos Santos%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Thaís Cadó%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Thais Cado%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Stefany Campinas%'
                THEN 'Time da Leidianne'
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leandro Alves%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leonardo Melo Patriota%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leonardo Patriota%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Nathan Carloto%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Camile Silveira%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Henrique Gonçalves%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Henrique Goncalves%'
                THEN 'Time do Marcelo'
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Dayana Moura%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Karine Pacífico%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Karine Pacifico%'
                THEN 'Time do Marcelo Executivas'
            ELSE 'Sem time definido'
        END AS time_vendas
    FROM zoho_users uc
),
pos_resolved AS (
    SELECT
        up.id::text AS pos_id,
        NULLIF(TRIM(up.first_name || ' ' || up.last_name), '') AS pos_vendas
    FROM zoho_users up
)
SELECT
    dd.data_criacao,
    dd.activity_id,
    dd.deal_id,
    dd.nome,
    dd.email,
    COALESCE(cr.executiva, 'Sem Closer') AS executiva,
    COALESCE(cr.time_vendas, 'Sem time definido') AS time_vendas,
    COALESCE(pr.pos_vendas, 'Sem pós-vendas') AS pos_vendas
FROM dedup dd
LEFT JOIN closer_resolved cr ON cr.closer_id = dd.closer_id
LEFT JOIN pos_resolved pr ON pr.pos_id = dd.pos_id
ORDER BY dd.data_criacao DESC, dd.deal_id;
