"""Instrumentação de performance — página Lead In & Reuniões.

Ativada via `?debug_perf=1` na URL. Não expõe SQL, credenciais ou dados sensíveis.

Medições também são registradas no logger `reconecta.lead_in.perf` (visível no terminal).
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable

import pandas as pd
import streamlit as st

logger = logging.getLogger("reconecta.lead_in.perf")

_DEBUG_PARAM = "debug_perf"
PAGE_LEAD_IN = "lead_in_reunioes"
_SESSION_KEY = f"_lead_in_{PAGE_LEAD_IN}_perf"


def perf_debug_enabled() -> bool:
    try:
        return st.query_params.get(_DEBUG_PARAM) == "1"
    except Exception:
        return False


def perf_reset_run() -> None:
    st.session_state[_SESSION_KEY] = {
        "page": PAGE_LEAD_IN,
        "queries": [],
        "blocks": [],
        "milestones": {},
        "page_total_seconds": None,
        "run_started": time.perf_counter(),
        "context": {},
    }


def _state() -> dict[str, Any]:
    return st.session_state.setdefault(_SESSION_KEY, {"queries": [], "blocks": []})


def perf_set_context(
    *,
    data_ini: date | None = None,
    data_fim: date | None = None,
    modo_historico_agenda: bool | None = None,
) -> None:
    if not perf_debug_enabled():
        return
    ctx: dict[str, Any] = {}
    if data_ini is not None:
        ctx["data_ini"] = data_ini.isoformat()
    if data_fim is not None:
        ctx["data_fim"] = data_fim.isoformat()
    if modo_historico_agenda is not None:
        ctx["modo_historico_agenda"] = modo_historico_agenda
    _state()["context"] = ctx


def perf_record_query(
    name: str,
    data_ini: date | None,
    data_fim: date | None,
    seconds: float,
    rows: int,
    *,
    cols: int | None = None,
    error: str | None = None,
) -> None:
    entry: dict[str, Any] = {
        "name": name,
        "data_ini": data_ini.isoformat() if data_ini else None,
        "data_fim": data_fim.isoformat() if data_fim else None,
        "seconds": round(seconds, 4),
        "rows": int(rows),
        "error": error,
    }
    if cols is not None:
        entry["cols"] = int(cols)
    _state().setdefault("queries", []).append(entry)
    cols_msg = f" cols={cols}" if cols is not None else ""
    logger.info(
        "[PERF] query %s [%s -> %s] %.3fs rows=%d%s%s",
        name,
        entry["data_ini"],
        entry["data_fim"],
        seconds,
        rows,
        cols_msg,
        f" ERR={error}" if error else "",
    )


def perf_fetch_df(
    name: str,
    fetch_fn: Callable[[], pd.DataFrame],
    data_ini: date | None,
    data_fim: date | None,
) -> pd.DataFrame:
    """Executa consulta, registra tempo e imprime no terminal."""
    t0 = time.perf_counter()
    err: str | None = None
    df = pd.DataFrame()
    try:
        df = fetch_fn()
    except Exception as exc:
        err = str(exc)
        logger.exception("Falha em %s", name)
        raise
    finally:
        elapsed = time.perf_counter() - t0
        cols = len(df.columns) if not df.empty else 0
        perf_record_query(
            name, data_ini, data_fim, elapsed, len(df), cols=cols, error=err,
        )
        if perf_debug_enabled():
            print(
                f"[PERF] query {name}: {elapsed:.3f}s "
                f"rows={len(df)} cols={cols}",
                flush=True,
            )
    return df


@contextmanager
def perf_timed_block(block: str):
    """Mede bloco de transform/render; loga no terminal e no painel debug."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        logger.info("[PERF] block %s: %.3fs", block, elapsed)
        if perf_debug_enabled():
            print(f"[PERF] {block}: {elapsed:.3f}s", flush=True)
            _state().setdefault("blocks", []).append(
                {"block": block, "seconds": round(elapsed, 4)}
            )


def perf_mark_milestone(label: str) -> None:
    """Marca tempo desde o início do rerun até um marco de render."""
    state = _state()
    started = state.get("run_started")
    if started is None:
        return
    elapsed = round(time.perf_counter() - started, 4)
    state.setdefault("milestones", {})[label] = elapsed
    logger.info("[PERF] milestone %s: %.3fs", label, elapsed)


def perf_finalize_page() -> None:
    state = _state()
    started = state.get("run_started")
    if started is not None:
        total = round(time.perf_counter() - started, 4)
        state["page_total_seconds"] = total
        logger.info("[PERF] page total: %.3fs", total)
        if perf_debug_enabled():
            print(f"[PERF] page total: {total:.3f}s", flush=True)


def perf_render_panel() -> None:
    if not perf_debug_enabled():
        return
    state = _state()
    queries = state.get("queries") or []
    with st.expander("Diagnóstico de performance (Lead In & Reuniões)", expanded=False):
        ctx = state.get("context") or {}
        if ctx.get("data_ini") and ctx.get("data_fim"):
            st.caption(f"**Período:** {ctx['data_ini']} -> {ctx['data_fim']}")
        if "modo_historico_agenda" in ctx:
            modo = "histórico" if ctx["modo_historico_agenda"] else "tempo real"
            st.caption(f"**Agenda:** {modo}")

        st.caption(f"**Consultas neste rerun:** {len(queries)}")
        for q in queries:
            err = f" · **erro:** {q['error']}" if q.get("error") else ""
            cols = f" · {q['cols']} cols" if q.get("cols") is not None else ""
            st.caption(
                f"**{q['name']}** · {q.get('data_ini')} -> {q.get('data_fim')} · "
                f"{q['seconds']:.3f}s · {q['rows']} linhas{cols}{err}"
            )

        milestones = state.get("milestones") or {}
        for label, sec in milestones.items():
            st.caption(f"**Até {label}** (aprox.): **{sec:.3f}s**")

        blocks = state.get("blocks") or []
        if blocks:
            st.markdown("**Blocos medidos:**")
            for b in blocks:
                st.caption(f"**{b['block']}**: {b['seconds']:.3f}s")

        total = state.get("page_total_seconds")
        if total is not None:
            st.caption(f"**Tempo total do rerun:** **{total:.3f}s**")
