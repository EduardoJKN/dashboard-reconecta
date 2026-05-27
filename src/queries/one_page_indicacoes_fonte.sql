-- =============================================================================
-- One Page — Card "Indic." (vendas por fonte do lead, regra Looker).
-- =============================================================================
-- Conta deals ganhos no período cuja origem é indicação (`fonte_de_lead`),
-- independente de `tipo_venda`. Uma venda pode ser "Novo cliente" e ainda
-- contar aqui se a fonte foi Indicação (não é mutuamente exclusivo com Novos).
--
-- Regra:
--   COUNT(DISTINCT id) WHERE
--     stage IN ('Ganho','Fechado Ganho')
--     AND data_hora_compra::date IN [:data_ini, :data_fim]
--     AND fonte_de_lead = 'Indicação'
--
-- E-mail: nulo/vazio excluído + filtros canônicos de teste (One Page).
-- =============================================================================
SELECT COUNT(DISTINCT d.id)::bigint AS indicacoes
FROM zoho_deals d
WHERE d.stage IN ('Ganho', 'Fechado Ganho')
  AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
  AND d.fonte_de_lead = 'Indicação'
  AND d.email IS NOT NULL
  AND btrim(d.email) <> ''
  AND lower(d.email) NOT LIKE '%@teste%'
  AND lower(d.email) NOT LIKE 'teste@%'
  AND lower(d.email) NOT LIKE '%smarts%'
  AND lower(d.email) NOT LIKE '%reconecta%';
