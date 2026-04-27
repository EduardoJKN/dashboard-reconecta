"""Configuração de conexão com Postgres.

Ordem de precedência ao ler cada credencial:
1. `st.secrets["postgres"][<chave>]` — usado em produção (Streamlit Cloud)
2. variável de ambiente PG_*  — usado localmente via .env

A URL final é montada via `sqlalchemy.engine.URL.create()` (NÃO via f-string),
que URL-encoda automaticamente caracteres especiais na senha (`@`, `/`, `:`,
`?`, `#`) e impede que o psycopg2 caia no fallback de socket Unix
(ex.: `/.s.PGSQL.<porta>`)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()


def _read(secrets_key: str, env_key: str, default: str = "") -> str:
    """Tenta ler de `st.secrets["postgres"][secrets_key]`; cai para `os.getenv(env_key)`.
    Se nenhum dos dois estiver definido, devolve `default`."""
    try:
        import streamlit as st
        if "postgres" in st.secrets and secrets_key in st.secrets["postgres"]:
            val = st.secrets["postgres"][secrets_key]
            if val not in (None, ""):
                return str(val)
    except Exception:
        pass
    return os.getenv(env_key, default)


def _read_strip(secrets_key: str, env_key: str, default: str = "") -> str:
    return _read(secrets_key, env_key, default).strip()


@dataclass(frozen=True)
class Settings:
    pg_host:     str = field(default_factory=lambda: _read_strip("host", "PG_HOST", "localhost"))
    pg_port:     int = field(default_factory=lambda: int(_read_strip("port", "PG_PORT", "5432")))
    pg_db:       str = field(default_factory=lambda: _read_strip("database", "PG_DB", "postgres"))
    pg_user:     str = field(default_factory=lambda: _read_strip("user", "PG_USER", "postgres"))
    pg_password: str = field(default_factory=lambda: _read("password", "PG_PASSWORD", ""))  # senha mantém espaços/chars
    pg_sslmode:  str = field(default_factory=lambda: _read_strip("sslmode", "PG_SSLMODE", "prefer"))

    @property
    def dsn(self) -> URL:
        """URL TCP bem formada para SQLAlchemy/psycopg2.

        - `URL.create()` URL-encoda a senha automaticamente (resolve casos com
          `@`, `/`, `:`, `?`, `#` na senha do Railway/Neon/Supabase).
        - Host e porta são passados como campos distintos, então o psycopg2
          não pode interpretar a string como path de socket Unix.
        - Equivale a: postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DB?sslmode=...
        """
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.pg_user,
            password=self.pg_password,
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_db,
            query={"sslmode": self.pg_sslmode},
        )


settings = Settings()
