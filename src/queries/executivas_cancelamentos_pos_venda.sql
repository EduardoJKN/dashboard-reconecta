-- =============================================================================
-- Cancelamentos por Pós-venda — 1 linha por activity Consulta cancelada.
-- =============================================================================
-- Universo = card Cancelados (Consulta + Cancelada/Cancelado).
-- E-mail: deal.email → ext_reconecta.leads via zoho_id (regra do detalhe
-- Pré-vendas / prevendas_leads_detalhe_diario).
-- Agregação por e-mail ocorre em Python (`cancelamentos_pos_processar`).
-- =============================================================================
WITH cancelamentos AS (
    SELECT
        a.id::text AS activity_id,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END AS deal_id,
        COALESCE(a.start_datetime, a.created_time) AS ts_cancelamento,
        COALESCE(a.start_datetime, a.created_time)::date AS data_cancelamento,
        a.status_reuniao,
        NULLIF(btrim(a.motivo_cancelamento_e_nao_comparecimento), '') AS motivo_cancelamento,
        a.owner::text AS activity_owner_id,
        NULLIF(TRIM(ua.first_name || ' ' || ua.last_name), '') AS activity_owner_nome
    FROM zoho_activities a
    LEFT JOIN zoho_users ua ON ua.id::text = a.owner::text
    WHERE a.activity_type = 'Consulta'
      AND a.status_reuniao IN ('Cancelada', 'Cancelado')
      AND a.what_id IS NOT NULL
      AND btrim(a.what_id::text) <> ''
),
deals_info AS (
    SELECT
        c.activity_id,
        c.deal_id,
        c.ts_cancelamento,
        c.data_cancelamento,
        c.status_reuniao,
        c.motivo_cancelamento,
        c.activity_owner_nome,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), '')
        ) AS nome_cliente,
        NULLIF(btrim(d.email), '') AS email,
        d.executiva_vendas::text AS closer_id
    FROM cancelamentos c
    LEFT JOIN zoho_deals d ON d.id::text = c.deal_id
),
lead_email AS (
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text AS deal_id,
        NULLIF(btrim(l.email), '') AS email,
        lower(btrim(l.email)) AS email_norm
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY l.zoho_id::text, l.timestamp DESC NULLS LAST, l.id DESC
),
cancel_com_email AS (
    SELECT
        di.*,
        COALESCE(
            NULLIF(lower(btrim(di.email)), ''),
            le.email_norm
        ) AS email_norm,
        COALESCE(di.email, le.email) AS email_resolvido
    FROM deals_info di
    LEFT JOIN lead_email le ON le.deal_id = di.deal_id
),
closer_resolved AS (
    SELECT
        ce.activity_id,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS closer_nome_deal,
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
    FROM cancel_com_email ce
    LEFT JOIN zoho_users uc ON uc.id::text = ce.closer_id
)
SELECT
    ce.activity_id,
    ce.deal_id,
    ce.email_norm,
    ce.email_resolvido AS email,
    ce.nome_cliente,
    ce.data_cancelamento,
    ce.ts_cancelamento,
    ce.status_reuniao,
    ce.motivo_cancelamento,
    COALESCE(cr.closer_nome_deal, ce.activity_owner_nome) AS closer_nome,
    cr.time_vendas
FROM cancel_com_email ce
LEFT JOIN closer_resolved cr ON cr.activity_id = ce.activity_id
ORDER BY ce.data_cancelamento DESC NULLS LAST, ce.activity_id;
