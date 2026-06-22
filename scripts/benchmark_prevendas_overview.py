#!/usr/bin/env python
"""Benchmark — Visão Geral Pré-vendas (somente leitura).

Mede o tempo das queries SQL e das transformações pandas que a página
`views/prevendas_overview.py` executa em um carregamento completo (cache
frio via `run_sql_file` direto, sem `@st.cache_data`).

Uso:
  python scripts/benchmark_prevendas_overview.py
  python scripts/benchmark_prevendas_overview.py --scenario mes_atual
  python scripts/benchmark_prevendas_overview.py --runs 3
"""
from __future__ import annotations

import argparse
import statistics
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

from src.db import run_sql_file  # noqa: E402
from src.prevendas_transforms import (  # noqa: E402
    prevendas_anotar_sdr,
    prevendas_anotar_tipo_sdr_detalhe,
    prevendas_diario_filtrado_por_sdr,
    prevendas_funil_etapas,
    prevendas_normalizar_detalhe,
    prevendas_overview_kpis,
    prevendas_ranking_sdr_oficiais,
)
from src.transforms import visao_geral_kpis  # noqa: E402 — só modo full legado

# Queries do carregamento completo legado (pré-CP1).
_AUDITORIA_DIA = date(2026, 6, 10)

PAGE_QUERIES_FULL: list[tuple[str, str, bool]] = [
    ("prevendas_overview_diario", "prevendas_overview_diario.sql", True),
    ("prevendas_leads_detalhe_diario", "prevendas_leads_detalhe_diario.sql", True),
    ("prevendas_por_sdr", "prevendas_por_sdr_v2.sql", True),
    ("prevendas_sdrs_oficiais", "prevendas_sdrs_oficiais.sql", False),
    ("prevendas_leads_por_origem", "prevendas_leads_por_origem.sql", True),
    ("mkt_visao_geral_periodo", "mkt_visao_geral_periodo.sql", True),
    ("investimento_diario", "investimento_diario.sql", True),
    ("dashboard_executivas", "dashboard_executivas.sql", True),
    (
        "prevendas_leads_detalhe_diario (auditoria jun/2026)",
        "prevendas_leads_detalhe_diario.sql",
        True,
    ),
    ("prevendas_oportunidades_sdr", "prevendas_oportunidades_sdr.sql", True),
    ("prevendas_cohort_leads", "prevendas_cohort_leads.sql", True),
]

# CP1 — primeiro paint (cards, funil, tendência, ranking).
# CP2 — sem dashboard_executivas (Investido usa só investimento_diario).
PAGE_QUERIES_INITIAL: list[tuple[str, str, bool]] = [
    q for q in PAGE_QUERIES_FULL
    if q[0] not in (
        "dashboard_executivas",
        "prevendas_leads_detalhe_diario (auditoria jun/2026)",
        "prevendas_oportunidades_sdr",
        "prevendas_cohort_leads",
    )
]

SCENARIO_ALIASES = {"ultimos_7_dias": "7_dias"}

SCENARIOS: dict[str, tuple[date, date]] = {}


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
        "mes_atual": (mes_ini, hoje),
        "mes_anterior": (mes_ant_ini, mes_ant_fim),
        "7_dias": (hoje - timedelta(days=6), hoje),
        "60_dias": (hoje - timedelta(days=59), hoje),
        "90_dias": (hoje - timedelta(days=89), hoje),
    })


def _params(data_ini: date, data_fim: date) -> dict:
    return {"data_ini": data_ini, "data_fim": data_fim}


def _audit_params() -> dict:
    d = _AUDITORIA_DIA
    return _params(
        date(d.year, d.month, 1),
        date(d.year, d.month, 30),
    )


def _run_sql(
    name: str,
    fname: str,
    *,
    dated: bool,
    data_ini: date,
    data_fim: date,
) -> dict:
    if "auditoria" in name:
        p = _audit_params()
    elif dated:
        p = _params(data_ini, data_fim)
    else:
        p = None

    t0 = time.perf_counter()
    df = run_sql_file(fname, p)
    elapsed = time.perf_counter() - t0
    return {
        "name": name,
        "file": fname,
        "seconds": elapsed,
        "rows": len(df),
        "cols": len(df.columns) if not df.empty else 0,
        "columns": list(df.columns),
        "df": df,
    }


def _postprocess_diario(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and "data_ref" in df.columns:
        df = df.copy()
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def _postprocess_detalhe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for col in ("data_agendamento", "data_criacao", "data_venda"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


def _postprocess_inv(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and "data_ref" in df.columns:
        df = df.copy()
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def _investido_kpis_cp2(df_inv: pd.DataFrame) -> dict:
    """Card Investido — CP2: só investimento_diario (sem executivas)."""
    if df_inv is None or df_inv.empty:
        return {"investimento": 0, "dias": 0}
    return {
        "investimento": float(df_inv["investimento_total"].sum()),
        "dias": int(pd.to_datetime(df_inv["data_ref"]).dt.date.nunique()),
    }


def _postprocess_executivas(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and "data_ref" in df.columns:
        df = df.copy()
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def _run_transforms(
    data_ini: date,
    data_fim: date,
    *,
    df_diario: pd.DataFrame,
    df_detalhe: pd.DataFrame,
    df_sdr: pd.DataFrame,
    df_sdrs_oficiais: pd.DataFrame,
    df_inv: pd.DataFrame,
    df_det_norm_base: pd.DataFrame,
    df_det_norm_global: pd.DataFrame,
    use_executivas_investido: bool = False,
    df_exec: pd.DataFrame | None = None,
) -> tuple[float, list[dict]]:
    steps: list[dict] = []

    def _step(label: str, fn):
        t0 = time.perf_counter()
        out = fn()
        steps.append({"name": label, "seconds": time.perf_counter() - t0})
        return out

    df_sdr_anotado = _step(
        "prevendas_anotar_sdr",
        lambda: prevendas_anotar_sdr(df_sdr),
    )
    _step(
        "prevendas_normalizar_detalhe (única)",
        lambda: df_det_norm_base,
    )
    _step(
        "prevendas_anotar_tipo_sdr_detalhe",
        lambda: df_det_norm_global,
    )
    df_diario_view = _step(
        "prevendas_diario_filtrado_por_sdr (sem filtro global)",
        lambda: df_diario,
    )
    k_origem = _step(
        "prevendas_overview_kpis (cards + funil)",
        lambda: prevendas_overview_kpis(df_diario_view),
    )
    _step(
        "prevendas_funil_etapas",
        lambda: prevendas_funil_etapas(k_origem),
    )
    df_sdr_filt = df_sdr_anotado
    _step(
        "prevendas_ranking_sdr_oficiais",
        lambda: prevendas_ranking_sdr_oficiais(df_sdr_filt, df_sdrs_oficiais),
    )
    if use_executivas_investido and df_exec is not None:
        _step(
            "visao_geral_kpis (investido legado)",
            lambda: visao_geral_kpis(df_exec, df_inv),
        )
    else:
        _step(
            "investido_kpis (CP2)",
            lambda: _investido_kpis_cp2(df_inv),
        )
    _step(
        "reuso df_det_norm_view (ranking)",
        lambda: df_det_norm_global,
    )
    _step(
        "reuso df_det_norm_global (tabela expander)",
        lambda: df_det_norm_global,
    )
    _step(
        "prevendas_diario_filtrado_por_sdr (expander tabela)",
        lambda: prevendas_diario_filtrado_por_sdr(
            df_det_norm_global, df_diario, [], [], data_ini, data_fim,
        ),
    )

    total = sum(s["seconds"] for s in steps)
    return total, steps


def benchmark_once(
    data_ini: date,
    data_fim: date,
    *,
    mode: str = "initial",
) -> dict:
    page_queries = (
        PAGE_QUERIES_INITIAL if mode == "initial" else PAGE_QUERIES_FULL
    )
    sql_details: list[dict] = []
    dfs: dict[str, pd.DataFrame] = {}
    sql_total = 0.0

    for name, fname, dated in page_queries:
        detail = _run_sql(name, fname, dated=dated, data_ini=data_ini, data_fim=data_fim)
        sql_total += detail["seconds"]
        sql_details.append({k: v for k, v in detail.items() if k != "df"})
        key = name.split(" ")[0]
        if key == "prevendas_leads_detalhe_diario" and "auditoria" in name:
            dfs["detalhe_audit"] = detail["df"]
        else:
            dfs.setdefault(key, detail["df"])

    df_diario = _postprocess_diario(dfs["prevendas_overview_diario"])
    df_detalhe = _postprocess_detalhe(dfs["prevendas_leads_detalhe_diario"])
    df_inv = _postprocess_inv(dfs.get("investimento_diario", pd.DataFrame()))
    use_exec = mode == "full" and "dashboard_executivas" in dfs
    df_exec = (
        _postprocess_executivas(dfs["dashboard_executivas"]) if use_exec else None
    )

    t_norm = time.perf_counter()
    df_det_norm_base = prevendas_normalizar_detalhe(df_detalhe)
    df_det_norm_global = prevendas_anotar_tipo_sdr_detalhe(df_det_norm_base)
    norm_seconds = time.perf_counter() - t_norm

    transform_total, transform_steps = _run_transforms(
        data_ini,
        data_fim,
        df_diario=df_diario,
        df_detalhe=df_detalhe,
        df_sdr=dfs["prevendas_por_sdr"],
        df_sdrs_oficiais=dfs["prevendas_sdrs_oficiais"],
        df_inv=df_inv,
        df_det_norm_base=df_det_norm_base,
        df_det_norm_global=df_det_norm_global,
        use_executivas_investido=use_exec,
        df_exec=df_exec,
    )

    transform_steps = [
        {"name": "normalizar+anotar (única)", "seconds": norm_seconds},
        *transform_steps,
    ]
    transform_total += norm_seconds

    prep_total = sql_total + transform_total
    slowest_sql = max(sql_details, key=lambda d: d["seconds"])
    slowest_tx = max(transform_steps, key=lambda d: d["seconds"])

    return {
        "mode": mode,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "sql_total": sql_total,
        "transform_total": transform_total,
        "prep_total": prep_total,
        "sql_details": sql_details,
        "transform_steps": transform_steps,
        "slowest_sql": slowest_sql,
        "slowest_tx": slowest_tx,
        "n_queries": len(sql_details),
    }


def _fmt_period(data_ini: date, data_fim: date) -> str:
    return f"{data_ini.isoformat()} → {data_fim.isoformat()}"


def _guess_bottleneck(result: dict) -> str:
    sql = result["sql_total"]
    tx = result["transform_total"]
    slow_sql = result["slowest_sql"]
    if sql >= tx * 2 and sql >= 1.0:
        return (
            f"SQL ({sql:.2f}s, {sql / result['prep_total'] * 100:.0f}% do prep) — "
            f"pior query: {slow_sql['name']} ({slow_sql['seconds']:.2f}s, "
            f"{slow_sql['rows']} rows)"
        )
    if tx >= sql * 1.5 and tx >= 0.3:
        return (
            f"Pandas ({tx:.2f}s) — pior etapa: {result['slowest_tx']['name']} "
            f"({result['slowest_tx']['seconds']:.2f}s)"
        )
    return (
        f"Misto SQL ({sql:.2f}s) + Pandas ({tx:.2f}s) — "
        f"SQL dominante: {slow_sql['name']}"
    )


def _suggestions(result: dict) -> list[str]:
    tips: list[str] = []
    by_name = {d["name"]: d for d in result["sql_details"]}
    det = by_name.get("prevendas_leads_detalhe_diario", {})
    det_audit = by_name.get("prevendas_leads_detalhe_diario (auditoria jun/2026)", {})
    overview = by_name.get("prevendas_overview_diario", {})
    por_sdr = by_name.get("prevendas_por_sdr", {})
    oport = by_name.get("prevendas_oportunidades_sdr", {})
    cohort = by_name.get("prevendas_cohort_leads", {})

    if det.get("seconds", 0) > 0.5:
        tips.append(
            "Reduzir custo de `prevendas_leads_detalhe_diario.sql` — linha-a-linha "
            f"({det.get('rows', 0)} rows). Reutilizar 1 carga; evitar 2ª query da auditoria."
        )
    if det_audit.get("seconds", 0) > 0.1:
        tips.append(
            "Mover auditoria temporária para lazy-load (só ao abrir expander) ou "
            "reutilizar `df_detalhe` quando o período da página cobrir o mês auditado."
        )
    if overview.get("seconds", 0) > por_sdr.get("seconds", 0):
        tips.append(
            "Avaliar `prevendas_overview_diario_v2.sql` com agregação já no SQL; "
            "manter query atual para regressão numérica."
        )
    if por_sdr.get("seconds", 0) > 0.3 and overview.get("seconds", 0) > 0.3:
        tips.append(
            "`prevendas_overview_diario` e `prevendas_por_sdr` compartilham CTEs "
            "pesados — candidatas a view materializada ou CTE comum."
        )
    if oport.get("seconds", 0) > 0.5:
        tips.append(
            "Adiar `prevendas_oportunidades_sdr` para expander/seção lazy ou "
            "cachear pivot Python separadamente."
        )
    if cohort.get("seconds", 0) > 0.5:
        tips.append(
            "Cohort (`prevendas_cohort_leads`) roda sempre com expander aberto — "
            "carregar sob demanda ao trocar base Leads/Oportunidades."
        )
    if result["transform_total"] > result["sql_total"] * 0.25:
        tips.append(
            "`prevendas_normalizar_detalhe` é chamado 3× na página — cachear "
            "resultado em variável única reutilizada."
        )
    if len(tips) < 3:
        tips.append(
            "Garantir `@st.cache_data` quente: 11 queries no 1º load; reruns "
            "devem pular SQL se período/filtros não mudarem."
        )
    return tips[:6]


def _print_scenario(label: str, result: dict) -> None:
    dias = (result["data_fim"] - result["data_ini"]).days + 1
    mode = result.get("mode", "initial")
    print(f"\n{'=' * 72}")
    print(f"CENÁRIO: {label} | modo: {mode}")
    print(f"Período: {_fmt_period(result['data_ini'], result['data_fim'])} ({dias} dias)")
    print(f"{'=' * 72}")

    print("\n--- SQL (cache frio) ---")
    for d in sorted(result["sql_details"], key=lambda x: -x["seconds"]):
        print(
            f"  {d['seconds']:7.3f}s  {d['rows']:6d} rows  {d['cols']:2d} cols  "
            f"{d['name']}"
        )
    print(
        f"  {'—' * 8}  TOTAL SQL: {result['sql_total']:.3f}s  "
        f"({result['n_queries']} queries)"
    )

    print("\n--- Transformações pandas (principais) ---")
    for s in sorted(result["transform_steps"], key=lambda x: -x["seconds"]):
        print(f"  {s['seconds']:7.3f}s  {s['name']}")
    print(f"  {'—' * 8}  TOTAL TRANSFORMS: {result['transform_total']:.3f}s")

    print("\n--- Resumo ---")
    print(f"  Preparação de dados (SQL + transforms): {result['prep_total']:.3f}s")
    print(f"  Gargalo provável: {_guess_bottleneck(result)}")

    print("\n--- Sugestões ---")
    for i, tip in enumerate(_suggestions(result), 1):
        print(f"  {i}. {tip}")

    # Amostra de colunas da query principal
    main = next(d for d in result["sql_details"] if d["name"] == "prevendas_overview_diario")
    cols = main.get("columns") or []
    if cols:
        shown = ", ".join(cols[:8])
        extra = f" … +{len(cols) - 8}" if len(cols) > 8 else ""
        print(f"\n  Colunas prevendas_overview_diario: {shown}{extra}")


def _stats(values: list[float]) -> dict:
    s = sorted(values)
    return {
        "p50": statistics.median(s),
        "mean": statistics.mean(s),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "all", "mes_atual", "mes_anterior", "7_dias",
            "ultimos_7_dias", "60_dias", "90_dias",
        ),
        default="all",
    )
    parser.add_argument(
        "--mode",
        choices=("initial", "full"),
        default="initial",
        help="initial = CP2 primeiro paint (7 queries); full = legado (11)",
    )
    parser.add_argument("--runs", type=int, default=1, help="Repetições por cenário")
    parser.add_argument(
        "--hoje",
        type=str,
        default=None,
        help="Data de referência ISO (default: hoje)",
    )
    args = parser.parse_args()

    hoje = date.fromisoformat(args.hoje) if args.hoje else date.today()
    _init_scenarios(hoje)

    labels = (
        list(SCENARIOS.keys())
        if args.scenario == "all"
        else [SCENARIO_ALIASES.get(args.scenario, args.scenario)]
    )

    page_queries = (
        PAGE_QUERIES_INITIAL if args.mode == "initial" else PAGE_QUERIES_FULL
    )
    print("Benchmark — Visão Geral Pré-vendas")
    print(f"Referência: {hoje.isoformat()} | runs/cenário: {args.runs} | modo: {args.mode}")
    print(f"Queries por load: {len(page_queries)}")

    for label in labels:
        data_ini, data_fim = SCENARIOS[label]
        runs: list[dict] = []
        for _ in range(args.runs):
            runs.append(benchmark_once(data_ini, data_fim, mode=args.mode))
        _print_scenario(label, runs[-1])
        if args.runs > 1:
            prep = [r["prep_total"] for r in runs]
            sql = [r["sql_total"] for r in runs]
            st_prep = _stats(prep)
            st_sql = _stats(sql)
            print(
                f"\n  [{args.runs} runs] prep p50={st_prep['p50']:.3f}s "
                f"mean={st_prep['mean']:.3f}s | "
                f"sql p50={st_sql['p50']:.3f}s mean={st_sql['mean']:.3f}s"
            )

    print(f"\n{'=' * 72}")
    print("FIM — use este baseline antes/depois das otimizações.")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
