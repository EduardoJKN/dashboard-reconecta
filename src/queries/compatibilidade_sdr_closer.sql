-- =============================================================================
-- SDR × Closer — fonte direta zoho_deals + zoho_users (sem view bi.vw_*).
-- =============================================================================
-- Substitui a leitura de `bi.vw_compatibilidade_sdr_closer`, que tinha 5
-- desvios em relação à regra oficial validada para Vendas novas:
--   1. Filtrava `executiva_vendas IS NOT NULL AND (sdr_ss OR prevendas) IS NOT
--      NULL` no banco — excluía deals que deveriam aparecer como "Sem SDR" /
--      "Sem Closer". Causa principal das 10 vendas faltando no mês atual.
--   2. Considerava apenas `stage = 'Ganho'` — fora `'Fechado Ganho'`.
--   3. Agrupava por `mes_ref = date_trunc('month', d.created_at)` (data do
--      lead) e a página filtrava por esse mes_ref → não pegava ganhos cuja
--      venda fechou no mês mas o lead veio antes.
--   4. Não filtrava `tipo_venda = 'Novo cliente'`.
--   5. Rotulava nulos como `SEM_SDR` / `SEM_CLOSER` em vez de `Sem SDR` /
--      `Sem Closer`.
--
-- Regra oficial alinhada com Visão Geral / Funil Marketing / ROAS-CAC:
--   - Janela:    `data_hora_compra::date BETWEEN :data_ini AND :data_fim`
--   - Stage:     `stage IN ('Ganho','Fechado Ganho')`
--   - Tipo:      `tipo_venda = 'Novo cliente'`  (caminho de aquisição)
--   - SDR:       `zoho_deals.sdr_ss` → `zoho_users` (sem fallback de
--                  zoho_activities; sdr_ss nulo ⇒ "Sem SDR")
--   - Closer:    `zoho_deals.executiva_vendas` → `zoho_users`
--                  (executiva_vendas nula ⇒ "Sem Closer")
--
-- Shape preservado para os transforms (annotate_and_clean_sdr_closer,
-- sdr_closer_totais, sdr_closer_matriz, sdr_ranking, closer_ranking) — 12
-- colunas iguais às da view antiga. Diferenças semânticas:
--   - `mes_ref` agora é `date_trunc('month', data_hora_compra)` (data da
--     venda, alinhada com Visão Geral).
--   - `leads_recebidos = ganhos` é um valor PROVISÓRIO. Como esta página
--     opera sobre vendas fechadas, "leads recebidos" perde semântica até
--     que a página seja replanejada. Mantido com esse valor para preservar
--     o layout atual sem mexer nos transforms; revisão de UX pendente.
--   - `taxa_conversao = 100%` por construção (mesmo motivo do item acima).
--   - `tipo_sdr` / `time_closer` saem como categoria provisória 'Não
--     classificado'; o transform `annotate_and_clean_sdr_closer` sobrescreve
--     com a classificação canônica de `team_classification.py`.
-- =============================================================================
WITH base AS (
    SELECT
        d.id                                                  AS deal_id,
        d.data_hora_compra::date                              AS data_ganho,
        d.created_at::date                                    AS data_lead,
        COALESCE(
            NULLIF(TRIM(sdr.first_name || ' ' || sdr.last_name), ''),
            'Sem SDR'
        )                                                     AS sdr,
        COALESCE(
            NULLIF(TRIM(closer.first_name || ' ' || closer.last_name), ''),
            'Sem Closer'
        )                                                     AS closer,
        CASE
            WHEN NULLIF(TRIM(d.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END                                                   AS montante,
        CASE
            WHEN NULLIF(TRIM(d.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END                                                   AS receita
    FROM zoho_deals d
    LEFT JOIN zoho_users closer
           ON closer.id::text = d.executiva_vendas::text
    LEFT JOIN zoho_users sdr
           ON sdr.id::text = d.sdr_ss::text
    WHERE d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
      AND d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
)
SELECT
    sdr,
    closer,
    DATE_TRUNC('month', data_ganho)::date                     AS mes_ref,
    -- "Leads recebidos" provisório = ganhos. Esta página agora opera só
    -- sobre vendas fechadas; o card de leads/taxa fica com semântica
    -- redundante até futura revisão de UX. Mantido pra preservar o shape
    -- consumido por sdr_closer_totais / sdr_ranking / closer_ranking.
    COUNT(DISTINCT deal_id)                                   AS leads_recebidos,
    COUNT(DISTINCT deal_id)                                   AS ganhos,
    100.00::numeric                                           AS taxa_conversao,
    SUM(receita)                                              AS receita_total,
    SUM(montante)                                             AS montante_total,
    ROUND(SUM(montante) / NULLIF(COUNT(DISTINCT deal_id), 0)::numeric, 2)
                                                              AS ticket_medio,
    ROUND(AVG(GREATEST(data_ganho - data_lead, 0))::numeric, 2)
                                                              AS dias_ate_fechamento,
    -- tipo_sdr / time_closer saem provisórios; annotate_and_clean_sdr_closer
    -- sobrescreve com a classificação canônica de team_classification.py.
    'Não classificado'::text                                  AS tipo_sdr,
    'Não classificado'::text                                  AS time_closer
FROM base
GROUP BY sdr, closer, DATE_TRUNC('month', data_ganho)::date
ORDER BY ganhos DESC, sdr, closer;
