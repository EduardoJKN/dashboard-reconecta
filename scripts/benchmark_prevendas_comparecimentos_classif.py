#!/usr/bin/env python
"""Benchmark e equivalência — prevendas_comparecimentos_classif v1 vs v2.

Somente leitura.

Uso:
  python scripts/benchmark_prevendas_comparecimentos_classif.py
  python scripts/benchmark_prevendas_comparecimentos_classif.py --scenario mes_atual --runs 3
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.db import run_sql_file  # noqa: E402

HOJE = date(2026, 6, 22)
SQL_V1 = "prevendas_comparecimentos_classif.sql"
SQL_V2 = "prevendas_comparecimentos_classif_v2.sql"

SCENARIOS: dict[str, tuple[date, date]] = {
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "mes_anterior": (date(2026, 5, 1), date(2026, 5, 31)),
    "ultimos_60_dias": (HOJE - timedelta(days=59), HOJE),
    "periodo_sem_dados": (date(2018, 1, 1), date(2018, 1, 31)),
    "futuro_sem_dados": (date(2030, 1, 1), date(2030, 1, 31)),
}

SCENARIO_ALIASES = {"7_dias": "ultimos_7_dias", "60_dias": "ultimos_60_dias"}

KEY_COLS = ["sdr", "fonte_sdr", "bucket"]
INT_COLS = ["leads_com_agend", "leads_com_compar", "leads_com_venda_nova"]
METRIC_COLS = INT_COLS


def _params(data_ini: date, data_fim: date) -> dict:
    return {"data_ini": data_ini, "data_fim": data_fim}


def _run(fname: str, p: dict) -> tuple[float, pd.DataFrame]:
    t0 = time.perf_counter()
    df = run_sql_file(fname, p)
    return time.perf_counter() - t0, df


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=KEY_COLS + METRIC_COLS)
    out = df.copy()
    for c in KEY_COLS:
        if c in out.columns:
            out[c] = out[c].fillna("").astype(str).str.strip()
    for c in INT_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(np.int64)
    sort_cols = [c for c in KEY_COLS if c in out.columns]
    return out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


def _compare_equiv(df1: pd.DataFrame, df2: pd.DataFrame) -> dict:
    n1 = _normalize_df(df1)
    n2 = _normalize_df(df2)

    result: dict = {
        "pass": True,
        "cols_v1": list(df1.columns) if df1 is not None else [],
        "cols_v2": list(df2.columns) if df2 is not None else [],
        "rows_v1": len(n1),
        "rows_v2": len(n2),
        "issues": [],
        "divergences": pd.DataFrame(),
        "totals_v1": {},
        "totals_v2": {},
    }

    if list(n1.columns) != list(n2.columns):
        result["pass"] = False
        result["issues"].append(
            f"Colunas diferem: v1={list(n1.columns)} v2={list(n2.columns)}"
        )

    if len(n1) != len(n2):
        result["pass"] = False
        result["issues"].append(f"Linhas: v1={len(n1)} v2={len(n2)}")

    keys1 = set(zip(n1["sdr"], n1["fonte_sdr"], n1["bucket"])) if len(n1) else set()
    keys2 = set(zip(n2["sdr"], n2["fonte_sdr"], n2["bucket"])) if len(n2) else set()
    only1 = keys1 - keys2
    only2 = keys2 - keys1
    if only1 or only2:
        result["pass"] = False
        result["issues"].append(
            f"Chaves só em v1: {len(only1)} | só em v2: {len(only2)}"
        )
        if only1:
            result["issues"].append(f"  Ex. v1: {list(only1)[:5]}")
        if only2:
            result["issues"].append(f"  Ex. v2: {list(only2)[:5]}")

    merged = n1.merge(
        n2, on=KEY_COLS, how="outer", suffixes=("_v1", "_v2"), indicator=True,
    )
    if (merged["_merge"] != "both").any():
        result["pass"] = False
        orphan = merged[merged["_merge"] != "both"]
        result["issues"].append(f"Merge outer com {len(orphan)} linha(s) órfã(s)")

    diffs: list[dict] = []
    for col in METRIC_COLS:
        c1, c2 = f"{col}_v1", f"{col}_v2"
        if c1 not in merged.columns or c2 not in merged.columns:
            continue
        v1s = merged[c1].fillna(0)
        v2s = merged[c2].fillna(0)
        result["totals_v1"][col] = int(v1s.sum())
        result["totals_v2"][col] = int(v2s.sum())

        delta = (v1s.astype(np.int64) - v2s.astype(np.int64)).abs()
        bad = merged[delta > 0]
        if not bad.empty:
            result["pass"] = False
            for _, row in bad.head(20).iterrows():
                diffs.append({
                    "sdr": row["sdr"],
                    "fonte_sdr": row["fonte_sdr"],
                    "bucket": row["bucket"],
                    "metrica": col,
                    "v1": int(row[c1]),
                    "v2": int(row[c2]),
                    "delta": int(row[c1]) - int(row[c2]),
                })

    if diffs:
        result["divergences"] = pd.DataFrame(diffs).head(20)

    return result


def _stats(values: list[float]) -> dict:
    s = sorted(values)
    return {
        "p50": statistics.median(s),
        "mean": statistics.mean(s),
        "min": s[0],
        "max": s[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="all", help="Nome do cenário ou 'all'")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    if args.scenario == "all":
        labels = list(SCENARIOS.keys())
    else:
        labels = [SCENARIO_ALIASES.get(args.scenario, args.scenario)]

    print("Benchmark + equivalência — prevendas_comparecimentos_classif v1 vs v2")
    print(f"Referência: {HOJE.isoformat()} | runs: {args.runs}")
    print()

    all_pass = True
    summary_rows: list[dict] = []

    for label in labels:
        if label not in SCENARIOS:
            print(f"Cenário desconhecido: {label}")
            continue
        di, df = SCENARIOS[label]
        p = _params(di, df)

        times_v1: list[float] = []
        times_v2: list[float] = []
        df_v1 = df_v2 = None

        for _ in range(args.runs):
            t1, d1 = _run(SQL_V1, p)
            t2, d2 = _run(SQL_V2, p)
            times_v1.append(t1)
            times_v2.append(t2)
            df_v1, df_v2 = d1, d2

        st1 = _stats(times_v1)
        st2 = _stats(times_v2)
        gain_abs = st1["p50"] - st2["p50"]
        gain_pct = (gain_abs / st1["p50"] * 100) if st1["p50"] else 0.0

        equiv = _compare_equiv(df_v1, df_v2)
        status = "PASS" if equiv["pass"] else "FAIL"
        all_pass = all_pass and equiv["pass"]

        print("=" * 72)
        print(f"CENÁRIO: {label} ({di} → {df})")
        print("=" * 72)
        print(
            f"Tempo v1: p50={st1['p50']:.3f}s mean={st1['mean']:.3f}s "
            f"(min={st1['min']:.3f}s max={st1['max']:.3f}s)"
        )
        print(
            f"Tempo v2: p50={st2['p50']:.3f}s mean={st2['mean']:.3f}s "
            f"(min={st2['min']:.3f}s max={st2['max']:.3f}s)"
        )
        print(
            f"Ganho: {gain_abs:.3f}s ({gain_pct:.1f}%) | "
            f"Linhas v1={equiv['rows_v1']} v2={equiv['rows_v2']} | "
            f"Cols v1={len(equiv['cols_v1'])} v2={len(equiv['cols_v2'])}"
        )
        print(f"Equivalência: {status}")
        if equiv["totals_v1"]:
            print(
                f"Totais v1: agend={equiv['totals_v1'].get('leads_com_agend')} "
                f"compar={equiv['totals_v1'].get('leads_com_compar')} "
                f"venda={equiv['totals_v1'].get('leads_com_venda_nova')}"
            )
            print(
                f"Totais v2: agend={equiv['totals_v2'].get('leads_com_agend')} "
                f"compar={equiv['totals_v2'].get('leads_com_compar')} "
                f"venda={equiv['totals_v2'].get('leads_com_venda_nova')}"
            )
        if equiv["issues"]:
            for issue in equiv["issues"]:
                print(f"  ! {issue}")
        if not equiv["divergences"].empty:
            print("\nTop divergências:")
            print(equiv["divergences"].to_string(index=False))
        print()

        summary_rows.append({
            "cenario": label,
            "t_v1_p50": st1["p50"],
            "t_v2_p50": st2["p50"],
            "ganho_s": gain_abs,
            "ganho_pct": gain_pct,
            "equiv": status,
        })

    print("=" * 72)
    print("RESUMO")
    print("=" * 72)
    for row in summary_rows:
        print(
            f"{row['cenario']:28s}  v1={row['t_v1_p50']:7.3f}s  "
            f"v2={row['t_v2_p50']:7.3f}s  "
            f"Δ={row['ganho_s']:6.3f}s ({row['ganho_pct']:5.1f}%)  "
            f"{row['equiv']}"
        )
    print()
    if all_pass:
        print(
            "APROVAÇÃO: v2 pode substituir v1 no CP seguinte "
            "(equivalência OK em todos os cenários)."
        )
    else:
        print("REPROVAÇÃO: v2 NÃO deve substituir v1 até corrigir divergências.")
    print("=" * 72)


if __name__ == "__main__":
    main()
