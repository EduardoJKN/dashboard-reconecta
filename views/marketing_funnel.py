"""Funil Marketing — pipeline completo do investimento à venda.

Migrada da `bi.mv_mkt_funil` (defasada, dependia de REFRESH manual) para as
fontes oficiais já validadas em Visão Geral / Growth / ROAS-CAC:

    mkt_visao_geral_kpis_canal.sql      — invest/leads/qualif/vendas/montante/
                                          receita por canal (priority match
                                          zoho_id > session_id > email; inclui
                                          'Sem canal' p/ deals não atribuídos).
    mkt_growth_atividades_canal.sql     — leads únicos com activity Consulta/
                                          Indicação por canal (otimizada UNION
                                          ALL — antes 46s, hoje ~3s).
    mkt_visao_geral_diario.sql          — série diária total geral (mesma
                                          política da Visão Geral / ROAS-CAC).

Vendas = Vendas novas (`tipo_venda='Novo cliente'`) — caminho de aquisição.
Vendas totais (todos `Ganho/Fechado Ganho`) ficam como métrica complementar.
"""
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_growth_atividades_canal,
    get_mkt_visao_geral_diario,
    get_mkt_visao_geral_kpis_canal,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_VISIVEIS_OVERVIEW,
    filtro_canais_padrao,
    funil_diario_oficial,
    funil_estagios_oficial,
    funil_kpis_oficial,
    funil_por_canal_oficial,
)
from src.transforms import delta_pct
from src.ui.charts import funnel, last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, int_br, pct

# ---------------------------------------------------------------------------
# Header + filtros (período + canal — lista canônica da Visão Geral)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Funil Marketing",
    subtitle="Pipeline completo · do investimento à venda",
    filters=["canal"],
)
col_map = {"canal": "canal"}
ctx.apply_filters(filtro_canais_padrao(CANAIS_VISIVEIS_OVERVIEW), col_map)

# ---------------------------------------------------------------------------
# Carga (período atual + período anterior para deltas)
# ---------------------------------------------------------------------------
df_kpc = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_kpis_canal",
)
df_atividades = safe_run(
    lambda: get_mkt_growth_atividades_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_growth_atividades_canal",
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
df_atividades_prev = safe_run(
    lambda: get_mkt_growth_atividades_canal(prev_ini, prev_fim),
    view_label="mkt_growth_atividades_canal",
)

# ---------------------------------------------------------------------------
# Filtro de canal — mesma regra da Visão Geral / ROAS-CAC:
#   vazio  ou  == lista canônica → todos os canais (filtro inativo)
#   qualquer subset            → filtro ativo, soma só os selecionados
# Quando inativo, soma TODAS as rows (inclusive 'Sem canal') — bate com o
# total geral oficial.
# ---------------------------------------------------------------------------
canais_sel: list[str] = list(ctx.selections.get("canal") or [])
canais_canonicos = set(CANAIS_VISIVEIS_OVERVIEW)
filtro_canal_ativo = bool(canais_sel) and set(canais_sel) != canais_canonicos
filtro_todos_canais = not filtro_canal_ativo

k = funil_kpis_oficial(df_kpc, df_atividades,
                       canais=canais_sel, todos_canais=filtro_todos_canais)
kp = funil_kpis_oficial(df_kpc_prev, df_atividades_prev,
                        canais=canais_sel, todos_canais=filtro_todos_canais)

# ---------------------------------------------------------------------------
# Topo do funil — Investimento, Leads, Qualif, Tx qualificação (4 cards)
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
        hint="canais filtrados · vw_mkt_overview (oficial)",
        accent=True,
    )
with c2:
    metric_card_v2(
        "Leads",
        int_br(k["leads"]),
        delta_pct=delta_pct(k["leads"], kp["leads"]),
        hint="únicos · regra oficial Visão Geral",
    )
with c3:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
        hint=f"+12: {int_br(k['leads_mais_12'])} · "
             f"-12: {int_br(k['leads_menos_12'])}",
    )
with c4:
    metric_card_v2(
        "Tx qualificação",
        pct(k["tx_qualificacao"], casas=2),
        delta_pct=delta_pct(k["tx_qualificacao"], kp["tx_qualificacao"]),
        hint="qualif ÷ leads",
    )

# ---------------------------------------------------------------------------
# Meio do funil — Agendamentos, Comparecimentos, Vendas, Vendas novas (4 cards)
# ---------------------------------------------------------------------------
section_title("Meio do funil", "lead → reunião → venda")

m1, m2, m3, m4 = st.columns(4, gap="small")
with m1:
    metric_card_v2(
        "Agendamentos",
        int_br(k["agendamentos"]),
        delta_pct=delta_pct(k["agendamentos"], kp["agendamentos"]),
        hint=f"taxa {pct(k['tx_lead_agend'], casas=1)} · zoho_activities",
    )
with m2:
    metric_card_v2(
        "Comparecimentos",
        int_br(k["comparecimentos"]),
        delta_pct=delta_pct(k["comparecimentos"], kp["comparecimentos"]),
        hint=f"taxa {pct(k['tx_agend_compar'], casas=1)} · status='Concluída'",
    )
with m3:
    metric_card_v2(
        "Vendas (totais)",
        int_br(k["vendas"]),
        delta_pct=delta_pct(k["vendas"], kp["vendas"]),
        hint="stage Ganho/Fechado Ganho · todos os tipos de venda",
    )
with m4:
    metric_card_v2(
        "Vendas novas",
        int_br(k["vendas_novas"]),
        delta_pct=delta_pct(k["vendas_novas"], kp["vendas_novas"]),
        hint=f"tipo_venda='Novo cliente' · "
             f"taxa {pct(k['tx_lead_venda'], casas=1)} dos leads",
        accent=True,
    )

# ---------------------------------------------------------------------------
# Fim do funil — Receita, Montante, CPL (3 cards)
# ---------------------------------------------------------------------------
section_title("Fim do funil", "valor gerado e custo de aquisição")

f1, f2, f3 = st.columns(3, gap="small")
with f1:
    metric_card_v2(
        "Receita total",
        brl(k["valor_receita"], casas=2),
        delta_pct=delta_pct(k["valor_receita"], kp["valor_receita"]),
        hint=f"SUM(receita) zoho_deals · ticket "
             f"{brl(k['ticket_medio'], casas=2) if k['ticket_medio'] else '—'}",
    )
with f2:
    metric_card_v2(
        "Montante total",
        brl(k["montante"], casas=2),
        delta_pct=delta_pct(k["montante"], kp["montante"]),
        hint="SUM(amount) zoho_deals",
    )
with f3:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2) if k["cpl"] else "—",
        delta_pct=delta_pct(k["cpl"], kp["cpl"]),
        hint="invest ÷ leads",
    )

if filtro_canal_ativo:
    st.caption(
        "ℹ️ Filtro de canal ativo — KPIs exibem a parcela atribuída aos canais "
        "selecionados. Vendas sem correspondência de lead entram como **Sem "
        "canal** e ficam fora quando o filtro é específico. A **Evolução "
        "diária** continua mostrando o total geral."
    )

# ---------------------------------------------------------------------------
# Funil visual com drop-off entre estágios (6 etapas)
# Investimento entra com escala R$ — somado como contagem no Plotly funnel
# fica distorcido. Mantemos só as 5 etapas de contagem (Leads → Vendas novas)
# no chart e exibimos o invest no card e na evolução diária.
# ---------------------------------------------------------------------------
section_title("Funil visual",
              "leads → vendas novas · queda percentual entre estágios")

labels_full, values_full = funil_estagios_oficial(k)
# Drop "Investimento" (índice 0) do funnel chart — escala incompatível.
labels = labels_full[1:]
values = values_full[1:]

if all(v == 0 for v in values):
    st.info("Sem dados no período para os canais selecionados.")
else:
    st.plotly_chart(
        funnel(labels, values, height=400, show_dropoff=True),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Evolução diária — sempre TOTAL GERAL (alinhado com Visão Geral / ROAS-CAC)
# ---------------------------------------------------------------------------
section_title("Evolução diária",
              "investimento × leads × qualificados × vendas novas")

diario = funil_diario_oficial(df_vg_diario)
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
        x=diario["data_ref"], y=diario["leads_qualificados"],
        name="Qualificados",
        line=dict(color="#7C3AED", width=2.2, dash="dash"),
        mode="lines+markers+text", marker=dict(size=6, color="#7C3AED"),
        text=last_point_text(diario["leads_qualificados"], int_br),
        textposition="top center",
        textfont=dict(color="#7C3AED", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} qualif<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["vendas_novas"], name="Vendas novas",
        line=dict(color=PALETTE["gold_bright"], width=2.2, dash="dot"),
        mode="lines+markers+text",
        marker=dict(size=6, color=PALETTE["gold_bright"]),
        text=last_point_text(diario["vendas_novas"], int_br),
        textposition="top center",
        textfont=dict(color=PALETTE["gold_bright"], size=11, family="Inter"),
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
# Tabela por canal — preserva canais sem dado quando o filtro inclui canais
# canônicos sem volume (Pinterest, LinkedIn, etc.)
# ---------------------------------------------------------------------------
section_title("Por canal",
              "métricas consolidadas · canais selecionados (inclui Sem canal "
              "quando filtro = todos)")

if filtro_canal_ativo:
    canais_visiveis = canais_sel
else:
    # Todos canais: mostra todos os canais que aparecem em df_kpc (incluindo
    # 'Sem canal'). Não força a lista canônica pra que 'Sem canal' apareça.
    canais_visiveis = (
        df_kpc["canal"].dropna().astype(str).unique().tolist()
        if not df_kpc.empty else list(CANAIS_VISIVEIS_OVERVIEW)
    )

by_canal = funil_por_canal_oficial(
    df_kpc, df_atividades, canais_visiveis=canais_visiveis,
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
            "leads_mais_12": st.column_config.NumberColumn("+12", format="%d"),
            "leads_menos_12": st.column_config.NumberColumn("-12", format="%d"),
            "agendamentos": st.column_config.NumberColumn(
                "Agend.", format="%d"),
            "comparecimentos": st.column_config.NumberColumn(
                "Compar.", format="%d"),
            "vendas": st.column_config.NumberColumn("Vendas", format="%d"),
            "vendas_novas": st.column_config.NumberColumn(
                "Vendas novas", format="%d"),
            "montante": st.column_config.NumberColumn(
                "Montante", format="R$ %.2f"),
            "valor_receita": st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"),
            "cpl": st.column_config.NumberColumn("CPL", format="R$ %.2f"),
            "tx_qualificacao": st.column_config.NumberColumn(
                "Tx Qualif.", format="%.2f%%"),
            "tx_lead_venda": st.column_config.NumberColumn(
                "Tx Lead→Venda", format="%.2f%%"),
        },
    )

st.caption(
    "**Mesmas fontes da Visão Geral Marketing / Growth / ROAS-CAC.** "
    "Investimento: `bi.vw_mkt_overview`. Leads / qualificados / +12 / -12: "
    "regra oficial via `bi_mkt.vw_visao_geral_canal_base` (canal-aware, "
    "classif canônica last_row). Agendamentos / Comparecimentos: leads "
    "únicos com activity `Consulta`/`Indicação` em `zoho_activities` ligada "
    "via `what_id` a deal pareado. Vendas / Vendas novas / Montante / "
    "Receita: `zoho_deals` com priority match `zoho_id > session_id > "
    "email`; deals sem lead correspondente entram como **Sem canal**. "
    "**Vendas novas** = `tipo_venda='Novo cliente'` (caminho de aquisição). "
    "Página migrada da `bi.mv_mkt_funil` (defasada) — não depende mais de "
    "REFRESH manual."
)
