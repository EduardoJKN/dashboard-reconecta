-- =============================================================================
-- Funil de Marketing consumido pelas páginas Funil e Campanhas.
--
-- Lê de bi.mv_mkt_funil (MATERIALIZED VIEW) por performance — a fonte
-- lógica continua sendo bi.vw_mkt_funil, mas o app consome a MV.
-- A view original passou a custar ~95s no EXPLAIN ANALYZE; a MV resolveu
-- o gargalo com índices em (data_ref), (canal) e (data_ref, canal).
--
-- ⚠ A materialized view precisa ser atualizada periodicamente:
--     REFRESH MATERIALIZED VIEW bi.mv_mkt_funil;
--
--   (Recomendado rodar via cron/scheduler na frequência que o time de dados
--   considerar adequada — ex.: a cada 1h ou diariamente após o load do FDW.
--   Sem o REFRESH, o dashboard mostra dados estagnados.)
-- =============================================================================
SELECT
    data_ref,
    canal,
    investimento,
    impressoes,
    cliques,
    leads,
    leads_qualif_mais_12,
    leads_qualif_menos_12,
    deals,
    deals_ganhos,
    vendas,
    valor_venda,
    valor_receita
FROM bi.mv_mkt_funil
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref, canal;
