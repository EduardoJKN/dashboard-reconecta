"""Instrumentação de performance — páginas de Marketing.

Ativada via `?debug_perf=1` na URL. Não expõe SQL, credenciais ou dados sensíveis."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from typing import Any

import streamlit as st

logger = logging.getLogger("reconecta.marketing.perf")

_SESSION_KEY = "_mkt_overview_perf"
_DEBUG_PARAM = "debug_perf"


def perf_debug_enabled() -> bool:
    try:
        return st.query_params.get(_DEBUG_PARAM) == "1"
    except Exception:
        return False


def perf_reset_run() -> None:
    import time

    st.session_state[_SESSION_KEY] = {
        "queries": [],
        "kpi_render_seconds": None,
        "page_total_seconds": None,
        "run_started": time.perf_counter(),
    }


def _state() -> dict[str, Any]:
    return st.session_state.setdefault(_SESSION_KEY, {"queries": []})


def perf_record_query(
    name: str,
    data_ini: date | None,
    data_fim: date | None,
    seconds: float,
    rows: int,
    *,
    error: str | None = None,
) -> None:
    entry = {
        "name": name,
        "data_ini": data_ini.isoformat() if data_ini else None,
        "data_fim": data_fim.isoformat() if data_fim else None,
        "seconds": round(seconds, 4),
        "rows": int(rows),
        "error": error,
    }
    _state().setdefault("queries", []).append(entry)
    logger.info(
        "query %s [%s → %s] %.3fs rows=%d%s",
        name,
        entry["data_ini"],
        entry["data_fim"],
        seconds,
        rows,
        f" ERR={error}" if error else "",
    )


def perf_mark_kpi_rendered() -> None:
    import time

    state = _state()
    if state.get("kpi_render_seconds") is None:
        started = state.get("run_started")
        if started is not None:
            state["kpi_render_seconds"] = round(time.perf_counter() - started, 4)


def perf_finalize_page() -> None:
    import time

    state = _state()
    started = state.get("run_started")
    if started is not None:
        state["page_total_seconds"] = round(time.perf_counter() - started, 4)


@contextmanager
def perf_timed_block(block: str):
    import time

    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        logger.info("block %s: %.3fs", block, elapsed)
        if perf_debug_enabled():
            blocks = _state().setdefault("blocks", [])
            blocks.append({"block": block, "seconds": round(elapsed, 4)})


def perf_query_count() -> int:
    return len(_state().get("queries") or [])


def perf_render_panel() -> None:
    if not perf_debug_enabled():
        return
    state = _state()
    queries = state.get("queries") or []
    with st.expander("Diagnóstico de performance (Marketing)", expanded=False):
        st.caption(f"**Consultas executadas neste rerun:** {len(queries)}")
        for q in queries:
            err = f" · **erro:** {q['error']}" if q.get("error") else ""
            st.caption(
                f"**{q['name']}** · {q.get('data_ini')} → {q.get('data_fim')} · "
                f"{q['seconds']:.3f}s · {q['rows']} linhas{err}"
            )
        kpi_t = state.get("kpi_render_seconds")
        if kpi_t is not None:
            st.caption(
                f"**Tempo até render dos KPIs** (aprox.: fim das queries P1/P2 + "
                f"início dos cards): **{kpi_t:.3f}s**"
            )
        total = state.get("page_total_seconds")
        if total is not None:
            st.caption(f"**Tempo total do rerun:** **{total:.3f}s**")
        blocks = state.get("blocks") or []
        for b in blocks:
            st.caption(f"**{b['block']}**: {b['seconds']:.3f}s")
