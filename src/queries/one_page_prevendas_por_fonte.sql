-- =============================================================================
-- One Page — Pré-vendas por FONTE (regra `origem_final` do Looker legado).
-- =============================================================================
-- 1 row por (data_ref, fonte). Substitui a quebra INBOUND/SS via `tipo_sdr`
-- (que vinha de team_classification.py) pela regra oficial do Looker, que
-- olha `zoho_deals.fonte_de_lead`:
--
--   - 'Fábrica de Contatos'           → 'Fábrica'   (SS no One Page)
--   - 'Outbound', 'Prospecção'        → 'Outbound'
--   - 'Reagendamento', 'Follow-up'    → desambigua por `sdr_ss` (Fábrica
--                                       vs Outbound vs Inbound). Sem as
--                                       IDs reais hoje, fallback = 'Inbound'.
--                                       TODO: receber as IDs reais e
--                                       acrescentar a CASE secundária.
--   - qualquer outro / NULL           → 'Inbound'
--
-- Activities: `activity_type IN ('Consulta','Indicação')` AND
-- `status_reuniao IS NOT NULL`. Filtro alinhado com
-- `prevendas_overview_diario.sql` e `prevendas_por_sdr.sql`.
--
-- Agendamentos LÍQUIDOS (sem `Vencida`); vencidas ficam separadas em
-- `agendamentos_vencidos`. Comparecimentos = `Concluída`/`Concluído`.
-- Mesma regra +12/-12 COMBINADA (lead_classification OR qualificacao OR
-- classificado_cal OR ext.classificado).
--
-- "ate_hoje": subset que tem `start_datetime::date <= CURRENT_DATE` —
-- exclui reuniões futuras do denominador de % comparecimento.
--
-- Activities sem deal pareado caem em 'Inbound' (else final) — evita
-- perder linhas no grão.
-- =============================================================================
WITH
-- ---------------------------------------------------------------------------
-- 1) Resolve fonte/origem_final por deal (regra Looker)
-- ---------------------------------------------------------------------------
deals_clean AS (
    SELECT
        d.id                                  AS deal_id,
        d.sdr_ss,
        d.amount                              AS amount_raw,
        d.receita                             AS receita_raw,
        d.stage,
        d.tipo_venda,
        d.data_hora_compra::date              AS data_venda_ref,
        d.lead_classification,
        d.qualificacao,
        d.classificado_cal,
        CASE
            WHEN d.fonte_de_lead = 'Fábrica de Contatos'         THEN 'Fábrica'
            WHEN d.fonte_de_lead IN ('Outbound', 'Prospecção')   THEN 'Outbound'
            -- TODO Looker legacy: desambiguar Reagendamento/Follow-up via
            -- `d.sdr_ss::text IN ('<ID_SDR_FABRICA>')` → 'Fábrica' e
            -- `d.sdr_ss::text IN ('<ID_SDR_OUTBOUND>')` → 'Outbound'.
            -- Sem as IDs reais cadastradas, esses 2 buckets caem no
            -- default 'Inbound' (190 deals nos últimos 90 dias).
            ELSE 'Inbound'
        END                                    AS fonte
    FROM zoho_deals d
),
-- ---------------------------------------------------------------------------
-- 2) Classificação +12/-12 via ext_reconecta.leads (BOOL_OR por deal).
--    Mesma regra de `prevendas_overview_diario.sql:147-157`.
-- ---------------------------------------------------------------------------
leads_classif AS (
    SELECT
        d.deal_id,
        BOOL_OR(l.classificado = 'Atua +12') AS tem_ext_mais_12,
        BOOL_OR(l.classificado = 'Atua -12') AS tem_ext_menos_12
    FROM deals_clean d
    LEFT JOIN ext_reconecta.leads l
           ON d.deal_id::text = l.zoho_id::text
          AND l.email IS NOT NULL
          AND btrim(l.email) <> ''
          AND lower(l.email) NOT LIKE '%@teste%'
          AND lower(l.email) NOT LIKE 'teste@%'
          AND lower(l.email) NOT LIKE '%smarts%'
          AND lower(l.email) NOT LIKE '%reconecta%'
    GROUP BY d.deal_id
),
deal_flags AS (
    SELECT
        d.deal_id,
        d.fonte,
        d.data_venda_ref,
        d.stage,
        d.tipo_venda,
        d.amount_raw,
        d.receita_raw,
        (
            d.lead_classification = 'Atua +12'
            OR d.qualificacao    = 'Atua +12'
            OR d.classificado_cal = 'Atua +12'
            OR COALESCE(lc.tem_ext_mais_12, FALSE)
        ) AS tem_mais_12,
        (
            d.lead_classification = 'Atua -12'
            OR d.qualificacao    = 'Atua -12'
            OR d.classificado_cal = 'Atua -12'
            OR COALESCE(lc.tem_ext_menos_12, FALSE)
        ) AS tem_menos_12
    FROM deals_clean d
    LEFT JOIN leads_classif lc USING (deal_id)
),
-- ---------------------------------------------------------------------------
-- 3) Atividades base — `Consulta`/`Indicação` com status preenchido.
-- ---------------------------------------------------------------------------
acts AS (
    SELECT
        a.id                            AS activity_id,
        a.what_id                       AS deal_id,
        a.start_datetime::date          AS data_reuniao,
        a.created_time::date            AS data_criacao,
        a.status_reuniao
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
),
acts_reuniao AS (
    -- Activities cuja reunião está no período (eixo principal das métricas).
    -- INNER JOIN com `deal_flags`: descarta activities sem deal pareado
    -- (what_id NULL ou apontando para deal inexistente). Esse é o mesmo
    -- recorte que `prevendas_overview_diario.sql` faz (INNER JOIN com
    -- base_dados via what_id), garantindo que a soma INBOUND + Fábrica +
    -- Outbound bata com o card consolidado de "Agendamentos" da One
    -- Page. Em abr/2026 isso descarta 39 activities órfãs (~7%).
    SELECT
        a.activity_id,
        a.deal_id,
        a.data_reuniao,
        a.status_reuniao,
        df.fonte,
        df.tem_mais_12,
        df.tem_menos_12
    FROM acts a
    JOIN deal_flags df ON df.deal_id = a.deal_id
    WHERE a.data_reuniao BETWEEN :data_ini AND :data_fim
),
acts_criacao AS (
    -- Activities criadas no período (alimenta `agendamentos_criados`).
    -- Mesma regra de INNER JOIN — órfãs ficam de fora.
    SELECT
        a.activity_id,
        a.data_criacao,
        df.fonte
    FROM acts a
    JOIN deal_flags df ON df.deal_id = a.deal_id
    WHERE a.data_criacao BETWEEN :data_ini AND :data_fim
),
-- ---------------------------------------------------------------------------
-- 4) Agregados por (data_ref, fonte)
-- ---------------------------------------------------------------------------
ag_dia AS (
    SELECT
        data_reuniao                                                   AS data_ref,
        fonte,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao <> 'Vencida'
        )::bigint                                                       AS agendamentos,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao = 'Vencida'
        )::bigint                                                       AS agendamentos_vencidos,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao <> 'Vencida' AND tem_mais_12
        )::bigint                                                       AS agendamentos_mais_12,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao <> 'Vencida' AND tem_menos_12
        )::bigint                                                       AS agendamentos_menos_12,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao <> 'Vencida'
              AND data_reuniao <= CURRENT_DATE
        )::bigint                                                       AS agendamentos_ate_hoje,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao <> 'Vencida'
              AND data_reuniao <= CURRENT_DATE
              AND tem_mais_12
        )::bigint                                                       AS agendamentos_mais_12_ate_hoje,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao <> 'Vencida'
              AND data_reuniao <= CURRENT_DATE
              AND tem_menos_12
        )::bigint                                                       AS agendamentos_menos_12_ate_hoje,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao IN ('Concluída', 'Concluído')
        )::bigint                                                       AS comparecimentos,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao IN ('Concluída', 'Concluído')
              AND data_reuniao <= CURRENT_DATE
        )::bigint                                                       AS comparecimentos_ate_hoje
    FROM acts_reuniao
    GROUP BY data_reuniao, fonte
),
criacao_dia AS (
    SELECT
        data_criacao                                                   AS data_ref,
        fonte,
        COUNT(DISTINCT activity_id)::bigint                            AS agendamentos_criados
    FROM acts_criacao
    GROUP BY data_criacao, fonte
),
-- "Oportunidades" sem fonte canônica no Looker — proxy MVP: deals
-- distintos com pelo menos uma activity (de Consulta/Indicação) no
-- período. Cobre o sentido prático do Looker ("deal entrou no funil de
-- Pré-vendas pela data da reunião marcada"). Se a operação tiver outra
-- definição (ex.: deal criado no período por created_time), trocar a CTE.
oport_dia AS (
    SELECT
        data_reuniao                                                   AS data_ref,
        fonte,
        COUNT(DISTINCT deal_id)::bigint                                AS oportunidades
    FROM acts_reuniao
    WHERE deal_id IS NOT NULL
    GROUP BY data_reuniao, fonte
),
deals_dia AS (
    -- Vendas/montante/receita por (data_venda_ref, fonte). Mantém
    -- regra de Vendas: stage IN ('Ganho','Fechado Ganho') AND tipo_venda
    -- = 'Novo cliente'. Limpeza de amount/receita igual às outras SQLs.
    SELECT
        data_venda_ref                                                 AS data_ref,
        fonte,
        COUNT(DISTINCT deal_id)::bigint                                AS vendas,
        SUM(
            CASE WHEN amount_raw IS NULL
                   OR btrim(amount_raw::text) = '' THEN 0::numeric
                 ELSE REPLACE(
                          REPLACE(
                              REGEXP_REPLACE(TRIM(amount_raw::text),
                                             '[^0-9,.-]', '', 'g'),
                              '.', ''),
                          ',', '.'
                      )::numeric
            END
        )::numeric                                                      AS montante,
        SUM(
            CASE WHEN receita_raw IS NULL
                   OR btrim(receita_raw::text) = '' THEN 0::numeric
                 ELSE REPLACE(
                          REPLACE(
                              REGEXP_REPLACE(TRIM(receita_raw::text),
                                             '[^0-9,.-]', '', 'g'),
                              '.', ''),
                          ',', '.'
                      )::numeric
            END
        )::numeric                                                      AS receita
    FROM deal_flags
    WHERE stage IN ('Ganho', 'Fechado Ganho')
      AND tipo_venda = 'Novo cliente'
      AND data_venda_ref BETWEEN :data_ini AND :data_fim
    GROUP BY data_venda_ref, fonte
),
keys AS (
    SELECT data_ref, fonte FROM ag_dia
    UNION SELECT data_ref, fonte FROM criacao_dia
    UNION SELECT data_ref, fonte FROM oport_dia
    UNION SELECT data_ref, fonte FROM deals_dia
)
SELECT
    k.data_ref,
    k.fonte,
    COALESCE(o.oportunidades, 0)::bigint                              AS oportunidades,
    COALESCE(c.agendamentos_criados, 0)::bigint                       AS agendamentos_criados,
    COALESCE(a.agendamentos, 0)::bigint                               AS agendamentos,
    COALESCE(a.agendamentos_vencidos, 0)::bigint                      AS agendamentos_vencidos,
    COALESCE(a.agendamentos_mais_12, 0)::bigint                       AS agendamentos_mais_12,
    COALESCE(a.agendamentos_menos_12, 0)::bigint                      AS agendamentos_menos_12,
    COALESCE(a.agendamentos_ate_hoje, 0)::bigint                      AS agendamentos_ate_hoje,
    COALESCE(a.agendamentos_mais_12_ate_hoje, 0)::bigint              AS agendamentos_mais_12_ate_hoje,
    COALESCE(a.agendamentos_menos_12_ate_hoje, 0)::bigint             AS agendamentos_menos_12_ate_hoje,
    CASE WHEN COALESCE(a.agendamentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.agendamentos_mais_12, 0)::numeric
              / a.agendamentos * 100
    END                                                                AS perc_agendamentos_mais_12,
    COALESCE(a.comparecimentos, 0)::bigint                            AS comparecimentos,
    COALESCE(a.comparecimentos_ate_hoje, 0)::bigint                   AS comparecimentos_ate_hoje,
    CASE WHEN COALESCE(a.agendamentos, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.comparecimentos, 0)::numeric
              / a.agendamentos * 100
    END                                                                AS perc_comparecimento,
    CASE WHEN COALESCE(a.agendamentos_ate_hoje, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.comparecimentos_ate_hoje, 0)::numeric
              / a.agendamentos_ate_hoje * 100
    END                                                                AS perc_comparecimento_ate_hoje,
    COALESCE(d.vendas, 0)::bigint                                     AS vendas,
    COALESCE(d.montante, 0)::numeric                                  AS montante,
    COALESCE(d.receita, 0)::numeric                                   AS receita
FROM keys k
LEFT JOIN ag_dia      a USING (data_ref, fonte)
LEFT JOIN criacao_dia c USING (data_ref, fonte)
LEFT JOIN oport_dia   o USING (data_ref, fonte)
LEFT JOIN deals_dia   d USING (data_ref, fonte)
ORDER BY k.data_ref, k.fonte;
