"""Primitivos visuais do dashboard — cards, headers, filtros."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .app_theme import apply_app_theme


# ---------------------------------------------------------------------------
# Column config — tabelas de ranking (Time de Vendas → Visão Geral e
# Executivas & Times). Compartilhado entre as duas páginas para garantir
# consistência visual e evitar drift. As colunas % vêm da view já na
# escala 0–100, então o format só anexa o sufixo `%` (não multiplica).
# Moeda fica sem casas decimais por preferência do dashboard atual.
# ---------------------------------------------------------------------------

_RANKING_MOEDA_LABELS: dict[str, str] = {
    "montante":           "Montante",
    "receita":            "Receita",
    "ticket_medio":       "Ticket médio",
    "montante_mais_12":   "Montante +12",
    "montante_menos_12":  "Montante -12",
    "montante_nao_atua":  "Montante Não atua",
    "receita_mais_12":    "Receita +12",
    "receita_menos_12":   "Receita -12",
    "receita_nao_atua":   "Receita Não atua",
}

_RANKING_PCT_LABELS: dict[str, str] = {
    "pct_comparecimento": "% Comparecimento",
    "pct_conversao":      "% Conversão",
    "pct_vendas":         "% Vendas",
    "pct_recebimento":    "% Recebimento",
    "pct_agendamento":    "% Agendamento",
}


def ranking_column_config(
    df: pd.DataFrame,
    pin_executiva: bool = False,
    pin_column: str | None = None,
) -> dict:
    """`column_config` p/ um df de ranking (principal ou complementar).

    Devolve só configs das colunas presentes no df — passar o dict pelo
    `st.dataframe(..., column_config=...)` em tabelas que não têm todas
    essas colunas não gera warning.

    - Moeda: `R$ %.0f` (sem casas decimais, padrão do dashboard).
    - Percentual: `%.2f%%` (valores já vêm na escala 0–100, sem
      multiplicação).
    - `pin_executiva=True` fixa a coluna `executiva` à esquerda — usar
      na tabela detalhada, onde o scroll horizontal esconde o nome da
      closer.
    - `pin_column` fixa qualquer coluna pelo nome exibido (ex.: `Closer`,
      `Pré-venda` na página Lead In & Reuniões).
    """
    if df is None or getattr(df, "empty", True):
        return {}
    cfg: dict = {}
    pin_col = pin_column or ("executiva" if pin_executiva else None)
    if pin_col and pin_col in df.columns:
        cfg[pin_col] = st.column_config.Column(pinned=True)
    for col, label in _RANKING_MOEDA_LABELS.items():
        if col in df.columns:
            cfg[col] = st.column_config.NumberColumn(label, format="R$ %.0f")
    for col, label in _RANKING_PCT_LABELS.items():
        if col in df.columns:
            cfg[col] = st.column_config.NumberColumn(label, format="%.2f%%")
    return cfg


# ---------------------------------------------------------------------------
# Setup / boilerplate
# ---------------------------------------------------------------------------

def apply_dark_theme() -> None:
    """Injeta fontes + CSS global. Chamar uma vez por página, após set_page_config."""
    apply_app_theme()


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


_ORIGEM_CHIP_CLS = {
    "VSL":        "vsl",
    "SE":         "se",
    "AG":         "ag",
    "Sem origem": "sem-origem",
}


def _qual_split_html(items: list[tuple[str, str]]) -> str:
    """Bloco compacto Qualificados / Não Qualificados (nowrap por chip)."""
    if not items:
        return ""
    chip_htmls = [
        f'<span class="mcard-qual-chip">'
        f'<span class="lbl">{html.escape(lbl)}:</span> '
        f'<span class="val">{html.escape(str(val))}</span>'
        f"</span>"
        for lbl, val in items
    ]
    inline_parts: list[str] = []
    for i, chip in enumerate(chip_htmls):
        if i > 0:
            inline_parts.append(
                '<span class="mcard-qual-sep" aria-hidden="true">·</span>'
            )
        inline_parts.append(chip)
    return (
        '<div class="mcard-qual-split">'
        f'<div class="mcard-qual-inline">{"".join(inline_parts)}</div>'
        '<div class="mcard-qual-stack">'
        f'{"".join(chip_htmls)}'
        "</div>"
        "</div>"
    )


def _origens_chip_html(chip_lbl: str, chip_val: str) -> str:
    chip_cls = _ORIGEM_CHIP_CLS.get(chip_lbl, "")
    stripped = str(chip_val).strip()
    is_empty = (
        stripped in ("—", "-", "0")
        or stripped.startswith("0 ")
        or stripped.startswith("0/")
        or stripped.startswith("0,0%")
    )
    extra = " empty" if is_empty else ""
    return (
        f'<span class="mcard-origens-chip {chip_cls}{extra}">'
        f'<span class="lbl">{html.escape(chip_lbl)}</span>'
        f'<span class="val">{html.escape(stripped)}</span>'
        "</span>"
    )


def _metric_card_resumo_html(
    *,
    label: str,
    label_attr: str,
    value: str,
    val_cls: str,
    delta_html: str,
    hint_html: str,
    breakdown: list[tuple[str, str]] | None,
    breakdown_placeholder: bool,
    origens: dict | None,
) -> str:
    """Layout fixo da linha executiva (Visão Geral Pré-vendas)."""
    if breakdown:
        cost_lbl, cost_val = breakdown[0]
        cost_html = (
            f'<div class="mcard-cost">'
            f"<span>{html.escape(cost_lbl)}</span>"
            f"<strong>{html.escape(str(cost_val))}</strong>"
            f"</div>"
        )
    elif breakdown_placeholder:
        cost_html = (
            '<div class="mcard-cost mcard-cost-placeholder" aria-hidden="true">'
            "<span>&nbsp;</span><strong>&nbsp;</strong>"
            "</div>"
        )
    else:
        cost_html = ""

    if origens:
        title = origens.get("title", "Por origem")
        chips = origens.get("chips") or []
        muted = origens.get("muted")
        chips_html = "".join(
            _origens_chip_html(lbl, val) for lbl, val in chips
        )
        origin_html = (
            f'<div class="mcard-origin-block">'
            f'<span class="mcard-origens-title">{html.escape(title)}</span>'
            f'<div class="mcard-origens-chips">{chips_html}</div>'
            f"</div>"
        )
        if muted:
            m_lbl, m_val = muted
            footer_html = (
                f'<div class="mcard-footer">'
                f'<span class="lbl">{html.escape(m_lbl)}</span>'
                f'<span class="val">{html.escape(str(m_val))}</span>'
                f"</div>"
            )
        else:
            footer_html = (
                '<div class="mcard-footer mcard-footer-placeholder" '
                'aria-hidden="true">'
                "<span>&nbsp;</span><span>&nbsp;</span>"
                "</div>"
            )
    else:
        origin_html = (
            '<div class="mcard-origin-block mcard-origin-placeholder" '
            'aria-hidden="true">'
            '<span class="mcard-origens-title">&nbsp;</span>'
            '<div class="mcard-origens-chips">&nbsp;</div>'
            "</div>"
        )
        footer_html = (
            '<div class="mcard-footer mcard-footer-placeholder" '
            'aria-hidden="true">'
            "<span>&nbsp;</span><span>&nbsp;</span>"
            "</div>"
        )

    return (
        f'<div class="mcard mcard-resumo">'
        f'<div class="mcard-header-block">'
        f'<div class="mcard-head">'
        f'<span class="mcard-label"{label_attr}>{html.escape(label)}</span>'
        f"{delta_html}"
        f"</div>"
        f'<div class="{val_cls}">{html.escape(str(value))}</div>'
        f"{hint_html}"
        f"</div>"
        f"{cost_html}"
        f'<div class="mcard-resumo-spacer" aria-hidden="true"></div>'
        f"{origin_html}"
        f"{footer_html}"
        f"</div>"
    )


def metric_card_v2(
    label: str,
    value: str,
    delta_pct: float | None = None,
    hint: str | None = None,
    accent: bool = False,
    breakdown: list[tuple[str, str]] | None = None,
    qual_split: list[tuple[str, str]] | None = None,
    origens: dict | None = None,
    variant: str | None = None,
    breakdown_placeholder: bool = False,
    help: str | None = None,
    card_class: str | None = None,
) -> None:
    """Card Looker-style:
    - header: label (esq.) + delta pill opcional (dir.)
    - valor grande
    - hint pequeno (opcional)
    - breakdown estruturado (opcional)
    - origens (opcional): bloco "Por origem" com chips coloridos +
      linha muted. Estrutura esperada:
        {
            "title": "Por origem",
            "chips": [("VSL", "3"), ("SE", "1"), ("AG", "0")],
            "muted": ("Sem origem", "1.038"),   # opcional
        }
      Cada chip ganha classe CSS .vsl / .se / .ag por label conhecido;
      valores '—' ou '0' recebem .empty pra atenuar visualmente.

    `variant="resumo"` — layout alto com áreas fixas (main + origem) para
    alinhar cards em linhas densas (ex.: Visão Geral Pré-vendas).

    `breakdown_placeholder=True` — reserva altura do bloco de custo quando
    o card não tem breakdown (mantém alinhamento entre cards vizinhos).

    `help` — tooltip nativo no título (regras técnicas sem poluir o card).
    """
    delta_html = ""
    if delta_pct is not None:
        cls, txt = _fmt_delta(delta_pct)
        delta_html = f'<span class="mcard-delta {cls}">{html.escape(txt)}</span>'

    label_attr = f' title="{html.escape(help)}"' if help else ""

    if hint:
        hint_html = f'<div class="mcard-hint">{html.escape(hint)}</div>'
    elif variant == "resumo":
        hint_html = (
            '<div class="mcard-hint mcard-hint-placeholder" '
            'aria-hidden="true">&nbsp;</div>'
        )
    else:
        hint_html = ""

    val_cls = "mcard-value accent" if accent else "mcard-value"

    if variant == "resumo":
        st.markdown(
            _metric_card_resumo_html(
                label=label,
                label_attr=label_attr,
                value=str(value),
                val_cls=val_cls,
                delta_html=delta_html,
                hint_html=hint_html,
                breakdown=breakdown,
                breakdown_placeholder=breakdown_placeholder,
                origens=origens,
            ),
            unsafe_allow_html=True,
        )
        return

    break_html = ""
    if qual_split:
        break_html = _qual_split_html(qual_split)
    elif breakdown:
        rows = "".join(
            f'<div class="mcard-break-row"><span class="k">{html.escape(k)}</span>'
            f'<span class="v">{html.escape(v)}</span></div>'
            for k, v in breakdown
        )
        break_html = f'<div class="mcard-break">{rows}</div>'

    origens_html = ""
    if origens:
        title = origens.get("title", "Por origem")
        chips = origens.get("chips") or []
        muted = origens.get("muted")
        chips_html = "".join(
            _origens_chip_html(lbl, val) for lbl, val in chips
        )
        chips_wrap = (
            f'<div class="mcard-origens-chips">{chips_html}</div>'
            if chips_html else ""
        )
        muted_html = ""
        if muted:
            m_lbl, m_val = muted
            muted_html = (
                f'<div class="mcard-origens-muted">'
                f'<span class="lbl">{html.escape(m_lbl)}</span>'
                f'<span class="val">{html.escape(str(m_val))}</span>'
                f"</div>"
            )
        origens_html = (
            f'<div class="mcard-origens">'
            f'<span class="mcard-origens-title">{html.escape(title)}</span>'
            f"{chips_wrap}"
            f"{muted_html}"
            f"</div>"
        )

    card_cls = "mcard"
    if card_class:
        card_cls += f" {card_class}"

    st.markdown(
        f'<div class="{card_cls}">'
        f'<div class="mcard-head">'
        f'<span class="mcard-label"{label_attr}>{html.escape(label)}</span>'
        f"{delta_html}"
        f"</div>"
        f'<div class="{val_cls}">{html.escape(str(value))}</div>'
        f"{hint_html}"
        f"{break_html}"
        f"{origens_html}"
        f"</div>",
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
