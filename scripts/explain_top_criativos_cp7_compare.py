#!/usr/bin/env python
"""EXPLAIN ANALYZE BUFFERS — pre_cp7 vs CP7 (MATERIALIZED CTEs)."""
from __future__ import annotations

import re
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

from sqlalchemy import text

from src.db import get_engine

TODAY = date(2026, 6, 23)
PERIODS = [
    ("ultimos_7_dias", TODAY - timedelta(days=6), TODAY),
    ("abr_2026", date(2026, 4, 1), date(2026, 4, 30)),
    ("mai_2026", date(2026, 5, 1), date(2026, 5, 31)),
    ("jun_2026_parcial", date(2026, 6, 1), date(2026, 6, 15)),
    ("sem_dados", date(2020, 1, 1), date(2020, 1, 7)),
]

VARIANTS = {
    "pre_cp7": ROOT / "src" / "queries" / "mkt_top_criativos_por_nome_pre_cp7.sql",
    "cp7": ROOT / "src" / "queries" / "mkt_top_criativos_por_nome.sql",
}


def _exec_ms(plan_lines: list[str]) -> float | None:
    for line in plan_lines:
        if line.startswith("Execution Time:"):
            return float(line.split(":")[1].strip().replace(" ms", ""))
    return None


def _max_loops(plan_lines: list[str]) -> int:
    mx = 1
    for line in plan_lines:
        m = re.search(r"loops=(\d+)", line)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def _has_bad_nested_loop(plan_lines: list[str]) -> bool:
    """Detecta WindowAgg/subquery com loops >> 1 no join de aplicações."""
    for line in plan_lines:
        if "Subquery Scan on sub" in line or "WindowAgg" in line:
            m = re.search(r"loops=(\d+)", line)
            if m and int(m.group(1)) > 100:
                return True
    return False


def explain_file(path: Path, params: dict) -> dict:
    sql = path.read_text(encoding="utf-8")
    explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n{sql}"
    with get_engine().connect() as conn:
        rows = conn.execute(text(explain_sql), params).fetchall()
    plan = [r[0] for r in rows]
    return {
        "exec_ms": _exec_ms(plan),
        "max_loops": _max_loops(plan),
        "bad_nested_loop": _has_bad_nested_loop(plan),
        "plan": "\n".join(plan),
    }


def main() -> None:
    out_dir = ROOT / "scripts" / "explain_top_criativos_cp7_outputs"
    out_dir.mkdir(exist_ok=True)

    print("=== EXPLAIN ANALYZE BUFFERS: pre_cp7 vs CP7 ===\n")
    print(f"{'periodo':<20} {'variant':<8} {'exec_s':>8} {'max_loops':>10} {'bad_nl':>7}")
    print("-" * 58)

    for label, di, df in PERIODS:
        params = {"data_ini": di, "data_fim": df}
        for vname, vpath in VARIANTS.items():
            print(f"  {label} / {vname} ...", flush=True)
            r = explain_file(vpath, params)
            exec_s = (r["exec_ms"] or 0) / 1000
            print(
                f"{label:<20} {vname:<8} {exec_s:8.2f} "
                f"{r['max_loops']:10d} {str(r['bad_nested_loop']):>7}"
            )
            (out_dir / f"{label}_{vname}.txt").write_text(r["plan"], encoding="utf-8")
        print()


if __name__ == "__main__":
    main()
