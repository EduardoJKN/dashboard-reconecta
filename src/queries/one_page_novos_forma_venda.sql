-- =============================================================================
-- One Page — Card "Novos": breakdown por forma_venda (Em call / Follow).
-- =============================================================================
-- Base: vendas novas ganhas no período (mesma janela de tipo_venda do card
-- Novos na view, com stage ampliado para 'Fechado Ganho').
--
--   novos   = COUNT(DISTINCT id) com tipo_venda = 'Novo cliente'
--   em_call = subset com forma_venda = 'Em call'
--   follow  = subset com forma_venda = 'Follow up' (sem null/vazio — Looker)
--
-- Não altera o número principal de Novos (view legada). Apenas sub-stats.
-- E-mail: nulo/vazio excluído + filtros canônicos de teste (One Page).
-- =============================================================================
SELECT
    COUNT(DISTINCT d.id)::bigint AS novos,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.forma_venda = 'Em call'
    )::bigint AS em_call,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.forma_venda = 'Follow up'
    )::bigint AS follow
FROM zoho_deals d
WHERE d.stage IN ('Ganho', 'Fechado Ganho')
  AND d.tipo_venda = 'Novo cliente'
  AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
  AND d.email IS NOT NULL
  AND btrim(d.email) <> ''
  AND lower(d.email) NOT LIKE '%@teste%'
  AND lower(d.email) NOT LIKE 'teste@%'
  AND lower(d.email) NOT LIKE '%smarts%'
  AND lower(d.email) NOT LIKE '%reconecta%';
