"""Carregamento paralelo experimental — Funil da Reconecta (CP8).

Workers executam apenas `run_sql_file` / lógica pura — sem `st.*` nem
`@st.cache_data`. O thread principal registra perf e monta snapshots.

Flags:
  FUNIL_PARALLEL_LOADS=0|1  (default OFF)
  FUNIL_PARALLEL_WORKERS=N  (1–4, default 3 se inválido)
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, TypeVar

import pandas as pd

from src.db import run_sql_file
from src.repositories import (
    EXECUTIVAS_VERSION_V1,
    EXECUTIVAS_VERSION_V2,
    LEGACY_VERSION_V1,
    LEGACY_VERSION_V2,
    _date_params,
    funil_executivas_v2_enabled,
    funil_legacy_v2_enabled,
)

logger = logging.getLogger("reconecta.funil_parallel")

T = TypeVar("T")

DEFAULT_WORKERS = 3
MIN_WORKERS = 1
MAX_WORKERS = 4  # pool_size=5 + max_overflow=5 — conservador para não saturar o pool


def funil_parallel_loads_enabled() -> bool:
    flag = os.environ.get("FUNIL_PARALLEL_LOADS", "0").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def funil_parallel_workers() -> int:
    """Workers para ThreadPoolExecutor — clamp 1..4; inválido → 3."""
    raw = os.environ.get("FUNIL_PARALLEL_WORKERS", "").strip()
    if raw.isdigit():
        n = int(raw)
        return max(MIN_WORKERS, min(n, MAX_WORKERS))
    return DEFAULT_WORKERS


@dataclass
class ParallelTaskResult:
    name: str
    seconds: float
    error: str | None = None


@dataclass
class ParallelLoadReport:
    enabled: bool = False
    workers: int = 0
    mode: str = "sequential"
    fallback: bool = False
    fallback_error: str | None = None
    total_seconds: float = 0.0
    groups: list[ParallelTaskResult] = field(default_factory=list)
    scope: str = ""


def _fetch_prevendas_uncached(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file(
        "prevendas_overview_diario.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def _fetch_investimento_uncached(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file("investimento_diario.sql", _date_params(data_ini, data_fim))
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def _fetch_legacy_v1_uncached(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool,
) -> pd.DataFrame:
    params = _date_params(data_ini, data_fim)
    params["excluir_testes_aplicacoes"] = 1 if excluir_testes_aplicacoes else 0
    df = run_sql_file("one_page_legacy_diario.sql", params)
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def _fetch_legacy_v2_uncached(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool,
) -> pd.DataFrame:
    params = _date_params(data_ini, data_fim)
    params["excluir_testes_aplicacoes"] = 1 if excluir_testes_aplicacoes else 0
    df = run_sql_file("one_page_legacy_diario_v2.sql", params)
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def fetch_legacy_for_funil_uncached(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool = False,
) -> tuple[pd.DataFrame, str, str | None]:
    """Legacy para Funil — mesma regra v2/fallback v1, sem cache Streamlit."""
    if funil_legacy_v2_enabled():
        try:
            df = _fetch_legacy_v2_uncached(
                data_ini, data_fim, excluir_testes_aplicacoes=excluir_testes_aplicacoes
            )
            return df, LEGACY_VERSION_V2, None
        except Exception as exc:
            logger.exception("Legacy v2 uncached falhou — fallback v1")
            df = _fetch_legacy_v1_uncached(
                data_ini, data_fim, excluir_testes_aplicacoes=excluir_testes_aplicacoes
            )
            return df, LEGACY_VERSION_V1, str(exc)
    df = _fetch_legacy_v1_uncached(
        data_ini, data_fim, excluir_testes_aplicacoes=excluir_testes_aplicacoes
    )
    return df, LEGACY_VERSION_V1, None


def _fetch_executivas_v1_uncached(data_ini: date, data_fim: date) -> pd.DataFrame:
    from src.transforms import executivas_aplicar_time_vendas_overrides

    df = run_sql_file("dashboard_executivas.sql", _date_params(data_ini, data_fim))
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
        df = executivas_aplicar_time_vendas_overrides(df)
    return df


def _fetch_executivas_v2_uncached(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file(
        "dashboard_executivas_funil_v2.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def fetch_executivas_for_funil_uncached(
    data_ini: date,
    data_fim: date,
) -> tuple[pd.DataFrame, str, str | None]:
    """Executivas para Funil — mesma regra v2/fallback v1, sem cache Streamlit."""
    if funil_executivas_v2_enabled():
        try:
            df = _fetch_executivas_v2_uncached(data_ini, data_fim)
            return df, EXECUTIVAS_VERSION_V2, None
        except Exception as exc:
            logger.exception("Executivas v2 uncached falhou — fallback v1")
            df = _fetch_executivas_v1_uncached(data_ini, data_fim)
            return df, EXECUTIVAS_VERSION_V1, str(exc)
    df = _fetch_executivas_v1_uncached(data_ini, data_fim)
    return df, EXECUTIVAS_VERSION_V1, None


def _run_timed(name: str, fn: Callable[[], T]) -> tuple[T, ParallelTaskResult]:
    t0 = time.perf_counter()
    err: str | None = None
    try:
        value = fn()
    except Exception as exc:
        err = str(exc)
        elapsed = time.perf_counter() - t0
        raise exc
    elapsed = time.perf_counter() - t0
    return value, ParallelTaskResult(name=name, seconds=elapsed, error=err)


def run_parallel_named(
    tasks: dict[str, Callable[[], T]],
    *,
    workers: int | None = None,
    group_name: str = "parallel",
) -> tuple[dict[str, T], ParallelLoadReport]:
    """Executa tarefas nomeadas em paralelo; propaga a primeira exceção."""
    n_workers = workers if workers is not None else funil_parallel_workers()
    report = ParallelLoadReport(
        enabled=True,
        workers=n_workers,
        mode=group_name,
    )
    t0 = time.perf_counter()
    results: dict[str, T] = {}

    if len(tasks) <= 1:
        for name, fn in tasks.items():
            value, task_res = _run_timed(name, fn)
            results[name] = value
            report.groups.append(task_res)
        report.total_seconds = time.perf_counter() - t0
        return results, report

    with ThreadPoolExecutor(max_workers=min(n_workers, len(tasks))) as pool:
        future_map = {
            pool.submit(_run_timed, name, fn): name for name, fn in tasks.items()
        }
        for future in as_completed(future_map):
            name = future_map[future]
            value, task_res = future.result()
            results[name] = value
            report.groups.append(task_res)

    report.groups.sort(key=lambda g: g.name)
    report.total_seconds = time.perf_counter() - t0
    return results, report


def load_one_page_funnel_frames_parallel(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool = False,
    workers: int | None = None,
) -> tuple[
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
    ParallelLoadReport,
    dict[str, Any],
]:
    """Carrega as 4 fontes do Atual em paralelo (uncached)."""
    excl = bool(excluir_testes_aplicacoes)

    def _legacy() -> tuple[pd.DataFrame, str, str | None]:
        return fetch_legacy_for_funil_uncached(
            data_ini, data_fim, excluir_testes_aplicacoes=excl
        )

    tasks: dict[str, Callable[[], Any]] = {
        "legacy": _legacy,
        "prevendas": lambda: _fetch_prevendas_uncached(data_ini, data_fim),
        "executivas": lambda: fetch_executivas_for_funil_uncached(data_ini, data_fim),
        "investimento": lambda: _fetch_investimento_uncached(data_ini, data_fim),
    }
    raw, report = run_parallel_named(
        tasks, workers=workers, group_name="atual_sources"
    )
    report.scope = "atual"

    leg_tuple = raw["legacy"]
    ex_tuple = raw["executivas"]
    meta = {
        "legacy": {
            "version": leg_tuple[1],
            "fallback_error": leg_tuple[2],
            "rows": len(leg_tuple[0]),
        },
        "executivas": {
            "version": ex_tuple[1],
            "fallback_error": ex_tuple[2],
            "rows": len(ex_tuple[0]),
            "cols": len(ex_tuple[0].columns) if not ex_tuple[0].empty else 0,
        },
        "prev_rows": len(raw["prevendas"]),
        "inv_rows": len(raw["investimento"]),
    }
    frames = (leg_tuple[0], raw["prevendas"], ex_tuple[0], raw["investimento"])
    return frames, report, meta


def load_benchmark_shared_frames_parallel(
    wide_ini: date,
    wide_fim: date,
    *,
    workers: int | None = None,
) -> tuple[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], ParallelLoadReport, dict]:
    """Prevendas + executivas + investimento no intervalo amplo — paralelo."""
    tasks: dict[str, Callable[[], Any]] = {
        "prevendas": lambda: _fetch_prevendas_uncached(wide_ini, wide_fim),
        "executivas": lambda: fetch_executivas_for_funil_uncached(wide_ini, wide_fim),
        "investimento": lambda: _fetch_investimento_uncached(wide_ini, wide_fim),
    }
    raw, report = run_parallel_named(
        tasks, workers=workers, group_name="benchmark_shared"
    )
    report.scope = "benchmark_shared"
    ex_tuple = raw["executivas"]
    meta = {
        "executivas": {
            "version": ex_tuple[1],
            "fallback_error": ex_tuple[2],
            "rows": len(ex_tuple[0]),
            "cols": len(ex_tuple[0].columns) if not ex_tuple[0].empty else 0,
        },
    }
    return (raw["prevendas"], ex_tuple[0], raw["investimento"]), report, meta


def fetch_legacy_windows_parallel(
    ranges: list[tuple[date, date, str]],
    *,
    excluir_testes_aplicacoes: bool,
    workers: int | None = None,
) -> tuple[list[tuple[date, date, pd.DataFrame, str, str | None]], ParallelLoadReport]:
    """Legacy diário por janela de benchmark — paralelo."""
    excl = bool(excluir_testes_aplicacoes)
    tasks: dict[str, Callable[[], Any]] = {}
    key_to_range: dict[str, tuple[date, date, str]] = {}

    for i, (ini, fim, label) in enumerate(ranges):
        key = f"legacy_{i}"
        key_to_range[key] = (ini, fim, label)
        tasks[key] = lambda ini=ini, fim=fim: fetch_legacy_for_funil_uncached(
            ini, fim, excluir_testes_aplicacoes=excl
        )

    raw, report = run_parallel_named(
        tasks, workers=workers, group_name="benchmark_legacy_windows"
    )
    report.scope = "benchmark_legacy"
    out: list[tuple[date, date, pd.DataFrame, str, str | None]] = []
    for key in sorted(raw.keys()):
        ini, fim, _ = key_to_range[key]
        df, ver, fb = raw[key]
        out.append((ini, fim, df, ver, fb))
    return out, report
