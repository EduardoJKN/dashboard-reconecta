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

import streamlit as st

from src.funil_export import (
    FunilExportBundle,
    export_funil_csv,
    export_funil_excel,
    export_funil_pdf,
)
from src.funil_meta_store import (
    PERIODO_TIPO_PADRAO,
    load_funil_meta,
    metas_dict_from_scenario,
    save_funil_meta,
)
from src.one_page_funnel import (
    FunnelSnapshot,
    load_one_page_funnel,
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


def pct_fmt(v: float, casas: int = 2) -> str:
    """Taxa em fração (0–1+) → exibição com % e duas casas."""
    return f"{v * 100:.{casas}f}%".replace(".", ",")


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
    padding: 12px 14px;
    min-height: 4.1rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
    box-sizing: border-box;
    border-radius: 7px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.2),
        0 2px 8px rgba(0, 0, 0, 0.12);
}
.fr-fatu .lbl {
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: rgba(58, 24, 32, 0.58);
}
.fr-fatu .val {
    font-family: ui-monospace, "IBM Plex Mono", monospace;
    font-size: 1.36rem;
    font-weight: 700;
    margin-top: 3px;
    color: rgba(48, 20, 30, 0.9);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.015em;
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
        if k.startswith("meta_ed_"):
            if not sim_only:
                del st.session_state[k]
            continue
        if k.endswith(_WIDGET_SUFFIXES):
            del st.session_state[k]


def _clear_meta_editor_widget_keys() -> None:
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("meta_ed_"):
            del st.session_state[k]


def _funil_period_storage_key(data_ini: date, data_fim: date) -> str:
    return f"{data_ini.isoformat()}_{data_fim.isoformat()}"


def _sync_official_meta_for_period(
    data_ini: date,
    data_fim: date,
    *,
    force: bool = False,
) -> None:
    """Carrega metas oficiais do banco quando o filtro global muda."""
    key = _funil_period_storage_key(data_ini, data_fim)
    if not force and st.session_state.get("funil_meta_period_key") == key:
        return
    st.session_state["funil_meta_period_key"] = key
    try:
        loaded = load_funil_meta(PERIODO_TIPO_PADRAO, data_ini, data_fim)
    except Exception:
        loaded = None
    official = loaded if loaded is not None else asdict(_BASE_META)
    st.session_state["funil_meta_oficial"] = official
    st.session_state["funil_meta_draft"] = dict(official)
    _clear_meta_editor_widget_keys()


def _get_meta_oficial() -> Scenario:
    return Scenario(
        **st.session_state.get("funil_meta_oficial", asdict(_BASE_META)),
    )


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
) -> float:
    """Linha editável — mesma altura/tipografia; input compacto à direita."""
    col_l, col_r = st.columns(
        [1.55, 1], gap="small", vertical_alignment="center",
    )
    with col_l:
        st.markdown(
            f'<span class="fr-vitrine-editable-row {html.escape(cell_class)}" '
            f'aria-hidden="true"></span>'
            f'<span class="lbl bold lbl-chip">{html.escape(label)}</span>',
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


def _vitrine_row_specs(periodo: str) -> list[dict]:
    """Ordem fixa dos indicadores — mesma sequência nas três colunas."""
    return [
        {"id": "inv", "label": _investimento_label(periodo), "sim_editable": True,
         "input": "inv_period"},
        {"id": "cl", "label": "Custo por Lead (R$)", "sim_editable": True,
         "input": "money"},
        {"id": "leads", "label": "Leads", "computed": True, "group_after": True},
        {"id": "pct_la", "label": "% Lead → Aplicação", "sim_editable": True,
         "input": "pct"},
        {"id": "aplicacoes", "label": "Aplicações", "computed": True,
         "group_after": True},
        {"id": "pct_a_ag", "label": "% Aplicação → Agendamento", "sim_editable": True,
         "input": "pct"},
        {"id": "agendamentos", "label": "Agendamentos", "computed": True,
         "group_after": True},
        {"id": "pct_ag_c", "label": "% Agendamento → Comparecimento",
         "sim_editable": True, "input": "pct"},
        {"id": "comparecimento", "label": "Comparecimento", "computed": True},
        {"id": "pct_c_v", "label": "% Comparecimento → Venda", "sim_editable": True,
         "input": "pct"},
        {"id": "vendas", "label": "Vendas", "computed": True, "highlight": True,
         "group_after": True},
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
    if snapshot is not None:
        return snapshot_calc_display(snapshot, periodo, PERIODOS)
    return calcular_funil(atual_s, periodo)


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
) -> tuple[Scenario, Scenario, Scenario]:
    """Comparativo em grade: uma linha horizontal por indicador (Atual | Sim | Meta)."""
    st.markdown('<div class="fr-vitrine-sync">', unsafe_allow_html=True)

    key_prefix = "simulador"
    div = PERIODOS[periodo]["divisor"]
    rows = _vitrine_row_specs(periodo)
    n_rows = len(rows)
    calc_atual_display = _calc_atual_display(snapshot, atual_s, periodo)

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
    meta_s = _get_meta_oficial()

    for idx, spec in enumerate(rows):
        sim_s = Scenario(**sim_state)
        calc_s = calcular_funil(sim_s, periodo)
        calc_m = calcular_funil(meta_s, periodo)

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
            if spec.get("sim_editable"):
                inp = spec["input"]
                step = 100.0 if inp == "inv_period" else (0.5 if inp == "pct" else 1.0)
                raw = _render_scenario_row_editable(
                    label,
                    _sim_widget_key(spec, key_prefix),
                    _sim_editable_value(spec, sim_state, div=div),
                    cell_class=cell_sim,
                    step=step,
                    is_percent=(inp == "pct"),
                )
                _apply_sim_editable(spec, sim_state, raw, div=div)
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
    calc_s = calcular_funil(sim_s, periodo)
    calc_m = calcular_funil(meta_s, periodo)

    f_atual, f_sim, f_meta = st.columns(3, gap="medium")
    with f_atual:
        st.markdown(
            '<div class="fr-vitrine-fatu-shell col-atual">',
            unsafe_allow_html=True,
        )
        _render_faturamento_block(calc_atual_display)
        st.markdown("</div></div>", unsafe_allow_html=True)
    with f_sim:
        st.markdown(
            '<div class="fr-vitrine-fatu-shell col-sim">',
            unsafe_allow_html=True,
        )
        _render_faturamento_block(calc_s)
        st.markdown("</div></div>", unsafe_allow_html=True)
    with f_meta:
        st.markdown(
            '<div class="fr-vitrine-fatu-shell col-meta">',
            unsafe_allow_html=True,
        )
        _render_faturamento_block(calc_m)
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


def _render_faturamento_block(calc: dict) -> None:
    st.markdown(
        f'<div class="fr-card fr-fatu-card">'
        f'  <div class="fr-fatu">'
        f'    <div class="lbl">Faturamento</div>'
        f'    <div class="val">{html.escape(brl(calc["faturamento"]))}</div>'
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


def _render_meta_editor(
    periodo: str,
    *,
    data_ini: date,
    data_fim: date,
) -> Scenario:
    """Editor de rascunho — metas oficiais só persistem ao clicar em Aplicar."""
    section_title(
        "Editor de metas",
        "objetivos oficiais do período — a coluna Meta usa o que estiver salvo",
    )
    st.markdown(
        '<div class="fr-editor-wrap meta">'
        '<p class="fr-editor-hint">'
        "Ajuste investimento, custo por lead, taxas e ticket alvo. "
        "As alterações abaixo são um <strong>rascunho</strong> até você aplicar. "
        "A coluna <strong>Meta</strong>, o gargalo e os exports usam as metas "
        "<strong>oficiais</strong> já salvas para este período."
        "</p>",
        unsafe_allow_html=True,
    )
    if "funil_meta_draft" not in st.session_state:
        st.session_state["funil_meta_draft"] = dict(
            st.session_state.get("funil_meta_oficial", asdict(_BASE_META)),
        )
    draft = _render_scenario_fields_editor(
        periodo,
        "funil_meta_draft",
        _get_meta_oficial(),
        "meta_ed",
    )
    st.session_state["funil_meta_draft"] = asdict(draft)

    st.warning(
        "Você está prestes a alterar as metas oficiais do período selecionado "
        f"({data_ini.strftime('%d/%m/%Y')}–{data_fim.strftime('%d/%m/%Y')}). "
        "Confirme abaixo antes de aplicar.",
    )
    confirmado = st.checkbox(
        "Confirmo que quero aplicar essas metas como oficiais",
        key="funil_meta_confirm_apply",
    )
    b_apply, b_restore = st.columns(2)
    with b_apply:
        aplicar = st.button(
            "Aplicar metas oficiais",
            type="primary",
            use_container_width=True,
            disabled=not confirmado,
        )
    with b_restore:
        if st.button("Restaurar metas padrão", use_container_width=True):
            st.session_state["funil_meta_draft"] = asdict(_BASE_META)
            _clear_meta_editor_widget_keys()
            st.info(
                "Rascunho restaurado aos valores padrão. "
                "Clique em «Aplicar metas oficiais» para gravar no banco."
            )
            st.rerun()

    if aplicar:
        try:
            save_funil_meta(
                PERIODO_TIPO_PADRAO,
                data_ini,
                data_fim,
                metas_dict_from_scenario(st.session_state["funil_meta_draft"]),
                criado_por="dashboard",
            )
            st.session_state["funil_meta_oficial"] = dict(
                st.session_state["funil_meta_draft"],
            )
            st.session_state["funil_meta_confirm_apply"] = False
            st.success("Metas aplicadas com sucesso.")
            st.rerun()
        except Exception as exc:
            st.error(f"Não foi possível salvar as metas: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)
    return draft


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
        "Mesma regra da One Page."
    ),
)

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

_sync_official_meta_for_period(ctx.data_ini, ctx.data_fim)

atual_s = Scenario(**st.session_state["funil_atual"])
meta_oficial_s = _get_meta_oficial()

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

# Alerta de gargalo (Atual real vs Meta oficial).
impactos = identificar_gargalos(atual_s, meta_oficial_s)
_render_alerta_gargalo(impactos, periodo)

section_title(
    "Comparativo de cenários",
    "Compare Atual, Simulador e Meta — ajuste o cenário na coluna central.",
)
atual_s, sim_s, meta_s = _render_vitrine_comparison(
    periodo, atual_s=atual_s, snapshot=_funnel_snapshot,
)

calc_atual = _calc_atual_display(_funnel_snapshot, atual_s, periodo)
calc_sim   = calcular_funil(sim_s, periodo)
calc_meta  = calcular_funil(meta_s, periodo)

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
    meta=meta_oficial_s,
    calc_atual=calc_atual,
    calc_sim=calc_sim,
    calc_meta=calc_meta,
    impactos=impactos,
)
with _export_top_slot.container():
    with st.popover("Exportar relatório", use_container_width=True):
        _render_export_actions(_export_bundle)

# Editor de metas — rascunho; oficial só ao aplicar.
_render_meta_editor(periodo, data_ini=ctx.data_ini, data_fim=ctx.data_fim)

st.markdown(
    '<div class="fr-footer-note">'
    f'Atual: dados reais do período ({ctx.data_ini.strftime("%d/%m/%Y")}'
    f'–{ctx.data_fim.strftime("%d/%m/%Y")}), mesmas regras da One Page. '
    'Semana e Dia são aproximações proporcionais (÷ 4 e ÷ 28). '
    'Edite o Simulador na coluna central; metas oficiais no editor abaixo '
    '(salvas ao clicar em Aplicar).'
    '</div>',
    unsafe_allow_html=True,
)
