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
_PERIOD_INITIALIZED = "_global_period_initialized"

# IMPORTANTE: a primeira opção é o fallback que `st.selectbox` exibe quando
# session_state[key] não está disponível NO MOMENTO em que o widget renderiza.
# Como o selectbox vive dentro de `st.popover` (container lazy), há uma
# janela em que o widget instancia sem ler o session_state pré-populado e
# cai no índice 0. Se PRESETS_PT[0] != _DEFAULT_PRESET, o widget escolhe
# "Semana atual" e sobrescreve PRESET no session_state — o bug reportado.
# Manter "Mês atual" como índice 0 elimina essa classe de problema.
_DEFAULT_PRESET = "Mês atual"

PRESETS_PT: list[str] = [
    "Mês atual",        # <- índice 0 = default robusto (fallback do widget)
    "Semana atual",
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
    """One-shot init do estado de período + auto-heal de keys ausentes.

    Regras:
      - 1ª chamada (flag `_PERIOD_INITIALIZED` ausente):
          - PRESET = "Mês atual"
          - RANGE  = (1º dia do mês, último dia do mês)
          - flag   = True
      - Chamadas subsequentes: NÃO sobrescreve valores existentes do
        usuário. Apenas restaura keys que tenham sido **removidas** pelo
        Streamlit (containers lazy como `st.popover` podem limpar
        `session_state[key]` de widgets ao desmontar entre reruns —
        causa do KeyError reportado).

    Aceita tupla de 1 elemento (`(d,)`) como `(d, d)` — Streamlit emite
    1-tupla durante seleção parcial no `st.date_input` em modo range.
    Antes essa situação resetava pro preset (bug "volta sozinho pro mês
    inteiro").

    Mudanças intencionais de PRESET/RANGE vêm dos callbacks
    `_on_period_preset_change` e `_on_period_range_change`.
    """
    today = date.today()

    # 1) Seed inicial UMA VEZ por sessão.
    if not st.session_state.get(_PERIOD_INITIALIZED):
        st.session_state[PERIOD_PRESET_KEY] = _DEFAULT_PRESET
        rng = (resolve_preset(_DEFAULT_PRESET, today)
               or (today - timedelta(days=30), today))
        st.session_state[PERIOD_RANGE_KEY] = rng
        st.session_state[_PERIOD_INITIALIZED] = True

    # 2) Auto-heal: se algum dos valores foi removido pelo Streamlit
    #    (widget cleanup em popover), restaura *só o ausente* — sem tocar
    #    em valor existente do usuário. Não confunde com o bug antigo
    #    (que sobrescrevia mesmo quando o user já tinha mexido).
    if PERIOD_PRESET_KEY not in st.session_state:
        st.session_state[PERIOD_PRESET_KEY] = _DEFAULT_PRESET
    elif st.session_state[PERIOD_PRESET_KEY] not in PRESETS_PT:
        # Valor inválido (algum widget legado escreveu lixo): corrige.
        st.session_state[PERIOD_PRESET_KEY] = _DEFAULT_PRESET

    if PERIOD_RANGE_KEY not in st.session_state:
        st.session_state[PERIOD_RANGE_KEY] = (
            resolve_preset(
                st.session_state[PERIOD_PRESET_KEY], today
            ) or (today - timedelta(days=30), today)
        )

    # 3) Devolve a tupla normalizada SEM reescrever valores válidos.
    rng = st.session_state[PERIOD_RANGE_KEY]
    if isinstance(rng, tuple):
        if len(rng) == 2:
            return rng
        if len(rng) == 1:
            # User no meio de uma seleção (data_ini escolhida, data_fim
            # ainda não). Trata como (d, d) — não reseta o range.
            return rng[0], rng[0]
    # Último fallback (corner case: tipo errado em session_state).
    fallback = (resolve_preset(_DEFAULT_PRESET, today)
                or (today - timedelta(days=30), today))
    st.session_state[PERIOD_RANGE_KEY] = fallback
    return fallback


def _on_period_preset_change() -> None:
    """Callback do selectbox de preset. Roda DENTRO do mesmo ciclo do
    Streamlit, antes de qualquer leitura subsequente do session_state.
    Re-resolve o RANGE para casar com o preset escolhido."""
    today = date.today()
    new_preset = st.session_state.get(PERIOD_PRESET_KEY)
    if new_preset not in PRESETS_PT:
        st.session_state[PERIOD_PRESET_KEY] = _DEFAULT_PRESET
        new_preset = _DEFAULT_PRESET
    if new_preset != "Personalizado":
        new_range = resolve_preset(new_preset, today)
        if new_range:
            st.session_state[PERIOD_RANGE_KEY] = new_range


def _on_period_range_change() -> None:
    """Callback do date_input. Quando o user altera o range manualmente,
    troca o preset para "Personalizado" se o range escolhido não casar
    com nenhum preset conhecido. Mantém o label do botão coerente com a
    janela exibida."""
    today = date.today()
    rng = st.session_state.get(PERIOD_RANGE_KEY)
    if not (isinstance(rng, tuple) and len(rng) == 2):
        # Tupla parcial (1 elemento) durante seleção: ainda não decide.
        return
    current_preset = st.session_state.get(PERIOD_PRESET_KEY)
    # Se o preset atual já bate com o range escolhido, mantém como está.
    if current_preset and current_preset != "Personalizado":
        if resolve_preset(current_preset, today) == rng:
            return
    st.session_state[PERIOD_PRESET_KEY] = "Personalizado"


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
    # tipo_sdr abre vazio (= "Todos") — pedido do user. As categorias
    # "Sem SDR" e "SDR não classificado" só aparecem quando o usuário
    # explicitamente seleciona algo no filtro.
    "tipo_sdr":    "none",
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
    # `_ensure_period_state` faz auto-heal: se Streamlit limpou a key de
    # algum widget (popover/expander unmount entre reruns), ela é
    # restaurada aqui antes de qualquer leitura.
    safe_rng = _ensure_period_state()

    # Leitura DEFENSIVA com `.get(...)` — mesmo após o auto-heal, manter
    # `.get` evita KeyError em qualquer corner case onde o Streamlit
    # rodar o leitor antes do seed (ex.: re-import lazy do módulo).
    rng = st.session_state.get(PERIOD_RANGE_KEY, safe_rng)
    preset = st.session_state.get(PERIOD_PRESET_KEY, _DEFAULT_PRESET)
    if preset not in PRESETS_PT:
        preset = _DEFAULT_PRESET
        st.session_state[PERIOD_PRESET_KEY] = preset
    btn_label = _period_button_label(rng, preset)

    with container:
        filter_label("Período")
        with st.popover(btn_label, use_container_width=True):
            # `on_change` roda no MESMO ciclo do Streamlit antes do próximo
            # render, garantindo que RANGE/LAST_APPLIED já estejam alinhados
            # quando a página seguinte ler `data_ini`/`data_fim`. Sem esse
            # callback, mudar o preset deixava o range com 1 ciclo de atraso.
            st.selectbox(
                "Atalho", PRESETS_PT,
                key=PERIOD_PRESET_KEY,
                label_visibility="collapsed",
                on_change=_on_period_preset_change,
            )
            st.date_input(
                "Intervalo",
                key=PERIOD_RANGE_KEY,
                format="DD/MM/YYYY",
                label_visibility="collapsed",
                on_change=_on_period_range_change,
            )

        # Debug helper — exibe o estado interno do filtro quando a query
        # string contém ?debug_period=1. Útil pra reproduzir bug de sync
        # sem instrumentar logs em produção.
        if st.query_params.get("debug_period") == "1":
            with st.expander("🔧 debug_period", expanded=False):
                st.write({
                    "PERIOD_PRESET_KEY (label)": st.session_state.get(PERIOD_PRESET_KEY),
                    "PERIOD_RANGE_KEY (range)":  st.session_state.get(PERIOD_RANGE_KEY),
                    "_PERIOD_INITIALIZED":       st.session_state.get(_PERIOD_INITIALIZED),
                    "PRESETS_PT[0] (fallback)":  PRESETS_PT[0],
                    "_DEFAULT_PRESET":           _DEFAULT_PRESET,
                })

    # Mesma proteção da leitura no topo da função: `.get` com fallback.
    rng = st.session_state.get(PERIOD_RANGE_KEY, safe_rng)
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
