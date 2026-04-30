"""Visão Geral Marketing — KPIs consolidados (paid + leads + ROAS).

Consome `bi.vw_mkt_overview` (P0) e `bi.mv_mkt_roas` (opcional, via materialized
view por performance — fonte lógica `bi.vw_mkt_roas`). Se uma das views ainda
não existir, mostra aviso amigável e segue."""
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_leads_classif_canal,
    get_mkt_leads_classificacao,
    get_mkt_leads_funil_diario,
    get_mkt_overview,
    get_mkt_roas,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_VISIVEIS_OVERVIEW,
    filtro_canais_padrao,
    overview_diario,
    overview_kpis,
    overview_por_canal,
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
    subtitle="Investimento, leads e ROAS consolidados",
    filters=["canal"],
)
col_map = {"canal": "canal"}

# ---------------------------------------------------------------------------
# Carga (período atual)
# ---------------------------------------------------------------------------
df_ov_all = safe_run(
    lambda: get_mkt_overview(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_overview",
)
df_roas_all = safe_run(
    lambda: get_mkt_roas(ctx.data_ini, ctx.data_fim),
    view_label="bi.mv_mkt_roas",
)
# Fonte canônica de Leads totais quando o filtro está em "todos canais".
# Não tem grão de canal — quando o filtro é parcial, caímos para vw_mkt_overview.
df_lp_funil_all = safe_run(
    lambda: get_mkt_leads_funil_diario(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_funil_leads_diario",
)
# Classificação consolidada (+12 / -12 / ambíguos) com dedupe correto.
# Sem grão de canal — só usada nos KPIs quando filtro = todos canais.
df_classif_all = safe_run(
    lambda: get_mkt_leads_classificacao(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_leads_classificacao",
)
# Mesma fonte mas COM grão de canal — usado pela tabela "Por canal" para
# substituir Qualif +12 / CPL +12 / Tx Qualif +12 pelos números validados.
df_classif_canal_all = safe_run(
    lambda: get_mkt_leads_classif_canal(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_leads_classificacao (canal)",
)

# Seed do filtro com a lista canônica de canais — garante que LinkedIn,
# TikTok, YouTube e Pinterest aparecem como opções mesmo quando não têm
# dados no período. Filtros aplicados em seguida usam refilter() na fonte real.
ctx.apply_filters(filtro_canais_padrao(CANAIS_VISIVEIS_OVERVIEW), col_map)

if df_ov_all.empty:
    st.warning("Sem dados para o período selecionado em `bi.vw_mkt_overview`.")
    st.stop()

df_ov = ctx.refilter(df_ov_all, col_map)
df_roas = (
    ctx.refilter(df_roas_all, col_map) if not df_roas_all.empty else df_roas_all
)
# df_classif_canal já tem coluna `canal` — refilter aplica o filtro do header
df_classif_canal = (
    ctx.refilter(df_classif_canal_all, col_map)
    if not df_classif_canal_all.empty else df_classif_canal_all
)

# Detecta se o filtro de canal está em "todos canais" — base para escolher
# entre lp_form (validado, sem canal) e vw_mkt_overview (canal-aware).
canais_no_dado = set(df_ov_all["canal"].dropna().astype(str).unique())
canais_sel = set(ctx.selections.get("canal") or [])
filtro_todos_canais = (not canais_sel) or (canais_sel >= canais_no_dado)
usar_lp_form = (
    filtro_todos_canais
    and df_lp_funil_all is not None
    and not df_lp_funil_all.empty
)

# ---------------------------------------------------------------------------
# Período anterior — base para deltas (inclusive ROAS)
# ---------------------------------------------------------------------------
dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_ov_prev_all = safe_run(
    lambda: get_mkt_overview(prev_ini, prev_fim),
    view_label="bi.vw_mkt_overview",
)
df_roas_prev_all = safe_run(
    lambda: get_mkt_roas(prev_ini, prev_fim),
    view_label="bi.mv_mkt_roas",
)
df_lp_funil_prev_all = safe_run(
    lambda: get_mkt_leads_funil_diario(prev_ini, prev_fim),
    view_label="bi.vw_funil_leads_diario",
)
df_classif_prev_all = safe_run(
    lambda: get_mkt_leads_classificacao(prev_ini, prev_fim),
    view_label="bi.vw_mkt_leads_classificacao",
)
df_ov_prev = (
    ctx.refilter(df_ov_prev_all, col_map) if not df_ov_prev_all.empty else df_ov_prev_all
)
df_roas_prev = (
    ctx.refilter(df_roas_prev_all, col_map) if not df_roas_prev_all.empty else df_roas_prev_all
)

# Mesma regra do período atual: só usa lp_form quando filtro = todos canais.
df_lp_para_kpis = df_lp_funil_all if usar_lp_form else None
df_lp_para_kpis_prev = (
    df_lp_funil_prev_all
    if (usar_lp_form
        and df_lp_funil_prev_all is not None
        and not df_lp_funil_prev_all.empty)
    else None
)

# Classificação dedupada — sem grão de canal, só faz sentido em "todos canais".
# A decisão de usar/não usar agora depende APENAS do filtro: passamos o
# DataFrame mesmo se ele vier vazio (a guarda interna em overview_kpis decide
# se aplica a sobrescrita). Isso facilita debugar quando a query devolve vazio.
usar_classif = filtro_todos_canais
df_classif_para_kpis = df_classif_all if filtro_todos_canais else None
df_classif_para_kpis_prev = df_classif_prev_all if filtro_todos_canais else None

k = overview_kpis(df_ov, df_roas, df_lp_para_kpis, df_classif_para_kpis)
kp = overview_kpis(df_ov_prev, df_roas_prev,
                   df_lp_para_kpis_prev, df_classif_para_kpis_prev)

# Hint do card "Leads totais" — indica qual fonte foi usada
leads_hint = (
    "lp_form · todos canais (validado)" if usar_lp_form
    else (
        "vw_mkt_overview · filtro de canal aplicado"
        if not filtro_todos_canais
        else "vw_mkt_overview · lp_form indisponível"
    )
)

# Hint do card "Leads qualificados" — mostra split +12/-12 e ambíguos quando
# a fonte com dedupe está disponível.
qualif_hint = (
    f"+12: {int_br(k['leads_qualif_mais_12'])} · "
    f"-12: {int_br(k['leads_qualif_menos_12'])}"
)
if usar_classif:
    qualif_hint += (
        f" · ambíguos: {int_br(k.get('leads_qualif_ambiguos', 0))} (excluídos)"
    )

# ---------------------------------------------------------------------------
# Linha 1 — Financeiro (3 cards: Investimento · Investimento/dia · ROAS)
# ---------------------------------------------------------------------------
section_title(
    "Financeiro",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3 = st.columns(3, gap="small")
with c1:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="Meta + Google + Pinterest",
        accent=True,
    )
with c2:
    metric_card_v2(
        "Investimento / dia",
        brl(k["investimento_dia"], casas=2),
        delta_pct=delta_pct(k["investimento_dia"], kp["investimento_dia"]),
        hint=f"{k['dias_com_invest']} dias com invest > 0",
    )
with c3:
    if k["roas"]:
        metric_card_v2(
            "ROAS",
            f"{k['roas']:.2f}x".replace(".", ","),
            delta_pct=delta_pct(k["roas"], kp["roas"]),
            hint=f"R$ {k['roas']:.2f} de receita / R$ 1 investido".replace(".", ","),
            accent=True,
        )
    else:
        metric_card_v2(
            "ROAS", "—",
            hint="vw_mkt_roas indisponível ou sem vendas atribuídas",
        )

# ---------------------------------------------------------------------------
# Linha 2 — Leads (4 cards: total · qualificados · +12 · -12)
# ---------------------------------------------------------------------------
section_title("Leads", "volume e qualificação")

l1, l2, l3, l4 = st.columns(4, gap="small")
with l1:
    metric_card_v2(
        "Leads totais",
        int_br(k["leads"]),
        delta_pct=delta_pct(k["leads"], kp["leads"]),
        hint=leads_hint,
    )
with l2:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
        hint=qualif_hint,
    )
with l3:
    metric_card_v2(
        "Leads +12",
        int_br(k["leads_qualif_mais_12"]),
        delta_pct=delta_pct(k["leads_qualif_mais_12"], kp["leads_qualif_mais_12"]),
        hint="classificado = 'Atua +12'",
    )
with l4:
    metric_card_v2(
        "Leads -12",
        int_br(k["leads_qualif_menos_12"]),
        delta_pct=delta_pct(k["leads_qualif_menos_12"], kp["leads_qualif_menos_12"]),
        hint="classificado = 'Atua -12'",
    )

# ---------------------------------------------------------------------------
# Linha 3 — Eficiência (3 cards: CPL · CPL qualificado · Taxa de qualificação)
# ---------------------------------------------------------------------------
section_title("Eficiência", "custo por aquisição e qualificação")

e1, e2, e3, e4 = st.columns(4, gap="small")
with e1:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2),
        delta_pct=delta_pct(k["cpl"], kp["cpl"]),
        hint="invest ÷ leads",
    )
with e2:
    metric_card_v2(
        "CPL qualificado",
        brl(k["cpl_qualificado"], casas=2),
        delta_pct=delta_pct(k["cpl_qualificado"], kp["cpl_qualificado"]),
        hint="invest ÷ leads (Atua +12 ou -12)",
    )
with e3:
    metric_card_v2(
        "CPL +12",
        brl(k["cpl_mais_12"], casas=2),
        delta_pct=delta_pct(k["cpl_mais_12"], kp["cpl_mais_12"]),
        hint="invest ÷ leads Atua +12",
    )
with e4:
    metric_card_v2(
        "Taxa de qualificação",
        pct(k["taxa_qualif"], casas=2),
        delta_pct=delta_pct(k["taxa_qualif"], kp["taxa_qualif"]),
        hint="qualif ÷ totais",
    )

# ---------------------------------------------------------------------------
# Tendência diária — Investimento × Leads × Leads qualificados
# ---------------------------------------------------------------------------
section_title("Tendência diária", "investimento × leads × leads qualificados")

diario = overview_diario(df_ov)
if diario.empty:
    st.info("Sem dados diários no período.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["investimento"], name="Investimento",
        marker=dict(color=PALETTE["gold"],
                    line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.2f}<extra></extra>",
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
# Tabela "Por canal" — formato 2 casas (en-US locale do Streamlit)
# ---------------------------------------------------------------------------
section_title("Por canal", "distribuição de leads e performance comparativa")

by_canal = overview_por_canal(df_ov, df_roas, df_classif_canal)

col_donut, col_tab = st.columns([1, 2], gap="large")

with col_donut:
    # Mesma fonte da tabela ao lado — só as linhas com leads > 0 entram no donut
    # (canais sem volume não fazem sentido como fatias do total).
    donut_data = by_canal[by_canal["leads"] > 0][["canal", "leads"]].copy()
    if donut_data.empty:
        st.caption("Sem leads no período.")
    else:
        st.plotly_chart(
            donut(donut_data, names="canal", values="leads",
                  height=300, total_label="Leads"),
            use_container_width=True,
        )

with col_tab:
    if by_canal.empty:
        st.caption("Sem canais no período selecionado.")
    else:
        # Foco da qualificação na tabela é em +12 (Qualif +12 / CPL +12 /
        # Tx Qualif +12). "Qualif." consolidado fica como referência. Os
        # consolidados antigos "CPL Qualif." e "Tx Qualif." saíram da view.
        cols_show = ["canal", "investimento", "leads",
                     "leads_qualificados", "cpl",
                     "leads_qualif_mais_12", "cpl_mais_12", "tx_qualif_mais_12"]
        col_cfg = {
            "canal": "Canal",
            "investimento": st.column_config.NumberColumn(
                "Investimento", format="R$ %.2f"),
            "leads": st.column_config.NumberColumn("Leads", format="%d"),
            "leads_qualificados": st.column_config.NumberColumn(
                "Qualif.", format="%d"),
            "cpl": st.column_config.NumberColumn("CPL", format="R$ %.2f"),
            "leads_qualif_mais_12": st.column_config.NumberColumn(
                "Qualif +12", format="%d"),
            "cpl_mais_12": st.column_config.NumberColumn(
                "CPL +12", format="R$ %.2f"),
            "tx_qualif_mais_12": st.column_config.NumberColumn(
                "Tx Qualif +12", format="%.2f%%"),
        }
        if df_roas is not None and not df_roas.empty:
            cols_show += ["vendas", "cac", "roas"]
            col_cfg["vendas"] = st.column_config.NumberColumn(
                "Vendas", format="%d")
            col_cfg["cac"] = st.column_config.NumberColumn(
                "CAC", format="R$ %.2f")
            col_cfg["roas"] = st.column_config.NumberColumn(
                "ROAS", format="%.2fx")

        st.dataframe(
            by_canal[cols_show],
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
