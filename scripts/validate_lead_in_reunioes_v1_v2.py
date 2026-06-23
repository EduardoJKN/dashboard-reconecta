#!/usr/bin/env python
"""Validação de equivalência — lead_in_reunioes_consultas v1 vs v2 (somente leitura).

Compara resultado SQL v1 e v2 nos mesmos períodos, incluindo métricas usadas
pelos cards, matriz, agenda e rankings (via lead_in_aplicar_pre + KPIs).

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\validate_lead_in_reunioes_v1_v2.py
"""
from __future__ import annotations

import argparse
import sys
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

from src.lead_in_transforms import (  # noqa: E402
    lead_in_aplicar_pre,
    lead_in_kpis,
    lead_in_matriz,
    lead_in_preparar_agenda,
)
from src.repositories import (  # noqa: E402
    _load_lead_in_reunioes_consultas,
    _load_lead_in_reunioes_consultas_sql,
    get_lead_in_email_sdr_lookup,
    get_prevendas_sdrs_oficiais,
)

HOJE = date(2026, 6, 22)

COMPARE_COLS = [
    "activity_id",
    "deal_id",
    "data_reuniao",
    "ts_reuniao",
    "data_criacao_agendamento",
    "start_datetime",
    "end_datetime",
    "status_reuniao",
    "prevendas_raw",
    "motivo_cancelamento",
    "nome_cliente",
    "email",
    "email_norm",
    "telefone",
    "closer",
    "deal_sdr_ss_id",
    "deal_sdr_nome",
    "origem",
    "fonte_pre_bruta",
]

KPI_KEYS = [
    "total",
    "agendadas",
    "realizadas",
    "canceladas",
    "outros",
    "com_pre",
    "sem_pre",
    "taxa_realizacao",
    "taxa_cancelamento",
]


def _init_scenarios(hoje: date) -> dict[str, tuple[date, date]]:
    mes_ini = hoje.replace(day=1)
    if mes_ini.month == 1:
        mes_ant_ini = date(hoje.year - 1, 12, 1)
        mes_ant_fim = date(hoje.year - 1, 12, 31)
    else:
        mes_ant_ini = date(hoje.year, hoje.month - 1, 1)
        prox = mes_ant_ini.replace(day=28) + timedelta(days=4)
        mes_ant_fim = prox.replace(day=1) - timedelta(days=1)
    return {
        "ultimos_7_dias": (hoje - timedelta(days=6), hoje),
        "mes_atual": (mes_ini, hoje),
        "mes_anterior": (mes_ant_ini, mes_ant_fim),
        "ultimos_90_dias": (hoje - timedelta(days=89), hoje),
    }


def _norm_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in COMPARE_COLS:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[COMPARE_COLS].copy()
    out["activity_id"] = out["activity_id"].astype(str)
    for col in ("data_reuniao", "ts_reuniao", "data_criacao_agendamento", "start_datetime", "end_datetime"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    for col in out.select_dtypes(include="object").columns:
        out[col] = out[col].fillna("").astype(str).str.strip()
    out = out.sort_values("activity_id").reset_index(drop=True)
    return out


def _compare_frames(v1: pd.DataFrame, v2: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    n1, n2 = len(v1), len(v2)
    if n1 != n2:
        issues.append(f"contagem de linhas: v1={n1} v2={n2} (delta={n2 - n1})")

    cols1 = set(v1.columns)
    cols2 = set(v2.columns)
    if cols1 != cols2:
        only1 = sorted(cols1 - cols2)
        only2 = sorted(cols2 - cols1)
        if only1:
            issues.append(f"colunas só na v1: {only1}")
        if only2:
            issues.append(f"colunas só na v2: {only2}")

    if v1.empty and v2.empty:
        return issues

    a = _norm_df(v1)
    b = _norm_df(v2)
    ids1 = set(a["activity_id"])
    ids2 = set(b["activity_id"])
    only_v1 = sorted(ids1 - ids2)
    only_v2 = sorted(ids2 - ids1)
    if only_v1:
        issues.append(f"activity_id só na v1 ({len(only_v1)}): {only_v1[:5]}{'…' if len(only_v1) > 5 else ''}")
    if only_v2:
        issues.append(f"activity_id só na v2 ({len(only_v2)}): {only_v2[:5]}{'…' if len(only_v2) > 5 else ''}")

    common = sorted(ids1 & ids2)
    if not common:
        return issues

    merged = a[a["activity_id"].isin(common)].merge(
        b[b["activity_id"].isin(common)],
        on="activity_id",
        suffixes=("_v1", "_v2"),
        how="inner",
    )
    for col in COMPARE_COLS:
        if col == "activity_id":
            continue
        c1, c2 = f"{col}_v1", f"{col}_v2"
        if c1 not in merged.columns:
            continue
        if col in ("data_reuniao", "ts_reuniao", "data_criacao_agendamento", "start_datetime", "end_datetime"):
            d1 = pd.to_datetime(merged[c1], errors="coerce")
            d2 = pd.to_datetime(merged[c2], errors="coerce")
            diff = d1.ne(d2) & ~(d1.isna() & d2.isna())
        elif col in ("taxa_realizacao", "taxa_cancelamento"):
            continue
        else:
            diff = merged[c1].astype(str) != merged[c2].astype(str)
        n_diff = int(diff.sum())
        if n_diff:
            sample = merged.loc[diff, ["activity_id", c1, c2]].head(3)
            issues.append(f"coluna `{col}` difere em {n_diff} linha(s); amostra:\n{sample.to_string(index=False)}")
    return issues


def _status_counts(df: pd.DataFrame) -> pd.Series:
    if df.empty or "status_reuniao" not in df.columns:
        return pd.Series(dtype=int)
    return df["status_reuniao"].fillna("(nulo)").value_counts().sort_index()


def _compare_downstream(
    df_v1: pd.DataFrame,
    df_v2: pd.DataFrame,
    df_pre: pd.DataFrame,
    df_email: pd.DataFrame,
    data_ini: date,
    data_fim: date,
) -> list[str]:
    issues: list[str] = []
    if df_v1.empty and df_v2.empty:
        return issues

    d1 = lead_in_aplicar_pre(df_v1, df_pre, df_email)
    d2 = lead_in_aplicar_pre(df_v2, df_pre, df_email)
    k1 = lead_in_kpis(d1)
    k2 = lead_in_kpis(d2)
    for key in KPI_KEYS:
        v1, v2 = k1.get(key), k2.get(key)
        if isinstance(v1, float) and isinstance(v2, float):
            if abs(v1 - v2) > 1e-9:
                issues.append(f"KPI `{key}`: v1={v1} v2={v2}")
        elif v1 != v2:
            issues.append(f"KPI `{key}`: v1={v1} v2={v2}")

    m1 = lead_in_matriz(d1)
    m2 = lead_in_matriz(d2)
    if not m1.equals(m2):
        issues.append(f"matriz difere:\nv1:\n{m1}\nv2:\n{m2}")

    sc1 = _status_counts(d1)
    sc2 = _status_counts(d2)
    if not sc1.equals(sc2):
        issues.append(f"status_reuniao (pós apply_pre) difere:\nv1:\n{sc1}\nv2:\n{sc2}")

    ag1, *_ = lead_in_preparar_agenda(d1, data_ini, data_fim)
    ag2, *_ = lead_in_preparar_agenda(d2, data_ini, data_fim)
    if len(ag1) != len(ag2):
        issues.append(f"agenda rows: v1={len(ag1)} v2={len(ag2)}")

    return issues


def validate_scenario(
    label: str,
    data_ini: date,
    data_fim: date,
) -> dict:
    print(f"\n{'=' * 72}", flush=True)
    print(f"CENÁRIO: {label} | {data_ini} → {data_fim}", flush=True)
    print(f"{'=' * 72}", flush=True)

    df_v1 = _load_lead_in_reunioes_consultas(data_ini, data_fim)
    df_v2 = _load_lead_in_reunioes_consultas_sql(
        "lead_in_reunioes_consultas_v2.sql", data_ini, data_fim,
    )
    print(f"  linhas v1={len(df_v1)} v2={len(df_v2)} | cols v1={list(df_v1.columns)}", flush=True)

    issues = _compare_frames(df_v1, df_v2)
    if not issues and not df_v1.empty:
        df_pre = get_prevendas_sdrs_oficiais()
        df_email = get_lead_in_email_sdr_lookup(data_ini, data_fim)
        issues.extend(_compare_downstream(df_v1, df_v2, df_pre, df_email, data_ini, data_fim))

    ok = len(issues) == 0
    if ok:
        print("  ✓ Equivalência OK (SQL + downstream)", flush=True)
    else:
        print(f"  ✗ {len(issues)} diferença(s):", flush=True)
        for i, msg in enumerate(issues, 1):
            print(f"    {i}. {msg}", flush=True)

    return {"scenario": label, "ok": ok, "issues": issues, "rows_v1": len(df_v1), "rows_v2": len(df_v2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="all")
    parser.add_argument("--hoje", default=None)
    args = parser.parse_args()

    hoje = date.fromisoformat(args.hoje) if args.hoje else HOJE
    scenarios = _init_scenarios(hoje)
    labels = list(scenarios.keys()) if args.scenario == "all" else [args.scenario]

    print("Validação v1 vs v2 — lead_in_reunioes_consultas", flush=True)
    print(f"Referência: {hoje.isoformat()}", flush=True)

    results = []
    for label in labels:
        if label not in scenarios:
            print(f"Cenário desconhecido: {label}", flush=True)
            continue
        di, df = scenarios[label]
        results.append(validate_scenario(label, di, df))

    print(f"\n{'#' * 72}", flush=True)
    print("# RESUMO", flush=True)
    all_ok = all(r["ok"] for r in results)
    for r in results:
        status = "OK" if r["ok"] else f"FALHA ({len(r['issues'])} difs)"
        print(f"  {r['scenario']}: {status} | rows v1={r['rows_v1']} v2={r['rows_v2']}", flush=True)
    print(f"\nResultado geral: {'EQUIVALENTE' if all_ok else 'DIFERENÇAS ENCONTRADAS'}", flush=True)


if __name__ == "__main__":
    main()
