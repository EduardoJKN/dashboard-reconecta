#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Validação — benchmark histórico com same_interval (janelas parciais).

Uso:
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\validate_funil_benchmark_same_interval.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.funil_benchmark import compute_funil_benchmark, resolve_historical_base, ranges_to_cache_json
from src.one_page_funnel import (
    build_funnel_snapshot_for_window,
    load_benchmark_shared_frames,
)


def _metric_mean(raw: dict, key: str) -> float:
    metrics = raw.get("metrics") or {}
    entry = metrics.get(key) or {}
    return float(entry.get("mean") or 0)


def _check_partial_same_interval() -> tuple[bool, str]:
    hoje = date.today()
    page_ini = hoje.replace(day=1)
    page_fim = hoje
    spec = resolve_historical_base(
        page_ini, page_fim, base_key="90", same_interval=True,
    )
    if spec.hist_ini > spec.hist_fim:
        return False, f"hist_ini > hist_fim ({spec.hist_ini} > {spec.hist_fim})"
    if not spec.ranges:
        return False, "sem janelas"

    df_prev_w, df_exec_w, df_inv_w = load_benchmark_shared_frames(
        spec.hist_ini.isoformat(), spec.hist_fim.isoformat(),
    )
    snaps = []
    for ini, fim, _ in spec.ranges:
        snaps.append(
            build_funnel_snapshot_for_window(
                ini, fim,
                excluir_testes_aplicacoes=False,
                df_prev_wide=df_prev_w,
                df_exec_wide=df_exec_w,
                df_inv_wide=df_inv_w,
            )
        )
    ag_total = sum(s.agendamentos for s in snaps)
    cmp_total = sum(s.comparecimento for s in snaps)
    vend_total = sum(s.vendas for s in snaps)
    if ag_total <= 0:
        return False, f"agendamentos soma={ag_total}"
    if cmp_total <= 0:
        return False, f"comparecimentos soma={cmp_total}"
    if vend_total <= 0:
        return False, f"vendas soma={vend_total}"

    raw = compute_funil_benchmark(
        spec.hist_ini.isoformat(),
        spec.hist_fim.isoformat(),
        "90",
        False,
        ranges_to_cache_json(spec.ranges),
    )
    ag_mean = _metric_mean(raw, "agendamentos")
    vend_mean = _metric_mean(raw, "vendas")
    ticket_mean = _metric_mean(raw, "ticket")
    if ag_mean <= 0:
        return False, f"benchmark agendamentos mean={ag_mean}"
    if vend_mean <= 0:
        return False, f"benchmark vendas mean={vend_mean}"
    if ticket_mean <= 0:
        return False, f"benchmark ticket mean={ticket_mean}"
    return True, (
        f"ag={ag_mean:.0f} vendas={vend_mean:.0f} ticket={ticket_mean:.2f}"
    )


def _check_closed_month() -> tuple[bool, str]:
    hoje = date.today()
    page_ini = hoje.replace(day=1)
    page_fim = hoje
    spec = resolve_historical_base(
        page_ini, page_fim, base_key="90", same_interval=False,
    )
    if spec.hist_ini > spec.hist_fim:
        return False, f"hist_ini > hist_fim"
    raw = compute_funil_benchmark(
        spec.hist_ini.isoformat(),
        spec.hist_fim.isoformat(),
        "90",
        False,
        ranges_to_cache_json(spec.ranges),
    )
    ag_mean = _metric_mean(raw, "agendamentos")
    if ag_mean <= 0:
        return False, f"agendamentos mean={ag_mean}"
    return True, f"ag={ag_mean:.0f}"


def main() -> int:
    cases = [
        ("partial_same_interval", _check_partial_same_interval),
        ("closed_month", _check_closed_month),
    ]
    failed = 0
    for name, fn in cases:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, str(exc)
        status = "OK" if ok else "FAIL"
        print(f"{status:4} {name:24} {detail}")
        if not ok:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
