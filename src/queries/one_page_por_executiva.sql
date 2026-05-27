-- =============================================================================
-- One Page — Tabela "Por Executiva" (cálculo direto, sem view legada).
-- =============================================================================
-- Substitui a leitura de `bi.vw_dashboard_comercial_executivas_rw` para esta
-- tabela específica. Calcula direto a partir de:
--   - zoho_deals                        (vendas, montante, receita)
--   - zoho_activities                   (agendamentos, comparecimentos)
--   - fdw_reconecta.executivas_vendas   (cadastro oficial — nome + ativo)
--
-- Atribuição da executiva: `zoho_deals.executiva_vendas::text = ev.id_crm::text`.
--
-- Parâmetro :modo controla o universo de executivas mostradas:
--   - 'ativas'  → padrão, só `ev.ativo = 'y'` com match no cadastro.
--   - 'todas'   → ativas + inativas + IDs sem cadastro (rotulados como
--                 'ID sem cadastro: <id_zoho>' para auditoria histórica).
--
-- Métricas (todas líquidas e por deal/activity distinct):
--   - agendamentos  : COUNT(DISTINCT activity_id) WHERE
--                     activity_type IN ('Consulta','Indicação')
--                     AND status_reuniao IS NOT NULL
--                     AND status_reuniao <> 'Vencida'
--                     AND start_datetime::date IN [:data_ini, :data_fim]
--   - comparecimentos : subset com status IN ('Concluída','Concluído')
--   - vendas        : COUNT(DISTINCT deal_id) WHERE
--                     stage IN ('Ganho','Fechado Ganho')
--                     AND data_hora_compra::date IN [:data_ini, :data_fim]
--   - montante / receita : SUM com limpeza canônica de string -> numeric.
--
-- Filtro de e-mails teste aplicado em `zoho_deals.email` (acompanha o deal
-- tanto para agendamentos/comparecimentos — via JOIN do deal — quanto para
-- vendas). E-mail nulo no deal NÃO descarta (mesma política das outras SQLs).
--
-- Percentuais recalculados na própria SQL (linha-a-linha):
--   pct_recebimento     = receita / montante
--   pct_conversao       = vendas / agendamentos
--   pct_vendas          = vendas / comparecimentos
--   pct_comparecimento  = comparecimentos / agendamentos
-- =============================================================================
WITH deals_validos AS (
    -- Universo base de deals com filtro canônico de e-mails de teste.
    -- Aplicado uma vez para reuso em activities (via JOIN) e em vendas.
    SELECT
        d.id::text                  AS deal_id,
        d.executiva_vendas::text    AS id_crm,
        d.stage,
        d.tipo_venda,
        d.data_hora_compra::date    AS data_venda_ref,
        CASE
            WHEN NULLIF(btrim(d.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END                         AS montante,
        CASE
            WHEN NULLIF(btrim(d.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END                         AS receita
    FROM zoho_deals d
    WHERE d.executiva_vendas IS NOT NULL
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
agend_por_executiva AS (
    SELECT
        dv.id_crm,
        COUNT(DISTINCT za.id) FILTER (
            WHERE za.status_reuniao <> 'Vencida'
        )                                                       AS agendamentos,
        COUNT(DISTINCT za.id) FILTER (
            WHERE za.status_reuniao IN ('Concluída','Concluído')
        )                                                       AS comparecimentos
    FROM zoho_activities za
    JOIN deals_validos dv ON dv.deal_id = za.what_id::text
    WHERE za.activity_type IN ('Consulta','Indicação')
      AND za.status_reuniao IS NOT NULL
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
    GROUP BY dv.id_crm
),
vendas_por_executiva AS (
    SELECT
        dv.id_crm,
        COUNT(DISTINCT dv.deal_id) AS vendas,
        SUM(dv.montante)::numeric  AS montante,
        SUM(dv.receita)::numeric   AS receita
    FROM deals_validos dv
    WHERE dv.stage IN ('Ganho','Fechado Ganho')
      AND dv.data_venda_ref BETWEEN :data_ini AND :data_fim
    GROUP BY dv.id_crm
),
-- Universo de id_crm que tiveram qualquer atividade no período. Usado no
-- modo 'todas' para detectar IDs em zoho_deals que NÃO têm cadastro.
ids_no_periodo AS (
    SELECT id_crm FROM agend_por_executiva
    UNION
    SELECT id_crm FROM vendas_por_executiva
),
linhas_cadastro AS (
    -- Linhas vindas do cadastro oficial — sempre carregam o nome.
    SELECT
        ev.id_crm::text                  AS id_crm,
        ev.nome                          AS executiva,
        ev.ativo                         AS ativo,
        FALSE                            AS sem_cadastro
    FROM fdw_reconecta.executivas_vendas ev
    WHERE ev.id_crm IS NOT NULL
      AND btrim(ev.id_crm) <> ''
),
linhas_sem_cadastro AS (
    -- IDs detectados no período que NÃO existem no cadastro oficial.
    -- Só importam no modo 'todas'; no modo 'ativas' são descartados.
    SELECT
        ip.id_crm,
        'ID sem cadastro: ' || ip.id_crm AS executiva,
        NULL::character                  AS ativo,
        TRUE                             AS sem_cadastro
    FROM ids_no_periodo ip
    LEFT JOIN linhas_cadastro lc ON lc.id_crm = ip.id_crm
    WHERE lc.id_crm IS NULL
),
linhas_universo AS (
    -- Universo final filtrado pelo :modo.
    --   'ativas' → só cadastro com ativo='y' (sem orfãos).
    --   'todas'  → cadastro (qualquer ativo) + orfãos.
    SELECT id_crm, executiva, ativo, sem_cadastro
    FROM linhas_cadastro
    WHERE :modo = 'ativas' AND ativo = 'y'
    UNION ALL
    SELECT id_crm, executiva, ativo, sem_cadastro
    FROM linhas_cadastro
    WHERE :modo = 'todas'
    UNION ALL
    SELECT id_crm, executiva, ativo, sem_cadastro
    FROM linhas_sem_cadastro
    WHERE :modo = 'todas'
)
SELECT
    lu.executiva,
    lu.ativo,
    lu.sem_cadastro,
    COALESCE(a.agendamentos,    0)::bigint  AS agendamentos,
    COALESCE(a.comparecimentos, 0)::bigint  AS comparecimentos,
    COALESCE(v.vendas,          0)::bigint  AS vendas,
    COALESCE(v.montante,        0)::numeric AS montante,
    COALESCE(v.receita,         0)::numeric AS receita,
    CASE WHEN COALESCE(v.montante, 0) = 0 THEN 0::numeric
         ELSE COALESCE(v.receita, 0)::numeric / v.montante * 100
    END                                     AS pct_recebimento,
    CASE WHEN COALESCE(a.agendamentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(v.vendas, 0)::numeric / a.agendamentos * 100
    END                                     AS pct_conversao,
    CASE WHEN COALESCE(a.comparecimentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(v.vendas, 0)::numeric / a.comparecimentos * 100
    END                                     AS pct_vendas,
    CASE WHEN COALESCE(a.agendamentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.comparecimentos, 0)::numeric / a.agendamentos * 100
    END                                     AS pct_comparecimento
FROM linhas_universo lu
LEFT JOIN agend_por_executiva  a ON a.id_crm = lu.id_crm
LEFT JOIN vendas_por_executiva v ON v.id_crm = lu.id_crm
ORDER BY COALESCE(v.receita, 0) DESC, lu.executiva;
