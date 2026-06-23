#!/usr/bin/env python
"""Checkpoint Streamlit — Lead In & Reuniões com debug_perf=1.

Simula reruns da view com `?debug_perf=1` e períodos distintos via AppTest
(mesmo código da página, sem auth do app.py).

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\checkpoint_lead_in_streamlit.py
"""
from __future__ import annotations

import json
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

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ui.page import PERIOD_PRESET_KEY, PERIOD_RANGE_KEY  # noqa: E402

HOJE = date(2026, 6, 22)
PERF_KEY = "_lead_in_lead_in_reunioes_perf"
VIEW = ROOT / "views" / "lead_in_reunioes.py"

SCENARIOS: dict[str, tuple[date, date]] = {
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "mes_anterior": (date(2026, 5, 1), date(2026, 5, 31)),
    "ultimos_90_dias": (HOJE - timedelta(days=89), HOJE),
}


def _perf_state(at: AppTest) -> dict:
    try:
        return dict(at.session_state[PERF_KEY])
    except (KeyError, AttributeError):
        return {}


def _sql_prep_seconds(perf: dict) -> float:
    return sum(q.get("seconds", 0) for q in perf.get("queries") or [])


def _main_query(perf: dict) -> dict | None:
    for q in perf.get("queries") or []:
        if "consultas_v2" in q.get("name", ""):
            return q
    return None


def _slow_blocks(perf: dict, threshold: float = 1.0) -> list[dict]:
    slow: list[dict] = []
    for q in perf.get("queries") or []:
        if q.get("seconds", 0) >= threshold:
            slow.append({"kind": "query", "name": q["name"], "seconds": q["seconds"]})
    for b in perf.get("blocks") or []:
        if b.get("seconds", 0) >= threshold:
            slow.append({"kind": "block", "name": b["block"], "seconds": b["seconds"]})
    return sorted(slow, key=lambda x: -x["seconds"])


def _visual_checks(at: AppTest) -> dict[str, bool | str]:
    errs = [e.value for e in (at.error or [])]
    excs = [e.value for e in (at.exception or [])]
    has_err = bool(errs or excs)

    metrics = at.metric
    dataframes = at.dataframe
    expanders = at.expander
    charts = at.get("plotly_chart") or []

    checks = {
        "sem_erro_streamlit": not has_err,
        "cards_metric": len(metrics) >= 6,
        "matriz_dataframe": len(dataframes) >= 1,
        "rankings_dataframes": len(dataframes) >= 3,
        "agenda_plotly": len(charts) >= 1,
        "expander_detalhe": any("detalhe" in (e.label or "").lower() for e in expanders),
        "expander_diagnostico": any(
            "validação" in (e.label or "").lower() or "diagnóstico" in (e.label or "").lower()
            for e in expanders
        ),
        "expander_perf": any("performance" in (e.label or "").lower() for e in expanders),
    }
    if has_err:
        checks["erro"] = "; ".join(errs + excs)
    return checks


def run_scenario(label: str, data_ini: date, data_fim: date) -> dict:
    print(f"\n{'=' * 72}", flush=True)
    print(f"CENÁRIO: {label} | {data_ini} → {data_fim}", flush=True)
    print(f"{'=' * 72}", flush=True)

    at = AppTest.from_file(str(VIEW), default_timeout=900)
    at.query_params["debug_perf"] = "1"
    at.session_state[PERIOD_RANGE_KEY] = (data_ini, data_fim)
    at.session_state[PERIOD_PRESET_KEY] = "Personalizado"
    at.session_state["_global_period_initialized"] = True

    at.run(timeout=900)

    perf = _perf_state(at)
    main_q = _main_query(perf)
    visual = _visual_checks(at)
    slow = _slow_blocks(perf)

    result = {
        "scenario": label,
        "period": f"{data_ini}→{data_fim}",
        "page_total_seconds": perf.get("page_total_seconds"),
        "sql_prep_seconds": round(_sql_prep_seconds(perf), 4),
        "main_query": main_q,
        "slow_blocks": slow,
        "visual": visual,
        "queries": perf.get("queries") or [],
        "blocks": perf.get("blocks") or [],
        "milestones": perf.get("milestones") or {},
    }

    if main_q:
        print(
            f"  query principal: {main_q['name']} · {main_q['seconds']:.3f}s · "
            f"{main_q['rows']} linhas",
            flush=True,
        )
    else:
        print("  ⚠ query principal v2 não encontrada no perf", flush=True)

    print(f"  prep SQL (soma): {result['sql_prep_seconds']:.3f}s", flush=True)
    print(f"  tempo total página: {result['page_total_seconds']:.3f}s", flush=True)

    if slow:
        print("  blocos >= 1s:", flush=True)
        for s in slow:
            print(f"    - [{s['kind']}] {s['name']}: {s['seconds']:.3f}s", flush=True)
    else:
        print("  blocos >= 1s: nenhum", flush=True)

    ok_visual = all(v is True for k, v in visual.items() if k != "erro")
    print(f"  visual: {'OK' if ok_visual else 'REVISAR'}", flush=True)
    for k, v in visual.items():
        if k == "erro":
            print(f"    erro: {v}", flush=True)
        else:
            print(f"    {k}: {v}", flush=True)

    return result


def main() -> None:
    print("Checkpoint Streamlit — Lead In & Reuniões (?debug_perf=1)", flush=True)
    print(f"Referência: {HOJE.isoformat()}", flush=True)

    results = [run_scenario(l, di, df) for l, (di, df) in SCENARIOS.items()]

    print(f"\n{'#' * 72}", flush=True)
    print("# RESUMO CHECKPOINT", flush=True)
    print(f"{'#' * 72}", flush=True)
    print(f"{'cenário':<18} {'query v2':>9} {'prep SQL':>10} {'página':>10} {'visual':>8}", flush=True)
    print("-" * 72, flush=True)
    for r in results:
        mq = r["main_query"] or {}
        vok = all(v is True for k, v in r["visual"].items() if k != "erro")
        print(
            f"{r['scenario']:<18} "
            f"{mq.get('seconds', 0):9.3f}s "
            f"{r['sql_prep_seconds']:10.3f}s "
            f"{r.get('page_total_seconds') or 0:10.3f}s "
            f"{'OK' if vok else 'FAIL':>8}",
            flush=True,
        )

    out = ROOT / "scripts" / "checkpoint_lead_in_streamlit_results.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nDetalhes salvos em: {out}", flush=True)


if __name__ == "__main__":
    main()
