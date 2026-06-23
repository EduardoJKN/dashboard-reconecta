"""Persistência das metas oficiais do Funil da Reconecta.

Usa exclusivamente `METAS_DATABASE_URL` (`src.metas_db`). A estrutura
(`bi.metas_funil_reconecta`, `bi.vw_metas_funil_reconecta`) é criada
manualmente no banco — o app não executa DDL em runtime.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
import streamlit as st

from src.metas_db import (
    MetasDatabaseNotConfiguredError,
    execute_metas_sql,
    execute_metas_sql_rowcount,
    get_metas_engine,
    is_metas_database_configured,
    run_metas_sql,
)
from src.one_page_funnel import project_receita_from_montante

PERIODO_TIPO_META_MENSAL = "mes"
PERIODO_TIPO_PADRAO = PERIODO_TIPO_META_MENSAL
LEGACY_PERIODO_TIPOS = ("filtro_global",)

_META_CACHE_TTL = 600

_MESES_PT = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

_META_VOLUME_SCALE_KEYS = (
    "investimento_mes",
    "investimento",
    "leads",
    "leads_meta",
    "aplicacoes",
    "aplicacoes_meta",
    "agendamentos",
    "agendamentos_meta",
    "comparecimento",
    "comparecimentos",
    "comparecimentos_meta",
    "vendas",
    "vendas_meta",
    "montante",
    "montante_meta",
    "receita",
    "receita_meta",
)

_META_SAVE_SCALE_KEYS = (
    "investimento",
    "leads_meta",
    "aplicacoes_meta",
    "agendamentos_meta",
    "comparecimentos_meta",
    "vendas_meta",
    "montante_meta",
    "receita_meta",
)


@dataclass(frozen=True)
class MetaMensalProporcao:
    """Proporção da meta mensal oficial para o recorte selecionado."""

    mes_inicio: date
    mes_fim: date
    selecao_inicio: date
    selecao_fim: date
    dias_selecionados: int
    dias_mes: int
    fator: float
    multi_mes: bool = False

    @property
    def mes_label(self) -> str:
        return f"{_MESES_PT[self.mes_inicio.month - 1]}/{self.mes_inicio.year}"

    def legenda(self) -> str | None:
        if self.multi_mes:
            return None
        if abs(self.fator - 1.0) <= 1e-9:
            return (
                f"Meta oficial mensal de {self.mes_label} "
                f"({self.mes_inicio.strftime('%d/%m/%Y')} – "
                f"{self.mes_fim.strftime('%d/%m/%Y')})."
            )
        pct = self.fator * 100.0
        return (
            f"Meta oficial de {self.mes_label} proporcional ao período selecionado: "
            f"{self.dias_selecionados} de {self.dias_mes} dias "
            f"({pct:.1f}% da meta mensal)."
        )


def first_day_of_month(d: date) -> date:
    return d.replace(day=1)


def last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def days_inclusive(data_ini: date, data_fim: date) -> int:
    return (data_fim - data_ini).days + 1


def is_single_calendar_month(data_ini: date, data_fim: date) -> bool:
    return data_ini.year == data_fim.year and data_ini.month == data_fim.month


def resolve_meta_mensal_proporcao(
    selecao_inicio: date,
    selecao_fim: date,
) -> MetaMensalProporcao:
    """Calcula fator dias_selecionados / dias_mes para metas mensais."""
    ini = _as_date(selecao_inicio)
    fim = _as_date(selecao_fim)
    if not is_single_calendar_month(ini, fim):
        return MetaMensalProporcao(
            mes_inicio=first_day_of_month(ini),
            mes_fim=last_day_of_month(ini),
            selecao_inicio=ini,
            selecao_fim=fim,
            dias_selecionados=days_inclusive(ini, fim),
            dias_mes=days_inclusive(first_day_of_month(ini), last_day_of_month(ini)),
            fator=1.0,
            multi_mes=True,
        )
    mes_ini = first_day_of_month(ini)
    mes_fim = last_day_of_month(ini)
    dias_sel = days_inclusive(ini, fim)
    dias_mes = days_inclusive(mes_ini, mes_fim)
    fator = dias_sel / dias_mes if dias_mes > 0 else 1.0
    return MetaMensalProporcao(
        mes_inicio=mes_ini,
        mes_fim=mes_fim,
        selecao_inicio=ini,
        selecao_fim=fim,
        dias_selecionados=dias_sel,
        dias_mes=dias_mes,
        fator=fator,
        multi_mes=False,
    )


def _scale_meta_row_fields(row: dict[str, Any], factor: float) -> dict[str, Any]:
    """Escala volumes e valores totais; mantém taxas, CPL e ticket."""
    if abs(factor - 1.0) <= 1e-12:
        return dict(row)
    out = dict(row)
    for key in _META_VOLUME_SCALE_KEYS:
        if key not in out or out[key] is None:
            continue
        out[key] = float(out[key]) * factor
    scenario = out.get("scenario")
    if isinstance(scenario, dict):
        sc = dict(scenario)
        sc["investimento"] = float(sc.get("investimento", 0)) * factor
        out["scenario"] = sc
    return out


def scale_meta_row_to_selection(
    row: dict[str, Any],
    factor: float,
) -> dict[str, Any]:
    """Meta mensal completa → meta proporcional ao recorte selecionado."""
    return _scale_meta_row_fields(row, factor)


def scale_meta_save_payload_to_monthly(
    payload: dict[str, float],
    factor: float,
) -> dict[str, float]:
    """Converte payload proporcional da tela em meta mensal para persistência."""
    if abs(factor - 1.0) <= 1e-12:
        return dict(payload)
    if factor <= 0:
        return dict(payload)
    inv = 1.0 / factor
    out = dict(payload)
    for key in _META_SAVE_SCALE_KEYS:
        if key in out:
            out[key] = float(out[key]) * inv
    return out


def monthly_save_bounds(selecao_inicio: date, selecao_fim: date) -> tuple[date, date]:
    """Período civil do mês para salvar meta oficial."""
    prop = resolve_meta_mensal_proporcao(selecao_inicio, selecao_fim)
    return prop.mes_inicio, prop.mes_fim

_LOAD_LATEST_SQL = """
SELECT *
FROM bi.vw_metas_funil_reconecta
WHERE periodo_tipo = :periodo_tipo
  AND periodo_inicio = CAST(:periodo_inicio AS DATE)
  AND periodo_fim = CAST(:periodo_fim AS DATE)
ORDER BY
  versao_meta DESC NULLS LAST,
  atualizado_em DESC NULLS LAST,
  criado_em DESC NULLS LAST,
  id DESC
LIMIT 1
"""

_LOAD_SQL = _LOAD_LATEST_SQL

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
    pct = pct_to_display_percent(raw)
    if pct > 0:
        return pct
    montante = float(
        _get_first_from_reference(row, ["montante", "montante_meta"]) or 0,
    )
    receita = float(
        _get_first_from_reference(row, ["receita", "receita_meta"]) or 0,
    )
    if montante <= 0:
        vendas = float(_get_first_from_reference(row, ["vendas", "vendas_meta"]) or 0)
        ticket = float(_get_first_from_reference(row, ["ticket_medio", "ticket"]) or 0)
        if vendas > 0 and ticket > 0:
            montante = vendas * ticket
    if montante > 0 and receita > 0:
        return receita / montante * 100.0
    return 0.0


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


def _meta_historico_row_from_db(raw: Any) -> dict[str, Any]:
    """Linha da view → dict compatível com referências do funil."""
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
    return {
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
        "investimento_mes": metas["investimento"],
        "investimento": metas["investimento"],
        "custo_por_lead": metas["custo_lead"],
        "custo_lead": metas["custo_lead"],
        "leads": _optional_float(raw, "leads_meta") or calc["leads"],
        "leads_meta": _optional_float(raw, "leads_meta") or calc["leads"],
        "pct_lead_aplicacao": raw.get("pct_lead_aplicacao"),
        "pct_la": metas["pct_la"],
        "aplicacoes": _optional_float(raw, "aplicacoes_meta") or calc["aplicacoes"],
        "aplicacoes_meta": _optional_float(raw, "aplicacoes_meta") or calc["aplicacoes"],
        "pct_aplicacao_agendamento": raw.get("pct_aplicacao_agendamento"),
        "pct_a_ag": metas["pct_a_ag"],
        "agendamentos": _optional_float(raw, "agendamentos_meta") or calc["agendamentos"],
        "agendamentos_meta": _optional_float(raw, "agendamentos_meta") or calc["agendamentos"],
        "pct_agendamento_comparecimento": raw.get("pct_agendamento_comparecimento"),
        "pct_ag_c": metas["pct_ag_c"],
        "comparecimento": (
            _optional_float(raw, "comparecimentos_meta") or calc["comparecimento"]
        ),
        "comparecimentos_meta": (
            _optional_float(raw, "comparecimentos_meta") or calc["comparecimento"]
        ),
        "pct_comparecimento_venda": raw.get("pct_comparecimento_venda"),
        "pct_c_v": metas["pct_c_v"],
        "vendas": _optional_float(raw, "vendas_meta") or calc["vendas"],
        "vendas_meta": _optional_float(raw, "vendas_meta") or calc["vendas"],
        "ticket_medio": metas["ticket"],
        "ticket": metas["ticket"],
        "montante_meta": montante,
        "montante": montante,
        "receita_meta": receita,
        "receita": receita,
        "pct_receita_sobre_montante": pct_recebimento,
        "pct_recebimento": pct_recebimento,
        "scenario": metas_dict_to_scenario(metas),
        "criado_em": raw.get("criado_em"),
        "atualizado_em": raw.get("atualizado_em"),
        "criado_por": raw.get("criado_por"),
        "observacao": raw.get("observacao"),
    }


def load_latest_meta_funil(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> dict[str, Any] | None:
    """Última meta oficial salva para o período (`bi.vw_metas_funil_reconecta`)."""
    return _load_latest_meta_funil_cached(
        periodo_tipo,
        periodo_inicio.isoformat(),
        periodo_fim.isoformat(),
    )


@st.cache_data(ttl=_META_CACHE_TTL, show_spinner=False)
def _load_latest_meta_funil_cached(
    periodo_tipo: str,
    periodo_inicio_iso: str,
    periodo_fim_iso: str,
) -> dict[str, Any] | None:
    return _load_latest_meta_funil_from_db(
        periodo_tipo,
        date.fromisoformat(periodo_inicio_iso),
        date.fromisoformat(periodo_fim_iso),
    )


def _load_latest_meta_funil_from_db(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> dict[str, Any] | None:
    """Leitura direta no banco de metas (sem cache Streamlit)."""
    if not is_metas_database_configured():
        return None
    params = {
        "periodo_tipo": periodo_tipo,
        "periodo_inicio": _as_date(periodo_inicio),
        "periodo_fim": _as_date(periodo_fim),
    }
    with get_metas_engine().connect() as conn:
        row = conn.execute(text(_LOAD_LATEST_SQL), params).mappings().first()
    if row is None:
        return None
    return _meta_historico_row_from_db(row)


def load_metas_funil_for_period(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> list[dict[str, Any]]:
    """Todas as metas oficiais do período, da mais recente para a mais antiga."""
    return list(
        _load_metas_funil_for_period_cached(
            periodo_tipo,
            periodo_inicio.isoformat(),
            periodo_fim.isoformat(),
        )
    )


@st.cache_data(ttl=_META_CACHE_TTL, show_spinner=False)
def _load_metas_funil_for_period_cached(
    periodo_tipo: str,
    periodo_inicio_iso: str,
    periodo_fim_iso: str,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        _load_metas_funil_for_period_from_db(
            periodo_tipo,
            date.fromisoformat(periodo_inicio_iso),
            date.fromisoformat(periodo_fim_iso),
        )
    )


def _load_metas_funil_for_period_from_db(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> list[dict[str, Any]]:
    if not is_metas_database_configured():
        return []
    sql = """
SELECT *
FROM bi.vw_metas_funil_reconecta
WHERE periodo_tipo = :periodo_tipo
  AND periodo_inicio = CAST(:periodo_inicio AS DATE)
  AND periodo_fim = CAST(:periodo_fim AS DATE)
ORDER BY
  versao_meta DESC NULLS LAST,
  atualizado_em DESC NULLS LAST,
  criado_em DESC NULLS LAST,
  id DESC
"""
    params = {
        "periodo_tipo": periodo_tipo,
        "periodo_inicio": _as_date(periodo_inicio),
        "periodo_fim": _as_date(periodo_fim),
    }
    df = run_metas_sql(sql, params)
    if df.empty:
        return []
    return [_meta_historico_row_from_db(raw) for _, raw in df.iterrows()]


def invalidate_funil_meta_load_cache() -> None:
    """Limpa cache de leitura após salvar/excluir meta oficial."""
    _load_latest_meta_funil_cached.clear()
    _load_metas_funil_for_period_cached.clear()


def meta_latest_cache_hits() -> int | None:
    """Hits do cache de `load_latest_meta_funil` (None se indisponível)."""
    try:
        return int(_load_latest_meta_funil_cached.get_stats().hits)
    except (AttributeError, TypeError):
        return None


def meta_cache_hit_between(before: int | None, after: int | None) -> bool:
    if before is None or after is None:
        return False
    return after > before


def meta_load_cache_stats() -> dict[str, int]:
    """Hits/misses do cache de leitura (para benchmark/debug)."""
    try:
        latest = _load_latest_meta_funil_cached.get_stats()
        period = _load_metas_funil_for_period_cached.get_stats()
        return {
            "latest_hits": int(latest.hits),
            "latest_misses": int(latest.misses),
            "period_hits": int(period.hits),
            "period_misses": int(period.misses),
        }
    except (AttributeError, TypeError):
        return {
            "latest_hits": 0,
            "latest_misses": 0,
            "period_hits": 0,
            "period_misses": 0,
        }


def load_latest_meta_funil_mensal(
    selecao_inicio: date,
    selecao_fim: date,
) -> tuple[dict[str, Any] | None, MetaMensalProporcao]:
    """Última meta mensal oficial, proporcional ao recorte selecionado."""
    prop = resolve_meta_mensal_proporcao(selecao_inicio, selecao_fim)
    if prop.multi_mes:
        return None, prop

    row: dict[str, Any] | None = None
    for tipo in (PERIODO_TIPO_META_MENSAL, *LEGACY_PERIODO_TIPOS):
        row = load_latest_meta_funil(tipo, prop.mes_inicio, prop.mes_fim)
        if row is not None:
            break
    if row is None:
        for tipo in (PERIODO_TIPO_META_MENSAL, *LEGACY_PERIODO_TIPOS):
            legacy = load_latest_meta_funil(
                tipo, prop.selecao_inicio, prop.selecao_fim,
            )
            if legacy is not None:
                legacy["meta_mensal_proporcao"] = prop
                return legacy, prop
        return None, prop

    scaled = scale_meta_row_to_selection(row, prop.fator)
    scaled["meta_mensal_proporcao"] = prop
    scaled["meta_mensal_row"] = row
    return scaled, prop


def load_metas_funil_mensal_for_selection(
    selecao_inicio: date,
    selecao_fim: date,
) -> tuple[list[dict[str, Any]], MetaMensalProporcao]:
    """Metas mensais oficiais do mês de referência (valores mensais completos)."""
    prop = resolve_meta_mensal_proporcao(selecao_inicio, selecao_fim)
    if prop.multi_mes:
        return [], prop

    rows: list[dict[str, Any]] = []
    for tipo in (PERIODO_TIPO_META_MENSAL, *LEGACY_PERIODO_TIPOS):
        rows = load_metas_funil_for_period(tipo, prop.mes_inicio, prop.mes_fim)
        if rows:
            break
    return rows, prop


def prepare_meta_row_for_selection(
    row: dict[str, Any],
    selecao_inicio: date,
    selecao_fim: date,
) -> dict[str, Any]:
    """Meta mensal de referência → valores proporcionais ao filtro atual."""
    prop = resolve_meta_mensal_proporcao(selecao_inicio, selecao_fim)
    if prop.multi_mes:
        return dict(row)
    scaled = scale_meta_row_to_selection(row, prop.fator)
    scaled["meta_mensal_proporcao"] = prop
    scaled["meta_mensal_row"] = row
    return scaled


def load_funil_meta(
    periodo_tipo: str,
    periodo_inicio: date,
    periodo_fim: date,
) -> tuple[dict[str, float], float] | None:
    """Carrega metas oficiais do período ou None se não houver registro.

    Retorna `(cenário, pct_recebimento)` com financeiro resolvido por fallback.
    """
    row = load_latest_meta_funil(periodo_tipo, periodo_inicio, periodo_fim)
    if row is None:
        return None
    metas = _row_to_metas_dict_from_historico(row)
    pct_recebimento = float(row.get("pct_recebimento") or 0)
    return metas, pct_recebimento


def _row_to_metas_dict_from_historico(row: dict[str, Any]) -> dict[str, float]:
    scenario = row.get("scenario")
    if isinstance(scenario, dict):
        return {
            "investimento": float(scenario["investimento"]),
            "custo_lead": float(scenario["custo_lead"]),
            "pct_la": float(scenario["pct_la"]),
            "pct_a_ag": float(scenario["pct_a_ag"]),
            "pct_ag_c": float(scenario["pct_ag_c"]),
            "pct_c_v": float(scenario["pct_c_v"]),
            "ticket": float(scenario["ticket"]),
        }
    return _row_to_metas_dict(row)


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
    invalidate_funil_meta_load_cache()
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
        rows.append(_meta_historico_row_from_db(raw))
    return rows


def delete_meta_funil(meta_id: int) -> int:
    """Remove meta oficial (`DELETE` direto em `bi.metas_funil_reconecta`)."""
    if not is_metas_database_configured():
        raise MetasDatabaseNotConfiguredError(
            "METAS_DATABASE_URL não configurada."
        )
    deleted = execute_metas_sql_rowcount(_DELETE_SQL, {"id": int(meta_id)})
    if deleted > 0:
        invalidate_funil_meta_load_cache()
    return deleted


__all__ = [
    "MetasDatabaseNotConfiguredError",
    "MetaMensalProporcao",
    "PERIODO_TIPO_PADRAO",
    "PERIODO_TIPO_META_MENSAL",
    "LEGACY_PERIODO_TIPOS",
    "is_metas_database_configured",
    "days_inclusive",
    "first_day_of_month",
    "is_single_calendar_month",
    "last_day_of_month",
    "load_funil_meta",
    "load_latest_meta_funil",
    "load_latest_meta_funil_mensal",
    "load_metas_funil_for_period",
    "load_metas_funil_mensal_for_selection",
    "load_metas_funil_historico",
    "invalidate_funil_meta_load_cache",
    "meta_latest_cache_hits",
    "meta_cache_hit_between",
    "meta_load_cache_stats",
    "monthly_save_bounds",
    "prepare_meta_row_for_selection",
    "resolve_meta_mensal_proporcao",
    "scale_meta_row_to_selection",
    "scale_meta_save_payload_to_monthly",
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
