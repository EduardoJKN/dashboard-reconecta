#!/usr/bin/env python
"""Benchmark comparativo — funil e benchmark v1 vs v2."""
from __future__ import annotations

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

from src.funil_benchmark import (  # noqa: E402
    build_equivalent_month_ranges,
    compute_funil_benchmark_v1,
    compute_funil_benchmark_v2,
    ranges_to_cache_json,
)
from src.one_page_funnel import (  # noqa: E402
    _load_one_page_funnel_cached,
    _load_one_page_funnel_impl,
    load_benchmark_shared_frames,
    load_one_page_funnel,
)
from src.repositories import get_one_page_legacy_diario_benchmark_batch_v2  # noqa: E402

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
]


def _clear_funnel_cache() -> None:
    _load_one_page_funnel_cached.clear()
    load_benchmark_shared_frames.clear()
    compute_funil_benchmark_v1.clear()
    compute_funil_benchmark_v2.clear()
    get_one_page_legacy_diario_benchmark_batch_v2.clear()


def _bench_impl(ini: date, fim: date) -> float:
    t0 = time.perf_counter()
    _load_one_page_funnel_impl(ini, fim, excluir_testes_aplicacoes=True)
    return time.perf_counter() - t0


def _bench_cached(ini: date, fim: date) -> float:
    t0 = time.perf_counter()
    load_one_page_funnel(ini, fim, excluir_testes_aplicacoes=True)
    return time.perf_counter() - t0


def _bench_benchmark_v1(ini: date, fim: date) -> tuple[float, int, int]:
    ranges = build_equivalent_month_ranges(ini, fim, 3)
    ranges_json = ranges_to_cache_json(ranges)
    hist_ini = min(r[0] for r in ranges)
    hist_fim = max(r[1] for r in ranges)
    t0 = time.perf_counter()
    result = compute_funil_benchmark_v1(
        hist_ini.isoformat(),
        hist_fim.isoformat(),
        "90",
        True,
        ranges_json,
    )
    elapsed = time.perf_counter() - t0
    n = len(ranges)
    return elapsed, n, int(result.get("benchmark_repo_queries") or 4 * n)


def _bench_benchmark_v2(ini: date, fim: date) -> tuple[float, int, int, dict]:
    ranges = build_equivalent_month_ranges(ini, fim, 3)
    ranges_json = ranges_to_cache_json(ranges)
    hist_ini = min(r[0] for r in ranges)
    hist_fim = max(r[1] for r in ranges)
    t0 = time.perf_counter()
    result = compute_funil_benchmark_v2(
        hist_ini.isoformat(),
        hist_fim.isoformat(),
        "90",
        True,
        ranges_json,
    )
    elapsed = time.perf_counter() - t0
    n = len(ranges)
    meta = {
        "legacy_mode": result.get("legacy_benchmark_mode"),
        "legacy_queries": result.get("legacy_benchmark_queries"),
        "legacy_time": result.get("legacy_benchmark_time"),
        "legacy_fallback": result.get("legacy_benchmark_fallback"),
    }
    return (
        elapsed,
        n,
        int(result.get("benchmark_repo_queries") or 3 + n),
        meta,
    )


def main() -> None:
    print("Benchmark Funil — atual + benchmark v1 vs v2 (cold)")
    print("-" * 88)
    for label, ini, fim in PERIODS:
        _clear_funnel_cache()
        atual_cold = _bench_cached(ini, fim)
        bm_v1, n_win, q_v1 = _bench_benchmark_v1(ini, fim)

        _clear_funnel_cache()
        atual_warm = _bench_cached(ini, fim)
        bm_v2, _, q_v2, leg_meta = _bench_benchmark_v2(ini, fim)

        print(f"\n{label} ({ini} -> {fim})")
        print(
            f"  atual cold={atual_cold:6.2f}s  warm={atual_warm:6.2f}s  "
            f"({n_win} janelas benchmark)"
        )
        print(
            f"  benchmark v1: {bm_v1:6.2f}s  repo_queries~{q_v1}  "
            f"funnel_loads={n_win}"
        )
        leg_t = leg_meta.get("legacy_time")
        leg_t_txt = f"{leg_t:.2f}s" if leg_t is not None else "—"
        print(
            f"  benchmark v2: {bm_v2:6.2f}s  repo_queries~{q_v2}  "
            f"legacy={leg_meta.get('legacy_mode')}({leg_meta.get('legacy_queries')}q, "
            f"{leg_t_txt})  funnel_loads_evitados={n_win * 3}"
        )
        if bm_v1 > 0:
            pct = (bm_v1 - bm_v2) / bm_v1 * 100
            print(f"  ganho v2 vs v1: {pct:+.1f}%")


if __name__ == "__main__":
    main()
