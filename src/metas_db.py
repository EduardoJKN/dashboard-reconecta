"""Conexão dedicada às metas do Funil da Reconecta (METAS_DATABASE_URL).

Separada do Postgres principal do dashboard (`src.db` / PG_*).
Usar somente para leitura/escrita em `bi.metas_funil_reconecta` e
`bi.vw_metas_funil_reconecta`.
"""
from __future__ import annotations

import os
from functools import lru_cache

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()


class MetasDatabaseNotConfiguredError(RuntimeError):
    """METAS_DATABASE_URL não está definida no ambiente ou nos secrets."""


def get_metas_database_url() -> str | None:
    """URL completa do banco de metas (env → secrets do Streamlit)."""
    url = os.getenv("METAS_DATABASE_URL", "").strip()
    if url:
        return url
    try:
        import streamlit as st

        val = st.secrets.get("METAS_DATABASE_URL")
        if val not in (None, ""):
            return str(val).strip()
    except Exception:
        pass
    return None


def is_metas_database_configured() -> bool:
    return bool(get_metas_database_url())


@lru_cache(maxsize=1)
def get_metas_engine() -> Engine:
    url = get_metas_database_url()
    if not url:
        raise MetasDatabaseNotConfiguredError(
            "METAS_DATABASE_URL não configurada. Defina no `.env` local ou em "
            "`.streamlit/secrets.toml` / Secrets do Streamlit Cloud."
        )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        future=True,
    )


def run_metas_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_metas_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def execute_metas_sql(sql: str, params: dict | None = None) -> None:
    with get_metas_engine().begin() as conn:
        conn.execute(text(sql), params or {})
