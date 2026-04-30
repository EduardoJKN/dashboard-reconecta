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


@st.cache_data(ttl=_TTL, show_spinner="Lendo Campanhas…")
def get_mkt_campanhas(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_campanhas.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Funil Marketing…")
def get_mkt_funil(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_funil.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Criativos…")
def get_mkt_criativos(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_criativos.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo resultados por campanha…")
def get_mkt_campanha_resultados(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Resultados atribuídos por campanha — agrega `odam.mart_ad_funnel_daily`
    para o grão `campaign_id` no período. Usado SÓ pela seção Comparar
    campanhas (V1.5). Cobertura primária: Meta. Campanhas sem linha aqui
    são tratadas como "sem atribuição" pelo merge no app."""
    return run_sql_file("mkt_campanha_resultados.sql", _params(data_ini, data_fim))


@st.cache_data(ttl=_TTL, show_spinner="Lendo cobertura da atribuição…")
def get_mkt_campanha_cobertura(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Cobertura da atribuição da mart (presença de campaign_id) no período.
    Retorna 1 linha com 9 colunas: total + com/sem campaign_id para leads,
    vendas, receita. Diagnóstico apenas — NÃO usar pra alimentar números
    da comparação por campanha."""
    return run_sql_file("mkt_campanha_cobertura.sql", _params(data_ini, data_fim))


@st.cache_data(ttl=_TTL, show_spinner="Lendo resultados por criativo…")
def get_mkt_criativos_resultados(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Resultados atribuídos por anúncio — agrega `odam.mart_ad_funnel_daily`
    por `ad_id` no período. Usado pela página Criativos (cards gerais,
    Top 12 enriched, ranking dinâmico). Mesma regra do mart de campanhas:
    invest/spend daqui NÃO é oficial — usar invest da `bi.vw_mkt_criativos`."""
    return run_sql_file(
        "mkt_criativos_resultados.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo cobertura por criativo…")
def get_mkt_criativos_cobertura(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Cobertura da atribuição da mart (presença de ad_id) no período.
    Retorna 1 linha com 9 colunas. Diagnóstico apenas."""
    return run_sql_file(
        "mkt_criativos_cobertura.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo Growth (mart diária)…")
def get_mkt_growth_daily(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Resultado atribuído POR DATA — agrega `odam.mart_ad_funnel_daily`
    para o grão `data_ref` (sem campaign_id/ad_id). Consumida apenas pela
    página Growth, para alimentar:
      - cards do período (totais de agendamentos/comparecimentos/vendas)
      - funil 7 etapas adaptado
      - scatter Leads × Agendamentos diários

    Cobertura primária Meta. Inclui linhas com ad_id NULL (foto consolidada
    do funil — atribuição por anúncio é diagnosticada na página Criativos)."""
    return _to_datetime(
        run_sql_file("mkt_growth_daily.sql", _params(data_ini, data_fim))
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo Leads (lp_form)…")
def get_mkt_leads_funil_diario(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Fonte validada para 'Leads totais' na Visão Geral Marketing — sem
    grão de canal (apenas data_ref). Usada quando o filtro está em 'todos
    canais'; senão a página cai para bi.vw_mkt_overview."""
    return _to_datetime(
        run_sql_file("mkt_leads_funil_diario.sql", _params(data_ini, data_fim))
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo classificação de leads…")
def get_mkt_leads_classificacao(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Classificação consolidada (+12, -12, ambíguos) com dedupe DENTRO DA
    JANELA do dashboard. Lê de `bi.vw_mkt_leads_classificacao` (base limpa
    sem dedupe lifetime); o dedupe por janela acontece na própria query do
    app via BOOL_OR. Sem grão de canal — Visão Geral Marketing só consome
    quando filtro está em 'todos canais'."""
    return _to_datetime(
        run_sql_file("mkt_leads_classificacao.sql", _params(data_ini, data_fim))
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo classificação por canal…")
def get_mkt_leads_classif_canal(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Classificação +12/-12/ambíguo deduplicada POR CANAL na janela.
    Mesma fonte que `get_mkt_leads_classificacao`, mas com grão `(canal)` —
    usado pela tabela 'Por canal' da Visão Geral Marketing para mostrar
    Qualif +12, CPL +12 e Tx Qualif +12 por canal com números validados."""
    return run_sql_file("mkt_leads_classif_canal.sql", _params(data_ini, data_fim))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Social…")
def get_mkt_social(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file("mkt_social.sql", _params(data_ini, data_fim))
    if not df.empty:
        if "data_ref" in df.columns:
            df["data_ref"] = pd.to_datetime(df["data_ref"])
        if "publicado_em" in df.columns:
            df["publicado_em"] = pd.to_datetime(df["publicado_em"])
    return df


# Registro das views BI de marketing — pode ser plugado na página de Inspeção
# se algum dia quisermos. Não é importado pelo `repositories.VIEW_REGISTRY`
# (mantido intocado).
MKT_VIEW_REGISTRY: dict[str, str] = {
    "Marketing — Visão Geral": "bi.vw_mkt_overview",
    "Marketing — Campanhas":   "bi.vw_mkt_campanhas",
    "Marketing — Criativos":   "bi.vw_mkt_criativos",
    "Marketing — Funil (MV)":     "bi.mv_mkt_funil",  # consumida pelo app
    "Marketing — Funil (lógica)": "bi.vw_mkt_funil",  # fonte de origem da MV
    "Marketing — ROAS (MV)":   "bi.mv_mkt_roas",  # consumida pelo app
    "Marketing — ROAS (lógica)": "bi.vw_mkt_roas",  # fonte de origem da MV
    "Marketing — Social IG":   "bi.vw_mkt_social",
}
