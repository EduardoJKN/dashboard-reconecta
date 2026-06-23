from datetime import date
import json
import logging
import os

import pandas as pd
import streamlit as st

from .db import run_sql_file

logger = logging.getLogger("reconecta.repositories")
LEGACY_VERSION_V1 = "v1"
LEGACY_VERSION_V2 = "v2"
LEGACY_BENCHMARK_BATCH_VERSION = "benchmark_batch_v2"

LEGACY_DIARIO_COLUMNS: tuple[str, ...] = (
    "data_ref",
    "novos_leads",
    "novas_aplicacoes",
    "aplicacoes_mais_12",
    "aplicacoes_menos_12",
    "aplicacoes_nao_atua",
    "agendamentos",
    "emails_com_agendamento",
    "aplicacoes_com_agendamento",
    "aplicacoes_mais_12_com_agendamento",
    "aplicacoes_menos_12_com_agendamento",
    "aplicacoes_nao_atua_com_agendamento",
    "investimento",
    "novas_aplicacoes_periodo",
    "aplicacoes_mais_12_periodo",
    "aplicacoes_menos_12_periodo",
    "aplicacoes_nao_atua_periodo",
    "aplicacoes_com_agendamento_periodo",
    "aplicacoes_mais_12_com_agendamento_periodo",
    "aplicacoes_menos_12_com_agendamento_periodo",
    "aplicacoes_nao_atua_com_agendamento_periodo",
)
EXECUTIVAS_VERSION_V1 = "v1"
EXECUTIVAS_VERSION_V2 = "v2"

_TTL = 600
_TTL_AGENDA_RT = 60


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
    from src.transforms import executivas_aplicar_time_vendas_overrides

    df = run_sql_file("dashboard_executivas.sql", _date_params(data_ini, data_fim))
    if not df.empty:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
        df = executivas_aplicar_time_vendas_overrides(df)
    return df


@st.cache_data(ttl=_TTL, show_spinner=False)
def get_executivas_for_funil_v2(
    data_ini_iso: str,
    data_fim_iso: str,
) -> pd.DataFrame:
    """Executivas agregadas diárias — view BI v2, colunas mínimas para o Funil."""
    data_ini = date.fromisoformat(data_ini_iso)
    data_fim = date.fromisoformat(data_fim_iso)
    df = run_sql_file(
        "dashboard_executivas_funil_v2.sql",
        _date_params(data_ini, data_fim),
    )
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def funil_executivas_v2_enabled() -> bool:
    flag = os.environ.get("FUNIL_EXECUTIVAS_V2", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def get_executivas_for_funil(
    data_ini: date,
    data_fim: date,
) -> tuple[pd.DataFrame, str, str | None]:
    """Executivas para Funil — v2 com fallback v1. Retorna (df, version, fallback_error)."""
    if funil_executivas_v2_enabled():
        try:
            df = get_executivas_for_funil_v2(
                data_ini.isoformat(),
                data_fim.isoformat(),
            )
            return df, EXECUTIVAS_VERSION_V2, None
        except Exception as exc:
            logger.exception("Executivas v2 falhou — fallback v1")
            df = get_executivas(data_ini, data_fim)
            return df, EXECUTIVAS_VERSION_V1, str(exc)
    df = get_executivas(data_ini, data_fim)
    return df, EXECUTIVAS_VERSION_V1, None


@st.cache_data(ttl=_TTL, show_spinner="Lendo vendas oficiais (Campanhas)…")
def get_mkt_campanhas_vendas_oficiais(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Total CRM de vendas novas para Campanhas (__todos__).

    Leve substituto de int(SUM(vendas)) sobre dashboard_executivas.sql —
    cache separado de get_executivas."""
    return run_sql_file(
        "mkt_campanhas_vendas_oficiais.sql",
        _date_params(data_ini, data_fim),
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo Por Executiva…")
def get_one_page_por_executiva(data_ini: date,
                               data_fim: date,
                               modo: str = "ativas") -> pd.DataFrame:
    """Tabela Por Executiva da One Page — cálculo direto.

    Vai a `zoho_deals` + `zoho_activities` + `fdw_reconecta.executivas_vendas`
    em vez da view legada `bi.vw_dashboard_comercial_executivas_rw`. Resolve
    o nome via `id_crm`.

    Parâmetro `modo`:
      - 'ativas' (padrão): só executivas com `ativo='y'` no cadastro oficial;
        IDs sem cadastro são descartados.
      - 'todas': cadastro inteiro (ativas + inativas) + IDs sem cadastro
        rotulados como 'ID sem cadastro: <id>' — útil para auditoria.
    """
    if modo not in ("ativas", "todas"):
        modo = "ativas"
    params = _date_params(data_ini, data_fim)
    params["modo"] = modo
    return run_sql_file("one_page_por_executiva.sql", params)


@st.cache_data(ttl=_TTL, show_spinner="Lendo SDR × Closer da One Page…")
def get_one_page_sdr_closer(
    data_ini: date,
    data_fim: date,
    modo: str = "ativos",
) -> pd.DataFrame:
    """Tabela Por SDR × Closer da One Page — cálculo direto.

    Vai a `zoho_deals` + `zoho_activities` +
    `fdw_reconecta.executivas_pre_vendas` +
    `fdw_reconecta.executivas_vendas`, em vez da query/view legada.

    Parâmetro `modo`:
      - 'ativos': apenas SDRs no cadastro oficial e closers ativos;
      - 'todas': inclui histórico, inativos e IDs sem cadastro.
    """
    if modo not in ("ativos", "todas"):
        modo = "ativos"

    params = _date_params(data_ini, data_fim)
    params["modo"] = modo

    return run_sql_file("one_page_sdr_closer.sql", params)


@st.cache_data(ttl=_TTL, show_spinner="Lendo Novos (forma venda) da One Page…")
def get_one_page_novos_forma_venda(data_ini: date, data_fim: date) -> dict:
    """Sub-stats Em call / Follow do card Novos (One Page).

    Base: `zoho_deals` com `tipo_venda = 'Novo cliente'` e compra no período.
    O total `novos` retornado é referência de auditoria — o card principal
    continua vindo da view via `visao_geral_kpis`.
    """
    df = run_sql_file(
        "one_page_novos_forma_venda.sql", _date_params(data_ini, data_fim)
    )
    if df.empty:
        return {"novos": 0, "em_call": 0, "follow": 0}
    row = df.iloc[0]
    return {
        "novos": int(row["novos"] or 0),
        "em_call": int(row["em_call"] or 0),
        "follow": int(row["follow"] or 0),
    }


@st.cache_data(ttl=_TTL, show_spinner="Lendo indicações (fonte) da One Page…")
def get_one_page_indicacoes_fonte(data_ini: date, data_fim: date) -> int:
    """Card Indic. da One Page — vendas por `fonte_de_lead = 'Indicação'`.

    Substitui a coluna `indicacoes` da view legada (que usava `tipo_venda`)
    apenas neste card. Alinhado ao Looker: ganhos no período por
    `data_hora_compra`, com filtros canônicos de e-mail de teste.
    """
    df = run_sql_file(
        "one_page_indicacoes_fonte.sql", _date_params(data_ini, data_fim)
    )
    if df.empty:
        return 0
    val = df.iloc[0]["indicacoes"]
    return int(val) if val is not None else 0


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


@st.cache_data(ttl=_TTL, show_spinner="Lendo One Page (Pré-vendas por fonte)…")
def get_one_page_prevendas_por_fonte(data_ini: date,
                                     data_fim: date) -> pd.DataFrame:
    """Série diária por FONTE de Pré-vendas (regra `origem_final` Looker).

    1 row por (data_ref, fonte ∈ {'Inbound','Fábrica','Outbound'}).
    Substitui a quebra INBOUND/SS via `tipo_sdr` nos cards específicos
    da One Page (Consultas hoje IN/SS, Comparec IN/SS, Agend ±12 IN/SS).

    Não substitui o consolidado de Pré-vendas (esse continua via
    `get_prevendas_overview_diario` + `prevendas_overview_kpis`). A soma
    INBOUND + Fábrica + Outbound bate com o consolidado porque ambos
    descartam activities órfãs (`what_id` sem deal pareado).

    Colunas: data_ref, fonte, oportunidades, agendamentos_criados,
    agendamentos (líquido), agendamentos_vencidos, ±12 buckets,
    *_ate_hoje variants (só start_datetime <= CURRENT_DATE),
    perc_agendamentos_mais_12, comparecimentos, comparecimentos_ate_hoje,
    perc_comparecimento, perc_comparecimento_ate_hoje, vendas,
    montante, receita.

    Validado abr/2026: Fábrica 132 / Inbound 383 / Outbound 3 (= 518
    agend líquidos = consolidado prev_dia).
    """
    df = run_sql_file(
        "one_page_prevendas_por_fonte.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo One Page (regra legada)…")
def get_one_page_legacy_diario(
    data_ini: date,
    data_fim: date,
    excluir_testes_aplicacoes: bool = False,
) -> pd.DataFrame:
    """Série diária da One Page seguindo a regra LEGADA do Looker.

    Diferente de `get_mkt_visao_geral_diario` em duas dimensões:
      1. "Aplicações" vem de `fdw_reconecta.typeform_aplicacoes`
         (e-mail único no período, data SP, dados_completos), NÃO de
         `ext_reconecta.leads.classificado`.
      2. "Investimento" vem de `fdw_reconecta.anuncios` excluindo
         campanhas `REL_02*`, NÃO de `bi.vw_investimento_diario`.
         (Diferença típica de R$ 10–20 vs o total geral — corresponde
         ao Google Ads, que a fdw da Meta não cobre.)

    Colunas devolvidas (1 row por data_ref):
      data_ref · novos_leads · novas_aplicacoes ·
      aplicacoes_mais_12 · aplicacoes_menos_12 · aplicacoes_nao_atua ·
      agendamentos · emails_com_agendamento ·
      aplicacoes_com_agendamento · aplicacoes_*_com_agendamento (+12/-12/nao_atua) ·
      investimento

    Validado abr/2026 (base anterior): novos_leads=854, novas_aplicacoes=701,
    aplicacoes_+12=233, -12=392, nao_atua=77, agendamentos=510,
    investimento R$ 102.185,30.
    """
    params = _date_params(data_ini, data_fim)
    params["excluir_testes_aplicacoes"] = 1 if excluir_testes_aplicacoes else 0
    df = run_sql_file("one_page_legacy_diario.sql", params)
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


@st.cache_data(ttl=_TTL, show_spinner=False)
def get_one_page_legacy_diario_v2(
    data_ini_iso: str,
    data_fim_iso: str,
    excluir_testes_aplicacoes: bool,
) -> pd.DataFrame:
    """Série diária legada v2 — escopo reduzido em leads/deals para o período."""
    data_ini = date.fromisoformat(data_ini_iso)
    data_fim = date.fromisoformat(data_fim_iso)
    params = _date_params(data_ini, data_fim)
    params["excluir_testes_aplicacoes"] = 1 if excluir_testes_aplicacoes else 0
    df = run_sql_file("one_page_legacy_diario_v2.sql", params)
    if not df.empty and "data_ref" in df.columns:
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def funil_legacy_v2_enabled() -> bool:
    flag = os.environ.get("FUNIL_LEGACY_V2", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def get_one_page_legacy_diario_for_funil(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool = False,
) -> tuple[pd.DataFrame, str, str | None]:
    """Legacy para Funil — v2 com fallback v1. Retorna (df, version, fallback_error)."""
    if funil_legacy_v2_enabled():
        try:
            df = get_one_page_legacy_diario_v2(
                data_ini.isoformat(),
                data_fim.isoformat(),
                bool(excluir_testes_aplicacoes),
            )
            return df, LEGACY_VERSION_V2, None
        except Exception as exc:
            logger.exception("Legacy v2 falhou — fallback v1")
            df = get_one_page_legacy_diario(
                data_ini, data_fim,
                excluir_testes_aplicacoes=excluir_testes_aplicacoes,
            )
            return df, LEGACY_VERSION_V1, str(exc)
    df = get_one_page_legacy_diario(
        data_ini, data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    return df, LEGACY_VERSION_V1, None


def funil_legacy_benchmark_batch_v2_enabled() -> bool:
    """Experimental — opt-in via `FUNIL_LEGACY_BENCHMARK_BATCH_V2=1` (default OFF)."""
    flag = os.environ.get("FUNIL_LEGACY_BENCHMARK_BATCH_V2", "0").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def benchmark_periods_json(
    ranges: list[tuple[date, date, str]],
) -> str:
    """JSON para `one_page_legacy_diario_benchmark_batch_v2.sql`."""
    return json.dumps([
        {
            "period_key": str(i),
            "data_ini": ini.isoformat(),
            "data_fim": fim.isoformat(),
        }
        for i, (ini, fim, _label) in enumerate(ranges)
    ])


@st.cache_data(ttl=_TTL, show_spinner=False)
def get_one_page_legacy_diario_benchmark_batch_v2(
    periods_json: str,
    excluir_testes_aplicacoes: bool,
) -> pd.DataFrame:
    """Legacy diário batch — N janelas com dedupe por `period_key`."""
    params = {
        "periods_json": periods_json,
        "excluir_testes_aplicacoes": 1 if excluir_testes_aplicacoes else 0,
    }
    df = run_sql_file("one_page_legacy_diario_benchmark_batch_v2.sql", params)
    if df.empty:
        return pd.DataFrame(columns=list(LEGACY_DIARIO_COLUMNS))
    if "data_ref" in df.columns:
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


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads por funil de origem…")
def get_prevendas_leads_por_origem(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Leads do período (daily-distinct por email) quebrados por
    funil_origem. Soma bate com o card 'Leads totais' da Visão Geral
    Pré-vendas. Ver `prevendas_leads_por_origem.sql`."""
    return run_sql_file(
        "prevendas_leads_por_origem.sql", _date_params(data_ini, data_fim)
    )


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


def get_vendas_leads_detalhe_diario(data_ini: date,
                                    data_fim: date) -> pd.DataFrame:
    """Detalhe linha-a-linha pra Top Closers de Vendas.

    Reaproveita `prevendas_leads_detalhe_diario.sql` — mesma fonte/regra
    do detalhe de Pré-vendas, com `time_vendas` agora exposto (CASE
    espelha a view bi.vw_dashboard_comercial_executivas_rw). Delega pra
    `get_prevendas_leads_detalhe_diario` para compartilhar o cache
    `@st.cache_data` — uma única carga por período atende as duas
    páginas (Pré-vendas Visão Geral + Vendas Executivas/Visão Geral).
    """
    return get_prevendas_leads_detalhe_diario(data_ini, data_fim)


@st.cache_data(ttl=_TTL, show_spinner="Lendo cadastro oficial de Pré-vendas…")
def get_prevendas_sdrs_oficiais() -> pd.DataFrame:
    return run_sql_file("prevendas_sdrs_oficiais.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo lookup email → SDR (Lead In)…")
def get_lead_in_email_sdr_lookup(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Candidatos email → SDR (base ext_reconecta.leads + CRM)."""
    df = run_sql_file("lead_in_email_sdr_lookup.sql", _date_params(data_ini, data_fim))
    if not df.empty and "ts_vinculo" in df.columns:
        df["ts_vinculo"] = pd.to_datetime(df["ts_vinculo"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Lead In & Reuniões…")
def get_lead_in_reunioes_consultas(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Consultas (`activity_type = 'Consulta'`) no período por data da reunião."""
    return _load_lead_in_reunioes_consultas(data_ini, data_fim)


def _load_lead_in_reunioes_consultas(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _load_lead_in_reunioes_consultas_sql(
        "lead_in_reunioes_consultas.sql", data_ini, data_fim,
    )


def _load_lead_in_reunioes_consultas_sql(
    sql_file: str, data_ini: date, data_fim: date,
) -> pd.DataFrame:
    df = run_sql_file(sql_file, _date_params(data_ini, data_fim))
    if df.empty:
        return df
    for col in (
        "data_reuniao",
        "ts_reuniao",
        "data_criacao_agendamento",
        "start_datetime",
        "end_datetime",
    ):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Lead In & Reuniões…")
def get_lead_in_reunioes_consultas_v2(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Consultas v2 — mesma semântica da v1, SQL otimizado."""
    return _load_lead_in_reunioes_consultas_sql(
        "lead_in_reunioes_consultas_v2.sql", data_ini, data_fim,
    )


@st.cache_data(ttl=_TTL_AGENDA_RT, show_spinner=False)
def get_lead_in_reunioes_consultas_agenda(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Consultas para agenda em tempo real — TTL curto (60s)."""
    return _load_lead_in_reunioes_consultas(data_ini, data_fim)


@st.cache_data(ttl=_TTL_AGENDA_RT, show_spinner=False)
def get_lead_in_reunioes_consultas_agenda_v2(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Consultas v2 para agenda em tempo real — TTL curto (60s)."""
    return _load_lead_in_reunioes_consultas_sql(
        "lead_in_reunioes_consultas_v2.sql", data_ini, data_fim,
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo campos de pré (deals Churn)…")
def get_lead_in_churn_deal_pre() -> pd.DataFrame:
    """`prevendas_raw` + `deal_sdr_nome` por deal `stage = 'Churn'`."""
    return run_sql_file("lead_in_churn_deal_pre.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo cadastro oficial de Vendas…")
def get_executivas_oficiais() -> pd.DataFrame:
    """Time ativo de Vendas (`fdw_reconecta.executivas_vendas WHERE ativo='y'`).

    Fonte oficial usada para filtrar o ranking de closers das páginas Visão
    Geral e Executivas & Times. Detalhes em `executivas_oficiais.sql`."""
    return run_sql_file("executivas_oficiais.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo cadastro completo de Vendas…")
def get_executivas_oficiais_todas() -> pd.DataFrame:
    """Cadastro ativo + histórico (`executivas_oficiais_todas.sql`)."""
    return run_sql_file("executivas_oficiais_todas.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo cadastro oficial de Pós-venda…")
def get_executivas_pos_vendas_oficiais() -> pd.DataFrame:
    """Cadastro pós-venda (`assistencial.executivas_pos_vendas`, ativos + históricos)."""
    return run_sql_file("executivas_pos_vendas_oficiais.sql")


@st.cache_data(ttl=_TTL, show_spinner="Lendo agendamentos do funil…")
def get_executivas_funil_agendamentos(data_ini: date, data_fim: date) -> pd.DataFrame:
    """1 linha por activity — mesma regra de `agendamentos` na view executivas."""
    df = run_sql_file(
        "executivas_funil_agendamentos.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty:
        for col in ("data_reuniao", "data_criacao_activity", "deal_created_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Lead In & Agendamentos…")
def get_executivas_lead_in_triagem(data_ini: date, data_fim: date) -> pd.DataFrame:
    """1 linha por deal criado no período — triagem + stage + closer."""
    df = run_sql_file(
        "executivas_lead_in_triagem.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty and "data_criacao" in df.columns:
        df["data_criacao"] = pd.to_datetime(df["data_criacao"], errors="coerce")
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo churns (stage Churn)…")
def get_executivas_churn_pos_venda() -> pd.DataFrame:
    """1 linha por deal `stage = 'Churn'` — card/ranking Churn (não a aba pós-venda)."""
    df = run_sql_file("executivas_churn_pos_venda.sql")
    if not df.empty:
        for col in ("data_churn", "ultimo_contato_pos", "ts_churn"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo cancelamentos (Consulta cancelada)…")
def get_executivas_cancelamentos_pos_venda() -> pd.DataFrame:
    """1 linha por activity Consulta cancelada (com e-mail resolvido)."""
    df = run_sql_file("executivas_cancelamentos_pos_venda.sql")
    if not df.empty:
        for col in ("data_cancelamento", "ts_cancelamento"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo contatos de pós por e-mail…")
def get_executivas_pos_contatos_email() -> pd.DataFrame:
    """União de fontes de pós indexadas por email_norm."""
    df = run_sql_file("executivas_pos_contatos_email.sql")
    if not df.empty and "dt_contato" in df.columns:
        df["dt_contato"] = pd.to_datetime(df["dt_contato"], errors="coerce")
    return df


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
    # CP3-B: v2 otimizada (escopo de deals/leads no período). Legado:
    # `prevendas_por_sdr.sql` — regressão via scripts/benchmark_prevendas_por_sdr.py
    return run_sql_file(
        "prevendas_por_sdr_v2.sql", _date_params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo qualificação × comparecimento…")
def get_prevendas_qualif_comparecimento(data_ini: date,
                                      data_fim: date) -> pd.DataFrame:
    """Agendamentos classificáveis (Recepção / Reunião Agendada) com flag de
    comparecimento — 1 row por activity. Ver `prevendas_qualif_comparecimento.sql`."""
    df = run_sql_file(
        "prevendas_qualif_comparecimento.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty:
        if "data_reuniao" in df.columns:
            df["data_reuniao"] = pd.to_datetime(df["data_reuniao"])
        for col in ("start_datetime", "activity_created_time", "deal_created_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


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


@st.cache_data(ttl=_TTL, show_spinner="Lendo cohort de agendamentos…")
def get_prevendas_cohort_agendamentos(data_ini: date,
                                      data_fim: date) -> pd.DataFrame:
    """Cohort de agendamentos por dia de geração do deal.

    Grão: 1 row por deal criado no período (`data_geracao`, `sdr`,
    `data_agend`, `lag_dias`). O Python pivota e acumula D0..D7.
    Detalhes em `src/queries/prevendas_cohort_agendamentos.sql`.
    """
    df = run_sql_file(
        "prevendas_cohort_agendamentos.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty:
        df["data_geracao"] = pd.to_datetime(df["data_geracao"])
        if "data_agend" in df.columns:
            df["data_agend"] = pd.to_datetime(df["data_agend"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo cohort de agendamentos (leads)…")
def get_prevendas_cohort_leads(data_ini: date,
                               data_fim: date) -> pd.DataFrame:
    """Cohort de agendamentos por dia de geração do LEAD (daily-distinct
    por email). Grão: 1 row por (data_lead, email_norm) com `sdr` (via
    deal pareado) e `lag_dias` até o primeiro agendamento.
    Detalhes em `src/queries/prevendas_cohort_leads.sql`.
    """
    df = run_sql_file(
        "prevendas_cohort_leads.sql", _date_params(data_ini, data_fim)
    )
    if not df.empty:
        df["data_lead"] = pd.to_datetime(df["data_lead"])
        if "data_agend" in df.columns:
            df["data_agend"] = pd.to_datetime(df["data_agend"])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo matriz Pré-vendas SDR × Closer…")
def get_prevendas_sdr_closer(data_ini: date, data_fim: date) -> pd.DataFrame:
    return run_sql_file(
        "prevendas_sdr_closer.sql", _date_params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo classificação de comparecimentos…")
def get_prevendas_comparecimentos_classif(data_ini: date,
                                          data_fim: date) -> pd.DataFrame:
    # CP3-B: v2 otimizada (escopo de deals/leads no período). Legado:
    # `prevendas_comparecimentos_classif.sql` — regressão via
    # scripts/benchmark_prevendas_comparecimentos_classif.py
    return run_sql_file(
        "prevendas_comparecimentos_classif_v2.sql",
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
