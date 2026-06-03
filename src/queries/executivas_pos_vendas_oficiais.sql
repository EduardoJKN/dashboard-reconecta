-- =============================================================================
-- Pós-venda — cadastro oficial (ativos + históricos).
-- =============================================================================
-- Origem: `fdw_reconecta.executivas_pos_vendas` (espelho FDW de
-- `assistencial.executivas_pos_vendas` no Reconecta DB).
--
-- NÃO usar `executiva_pos_vendas_peso` (roleta de distribuição).
--
-- Uso: match por `id_crm` (= ID Zoho em `zoho_deals.executiva_contas`) e
-- fallback por tokens de nome (mesma regra dos closers em transforms.py).
-- =============================================================================
SELECT
    id,
    nome,
    email,
    id_crm,
    id_clickup,
    ativo
FROM fdw_reconecta.executivas_pos_vendas
WHERE nome IS NOT NULL
  AND btrim(nome) <> ''
ORDER BY ativo DESC, nome;
