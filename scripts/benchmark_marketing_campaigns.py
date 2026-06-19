#!/usr/bin/env python
"""Benchmark de consultas — Campanhas Marketing.

Camadas de medicao (nao misturar):

  A) Cache frio da aplicacao — processo Python novo OU st.cache_data.clear();
     run_sql_file e executado; buffers PostgreSQL NAO controlados.
  B) Cache quente da aplicacao — 1a chamada preenche @st.cache_data;
     repeticoes nao executam SQL.
  C) Script SQL direto (--mode compare) — run_sql_file sequencial, sem
     @st.cache_data; mede latencia SQL bruta, nao a pagina Streamlit.

Uso:
  python scripts/benchmark_marketing_campaigns.py --layers
  python scripts/benchmark_marketing_campaigns.py --mode compare
  python scripts/benchmark_marketing_campaigns.py --mode legacy
  python scripts/benchmark_marketing_campaigns.py --mode optimized --scenario todos
"""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
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

from src.db import run_sql_file  # noqa: E402

DATA_INI = date(2026, 4, 1)
DATA_FIM = date(2026, 4, 30)
P = {"data_ini": DATA_INI, "data_fim": DATA_FIM}

# (nome logico, arquivo sql)
Q_CAMPANHAS = ("bi.vw_mkt_campanhas", "mkt_campanhas.sql")
Q_FUNIL_MORTO = ("bi.vw_mkt_funil", "mkt_funil.sql")
Q_LEADS_CANAL = (
    "bi_mkt.vw_visao_geral_canal_base (canal-diario)",
    "mkt_campanhas_leads_canal_diario.sql",
)
Q_LEADS_UTM = ("ext_reconecta.leads (por utm_campaign)", "mkt_campanhas_leads_por_utm.sql")
Q_CAMP_FUNIL = ("mkt_campanha_funil", "mkt_campanha_funil.sql")
Q_LEADS_VG = ("leads_visao_geral", "leads_visao_geral.sql")
Q_EXEC = ("dashboard_executivas", "dashboard_executivas.sql")
Q_INV = ("investimento_diario", "investimento_diario.sql")
Q_PREV = ("prevendas_overview_diario", "prevendas_overview_diario.sql")
Q_PAGINAS = (
    "ext_reconecta.leads (email-level pra Comparar campanhas)",
    "mkt_paginas_variantes.sql",
)
Q_COBERTURA = ("odam.mart_ad_funnel_daily (cobertura)", "mkt_campanha_cobertura.sql")


def _run(name: str, fname: str) -> tuple[float, int, int]:
    t0 = time.perf_counter()
    df = run_sql_file(fname, P)
    elapsed = time.perf_counter() - t0
    cols = len(df.columns) if not df.empty else 0
    return elapsed, len(df), cols


def _run_many(queries: list[tuple[str, str]]) -> tuple[float, int, list[dict]]:
    details: list[dict] = []
    total = 0.0
    for name, fname in queries:
        sec, rows, cols = _run(name, fname)
        total += sec
        details.append({"name": name, "seconds": sec, "rows": rows, "cols": cols})
    return total, len(queries), details


def legacy_full() -> tuple[float, int, float, float, list[dict]]:
    """Fluxo anterior: 11 queries sequenciais antes do fim da pagina."""
    queries = [
        Q_CAMPANHAS, Q_FUNIL_MORTO, Q_LEADS_CANAL, Q_LEADS_UTM,
        Q_CAMP_FUNIL, Q_LEADS_VG, Q_EXEC, Q_INV, Q_PREV,
        Q_PAGINAS, Q_COBERTURA,
    ]
    t0 = time.perf_counter()
    p1_end = 0.0
    sel_end = 0.0
    details: list[dict] = []
    for i, (name, fname) in enumerate(queries):
        sec, rows, cols = _run(name, fname)
        details.append({"name": name, "seconds": sec, "rows": rows, "cols": cols})
        if i == 3:
            p1_end = time.perf_counter() - t0
        if i == 8:
            sel_end = time.perf_counter() - t0
    return time.perf_counter() - t0, len(queries), p1_end, sel_end, details


def optimized_flow(scenario: str) -> tuple[float, int, float, float, list[dict]]:
    """Fluxo otimizado CP1-3."""
    queries: list[tuple[str, str]] = [Q_CAMPANHAS, Q_LEADS_CANAL]
    t0 = time.perf_counter()
    p1_end = 0.0
    sel_end = 0.0
    details: list[dict] = []

    for i, (name, fname) in enumerate(queries):
        sec, rows, cols = _run(name, fname)
        details.append({"name": name, "seconds": sec, "rows": rows, "cols": cols})
        if i == 1:
            p1_end = time.perf_counter() - t0

    sec, rows, cols = _run(*Q_CAMP_FUNIL)
    details.append({"name": Q_CAMP_FUNIL[0], "seconds": sec, "rows": rows, "cols": cols})
    sel_end = time.perf_counter() - t0

    if scenario == "todos":
        for q in (Q_LEADS_VG, Q_EXEC, Q_INV, Q_PREV):
            sec, rows, cols = _run(*q)
            details.append({"name": q[0], "seconds": sec, "rows": rows, "cols": cols})

    funil_end = time.perf_counter() - t0

    sec, rows, cols = _run(*Q_LEADS_UTM)
    details.append({"name": Q_LEADS_UTM[0], "seconds": sec, "rows": rows, "cols": cols})

    sec, rows, cols = _run(*Q_PAGINAS)
    details.append({"name": Q_PAGINAS[0], "seconds": sec, "rows": rows, "cols": cols})

    return time.perf_counter() - t0, len(details), p1_end, sel_end, funil_end, details


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


def _print_detail(details: list[dict]) -> None:
    for d in details:
        print(
            f"  {d['name']}: {d['seconds']:.3f}s "
            f"({d['rows']} rows, {d['cols']} cols)"
        )


def _print_layer_stats(
    label: str,
    values: list[float],
    sql_counts: list[int],
    *,
    show_p95: bool = True,
) -> None:
    st = _stats(values)
    sc = _stats([float(x) for x in sql_counts])
    line = (
        f"{label}: sql_count p50={sc['p50']:.0f} min={sc['min']:.0f} max={sc['max']:.0f} | "
        f"time p50={st['p50']:.3f}s min={st['min']:.3f}s max={st['max']:.3f}s"
    )
    if show_p95 and len(values) >= 5:
        line += f" p95={st['p95']:.3f}s"
    print(line)


def _run_app_flow_cached(
    scenario: str,
    *,
    clear_cache: bool,
) -> tuple[float, float, float, float, float, int]:
    """Simula fluxo otimizado via funcoes @st.cache_data (como a pagina)."""
    import streamlit as st
    import src.marketing_queries as mq
    import src.repositories as repos
    from src.db import run_sql_file as db_run_sql_file
    from src.marketing_queries import (
        get_mkt_campanha_funil,
        get_mkt_campanhas,
        get_mkt_campanhas_leads_canal_diario,
        get_mkt_campanhas_leads_por_utm,
        get_mkt_paginas_variantes,
    )
    from src.repositories import (
        get_executivas,
        get_investimento_diario,
        get_leads_visao_geral,
        get_prevendas_overview_diario,
    )

    sql_count = 0
    real_mq = mq.run_sql_file
    real_repos = repos.run_sql_file

    def _counting_run(filename: str, params=None):
        nonlocal sql_count
        sql_count += 1
        return db_run_sql_file(filename, params)

    mq.run_sql_file = _counting_run  # type: ignore[assignment]
    repos.run_sql_file = _counting_run  # type: ignore[assignment]
    if clear_cache:
        st.cache_data.clear()

    t0 = time.perf_counter()
    get_mkt_campanhas(DATA_INI, DATA_FIM)
    get_mkt_campanhas_leads_canal_diario(DATA_INI, DATA_FIM)
    t_p1 = time.perf_counter() - t0

    get_mkt_campanha_funil(DATA_INI, DATA_FIM)
    t_sel = time.perf_counter() - t0

    if scenario == "todos":
        get_leads_visao_geral(DATA_INI, DATA_FIM)
        get_executivas(DATA_INI, DATA_FIM)
        get_investimento_diario(DATA_INI, DATA_FIM)
        get_prevendas_overview_diario(DATA_INI, DATA_FIM)
    t_funil = time.perf_counter() - t0

    get_mkt_campanhas_leads_por_utm(DATA_INI, DATA_FIM)
    get_mkt_paginas_variantes(DATA_INI, DATA_FIM)
    t_total = time.perf_counter() - t0

    mq.run_sql_file = real_mq  # type: ignore[assignment]
    repos.run_sql_file = real_repos  # type: ignore[assignment]
    return t_p1, t_sel, t_funil, t_total, t_total, sql_count


def _run_layers(cold_runs: int = 4, warm_runs: int = 10) -> None:
    print("\n=== A) CACHE FRIO DA APLICACAO (@st.cache_data limpo) ===")
    print("Metodo: st.cache_data.clear() + funcoes get_mkt_* / get_* oficiais")
    print("Nota: buffers internos do PostgreSQL NAO foram controlados")
    print(f"Periodo: {DATA_INI.isoformat()} -> {DATA_FIM.isoformat()}")

    for scenario, label, expected_sql in (
        ("todos", "__todos__ (pagina completa lazy fechados)", 9),
        ("campanha", "campanha individual (sem oficiais)", 5),
    ):
        times_p1, times_sel, times_funil, times_tot, sqls = [], [], [], [], []
        for _ in range(cold_runs):
            p1, sel, fun, tot, _, n_sql = _run_app_flow_cached(
                scenario, clear_cache=True,
            )
            times_p1.append(p1)
            times_sel.append(sel)
            times_funil.append(fun)
            times_tot.append(tot)
            sqls.append(n_sql)
        print(f"\n--- {label} (esperado {expected_sql} SQL/exec) ---")
        _print_layer_stats("Financeiro/Volume", times_p1, sqls, show_p95=False)
        _print_layer_stats("Ate seletor", times_sel, sqls, show_p95=False)
        _print_layer_stats("Ate cards funil", times_funil, sqls, show_p95=False)
        _print_layer_stats("Total pagina", times_tot, sqls, show_p95=False)
        print(f"  SQL/exec: min={min(sqls)} p50={statistics.median(sqls):.0f} max={max(sqls)}")

    print("\n=== B) CACHE QUENTE DA APLICACAO (2a+ chamada no mesmo processo) ===")
    import streamlit as st
    import src.marketing_queries as mq
    from src.db import run_sql_file as db_run_sql_file
    from src.marketing_queries import get_mkt_campanhas

    st.cache_data.clear()
    sql_warm: list[int] = []
    times_warm: list[float] = []
    real_mq = mq.run_sql_file

    def _counting_run(filename: str, params=None):
        sql_warm.append(1)
        return db_run_sql_file(filename, params)

    mq.run_sql_file = _counting_run  # type: ignore[assignment]
    get_mkt_campanhas(DATA_INI, DATA_FIM)  # priming
    priming_sql = len(sql_warm)
    sql_warm.clear()

    for _ in range(warm_runs):
        t0 = time.perf_counter()
        get_mkt_campanhas(DATA_INI, DATA_FIM)
        times_warm.append(time.perf_counter() - t0)

    mq.run_sql_file = real_mq  # type: ignore[assignment]
    print(f"Priming SQL (1a chamada get_mkt_campanhas): {priming_sql}")
    print(f"Repeticoes quentes (n={warm_runs}): sql_total={len(sql_warm)}")
    _print_layer_stats("get_mkt_campanhas repetido", times_warm, [0] * len(times_warm))

    print("\n=== C) PAGINA STREAMLIT (?debug_perf=1) ===")
    print("Nao medido neste script. Use a UI com ?debug_perf=1 e painel")
    print("'Diagnostico de performance (marketing_campaigns)' no fim da pagina.")


def _run_subprocess_cold_once(scenario: str) -> dict:
    code = f"""
import sys, time, json
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
st.cache_data.clear()
from scripts.benchmark_marketing_campaigns import _run_app_flow_cached
p1, sel, fun, tot, _, n = _run_app_flow_cached({scenario!r}, clear_cache=True)
print(json.dumps({{"p1": p1, "sel": sel, "fun": fun, "tot": tot, "sql": n}}))
"""
    out = subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        stderr=subprocess.DEVNULL,
    )
    import json
    return json.loads(out.decode().strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--layers",
        action="store_true",
        help="Mede cache frio/quente da aplicacao (@st.cache_data)",
    )
    parser.add_argument(
        "--mode",
        choices=("legacy", "optimized", "compare"),
        default="compare",
    )
    parser.add_argument(
        "--scenario",
        choices=("todos", "campanha"),
        default="todos",
        help="todos=+4 oficiais; campanha=sem oficiais",
    )
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()

    period = f"{DATA_INI.isoformat()} -> {DATA_FIM.isoformat()}"
    print(f"Periodo: {period}")

    if args.layers:
        _run_layers(cold_runs=min(5, args.runs), warm_runs=10)
        return

    if args.mode == "compare":
        print("\n=== SQL DIRETO (run_sql_file sequencial, SEM @st.cache_data) ===")
        print("Nota: buffers internos do PostgreSQL NAO foram controlados")
        print("\n=== LEGACY (11 queries, cobertura eager) ===")
        leg_tot, leg_p1, leg_sel = [], [], []
        leg_details: list[dict] = []
        for _ in range(args.runs):
            t, n, p1, sel, det = legacy_full()
            leg_tot.append(t)
            leg_p1.append(p1)
            leg_sel.append(sel)
            leg_details = det
        _print_stats(f"Total ({args.runs} runs, 11 queries)", leg_tot)
        _print_stats("Ate Financeiro/Volume (4 queries legado)", leg_p1)
        _print_stats("Ate seletor (9 queries c/ oficiais)", leg_sel)
        leg_fun = []
        for _ in range(args.runs):
            _, _, _, sel, _ = legacy_full()
            leg_fun.append(sel)
        _print_stats("Ate cards funil __todos__ (9 queries SQL)", leg_fun)
        print("Detalhe (1 run):")
        _print_detail(leg_details)

        print("\n=== OPTIMIZED todos (7 queries, sem cobertura/auditoria) ===")
        opt_tot, opt_p1, opt_sel = [], [], []
        opt_details: list[dict] = []
        for _ in range(args.runs):
            t, n, p1, sel, _, det = optimized_flow("todos")
            opt_tot.append(t)
            opt_p1.append(p1)
            opt_sel.append(sel)
            opt_details = det
        opt_fun = []
        for _ in range(args.runs):
            _, _, _, _, fun, _ = optimized_flow("todos")
            opt_fun.append(fun)
        _print_stats(f"Total ({args.runs} runs, 9 queries pagina)", opt_tot)
        _print_stats("Ate Financeiro/Volume (2 queries)", opt_p1)
        _print_stats("Ate seletor (3 queries, sem oficiais)", opt_sel)
        _print_stats("Ate cards funil __todos__ (7 queries SQL)", opt_fun)
        print("Detalhe (1 run):")
        _print_detail(opt_details)

        print("\n=== OPTIMIZED campanha individual (3 queries funil path) ===")
        camp_tot, camp_p1, camp_sel = [], [], []
        camp_details: list[dict] = []
        for _ in range(args.runs):
            t, n, p1, sel, _, det = optimized_flow("campanha")
            t_funil = p1 + (sel - p1)
            camp_tot.append(t_funil)
            camp_p1.append(p1)
            camp_sel.append(sel)
            camp_details = det[:3]
        _print_stats(f"Ate funil cards ({args.runs} runs, 3 queries)", camp_tot)
        _print_stats("Ate Financeiro/Volume", camp_p1)
        _print_stats("Ate seletor", camp_sel)
        print("Detalhe funil path (1 run):")
        _print_detail(camp_details)
        return

    runs = args.runs
    totals = []
    for _ in range(runs):
        if args.mode == "legacy":
            t, _, _, _, _ = legacy_full()
        else:
            t, _, _, _, _ = optimized_flow(args.scenario)
        totals.append(t)
    _print_stats(args.mode, totals)


if __name__ == "__main__":
    main()
