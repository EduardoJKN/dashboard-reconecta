-- Média móvel de vendas ganhas — fórmula do Looker:
--   COUNT(CASE WHEN stage IN ('Fechado Ganho','Ganho')
--                 AND data_hora_compra >= CURRENT_DATE - INTERVAL '21 days'
--              THEN id END) / 15
-- Não recebe filtro de período da página: é sempre relativo a CURRENT_DATE.
SELECT
    COUNT(*)::numeric / 15.0 AS media_movel
FROM bi.trat_negocios_rw
WHERE stage IN ('Fechado Ganho', 'Ganho')
  AND data_hora_compra >= CURRENT_DATE - INTERVAL '21 days';
