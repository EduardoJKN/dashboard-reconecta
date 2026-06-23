#!/usr/bin/env python
"""Valida equivalência legacy por janela vs legacy batch (benchmark CP6)."""
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

from src.funil_benchmark import build_equivalent_month_ranges  # noqa: E402
from src.one_page_funnel import (  # noqa: E402
    FunnelSnapshot,
    aplicacoes_kpis,
    build_funnel_snapshot,
    build_funnel_snapshot_for_window,
    build_funnel_snapshot_for_window_with_legacy,
    legacy_df_for_benchmark_period,
    load_benchmark_shared_frames,
)
from src.repositories import (  # noqa: E402
    benchmark_periods_json,
    get_executivas_for_funil,
    get_investimento_diario,
    get_one_page_legacy_diario_benchmark_batch_v2,
    get_one_page_legacy_diario_for_funil,
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

SNAPSHOT_FIELDS = (
    "investimento", "leads", "aplicacoes", "agendamentos", "comparecimento",
    "vendas", "montante", "receita", "pct_recebimento", "custo_lead",
    "pct_la", "pct_a_ag", "pct_ag_c", "pct_c_v", "ticket",
)
MONEY = {"investimento", "montante", "receita", "custo_lead", "ticket"}


def _clear() -> None:
    get_one_page_legacy_diario_benchmark_batch_v2.clear()
    load_benchmark_shared_frames.clear()


def _load_per_window(ini: date, fim: date) -> pd.DataFrame:
    df, _, _ = get_one_page_legacy_diario_for_funil(
        ini, fim, excluir_testes_aplicacoes=True,
    )
    return df


def _compare_frames(df_pw: pd.DataFrame, df_batch: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    c_pw = df_pw.sort_values("data_ref").reset_index(drop=True) if not df_pw.empty else df_pw
    c_b = df_batch.sort_values("data_ref").reset_index(drop=True) if not df_batch.empty else df_batch
    if list(c_pw.columns) != list(c_b.columns):
        issues.append(f"colunas: {list(c_pw.columns)} vs {list(c_b.columns)}")
    if len(c_pw) != len(c_b):
        issues.append(f"linhas: {len(c_pw)} vs {len(c_b)}")
    if c_pw.empty and c_b.empty:
        return issues
    for col in c_pw.columns:
        if col not in c_b.columns:
            continue
        a, b = c_pw[col], c_b[col]
        if pd.api.types.is_numeric_dtype(a):
            diff = (a.fillna(0).astype(float) - b.fillna(0).astype(float)).abs()
            tol = 0.01 if col == "investimento" else 1e-6
            if diff.max() > tol:
                issues.append(f"{col}: max_diff={diff.max()}")
        elif not a.equals(b):
            issues.append(f"{col}: valores divergentes")
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


def _compare_snapshots(s1: FunnelSnapshot, s2: FunnelSnapshot) -> list[str]:
    issues: list[str] = []
    for f in SNAPSHOT_FIELDS:
        v1 = float(getattr(s1, f))
        v2 = float(getattr(s2, f))
        tol = 0.01 if f in MONEY else 1e-6
        if abs(v1 - v2) > tol:
            issues.append(f"snapshot.{f}: {v1} vs {v2}")
    return issues


def _snapshot_from_legacy(df_legacy: pd.DataFrame, ini: date, fim: date) -> FunnelSnapshot:
    df_prev = get_prevendas_overview_diario(ini, fim)
    df_exec, _, _ = get_executivas_for_funil(ini, fim)
    df_inv = get_investimento_diario(ini, fim)
    return build_funnel_snapshot(df_legacy, df_prev, df_exec, df_inv)


def _validate_scenario(label: str, ini: date, fim: date) -> bool:
    ranges = build_equivalent_month_ranges(ini, fim, 3)
    if not ranges:
        print(f"OK   {label} (sem janelas históricas)")
        return True

    hist_ini = min(r[0] for r in ranges)
    hist_fim = max(r[1] for r in ranges)
    _clear()
    df_prev_wide, df_exec_wide, df_inv_wide = load_benchmark_shared_frames(
        hist_ini.isoformat(), hist_fim.isoformat(),
    )
    periods_json = benchmark_periods_json(ranges)
    df_batch_all = get_one_page_legacy_diario_benchmark_batch_v2(periods_json, True)

    ok_all = True
    for i, (w_ini, w_fim, w_label) in enumerate(ranges):
        df_pw = _load_per_window(w_ini, w_fim)
        df_b = legacy_df_for_benchmark_period(df_batch_all, str(i))
        issues = _compare_frames(df_pw, df_b)
        issues.extend(_compare_kpis(df_pw, df_b))

        snap_pw = build_funnel_snapshot_for_window(
            w_ini, w_fim,
            excluir_testes_aplicacoes=True,
            df_prev_wide=df_prev_wide,
            df_exec_wide=df_exec_wide,
            df_inv_wide=df_inv_wide,
        )
        snap_b = build_funnel_snapshot_for_window_with_legacy(
            w_ini, w_fim,
            df_one=df_b,
            df_prev_wide=df_prev_wide,
            df_exec_wide=df_exec_wide,
            df_inv_wide=df_inv_wide,
        )
        issues.extend(_compare_snapshots(snap_pw, snap_b))

        snap_legacy_pw = _snapshot_from_legacy(df_pw, w_ini, w_fim)
        snap_legacy_b = _snapshot_from_legacy(df_b, w_ini, w_fim)
        issues.extend(_compare_snapshots(snap_legacy_pw, snap_legacy_b))

        ok = not issues
        ok_all = ok_all and ok
        status = "OK" if ok else "FAIL"
        print(f"{status:4} {label} · janela {w_label} ({w_ini}→{w_fim})")
        for line in issues:
            print(f"      {line}")
    return ok_all


def main() -> None:
    all_ok = True
    for label, ini, fim in PERIODS:
        all_ok = _validate_scenario(label, ini, fim) and all_ok
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
