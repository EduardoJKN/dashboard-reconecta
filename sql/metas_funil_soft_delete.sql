-- Permissão de exclusão para metas oficiais do Funil da Reconecta.
-- Executar manualmente no Postgres de metas (METAS_DATABASE_URL).

GRANT DELETE ON bi.metas_funil_reconecta TO reconecta_metas_writer;
