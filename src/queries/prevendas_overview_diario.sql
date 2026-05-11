-- =============================================================================
-- Pré-vendas — série diária consolidada (Visão Geral Pré-vendas).
-- =============================================================================
-- 1 linha por data_ref no período com:
--   leads        = leads únicos/dia (regra Visão Geral Marketing)
--   agendamentos = leads únicos com activity Consulta/Indicação no dia
--                  (start_datetime::date) — atribuídos via what_id → deal
--                  → priority match lead `zoho_id > session_id > email`.
--                  Quando a activity não casa com lead, ainda conta no
--                  `agendamentos_brutos` (atividades isoladas).
--   comparecimentos = subset com status_reuniao = 'Concluída'
--   vendas        = zoho_deals stage IN ('Ganho','Fechado Ganho') no
--                   data_hora_compra::date
--   vendas_novas  = subset tipo_venda = 'Novo cliente'
--   montante      = SUM(amount) das vendas
--   receita       = SUM(receita) das vendas
--
-- Observação: aqui o foco é Pré-vendas como SETOR — séries agregadas pra
-- alimentar a Tendência diária. Quebra por SDR vai em
-- prevendas_por_sdr.sql.
-- =============================================================================
WITH
-- Leads únicos/dia (mesma regra de mkt_visao_geral_diario.sql).
leads_diario AS (
    SELECT
        l.created_at::date AS data_ref,
        COUNT(DISTINCT lower(btrim(l.email)))::bigint AS leads
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    GROUP BY 1
),
-- Atividades de pré-vendas (Consulta/Indicação) com possível match a deal.
acts AS (
    SELECT
        a.start_datetime::date AS data_ref,
        a.what_id,
        a.status_reuniao,
        a.id AS activity_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta','Indicação')
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
-- Agregação diária de atividades (sem precisar passar pelo lead — a métrica
-- aqui é de atividades realizadas pela pré-vendas, conta cada activity 1×).
acts_diario AS (
    SELECT
        data_ref,
        COUNT(*)::bigint AS agendamentos,
        COUNT(*) FILTER (WHERE status_reuniao = 'Concluída')::bigint
            AS comparecimentos
    FROM acts
    GROUP BY data_ref
),
-- Vendas (zoho_deals) por dia, com regra oficial Vendas novas.
vendas_diario AS (
    SELECT
        zd.data_hora_compra::date AS data_ref,
        COUNT(DISTINCT zd.id)::bigint AS vendas,
        COUNT(DISTINCT zd.id) FILTER (
            WHERE zd.tipo_venda = 'Novo cliente'
        )::bigint AS vendas_novas,
        SUM(
            CASE WHEN NULLIF(btrim(zd.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(zd.amount), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
            END
        )::numeric AS montante,
        SUM(
            CASE WHEN NULLIF(btrim(zd.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(zd.receita), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
            END
        )::numeric AS receita
    FROM zoho_deals zd
    WHERE zd.stage IN ('Ganho','Fechado Ganho')
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),
keys AS (
    SELECT data_ref FROM leads_diario
    UNION SELECT data_ref FROM acts_diario
    UNION SELECT data_ref FROM vendas_diario
)
SELECT
    k.data_ref,
    COALESCE(l.leads, 0)::bigint           AS leads,
    COALESCE(a.agendamentos, 0)::bigint    AS agendamentos,
    COALESCE(a.comparecimentos, 0)::bigint AS comparecimentos,
    COALESCE(v.vendas, 0)::bigint          AS vendas,
    COALESCE(v.vendas_novas, 0)::bigint    AS vendas_novas,
    COALESCE(v.montante, 0)::numeric       AS montante,
    COALESCE(v.receita, 0)::numeric        AS receita
FROM keys k
LEFT JOIN leads_diario  l USING (data_ref)
LEFT JOIN acts_diario   a USING (data_ref)
LEFT JOIN vendas_diario v USING (data_ref)
ORDER BY k.data_ref;
