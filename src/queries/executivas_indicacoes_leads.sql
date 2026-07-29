-- =============================================================================
-- Executivas — Indicações (1 linha por deal com fonte Indicação no período).
-- =============================================================================
-- Universo: oportunidades/deals com `fonte_de_lead = 'Indicação'` e
-- `created_at::date` no período filtrado (chegada da indicação).
--
-- Stage atual do CRM (`zoho_deals.stage`) alimenta funil, kanban e tabela.
-- Closer/time: mesma regra CASE de prevendas_leads_detalhe_diario /
-- bi.vw_dashboard_comercial_executivas_rw (filtro TIMES no dashboard).
-- Pós-vendas: `executiva_contas` (quem acompanha / agenda no fluxo de
-- indicações, conforme operação do time).
--
-- E-mails de teste excluídos (mesma regra canônica da One Page).
-- =============================================================================
WITH deals_periodo AS (
    SELECT
        d.id::text AS deal_id,
        d.created_at::date AS data_criacao,
        d.stage,
        d.executiva_vendas::text AS closer_id,
        d.executiva_contas::text AS pos_id,
        COALESCE(
            NULLIF(btrim(d.contact_name), ''),
            NULLIF(btrim(d.nome_cal), ''),
            NULLIF(btrim(d.nome_typebot), ''),
            NULLIF(btrim(d.deal_name), ''),
            'Sem nome'
        ) AS nome_cliente,
        NULLIF(btrim(d.email), '') AS email,
        NULLIF(btrim(d.tipo_venda), '') AS tipo_venda,
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
        d.data_hora_compra::date AS data_compra
    FROM zoho_deals d
    WHERE d.fonte_de_lead = 'Indicação'
      AND d.created_at::date BETWEEN :data_ini AND :data_fim
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
closer_resolved AS (
    SELECT
        dp.deal_id,
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
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Dayana Moura%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Karine Pacífico%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Karine Pacifico%'
                THEN 'Time do Marcelo'
            ELSE 'Sem time definido'
        END AS time_vendas
    FROM deals_periodo dp
    LEFT JOIN zoho_users uc ON uc.id::text = dp.closer_id
),
pos_resolved AS (
    SELECT
        dp.deal_id,
        NULLIF(TRIM(up.first_name || ' ' || up.last_name), '') AS pos_vendas
    FROM deals_periodo dp
    LEFT JOIN zoho_users up ON up.id::text = dp.pos_id
)
SELECT
    dp.deal_id,
    dp.data_criacao,
    dp.stage,
    dp.nome_cliente,
    dp.email,
    dp.tipo_venda,
    dp.montante,
    dp.receita,
    dp.data_compra,
    COALESCE(cr.executiva, 'Sem Closer') AS executiva,
    COALESCE(cr.time_vendas, 'Sem time definido') AS time_vendas,
    COALESCE(pr.pos_vendas, 'Sem pós-vendas') AS pos_vendas
FROM deals_periodo dp
LEFT JOIN closer_resolved cr ON cr.deal_id = dp.deal_id
LEFT JOIN pos_resolved pr ON pr.deal_id = dp.deal_id
ORDER BY dp.data_criacao DESC, dp.deal_id;
