from datetime import timedelta

import streamlit as st

from src.repositories import (
    get_executivas,
    get_funil_leads_diario,
    get_investimento_diario,
    get_media_movel_vendas,
)
from src.transforms import (
    delta_pct,
    executivas_ranking,
    leads_totais_lp,
    receita_por_mes,
    visao_geral_kpis,
)
from src.ui.charts import bar_ranked, receita_vs_meta_mensal
from src.ui.components import hero_revenue_card, metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, brl_short, int_br, pct

# ---------------------------------------------------------------------------
# Page header + filtros globais
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Visão Geral",
    subtitle="Performance comercial consolidada",
    filters=["closer", "times"],
    right_text="Painel Executivo",
)

col_map = {"closer": "executiva", "times": "time_vendas"}

# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
try:
    df_exec_all = get_executivas(ctx.data_ini, ctx.data_fim)
    df_inv_all = get_investimento_diario(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar Postgres: {e}")
    st.stop()

# Leads (LP) — fonte separada (vw_funil_leads_diario), opcional/tolerante
try:
    df_leads = get_funil_leads_diario(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.warning(f"Falha ao consultar leads (LP): {e}")
    df_leads = None

# Média móvel de vendas (sempre últimos 21 dias absolutos)
try:
    media_movel_val = get_media_movel_vendas()
except Exception as e:
    st.warning(f"Falha ao consultar média móvel de vendas: {e}")
    media_movel_val = None

df_exec = ctx.apply_filters(df_exec_all, col_map)

if df_exec.empty:
    st.warning("Nenhum registro para o filtro atual.")
    st.stop()

# Período anterior (mesmo tamanho) para os deltas
dias_periodo = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias_periodo - 1)
try:
    df_exec_prev = ctx.refilter(get_executivas(prev_ini, prev_fim), col_map)
    df_inv_prev = get_investimento_diario(prev_ini, prev_fim)
except Exception:
    df_exec_prev = df_exec.iloc[0:0]
    df_inv_prev = df_inv_all.iloc[0:0]

# Leads do período anterior (para delta)
try:
    df_leads_prev = get_funil_leads_diario(prev_ini, prev_fim) if df_leads is not None else None
except Exception:
    df_leads_prev = None

k = visao_geral_kpis(df_exec, df_inv_all)
kp = visao_geral_kpis(df_exec_prev, df_inv_prev)

# ---------------------------------------------------------------------------
# Bloco financeiro
# ---------------------------------------------------------------------------
section_title(
    "Financeiro",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

fc1, fc2, fc3 = st.columns([1.3, 1, 1], gap="small")
with fc1:
    hero_revenue_card(
        receita_fmt=brl(k["receita"]),
        meta_fmt=brl_short(k["meta"]),
        pct_atingimento=k["pct_atingimento"],
        status=k["meta_status"],
    )
with fc2:
    metric_card_v2(
        "Montante",
        brl(k["montante"]),
        delta_pct=delta_pct(k["montante"], kp["montante"]),
        hint=f"Recebimento: {pct(k['pct_recebimento'])}",
    )
with fc3:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"]),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="variação vs. período anterior",
    )

# ---------------------------------------------------------------------------
# Bloco operacional
# ---------------------------------------------------------------------------
section_title("Operacional", "volume, conversão e eficiência")

s1, s2, s3, s4 = st.columns(4, gap="small")
with s1:
    if df_leads is not None:
        leads_atual = leads_totais_lp(df_leads)
        leads_prev = leads_totais_lp(df_leads_prev) if df_leads_prev is not None else None
        metric_card_v2(
            "Leads Totais",
            int_br(leads_atual),
            delta_pct=delta_pct(leads_atual, leads_prev) if leads_prev is not None else None,
            hint="leads únicos LP · vw_funil_leads_diario",
        )
    else:
        metric_card_v2("Leads Totais", "—",
                       hint="vw_funil_leads_diario indisponível")
with s2:
    metric_card_v2(
        "Vendas Novas",
        int_br(k["novos"]),
        delta_pct=delta_pct(k["novos"], kp["novos"]),
        hint=f"Asc. {int_br(k['ascensoes'])} · Ren. {int_br(k['renovacoes'])} · "
             f"Ind. {int_br(k['indicacoes'])}",
    )
    if media_movel_val is not None:
        ritmo_fmt = f"{media_movel_val:.1f}".replace(".", ",")
        st.markdown(
            f'<div class="kpi-foot">Ritmo últimos 21 dias: <b>{ritmo_fmt}</b> vendas/dia</div>',
            unsafe_allow_html=True,
        )
with s3:
    metric_card_v2(
        "Ticket Médio",
        brl(k["ticket_medio"]),
        delta_pct=delta_pct(k["ticket_medio"], kp["ticket_medio"]),
        hint="montante ÷ vendas",
    )
with s4:
    metric_card_v2(
        "Conversão Global",
        pct(k["conversao_global"]),
        delta_pct=delta_pct(k["conversao_global"], kp["conversao_global"]),
        hint="vendas ÷ (vendas+perdidos+cancelados)",
    )

# ---------------------------------------------------------------------------
# Receita mensal + Ranking de closers (lado a lado, headers inline)
# ---------------------------------------------------------------------------
col_chart, col_rank = st.columns([7, 3], gap="large")

with col_chart:
    st.markdown(
        "<div class='sec-title' style='margin:14px 0 6px 0'>"
        "Receita mensal <span class='sub'>vs meta · variação mês a mês</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    mensal = receita_por_mes(df_exec)
    if mensal.empty:
        st.info("Sem dados mensais no período selecionado.")
    else:
        st.plotly_chart(
            receita_vs_meta_mensal(mensal, height=320),
            use_container_width=True,
        )

with col_rank:
    h_l, h_r = st.columns([1.4, 1], vertical_alignment="bottom")
    with h_l:
        st.markdown(
            "<div class='sec-title' style='margin:14px 0 6px 0'>"
            "Ranking de Closers <span class='sub'>top 10</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    with h_r:
        rank_metric = st.selectbox(
            "Ordenar por",
            ["Receita", "Ganhos", "Ticket Médio"],
            index=0,
            key="home_rank_metric",
            label_visibility="collapsed",
        )
    _RANK_COL = {"Receita": "receita", "Ganhos": "vendas", "Ticket Médio": "ticket_medio"}
    metric_col = _RANK_COL[rank_metric]
    is_money = rank_metric in ("Receita", "Ticket Médio")

    rank = executivas_ranking(df_exec)
    if rank.empty:
        st.caption("Sem dados para o ranking.")
    else:
        st.plotly_chart(
            bar_ranked(rank, "executiva", metric_col, top_n=10, money=is_money,
                       height=320),
            use_container_width=True,
        )
