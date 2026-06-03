"""Helpers defensivos para o dashboard de Marketing.

Quando uma view BI ainda não existe no banco (ou mudou de schema), a página
não deve quebrar — em vez disso mostramos um aviso amigável e seguimos com
DataFrame vazio. Isso permite publicar a infraestrutura gradualmente, view
por view, sem derrubar todo o app."""
from __future__ import annotations

import traceback
from typing import Callable

import pandas as pd
import streamlit as st
from sqlalchemy.exc import OperationalError, ProgrammingError

_MISSING_HINTS = (
    "does not exist",
    "no existe",
    "não existe",
    "undefined table",
    "undefinedtable",
    "permission denied",
    "permissão negada",
)


def looks_like_missing_relation(exc: BaseException) -> bool:
    msg = str(exc).lower()
    # Erros de query (alias/coluna/sintaxe) não são relação ausente no banco.
    if any(h in msg for h in (
        "missing from-clause",
        "undefined column",
        "column ",
        "syntax error",
        "parse error",
    )):
        return False
    return any(h in msg for h in _MISSING_HINTS)


def safe_run(
    fn: Callable[[], pd.DataFrame],
    *,
    view_label: str,
    log_sql_error: bool = False,
) -> pd.DataFrame:
    """Executa `fn()` (deve retornar DataFrame). Em caso de view ausente,
    mostra `st.warning` e devolve DataFrame vazio. Erros que NÃO sejam de
    relação ausente são re-lançados — bug de query não pode ser silenciado.

    Se `log_sql_error=True`, imprime exceção + traceback no terminal (útil
    para diagnosticar falhas em `run_sql_file`)."""
    try:
        return fn()
    except (ProgrammingError, OperationalError) as e:
        if looks_like_missing_relation(e):
            if log_sql_error:
                print(f"[ERRO safe_run:{view_label} — relação ausente]", repr(e))
            st.warning(
                f"Fonte/consulta `{view_label}` ainda indisponível no banco "
                f"(view ausente, schema ou permissão). Detalhes no terminal do "
                f"Streamlit. Ajuste a query/objeto e recarregue a página."
            )
            return pd.DataFrame()
        print(f"[ERRO safe_run:{view_label}]", repr(e))
        print(traceback.format_exc())
        raise


def require_columns(df: pd.DataFrame, cols: tuple[str, ...],
                    ctx_label: str) -> bool:
    """Confere colunas; mostra aviso e retorna False se faltar alguma."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.info(f"`{ctx_label}` requer colunas ausentes: {', '.join(missing)}")
        return False
    return True
