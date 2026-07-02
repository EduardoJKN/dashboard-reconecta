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

# Shadow keys (NÃO atreladas a widget). Streamlit pode limpar a key de um
# widget que não foi renderizado num rerun (o popover é lazy + a troca de
# página via st.navigation pode disparar esse cleanup), e isso fazia o
# período voltar pro default ao navegar entre páginas. Persistimos o valor
# real nessas keys-sombra e hidratamos a key do widget a partir delas
# antes de cada render.
_PERSIST_PRESET_KEY = "_dashboard_period_preset_persist"
_PERSIST_RANGE_KEY = "_dashboard_period_range_persist"

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
    """Estado global do período — persistente entre páginas.

    O valor real fica em `_PERSIST_PRESET_KEY` / `_PERSIST_RANGE_KEY`
    (chaves SEM widget, nunca limpas pelo Streamlit). A cada rerun, antes
    do widget renderizar, hidratamos `PERIOD_PRESET_KEY` /
    `PERIOD_RANGE_KEY` a partir do persist — assim o popover sempre
    aparece com o último valor escolhido, mesmo após navegar de página.

    Mudanças do usuário entram via callbacks (`_on_period_preset_change`,
    `_on_period_range_change`) que escrevem em AMBOS (widget + persist).

    Aceita tupla de 1 elemento (`(d,)`) como `(d, d)` — Streamlit emite
    1-tupla durante seleção parcial no `st.date_input` em modo range.
    """
    today = date.today()

    # 1) Seed inicial UMA VEZ por sessão. Honra valores pré-existentes
    #    no widget key (test scripts via AppTest setam `PERIOD_*_KEY`
    #    antes do primeiro rerun).
    if not st.session_state.get(_PERIOD_INITIALIZED):
        existing_preset = st.session_state.get(PERIOD_PRESET_KEY)
        existing_range = st.session_state.get(PERIOD_RANGE_KEY)

        preset = existing_preset if existing_preset in PRESETS_PT else _DEFAULT_PRESET
        if isinstance(existing_range, tuple) and len(existing_range) == 2:
            rng = existing_range
        else:
            rng = (resolve_preset(preset, today)
                   or (today - timedelta(days=30), today))

        st.session_state[_PERSIST_PRESET_KEY] = preset
        st.session_state[_PERSIST_RANGE_KEY] = rng
        st.session_state[_PERIOD_INITIALIZED] = True

    # 2) Migração: cobre o caso em que algo (ex.: test script) atualizou
    #    apenas a key do widget após o init. Se persist está ausente mas
    #    o widget tem valor válido, copia para o persist.
    if _PERSIST_PRESET_KEY not in st.session_state:
        ep = st.session_state.get(PERIOD_PRESET_KEY)
        st.session_state[_PERSIST_PRESET_KEY] = (
            ep if ep in PRESETS_PT else _DEFAULT_PRESET
        )
    if _PERSIST_RANGE_KEY not in st.session_state:
        er = st.session_state.get(PERIOD_RANGE_KEY)
        if isinstance(er, tuple) and len(er) == 2:
            st.session_state[_PERSIST_RANGE_KEY] = er
        elif isinstance(er, tuple) and len(er) == 1:
            st.session_state[_PERSIST_RANGE_KEY] = (er[0], er[0])
        else:
            st.session_state[_PERSIST_RANGE_KEY] = (
                resolve_preset(st.session_state[_PERSIST_PRESET_KEY], today)
                or (today - timedelta(days=30), today)
            )

    # 3) Sanidade do persist.
    if st.session_state[_PERSIST_PRESET_KEY] not in PRESETS_PT:
        st.session_state[_PERSIST_PRESET_KEY] = _DEFAULT_PRESET

    persisted_rng = st.session_state[_PERSIST_RANGE_KEY]
    if isinstance(persisted_rng, tuple) and len(persisted_rng) == 1:
        persisted_rng = (persisted_rng[0], persisted_rng[0])
        st.session_state[_PERSIST_RANGE_KEY] = persisted_rng
    elif not (isinstance(persisted_rng, tuple) and len(persisted_rng) == 2):
        persisted_rng = (resolve_preset(st.session_state[_PERSIST_PRESET_KEY], today)
                         or (today - timedelta(days=30), today))
        st.session_state[_PERSIST_RANGE_KEY] = persisted_rng

    # 4) Hidrata as keys dos widgets ANTES de renderizarem — é isto que
    #    impede o reset ao trocar de página (Streamlit limpa silenciosamente
    #    a key de widget cuja instância não foi renderizada no rerun
    #    anterior; o persist sobrevive porque não está vinculado a widget).
    st.session_state[PERIOD_PRESET_KEY] = st.session_state[_PERSIST_PRESET_KEY]

    # Exceção: se o widget está no meio de uma seleção manual de range
    # (usuário já clicou na data inicial, ainda não escolheu a final),
    # o `st.date_input` mantém a key como uma 1-tupla. Reidratar com o
    # `persisted_rng` (2-tupla) aqui APAGA a seleção parcial e o calendário
    # volta ao range anterior, impedindo o segundo clique de fechar o range.
    # Preservamos a 1-tupla para que o próximo clique seja interpretado como
    # data final. O `_render_period_popover` continua devolvendo o range
    # aplicado (persist) enquanto a seleção não estiver completa, evitando
    # que as queries rodem com uma janela parcial.
    current_widget_rng = st.session_state.get(PERIOD_RANGE_KEY)
    is_partial_selection = (
        isinstance(current_widget_rng, tuple) and len(current_widget_rng) == 1
    )
    if not is_partial_selection:
        st.session_state[PERIOD_RANGE_KEY] = persisted_rng

    return persisted_rng


def _on_period_preset_change() -> None:
    """Callback do selectbox de preset. Roda DENTRO do mesmo ciclo do
    Streamlit, antes de qualquer leitura subsequente do session_state.
    Re-resolve o RANGE para casar com o preset escolhido e copia para o
    persist (shadow) — é o que garante a sobrevivência entre páginas."""
    today = date.today()
    new_preset = st.session_state.get(PERIOD_PRESET_KEY)
    if new_preset not in PRESETS_PT:
        st.session_state[PERIOD_PRESET_KEY] = _DEFAULT_PRESET
        new_preset = _DEFAULT_PRESET
    st.session_state[_PERSIST_PRESET_KEY] = new_preset
    if new_preset != "Personalizado":
        new_range = resolve_preset(new_preset, today)
        if new_range:
            st.session_state[PERIOD_RANGE_KEY] = new_range
            st.session_state[_PERSIST_RANGE_KEY] = new_range


def _on_period_range_change() -> None:
    """Callback do date_input. Quando o user altera o range manualmente,
    troca o preset para "Personalizado" se o range escolhido não casar
    com nenhum preset conhecido. Mantém o label do botão coerente com a
    janela exibida e propaga para o persist."""
    today = date.today()
    rng = st.session_state.get(PERIOD_RANGE_KEY)
    if not (isinstance(rng, tuple) and len(rng) == 2):
        # Tupla parcial (1 elemento) durante seleção: ainda não decide.
        return
    st.session_state[_PERSIST_RANGE_KEY] = rng
    current_preset = st.session_state.get(PERIOD_PRESET_KEY)
    # Se o preset atual já bate com o range escolhido, mantém como está.
    if current_preset and current_preset != "Personalizado":
        if resolve_preset(current_preset, today) == rng:
            return
    st.session_state[PERIOD_PRESET_KEY] = "Personalizado"
    st.session_state[_PERSIST_PRESET_KEY] = "Personalizado"


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
                    "PERIOD_PRESET_KEY (label)":   st.session_state.get(PERIOD_PRESET_KEY),
                    "PERIOD_RANGE_KEY (range)":    st.session_state.get(PERIOD_RANGE_KEY),
                    "_PERSIST_PRESET_KEY":         st.session_state.get(_PERSIST_PRESET_KEY),
                    "_PERSIST_RANGE_KEY":          st.session_state.get(_PERSIST_RANGE_KEY),
                    "_PERIOD_INITIALIZED":         st.session_state.get(_PERIOD_INITIALIZED),
                    "PRESETS_PT[0] (fallback)":    PRESETS_PT[0],
                    "_DEFAULT_PRESET":             _DEFAULT_PRESET,
                })

    # Mesma proteção da leitura no topo da função: `.get` com fallback.
    rng = st.session_state.get(PERIOD_RANGE_KEY, safe_rng)
    if isinstance(rng, tuple) and len(rng) == 2:
        return rng
    if isinstance(rng, tuple) and len(rng) == 1:
        # Seleção parcial em andamento — o usuário clicou só na data inicial.
        # Devolvemos o range aplicado (persist) para que o dashboard NÃO
        # reconsulte com uma janela de 1 dia enquanto o range não fecha.
        # Assim: calendário guarda o primeiro clique, dados seguem estáveis.
        return safe_rng
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
        # Lê do persist (sobrevive entre páginas), com fallback ao widget.
        rng = (st.session_state.get(_PERSIST_RANGE_KEY)
               or st.session_state.get(PERIOD_RANGE_KEY)
               or (date.today(), date.today()))
        data_ini, data_fim = rng if isinstance(rng, tuple) and len(rng) == 2 else (date.today(), date.today())

    return PageContext(
        data_ini=data_ini,
        data_fim=data_fim,
        filter_keys=list(filters),
        _filter_cols=filter_cols_dict,
    )
