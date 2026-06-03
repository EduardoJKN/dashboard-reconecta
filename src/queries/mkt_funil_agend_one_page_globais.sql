-- =============================================================================
-- Totais globais alinhados à One Page / Pré-vendas (1 row).
-- Mesma base de `prevendas_overview_diario.sql`:
--   - deals + activities (Consulta/Indicação, status_reuniao NOT NULL)
--   - agendamentos exibidos = reuniões no período (start_datetime::date)
--     excluindo status vencido (equivalente a bruto − vencidas no KPI)
--   - comparecimentos = reuniões concluídas no período
--   - vendas = deals Ganho + Novo cliente com compra no período
-- Decomposição Período / Histórico (sobre o total oficial):
--   - período: e-mail com aplicação Typeform no período (`created_at::date`)
--   - histórico: demais do total (UI fecha histórico = total − período)
-- =============================================================================
WITH aplicacoes_periodo_emails AS (
    SELECT DISTINCT lower(btrim(ta.email)) AS email_norm
    FROM fdw_reconecta.typeform_aplicacoes ta
    WHERE ta.created_at::date BETWEEN :data_ini AND :data_fim
      AND ta.dados_completos IS TRUE
      AND ta.email IS NOT NULL
      AND btrim(ta.email) <> ''
      AND lower(btrim(ta.email)) NOT LIKE '%@teste%'
      AND lower(btrim(ta.email)) NOT LIKE '%teste@%'
      AND lower(btrim(ta.email)) NOT LIKE '%smarts%'
      AND lower(btrim(ta.email)) NOT LIKE '%reconecta%'
),
pv_ext_leads_dedup AS (
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text AS deal_id,
        lower(btrim(l.email)) AS ext_email_norm
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY l.zoho_id::text, l."timestamp" DESC NULLS LAST, l.id DESC
),
pv_base_dados AS (
    SELECT
        d.id AS deal_id,
        lower(btrim(COALESCE(d.email, ''))) AS deal_email_norm,
        eld.ext_email_norm
    FROM zoho_deals d
    LEFT JOIN pv_ext_leads_dedup eld ON d.id::text = eld.deal_id
),
pv_acts AS (
    SELECT
        bd.deal_id,
        a.id AS activity_id,
        a.status_reuniao,
        a.start_datetime::date AS data_reuniao_ref,
        COALESCE(
            NULLIF(bd.deal_email_norm, ''),
            bd.ext_email_norm,
            ''
        ) AS email_norm
    FROM pv_base_dados bd
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
pv_acts_exibidos AS (
    SELECT activity_id, email_norm
    FROM pv_acts
    WHERE data_reuniao_ref BETWEEN :data_ini AND :data_fim
      AND COALESCE(status_reuniao, '') NOT ILIKE '%vencid%'
),
pv_acts_comparecimentos AS (
    SELECT activity_id, email_norm
    FROM pv_acts
    WHERE data_reuniao_ref BETWEEN :data_ini AND :data_fim
      AND status_reuniao IN ('Concluída', 'Concluído')
),
pv_deals_vendas AS (
    SELECT
        bd.deal_id,
        COALESCE(
            NULLIF(bd.deal_email_norm, ''),
            bd.ext_email_norm,
            ''
        ) AS email_norm
    FROM pv_base_dados bd
    INNER JOIN zoho_deals d ON d.id = bd.deal_id
    WHERE d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
agend_agg AS (
    SELECT
        COUNT(DISTINCT activity_id)::bigint                           AS agendamentos_globais,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE email_norm <> ''
              AND email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                                   AS agendamentos_leads_periodo_globais,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE email_norm = ''
               OR email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                                   AS agendamentos_leads_historico_globais
    FROM pv_acts_exibidos
),
comp_agg AS (
    SELECT
        COUNT(DISTINCT activity_id)::bigint                           AS comparecimentos_globais,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE email_norm <> ''
              AND email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                                   AS comparecimentos_leads_periodo_globais,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE email_norm = ''
               OR email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                                   AS comparecimentos_leads_historico_globais
    FROM pv_acts_comparecimentos
),
vendas_agg AS (
    SELECT
        COUNT(DISTINCT deal_id)::bigint                               AS vendas_globais,
        COUNT(DISTINCT deal_id) FILTER (
            WHERE email_norm <> ''
              AND email_norm IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                                   AS vendas_leads_periodo_globais,
        COUNT(DISTINCT deal_id) FILTER (
            WHERE email_norm = ''
               OR email_norm NOT IN (SELECT email_norm FROM aplicacoes_periodo_emails)
        )::bigint                                                   AS vendas_leads_historico_globais
    FROM pv_deals_vendas
)
SELECT *
FROM agend_agg
CROSS JOIN comp_agg
CROSS JOIN vendas_agg;
