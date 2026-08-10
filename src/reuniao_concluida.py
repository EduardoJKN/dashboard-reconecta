"""Regra oficial — Reunião Concluída / Comparecimento (Zoho → PG → Looker).

Fonte: `zoho_activities`. Unidade: activity (`COUNT(DISTINCT id)`).

Uma activity conta quando:
  - `start_datetime IS NOT NULL`
  - `activity_type IN ('Consulta', 'Indicação')`
  - `TRIM(LOWER(COALESCE(status_reuniao, '')))` ∈
      {'concluída', 'concluído', 'concluida', 'concluido'}
  - `start_datetime::date` no período filtrado
  - `start_datetime::date` ≤ hoje em America/Sao_Paulo

A data de referência é sempre `start_datetime` (nunca modified_time /
created_time / data do deal). Reuniões com start no futuro não entram,
mesmo com status inconsistente no Zoho.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

REUNIAO_CONCLUIDA_TZ = ZoneInfo("America/Sao_Paulo")

ACTIVITY_TYPES_REUNIAO = frozenset({"Consulta", "Indicação"})

STATUS_REUNIAO_CONCLUIDA = frozenset({
    "concluída",
    "concluído",
    "concluida",
    "concluido",
})

SQL_STATUS_REUNIAO_CONCLUIDA = (
    "TRIM(LOWER(COALESCE({alias}status_reuniao, ''))) IN ("
    "'concluída', 'concluído', 'concluida', 'concluido')"
)

SQL_HOJE_BRASIL = (
    "(CURRENT_TIMESTAMP AT TIME ZONE 'America/Sao_Paulo')::date"
)

REUNIAO_CONCLUIDA_HELP = (
    "Reunião concluída / comparecimento = activity Consulta/Indicação com "
    "status_reuniao concluída/concluído (com ou sem acento), data = "
    "start_datetime::date no período e ≤ hoje (America/Sao_Paulo). "
    "Contagem: DISTINCT activity_id. modified_time não é a data do "
    "comparecimento."
)


def hoje_brasil(agora: datetime | pd.Timestamp | None = None) -> date:
    """Data civil de referência em America/Sao_Paulo."""
    if agora is None:
        return datetime.now(REUNIAO_CONCLUIDA_TZ).date()
    ts = pd.Timestamp(agora)
    if ts.tzinfo is None:
        return ts.date()
    return ts.tz_convert(REUNIAO_CONCLUIDA_TZ).date()


def normalize_status_reuniao(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().lower()


def is_status_reuniao_concluida(value) -> bool:
    return normalize_status_reuniao(value) in STATUS_REUNIAO_CONCLUIDA


def sql_status_reuniao_concluida(alias: str = "") -> str:
    """Fragmento SQL do predicado de status (alias com ponto, se houver)."""
    prefix = alias if not alias or alias.endswith(".") else f"{alias}."
    return SQL_STATUS_REUNIAO_CONCLUIDA.format(alias=prefix)


def series_status_reuniao_concluida(series: pd.Series) -> pd.Series:
    return series.map(normalize_status_reuniao).isin(STATUS_REUNIAO_CONCLUIDA)


def _to_naive_brt_timestamp(series: pd.Series) -> pd.Series:
    st = pd.to_datetime(series, errors="coerce")
    if getattr(st.dt, "tz", None) is not None:
        st = st.dt.tz_convert(REUNIAO_CONCLUIDA_TZ).dt.tz_localize(None)
    return st


def series_start_date(series: pd.Series) -> pd.Series:
    """`start_datetime` → date (NaT → NaN)."""
    st = _to_naive_brt_timestamp(series)
    return st.dt.date


def mask_reuniao_concluida(
    df: pd.DataFrame,
    *,
    data_ini: date | None = None,
    data_fim: date | None = None,
    hoje: date | None = None,
    status_col: str = "status_reuniao",
    start_col: str = "start_datetime",
    activity_type_col: str | None = "activity_type",
    require_activity_type: bool = True,
) -> pd.Series:
    """Máscara booleana da regra oficial sobre um DataFrame de activities."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    hoje_ref = hoje if hoje is not None else hoje_brasil()
    status_ok = (
        series_status_reuniao_concluida(df[status_col])
        if status_col in df.columns
        else pd.Series(False, index=df.index)
    )

    if start_col not in df.columns:
        return pd.Series(False, index=df.index)

    start_d = series_start_date(df[start_col])
    has_start = start_d.notna()
    not_future = has_start & (start_d <= hoje_ref)

    in_period = pd.Series(True, index=df.index)
    if data_ini is not None:
        in_period &= has_start & (start_d >= data_ini)
    if data_fim is not None:
        in_period &= has_start & (start_d <= data_fim)

    type_ok = pd.Series(True, index=df.index)
    if require_activity_type and activity_type_col and activity_type_col in df.columns:
        type_ok = df[activity_type_col].isin(ACTIVITY_TYPES_REUNIAO)

    return status_ok & has_start & not_future & in_period & type_ok


def count_reunioes_concluidas(
    df: pd.DataFrame,
    *,
    data_ini: date | None = None,
    data_fim: date | None = None,
    hoje: date | None = None,
    activity_id_col: str = "activity_id",
    **mask_kwargs,
) -> int:
    """Conta DISTINCT activity_id sob a regra oficial."""
    if df is None or df.empty:
        return 0
    mask = mask_reuniao_concluida(
        df, data_ini=data_ini, data_fim=data_fim, hoje=hoje, **mask_kwargs,
    )
    sub = df.loc[mask]
    if sub.empty:
        return 0
    if activity_id_col in sub.columns:
        return int(sub[activity_id_col].nunique())
    if "id" in sub.columns:
        return int(sub["id"].nunique())
    return int(len(sub))
