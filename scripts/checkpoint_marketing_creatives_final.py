#!/usr/bin/env python
"""Checkpoint final — Criativos com ?debug_perf=1 (AppTest, multi-período).

Uso:
  python scripts/checkpoint_marketing_creatives_final.py
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

from streamlit.testing.v1 import AppTest

from src.ui.page import PERIOD_PRESET_KEY, PERIOD_RANGE_KEY

PERF_KEY = "_mkt_marketing_creatives_perf"
VIEW = ROOT / "views" / "marketing_creatives.py"
HOJE = date(2026, 6, 23)

SCENARIOS: dict[str, tuple[date, date]] = {
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "abr_2026": (date(2026, 4, 1), date(2026, 4, 30)),
    "mai_2026": (date(2026, 5, 1), date(2026, 5, 31)),
    "jun_2026_parcial": (date(2026, 6, 1), date(2026, 6, 15)),
    "sem_dados": (date(2020, 1, 1), date(2020, 1, 7)),
}

# Ordem esperada dos blocos principais (section_title)
BLOCK_ORDER = [
    "Performance Meta",
    "Funil do criativo selecionado",
    "Por status",
    "Por quality ranking",
    "Top 12 criativos",
    "Comparar criativos",
]

PERF_BLOCKS_EXPECTED = [
    "Performance Meta (criativos + resultados)",
    "Funil criativo_funil",
    "Distribuicoes (pandas+charts)",
    "Top 12 criativos",
    "Top 12 ranking (pandas)",
    "Top 12 cards (render)",
]


def _perf_state(at: AppTest) -> dict:
    try:
        return dict(at.session_state[PERF_KEY])
    except (KeyError, AttributeError):
        return {}


def _sec_titles(at: AppTest) -> list[str]:
    out: list[str] = []
    for m in at.markdown or []:
        v = str(m.value)
        if "sec-title" not in v:
            continue
        for title in BLOCK_ORDER:
            if title in v and title not in out:
                out.append(title)
    return out


def _block_seconds(perf: dict, needle: str) -> float | None:
    for b in perf.get("blocks") or []:
        if needle.lower() in b.get("block", "").lower():
            return b.get("seconds")
    return None


def _query_seconds(perf: dict, needle: str) -> float | None:
    for q in perf.get("queries") or []:
        if needle.lower() in q.get("name", "").lower():
            return q.get("seconds")
    return None


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
    md_vals = [str(m.value) for m in (at.markdown or [])]
    all_html = " ".join(md_vals)
    sec_html = " ".join(v for v in md_vals if "sec-title" in v)

    count_status = sec_html.count(">Por status")
    count_quality = sec_html.count("Por quality ranking")
    count_top12 = sec_html.count("Top 12 criativos")
    count_comparar = sec_html.count("Comparar criativos")
    count_mcards = all_html.count("mcard-value")
    plotly_n = len(at.get("plotly_chart") or [])

    titles_order = _sec_titles(at)
    order_ok = titles_order == [t for t in BLOCK_ORDER if t in titles_order]

    dist_blocks = [
        b for b in (perf.get("blocks") or [])
        if "distribuicoes" in b.get("block", "").lower()
    ]
    errs = [e.value for e in (at.error or [])] + [e.value for e in (at.exception or [])]
    no_data = label == "sem_dados"

    metrics = {
        "page_total_seconds": perf.get("page_total_seconds"),
        "kpi_render_seconds": perf.get("kpi_render_seconds"),
        "selector_render_seconds": perf.get("selector_render_seconds"),
        "funil_render_seconds": perf.get("funil_render_seconds"),
        "top12_render_seconds": perf.get("top12_render_seconds"),
        "p1_block": _block_seconds(perf, "Performance Meta (criativos"),
        "funil_block": _block_seconds(perf, "Funil criativo_funil"),
        "distrib_block": _block_seconds(perf, "Distribuicoes"),
        "top12_sql_block": _block_seconds(perf, "Top 12 criativos"),
        "top12_pandas_block": _block_seconds(perf, "Top 12 ranking"),
        "top12_render_block": _block_seconds(perf, "Top 12 cards"),
        "top_nome_query": _query_seconds(perf, "mkt_top_criativos_por_nome"),
        "comparar_query": _query_seconds(perf, "Comparar criativos"),
        "query_count": len(perf.get("queries") or []),
    }

    checks = {
        "sem_erro_streamlit": not errs,
        "distribuicoes_1x_status": (count_status == 0 if no_data else count_status == 1),
        "distribuicoes_1x_quality": (count_quality == 0 if no_data else count_quality == 1),
        "distrib_timer_1x": (len(dist_blocks) == 0 if no_data else len(dist_blocks) == 1),
        "top12_1x": count_top12 == 1,
        "comparar_1x": count_comparar == 1,
        "ordem_blocos": order_ok,
        "expander_auditoria": any(
            "anúncios do período" in (e.label or "").lower()
            for e in (at.expander or [])
        ),
        "expander_perf": any(
            "diagnóstico de performance" in (e.label or "").lower()
            for e in (at.expander or [])
        ),
        "metric_cards_html": (
            count_mcards >= 5 if not no_data else "Performance Meta" in titles_order
        ),
        "plotly_charts": (plotly_n == 0 if no_data else plotly_n >= 2),
    }
    visual_ok = all(checks.values())

    print("--- Visual ---")
    for k, v in checks.items():
        print(f"  {k}: {'OK' if v else 'FALHOU'}")
    print(f"  ordem detectada: {titles_order}")
    if errs:
        print(f"  erros: {errs[:2]}")

    print("--- Perf (debug_perf) ---")
    for k, v in metrics.items():
        if v is not None:
            if isinstance(v, float):
                print(f"  {k}: {v:.3f}s")
            else:
                print(f"  {k}: {v}")

    return {
        "scenario": label,
        "data_ini": data_ini.isoformat(),
        "data_fim": data_fim.isoformat(),
        "visual_ok": visual_ok,
        "checks": checks,
        "metrics": metrics,
        "titles_order": titles_order,
    }


def main() -> None:
    print("Checkpoint final — Criativos (?debug_perf=1)", flush=True)
    results = []
    all_ok = True
    for label, (di, df) in SCENARIOS.items():
        r = run_scenario(label, di, df)
        results.append(r)
        if not r["visual_ok"]:
            all_ok = False

    out = ROOT / "scripts" / "checkpoint_marketing_creatives_final_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados salvos em: {out}")
    print(f"\nRESULTADO GERAL: {'OK' if all_ok else 'FALHOU'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
