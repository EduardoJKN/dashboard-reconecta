SELECT
    id,
    nome,
    email,
    id_crm
FROM fdw_reconecta.executivas_pre_vendas
WHERE nome IS NOT NULL
  AND btrim(nome) <> ''
ORDER BY nome;
