#!/usr/bin/env python
"""Valida equivalência legacy v1 vs v2 — DataFrame e snapshot do funil."""
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

from src.one_page_funnel import (  # noqa: E402
    FunnelSnapshot,
    aplicacoes_kpis,
    build_funnel_snapshot,
)
from src.prevendas_transforms import prevendas_overview_kpis  # noqa: E402
from src.repositories import (  # noqa: E402
    get_executivas,
    get_investimento_diario,
    get_one_page_legacy_diario,
    get_one_page_legacy_diario_v2,
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

SNAPSHOT_FIELDS = (
    "investimento", "leads", "aplicacoes", "agendamentos", "comparecimento",
    "vendas", "montante", "receita", "pct_recebimento", "custo_lead",
    "pct_la", "pct_a_ag", "pct_ag_c", "pct_c_v", "ticket",
)
MONEY = {"investimento", "montante", "receita", "custo_lead", "ticket"}


def _clear() -> None:
    get_one_page_legacy_diario.clear()
    get_one_page_legacy_diario_v2.clear()


def _load_v1(ini: date, fim: date) -> pd.DataFrame:
    return get_one_page_legacy_diario(ini, fim, excluir_testes_aplicacoes=True)


def _load_v2(ini: date, fim: date) -> pd.DataFrame:
    return get_one_page_legacy_diario_v2(
        ini.isoformat(), fim.isoformat(), True,
    )


def _compare_frames(df1: pd.DataFrame, df2: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    if list(df1.columns) != list(df2.columns):
        issues.append(f"colunas: {list(df1.columns)} vs {list(df2.columns)}")
    if len(df1) != len(df2):
        issues.append(f"linhas: {len(df1)} vs {len(df2)}")
    if df1.empty and df2.empty:
        return issues
    c1 = df1.sort_values("data_ref").reset_index(drop=True)
    c2 = df2.sort_values("data_ref").reset_index(drop=True)
    for col in c1.columns:
        if col not in c2.columns:
            continue
        a, b = c1[col], c2[col]
        if pd.api.types.is_numeric_dtype(a):
            diff = (a.fillna(0).astype(float) - b.fillna(0).astype(float)).abs()
            tol = 0.01 if col == "investimento" else 1e-6
            if diff.max() > tol:
                issues.append(f"{col}: max_diff={diff.max()}")
        elif not a.equals(b):
            issues.append(f"{col}: valores divergentes")
    return issues


def _snapshot_from_legacy(
    df_legacy: pd.DataFrame, ini: date, fim: date,
) -> FunnelSnapshot:
    df_prev = get_prevendas_overview_diario(ini, fim)
    df_exec = get_executivas(ini, fim)
    df_inv = get_investimento_diario(ini, fim)
    return build_funnel_snapshot(df_legacy, df_prev, df_exec, df_inv)


def _compare_snapshots(s1: FunnelSnapshot, s2: FunnelSnapshot) -> list[str]:
    issues: list[str] = []
    for f in SNAPSHOT_FIELDS:
        v1 = float(getattr(s1, f))
        v2 = float(getattr(s2, f))
        tol = 0.01 if f in MONEY else 1e-6
        if abs(v1 - v2) > tol:
            issues.append(f"snapshot.{f}: {v1} vs {v2}")
    return issues


def _compare_kpis(df1: pd.DataFrame, df2: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    k1 = aplicacoes_kpis(df1)
    k2 = aplicacoes_kpis(df2)
    for key in k1:
        v1, v2 = float(k1[key]), float(k2[key])
        tol = 0.01 if "investimento" in key or key.startswith("custo") else 1e-4
        if abs(v1 - v2) > tol:
            issues.append(f"aplicacoes_kpis.{key}: {v1} vs {v2}")
    return issues


def main() -> None:
    ok_all = True
    for label, ini, fim in PERIODS:
        _clear()
        df1 = _load_v1(ini, fim)
        get_one_page_legacy_diario_v2.clear()
        df2 = _load_v2(ini, fim)
        issues = _compare_frames(df1, df2)
        issues.extend(_compare_kpis(df1, df2))
        snap1 = _snapshot_from_legacy(df1, ini, fim)
        snap2 = _snapshot_from_legacy(df2, ini, fim)
        issues.extend(_compare_snapshots(snap1, snap2))
        ok = not issues
        ok_all = ok_all and ok
        print(f"{'OK' if ok else 'FAIL':4} {label}")
        for line in issues:
            print(f"      {line}")
    if not ok_all:
        sys.exit(1)


if __name__ == "__main__":
    main()
