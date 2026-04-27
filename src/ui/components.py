"""Primitivos visuais do dashboard — cards, headers, filtros."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, timedelta

import streamlit as st

from .theme import GLOBAL_CSS


# ---------------------------------------------------------------------------
# Setup / boilerplate
# ---------------------------------------------------------------------------

def apply_dark_theme() -> None:
    """Injeta fontes + CSS global. Chamar uma vez por página, após set_page_config."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def sidebar_brand(subtitle: str = "Inteligência Comercial") -> None:
    with st.sidebar:
        st.markdown(
            f'<div class="brand">'
            f'<div class="brand-title">RECONECTA BI</div>'
            f'<div class="brand-sub">{html.escape(subtitle)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

def page_header(
    title: str,
    subtitle: str = "",
    data_ini: date | None = None,
    data_fim: date | None = None,
) -> None:
    periodo_html = ""
    if data_ini and data_fim:
        periodo_html = (
            f'<div class="page-header-right">'
            f'<div class="period-label">Período ativo</div>'
            f'<div class="period-badge">'
            f'{data_ini.strftime("%d/%m/%Y")} → {data_fim.strftime("%d/%m/%Y")}'
            f'</div></div>'
        )

    sub_html = f'<div class="subtitle">{html.escape(subtitle)}</div>' if subtitle else ""

    st.markdown(
        f'<div class="page-header">'
        f'<div class="page-header-left">'
        f'<h1>{html.escape(title)}</h1>'
        f'{sub_html}'
        f'</div>'
        f'{periodo_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "") -> None:
    sub = f'<span class="section-sub">{html.escape(subtitle)}</span>' if subtitle else ""
    st.markdown(
        f'<div class="section-header">'
        f'<span class="section-title">{html.escape(title)}</span>'
        f'{sub}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

@dataclass
class KPI:
    label: str
    value: str
    hint: str | None = None
    hero: bool = False


def metric_card(label: str, value: str, hint: str | None = None, hero: bool = False) -> None:
    cls = "kpi-card hero" if hero else "kpi-card"
    hint_html = f'<div class="kpi-hint">{html.escape(hint)}</div>' if hint else ""
    st.markdown(
        f'<div class="{cls}">'
        f'<div class="kpi-label">{html.escape(label)}</div>'
        f'<div class="kpi-value">{html.escape(str(value))}</div>'
        f'{hint_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def metric_row(items: list[KPI], gap: str = "small") -> None:
    cols = st.columns(len(items), gap=gap)
    for col, item in zip(cols, items):
        with col:
            metric_card(item.label, item.value, item.hint, item.hero)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

_PRESETS = [
    "Últimos 7 dias",
    "Últimos 30 dias",
    "Últimos 90 dias",
    "Mês atual",
    "Mês anterior",
    "Ano atual",
    "Últimos 12 meses",
    "Personalizado",
]


def date_range_sidebar(default_days: int = 90, key: str = "periodo") -> tuple[date, date]:
    """Seletor de período padrão — com presets e formatação consistente."""
    today = date.today()
    end = today
    start = today - timedelta(days=default_days)

    with st.sidebar:
        st.markdown("### Período")
        preset = st.selectbox(
            "Preset",
            _PRESETS,
            index=2,
            key=f"{key}_preset",
            label_visibility="collapsed",
        )

        if preset == "Últimos 7 dias":
            start, end = today - timedelta(days=7), today
        elif preset == "Últimos 30 dias":
            start, end = today - timedelta(days=30), today
        elif preset == "Últimos 90 dias":
            start, end = today - timedelta(days=90), today
        elif preset == "Mês atual":
            start, end = today.replace(day=1), today
        elif preset == "Mês anterior":
            first_this = today.replace(day=1)
            end = first_this - timedelta(days=1)
            start = end.replace(day=1)
        elif preset == "Ano atual":
            start, end = date(today.year, 1, 1), today
        elif preset == "Últimos 12 meses":
            start, end = today - timedelta(days=365), today

        picked = st.date_input(
            "Intervalo personalizado" if preset == "Personalizado" else "Intervalo",
            (start, end),
            format="DD/MM/YYYY",
            key=f"{key}_range",
        )

    if isinstance(picked, tuple) and len(picked) == 2:
        return picked
    return start, end


def multiselect_pill(label: str, options: list[str], key: str,
                     default_all: bool = True) -> list[str]:
    with st.sidebar:
        st.markdown(f"### {label}")
        if not options:
            st.caption("Nenhuma opção disponível.")
            return []
        default = options if default_all else []
        return st.multiselect(
            label, options, default=default, key=key,
            label_visibility="collapsed",
        )


# =============================================================================
# Looker-style components (home)
# =============================================================================

def top_header(title: str, subtitle: str = "",
               logo_text: str = "RECONECTA",
               right_text: str | None = None) -> None:
    """LEGACY — preferir `start_page` (que renderiza título dentro do header
    unificado). Mantido só para usos diretos."""
    sub_html = (f'<div class="ph-subtitle">{html.escape(subtitle)}</div>'
                if subtitle else "")
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


def filter_label(text: str) -> None:
    """Rótulo pequeno (caps) acima de um filtro inline."""
    st.markdown(f'<div class="filter-strip-label">{html.escape(text)}</div>',
                unsafe_allow_html=True)


def section_title(title: str, subtitle: str = "") -> None:
    sub = f'<span class="sub">{html.escape(subtitle)}</span>' if subtitle else ""
    st.markdown(
        f'<div class="sec-title">{html.escape(title)}{sub}</div>',
        unsafe_allow_html=True,
    )


def _fmt_delta(delta_pct: float | None) -> tuple[str, str]:
    """Retorna (classe_css, texto) para um delta em %."""
    if delta_pct is None:
        return "flat", "—"
    if abs(delta_pct) < 0.05:
        return "flat", "0,0%"
    arrow = "↑" if delta_pct > 0 else "↓"
    cls = "up" if delta_pct > 0 else "down"
    return cls, f"{arrow} {abs(delta_pct):.1f}%".replace(".", ",")


def metric_card_v2(
    label: str,
    value: str,
    delta_pct: float | None = None,
    hint: str | None = None,
    accent: bool = False,
    breakdown: list[tuple[str, str]] | None = None,
) -> None:
    """Card Looker-style:
    - header: label (esq.) + delta pill opcional (dir.)
    - valor grande
    - hint pequeno (opcional)
    - breakdown estruturado (opcional)
    """
    delta_html = ""
    if delta_pct is not None:
        cls, txt = _fmt_delta(delta_pct)
        delta_html = f'<span class="mcard-delta {cls}">{html.escape(txt)}</span>'

    hint_html = (f'<div class="mcard-hint">{html.escape(hint)}</div>'
                 if hint else "")

    break_html = ""
    if breakdown:
        rows = "".join(
            f'<div class="mcard-break-row"><span class="k">{html.escape(k)}</span>'
            f'<span class="v">{html.escape(v)}</span></div>'
            for k, v in breakdown
        )
        break_html = f'<div class="mcard-break">{rows}</div>'

    val_cls = "mcard-value accent" if accent else "mcard-value"
    st.markdown(
        f'<div class="mcard">'
        f'<div class="mcard-head">'
        f'<span class="mcard-label">{html.escape(label)}</span>'
        f'{delta_html}'
        f'</div>'
        f'<div class="{val_cls}">{html.escape(str(value))}</div>'
        f'{hint_html}'
        f'{break_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def hero_revenue_card(
    receita_fmt: str,
    meta_fmt: str,
    pct_atingimento: float,
    status: str,  # "abaixo" / "proximo" / "acima" / "sem_meta"
) -> None:
    """Bloco principal de receita com barra de progresso vs meta + status."""
    fill = min(max(pct_atingimento, 0), 150)  # cap visual em 150%
    fill_cls = "over" if pct_atingimento >= 100 else ""

    status_map = {
        "abaixo":   ("below", "Abaixo do esperado"),
        "proximo":  ("close", "Próximo da meta"),
        "acima":    ("above", "Acima do esperado"),
        "sem_meta": ("none", "Sem meta definida"),
        "sem_dados":("none", "Sem dados"),
    }
    pill_cls, pill_text = status_map.get(status, ("none", "—"))

    pct_txt = f"{pct_atingimento:.1f}% da meta ({meta_fmt})".replace(".", ",")

    st.markdown(
        f'<div class="hero-fin">'
        f'<div class="hero-fin-label">Receita</div>'
        f'<div class="hero-fin-value">{html.escape(receita_fmt)}</div>'
        f'<div class="hero-fin-bar">'
        f'<div class="hero-fin-bar-fill {fill_cls}" style="width: {fill}%"></div>'
        f'</div>'
        f'<div class="hero-fin-foot">'
        f'<span class="hero-fin-pct">{html.escape(pct_txt)}</span>'
        f'<span class="status-pill {pill_cls}">{html.escape(pill_text)}</span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
