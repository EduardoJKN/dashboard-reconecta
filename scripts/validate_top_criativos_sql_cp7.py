#!/usr/bin/env python
"""CP7 — equivalência SQL pre_cp7 vs MATERIALIZED CTEs.

Requer banco: RUN_DB_EQUIVALENCE=1
"""
from __future__ import annotations

import os
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

if os.environ.get("RUN_DB_EQUIVALENCE") != "1":
    print("Defina RUN_DB_EQUIVALENCE=1 para executar.")
    sys.exit(0)

import numpy as np
import pandas as pd

from src.db import run_sql_file

TODAY = date(2026, 6, 23)

PERIODS: list[tuple[str, date, date]] = [
    ("ultimos_7_dias", TODAY - timedelta(days=6), TODAY),
    ("abr_2026", date(2026, 4, 1), date(2026, 4, 30)),
    ("mai_2026", date(2026, 5, 1), date(2026, 5, 31)),
    ("jun_2026_parcial", date(2026, 6, 1), date(2026, 6, 15)),
    ("sem_dados", date(2020, 1, 1), date(2020, 1, 7)),
]

NUM_COLS = [
    "qtd_ad_ids", "qtd_campaigns", "qtd_adsets",
    "investimento", "impressoes", "alcance", "cliques", "cliques_link",
    "lp_views", "leads_meta", "ctr", "cpc",
    "leads_reais", "leads_mais_12", "leads_menos_12", "leads_nao_atua",
    "aplicacoes", "aplicacoes_mais_12", "aplicacoes_menos_12",
    "cpl_real", "cpl_mais_12", "cpl_meta",
]

BASELINE = "mkt_top_criativos_por_nome_pre_cp7.sql"
CP7 = "mkt_top_criativos_por_nome.sql"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["ad_name_norm"] = out["ad_name_norm"].astype(str)
    out = out.sort_values("ad_name_norm").reset_index(drop=True)
    for c in NUM_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _compare(base: pd.DataFrame, cp7: pd.DataFrame, label: str) -> list[str]:
    issues: list[str] = []
    b = _normalize(base)
    o = _normalize(cp7)

    if len(b) != len(o):
        issues.append(f"{label}: row_count pre_cp7={len(b)} cp7={len(o)}")
        return issues
    if b.empty:
        return issues

    if set(b["ad_name_norm"]) != set(o["ad_name_norm"]):
        issues.append(f"{label}: conjunto ad_name_norm diverge")
        return issues

    merged = b.merge(o, on="ad_name_norm", suffixes=("_b", "_o"), how="inner")
    for c in NUM_COLS:
        cb, co = f"{c}_b", f"{c}_o"
        if cb not in merged.columns:
            continue
        a = merged[cb].to_numpy(dtype=float)
        z = merged[co].to_numpy(dtype=float)
        both_nan = np.isnan(a) & np.isnan(z)
        diff = ~both_nan & (np.isnan(a) | np.isnan(z) | (np.abs(a - z) > 0.01))
        if diff.any():
            i = int(np.argmax(diff))
            issues.append(
                f"{label}: {c} diverge em {merged.iloc[i]['ad_name_norm']!r} "
                f"pre={merged.iloc[i][cb]} cp7={merged.iloc[i][co]}"
            )

    for c in ("ad_name", "campaign_name"):
        cb, co = f"{c}_b", f"{c}_o"
        if cb not in merged.columns:
            continue
        mism = merged[cb].fillna("").astype(str) != merged[co].fillna("").astype(str)
        if mism.any():
            row = merged.loc[mism.idxmax()]
            issues.append(f"{label}: {c} texto diverge em {row['ad_name_norm']!r}")

    if base["ad_name_norm"].astype(str).tolist() != cp7["ad_name_norm"].astype(str).tolist():
        issues.append(f"{label}: ORDER BY diverge")
        issues.append(f"  pre: {base['ad_name_norm'].head(3).tolist()}")
        issues.append(f"  cp7: {cp7['ad_name_norm'].head(3).tolist()}")

    return issues


def main() -> None:
    print("=== CP7 SQL equivalência: pre_cp7 vs MATERIALIZED ===\n")
    all_issues: list[str] = []
    timings: list[tuple[str, float, float, int]] = []

    for label, di, df in PERIODS:
        params = {"data_ini": di, "data_fim": df}
        print(f"--- {label} ({di} -> {df}) ---", flush=True)

        t0 = time.perf_counter()
        base = run_sql_file(BASELINE, params)
        t_base = time.perf_counter() - t0

        t0 = time.perf_counter()
        cp7 = run_sql_file(CP7, params)
        t_cp7 = time.perf_counter() - t0

        issues = _compare(base, cp7, label)
        all_issues.extend(issues)
        timings.append((label, t_base, t_cp7, len(cp7)))

        pct = (1 - t_cp7 / t_base) * 100 if t_base > 0 else 0
        print(
            f"  rows={len(cp7)} pre_cp7={t_base:.3f}s cp7={t_cp7:.3f}s "
            f"delta={pct:+.1f}% equiv={'OK' if not issues else 'FALHOU'}"
        )
        for i in issues:
            print(f"    {i}")

    print("\n=== Resumo tempos ===")
    for label, tb, tc, rows in timings:
        print(f"  {label:<20} pre={tb:7.3f}s  cp7={tc:7.3f}s  rows={rows}")

    if all_issues:
        print(f"\nRESULTADO: FALHOU ({len(all_issues)} divergências)")
        sys.exit(1)
    print("\nRESULTADO: OK — CP7 equivalente em todos os períodos")
    sys.exit(0)


if __name__ == "__main__":
    main()
