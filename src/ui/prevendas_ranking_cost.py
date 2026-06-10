"""Helpers compartilhados — custo/investimento no ranking de SDRs (Pré-vendas).

Mesma regra da Visão Geral Pré-vendas / One Page:
  custo_medio_geral = investido_total / total_da_metrica_no_periodo
  investimento_estimado_sdr = resultado_sdr * custo_medio_geral
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.transforms import _safe_div
from src.ui.theme import fmt_currency_br

RANKING_AVG_COST_LABELS: dict[str, str] = {
    "agendamentos_criados": "Custo médio / Ag. criado",
    "agendamentos": "Custo médio / Agend.",
    "agendamentos_mais_12": "Custo médio / Ag. +12",
    "agendamentos_menos_12": "Custo médio / Ag. -12",
    "comparecimentos": "Custo médio / Comp.",
    "vendas": "Custo médio / Venda",
    "cancelados": "Custo médio / Cancelado",
    "vencidos": "Custo médio / Vencido",
}


def total_metrica_ranking(
    metric_col: str,
    df_rank_base: pd.DataFrame,
    kpis: dict,
    *,
    agendamentos_exibidos: int | float | None = None,
) -> float:
    """Total do período para custo médio — mesma base dos cards de resumo."""
    if metric_col == "agendamentos":
        if agendamentos_exibidos is not None:
            return float(agendamentos_exibidos)
        ag_brutos = float(kpis.get("agendamentos", 0) or 0)
        vencidas = float(kpis.get("vencidas", 0) or 0)
        return float(max(ag_brutos - vencidas, 0))
    if metric_col == "agendamentos_criados":
        return float(kpis.get("agendamentos_criados", 0) or 0)
    if metric_col == "agendamentos_mais_12":
        return float(kpis.get("agendamentos_mais_12", 0) or 0)
    if metric_col == "comparecimentos":
        return float(kpis.get("comparecimentos", 0) or 0)
    if metric_col == "vendas":
        return float(kpis.get("vendas", 0) or 0)
    if metric_col == "vencidos":
        return float(kpis.get("vencidas", 0) or 0)
    if metric_col == "cancelados":
        return float(kpis.get("canceladas", 0) or 0)
    if metric_col in df_rank_base.columns:
        return float(df_rank_base[metric_col].fillna(0).sum())
    return 0.0


def custo_display_por_etapa(qtd, investido_total: float) -> str:
    return fmt_currency_br(_safe_div(investido_total, qtd))


def custo_medio_metrica_ranking(
    metric_col: str,
    df_rank_base: pd.DataFrame,
    investido_total: float,
    kpis: dict,
    *,
    agendamentos_exibidos: int | float | None = None,
) -> tuple[float, str]:
    """Investido ÷ total da métrica no período (mesma base dos cards)."""
    total = total_metrica_ranking(
        metric_col, df_rank_base, kpis,
        agendamentos_exibidos=agendamentos_exibidos,
    )
    if total <= 0:
        return 0.0, "—"
    custo = _safe_div(investido_total, total)
    return custo, fmt_currency_br(custo)


# Colunas numéricas da tabela "Indicadores por Pré-vendas" (label → col interna).
# `wide=True` → header mais longo (ex.: "Não atua").
INDICADORES_OPORT_METRIC_COLS: list[tuple[str, str, bool]] = [
    ("Op.", "oport_total", False),
    ("Op. +12", "oport_+12", False),
    ("Op. -12", "oport_-12", False),
    ("Op. Não atua", "oport_nao_atua", True),
    ("Ag.", "agend_total", False),
    ("Ag. +12", "agend_+12", False),
    ("Ag. -12", "agend_-12", False),
    ("Ag. Não atua", "agend_nao_atua", True),
    ("Comp.", "comp_total", False),
    ("Comp. +12", "comp_+12", False),
    ("Comp. -12", "comp_-12", False),
    ("Comp. Não atua", "comp_nao_atua", True),
    ("Vendas", "vendas_total", False),
    ("Vendas +12", "vendas_+12", False),
    ("Vendas -12", "vendas_-12", False),
    ("Vendas Não atua", "vendas_nao_atua", True),
]


def custo_medio_from_total(investido_total: float, total_metrica: float) -> float:
    if total_metrica <= 0:
        return 0.0
    return _safe_div(investido_total, total_metrica)


def custos_medios_indicadores_oport(
    tabela: pd.DataFrame,
    investido_total: float,
) -> dict[str, float]:
    """Custo médio por coluna — total geral = soma da coluna na tabela."""
    custos: dict[str, float] = {}
    for label, col, _ in INDICADORES_OPORT_METRIC_COLS:
        total = float(tabela[col].fillna(0).sum()) if col in tabela.columns else 0.0
        custos[label] = custo_medio_from_total(investido_total, total)
    return custos


def fmt_celula_indicador_com_custo(
    valor,
    custo_medio: float,
    *,
    show_cost: bool,
) -> str:
    """Número inteiro; com custo: ``58 (R$ 13.424,68)``. Zero → ``0``."""
    try:
        n = int(valor) if pd.notna(valor) else 0
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "0"
    if not show_cost or custo_medio <= 0:
        return str(n)
    inv = investimento_estimado_sdr(n, custo_medio)
    if inv == "—":
        return str(n)
    return f"{n} ({inv})"


def investimento_estimado_sdr(qtd, custo_medio: float) -> str:
    """resultado_sdr × custo médio geral da métrica."""
    try:
        q = float(qtd)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(q) or q <= 0 or custo_medio <= 0:
        return "—"
    return fmt_currency_br(q * custo_medio)


def metric_option_label_with_cost(
    label: str,
    metric_col: str,
    df_rank_base: pd.DataFrame,
    investido_total: float,
    kpis: dict,
    *,
    agendamentos_exibidos: int | float | None = None,
) -> str:
    total = total_metrica_ranking(
        metric_col, df_rank_base, kpis,
        agendamentos_exibidos=agendamentos_exibidos,
    )
    return f"{label} | {custo_display_por_etapa(total, investido_total)}"


def augment_ranking_plot_with_cost(
    ranking_plot: pd.DataFrame,
    metric_col: str,
    df_rank_base: pd.DataFrame,
    investido_total: float,
    kpis: dict,
    *,
    agendamentos_exibidos: int | float | None = None,
) -> tuple[pd.DataFrame, float, str]:
    """Adiciona coluna `_inv_estimado_sdr` e retorna custo médio (num, fmt)."""
    plot = ranking_plot.copy()
    custo_num, custo_fmt = custo_medio_metrica_ranking(
        metric_col, df_rank_base, investido_total, kpis,
        agendamentos_exibidos=agendamentos_exibidos,
    )
    plot["_inv_estimado_sdr"] = plot[metric_col].apply(
        lambda q: investimento_estimado_sdr(q, custo_num),
    )
    return plot, custo_num, custo_fmt


def init_ranking_metric_col_state(
    metric_options: dict[str, str],
    default_metric_label: str,
    col_state_key: str,
    legacy_label_key: str,
) -> str:
    metric_cols = list(metric_options.values())
    label_by_col = {col: label for label, col in metric_options.items()}

    if col_state_key not in st.session_state:
        legacy = st.session_state.get(legacy_label_key, default_metric_label)
        if legacy in metric_options:
            st.session_state[col_state_key] = metric_options[legacy]
        elif legacy in metric_cols:
            st.session_state[col_state_key] = legacy
        else:
            st.session_state[col_state_key] = metric_options.get(
                default_metric_label, metric_cols[0],
            )

    col_atual = st.session_state[col_state_key]
    if col_atual not in metric_cols:
        col_atual = metric_options.get(default_metric_label, metric_cols[0])
        st.session_state[col_state_key] = col_atual
    return col_atual


def render_ranking_metric_controls(
    *,
    metric_options: dict[str, str],
    default_metric_label: str,
    key_prefix: str,
    investido_total: float,
    kpis: dict,
    df_rank_base: pd.DataFrame,
    agendamentos_exibidos: int | float | None = None,
) -> tuple[str, str, bool]:
    """Checkbox + selectbox de métrica com custo médio opcional.

    Retorna ``(metric_col, metric_label, show_cost_on_bar)``.
    """
    metric_cols = list(metric_options.values())
    label_by_col = {col: label for label, col in metric_options.items()}

    col_state_key = f"{key_prefix}_ranking_metric_col"
    legacy_label_key = f"{key_prefix}_ranking_metric"
    col_atual = init_ranking_metric_col_state(
        metric_options, default_metric_label, col_state_key, legacy_label_key,
    )

    mostrar_custo = st.checkbox(
        "Exibir custo ao lado do valor",
        value=False,
        key=f"{key_prefix}_ranking_show_cost",
        help=(
            "Quando marcado: cada barra exibe o investimento estimado "
            "atribuído à SDR (resultado × custo médio da métrica) e o "
            "seletor mostra o custo médio geral do período (mesma regra "
            "dos cards)."
        ),
    )

    col_idx = metric_cols.index(col_atual)

    if mostrar_custo:
        display_options = [
            metric_option_label_with_cost(
                label_by_col[c], c, df_rank_base, investido_total, kpis,
                agendamentos_exibidos=agendamentos_exibidos,
            )
            for c in metric_cols
        ]
        display_to_col = dict(zip(display_options, metric_cols))
        metric_display = st.selectbox(
            "Métrica do ranking",
            options=display_options,
            index=col_idx,
            key=f"{key_prefix}_ranking_metric_display",
        )
        metric_col = display_to_col[metric_display]
    else:
        label_options = [label_by_col[c] for c in metric_cols]
        metric_label_sel = st.selectbox(
            "Métrica do ranking",
            options=label_options,
            index=col_idx,
            key=legacy_label_key,
        )
        metric_col = metric_options[metric_label_sel]

    st.session_state[col_state_key] = metric_col
    return metric_col, label_by_col[metric_col], mostrar_custo
