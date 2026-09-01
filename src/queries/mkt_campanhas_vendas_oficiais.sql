-- Total oficial de vendas (mix de ganhos) para Campanhas (__todos__).
--
-- Finalidade: substituir int(SUM(vendas)) sobre dashboard_executivas.sql
-- por contagem direta em zoho_deals — mesmo universo do card Ganhos
-- (Time de Vendas), somente leitura.
--
-- Mix canônico:
--   stage IN ('Ganho', 'Fechado Ganho')
--   data_hora_compra IS NOT NULL
--   data_hora_compra::date BETWEEN :data_ini AND :data_fim
--   tipo_venda IN (Novo cliente, Ascensão, Renovação, Renovação antecipada,
--                  Indicação, Upgrade, Novo cliente EVENTO) OR Ingresso%
--
-- Deduplicacao: 1 linha por deal_id em zoho_deals — COUNT(*) sem joins.
SELECT COUNT(*)::bigint AS vendas
FROM zoho_deals d
WHERE d.stage IN ('Ganho', 'Fechado Ganho')
  AND d.data_hora_compra IS NOT NULL
  AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
  AND (d.tipo_venda IN (
          'Novo cliente', 'Ascensão', 'Renovação', 'Renovação antecipada',
          'Indicação', 'Upgrade', 'Novo cliente EVENTO'
      ) OR d.tipo_venda LIKE 'Ingresso%');
