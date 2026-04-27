"""Visão Geral Marketing — KPIs consolidados (paid + leads + ROAS).

Consome `bi.vw_mkt_overview` (P0) e `bi.vw_mkt_roas` (opcional). Se uma das
views ainda não existir, mostra aviso amigável e segue."""
from datetime import timedelta

import streamlit as st

from src.marketing_queries import get_mkt_overview, get_mkt_roas
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    overview_diario,
    overview_kpis,
    overview_por_canal,
)
from src.transforms import delta_pct
from src.ui.charts import dual_line
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, int_br, pct

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
# Carga
# ---------------------------------------------------------------------------
df_ov_all = safe_run(
    lambda: get_mkt_overview(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_overview",
)

df_roas_all = safe_run(
    lambda: get_mkt_roas(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_roas",
)

if df_ov_all.empty:
    # Renderiza filtros mesmo vazio para não quebrar o layout
    ctx.apply_filters(df_ov_all, col_map)
    st.warning("Sem dados para o período selecionado em `bi.vw_mkt_overview`.")
    st.stop()

df_ov = ctx.apply_filters(df_ov_all, col_map)
df_roas = ctx.refilter(df_roas_all, col_map) if not df_roas_all.empty else df_roas_all

# Período anterior, mesmo tamanho — base para deltas
dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_ov_prev_all = safe_run(
    lambda: get_mkt_overview(prev_ini, prev_fim),
    view_label="bi.vw_mkt_overview",
)
df_ov_prev = (
    ctx.refilter(df_ov_prev_all, col_map) if not df_ov_prev_all.empty
    else df_ov_prev_all
)

k = overview_kpis(df_ov, df_roas)
kp = overview_kpis(df_ov_prev, None)

# ---------------------------------------------------------------------------
# KPI cards — bloco financeiro
# ---------------------------------------------------------------------------
section_title(
    "Financeiro",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"]),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="Meta + Google + Pinterest",
        accent=True,
    )
with c2:
    metric_card_v2(
        "CPL",
        brl(k["cpl"]),
        delta_pct=delta_pct(k["cpl"], kp["cpl"]),
        hint="invest ÷ leads",
    )
with c3:
    metric_card_v2(
        "CPL qualificado",
        brl(k["cpl_qualificado"]),
        delta_pct=delta_pct(k["cpl_qualificado"], kp["cpl_qualificado"]),
        hint="invest ÷ leads (Atua +12 ou -12)",
    )
with c4:
    if k["roas"]:
        metric_card_v2(
            "ROAS",
            f"{k['roas']:.2f}x",
            hint=f"CAC: {brl(k['cac']) if k['cac'] else '—'}",
            accent=True,
        )
    else:
        metric_card_v2(
            "ROAS", "—",
            hint="vw_mkt_roas indisponível ou sem vendas atribuídas",
        )

# ---------------------------------------------------------------------------
# KPI cards — bloco operacional
# ---------------------------------------------------------------------------
section_title("Volume e qualidade", "leads, classificação e taxa de qualificação")

s1, s2, s3, s4 = st.columns(4, gap="small")
with s1:
    metric_card_v2(
        "Leads totais",
        int_br(k["leads"]),
        delta_pct=delta_pct(k["leads"], kp["leads"]),
        hint="únicos via lp_form.leads",
    )
with s2:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
        hint=f"+12: {int_br(k['leads_qualif_mais_12'])} · "
             f"-12: {int_br(k['leads_qualif_menos_12'])}",
    )
with s3:
    metric_card_v2(
        "Taxa de qualificação",
        pct(k["taxa_qualif"]),
        delta_pct=delta_pct(k["taxa_qualif"], kp["taxa_qualif"]),
        hint="qualif ÷ totais",
    )
with s4:
    metric_card_v2(
        "CTR",
        pct(k["ctr"], casas=2),
        delta_pct=delta_pct(k["ctr"], kp["ctr"]),
        hint=f"{int_br(k['cliques'])} cliques / {int_br(k['impressoes'])} impressões",
    )

# ---------------------------------------------------------------------------
# Quebra por canal + tendência diária
# ---------------------------------------------------------------------------
col_canal, col_tend = st.columns([1, 1.2], gap="large")

with col_canal:
    section_title("Por canal", "performance comparativa")
    by_canal = overview_por_canal(df_ov, df_roas)
    if by_canal.empty:
        st.caption("Sem canais no período selecionado.")
    else:
        cols_show = ["canal", "investimento", "leads", "leads_qualificados",
                     "cpl", "cpl_qualificado", "taxa_qualif", "ctr"]
        col_cfg = {
            "canal": "Canal",
            "investimento": st.column_config.NumberColumn(
                "Investimento", format="R$ %.0f"),
            "leads": st.column_config.NumberColumn("Leads", format="%d"),
            "leads_qualificados": st.column_config.NumberColumn(
                "Qualif.", format="%d"),
            "cpl": st.column_config.NumberColumn("CPL", format="R$ %.2f"),
            "cpl_qualificado": st.column_config.NumberColumn(
                "CPL Qualif.", format="R$ %.2f"),
            "taxa_qualif": st.column_config.NumberColumn(
                "Tx Qualif.", format="%.1f%%"),
            "ctr": st.column_config.NumberColumn("CTR", format="%.2f%%"),
        }
        # Quando há vendas atribuídas, expõe CAC/ROAS no breakdown
        if df_roas is not None and not df_roas.empty:
            cols_show += ["vendas", "cac", "roas"]
            col_cfg["vendas"] = st.column_config.NumberColumn("Vendas", format="%d")
            col_cfg["cac"] = st.column_config.NumberColumn("CAC", format="R$ %.0f")
            col_cfg["roas"] = st.column_config.NumberColumn("ROAS", format="%.2fx")

        st.dataframe(
            by_canal[cols_show],
            use_container_width=True, hide_index=True,
            column_config=col_cfg,
        )

with col_tend:
    section_title("Tendência diária", "investimento × leads")
    diario = overview_diario(df_ov)
    if diario.empty:
        st.caption("Sem dados diários no período.")
    else:
        st.plotly_chart(
            dual_line(
                diario, x="data_ref",
                y_left="investimento", y_right="leads",
                label_left="Investimento (R$)", label_right="Leads",
                height=340,
            ),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Detalhamento dia × canal
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
