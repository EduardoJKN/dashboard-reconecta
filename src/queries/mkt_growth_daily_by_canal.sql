-- =============================================================================
-- Resultado atribuído por DATA × CANAL — agrega odam.mart_ad_funnel_daily
-- com canal derivado por JOIN com bi.vw_mkt_campanhas (campaign_id → canal).
-- Consumida apenas pela página Growth quando o usuário aplica filtro de canal.
--
-- Cobertura do JOIN no período típico: ~94% das linhas da mart casam com
-- campaign_id em vw_mkt_campanhas. As ~6% sem campaign_id (`canal IS NULL`
-- aqui) entram apenas no agregado "todos canais"; não aparecem ao filtrar
-- canais específicos.
--
-- Diferença vs mkt_growth_daily.sql:
--   * mkt_growth_daily.sql       → grão `data_ref` (sem canal)  → "todos"
--   * mkt_growth_daily_by_canal.sql → grão `data_ref × canal`   → filtrável
--
-- Mantemos os dois arquivos para escolher fonte conforme uso no app:
--   - filtro = todos canais  → mkt_growth_daily.sql        (inclui canal NULL)
--   - filtro = subset canais → mkt_growth_daily_by_canal.sql + filtro Python
-- =============================================================================
SELECT
    m.data_ref,
    cmp.canal,
    SUM(m.leads_atua_mais_12)::bigint  AS leads_mais_12,
    SUM(m.leads_atua_menos_12)::bigint AS leads_menos_12,
    SUM(m.leads_nao_atua)::bigint      AS leads_nao_atua,
    SUM(m.agendamentos)::bigint        AS agendamentos,
    SUM(m.comparecimentos)::bigint     AS comparecimentos,
    SUM(m.no_shows)::bigint            AS no_shows,
    SUM(m.deals)::bigint               AS deals,
    SUM(m.deals_ganhos)::bigint        AS deals_ganhos,
    SUM(m.vendas)::bigint              AS vendas,
    SUM(m.valor_venda)::numeric        AS valor_venda,
    SUM(m.valor_receita)::numeric      AS valor_receita
FROM odam.mart_ad_funnel_daily m
LEFT JOIN (
    SELECT DISTINCT campaign_id, canal
      FROM bi.vw_mkt_campanhas
     WHERE campaign_id IS NOT NULL
) cmp ON cmp.campaign_id = m.campaign_id
WHERE m.data_ref BETWEEN :data_ini AND :data_fim
GROUP BY m.data_ref, cmp.canal
ORDER BY m.data_ref, cmp.canal NULLS LAST;
