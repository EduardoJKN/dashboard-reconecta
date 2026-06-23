#!/usr/bin/env python
"""Valida equivalência executivas v1 vs v2 para o Funil."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.one_page_funnel import FunnelSnapshot, build_funnel_snapshot  # noqa: E402
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

FUNIL_KPI_COLS = (
    "vendas", "montante", "receita", "pct_recebimento",
    "ticket_medio", "perdidos", "cancelados", "oportunidades",
)
SNAPSHOT_FIELDS = (
    "vendas", "montante", "receita", "pct_recebimento", "ticket",
)
MONEY = {"montante", "receita", "ticket"}


def _clear() -> None:
    get_executivas.clear()
    get_executivas_for_funil_v2.clear()


def _compare_kpis(df1: pd.DataFrame, df2: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    k1 = visao_geral_kpis(df1, pd.DataFrame())
    k2 = visao_geral_kpis(df2, pd.DataFrame())
    for key in FUNIL_KPI_COLS:
        if key not in k1 or key not in k2:
            continue
        v1, v2 = float(k1[key]), float(k2[key])
        tol = 0.01 if key in {"montante", "receita", "ticket_medio"} else 1e-6
        if abs(v1 - v2) > tol:
            issues.append(f"visao_geral_kpis.{key}: {v1} vs {v2}")
    return issues


def _snapshot(
    df_exec: pd.DataFrame, ini: date, fim: date,
) -> FunnelSnapshot:
    df_one = get_one_page_legacy_diario(ini, fim, excluir_testes_aplicacoes=True)
    df_prev = get_prevendas_overview_diario(ini, fim)
    df_inv = get_investimento_diario(ini, fim)
    return build_funnel_snapshot(df_one, df_prev, df_exec, df_inv)


def _compare_snapshots(s1: FunnelSnapshot, s2: FunnelSnapshot) -> list[str]:
    issues: list[str] = []
    for f in SNAPSHOT_FIELDS:
        v1, v2 = float(getattr(s1, f)), float(getattr(s2, f))
        tol = 0.01 if f in MONEY else 1e-6
        if abs(v1 - v2) > tol:
            issues.append(f"snapshot.{f}: {v1} vs {v2}")
    return issues


def main() -> None:
    ok_all = True
    for label, ini, fim in PERIODS:
        _clear()
        df1 = get_executivas(ini, fim)
        get_executivas_for_funil_v2.clear()
        df2 = get_executivas_for_funil_v2(ini.isoformat(), fim.isoformat())
        issues = _compare_kpis(df1, df2)
        issues.extend(_compare_snapshots(_snapshot(df1, ini, fim), _snapshot(df2, ini, fim)))
        ok = not issues
        ok_all = ok_all and ok
        print(f"{'OK' if ok else 'FAIL':4} {label}")
        for line in issues:
            print(f"      {line}")
    if not ok_all:
        sys.exit(1)


if __name__ == "__main__":
    main()
