#!/usr/bin/env python
"""EXPLAIN das queries de executivas v1 e v2 (Funil)."""
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

from sqlalchemy import text  # noqa: E402

from src.db import QUERIES_DIR, get_engine  # noqa: E402

HOJE = date(2026, 6, 22)
SAMPLES = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE, False),
    ("mes_atual", HOJE.replace(day=1), HOJE, False),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17), True),
]


def _explain(sql_file: str, data_ini: date, data_fim: date) -> str:
    sql = (QUERIES_DIR / sql_file).read_text(encoding="utf-8")
    params = {"data_ini": data_ini, "data_fim": data_fim}
    explain_sql = f"EXPLAIN (FORMAT TEXT)\n{sql}"
    with get_engine().connect() as conn:
        rows = conn.execute(text(explain_sql), params).fetchall()
    return "\n".join(r[0] for r in rows)


def main() -> None:
    for label, ini, fim, analyze_ok in SAMPLES:
        print(f"\n{'#' * 72}")
        print(f"# {label} ({ini} -> {fim})")
        print(f"{'#' * 72}")
        for version, fname in (
            ("v1", "dashboard_executivas.sql"),
            ("v2_funil", "dashboard_executivas_funil_v2.sql"),
        ):
            print(f"\n--- EXPLAIN {version} ({fname}) ---")
            try:
                print(_explain(fname, ini, fim))
            except Exception as exc:
                print(f"ERRO: {exc}")

        if analyze_ok:
            sql = (QUERIES_DIR / "dashboard_executivas_funil_v2.sql").read_text(
                encoding="utf-8",
            )
            params = {"data_ini": ini, "data_fim": fim}
            explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n{sql}"
            print("\n--- EXPLAIN ANALYZE v2_funil (periodo curto) ---")
            try:
                with get_engine().connect() as conn:
                    rows = conn.execute(text(explain_sql), params).fetchall()
                print("\n".join(r[0] for r in rows))
            except Exception as exc:
                print(f"ERRO ANALYZE: {exc}")


if __name__ == "__main__":
    main()
