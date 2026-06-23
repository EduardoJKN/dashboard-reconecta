#!/usr/bin/env python
"""Valida equivalência numérica entre benchmark v1 e v2."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.funil_benchmark import (  # noqa: E402
    BENCHMARK_TAG_SPECS,
    build_equivalent_month_ranges,
    compute_funil_benchmark_v1,
    compute_funil_benchmark_v2,
    ranges_to_cache_json,
)
from src.one_page_funnel import (  # noqa: E402
    load_benchmark_shared_frames,
    _load_one_page_funnel_cached,
)
from src.repositories import get_one_page_legacy_diario_benchmark_batch_v2  # noqa: E402

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
    ("sem_dados", date(2099, 1, 1), date(2099, 1, 7)),
]

AGG_FIELDS = ("mean", "median", "p25", "p75", "best", "worst")
MONEY_KEYS = {"investimento", "custo_lead", "ticket"}
PCT_KEYS = {"pct_la", "pct_a_ag", "pct_ag_c", "pct_c_v", "pct_recebimento"}


def _clear_caches() -> None:
    compute_funil_benchmark_v1.clear()
    compute_funil_benchmark_v2.clear()
    load_benchmark_shared_frames.clear()
    _load_one_page_funnel_cached.clear()
    get_one_page_legacy_diario_benchmark_batch_v2.clear()


def _tolerance(key: str, kind: str) -> float:
    if key in MONEY_KEYS or kind == "money":
        return 0.01
    if key in PCT_KEYS or kind in {"pct", "pct100"}:
        return 1e-6
    return 1e-4


def _compare_metric(
    key: str,
    kind: str,
    v1: dict[str, Any],
    v2: dict[str, Any],
) -> list[str]:
    diffs: list[str] = []
    tol = _tolerance(key, kind)
    for field in AGG_FIELDS:
        a = v1.get(field)
        b = v2.get(field)
        if a is None and b is None:
            continue
        if a is None or b is None:
            diffs.append(f"{field}: {a} vs {b}")
            continue
        if abs(float(a) - float(b)) > tol:
            diffs.append(f"{field}: {a} vs {b} (Δ {float(a) - float(b):+.6g})")
    for field in ("best_period", "worst_period", "n_months"):
        if v1.get(field) != v2.get(field):
            diffs.append(f"{field}: {v1.get(field)} vs {v2.get(field)}")
    return diffs


def _run_pair(label: str, ini: date, fim: date) -> tuple[bool, list[str]]:
    ranges = build_equivalent_month_ranges(ini, fim, 3)
    ranges_json = ranges_to_cache_json(ranges)
    if not ranges:
        hist_ini, hist_fim = ini, fim
    else:
        hist_ini = min(r[0] for r in ranges)
        hist_fim = max(r[1] for r in ranges)

    _clear_caches()
    r1 = compute_funil_benchmark_v1(
        hist_ini.isoformat(),
        hist_fim.isoformat(),
        "90",
        True,
        ranges_json,
    )
    _clear_caches()
    r2 = compute_funil_benchmark_v2(
        hist_ini.isoformat(),
        hist_fim.isoformat(),
        "90",
        True,
        ranges_json,
    )

    issues: list[str] = []
    if (r1.get("error") or "") != (r2.get("error") or ""):
        issues.append(f"error: {r1.get('error')} vs {r2.get('error')}")
    if r1.get("monthly_count") != r2.get("monthly_count"):
        issues.append(
            f"monthly_count: {r1.get('monthly_count')} vs {r2.get('monthly_count')}"
        )

    m1 = r1.get("metrics") or {}
    m2 = r2.get("metrics") or {}
    for key, _label, _hib, kind in BENCHMARK_TAG_SPECS:
        if key not in m1 and key not in m2:
            continue
        if key not in m1 or key not in m2:
            issues.append(f"{key}: presente só em uma versão")
            continue
        metric_diffs = _compare_metric(key, kind, m1[key], m2[key])
        for d in metric_diffs:
            issues.append(f"{key}.{d}")

    ok = not issues
    status = "OK" if ok else "FAIL"
    print(f"{status:4} {label}", flush=True)
    for line in issues:
        print(f"      {line}", flush=True)
    if ok:
        leg_mode = r2.get("legacy_benchmark_mode", "?")
        leg_q = r2.get("legacy_benchmark_queries", "?")
        leg_t = r2.get("legacy_benchmark_time")
        leg_t_txt = f"{leg_t:.3f}s" if leg_t is not None else "—"
        leg_fb = r2.get("legacy_benchmark_fallback")
        print(
            f"      v2 repo_queries={r2.get('benchmark_repo_queries')} "
            f"funnel_loads_avoided={r2.get('funnel_loads_avoided')} "
            f"legacy_mode={leg_mode} legacy_queries={leg_q} "
            f"batch_enabled={r2.get('legacy_benchmark_batch_enabled', False)} "
            f"legacy_time={leg_t_txt}"
            + (f" FALLBACK={leg_fb}" if leg_fb else ""),
            flush=True,
        )
    return ok, issues


def main() -> None:
    all_ok = True
    for label, ini, fim in PERIODS:
        ok, _ = _run_pair(label, ini, fim)
        all_ok = all_ok and ok
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
