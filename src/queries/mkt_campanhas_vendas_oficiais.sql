-- Total oficial de vendas novas para Campanhas (__todos__).
--
-- Finalidade: substituir int(SUM(vendas)) sobre dashboard_executivas.sql
-- (45 colunas, bi.vw_dashboard_comercial_executivas_rw) por contagem direta
-- em zoho_deals — mesmo indicador, somente leitura.
--
-- Regra preservada (bi.vw_dashboard_comercial_executivas_rw):
--   stage = 'Ganho'
--   tipo_venda = 'Novo cliente'
--   data_hora_compra IS NOT NULL
--   data_hora_compra::date BETWEEN :data_ini AND :data_fim
-- Equivalente a data_ganho NOT NULL com data_ganho = data_hora_compra::date
-- nos deals contados pela view (nao inclui 'Fechado Ganho').
--
-- Deduplicacao: 1 linha por deal_id em zoho_deals — COUNT(*) sem joins.
--
-- Nao usar SUM(vendas) de outra fonte (funil UTM, prevendas): regras e graos
-- diferem; este total e o CRM executivas agregado do periodo.
SELECT COUNT(*)::bigint AS vendas
FROM zoho_deals d
WHERE d.stage = 'Ganho'
  AND d.tipo_venda = 'Novo cliente'
  AND d.data_hora_compra IS NOT NULL
  AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim;
