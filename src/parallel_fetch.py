"""Fetch paralelo de queries cacheadas do Streamlit.

Uso típico nas views:

    from src.parallel_fetch import fetch_named

    results, errors = fetch_named({
        "exec": (get_executivas, (data_ini, data_fim)),
        "inv":  (get_investimento_diario, (data_ini, data_fim)),
    })
    df_exec = results["exec"]
    if errors.get("exec"):
        st.error(...)

Cada callable roda em thread própria com o ScriptRunContext do Streamlit
propagado — necessário para `@st.cache_data` funcionar fora da thread
principal.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except ImportError:  # pragma: no cover
    add_script_run_ctx = None  # type: ignore[assignment]
    get_script_run_ctx = None  # type: ignore[assignment]


def _attach_script_ctx() -> None:
    if not (add_script_run_ctx and get_script_run_ctx):
        return
    ctx = get_script_run_ctx()
    if ctx is not None:
        add_script_run_ctx(threading.current_thread(), ctx)


def _run_one(
    name: str,
    fn: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> tuple[str, Any, BaseException | None]:
    _attach_script_ctx()
    try:
        return name, fn(*args, **(kwargs or {})), None
    except BaseException as exc:  # noqa: BLE001 — propaga erro nomeado
        return name, None, exc


def fetch_named(
    tasks: dict[str, tuple[Callable[..., Any], tuple[Any, ...]]
               | tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]],
    *,
    max_workers: int | None = None,
) -> tuple[dict[str, Any], dict[str, BaseException]]:
    """Executa tasks nomeadas em paralelo.

    `tasks[name]` = `(fn, args)` ou `(fn, args, kwargs)`.
    Retorna `(results, errors)` — chaves ausentes em `errors` = sucesso.
    """
    if not tasks:
        return {}, {}

    n = max_workers or min(8, max(1, len(tasks)))
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}

    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = []
        for name, spec in tasks.items():
            fn = spec[0]
            args = spec[1] if len(spec) > 1 else ()
            kwargs = spec[2] if len(spec) > 2 else {}
            futs.append(pool.submit(_run_one, name, fn, args, kwargs))
        for fut in as_completed(futs):
            name, value, err = fut.result()
            if err is not None:
                errors[name] = err
                results[name] = None
            else:
                results[name] = value

    return results, errors
