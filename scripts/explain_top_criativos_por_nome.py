#!/usr/bin/env python
"""EXPLAIN ANALYZE — mkt_top_criativos_por_nome (somente leitura)."""
from __future__ import annotations

import re
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

from sqlalchemy import text

from src.db import get_engine, run_sql_file

PERIODS = [
    ("ultimos_7_dias", date(2026, 6, 17), date(2026, 6, 23)),
    ("abr_2026", date(2026, 4, 1), date(2026, 4, 30)),
    ("mai_2026", date(2026, 5, 1), date(2026, 5, 31)),
    ("jun_2026_parcial", date(2026, 6, 1), date(2026, 6, 15)),
]

SQL_FILE = ROOT / "src" / "queries" / "mkt_top_criativos_por_nome.sql"
QUERY = SQL_FILE.read_text(encoding="utf-8")

FDW_CHECK = """
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    CASE c.relkind
        WHEN 'f' THEN 'foreign_table'
        WHEN 'r' THEN 'table'
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized_view'
        ELSE c.relkind::text
    END AS relkind,
    fs.srvname AS foreign_server
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_foreign_table ft ON ft.ftrelid = c.oid
LEFT JOIN pg_foreign_server fs ON fs.oid = ft.ftserver
WHERE (n.nspname, c.relname) IN (
    ('fdw_reconecta', 'anuncios'),
    ('fdw_reconecta', 'typeform_aplicacoes'),
    ('ext_reconecta', 'leads')
)
ORDER BY 1, 2;
"""


def _top_nodes(plan_lines: list[str], limit: int = 12) -> list[str]:
    """Extrai linhas do plano com tempo acumulado."""
    scored: list[tuple[float, str]] = []
    pat = re.compile(
        r"->\s+(.*?)\s+\(cost=[\d.]+\.\.[\d.]+\s+rows=\d+\s+width=\d+\)"
        r"(?:\s+\(actual time=[\d.]+\.\.[\d.]+\s+rows=\d+\s+loops=\d+\))?"
    )
    time_pat = re.compile(r"actual time=([\d.]+)\.\.([\d.]+)")
    for line in plan_lines:
        m = pat.search(line)
        if not m:
            continue
        tm = time_pat.search(line)
        t_max = float(tm.group(2)) if tm else 0.0
        scored.append((t_max, line.strip()))
    scored.sort(key=lambda x: -x[0])
    return [ln for _, ln in scored[:limit]]


def explain_period(label: str, data_ini: date, data_fim: date) -> dict:
    params = {"data_ini": data_ini, "data_fim": data_fim}
    explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT)\n{QUERY}"

    with get_engine().connect() as conn:
        rows = conn.execute(text(explain_sql), params).fetchall()

    plan_lines = [r[0] for r in rows]
    full = "\n".join(plan_lines)

    # totais do root
    root_time = None
    root_rows = None
    for line in plan_lines:
        if line.startswith("Execution Time:"):
            root_time = float(line.split(":")[1].strip().replace(" ms", ""))
        if "Planning Time:" in line:
            planning = float(line.split(":")[1].strip().replace(" ms", ""))
        if line.strip().startswith("Sort") and "actual time" in line and root_rows is None:
            pass
        m = re.search(r"actual time=[\d.]+\.\.([\d.]+)\s+rows=(\d+)", plan_lines[0] if plan_lines else "")
        if m and plan_lines[0].startswith("Sort"):
            root_time = float(m.group(1))

    # execution time line
    exec_ms = planning_ms = None
    for line in plan_lines:
        if line.startswith("Execution Time:"):
            exec_ms = float(line.split(":")[1].strip().replace(" ms", ""))
        if line.startswith("Planning Time:"):
            planning_ms = float(line.split(":")[1].strip().replace(" ms", ""))

    # row count from final gather
    df = run_sql_file("mkt_top_criativos_por_nome.sql", params)

    # detect FDW scans
    fdw_hits = [ln for ln in plan_lines if "Foreign Scan" in ln or "Foreign Table" in ln]

    return {
        "label": label,
        "data_ini": data_ini.isoformat(),
        "data_fim": data_fim.isoformat(),
        "exec_ms": exec_ms,
        "planning_ms": planning_ms,
        "result_rows": len(df),
        "top_nodes": _top_nodes(plan_lines),
        "fdw_scans": fdw_hits[:8],
        "full_plan": full,
    }


def main() -> None:
    print("=== FDW / relkind check ===\n")
    import pandas as pd
    fdw_df = pd.read_sql(text(FDW_CHECK), get_engine())
    print(fdw_df.to_string(index=False))

    out_dir = ROOT / "scripts" / "explain_top_criativos_outputs"
    out_dir.mkdir(exist_ok=True)

    print("\n=== EXPLAIN ANALYZE por período ===\n")
    summaries = []
    for label, di, df in PERIODS:
        print(f"--- {label} ({di} -> {df}) ---", flush=True)
        try:
            r = explain_period(label, di, df)
            summaries.append(r)
            print(f"  Execution Time: {r['exec_ms']:.1f} ms")
            print(f"  Planning Time:  {r['planning_ms']:.1f} ms")
            print(f"  Result rows:    {r['result_rows']}")
            print("  Top nodes (by max actual time):")
            for ln in r["top_nodes"][:6]:
                print(f"    {ln[:140]}")
            print("  Foreign scans:")
            for ln in r["fdw_scans"][:4]:
                print(f"    {ln[:140]}")
            (out_dir / f"{label}.txt").write_text(r["full_plan"], encoding="utf-8")
        except Exception as exc:
            print(f"  ERRO: {exc}")
        print()

    print("\n=== RESUMO ===")
    for r in summaries:
        print(
            f"  {r['label']:<20} exec={r['exec_ms']/1000:.2f}s "
            f"rows={r['result_rows']}"
        )


if __name__ == "__main__":
    main()
