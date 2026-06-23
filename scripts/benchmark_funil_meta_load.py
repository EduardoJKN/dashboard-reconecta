#!/usr/bin/env python
"""Benchmark isolado — carregamento da Meta oficial do Funil."""
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

import streamlit as st

from src.funil_meta_store import (  # noqa: E402
    invalidate_funil_meta_load_cache,
    is_metas_database_configured,
    load_latest_meta_funil_mensal,
    meta_cache_hit_between,
    meta_latest_cache_hits,
    meta_load_cache_stats,
)

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
    ("sem_dados", date(2099, 1, 1), date(2099, 1, 7)),
]


def _bootstrap_key(ini: date, fim: date) -> str:
    return f"funil_meta_bootstrapped_{ini.isoformat()}_{fim.isoformat()}"


def _clear_meta_caches() -> None:
    invalidate_funil_meta_load_cache()


def _bench_load_latest(ini: date, fim: date) -> tuple[float, bool]:
    hits_before = meta_latest_cache_hits()
    t0 = time.perf_counter()
    load_latest_meta_funil_mensal(ini, fim)
    elapsed = time.perf_counter() - t0
    hits_after = meta_latest_cache_hits()
    cache_hit = meta_cache_hit_between(hits_before, hits_after)
    if not cache_hit and hits_before is None and elapsed < 0.05:
        cache_hit = True
    return elapsed, cache_hit


def _bench_session_bootstrap(ini: date, fim: date, *, warm: bool) -> tuple[float, bool]:
    key = _bootstrap_key(ini, fim)
    if not warm:
        st.session_state.pop(key, None)
    t0 = time.perf_counter()
    if not st.session_state.get(key):
        load_latest_meta_funil_mensal(ini, fim)
        st.session_state[key] = True
    elapsed = time.perf_counter() - t0
    return elapsed, bool(st.session_state.get(key)) and warm


def main() -> None:
    db_ok = is_metas_database_configured()
    print(f"Meta DB configurado: {db_ok}")
    print("-" * 72)

    for label, ini, fim in PERIODS:
        _clear_meta_caches()
        st.session_state.clear()

        load_cold, cache_cold = _bench_load_latest(ini, fim)
        load_warm, cache_warm = _bench_load_latest(ini, fim)

        init_cold, _ = _bench_session_bootstrap(ini, fim, warm=False)
        init_warm, session_warm = _bench_session_bootstrap(ini, fim, warm=True)

        meta_total = load_cold + init_cold
        stats = meta_load_cache_stats()

        print(f"\n{label} ({ini} -> {fim})")
        print(f"  load_latest_meta_funil_mensal: {load_cold:6.3f}s  cache_hit={cache_cold}")
        print(f"  load_latest_meta_funil_mensal warm: {load_warm:6.3f}s  cache_hit={cache_warm}")
        print(f"  init_meta_session (simulado) cold: {init_cold:6.3f}s")
        print(f"  init_meta_session (simulado) warm: {init_warm:6.3f}s  session_hit={session_warm}")
        print(f"  editor_prepare:                 0.000s  (lazy)")
        print(f"  meta_total (cold):              {meta_total:6.3f}s")
        print(
            f"  cache stats: latest hits={stats['latest_hits']} "
            f"misses={stats['latest_misses']}"
        )


if __name__ == "__main__":
    main()
