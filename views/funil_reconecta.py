"""Funil da Reconecta — Simulador de cenários do funil comercial.

Adaptação Streamlit do componente React em
`calculadora_funil_reconecta (1).jsx` (raiz do projeto). Versão visual
inicial — todos os inputs são editáveis e os cálculos rodam em Python
puro (sem ir ao banco). Os valores base vêm da planilha original
referenciada no JSX e podem ser ajustados manualmente pelo usuário.

Estrutura:
  1. Header (título + ações: resetar, exportar CSV)
  2. Toggle de período (Mês / Semana / Dia)
  3. Alerta de gargalo crítico (etapa com maior impacto se for nivelada à meta)
  4. 3 colunas de cenário: Atual · Simulador · Meta (cards lado-a-lado,
     cada um com inputs editáveis do funil)
  5. Cards de "Gap até a meta" (4 chips com a diferença em volume)
  6. Comparativo Simulador vs Atual (faixa destaque)

Lógica do funil:
  investimento → leads (= invest / custo_lead)
              → aplicações       (= leads * pctLA)
              → agendamentos     (= aplicações * pctAAg)
              → comparecimento   (= agendamentos * pctAgC)
              → vendas           (= comparecimento * pctCV)
              → faturamento      (= vendas * ticket)

Períodos: semana = mês/4; dia = mês/28 (mantém a premissa do JSX original).
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass

import pandas as pd
import streamlit as st

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


# Valores base (espelham VALORES_BASE no JSX original). Editáveis em tela.
_BASE_ATUAL = Scenario(
    investimento=115140.74,
    custo_lead=113.55,
    pct_la=0.5069,
    pct_a_ag=0.762,
    pct_ag_c=0.50,
    pct_c_v=0.2094,
    ticket=21400.0,
)
# Simulador parte idêntico ao Atual (o usuário ajusta pra simular hipóteses).
_BASE_SIMULADOR = Scenario(**asdict(_BASE_ATUAL))
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

def calcular_funil(s: Scenario, periodo: str) -> dict:
    """Cascata do funil para o período escolhido."""
    div = PERIODOS[periodo]["divisor"]
    investimento = s.investimento / div
    leads = investimento / s.custo_lead if s.custo_lead > 0 else 0.0
    aplicacoes = leads * s.pct_la
    agendamentos = aplicacoes * s.pct_a_ag
    comparecimento = agendamentos * s.pct_ag_c
    vendas = comparecimento * s.pct_c_v
    faturamento = vendas * s.ticket
    return {
        "investimento":   investimento,
        "leads":          leads,
        "aplicacoes":     aplicacoes,
        "agendamentos":   agendamentos,
        "comparecimento": comparecimento,
        "vendas":         vendas,
        "faturamento":    faturamento,
    }


def identificar_gargalos(atual: Scenario, meta: Scenario) -> list[dict]:
    """Lista de etapas ordenadas pelo impacto que teriam no faturamento
    mensal se fossem niveladas ao valor da meta. Inclui também Custo
    por Lead e Ticket Médio (impactos não-percentuais)."""
    base_fat = calcular_funil(atual, "mes")["faturamento"]
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
        novo = calcular_funil(hipo, "mes")["faturamento"]
        impactos.append({
            "key": key, "label": label, "impacto": novo - base_fat,
            "atual": atual_val, "meta": meta_val, "is_money": False,
        })

    if atual.custo_lead > meta.custo_lead:
        hipo = Scenario(**{**asdict(atual), "custo_lead": meta.custo_lead})
        novo = calcular_funil(hipo, "mes")["faturamento"]
        impactos.append({
            "key": "custo_lead", "label": "Custo por Lead",
            "impacto": novo - base_fat,
            "atual": atual.custo_lead, "meta": meta.custo_lead,
            "is_money": True,
        })
    if atual.ticket < meta.ticket:
        hipo = Scenario(**{**asdict(atual), "ticket": meta.ticket})
        novo = calcular_funil(hipo, "mes")["faturamento"]
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


def num(v: float, casas: int = 1) -> str:
    """Número BR com `casas` decimais — usa ponto pra milhar, vírgula pra decimal."""
    s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def pct_fmt(v: float, casas: int = 2) -> str:
    return f"{v * 100:.{casas}f}%".replace(".", ",")


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
.fr-fatu {
    background: var(--color-gold);
    color: var(--color-wine);
    padding: 10px 14px;
}
.fr-fatu .lbl {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    color: var(--color-wine);
}
.fr-fatu .val {
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-size: 1.4rem;
    font-weight: 700;
    margin-top: 2px;
    color: var(--color-wine);
    font-variant-numeric: tabular-nums;
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


def _scenario_inputs(titulo: str, key_prefix: str, base: Scenario,
                     periodo: str) -> Scenario:
    """Renderiza o card de um cenário com inputs editáveis em
    `st.session_state` e devolve o objeto Scenario atualizado."""
    div = PERIODOS[periodo]["divisor"]
    accent = _CORES_CENARIO.get(titulo, PALETTE["wine"])

    # Inicializa session_state com base default na primeira execução.
    ss_key = f"funil_{key_prefix}"
    if ss_key not in st.session_state:
        st.session_state[ss_key] = asdict(base)
    state = st.session_state[ss_key]

    # Cabeçalho do card.
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-card-head" style="background:{accent};">'
        f'    <h3>{html.escape(titulo)}</h3>'
        f'    <div class="fr-period">{html.escape(PERIODOS[periodo]["label"])}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Investimento — ajustado ao período.
    label_inv = (
        "Investimento (mês)" if periodo == "mes"
        else "Investimento (semana)" if periodo == "semana"
        else "Investimento (dia)"
    )
    inv_periodo = st.number_input(
        label_inv,
        value=float(state["investimento"]) / div,
        min_value=0.0, step=100.0, format="%.2f",
        key=f"{key_prefix}_inv",
    )
    state["investimento"] = inv_periodo * div

    state["custo_lead"] = st.number_input(
        "Custo por Lead (R$)",
        value=float(state["custo_lead"]),
        min_value=0.0, step=1.0, format="%.2f",
        key=f"{key_prefix}_cl",
    )

    # Recalcula com valores correntes (necessário pra exibir derivados).
    s = Scenario(**state)
    calc = calcular_funil(s, periodo)

    # Linhas computadas + inputs de % alternados.
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-card-row"><span class="lbl bold">Leads</span>'
        f'    <span class="val computed">{num(calc["leads"])}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    state["pct_la"] = st.number_input(
        "% Lead → Aplicação",
        value=float(state["pct_la"]) * 100,
        min_value=0.0, max_value=100.0, step=0.5, format="%.2f",
        key=f"{key_prefix}_pla",
    ) / 100

    s = Scenario(**state); calc = calcular_funil(s, periodo)
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-card-row"><span class="lbl bold">Aplicações</span>'
        f'    <span class="val computed">{num(calc["aplicacoes"])}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    state["pct_a_ag"] = st.number_input(
        "% Aplicação → Agendamento",
        value=float(state["pct_a_ag"]) * 100,
        min_value=0.0, max_value=100.0, step=0.5, format="%.2f",
        key=f"{key_prefix}_paag",
    ) / 100

    s = Scenario(**state); calc = calcular_funil(s, periodo)
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-card-row"><span class="lbl bold">Agendamentos</span>'
        f'    <span class="val computed">{num(calc["agendamentos"])}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    state["pct_ag_c"] = st.number_input(
        "% Agendamento → Comparecimento",
        value=float(state["pct_ag_c"]) * 100,
        min_value=0.0, max_value=100.0, step=0.5, format="%.2f",
        key=f"{key_prefix}_pagc",
    ) / 100

    s = Scenario(**state); calc = calcular_funil(s, periodo)
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-card-row"><span class="lbl bold">Comparecimento</span>'
        f'    <span class="val computed">{num(calc["comparecimento"])}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    state["pct_c_v"] = st.number_input(
        "% Comparecimento → Venda",
        value=float(state["pct_c_v"]) * 100,
        min_value=0.0, max_value=100.0, step=0.5, format="%.2f",
        key=f"{key_prefix}_pcv",
    ) / 100

    s = Scenario(**state); calc = calcular_funil(s, periodo)
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-card-row highlight"><span class="lbl bold">Vendas</span>'
        f'    <span class="val computed" style="font-size:1.05rem;">{num(calc["vendas"])}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    state["ticket"] = st.number_input(
        "Ticket Médio (R$)",
        value=float(state["ticket"]),
        min_value=0.0, step=100.0, format="%.2f",
        key=f"{key_prefix}_tk",
    )

    s = Scenario(**state); calc = calcular_funil(s, periodo)
    st.markdown(
        f'<div class="fr-card">'
        f'  <div class="fr-fatu">'
        f'    <div class="lbl">Faturamento</div>'
        f'    <div class="val">{html.escape(brl(calc["faturamento"]))}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    return s


def _render_alerta_gargalo(impactos: list[dict], periodo: str) -> None:
    """Bloco de alerta com a etapa de maior impacto + ranking dos top-5."""
    top = impactos[0] if impactos else None
    div = PERIODOS[periodo]["divisor"]
    p_label = PERIODOS[periodo]["label"].lower()

    if not top or top["impacto"] <= 0:
        st.markdown(
            '<div class="fr-alert healthy">'
            '  <div class="kicker">↑ Funil saudável</div>'
            '  <h4>Cenário acima ou alinhado com a meta</h4>'
            '  <p class="note">Em todas as etapas, o cenário Atual está '
            'pelo menos no nível da meta. Não há gargalo a ser endereçado.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    ganho_periodo = top["impacto"] / div
    fmt_atual = brl(top["atual"]) if top.get("is_money") else pct_fmt(top["atual"])
    fmt_meta  = brl(top["meta"])  if top.get("is_money") else pct_fmt(top["meta"])

    pri_rows = []
    for idx, i in enumerate(
        [x for x in impactos[:5] if x["impacto"] > 0], start=1
    ):
        pri_rows.append(
            f'<div class="pri-row">'
            f'  <span class="left">'
            f'    <span class="badge">{idx}</span>{html.escape(i["label"])}'
            f'  </span>'
            f'  <span class="right">+ {html.escape(brl(i["impacto"]))}</span>'
            f'</div>'
        )
    pri_block = ""
    if len(pri_rows) > 1:
        pri_block = (
            '<div class="pri">'
            '  <div class="pri-title">Ordem de prioridade (impacto mensal)</div>'
            + "".join(pri_rows)
            + '</div>'
        )

    st.markdown(
        f'<div class="fr-alert">'
        f'  <div class="kicker">⚠ Gargalo crítico do funil</div>'
        f'  <h4>{html.escape(top["label"])}</h4>'
        f'  <div class="grid">'
        f'    <div><div class="k">Atual</div><div class="v">{html.escape(fmt_atual)}</div></div>'
        f'    <div><div class="k">Meta</div><div class="v">{html.escape(fmt_meta)}</div></div>'
        f'    <div>'
        f'      <div class="k">Ganho se ajustar ({html.escape(p_label)})</div>'
        f'      <div class="v accent">+ {html.escape(brl(ganho_periodo))}</div>'
        f'    </div>'
        f'  </div>'
        f'  <p class="note">Esta é a etapa com maior alavancagem: '
        f'levando ela ao nível da meta (mantendo o resto igual), o '
        f'faturamento já saltaria pelo valor acima.</p>'
        f'  {pri_block}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_gap_card(label: str, atual: float, meta: float,
                     periodo: str, is_money: bool = False) -> None:
    div = PERIODOS[periodo]["divisor"]
    gap = meta - atual
    pct = (gap / atual * 100) if atual > 0 else 0
    positivo = gap > 0
    valor = brl(gap / div) if is_money else int_br(gap / div)
    atual_f = brl(atual / div) if is_money else int_br(atual / div)
    meta_f  = brl(meta  / div) if is_money else int_br(meta  / div)
    delta_cls = "up" if positivo else "down"
    arrow = "↑" if positivo else "↓"

    st.markdown(
        f'<div class="fr-gap">'
        f'  <div class="lbl">{html.escape(label)}</div>'
        f'  <div class="row1">'
        f'    <span class="big">{html.escape(valor)}</span>'
        f'    <span class="delta {delta_cls}">{arrow} {abs(pct):.0f}%</span>'
        f'  </div>'
        f'  <div class="row2">'
        f'    <span>Atual: <span class="v">{html.escape(atual_f)}</span></span>'
        f'    <span>Meta: <span class="v">{html.escape(meta_f)}</span></span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_compare(calc_atual: dict, calc_sim: dict, calc_meta: dict) -> None:
    delta = calc_sim["faturamento"] - calc_atual["faturamento"]
    if delta > 0:
        title_html = f'<h3 class="up">+ {html.escape(brl(delta))}</h3>'
    elif delta < 0:
        title_html = f'<h3 class="down">- {html.escape(brl(abs(delta)))}</h3>'
    else:
        title_html = '<h3>Igual ao Atual</h3>'

    st.markdown(
        f'<div class="fr-compare">'
        f'  <div style="display:flex;justify-content:space-between;'
        f'flex-wrap:wrap;gap:14px;align-items:flex-start;">'
        f'    <div>'
        f'      <div class="kicker">Simulador vs Atual</div>'
        f'      {title_html}'
        f'      <p class="note">Diferença de faturamento entre o que você '
        f'está simulando e o cenário Atual real.</p>'
        f'    </div>'
        f'    <div class="right">'
        f'      <div class="col"><div class="k">Atual</div>'
        f'        <div class="v">{html.escape(brl(calc_atual["faturamento"]))}</div></div>'
        f'      <div class="col"><div class="k">Simulado</div>'
        f'        <div class="v gold">{html.escape(brl(calc_sim["faturamento"]))}</div></div>'
        f'      <div class="col"><div class="k">Meta</div>'
        f'        <div class="v green">{html.escape(brl(calc_meta["faturamento"]))}</div></div>'
        f'    </div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _exportar_csv(atual: Scenario, simulador: Scenario, meta: Scenario,
                  periodo: str) -> bytes:
    """Monta o CSV de comparação Atual / Simulador / Meta."""
    ca = calcular_funil(atual, periodo)
    cs = calcular_funil(simulador, periodo)
    cm = calcular_funil(meta, periodo)
    p_label = PERIODOS[periodo]["label"]
    rows = [
        ["Métrica", f"Atual ({p_label})", f"Simulador ({p_label})",
         f"Meta ({p_label})", "Gap Atual→Meta"],
        ["Investimento",    ca["investimento"],   cs["investimento"],   cm["investimento"],   cm["investimento"] - ca["investimento"]],
        ["Custo Lead",      atual.custo_lead,     simulador.custo_lead, meta.custo_lead,      meta.custo_lead - atual.custo_lead],
        ["Leads",           ca["leads"],          cs["leads"],          cm["leads"],          cm["leads"] - ca["leads"]],
        ["% L→A",           atual.pct_la,         simulador.pct_la,     meta.pct_la,          ""],
        ["Aplicações",      ca["aplicacoes"],     cs["aplicacoes"],     cm["aplicacoes"],     ""],
        ["% A→Ag",          atual.pct_a_ag,       simulador.pct_a_ag,   meta.pct_a_ag,        ""],
        ["Agendamentos",    ca["agendamentos"],   cs["agendamentos"],   cm["agendamentos"],   ""],
        ["% Ag→C",          atual.pct_ag_c,       simulador.pct_ag_c,   meta.pct_ag_c,        ""],
        ["Comparecimento",  ca["comparecimento"], cs["comparecimento"], cm["comparecimento"], ""],
        ["% C→V",           atual.pct_c_v,        simulador.pct_c_v,    meta.pct_c_v,         ""],
        ["Vendas",          ca["vendas"],         cs["vendas"],         cm["vendas"],         cm["vendas"] - ca["vendas"]],
        ["Ticket Médio",    atual.ticket,         simulador.ticket,     meta.ticket,          meta.ticket - atual.ticket],
        ["Faturamento",     ca["faturamento"],    cs["faturamento"],    cm["faturamento"],    cm["faturamento"] - ca["faturamento"]],
    ]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    # CSV com separador `;` (compatível com Excel pt-BR) e BOM UTF-8.
    return ("﻿" + df.to_csv(index=False, sep=";")).encode("utf-8")


# =============================================================================
# Página
# =============================================================================

start_page(
    title="Funil da Reconecta",
    subtitle="Simulador de cenários — compare contra a meta e ataque o gargalo",
    filters=(),
    include_period=False,
)

st.markdown(_FUNIL_CSS, unsafe_allow_html=True)

# Toggle de período (Mês / Semana / Dia) + ações de reset/export.
c1, c2 = st.columns([3, 2], gap="large")
with c1:
    periodo = st.segmented_control(
        "Período",
        options=list(PERIODOS.keys()),
        format_func=lambda k: PERIODOS[k]["label"],
        default="mes",
        key="funil_periodo",
        label_visibility="collapsed",
    ) or "mes"
with c2:
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Resetar valores", use_container_width=True):
            st.session_state["funil_atual"]     = asdict(_BASE_ATUAL)
            st.session_state["funil_simulador"] = asdict(_BASE_SIMULADOR)
            st.session_state["funil_meta"]      = asdict(_BASE_META)
            # Limpa os widgets de input ligados aos session_state acima
            for k in list(st.session_state.keys()):
                if isinstance(k, str) and (
                    k.endswith(("_inv", "_cl", "_tk",
                                "_pla", "_paag", "_pagc", "_pcv"))
                ):
                    del st.session_state[k]
            st.rerun()
    with b2:
        # Botão de export — espera os scenarios já estarem montados (fica
        # ativo após a renderização das colunas; usa session_state).
        try:
            _atual_export     = Scenario(**st.session_state.get("funil_atual",     asdict(_BASE_ATUAL)))
            _simulador_export = Scenario(**st.session_state.get("funil_simulador", asdict(_BASE_SIMULADOR)))
            _meta_export      = Scenario(**st.session_state.get("funil_meta",      asdict(_BASE_META)))
            st.download_button(
                "Exportar CSV",
                data=_exportar_csv(_atual_export, _simulador_export, _meta_export, periodo),
                file_name=f"funil_reconecta_{PERIODOS[periodo]['label'].lower()}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception:
            st.button("Exportar CSV", disabled=True, use_container_width=True)

# Alerta de gargalo (calculado com base nos valores atuais do session_state).
_atual_pre = Scenario(**st.session_state.get("funil_atual", asdict(_BASE_ATUAL)))
_meta_pre  = Scenario(**st.session_state.get("funil_meta",  asdict(_BASE_META)))
impactos = identificar_gargalos(_atual_pre, _meta_pre)
_render_alerta_gargalo(impactos, periodo)

# 3 colunas de cenário.
col_atual, col_sim, col_meta = st.columns(3, gap="medium")
with col_atual:
    atual_s = _scenario_inputs("Atual",     "atual",     _BASE_ATUAL,     periodo)
with col_sim:
    sim_s = _scenario_inputs("Simulador", "simulador", _BASE_SIMULADOR, periodo)
with col_meta:
    meta_s = _scenario_inputs("Meta",      "meta",      _BASE_META,      periodo)

# Recalcula com os scenarios já atualizados pelas inputs.
calc_atual = calcular_funil(atual_s, periodo)
calc_sim   = calcular_funil(sim_s,   periodo)
calc_meta  = calcular_funil(meta_s,  periodo)

# Gap até a meta — 4 cards lado a lado.
section_title(
    "Gap até a meta",
    f"diferença Atual → Meta no período ({PERIODOS[periodo]['label'].lower()})",
)
g1, g2, g3, g4 = st.columns(4, gap="small")
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
    _render_gap_card("Faturamento a mais",
                     calc_atual["faturamento"] * PERIODOS[periodo]["divisor"],
                     calc_meta["faturamento"]  * PERIODOS[periodo]["divisor"],
                     periodo, is_money=True)

# Comparativo Simulador vs Atual (faixa final).
st.markdown("&nbsp;", unsafe_allow_html=True)
_render_compare(calc_atual, calc_sim, calc_meta)

st.markdown(
    '<div class="fr-footer-note">'
    'Premissas: Semana = Mês ÷ 4 · Dia = Mês ÷ 28. '
    'Todos os campos numéricos são editáveis.'
    '</div>',
    unsafe_allow_html=True,
)
