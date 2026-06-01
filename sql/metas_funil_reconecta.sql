-- Metas oficiais do Funil da Reconecta (por intervalo do filtro global).
-- Executar manualmente no Postgres (Railway) se preferir criar antes do app.

CREATE TABLE IF NOT EXISTS metas_funil_reconecta (
    id SERIAL PRIMARY KEY,
    periodo_tipo TEXT NOT NULL,
    periodo_inicio DATE NOT NULL,
    periodo_fim DATE NOT NULL,
    investimento_mes NUMERIC,
    custo_por_lead NUMERIC,
    pct_lead_aplicacao NUMERIC,
    pct_aplicacao_agendamento NUMERIC,
    pct_agendamento_comparecimento NUMERIC,
    pct_comparecimento_venda NUMERIC,
    ticket_medio NUMERIC,
    criado_em TIMESTAMP DEFAULT NOW(),
    atualizado_em TIMESTAMP DEFAULT NOW(),
    criado_por TEXT,
    UNIQUE (periodo_tipo, periodo_inicio, periodo_fim)
);
