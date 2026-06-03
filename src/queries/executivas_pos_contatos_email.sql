-- =============================================================================
-- Contatos de pós-venda indexados por e-mail (união de fontes).
-- =============================================================================
-- Usado pela aba Cancelamentos por Pós-venda: cruzamento
-- cancelados.email_norm = pos.email_norm em Python.
-- =============================================================================
WITH deal_emails AS (
    SELECT
        d.id::text AS deal_id,
        NULLIF(btrim(d.email), '') AS email,
        lower(btrim(d.email)) AS email_norm
    FROM zoho_deals d
    WHERE d.email IS NOT NULL
      AND btrim(d.email) <> ''
      AND lower(d.email) NOT LIKE '%@teste%'
      AND lower(d.email) NOT LIKE 'teste@%'
      AND lower(d.email) NOT LIKE '%smarts%'
      AND lower(d.email) NOT LIKE '%reconecta%'
),
notificacao AS (
    SELECT
        lower(btrim(n.email)) AS email_norm,
        NULLIF(btrim(n.email), '') AS email,
        n.dt_criacao AS dt_contato,
        NULLIF(btrim(n.cs_nome), '') AS pos_nome_candidato,
        'controle_notificacao_vendas'::text AS origem
    FROM fdw_reconecta.controle_notificacao_vendas n
    WHERE n.email IS NOT NULL
      AND btrim(n.email) <> ''
      AND n.cs_nome IS NOT NULL
      AND btrim(n.cs_nome) <> ''
),
acompanhamento AS (
    SELECT
        de.email_norm,
        de.email,
        za.created_time AS dt_contato,
        COALESCE(
            NULLIF(btrim(za.executiva_contas_name), ''),
            NULLIF(btrim(za.owner_name), '')
        ) AS pos_nome_candidato,
        'zoho_acompanhamentos'::text AS origem
    FROM zoho_acompanhamentos za
    JOIN deal_emails de ON de.deal_id = za.cliente_id::text
    WHERE za.cliente_id IS NOT NULL
      AND btrim(za.cliente_id::text) <> ''
      AND COALESCE(
            NULLIF(btrim(za.executiva_contas_name), ''),
            NULLIF(btrim(za.owner_name), '')
          ) IS NOT NULL
),
pos_activities AS (
    SELECT
        de.email_norm,
        de.email,
        COALESCE(za.start_datetime, za.created_time) AS dt_contato,
        NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') AS pos_nome_candidato,
        ('zoho_activities (' || COALESCE(za.activity_type, '?') || ')')::text AS origem
    FROM zoho_activities za
    JOIN deal_emails de
      ON (
            CASE
                WHEN za.what_id ~ '^\{.*\}$'
                    THEN (za.what_id::json ->> 'id')::text
                ELSE regexp_replace(COALESCE(za.what_id, ''), '\D', '', 'g')
            END
        ) = de.deal_id
    LEFT JOIN zoho_users u ON u.id::text = za.owner::text
    WHERE za.activity_type IN (
        'Onboarding',
        'Acompanhamento',
        'Onboarding-mastermid-reconecta',
        'Call-asc'
    )
      AND za.what_id IS NOT NULL
      AND btrim(za.what_id::text) <> ''
      AND NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') IS NOT NULL
)
SELECT email_norm, email, dt_contato, pos_nome_candidato, origem
FROM notificacao
WHERE email_norm IS NOT NULL AND btrim(email_norm) <> ''
  AND pos_nome_candidato IS NOT NULL

UNION ALL

SELECT email_norm, email, dt_contato, pos_nome_candidato, origem
FROM acompanhamento
WHERE email_norm IS NOT NULL AND btrim(email_norm) <> ''
  AND pos_nome_candidato IS NOT NULL

UNION ALL

SELECT email_norm, email, dt_contato, pos_nome_candidato, origem
FROM pos_activities
WHERE email_norm IS NOT NULL AND btrim(email_norm) <> ''
  AND pos_nome_candidato IS NOT NULL;
