#!/usr/bin/env python
"""EXPLAIN (ANALYZE) — prevendas_comparecimentos_classif (somente leitura).

Uso:
  python scripts/explain_prevendas_comparecimentos_classif.py
  python scripts/explain_prevendas_comparecimentos_classif.py --scenario mes_atual
  python scripts/explain_prevendas_comparecimentos_classif.py --sql both
"""
from __future__ import annotations

import argparse
import re
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

from sqlalchemy import text  # noqa: E402

from src.db import QUERIES_DIR, get_engine  # noqa: E402

HOJE = date(2026, 6, 22)
SCENARIOS: dict[str, tuple[date, date]] = {
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "mes_anterior": (date(2026, 5, 1), date(2026, 5, 31)),
    "ultimos_60_dias": (HOJE - timedelta(days=59), HOJE),
}

SQL_FILES = {
    "v1": "prevendas_comparecimentos_classif.sql",
    "v2": "prevendas_comparecimentos_classif_v2.sql",
}


def _explain_prefix(use_buffers: bool) -> str:
    if use_buffers:
        return "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)"
    return "EXPLAIN (ANALYZE, FORMAT TEXT)"


def _run_explain(
    sql_file: str,
    data_ini: date,
    data_fim: date,
    *,
    use_buffers: bool,
) -> tuple[float, str, bool]:
    query = (QUERIES_DIR / sql_file).read_text(encoding="utf-8")
    explain_sql = f"{_explain_prefix(use_buffers)}\n{query}"
    params = {"data_ini": data_ini, "data_fim": data_fim}
    t0 = time.perf_counter()
    with get_engine().connect() as conn:
        try:
            rows = conn.execute(text(explain_sql), params).fetchall()
            elapsed = time.perf_counter() - t0
            plan = "\n".join(r[0] for r in rows)
            return elapsed, plan, use_buffers
        except Exception as exc:
            if use_buffers and "buffers" in str(exc).lower():
                return _run_explain(
                    sql_file, data_ini, data_fim, use_buffers=False,
                )
            raise


def _extract_total_time(plan: str) -> float | None:
    m = re.search(r"Execution Time:\s*([\d.]+)\s*ms", plan)
    return float(m.group(1)) / 1000.0 if m else None


def _top_nodes(plan: str, limit: int = 12) -> list[tuple[float, str]]:
    nodes: list[tuple[float, str]] = []
    for line in plan.splitlines():
        m = re.match(r"\s*(.+?)\s+\(cost=[\d.]+..([\d.]+)\s+rows=.*\)", line)
        if m:
            nodes.append((float(m.group(2)), m.group(1).strip()))
    nodes.sort(key=lambda x: -x[0])
    return nodes[:limit]


def _table_costs(plan: str) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for line in plan.splitlines():
        for pat in (
            r"Seq Scan on (\w+(?:\.\w+)?)",
            r"Index Scan.* on (\w+(?:\.\w+)?)",
            r"Index Only Scan.* on (\w+(?:\.\w+)?)",
            r"Bitmap Heap Scan on (\w+(?:\.\w+)?)",
            r"Hash Join.* on (\w+(?:\.\w+)?)",
        ):
            m = re.search(pat, line)
            if m:
                tbl = m.group(1)
                counts[tbl] = counts.get(tbl, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _seq_scan_evidence(plan: str) -> list[str]:
    evidence: list[str] = []
    for line in plan.splitlines():
        if "Seq Scan" in line:
            evidence.append(line.strip())
    return evidence[:8]


def _suggest_rewrite(plan: str, sql_label: str) -> list[str]:
    tips: list[str] = []
    if "ext_reconecta.leads" in plan or "leads l" in plan.lower():
        if "Seq Scan" in plan and "leads" in plan:
            tips.append(
                "`ext_reconecta.leads` com Seq Scan amplo em ext_leads_dedup — "
                "restringir a deal_ids do período."
            )
    if "zoho_deals" in plan and "Seq Scan on zoho_deals" in plan:
        tips.append(
            "`zoho_deals` Seq Scan em deal_classif — limitar a deals "
            "referenciados por activities do recorte."
        )
    if not tips:
        tips.append("Revisar CTEs que materializam bases maiores que o necessário.")
    if sql_label == "v2":
        tips.insert(0, "v2 restringe ext_leads_dedup e deal_classif a relevant_deal_ids.")
    return tips


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()) + ["all"],
        default="all",
    )
    parser.add_argument(
        "--sql",
        choices=("v1", "v2", "both"),
        default="v1",
        help="Qual query explicar (default: v1 legado)",
    )
    args = parser.parse_args()

    labels = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
    sql_keys = ["v1", "v2"] if args.sql == "both" else [args.sql]

    print("EXPLAIN ANALYZE — prevendas_comparecimentos_classif")
    print(f"Referência: {HOJE.isoformat()}")

    for sk in sql_keys:
        sql_file = SQL_FILES[sk]
        print(f"\n{'=' * 72}")
        print(f"SQL: {sql_file} ({sk})")
        print(f"{'=' * 72}")

        for label in labels:
            di, df = SCENARIOS[label]
            print(f"\n--- {label}: {di} → {df} ---")
            wall, plan, used_buffers = _run_explain(
                sql_file, di, df, use_buffers=True,
            )
            exec_t = _extract_total_time(plan)
            print(
                f"Wall: {wall:.2f}s | Execution Time (plano): "
                f"{exec_t:.2f}s" if exec_t else f"Wall: {wall:.2f}s",
            )
            print(f"BUFFERS: {'sim' if used_buffers else 'não (fallback)'}")

            print("\nTop nodes (estimated cost):")
            for cost, name in _top_nodes(plan):
                print(f"  cost={cost:,.0f}  {name}")

            print("\nTabelas mais referenciadas no plano:")
            for tbl, n in _table_costs(plan)[:8]:
                print(f"  {tbl}: {n}x")

            seq = _seq_scan_evidence(plan)
            if seq:
                print("\nEvidência Seq Scan:")
                for line in seq:
                    print(f"  {line}")

            print("\nSugestões de reescrita:")
            for i, tip in enumerate(_suggest_rewrite(plan, sk), 1):
                print(f"  {i}. {tip}")

            if args.scenario != "all":
                print("\n--- Plano (trecho final) ---")
                print("\n".join(plan.splitlines()[-25:]))


if __name__ == "__main__":
    main()
