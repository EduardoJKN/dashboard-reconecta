-- Metas oficiais do Funil da Reconecta (histórico por período + versão).
-- Executar manualmente no Postgres (METAS_DATABASE_URL).

CREATE TABLE IF NOT EXISTS bi.metas_funil_reconecta (
    id SERIAL PRIMARY KEY,
    periodo_tipo TEXT NOT NULL,
    periodo_inicio DATE NOT NULL,
    periodo_fim DATE NOT NULL,
    nome_meta TEXT,
    versao_meta INTEGER,
    investimento_mes NUMERIC,
    custo_por_lead NUMERIC,
    leads_meta NUMERIC,
    pct_lead_aplicacao NUMERIC,
    aplicacoes_meta NUMERIC,
    pct_aplicacao_agendamento NUMERIC,
    agendamentos_meta NUMERIC,
    pct_agendamento_comparecimento NUMERIC,
    comparecimentos_meta NUMERIC,
    pct_comparecimento_venda NUMERIC,
    vendas_meta NUMERIC,
    ticket_medio NUMERIC,
    montante_meta NUMERIC,
    pct_receita_sobre_montante NUMERIC,
    receita_meta NUMERIC,
    observacao TEXT,
    criado_em TIMESTAMP DEFAULT NOW(),
    atualizado_em TIMESTAMP DEFAULT NOW(),
    criado_por TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_metas_funil_reconecta_periodo_versao
    ON bi.metas_funil_reconecta (
        periodo_tipo,
        periodo_inicio,
        periodo_fim,
        versao_meta
    );

-- Migração de ambientes existentes: ver sql/metas_funil_versioning.sql

GRANT DELETE ON bi.metas_funil_reconecta TO reconecta_metas_writer;
