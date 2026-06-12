"""Funil da Reconecta — Simulador de cenários do funil comercial.

O cenário **Atual** usa dados reais do período (mesmas regras da One Page).
Simulador e Meta continuam paramétricos para simulação e metas.

Estrutura:
  1. Header (título + filtro de período global + ações)
  2. Toggle de visualização (Mês / Semana / Dia)
  3. Alerta de gargalo crítico (Atual vs Meta)
  4. Vitrine: grade sincronizada (Atual · Simulador · Meta)
  5. Cards de "Gap até a meta"
  6. Comparativo Simulador vs Atual
  7. Exportação (CSV / Excel / PDF)
  8. Editor de metas (rascunho + aplicar oficiais no banco)

Períodos de visualização: semana = total ÷ 4; dia = total ÷ 28.
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from src.funil_export import (
    FunilExportBundle,
    export_funil_csv,
    export_funil_excel,
    export_funil_pdf,
)
from src.funil_benchmark import (
    BENCHMARK_METRIC_SPECS,
    HISTORICO_PERIODOS,
    classify_realism,
    compute_funil_benchmark,
    resolve_historical_window,
    scenario_field_value,
)
from src.funil_historico import (
    historico_row_by_index,
    historico_rows_to_display_df,
    load_funil_historico_referencias,
)
from src.funil_meta_store import (
    PERIODO_TIPO_PADRAO,
    MetasDatabaseNotConfiguredError,
    is_metas_database_configured,
    load_funil_meta,
    load_metas_funil_historico,
    metas_dict_from_scenario,
    metas_dict_to_scenario,
    pct_to_display_percent,
    save_funil_meta,
    soft_delete_meta_funil,
)
from src.metas_auth import (
    METAS_VIEW_ONLY_MESSAGE,
    is_metas_editor_authenticated,
    render_metas_editor_gate,
)
from src.one_page_funnel import (
    FunnelSnapshot,
    load_one_page_funnel,
    project_receita_from_montante,
    snapshot_calc_display,
    snapshot_to_scenario_dict,
)
from src.ui.components import section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl as brl_global, int_br


# =============================================================================
# Modelo
# =============================================================================

@dataclass
class Scenario:
    investimento: float
    custo_lead: float
    pct_la: float    # Lead → Aplicação
    pct_a_ag: float  # Aplicação → Agendamento
    pct_ag_c: float  # Agendamento → Comparecimento
    pct_c_v: float   # Comparecimento → Venda
    ticket: float


# Fallback quando a carga do banco falha.
_BASE_ATUAL = Scenario(
    investimento=115140.74,
    custo_lead=113.55,
    pct_la=0.5069,
    pct_a_ag=0.762,
    pct_ag_c=0.50,
    pct_c_v=0.2094,
    ticket=21400.0,
)
_BASE_META = Scenario(
    investimento=115140.74,
    custo_lead=70.0,
    pct_la=0.80,
    pct_a_ag=0.80,
    pct_ag_c=0.70,
    pct_c_v=0.25,
    ticket=25000.0,
)


# Períodos — divisores aplicados sobre os valores mensais.
PERIODOS = {
    "mes":    {"label": "Mês",    "divisor": 1},
    "semana": {"label": "Semana", "divisor": 4},
    "dia":    {"label": "Dia",    "divisor": 28},
}


# Rótulos por etapa (key, label, anterior→resultado) — usado pelo gargalo.
ETAPAS = [
    ("pct_la",   "Lead → Aplicação"),
    ("pct_a_ag", "Aplicação → Agendamento"),
    ("pct_ag_c", "Agendamento → Comparecimento"),
    ("pct_c_v",  "Comparecimento → Venda"),
]


# =============================================================================
# Cálculos
# =============================================================================

def calcular_funil(
    s: Scenario,
    periodo: str,
    *,
    pct_recebimento: float = 0.0,
) -> dict:
    """Cascata do funil para o período escolhido (valores contínuos internos)."""
    div = PERIODOS[periodo]["divisor"]
    investimento = s.investimento / div
    leads = investimento / s.custo_lead if s.custo_lead > 0 else 0.0
    aplicacoes = leads * s.pct_la
    agendamentos = aplicacoes * s.pct_a_ag
    comparecimento = agendamentos * s.pct_ag_c
    vendas = comparecimento * s.pct_c_v
    montante = vendas * s.ticket
    receita = project_receita_from_montante(montante, pct_recebimento)
    return {
        "investimento":   investimento,
        "leads":          leads,
        "aplicacoes":     aplicacoes,
        "agendamentos":   agendamentos,
        "comparecimento": comparecimento,
        "vendas":         vendas,
        "montante":       montante,
        "receita":        receita,
    }


def calcular_funil_exibicao(
    s: Scenario,
    periodo: str,
    *,
    pct_recebimento: float = 0.0,
) -> dict:
    """Volumes para tela/export (Simulador e Meta).

    Vendas são arredondadas para inteiro; montante usa o mesmo inteiro
    × ticket — evita «Vendas = 0» com montante > 0 por fração decimal.
    Receita projetada aplica o % recebimento do período (regra visão geral).
    """
    calc = calcular_funil(s, periodo, pct_recebimento=pct_recebimento)
    vendas_int = int(round(calc["vendas"]))
    montante = float(vendas_int) * float(s.ticket)
    return {
        **calc,
        "vendas": float(vendas_int),
        "montante": montante,
        "receita": project_receita_from_montante(montante, pct_recebimento),
    }


def _calc_atual_para_tela(
    snapshot: FunnelSnapshot | None,
    atual_s: Scenario,
    periodo: str,
) -> dict:
    """Atual na escala da visualização; vendas inteiras; montante e receita reais."""
    if snapshot is not None:
        calc = snapshot_calc_display(snapshot, periodo, PERIODOS)
        vendas_int = int(round(calc["vendas"]))
        return {**calc, "vendas": float(vendas_int)}
    return calcular_funil_exibicao(atual_s, periodo)


def _gargalo_impacto_exibicao(impacto_mensal: float, periodo: str) -> float:
    """Escala o impacto mensal para a visualização Mês / Semana / Dia."""
    return float(impacto_mensal) / PERIODOS[periodo]["divisor"]


# Simulador — edição por taxa ou por volume (pares de etapas)
_SIM_EDIT_STAGES = ("leads", "la", "a_ag", "ag_c", "c_v")
_SIM_STAGE_VOLUME_FIELD = {
    "leads": "leads",
    "la": "aplicacoes",
    "a_ag": "agendamentos",
    "ag_c": "comparecimento",
    "c_v": "vendas",
}
_SIM_STAGE_PCT_FIELD = {
    "la": "pct_la",
    "a_ag": "pct_a_ag",
    "ag_c": "pct_ag_c",
    "c_v": "pct_c_v",
}
_DEFAULT_SIM_EDIT_MODES: dict[str, str] = {
    "leads": "derivado",
    "la": "taxa",
    "a_ag": "taxa",
    "ag_c": "taxa",
    "c_v": "taxa",
}
_DEFAULT_META_EDIT_MODES: dict[str, str] = dict(_DEFAULT_SIM_EDIT_MODES)


def _sim_mode_options(stage: str) -> tuple[tuple[str, ...], str]:
    if stage == "leads":
        return ("derivado", "volume"), "derivado"
    return ("taxa", "volume"), "taxa"


def _coerce_sim_mode_value(stage: str, value: object) -> str:
    """Converte valor legado (ex.: índice 0) para 'taxa' | 'volume' | 'derivado'."""
    options, fallback = _sim_mode_options(stage)
    if value in options:
        return str(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        idx = int(value)
        if 0 <= idx < len(options):
            return options[idx]
    return fallback


def _sim_mode_widget_key(key_prefix: str, stage: str) -> str:
    return f"{key_prefix}_edit_mode_select_{stage}"


def _modes_key_for_prefix(key_prefix: str) -> str:
    return (
        "funil_meta_edit_modes"
        if key_prefix == "meta_cfg"
        else "funil_sim_edit_modes"
    )


def _purge_legacy_sim_mode_widget_keys() -> None:
    """Remove keys antigas de toggles/segmented (antes de qualquer widget)."""
    for k in list(st.session_state.keys()):
        if not isinstance(k, str):
            continue
        if k.startswith("simulador_mode_"):
            del st.session_state[k]
        elif (
            k.startswith("simulador_edit_mode_")
            and not k.startswith("simulador_edit_mode_select_")
        ):
            del st.session_state[k]


def _sanitize_sim_edit_modes() -> None:
    """Sanitiza apenas o dict interno — nunca keys de widget após render."""
    if "funil_sim_edit_modes" not in st.session_state:
        st.session_state["funil_sim_edit_modes"] = dict(_DEFAULT_SIM_EDIT_MODES)
    modes = st.session_state["funil_sim_edit_modes"]
    for stage in _SIM_EDIT_STAGES:
        modes[stage] = _coerce_sim_mode_value(stage, modes.get(stage))


def _sanitize_edit_modes(modes_key: str, default: dict[str, str]) -> None:
    if modes_key not in st.session_state:
        st.session_state[modes_key] = dict(default)
    modes = st.session_state[modes_key]
    for stage in _SIM_EDIT_STAGES:
        modes[stage] = _coerce_sim_mode_value(stage, modes.get(stage))


def _ensure_sim_edit_modes() -> dict[str, str]:
    """Chamar uma vez no topo do rerun, antes de widgets do simulador."""
    _purge_legacy_sim_mode_widget_keys()
    _sanitize_sim_edit_modes()
    return st.session_state["funil_sim_edit_modes"]


def _ensure_meta_edit_modes() -> dict[str, str]:
    _sanitize_edit_modes("funil_meta_edit_modes", _DEFAULT_META_EDIT_MODES)
    return st.session_state["funil_meta_edit_modes"]


def _sim_edit_mode_for_stage(
    stage: str,
    key_prefix: str = "simulador",
    *,
    modes_key: str = "funil_sim_edit_modes",
    default_modes: dict[str, str] | None = None,
) -> str:
    """Modo ativo da etapa (lê widget se já existir no session_state)."""
    options, fallback = _sim_mode_options(stage)
    wkey = _sim_mode_widget_key(key_prefix, stage)
    if wkey in st.session_state:
        return _coerce_sim_mode_value(stage, st.session_state[wkey])
    base = default_modes or (
        _DEFAULT_META_EDIT_MODES
        if modes_key == "funil_meta_edit_modes"
        else _DEFAULT_SIM_EDIT_MODES
    )
    modes = st.session_state.get(modes_key, base)
    return _coerce_sim_mode_value(stage, modes.get(stage, fallback))


def _safe_ratio(num: float, den: float) -> float:
    d = float(den or 0)
    if d <= 0:
        return 0.0
    return max(0.0, float(num or 0) / d)


def _apply_sim_volume_mensal(stage: str, volume_mensal: float, state: dict) -> None:
    """Ajusta taxas (ou CPL) para atingir o volume mensal informado."""
    vol = max(0.0, float(volume_mensal))
    base = calcular_funil(Scenario(**state), "mes")
    if stage == "leads":
        inv = float(state["investimento"])
        if vol > 0:
            state["custo_lead"] = inv / vol
        return
    pct_key = _SIM_STAGE_PCT_FIELD.get(stage)
    if not pct_key:
        return
    upstream = {
        "la": base["leads"],
        "a_ag": base["aplicacoes"],
        "ag_c": base["agendamentos"],
        "c_v": base["comparecimento"],
    }.get(stage, 0.0)
    state[pct_key] = _safe_ratio(vol, upstream)


def _apply_scenario_edits_from_session(
    state: dict,
    periodo: str,
    div: int,
    key_prefix: str,
    *,
    modes_key: str = "funil_sim_edit_modes",
    default_modes: dict[str, str] | None = None,
) -> None:
    """Lê widgets do rerun anterior e atualiza o cenário em session_state."""
    rows = _vitrine_row_specs(periodo)

    for spec in rows:
        if spec.get("sim_stage") is None and spec.get("sim_editable"):
            wkey = _sim_widget_key(spec, key_prefix)
            if wkey in st.session_state:
                _apply_sim_editable(
                    spec, state, float(st.session_state[wkey]), div=div,
                )

    for stage in _SIM_EDIT_STAGES:
        smode = _sim_edit_mode_for_stage(
            stage,
            key_prefix,
            modes_key=modes_key,
            default_modes=default_modes,
        )
        if stage == "leads":
            if smode == "volume":
                wkey = f"{key_prefix}_vol_{stage}"
                if wkey in st.session_state:
                    _apply_sim_volume_mensal(
                        stage, float(st.session_state[wkey]) * div, state,
                    )
            continue
        if smode == "volume":
            wkey = f"{key_prefix}_vol_{stage}"
            if wkey in st.session_state:
                _apply_sim_volume_mensal(
                    stage, float(st.session_state[wkey]) * div, state,
                )
        elif smode == "taxa":
            pct_spec_id = {
                "la": "pct_la",
                "a_ag": "pct_a_ag",
                "ag_c": "pct_ag_c",
                "c_v": "pct_c_v",
            }.get(stage)
            if pct_spec_id:
                wkey = _sim_widget_key({"id": pct_spec_id}, key_prefix)
                if wkey in st.session_state:
                    raw = float(st.session_state[wkey])
                    field = _SIM_STAGE_PCT_FIELD[stage]
                    state[field] = raw / 100.0


def _apply_simulator_from_session(
    sim_state: dict,
    periodo: str,
    div: int,
    key_prefix: str,
) -> None:
    _apply_scenario_edits_from_session(
        sim_state, periodo, div, key_prefix,
    )


def _pct_recebimento_snapshot(snapshot: FunnelSnapshot | None) -> float:
    if snapshot is None:
        return 0.0
    return float(snapshot.pct_recebimento)


def identificar_gargalos(
    atual: Scenario,
    meta: Scenario,
    *,
    pct_recebimento: float = 0.0,
) -> list[dict]:
    """Etapas ordenadas pelo ganho em montante projetado (base mensal).

    Para cada etapa abaixo da meta, simula só aquela taxa no nível da meta
    (demais parâmetros do Atual iguais) e mede Δ montante no mês inteiro.
    A UI escala esse valor pela visualização (÷ 4 / ÷ 28).
    """
    base_fat = calcular_funil(atual, "mes", pct_recebimento=pct_recebimento)["montante"]
    impactos: list[dict] = []

    for key, label in ETAPAS:
        atual_val = getattr(atual, key)
        meta_val = getattr(meta, key)
        if atual_val >= meta_val:
            impactos.append({
                "key": key, "label": label, "impacto": 0.0,
                "atual": atual_val, "meta": meta_val, "is_money": False,
            })
            continue
        hipo = Scenario(**{**asdict(atual), key: meta_val})
        novo = calcular_funil(hipo, "mes", pct_recebimento=pct_recebimento)["montante"]
        impactos.append({
            "key": key, "label": label, "impacto": novo - base_fat,
            "atual": atual_val, "meta": meta_val, "is_money": False,
        })

    if atual.custo_lead > meta.custo_lead:
        hipo = Scenario(**{**asdict(atual), "custo_lead": meta.custo_lead})
        novo = calcular_funil(hipo, "mes", pct_recebimento=pct_recebimento)["montante"]
        impactos.append({
            "key": "custo_lead", "label": "Custo por Lead",
            "impacto": novo - base_fat,
            "atual": atual.custo_lead, "meta": meta.custo_lead,
            "is_money": True,
        })
    if atual.ticket < meta.ticket:
        hipo = Scenario(**{**asdict(atual), "ticket": meta.ticket})
        novo = calcular_funil(hipo, "mes", pct_recebimento=pct_recebimento)["montante"]
        impactos.append({
            "key": "ticket", "label": "Ticket Médio",
            "impacto": novo - base_fat,
            "atual": atual.ticket, "meta": meta.ticket,
            "is_money": True,
        })
    impactos.sort(key=lambda x: x["impacto"], reverse=True)
    return impactos


# =============================================================================
# Formatadores BR
# =============================================================================

def brl(v: float, casas: int = 2) -> str:
    return brl_global(v, casas=casas)


def pct_fmt(v: float, casas: int = 2) -> str:
    """Taxa em fração (0–1+) → exibição com % e duas casas (pt-BR)."""
    pct_val = v * 100
    s = f"{pct_val:,.{casas}f}%".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _pct_ratio_txt(numerator: float, denominator: float) -> str | None:
    """Quociente num/den formatado em % (2 casas), ou None se den ≤ 0."""
    den = float(denominator or 0)
    if den <= 0:
        return None
    return pct_fmt(float(numerator or 0) / den)


def _fatu_chips_html(chips: list[str]) -> str:
    """Área fixa de chips — mantém altura mesmo sem informação complementar."""
    inner = "".join(
        f'<span class="fr-fatu-chip">{html.escape(text)}</span>'
        for text in chips
    )
    return f'<div class="fr-fatu-chips">{inner}</div>'


def format_display_value(
    value: float,
    *,
    is_money: bool = False,
    is_percent: bool = False,
) -> str:
    """Formata valor para exibição na vitrine (sem alterar o valor interno)."""
    value = float(value or 0)
    if is_money:
        return brl(value)
    if is_percent:
        return pct_fmt(value)
    return int_br(value)


def _format_vitrine_value(rid: str, value: float) -> str:
    if rid in ("inv", "cl", "ticket"):
        return format_display_value(value, is_money=True)
    if rid in ("pct_la", "pct_a_ag", "pct_ag_c", "pct_c_v"):
        return format_display_value(value, is_percent=True)
    return format_display_value(value)


_SPEC_ID_TO_BENCHMARK_KEY: dict[str, str] = {
    "cl": "custo_lead",
    "pct_la": "pct_la",
    "pct_a_ag": "pct_a_ag",
    "pct_ag_c": "pct_ag_c",
    "pct_c_v": "pct_c_v",
    "ticket": "ticket",
}


def _format_benchmark_value(kind: str, value: float | None) -> str:
    if value is None:
        return "—"
    if kind == "money":
        return brl(float(value))
    return pct_fmt(float(value))


def _scenario_metric_value(s: Scenario, key: str) -> float:
    return float(getattr(s, key))


def _label_with_realism_badge(
    label: str,
    *,
    spec_id: str | None,
    value: float,
    benchmark_metrics: dict[str, dict[str, Any]] | None,
) -> str:
    """Label com badge de realismo (Simulador) quando há benchmark."""
    base = html.escape(label)
    if not spec_id or not benchmark_metrics:
        return base
    bkey = _SPEC_ID_TO_BENCHMARK_KEY.get(spec_id)
    if not bkey or bkey not in benchmark_metrics:
        return base
    bm = benchmark_metrics[bkey]
    text, cls = classify_realism(
        value,
        float(bm["mean"]),
        higher_is_better=bool(bm["higher_is_better"]),
    )
    if cls == "neutral":
        return base
    return (
        f'{base}<span class="fr-realism fr-realism-{html.escape(cls)}" '
        f'title="{html.escape(text)}">{html.escape(text)}</span>'
    )


def _apply_benchmark_scenario_to_sim(
    benchmark_metrics: dict[str, dict[str, Any]],
    mode: str,
) -> None:
    """Preenche o Simulador com cenário conservador / provável / otimista."""
    sim = dict(st.session_state.get("funil_simulador", {}))
    inv = sim.get("investimento")
    for key, _label, _hib, _kind in BENCHMARK_METRIC_SPECS:
        metric = benchmark_metrics.get(key)
        if metric:
            sim[key] = scenario_field_value(metric, mode)
    if inv is not None:
        sim["investimento"] = inv
    st.session_state["funil_simulador"] = sim


def _render_benchmark_historico(
    benchmark_raw: dict[str, Any],
    *,
    snapshot: FunnelSnapshot | None,
    atual_s: Scenario,
    meta_s: Scenario,
) -> None:
    """Seção Benchmark histórico + botões de cenário."""
    section_title(
        "Benchmark histórico",
        "Referência calculada com base no histórico selecionado.",
    )
    err = benchmark_raw.get("error")
    if err:
        st.info(err)
        return

    metrics = benchmark_raw.get("metrics") or {}
    if not metrics:
        st.info("Sem métricas históricas para o intervalo.")
        return

    hist_ini = date.fromisoformat(benchmark_raw["hist_ini"])
    hist_fim = date.fromisoformat(benchmark_raw["hist_fim"])
    st.caption(
        f'Janela: {hist_ini.strftime("%d/%m/%Y")} – {hist_fim.strftime("%d/%m/%Y")} '
        f'({benchmark_raw.get("monthly_count", 0)} mês(es) com dados). '
        "Mesmas regras da One Page e do Atual."
    )

    rows: list[dict[str, str]] = []
    for key, label, _hib, kind in BENCHMARK_METRIC_SPECS:
        bm = metrics.get(key, {})
        atual_val = (
            _scenario_metric_value(
                Scenario(**snapshot_to_scenario_dict(snapshot)), key,
            )
            if snapshot is not None
            else _scenario_metric_value(atual_s, key)
        )
        meta_val = _scenario_metric_value(meta_s, key)
        rows.append({
            "Métrica": label,
            "Média histórica": _format_benchmark_value(kind, bm.get("mean")),
            "Mediana": _format_benchmark_value(kind, bm.get("median")),
            "P75": _format_benchmark_value(kind, bm.get("p75")),
            "Melhor período": (
                f'{_format_benchmark_value(kind, bm.get("best"))} '
                f'({bm.get("best_period", "—")})'
            ),
            "Pior período": (
                f'{_format_benchmark_value(kind, bm.get("worst"))} '
                f'({bm.get("worst_period", "—")})'
            ),
            "Atual": _format_benchmark_value(kind, atual_val),
            "Meta da tela": _format_benchmark_value(kind, meta_val),
        })

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Métrica": st.column_config.TextColumn(width="medium"),
        },
    )

    st.markdown("**Cenários no Simulador**")
    b1, b2, b3, _ = st.columns([2, 2, 2, 3], gap="small")
    with b1:
        if st.button("Aplicar cenário conservador", use_container_width=True):
            _apply_benchmark_scenario_to_sim(metrics, "conservador")
            _clear_funil_widget_keys(sim_only=True)
            st.rerun()
    with b2:
        if st.button("Aplicar cenário provável", use_container_width=True):
            _apply_benchmark_scenario_to_sim(metrics, "provavel")
            _clear_funil_widget_keys(sim_only=True)
            st.rerun()
    with b3:
        if st.button("Aplicar cenário otimista", use_container_width=True):
            _apply_benchmark_scenario_to_sim(metrics, "otimista")
            _clear_funil_widget_keys(sim_only=True)
            st.rerun()
    st.caption(
        "Conservador: ~90% das taxas (ou CPL +10%). Provável: mediana histórica. "
        "Otimista: P75 nas taxas (ou P25 no CPL). Investimento do simulador não muda."
    )


# =============================================================================
# CSS local
# =============================================================================

_FUNIL_CSS = """
<style>
.fr-card {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
    margin-bottom: 14px;
}
.fr-card-head {
    padding: 10px 14px;
    color: #ffffff;
    border-bottom: 1px solid var(--color-border-strong);
}
.fr-card-head h3 {
    margin: 0 !important;
    font-size: 1.05rem;
    font-weight: 700;
    color: #ffffff !important;
    letter-spacing: 0.2px;
}
.fr-card-head .fr-period {
    font-size: 0.7rem;
    opacity: 0.85;
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.fr-card-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 14px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    gap: 10px;
}
.fr-card-row:last-child { border-bottom: 0; }
.fr-card-row .lbl {
    font-size: 0.72rem;
    color: var(--color-text-subtle);
    font-weight: 500;
}
.fr-card-row .lbl.indent { padding-left: 14px; opacity: 0.85; }
.fr-card-row .lbl.bold   { color: var(--color-text); font-weight: 700; }
.fr-card-row .val {
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--color-text);
    font-variant-numeric: tabular-nums;
    text-align: right;
}
.fr-card-row .val.computed { color: var(--color-gold); }
.fr-card-row.highlight {
    background: rgba(201, 168, 76, 0.05);
}
/* Vitrine — linhas com altura fixa (Atual · Simulador · Meta alinhados) */
.fr-vitrine-body {
    margin-bottom: 0;
}
.fr-vitrine-body .fr-card-row,
.fr-vitrine-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 0 12px 0 6px;
    height: 32px;
    min-height: 32px;
    max-height: 32px;
    box-sizing: border-box;
    border-bottom: none;
    margin: 0;
    overflow: hidden;
}
.fr-vitrine-row .lbl-chip {
    display: inline-flex;
    align-items: center;
    flex: 1 1 auto;
    min-width: 0;
    max-width: 64%;
    padding: 0 8px 0 4px;
    margin: 0;
    border: none;
    border-radius: 0;
    background: linear-gradient(
        90deg,
        rgba(255, 255, 255, 0.035) 0%,
        rgba(255, 255, 255, 0.01) 55%,
        transparent 100%
    );
    box-shadow: none;
    font-size: 0.7rem;
    font-weight: 600;
    color: rgba(200, 200, 205, 0.88);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
    letter-spacing: 0.015em;
}
.fr-vitrine-cell.col-sim .lbl-chip,
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.col-sim) .lbl-chip {
    color: rgba(215, 208, 195, 0.9);
    background: linear-gradient(
        90deg,
        rgba(201, 168, 76, 0.05) 0%,
        transparent 70%
    );
}
.fr-vitrine-row.highlight .lbl-chip {
    color: rgba(225, 215, 195, 0.92);
}
.fr-vitrine-body .fr-card-row .val,
.fr-vitrine-row .val {
    flex: 0 0 auto;
    white-space: nowrap;
    padding-right: 2px;
}
.fr-vitrine-row .val.static {
    color: rgba(255, 255, 255, 0.97);
    font-weight: 700;
    font-size: 0.86rem;
}
.fr-vitrine-row .val.computed {
    color: rgba(218, 195, 130, 0.98);
    font-weight: 700;
    font-size: 0.86rem;
    text-shadow: 0 0 10px rgba(201, 168, 76, 0.1);
}
.fr-vitrine-row.highlight {
    background: linear-gradient(
        90deg,
        rgba(201, 168, 76, 0.05) 0%,
        rgba(201, 168, 76, 0.015) 50%,
        transparent 100%
    );
}
.fr-card.fr-fatu-card {
    border: none;
    background: transparent;
    box-shadow: none;
    margin: 0;
    overflow: visible;
}
.fr-fatu {
    background: linear-gradient(
        155deg,
        rgba(198, 172, 112, 0.68) 0%,
        rgba(186, 158, 92, 0.62) 50%,
        rgba(168, 140, 78, 0.66) 100%
    );
    color: var(--color-wine);
    padding: 11px 13px 10px;
    min-height: 6.35rem;
    height: 6.35rem;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    box-sizing: border-box;
    border-radius: 7px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.2),
        0 2px 8px rgba(0, 0, 0, 0.12);
}
.fr-fatu--receita {
    min-height: 7.85rem;
    height: 7.85rem;
}
.fr-fatu-main { flex: 0 0 auto; }
.fr-fatu .lbl {
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: rgba(58, 24, 32, 0.58);
}
.fr-fatu .val {
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-size: 1.28rem;
    font-weight: 700;
    margin-top: 3px;
    color: rgba(48, 20, 30, 0.9);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.015em;
    line-height: 1.15;
}
.fr-fatu-chips {
    flex: 1 1 auto;
    min-height: 1.85rem;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: flex-end;
    align-content: flex-end;
    margin-top: auto;
    padding-top: 5px;
}
.fr-fatu--receita .fr-fatu-chips { min-height: 2.95rem; }
.fr-fatu-chip {
    display: inline-block;
    font-size: 0.82rem;
    font-weight: 700;
    line-height: 1.1;
    padding: 0.28rem 0.55rem;
    border-radius: 999px;
    background: rgba(48, 20, 30, 0.16);
    color: rgba(38, 14, 24, 0.94);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    letter-spacing: 0.01em;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.22);
}
.fr-fatu-stack { display: flex; flex-direction: column; gap: 8px; }
.fr-fatu.receita {
    background: linear-gradient(
        155deg,
        rgba(92, 0, 30, 0.72) 0%,
        rgba(108, 18, 42, 0.66) 50%,
        rgba(124, 32, 54, 0.7) 100%
    );
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.1);
}
.fr-fatu.receita .lbl { color: rgba(255, 255, 255, 0.72); }
.fr-fatu.receita .val { color: #ffffff; }
.fr-fatu.receita .fr-fatu-chip {
    background: rgba(255, 255, 255, 0.22);
    color: #ffffff;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28);
}

/* Alerta de gargalo */
.fr-alert {
    background: linear-gradient(135deg, var(--color-wine) 0%, var(--color-wine-soft) 100%);
    border: 2px solid rgba(201, 168, 76, 0.35);
    border-radius: 10px;
    padding: 16px 20px;
    color: #ffffff;
    margin-bottom: 18px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}
.fr-alert.healthy {
    background: var(--color-green-soft);
    border-color: var(--color-green);
}
.fr-alert .kicker {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--color-gold);
}
.fr-alert.healthy .kicker { color: var(--color-green); }
.fr-alert h4 {
    margin: 4px 0 !important;
    font-size: 1.35rem;
    color: #ffffff !important;
    font-weight: 700;
}
.fr-alert.healthy h4 { color: var(--color-green) !important; }
.fr-alert .grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin-top: 12px;
}
.fr-alert .grid .k {
    font-size: 0.62rem;
    color: rgba(255, 255, 255, 0.7);
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.8px;
}
.fr-alert .grid .v {
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-weight: 700;
    color: #ffffff;
    font-variant-numeric: tabular-nums;
    font-size: 0.95rem;
}
.fr-alert .grid .v.accent { color: var(--color-gold); font-size: 1.1rem; }
.fr-alert .pri {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.18);
}
.fr-alert .pri-title {
    font-size: 0.65rem;
    color: rgba(255, 255, 255, 0.7);
    text-transform: uppercase;
    letter-spacing: 1.4px;
    font-weight: 700;
    margin-bottom: 8px;
}
.fr-alert .pri-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.85rem;
    padding: 3px 0;
}
.fr-alert .pri-row .left {
    display: flex; align-items: center; gap: 8px;
    color: #ffffff;
}
.fr-alert .pri-row .badge {
    width: 20px; height: 20px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.15);
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 0.7rem; font-weight: 700;
}
.fr-alert .pri-row .right {
    color: var(--color-gold);
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.fr-alert .note {
    font-size: 0.72rem;
    color: rgba(255, 255, 255, 0.75);
    margin-top: 10px;
    font-style: italic;
}

/* Gap cards */
.fr-gap {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    padding: 12px 14px;
}
.fr-gap .lbl {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--color-text-subtle);
    text-transform: uppercase;
    letter-spacing: 1.2px;
}
.fr-gap .row1 {
    display: flex; align-items: baseline; gap: 8px; margin-top: 4px;
}
.fr-gap .big {
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--color-gold);
    font-variant-numeric: tabular-nums;
}
.fr-gap .delta {
    font-size: 0.7rem;
    font-weight: 700;
}
.fr-gap .delta.up   { color: var(--color-green); }
.fr-gap .delta.down { color: var(--color-red); }
.fr-gap .row2 {
    display: flex; justify-content: space-between;
    font-size: 0.7rem; color: var(--color-text-subtle); margin-top: 6px;
}
.fr-gap .row2 .v {
    color: var(--color-text); font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, monospace;
}

/* Comparativo final */
.fr-compare {
    background: linear-gradient(135deg, var(--color-wine) 0%, var(--color-wine-soft) 100%);
    border: 2px solid rgba(201, 168, 76, 0.4);
    border-radius: 10px;
    padding: 16px 20px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}
.fr-compare .kicker {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--color-gold);
}
.fr-compare h3 {
    margin: 4px 0 6px 0 !important;
    color: #ffffff !important;
    font-size: 1.6rem;
    font-weight: 700;
}
.fr-compare h3.up   { color: var(--color-green) !important; }
.fr-compare h3.down { color: var(--color-red)   !important; }
.fr-compare p.note { font-size: 0.78rem; color: rgba(255,255,255,0.75); margin: 0; }
.fr-compare .right {
    display: flex; gap: 22px; align-items: baseline;
}
.fr-compare .right .col { text-align: right; }
.fr-compare .right .col .k {
    font-size: 0.62rem; color: rgba(255,255,255,0.7);
    text-transform: uppercase; font-weight: 600; letter-spacing: 0.7px;
}
.fr-compare .right .col .v {
    font-family: ui-monospace, monospace;
    font-weight: 700; font-size: 1rem; color: #ffffff;
    font-variant-numeric: tabular-nums;
}
.fr-compare .right .col .v.gold  { color: var(--color-gold); }
.fr-compare .right .col .v.green { color: var(--color-green); }

.fr-footer-note {
    text-align: center;
    font-size: 0.7rem;
    color: var(--color-muted);
    margin-top: 14px;
}

.fr-scenario-wrap.consulta .fr-card-head .fr-head-badge {
    background: rgba(255, 255, 255, 0.12);
}
.fr-scenario-wrap.sim .fr-card {
    border-color: rgba(201, 168, 76, 0.28);
}
.fr-scenario-wrap.sim .fr-card-head {
    box-shadow: inset 0 -2px 0 rgba(201, 168, 76, 0.35);
}
.fr-scenario-wrap.sim .fr-card-head .fr-head-badge {
    background: rgba(201, 168, 76, 0.35);
    color: #fff;
}
/* Vitrine — card completo por coluna (cabeçalho + linhas + faturamento) */
.fr-vitrine-sync { margin-bottom: 10px; }
.fr-vitrine-sync .fr-vitrine-col-shell .fr-card {
    margin-bottom: 0;
    border-radius: 10px 10px 0 0;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-bottom: none;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.22);
    background: rgba(34, 34, 38, 0.92);
}
.fr-vitrine-sync .col-sim-shell .fr-card {
    border-color: rgba(201, 168, 76, 0.18);
    background: rgba(38, 32, 30, 0.94);
}
.fr-vitrine-sync .col-meta-shell .fr-card {
    border-color: rgba(4, 120, 87, 0.14);
    background: rgba(34, 36, 36, 0.92);
}
.fr-vitrine-sync .fr-vitrine-col-shell .fr-card-head {
    box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.05);
}
.fr-vitrine-fatu-shell {
    padding: 7px 8px 9px;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 0 0 10px 10px;
    background: rgba(30, 30, 33, 0.88);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
}
.fr-vitrine-fatu-shell.col-sim {
    border-color: rgba(201, 168, 76, 0.16);
    background: rgba(36, 30, 28, 0.9);
}
.fr-vitrine-fatu-shell.col-meta {
    border-color: rgba(4, 120, 87, 0.12);
    background: rgba(30, 33, 32, 0.88);
}
/* Células da grade */
.fr-vitrine-cell {
    border-bottom: 1px solid rgba(255, 255, 255, 0.028);
    box-sizing: border-box;
}
.fr-vitrine-cell.col-atual {
    background: rgba(34, 34, 38, 0.55);
    border-left: 1px solid rgba(255, 255, 255, 0.09);
    border-right: none;
}
.fr-vitrine-cell.col-sim {
    background: rgba(38, 32, 30, 0.58);
    border-left: 1px solid rgba(201, 168, 76, 0.14);
    border-right: 1px solid rgba(201, 168, 76, 0.14);
}
.fr-vitrine-cell.col-meta {
    background: rgba(34, 36, 36, 0.55);
    border-right: 1px solid rgba(255, 255, 255, 0.09);
    border-left: none;
}
.fr-vitrine-cell.fr-vitrine-zebra-odd {
    box-shadow: inset 0 0 0 999px rgba(255, 255, 255, 0.008);
}
.fr-vitrine-cell.fr-vitrine-group-start {
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow: inset 0 2px 5px -5px rgba(0, 0, 0, 0.35);
}
.fr-vitrine-cell.fr-vitrine-group-end {
    border-bottom: 1px solid rgba(255, 255, 255, 0.055);
    box-shadow: inset 0 -2px 6px -5px rgba(0, 0, 0, 0.28);
}
.fr-vitrine-cell.is-first {
    border-top: none;
}
.fr-vitrine-cell.col-atual.is-last,
.fr-vitrine-cell.col-meta.is-last,
.fr-vitrine-cell.col-sim.is-last {
    border-bottom: none;
}
.fr-vitrine-editable-row {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
.fr-sim-readonly-val {
    display: block;
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-size: 0.86rem;
    font-weight: 700;
    text-align: right;
    padding: 0 4px 0 0;
    color: rgba(255, 255, 255, 0.88);
    font-variant-numeric: tabular-nums;
    line-height: 22px;
}
/* Selectbox compacto — modo Auto / % / Nº */
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-sim-mode-row)
    > div[data-testid="column"]:has(.fr-sim-mode-select-wrap) {
    flex: 0 0 68px !important;
    min-width: 68px !important;
    max-width: 76px !important;
    width: 68px !important;
    padding: 0 !important;
    align-self: center !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-sim-mode-row)
    [data-testid="stSelectbox"] {
    margin: 0 !important;
    width: 100% !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-sim-mode-row)
    [data-testid="stSelectbox"] > div {
    gap: 0 !important;
    min-height: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-sim-mode-row)
    [data-testid="stSelectbox"] [data-baseweb="select"] > div {
    min-height: 22px !important;
    max-height: 22px !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-sim-mode-row)
    [data-testid="stSelectbox"] [data-baseweb="select"] span {
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row) {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    height: 32px !important;
    min-height: 32px !important;
    max-height: 32px !important;
    margin: 0 !important;
    padding: 0 12px 0 6px !important;
    gap: 8px !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.028) !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
    background: rgba(38, 32, 30, 0.58) !important;
    border-left: 1px solid rgba(201, 168, 76, 0.14) !important;
    border-right: 1px solid rgba(201, 168, 76, 0.14) !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row.is-first) {
    border-top: none !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-group-start) {
    border-top: 1px solid rgba(255, 255, 255, 0.06) !important;
    box-shadow: inset 0 2px 5px -5px rgba(0, 0, 0, 0.35) !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-group-end) {
    border-bottom: 1px solid rgba(255, 255, 255, 0.055) !important;
    box-shadow: inset 0 -2px 6px -5px rgba(0, 0, 0, 0.28) !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-zebra-odd) {
    box-shadow: inset 0 0 0 999px rgba(255, 255, 255, 0.008) !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    > div[data-testid="column"] {
    display: flex !important;
    align-items: center !important;
    min-height: 0 !important;
    padding: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    > div[data-testid="column"]:first-child {
    flex: 1 1 auto !important;
    min-width: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    > div[data-testid="column"]:last-child {
    flex: 0 0 42% !important;
    max-width: 42% !important;
    justify-content: flex-end !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-sim-mode-row)
    > div[data-testid="column"]:last-child {
    flex: 1 1 auto !important;
    max-width: none !important;
    min-width: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row) .lbl-chip {
    max-width: 100% !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="element-container"] {
    margin: 0 !important;
    padding: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInput"],
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInputContainer"] {
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    background: transparent !important;
    width: 100% !important;
    min-height: 0 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInput"] > div {
    gap: 0 !important;
    min-height: 0 !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInput"] input {
    height: 22px !important;
    min-height: 22px !important;
    max-height: 22px !important;
    padding: 0 4px !important;
    font-size: 0.86rem !important;
    line-height: 1.2 !important;
    font-family: ui-monospace, "IBM Plex Mono", monospace !important;
    font-weight: 700 !important;
    font-variant-numeric: tabular-nums !important;
    text-align: right !important;
    color: rgba(255, 255, 255, 0.94) !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.14) !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    transition: border-color 0.15s ease, color 0.15s ease;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInput"] input:hover {
    border-bottom-color: rgba(201, 168, 76, 0.35) !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInput"] input:focus {
    border-bottom-color: rgba(201, 168, 76, 0.5) !important;
    color: #ffffff !important;
    outline: none !important;
    box-shadow: none !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInputStepDown"],
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInputStepUp"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 14px !important;
    min-width: 14px !important;
    height: 14px !important;
    min-height: 14px !important;
    margin: 0 0 0 1px !important;
    padding: 0 !important;
    opacity: 0 !important;
    border: none !important;
    border-radius: 2px !important;
    background: transparent !important;
    color: rgba(255, 255, 255, 0.5) !important;
    transition: opacity 0.15s ease;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row):hover
    [data-testid="stNumberInputStepDown"],
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row):hover
    [data-testid="stNumberInputStepUp"] {
    opacity: 0.28 !important;
}
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInputStepDown"]:hover,
.fr-vitrine-sync [data-testid="stHorizontalBlock"]:has(.fr-vitrine-editable-row)
    [data-testid="stNumberInputStepUp"]:hover {
    opacity: 0.5 !important;
}
.fr-head-badge {
    display: inline-block;
    margin-top: 6px;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: rgba(255, 255, 255, 0.92);
}
.fr-editor-wrap {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    padding: 4px 16px 16px;
    margin-top: 8px;
    margin-bottom: 14px;
}
.fr-editor-wrap.meta {
    border-color: rgba(4, 120, 87, 0.35);
}
.fr-editor-hint {
    font-size: 0.78rem;
    color: var(--color-text-subtle);
    margin: 0 0 12px 0;
    line-height: 1.45;
}
.fr-realism {
    display: inline-block;
    margin-left: 6px;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.58rem;
    font-weight: 700;
    line-height: 1.2;
    vertical-align: middle;
    white-space: nowrap;
    max-width: 9rem;
    overflow: hidden;
    text-overflow: ellipsis;
}
.fr-realism-ok { background: rgba(4, 120, 87, 0.35); color: #a7f3d0; }
.fr-realism-good { background: rgba(4, 120, 87, 0.45); color: #d1fae5; }
.fr-realism-warn { background: rgba(180, 120, 20, 0.35); color: #fde68a; }
.fr-realism-bad { background: rgba(153, 27, 27, 0.4); color: #fecaca; }
.fr-realism-neutral { display: none; }
</style>
"""


# =============================================================================
# Render helpers
# =============================================================================

# Cores por cabeçalho de cenário (espelha o JSX: Atual cinza, Simulador
# vinho, Meta verde escuro).
_CORES_CENARIO = {
    "Atual":     "#3F3F46",
    "Simulador": PALETTE["wine"],
    "Meta":      "#047857",
}

_WIDGET_SUFFIXES = ("_inv", "_cl", "_tk", "_pla", "_paag", "_pagc", "_pcv")


def _ensure_scenario(ss_key: str, base: Scenario) -> dict:
    if ss_key not in st.session_state:
        st.session_state[ss_key] = asdict(base)
    return st.session_state[ss_key]


def _investimento_label(periodo: str) -> str:
    if periodo == "mes":
        return "Investimento (mês)"
    if periodo == "semana":
        return "Investimento (semana)"
    return "Investimento (dia)"


def _clear_funil_widget_keys(*, sim_only: bool = False) -> None:
    for k in list(st.session_state.keys()):
        if not isinstance(k, str):
            continue
        if k.startswith("meta_ed_") or k.startswith("meta_cfg_"):
            if not sim_only:
                del st.session_state[k]
            continue
        if (
            k.startswith("simulador_mode_")
            or k.startswith("simulador_edit_mode_")
            or k.startswith("simulador_vol_")
        ):
            del st.session_state[k]
            continue
        if k.endswith(_WIDGET_SUFFIXES):
            del st.session_state[k]
    if sim_only and "funil_sim_edit_modes" in st.session_state:
        del st.session_state["funil_sim_edit_modes"]


def _clear_meta_editor_widget_keys() -> None:
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and (
            k.startswith("meta_ed_") or k.startswith("meta_cfg_")
        ):
            del st.session_state[k]
    if "funil_meta_edit_modes" in st.session_state:
        del st.session_state["funil_meta_edit_modes"]


def _funil_period_storage_key(data_ini: date, data_fim: date) -> str:
    return f"{data_ini.isoformat()}_{data_fim.isoformat()}"


def _init_meta_session_for_period(
    data_ini: date,
    data_fim: date,
    snapshot: FunnelSnapshot | None,
) -> None:
    """Inicializa meta da tela quando o filtro global muda (banco de metas → padrão)."""
    key = _funil_period_storage_key(data_ini, data_fim)
    if st.session_state.get("funil_meta_period_key") == key:
        return
    st.session_state["funil_meta_period_key"] = key
    pct_padrao = float(snapshot.pct_recebimento) if snapshot is not None else 0.0

    meta_tela = asdict(_BASE_META)
    if is_metas_database_configured():
        try:
            loaded = load_funil_meta(PERIODO_TIPO_PADRAO, data_ini, data_fim)
            if loaded is not None:
                meta_tela = metas_dict_to_scenario(loaded)
        except Exception:
            pass

    st.session_state["funil_meta_tela"] = meta_tela
    st.session_state["funil_meta_pct_recebimento"] = pct_padrao
    st.session_state["funil_meta_pct_recebimento_padrao"] = pct_padrao
    _clear_meta_editor_widget_keys()


def _get_meta_tela() -> Scenario:
    return Scenario(
        **st.session_state.get("funil_meta_tela", asdict(_BASE_META)),
    )


def _get_meta_pct_recebimento() -> float:
    return float(st.session_state.get("funil_meta_pct_recebimento", 0.0))


def _apply_historico_row_to_sim(row: dict[str, Any]) -> None:
    st.session_state["funil_simulador"] = dict(row["scenario"])
    _clear_funil_widget_keys(sim_only=True)


def _apply_historico_row_to_meta(row: dict[str, Any]) -> None:
    st.session_state["funil_meta_tela"] = dict(row["scenario"])
    st.session_state["funil_meta_pct_recebimento"] = float(
        row.get("pct_recebimento") or 0,
    )
    _clear_meta_editor_widget_keys()


def _build_export_bundle(
    *,
    periodo: str,
    data_ini: date,
    data_fim: date,
    excluir_testes: bool,
    atual: Scenario,
    simulador: Scenario,
    meta: Scenario,
    calc_atual: dict,
    calc_sim: dict,
    calc_meta: dict,
    impactos: list[dict],
) -> FunilExportBundle:
    return FunilExportBundle(
        periodo_viz=periodo,
        periodo_viz_label=PERIODOS[periodo]["label"],
        data_ini=data_ini,
        data_fim=data_fim,
        excluir_testes=excluir_testes,
        atual=atual,
        simulador=simulador,
        meta=meta,
        calc_atual=calc_atual,
        calc_sim=calc_sim,
        calc_meta=calc_meta,
        impactos=impactos,
        periodos_cfg=PERIODOS,
    )


def _export_file_stem(data_ini: date, data_fim: date, periodo: str) -> str:
    p = PERIODOS[periodo]["label"].lower()
    return (
        f"funil_reconecta_{data_ini:%Y%m%d}_{data_fim:%Y%m%d}_{p}"
    )


def _render_export_actions(bundle: FunilExportBundle) -> None:
    """Botões de download — usado no popover do topo da página."""
    stem = _export_file_stem(bundle.data_ini, bundle.data_fim, bundle.periodo_viz)
    st.caption(
        "Período, testes, comparativo Atual/Simulador/Meta, gargalo e prioridades."
    )
    st.download_button(
        "CSV",
        data=export_funil_csv(bundle),
        file_name=f"{stem}.csv",
        mime="text/csv",
        use_container_width=True,
        key="funil_export_csv",
    )
    st.download_button(
        "Excel (.xlsx)",
        data=export_funil_excel(bundle),
        file_name=f"{stem}.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        use_container_width=True,
        key="funil_export_xlsx",
    )
    st.download_button(
        "PDF",
        data=export_funil_pdf(bundle),
        file_name=f"{stem}.pdf",
        mime="application/pdf",
        use_container_width=True,
        key="funil_export_pdf",
    )


def _value_row_html(label: str, valor: str, *, computed: bool = False,
                    highlight: bool = False) -> str:
    """Uma linha label | valor dentro do card da vitrine."""
    val_cls = "computed" if computed else "static"
    row_cls = "fr-card-row fr-vitrine-row"
    if highlight:
        row_cls += " highlight"
    return (
        f'<div class="{row_cls}">'
        f'<span class="lbl bold lbl-chip">{html.escape(label)}</span>'
        f'<span class="val {val_cls}">{html.escape(valor)}</span>'
        f'</div>'
    )


def _vitrine_cell_class(
    col: str,
    *,
    is_first: bool,
    is_last: bool,
    group_after: bool = False,
    group_start: bool = False,
    zebra: str = "",
) -> str:
    parts = ["fr-vitrine-cell", f"col-{col}"]
    if is_first:
        parts.append("is-first")
    if is_last:
        parts.append("is-last")
    if group_start:
        parts.append("fr-vitrine-group-start")
    if group_after:
        parts.append("fr-vitrine-group-end")
    if zebra:
        parts.append(zebra)
    return " ".join(parts)


def _render_scenario_row_readonly(
    label: str,
    value: str,
    *,
    computed: bool = False,
    highlight: bool = False,
    cell_class: str = "",
) -> None:
    """Linha somente leitura — label à esquerda, valor à direita."""
    st.markdown(
        f'<div class="{html.escape(cell_class)}">'
        f'{_value_row_html(label, value, computed=computed, highlight=highlight)}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _editable_pct_max(value_pct: float) -> float:
    """Limite superior para % editáveis — pode passar de 100% (fontes distintas)."""
    return max(300.0, float(value_pct or 0))


def _render_scenario_row_editable(
    label: str,
    key: str,
    value: float,
    *,
    cell_class: str = "",
    min_value: float = 0.0,
    max_value: float | None = None,
    step: float = 1.0,
    is_percent: bool = False,
    spec_id: str | None = None,
    realism_value: float | None = None,
    benchmark_metrics: dict[str, dict[str, Any]] | None = None,
) -> float:
    """Linha editável — mesma altura/tipografia; input compacto à direita."""
    col_l, col_r = st.columns(
        [1.55, 1], gap="small", vertical_alignment="center",
    )
    lbl_html = _label_with_realism_badge(
        label,
        spec_id=spec_id,
        value=realism_value if realism_value is not None else value,
        benchmark_metrics=benchmark_metrics,
    )
    with col_l:
        st.markdown(
            f'<span class="fr-vitrine-editable-row {html.escape(cell_class)}" '
            f'aria-hidden="true"></span>'
            f'<span class="lbl bold lbl-chip">{lbl_html}</span>',
            unsafe_allow_html=True,
        )
    with col_r:
        valor_inicial = float(value or 0)
        kwargs: dict = {
            "label": label,
            "value": valor_inicial,
            "min_value": min_value,
            "step": step,
            "format": "%.2f",
            "key": key,
            "label_visibility": "collapsed",
        }
        if is_percent:
            kwargs["max_value"] = _editable_pct_max(valor_inicial)
        elif max_value is not None:
            kwargs["max_value"] = max(max_value, valor_inicial)
        return float(st.number_input(**kwargs))


def _sim_mode_label(option: str) -> str:
    return {"derivado": "Auto", "taxa": "%", "volume": "Nº"}.get(option, option)


def _sim_mode_select(stage: str, key_prefix: str) -> str:
    """Selectbox compacto: leads → Auto|Nº; demais → %|Nº."""
    options, fallback = _sim_mode_options(stage)
    wkey = _sim_mode_widget_key(key_prefix, stage)
    modes_key = _modes_key_for_prefix(key_prefix)
    default = (
        _DEFAULT_META_EDIT_MODES
        if modes_key == "funil_meta_edit_modes"
        else _DEFAULT_SIM_EDIT_MODES
    )
    modes = st.session_state.setdefault(modes_key, dict(default))
    current = _coerce_sim_mode_value(stage, modes.get(stage, fallback))

    if wkey in st.session_state and st.session_state[wkey] not in options:
        del st.session_state[wkey]
    if wkey not in st.session_state:
        st.session_state[wkey] = current

    chosen = st.selectbox(
        "Modo",
        options=list(options),
        format_func=_sim_mode_label,
        key=wkey,
        label_visibility="collapsed",
    )
    result = _coerce_sim_mode_value(stage, chosen) if chosen in options else current
    modes[stage] = result
    return result


def _render_sim_inline_row(
    label: str,
    *,
    cell_class: str,
    stage: str,
    key_prefix: str,
    show_toggle: bool,
    widget: str,
    sim_state: dict | None = None,
    calc_s: dict | None = None,
    spec: dict | None = None,
    readonly_text: str = "",
    sim_s: Scenario | None = None,
    benchmark_metrics: dict[str, dict[str, Any]] | None = None,
) -> str | float | None:
    """Linha compacta do Simulador: label | [modo] | valor (uma linha, altura fixa)."""
    row_marker = f"fr-sim-mode-row {cell_class}" if show_toggle else cell_class
    if show_toggle:
        col_l, mode_col, input_col = st.columns(
            [1.55, 0.62, 1.08], gap="small", vertical_alignment="center",
        )
    else:
        col_l, input_col = st.columns(
            [1.55, 1], gap="small", vertical_alignment="center",
        )
        mode_col = None

    spec_id = spec["id"] if spec else None
    realism_val: float | None = None
    if sim_s is not None and spec_id in _SPEC_ID_TO_BENCHMARK_KEY:
        realism_val = _scenario_metric_value(sim_s, _SPEC_ID_TO_BENCHMARK_KEY[spec_id])
    lbl_html = _label_with_realism_badge(
        label,
        spec_id=spec_id,
        value=realism_val if realism_val is not None else 0.0,
        benchmark_metrics=benchmark_metrics,
    )
    with col_l:
        st.markdown(
            f'<span class="fr-vitrine-editable-row {html.escape(row_marker)}" '
            f'aria-hidden="true"></span>'
            f'<span class="lbl bold lbl-chip">{lbl_html}</span>',
            unsafe_allow_html=True,
        )

    smode = _sim_edit_mode_for_stage(
        stage,
        key_prefix,
        modes_key=_modes_key_for_prefix(key_prefix),
    )
    if mode_col is not None:
        with mode_col:
            st.markdown(
                '<span class="fr-sim-mode-select-wrap" aria-hidden="true"></span>',
                unsafe_allow_html=True,
            )
            smode = _sim_mode_select(stage, key_prefix)

    with input_col:
        if widget == "readonly":
            st.markdown(
                f'<div class="fr-sim-readonly-val">{html.escape(readonly_text)}</div>',
                unsafe_allow_html=True,
            )
            return smode
        if widget == "pct" and spec is not None and sim_state is not None:
            pct_field = _SIM_STAGE_PCT_FIELD[stage]
            valor_inicial = float(sim_state[pct_field]) * 100
            return float(st.number_input(
                label,
                value=valor_inicial,
                min_value=0.0,
                max_value=_editable_pct_max(valor_inicial),
                step=0.5,
                format="%.2f",
                key=_sim_widget_key(spec, key_prefix),
                label_visibility="collapsed",
            ))
        if widget == "vol":
            vol_field = _SIM_STAGE_VOLUME_FIELD[stage]
            base = float((calc_s or {}).get(vol_field, 0))
            return float(st.number_input(
                label,
                value=base,
                min_value=0.0,
                step=1.0,
                format="%.2f",
                key=f"{key_prefix}_vol_{stage}",
                label_visibility="collapsed",
            ))
    return smode


def _render_sim_vitrine_row(
    spec: dict,
    label: str,
    *,
    sim_state: dict,
    calc_s: dict,
    sim_s: Scenario,
    div: int,
    cell_class: str,
    key_prefix: str,
    benchmark_metrics: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Célula do Simulador — taxa ou volume conforme modo da etapa."""
    stage = spec.get("sim_stage")
    role = spec.get("sim_role")
    rid = spec["id"]

    if stage is None:
        inp = spec["input"]
        step = 100.0 if inp == "inv_period" else (0.5 if inp == "pct" else 1.0)
        rid = spec["id"]
        _render_scenario_row_editable(
            label,
            _sim_widget_key(spec, key_prefix),
            _sim_editable_value(spec, sim_state, div=div),
            cell_class=cell_class,
            step=step,
            is_percent=(inp == "pct"),
            spec_id=rid if rid in _SPEC_ID_TO_BENCHMARK_KEY else None,
            realism_value=_scenario_metric_value(
                sim_s, _SPEC_ID_TO_BENCHMARK_KEY[rid],
            ) if rid in _SPEC_ID_TO_BENCHMARK_KEY else None,
            benchmark_metrics=benchmark_metrics,
        )
        return

    smode = _sim_edit_mode_for_stage(
        stage,
        key_prefix,
        modes_key=_modes_key_for_prefix(key_prefix),
    )

    if role == "pct":
        if smode == "taxa":
            _render_sim_inline_row(
                label,
                cell_class=cell_class,
                stage=stage,
                key_prefix=key_prefix,
                show_toggle=True,
                widget="pct",
                sim_state=sim_state,
                spec=spec,
                sim_s=sim_s,
                benchmark_metrics=benchmark_metrics,
            )
        else:
            _render_scenario_row_readonly(
                label,
                _format_vitrine_value(
                    rid, float(sim_state[_SIM_STAGE_PCT_FIELD[stage]]),
                ),
                computed=False,
                cell_class=cell_class,
            )
        return

    if role == "volume":
        vol_field = _SIM_STAGE_VOLUME_FIELD[stage]
        if stage == "leads":
            if smode == "volume":
                _render_sim_inline_row(
                    label,
                    cell_class=cell_class,
                    stage=stage,
                    key_prefix=key_prefix,
                    show_toggle=True,
                    widget="vol",
                    calc_s=calc_s,
                    sim_s=sim_s,
                    benchmark_metrics=benchmark_metrics,
                )
            else:
                _render_sim_inline_row(
                    label,
                    cell_class=cell_class,
                    stage=stage,
                    key_prefix=key_prefix,
                    show_toggle=True,
                    widget="readonly",
                    readonly_text=_format_vitrine_value("leads", calc_s["leads"]),
                    sim_s=sim_s,
                    benchmark_metrics=benchmark_metrics,
                )
            return
        if smode == "volume":
            _render_sim_inline_row(
                label,
                cell_class=cell_class,
                stage=stage,
                key_prefix=key_prefix,
                show_toggle=True,
                widget="vol",
                calc_s=calc_s,
                sim_s=sim_s,
                benchmark_metrics=benchmark_metrics,
            )
        else:
            _render_scenario_row_readonly(
                label,
                _format_vitrine_value(vol_field, calc_s[vol_field]),
                computed=True,
                cell_class=cell_class,
            )
        return


def _vitrine_row_specs(periodo: str) -> list[dict]:
    """Ordem fixa dos indicadores — mesma sequência nas três colunas."""
    return [
        {"id": "inv", "label": _investimento_label(periodo), "sim_editable": True,
         "input": "inv_period"},
        {"id": "cl", "label": "Custo por Lead (R$)", "sim_editable": True,
         "input": "money"},
        {"id": "leads", "label": "Leads", "computed": True, "group_after": True,
         "sim_stage": "leads", "sim_role": "volume"},
        {"id": "pct_la", "label": "% Lead → Aplicação",
         "sim_stage": "la", "sim_role": "pct"},
        {"id": "aplicacoes", "label": "Aplicações", "computed": True,
         "group_after": True, "sim_stage": "la", "sim_role": "volume"},
        {"id": "pct_a_ag", "label": "% Aplicação → Agendamento",
         "sim_stage": "a_ag", "sim_role": "pct"},
        {"id": "agendamentos", "label": "Agendamentos", "computed": True,
         "group_after": True, "sim_stage": "a_ag", "sim_role": "volume"},
        {"id": "pct_ag_c", "label": "% Agendamento → Comparecimento",
         "sim_stage": "ag_c", "sim_role": "pct"},
        {"id": "comparecimento", "label": "Comparecimento", "computed": True,
         "sim_stage": "ag_c", "sim_role": "volume"},
        {"id": "pct_c_v", "label": "% Comparecimento → Venda",
         "sim_stage": "c_v", "sim_role": "pct"},
        {"id": "vendas", "label": "Vendas", "computed": True, "highlight": True,
         "group_after": True, "sim_stage": "c_v", "sim_role": "volume"},
        {"id": "ticket", "label": "Ticket Médio (R$)", "sim_editable": True,
         "input": "money", "group_after": True},
    ]


def _vitrine_atual_value(
    spec: dict,
    snapshot: FunnelSnapshot,
    calc_display: dict,
) -> tuple[str, bool, bool]:
    """Valores reais do Atual — volumes do snapshot, taxas derivadas."""
    rid = spec["id"]
    computed = bool(spec.get("computed"))
    highlight = bool(spec.get("highlight"))
    if rid == "inv":
        return _format_vitrine_value(rid, calc_display["investimento"]), computed, highlight
    if rid == "cl":
        return _format_vitrine_value(rid, snapshot.custo_lead), computed, highlight
    if rid == "leads":
        return _format_vitrine_value(rid, calc_display["leads"]), True, highlight
    if rid == "pct_la":
        return _format_vitrine_value(rid, snapshot.pct_la), computed, highlight
    if rid == "aplicacoes":
        return _format_vitrine_value(rid, calc_display["aplicacoes"]), True, highlight
    if rid == "pct_a_ag":
        return _format_vitrine_value(rid, snapshot.pct_a_ag), computed, highlight
    if rid == "agendamentos":
        return _format_vitrine_value(rid, calc_display["agendamentos"]), True, highlight
    if rid == "pct_ag_c":
        return _format_vitrine_value(rid, snapshot.pct_ag_c), computed, highlight
    if rid == "comparecimento":
        return _format_vitrine_value(rid, calc_display["comparecimento"]), True, highlight
    if rid == "pct_c_v":
        return _format_vitrine_value(rid, snapshot.pct_c_v), computed, highlight
    if rid == "vendas":
        return _format_vitrine_value(rid, calc_display["vendas"]), True, highlight
    if rid == "ticket":
        return _format_vitrine_value(rid, snapshot.ticket), computed, highlight
    return "", computed, highlight


def _calc_atual_display(
    snapshot: FunnelSnapshot | None,
    atual_s: Scenario,
    periodo: str,
) -> dict:
    return _calc_atual_para_tela(snapshot, atual_s, periodo)


def _vitrine_readonly_value(
    spec: dict,
    s: Scenario,
    calc: dict,
) -> tuple[str, bool, bool]:
    """Retorna (texto, computed, highlight) para uma célula somente leitura."""
    rid = spec["id"]
    computed = bool(spec.get("computed"))
    highlight = bool(spec.get("highlight"))
    if rid == "inv":
        return _format_vitrine_value(rid, calc["investimento"]), computed, highlight
    if rid == "cl":
        return _format_vitrine_value(rid, s.custo_lead), computed, highlight
    if rid == "leads":
        return _format_vitrine_value(rid, calc["leads"]), True, highlight
    if rid == "pct_la":
        return _format_vitrine_value(rid, s.pct_la), computed, highlight
    if rid == "aplicacoes":
        return _format_vitrine_value(rid, calc["aplicacoes"]), True, highlight
    if rid == "pct_a_ag":
        return _format_vitrine_value(rid, s.pct_a_ag), computed, highlight
    if rid == "agendamentos":
        return _format_vitrine_value(rid, calc["agendamentos"]), True, highlight
    if rid == "pct_ag_c":
        return _format_vitrine_value(rid, s.pct_ag_c), computed, highlight
    if rid == "comparecimento":
        return _format_vitrine_value(rid, calc["comparecimento"]), True, highlight
    if rid == "pct_c_v":
        return _format_vitrine_value(rid, s.pct_c_v), computed, highlight
    if rid == "vendas":
        return _format_vitrine_value(rid, calc["vendas"]), True, highlight
    if rid == "ticket":
        return _format_vitrine_value(rid, s.ticket), computed, highlight
    return "", computed, highlight


def _apply_sim_editable(
    spec: dict,
    state: dict,
    raw: float,
    *,
    div: int,
) -> None:
    """Persiste valor editado no Simulador conforme o tipo do campo."""
    rid = spec["id"]
    if rid == "inv":
        state["investimento"] = raw * div
    elif rid == "cl":
        state["custo_lead"] = raw
    elif rid == "pct_la":
        state["pct_la"] = raw / 100
    elif rid == "pct_a_ag":
        state["pct_a_ag"] = raw / 100
    elif rid == "pct_ag_c":
        state["pct_ag_c"] = raw / 100
    elif rid == "pct_c_v":
        state["pct_c_v"] = raw / 100
    elif rid == "ticket":
        state["ticket"] = raw


def _sim_editable_value(spec: dict, state: dict, *, div: int) -> float:
    rid = spec["id"]
    if rid == "inv":
        return float(state["investimento"]) / div
    if rid == "cl":
        return float(state["custo_lead"])
    if rid == "ticket":
        return float(state["ticket"])
    if rid == "pct_la":
        return float(state["pct_la"]) * 100
    if rid == "pct_a_ag":
        return float(state["pct_a_ag"]) * 100
    if rid == "pct_ag_c":
        return float(state["pct_ag_c"]) * 100
    if rid == "pct_c_v":
        return float(state["pct_c_v"]) * 100
    return 0.0


def _sim_widget_key(spec: dict, key_prefix: str) -> str:
    keys = {
        "inv": f"{key_prefix}_inv",
        "cl": f"{key_prefix}_cl",
        "pct_la": f"{key_prefix}_pla",
        "pct_a_ag": f"{key_prefix}_paag",
        "pct_ag_c": f"{key_prefix}_pagc",
        "pct_c_v": f"{key_prefix}_pcv",
        "ticket": f"{key_prefix}_tk",
    }
    return keys[spec["id"]]


def _render_vitrine_comparison(
    periodo: str,
    *,
    atual_s: Scenario,
    snapshot: FunnelSnapshot | None,
    benchmark_metrics: dict[str, dict[str, Any]] | None = None,
    pct_recebimento: float = 0.0,
    meta_pct_recebimento: float | None = None,
) -> tuple[Scenario, Scenario, Scenario]:
    """Comparativo em grade: uma linha horizontal por indicador (Atual | Sim | Meta)."""
    st.markdown('<div class="fr-vitrine-sync">', unsafe_allow_html=True)

    key_prefix = "simulador"
    div = PERIODOS[periodo]["divisor"]
    rows = _vitrine_row_specs(periodo)
    n_rows = len(rows)
    calc_atual_display = _calc_atual_para_tela(snapshot, atual_s, periodo)
    meta_pct = (
        float(meta_pct_recebimento)
        if meta_pct_recebimento is not None
        else _get_meta_pct_recebimento()
    )

    h_atual, h_sim, h_meta = st.columns(3, gap="medium")
    with h_atual:
        _render_scenario_header(
            "Atual", periodo, _CORES_CENARIO["Atual"],
            badge="Dados reais · consulta",
            wrap_class="consulta",
            col_shell="atual",
        )
    with h_sim:
        _render_scenario_header(
            "Simulador", periodo, _CORES_CENARIO["Simulador"],
            badge="Cenário de teste · editável",
            wrap_class="sim",
            col_shell="sim",
        )
    with h_meta:
        _render_scenario_header(
            "Meta", periodo, _CORES_CENARIO["Meta"],
            badge="Objetivo · consulta",
            wrap_class="consulta",
            col_shell="meta",
        )

    sim_state = _ensure_scenario("funil_simulador", atual_s)
    meta_s = _get_meta_tela()
    _apply_simulator_from_session(sim_state, periodo, div, key_prefix)

    for idx, spec in enumerate(rows):
        sim_s = Scenario(**sim_state)
        calc_s = calcular_funil_exibicao(
            sim_s, periodo, pct_recebimento=pct_recebimento,
        )
        calc_m = calcular_funil_exibicao(
            meta_s, periodo, pct_recebimento=meta_pct,
        )

        label = spec["label"]
        is_first = idx == 0
        is_last = idx == n_rows - 1
        group_after = bool(spec.get("group_after"))
        group_start = idx > 0 and bool(rows[idx - 1].get("group_after"))
        zebra = "fr-vitrine-zebra-odd" if idx % 2 else "fr-vitrine-zebra-even"

        c_atual, c_sim, c_meta = st.columns(3, gap="medium")
        if snapshot is not None:
            val_a, comp_a, hi_a = _vitrine_atual_value(
                spec, snapshot, calc_atual_display,
            )
        else:
            val_a, comp_a, hi_a = _vitrine_readonly_value(
                spec, atual_s, calc_atual_display,
            )
        val_m, comp_m, hi_m = _vitrine_readonly_value(spec, meta_s, calc_m)

        with c_atual:
            _render_scenario_row_readonly(
                label, val_a,
                computed=comp_a, highlight=hi_a,
                cell_class=_vitrine_cell_class(
                    "atual", is_first=is_first, is_last=is_last,
                    group_after=group_after, group_start=group_start,
                    zebra=zebra,
                ),
            )
        with c_sim:
            cell_sim = _vitrine_cell_class(
                "sim", is_first=is_first, is_last=is_last,
                group_after=group_after, group_start=group_start,
                zebra=zebra,
            )
            if spec.get("sim_editable") or spec.get("sim_stage"):
                _render_sim_vitrine_row(
                    spec,
                    label,
                    sim_state=sim_state,
                    calc_s=calc_s,
                    sim_s=sim_s,
                    div=div,
                    cell_class=cell_sim,
                    key_prefix=key_prefix,
                    benchmark_metrics=benchmark_metrics,
                )
            else:
                val_s, comp_s, hi_s = _vitrine_readonly_value(spec, sim_s, calc_s)
                _render_scenario_row_readonly(
                    label, val_s,
                    computed=comp_s, highlight=hi_s,
                    cell_class=cell_sim,
                )
        with c_meta:
            _render_scenario_row_readonly(
                label, val_m,
                computed=comp_m, highlight=hi_m,
                cell_class=_vitrine_cell_class(
                    "meta", is_first=is_first, is_last=is_last,
                    group_after=group_after, group_start=group_start,
                    zebra=zebra,
                ),
            )

    st.session_state["funil_simulador"] = sim_state

    sim_s = Scenario(**sim_state)
    calc_s = calcular_funil_exibicao(
        sim_s, periodo, pct_recebimento=pct_recebimento,
    )
    calc_m = calcular_funil_exibicao(
        meta_s, periodo, pct_recebimento=meta_pct,
    )

    f_atual, f_sim, f_meta = st.columns(3, gap="medium")
    with f_atual:
        st.markdown(
            '<div class="fr-vitrine-fatu-shell col-atual">',
            unsafe_allow_html=True,
        )
        _render_valor_blocks(calc_atual_display, bloco="atual")
        st.markdown("</div></div>", unsafe_allow_html=True)
    with f_sim:
        st.markdown(
            '<div class="fr-vitrine-fatu-shell col-sim">',
            unsafe_allow_html=True,
        )
        _render_valor_blocks(
            calc_s,
            bloco="simulador",
            ref_atual=calc_atual_display,
        )
        st.markdown("</div></div>", unsafe_allow_html=True)
    with f_meta:
        st.markdown(
            '<div class="fr-vitrine-fatu-shell col-meta">',
            unsafe_allow_html=True,
        )
        _render_valor_blocks(
            calc_m,
            bloco="meta",
            ref_sim=calc_s,
        )
        st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    return atual_s, sim_s, meta_s


def _render_scenario_header(titulo: str, periodo: str, accent: str, *,
                            badge: str, wrap_class: str,
                            col_shell: str = "") -> None:
    shell_cls = (
        f" fr-vitrine-col-shell col-{col_shell}-shell" if col_shell else ""
    )
    st.markdown(
        f'<div class="fr-scenario-wrap {wrap_class}{shell_cls}">'
        f'  <div class="fr-card">'
        f'    <div class="fr-card-head" style="background:{accent};">'
        f'      <h3>{html.escape(titulo)}</h3>'
        f'      <div class="fr-period">{html.escape(PERIODOS[periodo]["label"])}</div>'
        f'      <span class="fr-head-badge">{html.escape(badge)}</span>'
        f'    </div>'
        f'  </div>',
        unsafe_allow_html=True,
    )


def _render_valor_blocks(
    calc: dict,
    *,
    bloco: str = "simulador",
    ref_atual: dict | None = None,
    ref_sim: dict | None = None,
) -> None:
    """bloco: 'atual' | 'simulador' | 'meta'."""
    if bloco == "atual":
        titulo_montante = "Montante vendido"
        titulo_receita = "Receita"
    else:
        titulo_montante = "Montante projetado"
        titulo_receita = "Receita projetada"

    montante_val = float(calc.get("montante") or 0)
    receita_val = float(calc.get("receita") or 0)
    receita_txt = (
        brl(receita_val)
        if receita_val > 0 or bloco == "atual"
        else "—"
    )

    chips_montante: list[str] = []
    chips_receita: list[str] = []

    pct_rec_mont = _pct_ratio_txt(receita_val, montante_val)
    if pct_rec_mont:
        chips_receita.append(f"{pct_rec_mont} do montante")

    if bloco == "simulador" and ref_atual is not None:
        ref_m = float(ref_atual.get("montante") or 0)
        ref_r = float(ref_atual.get("receita") or 0)
        pct_m = _pct_ratio_txt(montante_val, ref_m)
        pct_r = _pct_ratio_txt(receita_val, ref_r)
        if pct_m:
            chips_montante.append(f"{pct_m} do atual")
        if pct_r:
            chips_receita.append(f"{pct_r} do atual")
    elif bloco == "meta" and ref_sim is not None:
        ref_m = float(ref_sim.get("montante") or 0)
        ref_r = float(ref_sim.get("receita") or 0)
        pct_m = _pct_ratio_txt(montante_val, ref_m)
        pct_r = _pct_ratio_txt(receita_val, ref_r)
        if pct_m:
            chips_montante.append(f"{pct_m} do simulado")
        if pct_r:
            chips_receita.append(f"{pct_r} do simulado")

    st.markdown(
        f'<div class="fr-card fr-fatu-card">'
        f'  <div class="fr-fatu-stack">'
        f'    <div class="fr-fatu">'
        f'      <div class="fr-fatu-main">'
        f'        <div class="lbl">{html.escape(titulo_montante)}</div>'
        f'        <div class="val">{html.escape(brl(montante_val))}</div>'
        f'      </div>'
        f'      {_fatu_chips_html(chips_montante)}'
        f'    </div>'
        f'    <div class="fr-fatu fr-fatu--receita receita">'
        f'      <div class="fr-fatu-main">'
        f'        <div class="lbl">{html.escape(titulo_receita)}</div>'
        f'        <div class="val">{html.escape(receita_txt)}</div>'
        f'      </div>'
        f'      {_fatu_chips_html(chips_receita)}'
        f'    </div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_scenario_fields_editor(
    periodo: str,
    ss_key: str,
    base: Scenario,
    widget_prefix: str,
) -> Scenario:
    """Inputs compactos em 2 colunas — atualiza `st.session_state[ss_key]`."""
    state = _ensure_scenario(ss_key, base)
    div = PERIODOS[periodo]["divisor"]
    label_inv = _investimento_label(periodo)

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        inv_periodo = st.number_input(
            label_inv,
            value=float(state["investimento"]) / div,
            min_value=0.0, step=100.0, format="%.2f",
            key=f"{widget_prefix}_inv",
        )
        state["investimento"] = inv_periodo * div
        state["custo_lead"] = st.number_input(
            "Custo por Lead (R$)",
            value=float(state["custo_lead"]),
            min_value=0.0, step=1.0, format="%.2f",
            key=f"{widget_prefix}_cl",
        )
        _pct_la = float(state["pct_la"]) * 100
        state["pct_la"] = st.number_input(
            "% Lead → Aplicação",
            value=_pct_la,
            min_value=0.0,
            max_value=_editable_pct_max(_pct_la),
            step=0.5,
            format="%.2f",
            key=f"{widget_prefix}_pla",
        ) / 100
        _pct_a_ag = float(state["pct_a_ag"]) * 100
        state["pct_a_ag"] = st.number_input(
            "% Aplicação → Agendamento",
            value=_pct_a_ag,
            min_value=0.0,
            max_value=_editable_pct_max(_pct_a_ag),
            step=0.5,
            format="%.2f",
            key=f"{widget_prefix}_paag",
        ) / 100
    with c2:
        _pct_ag_c = float(state["pct_ag_c"]) * 100
        state["pct_ag_c"] = st.number_input(
            "% Agendamento → Comparecimento",
            value=_pct_ag_c,
            min_value=0.0,
            max_value=_editable_pct_max(_pct_ag_c),
            step=0.5,
            format="%.2f",
            key=f"{widget_prefix}_pagc",
        ) / 100
        _pct_c_v = float(state["pct_c_v"]) * 100
        state["pct_c_v"] = st.number_input(
            "% Comparecimento → Venda",
            value=_pct_c_v,
            min_value=0.0,
            max_value=_editable_pct_max(_pct_c_v),
            step=0.5,
            format="%.2f",
            key=f"{widget_prefix}_pcv",
        ) / 100
        state["ticket"] = st.number_input(
            "Ticket Médio (R$)",
            value=float(state["ticket"]),
            min_value=0.0, step=100.0, format="%.2f",
            key=f"{widget_prefix}_tk",
        )

    return Scenario(**state)


_ORIGEM_DADOS_REAIS = "Dados reais históricos"
_ORIGEM_METAS_SALVAS = "Metas oficiais salvas"

_REFERENCIA_FUNIL_COL_CONFIG = {
    "Período": st.column_config.TextColumn(width="medium"),
    "Investimento": st.column_config.NumberColumn(format="R$ %.2f"),
    "CPL": st.column_config.NumberColumn(format="R$ %.2f"),
    "Leads": st.column_config.NumberColumn(format="%.0f"),
    "% L→Apl": st.column_config.NumberColumn(format="%.2f%%"),
    "Aplicações": st.column_config.NumberColumn(format="%.0f"),
    "% Apl→Ag": st.column_config.NumberColumn(format="%.2f%%"),
    "Agendamentos": st.column_config.NumberColumn(format="%.0f"),
    "% Ag→Comp": st.column_config.NumberColumn(format="%.2f%%"),
    "Comparecimentos": st.column_config.NumberColumn(format="%.0f"),
    "% Comp→Vda": st.column_config.NumberColumn(format="%.2f%%"),
    "Vendas": st.column_config.NumberColumn(format="%.0f"),
    "Ticket": st.column_config.NumberColumn(format="R$ %.2f"),
    "Montante": st.column_config.NumberColumn(format="R$ %.2f"),
    "Receita": st.column_config.NumberColumn(format="R$ %.2f"),
    "% Rec/Mont": st.column_config.NumberColumn(format="%.2f%%"),
    "Atualizado": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
    "Por": st.column_config.TextColumn(width="small"),
    "Observação": st.column_config.TextColumn(width="medium"),
}


def _metas_oficiais_to_display_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Tabela de metas salvas com volumes calculados e % sem duplicar escala."""
    records: list[dict[str, Any]] = []
    for r in rows:
        s = Scenario(**r["scenario"])
        pct_rec = float(r.get("pct_recebimento") or 0)
        calc = calcular_funil_exibicao(s, "mes", pct_recebimento=pct_rec)
        records.append({
            "Período": r["periodo"],
            "Investimento": r["investimento"],
            "CPL": r["custo_lead"],
            "Leads": calc["leads"],
            "% L→Apl": pct_to_display_percent(r["pct_la"]),
            "Aplicações": calc["aplicacoes"],
            "% Apl→Ag": pct_to_display_percent(r["pct_a_ag"]),
            "Agendamentos": calc["agendamentos"],
            "% Ag→Comp": pct_to_display_percent(r["pct_ag_c"]),
            "Comparecimentos": calc["comparecimento"],
            "% Comp→Vda": pct_to_display_percent(r["pct_c_v"]),
            "Vendas": calc["vendas"],
            "Ticket": r["ticket"],
            "Montante": calc["montante"],
            "Receita": calc["receita"],
            "% Rec/Mont": pct_rec,
            "Atualizado": r.get("atualizado_em"),
            "Por": r.get("criado_por") or "—",
            "Observação": r.get("observacao") or "—",
        })
    return pd.DataFrame(records)


def _render_referencia_acoes(
    row: dict[str, Any],
    *,
    can_edit_meta: bool,
    sim_key: str,
    meta_key: str,
    show_delete: bool = False,
) -> None:
    """Botões comuns abaixo da referência selecionada."""
    b_sim, b_meta, _ = st.columns([2, 2, 3], gap="small")
    with b_sim:
        if st.button("Carregar no Simulador", key=sim_key, use_container_width=True):
            _apply_historico_row_to_sim(row)
            st.rerun()
    with b_meta:
        if can_edit_meta:
            if st.button("Usar como Meta da tela", key=meta_key, use_container_width=True):
                _apply_historico_row_to_meta(row)
                st.session_state["funil_meta_loaded_db_id"] = row.get("meta_db_id")
                st.rerun()
        else:
            st.caption(METAS_VIEW_ONLY_MESSAGE)

    if show_delete and can_edit_meta:
        st.markdown("---")
        st.caption("Exclusão disponível apenas para metas oficiais salvas no banco.")
        confirm = st.checkbox(
            "Confirmo que quero excluir esta meta salva",
            key="funil_meta_delete_confirm",
        )
        if st.button("Excluir meta salva", key="funil_meta_delete_btn"):
            if not confirm:
                st.warning("Marque a confirmação antes de excluir.")
                return
            meta_id = row.get("meta_db_id")
            if meta_id is None:
                st.error("Registro sem identificador — não foi possível excluir.")
                return
            try:
                soft_delete_meta_funil(int(meta_id), excluido_por="editor")
            except Exception as exc:
                st.error(
                    f"Não foi possível excluir a meta: {exc}. "
                    "Verifique se as colunas de soft delete existem no banco "
                    "(`sql/metas_funil_soft_delete.sql`)."
                )
                return
            if st.session_state.get("funil_meta_loaded_db_id") == meta_id:
                st.session_state.pop("funil_meta_loaded_db_id", None)
                st.info(
                    "O registro foi removido do histórico. "
                    "A Meta da tela permanece na sessão atual até você alterá-la."
                )
            st.session_state.pop("funil_meta_delete_confirm", None)
            st.session_state.pop("funil_metas_db_sel_idx", None)
            st.success("Meta oficial excluída do histórico.")
            st.rerun()


def _render_referencia_dados_reais(
    *,
    data_ini: date,
    data_fim: date,
    excluir_testes: bool,
    can_edit_meta: bool,
) -> list[dict[str, Any]]:
    rows = load_funil_historico_referencias(
        data_fim.isoformat(),
        data_ini.isoformat(),
        data_fim.isoformat(),
        excluir_testes,
    )
    st.session_state["funil_historico_rows"] = rows

    if not rows:
        st.info("Sem dados históricos disponíveis para os períodos de referência.")
        return rows

    st.dataframe(
        historico_rows_to_display_df(rows),
        hide_index=True,
        use_container_width=True,
        column_config=_REFERENCIA_FUNIL_COL_CONFIG,
    )

    labels = [r["periodo"] for r in rows]
    sel_idx = st.selectbox(
        "Referência selecionada",
        options=range(len(labels)),
        format_func=lambda i: labels[i],
        key="funil_historico_sel_idx",
    )
    row = historico_row_by_index(rows, int(sel_idx))
    if row is None:
        return rows

    st.caption(
        f'{row["data_ini"].strftime("%d/%m/%Y")} – '
        f'{row["data_fim"].strftime("%d/%m/%Y")} · referência calculada com dados '
        "reais (somente leitura)."
    )
    _render_referencia_acoes(
        row,
        can_edit_meta=can_edit_meta,
        sim_key="funil_ref_real_sim",
        meta_key="funil_ref_real_meta",
    )
    return rows


def _render_referencia_metas_oficiais(*, can_edit_meta: bool) -> None:
    if not is_metas_database_configured():
        st.info(
            "Configure `METAS_DATABASE_URL` no `.env` ou nos Secrets do Streamlit "
            "para listar metas oficiais salvas."
        )
        return

    try:
        rows = load_metas_funil_historico(limit=100)
    except MetasDatabaseNotConfiguredError:
        return
    except Exception as exc:
        st.warning(f"Não foi possível carregar metas oficiais salvas: {exc}")
        return

    if not rows:
        st.info("Nenhuma meta oficial salva ainda para este ambiente.")
        return

    st.dataframe(
        _metas_oficiais_to_display_df(rows),
        hide_index=True,
        use_container_width=True,
        column_config=_REFERENCIA_FUNIL_COL_CONFIG,
    )

    labels = [r["periodo"] for r in rows]
    sel_idx = st.selectbox(
        "Referência selecionada",
        options=range(len(labels)),
        format_func=lambda i: labels[i],
        key="funil_metas_db_sel_idx",
    )
    row = historico_row_by_index(rows, int(sel_idx))
    if row is None:
        return

    st.caption(
        f'{row["data_ini"].strftime("%d/%m/%Y")} – '
        f'{row["data_fim"].strftime("%d/%m/%Y")} · meta oficial salva em '
        "`bi.metas_funil_reconecta`."
    )
    _render_referencia_acoes(
        row,
        can_edit_meta=can_edit_meta,
        sim_key="funil_ref_db_sim",
        meta_key="funil_ref_db_meta",
        show_delete=True,
    )


def _render_base_meta_referencia(
    *,
    data_ini: date,
    data_fim: date,
    excluir_testes: bool,
    can_edit_meta: bool,
) -> None:
    """Base única para escolher referência histórica ou meta oficial salva."""
    section_title(
        "Base para definição de meta",
        "escolha a origem da referência para Simulador e Meta da tela",
    )

    opcoes = [_ORIGEM_DADOS_REAIS]
    if is_metas_database_configured():
        opcoes.append(_ORIGEM_METAS_SALVAS)

    if len(opcoes) == 1:
        origem = opcoes[0]
        st.caption(
            "Metas oficiais salvas ficam disponíveis quando `METAS_DATABASE_URL` "
            "está configurada."
        )
    else:
        origem = st.segmented_control(
            "Origem da referência",
            options=opcoes,
            default=opcoes[0],
            key="funil_meta_referencia_origem",
        )

    if origem == _ORIGEM_METAS_SALVAS:
        _render_referencia_metas_oficiais(can_edit_meta=can_edit_meta)
    else:
        _render_referencia_dados_reais(
            data_ini=data_ini,
            data_fim=data_fim,
            excluir_testes=excluir_testes,
            can_edit_meta=can_edit_meta,
        )


def _render_meta_cenario_editor(
    periodo: str,
    *,
    data_ini: date,
    data_fim: date,
    can_edit_meta: bool,
) -> None:
    """Ajuste da Meta — edição local com opção de salvar meta oficial."""
    section_title(
        "Ajuste de cenário de meta",
        "edite a coluna Meta da tela — requer modo editor de metas",
    )
    if not can_edit_meta:
        st.caption(METAS_VIEW_ONLY_MESSAGE)
        return
    st.markdown(
        '<div class="fr-editor-wrap meta">'
        '<p class="fr-editor-hint">'
        "Defina a meta por valor absoluto (<strong>Nº</strong>) ou taxa "
        "(<strong>%</strong>), como no Simulador. "
        "A coluna <strong>Meta</strong>, o gargalo e os gaps usam estes valores "
        "enquanto a página estiver aberta."
        "</p>",
        unsafe_allow_html=True,
    )

    _ensure_meta_edit_modes()
    meta_state = _ensure_scenario("funil_meta_tela", _get_meta_tela())
    div = PERIODOS[periodo]["divisor"]
    _apply_scenario_edits_from_session(
        meta_state,
        periodo,
        div,
        "meta_cfg",
        modes_key="funil_meta_edit_modes",
        default_modes=_DEFAULT_META_EDIT_MODES,
    )

    meta_pct = _get_meta_pct_recebimento()
    meta_s = Scenario(**meta_state)
    calc_m = calcular_funil_exibicao(
        meta_s, periodo, pct_recebimento=meta_pct,
    )
    rows = _vitrine_row_specs(periodo)

    for spec in rows:
        label = spec["label"]
        if spec.get("sim_editable") or spec.get("sim_stage"):
            _render_sim_vitrine_row(
                spec,
                label,
                sim_state=meta_state,
                calc_s=calc_m,
                sim_s=meta_s,
                div=div,
                cell_class="fr-editor-cell",
                key_prefix="meta_cfg",
                benchmark_metrics=None,
            )
        else:
            val_m, comp_m, hi_m = _vitrine_readonly_value(spec, meta_s, calc_m)
            _render_scenario_row_readonly(
                label, val_m, computed=comp_m, highlight=hi_m,
                cell_class="fr-editor-cell",
            )

    st.session_state["funil_meta_tela"] = meta_state

    c_pct, c_rec = st.columns(2, gap="medium")
    with c_pct:
        st.session_state["funil_meta_pct_recebimento"] = float(st.number_input(
            "% Receita sobre Montante",
            value=float(meta_pct),
            min_value=0.0,
            max_value=200.0,
            step=0.1,
            format="%.2f",
            key="meta_cfg_pct_recebimento",
            help="Receita projetada = Montante × este percentual.",
        ))
    with c_rec:
        rec_proj = project_receita_from_montante(
            calc_m["montante"] * div,
            st.session_state["funil_meta_pct_recebimento"],
        )
        st.metric(
            "Receita projetada (mês)",
            brl(rec_proj),
            help="Calculada a partir das vendas × ticket e % recebimento.",
        )

    b_sim, b_save, b_reset, _ = st.columns([2, 2, 2, 2], gap="small")
    with b_sim:
        if st.button("Carregar no Simulador", key="meta_cfg_to_sim", use_container_width=True):
            st.session_state["funil_simulador"] = dict(meta_state)
            _clear_funil_widget_keys(sim_only=True)
            st.rerun()
    with b_save:
        if st.button("Salvar meta oficial", key="meta_cfg_save_db", use_container_width=True):
            if not is_metas_database_configured():
                st.error(
                    "Configure `METAS_DATABASE_URL` no `.env` ou nos Secrets "
                    "do Streamlit para salvar metas oficiais."
                )
            else:
                try:
                    save_funil_meta(
                        PERIODO_TIPO_PADRAO,
                        data_ini,
                        data_fim,
                        metas_dict_from_scenario(meta_state),
                    )
                    st.success(
                        f"Meta oficial salva para "
                        f"{data_ini.strftime('%d/%m/%Y')} – "
                        f"{data_fim.strftime('%d/%m/%Y')}."
                    )
                except Exception as exc:
                    st.error(f"Não foi possível salvar a meta oficial: {exc}")
    with b_reset:
        if st.button("Restaurar cenário padrão", use_container_width=True):
            st.session_state["funil_meta_tela"] = asdict(_BASE_META)
            st.session_state["funil_meta_pct_recebimento"] = float(
                st.session_state.get("funil_meta_pct_recebimento_padrao", 0.0),
            )
            _clear_meta_editor_widget_keys()
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def _render_alerta_gargalo(impactos: list[dict], periodo: str) -> None:
    """Alerta — meta da tela; ganho em montante projetado (base mensal)."""
    top = impactos[0] if impactos else None
    p_label = PERIODOS[periodo]["label"].lower()

    if not top or top["impacto"] <= 0:
        st.markdown(
            '<div class="fr-alert healthy">'
            '  <div class="kicker">↑ Funil saudável</div>'
            '  <h4>Cenário acima ou alinhado com a meta da tela</h4>'
            '  <p class="note">Comparado à meta ativa nesta sessão, o '
            'Atual está em dia em todas as etapas. Não há gargalo crítico.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    ganho_mes = float(top["impacto"])
    ganho_view = _gargalo_impacto_exibicao(ganho_mes, periodo)
    fmt_atual = brl(top["atual"]) if top.get("is_money") else pct_fmt(top["atual"])
    fmt_meta  = brl(top["meta"])  if top.get("is_money") else pct_fmt(top["meta"])
    ganho_k = (
        f"Ganho na visualização ({p_label})"
        if periodo != "mes"
        else "Ganho potencial (mês)"
    )

    pri_rows = []
    for idx, i in enumerate(
        [x for x in impactos[:5] if x["impacto"] > 0], start=1
    ):
        imp_v = _gargalo_impacto_exibicao(float(i["impacto"]), periodo)
        pri_rows.append(
            f'<div class="pri-row">'
            f'  <span class="left">'
            f'    <span class="badge">{idx}</span>{html.escape(i["label"])}'
            f'  </span>'
            f'  <span class="right">+ {html.escape(brl(imp_v))}</span>'
            f'</div>'
        )
    pri_block = ""
    if len(pri_rows) > 1:
        pri_block = (
            '<div class="pri">'
            f'  <div class="pri-title">Ordem de prioridade ({p_label})</div>'
            + "".join(pri_rows)
            + '</div>'
        )

    st.markdown(
        f'<div class="fr-alert">'
        f'  <div class="kicker">⚠ Gargalo crítico do funil</div>'
        f'  <h4>{html.escape(top["label"])}</h4>'
        f'  <div class="grid">'
        f'    <div><div class="k">Atual</div><div class="v">{html.escape(fmt_atual)}</div></div>'
        f'    <div><div class="k">Meta da tela</div><div class="v">{html.escape(fmt_meta)}</div></div>'
        f'    <div>'
        f'      <div class="k">{html.escape(ganho_k)}</div>'
        f'      <div class="v accent">+ {html.escape(brl(ganho_view))}</div>'
        f'    </div>'
        f'  </div>'
        f'  <p class="note">Simulação: só esta etapa sobe até a meta da tela; '
        f'demais parâmetros do Atual permanecem iguais. Ganho em '
        f'<strong>montante projetado</strong> (vendas × ticket). '
        f'Base mensal: + {html.escape(brl(ganho_mes))}/mês.</p>'
        f'  {pri_block}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_gap_card(label: str, atual: float, meta: float,
                     periodo: str, is_money: bool = False) -> None:
    """Gap Atual → meta da tela na escala da visualização (entrada já mensal)."""
    div = PERIODOS[periodo]["divisor"]
    gap = meta - atual
    positivo = gap > 0
    gap_view = gap / div
    atual_view = atual / div
    meta_view = meta / div
    if is_money:
        faltam = brl(abs(gap_view)) if positivo else brl(0)
        atual_f, meta_f = brl(atual_view), brl(meta_view)
    else:
        faltam = int_br(abs(gap_view)) if positivo else int_br(0)
        atual_f, meta_f = int_br(atual_view), int_br(meta_view)
    status = "Faltam" if positivo else ("Sobra" if gap < 0 else "No alvo")

    st.markdown(
        f'<div class="fr-gap">'
        f'  <div class="lbl">{html.escape(label)}</div>'
        f'  <div class="row1">'
        f'    <span class="big">{html.escape(status)} {html.escape(faltam)}</span>'
        f'  </div>'
        f'  <div class="row2">'
        f'    <span>Atual: <span class="v">{html.escape(atual_f)}</span></span>'
        f'    <span>Meta: <span class="v">{html.escape(meta_f)}</span></span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_compare(calc_atual: dict, calc_sim: dict, calc_meta: dict) -> None:
    delta_m = calc_sim["montante"] - calc_atual["montante"]
    if delta_m > 0:
        title_html = (
            f'<h3 class="up">+ {html.escape(brl(delta_m))}</h3>'
            f'<div class="kicker" style="margin-top:4px;">Montante</div>'
        )
    elif delta_m < 0:
        title_html = (
            f'<h3 class="down">- {html.escape(brl(abs(delta_m)))}</h3>'
            f'<div class="kicker" style="margin-top:4px;">Montante</div>'
        )
    else:
        title_html = (
            '<h3>Igual ao Atual</h3>'
            '<div class="kicker" style="margin-top:4px;">Montante</div>'
        )

    rec_atual = float(calc_atual.get("receita") or 0)
    rec_sim = float(calc_sim.get("receita") or 0)
    rec_meta = float(calc_meta.get("receita") or 0)
    rec_rows = ""
    if rec_atual > 0 or rec_sim > 0 or rec_meta > 0:
        rec_rows = (
            f'    <div class="right" style="margin-top:10px;">'
            f'      <div class="col"><div class="k">Receita atual</div>'
            f'        <div class="v">{html.escape(brl(rec_atual))}</div></div>'
            f'      <div class="col"><div class="k">Receita sim.</div>'
            f'        <div class="v gold">{html.escape(brl(rec_sim))}</div></div>'
            f'      <div class="col"><div class="k">Receita meta</div>'
            f'        <div class="v green">{html.escape(brl(rec_meta))}</div></div>'
            f'    </div>'
        )

    st.markdown(
        f'<div class="fr-compare">'
        f'  <div style="display:flex;justify-content:space-between;'
        f'flex-wrap:wrap;gap:14px;align-items:flex-start;">'
        f'    <div>'
        f'      <div class="kicker">Simulador vs Atual</div>'
        f'      {title_html}'
        f'      <p class="note">Diferença de montante entre Simulador '
        f'(vendas × ticket) e Atual real. Receita projetada usa o '
        f'% recebimento do período.</p>'
        f'    </div>'
        f'    <div class="right">'
        f'      <div class="col"><div class="k">Montante atual</div>'
        f'        <div class="v">{html.escape(brl(calc_atual["montante"]))}</div></div>'
        f'      <div class="col"><div class="k">Montante sim.</div>'
        f'        <div class="v gold">{html.escape(brl(calc_sim["montante"]))}</div></div>'
        f'      <div class="col"><div class="k">Montante meta</div>'
        f'        <div class="v green">{html.escape(brl(calc_meta["montante"]))}</div></div>'
        f'    </div>'
        f'  </div>'
        f'{rec_rows}'
        f'</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Página
# =============================================================================

ctx = start_page(
    title="Funil da Reconecta",
    subtitle="Simulador de cenários — compare contra a meta e ataque o gargalo",
    filters=(),
    include_period=True,
)

st.markdown(_FUNIL_CSS, unsafe_allow_html=True)

excluir_testes_aplicacoes = st.checkbox(
    "Excluir testes nas aplicações",
    value=bool(st.session_state.get("onepage_excluir_testes_aplicacoes", False)),
    key="onepage_excluir_testes_aplicacoes",
    help=(
        "Remove e-mails de teste das aplicações (Typeform). "
        "Mesma regra da One Page — afeta Atual, % Aplicação → Agendamento e exports."
    ),
)

st.session_state.setdefault("funil_hist_base", "90")
hist_base_key = st.selectbox(
    "Base histórica de comparação",
    options=list(HISTORICO_PERIODOS.keys()),
    format_func=lambda k: HISTORICO_PERIODOS[k]["label"],
    key="funil_hist_base",
    help=(
        "Não altera o período principal da página. "
        "Usa o intervalo imediatamente anterior ao filtro global."
    ),
)
_hist_days = int(HISTORICO_PERIODOS[hist_base_key]["days"])
_hist_window = resolve_historical_window(ctx.data_ini, _hist_days)
_benchmark_raw: dict[str, Any] = {}
_benchmark_metrics: dict[str, dict[str, Any]] | None = None
if _hist_window is None:
    _benchmark_raw = {"error": "Período principal sem histórico anterior suficiente."}
else:
    _h_ini, _h_fim = _hist_window
    with st.spinner("Calculando benchmark histórico…"):
        _benchmark_raw = compute_funil_benchmark(
            _h_ini.isoformat(),
            _h_fim.isoformat(),
            hist_base_key,
            excluir_testes_aplicacoes,
        )
    if not _benchmark_raw.get("error"):
        _benchmark_metrics = _benchmark_raw.get("metrics")

_funnel_snapshot: FunnelSnapshot | None = None
try:
    _funnel_snapshot = load_one_page_funnel(
        ctx.data_ini,
        ctx.data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    st.session_state["funil_atual"] = snapshot_to_scenario_dict(_funnel_snapshot)
except Exception as e:
    st.warning(f"Não foi possível carregar o cenário Atual do banco: {e}")
    st.session_state.setdefault("funil_atual", asdict(_BASE_ATUAL))

if "funil_simulador" not in st.session_state and _funnel_snapshot is not None:
    st.session_state["funil_simulador"] = snapshot_to_scenario_dict(_funnel_snapshot)

_init_meta_session_for_period(ctx.data_ini, ctx.data_fim, _funnel_snapshot)

atual_s = Scenario(**st.session_state["funil_atual"])
meta_tela_s = _get_meta_tela()
_meta_pct_rec = _get_meta_pct_recebimento()

# Visualização (Mês / Semana / Dia) + ações globais (reset / exportar).
c_periodo, c_reset, c_export = st.columns([4, 2, 2], gap="medium")
with c_periodo:
    periodo = st.segmented_control(
        "Visualização",
        options=list(PERIODOS.keys()),
        format_func=lambda k: PERIODOS[k]["label"],
        default="mes",
        key="funil_periodo",
        label_visibility="collapsed",
    ) or "mes"
with c_reset:
    if st.button("Resetar simulador", use_container_width=True):
        if "funil_simulador" in st.session_state:
            del st.session_state["funil_simulador"]
        _clear_funil_widget_keys(sim_only=True)
        st.rerun()
with c_export:
    _export_top_slot = st.empty()

# Alerta de gargalo (Atual real vs Meta oficial salva).
_pct_rec = _pct_recebimento_snapshot(_funnel_snapshot)
impactos = identificar_gargalos(
    atual_s, meta_tela_s, pct_recebimento=_pct_rec,
)
_render_alerta_gargalo(impactos, periodo)
st.caption(
    "Gargalo e gaps comparam o Atual (dados reais) com a **meta da tela** "
    "(padrão, editada localmente ou carregada de um histórico)."
)

_render_benchmark_historico(
    _benchmark_raw,
    snapshot=_funnel_snapshot,
    atual_s=atual_s,
    meta_s=meta_tela_s,
)

section_title(
    "Comparativo de cenários",
    "Simulador: em cada etapa escolha «Editar %» ou «Editar vol.» — o outro valor recalcula",
)
_ensure_sim_edit_modes()
atual_s, sim_s, meta_s = _render_vitrine_comparison(
    periodo,
    atual_s=atual_s,
    snapshot=_funnel_snapshot,
    benchmark_metrics=_benchmark_metrics,
    pct_recebimento=_pct_rec,
    meta_pct_recebimento=_meta_pct_rec,
)

calc_atual = _calc_atual_para_tela(_funnel_snapshot, atual_s, periodo)
calc_sim = calcular_funil_exibicao(
    sim_s, periodo, pct_recebimento=_pct_rec,
)
calc_meta = calcular_funil_exibicao(
    meta_s, periodo, pct_recebimento=_meta_pct_rec,
)

# Gap até a meta — volumes e financeiro.
section_title(
    "Gap até a meta",
    "quanto falta do Atual até a meta da tela — escala da visualização",
)
g1, g2, g3, g4, g5 = st.columns(5, gap="small")
with g1:
    _render_gap_card("Leads a mais",
                     calc_atual["leads"] * PERIODOS[periodo]["divisor"],
                     calc_meta["leads"]  * PERIODOS[periodo]["divisor"],
                     periodo)
with g2:
    _render_gap_card("Agendamentos a mais",
                     calc_atual["agendamentos"] * PERIODOS[periodo]["divisor"],
                     calc_meta["agendamentos"]  * PERIODOS[periodo]["divisor"],
                     periodo)
with g3:
    _render_gap_card("Vendas a mais",
                     calc_atual["vendas"] * PERIODOS[periodo]["divisor"],
                     calc_meta["vendas"]  * PERIODOS[periodo]["divisor"],
                     periodo)
with g4:
    _render_gap_card("Montante a mais",
                     calc_atual["montante"] * PERIODOS[periodo]["divisor"],
                     calc_meta["montante"]  * PERIODOS[periodo]["divisor"],
                     periodo, is_money=True)
with g5:
    _render_gap_card("Receita a mais",
                     calc_atual["receita"] * PERIODOS[periodo]["divisor"],
                     calc_meta["receita"]  * PERIODOS[periodo]["divisor"],
                     periodo, is_money=True)

# Comparativo Simulador vs Atual (faixa destaque).
st.markdown("&nbsp;", unsafe_allow_html=True)
_render_compare(calc_atual, calc_sim, calc_meta)

_export_bundle = _build_export_bundle(
    periodo=periodo,
    data_ini=ctx.data_ini,
    data_fim=ctx.data_fim,
    excluir_testes=excluir_testes_aplicacoes,
    atual=atual_s,
    simulador=sim_s,
    meta=meta_s,
    calc_atual=calc_atual,
    calc_sim=calc_sim,
    calc_meta=calc_meta,
    impactos=impactos,
)
with _export_top_slot.container():
    with st.popover("Exportar relatório", use_container_width=True):
        _render_export_actions(_export_bundle)

_render_base_meta_referencia(
    data_ini=ctx.data_ini,
    data_fim=ctx.data_fim,
    excluir_testes=excluir_testes_aplicacoes,
    can_edit_meta=is_metas_editor_authenticated(),
)
_can_edit_meta = render_metas_editor_gate()
_render_meta_cenario_editor(
    periodo,
    data_ini=ctx.data_ini,
    data_fim=ctx.data_fim,
    can_edit_meta=_can_edit_meta,
)

st.markdown(
    '<div class="fr-footer-note">'
    f'Atual: dados reais do período ({ctx.data_ini.strftime("%d/%m/%Y")}'
    f'–{ctx.data_fim.strftime("%d/%m/%Y")}), mesmas regras da One Page. '
    'Semana e Dia são aproximações proporcionais (÷ 4 e ÷ 28). '
    'Simulador e Meta: montante = vendas × ticket; receita usa % recebimento. '
    'Simulador: memória local. Meta oficial: salva em `bi.metas_funil_reconecta` '
    'quando `METAS_DATABASE_URL` está configurada.'
    '</div>',
    unsafe_allow_html=True,
)
