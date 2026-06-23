#!/usr/bin/env python
"""Valida cache/session_state da Meta oficial do Funil."""
from __future__ import annotations

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

import streamlit as st

from src.funil_meta_store import (  # noqa: E402
    invalidate_funil_meta_load_cache,
    is_metas_database_configured,
    load_latest_meta_funil_mensal,
    meta_cache_hit_between,
    meta_latest_cache_hits,
)

HOJE = date(2026, 6, 22)
INI_A = HOJE.replace(day=1)
FIM_A = HOJE
INI_B = date(2026, 5, 1)
FIM_B = date(2026, 5, 31)


def _bootstrap_key(ini: date, fim: date) -> str:
    return f"funil_meta_bootstrapped_{ini.isoformat()}_{fim.isoformat()}"


def _clear() -> None:
    invalidate_funil_meta_load_cache()
    st.session_state.clear()


def _cache_hit_on_second_call(ini: date, fim: date) -> bool:
    hits_before = meta_latest_cache_hits()
    load_latest_meta_funil_mensal(ini, fim)
    load_latest_meta_funil_mensal(ini, fim)
    hits_after = meta_latest_cache_hits()
    return meta_cache_hit_between(hits_before, hits_after) or hits_before is None


def test_first_load_ok() -> bool:
    _clear()
    _, prop = load_latest_meta_funil_mensal(INI_A, FIM_A)
    return prop is not None


def test_cache_warm() -> bool:
    if not is_metas_database_configured():
        return True
    _clear()
    return _cache_hit_on_second_call(INI_A, FIM_A)


def test_period_switch() -> bool:
    _clear()
    _, prop_a = load_latest_meta_funil_mensal(INI_A, FIM_A)
    _, prop_b = load_latest_meta_funil_mensal(INI_B, FIM_B)
    return prop_a.mes_inicio != prop_b.mes_inicio


def test_session_warm() -> bool:
    _clear()
    key = _bootstrap_key(INI_A, FIM_A)
    load_latest_meta_funil_mensal(INI_A, FIM_A)
    st.session_state[key] = True
    if not st.session_state.get(key):
        return False
    return st.session_state.get(key) is True


def test_invalidate_clears_cache() -> bool:
    if not is_metas_database_configured():
        return True
    _clear()
    load_latest_meta_funil_mensal(INI_A, FIM_A)
    invalidate_funil_meta_load_cache()
    hits_before = meta_latest_cache_hits()
    load_latest_meta_funil_mensal(INI_A, FIM_A)
    hits_after = meta_latest_cache_hits()
    if hits_before is not None and hits_after is not None:
        return hits_after == hits_before
    return True


def test_no_db_ok() -> bool:
    if is_metas_database_configured():
        return True
    _clear()
    try:
        _, prop = load_latest_meta_funil_mensal(date(2099, 1, 1), date(2099, 1, 7))
        return prop is not None
    except Exception:
        return False


def main() -> None:
    tests = [
        ("primeira_carga", test_first_load_ok),
        ("cache_warm", test_cache_warm),
        ("troca_periodo", test_period_switch),
        ("session_warm", test_session_warm),
        ("invalidate_apos_clear", test_invalidate_clears_cache),
        ("sem_db_ou_futuro", test_no_db_ok),
    ]
    ok_all = True
    for name, fn in tests:
        try:
            ok = fn()
        except Exception as exc:
            ok = False
            print(f"FAIL {name}: {exc}")
            ok_all = False
            continue
        ok_all = ok_all and ok
        print(f"{'OK' if ok else 'FAIL':4} {name}")
    if not ok_all:
        sys.exit(1)


if __name__ == "__main__":
    main()
