"""Contexto de página compartilhado entre todas as views.

Layout: título e filtros vivem na MESMA linha horizontal (barra vinho no topo).
- Coluna 0: título (logo + nome da página + subtítulo)
- Colunas seguintes: 1 por filtro categórico
- Última coluna: período (popover preset + date_input)

Uso típico em uma view:

    ctx = start_page(
        title="Executivas & Times",
        subtitle="...",
        filters=["times", "executiva"],
    )
    df = get_executivas(ctx.data_ini, ctx.data_fim)
    df = ctx.apply_filters(df, {"times": "time_vendas", "executiva": "executiva"})
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from .components import filter_label

# =============================================================================
# Configuração — período global
# =============================================================================

PERIOD_RANGE_KEY = "global_period_range"
PERIOD_PRESET_KEY = "global_period_preset"
_PERIOD_LAST_APPLIED = "_global_period_last_applied"

_DEFAULT_PRESET = "Mês atual"

PRESETS_PT: list[str] = [
    "Semana atual",
    "Mês atual",
    "Última semana",
    "Último mês",
    "Últimos 3 meses",
    "Últimos 6 meses",
    "Ano atual",
    "Último ano",
    "Personalizado",
]


def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    return nxt - timedelta(days=1)


def resolve_preset(label: str, today: date | None = None) -> tuple[date, date] | None:
    today = today or date.today()
    if label == "Semana atual":
        return today - timedelta(days=today.weekday()), today
    if label == "Mês atual":
        return today.replace(day=1), _last_day_of_month(today)
    if label == "Última semana":
        last_sun = today - timedelta(days=today.weekday() + 1)
        return last_sun - timedelta(days=6), last_sun
    if label == "Último mês":
        first_this = today.replace(day=1)
        last_of_last = first_this - timedelta(days=1)
        return last_of_last.replace(day=1), last_of_last
    if label == "Últimos 3 meses":
        return today - timedelta(days=90), today
    if label == "Últimos 6 meses":
        return today - timedelta(days=180), today
    if label == "Ano atual":
        return date(today.year, 1, 1), today
    if label == "Último ano":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None  # Personalizado


def _ensure_period_state() -> tuple[date, date]:
    today = date.today()
    if PERIOD_PRESET_KEY not in st.session_state:
        st.session_state[PERIOD_PRESET_KEY] = _DEFAULT_PRESET
    if PERIOD_RANGE_KEY not in st.session_state:
        rng = resolve_preset(_DEFAULT_PRESET, today) or (
            today - timedelta(days=30), today
        )
        st.session_state[PERIOD_RANGE_KEY] = rng
    if _PERIOD_LAST_APPLIED not in st.session_state:
        st.session_state[_PERIOD_LAST_APPLIED] = st.session_state[PERIOD_PRESET_KEY]
    return st.session_state[PERIOD_RANGE_KEY]


# =============================================================================
# Configuração — filtros categóricos
# =============================================================================

_FILTER_LABELS: dict[str, str] = {
    "closer":      "Closer",
    "executiva":   "Executiva",
    "times":       "Times",
    "time":        "Time",
    "sdr":         "SDR",
    "pipeline":    "Pipeline",
    "tipo_sdr":    "Tipo SDR",
    "time_closer": "Time Closer",
}

_FILTER_DEFAULTS: dict[str, str] = {
    "tipo_sdr":    "all_except_unknown",
    "time_closer": "all_except_unknown",
    "times":       "all_except_unknown",
    "time":        "all_except_unknown",
    "sdr":         "none",
    "closer":      "none",
    "executiva":   "none",
    "pipeline":    "all",
}

_UNKNOWN_TOKENS = ("sem time definido", "não classificado", "nao classificado",
                   "(não informado)", "(nao informado)")


def _is_unknown_label(label) -> bool:
    if not isinstance(label, str):
        return False
    s = label.strip().lower()
    return any(tok in s for tok in _UNKNOWN_TOKENS)


def _resolve_default(filter_key: str, options: list[str]) -> list[str]:
    rule = _FILTER_DEFAULTS.get(filter_key, "all")
    if rule == "all":
        return list(options)
    if rule == "none":
        return []
    if rule == "all_except_unknown":
        return [o for o in options if not _is_unknown_label(o)]
    return list(options)


# =============================================================================
# Multiselect compacto via popover
# =============================================================================

def _popover_label(sel: list[str], options: list[str]) -> str:
    n_opts = len(options)
    if n_opts == 0:
        return "—"
    if not sel:
        return "Todos"
    if len(sel) >= n_opts:
        return "Todos"
    if len(sel) == 1:
        s = str(sel[0])
        return s if len(s) <= 22 else s[:21] + "…"
    return f"{len(sel)} selecionados"


def _multiselect_compact(label: str, options: list[str], key: str,
                         default_sel: list[str]) -> list[str]:
    if key not in st.session_state:
        st.session_state[key] = list(default_sel)

    sel_atual = st.session_state.get(key, [])
    btn = _popover_label(sel_atual, options)

    with st.popover(btn, use_container_width=True):
        if options:
            ca, cb = st.columns(2)
            with ca:
                if st.button("Marcar todos", key=f"{key}__all",
                             use_container_width=True):
                    st.session_state[key] = list(options)
                    st.rerun()
            with cb:
                if st.button("Limpar", key=f"{key}__clear",
                             use_container_width=True):
                    st.session_state[key] = []
                    st.rerun()
            st.multiselect(
                label, options, key=key,
                label_visibility="collapsed",
                placeholder="Buscar…",
            )
        else:
            st.caption("Nenhuma opção disponível.")

    return list(st.session_state.get(key, []))


# =============================================================================
# Período compacto (popover)
# =============================================================================

def _period_button_label(rng: tuple[date, date], preset: str) -> str:
    if preset and preset != "Personalizado":
        return preset
    if isinstance(rng, tuple) and len(rng) == 2:
        return f"{rng[0].strftime('%d/%m/%Y')} → {rng[1].strftime('%d/%m/%Y')}"
    return "Selecionar período"


def _render_period_popover(container) -> tuple[date, date]:
    today = date.today()
    _ensure_period_state()

    rng = st.session_state[PERIOD_RANGE_KEY]
    preset = st.session_state.get(PERIOD_PRESET_KEY, _DEFAULT_PRESET)
    btn_label = _period_button_label(rng, preset)

    with container:
        filter_label("Período")
        with st.popover(btn_label, use_container_width=True):
            new_preset = st.selectbox(
                "Atalho", PRESETS_PT,
                key=PERIOD_PRESET_KEY,
                label_visibility="collapsed",
            )
            last_applied = st.session_state.get(_PERIOD_LAST_APPLIED)
            if new_preset != "Personalizado" and new_preset != last_applied:
                new_range = resolve_preset(new_preset, today)
                if new_range:
                    st.session_state[PERIOD_RANGE_KEY] = new_range
                st.session_state[_PERIOD_LAST_APPLIED] = new_preset
            st.date_input(
                "Intervalo",
                key=PERIOD_RANGE_KEY,
                format="DD/MM/YYYY",
                label_visibility="collapsed",
            )

    rng = st.session_state[PERIOD_RANGE_KEY]
    if isinstance(rng, tuple) and len(rng) == 2:
        return rng
    if isinstance(rng, tuple) and len(rng) == 1:
        return rng[0], rng[0]
    return today, today


# =============================================================================
# PageContext
# =============================================================================

@dataclass
class PageContext:
    data_ini: date
    data_fim: date
    filter_keys: list[str]
    _filter_cols: dict[str, Any]
    selections: dict[str, list[str]] = field(default_factory=dict)
    _rendered: bool = False

    def apply_filters(self, df: pd.DataFrame,
                      col_map: dict[str, str]) -> pd.DataFrame:
        self._render_widgets(df, col_map)
        return self._apply_selections(df, col_map)

    def refilter(self, df: pd.DataFrame,
                 col_map: dict[str, str]) -> pd.DataFrame:
        return self._apply_selections(df, col_map)

    def _render_widgets(self, df: pd.DataFrame,
                        col_map: dict[str, str]) -> None:
        if self._rendered:
            return
        for key in self.filter_keys:
            col = col_map.get(key)
            if col is None:
                continue
            label = _FILTER_LABELS.get(key, key.replace("_", " ").title())
            if df.empty or col not in df.columns:
                opts: list[str] = []
            else:
                opts = sorted(df[col].dropna().astype(str).unique().tolist())
            widget_key = f"_filter_{key}"
            default_sel = _resolve_default(key, opts)
            with self._filter_cols[key]:
                filter_label(label)
                sel = _multiselect_compact(label, opts, widget_key, default_sel)
            self.selections[key] = list(sel)
        self._rendered = True

    def _apply_selections(self, df: pd.DataFrame,
                          col_map: dict[str, str]) -> pd.DataFrame:
        if df.empty:
            return df
        mask = pd.Series([True] * len(df), index=df.index)
        for key, col in col_map.items():
            if col not in df.columns:
                continue
            sel = self.selections.get(key, [])
            if not sel:
                continue
            all_vals = df[col].dropna().astype(str).unique().tolist()
            if len(sel) >= len(all_vals):
                continue
            mask &= df[col].astype(str).isin(sel)
        return df[mask]


# =============================================================================
# Renderização do título dentro da 1ª coluna do header
# =============================================================================

def _render_title_block(container, title: str, subtitle: str, logo_text: str) -> None:
    sub_html = (
        f'<div class="ph-subtitle">{html.escape(subtitle)}</div>' if subtitle else ""
    )
    with container:
        st.markdown(
            f'<div class="page-header-title">'
            f'<span class="ph-logo">{html.escape(logo_text)}</span>'
            f'<span class="ph-divider"></span>'
            f'<div class="ph-text">'
            f'<div class="ph-title">{html.escape(title)}</div>'
            f'{sub_html}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# =============================================================================
# Entrypoint
# =============================================================================

_TITLE_WEIGHT = 2.2
_FILTER_WEIGHT = 1.4
_PERIOD_WEIGHT = 1.7


def start_page(
    title: str,
    subtitle: str = "",
    filters: list[str] | tuple[str, ...] = (),
    right_text: str | None = None,  # mantido p/ compat — não renderizado no novo layout
    logo_text: str = "RECONECTA",
    include_period: bool = True,
) -> PageContext:
    """Renderiza, em uma única linha (faixa vinho), o título + filtros categóricos
    + período. Retorna `PageContext` com data_ini/data_fim e colunas reservadas
    para os filtros (preencha com `ctx.apply_filters`)."""
    _ensure_period_state()

    weights = [_TITLE_WEIGHT] + [_FILTER_WEIGHT] * len(filters)
    if include_period:
        weights.append(_PERIOD_WEIGHT)

    cols = st.columns(weights, gap="small", vertical_alignment="center")

    _render_title_block(cols[0], title, subtitle, logo_text)

    filter_cols_dict: dict[str, Any] = {}
    for i, key in enumerate(filters):
        filter_cols_dict[key] = cols[1 + i]

    if include_period:
        data_ini, data_fim = _render_period_popover(cols[-1])
    else:
        rng = st.session_state.get(PERIOD_RANGE_KEY) or (date.today(), date.today())
        data_ini, data_fim = rng if isinstance(rng, tuple) and len(rng) == 2 else (date.today(), date.today())

    return PageContext(
        data_ini=data_ini,
        data_fim=data_fim,
        filter_keys=list(filters),
        _filter_cols=filter_cols_dict,
    )
