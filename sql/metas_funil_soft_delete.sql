-- Soft delete para metas oficiais do Funil da Reconecta.
-- Executar manualmente no Postgres de metas (METAS_DATABASE_URL).

ALTER TABLE bi.metas_funil_reconecta
ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS excluido_em TIMESTAMP,
ADD COLUMN IF NOT EXISTS excluido_por TEXT;

GRANT DELETE ON bi.metas_funil_reconecta TO reconecta_metas_writer;

-- Ajuste a view para listar só registros ativos (exemplo):
-- CREATE OR REPLACE VIEW bi.vw_metas_funil_reconecta AS
-- SELECT *
-- FROM bi.metas_funil_reconecta
-- WHERE COALESCE(ativo, TRUE) = TRUE;
