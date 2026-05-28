"""One Page — visão executiva consolidada (Marketing + Pré-vendas + Vendas).

Recriação fiel do One Page legado do Looker em Streamlit. Pensada
para o CEO bater o olho rapidamente: leads, aplicações, agendamentos,
comparecimentos, vendas, montante/receita e investimento, com cortes
por fonte de lead, executiva e SDR×Closer.

MVP — opção pelo CEO:
  - filtro de período apenas (sem closer/times/canal no header).
  - Cards e gráficos de Marketing usam a regra LEGADA do Looker via
    `get_one_page_legacy_diario`. Aplicações vêm de
    `fdw_reconecta.typeform_aplicacoes` (não de `leads_qualificados`)
    e investimento vem de `fdw_reconecta.anuncios` (REL_02* excluído).
    Esse investimento pode diferir em ~R$ 10–20 de
    `bi.vw_investimento_diario` (Google Ads não está na fdw da Meta).
  - Tabela "Indicadores - Fonte de Lead" usa
    `one_page_prevendas_por_fonte.sql` (mesma base dos cards
    INBOUND/SS): Agendamentos líquidos, +12/-12 combinados,
    Comparecimento, Montante, Receita e percentuais derivados.

Fontes:
  - get_one_page_legacy_diario                          (Marketing One Page)
  - get_executivas / get_investimento_diario            (Vendas)
  - get_media_movel_vendas                              (Vendas)
  - get_one_page_prevendas_por_fonte                    (tabela Fonte)
  - get_prevendas_overview_diario                         (Pré-vendas)
  - get_one_page_sdr_closer                               (tabela SDR×Closer)

Performance via `@st.cache_data(ttl=600)` em todos os repositories.
"""
from __future__ import annotations

import html
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.prevendas_transforms import prevendas_overview_kpis
from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_media_movel_vendas,
    get_one_page_indicacoes_fonte,
    get_one_page_legacy_diario,
    get_one_page_novos_forma_venda,
    get_one_page_por_executiva,
    get_one_page_prevendas_por_fonte,
    get_one_page_sdr_closer,
    get_prevendas_overview_diario,
)
from src.transforms import (
    delta_pct,
    visao_geral_kpis,
)
from src.ui.charts import (
    _base_layout,
    _style_axes,
    annotate_adaptive,
    style_temporal,
)
from src.ui.op_themes import (
    apply_one_page_theme,
    op_chart_apply_theme,
    op_theme_color,
    render_theme_selector,
)
from src.ui.components import (
    ranking_column_config,
    section_title,
)
from src.ui.page import start_page
from src.ui.theme import brl as _brl_global, int_br, pct as _pct_global


# Padronização de formatação da One Page: dinheiro com centavos
# (`R$ 116.841,00`) e percentual com 2 casas (`58,44%`). Sobrescrevemos
# `brl`/`pct` SÓ neste módulo (não vaza pra outras páginas) ajustando o
# default de `casas`. Chamadas que passam `casas=N` explicitamente
# continuam funcionando — o wrapper só altera o default.
def brl(v, casas: int = 2) -> str:
    return _brl_global(v, casas=casas)


def pct(v, casas: int = 2) -> str:
    return _pct_global(v, casas=casas)

# =============================================================================
# Helpers locais — específicos da One Page. Mantidos aqui (não em
# `src/transforms.py`) por preferência do user: agrupar transforms perto do
# bloco da página que os consome.
# =============================================================================


def _safe_div(num, den):
    try:
        d = float(den or 0)
        return float(num or 0) / d if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def _sum(df: pd.DataFrame, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(df[col].fillna(0).sum())


# =============================================================================
# Card compacto local — só desta página.
# Mantém `metric_card_v2` intacto pras outras páginas (Visão Geral,
# Executivas, Marketing…). Aqui o CEO pediu densidade Looker — padding e
# altura mínima menores, label/valor levemente menores, três variantes:
#   - hero    → valor + padding maior (Aplicações, Agendamentos, Receita,
#               Investido, Ticket médio)
#   - compact → padding/altura ainda menores (cards de apoio: ±12, CPA,
#               Ascensões, Renovações, Indicações, custos)
#   - default → intermediário (Leads, % Apl/Leads, %s, Agend./Comp., etc.)
#
# CSS é escopado via `:has(.op-card)` — só apertam o gap as linhas
# que contém card OP, charts/tabelas abaixo ficam intactos.
# =============================================================================

_OP_CARD_CSS = """
<style>
/* Layout central — header(label + delta) / valor / hint / badges empilhados.
   Antes o delta era position: absolute no canto direito, mas em cards
   compactos com label médio/longo (ex.: "NOVOS" + "↑ 12,3%") o badge
   atropelava o título. Solução: linha flex de cabeçalho com label e
   delta lado a lado — clearance natural, sem padding "mágico". */
.op-card {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 8px 11px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    gap: 2px;
    min-height: 0;
    height: 100%;
    position: relative;
    text-align: center;
    transition: border-color 0.15s;
}
.op-card:hover { border-color: var(--color-border-strong); }
.op-card.hero {
    padding: 8px 12px 9px;
    min-height: 0;
    gap: 1px;
    border-color: var(--color-border-strong);
}
.op-card.compact {
    padding: 5px 8px;
    min-height: 0;
    gap: 1px;
}
/* Cards simples (1 badge ou só hint) — menos altura fantasma na linha */
.op-card:has(.op-badges-single):not(:has(.op-badge-extras)) {
    padding: 7px 9px;
}
.op-card.compact:has(.op-hint):not(:has(.op-badges)):not(:has(.op-novos-chips)) {
    padding: 5px 8px 4px;
}
.op-card:not(.hero):not(.compact):has(.op-hint):not(:has(.op-badges)) {
    padding: 6px 9px;
}
/* Cabeçalho — label + delta inline. `gap: 8px` (era 6) garante respiro
   entre o título e o badge de variação, evitando que ele "cole" no label. */
.op-head {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    min-width: 0;
}
/* ---- Tipografia cards OP — escala hero / médio / compact ---- */
.op-label {
    color: var(--color-text-subtle);
    opacity: 0.9;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 1.3px;
    text-transform: uppercase;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.op-card.hero .op-label {
    font-size: 0.72rem;
    letter-spacing: 1.4px;
}
.op-card.compact .op-label {
    font-size: 0.62rem;
    letter-spacing: 1.1px;
}
.op-value {
    color: var(--color-text);
    font-size: 1.28rem;
    font-weight: 700;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    margin-top: 2px;
    white-space: nowrap;
}
.op-card.hero .op-value {
    font-size: 1.95rem;
    margin-top: 1px;
    line-height: 1.05;
}
.op-card.compact .op-value {
    font-size: 1.12rem;
    font-weight: 600;
    margin-top: 0;
}
.op-value.accent { color: var(--color-gold); }
/* Delta — anotação leve ao lado do label (texto colorido sem pílula
   chamativa). Versão executiva sutil; cores up/down/flat dão o sinal. */
.op-delta {
    font-size: 0.56rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.2px;
    opacity: 0.86;
    white-space: nowrap;
    flex: 0 0 auto;
}
.op-card.compact .op-delta { font-size: 0.5rem; }
.op-card.hero    .op-delta { font-size: 0.6rem; }
.op-delta.up   { color: var(--color-green); opacity: 0.92; }
.op-delta.down { color: var(--color-red); opacity: 0.92; }
.op-delta.flat { color: var(--color-text-subtle); opacity: 0.72; }
.op-hint {
    color: var(--color-text-subtle);
    font-size: 0.6rem;
    margin-top: 0;
    line-height: 1.15;
    opacity: 0.76;
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.op-card.hero .op-hint { font-size: 0.62rem; opacity: 0.78; }
.op-card.compact .op-hint { font-size: 0.58rem; opacity: 0.74; }

/* Mini-indicadores associados — sub-grid no rodapé do card. Usado pra
   "grudar" % Agendamento e Custo/Aplicação ao card de Aplicações (e ±12).
   Visual segue o padrão Looker de mini-métricas atreladas ao card principal. */
.op-badges {
    margin-top: 4px;
    padding-top: 4px;
    border-top: 1px dashed var(--color-border);
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 2px 10px;
    width: 100%;
}
/* Badge único — centraliza em coluna full ao invés de ocupar só a esquerda
   da grid de 2 colunas (usado por % Comp. nos cards Comp. INB/SS e por
   % Conversão no card Novos). */
.op-badges.op-badges-single { grid-template-columns: 1fr; }
.op-badge {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1px;
    min-width: 0;
}
.op-badge-label {
    color: var(--color-text-subtle);
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.55px;
    text-transform: uppercase;
    opacity: 0.88;
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.op-badge-value {
    color: var(--color-text);
    font-size: 0.96rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    line-height: 1.15;
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.op-card.hero .op-badges {
    margin-top: 4px;
    padding-top: 4px;
    gap: 2px 12px;
    width: 100%;
}
.op-card.hero .op-badge-label { font-size: 0.64rem; opacity: 0.9; }
.op-card.hero .op-badge-value { font-size: 1.02rem; }
.op-card.compact .op-badge-label { font-size: 0.58rem; }
.op-card.compact .op-badge-value { font-size: 0.88rem; }
/* Agend. INBOUND/SS — muitos sub-stats, mas conteúdo alinhado ao topo */
.op-card:not(.hero):not(.compact):has(.op-badge-extras) {
    padding: 7px 9px 8px;
    gap: 1px;
}
.op-card:has(.op-badges-single):not(:has(.op-badge-extras)) .op-badges {
    margin-top: 3px;
    padding-top: 3px;
}

/* Sub-stats dentro de um badge — usados pra detalhar Agend. ±12 IN/SS
   acoplados em Agend. INBOUND/SS (volume no destaque, % e custo logo
   abaixo). Visual mais discreto que o valor principal do badge. */
.op-badge-extras {
    margin-top: 2px;
    padding-top: 3px;
    border-top: 1px dotted var(--color-border);
    display: flex;
    flex-direction: column;
    gap: 1px;
    width: 100%;
}
.op-badge-extra {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 6px;
    width: 100%;
    min-width: 0;
}
.op-badge-extra-label {
    color: var(--color-text-subtle);
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.35px;
    text-transform: uppercase;
    opacity: 0.84;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}
.op-badge-extra-value {
    color: var(--color-text);
    font-size: 0.86rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    flex: 0 0 auto;
}
/* Em call / Follow inline — outros cards (Agend. INBOUND/SS). */
.op-badge-extras.op-badge-extras-inline {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px 10px;
    margin-top: 3px;
    padding-top: 4px;
    border-top: 1px dotted var(--color-border);
    width: 100%;
}
.op-badge-extras.op-badge-extras-inline .op-badge-extra {
    flex-direction: column;
    align-items: center;
    gap: 1px;
    min-width: 0;
}
.op-badge-extras.op-badge-extras-inline .op-badge-extra-label {
    font-size: 0.58rem;
    opacity: 0.86;
}
.op-badge-extras.op-badge-extras-inline .op-badge-extra-value {
    font-size: 0.86rem;
    font-weight: 600;
}
/* Toggle discreto do hero de Marketing — segmented_control compactado */
[data-testid="stSegmentedControl"] { margin: 0 0 6px 0; }
[data-testid="stSegmentedControl"] button {
    font-size: 0.62rem !important;
    padding: 2px 10px !important;
    min-height: 24px !important;
    line-height: 1.1 !important;
    letter-spacing: 0.4px;
}

/* Densidade — apenas blocos que contém cards OP. Charts/tabelas
   abaixo do KPI block usam seu próprio espaçamento (gap="large"). */
[data-testid="stHorizontalBlock"]:has(.op-card) {
    gap: 0.75rem !important;
    margin-bottom: 0;
}
/* Base — irmãos dentro de cada coluna KPI (título, toggle, cards). */
[data-testid="stColumn"]:has(.op-card) [data-testid="stVerticalBlock"] {
    gap: 0.6rem !important;
}
/* Espaçadores explícitos (op_spacer) — ritmo vertical:
   parent = 1rem (pai → filhos) · row = 0.9rem (linha → linha). */
.op-spacer {
    display: block;
    width: 100%;
    flex-shrink: 0;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    pointer-events: none;
}
.op-spacer-parent { height: 1rem; }
.op-spacer-row { height: 0.9rem; }
section[data-testid="stMain"]
    [data-testid="stElementContainer"]:has(.op-spacer) {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
}
/* Títulos de seção — margem local; escala tipográfica no bloco macro abaixo. */
.sec-title { margin: 10px 0 6px 0; padding-bottom: 4px; }

/* Linha-rodapé "Total do período" — usada APENAS abaixo da tabela
   "Por SDR × Closer" (que tem `height=420` com scroll interno).
   Renderizada como grid pra que cada valor caia aproximadamente
   embaixo da coluna correspondente do `st.dataframe` acima. Pixel-
   perfect é impossível (Glide DataGrid é um canvas com larguras
   internas dinâmicas, fora do alcance do DOM); o ajuste é via
   proporções em `fr` no `--cols`, calibradas pelo conteúdo médio
   de cada coluna da tabela.

   PALETA: cores hardcoded do tema dark DEFAULT do Streamlit (Glide
   DataGrid), NÃO da paleta marrom da Reconecta. O dataframe renderiza
   num canvas isolado que ignora nossos `--color-*` — se usássemos
   `--color-card` (#161311) aqui o rodapé ficaria mais quente que as
   linhas do dataframe (#0E1117), parecendo card separado. Mantendo
   essas constantes alinhadas com o Streamlit default, o rodapé se
   funde visualmente à tabela. Se a Reconecta um dia tematizar o
   dataframe via `.streamlit/config.toml`, atualizar estas constantes
   pra acompanhar.

   Nas outras 2 tabelas (Fonte de Lead, Por Executiva) o total segue
   como última linha dentro do próprio dataframe — são curtas, não
   precisam dessa duplicação. */
.op-foot-row {
    background: #0E1117;                      /* = Streamlit dark bg */
    border: 1px solid #262730;                /* = Streamlit secondaryBg */
    border-top: 0;
    border-radius: 0 0 10px 10px;             /* casa com radius do stDataFrame */
    margin: -8px 0 16px 0;
    padding: 0;
    display: grid;
    grid-template-columns: var(--cols);
    align-items: stretch;
}
.op-foot-cell {
    padding: 9px 10px;
    border-right: 1px solid rgba(255, 255, 255, 0.05);  /* separador sutil */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.85rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: #FAFAFA;                           /* = Streamlit textColor */
    min-width: 0;
}
.op-foot-cell:last-child { border-right: 0; }
.op-foot-cell.label  { font-weight: 700; text-align: left; }
.op-foot-cell.left   { text-align: left; }
.op-foot-cell.num    { text-align: right; }
/* `accent` mantido como classe pra não quebrar o caller, mas sem
   destaque visual — Total não pinta valores em dourado, fica com
   a mesma cor das demais células. */
.op-foot-cell.accent { color: #FAFAFA; }

/* =========================================================================
   One Page — layout macro (enquadramento / largura / header → KPI)
   Escopo: section[data-testid="stMain"] — só afeta a página ativa.
   ========================================================================= */
section[data-testid="stMain"] .block-container {
    padding-top: 0.35rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    max-width: 1720px !important;
}
section[data-testid="stMain"]
    [data-testid="stHorizontalBlock"]:has(.page-header-title) {
    margin-bottom: 4px !important;
}
/* Linha do seletor de tema — menos respiro antes dos cards */
section[data-testid="stMain"]
    [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:has(
        [data-testid="stSelectbox"]
    ) {
    margin-top: 0 !important;
    margin-bottom: 2px !important;
}
section[data-testid="stMain"] .sec-title {
    font-size: 1.02rem;
    line-height: 1.25;
}
section[data-testid="stMain"] .sec-title .sub,
section[data-testid="stMain"] .sec-title span {
    font-size: 0.72rem;
}
section[data-testid="stMain"] [data-testid="stColumn"]:has(.op-card) .sec-title {
    margin: 0 0 10px 0 !important;
    padding-bottom: 4px;
}
section[data-testid="stMain"] [data-testid="stColumn"]:has(.op-card) .sec-title .sub {
    opacity: 0.75;
}
section[data-testid="stMain"]
    [data-testid="stColumn"]:has(.op-card)
    [data-testid="stElementContainer"]:has(.sec-title) {
    margin-bottom: 4px !important;
}
/* Marketing — toggle entre título e card hero. */
section[data-testid="stMain"]
    [data-testid="stColumn"]:has(.op-card) [data-testid="stSegmentedControl"] {
    margin: 0 0 6px 0 !important;
}

/* Card Novos — chips Em call / Follow */
.op-card.compact:has(.op-novos-chips) {
    padding: 5px 8px 6px;
    gap: 0;
}
.op-novos-chips {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
    width: 100%;
    margin-top: 2px;
}
.op-chip {
    background: var(--color-bg-soft);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    padding: 3px 4px 2px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0;
    min-width: 0;
}
.op-chip-label {
    color: var(--color-text-subtle);
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    opacity: 0.88;
    line-height: 1.1;
}
.op-chip-value {
    color: var(--color-text);
    font-size: 0.86rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1.12;
}
.op-card.compact .op-badges.op-badges-novos {
    margin-top: 2px;
    padding-top: 3px;
    gap: 0;
}
.op-card.compact .op-badges.op-badges-novos .op-badge-value {
    font-size: 0.88rem;
}
.op-card.compact .op-badges.op-badges-novos .op-badge-label {
    font-size: 0.58rem;
    opacity: 0.88;
}
</style>
"""


def _op_fmt_delta(delta_pct: float | None) -> tuple[str, str]:
    """(classe_css, texto) — mesma convenção do `_fmt_delta` global, sem
    importar `_private` de outro módulo."""
    if delta_pct is None:
        return "flat", "—"
    if abs(delta_pct) < 0.05:
        return "flat", "0,0%"
    arrow = "↑" if delta_pct > 0 else "↓"
    cls = "up" if delta_pct > 0 else "down"
    return cls, f"{arrow} {abs(delta_pct):.1f}%".replace(".", ",")


def op_spacer(kind: str = "row") -> None:
    """Respiro vertical entre grupos de cards KPI.

    kind:
      - ``parent`` — 1rem (card pai → linha de filhos)
      - ``row``    — 0.9rem (linha → próxima linha na mesma coluna)
    """
    aliases = {"sm": "row", "md": "parent", "lg": "parent"}
    key = aliases.get(kind, kind)
    if key not in ("parent", "row"):
        key = "row"
    st.markdown(
        f'<div class="op-spacer op-spacer-{key}" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )


def one_page_metric_card(
    label: str,
    value: str,
    delta_pct: float | None = None,
    hint: str | None = None,
    accent: bool = False,
    hero: bool = False,
    compact: bool = False,
    wine_accent: bool = False,
    badges: list[tuple] | None = None,
    extras_inline: bool = False,
    badges_class: str | None = None,
    footer_chips: list[tuple[str, str]] | None = None,
) -> None:
    """Card compacto da One Page. `hero` e `compact` são mutuamente
    exclusivos visualmente — se ambos True, `hero` vence (atalho seguro
    pra evitar bugs de chamada).

    `wine_accent=True` adiciona a classe CSS `wine-accent` ao card.
    No tema Reconecta Dark é no-op visual; no tema Looker Legacy ganha
    uma borda topo vinho (`--color-wine`). Reservado pros cards
    financeiros principais (Montante, Investido) — visual de "destaque
    executivo" alinhado ao Looker classic.

    `badges` aceita duas formas de tupla:
      - `(label, value)`                       → badge simples (1 linha)
      - `(label, value, [(slabel, svalue),…])` → badge com sub-stats
                                                  listadas abaixo do valor
    Sub-stats são usadas pra detalhar Agend. ±12 IN/SS dentro de
    Agend. INBOUND/SS (volume + % por agendamento + custo por agendamento).
    """
    classes = ["op-card"]
    if hero:
        classes.append("hero")
    elif compact:
        classes.append("compact")
    if wine_accent:
        classes.append("wine-accent")

    delta_html = ""
    if delta_pct is not None:
        cls, txt = _op_fmt_delta(delta_pct)
        delta_html = f'<span class="op-delta {cls}">{html.escape(txt)}</span>'

    # Cabeçalho — label e delta em flex row. Delta omitido (não só
    # invisível) quando ausente, pra preservar centralização perfeita
    # do label nos cards sem comparação.
    head_html = (
        f'<div class="op-head">'
        f'<div class="op-label">{html.escape(label)}</div>'
        f'{delta_html}'
        f'</div>'
    )

    hint_html = (f'<div class="op-hint">{html.escape(hint)}</div>'
                 if hint else "")

    badges_html = ""
    if badges:
        items_parts = []
        for b in badges:
            b_lbl, b_val = b[0], b[1]
            extras = b[2] if len(b) > 2 else None
            extras_html = ""
            if extras:
                extras_items = "".join(
                    f'<div class="op-badge-extra">'
                    f'<span class="op-badge-extra-label">'
                    f'{html.escape(el)}</span>'
                    f'<span class="op-badge-extra-value">'
                    f'{html.escape(str(ev))}</span>'
                    f'</div>'
                    for el, ev in extras
                )
                extras_cls = "op-badge-extras"
                if extras_inline:
                    extras_cls += " op-badge-extras-inline"
                extras_html = (
                    f'<div class="{extras_cls}">{extras_items}</div>'
                )
            items_parts.append(
                f'<div class="op-badge">'
                f'<span class="op-badge-label">{html.escape(b_lbl)}</span>'
                f'<span class="op-badge-value">'
                f'{html.escape(str(b_val))}</span>'
                f'{extras_html}'
                f'</div>'
            )
        items = "".join(items_parts)
        badges_cls = "op-badges"
        if len(badges) == 1:
            badges_cls += " op-badges-single"
        if badges_class:
            badges_cls += f" {badges_class}"
        badges_html = f'<div class="{badges_cls}">{items}</div>'

    chips_html = ""
    if footer_chips:
        chip_items = "".join(
            f'<div class="op-chip">'
            f'<span class="op-chip-label">{html.escape(lbl)}</span>'
            f'<span class="op-chip-value">{html.escape(str(val))}</span>'
            f'</div>'
            for lbl, val in footer_chips
        )
        chips_html = f'<div class="op-novos-chips">{chip_items}</div>'

    val_cls = "op-value accent" if accent else "op-value"
    st.markdown(
        f'<div class="{" ".join(classes)}">'
        f'{head_html}'
        f'<div class="{val_cls}">{html.escape(str(value))}</div>'
        f'{hint_html}'
        f'{badges_html}'
        f'{chips_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_total_row(cells: list[tuple], weights: list[float]) -> None:
    """Linha-rodapé alinhada por CSS Grid, colada ao bottom do
    `st.dataframe` da tabela "Por SDR × Closer".

    Existe pra que o usuário enxergue o Total sem precisar rolar o
    scroll interno da tabela (altura=420). Não tenta replicar a largura
    exata das colunas do Glide DataGrid (impossível: as larguras vivem
    no canvas e não vazam pro DOM). O alinhamento é aproximado, via
    proporções em `fr` calibradas pelo conteúdo médio de cada coluna —
    fica visualmente próximo do "embaixo da coluna" pra leitura
    executiva.

    `cells`  — lista de `(texto, kind)`; kind ∈
                 {"label", "txt", "num", "accent"}.
    `weights` — lista de pesos em `fr`, MESMO comprimento de `cells`.
    """
    if not cells or len(cells) != len(weights):
        return
    tpl = " ".join(f"{w}fr" for w in weights)
    parts = []
    for text, kind in cells:
        classes = ["op-foot-cell"]
        if kind == "label":
            classes.append("label")
        elif kind == "txt":
            classes.append("left")
        elif kind == "accent":
            classes.append("num")
            classes.append("accent")
        else:  # "num"
            classes.append("num")
        parts.append(
            f'<div class="{" ".join(classes)}">{html.escape(str(text))}</div>'
        )
    st.markdown(
        f'<div class="op-foot-row" style="--cols:{tpl};">'
        f'{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


def _br_format_table(df: pd.DataFrame,
                     money_cols: tuple = (),
                     int_cols: tuple = (),
                     pct_cols: tuple = ()) -> pd.DataFrame:
    """Pré-formata colunas numéricas como strings BR usando os helpers
    locais (`brl`, `int_br`, `pct`).

    Necessário porque `st.column_config.NumberColumn` em Streamlit 1.56
    só aceita format printf-style (US) ou preset `"localized"` (depende
    do locale do browser do usuário — não-determinístico). Pré-formatar
    em string garante saída `R$ 934.000,00` / `67,25%` / `1.234` para
    todos os browsers. Trade-off: a coluna formatada vira `object`/str,
    perde sort numérico no header — sort fica alfabético.

    Aceita NaN/None: `brl` e `int_br` devolvem "—" nesses casos.
    """
    out = df.copy()
    for c in money_cols:
        if c in out.columns:
            out[c] = out[c].apply(brl)
    for c in int_cols:
        if c in out.columns:
            out[c] = out[c].apply(int_br)
    for c in pct_cols:
        if c in out.columns:
            out[c] = out[c].apply(pct)
    return out


def _aplicacoes_kpis(df_one: pd.DataFrame) -> dict:
    """KPIs de Marketing do bloco superior — regra LEGADA do Looker.

    Agrega `get_one_page_legacy_diario` no período. "Aplicações" =
    submissões brutas/dia em `fdw_reconecta.typeform_aplicacoes` (data SP). CPL,
    Custo/Aplicação e Custo/Aplicação +12 usam o investimento da MESMA
    query (anuncios, sem campanhas REL_02*) — mantém coerência com o
    Looker e evita misturar fontes de mídia.

    Para os cards compostos (Aplicações / Apl. -12 / Apl. +12), cada
    segmento tem seu próprio `% Agendamento` derivado de
    `aplicacoes_*_com_agendamento` — regra coerente entre total e ±12.
    O antigo `pct_agendamento` (agendamentos / aplicações) é mantido só
    por retrocompat, pode ser removido quando nenhum consumidor restar.
    """
    leads        = _sum(df_one, "novos_leads")
    aplicacoes   = _sum(df_one, "novas_aplicacoes")
    apl_mais12   = _sum(df_one, "aplicacoes_mais_12")
    apl_menos12  = _sum(df_one, "aplicacoes_menos_12")
    apl_naoatua  = _sum(df_one, "aplicacoes_nao_atua")
    investimento = _sum(df_one, "investimento")
    agendamentos = _sum(df_one, "agendamentos")
    # Aplicações com agendamento — por segmento (vem da query legada).
    apl_total_ag = _sum(df_one, "aplicacoes_com_agendamento")
    apl_m12_ag   = _sum(df_one, "aplicacoes_mais_12_com_agendamento")
    apl_n12_ag   = _sum(df_one, "aplicacoes_menos_12_com_agendamento")

    return {
        "leads_totais":         leads,
        "aplicacoes":           aplicacoes,
        "aplicacoes_mais_12":   apl_mais12,
        "aplicacoes_menos_12":  apl_menos12,
        "aplicacoes_nao_atua":  apl_naoatua,
        "pct_aplicacoes":       _safe_div(aplicacoes, leads) * 100,
        "investimento":         investimento,
        "cpl":                  _safe_div(investimento, leads),
        "custo_aplicacao":      _safe_div(investimento, aplicacoes),
        "custo_apl_mais_12":    _safe_div(investimento, apl_mais12),
        "custo_apl_menos_12":   _safe_div(investimento, apl_menos12),
        # Agendamentos da própria query legada (zoho_activities por
        # created_time::date, regra Looker). Permite que % Agendamento
        # seja recalculado sobre a MESMA base de aplicações — alinhado
        # com a definição do CEO.
        "agendamentos_legacy":  agendamentos,
        "pct_agendamento":      _safe_div(agendamentos, aplicacoes) * 100,
        # % Agendamento por segmento — base coerente (apl_*_com_agendamento).
        # São essas que alimentam os cards compostos no painel.
        "pct_agendamento_apl":          _safe_div(apl_total_ag, aplicacoes) * 100,
        "pct_agendamento_apl_mais_12":  _safe_div(apl_m12_ag,   apl_mais12) * 100,
        "pct_agendamento_apl_menos_12": _safe_div(apl_n12_ag,   apl_menos12) * 100,
    }


# Rótulos canônicos da classificação por FONTE (regra `origem_final` do
# Looker legado). INBOUND = `fonte = 'Inbound'`; SS = `fonte = 'Fábrica'`.
# Outbound existe na SQL (`fonte = 'Outbound'`) mas não vira card próprio
# nesta versão — fica disponível pra futuras seções/tabelas.
_FONTE_INBOUND = "Inbound"
_FONTE_SS = "Fábrica"


def _prev_por_fonte(df_fonte: pd.DataFrame) -> dict:
    """Soma métricas de Pré-vendas por `fonte` (regra origem_final Looker).

    Devolve dict `{fonte: {metric: valor}}` com chaves `'Inbound'` e
    `'Fábrica'` sempre presentes — quando o df vem vazio ou uma das
    fontes não tem linhas no período, devolve zeros (cards exibem "0"
    em vez de "—").
    """
    base = {
        m: 0.0
        for m in ("agendamentos", "agendamentos_vencidos",
                  "agendamentos_mais_12", "agendamentos_menos_12",
                  "agendamentos_criados", "agendamentos_ate_hoje",
                  "agendamentos_mais_12_ate_hoje",
                  "agendamentos_menos_12_ate_hoje",
                  "comparecimentos", "comparecimentos_ate_hoje",
                  "vendas", "montante", "receita")
    }
    out = {_FONTE_INBOUND: dict(base), _FONTE_SS: dict(base)}

    if df_fonte is None or df_fonte.empty or "fonte" not in df_fonte.columns:
        return out

    sum_cols = [c for c in base if c in df_fonte.columns]
    agg = df_fonte.groupby("fonte", as_index=False, dropna=False)[sum_cols].sum()
    for _, row in agg.iterrows():
        f = str(row.get("fonte") or "")
        if f in out:
            for c in sum_cols:
                out[f][c] = float(row.get(c, 0) or 0)
    return out


def _df_evolucao_aplicacoes(df_one: pd.DataFrame) -> pd.DataFrame:
    """Série diária pro gráfico de evolução leads × aplicações (regra legada).

    Aceita o df de `get_one_page_legacy_diario` e renomeia para a
    nomenclatura do gráfico. `leads_totais` ← `novos_leads`,
    `aplicacoes` ← `novas_aplicacoes`."""
    if df_one is None or df_one.empty:
        return pd.DataFrame()
    use = [c for c in ("data_ref", "novos_leads", "novas_aplicacoes",
                       "aplicacoes_mais_12", "aplicacoes_menos_12")
           if c in df_one.columns]
    out = df_one[use].copy().rename(columns={
        "novos_leads":      "leads_totais",
        "novas_aplicacoes": "aplicacoes",
    }).sort_values("data_ref")
    return out


def _pcts_prevendas(r) -> dict:
    """Percentuais canônicos a partir de absolutos somados.

    Compartilhado entre `_tabela_indicadores_fonte` (cálculo por linha de
    fonte) e `_total_prevendas_from_absolutes` (linha Total exibida na
    faixa abaixo da tabela). Mantém a regra única: % +12, % -12 e %
    Comparecimento têm `agendamentos` como denominador; % Conversão usa
    `vendas / agendamentos` e % Venda usa `vendas / comparecimentos`; %
    Recebimento é `receita / montante`.
    """
    ag   = float(r.get("agendamentos") or 0)
    comp = float(r.get("comparecimentos") or 0)
    mais = float(r.get("agendamentos_mais_12") or 0)
    meno = float(r.get("agendamentos_menos_12") or 0)
    vds  = float(r.get("vendas") or 0)
    mon  = float(r.get("montante") or 0)
    rec  = float(r.get("receita") or 0)
    return {
        "pct_mais_12":        _safe_div(mais, ag) * 100,
        "pct_menos_12":       _safe_div(meno, ag) * 100,
        "pct_comparecimento": _safe_div(comp, ag) * 100,
        "pct_conversao":      _safe_div(vds, ag) * 100,
        "pct_venda":          _safe_div(vds, comp) * 100,
        "pct_recebimento":    _safe_div(rec, mon) * 100,
    }


def _tabela_indicadores_fonte(df_fonte: pd.DataFrame) -> pd.DataFrame:
    """Tabela "Indicadores - Fonte de Lead" — formato Looker.

    Consolida `one_page_prevendas_por_fonte.sql` (1 row por fonte/dia) em
    uma linha por fonte (Inbound / Fábrica / Outbound). Agendamentos já
    chegam LÍQUIDOS (sem vencidos) da SQL; +12/-12 usam a regra COMBINADA
    (CRM + ext_reconecta.leads). Percentuais derivados em Python a partir
    dos absolutos somados — NÃO média simples das linhas diárias.

    O Total NÃO é emitido como linha aqui — ele é construído à parte
    por `_total_prevendas_from_absolutes` no bloco renderizador, que
    concatena como última linha do df antes de chamar `st.dataframe`.
    """
    if (df_fonte is None or df_fonte.empty
            or "fonte" not in df_fonte.columns):
        return pd.DataFrame()

    cols_abs = [
        "agendamentos",
        "agendamentos_mais_12", "agendamentos_menos_12",
        "comparecimentos", "vendas", "montante", "receita",
    ]
    use = ["fonte"] + [c for c in cols_abs if c in df_fonte.columns]
    agg = (df_fonte[use]
           .groupby("fonte", as_index=False, dropna=False)
           .sum(numeric_only=True))

    # Ordem fixa pra leitura estável (Looker). Outbound só entra se
    # houver atividade no período (segue o padrão da própria SQL).
    ordem = ["Inbound", "Fábrica", "Outbound"]
    agg["__ord"] = agg["fonte"].map({n: i for i, n in enumerate(ordem)})
    agg = agg[agg["__ord"].notna()].copy()
    agg = agg.sort_values("__ord").drop(columns="__ord")
    ativo = (
        agg.get("agendamentos", pd.Series(0, index=agg.index)).fillna(0) > 0
    ) | (
        agg.get("vendas", pd.Series(0, index=agg.index)).fillna(0) > 0
    )
    agg = agg[ativo].reset_index(drop=True)
    if agg.empty:
        return pd.DataFrame()

    derived = pd.DataFrame([_pcts_prevendas(r) for _, r in agg.iterrows()])
    agg = pd.concat([agg, derived], axis=1)

    rename = {
        "fonte":                 "Fonte",
        "agendamentos":          "Agendamentos",
        "agendamentos_mais_12":  "+12",
        "pct_mais_12":           "% +12",
        "agendamentos_menos_12": "-12",
        "pct_menos_12":          "% -12",
        "comparecimentos":       "Comparecimento",
        "montante":              "Montante",
        "receita":               "Receita",
        "pct_recebimento":       "% Recebimento",
        "pct_conversao":         "% Conversão",
        "pct_venda":             "% Venda",
        "pct_comparecimento":    "% Comparecimento",
    }
    ordered = [c for c in rename if c in agg.columns]
    return agg[ordered].rename(columns=rename).reset_index(drop=True)


def _total_prevendas_from_absolutes(df: pd.DataFrame,
                                    abs_cols: list[str]) -> dict:
    """Soma colunas absolutas e recalcula percentuais via `_pcts_prevendas`.

    `df` é o df-fonte (1 linha por grão — fonte/dia, executiva, par
    SDR×Closer) com as colunas absolutas brutas; `abs_cols` lista quais
    devem ser somadas. Sempre devolve um dicionário com chaves
    `agendamentos`, `comparecimentos`, `vendas`, `montante`, `receita`,
    `agendamentos_mais_12`, `agendamentos_menos_12` (zero quando ausente)
    + os percentuais derivados, que são montados como dict da última
    linha "Total do período" e concatenados ao df antes de renderizar.
    """
    base = {k: 0.0 for k in (
        "agendamentos", "agendamentos_mais_12", "agendamentos_menos_12",
        "comparecimentos", "vendas", "montante", "receita",
    )}
    if df is None or df.empty:
        base.update(_pcts_prevendas(base))
        return base
    for c in abs_cols:
        if c in df.columns:
            base[c] = float(pd.to_numeric(df[c], errors="coerce")
                             .fillna(0).sum())
    base.update(_pcts_prevendas(base))
    return base


def _tabela_sdr_closer(df_sc: pd.DataFrame) -> pd.DataFrame:
    """Consolida SDR × Closer com derivadas. Inclui apenas pares com
    pelo menos um agendamento ou venda (descarta linhas zeradas)."""
    if df_sc is None or df_sc.empty:
        return pd.DataFrame()
    use_cols = [c for c in (
        "sdr", "closer",
        "agendamentos", "comparecimentos", "vendas",
        "montante", "receita",
    ) if c in df_sc.columns]
    out = df_sc[use_cols].copy()
    # Mesma derivada do prevendas: % comparecimento, conversão, vendas,
    # recebimento. Fórmulas iguais a `executivas_ranking` pra coerência.
    if {"agendamentos", "comparecimentos"}.issubset(out.columns):
        out["pct_comparecimento"] = out.apply(
            lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100,
            axis=1,
        )
    if {"agendamentos", "vendas"}.issubset(out.columns):
        out["pct_conversao"] = out.apply(
            lambda r: _safe_div(r["vendas"], r["agendamentos"]) * 100,
            axis=1,
        )
    if {"comparecimentos", "vendas"}.issubset(out.columns):
        out["pct_vendas"] = out.apply(
            lambda r: _safe_div(r["vendas"], r["comparecimentos"]) * 100,
            axis=1,
        )
    if {"montante", "receita"}.issubset(out.columns):
        out["pct_recebimento"] = out.apply(
            lambda r: _safe_div(r["receita"], r["montante"]) * 100,
            axis=1,
        )
    # Mantém só pares com atividade
    if {"agendamentos", "vendas"}.issubset(out.columns):
        out = out[(out["agendamentos"] > 0) | (out["vendas"] > 0)]
    if "agendamentos" in out.columns:
        out = out.sort_values(["agendamentos", "vendas"], ascending=False)
    return out.reset_index(drop=True)


def _tabela_semanal(df_one: pd.DataFrame,
                    df_prev_dia: pd.DataFrame,
                    df_exec: pd.DataFrame) -> pd.DataFrame:
    """Indicadores semanais consolidados.

    Marketing (`df_one`) vem da regra LEGADA do Looker — leads/aplicações/
    investimento direto dela. Pré-vendas e Vendas mantêm suas fontes
    próprias. Agregação Pandas por ISO-week.
    """
    def _by_week(df: pd.DataFrame, agg_map: dict) -> pd.DataFrame:
        if df is None or df.empty or "data_ref" not in df.columns:
            return pd.DataFrame(columns=["semana"] + list(agg_map.keys()))
        d = df.copy()
        d["data_ref"] = pd.to_datetime(d["data_ref"])
        iso = d["data_ref"].dt.isocalendar()
        d["semana"] = (iso["year"].astype(str)
                       + "-W"
                       + iso["week"].astype(int).map("{:02d}".format))
        keep = [c for c in agg_map if c in d.columns]
        return (d.groupby("semana", as_index=False)[keep]
                 .agg({c: agg_map[c] for c in keep}))

    # Marketing → leads, aplicações (regra legada)
    sem_mkt = _by_week(df_one, {
        "novos_leads": "sum",
        "novas_aplicacoes": "sum",
        "aplicacoes_mais_12": "sum",
    }).rename(columns={
        "novos_leads":       "leads_totais",
        "novas_aplicacoes":  "leads_qualificados",
        "aplicacoes_mais_12": "leads_mais_12",
    })

    # Pré-vendas → agendamentos, comparecimentos, +12
    sem_prev = _by_week(df_prev_dia, {
        "agendamentos": "sum",
        "agendamentos_mais_12": "sum",
        "comparecimentos": "sum",
    })

    # Vendas → vendas/montante/receita (vem da view executivas)
    sem_vend = _by_week(df_exec, {
        "vendas": "sum",
        "montante": "sum",
        "receita": "sum",
    })

    # Merge progressivo — outer pra não perder semana com 1 fonte
    semanas = pd.DataFrame({"semana": []})
    for src in (sem_mkt, sem_prev, sem_vend):
        if not src.empty:
            semanas = (src if semanas.empty
                       else semanas.merge(src, on="semana", how="outer"))
    if semanas.empty:
        return semanas
    semanas = semanas.fillna(0).sort_values("semana")

    # Derivadas — todas defensivas (col pode não existir se uma fonte falhou)
    def _col(c):
        return semanas[c] if c in semanas.columns else pd.Series(0, index=semanas.index)

    semanas["pct_agendamento"] = (
        _col("agendamentos") / _col("leads_qualificados").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_mais_12"] = (
        _col("agendamentos_mais_12") / _col("agendamentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_comparecimento"] = (
        _col("comparecimentos") / _col("agendamentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_conversao"] = (
        _col("vendas") / _col("agendamentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_vendas"] = (
        _col("vendas") / _col("comparecimentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["ticket_medio"] = (
        _col("montante") / _col("vendas").replace(0, pd.NA)
    ).fillna(0)
    semanas["pct_recebimento"] = (
        _col("receita") / _col("montante").replace(0, pd.NA) * 100
    ).fillna(0)

    # Rename amigável
    rename = {
        "semana":               "Semana",
        "leads_totais":         "Leads",
        "agendamentos":         "Agendamentos",
        "pct_agendamento":      "% Agend.",
        "agendamentos_mais_12": "Agend. +12",
        "pct_mais_12":          "% +12",
        "comparecimentos":      "Comparec.",
        "pct_comparecimento":   "% Comparec.",
        "vendas":               "Vendas",
        "pct_conversao":        "% Conversão",
        "pct_vendas":           "% Vendas",
        "montante":             "Montante",
        "ticket_medio":         "Ticket médio",
        "receita":              "Receita",
        "pct_recebimento":      "% Recebimento",
    }
    ordered = [c for c in rename if c in semanas.columns]
    return semanas[ordered].rename(columns=rename).reset_index(drop=True)


# Ordem das métricas + tipo de formatação — espelha o One Page do Looker.
# Tuplas (label_no_df, kind ∈ {int, money, pct}). Itens fora do df_semanal
# atual são pulados silenciosamente (graceful degrade).
_SEMANAL_LINHAS: list[tuple[str, str]] = [
    ("Leads",         "int"),
    ("Agendamentos",  "int"),
    ("% Agend.",      "pct"),
    ("Agend. +12",    "int"),
    ("% +12",         "pct"),
    ("Comparec.",     "int"),
    ("% Comparec.",   "pct"),
    ("Vendas",        "int"),
    ("% Conversão",   "pct"),
    ("% Vendas",      "pct"),
    ("Montante",      "money"),
    ("Ticket médio",  "money"),
    ("Receita",       "money"),
    ("% Recebimento", "pct"),
]


def _fmt_semanal(v, kind: str) -> str:
    """Formata célula da matriz semanal por tipo. NaN/None → '—'."""
    if v is None:
        return "—"
    try:
        if isinstance(v, float) and v != v:  # NaN
            return "—"
    except Exception:
        pass
    if kind == "money":
        return brl(v)
    if kind == "pct":
        return pct(v)
    return int_br(v)


def _label_semana(semana_str: str, mostrar_ano: bool) -> str:
    """`'2026-W18'` → `'SEMANA_18'`. Se o período cruzar ano (mostrar_ano
    True) acrescenta o ano: `'SEMANA_52_2025'`. Fallback: devolve o
    valor original sem quebrar a renderização."""
    try:
        ano, sem = str(semana_str).split("-W")
        n = int(sem)
        return f"SEMANA_{n:02d}_{ano}" if mostrar_ano else f"SEMANA_{n:02d}"
    except (ValueError, AttributeError):
        return str(semana_str)


_SEMANAL_CSS = """
<style>
.op-semanal-wrap { overflow-x: auto; margin-top: 4px; padding-bottom: 6px; }
.op-semanal {
    width: 100%;
    border-collapse: collapse;
    font-family: Inter, system-ui, sans-serif;
    color: var(--color-text);
}
.op-semanal thead th {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-gold);
    padding: 14px 22px;
    border-bottom: 1px solid var(--color-border-strong);
    text-align: right;
    white-space: nowrap;
    background: var(--color-bg-soft);
}
.op-semanal thead th.op-corner {
    text-align: left;
    color: var(--color-text-subtle);
    min-width: 200px;
}
.op-semanal tbody td {
    padding: 16px 22px;
    border-bottom: 1px solid var(--color-border);
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
    font-size: 0.95rem;
}
.op-semanal tbody td.op-metric {
    text-align: left;
    font-weight: 500;
    color: var(--color-text-subtle);
    background: var(--color-card);
    position: sticky;
    left: 0;
    z-index: 1;
    min-width: 200px;
    border-right: 1px solid var(--color-border-strong);
}
.op-semanal tbody tr:last-child td { border-bottom: none; }
.op-semanal tbody tr:hover td:not(.op-metric) {
    background: rgba(201, 168, 76, 0.06);
}
.op-semanal tbody tr.op-row-emphasis td:not(.op-metric) {
    color: var(--color-gold-bright);
    font-weight: 600;
}
</style>
"""


def _render_indicadores_semanais(df_semanal: pd.DataFrame) -> None:
    """Renderiza a seção 'Indicadores semanais' como matriz executiva:
    semanas no topo (`SEMANA_19`, `SEMANA_20`…), métricas na lateral.
    Formato fiel ao One Page do Looker. Não toca na lógica de agregação
    — só na camada de apresentação.
    """
    if (df_semanal is None or df_semanal.empty
            or "Semana" not in df_semanal.columns):
        st.info("Sem dados semanais no período.")
        return

    # Ordem cronológica pelo identificador YYYY-Www.
    df = df_semanal.sort_values("Semana").reset_index(drop=True)

    # Se o período cruzar ano, mostra o ano no label pra evitar colisão
    # ('SEMANA_52_2025' vs 'SEMANA_01_2026').
    anos = {str(s).split("-W")[0] for s in df["Semana"]}
    cruza_ano = len(anos) > 1
    semanas = [_label_semana(s, cruza_ano) for s in df["Semana"]]

    # Só inclui linhas cuja métrica veio do _tabela_semanal — schema drift
    # ou fontes parcialmente vazias caem fora sem quebrar.
    linhas = [(m, kind) for m, kind in _SEMANAL_LINHAS if m in df.columns]
    if not linhas:
        st.info("Sem métricas disponíveis para a matriz semanal.")
        return

    # Linhas que ganham destaque (gold-bright bold) — métricas-âncora do
    # CEO. Não afeta layout, só legibilidade.
    _ENFASE = {"Leads", "Vendas", "Receita", "Montante"}

    head_cells = "".join(f"<th>{html.escape(w)}</th>" for w in semanas)
    body_rows: list[str] = []
    for metric, kind in linhas:
        cells = "".join(
            f"<td>{html.escape(_fmt_semanal(df.iloc[i][metric], kind))}</td>"
            for i in range(len(df))
        )
        cls = ' class="op-row-emphasis"' if metric in _ENFASE else ""
        body_rows.append(
            f'<tr{cls}>'
            f'<td class="op-metric">{html.escape(metric)}</td>'
            f'{cells}'
            f'</tr>'
        )

    table_html = (
        '<div class="op-semanal-wrap">'
        '<table class="op-semanal">'
        '<thead><tr>'
        '<th class="op-corner">Semana / Métrica</th>'
        f'{head_cells}'
        '</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        '</table></div>'
    )

    # CSS é idempotente (`<style>` repetido apenas substitui as regras),
    # mas mesmo assim injeta uma única vez por render — antes da tabela.
    st.markdown(_SEMANAL_CSS + table_html, unsafe_allow_html=True)


# =============================================================================
# Header — período apenas (decisão MVP: não usar canal nem
# closer/times no header pra manter a visão executiva limpa).
# =============================================================================
ctx = start_page(
    title="One Page",
    subtitle="Visão executiva consolidada — Marketing × Pré-vendas × Vendas",
)

# Seletor de tema (PoC) — linha compacta logo abaixo do header, com o
# selectbox alinhado à direita via `st.columns`. Versão anterior usava
# `position: fixed` pra pinar no canto superior direito, mas isso
# sobrepunha os controles nativos do Streamlit (Deploy/menu) tornando
# o widget difícil de clicar. Trade-off aceito: ~40px de espaço
# vertical extra abaixo do header, em troca de clicabilidade garantida.
# `label_visibility="collapsed"` + tooltip `help` mantêm o visual
# discreto. `apply_one_page_theme()` é chamada IMEDIATAMENTE depois pra
# que as `--color-*` overrides já estejam vigentes quando os cards/
# gráficos forem renderizados.
_, _th_r = st.columns([6, 1], gap="small")
with _th_r:
    render_theme_selector()
apply_one_page_theme()

# =============================================================================
# Carga
# =============================================================================
excluir_testes_aplicacoes = bool(
    st.session_state.get("onepage_excluir_testes_aplicacoes", False)
)
dias_periodo = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias_periodo - 1)

# Vendas (executivas + investimento) — fontes oficiais
try:
    df_exec      = get_executivas(ctx.data_ini, ctx.data_fim)
    df_inv       = get_investimento_diario(ctx.data_ini, ctx.data_fim)
    df_exec_prev = get_executivas(prev_ini, prev_fim)
    df_inv_prev  = get_investimento_diario(prev_ini, prev_fim)
except Exception as e:
    st.error(f"Falha ao consultar Vendas (executivas/investimento): {e}")
    st.stop()

# Marketing — regra LEGADA do One Page (typeform_aplicacoes + anuncios).
# Substitui `mkt_visao_geral_periodo`/`_diario` nos cards e gráficos —
# Aplicações deixam de ser `leads_qualificados` e passam a vir do
# typeform específico do Looker.
try:
    df_one = get_one_page_legacy_diario(
        ctx.data_ini,
        ctx.data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    df_one_prev = get_one_page_legacy_diario(
        prev_ini,
        prev_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
except Exception as e:
    st.error(f"Falha ao consultar One Page legado: {e}")
    df_one      = pd.DataFrame()
    df_one_prev = pd.DataFrame()

# Pré-vendas
# - `df_prev_dia`: alimenta o card consolidado de Agendamentos e a
#   % Comparecimento via `prevendas_overview_kpis` (regra oficial).
# - `df_prev_fonte`: alimenta os cards INBOUND/SS (regra origem_final do
#   Looker — quebra por `zoho_deals.fonte_de_lead`, não por tipo de SDR).
try:
    df_prev_dia   = get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim)
    df_prev_fonte = get_one_page_prevendas_por_fonte(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.warning(f"Falha ao consultar Pré-vendas: {e}")
    df_prev_dia   = pd.DataFrame()
    df_prev_fonte = pd.DataFrame()

# Média móvel — sempre últimos 21 dias (regra Looker)
try:
    media_movel_val = get_media_movel_vendas()
except Exception:
    media_movel_val = None

# =============================================================================
# KPIs base
# =============================================================================
k_apl      = _aplicacoes_kpis(df_one)
k_apl_prev = _aplicacoes_kpis(df_one_prev)

# Reaproveita o KPI oficial da Pré-vendas Visão Geral
# (`src/prevendas_transforms.py`): garante que "Agendamentos" exiba
# `agendamentos_exibidos = bruto - vencidas` e que `taxa_comparecimento`
# use `comparecimentos / agendamentos_exibidos` — mesma regra validada
# na página Pré-vendas. Evita re-implementar a fórmula localmente.
k_prev = prevendas_overview_kpis(df_prev_dia)

por_fonte = _prev_por_fonte(df_prev_fonte)

k_vendas      = visao_geral_kpis(df_exec, df_inv)
k_vendas_prev = visao_geral_kpis(df_exec_prev, df_inv_prev)

# Card Indic. — regra Looker (`fonte_de_lead = 'Indicação'`), não a coluna
# `indicacoes` da view (que classifica por `tipo_venda`). Pode sobrepor Novos.
try:
    k_vendas["indicacoes"] = get_one_page_indicacoes_fonte(
        ctx.data_ini, ctx.data_fim,
    )
    k_vendas_prev["indicacoes"] = get_one_page_indicacoes_fonte(
        prev_ini, prev_fim,
    )
except Exception as e:
    st.warning(f"Falha ao consultar Indic. (fonte): {e}")

# Sub-stats Em call / Follow no card Novos (forma_venda em zoho_deals).
novos_forma = {"em_call": 0, "follow": 0}
try:
    novos_forma = get_one_page_novos_forma_venda(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.warning(f"Falha ao consultar Novos (forma venda): {e}")

# =============================================================================
# Painel executivo — 3 colunas (Marketing | Pré-vendas | Vendas).
# Aproxima a leitura do One Page do Looker: cards mais próximos, blocos
# alinhados em paralelo, menos altura desperdiçada. Os 3 section_titles
# são curtos para não poluir o topo; a explicação completa das fontes
# vive nas SQLs (`one_page_legacy_diario.sql`, `one_page_prevendas_por_
# fonte.sql`) e nos hints dos próprios cards.
# =============================================================================
inb = por_fonte[_FONTE_INBOUND]
ss  = por_fonte[_FONTE_SS]

# Agendamentos consolidado (regra Pré-vendas Visão Geral)
ag_bruto = int(k_prev.get("agendamentos", 0))
ag_venc  = int(k_prev.get("vencidas", 0))
ag_exib  = int(k_prev.get("agendamentos_exibidos", max(ag_bruto - ag_venc, 0)))

# CSS dos cards locais — injetado uma vez, antes do KPI grid.
# Idempotente (re-injeção a cada rerun apenas redefine as regras).
st.markdown(_OP_CARD_CSS, unsafe_allow_html=True)

col_mkt, col_prev, col_vendas = st.columns([1.0, 1.25, 1.05], gap="medium")

# -----------------------------------------------------------------------------
# Coluna esquerda — Marketing / Aplicações
# Estrutura Looker — cards compostos (cada Aplicação carrega seu próprio
# % Agendamento + Custo/Apl. como mini-indicadores):
#   Hero (Aplicações ↔ Leads Totais via toggle):
#     - Aplicações:    badges = % Agendamento, Custo / Apl.
#     - Leads Totais:  badges = % Aplic. / Leads, CPL
#   Linha 2: Apl. -12 (badges: % Agend. -12, Custo / Apl. -12)
#          | Apl. +12 (badges: % Agend. +12, Custo / Apl. +12)
# -----------------------------------------------------------------------------
with col_mkt:
    section_title("Marketing", "leads × aplicações")

    excluir_testes_aplicacoes = st.checkbox(
        "Excluir testes",
        value=False,
        key="onepage_excluir_testes_aplicacoes",
        help=(
            "Remove e-mails de teste das aplicações (Typeform). "
            "Desmarcado bate com o total bruto de Submissions."
        ),
    )

    # Toggle do hero — alterna métrica principal sem trocar o layout.
    # `required=True` evita o estado None (clicar no selecionado deselecta
    # por padrão no segmented_control single-mode).
    mkt_hero_opt = st.segmented_control(
        "Métrica principal",
        options=["Aplicações", "Leads Totais"],
        default="Aplicações",
        key="op_mkt_hero_metric",
        label_visibility="collapsed",
        required=True,
    )
    if mkt_hero_opt == "Leads Totais":
        # Hero Leads — indicadores associados a Leads
        one_page_metric_card(
            "Leads Totais",
            int_br(k_apl["leads_totais"]),
            delta_pct=delta_pct(k_apl["leads_totais"],
                                k_apl_prev["leads_totais"]),
            hint="e-mails únicos no período",
            accent=True,
            hero=True,
            badges=[
                ("% Aplic. / Leads", pct(k_apl["pct_aplicacoes"])),
                ("CPL",              brl(k_apl["cpl"], casas=2)),
            ],
        )
    else:
        # Hero Aplicações — % Agendamento total + custo médio por aplicação
        one_page_metric_card(
            "Aplicações",
            int_br(k_apl["aplicacoes"]),
            delta_pct=delta_pct(k_apl["aplicacoes"], k_apl_prev["aplicacoes"]),
            accent=True,
            hero=True,
            badges=[
                ("% Agendamento", pct(k_apl["pct_agendamento_apl"])),
                ("Custo / Apl.",  brl(k_apl["custo_aplicacao"], casas=2)),
            ],
        )

    op_spacer("parent")

    # Linha 2 — Aplic. ±12 (cards compostos, cada um com % e custo do
    # próprio segmento)
    r = st.columns(2, gap="small")
    with r[0]:
        one_page_metric_card(
            "Apl. -12",
            int_br(k_apl["aplicacoes_menos_12"]),
            delta_pct=delta_pct(k_apl["aplicacoes_menos_12"],
                                k_apl_prev["aplicacoes_menos_12"]),
            badges=[
                ("% Agend. -12",     pct(k_apl["pct_agendamento_apl_menos_12"])),
                ("Custo / Apl. -12", brl(k_apl["custo_apl_menos_12"], casas=2)),
            ],
        )
    with r[1]:
        one_page_metric_card(
            "Apl. +12",
            int_br(k_apl["aplicacoes_mais_12"]),
            delta_pct=delta_pct(k_apl["aplicacoes_mais_12"],
                                k_apl_prev["aplicacoes_mais_12"]),
            accent=True,
            badges=[
                ("% Agend. +12",     pct(k_apl["pct_agendamento_apl_mais_12"])),
                ("Custo / Apl. +12", brl(k_apl["custo_apl_mais_12"], casas=2)),
            ],
        )

# -----------------------------------------------------------------------------
# Coluna central — Pré-vendas (INBOUND = fonte 'Inbound' / SS = fonte 'Fábrica')
# Estrutura Looker — cards compostos (a quebra -12/+12 e a taxa de
# comparecimento ficam acopladas ao card "pai" como badges, evitando
# cards soltos que duplicam a hierarquia da informação):
#   L1: Agendamentos (hero, largo)
#   L2: Agend. INBOUND  (badges: Agend. -12 IN | Agend. +12 IN)
#     | Agend. SS       (badges: Agend. -12 SS | Agend. +12 SS)
#   L3: Comp. INBOUND  (badge: % Comp. Inbound)
#     | Comp. SS       (badge: % Comp. SS)
# Regra rígida: -12 sempre na esquerda, +12 sempre na direita.
# -----------------------------------------------------------------------------
with col_prev:
    section_title("Pré-vendas", "agendamentos por fonte")

    # L1 — Agendamentos consolidado (hero, full-width) com Custo /
    # Agendamento acoplado (investimento legado da query Looker / total
    # de agendamentos exibidos no período).
    one_page_metric_card(
        "Agendamentos",
        int_br(ag_exib),
        hint=f"vencidos: {int_br(ag_venc)}",
        accent=True,
        hero=True,
        badges=[
            ("Custo / Ag.",
             brl(_safe_div(k_apl["investimento"], ag_exib), casas=2)),
        ],
    )

    op_spacer("parent")

    # L2 — Consultas (Inbound | SS) com quebra ±12 acoplada como badges.
    #
    # Origem dos números ±12 acoplados:
    #   - Fonte: `one_page_prevendas_por_fonte.sql` (1 row por fonte/dia,
    #     agregada em Python pelo helper `_prev_por_fonte`).
    #   - LÍQUIDO: o SQL já aplica `FILTER (WHERE status_reuniao <> 'Vencida')`
    #     em `agendamentos_mais_12` / `agendamentos_menos_12` — vencidos
    #     NÃO entram nestes cards. Mesma regra do hero "Agendamentos".
    #   - Classificação: regra COMBINADA das 4 fontes (espelha
    #     prevendas_overview_diario.sql): `lead_classification` OR
    #     `qualificacao` OR `classificado_cal` (CRM) OR
    #     `ext_reconecta.leads.classificado`.
    #   - Fonte INBOUND/SS: `zoho_deals.fonte_de_lead` com CASE no SQL —
    #     'Fábrica de Contatos' → SS; demais (Inbound, Reagendamento,
    #     Follow-up, NULL) → INBOUND. ('Outbound' fica fora dos cards.)
    #
    # Cada badge ±12 carrega sub-stats (% por consulta + custo por
    # consulta) — % usa o total de consultas da própria fonte como
    # denominador; custo usa o investimento legado k_apl["investimento"]
    # (mesma base do Custo / Agendamento do hero).
    inv_total = k_apl["investimento"]
    inb_tot   = inb["agendamentos"]
    ss_tot    = ss["agendamentos"]
    r = st.columns(2, gap="small")
    with r[0]:
        one_page_metric_card(
            "Agend. INBOUND",
            int_br(inb_tot),
            hint="agendamentos Inbound",
            badges=[
                ("Agend. -12 IN",
                 int_br(inb["agendamentos_menos_12"]),
                 [
                     ("% Agend.",
                      pct(_safe_div(inb["agendamentos_menos_12"],
                                    inb_tot) * 100)),
                     ("Custo / Ag.",
                      brl(_safe_div(inv_total,
                                    inb["agendamentos_menos_12"]),
                          casas=2)),
                 ]),
                ("Agend. +12 IN",
                 int_br(inb["agendamentos_mais_12"]),
                 [
                     ("% Agend.",
                      pct(_safe_div(inb["agendamentos_mais_12"],
                                    inb_tot) * 100)),
                     ("Custo / Ag.",
                      brl(_safe_div(inv_total,
                                    inb["agendamentos_mais_12"]),
                          casas=2)),
                 ]),
            ],
        )
    with r[1]:
        one_page_metric_card(
            "Agend. SS",
            int_br(ss_tot),
            hint="agendamentos Fábrica",
            badges=[
                ("Agend. -12 SS",
                 int_br(ss["agendamentos_menos_12"]),
                 [
                     ("% Agend.",
                      pct(_safe_div(ss["agendamentos_menos_12"],
                                    ss_tot) * 100)),
                     ("Custo / Ag.",
                      brl(_safe_div(inv_total,
                                    ss["agendamentos_menos_12"]),
                          casas=2)),
                 ]),
                ("Agend. +12 SS",
                 int_br(ss["agendamentos_mais_12"]),
                 [
                     ("% Agend.",
                      pct(_safe_div(ss["agendamentos_mais_12"],
                                    ss_tot) * 100)),
                     ("Custo / Ag.",
                      brl(_safe_div(inv_total,
                                    ss["agendamentos_mais_12"]),
                          casas=2)),
                 ]),
            ],
        )

    op_spacer("row")

    # L3 — Comparecimentos (Inbound | SS) com % próprio acoplado como badge
    # (substitui o antigo card "% Comparecimento" geral, full-width).
    r = st.columns(2, gap="small")
    with r[0]:
        one_page_metric_card(
            "Comp. INBOUND",
            int_br(inb["comparecimentos"]),
            hint="comparecimentos Inbound",
            badges=[
                ("% Comp.",
                 pct(_safe_div(inb["comparecimentos"],
                               inb["agendamentos"]) * 100)),
            ],
        )
    with r[1]:
        one_page_metric_card(
            "Comp. SS",
            int_br(ss["comparecimentos"]),
            hint="comparecimentos Fábrica",
            badges=[
                ("% Comp.",
                 pct(_safe_div(ss["comparecimentos"],
                               ss["agendamentos"]) * 100)),
            ],
        )

# -----------------------------------------------------------------------------
# Coluna direita — Vendas / Financeiro
# Estrutura Looker:
#   L1 (4 cards): Novos (badge: % Conversão = novos / comparecimentos) ·
#                 Ascensões · Renovações · Indicações
#   L2 (2 cards): Montante (hero accent) · Investido (hero)
#   L3 (3 cards): CPA · Média móvel · Ticket médio
#   L4 extra:     Receita / Vendido (compact, full-width)
# Montante virou o destaque financeiro principal; Receita / Vendido ficou
# como métrica secundária no rodapé.
# -----------------------------------------------------------------------------
with col_vendas:
    section_title("Vendas / Financeiro", "meta proporcional ao período")

    # L1 — breakdown de Vendas (4 cards). % Conversão acoplado a Novos
    # (vendas novas / comparecimentos do período — base k_prev).
    pct_conversao = _safe_div(
        k_vendas["novos"], k_prev.get("comparecimentos", 0)
    ) * 100
    r = st.columns(4, gap="small")
    with r[0]:
        one_page_metric_card(
            "Novos",
            int_br(k_vendas["novos"]),
            delta_pct=delta_pct(k_vendas["novos"], k_vendas_prev["novos"]),
            accent=True,
            compact=True,
            badges=[("% Conversão", pct(pct_conversao))],
            badges_class="op-badges-novos",
            footer_chips=[
                ("Em call", int_br(novos_forma.get("em_call", 0))),
                ("Follow",  int_br(novos_forma.get("follow", 0))),
            ],
        )
    with r[1]:
        one_page_metric_card(
            "Asc.",
            int_br(k_vendas["ascensoes"]),
            delta_pct=delta_pct(k_vendas["ascensoes"],
                                k_vendas_prev["ascensoes"]),
            compact=True,
        )
    with r[2]:
        one_page_metric_card(
            "Renov.",
            int_br(k_vendas["renovacoes"]),
            delta_pct=delta_pct(k_vendas["renovacoes"],
                                k_vendas_prev["renovacoes"]),
            compact=True,
        )
    with r[3]:
        one_page_metric_card(
            "Indic.",
            int_br(k_vendas["indicacoes"]),
            delta_pct=delta_pct(k_vendas["indicacoes"],
                                k_vendas_prev["indicacoes"]),
            compact=True,
        )

    op_spacer("row")

    # L2 — Montante | Investido (2 cards hero). Montante é o destaque
    # principal (accent). Hint usa `pct_recebimento` (receita / montante)
    # — descreve quanto do montante já virou caixa, sem invadir a
    # narrativa de "meta de receita" que pertence ao card Receita / Vendido.
    r = st.columns(2, gap="small")
    with r[0]:
        one_page_metric_card(
            "Montante",
            brl(k_vendas["montante"]),
            delta_pct=delta_pct(k_vendas["montante"],
                                k_vendas_prev["montante"]),
            hint=f"recebimento {pct(k_vendas['pct_recebimento'])}",
            accent=True,
            hero=True,
            wine_accent=True,
        )
    with r[1]:
        one_page_metric_card(
            "Investido",
            brl(k_vendas["investimento"]),
            delta_pct=delta_pct(k_vendas["investimento"],
                                k_vendas_prev["investimento"]),
            hint=f"{int_br(k_vendas['dias'])} dias",
            hero=True,
            wine_accent=True,
        )

    op_spacer("row")

    # L3 — CPA | Média móvel | Ticket médio (3 cards)
    ritmo_fmt = (
        f"{media_movel_val:.1f}".replace(".", ",")
        if media_movel_val is not None else "—"
    )
    r = st.columns(3, gap="small")
    with r[0]:
        one_page_metric_card(
            "CPA",
            brl(k_vendas["cpa"]) if k_vendas["cpa"] else "—",
            delta_pct=delta_pct(k_vendas["cpa"], k_vendas_prev["cpa"]),
            hint="invest / vendas",
        )
    with r[1]:
        one_page_metric_card(
            "Média móvel",
            ritmo_fmt,
            hint="vendas/dia (21d)",
        )
    with r[2]:
        one_page_metric_card(
            "Ticket méd.",
            brl(k_vendas["ticket_medio"]) if k_vendas["ticket_medio"] else "—",
            delta_pct=delta_pct(k_vendas["ticket_medio"],
                                k_vendas_prev["ticket_medio"]),
            hint="montante / vendas",
            accent=True,
        )

    op_spacer("row")

    # L4 — Receita / Vendido (full-width, compact — métrica secundária no
    # rodapé da área financeira). Meta + atingimento descrevem a receita
    # (pct_atingimento = receita / meta), por isso o hint da meta vive
    # aqui e não no card de Montante.
    receita_hint = (
        f"meta {brl(k_vendas['meta'])} · "
        f"{pct(k_vendas['pct_atingimento'])} atingido"
    )
    one_page_metric_card(
        "Receita / Vendido",
        brl(k_vendas["receita"]),
        delta_pct=delta_pct(k_vendas["receita"], k_vendas_prev["receita"]),
        hint=receita_hint,
        compact=True,
    )

# =============================================================================
# Gráficos
# =============================================================================
section_title("Tendências diárias", "evolução de leads, investimento e funil")

g_left, g_right = st.columns(2, gap="large")

# ---- 1. Evolução leads × aplicações ----------------------------------------
with g_left:
    st.markdown("**Leads × Aplicações** (regra Looker)")
    df_evo = _df_evolucao_aplicacoes(df_one)
    if df_evo.empty:
        st.info("Sem série diária de Marketing no período.")
    else:
        # Specs por trace: (nome, coluna, cor, dash, espessura, tamanho marker).
        # Formatter compartilhado (int_br) — todas as séries são contagens.
        # Cores lidas do tema ativo (`op_theme_color`) — substitui PALETTE
        # direto pra acompanhar troca de tema.
        _traces = [
            ("Leads",      "leads_totais",        op_theme_color("gold"),       None,   2.5, 5),
            ("Aplicações", "aplicacoes",          op_theme_color("wine_light"), None,   2.5, 5),
            ("Apl. +12",   "aplicacoes_mais_12",  op_theme_color("plus_12"),    "dash", 2.0, 4),
            ("Apl. -12",   "aplicacoes_menos_12", op_theme_color("minus_12"),   "dot",  2.0, 4),
        ]
        fig = go.Figure()
        for name, col, color, dash, w, msz in _traces:
            series = df_evo[col]
            fmt_series = [int_br(v) for v in series]
            fig.add_trace(go.Scatter(
                x=df_evo["data_ref"], y=series, name=name,
                customdata=[[v] for v in fmt_series],
                hovertemplate="%{customdata[0]}<extra></extra>",
                mode="lines+markers+text",
                text=annotate_adaptive(series, int_br),
                textposition="top center",
                textfont=dict(color=op_theme_color("text_subtle"), size=10, family="Inter"),
                cliponaxis=False,
                line=dict(color=color, width=w, dash=dash),
                marker=dict(size=msz),
            ))
        fig.update_layout(**_base_layout(height=320, unified=True))
        _style_axes(fig)
        style_temporal(fig)
        op_chart_apply_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

# ---- 2. Investimento por dia (mesma base do CPL: anuncios sem REL_02*) ----
with g_right:
    st.markdown("**Investimento por dia**")
    if df_one is None or df_one.empty or "investimento" not in df_one.columns:
        st.info("Sem investimento registrado no período.")
    else:
        df_inv_one = df_one[["data_ref", "investimento"]].sort_values("data_ref")
        # Construído inline (em vez de chamar `area()`) pra ter hovertemplate
        # com brl BR (R$ X.XXX,XX); o helper area() ainda não suporta
        # formatter customizado.
        inv_series = df_inv_one["investimento"]
        fmt_inv = [brl(v) for v in inv_series]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_inv_one["data_ref"], y=inv_series,
            name="Investimento",
            fill="tozeroy",
            line=dict(color=op_theme_color("gold"), width=2.5),
            fillcolor=op_theme_color("gold_fill"),
            mode="lines+markers+text",
            marker=dict(size=5),
            customdata=[[v] for v in fmt_inv],
            hovertemplate="%{customdata[0]}<extra></extra>",
            text=annotate_adaptive(inv_series, brl),
            textposition="top center",
            textfont=dict(color=op_theme_color("text_subtle"), size=10, family="Inter"),
            cliponaxis=False,
        ))
        fig.update_layout(**_base_layout(height=280, unified=True))
        _style_axes(fig, money_axis="y")
        style_temporal(fig)
        op_chart_apply_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

g_left2, g_right2 = st.columns(2, gap="large")

# ---- 3. Evolução de agendamentos -------------------------------------------
with g_left2:
    st.markdown("**Agendamentos × +12 / -12**")
    if df_prev_dia is None or df_prev_dia.empty:
        st.info("Sem série diária de Pré-vendas no período.")
    else:
        df_pd = df_prev_dia.sort_values("data_ref").copy()
        # Agendamentos -12: na série diária só temos `agendamentos_mais_12`.
        # Deriva o complemento como (total - +12) — aproximação aceitável
        # para visualização (regra +12/-12 não é mutuamente exclusiva no
        # detalhe, mas no agregado a sobreposição é marginal).
        df_pd["agendamentos_menos_12_aprox"] = (
            df_pd["agendamentos"] - df_pd["agendamentos_mais_12"]
        ).clip(lower=0)
        _traces = [
            ("Agendamentos",     "agendamentos",                op_theme_color("gold"),     None,   2.5, 5),
            ("Ag. +12",          "agendamentos_mais_12",        op_theme_color("plus_12"),  "dash", 2.0, 4),
            ("Ag. -12 (aprox.)", "agendamentos_menos_12_aprox", op_theme_color("minus_12"), "dot",  2.0, 4),
        ]
        fig = go.Figure()
        for name, col, color, dash, w, msz in _traces:
            series = df_pd[col]
            fmt_series = [int_br(v) for v in series]
            fig.add_trace(go.Scatter(
                x=df_pd["data_ref"], y=series, name=name,
                customdata=[[v] for v in fmt_series],
                hovertemplate="%{customdata[0]}<extra></extra>",
                mode="lines+markers+text",
                text=annotate_adaptive(series, int_br),
                textposition="top center",
                textfont=dict(color=op_theme_color("text_subtle"), size=10, family="Inter"),
                cliponaxis=False,
                line=dict(color=color, width=w, dash=dash),
                marker=dict(size=msz),
            ))
        fig.update_layout(**_base_layout(height=320, unified=True))
        _style_axes(fig)
        style_temporal(fig)
        op_chart_apply_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

# ---- 4. Volumes (ag/comp/vendas) -------------------------------------------
with g_right2:
    st.markdown("**Agendamentos × Comparecimentos × Vendas**")
    if df_prev_dia is None or df_prev_dia.empty or df_exec is None or df_exec.empty:
        st.info("Sem dados de Pré-vendas e/ou Vendas no período.")
    else:
        # Junta vendas (df_exec.vendas) à série diária de Pré-vendas.
        # As duas séries usam `data_ref` no mesmo grão (1 row/dia).
        vendas_dia = (df_exec.groupby("data_ref", as_index=False)["vendas"]
                      .sum())
        merged = (df_prev_dia[["data_ref", "agendamentos", "comparecimentos"]]
                  .merge(vendas_dia, on="data_ref", how="outer")
                  .fillna(0)
                  .sort_values("data_ref"))
        _traces = [
            ("Agendamentos", "agendamentos",     op_theme_color("gold"),       None,  2.5, 5),
            ("Comparec.",    "comparecimentos",  op_theme_color("wine_light"), None,  2.5, 5),
            ("Vendas",       "vendas",           op_theme_color("green"),      "dot", 2.5, 5),
        ]
        fig = go.Figure()
        for name, col, color, dash, w, msz in _traces:
            series = merged[col]
            fmt_series = [int_br(v) for v in series]
            fig.add_trace(go.Scatter(
                x=merged["data_ref"], y=series, name=name,
                customdata=[[v] for v in fmt_series],
                hovertemplate="%{customdata[0]}<extra></extra>",
                mode="lines+markers+text",
                text=annotate_adaptive(series, int_br),
                textposition="top center",
                textfont=dict(color=op_theme_color("text_subtle"), size=10, family="Inter"),
                cliponaxis=False,
                line=dict(color=color, width=w, dash=dash),
                marker=dict(size=msz),
            ))
        fig.update_layout(**_base_layout(height=320, unified=True))
        _style_axes(fig)
        style_temporal(fig)
        op_chart_apply_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# Tabelas
# =============================================================================

# ---- Tabela Indicadores - Fonte de Lead -----------------------------------
# Fonte: `one_page_prevendas_por_fonte.sql` (mesma base dos cards INBOUND/SS).
# Agendamentos já chegam LÍQUIDOS (sem vencidos); ±12 usa regra combinada
# (CRM + ext_reconecta.leads). `st.dataframe` interativo (sort/scroll/
# resize do Glide preservados). Linha "Total do período" é a última row
# do df — percentuais recalculados sobre os totais via
# `_total_prevendas_from_absolutes` (não média simples). Sem suporte
# nativo a pinning no Glide; total acompanha o sort do usuário.
section_title(
    "Indicadores - Fonte de Lead",
    "agendamentos líquidos · regra origem_final (Looker)",
)
tab_fonte = _tabela_indicadores_fonte(df_prev_fonte)
if tab_fonte.empty:
    st.info("Sem dados de Pré-vendas por fonte no período.")
else:
    tot_f = _total_prevendas_from_absolutes(
        df_prev_fonte,
        abs_cols=[
            "agendamentos", "agendamentos_mais_12", "agendamentos_menos_12",
            "comparecimentos", "vendas", "montante", "receita",
        ],
    )
    total_row_f = {
        "Fonte":             "Total do período",
        "Agendamentos":      tot_f["agendamentos"],
        "+12":               tot_f["agendamentos_mais_12"],
        "% +12":             tot_f["pct_mais_12"],
        "-12":               tot_f["agendamentos_menos_12"],
        "% -12":             tot_f["pct_menos_12"],
        "Comparecimento":    tot_f["comparecimentos"],
        "Montante":          tot_f["montante"],
        "Receita":           tot_f["receita"],
        "% Recebimento":     tot_f["pct_recebimento"],
        "% Conversão":       tot_f["pct_conversao"],
        "% Venda":           tot_f["pct_venda"],
        "% Comparecimento":  tot_f["pct_comparecimento"],
    }
    tab_fonte = pd.concat(
        [tab_fonte, pd.DataFrame([total_row_f])],
        ignore_index=True,
    )
    tab_fonte = _br_format_table(
        tab_fonte,
        money_cols=("Montante", "Receita"),
        int_cols=("Agendamentos", "+12", "-12", "Comparecimento"),
        pct_cols=("% +12", "% -12", "% Recebimento",
                  "% Conversão", "% Venda", "% Comparecimento"),
    )
    st.dataframe(
        tab_fonte,
        use_container_width=True,
        hide_index=True,
    )

# ---- Tabela por Executiva --------------------------------------------------
# Fonte: cálculo direto a partir de `zoho_deals` + `zoho_activities` +
# `fdw_reconecta.executivas_vendas`. Nome resolvido por
# `zoho_deals.executiva_vendas = executivas_vendas.id_crm`. Visão padrão
# mostra só ativas; opção "Todas / Histórico" expõe inativas e IDs órfãos
# pra auditoria. Não usa mais a view legada nem o `df_exec` cá no bloco.
section_title(
    "Por Executiva",
    "cálculo direto · zoho_deals + executivas_vendas (cadastro oficial)",
)
_modo_label = st.radio(
    "Visualização de executivas",
    options=("Ativas", "Todas / Histórico"),
    index=0,
    horizontal=True,
    help=(
        "Ativas: apenas executivas com `ativo='y'` no cadastro oficial.\n"
        "Todas / Histórico: inclui inativas e IDs sem cadastro (para auditoria)."
    ),
    key="onepage_exec_modo",
)
_modo_arg = "ativas" if _modo_label == "Ativas" else "todas"
rank_exec = get_one_page_por_executiva(ctx.data_ini, ctx.data_fim, _modo_arg)
if rank_exec is None or rank_exec.empty:
    st.info("Sem ranking de executivas no período.")
else:
    cols_exec = [c for c in (
        "executiva", "agendamentos", "comparecimentos", "vendas",
        "montante", "receita",
        "pct_recebimento", "pct_conversao", "pct_vendas", "pct_comparecimento",
    ) if c in rank_exec.columns]
    tab_exec = rank_exec[cols_exec].copy()
    tab_exec_disp = tab_exec.rename(columns={
        "executiva":          "Executiva",
        "agendamentos":       "Agendamentos",
        "comparecimentos":    "Comparec.",
        "vendas":             "Vendas",
        "montante":           "Montante",
        "receita":            "Receita",
        "pct_recebimento":    "% Recebimento",
        "pct_conversao":      "% Conversão",
        "pct_vendas":         "% Vendas",
        "pct_comparecimento": "% Comparec.",
    })
    tot_e = _total_prevendas_from_absolutes(
        tab_exec,
        abs_cols=["agendamentos", "comparecimentos",
                  "vendas", "montante", "receita"],
    )
    total_row_e = {
        "Executiva":      "Total do período",
        "Agendamentos":   tot_e["agendamentos"],
        "Comparec.":      tot_e["comparecimentos"],
        "Vendas":         tot_e["vendas"],
        "Montante":       tot_e["montante"],
        "Receita":        tot_e["receita"],
        "% Recebimento":  tot_e["pct_recebimento"],
        "% Conversão":    tot_e["pct_conversao"],
        "% Vendas":       tot_e["pct_venda"],
        "% Comparec.":    tot_e["pct_comparecimento"],
    }
    tab_exec_disp = pd.concat(
        [tab_exec_disp, pd.DataFrame([total_row_e])],
        ignore_index=True,
    )
    tab_exec_disp = _br_format_table(
        tab_exec_disp,
        money_cols=("Montante", "Receita"),
        int_cols=("Agendamentos", "Comparec.", "Vendas"),
        pct_cols=("% Recebimento", "% Conversão",
                  "% Vendas", "% Comparec."),
    )
    st.dataframe(
        tab_exec_disp,
        use_container_width=True,
        hide_index=True,
    )

# ---- Tabela por SDR × Closer -----------------------------------------------
# Fonte: cálculo direto a partir de `zoho_deals` + `zoho_activities` +
# `fdw_reconecta.executivas_pre_vendas` + `executivas_vendas`. Visão padrão
# mostra só SDR cadastrada + closer ativa; "Todas / Histórico" inclui
# inativas e IDs órfãos (fallback SDR em `zoho_users` quando possível).
section_title(
    "Por SDR × Closer",
    "cálculo direto · zoho_deals + executivas_pre_vendas / executivas_vendas",
)
_modo_sc_label = st.radio(
    "Visualização SDR × Closer",
    options=("Ativos", "Todas / Histórico"),
    index=0,
    horizontal=True,
    help=(
        "Ativos: SDR presente em `executivas_pre_vendas` e Closer com "
        "`ativo='y'` no cadastro oficial.\n"
        "Todas / Histórico: inclui inativas e IDs sem cadastro (para auditoria)."
    ),
    key="onepage_sc_modo",
)
_modo_sc_arg = "ativos" if _modo_sc_label == "Ativos" else "todas"
try:
    df_prev_sc = get_one_page_sdr_closer(
        ctx.data_ini, ctx.data_fim, _modo_sc_arg,
    )
except Exception as e:
    st.warning(f"Falha ao consultar SDR × Closer: {e}")
    df_prev_sc = pd.DataFrame()
tab_sc = _tabela_sdr_closer(df_prev_sc)
if tab_sc.empty:
    st.info("Sem pares SDR × Closer com atividade no período.")
else:
    tab_sc_disp = tab_sc.rename(columns={
        "sdr":                "SDR",
        "closer":             "Closer",
        "agendamentos":       "Agendamentos",
        "comparecimentos":    "Comparec.",
        "vendas":             "Vendas",
        "montante":           "Montante",
        "receita":            "Receita",
        "pct_recebimento":    "% Recebimento",
        "pct_conversao":      "% Conversão",
        "pct_vendas":         "% Vendas",
        "pct_comparecimento": "% Comparec.",
    })
    tab_sc_disp = _br_format_table(
        tab_sc_disp,
        money_cols=("Montante", "Receita"),
        int_cols=("Agendamentos", "Comparec.", "Vendas"),
        pct_cols=("% Recebimento", "% Conversão",
                  "% Vendas", "% Comparec."),
    )
    # Altura limitada (~420px) — até ~64 linhas no período típico,
    # ocuparia metade da One Page sem scroll interno. Total fica FORA
    # do scroll, numa linha-rodapé `_render_total_row` alinhada por
    # CSS Grid (aproximação visual: Glide não expõe larguras reais).
    st.dataframe(
        tab_sc_disp,
        use_container_width=True,
        hide_index=True,
        height=420,
    )
    tot_sc = _total_prevendas_from_absolutes(
        tab_sc,
        abs_cols=["agendamentos", "comparecimentos",
                  "vendas", "montante", "receita"],
    )
    # Pesos calibrados pelo conteúdo médio das colunas (SDR/Closer com
    # nomes longos = mais peso; numéricas/percentuais menores). Ordem
    # MESMA do `tab_sc_disp` pra colunas caírem visualmente alinhadas:
    # SDR · Closer · Agend. · Comp. · Vendas · Montante · Receita ·
    # % Comp. · % Conv. · % Vendas · % Recb.
    _render_total_row(
        cells=[
            ("Total do período",                       "label"),
            ("",                                        "txt"),
            (int_br(tot_sc["agendamentos"]),            "accent"),
            (int_br(tot_sc["comparecimentos"]),         "num"),
            (int_br(tot_sc["vendas"]),                  "num"),
            (brl(tot_sc["montante"]),                   "num"),
            (brl(tot_sc["receita"]),                    "accent"),
            (pct(tot_sc["pct_comparecimento"]),         "num"),
            (pct(tot_sc["pct_conversao"]),              "num"),
            (pct(tot_sc["pct_venda"]),                  "num"),
            (pct(tot_sc["pct_recebimento"]),            "num"),
        ],
        weights=[1.5, 1.8, 0.95, 0.85, 0.75, 1.05, 1.05, 1.0, 0.95, 0.85, 1.0],
    )

# ---- Tabela semanal (matriz executiva no formato Looker) -------------------
section_title(
    "Indicadores semanais",
    "matriz executiva · semanas no topo · métricas na lateral",
)
tab_sem = _tabela_semanal(df_one, df_prev_dia, df_exec)
_render_indicadores_semanais(tab_sem)
