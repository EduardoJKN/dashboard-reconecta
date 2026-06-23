#!/usr/bin/env python
"""Stress básico CP8.1 — paralelismo ON em staging/local.

Requer:
  FUNIL_PARALLEL_LOADS=1
  FUNIL_PARALLEL_WORKERS=3  (opcional; default clamp 1–4)

Executa N ciclos de AppTest na página Funil (cenários principais) e registra
fallback, erros e tempos. Não simula carga multi-usuário.

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  $env:FUNIL_PARALLEL_LOADS="1"
  $env:FUNIL_PARALLEL_WORKERS="3"
  python scripts\\stress_funil_parallel_staging.py
  python scripts\\stress_funil_parallel_staging.py --cycles 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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

from src.funil_parallel_load import (  # noqa: E402
    funil_parallel_loads_enabled,
    funil_parallel_workers,
)
from src.ui.page import PERIOD_PRESET_KEY, PERIOD_RANGE_KEY  # noqa: E402

HOJE = date(2026, 6, 22)
PERF_KEY = "_funil_funil_reconecta_perf"
VIEW = ROOT / "views" / "funil_reconecta.py"

SCENARIOS: dict[str, tuple[date, date]] = {
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "recorte_jun_2026": (date(2026, 6, 1), date(2026, 6, 17)),
    "sem_dados": (date(2099, 1, 1), date(2099, 1, 7)),
}


def _perf_state(at: AppTest) -> dict[str, Any]:
    try:
        raw = at.session_state[PERF_KEY]
        return dict(raw) if isinstance(raw, dict) else {}
    except (KeyError, AttributeError, TypeError):
        return {}


def _run_cold_warm(
    label: str,
    data_ini: date,
    data_fim: date,
) -> dict[str, Any]:
    at = AppTest.from_file(str(VIEW), default_timeout=900)
    at.query_params["debug_perf"] = "1"
    at.session_state[PERIOD_RANGE_KEY] = (data_ini, data_fim)
    at.session_state[PERIOD_PRESET_KEY] = "Personalizado"
    at.session_state["_global_period_initialized"] = True

    t0 = time.perf_counter()
    at.run(timeout=900)
    cold_elapsed = time.perf_counter() - t0
    perf_cold = _perf_state(at)
    errs = [e.value for e in (at.error or [])] + [
        e.value for e in (at.exception or [])
    ]

    t1 = time.perf_counter()
    at.run(timeout=900)
    warm_elapsed = time.perf_counter() - t1
    perf_warm = _perf_state(at)

    par_cold = perf_cold.get("parallel") or {}
    par_warm = perf_warm.get("parallel") or {}
    bm = perf_cold.get("benchmark") or {}

    return {
        "scenario": label,
        "cold_seconds": round(cold_elapsed, 3),
        "warm_seconds": round(warm_elapsed, 3),
        "main_sections_cold": perf_cold.get("main_sections_seconds"),
        "main_sections_warm": perf_warm.get("main_sections_seconds"),
        "parallel_enabled": par_cold.get("parallel_enabled"),
        "parallel_workers": par_cold.get("parallel_workers"),
        "parallel_fallback": bool(
            par_cold.get("parallel_fallback") or par_warm.get("parallel_fallback")
        ),
        "parallel_fallback_error": par_cold.get("parallel_fallback_error")
        or par_warm.get("parallel_fallback_error"),
        "legacy_benchmark_batch_enabled": bm.get("legacy_benchmark_batch_enabled"),
        "streamlit_errors": errs,
        "visual_ok": not errs
        and len(at.dataframe) >= 1
        and len(at.button) >= 3,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stress Funil paralelo staging")
    p.add_argument("--cycles", type=int, default=5, help="Ciclos completos (default 5)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cycles = max(1, int(args.cycles))

    if not funil_parallel_loads_enabled():
        print(
            "AVISO: FUNIL_PARALLEL_LOADS não está ON. "
            "Defina FUNIL_PARALLEL_LOADS=1 antes de rodar.",
            flush=True,
        )

    workers = funil_parallel_workers()
    print("Stress CP8.1 — Funil paralelo staging", flush=True)
    print(
        f"parallel={'ON' if funil_parallel_loads_enabled() else 'OFF'}  "
        f"workers={workers} (resolved)  cycles={cycles}",
        flush=True,
    )
    print("-" * 72, flush=True)

    all_cycles: list[dict] = []
    any_fail = False

    for cycle in range(1, cycles + 1):
        print(f"\n### Ciclo {cycle}/{cycles} ###", flush=True)
        cycle_t0 = time.perf_counter()
        cycle_rows: list[dict] = []

        for label, (ini, fim) in SCENARIOS.items():
            try:
                row = _run_cold_warm(label, ini, fim)
            except Exception as exc:
                row = {
                    "scenario": label,
                    "error": str(exc),
                    "parallel_fallback": True,
                    "visual_ok": False,
                }
                any_fail = True
            cycle_rows.append(row)

            fb = row.get("parallel_fallback")
            batch = row.get("legacy_benchmark_batch_enabled")
            err = row.get("streamlit_errors") or row.get("error")
            status = "OK" if row.get("visual_ok") and not fb and not err else "FAIL"
            if status != "OK":
                any_fail = True
            print(
                f"  {label:<18} cold={row.get('main_sections_cold') or row.get('cold_seconds', 0):6.2f}s  "
                f"warm={row.get('main_sections_warm') or row.get('warm_seconds', 0):5.2f}s  "
                f"fb={'yes' if fb else 'no':3}  batch={'on' if batch else 'off':3}  {status}",
                flush=True,
            )
            if err:
                print(f"    erro: {err}", flush=True)

        cycle_elapsed = time.perf_counter() - cycle_t0
        all_cycles.append(
            {
                "cycle": cycle,
                "elapsed_seconds": round(cycle_elapsed, 2),
                "scenarios": cycle_rows,
            }
        )

    summary = {
        "checkpoint": "CP8.1_stress",
        "reference_date": HOJE.isoformat(),
        "parallel_env": {
            "FUNIL_PARALLEL_LOADS": os.environ.get("FUNIL_PARALLEL_LOADS", "0"),
            "FUNIL_PARALLEL_WORKERS": os.environ.get("FUNIL_PARALLEL_WORKERS", ""),
            "resolved_workers": workers,
            "parallel_enabled": funil_parallel_loads_enabled(),
        },
        "cycles": cycles,
        "all_passed": not any_fail,
        "results": all_cycles,
    }

    out = ROOT / "scripts" / "stress_funil_parallel_staging_results.json"
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print(f"\n{'=' * 72}", flush=True)
    print(f"Resultado geral: {'PASS' if not any_fail else 'FAIL'}", flush=True)
    print(f"Detalhes: {out}", flush=True)

    sys.exit(0 if not any_fail else 1)


if __name__ == "__main__":
    main()
