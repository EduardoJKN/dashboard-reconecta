"""Repositórios de marketing — leem das views `bi.vw_mkt_*` no Postgres.

Cada função:
- usa cache `@st.cache_data(ttl=600)` (5 min);
- recebe `data_ini`/`data_fim` como `date`;
- retorna DataFrame com `data_ref` já em `datetime64`."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from .db import run_sql_file

_TTL = 600


def _params(data_ini: date, data_fim: date) -> dict:
    return {"data_ini": data_ini, "data_fim": data_fim}


def _to_datetime(df: pd.DataFrame, col: str = "data_ref") -> pd.DataFrame:
    if not df.empty and col in df.columns:
        df[col] = pd.to_datetime(df[col])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Visão Geral Marketing…")
def get_mkt_overview(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_overview.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo ROAS Marketing…")
def get_mkt_roas(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_roas.sql", _params(data_ini, data_fim)))


# Registro das views BI de marketing — pode ser plugado na página de Inspeção
# se algum dia quisermos. Não é importado pelo `repositories.VIEW_REGISTRY`
# (mantido intocado).
MKT_VIEW_REGISTRY: dict[str, str] = {
    "Marketing — Visão Geral": "bi.vw_mkt_overview",
    "Marketing — Campanhas":   "bi.vw_mkt_campanhas",
    "Marketing — Criativos":   "bi.vw_mkt_criativos",
    "Marketing — Funil":       "bi.vw_mkt_funil",
    "Marketing — ROAS (MV)":   "bi.mv_mkt_roas",  # consumida pelo app
    "Marketing — ROAS (lógica)": "bi.vw_mkt_roas",  # fonte de origem da MV
    "Marketing — Social IG":   "bi.vw_mkt_social",
}
