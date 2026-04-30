-- =============================================================================
-- Resultados atribuídos por ANÚNCIO (ad_id) — agrega odam.mart_ad_funnel_daily
-- para o grão `ad_id` no período. Usado pela página Criativos para:
--   * cards gerais (somando todos ad_ids)
--   * Top 12 enriched (merge por ad_id)
--   * ranking dinâmico (sort por leads/vendas/CPL/CAC/ROAS)
--   * funil individual (filter por ad_id, na Fase 2)
--
-- Importante (mesmas regras da V1.5 de campanhas):
--   * NÃO usar `spend`/`valor_venda` daqui como invest oficial — invest
--     oficial vem de `bi.vw_mkt_criativos` (página já consome).
--   * Linhas com ad_id NULL ficam fora (não distribuímos resultado sem
--     chave clara). Cobertura é diagnosticada em mkt_criativos_cobertura.sql.
-- =============================================================================
SELECT
    ad_id,
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
  AND ad_id IS NOT NULL
GROUP BY ad_id;
