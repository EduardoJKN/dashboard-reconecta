#!/usr/bin/env python
"""Benchmark de consultas — Visão Geral Marketing.

Simula a sequência de queries do fluxo legado (7) vs otimizado (CP 2/3),
sem Streamlit. Mede cache frio e quente via `@st.cache_data` desabilitado
(direto em `run_sql_file`).

Uso:
  python scripts/benchmark_marketing_overview.py --mode legacy
  python scripts/benchmark_marketing_overview.py --mode optimized --scenario no_canal
  python scripts/benchmark_marketing_overview.py --compare
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import run_sql_file  # noqa: E402

DATA_INI = date(2026, 4, 1)
DATA_FIM = date(2026, 4, 30)


def _prev_range(data_ini: date, data_fim: date) -> tuple[date, date]:
    dias = (data_fim - data_ini).days + 1
    prev_fim = data_ini - timedelta(days=1)
    prev_ini = prev_fim - timedelta(days=dias - 1)
    return prev_ini, prev_fim


def _run(name: str, fname: str, p: dict) -> tuple[float, int]:
    t0 = time.perf_counter()
    df = run_sql_file(fname, p)
    return time.perf_counter() - t0, len(df)


def legacy_flow(include_overview: bool = True) -> tuple[float, int]:
    prev_ini, prev_fim = _prev_range(DATA_INI, DATA_FIM)
    p_cur = {"data_ini": DATA_INI, "data_fim": DATA_FIM}
    p_prev = {"data_ini": prev_ini, "data_fim": prev_fim}
    t0 = time.perf_counter()
    n = 0
    for fname in (
        "mkt_visao_geral_diario.sql",
        "mkt_visao_geral_periodo.sql",
        "mkt_visao_geral_kpis_canal.sql",
    ):
        _run(fname, fname, p_cur)
        n += 1
    if include_overview:
        _run("mkt_overview.sql", "mkt_overview.sql", p_cur)
        n += 1
    _run("mkt_visao_geral_diario.sql", "mkt_visao_geral_diario.sql", p_prev)
    n += 1
    _run("mkt_visao_geral_periodo.sql", "mkt_visao_geral_periodo.sql", p_prev)
    n += 1
    _run("mkt_visao_geral_kpis_canal.sql", "mkt_visao_geral_kpis_canal.sql", p_prev)
    n += 1
    return time.perf_counter() - t0, n


def optimized_flow(
    scenario: str,
    *,
    detail_open: bool = False,
) -> tuple[float, int, float]:
    """Retorna (total_s, n_queries, kpi_phase_s)."""
    prev_ini, prev_fim = _prev_range(DATA_INI, DATA_FIM)
    p_cur = {"data_ini": DATA_INI, "data_fim": DATA_FIM}
    p_prev = {"data_ini": prev_ini, "data_fim": prev_fim}
    t0 = time.perf_counter()
    kpi_t0 = time.perf_counter()
    n = 0

    if scenario == "canal":
        _run("mkt_visao_geral_kpis_canal.sql", "mkt_visao_geral_kpis_canal.sql", p_cur)
        n += 1
        _run("mkt_visao_geral_kpis_canal.sql", "mkt_visao_geral_kpis_canal.sql", p_prev)
        n += 1
    else:
        _run("mkt_visao_geral_periodo.sql", "mkt_visao_geral_periodo.sql", p_cur)
        n += 1
        _run("mkt_visao_geral_periodo.sql", "mkt_visao_geral_periodo.sql", p_prev)
        n += 1

    kpi_phase = time.perf_counter() - kpi_t0

    _run("mkt_visao_geral_diario.sql", "mkt_visao_geral_diario.sql", p_cur)
    n += 1

    if scenario != "canal":
        _run("mkt_visao_geral_kpis_canal.sql", "mkt_visao_geral_kpis_canal.sql", p_cur)
        n += 1

    if detail_open:
        _run("mkt_overview.sql", "mkt_overview.sql", p_cur)
        n += 1

    return time.perf_counter() - t0, n, kpi_phase


def _stats(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    return {
        "min": s[0],
        "p50": statistics.median(s),
        "p95": s[max(0, int(len(s) * 0.95) - 1)],
        "max": s[-1],
        "mean": statistics.mean(s),
    }


def _print_stats(label: str, values: list[float]) -> None:
    st = _stats(values)
    print(
        f"{label}: min={st['min']:.3f}s p50={st['p50']:.3f}s "
        f"p95={st['p95']:.3f}s max={st['max']:.3f}s mean={st['mean']:.3f}s"
    )


def regression_compare() -> None:
    """Compara KPIs numéricos entre fontes periodo e kpis_canal agregado."""
    import pandas as pd
    from src.marketing_transforms import visao_geral_kpis, visao_geral_kpis_canal

    p = {"data_ini": DATA_INI, "data_fim": DATA_FIM}
    df_period = run_sql_file("mkt_visao_geral_periodo.sql", p)
    df_canal = run_sql_file("mkt_visao_geral_kpis_canal.sql", p)
    df_diario = run_sql_file("mkt_visao_geral_diario.sql", p)

    k_period = visao_geral_kpis(df_period)
    k_canal_all = visao_geral_kpis_canal(df_canal, list(df_canal["canal"]))

    keys = [
        "investimento_total_geral", "leads_totais", "leads_qualificados",
        "leads_mais_12", "leads_menos_12", "leads_nao_atua",
        "vendas_novas_total_geral", "montante_total_geral", "receita_total_geral",
        "roas_total_geral", "cpl", "cpl_qualificado", "taxa_qualificacao",
    ]
    print("=== Regressão numérica (periodo vs kpis_canal todos canais) ===")
    for key in keys:
        a, b = k_period.get(key), k_canal_all.get(key)
        ok = abs(float(a) - float(b)) < 0.02 if a != b else a == b
        flag = "OK" if ok else "DIFF"
        print(f"  {key}: periodo={a} canal_agg={b} [{flag}]")

    print(f"  diario rows: {len(df_diario)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("legacy", "optimized", "compare"), default="compare")
    parser.add_argument("--scenario", choices=("no_canal", "canal"), default="no_canal")
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()

    if args.mode == "compare":
        print("=== LEGACY (7 queries, detalhe fechado) ===")
        totals = []
        kpis = []
        for _ in range(args.runs):
            t, n = legacy_flow(include_overview=True)
            totals.append(t)
            # legacy KPI phase ≈ diario + periodo + kpis_canal + overview + prev*3
            prev_ini, prev_fim = _prev_range(DATA_INI, DATA_FIM)
            p_cur = {"data_ini": DATA_INI, "data_fim": DATA_FIM}
            p_prev = {"data_ini": prev_ini, "data_fim": prev_fim}
            t_k = 0.0
            for fname in (
                "mkt_visao_geral_diario.sql",
                "mkt_visao_geral_periodo.sql",
                "mkt_visao_geral_kpis_canal.sql",
                "mkt_overview.sql",
            ):
                d, _ = _run(fname, fname, p_cur)
                t_k += d
            for fname in (
                "mkt_visao_geral_diario.sql",
                "mkt_visao_geral_periodo.sql",
                "mkt_visao_geral_kpis_canal.sql",
            ):
                d, _ = _run(fname, fname, p_prev)
                t_k += d
            kpis.append(t_k)
        _print_stats(f"Total ({args.runs} runs, {totals[0] and 7} queries)", totals)
        _print_stats("Fase até KPIs (aprox. legado)", kpis)

        print("\n=== OPTIMIZED no_canal (4 queries, detalhe fechado) ===")
        opt_tot, opt_kpi = [], []
        for _ in range(args.runs):
            t, n, kpi = optimized_flow("no_canal", detail_open=False)
            opt_tot.append(t)
            opt_kpi.append(kpi)
        _print_stats(f"Total ({args.runs} runs, 4 queries)", opt_tot)
        _print_stats("Fase até KPIs (periodo×2)", opt_kpi)

        print("\n=== OPTIMIZED canal (3 queries, detalhe fechado) ===")
        opt_c_tot, opt_c_kpi = [], []
        for _ in range(args.runs):
            t, n, kpi = optimized_flow("canal", detail_open=False)
            opt_c_tot.append(t)
            opt_c_kpi.append(kpi)
        _print_stats(f"Total ({args.runs} runs, 3 queries)", opt_c_tot)
        _print_stats("Fase até KPIs (kpis_canal×2)", opt_c_kpi)

        print("\n=== OPTIMIZED no_canal + detalhe (5 queries) ===")
        det_tot = []
        for _ in range(min(3, args.runs)):
            t, n, _ = optimized_flow("no_canal", detail_open=True)
            det_tot.append(t)
        _print_stats(f"Total ({len(det_tot)} runs, 5 queries)", det_tot)

        regression_compare()
        return

    runs = args.runs
    totals = []
    for _ in range(runs):
        if args.mode == "legacy":
            t, _ = legacy_flow(include_overview=not args.detail)
        else:
            t, _, _ = optimized_flow(args.scenario, detail_open=args.detail)
        totals.append(t)
    _print_stats(args.mode, totals)


if __name__ == "__main__":
    main()
