"""Persistência das metas oficiais do Funil da Reconecta.

Usa exclusivamente `METAS_DATABASE_URL` (`src.metas_db`). A estrutura
(`bi.metas_funil_reconecta`, `bi.vw_metas_funil_reconecta`) é criada
manualmente no banco — o app não executa DDL em runtime.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from src.metas_db import (
    MetasDatabaseNotConfiguredError,
    execute_metas_sql,
    is_metas_database_configured,
    run_metas_sql,
)

PERIODO_TIPO_PADRAO = "filtro_global"

_LOAD_SQL = """
SELECT
    investimento_mes,
    custo_por_lead,
    pct_lead_aplicacao,
    pct_aplicacao_agendamento,
    pct_agendamento_comparecimento,
    pct_comparecimento_venda,
    ticket_medio
FROM bi.metas_funil_reconecta
WHERE periodo_tipo = :periodo_tipo
  AND periodo_inicio = :periodo_inicio
  AND periodo_fim = :periodo_fim
LIMIT 1
"""

_UPSERT_SQL = """
INSERT INTO bi.metas_funil_reconecta (
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

_HISTORICO_SQL = """
SELECT *
FROM bi.vw_metas_funil_reconecta
ORDER BY periodo_fim DESC, atualizado_em DESC NULLS LAST
LIMIT :limit
"""

_SOFT_DELETE_SQL = """
UPDATE bi.metas_funil_reconecta
SET ativo = FALSE,
    excluido_em = NOW(),
    excluido_por = :excluido_por,
    atualizado_em = NOW()
WHERE id = :id
  AND COALESCE(ativo, TRUE) = TRUE
"""


def pct_to_display_percent(val: float) -> float:
    """Converte taxa 0–1 ou 0–100 (banco) para exibição em pontos (80 → 80,00%)."""
    v = float(val or 0)
    if abs(v) <= 1.0:
        return v * 100.0
    return v


def _normalize_pct_from_db(val: float) -> float:
    """Normaliza taxa do banco (0–100) para escala interna do funil (0–1)."""
    v = float(val or 0)
    if abs(v) > 1.0:
        return v / 100.0
    return v


def _pct_to_db_store(val: float) -> float:
    """Persiste taxa no padrão 0–100 do banco."""
    v = float(val or 0)
    if abs(v) <= 1.0:
        return v * 100.0
    return v


def _row_to_metas_dict(row: Any) -> dict[str, float]:
    return {
        "investimento": float(row["investimento_mes"] or 0),
        "custo_lead": float(row["custo_por_lead"] or 0),
        "pct_la": _normalize_pct_from_db(row["pct_lead_aplicacao"]),
        "pct_a_ag": _normalize_pct_from_db(row["pct_aplicacao_agendamento"]),
        "pct_ag_c": _normalize_pct_from_db(row["pct_agendamento_comparecimento"]),
        "pct_c_v": _normalize_pct_from_db(row["pct_comparecimento_venda"]),
        "ticket": float(row["ticket_medio"] or 0),
    }


def metas_dict_to_scenario(metas_dict: dict[str, float]) -> dict[str, float]:
    """Formato de `st.session_state['funil_meta_tela']` / `Scenario`."""
    return {
        "investimento": float(metas_dict["investimento"]),
        "custo_lead": float(metas_dict["custo_lead"]),
        "pct_la": float(metas_dict["pct_la"]),
        "pct_a_ag": float(metas_dict["pct_a_ag"]),
        "pct_ag_c": float(metas_dict["pct_ag_c"]),
        "pct_c_v": float(metas_dict["pct_c_v"]),
        "ticket": float(metas_dict["ticket"]),
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


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def load_funil_meta(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> dict[str, float] | None:
    """Carrega metas oficiais do período ou None se não houver registro."""
    df = run_metas_sql(
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
    execute_metas_sql(
        _UPSERT_SQL,
        {
            "periodo_tipo": periodo_tipo,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
            "investimento_mes": float(metas_dict["investimento"]),
            "custo_por_lead": float(metas_dict["custo_lead"]),
            "pct_lead_aplicacao": _pct_to_db_store(metas_dict["pct_la"]),
            "pct_aplicacao_agendamento": _pct_to_db_store(metas_dict["pct_a_ag"]),
            "pct_agendamento_comparecimento": _pct_to_db_store(metas_dict["pct_ag_c"]),
            "pct_comparecimento_venda": _pct_to_db_store(metas_dict["pct_c_v"]),
            "ticket_medio": float(metas_dict["ticket"]),
            "criado_por": criado_por,
        },
    )


def load_metas_funil_historico(*, limit: int = 100) -> list[dict[str, Any]]:
    """Histórico de metas oficiais salvas (`bi.vw_metas_funil_reconecta`)."""
    df = run_metas_sql(_HISTORICO_SQL, {"limit": int(limit)})
    if df.empty:
        return []

    rows: list[dict[str, Any]] = []
    for _, raw in df.iterrows():
        ini = _as_date(raw["periodo_inicio"])
        fim = _as_date(raw["periodo_fim"])
        metas = _row_to_metas_dict(raw)
        pct_rec_raw = raw.get("pct_receita_sobre_montante")
        if pct_rec_raw is None:
            pct_rec_raw = raw.get("pct_recebimento_sobre_montante")
        pct_recebimento = (
            pct_to_display_percent(float(pct_rec_raw))
            if pct_rec_raw is not None
            else 0.0
        )
        meta_db_id = int(raw["id"])
        rows.append({
            "id": f"meta_db_{meta_db_id}",
            "meta_db_id": meta_db_id,
            "periodo": (
                f"Meta oficial · {ini.strftime('%d/%m/%Y')} – "
                f"{fim.strftime('%d/%m/%Y')}"
            ),
            "data_ini": ini,
            "data_fim": fim,
            "periodo_tipo": str(raw.get("periodo_tipo") or ""),
            "investimento": metas["investimento"],
            "custo_lead": metas["custo_lead"],
            "pct_la": metas["pct_la"],
            "pct_a_ag": metas["pct_a_ag"],
            "pct_ag_c": metas["pct_ag_c"],
            "pct_c_v": metas["pct_c_v"],
            "ticket": metas["ticket"],
            "pct_recebimento": pct_recebimento,
            "scenario": metas_dict_to_scenario(metas),
            "criado_em": raw.get("criado_em"),
            "atualizado_em": raw.get("atualizado_em"),
            "criado_por": raw.get("criado_por"),
            "observacao": raw.get("observacao"),
        })
    return rows


def soft_delete_meta_funil(meta_id: int, *, excluido_por: str | None = None) -> None:
    """Soft delete de meta oficial (`ativo = FALSE`). Requer colunas no banco."""
    execute_metas_sql(
        _SOFT_DELETE_SQL,
        {"id": int(meta_id), "excluido_por": excluido_por},
    )


__all__ = [
    "MetasDatabaseNotConfiguredError",
    "PERIODO_TIPO_PADRAO",
    "is_metas_database_configured",
    "load_funil_meta",
    "load_metas_funil_historico",
    "metas_dict_from_scenario",
    "metas_dict_to_scenario",
    "pct_to_display_percent",
    "save_funil_meta",
    "soft_delete_meta_funil",
]
