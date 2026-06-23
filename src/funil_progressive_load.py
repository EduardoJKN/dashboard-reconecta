# -*- coding: utf-8 -*-
"""Carregamento progressivo - Funil da Reconecta (CP9 / CP9.1 / CP9.2).

CP9.1: vitrine rapida na primeira dobra; benchmark automatico depois (modo auto).

Flags:
  FUNIL_PROGRESSIVE_LOAD=1|0           (default ON)
  FUNIL_PROGRESSIVE_BENCHMARK_MODE=    auto | manual | classic
    auto    - benchmark apos a primeira dobra, sem clique (default)
    manual  - botao Carregar benchmark historico (fallback/debug)
    classic - eager como antes do CP9 (benchmark antes da vitrine)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import streamlit as st

BENCHMARK_LOAD_BTN_KEY = "funil_load_benchmark_btn"


@dataclass(frozen=True)
class BenchmarkCacheContext:
    """Identidade completa do benchmark para cache em session_state."""

    data_ini: date
    data_fim: date
    hist_base_key: str
    same_interval: bool
    custom_granularity: str
    custom_n_periods: int
    ranges_fingerprint: str
    hist_ini_iso: str
    hist_fim_iso: str
    excluir_testes_aplicacoes: bool
    mes_atual_ate_hoje: bool = False


def build_benchmark_cache_context(
    *,
    data_ini: date,
    data_fim: date,
    hist_spec: Any,
    hist_base_key: str,
    same_interval: bool,
    custom_granularity: str = "mes",
    custom_n_periods: int = 3,
    excluir_testes_aplicacoes: bool,
    mes_atual_ate_hoje: bool = False,
) -> BenchmarkCacheContext:
    from src.funil_benchmark import ranges_to_cache_json

    ranges_fp = (
        ranges_to_cache_json(hist_spec.ranges) if hist_spec.ranges else ""
    )
    return BenchmarkCacheContext(
        data_ini=data_ini,
        data_fim=data_fim,
        hist_base_key=hist_base_key,
        same_interval=bool(same_interval),
        custom_granularity=custom_granularity,
        custom_n_periods=int(custom_n_periods),
        ranges_fingerprint=ranges_fp,
        hist_ini_iso=hist_spec.hist_ini.isoformat(),
        hist_fim_iso=hist_spec.hist_fim.isoformat(),
        excluir_testes_aplicacoes=bool(excluir_testes_aplicacoes),
        mes_atual_ate_hoje=bool(mes_atual_ate_hoje),
    )


def make_benchmark_cache_key(ctx: BenchmarkCacheContext) -> str:
    """Chave estavel com periodo + preset historico + janelas + flags."""
    payload = "|".join(
        [
            ctx.ranges_fingerprint,
            ctx.hist_ini_iso,
            ctx.hist_fim_iso,
            ctx.hist_base_key,
            "si1" if ctx.same_interval else "si0",
            ctx.custom_granularity,
            str(ctx.custom_n_periods),
            "xt1" if ctx.excluir_testes_aplicacoes else "xt0",
            "ma1" if ctx.mes_atual_ate_hoje else "ma0",
        ],
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return (
        f"{ctx.data_ini.isoformat()}_{ctx.data_fim.isoformat()}_"
        f"{ctx.hist_base_key}_{digest}"
    )


def benchmark_loaded_session_key(ctx: BenchmarkCacheContext) -> str:
    return f"funil_benchmark_loaded_{make_benchmark_cache_key(ctx)}"


def benchmark_cache_session_key(ctx: BenchmarkCacheContext) -> str:
    return f"funil_benchmark_data_{make_benchmark_cache_key(ctx)}"


def is_benchmark_loaded(ctx: BenchmarkCacheContext) -> bool:
    return bool(st.session_state.get(benchmark_loaded_session_key(ctx)))


def mark_benchmark_loaded(ctx: BenchmarkCacheContext) -> None:
    st.session_state[benchmark_loaded_session_key(ctx)] = True


def get_cached_benchmark(ctx: BenchmarkCacheContext) -> dict[str, Any] | None:
    raw = st.session_state.get(benchmark_cache_session_key(ctx))
    return dict(raw) if isinstance(raw, dict) else None


def cache_benchmark(ctx: BenchmarkCacheContext, raw: dict[str, Any]) -> None:
    st.session_state[benchmark_cache_session_key(ctx)] = dict(raw)
    mark_benchmark_loaded(ctx)


def funil_progressive_load_enabled() -> bool:
    flag = os.environ.get("FUNIL_PROGRESSIVE_LOAD", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def funil_progressive_benchmark_mode() -> str:
    """auto | manual | classic."""
    if not funil_progressive_load_enabled():
        return "classic"
    mode = os.environ.get("FUNIL_PROGRESSIVE_BENCHMARK_MODE", "auto").strip().lower()
    if mode in {"classic", "off", "eager", "0"}:
        return "classic"
    if mode == "manual":
        return "manual"
    return "auto"


def funil_period_key(data_ini: date, data_fim: date) -> str:
    return f"{data_ini.isoformat()}_{data_fim.isoformat()}"


def should_defer_benchmark(data_ini: date, data_fim: date) -> bool:
    """True quando o benchmark nao deve bloquear a primeira dobra."""
    mode = funil_progressive_benchmark_mode()
    if mode == "classic":
        return False
    return True


def should_auto_compute_benchmark(ctx: BenchmarkCacheContext) -> bool:
    """True quando o benchmark deve carregar automaticamente apos a primeira dobra."""
    mode = funil_progressive_benchmark_mode()
    if mode == "auto":
        return True
    if mode == "manual":
        return is_benchmark_loaded(ctx)
    return False


def should_compute_benchmark(ctx: BenchmarkCacheContext) -> bool:
    """True se `_load_page_benchmark` deve executar o calculo nesta chamada."""
    mode = funil_progressive_benchmark_mode()
    if mode == "classic":
        return True
    if mode == "auto":
        return True
    if mode == "manual":
        return is_benchmark_loaded(ctx)
    return True


def should_show_benchmark_button(ctx: BenchmarkCacheContext) -> bool:
    mode = funil_progressive_benchmark_mode()
    return mode == "manual" and not is_benchmark_loaded(ctx)
