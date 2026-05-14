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
    # Migrado de bi.vw_compatibilidade_sdr_closer (defasada e com regra
    # divergente) para zoho_deals + zoho_users diretos. Janela = dia exato
    # do header (data_ini/data_fim) — alinhado com Visão Geral, em vez do
    # truncamento de mês antigo.
    #
    # Blindagem de bind parameters: enviamos AMBOS `data_ini/data_fim` e
    # `mes_ini/mes_fim` apontando pra mesma janela. SQLAlchemy ignora
    # parâmetros não referenciados pela SQL, então o payload aceita
    # qualquer versão da query (atual usa `:mes_ini/:mes_fim`; histórico
    # usava `:data_ini/:data_fim`). Resolve cenário de deploy parcial
    # onde Python e SQL ficam dessincronizados.
    params = _date_params(data_ini, data_fim)
    params.update({
        "mes_ini": data_ini,
        "mes_fim": data_fim,
    })
    df = run_sql_file("compatibilidade_sdr_closer.sql", params)
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


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads…")
def get_leads_visao_geral(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Leads únicos/dia para o card 'Leads Totais' da Visão Geral comercial.

    Substitui `get_funil_leads_diario` no card específico — esta fonte
    devolve 1 row por (data_ref, email_norm) com `executiva` e
    `time_vendas` resolvidos via lead → deal pareado (priority match
    `zoho_id > session_id > email`). Permite que `ctx.refilter` aplique
    os filtros de Closer / Times da página sobre o card. Leads sem deal
    pareado (~1%) ou com deal sem closer atribuído (~57%) ficam com
    NULL nessas colunas — entram só quando filtro = Todos.
    Validado abr/2026: total=854, Leidianne=156, Marcelo=180, Hawinne=63.
    """
    df = run_sql_file(
        "leads_visao_geral.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
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


# ---------------------------------------------------------------------------
# Pré-vendas — fontes diretas em zoho_activities + zoho_deals + leads.
# SDR primário: `zoho_activities.prevendas` (NULL → 'Sem SDR').
# Closer (matriz SDR × Closer): `zoho_activities.owner` resolvido via
# `zoho_users` (NULL → 'Sem Closer').
# ---------------------------------------------------------------------------
@st.cache_data(ttl=_TTL, show_spinner="Lendo Pré-vendas (diário)…")
def get_prevendas_overview_diario(data_ini: date, data_fim: date) -> pd.DataFrame:
    df = run_sql_file(
        "prevendas_overview_diario.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Pré-vendas (detalhe diário)…")
def get_prevendas_leads_detalhe_diario(data_ini: date,
                                       data_fim: date) -> pd.DataFrame:
    df = run_sql_file(
        "prevendas_leads_detalhe_diario.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty:
        for col in ("data_agendamento", "data_criacao", "data_venda"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo cadastro oficial de Pré-vendas…")
def get_prevendas_sdrs_oficiais() -> pd.DataFrame:
    return run_sql_file("prevendas_sdrs_oficiais.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo Pré-vendas (diário por SDR)…")
def get_prevendas_overview_diario_por_sdr(data_ini: date,
                                          data_fim: date) -> pd.DataFrame:
    df = run_sql_file(
        "prevendas_overview_diario_por_sdr.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Pré-vendas por SDR…")
def get_prevendas_por_sdr(data_ini: date, data_fim: date) -> pd.DataFrame:
    return run_sql_file(
        "prevendas_por_sdr.sql", _date_params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo oportunidades por SDR…")
def get_prevendas_oportunidades_sdr(data_ini: date,
                                    data_fim: date) -> pd.DataFrame:
    """Oportunidades (deals criados no período) × Agendamentos (activities
    no período), agrupado por (sdr, classif_bucket).

    1 row por (sdr, classif_bucket ∈ {+12, -12, Não atua, Sem classif}).
    O Python pivota para tabela com colunas por bucket + conversões.
    Detalhes em `src/queries/prevendas_oportunidades_sdr.sql`.
    """
    return run_sql_file(
        "prevendas_oportunidades_sdr.sql", _date_params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo matriz Pré-vendas SDR × Closer…")
def get_prevendas_sdr_closer(data_ini: date, data_fim: date) -> pd.DataFrame:
    return run_sql_file(
        "prevendas_sdr_closer.sql", _date_params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo classificação de comparecimentos…")
def get_prevendas_comparecimentos_classif(data_ini: date,
                                          data_fim: date) -> pd.DataFrame:
    return run_sql_file(
        "prevendas_comparecimentos_classif.sql",
        _date_params(data_ini, data_fim),
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo SLA (amostra)…")
def get_prevendas_sla(data_ini: date, data_fim: date) -> pd.DataFrame:
    """⚠ Cobertura PARCIAL: apenas ~39% dos leads têm `sla` preenchido em
    abr/2026. Não usar como ranking individual nem como SLA contratual."""
    return run_sql_file(
        "prevendas_sla.sql", _date_params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo notificações de vendas…")
def get_prevendas_notificacoes_vendas(data_ini: date,
                                      data_fim: date) -> pd.DataFrame:
    """Notificações de welcome/onboarding (Customer Success) com
    cruzamento opcional ao funil comercial.

    Fonte: `assistencial.controle_notificacao_vendas` + LEFT JOIN
    `zoho.crm_negocios` (priority `id_negocio > email`). Documentação
    completa em `src/queries/prevendas_notificacoes_vendas.sql`.
    """
    df = run_sql_file(
        "prevendas_notificacoes_vendas.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty:
        df["dt_criacao"] = pd.to_datetime(df["dt_criacao"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads repassados para SDRs…")
def get_notificacoes_leads_sdr(data_ini: date,
                               data_fim: date) -> pd.DataFrame:
    """Leads daily-distinct com tentativa de associação ao SDR responsável.

    Fonte: `ext_reconecta.leads` (mesma base de leads_visao_geral.sql)
    cruzado com `zoho_deals` + `zoho_activities` para resolver SDR via
    cascata `activity.prevendas > deal.sdr_ss > NULL`. Detalhes em
    `src/queries/notificacoes_leads_sdr.sql`.
    """
    df = run_sql_file(
        "notificacoes_leads_sdr.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"])
        df["data_ref"]   = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo jornada do lead até a venda…")
def get_jornada_lead_venda(data_ini: date,
                           data_fim: date) -> pd.DataFrame:
    """Deals ganhos no período com os 5 timestamps da jornada para o
    Python calcular Δt (média/mediana). Detalhes em
    `src/queries/jornada_lead_venda.sql`."""
    df = run_sql_file(
        "jornada_lead_venda.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty:
        for col in (
            "ts_lead", "ts_deal", "ts_agendamento_criado",
            "ts_reuniao_agendada", "ts_comparecimento", "ts_venda",
        ):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
    return df


VIEW_REGISTRY: dict[str, str] = {
    "Executivas (KPIs principais)": "bi.vw_dashboard_comercial_executivas_rw",
    "SDR × Closer": "bi.vw_compatibilidade_sdr_closer",
    "Investimento diário": "bi.vw_investimento_diario",
    "Negócios (pipeline bruto)": "bi.trat_negocios_rw",
    "Funil de leads (LP)": "bi.vw_funil_leads_diario",
    "Tipos de venda (time)": "bi.vw_tipos_venda_time",
}
