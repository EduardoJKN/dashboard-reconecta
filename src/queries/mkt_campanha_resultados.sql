-- =============================================================================
-- Resultados atribuídos por CAMPANHA — agrega odam.mart_ad_funnel_daily
-- (grão ad_id × data_ref) para o grão `campaign_id` no período.
--
-- Usado APENAS pela seção "Comparar campanhas" da página Campanhas (V1.5).
--
-- Importante:
--   * NÃO usar `valor_venda` daqui como invest oficial — invest oficial vem
--     de bi.vw_mkt_campanhas. Aqui pegamos só métricas de FUNIL/RESULTADO.
--   * Cobertura é Meta-only (mart hoje só popula Meta). Campanhas sem linha
--     aqui são tratadas como "sem atribuição" no app.
--   * Merge na app é por `campaign_id` direto — sem JOIN com fdw_reconecta.
--   * `no_shows` vem direto da coluna do mart (não calcular como
--     agendamentos − comparecimentos, regra confirmada com o time).
-- =============================================================================
SELECT
    campaign_id,
    SUM(leads_atua_mais_12)::bigint  AS leads_mais_12,
    SUM(leads_atua_menos_12)::bigint AS leads_menos_12,
    SUM(leads_nao_atua)::bigint      AS leads_nao_atua,
    SUM(leads_atua_mais_12 + leads_atua_menos_12 + leads_nao_atua)::bigint
                                     AS leads_total,
    SUM(agendamentos)::bigint        AS agendamentos,
    SUM(comparecimentos)::bigint     AS comparecimentos,
    SUM(no_shows)::bigint            AS no_shows,
    SUM(deals)::bigint               AS deals,
    SUM(deals_ganhos)::bigint        AS deals_ganhos,
    SUM(vendas)::bigint              AS vendas,
    SUM(valor_venda)::numeric        AS valor_venda,
    SUM(valor_receita)::numeric      AS valor_receita
FROM odam.mart_ad_funnel_daily
WHERE data_ref BETWEEN :data_ini AND :data_fim
  AND campaign_id IS NOT NULL
GROUP BY campaign_id;
