#!/usr/bin/env python
"""Benchmark — Lead In & Reuniões (somente leitura).

Mede queries e transforms de `views/lead_in_reunioes.py` fora do Streamlit
(sem `@st.cache_data`).

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\benchmark_vendas_lead_in_reunioes.py

  python scripts\\benchmark_vendas_lead_in_reunioes.py --scenario mes_atual --runs 3
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd  # noqa: E402

from src.db import run_sql_file  # noqa: E402
from src.lead_in_transforms import (  # noqa: E402
    lead_in_aplicar_pre,
    lead_in_churn_preparar,
    lead_in_diagnostico,
    lead_in_kpis,
    lead_in_matriz,
    lead_in_preparar_agenda,
    lead_in_ranking_closer_com_churn,
    lead_in_ranking_pre_com_churn,
)
from src.transforms import churn_pos_filtrar_periodo  # noqa: E402

HOJE = date(2026, 6, 22)
DEFAULT_RUNS = 3

SCENARIOS: dict[str, tuple[date, date]] = {}
SCENARIO_ALIASES = {
    "7_dias": "ultimos_7_dias",
    "90_dias": "ultimos_90_dias",
}


@dataclass
class BlockResult:
    name: str
    scenario: str
    data_ini: date
    data_fim: date
    times: list[float] = field(default_factory=list)
    rows: int | None = None
    cols: int | None = None
    shape: tuple[int, int] | None = None
    extra: str = ""

    @property
    def mean(self) -> float:
        return statistics.mean(self.times) if self.times else 0.0

    @property
    def p50(self) -> float:
        return statistics.median(self.times) if self.times else 0.0

    @property
    def kind(self) -> str:
        return "SQL" if self.name.startswith("get_") or self.name.startswith("sql:") else "pandas"


def _init_scenarios(hoje: date | None = None) -> None:
    hoje = hoje or date.today()
    mes_ini = hoje.replace(day=1)
    if mes_ini.month == 1:
        mes_ant_ini = date(hoje.year - 1, 12, 1)
        mes_ant_fim = date(hoje.year - 1, 12, 31)
    else:
        mes_ant_ini = date(hoje.year, hoje.month - 1, 1)
        prox = mes_ant_ini.replace(day=28) + timedelta(days=4)
        mes_ant_fim = prox.replace(day=1) - timedelta(days=1)

    SCENARIOS.clear()
    SCENARIOS.update({
        "ultimos_7_dias": (hoje - timedelta(days=6), hoje),
        "mes_atual": (mes_ini, hoje),
        "mes_anterior": (mes_ant_ini, mes_ant_fim),
        "ultimos_90_dias": (hoje - timedelta(days=89), hoje),
    })


def _params(data_ini: date, data_fim: date) -> dict:
    return {"data_ini": data_ini, "data_fim": data_fim}


def _shape_of(obj: Any) -> tuple[int, int] | None:
    if isinstance(obj, pd.DataFrame):
        return obj.shape
    if isinstance(obj, tuple):
        for item in obj:
            if isinstance(item, pd.DataFrame):
                return item.shape
    return None


def _rows_of(obj: Any, *, fallback: int | None = None) -> int | None:
    if isinstance(obj, pd.DataFrame):
        return len(obj)
    if isinstance(obj, dict):
        for key in ("total", "total_consultas", "agendadas"):
            if key in obj and isinstance(obj[key], (int, float)):
                return int(obj[key])
        return len(obj)
    if isinstance(obj, tuple):
        sh = _shape_of(obj)
        return sh[0] if sh else fallback
    return fallback


def _cols_of(obj: Any) -> int | None:
    if isinstance(obj, pd.DataFrame):
        return len(obj.columns)
    if isinstance(obj, tuple):
        sh = _shape_of(obj)
        return sh[1] if sh else None
    return None


def _bench_block(
    name: str,
    scenario: str,
    data_ini: date,
    data_fim: date,
    fn: Callable[[], Any],
    *,
    runs: int,
    rows_hint: int | None = None,
) -> tuple[BlockResult, Any]:
    result = BlockResult(
        name=name,
        scenario=scenario,
        data_ini=data_ini,
        data_fim=data_fim,
    )
    last_out: Any = None
    for _ in range(runs):
        t0 = time.perf_counter()
        last_out = fn()
        result.times.append(time.perf_counter() - t0)

    result.rows = _rows_of(last_out, fallback=rows_hint)
    result.cols = _cols_of(last_out)
    result.shape = _shape_of(last_out)
    return result, last_out


def _load_lead_in_reunioes_consultas(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _load_lead_in_reunioes_consultas_file(
        "lead_in_reunioes_consultas.sql", data_ini, data_fim,
    )


def _load_lead_in_reunioes_consultas_v2(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _load_lead_in_reunioes_consultas_file(
        "lead_in_reunioes_consultas_v2.sql", data_ini, data_fim,
    )


def _load_lead_in_reunioes_consultas_file(
    sql_file: str, data_ini: date, data_fim: date,
) -> pd.DataFrame:
    df = run_sql_file(sql_file, _params(data_ini, data_fim))
    if df.empty:
        return df
    for col in (
        "data_reuniao",
        "ts_reuniao",
        "data_criacao_agendamento",
        "start_datetime",
        "end_datetime",
    ):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


def _load_lead_in_email_sdr_lookup(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file("lead_in_email_sdr_lookup.sql", _params(data_ini, data_fim))
    if not df.empty and "ts_vinculo" in df.columns:
        df["ts_vinculo"] = pd.to_datetime(df["ts_vinculo"])
    return df


def _load_executivas_churn_pos_venda() -> pd.DataFrame:
    df = run_sql_file("executivas_churn_pos_venda.sql")
    if not df.empty:
        for col in ("data_churn", "ultimo_contato_pos", "ts_churn"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def benchmark_scenario(
    scenario: str,
    data_ini: date,
    data_fim: date,
    *,
    runs: int,
    compare_consultas: bool = False,
    consultas_only: bool = False,
) -> list[BlockResult]:
    results: list[BlockResult] = []
    dias = (data_fim - data_ini).days + 1

    print(f"\n{'=' * 78}", flush=True)
    print(f"CENÁRIO: {scenario}", flush=True)
    print(f"Período: {data_ini} → {data_fim} ({dias} dias) | runs por bloco: {runs}", flush=True)
    print(f"{'=' * 78}", flush=True)

    # ------------------------------------------------------------------
    # SQL / repositories
    # ------------------------------------------------------------------
    print("\n--- SQL / repositories ---", flush=True)

    sql_blocks: list[tuple[str, Callable[[], pd.DataFrame], bool]] = [
        (
            "get_lead_in_reunioes_consultas (v1)",
            lambda: _load_lead_in_reunioes_consultas(data_ini, data_fim),
            True,
        ),
    ]
    if compare_consultas or consultas_only:
        sql_blocks.append((
            "get_lead_in_reunioes_consultas_v2 (v2)",
            lambda: _load_lead_in_reunioes_consultas_v2(data_ini, data_fim),
            True,
        ))
    if not consultas_only:
        sql_blocks.extend([
            (
                "get_lead_in_email_sdr_lookup",
                lambda: _load_lead_in_email_sdr_lookup(data_ini, data_fim),
                True,
            ),
            ("get_prevendas_sdrs_oficiais", lambda: run_sql_file("prevendas_sdrs_oficiais.sql"), False),
            ("get_executivas_churn_pos_venda", _load_executivas_churn_pos_venda, False),
            ("get_executivas_oficiais", lambda: run_sql_file("executivas_oficiais.sql"), False),
            ("get_lead_in_churn_deal_pre", lambda: run_sql_file("lead_in_churn_deal_pre.sql"), False),
        ])

    loaded: dict[str, pd.DataFrame] = {}
    for name, loader, dated in sql_blocks:
        br, df_loaded = _bench_block(name, scenario, data_ini, data_fim, loader, runs=runs)
        results.append(br)
        loaded[name] = df_loaded if isinstance(df_loaded, pd.DataFrame) else pd.DataFrame()
        period_note = f"{data_ini}→{data_fim}" if dated else "sem filtro de período"
        _print_block(br, period_note)

    if compare_consultas or consultas_only:
        v1 = next((r for r in results if "v1" in r.name), None)
        v2 = next((r for r in results if "v2" in r.name), None)
        if v1 and v2 and v1.mean > 0:
            gain = (1 - v2.mean / v1.mean) * 100
            print(
                f"\n  >>> consultas v1 vs v2: "
                f"v1={v1.mean:.3f}s v2={v2.mean:.3f}s | "
                f"ganho={gain:.1f}% | rows v1={v1.rows} v2={v2.rows}",
                flush=True,
            )

    if consultas_only:
        return results

    df_raw = loaded.get("get_lead_in_reunioes_consultas (v1)", pd.DataFrame())
    df_pre = loaded["get_prevendas_sdrs_oficiais"]
    df_email_sdr = loaded["get_lead_in_email_sdr_lookup"]
    df_churn_all = loaded["get_executivas_churn_pos_venda"]
    df_oficiais = loaded["get_executivas_oficiais"]
    df_churn_deal_pre = loaded["get_lead_in_churn_deal_pre"]

    print(
        f"\n  DataFrames principais (após carga): "
        f"consultas={df_raw.shape} | email_sdr={df_email_sdr.shape} | "
        f"churn_all={df_churn_all.shape} | churn_deal_pre={df_churn_deal_pre.shape}",
        flush=True,
    )

    if df_raw.empty:
        print("\n  ⚠ Sem consultas no período — transforms dependentes serão pulados.", flush=True)
        return results

    # ------------------------------------------------------------------
    # Pandas / transforms
    # ------------------------------------------------------------------
    print("\n--- Pandas / transforms ---", flush=True)

    br_churn_filt, df_churn_period = _bench_block(
        "churn_pos_filtrar_periodo",
        scenario,
        data_ini,
        data_fim,
        lambda: churn_pos_filtrar_periodo(df_churn_all, data_ini, data_fim),
        runs=runs,
        rows_hint=len(df_churn_all),
    )
    results.append(br_churn_filt)
    _print_block(br_churn_filt, f"{data_ini}→{data_fim}")
    if not isinstance(df_churn_period, pd.DataFrame):
        df_churn_period = churn_pos_filtrar_periodo(df_churn_all, data_ini, data_fim)

    br_aplicar, df = _bench_block(
        "lead_in_aplicar_pre (dataframe principal)",
        scenario,
        data_ini,
        data_fim,
        lambda: lead_in_aplicar_pre(df_raw.copy(), df_pre, df_email_sdr),
        runs=runs,
        rows_hint=len(df_raw),
    )
    results.append(br_aplicar)
    _print_block(br_aplicar, f"{data_ini}→{data_fim}")
    if not isinstance(df, pd.DataFrame):
        df = lead_in_aplicar_pre(df_raw, df_pre, df_email_sdr)

    transform_blocks: list[tuple[str, Callable[[], Any]]] = [
        ("lead_in_kpis", lambda: lead_in_kpis(df)),
        ("lead_in_diagnostico", lambda: lead_in_diagnostico(df, df_pre)),
        ("lead_in_matriz", lambda: lead_in_matriz(df)),
        (
            "lead_in_churn_preparar",
            lambda: lead_in_churn_preparar(
                df_churn_period, df_churn_deal_pre, df_pre, df_email_sdr,
            ),
        ),
        (
            "lead_in_ranking_closer_com_churn",
            lambda: lead_in_ranking_closer_com_churn(df, df_churn_period, df_oficiais),
        ),
        (
            "lead_in_ranking_pre_com_churn",
            lambda: lead_in_ranking_pre_com_churn(
                df, df_churn_period, df_pre, df_email_sdr, df_churn_deal_pre,
            ),
        ),
        (
            "lead_in_preparar_agenda",
            lambda: lead_in_preparar_agenda(df, data_ini, data_fim),
        ),
    ]

    for name, fn in transform_blocks:
        br, _ = _bench_block(
            name,
            scenario,
            data_ini,
            data_fim,
            fn,
            runs=runs,
            rows_hint=len(df),
        )
        results.append(br)
        _print_block(br, f"{data_ini}→{data_fim}")

    sql_total = sum(r.mean for r in results if r.kind == "SQL")
    pandas_total = sum(r.mean for r in results if r.kind == "pandas")
    print(f"\n--- Totais médios do cenário ---", flush=True)
    print(f"  SQL (soma das médias):     {sql_total:.3f}s", flush=True)
    print(f"  Pandas (soma das médias):  {pandas_total:.3f}s", flush=True)
    print(f"  Preparação estimada:       {sql_total + pandas_total:.3f}s", flush=True)

    return results


def _print_block(br: BlockResult, period_note: str) -> None:
    times_fmt = " | ".join(f"{t:.3f}s" for t in br.times)
    shape_s = f" shape={br.shape}" if br.shape else ""
    cols_s = f" cols={br.cols}" if br.cols is not None else ""
    rows_s = br.rows if br.rows is not None else "—"
    print(
        f"  {br.name}\n"
        f"    período: {period_note}\n"
        f"    execuções: {times_fmt}\n"
        f"    média: {br.mean:.3f}s | p50: {br.p50:.3f}s | "
        f"linhas: {rows_s}{cols_s}{shape_s}",
        flush=True,
    )


def _print_global_summary(all_results: list[BlockResult]) -> None:
    print(f"\n{'#' * 78}", flush=True)
    print("# RESUMO GLOBAL — blocos ordenados por tempo médio (mais lento primeiro)", flush=True)
    print(f"{'#' * 78}", flush=True)

    by_key: dict[tuple[str, str], list[BlockResult]] = {}
    for r in all_results:
        by_key.setdefault((r.scenario, r.name), []).append(r)

    aggregated: list[dict[str, Any]] = []
    for r in all_results:
        aggregated.append({
            "scenario": r.scenario,
            "name": r.name,
            "kind": r.kind,
            "mean": r.mean,
            "p50": r.p50,
            "times": r.times,
            "rows": r.rows,
            "shape": r.shape,
            "period": f"{r.data_ini}→{r.data_fim}",
        })

    aggregated.sort(key=lambda x: -x["mean"])

    print(
        f"\n{'#':>3}  {'tipo':<6}  {'média':>7}  {'p50':>7}  "
        f"{'linhas':>8}  {'shape':<14}  cenário / bloco",
        flush=True,
    )
    print("-" * 78, flush=True)
    for i, row in enumerate(aggregated, 1):
        shape_s = str(row["shape"]) if row["shape"] else "—"
        rows_s = str(row["rows"]) if row["rows"] is not None else "—"
        times_s = ", ".join(f"{t:.3f}" for t in row["times"])
        print(
            f"{i:3d}  {row['kind']:<6}  {row['mean']:7.3f}s  {row['p50']:7.3f}s  "
            f"{rows_s:>8}  {shape_s:<14}  {row['scenario']} / {row['name']}",
            flush=True,
        )
        print(f"      exec: [{times_s}]  período: {row['period']}", flush=True)

    # Top offenders across scenarios (same block name, max mean)
    by_name: dict[str, list[float]] = {}
    for row in aggregated:
        by_name.setdefault(row["name"], []).append(row["mean"])

    print(f"\n--- Top 10 blocos (maior média em qualquer cenário) ---", flush=True)
    top = sorted(
        ((name, max(means), statistics.mean(means)) for name, means in by_name.items()),
        key=lambda x: -x[1],
    )[:10]
    for i, (name, peak, avg) in enumerate(top, 1):
        print(f"  {i:2d}. {name:<42} pico={peak:.3f}s  média cenários={avg:.3f}s", flush=True)

    sql_blocks = [r for r in aggregated if r["kind"] == "SQL"]
    pd_blocks = [r for r in aggregated if r["kind"] == "pandas"]
    if sql_blocks and pd_blocks:
        sql_sum = sum(r["mean"] for r in sql_blocks) / len({r["scenario"] for r in sql_blocks})
        pd_sum = sum(r["mean"] for r in pd_blocks) / len({r["scenario"] for r in pd_blocks})
        print(f"\n--- Hipótese de camada dominante (média por cenário) ---", flush=True)
        print(f"  SQL agregado (~soma médias/cenário):    {sql_sum:.3f}s", flush=True)
        print(f"  Pandas agregado (~soma médias/cenário): {pd_sum:.3f}s", flush=True)
        if sql_sum > pd_sum * 1.5:
            print("  → Gargalo provável: SQL", flush=True)
        elif pd_sum > sql_sum * 1.5:
            print("  → Gargalo provável: Pandas", flush=True)
        else:
            print("  → Gargalo misto SQL + Pandas", flush=True)


def _print_consultas_comparison(all_results: list[BlockResult]) -> None:
    pairs: dict[str, dict[str, BlockResult]] = {}
    for r in all_results:
        if "v1" in r.name:
            pairs.setdefault(r.scenario, {})["v1"] = r
        elif "v2" in r.name:
            pairs.setdefault(r.scenario, {})["v2"] = r
    if not pairs or not any("v1" in p and "v2" in p for p in pairs.values()):
        return
    print(f"\n{'#' * 78}", flush=True)
    print("# COMPARAÇÃO consultas v1 vs v2", flush=True)
    print(f"{'#' * 78}", flush=True)
    print(f"{'cenário':<20} {'v1 média':>10} {'v2 média':>10} {'ganho':>8} {'rows':>12}", flush=True)
    print("-" * 78, flush=True)
    for scenario, p in sorted(pairs.items()):
        if "v1" not in p or "v2" not in p:
            continue
        v1, v2 = p["v1"], p["v2"]
        gain = (1 - v2.mean / v1.mean) * 100 if v1.mean else 0.0
        rows_ok = "✓" if v1.rows == v2.rows else f"{v1.rows}/{v2.rows}"
        print(
            f"{scenario:<20} {v1.mean:10.3f}s {v2.mean:10.3f}s {gain:7.1f}% {rows_ok:>12}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="all", help="all | ultimos_7_dias | mes_atual | …")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--hoje", type=str, default=None, help="YYYY-MM-DD (default: HOJE fixo)")
    parser.add_argument(
        "--compare-consultas",
        action="store_true",
        help="Mede v1 e v2 da query principal lado a lado",
    )
    parser.add_argument(
        "--consultas-only",
        action="store_true",
        help="Benchmark só da query consultas v1/v2 (rápido)",
    )
    args = parser.parse_args()

    compare = args.compare_consultas or args.consultas_only

    hoje = date.fromisoformat(args.hoje) if args.hoje else HOJE
    _init_scenarios(hoje)

    if args.scenario == "all":
        labels = list(SCENARIOS.keys())
    else:
        labels = [SCENARIO_ALIASES.get(args.scenario, args.scenario)]

    print("Benchmark — Lead In & Reuniões (somente leitura)", flush=True)
    print(f"Referência: {hoje.isoformat()} | runs por bloco: {args.runs}", flush=True)
    print(f"Cenários: {', '.join(labels)}", flush=True)
    if compare:
        print("Modo: comparação consultas v1 vs v2", flush=True)

    all_results: list[BlockResult] = []
    for label in labels:
        if label not in SCENARIOS:
            print(f"Cenário desconhecido: {label}")
            continue
        di, df = SCENARIOS[label]
        all_results.extend(
            benchmark_scenario(
                label, di, df,
                runs=args.runs,
                compare_consultas=compare,
                consultas_only=args.consultas_only,
            )
        )

    if compare:
        _print_consultas_comparison(all_results)
    if not args.consultas_only:
        _print_global_summary(all_results)

    print(f"\n{'=' * 78}", flush=True)
    print("FIM", flush=True)
    print(f"{'=' * 78}", flush=True)


if __name__ == "__main__":
    main()
