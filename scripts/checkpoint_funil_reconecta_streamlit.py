#!/usr/bin/env python
"""Checkpoint Streamlit — Funil da Reconecta com debug_perf=1.

Simula reruns da view com `?debug_perf=1` e períodos distintos via AppTest.

CP8: suporte a carregamento paralelo experimental (FUNIL_PARALLEL_LOADS).

CP8.1: ativação controlada staging — parallel ON via env, workers clamp 1–4.

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\checkpoint_funil_reconecta_streamlit.py
  python scripts\\checkpoint_funil_reconecta_streamlit.py --runs 3
  $env:FUNIL_PARALLEL_LOADS="1"; $env:FUNIL_PARALLEL_WORKERS="3"
  python scripts\\checkpoint_funil_reconecta_streamlit.py
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ui.page import PERIOD_PRESET_KEY, PERIOD_RANGE_KEY  # noqa: E402

HOJE = date(2026, 6, 22)
PERF_KEY = "_funil_funil_reconecta_perf"
VIEW = ROOT / "views" / "funil_reconecta.py"

SCENARIOS: dict[str, tuple[date, date]] = {
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "mes_anterior": (date(2026, 5, 1), date(2026, 5, 31)),
    "recorte_jun_2026": (date(2026, 6, 1), date(2026, 6, 17)),
    "sem_dados": (date(2099, 1, 1), date(2099, 1, 7)),
}

CP7_1_BASELINE: dict[str, float] = {
    "ultimos_7_dias": 23.0,
    "mes_atual": 17.4,
    "mes_anterior": 19.3,
    "recorte_jun_2026": 17.5,
    "sem_dados": 17.6,
}


def _parallel_env() -> dict[str, Any]:
    from src.funil_parallel_load import funil_parallel_workers

    loads = os.environ.get("FUNIL_PARALLEL_LOADS", "0").strip()
    workers_raw = os.environ.get("FUNIL_PARALLEL_WORKERS", "").strip()
    enabled = loads.lower() in {"1", "true", "yes", "on"}
    resolved = funil_parallel_workers() if enabled else 0
    return {
        "FUNIL_PARALLEL_LOADS": loads,
        "FUNIL_PARALLEL_WORKERS": workers_raw or "(default 3)",
        "resolved_workers": resolved,
        "parallel_enabled": enabled,
    }


def _referencia_load_key(data_ini: date, data_fim: date) -> str:
    return f"funil_ref_meta_loaded_{data_ini.isoformat()}_{data_fim.isoformat()}"


def _perf_state(at: AppTest) -> dict[str, Any]:
    try:
        raw = at.session_state[PERF_KEY]
        return dict(raw) if isinstance(raw, dict) else {}
    except (KeyError, AttributeError, TypeError):
        return {}


def _block_seconds(perf: dict, *names: str) -> float | None:
    blocks = {b["block"]: b["seconds"] for b in (perf.get("blocks") or [])}
    for name in names:
        if name in blocks:
            return float(blocks[name])
    return None


def _summarize_run(
    perf: dict,
    *,
    mode: str,
    label: str,
    data_ini: date,
    data_fim: date,
) -> dict[str, Any]:
    milestones = perf.get("milestones") or {}
    main_t = perf.get("main_sections_seconds")
    if main_t is None:
        main_t = milestones.get("renderização seções principais")
    return {
        "mode": mode,
        "scenario": label,
        "period": f"{data_ini}→{data_fim}",
        "main_sections_seconds": main_t,
        "page_total_seconds": perf.get("page_total_seconds"),
        "funnel_load_count": perf.get("funnel_loads", 0),
        "query_count": len(perf.get("queries") or []),
        "referencia_loaded": bool(perf.get("referencia_loaded")),
        "referencia_skipped": bool(perf.get("referencia_skipped")),
        "export_prepared": bool(perf.get("export_prepared")),
        "benchmark": dict(perf.get("benchmark") or {}),
        "meta": dict(perf.get("meta") or {}),
        "legacy_benchmark_batch": dict(perf.get("legacy_benchmark_batch") or {}),
        "legacy": dict(perf.get("legacy") or {}),
        "legacy_runs": list(perf.get("legacy_runs") or []),
        "executivas": dict(perf.get("executivas") or {}),
        "parallel": dict(perf.get("parallel") or {}),
        "blocks": {
            "atual": _block_seconds(perf, "carregamento Atual real"),
            "meta": _block_seconds(perf, "carregamento Meta oficial"),
            "benchmark": _block_seconds(perf, "Benchmark histórico"),
            "referencia": _block_seconds(perf, "Referência histórica"),
            "export": _block_seconds(perf, "Export"),
        },
        "milestones": milestones,
        "queries": perf.get("queries") or [],
    }


def _run_apptest(
    data_ini: date,
    data_fim: date,
    *,
    load_referencia: bool = False,
) -> AppTest:
    at = AppTest.from_file(str(VIEW), default_timeout=900)
    at.query_params["debug_perf"] = "1"
    at.session_state[PERIOD_RANGE_KEY] = (data_ini, data_fim)
    at.session_state[PERIOD_PRESET_KEY] = "Personalizado"
    at.session_state["_global_period_initialized"] = True
    if load_referencia:
        at.session_state[_referencia_load_key(data_ini, data_fim)] = True
    at.run(timeout=900)
    return at


def _visual_checks(at: AppTest) -> dict[str, bool | str]:
    errs = [e.value for e in (at.error or [])]
    excs = [e.value for e in (at.exception or [])]
    has_err = bool(errs or excs)
    checks = {
        "sem_erro_streamlit": not has_err,
        "benchmark_dataframe": len(at.dataframe) >= 1,
        "controles_simulador": len(at.button) >= 3,
        "expander_perf": any(
            "performance" in (e.label or "").lower()
            or "funil da reconecta" in (e.label or "").lower()
            for e in (at.expander or [])
        ),
    }
    if has_err:
        checks["erro"] = "; ".join(errs + excs)
    return checks


def _print_row(name: str, row: dict[str, Any]) -> None:
    main_t = row.get("main_sections_seconds") or 0
    funil = row.get("funnel_load_count", 0)
    ref = "skip" if row.get("referencia_skipped") else (
        "load" if row.get("referencia_loaded") else "—"
    )
    export = "prep" if row.get("export_prepared") else "—"
    bm = row.get("benchmark") or {}
    bm_txt = ""
    if bm:
        batch_on = bm.get("legacy_benchmark_batch_enabled")
        batch_txt = "off" if batch_on is False else ("on" if batch_on else "?")
        bm_txt = (
            f"  bm={bm.get('version', '?')}"
            f"/q~{bm.get('repo_queries', '?')}"
            f"/leg={bm.get('legacy_benchmark_mode', '?')}"
            f"/batch={batch_txt}"
        )
    leg = row.get("legacy") or {}
    leg_txt = f"  leg={leg.get('version', '—')}" if leg else "  leg=—"
    ex = row.get("executivas") or {}
    ex_txt = f"  ex={ex.get('version', '—')}" if ex else "  ex=—"
    par = row.get("parallel") or {}
    par_txt = ""
    if par.get("parallel_enabled") is not None:
        par_txt = (
            f"  par={'on' if par.get('parallel_enabled') else 'off'}"
            f"/w={par.get('parallel_workers', '—')}"
            f"/fb={'yes' if par.get('parallel_fallback') else 'no'}"
        )
    print(
        f"  {name:<22} main={main_t:7.3f}s  funil={funil:2d}  "
        f"ref={ref}  exp={export}{bm_txt}{leg_txt}{ex_txt}{par_txt}",
        flush=True,
    )


def _print_blocks_detail(row: dict[str, Any], *, title: str = "blocos") -> None:
    blocks = row.get("blocks") or {}
    meta = row.get("meta") or {}
    bm = row.get("benchmark") or {}
    print(f"  [{title}]", flush=True)
    for key in ("atual", "meta", "benchmark", "referencia", "export"):
        val = blocks.get(key)
        if val is not None:
            print(f"    {key:12} {val:7.3f}s", flush=True)
    print(
        f"    meta_session_hit={meta.get('session_hit')}  "
        f"meta_cache_hit={meta.get('cache_hit')}  "
        f"legacy_bm={bm.get('legacy_benchmark_mode', 'per_window')}  "
        f"batch_enabled={bm.get('legacy_benchmark_batch_enabled', False)}",
        flush=True,
    )


def _cold_timing_stats(times: list[float]) -> dict[str, Any]:
    if not times:
        return {"runs": [], "median": 0.0, "min": 0.0, "max": 0.0}
    return {
        "runs": [round(t, 4) for t in times],
        "median": round(statistics.median(times), 4),
        "min": round(min(times), 4),
        "max": round(max(times), 4),
    }


def run_scenario(
    label: str,
    data_ini: date,
    data_fim: date,
    *,
    n_runs: int = 1,
) -> dict[str, Any]:
    print(f"\n{'=' * 72}", flush=True)
    print(f"CENÁRIO: {label} | {data_ini} → {data_fim}", flush=True)
    print(f"{'=' * 72}", flush=True)

    cold_runs: list[dict[str, Any]] = []
    for run_idx in range(n_runs):
        if n_runs > 1:
            print(f"  --- cold run {run_idx + 1}/{n_runs} ---", flush=True)
        at_cold = _run_apptest(data_ini, data_fim, load_referencia=False)
        perf_cold = _perf_state(at_cold)
        cold = _summarize_run(
            perf_cold,
            mode="cold_sem_referencia",
            label=label,
            data_ini=data_ini,
            data_fim=data_fim,
        )
        cold["visual"] = _visual_checks(at_cold)
        cold_runs.append(cold)
        if n_runs == 1:
            _print_row("cold_sem_referencia", cold)

    times = [float(c.get("main_sections_seconds") or 0) for c in cold_runs]
    timing = _cold_timing_stats(times)
    cold = cold_runs[-1]

    if n_runs > 1:
        for i, t in enumerate(times, start=1):
            print(f"  cold run{i:<17} main={t:7.3f}s", flush=True)
        print(
            f"  mediana              main={timing['median']:7.3f}s  "
            f"min={timing['min']:.3f}s  max={timing['max']:.3f}s",
            flush=True,
        )

    at_warm = _run_apptest(data_ini, data_fim, load_referencia=False)
    at_warm.run(timeout=900)
    perf_warm = _perf_state(at_warm)
    warm = _summarize_run(
        perf_warm,
        mode="warm_rerun",
        label=label,
        data_ini=data_ini,
        data_fim=data_fim,
    )
    _print_row("warm_rerun", warm)

    if n_runs == 1:
        at_ref = _run_apptest(data_ini, data_fim, load_referencia=True)
        perf_ref = _perf_state(at_ref)
        with_ref = _summarize_run(
            perf_ref,
            mode="cold_com_referencia",
            label=label,
            data_ini=data_ini,
            data_fim=data_fim,
        )
        _print_row("cold_com_referencia", with_ref)
    else:
        with_ref = {}

    cp71 = CP7_1_BASELINE.get(label)
    cold_main = timing["median"] if n_runs > 1 else (cold.get("main_sections_seconds") or 0)
    if cp71 is not None:
        delta = cold_main - cp71
        print(
            f"  CP7.1 baseline (run1) main={cp71:7.3f}s  "
            f"(Δ vs agora: {delta:+.3f}s)",
            flush=True,
        )

    if label == "sem_dados" or (timing["max"] - timing["min"] > 2.0 and n_runs > 1):
        _print_blocks_detail(cold, title="diagnóstico blocos (último cold)")

    ok = all(
        v is True for k, v in cold.get("visual", {}).items() if k != "erro"
    )
    print(f"  visual (cold sem ref): {'OK' if ok else 'REVISAR'}", flush=True)

    return {
        "scenario": label,
        "cp7_1_baseline_main_sections": cp71,
        "cold_timing": timing,
        "cold_sem_referencia": cold,
        "cold_runs": cold_runs if n_runs > 1 else None,
        "warm_rerun": warm,
        "cold_com_referencia": with_ref or None,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Checkpoint Funil da Reconecta")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Repetições do cold sem referência por cenário (default: 1)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    n_runs = max(1, int(args.runs))

    print("Checkpoint CP8.1 — Funil da Reconecta (?debug_perf=1)", flush=True)
    par_env = _parallel_env()
    print(
        f"Referência: {HOJE.isoformat()}  |  cold runs/cenário: {n_runs}  |  "
        f"parallel={'ON' if par_env['parallel_enabled'] else 'OFF'}  "
        f"workers={par_env.get('resolved_workers') or par_env['FUNIL_PARALLEL_WORKERS']}",
        flush=True,
    )

    results = [
        run_scenario(label, ini, fim, n_runs=n_runs)
        for label, (ini, fim) in SCENARIOS.items()
    ]

    print(f"\n{'#' * 72}", flush=True)
    print("# RESUMO CP8.1", flush=True)
    print(f"{'#' * 72}", flush=True)
    if n_runs > 1:
        hdr = (
            f"{'cenário':<18} {'CP7.1':>6} "
            + " ".join(f"{'r'+str(i):>6}" for i in range(1, n_runs + 1))
            + f" {'med':>6} {'min':>6} {'max':>6} {'warm':>6} {'visual':>7}"
        )
    else:
        hdr = (
            f"{'cenário':<18} {'CP7.1':>6} {'cold':>6} {'warm':>6} "
            f"{'meta':>5} {'visual':>7}"
        )
    print(hdr, flush=True)
    print("-" * 72, flush=True)

    for r in results:
        cold = r["cold_sem_referencia"]
        warm = r["warm_rerun"]
        timing = r.get("cold_timing") or {}
        vok = all(
            v is True for k, v in cold.get("visual", {}).items() if k != "erro"
        )
        cp71b = r.get("cp7_1_baseline_main_sections") or 0
        if n_runs > 1:
            runs = timing.get("runs") or []
            run_cols = " ".join(f"{t:6.1f}s" for t in runs)
            print(
                f"{r['scenario']:<18} "
                f"{cp71b:5.1f}s "
                f"{run_cols} "
                f"{timing.get('median', 0):5.1f}s "
                f"{timing.get('min', 0):5.1f}s "
                f"{timing.get('max', 0):5.1f}s "
                f"{warm.get('main_sections_seconds') or 0:5.1f}s "
                f"{'OK' if vok else 'FAIL':>7}",
                flush=True,
            )
        else:
            meta_blk = (cold.get("blocks") or {}).get("meta")
            print(
                f"{r['scenario']:<18} "
                f"{cp71b:5.1f}s "
                f"{cold.get('main_sections_seconds') or 0:5.1f}s "
                f"{warm.get('main_sections_seconds') or 0:5.1f}s "
                f"{meta_blk or 0:4.2f}s "
                f"{'OK' if vok else 'FAIL':>7}",
                flush=True,
            )

    payload = {
        "checkpoint": "CP8.1",
        "reference_date": HOJE.isoformat(),
        "cold_runs_per_scenario": n_runs,
        "cp7_1_baseline_main_sections": CP7_1_BASELINE,
        "parallel_env": par_env,
        "meta_cache_ttl_seconds": 600,
        "legacy_benchmark_batch_default": False,
        "scenarios": results,
    }
    out = ROOT / "scripts" / "checkpoint_funil_reconecta_results.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nDetalhes salvos em: {out}", flush=True)


if __name__ == "__main__":
    main()
