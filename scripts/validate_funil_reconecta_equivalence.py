#!/usr/bin/env python
"""Valida equivalência numérica: implementação direta vs cache de funil."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.one_page_funnel import (  # noqa: E402
    FunnelSnapshot,
    _load_one_page_funnel_impl,
    load_one_page_funnel,
)

HOJE = date(2026, 6, 22)
PERIODS = [
    ("ultimos_7_dias", HOJE - timedelta(days=6), HOJE),
    ("mes_atual", HOJE.replace(day=1), HOJE),
    ("mes_anterior", date(2026, 5, 1), date(2026, 5, 31)),
    ("recorte_jun_2026", date(2026, 6, 1), date(2026, 6, 17)),
]

FIELDS = (
    "investimento", "leads", "aplicacoes", "agendamentos", "comparecimento",
    "vendas", "montante", "receita", "pct_recebimento", "custo_lead",
    "pct_la", "pct_a_ag", "pct_ag_c", "pct_c_v", "ticket",
)


def _diff(a: FunnelSnapshot, b: FunnelSnapshot) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in FIELDS:
        va = float(getattr(a, f))
        vb = float(getattr(b, f))
        if abs(va - vb) > 1e-6:
            out[f] = va - vb
    return out


def main() -> None:
    ok = True
    for label, ini, fim in PERIODS:
        direct = _load_one_page_funnel_impl(ini, fim, excluir_testes_aplicacoes=True)
        cached = load_one_page_funnel(ini, fim, excluir_testes_aplicacoes=True)
        d = _diff(direct, cached)
        if d:
            ok = False
            print(f"FAIL {label}: diferenças {d}")
        else:
            print(f"OK   {label}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
