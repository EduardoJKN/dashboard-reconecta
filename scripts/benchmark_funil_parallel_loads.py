#!/usr/bin/env python
"""Benchmark CP8 — carregamento paralelo vs sequencial (cold).

Compara:
  1. Sequencial (FUNIL_PARALLEL_LOADS=0)
  2. Paralelo com 2, 3 e 4 workers

Nota sobre métricas de warm:
  - **warm_pagina_streamlit** (~0,05s): rerun completo da página com cache quente.
    Medido pelo checkpoint (`checkpoint_funil_reconecta_streamlit.py`), não aqui.
  - **warm_snapshot_cached**: neste script, tempo do 2º `load_one_page_funnel` no
    mesmo processo SEM limpar `st.cache_data` — só o bloco Atual/snapshot em cache.
    Não equivale ao warm da página inteira (Meta + Benchmark + vitrine).

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\benchmark_funil_parallel_loads.py
"""
from __future__ import annotations

import json
import os
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

from src.funil_benchmark import (  # noqa: E402
    build_equivalent_month_ranges,
    compute_funil_benchmark_v2,
    ranges_to_cache_json,
)
from src.one_page_funnel import (  # noqa: E402
    _load_one_page_funnel_cached,
    _load_one_page_funnel_impl,
    load_benchmark_shared_frames,
    load_one_page_funnel,
    snapshot_as_dict,
)
from src.repositories import get_one_page_legacy_diario_benchmark_batch_v2  # noqa: E402

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
    ("sem_dados", date(2099, 1, 1), date(2099, 1, 7)),
]
WORKER_COUNTS = (2, 3, 4)


def _clear_funnel_cache() -> None:
    _load_one_page_funnel_cached.clear()
    load_benchmark_shared_frames.clear()
    compute_funil_benchmark_v2.clear()
    get_one_page_legacy_diario_benchmark_batch_v2.clear()


def _set_parallel(enabled: bool, workers: int | None = None) -> None:
    if enabled:
        os.environ["FUNIL_PARALLEL_LOADS"] = "1"
        if workers is not None:
            os.environ["FUNIL_PARALLEL_WORKERS"] = str(workers)
        else:
            os.environ.pop("FUNIL_PARALLEL_WORKERS", None)
    else:
        os.environ["FUNIL_PARALLEL_LOADS"] = "0"
        os.environ.pop("FUNIL_PARALLEL_WORKERS", None)


def _bench_atual_cold(ini: date, fim: date) -> float:
    t0 = time.perf_counter()
    _load_one_page_funnel_impl(ini, fim, excluir_testes_aplicacoes=True)
    return time.perf_counter() - t0


def _bench_atual_warm_snapshot_cached(ini: date, fim: date) -> float:
    """2ª chamada a load_one_page_funnel com cache Atual já populado (não é warm da página)."""
    t0 = time.perf_counter()
    load_one_page_funnel(ini, fim, excluir_testes_aplicacoes=True)
    return time.perf_counter() - t0


def _bench_benchmark_v2(ini: date, fim: date) -> float:
    ranges = build_equivalent_month_ranges(ini, fim, 3)
    ranges_json = ranges_to_cache_json(ranges)
    hist_ini = min(r[0] for r in ranges)
    hist_fim = max(r[1] for r in ranges)
    t0 = time.perf_counter()
    compute_funil_benchmark_v2(
        hist_ini.isoformat(),
        hist_fim.isoformat(),
        "90",
        True,
        ranges_json,
    )
    return time.perf_counter() - t0


def _equiv_check(ini: date, fim: date) -> tuple[bool, str | None]:
    _set_parallel(False)
    _clear_funnel_cache()
    seq = snapshot_as_dict(
        _load_one_page_funnel_impl(ini, fim, excluir_testes_aplicacoes=True)
    )
    _clear_funnel_cache()
    _set_parallel(True, workers=3)
    try:
        par = snapshot_as_dict(
            _load_one_page_funnel_impl(ini, fim, excluir_testes_aplicacoes=True)
        )
    except Exception as exc:
        return False, str(exc)
    if seq != par:
        diff = {k: (seq.get(k), par.get(k)) for k in seq if seq.get(k) != par.get(k)}
        return False, f"diff_keys={list(diff.keys())[:5]}"
    return True, None


def main() -> None:
    print("Benchmark CP8 — paralelo vs sequencial (cold)")
    print("=" * 88)
    print(
        "Warm da página Streamlit (~0,05s): medir via checkpoint_funil_reconecta_streamlit.py"
    )
    print(
        "warm_snapshot_cached (abaixo): só 2º load_one_page_funnel com cache Atual — "
        "NÃO é warm da página inteira."
    )

    results: list[dict] = []

    for label, ini, fim in PERIODS:
        print(f"\n{label} ({ini} -> {fim})")
        row: dict = {"scenario": label, "period": f"{ini}->{fim}"}

        _set_parallel(False)
        _clear_funnel_cache()
        atual_seq = _bench_atual_cold(ini, fim)
        bm_seq = _bench_benchmark_v2(ini, fim)
        cold_seq = atual_seq + bm_seq
        row["sequential"] = {
            "atual": round(atual_seq, 3),
            "benchmark": round(bm_seq, 3),
            "cold_total": round(cold_seq, 3),
        }
        print(
            f"  sequencial  atual={atual_seq:6.2f}s  benchmark={bm_seq:6.2f}s  "
            f"cold_total={cold_seq:6.2f}s"
        )

        equiv_ok, equiv_err = _equiv_check(ini, fim)
        row["equivalence_ok"] = equiv_ok
        row["equivalence_error"] = equiv_err
        print(f"  equivalência atual seq vs par(3w): {'OK' if equiv_ok else 'FAIL'}")
        if equiv_err:
            print(f"    {equiv_err}")

        parallel_runs: dict[str, dict] = {}
        for w in WORKER_COUNTS:
            _set_parallel(True, workers=w)
            _clear_funnel_cache()
            try:
                atual_par = _bench_atual_cold(ini, fim)
                bm_par = _bench_benchmark_v2(ini, fim)
                cold_par = atual_par + bm_par
                warm_snap = _bench_atual_warm_snapshot_cached(ini, fim)
                pct = (cold_seq - cold_par) / cold_seq * 100 if cold_seq > 0 else 0.0
                parallel_runs[str(w)] = {
                    "atual": round(atual_par, 3),
                    "benchmark": round(bm_par, 3),
                    "cold_total": round(cold_par, 3),
                    "warm_snapshot_cached": round(warm_snap, 3),
                    "gain_pct": round(pct, 1),
                    "fallback": False,
                    "error": None,
                }
                print(
                    f"  paralelo w={w}  atual={atual_par:6.2f}s  benchmark={bm_par:6.2f}s  "
                    f"cold={cold_par:6.2f}s  warm_snapshot_cached={warm_snap:5.3f}s  "
                    f"ganho={pct:+.1f}%"
                )
            except Exception as exc:
                parallel_runs[str(w)] = {
                    "fallback": True,
                    "error": str(exc),
                }
                print(f"  paralelo w={w}  ERRO: {exc}")

        row["parallel"] = parallel_runs
        results.append(row)

    _set_parallel(False)
    out = ROOT / "scripts" / "benchmark_funil_parallel_results.json"
    out.write_text(
        json.dumps(
            {
                "reference_date": HOJE.isoformat(),
                "warm_notes": {
                    "warm_pagina_streamlit": (
                        "~0.05s — medir via checkpoint_funil_reconecta_streamlit.py"
                    ),
                    "warm_snapshot_cached": (
                        "2º load_one_page_funnel com st.cache_data do Atual — "
                        "não inclui Meta/Benchmark/vitrine"
                    ),
                },
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nDetalhes salvos em: {out}")


if __name__ == "__main__":
    main()
