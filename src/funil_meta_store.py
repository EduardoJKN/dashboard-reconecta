"""Persistência das metas oficiais do Funil da Reconecta (Postgres)."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from src.db import execute_sql, run_sql

PERIODO_TIPO_PADRAO = "filtro_global"

_ENSURE_TABLE_SQL = """
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
)
"""

_LOAD_SQL = """
SELECT
    investimento_mes,
    custo_por_lead,
    pct_lead_aplicacao,
    pct_aplicacao_agendamento,
    pct_agendamento_comparecimento,
    pct_comparecimento_venda,
    ticket_medio
FROM metas_funil_reconecta
WHERE periodo_tipo = :periodo_tipo
  AND periodo_inicio = :periodo_inicio
  AND periodo_fim = :periodo_fim
LIMIT 1
"""

_UPSERT_SQL = """
INSERT INTO metas_funil_reconecta (
    periodo_tipo,
    periodo_inicio,
    periodo_fim,
    investimento_mes,
    custo_por_lead,
    pct_lead_aplicacao,
    pct_aplicacao_agendamento,
    pct_agendamento_comparecimento,
    pct_comparecimento_venda,
    ticket_medio,
    criado_por
) VALUES (
    :periodo_tipo,
    :periodo_inicio,
    :periodo_fim,
    :investimento_mes,
    :custo_por_lead,
    :pct_lead_aplicacao,
    :pct_aplicacao_agendamento,
    :pct_agendamento_comparecimento,
    :pct_comparecimento_venda,
    :ticket_medio,
    :criado_por
)
ON CONFLICT (periodo_tipo, periodo_inicio, periodo_fim)
DO UPDATE SET
    investimento_mes = EXCLUDED.investimento_mes,
    custo_por_lead = EXCLUDED.custo_por_lead,
    pct_lead_aplicacao = EXCLUDED.pct_lead_aplicacao,
    pct_aplicacao_agendamento = EXCLUDED.pct_aplicacao_agendamento,
    pct_agendamento_comparecimento = EXCLUDED.pct_agendamento_comparecimento,
    pct_comparecimento_venda = EXCLUDED.pct_comparecimento_venda,
    ticket_medio = EXCLUDED.ticket_medio,
    atualizado_em = NOW(),
    criado_por = COALESCE(EXCLUDED.criado_por, metas_funil_reconecta.criado_por)
"""


def ensure_metas_table() -> None:
    execute_sql(_ENSURE_TABLE_SQL)


def _row_to_metas_dict(row: Any) -> dict[str, float]:
    return {
        "investimento": float(row["investimento_mes"] or 0),
        "custo_lead": float(row["custo_por_lead"] or 0),
        "pct_la": float(row["pct_lead_aplicacao"] or 0),
        "pct_a_ag": float(row["pct_aplicacao_agendamento"] or 0),
        "pct_ag_c": float(row["pct_agendamento_comparecimento"] or 0),
        "pct_c_v": float(row["pct_comparecimento_venda"] or 0),
        "ticket": float(row["ticket_medio"] or 0),
    }


def metas_dict_from_scenario(scenario: Any) -> dict[str, float]:
    """Converte Scenario ou dict de session_state para o formato de persistência."""
    if hasattr(scenario, "investimento"):
        d = asdict(scenario)
    else:
        d = dict(scenario)
    return {
        "investimento": float(d["investimento"]),
        "custo_lead": float(d["custo_lead"]),
        "pct_la": float(d["pct_la"]),
        "pct_a_ag": float(d["pct_a_ag"]),
        "pct_ag_c": float(d["pct_ag_c"]),
        "pct_c_v": float(d["pct_c_v"]),
        "ticket": float(d["ticket"]),
    }


def load_funil_meta(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> dict[str, float] | None:
    """Carrega metas oficiais do período ou None se não houver registro."""
    ensure_metas_table()
    df = run_sql(
        _LOAD_SQL,
        {
            "periodo_tipo": periodo_tipo,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
        },
    )
    if df.empty:
        return None
    return _row_to_metas_dict(df.iloc[0])


def save_funil_meta(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
    metas_dict: dict[str, float],
    *,
    criado_por: str | None = None,
) -> None:
    """Grava (UPSERT) metas oficiais para o intervalo do filtro global."""
    ensure_metas_table()
    execute_sql(
        _UPSERT_SQL,
        {
            "periodo_tipo": periodo_tipo,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
            "investimento_mes": float(metas_dict["investimento"]),
            "custo_por_lead": float(metas_dict["custo_lead"]),
            "pct_lead_aplicacao": float(metas_dict["pct_la"]),
            "pct_aplicacao_agendamento": float(metas_dict["pct_a_ag"]),
            "pct_agendamento_comparecimento": float(metas_dict["pct_ag_c"]),
            "pct_comparecimento_venda": float(metas_dict["pct_c_v"]),
            "ticket_medio": float(metas_dict["ticket"]),
            "criado_por": criado_por,
        },
    )
