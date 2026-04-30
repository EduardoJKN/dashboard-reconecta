"""ROAS / CAC — eficiência consolidada de mídia paga (página executiva).

Consome `bi.mv_mkt_roas` (materialized view — REFRESH manual via
`REFRESH MATERIALIZED VIEW bi.mv_mkt_roas;`). Cruza investimento, leads,
vendas atribuídas e receita por (data_ref, canal)."""
from datetime import timedelta

import streamlit as st

from src.marketing_queries import (
    get_mkt_leads_classif_canal,
    get_mkt_leads_classificacao,
    get_mkt_leads_funil_diario,
    get_mkt_roas,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_PADRAO,
    filtro_canais_padrao,
    roas_diario,
    roas_kpis,
    roas_por_canal,
)
from src.transforms import delta_pct
from src.ui.charts import bar_simple, dual_line
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, int_br, pct  # noqa: F401  (pct reservado p/ futuras métricas)

# ---------------------------------------------------------------------------
# Header + filtros (período + canal — 4 canais sempre visíveis)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="ROAS / CAC",
    subtitle="Eficiência consolidada · receita atribuída ÷ investimento",
    filters=["canal"],
)
col_map = {"canal": "canal"}

# Mantém Pinterest/Google sempre no filtro, mesmo zerados
ctx.apply_filters(filtro_canais_padrao(CANAIS_PADRAO), col_map)

# ---------------------------------------------------------------------------
# Carga (período atual + período anterior para deltas)
# ---------------------------------------------------------------------------
df_all = safe_run(
    lambda: get_mkt_roas(ctx.data_ini, ctx.data_fim),
    view_label="bi.mv_mkt_roas",
)
df = ctx.refilter(df_all, col_map) if not df_all.empty else df_all

# Fontes deduplicadas para leads/qualif (mesmo padrão da Visão Geral)
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

# Detecta filtro = todos canais (mesma regra da Visão Geral)
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
    lambda: get_mkt_roas(prev_ini, prev_fim),
    view_label="bi.mv_mkt_roas",
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

# KPIs: leads/qualif do dedup só quando filtro = todos canais
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

k = roas_kpis(df, df_lp_para_kpis, df_classif_para_kpis)
kp = roas_kpis(df_prev, df_lp_para_kpis_prev, df_classif_para_kpis_prev)

# ---------------------------------------------------------------------------
# Hero — eficiência (ROAS / CAC / Invest / Receita)
# ---------------------------------------------------------------------------
section_title(
    "Eficiência",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
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
            hint="sem vendas atribuídas no período",
        )
with c2:
    metric_card_v2(
        "CAC",
        brl(k["cac"], casas=2) if k["cac"] else "—",
        delta_pct=delta_pct(k["cac"], kp["cac"]),
        hint="invest ÷ vendas atribuídas",
    )
with c3:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="canais filtrados no período",
    )
with c4:
    metric_card_v2(
        "Receita atribuída",
        brl(k["valor_receita"], casas=2),
        delta_pct=delta_pct(k["valor_receita"], kp["valor_receita"]),
        hint=f"{int_br(k['vendas'])} vendas · "
             f"ticket {brl(k['ticket_medio'], casas=2) if k['ticket_medio'] else '—'}",
    )

# ---------------------------------------------------------------------------
# Funil de aquisição — leads + qualif + CPL
# ---------------------------------------------------------------------------
section_title("Funil de aquisição", "do investimento até a venda")

s1, s2, s3, s4 = st.columns(4, gap="small")
with s1:
    metric_card_v2(
        "Leads",
        int_br(k["leads"]),
        delta_pct=delta_pct(k["leads"], kp["leads"]),
        hint="únicos via lp_form.leads",
    )
with s2:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
        hint="Atua +12 ou -12",
    )
with s3:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2),
        delta_pct=delta_pct(k["cpl"], kp["cpl"]),
        hint="invest ÷ leads",
    )
with s4:
    metric_card_v2(
        "CPL qualificado",
        brl(k["cpl_qualificado"], casas=2),
        delta_pct=delta_pct(k["cpl_qualificado"], kp["cpl_qualificado"]),
        hint="invest ÷ leads qualificados",
    )

# ---------------------------------------------------------------------------
# Tendência diária — investimento × receita atribuída
# ---------------------------------------------------------------------------
section_title("Tendência diária", "investimento × receita atribuída")

diario = roas_diario(df)
if diario.empty:
    st.info("Sem dados no período para os canais selecionados.")
else:
    st.plotly_chart(
        dual_line(
            diario, x="data_ref",
            y_left="investimento", y_right="valor_receita",
            label_left="Investimento (R$)", label_right="Receita (R$)",
            height=340,
        ),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# ROAS e CAC por canal
# ---------------------------------------------------------------------------
by_canal = roas_por_canal(df, df_classif_canal)

col_roas, col_cac = st.columns(2, gap="large")

with col_roas:
    section_title("ROAS por canal", "maior = melhor · só canais com investimento")
    # ROAS só faz sentido onde houve investimento — canais zerados sairiam
    # como 0 e enganariam a leitura. A tabela abaixo mostra todos.
    by_canal_invest = by_canal[by_canal["investimento"] > 0]
    if by_canal_invest.empty:
        st.info("Nenhum canal com investimento no período.")
    else:
        st.plotly_chart(
            bar_simple(by_canal_invest, x="canal", y="roas", height=280),
            use_container_width=True,
        )

with col_cac:
    section_title("CAC por canal", "menor = melhor · só canais com vendas")
    # CAC = invest/vendas. Sem vendas, CAC=0 seria visualmente "ótimo" mas
    # é informativamente errado. Filtramos vendas > 0.
    by_canal_vendas = by_canal[by_canal["vendas"] > 0]
    if by_canal_vendas.empty:
        st.info("Nenhum canal com vendas atribuídas no período.")
    else:
        st.plotly_chart(
            bar_simple(by_canal_vendas, x="canal", y="cac", height=280, money=True),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Detalhamento por canal — todos os canais (preserva Pinterest/Google zerados)
# ---------------------------------------------------------------------------
section_title("Detalhamento por canal",
              "métricas consolidadas · todos os canais filtrados")
if by_canal.empty:
    st.info("Sem dados no período.")
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
            "vendas": st.column_config.NumberColumn("Vendas", format="%d"),
            "valor_receita": st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"),
            "roas": st.column_config.NumberColumn("ROAS", format="%.2fx"),
            "cac": st.column_config.NumberColumn("CAC", format="R$ %.2f"),
            "cpl": st.column_config.NumberColumn("CPL", format="R$ %.2f"),
            "cpl_qualificado": st.column_config.NumberColumn(
                "CPL Qualif.", format="R$ %.2f"),
        },
    )

# Nota de freshness — a MV precisa ser atualizada periodicamente
st.caption(
    "Dados consumidos de `bi.mv_mkt_roas` (materialized view). "
    "Atualize com `REFRESH MATERIALIZED VIEW bi.mv_mkt_roas;` se notar atraso."
)
