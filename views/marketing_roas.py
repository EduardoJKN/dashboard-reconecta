"""ROAS / CAC — eficiência consolidada (regra oficial Visão Geral).

Fontes alinhadas com a Visão Geral Marketing e Growth:
    `mkt_visao_geral_kpis_canal.sql`        — invest + leads + financeiro
                                              (vendas, vendas_novas, montante,
                                              receita) por canal, atribuído via
                                              priority `zoho_id > session_id >
                                              email`. Inclui 'Sem canal' para
                                              deals não atribuídos.
    `mkt_campanhas_leads_canal_diario.sql`  — leads/qualif por (data_ref, canal)
                                              via regra last_row + canal_final.
    `mkt_visao_geral_diario.sql`            — série diária total geral
                                              (invest + montante + receita por
                                              data_ref) usada na Tendência
                                              diária — mesma política da
                                              Visão Geral.

ROAS = Montante total / Investimento. CAC = Investimento / Vendas novas
(`tipo_venda='Novo cliente'` — caminho de aquisição). Mesmas regras dos
demais painéis de marketing — métricas 'totais', não 'atribuídas via UTM'.
"""
from datetime import timedelta

import streamlit as st

from src.marketing_queries import (
    get_mkt_campanhas_leads_canal_diario,
    get_mkt_visao_geral_diario,
    get_mkt_visao_geral_kpis_canal,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_VISIVEIS_OVERVIEW,
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
# Header + filtros (período + canal — mesma lista canônica da Visão Geral)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="ROAS / CAC",
    subtitle="Eficiência consolidada · ROAS = montante total ÷ investimento",
    filters=["canal"],
)
col_map = {"canal": "canal"}

# Seed do filtro com a lista canônica de canais (mesma da Visão Geral) —
# garante visibilidade dos canais sem dados no período.
ctx.apply_filters(filtro_canais_padrao(CANAIS_VISIVEIS_OVERVIEW), col_map)

# ---------------------------------------------------------------------------
# Carga (período atual + período anterior para deltas)
# ---------------------------------------------------------------------------
df_kpc = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_kpis_canal",
)
df_leads_canal_diario = safe_run(
    lambda: get_mkt_campanhas_leads_canal_diario(ctx.data_ini, ctx.data_fim),
    view_label="mkt_campanhas_leads_canal_diario",
)
df_vg_diario = safe_run(
    lambda: get_mkt_visao_geral_diario(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_diario",
)

dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_kpc_prev = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(prev_ini, prev_fim),
    view_label="mkt_visao_geral_kpis_canal",
)
df_leads_canal_diario_prev = safe_run(
    lambda: get_mkt_campanhas_leads_canal_diario(prev_ini, prev_fim),
    view_label="mkt_campanhas_leads_canal_diario",
)

# ---------------------------------------------------------------------------
# Filtro de canal — mesma regra da Visão Geral:
#   vazio  ou  == lista canônica → todos os canais (filtro inativo)
#   qualquer subset            → filtro ativo, soma só os selecionados
# Quando inativo, soma TODAS as rows (inclusive 'Sem canal') — bate com o
# total geral oficial. Selecionar canal sem linha em df_kpc zera os cards
# (não cai pra total geral).
# ---------------------------------------------------------------------------
canais_sel: list[str] = list(ctx.selections.get("canal") or [])
canais_canonicos = set(CANAIS_VISIVEIS_OVERVIEW)
filtro_canal_ativo = bool(canais_sel) and set(canais_sel) != canais_canonicos
filtro_todos_canais = not filtro_canal_ativo

k = roas_kpis(df_kpc, df_leads_canal_diario,
              canais=canais_sel, todos_canais=filtro_todos_canais)
kp = roas_kpis(df_kpc_prev, df_leads_canal_diario_prev,
               canais=canais_sel, todos_canais=filtro_todos_canais)

# ---------------------------------------------------------------------------
# Hero — eficiência (ROAS / CAC / Invest / Montante / Receita)
# ---------------------------------------------------------------------------
section_title(
    "Eficiência",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4, c5 = st.columns(5, gap="small")
with c1:
    if k["roas"]:
        metric_card_v2(
            "ROAS",
            f"{k['roas']:.2f}x".replace(".", ","),
            delta_pct=delta_pct(k["roas"], kp["roas"]),
            hint="montante total ÷ investimento",
            accent=True,
        )
    else:
        metric_card_v2(
            "ROAS", "—",
            hint="sem montante no período",
        )
with c2:
    metric_card_v2(
        "CAC",
        brl(k["cac"], casas=2) if k["cac"] else "—",
        delta_pct=delta_pct(k["cac"], kp["cac"]),
        hint="invest ÷ vendas novas",
    )
with c3:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="canais filtrados · vw_mkt_overview (oficial)",
    )
with c4:
    metric_card_v2(
        "Montante total",
        brl(k["montante"], casas=2),
        delta_pct=delta_pct(k["montante"], kp["montante"]),
        hint=f"SUM(amount) zoho_deals · {int_br(k['vendas'])} vendas "
             f"({int_br(k['vendas_novas'])} novas)",
    )
with c5:
    metric_card_v2(
        "Receita total",
        brl(k["valor_receita"], casas=2),
        delta_pct=delta_pct(k["valor_receita"], kp["valor_receita"]),
        hint=f"SUM(receita) zoho_deals · ticket "
             f"{brl(k['ticket_medio'], casas=2) if k['ticket_medio'] else '—'}",
    )

if filtro_canal_ativo:
    st.caption(
        "ℹ️ Filtro de canal ativo — KPIs exibem a parcela atribuída aos "
        "canais selecionados. Vendas sem correspondência de lead entram "
        "como **Sem canal** e ficam fora quando o filtro é específico. "
        "A **Tendência diária** continua mostrando o total geral."
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
        hint="únicos · regra oficial Visão Geral",
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
# Tendência diária — investimento × receita total (sempre total geral,
# mesma política da Visão Geral; filtro de canal não altera a série)
# ---------------------------------------------------------------------------
section_title("Tendência diária", "investimento × receita total")

diario = roas_diario(df_vg_diario)
if diario.empty:
    st.info("Sem dados no período.")
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
by_canal = roas_por_canal(df_kpc, df_leads_canal_diario)

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
    section_title("CAC por canal", "menor = melhor · só canais com vendas novas")
    # CAC = invest / vendas novas. Sem vendas novas, CAC=0 seria visualmente
    # "ótimo" mas é informativamente errado. Filtramos vendas_novas > 0.
    by_canal_cac = by_canal[by_canal["vendas_novas"] > 0]
    if by_canal_cac.empty:
        st.info("Nenhum canal com vendas novas no período.")
    else:
        st.plotly_chart(
            bar_simple(by_canal_cac, x="canal", y="cac", height=280, money=True),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Detalhamento por canal — todos os canais (preserva Pinterest/Google zerados)
# ---------------------------------------------------------------------------
section_title("Detalhamento por canal",
              "métricas consolidadas · todos os canais com dados no período")
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
            "vendas_novas": st.column_config.NumberColumn(
                "Vendas novas", format="%d"),
            "valor_venda": st.column_config.NumberColumn(
                "Montante", format="R$ %.2f"),
            "valor_receita": st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"),
            "roas": st.column_config.NumberColumn("ROAS", format="%.2fx"),
            "cac": st.column_config.NumberColumn("CAC", format="R$ %.2f"),
            "cpl": st.column_config.NumberColumn("CPL", format="R$ %.2f"),
            "cpl_qualificado": st.column_config.NumberColumn(
                "CPL Qualif.", format="R$ %.2f"),
        },
    )

st.caption(
    "**Mesmas fontes da Visão Geral Marketing.** Investimento: "
    "`bi.vw_mkt_overview`. Leads e qualificados: regra oficial via "
    "`bi_mkt.vw_visao_geral_canal_base` (canal-aware, classificação canônica "
    "last_row do e-mail no período). Vendas / vendas novas / montante / "
    "receita: `zoho_deals` (stages Ganho/Fechado Ganho) com priority match "
    "`zoho_id > session_id > email` para atribuição por canal — deals sem "
    "lead correspondente entram como **Sem canal**. "
    "**ROAS = Montante total ÷ Investimento.** **CAC = Investimento ÷ "
    "Vendas novas** (`tipo_venda='Novo cliente'` — caminho de aquisição; "
    "ascensão / renovação / indicação ficam fora). Receita inclui todos os "
    "deals Ganho do período."
)
