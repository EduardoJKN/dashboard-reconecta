-- =============================================================================
-- Executivas oficiais — cadastro completo (ativas + históricas/inativas).
-- =============================================================================
-- Origem: `fdw_reconecta.executivas_vendas`.
-- Uso: ranking Top Closers em modo "Histórico geral" (Executivas & Times).
-- =============================================================================
SELECT
    id,
    nome,
    email,
    id_crm,
    ativo
FROM fdw_reconecta.executivas_vendas
WHERE nome IS NOT NULL
  AND btrim(nome) <> ''
ORDER BY ativo DESC, nome;
