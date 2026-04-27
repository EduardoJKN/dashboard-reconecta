-- =============================================================================
-- ROAS / CAC consumido pela página Visão Geral Marketing.
--
-- Lê de bi.mv_mkt_roas (MATERIALIZED VIEW) por performance — a fonte
-- lógica continua sendo bi.vw_mkt_roas, mas o app consome a MV.
--
-- ⚠ A materialized view precisa ser atualizada periodicamente:
--     REFRESH MATERIALIZED VIEW bi.mv_mkt_roas;
--
--   (Recomendado rodar via cron/scheduler na frequência que o time de dados
--   considerar adequada — ex.: a cada 1h ou diariamente após o load
--   noturno do FDW. Sem o REFRESH, o dashboard mostra dados estagnados.)
-- =============================================================================
SELECT
    data_ref,
    canal,
    investimento,
    leads,
    leads_qualificados,
    vendas,
    valor_venda,
    valor_receita,
    cpl,
    cpl_qualificado,
    cac,
    roas
FROM bi.mv_mkt_roas
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref, canal;
