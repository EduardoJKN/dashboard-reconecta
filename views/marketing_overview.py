"""Visão Geral Marketing — KPIs executivos validados em pgAdmin.

Cards principais lêem `mkt_visao_geral_diario.sql` (regra oficial: investimento
total geral + leads por e-mail único/dia + zoho_deals Ganho/Fechado Ganho).
Tabela "Por canal" e detalhamento continuam usando `bi.vw_mkt_overview` /
`bi.mv_mkt_roas` / `bi.vw_mkt_leads_classificacao`."""
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_overview,
    get_mkt_visao_geral_diario,
    get_mkt_visao_geral_periodo,
    get_mkt_visao_geral_kpis_canal,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_VISIVEIS_OVERVIEW,
    filtro_canais_padrao,
    visao_geral_diario,
    visao_geral_kpis,
    visao_geral_kpis_canal,
)
from src.transforms import delta_pct
from src.ui.charts import donut, last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, int_br, pct

# ---------------------------------------------------------------------------
# Header + filtros (período + canal)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Visão Geral Marketing",
    subtitle="Investimento, leads e resultado oficial CRM/comercial",
    filters=["canal"],
)
col_map = {"canal": "canal"}

# ---------------------------------------------------------------------------
# Carga (período atual)
# ---------------------------------------------------------------------------
# Série diária oficial — usada na tendência.
df_vg_all = safe_run(
    lambda: get_mkt_visao_geral_diario(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_diario",
)
# KPIs do período — usados nos cards sem filtro de canal.
df_vg_period_all = safe_run(
    lambda: get_mkt_visao_geral_periodo(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_periodo",
)
# KPIs completos por canal — invest + leads + financeiro atribuído.
# Usado quando o usuário filtra canal específico: substitui k/kp e afeta
# Visão executiva, Geração de leads e Eficiência (mas não Tendência diária).
df_kpc_all = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_kpis_canal",
)
df_ov_all = safe_run(
    lambda: get_mkt_overview(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_overview",
)

# Seed do filtro com a lista canônica de canais — garante que LinkedIn,
# TikTok, YouTube e Pinterest aparecem como opções mesmo quando não têm
# dados no período. Filtros aplicados em seguida usam refilter() na fonte real.
ctx.apply_filters(filtro_canais_padrao(CANAIS_VISIVEIS_OVERVIEW), col_map)

if df_vg_all.empty and df_vg_period_all.empty and df_ov_all.empty:
    st.warning("Sem dados para o período selecionado.")
    st.stop()

df_ov = ctx.refilter(df_ov_all, col_map)

# ---------------------------------------------------------------------------
# Período anterior — base para deltas
# ---------------------------------------------------------------------------
dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_vg_prev_all = safe_run(
    lambda: get_mkt_visao_geral_diario(prev_ini, prev_fim),
    view_label="mkt_visao_geral_diario",
)
df_vg_prev_period_all = safe_run(
    lambda: get_mkt_visao_geral_periodo(prev_ini, prev_fim),
    view_label="mkt_visao_geral_periodo",
)
df_kpc_prev_all = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(prev_ini, prev_fim),
    view_label="mkt_visao_geral_kpis_canal",
)

# Filtro de canal: detecta quando o usuário escolhe canais específicos.
# Comparação contra a LISTA CANÔNICA (CANAIS_VISIVEIS_OVERVIEW), não contra
# o universo de canais com dados no período — caso contrário, selecionar
# um canal sem dados no mês (ex.: TikTok) cairia para "todos" em vez de
# zerar os cards. Regra:
#   - vazio                                → todos (filtro inativo)
#   - == set(CANAIS_VISIVEIS_OVERVIEW)     → todos (filtro inativo)
#   - qualquer outro caso                  → filtro ativo
# Quando o canal selecionado não tem linhas em df_kpc_all,
# visao_geral_kpis_canal retorna zeros (já tratado no transform).
canais_sel: list[str] = list(ctx.selections.get("canal") or [])
canais_canonicos = set(CANAIS_VISIVEIS_OVERVIEW)
filtro_canal_ativo = bool(canais_sel) and set(canais_sel) != canais_canonicos

# K = KPIs principais. Quando há filtro, troca pra parcela atribuída aos
# canais selecionados (afeta Visão executiva + Geração de leads + Eficiência).
# Senão, fica o total geral comercial (regra validada pgAdmin).
if filtro_canal_ativo:
    k = visao_geral_kpis_canal(df_kpc_all, canais_sel)
    kp = visao_geral_kpis_canal(df_kpc_prev_all, canais_sel)
else:
    k = visao_geral_kpis(df_vg_period_all)
    kp = visao_geral_kpis(df_vg_prev_period_all)

if filtro_canal_ativo:
    st.caption(
        "ℹ️ Quando há filtro de canal, os KPIs exibem a parcela atribuída "
        "aos canais selecionados. Vendas sem correspondência de lead entram "
        "como **Sem canal**. A **Tendência diária** continua mostrando o "
        "total geral comercial."
    )
else:
    st.caption(
        "ℹ️ Os KPIs do topo seguem o total geral comercial. Em Geração de "
        "leads, os cards deduplicam o e-mail no período para classificados "
        "(+12 / -12). A Tendência diária continua mostrando a classificação "
        "da própria linha do dia."
    )

# ---------------------------------------------------------------------------
# Bloco 1 — Visão executiva (resultado oficial CRM/comercial)
# ---------------------------------------------------------------------------
section_title(
    "Visão executiva",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')} · "
    "investimento total + zoho_deals (Ganho/Fechado Ganho)",
)

v1, v2, v3, v4, v5, v6 = st.columns(6, gap="small")
with v1:
    metric_card_v2(
        "Investimento total geral",
        brl(k["investimento_total_geral"], casas=2),
        delta_pct=delta_pct(k["investimento_total_geral"],
                            kp["investimento_total_geral"]),
        hint="Meta + Google + Pinterest",
        accent=True,
    )
with v2:
    # Período atual e anterior têm o MESMO nº de dias (prev_ini calculado
    # a partir de `dias`), então `dias` serve para os dois lados do delta.
    invest_dia = k["investimento_total_geral"] / dias if dias else 0
    invest_dia_prev = kp["investimento_total_geral"] / dias if dias else 0
    metric_card_v2(
        "Investimento / dia",
        brl(invest_dia, casas=2),
        delta_pct=delta_pct(invest_dia, invest_dia_prev),
        hint=f"invest total ÷ {dias} dia{'s' if dias != 1 else ''}",
    )
with v3:
    metric_card_v2(
        "Vendas novas",
        int_br(k["vendas_novas_total_geral"]),
        delta_pct=delta_pct(k["vendas_novas_total_geral"],
                            kp["vendas_novas_total_geral"]),
        hint="tipo_venda = 'Novo cliente'",
    )
with v4:
    metric_card_v2(
        "Montante total geral",
        brl(k["montante_total_geral"], casas=2),
        delta_pct=delta_pct(k["montante_total_geral"], kp["montante_total_geral"]),
        hint="SUM(amount) · zoho_deals",
    )
with v5:
    metric_card_v2(
        "Receita total geral",
        brl(k["receita_total_geral"], casas=2),
        delta_pct=delta_pct(k["receita_total_geral"], kp["receita_total_geral"]),
        hint="SUM(receita) · zoho_deals",
    )
with v6:
    if k["investimento_total_geral"] > 0:
        metric_card_v2(
            "ROAS total geral",
            f"{k['roas_total_geral']:.2f}x".replace(".", ","),
            delta_pct=delta_pct(k["roas_total_geral"],
                                kp["roas_total_geral"]),
            hint="montante total ÷ invest total",
            accent=True,
        )
    else:
        metric_card_v2("ROAS total geral", "—",
                       hint="sem investimento no período")

st.caption(
    "**Total geral comercial** = resultado oficial do CRM/vendas. Inclui "
    "vendas de fontes ainda não totalmente rastreáveis por anúncio "
    "(orgânico, social sellers, direct, link in bio)."
)

# ---------------------------------------------------------------------------
# Bloco 2 — Geração de leads (e-mails únicos por dia · classificação canônica)
# ---------------------------------------------------------------------------
hint_canal = (
    f"canal: {', '.join(canais_sel)}" if filtro_canal_ativo
    else "todos os canais"
)
section_title(
    "Geração de leads",
    f"cards: e-mail deduplicado no período por bucket (+12/-12 podem sobrepor) · tendência: classificação da linha do dia · {hint_canal}",
)

g1, g2, g3, g4, g5 = st.columns(5, gap="small")
with g1:
    metric_card_v2(
        "Leads totais",
        int_br(k["leads_totais"]),
        delta_pct=delta_pct(k["leads_totais"], kp["leads_totais"]),
        hint="ext_reconecta.leads · sem testes/internos",
    )
with g2:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
        hint="+12 ou -12 · e-mail único no período",
    )
with g3:
    metric_card_v2(
        "Leads +12",
        int_br(k["leads_mais_12"]),
        delta_pct=delta_pct(k["leads_mais_12"], kp["leads_mais_12"]),
        hint="e-mail com pelo menos uma linha 'Atua +12' no período",
    )
with g4:
    metric_card_v2(
        "Leads -12",
        int_br(k["leads_menos_12"]),
        delta_pct=delta_pct(k["leads_menos_12"], kp["leads_menos_12"]),
        hint="e-mail com pelo menos uma linha 'Atua -12' no período",
    )
with g5:
    metric_card_v2(
        "Leads Não atua",
        int_br(k["leads_nao_atua"]),
        delta_pct=delta_pct(k["leads_nao_atua"], kp["leads_nao_atua"]),
        hint="e-mail com pelo menos uma linha 'Não atua' no período",
    )

# ---------------------------------------------------------------------------
# Bloco 3 — Eficiência (CPL · CPL qualificado · Taxa qualificação)
# ---------------------------------------------------------------------------
section_title(
    "Eficiência",
    "CPL e taxa de qualificação calculados sobre o investimento total geral",
)

e1, e2, e3 = st.columns(3, gap="small")
with e1:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2),
        delta_pct=delta_pct(k["cpl"], kp["cpl"]),
        hint="invest total geral ÷ leads totais",
    )
with e2:
    metric_card_v2(
        "CPL qualificado",
        brl(k["cpl_qualificado"], casas=2),
        delta_pct=delta_pct(k["cpl_qualificado"], kp["cpl_qualificado"]),
        hint="invest total geral ÷ leads qualificados",
    )
with e3:
    metric_card_v2(
        "Taxa de qualificação",
        pct(k["taxa_qualificacao"], casas=2),
        delta_pct=delta_pct(k["taxa_qualificacao"], kp["taxa_qualificacao"]),
        hint="qualificados ÷ leads totais",
    )

# ---------------------------------------------------------------------------
# Tendência diária — Investimento × Leads totais × Leads qualificados
# ---------------------------------------------------------------------------
section_title("Tendência diária",
              "investimento × leads totais × leads qualificados × leads +12")

st.caption(
    "Na tendência diária, `Leads +12 / -12 / Não atua` usam a classificação "
    "da própria linha do dia com e-mail único por dia. Nos cards do período, "
    "os buckets `+12 / -12 / Não atua` são contados por e-mail único dentro "
    "de cada classificação e podem se sobrepor."
)

diario = visao_geral_diario(df_vg_all)
if diario.empty:
    st.info("Sem dados diários no período.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["investimento_total_geral"],
        name="Investimento total",
        marker=dict(color=PALETTE["gold"],
                    line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_totais"], name="Leads totais",
        line=dict(color=PALETTE["wine_light"], width=2.5),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["leads_totais"], int_br),
        textposition="top center",
        textfont=dict(color=PALETTE["wine_light"], size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_qualificados"],
        name="Leads qualificados",
        # Roxo vibrante (#7C3AED) — cor distinta do dourado (invest) e do
        # vinho (leads). Trocado de ciano/verde porque essas se misturavam
        # com o tema dark + tints amarelados.
        line=dict(color="#7C3AED", width=2.5, dash="dot"),
        mode="lines+markers+text", marker=dict(size=6, color="#7C3AED"),
        text=last_point_text(diario["leads_qualificados"], int_br),
        textposition="top center",
        textfont=dict(color="#7C3AED", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} qualif<extra></extra>",
    ))
    # Leads +12 — soma diária bate com o card oficial "Leads +12"
    # (regra `classificado = 'Atua +12'` na própria linha do dia).
    # Cor azul saturado (#1D4ED8) escolhida pra ficar distinta
    # das outras 3 (dourado/vinho/roxo).
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_mais_12"],
        name="Leads +12",
        line=dict(color="#1D4ED8", width=2.2, dash="dash"),
        mode="lines+markers+text", marker=dict(size=6, color="#1D4ED8"),
        text=last_point_text(diario["leads_mais_12"], int_br),
        textposition="bottom center",
        textfont=dict(color="#1D4ED8", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads +12<extra></extra>",
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
        yaxis2=dict(title="Leads", overlaying="y", side="right",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=PALETTE["wine_light"])),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"],
                     tickfont=dict(color=PALETTE["text_subtle"], size=11))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Por canal — fonte única `mkt_visao_geral_kpis_canal` (mesma dos KPIs do topo)
# ---------------------------------------------------------------------------
section_title("Por canal",
              "investimento + leads + financeiro atribuído por canal")

# Quando o filtro de canal estiver ativo, mostra só os selecionados; quando
# inativo, mostra todos os canais com dados (incluindo 'Sem canal' p/ deals
# não atribuídos). Canal selecionado SEM linha em df_kpc_all aparece zerado
# (não cai pra total geral), garantido pelo reindex abaixo.
if filtro_canal_ativo:
    df_canal = (
        df_kpc_all.set_index("canal")
                  .reindex(canais_sel, fill_value=0)
                  .reset_index()
    )
else:
    df_canal = df_kpc_all.copy()

col_donut, col_tab = st.columns([1, 2], gap="large")

with col_donut:
    # Donut distribui leads_totais — canais sem leads ficam fora.
    donut_data = (
        df_canal[df_canal["leads_totais"] > 0][["canal", "leads_totais"]].copy()
    )
    if donut_data.empty:
        st.caption("Sem leads no período/filtro.")
    else:
        st.plotly_chart(
            donut(donut_data, names="canal", values="leads_totais",
                  height=300, total_label="Leads"),
            use_container_width=True,
        )

with col_tab:
    if df_canal.empty:
        st.caption("Sem canais no período selecionado.")
    else:
        cols_show = [
            "canal", "investimento_total_geral",
            "leads_totais", "leads_qualificados",
            "leads_mais_12", "leads_menos_12", "leads_nao_atua",
            "vendas_total_geral", "vendas_novas_total_geral",
            "montante_total_geral", "receita_total_geral",
            "roas_total_geral", "cpl", "cpl_qualificado", "cpl_mais_12",
            "taxa_qualificacao", "taxa_qualificacao_mais_12",
            "ticket_medio",
        ]
        col_cfg = {
            "canal": "Canal",
            "investimento_total_geral": st.column_config.NumberColumn(
                "Investimento", format="R$ %.2f"),
            "leads_totais": st.column_config.NumberColumn(
                "Leads", format="%d"),
            "leads_qualificados": st.column_config.NumberColumn(
                "Qualificados", format="%d"),
            "leads_mais_12": st.column_config.NumberColumn(
                "+12", format="%d"),
            "leads_menos_12": st.column_config.NumberColumn(
                "-12", format="%d"),
            "leads_nao_atua": st.column_config.NumberColumn(
                "Não atua", format="%d"),
            "vendas_total_geral": st.column_config.NumberColumn(
                "Vendas", format="%d"),
            "vendas_novas_total_geral": st.column_config.NumberColumn(
                "Vendas novas", format="%d"),
            "montante_total_geral": st.column_config.NumberColumn(
                "Montante", format="R$ %.2f"),
            "receita_total_geral": st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"),
            "roas_total_geral": st.column_config.NumberColumn(
                "ROAS", format="%.2fx"),
            "cpl": st.column_config.NumberColumn(
                "CPL", format="R$ %.2f"),
            "cpl_qualificado": st.column_config.NumberColumn(
                "CPL qualificado", format="R$ %.2f"),
            "cpl_mais_12": st.column_config.NumberColumn(
                "CPL +12", format="R$ %.2f"),
            "taxa_qualificacao": st.column_config.NumberColumn(
                "Taxa qualificação", format="%.2f%%"),
            "taxa_qualificacao_mais_12": st.column_config.NumberColumn(
                "Tx Qualif +12", format="%.2f%%"),
            "ticket_medio": st.column_config.NumberColumn(
                "Ticket médio", format="R$ %.2f"),
        }
        st.dataframe(
            df_canal[cols_show].sort_values(
                "investimento_total_geral", ascending=False
            ),
            use_container_width=True, hide_index=True,
            column_config=col_cfg,
        )

# ---------------------------------------------------------------------------
# Detalhamento dia × canal (expander)
# ---------------------------------------------------------------------------
with st.expander("Detalhamento por dia × canal (tabela completa)"):
    st.dataframe(
        df_ov.sort_values(["data_ref", "canal"]),
        use_container_width=True, hide_index=True,
        column_config={
            "data_ref": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "canal": "Canal",
            "investimento": st.column_config.NumberColumn(
                "Invest.", format="R$ %.2f"),
            "impressoes": st.column_config.NumberColumn("Impressões", format="%d"),
            "cliques": st.column_config.NumberColumn("Cliques", format="%d"),
            "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
            "leads": st.column_config.NumberColumn("Leads", format="%d"),
            "leads_qualificados": st.column_config.NumberColumn(
                "Qualif.", format="%d"),
            "leads_qualif_mais_12": st.column_config.NumberColumn(
                "+12", format="%d"),
            "leads_qualif_menos_12": st.column_config.NumberColumn(
                "-12", format="%d"),
        },
    )
