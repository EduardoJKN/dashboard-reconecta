-- =============================================================================
-- Executivas — Funil v2 (agregado diário, colunas mínimas).
-- =============================================================================
-- Equivalente a `dashboard_executivas.sql` + `visao_geral_kpis` para o Funil.
-- Fonte: `bi.vw_dashboard_comercial_executivas_rw` (mesma view da v1).
-- Agrega por `data_ref` — reduz linhas transferidas (executiva × dia → dia).
-- Não aplica `executivas_aplicar_time_vendas_overrides` (só altera time_vendas).
-- =============================================================================
SELECT
    data_ref,
    SUM(vendas)::bigint                              AS vendas,
    SUM(montante)::numeric                           AS montante,
    SUM(receita)::numeric                            AS receita,
    SUM(COALESCE(perdidos, 0))::bigint               AS perdidos,
    SUM(COALESCE(cancelados, 0))::bigint             AS cancelados,
    SUM(COALESCE(oportunidades, 0))::bigint          AS oportunidades,
    SUM(COALESCE(novos, 0))::bigint                  AS novos,
    SUM(COALESCE(ascensoes, 0))::bigint              AS ascensoes,
    SUM(COALESCE(renovacoes, 0))::bigint             AS renovacoes,
    SUM(COALESCE(indicacoes, 0))::bigint             AS indicacoes
FROM bi.vw_dashboard_comercial_executivas_rw
WHERE data_ref BETWEEN :data_ini AND :data_fim
GROUP BY data_ref
ORDER BY data_ref;
