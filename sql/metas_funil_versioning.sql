-- Histórico de metas por período (múltiplas versões).
-- Executar manualmente no Postgres de metas (METAS_DATABASE_URL).

ALTER TABLE bi.metas_funil_reconecta
    ADD COLUMN IF NOT EXISTS nome_meta TEXT,
    ADD COLUMN IF NOT EXISTS versao_meta INTEGER;

UPDATE bi.metas_funil_reconecta
SET
    versao_meta = COALESCE(versao_meta, 1),
    nome_meta = COALESCE(NULLIF(TRIM(nome_meta), ''), 'Meta oficial')
WHERE versao_meta IS NULL
   OR nome_meta IS NULL
   OR TRIM(nome_meta) = '';

-- Remover UNIQUE antiga (ajuste o nome conforme pg_constraint, se necessário):
ALTER TABLE bi.metas_funil_reconecta
    DROP CONSTRAINT IF EXISTS metas_funil_reconecta_periodo_tipo_periodo_inicio_periodo_fim_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_metas_funil_reconecta_periodo_versao
    ON bi.metas_funil_reconecta (
        periodo_tipo,
        periodo_inicio,
        periodo_fim,
        versao_meta
    );

CREATE OR REPLACE VIEW bi.vw_metas_funil_reconecta AS
SELECT
    id,
    periodo_tipo,
    periodo_inicio,
    periodo_fim,
    nome_meta,
    versao_meta,
    investimento_mes,
    custo_por_lead,
    leads_meta,
    pct_lead_aplicacao,
    aplicacoes_meta,
    pct_aplicacao_agendamento,
    agendamentos_meta,
    pct_agendamento_comparecimento,
    comparecimentos_meta,
    pct_comparecimento_venda,
    vendas_meta,
    ticket_medio,
    montante_meta,
    pct_receita_sobre_montante,
    receita_meta,
    observacao,
    criado_em,
    atualizado_em,
    criado_por
FROM bi.metas_funil_reconecta;

GRANT DELETE ON bi.metas_funil_reconecta TO reconecta_metas_writer;
