-- =============================================================================
-- Criativos — auditoria de leads (lp_form.leads), espelhando o filtro da ext.
-- Se o role não tiver permissão em lp_form, a página cai para a query *_ext.
-- =============================================================================
SELECT *
FROM lp_form.leads l
WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
  AND l.email IS NOT NULL
  AND btrim(l.email) <> ''
  AND lower(l.email) NOT LIKE '%@teste%'
  AND lower(l.email) NOT LIKE 'teste@%'
  AND lower(l.email) NOT LIKE '%smarts%'
  AND lower(l.email) NOT LIKE '%reconecta%'
ORDER BY l.created_at DESC;
