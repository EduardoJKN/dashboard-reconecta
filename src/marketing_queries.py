"""Repositórios de marketing — leem das views `bi.vw_mkt_*` no Postgres.

Cada função:
- usa cache `@st.cache_data(ttl=600)` (5 min);
- recebe `data_ini`/`data_fim` como `date`;
- retorna DataFrame com `data_ref` já em `datetime64`."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from sqlalchemy.exc import OperationalError, ProgrammingError

from .db import run_sql_file
from .marketing_safe import looks_like_missing_relation

_TTL = 600


def _params(data_ini: date, data_fim: date) -> dict:
    return {"data_ini": data_ini, "data_fim": data_fim}


_ONE_PAGE_FUNIL_COLS = (
    "agendamentos_globais",
    "agendamentos_leads_periodo_globais",
    "agendamentos_leads_historico_globais",
    "comparecimentos_globais",
    "comparecimentos_leads_periodo_globais",
    "comparecimentos_leads_historico_globais",
    "vendas_globais",
    "vendas_leads_periodo_globais",
    "vendas_leads_historico_globais",
)


def _merge_funil_one_page_globais(
    df: pd.DataFrame, data_ini: date, data_fim: date,
) -> pd.DataFrame:
    """Anexa colunas globais One Page (agend/comp/vendas + decomp) em cada row."""
    if df is None or df.empty:
        return df
    op = get_mkt_funil_one_page_globais(data_ini, data_fim)
    if not op:
        return df
    out = df.copy()
    for col in _ONE_PAGE_FUNIL_COLS:
        out[col] = op.get(col, 0)
    return out


def _merge_funil_one_page_agend(
    df: pd.DataFrame, data_ini: date, data_fim: date,
) -> pd.DataFrame:
    """Alias legado — delega para ``_merge_funil_one_page_globais``."""
    return _merge_funil_one_page_globais(df, data_ini, data_fim)


@st.cache_data(ttl=_TTL, show_spinner="Lendo totais One Page do funil…")
def get_mkt_funil_one_page_globais(
    data_ini: date, data_fim: date,
) -> dict:
    """1 row — agendamentos, comparecimentos, vendas + decomp período/histórico."""
    try:
        df = run_sql_file(
            "mkt_funil_agend_one_page_globais.sql", _params(data_ini, data_fim),
        )
    except (ProgrammingError, OperationalError):
        return {}
    if df is None or df.empty:
        return {}
    row = df.iloc[0]
    return {c: int(row[c]) if row[c] is not None else 0 for c in _ONE_PAGE_FUNIL_COLS}


def get_mkt_funil_agend_one_page_globais(
    data_ini: date, data_fim: date,
) -> dict:
    """Alias legado — retorna só colunas de agendamento."""
    op = get_mkt_funil_one_page_globais(data_ini, data_fim)
    return {k: op[k] for k in (
        "agendamentos_globais",
        "agendamentos_leads_periodo_globais",
        "agendamentos_leads_historico_globais",
    ) if k in op}


def _to_datetime(df: pd.DataFrame, col: str = "data_ref") -> pd.DataFrame:
    if not df.empty and col in df.columns:
        df[col] = pd.to_datetime(df[col])
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo Visão Geral Marketing…")
def get_mkt_overview(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_overview.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Visão Geral Marketing…")
def get_mkt_visao_geral_diario(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Visão Geral Marketing — fonte oficial validada (regra pgAdmin).

    Retorna 1 linha por `data_ref` com investimento total geral, leads
    por e-mail único/dia, classificação da própria linha do dia
    (+12 / -12 / Não atua) e financeiro direto de zoho_deals (stages Ganho / Fechado
    Ganho). Substitui mkt_overview_v2 nos cards principais.
    """
    return _to_datetime(
        run_sql_file("mkt_visao_geral_diario.sql", _params(data_ini, data_fim))
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo KPIs do período Marketing…")
def get_mkt_visao_geral_periodo(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Visão Geral Marketing — KPIs do período para os cards do topo.

    Usa deduplicação por e-mail no período DENTRO de cada bucket de
    classificação (`+12`, `-12`, `Não atua`). Os buckets podem se sobrepor:
    o mesmo e-mail pode contar em mais de uma classificação no período.
    Continua separado da série diária usada no gráfico de tendência.
    """
    return run_sql_file("mkt_visao_geral_periodo.sql", _params(data_ini, data_fim))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Visão Geral Marketing por canal…")
def get_mkt_visao_geral_canal(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Geração de leads POR CANAL — fonte: bi_mkt.vw_visao_geral_canal_base.

    Retorna 1 linha por canal com leads_totais, leads_qualificados,
    leads_mais_12, leads_menos_12 e leads_nao_atua. Usado para sobrescrever
    os cards de Geração de leads na Visão Geral Marketing quando o usuário
    seleciona canais específicos no filtro do header. Cards financeiros
    seguem a fonte total geral.
    """
    return run_sql_file("mkt_visao_geral_canal.sql", _params(data_ini, data_fim))


@st.cache_data(ttl=_TTL, show_spinner="Lendo KPIs por canal…")
def get_mkt_visao_geral_kpis_canal(data_ini: date, data_fim: date) -> pd.DataFrame:
    """KPIs completos POR CANAL — investimento + leads + financeiro atribuído.

    1 linha por canal (incluindo 'Sem canal' para deals sem lead match).
    Usado quando o usuário filtra canal específico — substitui os 3 blocos
    superiores da Visão Geral Marketing (Visão executiva, Geração de leads,
    Eficiência) pela parcela atribuída aos canais selecionados.

    Atribuição financeira: zoho_deals → ext_reconecta.leads (priority key
    zoho_id > session_id > email) → bi_mkt.vw_visao_geral_canal_base no
    (data_ref, email) do lead matched.
    """
    return run_sql_file(
        "mkt_visao_geral_kpis_canal.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo Visão Geral Marketing (V2)…")
def get_mkt_overview_v2(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Visão Geral Marketing V2 — fonte única `bi.vw_mkt_overview_daily_v2`.

    Retorna 1 linha por `data_ref` (grão diário, SEM canal) com 3 blocos:
      - mídia rastreável (investimento_midia, impressões, leads_*, ganhos_atribuidos…)
      - total geral comercial (investimento_total_geral, vendas_total_geral, montante_total_geral…)
      - ratios diários pré-calculados (roas_*, cpl_*) — recalcular sobre SUM no agregado do período."""
    return _to_datetime(
        run_sql_file("mkt_overview_v2.sql", _params(data_ini, data_fim))
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo ROAS Marketing…")
def get_mkt_roas(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_roas.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Campanhas…")
def get_mkt_campanhas(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_campanhas.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo Funil Marketing…")
def get_mkt_funil(data_ini: date, data_fim: date) -> pd.DataFrame:
    return _to_datetime(run_sql_file("mkt_funil.sql", _params(data_ini, data_fim)))


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads por página / variante…")
def get_mkt_paginas_variantes(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Comparar páginas / variantes — leads agregados por
    (page_pathname, lp_variante) com classificação canônica.

    Period-distinct: cada e-mail conta 1× por (path, variante) no período.
    Sem dado de visit/sessão — só geração de leads. Usado pelo MVP de
    "Comparar páginas / variantes" na página Growth.
    """
    return run_sql_file(
        "mkt_paginas_variantes.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads por campanha (UTM)…")
def get_mkt_campanhas_leads_por_utm(data_ini: date,
                                    data_fim: date) -> pd.DataFrame:
    """Leads por campanha — match `campaign_name` ↔ `utm_campaign`.

    1 linha por `utm_campaign` normalizado (LOWER+BTRIM) com
    leads_totais, leads_qualificados, leads_mais_12, leads_menos_12 —
    period-distinct (cada e-mail conta 1× por campanha no período).
    Classificação canônica via última row do e-mail (mesma regra
    Visão Geral). Usado pra enriquecer a tabela "Campanhas ativas".
    """
    return run_sql_file(
        "mkt_campanhas_leads_por_utm.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads por canal (Campanhas)…")
def get_mkt_campanhas_leads_canal_diario(data_ini: date,
                                         data_fim: date) -> pd.DataFrame:
    """Tendência diária de leads por canal — fonte oficial Visão Geral.

    1 linha por (data_ref, canal). Mesma semântica de
    `mkt_visao_geral_canal.sql` (regra last_row + canal_final), mas com
    grão diário pra alimentar o gráfico Tendência diária da página
    Campanhas. Cards de leads/CPL agregam essa fonte por canal.
    """
    return _to_datetime(
        run_sql_file("mkt_campanhas_leads_canal_diario.sql",
                     _params(data_ini, data_fim))
    )


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
    ordenações por mart, diagnósticos). O bloco Top 12 usa fonte própria
    (`mkt_top_criativos_por_nome.sql`). Mesma regra do mart de campanhas:
    invest/spend daqui NÃO é oficial — usar invest da `bi.vw_mkt_criativos`."""
    return run_sql_file(
        "mkt_criativos_resultados.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo Top criativos por nome…")
def get_mkt_top_criativos_por_nome(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Top Criativos — mídia em `fdw_reconecta.anuncios` + leads em
    `ext_reconecta.leads`, agregados por nome normalizado. Arquivo
    `mkt_top_criativos_por_nome.sql` (não é view materializada)."""
    return run_sql_file(
        "mkt_top_criativos_por_nome.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo fdw_reconecta.anuncios…")
def get_mkt_criativos_anuncios_fdw(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Linhas brutas de `fdw_reconecta.anuncios` no período (auditoria)."""
    df = run_sql_file(
        "mkt_criativos_anuncios_fdw.sql", _params(data_ini, data_fim)
    )
    if df.empty:
        return df
    df = df.copy()
    for c in ("date_start", "date_stop", "created_time", "updated_time"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@st.cache_data(ttl=_TTL, show_spinner="Lendo leads (audit UTM, ext)…")
def get_mkt_criativos_leads_utm_audit_ext(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Leads do período em `ext_reconecta.leads` (SELECT * + filtros de e-mail)."""
    df = run_sql_file(
        "mkt_criativos_leads_utm_audit_ext.sql", _params(data_ini, data_fim)
    )
    if df.empty:
        return df
    df = df.copy()
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df


def get_mkt_criativos_leads_utm_audit(data_ini: date, data_fim: date) -> tuple[pd.DataFrame, str]:
    """Leads para auditoria UTM: tenta `lp_form.leads`; fallback `ext_reconecta.leads`.

    Retorna `(df, fonte)` com rótulo da tabela efetiva."""
    try:
        df = run_sql_file(
            "mkt_criativos_leads_utm_audit_lp_form.sql",
            _params(data_ini, data_fim),
        )
    except (ProgrammingError, OperationalError) as e:
        if looks_like_missing_relation(e):
            df = get_mkt_criativos_leads_utm_audit_ext(data_ini, data_fim)
            return df, "ext_reconecta.leads"
        raise
    df = df.copy()
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df, "lp_form.leads"


@st.cache_data(ttl=_TTL, show_spinner="Lendo cobertura por criativo…")
def get_mkt_criativos_cobertura(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Cobertura da atribuição da mart (presença de ad_id) no período.
    Retorna 1 linha com 9 colunas. Diagnóstico apenas."""
    return run_sql_file(
        "mkt_criativos_cobertura.sql", _params(data_ini, data_fim)
    )


# Regra oficial dos funis de Marketing (Criativos + Campanhas):
# leads: ext_reconecta.leads → timestamp::date
# typeform: created_at::date
# Aplicações em "Todos os resultados": universo Typeform do período (igual One Page).
# Aplicações em criativo/campanha específica: ∩ e-mail com leads da seleção.


@st.cache_data(ttl=_TTL, show_spinner="Lendo funil por criativo…")
def get_mkt_criativo_funil(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Funil completo POR CRIATIVO (grão `ad_name` consolidado).

    1 linha por `ad_name_norm` no período, com mídia (invest/imp/cliques/
    link_clicks/alcance/CTR/CPC) + leads (totais/+12/-12/qualif) + funil
    (agendamentos/comparecimentos/vendas_novas) e derivadas (CPL/CPL+12/
    CAC/taxas).

    Match único viável: `lower(btrim(ad_name)) =
    lower(btrim(utm_content))` — `ad_id` está vazio em
    `ext_reconecta.leads`, `zoho_deals` e `zoho_activities`. Granularidade
    `ad_name` consolida múltiplos `ad_id` do mesmo criativo (CBO/A-B).
    Lead → deal por priority `zoho_id > session_id > email`; deal →
    activity via `what_id`. Mesma regra oficial Visão Geral / Growth.
    """
    df = run_sql_file(
        "mkt_criativo_funil.sql", _params(data_ini, data_fim),
    )
    return _merge_funil_one_page_agend(df, data_ini, data_fim)


@st.cache_data(ttl=_TTL, show_spinner="Lendo funil por campanha…")
def get_mkt_campanha_funil(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Funil completo POR CAMPANHA (grão `campaign_name` consolidado).

    Espelho de `get_mkt_criativo_funil` em outro grão: 1 linha por
    `campaign_name_norm` no período, com mídia (invest/imp/cliques/
    alcance/CTR/CPC) + leads (totais/+12/-12/qualif) + funil
    (agendamentos/comparecimentos/vendas_novas) e derivadas (CPL/CPL+12/
    CAC/taxas).

    Match: `lower(btrim(campaign_name)) = lower(btrim(utm_campaign))`.
    `campaign_id` não está populado nos leads — utm_campaign é o token
    confiável. Granularidade `campaign_name` consolida múltiplos
    `campaign_id` do mesmo nome (cópias, CBO). Lead → deal e deal →
    activity seguem a regra oficial (mesma da Visão Geral / Growth /
    funil de criativos).
    """
    df = run_sql_file(
        "mkt_campanha_funil.sql", _params(data_ini, data_fim),
    )
    return _merge_funil_one_page_agend(df, data_ini, data_fim)


@st.cache_data(ttl=_TTL, show_spinner="Lendo auditoria do funil…")
def get_mkt_funil_leads_auditoria(data_ini: date, data_fim: date,
                                  nivel: str, item_norm: str) -> pd.DataFrame:
    """Tabela de conferência nome-a-nome de leads/vendas do funil.

    Reaproveita 100% a lógica de atribuição de `mkt_criativo_funil.sql` /
    `mkt_campanha_funil.sql` (deal-centric, email > telefone, cross-período
    per-deal, desempate origem_util + lead mais recente).

    Params:
      - nivel: 'criativo' | 'campanha' (determina utm_content vs utm_campaign)
      - item_norm: valor de `ad_name_norm` ou `campaign_name_norm` do bucket
        selecionado. Aceita também os sintéticos:
            '__todos__' (todos os resultados)
            '__sem_criativo_identificado__'
            '__sem_campanha_identificada__'

    Schema: 18 colunas (Data venda · Nome deal · E-mail/Telefone deal ·
    Montante · Data lead · Dias lead-venda · Nome/E-mail/Telefone lead ·
    Classificação · Tipo de origem · UTM source · UTM medium · Campanha
    atribuída · Criativo atribuído · Tipo match · Regra atribuição)."""
    params = {
        **_params(data_ini, data_fim),
        "nivel": str(nivel),
        "item_norm": str(item_norm),
    }
    df = run_sql_file("mkt_funil_leads_auditoria.sql", params)
    if not df.empty:
        for col in ("data_venda", "data_lead"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
    return df


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


@st.cache_data(ttl=_TTL, show_spinner="Lendo Growth (atividades por canal)…")
def get_mkt_growth_atividades_canal(data_ini: date,
                                    data_fim: date) -> pd.DataFrame:
    """Funil Growth — leads únicos com Agendamento / Comparecimento por canal.

    Substitui as etapas Agendamentos/Comparecimentos do funil principal
    (que vinham de odam.mart_ad_funnel_daily, Meta-only) pela contagem
    de leads únicos via priority match `lead → deal → activity` em
    `zoho_activities`. Atividades filtradas por
    `activity_type IN ('Consulta','Indicação')` e janela
    `start_datetime::date`. Comparecimento exige `status_reuniao='Concluída'`.

    Validação abril/2026: leads_com_agendamento=279, leads_com_comparecimento=199.
    """
    return run_sql_file(
        "mkt_growth_atividades_canal.sql", _params(data_ini, data_fim)
    )


@st.cache_data(ttl=_TTL, show_spinner="Lendo Growth (mart por canal)…")
def get_mkt_growth_daily_by_canal(data_ini: date, data_fim: date) -> pd.DataFrame:
    """Mesma agregação de `get_mkt_growth_daily`, mas com canal derivado por
    LEFT JOIN com `bi.vw_mkt_campanhas` (campaign_id → canal). Linhas da
    mart com `campaign_id` NULL ficam com `canal=NaN` no DataFrame —
    a página Growth as inclui apenas quando o filtro está em 'todos canais'.

    Diferença vs `get_mkt_growth_daily`:
      - `get_mkt_growth_daily`        → 1 linha por data_ref (sem canal)
      - `get_mkt_growth_daily_by_canal`→ 1 linha por (data_ref × canal),
                                        canal pode ser NULL"""
    return _to_datetime(
        run_sql_file("mkt_growth_daily_by_canal.sql",
                     _params(data_ini, data_fim))
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
    "Marketing — Visão Geral V2": "bi.vw_mkt_overview_daily_v2",
    "Marketing — Visão Geral": "bi.vw_mkt_overview",
    "Marketing — Campanhas":   "bi.vw_mkt_campanhas",
    "Marketing — Criativos":   "bi.vw_mkt_criativos",
    "Marketing — Funil (MV)":     "bi.mv_mkt_funil",  # consumida pelo app
    "Marketing — Funil (lógica)": "bi.vw_mkt_funil",  # fonte de origem da MV
    "Marketing — ROAS (MV)":   "bi.mv_mkt_roas",  # consumida pelo app
    "Marketing — ROAS (lógica)": "bi.vw_mkt_roas",  # fonte de origem da MV
    "Marketing — Social IG":   "bi.vw_mkt_social",
}
