#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnóstico — benchmark same_interval (janelas parciais vs mês fechado).

Uso:
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\debug_funil_benchmark_same_interval.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.funil_benchmark import resolve_historical_base
from src.one_page_funnel import (
    build_funnel_snapshot,
    build_funnel_snapshot_for_window,
    filter_df_date_range,
    load_benchmark_shared_frames,
)
from src.prevendas_transforms import prevendas_overview_kpis
from src.repositories import get_investimento_diario, get_prevendas_overview_diario
from src.one_page_funnel import _fetch_legacy_for_funil, _fetch_executivas_for_funil
from src.transforms import visao_geral_kpis


def _sum_col(df, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(df[col].sum())


def _diag_window(
    *,
    label: str,
    ini: date,
    fim: date,
    hist_ini: date,
    hist_fim: date,
    df_prev_wide,
    df_exec_wide,
    df_inv_wide,
) -> dict:
    df_one = _fetch_legacy_for_funil(ini, fim, excluir_testes_aplicacoes=False)
    df_prev_f = filter_df_date_range(df_prev_wide, ini, fim)
    df_exec_f = filter_df_date_range(df_exec_wide, ini, fim)
    df_inv_f = filter_df_date_range(df_inv_wide, ini, fim)

    snap = build_funnel_snapshot_for_window(
        ini,
        fim,
        excluir_testes_aplicacoes=False,
        df_prev_wide=df_prev_wide,
        df_exec_wide=df_exec_wide,
        df_inv_wide=df_inv_wide,
    )
    k_prev = prevendas_overview_kpis(df_prev_f)
    k_exec = visao_geral_kpis(df_exec_f, df_inv_f)

    return {
        "label": label,
        "window": f"{ini} -> {fim}",
        "wide_span": f"{hist_ini} -> {hist_fim}",
        "legacy_rows": len(df_one),
        "prev_rows_wide": len(df_prev_wide),
        "prev_rows_filtered": len(df_prev_f),
        "exec_rows_filtered": len(df_exec_f),
        "inv_rows_filtered": len(df_inv_f),
        "leads_prev": k_prev.get("leads", 0),
        "agendamentos": k_prev.get("agendamentos_exibidos", 0),
        "comparecimentos": k_prev.get("comparecimentos", 0),
        "vendas_prev": k_prev.get("vendas", 0),
        "montante_prev": k_prev.get("montante", 0),
        "receita_prev": k_prev.get("receita", 0),
        "vendas_exec": k_exec.get("vendas", 0),
        "montante_exec": k_exec.get("montante", 0),
        "receita_exec": k_exec.get("receita", 0),
        "snap_agendamentos": snap.agendamentos,
        "snap_comparecimento": snap.comparecimento,
        "snap_vendas": snap.vendas,
        "snap_ticket": snap.ticket,
        "snap_pct_rec": snap.pct_recebimento,
    }


def _run_case(*, same_interval: bool, title: str) -> list[dict]:
    hoje = date.today()
    page_ini = hoje.replace(day=1)
    page_fim = hoje
    spec = resolve_historical_base(
        page_ini,
        page_fim,
        base_key="90",
        same_interval=same_interval,
    )
    print(f"\n{'=' * 72}")
    print(title)
    print(f"Período atual: {page_ini} -> {page_fim}")
    print(f"same_interval: {same_interval}")
    print(f"Base: {spec.summary}")
    print(f"Intervalo amplo (shared): {spec.hist_ini} -> {spec.hist_fim}")
    if spec.hist_ini > spec.hist_fim:
        print("ERRO: hist_ini > hist_fim (intervalo amplo inválido)")
    print(f"Janelas: {spec.window_detail}")

    df_prev_w, df_exec_w, df_inv_w = load_benchmark_shared_frames(
        spec.hist_ini.isoformat(),
        spec.hist_fim.isoformat(),
    )
    rows: list[dict] = []
    for ini, fim, lbl in sorted(spec.ranges, key=lambda r: r[0]):
        row = _diag_window(
            label=lbl,
            ini=ini,
            fim=fim,
            hist_ini=spec.hist_ini,
            hist_fim=spec.hist_fim,
            df_prev_wide=df_prev_w,
            df_exec_wide=df_exec_w,
            df_inv_wide=df_inv_w,
        )
        rows.append(row)
        print(
            f"  [{lbl}] {ini} -> {fim} | "
            f"prev_f={row['prev_rows_filtered']} ag={row['snap_agendamentos']:.0f} "
            f"cmp={row['snap_comparecimento']:.0f} vendas={row['snap_vendas']:.0f} "
            f"ticket={row['snap_ticket']:.2f}"
        )

    # Comparação direta (1ª janela) vs wide+filter
    if spec.ranges:
        ini, fim, _ = sorted(spec.ranges, key=lambda r: r[0])[0]
        df_prev_direct = get_prevendas_overview_diario(ini, fim)
        direct_ag = _sum_col(df_prev_direct, "agendamentos")
        filtered_ag = _sum_col(filter_df_date_range(df_prev_w, ini, fim), "agendamentos")
        print(
            f"  [check 1ª janela] agendamentos direct={direct_ag:.0f} "
            f"filtered={filtered_ag:.0f} match={abs(direct_ag - filtered_ag) < 0.01}"
        )
    return rows


def main() -> int:
    print("Debug — benchmark same_interval (Funil da Reconecta)")
    partial = _run_case(
        same_interval=True,
        title="CASO A — same_interval=true (janelas parciais)",
    )
    closed = _run_case(
        same_interval=False,
        title="CASO B — same_interval=false (meses fechados)",
    )

    partial_ok = all(r["snap_agendamentos"] > 0 or r["prev_rows_filtered"] == 0 for r in partial)
    closed_ok = all(r["snap_vendas"] >= 0 for r in closed)
    print(f"\nResumo: partial_ag_ok={partial_ok} closed_ok={closed_ok}")
    return 0 if partial_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
