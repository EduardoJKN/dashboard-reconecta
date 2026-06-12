"""Histórico de referência do Funil da Reconecta — somente leitura (sem banco)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from src.funil_meta_store import pct_to_display_percent
from src.one_page_funnel import (
    FunnelSnapshot,
    load_one_page_funnel,
    snapshot_to_scenario_dict,
)


def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    return nxt - timedelta(days=1)


def reference_period_defs(anchor: date) -> list[tuple[str, str, date, date]]:
    """Períodos de referência ancorados na data fim do filtro."""
    defs: list[tuple[str, str, date, date]] = []
    first_curr = anchor.replace(day=1)
    defs.append(
        ("mes_atual", f"Mês atual ({first_curr:%m/%Y})", first_curr, anchor),
    )

    month_start = first_curr
    for months_back in (1, 2, 3):
        prev_end = month_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        label = (
            "Mês anterior"
            if months_back == 1
            else f"{months_back} meses atrás"
        )
        defs.append(
            (
                f"mes_{months_back}",
                f"{label} ({prev_start:%m/%Y})",
                prev_start,
                prev_end,
            ),
        )
        month_start = prev_start

    defs.append(
        (
            "ult_3m",
            "Últimos 3 meses",
            anchor - timedelta(days=89),
            anchor,
        ),
    )
    defs.append(
        (
            "ult_6m",
            "Últimos 6 meses",
            anchor - timedelta(days=179),
            anchor,
        ),
    )
    return defs


def snapshot_to_historico_row(
    snapshot: FunnelSnapshot,
    *,
    period_id: str,
    label: str,
    data_ini: date,
    data_fim: date,
) -> dict[str, Any]:
    """Uma linha do histórico com cenário reutilizável em session_state."""
    vendas = float(snapshot.vendas)
    montante = float(snapshot.montante)
    receita = float(snapshot.receita)
    return {
        "id": period_id,
        "periodo": label,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "investimento": float(snapshot.investimento),
        "custo_lead": float(snapshot.custo_lead),
        "leads": float(snapshot.leads),
        "pct_la": float(snapshot.pct_la),
        "aplicacoes": float(snapshot.aplicacoes),
        "pct_a_ag": float(snapshot.pct_a_ag),
        "agendamentos": float(snapshot.agendamentos),
        "pct_ag_c": float(snapshot.pct_ag_c),
        "comparecimento": float(snapshot.comparecimento),
        "pct_c_v": float(snapshot.pct_c_v),
        "vendas": vendas,
        "ticket": float(snapshot.ticket),
        "montante": montante,
        "receita": receita,
        "pct_recebimento": float(snapshot.pct_recebimento),
        "scenario": snapshot_to_scenario_dict(snapshot),
    }


@st.cache_data(ttl=600, show_spinner=False)
def load_funil_historico_referencias(
    anchor_iso: str,
    periodo_ini_iso: str,
    periodo_fim_iso: str,
    excluir_testes_aplicacoes: bool,
) -> list[dict[str, Any]]:
    """Carrega snapshots reais por período — mesmas regras do bloco Atual."""
    anchor = date.fromisoformat(anchor_iso)
    p_ini = date.fromisoformat(periodo_ini_iso)
    p_fim = date.fromisoformat(periodo_fim_iso)
    rows: list[dict[str, Any]] = []

    try:
        snap_sel = load_one_page_funnel(
            p_ini,
            p_fim,
            excluir_testes_aplicacoes=excluir_testes_aplicacoes,
        )
        rows.append(
            snapshot_to_historico_row(
                snap_sel,
                period_id="periodo_selecionado",
                label="Período selecionado",
                data_ini=p_ini,
                data_fim=p_fim,
            ),
        )
    except Exception:
        pass

    for period_id, label, ini, fim in reference_period_defs(anchor):
        try:
            snap = load_one_page_funnel(
                ini,
                fim,
                excluir_testes_aplicacoes=excluir_testes_aplicacoes,
            )
            rows.append(
                snapshot_to_historico_row(
                    snap,
                    period_id=period_id,
                    label=label,
                    data_ini=ini,
                    data_fim=fim,
                ),
            )
        except Exception:
            continue

    return rows


def historico_rows_to_display_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """DataFrame para exibição (sem payload de cenário)."""
    if not rows:
        return pd.DataFrame()
    records = []
    for r in rows:
        records.append({
            "Período": r["periodo"],
            "Investimento": r["investimento"],
            "CPL": r["custo_lead"],
            "Leads": r["leads"],
            "% L→Apl": pct_to_display_percent(r["pct_la"]),
            "Aplicações": r["aplicacoes"],
            "% Apl→Ag": pct_to_display_percent(r["pct_a_ag"]),
            "Agendamentos": r["agendamentos"],
            "% Ag→Comp": pct_to_display_percent(r["pct_ag_c"]),
            "Comparecimentos": r["comparecimento"],
            "% Comp→Vda": pct_to_display_percent(r["pct_c_v"]),
            "Vendas": r["vendas"],
            "Ticket": r["ticket"],
            "Montante": r["montante"],
            "Receita": r["receita"],
            "% Rec/Mont": r["pct_recebimento"],
        })
    return pd.DataFrame(records)


def historico_row_by_index(
    rows: list[dict[str, Any]],
    index: int,
) -> dict[str, Any] | None:
    if not rows or index < 0 or index >= len(rows):
        return None
    return rows[index]
