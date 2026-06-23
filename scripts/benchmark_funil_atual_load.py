#!/usr/bin/env python
"""Benchmark isolado — bloco Atual do funil por fonte."""
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

from src.one_page_funnel import (  # noqa: E402
    _load_one_page_funnel_cached,
    build_funnel_snapshot,
)
from src.repositories import (  # noqa: E402
    get_executivas,
    get_investimento_diario,
    get_one_page_legacy_diario,
    get_one_page_legacy_diario_v2,
    get_prevendas_overview_diario,
)

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
    ("sem_dados", date(2099, 1, 1), date(2099, 1, 7)),
]


def _clear_caches() -> None:
    get_one_page_legacy_diario.clear()
    get_one_page_legacy_diario_v2.clear()
    get_prevendas_overview_diario.clear()
    get_executivas.clear()
    get_investimento_diario.clear()
    _load_one_page_funnel_cached.clear()


def _timed(fn) -> tuple[float, object]:
    t0 = time.perf_counter()
    out = fn()
    return time.perf_counter() - t0, out


def _bench_atual_cold(ini: date, fim: date) -> dict:
    _clear_caches()
    excl = True

    t_legacy, df_legacy = _timed(
        lambda: get_one_page_legacy_diario(ini, fim, excluir_testes_aplicacoes=excl)
    )
    t_prev, df_prev = _timed(lambda: get_prevendas_overview_diario(ini, fim))
    t_exec, df_exec = _timed(lambda: get_executivas(ini, fim))
    t_inv, df_inv = _timed(lambda: get_investimento_diario(ini, fim))
    t_build, _snap = _timed(
        lambda: build_funnel_snapshot(df_legacy, df_prev, df_exec, df_inv)
    )
    total = t_legacy + t_prev + t_exec + t_inv + t_build

    return {
        "legacy_diario": t_legacy,
        "prevendas": t_prev,
        "executivas": t_exec,
        "investimento": t_inv,
        "build_snapshot": t_build,
        "total_atual": total,
        "rows": {
            "legacy_diario": len(df_legacy),
            "prevendas": len(df_prev),
            "executivas": len(df_exec),
            "investimento": len(df_inv),
        },
        "cache": "cold",
    }


def _bench_atual_warm(ini: date, fim: date) -> dict:
    excl = True
    t_legacy, _ = _timed(
        lambda: get_one_page_legacy_diario(ini, fim, excluir_testes_aplicacoes=excl)
    )
    t_prev, _ = _timed(lambda: get_prevendas_overview_diario(ini, fim))
    t_exec, _ = _timed(lambda: get_executivas(ini, fim))
    t_inv, _ = _timed(lambda: get_investimento_diario(ini, fim))
    total = t_legacy + t_prev + t_exec + t_inv
    return {
        "legacy_diario": t_legacy,
        "prevendas": t_prev,
        "executivas": t_exec,
        "investimento": t_inv,
        "total_atual": total,
        "cache": "warm",
    }


def _bench_legacy_v1_v2(ini: date, fim: date) -> dict:
    _clear_caches()
    excl = True
    t_v1, _ = _timed(
        lambda: get_one_page_legacy_diario(ini, fim, excluir_testes_aplicacoes=excl)
    )
    get_one_page_legacy_diario_v2.clear()
    t_v2, _ = _timed(
        lambda: get_one_page_legacy_diario_v2(
            ini.isoformat(), fim.isoformat(), excl,
        )
    )
    return {"legacy_v1": t_v1, "legacy_v2": t_v2}


def main() -> None:
    print("Benchmark Atual — por fonte (cold) + warm + legacy v1 vs v2")
    print("=" * 72)
    for label, ini, fim in PERIODS:
        cold = _bench_atual_cold(ini, fim)
        warm = _bench_atual_warm(ini, fim)
        leg = _bench_legacy_v1_v2(ini, fim)
        print(f"\n{label} ({ini} -> {fim})")
        print(f"  legacy_diario:  {cold['legacy_diario']:6.2f}s  ({cold['rows']['legacy_diario']} linhas)")
        print(f"  prevendas:      {cold['prevendas']:6.2f}s  ({cold['rows']['prevendas']} linhas)")
        print(f"  executivas:     {cold['executivas']:6.2f}s  ({cold['rows']['executivas']} linhas)")
        print(f"  investimento:   {cold['investimento']:6.2f}s  ({cold['rows']['investimento']} linhas)")
        print(f"  build_snapshot: {cold['build_snapshot']:6.2f}s")
        print(f"  total_atual:    {cold['total_atual']:6.2f}s  [cold]")
        print(
            f"  warm total:     {warm['total_atual']:6.2f}s  "
            f"(legacy={warm['legacy_diario']:.3f}s)"
        )
        print(
            f"  legacy v1:      {leg['legacy_v1']:6.2f}s  |  "
            f"v2: {leg['legacy_v2']:6.2f}s"
        )
        if leg["legacy_v1"] > 0:
            pct = (leg["legacy_v1"] - leg["legacy_v2"]) / leg["legacy_v1"] * 100
            print(f"  ganho legacy v2: {pct:+.1f}%")


if __name__ == "__main__":
    main()
