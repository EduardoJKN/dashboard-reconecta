"""Instrumentação de performance — página Funil da Reconecta.

Ativada via `?debug_perf=1` na URL. Não expõe SQL, credenciais ou dados sensíveis.

Medições também são registradas no logger `reconecta.funil_reconecta.perf`.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable

import pandas as pd
import streamlit as st

logger = logging.getLogger("reconecta.funil_reconecta.perf")

_DEBUG_PARAM = "debug_perf"
PAGE_FUNIL = "funil_reconecta"
_SESSION_KEY = f"_funil_{PAGE_FUNIL}_perf"


def perf_debug_enabled() -> bool:
    try:
        return st.query_params.get(_DEBUG_PARAM) == "1"
    except Exception:
        return False


def perf_reset_run() -> None:
    st.session_state[_SESSION_KEY] = {
        "page": PAGE_FUNIL,
        "queries": [],
        "blocks": [],
        "milestones": {},
        "page_total_seconds": None,
        "main_sections_seconds": None,
        "run_started": time.perf_counter(),
        "context": {},
        "funnel_loads": 0,
        "referencia_loaded": False,
        "referencia_skipped": False,
        "export_prepared": False,
        "benchmark": {},
        "legacy": {},
        "legacy_runs": [],
        "executivas": {},
        "executivas_runs": [],
        "meta": {},
        "progressive": {},
    }


def _state() -> dict[str, Any]:
    return st.session_state.setdefault(
        _SESSION_KEY,
        {"queries": [], "blocks": [], "funnel_loads": 0},
    )


def perf_set_context(
    *,
    data_ini: date | None = None,
    data_fim: date | None = None,
    hist_base_key: str | None = None,
    excluir_testes_aplicacoes: bool | None = None,
    period_preset: str | None = None,
    period_original_ini: date | None = None,
    period_original_fim: date | None = None,
    usar_mes_atual_ate_hoje: bool | None = None,
    meta_proporcional: bool | None = None,
    dias_meta: str | None = None,
) -> None:
    if not perf_debug_enabled():
        return
    ctx: dict[str, Any] = {}
    if data_ini is not None:
        ctx["data_ini"] = data_ini.isoformat()
    if data_fim is not None:
        ctx["data_fim"] = data_fim.isoformat()
    if hist_base_key is not None:
        ctx["hist_base_key"] = hist_base_key
    if excluir_testes_aplicacoes is not None:
        ctx["excluir_testes_aplicacoes"] = excluir_testes_aplicacoes
    if period_preset is not None:
        ctx["periodo_original"] = period_preset
    if period_original_ini is not None and period_original_fim is not None:
        ctx["periodo_preset_range"] = (
            f"{period_original_ini.isoformat()} -> {period_original_fim.isoformat()}"
        )
    if usar_mes_atual_ate_hoje is not None:
        ctx["usar_mes_atual_ate_hoje"] = bool(usar_mes_atual_ate_hoje)
    if meta_proporcional is not None:
        ctx["meta_proporcional"] = bool(meta_proporcional)
    if dias_meta is not None:
        ctx["dias_meta"] = dias_meta
    if data_ini is not None and data_fim is not None:
        ctx["periodo_efetivo"] = (
            f"{data_ini.strftime('%d/%m/%Y')} -> {data_fim.strftime('%d/%m/%Y')}"
        )
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


def perf_record_funnel_load(
    data_ini: date,
    data_fim: date,
    seconds: float,
    *,
    source: str = "load_one_page_funnel",
) -> None:
    _state()["funnel_loads"] = int(_state().get("funnel_loads") or 0) + 1
    perf_record_query(
        source,
        data_ini,
        data_fim,
        seconds,
        rows=1,
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


def perf_set_referencia_status(*, loaded: bool, skipped: bool) -> None:
    if not perf_debug_enabled():
        return
    state = _state()
    state["referencia_loaded"] = bool(loaded)
    state["referencia_skipped"] = bool(skipped)


def perf_set_export_prepared(prepared: bool) -> None:
    if not perf_debug_enabled():
        return
    _state()["export_prepared"] = bool(prepared)


def perf_record_parallel_load(
    *,
    scope: str,
    enabled: bool,
    workers: int,
    mode: str,
    fallback: bool,
    total_seconds: float = 0.0,
    fallback_error: str | None = None,
    groups: list[dict[str, Any]] | None = None,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "scope": scope,
        "enabled": bool(enabled),
        "workers": int(workers),
        "mode": mode,
        "fallback": bool(fallback),
        "fallback_error": fallback_error,
        "total_seconds": round(total_seconds, 4) if total_seconds else 0.0,
        "groups": list(groups or []),
    }
    state = _state()
    parallel = state.setdefault("parallel", {})
    runs = parallel.setdefault("runs", [])
    runs.append(entry)
    parallel.update(
        {
            "parallel_enabled": bool(enabled) and not fallback,
            "parallel_workers": int(workers),
            "parallel_fallback": bool(fallback),
            "parallel_mode": mode,
            "parallel_last_scope": scope,
            "parallel_last_seconds": entry["total_seconds"],
        }
    )
    if fallback_error:
        parallel["parallel_fallback_error"] = fallback_error
    logger.info(
        "[PERF] parallel scope=%s mode=%s workers=%d fallback=%s %.3fs",
        scope,
        mode,
        workers,
        fallback,
        total_seconds,
    )


def perf_record_benchmark_run(
    *,
    version: str,
    windows: int,
    repo_queries: int,
    funnel_loads_avoided: int,
    used_v2: bool,
    fallback_error: str | None,
    legacy_benchmark_mode: str | None = None,
    legacy_benchmark_time: float | None = None,
    legacy_benchmark_queries: int | None = None,
    legacy_benchmark_fallback: str | None = None,
    legacy_benchmark_batch_enabled: bool | None = None,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "version": version,
        "windows": int(windows),
        "repo_queries": int(repo_queries),
        "funnel_loads_avoided": int(funnel_loads_avoided),
        "used_v2": bool(used_v2),
        "fallback_error": fallback_error,
        "legacy_benchmark_mode": legacy_benchmark_mode,
        "legacy_benchmark_time": legacy_benchmark_time,
        "legacy_benchmark_queries": legacy_benchmark_queries,
        "legacy_benchmark_fallback": legacy_benchmark_fallback,
        "legacy_benchmark_batch_enabled": legacy_benchmark_batch_enabled,
    }
    _state()["benchmark"] = entry
    logger.info(
        "[PERF] benchmark %s windows=%d repo_queries=%d funnel_loads_avoided=%d "
        "legacy_mode=%s legacy_queries=%s%s%s",
        version,
        windows,
        repo_queries,
        funnel_loads_avoided,
        legacy_benchmark_mode or "—",
        legacy_benchmark_queries if legacy_benchmark_queries is not None else "—",
        f" legacy_time={legacy_benchmark_time:.3f}s" if legacy_benchmark_time else "",
        f" FALLBACK={fallback_error or legacy_benchmark_fallback}"
        if fallback_error or legacy_benchmark_fallback
        else "",
    )


def perf_record_legacy_benchmark_batch(
    *,
    mode: str,
    seconds: float | None,
    queries: int,
    fallback_error: str | None = None,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "mode": mode,
        "seconds": round(seconds, 4) if seconds is not None else None,
        "queries": int(queries),
        "fallback_error": fallback_error,
    }
    state = _state()
    state["legacy_benchmark_batch"] = entry
    logger.info(
        "[PERF] legacy_benchmark_batch mode=%s queries=%d%s%s",
        mode,
        queries,
        f" {seconds:.3f}s" if seconds is not None else "",
        f" FALLBACK={fallback_error}" if fallback_error else "",
    )


def perf_record_meta_init(
    *,
    session_hit: bool,
    seconds: float,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "session_hit": bool(session_hit),
        "init_seconds": round(seconds, 4),
    }
    state = _state()
    meta = state.setdefault("meta", {})
    meta.update(entry)
    logger.info(
        "[PERF] meta init session_hit=%s %.3fs",
        session_hit,
        seconds,
    )


def perf_record_meta_load(
    *,
    seconds: float,
    cache_hit: bool,
    session_hit: bool,
    db_configured: bool,
    row_found: bool | None = None,
    cache_invalidated: bool = False,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "load_seconds": round(seconds, 4),
        "cache_hit": bool(cache_hit),
        "session_hit": bool(session_hit),
        "db_configured": bool(db_configured),
        "row_found": row_found,
        "cache_invalidated": bool(cache_invalidated),
        "batch_enabled": False,
    }
    state = _state()
    meta = state.setdefault("meta", {})
    meta.update(entry)
    logger.info(
        "[PERF] meta load db=%s cache_hit=%s session_hit=%s %.3fs row=%s",
        db_configured,
        cache_hit,
        session_hit,
        seconds,
        row_found,
    )


def perf_record_legacy_run(
    data_ini: date,
    data_fim: date,
    seconds: float,
    *,
    version: str,
    rows: int,
    fallback_error: str | None,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "version": version,
        "seconds": round(seconds, 4),
        "data_ini": data_ini.isoformat(),
        "data_fim": data_fim.isoformat(),
        "rows": int(rows),
        "fallback_error": fallback_error,
    }
    state = _state()
    runs = state.setdefault("legacy_runs", [])
    runs.append(entry)
    state["legacy"] = entry
    logger.info(
        "[PERF] legacy %s [%s -> %s] %.3fs rows=%d%s",
        version,
        entry["data_ini"],
        entry["data_fim"],
        seconds,
        rows,
        f" FALLBACK={fallback_error}" if fallback_error else "",
    )
    perf_record_query(
        f"legacy_diario_{version}",
        data_ini,
        data_fim,
        seconds,
        rows,
    )


def perf_record_executivas_run(
    data_ini: date,
    data_fim: date,
    seconds: float,
    *,
    version: str,
    rows: int,
    cols: int,
    fallback_error: str | None,
) -> None:
    if not perf_debug_enabled():
        return
    entry = {
        "version": version,
        "seconds": round(seconds, 4),
        "data_ini": data_ini.isoformat(),
        "data_fim": data_fim.isoformat(),
        "rows": int(rows),
        "cols": int(cols),
        "fallback_error": fallback_error,
    }
    state = _state()
    state.setdefault("executivas_runs", []).append(entry)
    state["executivas"] = entry
    logger.info(
        "[PERF] executivas %s [%s -> %s] %.3fs rows=%d cols=%d%s",
        version,
        entry["data_ini"],
        entry["data_fim"],
        seconds,
        rows,
        cols,
        f" FALLBACK={fallback_error}" if fallback_error else "",
    )
    perf_record_query(
        f"executivas_{version}",
        data_ini,
        data_fim,
        seconds,
        rows,
        cols=cols,
    )


def perf_finalize_first_fold() -> None:
    """Marca tempo até a primeira dobra útil (vitrine + gaps, sem benchmark lazy)."""
    if not perf_debug_enabled():
        return
    state = _state()
    started = state.get("run_started")
    if started is None:
        return
    total = round(time.perf_counter() - started, 4)
    state["first_fold_seconds"] = total
    prog = state.setdefault("progressive", {})
    prog["first_fold_time"] = total
    milestones = state.setdefault("milestones", {})
    milestones["primeira dobra útil"] = total
    logger.info("[PERF] primeira dobra útil: %.3fs", total)
    print(f"[PERF] primeira dobra útil: {total:.3f}s", flush=True)


def perf_record_progressive(
    *,
    enabled: bool,
    benchmark_mode: str = "classic",
    benchmark_auto_loaded: bool = False,
    benchmark_skipped: bool = False,
    benchmark_time: float | None = None,
    benchmark_lazy_seconds: float | None = None,
) -> None:
    """Registra métricas CP9/CP9.1. `benchmark_lazy_seconds` mantido por compat."""
    bm_t = benchmark_time
    if bm_t is None and benchmark_lazy_seconds is not None:
        bm_t = benchmark_lazy_seconds
    if not perf_debug_enabled():
        return
    entry = {
        "progressive_load_enabled": bool(enabled),
        "progressive_benchmark_mode": benchmark_mode,
        "benchmark_auto_loaded": bool(benchmark_auto_loaded),
        "benchmark_loaded": bool(benchmark_auto_loaded),
        "benchmark_skipped": bool(benchmark_skipped),
        "benchmark_time": round(bm_t, 4) if bm_t is not None else None,
        "benchmark_lazy_time": round(bm_t, 4) if bm_t is not None else None,
    }
    state = _state()
    prog = state.setdefault("progressive", {})
    prog.update(entry)
    logger.info(
        "[PERF] progressive enabled=%s mode=%s bm_auto=%s bm_skipped=%s bm_time=%s",
        enabled,
        benchmark_mode,
        benchmark_auto_loaded,
        benchmark_skipped,
        bm_t,
    )


def perf_finalize_page(*, main_sections_only: bool = False) -> None:
    state = _state()
    started = state.get("run_started")
    if started is not None:
        total = round(time.perf_counter() - started, 4)
        if main_sections_only:
            state["main_sections_seconds"] = total
            prog = state.setdefault("progressive", {})
            mode = prog.get("progressive_benchmark_mode", "classic")
            if mode != "manual" or prog.get("benchmark_auto_loaded"):
                prog["full_page_time"] = total
            label = "main sections total"
        else:
            state["page_total_seconds"] = total
            label = "page total"
        logger.info("[PERF] %s: %.3fs", label, total)
        if perf_debug_enabled():
            print(f"[PERF] {label}: {total:.3f}s", flush=True)


def perf_finalize_full_page() -> None:
    state = _state()
    started = state.get("run_started")
    if started is not None:
        total = round(time.perf_counter() - started, 4)
        state["page_total_seconds"] = total
        logger.info("[PERF] page total: %.3fs", total)
        if perf_debug_enabled():
            print(f"[PERF] page total: {total:.3f}s", flush=True)


def perf_query_count() -> int:
    return len(_state().get("queries") or [])


def perf_funnel_load_count() -> int:
    return int(_state().get("funnel_loads") or 0)


def _block_seconds(state: dict[str, Any], *names: str) -> float | None:
    blocks = state.get("blocks") or []
    by_name = {b["block"]: b["seconds"] for b in blocks}
    for name in names:
        if name in by_name:
            return float(by_name[name])
    return None


def perf_render_panel() -> None:
    if not perf_debug_enabled():
        return
    state = _state()
    queries = state.get("queries") or []
    with st.expander(
        "Diagnóstico de performance (Funil da Reconecta)",
        expanded=False,
    ):
        ctx = state.get("context") or {}
        if ctx.get("periodo_original"):
            st.caption(f"**Período original:** {ctx['periodo_original']}")
        if ctx.get("periodo_preset_range"):
            st.caption(f"**Range do preset:** {ctx['periodo_preset_range']}")
        if ctx.get("periodo_efetivo"):
            st.caption(f"**Período efetivo:** {ctx['periodo_efetivo']}")
        elif ctx.get("data_ini") and ctx.get("data_fim"):
            st.caption(f"**Período:** {ctx['data_ini']} -> {ctx['data_fim']}")
        if "usar_mes_atual_ate_hoje" in ctx:
            st.caption(
                f"**Mês atual até hoje:** "
                f"{'sim' if ctx['usar_mes_atual_ate_hoje'] else 'não'}"
            )
        if "meta_proporcional" in ctx:
            st.caption(
                f"**Meta proporcional:** "
                f"{'sim' if ctx['meta_proporcional'] else 'não'}"
            )
        if ctx.get("dias_meta"):
            st.caption(f"**Dias meta:** {ctx['dias_meta']}")
        if ctx.get("hist_base_key"):
            st.caption(f"**Base histórica:** {ctx['hist_base_key']}")
        if "excluir_testes_aplicacoes" in ctx:
            st.caption(
                f"**Excluir testes (aplicações):** "
                f"{'sim' if ctx['excluir_testes_aplicacoes'] else 'não'}"
            )

        st.markdown("**Resumo por bloco**")
        for label, keys in (
            ("Atual", ("carregamento Atual real",)),
            ("Meta oficial", ("carregamento Meta oficial",)),
            ("Benchmark essencial", ("Benchmark histórico",)),
            (
                "Referência histórica",
                ("Referência histórica", "renderização base meta / editor"),
            ),
            ("Export", ("Export",)),
        ):
            sec = _block_seconds(state, *keys)
            if sec is not None:
                st.caption(f"**{label}:** {sec:.3f}s")

        ref_loaded = state.get("referencia_loaded")
        ref_skipped = state.get("referencia_skipped")
        if ref_skipped:
            st.caption("**Referência histórica:** pulada neste rerun")
        elif ref_loaded:
            st.caption("**Referência histórica:** carregada neste rerun")
        else:
            st.caption("**Referência histórica:** não solicitada")

        if state.get("export_prepared"):
            st.caption("**Export:** arquivos preparados neste rerun")
        else:
            st.caption("**Export:** não preparado")

        main_t = state.get("main_sections_seconds")
        if main_t is not None:
            st.caption(
                f"**Tempo seções principais** (até export): **{main_t:.3f}s**"
            )
        total = state.get("page_total_seconds")
        if total is not None:
            st.caption(f"**Tempo total do rerun:** **{total:.3f}s**")

        st.caption(
            f"**Cargas de funil (`load_one_page_funnel`):** "
            f"{perf_funnel_load_count()}"
        )
        bm = state.get("benchmark") or {}
        if bm:
            ver = bm.get("version", "—")
            wins = bm.get("windows", "—")
            rq = bm.get("repo_queries", "—")
            avoided = bm.get("funnel_loads_avoided", "—")
            active = "v2" if bm.get("used_v2") else "v1"
            st.caption(
                f"**Benchmark:** ativo={active} · versão={ver} · "
                f"janelas={wins} · repo_queries≈{rq} · "
                f"cargas funil evitadas={avoided}"
            )
            if bm.get("fallback_error"):
                st.caption(
                    f"**Benchmark fallback:** {bm['fallback_error']}"
                )
            leg_mode = bm.get("legacy_benchmark_mode") or "per_window"
            batch_on = bm.get("legacy_benchmark_batch_enabled")
            if batch_on is None:
                batch_on = leg_mode == "batch"
            st.caption(
                f"**Legacy benchmark:** mode={leg_mode} · "
                f"batch_enabled={'true' if batch_on else 'false'}"
            )
            leg_q = bm.get("legacy_benchmark_queries", "—")
            leg_t = bm.get("legacy_benchmark_time")
            leg_t_txt = f"{leg_t:.3f}s" if leg_t is not None else "—"
            st.caption(
                f"**Legacy benchmark queries/tempo:** "
                f"queries≈{leg_q} · tempo={leg_t_txt}"
            )
            if bm.get("legacy_benchmark_fallback"):
                st.caption(
                    f"**Legacy benchmark fallback:** "
                    f"{bm['legacy_benchmark_fallback']}"
                )
        leg_batch = state.get("legacy_benchmark_batch") or {}
        if leg_batch:
            st.caption(
                f"**Legacy batch (último):** mode={leg_batch.get('mode', '—')} · "
                f"queries={leg_batch.get('queries', '—')} · "
                f"tempo={leg_batch.get('seconds', 0) or 0:.3f}s"
            )
        leg = state.get("legacy") or {}
        if leg:
            st.caption(
                f"**Legacy:** versão={leg.get('version', '—')} · "
                f"tempo={leg.get('seconds', 0):.3f}s · "
                f"linhas={leg.get('rows', '—')}"
            )
            if leg.get("fallback_error"):
                st.caption(f"**Legacy fallback:** {leg['fallback_error']}")
        legacy_runs = state.get("legacy_runs") or []
        if len(legacy_runs) > 1:
            st.caption(
                f"**Chamadas legacy neste rerun:** {len(legacy_runs)} "
                f"(Atual + janelas benchmark)"
            )
        ex = state.get("executivas") or {}
        if ex:
            st.caption(
                f"**Executivas:** versão={ex.get('version', '—')} · "
                f"tempo={ex.get('seconds', 0):.3f}s · "
                f"linhas={ex.get('rows', '—')} · cols={ex.get('cols', '—')}"
            )
            if ex.get("fallback_error"):
                st.caption(f"**Executivas fallback:** {ex['fallback_error']}")
        ex_runs = state.get("executivas_runs") or []
        if len(ex_runs) > 1:
            st.caption(f"**Chamadas executivas neste rerun:** {len(ex_runs)}")
        meta = state.get("meta") or {}
        if meta:
            sess = meta.get("session_hit")
            cache = meta.get("cache_hit")
            load_t = meta.get("load_seconds")
            init_t = meta.get("init_seconds")
            st.caption(
                f"**Meta oficial:** mode=per_window · batch_enabled=false · "
                f"session_hit={'true' if sess else 'false'} · "
                f"cache_hit={'true' if cache else 'false'}"
            )
            if init_t is not None:
                st.caption(f"**Meta init:** {init_t:.3f}s")
            if load_t is not None:
                st.caption(f"**Meta load (DB):** {load_t:.3f}s")
            if meta.get("cache_invalidated"):
                st.caption("**Meta cache:** invalidado neste rerun")
        leg_atual_ver = (state.get("legacy") or {}).get("version", "—")
        ex_ver = (state.get("executivas") or {}).get("version", "—")
        bm_leg = (bm or {}).get("legacy_benchmark_mode", "per_window")
        bm_batch = (bm or {}).get("legacy_benchmark_batch_enabled", False)
        st.caption(
            f"**Versões:** legacy={leg_atual_ver} · executivas={ex_ver} · "
            f"legacy_benchmark={bm_leg} · batch_enabled="
            f"{'true' if bm_batch else 'false'}"
        )
        prog = state.get("progressive") or {}
        if prog:
            mode = prog.get("progressive_benchmark_mode", "—")
            st.caption(
                f"**Progressive (CP9.1):** enabled="
                f"{'true' if prog.get('progressive_load_enabled') else 'false'} · "
                f"mode={mode} · "
                f"benchmark_auto_loaded="
                f"{'true' if prog.get('benchmark_auto_loaded') else 'false'} · "
                f"benchmark_skipped={'true' if prog.get('benchmark_skipped') else 'false'}"
            )
            ff = prog.get("first_fold_time") or state.get("first_fold_seconds")
            if ff is not None:
                st.caption(f"**Tempo primeira dobra útil:** {ff:.3f}s")
            full_t = prog.get("full_page_time")
            if full_t is not None:
                st.caption(f"**Tempo análise completa:** {full_t:.3f}s")
            bm_t = prog.get("benchmark_time") or prog.get("benchmark_lazy_time")
            if bm_t is not None:
                st.caption(f"**Benchmark (este rerun):** {bm_t:.3f}s")

        parallel = state.get("parallel") or {}
        if parallel:
            p_en = parallel.get("parallel_enabled")
            p_w = parallel.get("parallel_workers", "—")
            p_fb = parallel.get("parallel_fallback")
            p_mode = parallel.get("parallel_mode", "—")
            st.caption(
                f"**Paralelo (CP8):** enabled={'true' if p_en else 'false'} · "
                f"workers={p_w} · mode={p_mode} · "
                f"fallback={'true' if p_fb else 'false'}"
            )
            if parallel.get("parallel_fallback_error"):
                st.caption(
                    f"**Paralelo fallback:** {parallel['parallel_fallback_error']}"
                )
            runs = parallel.get("runs") or []
            if runs:
                st.markdown("**Grupos paralelos**")
                for r in runs:
                    groups = r.get("groups") or []
                    grp_txt = ", ".join(
                        f"{g['name']}={g['seconds']:.3f}s" for g in groups
                    ) if groups else "—"
                    st.caption(
                        f"**{r.get('scope', '—')}** · {r.get('mode', '—')} · "
                        f"total={r.get('total_seconds', 0):.3f}s · {grp_txt}"
                    )
        st.caption(
            f"**Consultas / cargas medidas neste rerun:** {len(queries)}"
        )

        milestones = state.get("milestones") or {}
        if milestones:
            st.markdown("**Marcos**")
            for label, sec in milestones.items():
                st.caption(f"**Até {label}** (aprox.): **{sec:.3f}s**")

        blocks = state.get("blocks") or []
        if blocks:
            st.markdown("**Blocos medidos (detalhe)**")
            for b in blocks:
                st.caption(f"**{b['block']}**: {b['seconds']:.3f}s")

        if queries:
            st.markdown("**Cargas individuais**")
            for q in queries:
                err = f" · **erro:** {q['error']}" if q.get("error") else ""
                cols = f" · {q['cols']} cols" if q.get("cols") is not None else ""
                st.caption(
                    f"**{q['name']}** · {q.get('data_ini')} -> {q.get('data_fim')} · "
                    f"{q['seconds']:.3f}s · {q['rows']} linhas{cols}{err}"
                )
