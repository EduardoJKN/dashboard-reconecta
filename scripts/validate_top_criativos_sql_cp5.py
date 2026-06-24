#!/usr/bin/env python
"""CP5 — equivalência SQL mkt_top_criativos_por_nome (scan único leads).

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
    ("mes_atual", date(2026, 6, 1), TODAY),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("jun_2026_parcial", date(2026, 6, 1), date(2026, 6, 15)),
    ("sem_dados", date(2020, 1, 1), date(2020, 1, 7)),
    ("abr_2026_mes", date(2026, 4, 1), date(2026, 4, 30)),
]

NUM_COLS = [
    "qtd_ad_ids", "qtd_campaigns", "qtd_adsets",
    "investimento", "impressoes", "alcance", "cliques", "cliques_link",
    "lp_views", "leads_meta", "ctr", "cpc",
    "leads_reais", "leads_mais_12", "leads_menos_12", "leads_nao_atua",
    "aplicacoes", "aplicacoes_mais_12", "aplicacoes_menos_12",
    "cpl_real", "cpl_mais_12", "cpl_meta",
]


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


def _compare(leg: pd.DataFrame, opt: pd.DataFrame, label: str) -> list[str]:
    issues: list[str] = []
    leg_n = _normalize(leg)
    opt_n = _normalize(opt)

    if len(leg_n) != len(opt_n):
        issues.append(f"{label}: row_count legacy={len(leg_n)} opt={len(opt_n)}")
        return issues

    if leg_n.empty:
        return issues

    keys_leg = set(leg_n["ad_name_norm"])
    keys_opt = set(opt_n["ad_name_norm"])
    if keys_leg != keys_opt:
        only_leg = keys_leg - keys_opt
        only_opt = keys_opt - keys_leg
        if only_leg:
            issues.append(f"{label}: só legacy: {sorted(only_leg)[:5]}")
        if only_opt:
            issues.append(f"{label}: só opt: {sorted(only_opt)[:5]}")
        return issues

    merged = leg_n.merge(
        opt_n, on="ad_name_norm", suffixes=("_leg", "_opt"), how="inner",
    )
    for c in NUM_COLS:
        cl, co = f"{c}_leg", f"{c}_opt"
        if cl not in merged.columns or co not in merged.columns:
            continue
        a = merged[cl].to_numpy(dtype=float)
        b = merged[co].to_numpy(dtype=float)
        both_nan = np.isnan(a) & np.isnan(b)
        diff = ~both_nan & (
            np.isnan(a) | np.isnan(b) | (np.abs(a - b) > 0.01)
        )
        if diff.any():
            idx = int(np.argmax(diff))
            issues.append(
                f"{label}: {c} diverge em {merged.iloc[idx]['ad_name_norm']!r} "
                f"legacy={merged.iloc[idx][cl]} opt={merged.iloc[idx][co]}"
            )

    str_cols = ["ad_name", "campaign_name"]
    for c in str_cols:
        cl, co = f"{c}_leg", f"{c}_opt"
        if cl not in merged.columns:
            continue
        mism = merged[cl].fillna("").astype(str) != merged[co].fillna("").astype(str)
        if mism.any():
            row = merged.loc[mism.iloc[0] if hasattr(mism, 'iloc') else mism.idxmax()]
            issues.append(f"{label}: {c} texto diverge em {row['ad_name_norm']!r}")

    order_leg = leg["ad_name_norm"].astype(str).tolist()
    order_opt = opt["ad_name_norm"].astype(str).tolist()
    if order_leg != order_opt:
        issues.append(f"{label}: ORDER BY diverge (primeiros 3 leg/opt)")
        issues.append(f"  leg: {order_leg[:3]}")
        issues.append(f"  opt: {order_opt[:3]}")

    return issues


def main() -> None:
    print("=== CP5 SQL equivalência: top_criativos_por_nome ===\n")
    all_issues: list[str] = []
    timings: list[tuple[str, float, float]] = []

    for label, di, df in PERIODS:
        params = {"data_ini": di, "data_fim": df}
        print(f"--- {label} ({di} -> {df}) ---")

        t0 = time.perf_counter()
        leg = run_sql_file("mkt_top_criativos_por_nome_legacy.sql", params)
        t_leg = time.perf_counter() - t0

        t0 = time.perf_counter()
        opt = run_sql_file("mkt_top_criativos_por_nome.sql", params)
        t_opt = time.perf_counter() - t0

        timings.append((label, t_leg, t_opt))
        issues = _compare(leg, opt, label)
        all_issues.extend(issues)

        pct = (1 - t_opt / t_leg) * 100 if t_leg > 0 else 0
        print(
            f"  rows={len(opt)} legacy={t_leg:.3f}s opt={t_opt:.3f}s "
            f"delta={pct:+.1f}% equiv={'OK' if not issues else 'FALHOU'}"
        )
        for i in issues:
            print(f"    {i}")

    print("\n=== Resumo tempos SQL ===")
    for label, t_leg, t_opt in timings:
        print(f"  {label:<20} legacy={t_leg:7.3f}s  opt={t_opt:7.3f}s")

    if all_issues:
        print(f"\nRESULTADO: FALHOU ({len(all_issues)} divergências)")
        sys.exit(1)
    print("\nRESULTADO: OK — SQL otimizado equivalente em todos os períodos")
    sys.exit(0)


if __name__ == "__main__":
    main()
