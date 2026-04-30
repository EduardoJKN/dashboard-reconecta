-- =============================================================================
-- Resultado atribuído por DATA — agrega odam.mart_ad_funnel_daily para o
-- grão `data_ref` (sem distinção de campaign_id/ad_id). Consumida apenas
-- pela página Growth.
--
-- Diferenças vs mkt_campanha_resultados.sql / mkt_criativos_resultados.sql:
--   * Aqui o grão é diário e somamos TUDO (incluindo linhas com ad_id NULL),
--     porque a página Growth mostra a foto consolidada do funil — não estamos
--     atribuindo nada por campanha/anúncio aqui. Cobertura por ad_id
--     continua diagnosticada na página Criativos.
--   * Cobertura primária Meta — Google/Pinterest/Organico geralmente sem
--     linha aqui. Os números refletem o atribuído, não o universo total.
-- =============================================================================
SELECT
    data_ref,
    SUM(leads_atua_mais_12)::bigint  AS leads_mais_12,
    SUM(leads_atua_menos_12)::bigint AS leads_menos_12,
    SUM(leads_nao_atua)::bigint      AS leads_nao_atua,
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
GROUP BY data_ref
ORDER BY data_ref;
