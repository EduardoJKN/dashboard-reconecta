"""Temas visuais da One Page (PoC).

Permite alternar paleta de cores SÓ na One Page, sem mexer no tema global
do app (`theme.py` / `.streamlit/config.toml`). Funciona em 2 frentes:

1. **CSS scoped**: `apply_one_page_theme()` injeta `<style>` que sobrescreve
   `--color-*` apenas dentro de `section[data-testid="stMain"]`. Sidebar
   e outras páginas continuam usando o `:root` global definido em
   `theme.py`. Como cada página é um script Streamlit independente, o
   override desaparece automaticamente quando o usuário navega.

2. **Cores de gráficos (Plotly)**: `op_theme_color()` lê cores nomeadas
   do tema ativo (lendo de `st.session_state["op_theme"]`), substituindo
   acessos diretos a `PALETTE[...]`. `op_chart_apply_theme(fig)` aplica
   plot_bgcolor / gridcolor / font color compatíveis com o tema.

LIMITAÇÕES da PoC:
  - `st.dataframe` (Glide DataGrid) renderiza num iframe-canvas que
    ignora nossas CSS variables. Tabelas seguem o tema dark default do
    Streamlit; só fica visualmente "fora" no tema Looker. Resolver isso
    exigiria `.streamlit/config.toml`, fora de escopo.
  - Markdown / `st.info` / outros widgets nativos pegam o tema global
    do Streamlit. Aqui só temos controle sobre os componentes locais
    da One Page (cards `.op-*`, gráficos Plotly, faixa `.op-foot-row`).
  - O fundo da `section[data-testid="stMain"]` só é repintado quando o
    tema declarar `main_bg_override=True` (Looker). Em modo Dark, o
    `.stApp` global mantém o bg quente — mesmo visual de hoje.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


# ---------------------------------------------------------------------------
# Dicionário canônico de temas
# ---------------------------------------------------------------------------

ONE_PAGE_THEMES: dict[str, dict[str, Any]] = {
    "reconecta_dark": {
        "label": "Reconecta Dark",
        # Sobrescritas das CSS vars já usadas no `_OP_CARD_CSS` e nas
        # regras globais de `theme.py`. Os valores aqui replicam a paleta
        # atual (`PALETTE` em theme.py) — esse tema é no-op visual mas
        # mantém o esquema de override coerente.
        "css_vars": {
            "color-bg":            "#0a0806",
            "color-bg-soft":       "#110d09",
            "color-card":          "#161311",
            "color-card-hover":    "#1e1915",
            "color-card-strong":   "#1a1612",
            "color-border":        "#2a2118",
            "color-border-strong": "#3a2e20",
            "color-gold":          "#c9a84c",
            "color-gold-bright":   "#e8c96e",
            "color-gold-soft":     "#8a7230",
            "color-wine":          "#7c1f2e",
            "color-wine-light":    "#c03048",
            "color-wine-soft":     "#4a1219",
            "color-text":          "#f1e9df",
            "color-text-subtle":   "#a89a8a",
            "color-muted":         "#6a5a4a",
            "color-green":         "#4ade80",
            "color-green-soft":    "#1f4a2e",
            "color-red":           "#f87171",
            "color-red-soft":      "#4a1e1e",
            "color-yellow":        "#fbbf24",
            "color-blue":          "#60a5fa",
        },
        # Cores específicas de gráficos Plotly — lidas via op_theme_color().
        "chart": {
            "gold":         "#c9a84c",
            "gold_fill":    "rgba(201,168,76,0.18)",  # área translúcida (Investimento)
            "wine_light":   "#c03048",
            "green":        "#4ade80",
            "plus_12":      "#1D4ED8",  # azul (era hardcoded no .py)
            "minus_12":     "#7C3AED",  # roxo (era hardcoded no .py)
            "text":         "#f1e9df",
            "text_subtle": "#a89a8a",
            "grid":         "#2a2118",
            "plot_bg":      "#161311",  # = card
            "paper_bg":     "rgba(0,0,0,0)",
        },
        "main_bg_override": False,
    },
    "looker_legacy": {
        "label": "Legado Looker",
        # Paleta inspirada no Looker Studio classic: fundo claro,
        # cards brancos, vermelho-vinho nos destaques, dourado pros
        # números principais, verde Google pra positivos.
        "css_vars": {
            "color-bg":            "#f5f5f5",
            "color-bg-soft":       "#eeeeee",
            "color-card":          "#ffffff",
            "color-card-hover":    "#fafafa",
            "color-card-strong":   "#f5f5f5",
            "color-border":        "#dadce0",
            "color-border-strong": "#bdc1c6",
            "color-gold":          "#d4a017",
            "color-gold-bright":   "#f1c232",
            "color-gold-soft":     "#b8860b",
            "color-wine":          "#8b2828",
            "color-wine-light":    "#a83838",
            "color-wine-soft":     "#fce8e8",
            "color-text":          "#202124",
            "color-text-subtle":   "#5f6368",
            "color-muted":         "#80868b",
            "color-green":         "#0f9d58",
            "color-green-soft":    "#d4f4dd",
            "color-red":           "#d93025",
            "color-red-soft":      "#fce8e6",
            "color-yellow":        "#f4b400",
            "color-blue":          "#1a73e8",
        },
        "chart": {
            "gold":         "#d4a017",
            "gold_fill":    "rgba(212,160,23,0.18)",
            "wine_light":   "#a83838",
            "green":        "#0f9d58",
            "plus_12":      "#1a73e8",
            "minus_12":     "#7b1fa2",
            "text":         "#202124",
            "text_subtle": "#5f6368",
            "grid":         "#dadce0",
            "plot_bg":      "#ffffff",
            "paper_bg":     "rgba(0,0,0,0)",
        },
        "main_bg_override": True,
    },
}


DEFAULT_THEME = "reconecta_dark"
_SESSION_KEY = "op_theme"


# ---------------------------------------------------------------------------
# CSS compacto exclusivo do tema Looker Legacy
# ---------------------------------------------------------------------------
# Aplicado SÓ quando `looker_legacy` é o tema ativo (sem marker class, via
# emissão condicional dentro de `apply_one_page_theme`). Reduz padding/
# min-height/font dos cards, encurta gaps entre blocos, faixa de header
# mais baixa com sombra suave, e dá leveza com `box-shadow` discreto nos
# cards — visual de "relatório executivo Looker".
#
# `.op-card.wine-accent` é a única classe que casa um marker do Python
# (`wine_accent=True` em `one_page_metric_card`). Reservada pros cards
# financeiros principais (Montante, Investido). No tema Reconecta Dark
# é no-op (a classe existe no DOM mas nenhuma regra a estiliza).
_LOOKER_COMPACT_CSS = """
section[data-testid='stMain'] .op-card {
    padding: 8px 10px;
    min-height: 56px;
    border-radius: 6px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06),
                0 2px 8px rgba(0, 0, 0, 0.04);
}
section[data-testid='stMain'] .op-card.hero {
    padding: 10px 14px;
    min-height: 76px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08),
                0 4px 12px rgba(0, 0, 0, 0.04);
}
section[data-testid='stMain'] .op-card.compact {
    padding: 5px 8px;
    min-height: 44px;
}
section[data-testid='stMain'] .op-card .op-value         { font-size: 1.15rem; }
section[data-testid='stMain'] .op-card.hero .op-value    { font-size: 1.5rem;  }
section[data-testid='stMain'] .op-card.compact .op-value { font-size: 0.95rem; }
section[data-testid='stMain'] .op-card.wine-accent {
    border-top: 3px solid var(--color-wine);
}
section[data-testid='stMain'] [data-testid='stHorizontalBlock']:has(.op-card) {
    gap: 0.4rem !important;
    margin-bottom: 4px;
}
section[data-testid='stMain'] [data-testid='stColumn']:has(.op-card)
    [data-testid='stVerticalBlock'] {
    gap: 0.3rem !important;
}
section[data-testid='stMain'] .sec-title {
    margin: 6px 0 3px 0;
    padding-bottom: 2px;
    font-size: 0.9rem;
}
section[data-testid='stMain']
    [data-testid='stHorizontalBlock']:has(.page-header-title) {
    min-height: 48px;
    padding: 6px 16px !important;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.10);
}

/* `.stApp` é PAI de `section[data-testid='stMain']`. CSS variables
   ainda não ascendem do filho pro pai, então não dá pra fazer ele ler
   o `--color-bg` que sobrescrevemos dentro do stMain. Solução: definir
   o background direto com o valor literal do tema Looker (`#f5f5f5`,
   igual a `css_vars["color-bg"]`). Resolve a faixa escura que aparecia
   atrás do stHeader. Sidebar pinta por cima com `--color-bg-soft`
   global (vem do theme.py), então segue dark — exatamente o que
   queremos. */
.stApp { background: #f5f5f5; }

/* `st.info` / `st.warning` / `st.error` dentro da One Page — alerts
   nativos do Streamlit usam tons internos próprios que não respondem
   a `--color-card`. Aqui forçamos fundo branco + borda cinza-claro
   + texto escuro pra combinarem com o resto do Looker. Scope limita
   ao conteúdo da One Page, não vaza pra sidebar/outras páginas. */
section[data-testid='stMain'] [data-testid='stAlert'] {
    background-color: #ffffff;
    border: 1px solid #dadce0;
    color: #202124;
}
section[data-testid='stMain'] [data-testid='stAlert'] * {
    color: #202124 !important;
}

/* Chrome do Streamlit (canto superior direito: deploy, menu de 3
   pontos, ícones nativos). No tema Reconecta Dark a cor padrão clara
   funciona; no Looker o fundo claro deixa os ícones camuflados.
   Forçamos cor escura + hover sutil. `svg fill: currentColor` faz os
   ícones SVG seguirem a cor do botão. */
[data-testid='stHeader'] { color: #202124; }
[data-testid='stHeader'] button {
    color: #202124 !important;
}
[data-testid='stHeader'] svg { fill: currentColor; }
[data-testid='stHeader'] button:hover {
    background-color: rgba(0, 0, 0, 0.05);
}

/* Select de "Período" dentro do header vinho — passo 1: estiliza o
   CONTAINER (botão do popover ou select baseweb) com fundo escuro
   opaco + borda branca translúcida. Passo 2: força a cor branca em
   TODOS os descendentes (`*`) — o BaseWeb empacota o texto dentro de
   spans/divs com cor própria que não responde a `color` herdado;
   `!important` + selector global aos filhos garante override. SVG
   da seta segue `currentColor`. Label "PERÍODO" acima fica em
   branco quase-puro pra combinar com o input. */
[data-testid='stHorizontalBlock']:has(.page-header-title)
    [data-baseweb='select'] > div,
[data-testid='stHorizontalBlock']:has(.page-header-title)
    [data-testid='stPopover'] > div > button {
    background: rgba(0, 0, 0, 0.55) !important;
    border: 1px solid rgba(255, 255, 255, 0.35) !important;
    color: #ffffff !important;
}
[data-testid='stHorizontalBlock']:has(.page-header-title)
    [data-baseweb='select'] > div *,
[data-testid='stHorizontalBlock']:has(.page-header-title)
    [data-testid='stPopover'] > div > button * {
    color: #ffffff !important;
}
[data-testid='stHorizontalBlock']:has(.page-header-title)
    [data-baseweb='select'] svg,
[data-testid='stHorizontalBlock']:has(.page-header-title)
    [data-testid='stPopover'] svg {
    color: #ffffff !important;
    fill: currentColor;
}
[data-testid='stHorizontalBlock']:has(.page-header-title)
    .filter-strip-label {
    color: rgba(255, 255, 255, 0.85) !important;
}

/* Linha-rodapé "Total do período" da SDR × Closer — no base
   (`_OP_CARD_CSS`) está hardcoded com `#0E1117` / `#FAFAFA` pra casar
   com o Glide DataGrid dark default. No Looker, repintamos pra
   acompanhar o esquema claro: fundo branco, borda cinza-claro,
   texto escuro, separadores sutis. Especificidade maior (descendant
   do `section[data-testid='stMain']`) sobrescreve o base. */
section[data-testid='stMain'] .op-foot-row {
    background: #ffffff;
    border: 1px solid #dadce0;
    border-top: 0;
}
section[data-testid='stMain'] .op-foot-cell {
    color: #202124;
    border-right: 1px solid rgba(0, 0, 0, 0.06);
}
section[data-testid='stMain'] .op-foot-cell:last-child { border-right: 0; }
section[data-testid='stMain'] .op-foot-cell.accent { color: #202124; }
"""


# ---------------------------------------------------------------------------
# Helpers públicos
# ---------------------------------------------------------------------------

def get_active_theme_key() -> str:
    """Lê (e inicializa, se necessário) a chave do tema ativo na
    `st.session_state`. Default = Reconecta Dark."""
    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = DEFAULT_THEME
    key = st.session_state[_SESSION_KEY]
    if key not in ONE_PAGE_THEMES:
        st.session_state[_SESSION_KEY] = DEFAULT_THEME
        return DEFAULT_THEME
    return key


def _active_theme() -> dict[str, Any]:
    return ONE_PAGE_THEMES[get_active_theme_key()]


def op_theme_color(name: str, fallback: str = "#999999") -> str:
    """Devolve uma cor nomeada do tema ativo. Usado em Plotly traces
    pra substituir acessos diretos a `PALETTE[...]`.

    Nomes suportados (chaves do `chart` dict de cada tema):
      gold, wine_light, green, plus_12, minus_12, text, text_subtle,
      grid, plot_bg, paper_bg
    """
    chart = _active_theme().get("chart", {})
    return chart.get(name, fallback)


def apply_one_page_theme(theme_key: str | None = None) -> None:
    """Injeta o CSS do tema ativo, sobrescrevendo as `--color-*` SÓ
    dentro de `section[data-testid="stMain"]`. Não afeta sidebar nem
    outras páginas (que renderizam em script Streamlit separado).

    Quando `theme_key` é None, lê do session_state.
    """
    if theme_key is None:
        theme_key = get_active_theme_key()
    theme = ONE_PAGE_THEMES.get(theme_key, ONE_PAGE_THEMES[DEFAULT_THEME])

    vars_lines = "\n".join(
        f"    --{name}: {value};"
        for name, value in theme["css_vars"].items()
    )
    # Quando `main_bg_override=True` (Looker), repinta o fundo da main
    # com `--color-bg` do tema (caso contrário o .stApp global escuro
    # vaza por baixo do conteúdo claro). Em Dark, deixa o .stApp global
    # responder — preserva o visual atual sem mexer em nada.
    main_bg_rule = (
        "section[data-testid='stMain'] { background: var(--color-bg); }"
        if theme.get("main_bg_override") else ""
    )
    # No tema Looker, o texto markdown precisa virar escuro pra ficar
    # legível em fundo claro. Aplico só em descendentes da stMain —
    # sidebar/outras páginas não afetadas.
    text_override = (
        "section[data-testid='stMain'] .stMarkdown,"
        " section[data-testid='stMain'] .stMarkdown p,"
        " section[data-testid='stMain'] .stMarkdown strong"
        " { color: var(--color-text); }"
        if theme.get("main_bg_override") else ""
    )
    # Compactação visual exclusiva do Looker (cards menores, sombras,
    # header mais baixo). Aplicado a partir da mesma camada de override
    # do tema, mas só pra esse key.
    looker_extra = (
        _LOOKER_COMPACT_CSS if theme_key == "looker_legacy" else ""
    )

    st.markdown(
        "<style>\n"
        "section[data-testid='stMain'] {\n"
        f"{vars_lines}\n"
        "}\n"
        f"{main_bg_rule}\n"
        f"{text_override}\n"
        f"{looker_extra}\n"
        "</style>",
        unsafe_allow_html=True,
    )


def render_theme_selector(label: str = "Tema visual") -> None:
    """Renderiza um `selectbox` compacto pra escolher o tema. Lê/grava
    em `st.session_state[_SESSION_KEY]`. Mantém a seleção entre reruns
    (mesma sessão); não persiste entre páginas/sessions.

    Label fica colapsada (dica vai pro tooltip `help`) — o caller é
    responsável por posicionar via `st.columns`, alinhado à direita
    logo abaixo do header. Tentamos antes via `position: fixed`, mas
    causou sobreposição com o toolbar nativo do Streamlit (Deploy /
    menu de 3 pontos) — voltamos pra layout no fluxo normal.
    """
    get_active_theme_key()  # garante init
    st.selectbox(
        label,
        options=list(ONE_PAGE_THEMES.keys()),
        format_func=lambda k: ONE_PAGE_THEMES[k]["label"],
        key=_SESSION_KEY,
        label_visibility="collapsed",
        help="Tema visual da One Page",
    )


def op_chart_apply_theme(fig) -> None:
    """Sobrescreve cores do layout Plotly pra acompanhar o tema ativo.

    Aplicar DEPOIS de `_base_layout(...)` / `_style_axes(...)`:
        fig.update_layout(**_base_layout(...))
        _style_axes(fig)
        op_chart_apply_theme(fig)

    Mantém intactas as cores das traces (cada trace já é construída com
    `op_theme_color(...)` pelo caller). Aqui só ajustamos o "container"
    do gráfico: fundo do plot, cor do texto, gridlines.
    """
    fig.update_layout(
        plot_bgcolor=op_theme_color("plot_bg"),
        paper_bgcolor=op_theme_color("paper_bg"),
        font=dict(color=op_theme_color("text")),
        # Tooltip acompanha o tema — caso contrário no Looker fica com
        # fundo escuro (vem do `_base_layout` global em charts.py, que
        # usa PALETTE quente).
        hoverlabel=dict(
            bgcolor=op_theme_color("plot_bg"),
            bordercolor=op_theme_color("grid"),
            font=dict(color=op_theme_color("text")),
        ),
    )
    axis_color = op_theme_color("grid")
    tick_color = op_theme_color("text_subtle")
    for axis_update in (fig.update_xaxes, fig.update_yaxes):
        axis_update(
            gridcolor=axis_color,
            zerolinecolor=axis_color,
            linecolor=axis_color,
            tickfont=dict(color=tick_color),
        )
