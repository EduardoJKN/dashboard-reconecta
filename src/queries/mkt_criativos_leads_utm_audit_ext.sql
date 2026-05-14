-- =============================================================================
-- Criativos — auditoria de leads (ext_reconecta.leads) no período.
-- Mesma limpeza de e-mail usada em mkt_paginas_variantes / Top por nome.
-- Colunas calculadas (norms, match UTM ↔ fdw) são feitas no Python.
-- =============================================================================
SELECT *
FROM ext_reconecta.leads l
WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
  AND l.email IS NOT NULL
  AND btrim(l.email) <> ''
  AND lower(l.email) NOT LIKE '%@teste%'
  AND lower(l.email) NOT LIKE 'teste@%'
  AND lower(l.email) NOT LIKE '%smarts%'
  AND lower(l.email) NOT LIKE '%reconecta%'
ORDER BY l.created_at DESC;
