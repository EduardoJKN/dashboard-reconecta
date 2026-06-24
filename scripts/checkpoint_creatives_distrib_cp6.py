#!/usr/bin/env python
"""CP6 — verifica Distribuições renderizadas 1x + timer debug_perf."""
from __future__ import annotations

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

from streamlit.testing.v1 import AppTest

from src.ui.page import PERIOD_PRESET_KEY, PERIOD_RANGE_KEY

HOJE = date(2026, 6, 23)
PERF_KEY = "_mkt_marketing_creatives_perf"
VIEW = ROOT / "views" / "marketing_creatives.py"


def _perf_state(at: AppTest) -> dict:
    try:
        return dict(at.session_state[PERF_KEY])
    except (KeyError, AttributeError):
        return {}


def main() -> None:
    di, df = HOJE - timedelta(days=6), HOJE
    print(f"AppTest Criativos ?debug_perf=1 | {di} -> {df}", flush=True)

    at = AppTest.from_file(str(VIEW), default_timeout=900)
    at.query_params["debug_perf"] = "1"
    at.session_state[PERIOD_RANGE_KEY] = (di, df)
    at.session_state[PERIOD_PRESET_KEY] = "Personalizado"
    at.session_state["_global_period_initialized"] = True
    at.run(timeout=900)

    # section_title renderiza HTML com class sec-title
    md_vals = [str(m.value) for m in (at.markdown or [])]
    sec_titles = [v for v in md_vals if "sec-title" in v]
    count_status = sum(1 for v in sec_titles if ">Por status" in v or ">Por status<" in v)
    count_quality = sum(1 for v in sec_titles if "Por quality ranking" in v)

    perf = _perf_state(at)
    dist_blocks = [
        b for b in (perf.get("blocks") or [])
        if "distribuicoes" in b.get("block", "").lower()
    ]
    errs = [e.value for e in (at.error or [])] + [e.value for e in (at.exception or [])]

    print("\n--- Visual ---")
    print(f"  'Por status' mentions: {count_status} (expect 1)")
    print(f"  'Por quality ranking' mentions: {count_quality} (expect 1)")
    print(f"  plotly charts: {len(at.get('plotly_chart') or [])}")
    print(f"  streamlit errors: {len(errs)}")

    print("\n--- Perf (blocos Distribuicoes) ---")
    for b in dist_blocks:
        print(f"  {b['block']}: {b['seconds']:.3f}s")
    if not dist_blocks:
        print("  (nenhum bloco Distribuicoes registrado)")

    total = perf.get("page_total_seconds")
    if total is not None:
        print(f"\n  page_total_seconds: {total:.3f}s")

    ok = (
        count_status == 1
        and count_quality == 1
        and len(dist_blocks) == 1
        and not errs
    )
    print(f"\nRESULT: {'OK' if ok else 'FALHOU'}")
    if errs:
        print("  errors:", errs[:3])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
