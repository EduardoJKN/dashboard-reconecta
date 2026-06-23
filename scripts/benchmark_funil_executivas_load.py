#!/usr/bin/env python
"""Benchmark isolado — get_executivas para o Funil."""
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

import pandas as pd  # noqa: E402

from src.one_page_funnel import build_funnel_snapshot  # noqa: E402
from src.repositories import (  # noqa: E402
    get_executivas,
    get_executivas_for_funil_v2,
    get_investimento_diario,
    get_one_page_legacy_diario,
    get_prevendas_overview_diario,
)
from src.transforms import visao_geral_kpis  # noqa: E402

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
    ("sem_dados", date(2099, 1, 1), date(2099, 1, 7)),
]


def _clear() -> None:
    get_executivas.clear()
    get_executivas_for_funil_v2.clear()


def _timed(fn) -> tuple[float, pd.DataFrame]:
    t0 = time.perf_counter()
    df = fn()
    return time.perf_counter() - t0, df


def main() -> None:
    print("Benchmark Executivas — v1 vs v2 (Funil)")
    print("=" * 72)
    for label, ini, fim in PERIODS:
        _clear()
        t_v1, df_v1 = _timed(lambda: get_executivas(ini, fim))
        get_executivas_for_funil_v2.clear()
        t_v2, df_v2 = _timed(
            lambda: get_executivas_for_funil_v2(ini.isoformat(), fim.isoformat())
        )
        t_warm, _ = _timed(lambda: get_executivas_for_funil_v2(
            ini.isoformat(), fim.isoformat(),
        ))

        k_v1 = visao_geral_kpis(df_v1, pd.DataFrame())
        k_v2 = visao_geral_kpis(df_v2, pd.DataFrame())

        t_build = 0.0
        try:
            df_one = get_one_page_legacy_diario(ini, fim, excluir_testes_aplicacoes=True)
            df_prev = get_prevendas_overview_diario(ini, fim)
            df_inv = get_investimento_diario(ini, fim)
            t0 = time.perf_counter()
            build_funnel_snapshot(df_one, df_prev, df_v2, df_inv)
            t_build = time.perf_counter() - t0
        except Exception:
            pass

        print(f"\n{label} ({ini} -> {fim})")
        print(f"  get_executivas_v1: {t_v1:6.2f}s  linhas={len(df_v1)}  cols={len(df_v1.columns)}")
        print(f"  get_executivas_v2: {t_v2:6.2f}s  linhas={len(df_v2)}  cols={len(df_v2.columns)}")
        print(f"  build_snapshot_com_executivas: {t_build:6.2f}s")
        print(f"  warm v2: {t_warm:6.2f}s")
        if t_v1 > 0:
            print(f"  ganho v2 vs v1: {(t_v1 - t_v2) / t_v1 * 100:+.1f}%")
        print(
            f"  vendas v1={k_v1['vendas']} v2={k_v2['vendas']} "
            f"match={k_v1['vendas'] == k_v2['vendas']}"
        )


if __name__ == "__main__":
    main()
