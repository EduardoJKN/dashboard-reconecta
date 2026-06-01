"""Funil consolidado da One Page — fontes e regras compartilhadas.

Agrega Marketing (legacy diário), Pré-vendas (overview) e Vendas
(executivas) no mesmo recorte de datas usado pela página One Page.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from src.prevendas_transforms import prevendas_overview_kpis
from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_one_page_legacy_diario,
    get_prevendas_overview_diario,
)
from src.transforms import visao_geral_kpis


def safe_div(num, den) -> float:
    try:
        d = float(den or 0)
        return float(num or 0) / d if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def sum_column(df: pd.DataFrame, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(df[col].fillna(0).sum())


def period_column(df: pd.DataFrame, period_col: str, daily_col: str) -> float:
    """Total do período: coluna *_periodo (dedupe no intervalo) ou soma diária."""
    if df is None or df.empty:
        return 0.0
    if period_col in df.columns:
        return float(df[period_col].fillna(0).max())
    return sum_column(df, daily_col)


def aplicacoes_kpis(df_one: pd.DataFrame) -> dict:
    """KPIs de Marketing — regra LEGADA do Looker (`one_page_legacy_diario`).

    Aplicações e ±12 usam e-mails únicos no período (`*_periodo`), não a
    soma de distintos por dia (evita contar o mesmo e-mail em dias diferentes).
    """
    leads = sum_column(df_one, "novos_leads")
    aplicacoes = period_column(
        df_one, "novas_aplicacoes_periodo", "novas_aplicacoes"
    )
    apl_mais12 = period_column(
        df_one, "aplicacoes_mais_12_periodo", "aplicacoes_mais_12"
    )
    apl_menos12 = period_column(
        df_one, "aplicacoes_menos_12_periodo", "aplicacoes_menos_12"
    )
    apl_naoatua = period_column(
        df_one, "aplicacoes_nao_atua_periodo", "aplicacoes_nao_atua"
    )
    investimento = sum_column(df_one, "investimento")
    agendamentos = sum_column(df_one, "agendamentos")
    apl_total_ag = period_column(
        df_one, "aplicacoes_com_agendamento_periodo", "aplicacoes_com_agendamento"
    )
    apl_m12_ag = period_column(
        df_one,
        "aplicacoes_mais_12_com_agendamento_periodo",
        "aplicacoes_mais_12_com_agendamento",
    )
    apl_n12_ag = period_column(
        df_one,
        "aplicacoes_menos_12_com_agendamento_periodo",
        "aplicacoes_menos_12_com_agendamento",
    )

    return {
        "leads_totais": leads,
        "aplicacoes": aplicacoes,
        "aplicacoes_mais_12": apl_mais12,
        "aplicacoes_menos_12": apl_menos12,
        "aplicacoes_nao_atua": apl_naoatua,
        "pct_aplicacoes": safe_div(aplicacoes, leads) * 100,
        "investimento": investimento,
        "cpl": safe_div(investimento, leads),
        "custo_aplicacao": safe_div(investimento, aplicacoes),
        "custo_apl_mais_12": safe_div(investimento, apl_mais12),
        "custo_apl_menos_12": safe_div(investimento, apl_menos12),
        "agendamentos_legacy": agendamentos,
        "pct_agendamento": safe_div(agendamentos, aplicacoes) * 100,
        "pct_agendamento_apl": safe_div(apl_total_ag, aplicacoes) * 100,
        "pct_agendamento_apl_mais_12": safe_div(apl_m12_ag, apl_mais12) * 100,
        "pct_agendamento_apl_menos_12": safe_div(apl_n12_ag, apl_menos12) * 100,
    }


@dataclass
class FunnelSnapshot:
    """Volumes e taxas reais do período (totais, antes de escala Mês/Sem/Dia)."""
    investimento: float
    leads: float
    aplicacoes: float
    agendamentos: float
    comparecimento: float
    vendas: float
    montante: float
    custo_lead: float
    pct_la: float
    pct_a_ag: float
    pct_ag_c: float
    pct_c_v: float
    ticket: float


def load_one_page_funnel(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool = False,
) -> FunnelSnapshot:
    """Carrega o funil real do período com as mesmas regras da One Page."""
    df_one = get_one_page_legacy_diario(
        data_ini, data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    df_prev = get_prevendas_overview_diario(data_ini, data_fim)
    df_exec = get_executivas(data_ini, data_fim)
    df_inv = get_investimento_diario(data_ini, data_fim)

    k_apl = aplicacoes_kpis(df_one)
    k_prev = prevendas_overview_kpis(df_prev)
    k_vend = visao_geral_kpis(df_exec, df_inv)

    investimento = float(k_apl["investimento"])
    leads = float(k_apl["leads_totais"])
    aplicacoes = float(k_apl["aplicacoes"])
    agendamentos = float(k_prev["agendamentos_exibidos"])
    comparecimento = float(k_prev["comparecimentos"])
    vendas = float(k_vend["vendas"])
    montante = float(k_vend["montante"])

    return FunnelSnapshot(
        investimento=investimento,
        leads=leads,
        aplicacoes=aplicacoes,
        agendamentos=agendamentos,
        comparecimento=comparecimento,
        vendas=vendas,
        montante=montante,
        custo_lead=safe_div(investimento, leads),
        pct_la=safe_div(aplicacoes, leads),
        pct_a_ag=safe_div(agendamentos, aplicacoes),
        pct_ag_c=safe_div(comparecimento, agendamentos),
        pct_c_v=safe_div(vendas, comparecimento),
        ticket=safe_div(montante, vendas),
    )


def snapshot_to_scenario_dict(snapshot: FunnelSnapshot) -> dict:
    """Converte snapshot em dict compatível com `Scenario` do Funil."""
    return {
        "investimento": snapshot.investimento,
        "custo_lead": snapshot.custo_lead,
        "pct_la": snapshot.pct_la,
        "pct_a_ag": snapshot.pct_a_ag,
        "pct_ag_c": snapshot.pct_ag_c,
        "pct_c_v": snapshot.pct_c_v,
        "ticket": snapshot.ticket,
    }


def snapshot_calc_display(
    snapshot: FunnelSnapshot,
    periodo: str,
    periodos: dict,
) -> dict:
    """Volumes do Atual na escala Mês / Semana / Dia (divisores proporcionais)."""
    div = periodos[periodo]["divisor"]
    return {
        "investimento": snapshot.investimento / div,
        "leads": snapshot.leads / div,
        "aplicacoes": snapshot.aplicacoes / div,
        "agendamentos": snapshot.agendamentos / div,
        "comparecimento": snapshot.comparecimento / div,
        "vendas": snapshot.vendas / div,
        "faturamento": snapshot.montante / div,
    }


def snapshot_as_dict(snapshot: FunnelSnapshot) -> dict:
    return asdict(snapshot)
