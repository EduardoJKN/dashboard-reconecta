#!/usr/bin/env python
"""Benchmark de consultas — Criativos Marketing.

Camadas de medicao (nao misturar):

  A) Cache frio da aplicacao — processo Python novo OU st.cache_data.clear();
     run_sql_file e executado; buffers PostgreSQL NAO controlados.
  B) Cache quente da aplicacao — 1a chamada preenche @st.cache_data;
     repeticoes nao executam SQL.
  C) Script SQL direto — run_sql_file sequencial, sem @st.cache_data;
     mede latencia SQL bruta, nao a pagina Streamlit.

Uso:
  python scripts/benchmark_marketing_creatives.py --layers
  python scripts/benchmark_marketing_creatives.py --mode compare
  python scripts/benchmark_marketing_creatives.py --mode legacy
  python scripts/benchmark_marketing_creatives.py --mode optimized --scenario todos
"""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from datetime import date, timedelta
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

PREV_FIM = DATA_INI - timedelta(days=1)
PREV_INI = PREV_FIM - timedelta(days=(DATA_FIM - DATA_INI).days)
P_PREV = {"data_ini": PREV_INI, "data_fim": PREV_FIM}

Q_CRIATIVOS = ("bi.vw_mkt_criativos", "mkt_criativos.sql")
Q_CRIATIVOS_PREV = ("bi.vw_mkt_criativos (periodo anterior)", "mkt_criativos.sql")
Q_RESULTADOS = ("odam.mart_ad_funnel_daily (criativos)", "mkt_criativos_resultados.sql")
Q_RESULTADOS_PREV = (
    "odam.mart_ad_funnel_daily (criativos, periodo anterior)",
    "mkt_criativos_resultados.sql",
)
Q_TOP_NOME = ("mkt_top_criativos_por_nome", "mkt_top_criativos_por_nome.sql")
Q_FUNIL = ("mkt_criativo_funil", "mkt_criativo_funil.sql")
Q_LEADS_VG = ("leads_visao_geral", "leads_visao_geral.sql")
Q_EXEC = ("dashboard_executivas", "dashboard_executivas.sql")
Q_VENDAS_OFICIAIS = (
    "mkt_campanhas_vendas_oficiais",
    "mkt_campanhas_vendas_oficiais.sql",
)
Q_INV = ("investimento_diario", "investimento_diario.sql")
Q_PREV = ("prevendas_overview_diario", "prevendas_overview_diario.sql")
Q_PAGINAS = (
    "ext_reconecta.leads (email-level pra Comparar criativos)",
    "mkt_paginas_variantes.sql",
)
Q_FDW = ("fdw_reconecta.anuncios (audit)", "mkt_criativos_anuncios_fdw.sql")


def _run(name: str, fname: str, params: dict | None = None) -> tuple[float, int, int]:
    t0 = time.perf_counter()
    df = run_sql_file(fname, params or P)
    elapsed = time.perf_counter() - t0
    cols = len(df.columns) if not df.empty else 0
    return elapsed, len(df), cols


def _stats(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    out = {
        "min": s[0],
        "p50": statistics.median(s),
        "max": s[-1],
        "mean": statistics.mean(s),
    }
    if len(s) >= 5:
        out["p95"] = s[max(0, int(len(s) * 0.95) - 1)]
    return out


def _print_stats(label: str, values: list[float], *, show_p95: bool = True) -> None:
    st = _stats(values)
    line = (
        f"{label}: min={st['min']:.3f}s p50={st['p50']:.3f}s "
        f"max={st['max']:.3f}s mean={st['mean']:.3f}s"
    )
    if show_p95 and "p95" in st:
        line += f" p95={st['p95']:.3f}s"
    print(line)


def _print_detail(details: list[dict]) -> None:
    for d in details:
        print(
            f"  {d['name']}: {d['seconds']:.3f}s "
            f"({d['rows']} rows, {d['cols']} cols)"
        )


def legacy_full() -> tuple[float, int, float, float, float, list[dict]]:
    """Fluxo anterior: top_nome + oficiais eager + fdw eager."""
    queries: list[tuple[str, str, dict | None]] = [
        (Q_CRIATIVOS[0], Q_CRIATIVOS[1], P),
        (Q_CRIATIVOS_PREV[0], Q_CRIATIVOS_PREV[1], P_PREV),
        (Q_RESULTADOS[0], Q_RESULTADOS[1], P),
        (Q_RESULTADOS_PREV[0], Q_RESULTADOS_PREV[1], P_PREV),
        (Q_TOP_NOME[0], Q_TOP_NOME[1], P),
        (Q_FUNIL[0], Q_FUNIL[1], P),
        (Q_LEADS_VG[0], Q_LEADS_VG[1], P),
        (Q_EXEC[0], Q_EXEC[1], P),
        (Q_INV[0], Q_INV[1], P),
        (Q_PREV[0], Q_PREV[1], P),
        (Q_PAGINAS[0], Q_PAGINAS[1], P),
        (Q_FDW[0], Q_FDW[1], P),
    ]
    t0 = time.perf_counter()
    p1_end = 0.0
    sel_end = 0.0
    funil_end = 0.0
    details: list[dict] = []
    for i, (name, fname, params) in enumerate(queries):
        sec, rows, cols = _run(name, fname, params)
        details.append({"name": name, "seconds": sec, "rows": rows, "cols": cols})
        if i == 3:
            p1_end = time.perf_counter() - t0
        if i == 5:
            sel_end = time.perf_counter() - t0
        if i == 9:
            funil_end = time.perf_counter() - t0
    return time.perf_counter() - t0, len(queries), p1_end, sel_end, funil_end, details


def optimized_flow(scenario: str) -> tuple[float, int, float, float, float, list[dict], str]:
    """Fluxo otimizado CP1-4 (auditorias fechadas)."""
    details: list[dict] = []
    t0 = time.perf_counter()
    p1_end = 0.0
    sel_end = 0.0
    funil_end = 0.0

    p1_queries = [
        (Q_CRIATIVOS[0], Q_CRIATIVOS[1], P),
        (Q_CRIATIVOS_PREV[0], Q_CRIATIVOS_PREV[1], P_PREV),
        (Q_RESULTADOS[0], Q_RESULTADOS[1], P),
        (Q_RESULTADOS_PREV[0], Q_RESULTADOS_PREV[1], P_PREV),
    ]
    for i, (name, fname, params) in enumerate(p1_queries):
        sec, rows, cols = _run(name, fname, params)
        details.append({"name": name, "seconds": sec, "rows": rows, "cols": cols})
        if i == 3:
            p1_end = time.perf_counter() - t0

    sec, rows, cols = _run(Q_FUNIL[0], Q_FUNIL[1], P)
    details.append({"name": Q_FUNIL[0], "seconds": sec, "rows": rows, "cols": cols})
    sel_end = time.perf_counter() - t0

    if scenario == "todos":
        for q in (Q_LEADS_VG, Q_VENDAS_OFICIAIS, Q_INV, Q_PREV):
            sec, rows, cols = _run(q[0], q[1], P)
            details.append({"name": q[0], "seconds": sec, "rows": rows, "cols": cols})
    funil_end = time.perf_counter() - t0

    sec, rows, cols = _run(Q_TOP_NOME[0], Q_TOP_NOME[1], P)
    details.append({"name": Q_TOP_NOME[0], "seconds": sec, "rows": rows, "cols": cols})
    top12_sql_note = (
        f"SQL direto top_nome neste run: {sec:.3f}s"
        if sec > 0.05
        else "top_nome omitido ou cache PG quente neste run"
    )

    sec, rows, cols = _run(Q_PAGINAS[0], Q_PAGINAS[1], P)
    details.append({"name": Q_PAGINAS[0], "seconds": sec, "rows": rows, "cols": cols})

    return time.perf_counter() - t0, len(details), p1_end, sel_end, funil_end, details, top12_sql_note


def _run_app_flow_cached(
    scenario: str,
    *,
    clear_cache: bool,
) -> tuple[float, float, float, float, int]:
    """Simula fluxo otimizado via funcoes @st.cache_data."""
    import streamlit as st
    import src.marketing_queries as mq
    import src.repositories as repos
    from src.db import run_sql_file as db_run_sql_file
    from src.marketing_queries import (
        get_mkt_criativo_funil,
        get_mkt_criativos,
        get_mkt_criativos_resultados,
        get_mkt_paginas_variantes,
        get_mkt_top_criativos_por_nome,
    )
    from src.repositories import (
        get_investimento_diario,
        get_leads_visao_geral,
        get_mkt_campanhas_vendas_oficiais,
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
    get_mkt_criativos(DATA_INI, DATA_FIM)
    get_mkt_criativos(PREV_INI, PREV_FIM)
    get_mkt_criativos_resultados(DATA_INI, DATA_FIM)
    get_mkt_criativos_resultados(PREV_INI, PREV_FIM)
    t_p1 = time.perf_counter() - t0

    get_mkt_criativo_funil(DATA_INI, DATA_FIM)
    t_sel = time.perf_counter() - t0

    if scenario == "todos":
        get_leads_visao_geral(DATA_INI, DATA_FIM)
        get_mkt_campanhas_vendas_oficiais(DATA_INI, DATA_FIM)
        get_investimento_diario(DATA_INI, DATA_FIM)
        get_prevendas_overview_diario(DATA_INI, DATA_FIM)
    t_funil = time.perf_counter() - t0

    get_mkt_top_criativos_por_nome(DATA_INI, DATA_FIM)
    get_mkt_paginas_variantes(DATA_INI, DATA_FIM)
    t_total = time.perf_counter() - t0

    mq.run_sql_file = real_mq  # type: ignore[assignment]
    repos.run_sql_file = real_repos  # type: ignore[assignment]
    return t_p1, t_sel, t_funil, t_total, sql_count


def _benchmark_top_nome_heavy() -> None:
    print("\n=== QUERY PESADA: mkt_top_criativos_por_nome ===")
    print("Aquecimento: 1 execucao nao contabilizada")
    print("Nota: buffers internos do PostgreSQL NAO controlados")
    _run(Q_TOP_NOME[0], Q_TOP_NOME[1], P)

    cold_times: list[float] = []
    for i in range(3):
        t0 = time.perf_counter()
        sec, rows, cols = _run(Q_TOP_NOME[0], Q_TOP_NOME[1], P)
        cold_times.append(time.perf_counter() - t0)
        print(f"  cold #{i + 1}: {sec:.3f}s ({rows} rows, {cols} cols)")

    print("Cache vazio (max 3 amostras) — sem P95:")
    _print_stats("top_nome SQL direto", cold_times, show_p95=False)

    import streamlit as st
    import src.marketing_queries as mq
    from src.db import run_sql_file as db_run_sql_file
    from src.marketing_queries import get_mkt_top_criativos_por_nome

    st.cache_data.clear()
    sql_warm: list[int] = []
    warm_times: list[float] = []
    real_mq = mq.run_sql_file

    def _counting_run(filename: str, params=None):
        sql_warm.append(1)
        return db_run_sql_file(filename, params)

    mq.run_sql_file = _counting_run  # type: ignore[assignment]
    get_mkt_top_criativos_por_nome(DATA_INI, DATA_FIM)
    sql_warm.clear()

    for _ in range(10):
        t0 = time.perf_counter()
        get_mkt_top_criativos_por_nome(DATA_INI, DATA_FIM)
        warm_times.append(time.perf_counter() - t0)

    mq.run_sql_file = real_mq  # type: ignore[assignment]
    print(f"Cache quente (@st.cache_data, n=10): sql_total={len(sql_warm)}")
    _print_stats("top_nome cache quente", warm_times)


def _run_layers() -> None:
    print("\n=== A) CACHE FRIO DA APLICACAO (@st.cache_data limpo) ===")
    print(f"Periodo: {DATA_INI.isoformat()} -> {DATA_FIM.isoformat()}")

    for scenario, label, expected_sql in (
        ("todos", "__todos__ (sem auditorias)", 10),
        ("criativo", "criativo individual (sem oficiais)", 6),
    ):
        times_p1, times_sel, times_funil, times_tot, sqls = [], [], [], [], []
        for _ in range(3):
            p1, sel, fun, tot, n_sql = _run_app_flow_cached(
                scenario, clear_cache=True,
            )
            times_p1.append(p1)
            times_sel.append(sel)
            times_funil.append(fun)
            times_tot.append(tot)
            sqls.append(n_sql)
        print(f"\n--- {label} (esperado ~{expected_sql} SQL/exec) ---")
        _print_stats("Performance Meta", times_p1, show_p95=False)
        _print_stats("Ate seletor", times_sel, show_p95=False)
        _print_stats("Ate cards funil", times_funil, show_p95=False)
        _print_stats("Total pagina (sem UI)", times_tot, show_p95=False)
        print(f"  SQL/exec: min={min(sqls)} p50={statistics.median(sqls):.0f} max={max(sqls)}")

    print("\n=== B) COMPARACAO SQL DIRETO (1 execucao cada fluxo) ===")
    leg_t, leg_n, leg_p1, leg_sel, leg_fun, leg_d = legacy_full()
    opt_t, opt_n, opt_p1, opt_sel, opt_fun, opt_d, top_note = optimized_flow("todos")
    print(f"\nLegacy: {leg_n} queries, total={leg_t:.3f}s")
    print(f"  ate Performance Meta: {leg_p1:.3f}s")
    print(f"  ate seletor (com top_nome antes!): {leg_sel:.3f}s")
    print(f"  ate funil+oficiais: {leg_fun:.3f}s")
    _print_detail(leg_d)

    print(f"\nOtimizado: {opt_n} queries, total={opt_t:.3f}s")
    print(f"  ate Performance Meta: {opt_p1:.3f}s")
    print(f"  ate seletor: {opt_sel:.3f}s")
    print(f"  ate funil+oficiais: {opt_fun:.3f}s")
    print(f"  {top_note}")
    print(
        "  Referencia SQL frio top_nome: ~133s (benchmark --layers secao pesada)"
    )
    _print_detail(opt_d)

    print("\n=== C) PAGINA STREAMLIT (?debug_perf=1) ===")
    print("Nao medido neste script. Use a UI com ?debug_perf=1.")

    _benchmark_top_nome_heavy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("legacy", "optimized", "compare"),
        default="compare",
    )
    parser.add_argument(
        "--scenario",
        choices=("todos", "criativo"),
        default="todos",
    )
    args = parser.parse_args()

    if args.layers:
        _run_layers()
        return

    if args.mode in ("legacy", "compare"):
        leg_t, leg_n, leg_p1, leg_sel, leg_fun, leg_d = legacy_full()
        print(f"LEGACY: {leg_n} queries total={leg_t:.3f}s")
        print(f"  Performance Meta: {leg_p1:.3f}s")
        print(f"  Seletor: {leg_sel:.3f}s")
        print(f"  Funil+oficiais: {leg_fun:.3f}s")
        _print_detail(leg_d)

    if args.mode in ("optimized", "compare"):
        opt_t, opt_n, opt_p1, opt_sel, opt_fun, opt_d, top_note = optimized_flow(args.scenario)
        print(f"OTIMIZADO ({args.scenario}): {opt_n} queries total={opt_t:.3f}s")
        print(f"  Performance Meta: {opt_p1:.3f}s")
        print(f"  Seletor: {opt_sel:.3f}s")
        print(f"  Funil+oficiais: {opt_fun:.3f}s")
        print(f"  {top_note}")
        _print_detail(opt_d)


if __name__ == "__main__":
    main()
