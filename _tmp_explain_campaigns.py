"""EXPLAIN ANALYZE temporario — somente leitura, 1 query por execucao."""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from src.db import QUERIES_DIR, get_engine

DATA_INI = date(2026, 4, 1)
DATA_FIM = date(2026, 4, 30)
P = {"data_ini": DATA_INI, "data_fim": DATA_FIM}

# statement_timeout 120s — somente leitura
TIMEOUT_MS = 120_000

FILES = [
    "dashboard_executivas.sql",
    "mkt_campanha_funil.sql",
]


def explain_one(fname: str) -> None:
    sql = (QUERIES_DIR / fname).read_text(encoding="utf-8")
    explain_sql = f"SET statement_timeout = '{TIMEOUT_MS}ms';\nEXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n{sql}"
    print(f"\n{'='*70}\n{fname}\n{'='*70}")
    t0 = time.perf_counter()
    with get_engine().connect() as conn:
        rows = conn.execute(text(explain_sql), P).fetchall()
    elapsed = time.perf_counter() - t0
    plan = "\n".join(str(r[0]) for r in rows)
    print(plan)
    for line in plan.splitlines():
        if "Execution Time:" in line or "Planning Time:" in line:
            print(f"  >> {line.strip()}")
    print(f"[wall_time={elapsed:.3f}s]")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        explain_one(target)
    else:
        for f in FILES:
            explain_one(f)
