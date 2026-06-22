"""Instrumentação de performance — páginas de Marketing.

Ativada via `?debug_perf=1` na URL. Não expõe SQL, credenciais ou dados sensíveis.

Cada página usa um namespace isolado em session_state (ex.: ``marketing_overview``,
``marketing_campaigns``) para não misturar contadores entre páginas."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from typing import Any

import streamlit as st

logger = logging.getLogger("reconecta.marketing.perf")

_DEBUG_PARAM = "debug_perf"

PAGE_OVERVIEW = "marketing_overview"
PAGE_CAMPAIGNS = "marketing_campaigns"
PAGE_CREATIVES = "marketing_creatives"


def _session_key(page: str) -> str:
    return f"_mkt_{page}_perf"


def perf_debug_enabled() -> bool:
    try:
        return st.query_params.get(_DEBUG_PARAM) == "1"
    except Exception:
        return False


def perf_reset_run(page: str = PAGE_OVERVIEW) -> None:
    import time

    st.session_state[_session_key(page)] = {
        "page": page,
        "queries": [],
        "kpi_render_seconds": None,
        "selector_render_seconds": None,
        "funil_render_seconds": None,
        "top12_render_seconds": None,
        "page_total_seconds": None,
        "run_started": time.perf_counter(),
        "context": {},
    }


def _state(page: str = PAGE_OVERVIEW) -> dict[str, Any]:
    return st.session_state.setdefault(_session_key(page), {"queries": []})


def perf_set_context(
    page: str,
    *,
    data_ini: date | None = None,
    data_fim: date | None = None,
    canais: list[str] | None = None,
    funil_item: str | None = None,
    campanha: list[str] | None = None,
    status: list[str] | None = None,
) -> None:
    """Registra contexto do rerun (sem dados sensíveis)."""
    if not perf_debug_enabled():
        return
    ctx: dict[str, Any] = {}
    if data_ini is not None:
        ctx["data_ini"] = data_ini.isoformat()
    if data_fim is not None:
        ctx["data_fim"] = data_fim.isoformat()
    if canais is not None:
        ctx["canais"] = list(canais)
    if funil_item is not None:
        ctx["funil_item"] = funil_item
    if campanha is not None:
        ctx["campanha"] = list(campanha)
    if status is not None:
        ctx["status"] = list(status)
    _state(page)["context"] = ctx


def perf_record_query(
    name: str,
    data_ini: date | None,
    data_fim: date | None,
    seconds: float,
    rows: int,
    *,
    page: str = PAGE_OVERVIEW,
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
    _state(page).setdefault("queries", []).append(entry)
    cols_msg = f" cols={cols}" if cols is not None else ""
    logger.info(
        "query [%s] %s [%s -> %s] %.3fs rows=%d%s%s",
        page,
        name,
        entry["data_ini"],
        entry["data_fim"],
        seconds,
        rows,
        cols_msg,
        f" ERR={error}" if error else "",
    )


def _mark_elapsed(page: str, field: str) -> None:
    import time

    state = _state(page)
    if state.get(field) is not None:
        return
    started = state.get("run_started")
    if started is not None:
        state[field] = round(time.perf_counter() - started, 4)


def perf_mark_kpi_rendered(page: str = PAGE_OVERVIEW) -> None:
    _mark_elapsed(page, "kpi_render_seconds")


def perf_mark_selector_rendered(page: str = PAGE_CAMPAIGNS) -> None:
    _mark_elapsed(page, "selector_render_seconds")


def perf_mark_funil_rendered(page: str = PAGE_CAMPAIGNS) -> None:
    _mark_elapsed(page, "funil_render_seconds")


def perf_mark_top12_rendered(page: str = PAGE_CREATIVES) -> None:
    _mark_elapsed(page, "top12_render_seconds")


def perf_finalize_page(page: str = PAGE_OVERVIEW) -> None:
    import time

    state = _state(page)
    started = state.get("run_started")
    if started is not None:
        state["page_total_seconds"] = round(time.perf_counter() - started, 4)


@contextmanager
def perf_timed_block(block: str, *, page: str = PAGE_OVERVIEW):
    import time

    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        logger.info("block [%s] %s: %.3fs", page, block, elapsed)
        if perf_debug_enabled():
            blocks = _state(page).setdefault("blocks", [])
            blocks.append({"block": block, "seconds": round(elapsed, 4)})


def perf_query_count(page: str = PAGE_OVERVIEW) -> int:
    return len(_state(page).get("queries") or [])


def perf_render_panel(page: str = PAGE_OVERVIEW) -> None:
    if not perf_debug_enabled():
        return
    state = _state(page)
    queries = state.get("queries") or []
    page_name = state.get("page") or page
    with st.expander(
        f"Diagnóstico de performance ({page_name})",
        expanded=False,
    ):
        st.caption(f"**Consultas executadas neste rerun:** {len(queries)}")
        ctx = state.get("context") or {}
        if ctx:
            parts = []
            if ctx.get("data_ini") and ctx.get("data_fim"):
                parts.append(f"**Período:** {ctx['data_ini']} -> {ctx['data_fim']}")
            if ctx.get("canais") is not None:
                parts.append(f"**Canais:** {', '.join(ctx['canais']) or 'todos'}")
            if ctx.get("funil_item"):
                parts.append(f"**Funil:** `{ctx['funil_item']}`")
            if ctx.get("campanha") is not None:
                parts.append(f"**Campanha:** {', '.join(ctx['campanha']) or 'todas'}")
            if ctx.get("status") is not None:
                parts.append(f"**Status:** {', '.join(ctx['status']) or 'todos'}")
            st.caption(" · ".join(parts))
        for q in queries:
            err = f" · **erro:** {q['error']}" if q.get("error") else ""
            cols = f" · {q['cols']} cols" if q.get("cols") is not None else ""
            st.caption(
                f"**{q['name']}** · {q.get('data_ini')} -> {q.get('data_fim')} · "
                f"{q['seconds']:.3f}s · {q['rows']} linhas{cols}{err}"
            )
        kpi_t = state.get("kpi_render_seconds")
        if kpi_t is not None:
            kpi_label = (
                "Performance Meta"
                if page_name == PAGE_CREATIVES
                else "Financeiro/Volume"
            )
            st.caption(
                f"**Tempo ate {kpi_label}** (aprox.): **{kpi_t:.3f}s**"
            )
        sel_t = state.get("selector_render_seconds")
        if sel_t is not None:
            sel_label = (
                "seletor de criativo"
                if page_name == PAGE_CREATIVES
                else "seletor de campanha"
            )
            st.caption(
                f"**Tempo ate {sel_label}** (aprox.): **{sel_t:.3f}s**"
            )
        funil_t = state.get("funil_render_seconds")
        if funil_t is not None:
            st.caption(
                f"**Tempo ate cards do funil** (aprox.): **{funil_t:.3f}s**"
            )
        top12_t = state.get("top12_render_seconds")
        if top12_t is not None:
            st.caption(
                f"**Tempo ate Top 12** (aprox.): **{top12_t:.3f}s**"
            )
        total = state.get("page_total_seconds")
        if total is not None:
            st.caption(f"**Tempo total do rerun:** **{total:.3f}s**")
        blocks = state.get("blocks") or []
        for b in blocks:
            st.caption(f"**{b['block']}**: {b['seconds']:.3f}s")
