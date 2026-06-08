-- =============================================================================
-- Executivas — agendamentos do Funil absoluto (1 linha por activity).
-- =============================================================================
-- Replica a regra de `agendamentos` em bi.vw_dashboard_comercial_executivas_rw:
--   - fonte: zoho_activities (Consulta / Indicação)
--   - data_ref: start_datetime::date (data da reunião, NÃO created_at do deal)
--   - status_reuniao IS NOT NULL
--   - status_reuniao <> 'Vencida' (case-insensitive, trim)
--   - ligação ao deal: what_id normalizado → zoho_deals.id
--   - atribuição: executiva_vendas do deal (fallback: owner da activity)
--
-- Objetivo: cruzar cada agendamento do funil com zoho_deals.stage atual.
-- =============================================================================
WITH atividades_parseadas AS (
    SELECT
        za.id::text AS activity_id,
        za.owner::text AS activity_owner_id,
        za.start_datetime::date AS data_reuniao,
        za.created_time::date AS data_criacao_activity,
        za.status_reuniao,
        za.activity_type,
        CASE
            WHEN za.what_id ~ '^\{.*\}$'
                THEN (za.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(za.what_id, ''), '\D', '', 'g')
        END AS deal_id
    FROM zoho_activities za
    WHERE za.activity_type IN ('Consulta', 'Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
),
deals_ligados AS (
    SELECT
        ap.activity_id,
        ap.data_reuniao,
        ap.data_criacao_activity,
        ap.status_reuniao,
        ap.activity_type,
        NULLIF(ap.deal_id, '') AS deal_id,
        COALESCE(d.executiva_vendas::text, ap.activity_owner_id) AS owner_id,
        d.stage,
        d.triagem,
        COALESCE(NULLIF(TRIM(d.triagem), ''), 'Sem informação') AS triagem_tratada,
        d.created_at::date AS deal_created_at
    FROM atividades_parseadas ap
    LEFT JOIN zoho_deals d ON d.id::text = NULLIF(ap.deal_id, '')
    WHERE ap.status_reuniao IS NOT NULL
      AND lower(btrim(ap.status_reuniao)) <> 'vencida'
),
closer_resolved AS (
    SELECT
        dl.activity_id,
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
            ELSE 'Sem time definido'
        END AS time_vendas
    FROM deals_ligados dl
    LEFT JOIN zoho_users uc ON uc.id::text = dl.owner_id
)
SELECT
    dl.activity_id,
    dl.data_reuniao,
    dl.data_criacao_activity,
    dl.status_reuniao,
    dl.activity_type,
    dl.deal_id,
    dl.deal_created_at,
    COALESCE(dl.stage, 'Sem etapa') AS stage,
    dl.triagem_tratada,
    COALESCE(cr.executiva, 'Sem Closer') AS executiva,
    COALESCE(cr.time_vendas, 'Sem time definido') AS time_vendas
FROM deals_ligados dl
LEFT JOIN closer_resolved cr ON cr.activity_id = dl.activity_id
ORDER BY dl.data_reuniao DESC, dl.activity_id;
