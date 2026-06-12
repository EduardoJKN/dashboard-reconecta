"""Persistência das metas oficiais do Funil da Reconecta.

Usa exclusivamente `METAS_DATABASE_URL` (`src.metas_db`). A estrutura
(`bi.metas_funil_reconecta`, `bi.vw_metas_funil_reconecta`) é criada
manualmente no banco — o app não executa DDL em runtime.
"""
from __future__ import annotations

import math
from dataclasses import asdict
from datetime import date
from typing import Any

from src.metas_db import (
    MetasDatabaseNotConfiguredError,
    execute_metas_sql,
    execute_metas_sql_rowcount,
    is_metas_database_configured,
    run_metas_sql,
)
from src.one_page_funnel import project_receita_from_montante

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
ORDER BY versao_meta DESC NULLS LAST, atualizado_em DESC NULLS LAST
LIMIT 1
"""

_NEXT_VERSION_SQL = """
SELECT COALESCE(MAX(versao_meta), 0) + 1 AS proxima_versao
FROM bi.metas_funil_reconecta
WHERE periodo_tipo = :periodo_tipo
  AND periodo_inicio = :periodo_inicio
  AND periodo_fim = :periodo_fim
"""

_INSERT_SQL = """
INSERT INTO bi.metas_funil_reconecta (
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
    criado_por
) VALUES (
    :periodo_tipo,
    :periodo_inicio,
    :periodo_fim,
    :nome_meta,
    :versao_meta,
    :investimento_mes,
    :custo_por_lead,
    :leads_meta,
    :pct_lead_aplicacao,
    :aplicacoes_meta,
    :pct_aplicacao_agendamento,
    :agendamentos_meta,
    :pct_agendamento_comparecimento,
    :comparecimentos_meta,
    :pct_comparecimento_venda,
    :vendas_meta,
    :ticket_medio,
    :montante_meta,
    :pct_receita_sobre_montante,
    :receita_meta,
    :observacao,
    :criado_por
)
"""

_HISTORICO_SQL = """
SELECT *
FROM bi.vw_metas_funil_reconecta
ORDER BY periodo_inicio DESC, versao_meta DESC NULLS LAST, atualizado_em DESC NULLS LAST
LIMIT :limit
"""

_DELETE_SQL = """
DELETE FROM bi.metas_funil_reconecta
WHERE id = :id
"""


def meta_nome_for_versao(versao: int | None) -> str:
    """Rótulo da versão: Meta oficial | Meta oficial 2 | …"""
    v = int(versao or 1)
    if v <= 1:
        return "Meta oficial"
    return f"Meta oficial {v}"


def meta_periodo_label(
    data_ini: date,
    data_fim: date,
    *,
    versao: int | None = None,
    nome_meta: str | None = None,
) -> str:
    """Ex.: Meta oficial 2 · 01/06/2026 – 30/06/2026"""
    nome = (nome_meta or "").strip() or meta_nome_for_versao(versao)
    return (
        f"{nome} · {data_ini.strftime('%d/%m/%Y')} – "
        f"{data_fim.strftime('%d/%m/%Y')}"
    )


def _resolve_meta_nome_versao(raw: Any) -> tuple[str, int]:
    versao = int(_optional_float(raw, "versao_meta") or 1)
    nome_raw = raw.get("nome_meta") if hasattr(raw, "get") else None
    nome = str(nome_raw).strip() if nome_raw not in (None, "") else ""
    if not nome:
        nome = meta_nome_for_versao(versao)
    return nome, versao


def _next_meta_versao(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> int:
    df = run_metas_sql(
        _NEXT_VERSION_SQL,
        {
            "periodo_tipo": periodo_tipo,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
        },
    )
    if df.empty:
        return 1
    return int(df.iloc[0]["proxima_versao"] or 1)


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


def _get_first_from_reference(
    row: dict[str, Any],
    keys: list[str],
    default: float = 0.0,
) -> float:
    """Primeiro valor não nulo na linha de referência ou em `scenario`."""
    for k in keys:
        if k in row and row[k] is not None:
            return float(row[k])
    scenario = row.get("scenario")
    if isinstance(scenario, dict):
        for k in keys:
            if k in scenario and scenario[k] is not None:
                return float(scenario[k])
    return float(default)


def normalize_reference_to_meta_payload(row: dict[str, Any]) -> dict[str, float]:
    """Referência histórica ou meta salva → dict `funil_meta_tela` / `Scenario`."""
    return {
        "investimento": _get_first_from_reference(
            row, ["investimento_mes", "investimento"],
        ),
        "custo_lead": _get_first_from_reference(
            row, ["custo_por_lead", "custo_lead", "cpl"],
        ),
        "pct_la": _normalize_pct_from_db(_get_first_from_reference(
            row, ["pct_lead_aplicacao", "pct_la", "pct_l_apl"],
        )),
        "pct_a_ag": _normalize_pct_from_db(_get_first_from_reference(
            row, ["pct_aplicacao_agendamento", "pct_a_ag", "pct_apl_ag"],
        )),
        "pct_ag_c": _normalize_pct_from_db(_get_first_from_reference(
            row,
            ["pct_agendamento_comparecimento", "pct_ag_c", "pct_ag_comp"],
        )),
        "pct_c_v": _normalize_pct_from_db(_get_first_from_reference(
            row, ["pct_comparecimento_venda", "pct_c_v", "pct_comp_vda"],
        )),
        "ticket": _get_first_from_reference(row, ["ticket_medio", "ticket"]),
    }


def normalize_reference_pct_recebimento(row: dict[str, Any]) -> float:
    """% recebimento sobre montante (escala 0–100 para widgets)."""
    raw = _get_first_from_reference(
        row,
        [
            "pct_receita_sobre_montante",
            "pct_receita_montante",
            "pct_recebimento_sobre_montante",
            "pct_recebimento",
        ],
    )
    return pct_to_display_percent(raw)


def _safe_volume_ratio(num: float, den: float) -> float:
    d = float(den or 0)
    if d <= 0:
        return 0.0
    return max(0.0, float(num or 0) / d)


def normalize_reference_volumes(row: dict[str, Any]) -> dict[str, float] | None:
    """Volumes absolutos da referência (histórico real), se presentes na linha."""
    field_keys: list[tuple[str, list[str]]] = [
        ("leads", ["leads", "leads_meta"]),
        ("aplicacoes", ["aplicacoes", "aplicacoes_meta"]),
        ("agendamentos", ["agendamentos", "agendamentos_meta"]),
        ("comparecimento", ["comparecimento", "comparecimentos", "comparecimentos_meta"]),
        ("vendas", ["vendas", "vendas_meta"]),
        ("montante", ["montante", "montante_meta"]),
        ("receita", ["receita", "receita_meta"]),
    ]
    volumes: dict[str, float] = {}
    for field, keys in field_keys:
        if any(k in row and row[k] is not None for k in keys):
            volumes[field] = _get_first_from_reference(row, keys)

    if not volumes:
        return None
    if "agendamentos" not in volumes and "vendas" not in volumes:
        return None

    if volumes.get("montante", 0) <= 0:
        vendas = volumes.get("vendas", 0)
        ticket = _get_first_from_reference(row, ["ticket_medio", "ticket"])
        if vendas > 0 and ticket > 0:
            volumes["montante"] = vendas * ticket

    return volumes


def meta_payload_from_reference_volumes(
    row: dict[str, Any],
    volumes: dict[str, float],
) -> dict[str, float]:
    """Cenário com taxas efetivas derivadas dos volumes absolutos da referência."""
    investimento = _get_first_from_reference(
        row, ["investimento_mes", "investimento"],
    )
    ticket = _get_first_from_reference(row, ["ticket_medio", "ticket"])
    leads = volumes.get("leads", 0.0)
    aplicacoes = volumes.get("aplicacoes", 0.0)
    agendamentos = volumes.get("agendamentos", 0.0)
    comparecimento = volumes.get("comparecimento", 0.0)
    vendas = volumes.get("vendas", 0.0)

    if leads > 0:
        custo_lead = investimento / leads
    else:
        custo_lead = _get_first_from_reference(
            row, ["custo_por_lead", "custo_lead", "cpl"],
        )

    return {
        "investimento": investimento,
        "custo_lead": custo_lead,
        "pct_la": _safe_volume_ratio(aplicacoes, leads),
        "pct_a_ag": _safe_volume_ratio(agendamentos, aplicacoes),
        "pct_ag_c": _safe_volume_ratio(comparecimento, agendamentos),
        "pct_c_v": _safe_volume_ratio(vendas, comparecimento),
        "ticket": ticket,
    }


def pct_recebimento_from_reference_volumes(
    row: dict[str, Any],
    volumes: dict[str, float],
) -> float:
    """% recebimento = receita / montante (prioriza valores absolutos)."""
    montante = float(volumes.get("montante") or 0)
    receita = float(volumes.get("receita") or 0)
    if montante <= 0:
        vendas = float(volumes.get("vendas") or 0)
        ticket = _get_first_from_reference(row, ["ticket_medio", "ticket"])
        if vendas > 0 and ticket > 0:
            montante = vendas * ticket
    if montante > 0 and receita > 0:
        return receita / montante * 100.0
    return normalize_reference_pct_recebimento(row)


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


def _calc_meta_volumes_mes(
    metas: dict[str, float],
    *,
    pct_recebimento: float = 0.0,
) -> dict[str, float]:
    """Cascata mensal a partir do cenário (vendas inteiras, montante = vendas × ticket)."""
    inv = float(metas["investimento"])
    cl = float(metas["custo_lead"])
    leads = inv / cl if cl > 0 else 0.0
    aplicacoes = leads * float(metas["pct_la"])
    agendamentos = aplicacoes * float(metas["pct_a_ag"])
    comparecimento = agendamentos * float(metas["pct_ag_c"])
    vendas = int(round(comparecimento * float(metas["pct_c_v"])))
    ticket = float(metas["ticket"])
    montante = float(vendas) * ticket
    receita = project_receita_from_montante(montante, pct_recebimento)
    return {
        "leads": leads,
        "aplicacoes": aplicacoes,
        "agendamentos": agendamentos,
        "comparecimento": float(comparecimento),
        "vendas": float(vendas),
        "montante": montante,
        "receita": receita,
    }


def _optional_float(row: Any, key: str) -> float | None:
    if key not in row:
        return None
    val = row[key]
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(num):
        return None
    return num


def _resolve_meta_financeiro(
    raw: Any,
    metas: dict[str, float],
    *,
    pct_recebimento: float,
) -> tuple[float, float, float]:
    """Montante, receita e % recebimento com fallback para registros antigos."""
    calc = _calc_meta_volumes_mes(metas, pct_recebimento=pct_recebimento)
    montante = _optional_float(raw, "montante_meta")
    receita = _optional_float(raw, "receita_meta")
    pct_raw = _optional_float(raw, "pct_receita_sobre_montante")
    if pct_raw is None:
        pct_raw = _optional_float(raw, "pct_recebimento_sobre_montante")

    if montante is None:
        montante = calc["montante"]
    if pct_raw is not None:
        pct_rec = pct_to_display_percent(pct_raw)
    elif pct_recebimento > 0:
        pct_rec = pct_recebimento
    else:
        pct_rec = 0.0

    if receita is None and montante > 0 and pct_rec > 0:
        receita = montante * pct_rec / 100.0
    elif receita is None:
        receita = calc["receita"]

    if (pct_raw is None and montante > 0 and receita > 0):
        pct_rec = receita / montante * 100.0

    return float(montante), float(receita), float(pct_rec)


def build_funil_meta_save_payload(
    scenario_dict: dict[str, float],
    calc_m: dict[str, float],
    *,
    pct_recebimento: float,
) -> dict[str, float]:
    """Payload completo para INSERT — inclui volumes e financeiro projetado."""
    base = metas_dict_from_scenario(scenario_dict)
    montante = float(calc_m["montante"])
    receita = project_receita_from_montante(montante, pct_recebimento)
    return {
        **base,
        "leads_meta": float(calc_m["leads"]),
        "aplicacoes_meta": float(calc_m["aplicacoes"]),
        "agendamentos_meta": float(calc_m["agendamentos"]),
        "comparecimentos_meta": float(calc_m["comparecimento"]),
        "vendas_meta": float(calc_m["vendas"]),
        "montante_meta": montante,
        "pct_receita_sobre_montante": float(pct_recebimento),
        "receita_meta": receita,
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
    observacao: str | None = None,
) -> dict[str, Any]:
    """Insere nova versão de meta oficial (histórico por período)."""
    montante = float(metas_dict.get("montante_meta") or 0)
    receita = float(metas_dict.get("receita_meta") or 0)
    pct_rec = float(metas_dict.get("pct_receita_sobre_montante") or 0)
    if montante <= 0:
        vendas = float(metas_dict.get("vendas_meta") or 0)
        ticket = float(metas_dict.get("ticket") or 0)
        montante = vendas * ticket
    if receita <= 0 and montante > 0 and pct_rec > 0:
        receita = project_receita_from_montante(montante, pct_rec)

    versao_meta = _next_meta_versao(periodo_tipo, periodo_inicio, periodo_fim)
    nome_meta = meta_nome_for_versao(versao_meta)

    execute_metas_sql(
        _INSERT_SQL,
        {
            "periodo_tipo": periodo_tipo,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
            "nome_meta": nome_meta,
            "versao_meta": versao_meta,
            "investimento_mes": float(metas_dict["investimento"]),
            "custo_por_lead": float(metas_dict["custo_lead"]),
            "leads_meta": float(metas_dict.get("leads_meta") or 0),
            "pct_lead_aplicacao": _pct_to_db_store(metas_dict["pct_la"]),
            "aplicacoes_meta": float(metas_dict.get("aplicacoes_meta") or 0),
            "pct_aplicacao_agendamento": _pct_to_db_store(metas_dict["pct_a_ag"]),
            "agendamentos_meta": float(metas_dict.get("agendamentos_meta") or 0),
            "pct_agendamento_comparecimento": _pct_to_db_store(metas_dict["pct_ag_c"]),
            "comparecimentos_meta": float(metas_dict.get("comparecimentos_meta") or 0),
            "pct_comparecimento_venda": _pct_to_db_store(metas_dict["pct_c_v"]),
            "vendas_meta": float(metas_dict.get("vendas_meta") or 0),
            "ticket_medio": float(metas_dict["ticket"]),
            "montante_meta": montante,
            "pct_receita_sobre_montante": pct_rec,
            "receita_meta": receita,
            "observacao": observacao,
            "criado_por": criado_por,
        },
    )
    return {
        "nome_meta": nome_meta,
        "versao_meta": versao_meta,
        "periodo_label": meta_periodo_label(
            periodo_inicio, periodo_fim,
            versao=versao_meta, nome_meta=nome_meta,
        ),
    }


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
        calc = _calc_meta_volumes_mes(metas)
        pct_rec_raw = _optional_float(raw, "pct_receita_sobre_montante")
        if pct_rec_raw is None:
            pct_rec_raw = _optional_float(raw, "pct_recebimento_sobre_montante")
        pct_hint = pct_to_display_percent(pct_rec_raw) if pct_rec_raw is not None else 0.0
        montante, receita, pct_recebimento = _resolve_meta_financeiro(
            raw, metas, pct_recebimento=pct_hint,
        )
        meta_db_id = int(raw["id"])
        nome_meta, versao_meta = _resolve_meta_nome_versao(raw)
        rows.append({
            "id": f"meta_db_{meta_db_id}",
            "meta_db_id": meta_db_id,
            "periodo": meta_periodo_label(
                ini, fim, versao=versao_meta, nome_meta=nome_meta,
            ),
            "nome_meta": nome_meta,
            "versao_meta": versao_meta,
            "data_ini": ini,
            "data_fim": fim,
            "periodo_tipo": str(raw.get("periodo_tipo") or ""),
            "investimento": metas["investimento"],
            "custo_lead": metas["custo_lead"],
            "leads": _optional_float(raw, "leads_meta") or calc["leads"],
            "pct_la": metas["pct_la"],
            "aplicacoes": _optional_float(raw, "aplicacoes_meta") or calc["aplicacoes"],
            "pct_a_ag": metas["pct_a_ag"],
            "agendamentos": _optional_float(raw, "agendamentos_meta") or calc["agendamentos"],
            "pct_ag_c": metas["pct_ag_c"],
            "comparecimento": (
                _optional_float(raw, "comparecimentos_meta") or calc["comparecimento"]
            ),
            "pct_c_v": metas["pct_c_v"],
            "vendas": _optional_float(raw, "vendas_meta") or calc["vendas"],
            "ticket": metas["ticket"],
            "montante": montante,
            "receita": receita,
            "pct_recebimento": pct_recebimento,
            "scenario": metas_dict_to_scenario(metas),
            "criado_em": raw.get("criado_em"),
            "atualizado_em": raw.get("atualizado_em"),
            "criado_por": raw.get("criado_por"),
            "observacao": raw.get("observacao"),
        })
    return rows


def delete_meta_funil(meta_id: int) -> int:
    """Remove meta oficial (`DELETE` direto em `bi.metas_funil_reconecta`)."""
    if not is_metas_database_configured():
        raise MetasDatabaseNotConfiguredError(
            "METAS_DATABASE_URL não configurada."
        )
    return execute_metas_sql_rowcount(_DELETE_SQL, {"id": int(meta_id)})


__all__ = [
    "MetasDatabaseNotConfiguredError",
    "PERIODO_TIPO_PADRAO",
    "is_metas_database_configured",
    "load_funil_meta",
    "load_metas_funil_historico",
    "build_funil_meta_save_payload",
    "metas_dict_from_scenario",
    "metas_dict_to_scenario",
    "meta_payload_from_reference_volumes",
    "normalize_reference_pct_recebimento",
    "normalize_reference_to_meta_payload",
    "normalize_reference_volumes",
    "pct_recebimento_from_reference_volumes",
    "pct_to_display_percent",
    "delete_meta_funil",
    "meta_nome_for_versao",
    "meta_periodo_label",
    "save_funil_meta",
]
