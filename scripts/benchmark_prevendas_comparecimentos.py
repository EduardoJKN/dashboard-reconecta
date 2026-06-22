#!/usr/bin/env python
"""Benchmark — Comparecimentos & Oportunidades (somente leitura).

Mede queries e transforms de `views/prevendas_comparecimentos.py`.

Modos:
  initial — cards, funil, quebra por classificação (sem ranking/detalhe)
  full    — tudo que a página carrega hoje (inclui ranking SDR)

Uso:
  python scripts/benchmark_prevendas_comparecimentos.py
  python scripts/benchmark_prevendas_comparecimentos.py --mode initial --scenario mes_atual --runs 3
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

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd  # noqa: E402

from src.db import run_sql_file  # noqa: E402
from src.prevendas_transforms import (  # noqa: E402
    prevendas_anotar_sdr,
    prevendas_classif_kpis,
    prevendas_overview_kpis,
    prevendas_ranking_sdr_oficiais,
)

HOJE = date(2026, 6, 22)

CLASSIF_SQL = {
    "v1": "prevendas_comparecimentos_classif.sql",
    "v2": "prevendas_comparecimentos_classif_v2.sql",
}

QUERIES_FULL: list[tuple[str, str, bool]] = [
    ("prevendas_comparecimentos_classif", "prevendas_comparecimentos_classif.sql", True),
    ("prevendas_overview_diario", "prevendas_overview_diario.sql", True),
    ("prevendas_por_sdr", "prevendas_por_sdr_v2.sql", True),
    ("prevendas_leads_detalhe_diario", "prevendas_leads_detalhe_diario.sql", True),
    ("prevendas_sdrs_oficiais", "prevendas_sdrs_oficiais.sql", False),
]

QUERIES_INITIAL: list[tuple[str, str, bool]] = [
    q for q in QUERIES_FULL
    if q[0] not in ("prevendas_leads_detalhe_diario", "prevendas_sdrs_oficiais")
]

SCENARIOS: dict[str, tuple[date, date]] = {}
SCENARIO_ALIASES = {"7_dias": "ultimos_7_dias", "60_dias": "ultimos_60_dias"}


def _init_scenarios(hoje: date | None = None) -> None:
    hoje = hoje or date.today()
    mes_ini = hoje.replace(day=1)
    if mes_ini.month == 1:
        mes_ant_ini = date(hoje.year - 1, 12, 1)
        mes_ant_fim = date(hoje.year - 1, 12, 31)
    else:
        mes_ant_ini = date(hoje.year, hoje.month - 1, 1)
        prox = mes_ant_ini.replace(day=28) + timedelta(days=4)
        mes_ant_fim = prox.replace(day=1) - timedelta(days=1)

    SCENARIOS.clear()
    SCENARIOS.update({
        "mes_atual": (mes_ini, hoje),
        "ultimos_7_dias": (hoje - timedelta(days=6), hoje),
        "mes_anterior": (mes_ant_ini, mes_ant_fim),
        "ultimos_60_dias": (hoje - timedelta(days=59), hoje),
        "periodo_sem_dados": (date(2018, 1, 1), date(2018, 1, 31)),
    })


def _params(data_ini: date, data_fim: date) -> dict:
    return {"data_ini": data_ini, "data_fim": data_fim}


def _run_sql(name: str, fname: str, *, dated: bool, data_ini: date, data_fim: date) -> dict:
    p = _params(data_ini, data_fim) if dated else None
    t0 = time.perf_counter()
    df = run_sql_file(fname, p)
    return {
        "name": name,
        "seconds": time.perf_counter() - t0,
        "rows": len(df),
        "cols": len(df.columns) if not df.empty else 0,
        "columns": list(df.columns),
        "df": df,
    }


def _run_transforms(
    *,
    mode: str,
    df_classif: pd.DataFrame,
    df_diario: pd.DataFrame,
    df_sdr: pd.DataFrame,
    df_detalhe: pd.DataFrame,
    df_sdrs_oficiais: pd.DataFrame,
) -> tuple[float, list[dict]]:
    steps: list[dict] = []

    def _step(label: str, fn):
        t0 = time.perf_counter()
        fn()
        steps.append({"name": label, "seconds": time.perf_counter() - t0})

    _step("prevendas_anotar_sdr", lambda: prevendas_anotar_sdr(df_sdr))
    _step("prevendas_overview_kpis (cards/funil)", lambda: prevendas_overview_kpis(df_diario))
    _step("prevendas_classif_kpis (quebra +12/-12)", lambda: prevendas_classif_kpis(df_classif))

    if mode == "full":
        df_sdr_ann = prevendas_anotar_sdr(df_sdr)
        _step(
            "prevendas_ranking_sdr_oficiais (ranking)",
            lambda: prevendas_ranking_sdr_oficiais(df_sdr_ann, df_sdrs_oficiais),
        )
        _ = df_detalhe  # carregado para render_top_sdr_interativo

    return sum(s["seconds"] for s in steps), steps


def _queries_for_mode(mode: str, classif_sql: str) -> list[tuple[str, str, bool]]:
    base = QUERIES_INITIAL if mode == "initial" else QUERIES_FULL
    return [
        (name, CLASSIF_SQL[classif_sql] if name == "prevendas_comparecimentos_classif" else fname, dated)
        for name, fname, dated in base
    ]


def benchmark_once(
    data_ini: date,
    data_fim: date,
    *,
    mode: str,
    classif_sql: str = "v1",
) -> dict:
    queries = _queries_for_mode(mode, classif_sql)
    sql_details: list[dict] = []
    dfs: dict[str, pd.DataFrame] = {}
    sql_total = 0.0

    for name, fname, dated in queries:
        detail = _run_sql(name, fname, dated=dated, data_ini=data_ini, data_fim=data_fim)
        sql_total += detail["seconds"]
        sql_details.append({k: v for k, v in detail.items() if k != "df"})
        dfs[name] = detail["df"]

    transform_total, transform_steps = _run_transforms(
        mode=mode,
        df_classif=dfs["prevendas_comparecimentos_classif"],
        df_diario=dfs["prevendas_overview_diario"],
        df_sdr=dfs["prevendas_por_sdr"],
        df_detalhe=dfs.get("prevendas_leads_detalhe_diario", pd.DataFrame()),
        df_sdrs_oficiais=dfs.get("prevendas_sdrs_oficiais", pd.DataFrame()),
    )

    slowest = max(sql_details, key=lambda d: d["seconds"])
    return {
        "mode": mode,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "sql_total": sql_total,
        "transform_total": transform_total,
        "prep_total": sql_total + transform_total,
        "sql_details": sql_details,
        "transform_steps": transform_steps,
        "slowest_sql": slowest,
        "n_queries": len(sql_details),
    }


def _guess_bottleneck(result: dict) -> str:
    sql = result["sql_total"]
    tx = result["transform_total"]
    s = result["slowest_sql"]
    if sql >= tx * 3:
        return (
            f"SQL ({sql:.2f}s, {sql/result['prep_total']*100:.0f}% do prep) — "
            f"pior: {s['name']} ({s['seconds']:.2f}s, {s['rows']} rows)"
        )
    return f"Misto SQL ({sql:.2f}s) + pandas ({tx:.2f}s)"


def _suggestions(result: dict) -> list[str]:
    tips: list[str] = []
    by = {d["name"]: d for d in result["sql_details"]}
    cl = by.get("prevendas_comparecimentos_classif", {})
    det = by.get("prevendas_leads_detalhe_diario", {})
    por_sdr = by.get("prevendas_por_sdr", {})

    if cl.get("seconds", 0) > 1.0:
        tips.append(
            "Gargalo principal: `prevendas_comparecimentos_classif.sql` — "
            "escaneia ext.leads + todos zoho_deals para classificação. "
            "Candidata a v2 com escopo de deals do período."
        )
    if det.get("seconds", 0) > 0.5 and result["mode"] == "full":
        tips.append(
            "Adiar `prevendas_leads_detalhe_diario` — só necessário para "
            "ranking/detalhe SDR (lazy-load ou checkbox)."
        )
    if por_sdr.get("seconds", 0) > 2.0:
        tips.append("Verificar se `prevendas_por_sdr_v2` está ativa no repositório.")
    elif por_sdr.get("seconds", 0) < 2.0:
        tips.append(
            f"`prevendas_por_sdr_v2` já leve ({por_sdr.get('seconds', 0):.2f}s) — "
            "não é mais o gargalo desta página."
        )
    if result["mode"] == "full" and len(result["sql_details"]) >= 5:
        tips.append(
            "CP1: modo initial (3 queries) cobre cards+funil+classificação; "
            "detalhe+sdrs_oficiais só para ranking."
        )
    return tips[:5]


def _print_scenario(label: str, result: dict) -> None:
    dias = (result["data_fim"] - result["data_ini"]).days + 1
    print(f"\n{'=' * 72}")
    print(f"CENÁRIO: {label} | modo: {result['mode']}")
    print(f"Período: {result['data_ini']} → {result['data_fim']} ({dias} dias)")
    print(f"Queries: {result['n_queries']}")
    print(f"{'=' * 72}")

    print("\n--- SQL (cache frio) ---")
    for d in sorted(result["sql_details"], key=lambda x: -x["seconds"]):
        cols = ", ".join(d.get("columns", [])[:6])
        extra = " …" if d.get("columns") and len(d["columns"]) > 6 else ""
        print(
            f"  {d['seconds']:7.3f}s  {d['rows']:6d} rows  {d['cols']:2d} cols  "
            f"{d['name']}"
        )
        if cols:
            print(f"           cols: {cols}{extra}")
    print(f"  {'—' * 8}  TOTAL SQL: {result['sql_total']:.3f}s")

    print("\n--- Transformações pandas ---")
    for s in sorted(result["transform_steps"], key=lambda x: -x["seconds"]):
        print(f"  {s['seconds']:7.3f}s  {s['name']}")
    print(f"  {'—' * 8}  TOTAL TRANSFORMS: {result['transform_total']:.3f}s")

    print("\n--- Resumo ---")
    print(f"  Preparação (SQL + transforms): {result['prep_total']:.3f}s")
    print(f"  Gargalo provável: {_guess_bottleneck(result)}")
    print("\n--- Sugestões ---")
    for i, tip in enumerate(_suggestions(result), 1):
        print(f"  {i}. {tip}")


def _stats(values: list[float]) -> dict:
    s = sorted(values)
    return {"p50": statistics.median(s), "mean": statistics.mean(s)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("initial", "full", "both"), default="both")
    parser.add_argument("--scenario", default="all")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--hoje", type=str, default=None)
    parser.add_argument(
        "--classif-sql",
        choices=("v1", "v2"),
        default="v2",
        help="Versão da query de classificação (default: v2, estado atual do repository)",
    )
    args = parser.parse_args()

    hoje = date.fromisoformat(args.hoje) if args.hoje else HOJE
    _init_scenarios(hoje)

    if args.scenario == "all":
        labels = list(SCENARIOS.keys())
    else:
        labels = [SCENARIO_ALIASES.get(args.scenario, args.scenario)]

    modes = ["initial", "full"] if args.mode == "both" else [args.mode]

    print("Benchmark — Comparecimentos & Oportunidades")
    print(
        f"Referência: {hoje.isoformat()} | runs: {args.runs} | "
        f"classif: {args.classif_sql} ({CLASSIF_SQL[args.classif_sql]})"
    )

    for mode in modes:
        print(f"\n{'#' * 72}")
        print(f"# MODO: {mode.upper()} ({len(QUERIES_INITIAL if mode == 'initial' else QUERIES_FULL)} queries)")
        print(f"{'#' * 72}")

        for label in labels:
            if label not in SCENARIOS:
                print(f"Cenário desconhecido: {label}")
                continue
            di, df = SCENARIOS[label]
            runs = [
                benchmark_once(di, df, mode=mode, classif_sql=args.classif_sql)
                for _ in range(args.runs)
            ]
            _print_scenario(label, runs[-1])
            if args.runs > 1:
                prep = [r["prep_total"] for r in runs]
                sql = [r["sql_total"] for r in runs]
                st = _stats(prep)
                ss = _stats(sql)
                print(
                    f"\n  [{args.runs} runs] prep p50={st['p50']:.3f}s "
                    f"mean={st['mean']:.3f}s | "
                    f"sql p50={ss['p50']:.3f}s mean={ss['mean']:.3f}s"
                )

    print(f"\n{'=' * 72}")
    print("FIM")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
