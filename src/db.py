from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import settings

QUERIES_DIR = Path(__file__).parent / "queries"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        settings.dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )


def run_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def run_sql_file(filename: str, params: dict | None = None) -> pd.DataFrame:
    return run_sql((QUERIES_DIR / filename).read_text(encoding="utf-8"), params)
