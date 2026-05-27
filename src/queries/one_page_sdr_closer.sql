-- =============================================================================
-- One Page — Tabela "Por SDR × Closer" (cálculo direto, sem view legada).
-- =============================================================================
-- Substitui a leitura de `prevendas_sdr_closer.sql` para esta tabela específica
-- da One Page. Calcula direto a partir de:
--   - zoho_deals                          (vendas, montante, receita, chaves)
--   - zoho_activities                     (agendamentos, comparecimentos)
--   - fdw_reconecta.executivas_pre_vendas (cadastro oficial — nome SDR)
--   - fdw_reconecta.executivas_vendas     (cadastro oficial — nome Closer + ativo)
--   - zoho_users                          (fallback visual só no modo histórico)
--
-- Atribuição:
--   SDR     ← `zoho_deals.sdr_ss::text         = executivas_pre_vendas.id_crm::text`
--   Closer  ← `zoho_deals.executiva_vendas::text = executivas_vendas.id_crm::text`
-- Activities herdam o par do deal (via `what_id`).
--
-- Parâmetro :modo controla o universo do par:
--   - 'ativos' (padrão) → exige SDR cadastrada em executivas_pre_vendas
--                          E Closer cadastrada e ATIVA em executivas_vendas.
--                          IDs órfãos não aparecem.
--   - 'todas'           → inclui inativas + IDs sem cadastro. SDR sem
--                          cadastro tenta fallback em `zoho_users` e exibe
--                          'Nome (sem cadastro pré-vendas)'; se nem em
--                          zoho_users → 'SDR sem cadastro: <id>'. Closer
--                          sem cadastro → 'Closer sem cadastro: <id>'.
--
-- ⚠ executivas_pre_vendas NÃO tem coluna `ativo` (validado mai/2026). Por
-- isso o filtro de "ativos" para SDR é "presente no cadastro" e só vale
-- para Closer a comparação contra `ativo='y'`.
--
-- Métricas (líquidas, mesma regra das demais SQLs):
--   agendamentos   = COUNT(DISTINCT activity_id) WHERE
--                    activity_type IN ('Consulta','Indicação') AND
--                    status_reuniao IS NOT NULL AND
--                    status_reuniao <> 'Vencida' AND
--                    start_datetime::date IN [:data_ini, :data_fim]
--   comparecimentos = subset com status IN ('Concluída','Concluído')
--   vendas          = COUNT(DISTINCT deal_id) WHERE
--                    stage IN ('Ganho','Fechado Ganho') AND
--                    tipo_venda = 'Novo cliente' AND
--                    data_hora_compra::date IN [:data_ini, :data_fim]
--                    (alinhado ao card Novos da One Page)
--   montante/receita = SUM das vendas novas acima (mesma limpeza string→numeric).
--
-- Filtro de e-mails teste aplicado em `zoho_deals.email` — e-mail nulo NÃO
-- descarta (alinhado com one_page_por_executiva.sql).
--
-- Percentuais recalculados linha-a-linha:
--   pct_comparecimento = comparecimentos / agendamentos
--   pct_conversao      = vendas / agendamentos
--   pct_vendas         = vendas / comparecimentos
--   pct_recebimento    = receita / montante
-- =============================================================================
WITH deals_validos AS (
    -- 1 row por deal com filtro canônico de e-mails de teste.
    SELECT
        d.id::text                  AS deal_id,
        d.sdr_ss::text              AS sdr_id,
        d.executiva_vendas::text    AS closer_id,
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
    WHERE d.sdr_ss IS NOT NULL
      AND d.executiva_vendas IS NOT NULL
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
agend_por_par AS (
    SELECT
        dv.sdr_id,
        dv.closer_id,
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
    GROUP BY dv.sdr_id, dv.closer_id
),
vendas_por_par AS (
    SELECT
        dv.sdr_id,
        dv.closer_id,
        COUNT(DISTINCT dv.deal_id) AS vendas,
        SUM(dv.montante)::numeric  AS montante,
        SUM(dv.receita)::numeric   AS receita
    FROM deals_validos dv
    WHERE dv.stage IN ('Ganho','Fechado Ganho')
      AND dv.tipo_venda = 'Novo cliente'
      AND dv.data_venda_ref BETWEEN :data_ini AND :data_fim
    GROUP BY dv.sdr_id, dv.closer_id
),
pares_no_periodo AS (
    -- União dos pares com atividade ou venda. Só (sdr_id, closer_id) que
    -- aparecem em alguma das duas CTEs entram no universo do período.
    SELECT sdr_id, closer_id FROM agend_por_par
    UNION
    SELECT sdr_id, closer_id FROM vendas_por_par
),
-- ---------------------------------------------------------------------------
-- Resolução de nomes — três fontes em prioridade.
-- ---------------------------------------------------------------------------
sdr_resolved AS (
    SELECT
        pp.sdr_id,
        pv.nome                AS sdr_nome_oficial,
        TRIM(u.first_name || ' ' || COALESCE(u.last_name, '')) AS sdr_nome_zoho
    FROM pares_no_periodo pp
    LEFT JOIN fdw_reconecta.executivas_pre_vendas pv ON pp.sdr_id = pv.id_crm::text
    LEFT JOIN zoho_users u                            ON pp.sdr_id = u.id::text
    GROUP BY pp.sdr_id, pv.nome, TRIM(u.first_name || ' ' || COALESCE(u.last_name, ''))
),
closer_resolved AS (
    SELECT
        pp.closer_id,
        ev.nome  AS closer_nome,
        ev.ativo AS closer_ativo
    FROM pares_no_periodo pp
    LEFT JOIN fdw_reconecta.executivas_vendas ev ON pp.closer_id = ev.id_crm::text
    GROUP BY pp.closer_id, ev.nome, ev.ativo
)
SELECT
    -- Nome SDR resolvido conforme :modo.
    CASE
        WHEN sr.sdr_nome_oficial IS NOT NULL
            THEN sr.sdr_nome_oficial
        WHEN :modo = 'todas' AND sr.sdr_nome_zoho IS NOT NULL
             AND btrim(sr.sdr_nome_zoho) <> ''
            THEN sr.sdr_nome_zoho || ' (sem cadastro pré-vendas)'
        WHEN :modo = 'todas'
            THEN 'SDR sem cadastro: ' || pp.sdr_id
        ELSE NULL
    END AS sdr,
    -- Nome Closer resolvido conforme :modo.
    CASE
        WHEN cr.closer_nome IS NOT NULL
            THEN cr.closer_nome
        WHEN :modo = 'todas'
            THEN 'Closer sem cadastro: ' || pp.closer_id
        ELSE NULL
    END                                       AS closer,
    cr.closer_ativo                           AS closer_ativo,
    (sr.sdr_nome_oficial IS NULL)             AS sdr_sem_cadastro_oficial,
    (cr.closer_nome      IS NULL)             AS closer_sem_cadastro_oficial,
    COALESCE(a.agendamentos,    0)::bigint    AS agendamentos,
    COALESCE(a.comparecimentos, 0)::bigint    AS comparecimentos,
    COALESCE(v.vendas,          0)::bigint    AS vendas,
    COALESCE(v.montante,        0)::numeric   AS montante,
    COALESCE(v.receita,         0)::numeric   AS receita,
    CASE WHEN COALESCE(a.agendamentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.comparecimentos, 0)::numeric / a.agendamentos * 100
    END                                       AS pct_comparecimento,
    CASE WHEN COALESCE(a.agendamentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(v.vendas, 0)::numeric / a.agendamentos * 100
    END                                       AS pct_conversao,
    CASE WHEN COALESCE(a.comparecimentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(v.vendas, 0)::numeric / a.comparecimentos * 100
    END                                       AS pct_vendas,
    CASE WHEN COALESCE(v.montante, 0) = 0 THEN 0::numeric
         ELSE COALESCE(v.receita, 0)::numeric / v.montante * 100
    END                                       AS pct_recebimento
FROM pares_no_periodo pp
LEFT JOIN sdr_resolved    sr ON sr.sdr_id    = pp.sdr_id
LEFT JOIN closer_resolved cr ON cr.closer_id = pp.closer_id
LEFT JOIN agend_por_par   a  ON a.sdr_id     = pp.sdr_id AND a.closer_id = pp.closer_id
LEFT JOIN vendas_por_par  v  ON v.sdr_id     = pp.sdr_id AND v.closer_id = pp.closer_id
WHERE
    -- Modo 'ativos': SDR cadastrada + Closer cadastrada e ativa.
    -- Modo 'todas':  qualquer par com atividade no período (inclui órfãos).
    (
        :modo = 'ativos'
        AND sr.sdr_nome_oficial IS NOT NULL
        AND cr.closer_nome      IS NOT NULL
        AND cr.closer_ativo     = 'y'
    )
    OR :modo = 'todas'
ORDER BY agendamentos DESC, vendas DESC, sdr, closer;
