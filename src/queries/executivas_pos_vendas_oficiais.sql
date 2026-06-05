-- =============================================================================
-- Pós-venda — cadastro oficial (ativos + históricos).
-- =============================================================================
-- Origem: `assistencial.executivas_pos_vendas` (foreign table no Railway).
--
-- NÃO usar `fdw_reconecta.executivas_pos_vendas` nem
-- `assistencial.executiva_pos_vendas_peso` (roleta de distribuição).
--
-- Permissões (rodar como superuser no Railway):
--   GRANT USAGE ON SCHEMA assistencial TO reconecta_readonly;
--   GRANT SELECT ON assistencial.executivas_pos_vendas TO reconecta_readonly;
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
FROM assistencial.executivas_pos_vendas
WHERE nome IS NOT NULL
  AND btrim(nome) <> ''
ORDER BY ativo DESC, nome;
