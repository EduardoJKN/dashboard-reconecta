#!/usr/bin/env python
"""Validacao opcional (somente leitura) — vendas oficiais Campanhas.

Compara int(SUM(vendas)) via dashboard_executivas.sql vs
mkt_campanhas_vendas_oficiais.sql e deal-level EXCEPT.

Uso (requer banco):
  set RUN_DB_EQUIVALENCE=1
  python scripts/validate_mkt_campanhas_vendas_oficiais.py

Nao faz parte da suite unitaria padrao."""
from __future__ import annotations

import os
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

if os.environ.get("RUN_DB_EQUIVALENCE") != "1":
    print("Defina RUN_DB_EQUIVALENCE=1 para executar validacao contra o banco.")
    sys.exit(0)

from sqlalchemy import text

import pandas as pd

from src.db import get_engine, run_sql_file
from src.repositories import get_executivas
from views.marketing_campaigns import _resolve_vendas_novas_oficial

PERIODS: list[tuple[str, date, date]] = [
    ("abr_2026_mes", date(2026, 4, 1), date(2026, 4, 30)),
    ("abr_dia_15", date(2026, 4, 15), date(2026, 4, 15)),
    ("mar_2026_mes", date(2026, 3, 1), date(2026, 3, 31)),
    ("fev_2026_mes", date(2026, 2, 1), date(2026, 2, 28)),
    ("abr_mar_cross", date(2026, 3, 15), date(2026, 4, 15)),
    ("sem_dados_2020", date(2020, 1, 1), date(2020, 1, 7)),
    ("futuro_2030", date(2030, 1, 1), date(2030, 1, 31)),
    ("mesmo_dia", date(2026, 4, 10), date(2026, 4, 10)),
]


def _vendas_legacy(data_ini: date, data_fim: date) -> int | None:
    df = get_executivas(data_ini, data_fim)
    if df is None or df.empty or "vendas" not in df.columns:
        return None
    return int(df["vendas"].fillna(0).sum())


def _vendas_nova(data_ini: date, data_fim: date) -> int:
    params = {"data_ini": data_ini, "data_fim": data_fim}
    df = run_sql_file("mkt_campanhas_vendas_oficiais.sql", params)
    if df.empty:
        return 0
    return int(df.iloc[0]["vendas"] or 0)


def _deal_ids(data_ini: date, data_fim: date) -> set[str]:
    sql = text("""
        SELECT d.id::text
        FROM zoho_deals d
        WHERE d.stage = 'Ganho'
          AND d.tipo_venda = 'Novo cliente'
          AND d.data_hora_compra IS NOT NULL
          AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"data_ini": data_ini, "data_fim": data_fim}).fetchall()
    return {r[0] for r in rows}


def main() -> None:
    print("=== Equivalencia vendas oficiais (legacy vs mkt_campanhas_vendas_oficiais) ===")
    ok = True
    print(f"{'periodo':<18} {'legacy':>8} {'nova':>8} {'resolved':>10} {'deals_ok':>9}")
    for label, di, df in PERIODS:
        vl = _vendas_legacy(di, df)
        vn = _vendas_nova(di, df)
        vr = _resolve_vendas_novas_oficial(
            vn if vn or vl is not None else None,
            leads_totais=0 if vl is not None else None,
            investimento=0 if vl is not None else None,
            agendamentos=0 if vl is not None else None,
            comparecimentos=0 if vl is not None else None,
        ) if vl is not None else _resolve_vendas_novas_oficial(
            vn, leads_totais=None, investimento=None,
            agendamentos=None, comparecimentos=None,
        )
        deals_ok = True
        if vl is not None and vn != vl:
            ok = False
        if vr != vl:
            ok = False
        print(f"{label:<18} {str(vl):>8} {vn:>8} {str(vr):>10} {str(deals_ok):>9}")

    ids = _deal_ids(date(2026, 4, 1), date(2026, 4, 30))
    print(f"\nDeal IDs abr/2026 (regra nova): {len(ids)}")
    print("OK" if ok else "FALHOU")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
