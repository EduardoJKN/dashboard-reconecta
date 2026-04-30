"""Funil Marketing — pipeline completo do investimento à venda.

Consome `bi.vw_mkt_funil` (paid + odam.v_attribution_lead_to_deal). KPIs com
delta vs período anterior, funil visual com drop-off entre estágios, evolução
diária e tabela por canal preservando Pinterest/Google quando zerados."""
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_funil,
    get_mkt_leads_classif_canal,
    get_mkt_leads_classificacao,
    get_mkt_leads_funil_diario,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_PADRAO,
    filtro_canais_padrao,
    funil_diario,
    funil_estagios,
    funil_kpis,
    funil_por_canal,
)
from src.transforms import delta_pct
from src.ui.charts import funnel, last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, int_br, pct

# ---------------------------------------------------------------------------
# Header + filtros (período + canal — 4 canais sempre visíveis)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Funil Marketing",
    subtitle="Pipeline completo · do investimento à venda",
    filters=["canal"],
)
col_map = {"canal": "canal"}
ctx.apply_filters(filtro_canais_padrao(CANAIS_PADRAO), col_map)

# ---------------------------------------------------------------------------
# Carga (período atual + período anterior para deltas)
# ---------------------------------------------------------------------------
df_all = safe_run(
    lambda: get_mkt_funil(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_funil",
)
df = ctx.refilter(df_all, col_map) if not df_all.empty else df_all

# Fontes deduplicadas (mesmo padrão de Visão Geral / ROAS-CAC):
# - lp_form: total de leads validado (sem grão de canal)
# - classificação consolidada: +12 / -12 / ambíguos por janela
# - classif_canal: tabela "Por canal" com leads/qualif por canal (dedup)
df_lp_funil_all = safe_run(
    lambda: get_mkt_leads_funil_diario(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_funil_leads_diario",
)
df_classif_all = safe_run(
    lambda: get_mkt_leads_classificacao(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_leads_classificacao",
)
df_classif_canal_all = safe_run(
    lambda: get_mkt_leads_classif_canal(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_leads_classificacao (canal)",
)

# Detecta filtro = todos canais (mesma regra da Visão Geral / ROAS-CAC).
# Quando filtro é parcial, KPIs caem para fallback (lp_form e classif não
# têm grão de canal). A tabela "Por canal" usa classif_canal direto via
# refilter (essa fonte tem coluna `canal`).
canais_no_dado = (
    set(df_all["canal"].dropna().astype(str).unique()) if not df_all.empty else set()
)
canais_sel = set(ctx.selections.get("canal") or [])
filtro_todos_canais = (not canais_sel) or (canais_sel >= canais_no_dado)
usar_lp_form = (
    filtro_todos_canais
    and df_lp_funil_all is not None
    and not df_lp_funil_all.empty
)
usar_classif = (
    filtro_todos_canais
    and df_classif_all is not None
    and not df_classif_all.empty
)

dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_prev_all = safe_run(
    lambda: get_mkt_funil(prev_ini, prev_fim),
    view_label="bi.vw_mkt_funil",
)
df_prev = (
    ctx.refilter(df_prev_all, col_map) if not df_prev_all.empty else df_prev_all
)
df_lp_funil_prev_all = safe_run(
    lambda: get_mkt_leads_funil_diario(prev_ini, prev_fim),
    view_label="bi.vw_funil_leads_diario",
)
df_classif_prev_all = safe_run(
    lambda: get_mkt_leads_classificacao(prev_ini, prev_fim),
    view_label="bi.vw_mkt_leads_classificacao",
)

# Para a tabela "Por canal" — refilter pelo canal selecionado pelo usuário
df_classif_canal = (
    ctx.refilter(df_classif_canal_all, col_map)
    if not df_classif_canal_all.empty else df_classif_canal_all
)

# KPIs: dedup só quando filtro = todos canais
df_lp_para_kpis = df_lp_funil_all if usar_lp_form else None
df_classif_para_kpis = df_classif_all if usar_classif else None
df_lp_para_kpis_prev = (
    df_lp_funil_prev_all
    if (usar_lp_form
        and df_lp_funil_prev_all is not None
        and not df_lp_funil_prev_all.empty)
    else None
)
df_classif_para_kpis_prev = (
    df_classif_prev_all
    if (usar_classif
        and df_classif_prev_all is not None
        and not df_classif_prev_all.empty)
    else None
)

k = funil_kpis(df, df_lp_para_kpis, df_classif_para_kpis)
kp = funil_kpis(df_prev, df_lp_para_kpis_prev, df_classif_para_kpis_prev)

# ---------------------------------------------------------------------------
# Topo do funil — investimento, leads, qualificados, taxa qualif (4 cards)
# ---------------------------------------------------------------------------
section_title(
    "Topo do funil",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="canais filtrados no período",
        accent=True,
    )
with c2:
    metric_card_v2(
        "Leads",
        int_br(k["leads"]),
        delta_pct=delta_pct(k["leads"], kp["leads"]),
        hint="lp_form.leads · únicos",
    )
with c3:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
        hint=f"+12: {int_br(k['leads_qualif_mais_12'])} · "
             f"-12: {int_br(k['leads_qualif_menos_12'])}",
    )
with c4:
    metric_card_v2(
        "Tx qualificação",
        pct(k["tx_qualificacao"], casas=2),
        delta_pct=delta_pct(k["tx_qualificacao"], kp["tx_qualificacao"]),
        hint="qualif ÷ leads",
    )

# ---------------------------------------------------------------------------
# Meio do funil — deals, deals ganhos, taxas (4 cards)
# ---------------------------------------------------------------------------
section_title("Meio do funil", "lead → deal → venda")

m1, m2, m3, m4 = st.columns(4, gap="small")
with m1:
    metric_card_v2(
        "Deals",
        int_br(k["deals"]),
        delta_pct=delta_pct(k["deals"], kp["deals"]),
        hint="deals atribuídos no Zoho",
    )
with m2:
    metric_card_v2(
        "Deals ganhos",
        int_br(k["deals_ganhos"]),
        delta_pct=delta_pct(k["deals_ganhos"], kp["deals_ganhos"]),
        hint="stage = 'Ganho'",
    )
with m3:
    metric_card_v2(
        "Tx lead → deal",
        pct(k["tx_lead_deal"], casas=2),
        delta_pct=delta_pct(k["tx_lead_deal"], kp["tx_lead_deal"]),
        hint="deals ÷ leads",
    )
with m4:
    metric_card_v2(
        "Tx deal → venda",
        pct(k["tx_deal_venda"], casas=2),
        delta_pct=delta_pct(k["tx_deal_venda"], kp["tx_deal_venda"]),
        hint="vendas ÷ deals",
    )

# ---------------------------------------------------------------------------
# Fim do funil — vendas, receita, CPL (3 cards)
# ---------------------------------------------------------------------------
section_title("Fim do funil", "vendas e custo")

f1, f2, f3 = st.columns(3, gap="small")
with f1:
    metric_card_v2(
        "Vendas",
        int_br(k["vendas"]),
        delta_pct=delta_pct(k["vendas"], kp["vendas"]),
        hint="stage 'Ganho' com data_compra",
        accent=True,
    )
with f2:
    metric_card_v2(
        "Receita",
        brl(k["valor_receita"], casas=2),
        delta_pct=delta_pct(k["valor_receita"], kp["valor_receita"]),
        hint="receita atribuída via odam.v_attribution",
    )
with f3:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2),
        delta_pct=delta_pct(k["cpl"], kp["cpl"]),
        hint="invest ÷ leads",
    )

# ---------------------------------------------------------------------------
# Funil visual com drop-off entre estágios
# ---------------------------------------------------------------------------
section_title("Funil visual", "queda percentual entre estágios destaca gargalos")

labels, values = funil_estagios(k)
if all(v == 0 for v in values):
    st.info("Sem dados no período para os canais selecionados.")
else:
    st.plotly_chart(
        funnel(labels, values, height=400, show_dropoff=True),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Evolução diária — invest (barra) + leads/deals/vendas (linhas)
# ---------------------------------------------------------------------------
section_title("Evolução diária", "investimento × leads × deals × vendas")

diario = funil_diario(df)
if diario.empty:
    st.info("Sem dados diários no período.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["investimento"], name="Investimento",
        marker=dict(color=PALETTE["gold"],
                    line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads"], name="Leads",
        line=dict(color=PALETTE["wine_light"], width=2.5),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["leads"], int_br),
        textposition="top center",
        textfont=dict(color=PALETTE["wine_light"], size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["deals"], name="Deals",
        line=dict(color=PALETTE["blue"], width=2.2, dash="dash"),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["deals"], int_br),
        textposition="top center",
        textfont=dict(color=PALETTE["blue"], size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} deals<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["vendas"], name="Vendas",
        # Roxo vibrante (#7C3AED) — distingue Vendas de Leads (vinho) e
        # Deals (azul). O verde anterior se misturava com o azul.
        line=dict(color="#7C3AED", width=2.2, dash="dot"),
        mode="lines+markers+text", marker=dict(size=6, color="#7C3AED"),
        text=last_point_text(diario["vendas"], int_br),
        textposition="top center",
        textfont=dict(color="#7C3AED", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} vendas<extra></extra>",
    ))
    fig.update_layout(
        height=380,
        margin=dict(l=12, r=12, t=20, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PALETTE["card"],
        font=dict(color=PALETTE["text"], family="Inter, system-ui, sans-serif",
                  size=12),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=PALETTE["bg_soft"],
                        bordercolor=PALETTE["border_strong"],
                        font=dict(color=PALETTE["text"], family="Inter")),
        legend=dict(orientation="h", yanchor="bottom", y=-0.22,
                    xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(color=PALETTE["text_subtle"], size=11)),
        bargap=0.32,
        yaxis=dict(title="Investimento (R$)",
                   gridcolor=PALETTE["border"],
                   tickfont=dict(color=PALETTE["gold"]),
                   tickprefix="R$ ", separatethousands=True),
        yaxis2=dict(title="Quantidade", overlaying="y", side="right",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=PALETTE["wine_light"])),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"],
                     tickfont=dict(color=PALETTE["text_subtle"], size=11))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Tabela por canal — todos canais selecionados, mesmo zerados
# ---------------------------------------------------------------------------
section_title("Por canal", "métricas consolidadas · canais selecionados")

canais_visiveis = ctx.selections.get("canal") or list(CANAIS_PADRAO)
by_canal = funil_por_canal(
    df, canais_visiveis=canais_visiveis, df_classif_canal=df_classif_canal
)

if by_canal.empty:
    st.info("Sem dados por canal no período.")
else:
    st.dataframe(
        by_canal, use_container_width=True, hide_index=True,
        column_config={
            "canal": "Canal",
            "investimento": st.column_config.NumberColumn(
                "Invest.", format="R$ %.2f"),
            "leads": st.column_config.NumberColumn("Leads", format="%d"),
            "leads_qualificados": st.column_config.NumberColumn(
                "Qualif.", format="%d"),
            "deals": st.column_config.NumberColumn("Deals", format="%d"),
            "vendas": st.column_config.NumberColumn("Vendas", format="%d"),
            "valor_receita": st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"),
            "conversoes_pct": st.column_config.NumberColumn(
                "Conversões", format="%.2f%%"),
        },
    )
