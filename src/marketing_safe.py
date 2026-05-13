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
        if log_sql_error or "mkt_top_criativos_por_nome" in view_label:
            print(f"[ERRO safe_run:{view_label}]", repr(e))
            print(traceback.format_exc())
        if looks_like_missing_relation(e):
            st.warning(
                f"Fonte/consulta `{view_label}` ainda indisponível no banco "
                f"(view ausente, schema ou permissão). Detalhes no terminal do "
                f"Streamlit. Ajuste a query/objeto e recarregue a página."
            )
            return pd.DataFrame()
        raise


def require_columns(df: pd.DataFrame, cols: tuple[str, ...],
                    ctx_label: str) -> bool:
    """Confere colunas; mostra aviso e retorna False se faltar alguma."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.info(f"`{ctx_label}` requer colunas ausentes: {', '.join(missing)}")
        return False
    return True
