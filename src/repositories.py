from datetime import date

import pandas as pd
import streamlit as st

from .db import run_sql_file

_TTL = 600


def _date_params(data_ini: date, data_fim: date) -> dict:
    """Passa objetos `date` nativos — SQLAlchemy/psycopg2 coerce sem cast."""
    return {"data_ini": data_ini, "data_fim": data_fim}


def _month_params(data_ini: date, data_fim: date) -> dict:
    """Para views agregadas mensalmente: trunca no primeiro dia do mês em Python."""
    return {
        "mes_ini": data_ini.replace(day=1),
        "mes_fim": data_fim.replace(day=1),
    }


@st.cache_data(ttl=_TTL, show_spinner="Lendo executivas…")
def get_executivas(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file("dashboard_executivas.sql", _date_params(data_ini, data_fim))
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo SDR × Closer…")
def get_sdr_closer(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file(
        "compatibilidade_sdr_closer.sql",
        _month_params(data_ini, data_fim),
    )
    if not df.empty:
        df["mes_ref"] = pd.to_datetime(df["mes_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo investimento…")
def get_investimento_diario(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file("investimento_diario.sql", _date_params(data_ini, data_fim))
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL)
def get_tipos_venda() -> pd.DataFrame:
    return run_sql_file("tipos_venda_time.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo funil de leads…")
def get_funil_leads_diario(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file("funil_leads_diario.sql", _date_params(data_ini, data_fim))
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
        if "leads_lp_unicos" in df.columns:
            df["leads_lp_unicos"] = pd.to_numeric(df["leads_lp_unicos"], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo média móvel de vendas…")
def get_media_movel_vendas() -> float:
    """Média móvel de vendas ganhas — sempre relativa a CURRENT_DATE.
    NÃO recebe filtro de período (replica fórmula do Looker)."""
    df = run_sql_file("media_movel_vendas.sql")
    if df.empty:
        return 0.0
    val = df.iloc[0]["media_movel"]
    return float(val) if val is not None else 0.0


VIEW_REGISTRY: dict[str, str] = {
    "Executivas (KPIs principais)": "bi.vw_dashboard_comercial_executivas_rw",
    "SDR × Closer": "bi.vw_compatibilidade_sdr_closer",
    "Investimento diário": "bi.vw_investimento_diario",
    "Negócios (pipeline bruto)": "bi.trat_negocios_rw",
    "Funil de leads (LP)": "bi.vw_funil_leads_diario",
    "Tipos de venda (time)": "bi.vw_tipos_venda_time",
}
