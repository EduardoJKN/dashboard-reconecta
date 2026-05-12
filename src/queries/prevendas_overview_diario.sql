-- =============================================================================
-- Pré-vendas — série diária consolidada (Visão Geral Pré-vendas).
-- =============================================================================
-- Regra fiel do dashboard legado validada manualmente no pgAdmin:
--   - base principal em `zoho_deals`
--   - LEFT JOIN `ext_reconecta.leads` ON d.id::text = l.zoho_id::text
--   - activities ligadas ao deal via `what_id` normalizado
--   - considerar apenas activities com `status_reuniao IS NOT NULL`
--
-- Métricas diárias:
--   - agendamentos_criados = `zoho_activities.created_time::date`
--   - agendamentos         = `zoho_activities.start_datetime::date`
--   - agendamentos_mais_12 = agendamentos com `classificado = 'Atua +12'`
--   - comparecimentos      = status_reuniao IN ('Concluída', 'Concluído')
--   - vendas               = `zoho_deals.data_hora_compra::date`
--                            com `stage = 'Ganho'` e `tipo_venda = 'Novo cliente'`
--   - montante / receita   = valores direto de `zoho_deals`
--
-- Compatibilidade com páginas ainda não migradas:
--   - `novos_agendamentos` = alias de `agendamentos_criados`
--   - `vendas_novas`       = alias de `vendas`
-- =============================================================================
WITH leads_diario AS (
    SELECT
        l.created_at::date AS data_ref,
        COUNT(DISTINCT lower(btrim(l.email)))::bigint AS leads
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    GROUP BY 1
),
base_dados AS (
    SELECT
        d.id AS deal_id,
        d.data_hora_compra::date AS data_venda_ref,
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
        l.classificado
    FROM zoho_deals d
    LEFT JOIN ext_reconecta.leads l ON d.id::text = l.zoho_id::text
),
acts AS (
    SELECT
        bd.deal_id,
        bd.classificado,
        a.created_time::date AS data_criacao_ref,
        a.start_datetime::date AS data_reuniao_ref,
        a.status_reuniao,
        a.id AS activity_id
    FROM base_dados bd
    JOIN zoho_activities a
      ON regexp_replace(COALESCE(a.what_id::text, ''), '[^0-9A-Za-z]', '', 'g')
       = regexp_replace(bd.deal_id::text, '[^0-9A-Za-z]', '', 'g')
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND (
          a.created_time::date BETWEEN :data_ini AND :data_fim
          OR a.start_datetime::date BETWEEN :data_ini AND :data_fim
      )
),
agendamentos_criados_diario AS (
    SELECT
        data_criacao_ref AS data_ref,
        COUNT(*)::bigint AS agendamentos_criados
    FROM acts
    WHERE data_criacao_ref BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),
agendamentos_diario AS (
    SELECT
        data_reuniao_ref AS data_ref,
        COUNT(*)::bigint AS agendamentos,
        COUNT(*) FILTER (
            WHERE classificado = 'Atua +12'
        )::bigint AS agendamentos_mais_12,
        COUNT(*) FILTER (
            WHERE status_reuniao IN ('Concluída', 'Concluído')
        )::bigint AS comparecimentos,
        COUNT(*) FILTER (
            WHERE status_reuniao = 'Vencida'
        )::bigint AS vencidas
    FROM acts
    WHERE data_reuniao_ref BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),
vendas_diario AS (
    SELECT
        bd.data_venda_ref AS data_ref,
        COUNT(DISTINCT bd.deal_id)::bigint AS vendas,
        SUM(bd.montante)::numeric AS montante,
        SUM(bd.receita)::numeric AS receita
    FROM base_dados bd
    WHERE bd.stage = 'Ganho'
      AND bd.tipo_venda = 'Novo cliente'
      AND bd.data_venda_ref BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),
keys AS (
    SELECT data_ref FROM leads_diario
    UNION
    SELECT data_ref FROM agendamentos_criados_diario
    UNION
    SELECT data_ref FROM agendamentos_diario
    UNION
    SELECT data_ref FROM vendas_diario
)
SELECT
    k.data_ref,
    COALESCE(l.leads, 0)::bigint AS leads,
    COALESCE(c.agendamentos_criados, 0)::bigint AS agendamentos_criados,
    COALESCE(c.agendamentos_criados, 0)::bigint AS novos_agendamentos,
    COALESCE(a.agendamentos, 0)::bigint AS agendamentos,
    COALESCE(a.agendamentos, 0)::bigint AS reunioes_marcadas,
    COALESCE(a.agendamentos_mais_12, 0)::bigint AS agendamentos_mais_12,
    COALESCE(a.comparecimentos, 0)::bigint AS comparecimentos,
    COALESCE(a.comparecimentos, 0)::bigint AS concluidas,
    0::bigint AS canceladas,
    COALESCE(a.vencidas, 0)::bigint AS vencidas,
    0::bigint AS agendadas_pendentes,
    COALESCE(v.vendas, 0)::bigint AS vendas,
    COALESCE(v.vendas, 0)::bigint AS vendas_novas,
    COALESCE(v.montante, 0)::numeric AS montante,
    COALESCE(v.receita, 0)::numeric AS receita
FROM keys k
LEFT JOIN leads_diario l USING (data_ref)
LEFT JOIN agendamentos_criados_diario c USING (data_ref)
LEFT JOIN agendamentos_diario a USING (data_ref)
LEFT JOIN vendas_diario v USING (data_ref)
ORDER BY k.data_ref;
