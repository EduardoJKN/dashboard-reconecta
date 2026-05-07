"""Growth — visão consolidada "do investimento à venda".

Página adaptada do mock `sah_growth_landing_pages.html` para usar SOMENTE
dados reais já disponíveis no projeto. As seções do mock que dependiam de
rastreador session-level (engajamento, scroll, form abandonment) ficaram
fora desta V1; quando o time conectar GA/Pixel/Mixpanel ao banco, voltam.

Fontes:
    bi.vw_mkt_overview                — invest, imp, cliques, leads, +12, -12
    odam.mart_ad_funnel_daily         — agend/comparec/no-shows/vendas/receita
                                         (consumida via mkt_growth_daily_by_canal.sql
                                         com canal derivado por JOIN com vw_mkt_campanhas)
    bi.mv_mkt_roas                    — base para CPL/CAC/ROAS diários
"""
from __future__ import annotations

import html as html_lib
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_campanhas_leads_canal_diario,
    get_mkt_growth_atividades_canal,
    get_mkt_growth_daily_by_canal,
    get_mkt_overview,
    get_mkt_paginas_variantes,
    get_mkt_roas,
    get_mkt_visao_geral_kpis_canal,
)
from src.transforms import _safe_div
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_PADRAO,
    agregar_paginas_variantes,
    compara_paginas_variantes,
    filtro_canais_padrao,
    growth_cobertura_canal,
    growth_diario_overview,
    growth_eficiencia_diaria,
    growth_funil_etapas,
    growth_kpis,
    growth_mart_filtrar,
    growth_scatter_leads_agend,
    lista_paginas_variantes,
    pagina_variante_kpis,
)
from src.transforms import delta_pct
from src.ui.charts import last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, brl_short, int_br, pct

# ---------------------------------------------------------------------------
# Header — filtro de canal (Opção A do diagnóstico): canal nativo nas views
# BI (overview, mv_roas) e canal derivado por JOIN na mart. Linhas da mart
# com `campaign_id` NULL ficam apenas no agregado "todos canais".
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Growth",
    subtitle="Performance Marketing → Resultado · do investimento à venda",
    filters=["canal"],
)
col_map = {"canal": "canal"}
# Garante os 4 canais sempre visíveis no filtro (mesmo zerados) — mesmo
# padrão das demais páginas (Funil, Visão Geral, ROAS-CAC).
ctx.apply_filters(filtro_canais_padrao(CANAIS_PADRAO), col_map)

# ---------------------------------------------------------------------------
# Cargas (período atual + anterior para deltas)
# ---------------------------------------------------------------------------
df_overview_all = safe_run(
    lambda: get_mkt_overview(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_overview",
)
df_growth_mart_by_canal = safe_run(
    lambda: get_mkt_growth_daily_by_canal(ctx.data_ini, ctx.data_fim),
    view_label="odam.mart_ad_funnel_daily (growth · por canal)",
)
df_roas_all = safe_run(
    lambda: get_mkt_roas(ctx.data_ini, ctx.data_fim),
    view_label="bi.mv_mkt_roas",
)

dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_overview_prev_all = safe_run(
    lambda: get_mkt_overview(prev_ini, prev_fim),
    view_label="bi.vw_mkt_overview",
)
df_growth_mart_prev_by_canal = safe_run(
    lambda: get_mkt_growth_daily_by_canal(prev_ini, prev_fim),
    view_label="odam.mart_ad_funnel_daily (growth · por canal)",
)

# ---------------------------------------------------------------------------
# Aplica filtro de canal (Opção A)
# - Topo (overview): refilter nativo via canal
# - Eficiência (mv_roas): refilter nativo via canal
# - Fundo (mart by_canal): growth_mart_filtrar — `todos_canais=True` inclui
#   linhas com canal=NaN (campaign_id NULL); subset filtra exclusivo, NaN sai
# ---------------------------------------------------------------------------
canais_no_dado = (
    set(df_overview_all["canal"].dropna().astype(str).unique())
    if not df_overview_all.empty else set()
)
canais_sel = list(ctx.selections.get("canal") or [])
filtro_todos_canais = (not canais_sel) or (set(canais_sel) >= canais_no_dado)

df_overview = (
    ctx.refilter(df_overview_all, col_map) if not df_overview_all.empty else df_overview_all
)
df_overview_prev = (
    ctx.refilter(df_overview_prev_all, col_map)
    if not df_overview_prev_all.empty else df_overview_prev_all
)
df_roas = (
    ctx.refilter(df_roas_all, col_map) if not df_roas_all.empty else df_roas_all
)
df_growth_mart = growth_mart_filtrar(
    df_growth_mart_by_canal, canais_sel, todos_canais=filtro_todos_canais,
)
df_growth_mart_prev = growth_mart_filtrar(
    df_growth_mart_prev_by_canal, canais_sel, todos_canais=filtro_todos_canais,
)

# Cobertura do canal na mart do período atual — usada na caption do funil
# pra deixar explícito quanto do fundo do funil "sumiu" ao filtrar.
cob_canal = growth_cobertura_canal(df_growth_mart_by_canal)

k = growth_kpis(df_overview, df_growth_mart)
kp = growth_kpis(df_overview_prev, df_growth_mart_prev)

# ---------------------------------------------------------------------------
# Override oficial — Opção C (alinhamento parcial do funil com Visão Geral):
#   - Leads / Leads +12: bi_mkt.vw_visao_geral_canal_base (canal-aware,
#     last_row + canal_final, mesma regra da Visão Geral / Campanhas)
#   - Vendas / Receita / CAC / ROAS: zoho_deals Ganho/Fechado Ganho com
#     priority match zoho_id > session_id > email pra atribuição por canal
#   - Imp / Cliques: vw_mkt_overview (paid) — INALTERADOS
#   - Agendamentos / Comparecimentos: odam.mart_ad_funnel_daily (Meta-only)
#     INALTERADOS — fonte oficial CRM (vw_dashboard_comercial_executivas_rw)
#     não tem dimensão de canal, então mantém a rastreada pra preservar o
#     filtro do header
# ---------------------------------------------------------------------------
df_leads_canal_diario = safe_run(
    lambda: get_mkt_campanhas_leads_canal_diario(ctx.data_ini, ctx.data_fim),
    view_label="bi_mkt.vw_visao_geral_canal_base (canal-diario)",
)
df_leads_canal_diario_prev = safe_run(
    lambda: get_mkt_campanhas_leads_canal_diario(prev_ini, prev_fim),
    view_label="bi_mkt.vw_visao_geral_canal_base (canal-diario)",
)
df_kpc_canal = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_kpis_canal",
)
df_kpc_canal_prev = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(prev_ini, prev_fim),
    view_label="mkt_visao_geral_kpis_canal",
)
df_atividades_canal = safe_run(
    lambda: get_mkt_growth_atividades_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_growth_atividades_canal",
)
df_atividades_canal_prev = safe_run(
    lambda: get_mkt_growth_atividades_canal(prev_ini, prev_fim),
    view_label="mkt_growth_atividades_canal",
)


def _override_oficial(k_dict, df_leads_d, df_kpc, df_act, canais_sel,
                     todos_canais):
    """Sobrescreve no dict de KPIs:
        - leads / leads_mais_12 (+ recalcula cpl / cpl_mais_12)
        - agendamentos / comparecimentos (leads únicos via zoho_activities)
        - vendas / valor_receita (+ recalcula cac / roas)
    Quando `todos_canais=True`, soma TODAS as rows (inclusive 'Outros' /
    'Sem canal') — bate com o agregado da Visão Geral. Quando há filtro,
    soma apenas os canais selecionados.

    Funil contabiliza **leads únicos** que atingiram cada etapa, não
    quantidade de atividades. `agendamentos` = COUNT DISTINCT email com
    pelo menos 1 activity Consulta/Indicação na janela; `comparecimentos`
    exige status_reuniao='Concluída'."""
    invest_atual = float(k_dict.get("investimento", 0) or 0)

    # Leads / +12 oficial (daily by canal). Soma cross-days = totais período.
    if df_leads_d is not None and not df_leads_d.empty:
        sub = (df_leads_d if todos_canais
               else df_leads_d[df_leads_d["canal"].isin(canais_sel)])
        if not sub.empty:
            leads_oficial = float(sub["leads_totais"].sum())
            mais12_oficial = float(sub["leads_mais_12"].sum())
            k_dict["leads"]         = leads_oficial
            k_dict["leads_mais_12"] = mais12_oficial
            k_dict["cpl"]           = _safe_div(invest_atual, leads_oficial)
            k_dict["cpl_mais_12"]   = _safe_div(invest_atual, mais12_oficial)

    # Agendamentos / Comparecimentos — leads únicos com activity Zoho.
    if df_act is not None and not df_act.empty:
        sub_act = (df_act if todos_canais
                   else df_act[df_act["canal"].isin(canais_sel)])
        if not sub_act.empty:
            k_dict["agendamentos"]    = float(sub_act["leads_com_agendamento"].sum())
            k_dict["comparecimentos"] = float(sub_act["leads_com_comparecimento"].sum())
        else:
            k_dict["agendamentos"]    = 0.0
            k_dict["comparecimentos"] = 0.0

    # Vendas oficial — APENAS NOVO CLIENTE.
    # Para o funil Growth (caminho de aquisição), vendas conta só
    # `tipo_venda='Novo cliente'`. Ascensão / Renovação / Indicação ficam
    # de fora — bate com 50 (e não 57) em abril/2026.
    #
    # ⚠ Receita e ROAS continuam usando `receita_total_geral` (TODOS os
    # deals Ganho/Fechado Ganho, inclusive ascensão/renovação/indicação)
    # porque `mkt_visao_geral_kpis_canal.sql` não computa receita_novas
    # separado. Isso cria inconsistência semântica entre CAC (sobre vendas
    # novas) e ROAS (sobre receita total). Sinalizado na caption — pendente
    # decisão do time se receita também deve virar "só novos".
    if df_kpc is not None and not df_kpc.empty:
        if todos_canais:
            sub_kpc = df_kpc  # inclui Sem canal — bate com 50 / 774.182
        else:
            sub_kpc = df_kpc[df_kpc["canal"].isin(canais_sel)]
        if not sub_kpc.empty:
            vendas_novas = float(sub_kpc["vendas_novas_total_geral"].sum())
            receita_oficial = float(sub_kpc["receita_total_geral"].sum())
            k_dict["vendas"]        = vendas_novas
            k_dict["valor_receita"] = receita_oficial
            k_dict["cac"]           = _safe_div(invest_atual, vendas_novas)
            k_dict["roas"]          = _safe_div(receita_oficial, invest_atual)


_override_oficial(k,  df_leads_canal_diario,      df_kpc_canal,
                  df_atividades_canal,      canais_sel, filtro_todos_canais)
_override_oficial(kp, df_leads_canal_diario_prev, df_kpc_canal_prev,
                  df_atividades_canal_prev, canais_sel, filtro_todos_canais)

# ---------------------------------------------------------------------------
# Seção 1 — KPIs (7 cards · 4 + 3) com delta vs período anterior
# ---------------------------------------------------------------------------
section_title(
    "Indicadores principais",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')} "
    f"· vs período anterior",
)

c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="canais combinados · vw_mkt_overview",
        accent=True,
    )
with c2:
    metric_card_v2(
        "Leads",
        int_br(k["leads"]),
        delta_pct=delta_pct(k["leads"], kp["leads"]),
        hint="todos canais · vw_mkt_overview",
    )
with c3:
    metric_card_v2(
        "Leads +12",
        int_br(k["leads_mais_12"]),
        delta_pct=delta_pct(k["leads_mais_12"], kp["leads_mais_12"]),
        hint="qualif. ATUA +12 · vw_mkt_overview",
    )
with c4:
    metric_card_v2(
        "Agendamentos",
        int_br(k["agendamentos"]),
        delta_pct=delta_pct(k["agendamentos"], kp["agendamentos"]),
        hint="atribuído · mart",
    )

c5, c6, c7 = st.columns(3, gap="small")
with c5:
    metric_card_v2(
        "Comparecimentos",
        int_br(k["comparecimentos"]),
        delta_pct=delta_pct(k["comparecimentos"], kp["comparecimentos"]),
        hint="atribuído · mart",
    )
with c6:
    metric_card_v2(
        "Vendas",
        int_br(k["vendas"]),
        delta_pct=delta_pct(k["vendas"], kp["vendas"]),
        hint="atribuído · mart",
        accent=True,
    )
with c7:
    metric_card_v2(
        "Receita",
        brl(k["valor_receita"], casas=2),
        delta_pct=delta_pct(k["valor_receita"], kp["valor_receita"]),
        hint="atribuído · mart",
    )

# ---------------------------------------------------------------------------
# Seção 2 — Funil 7 etapas adaptado
# Imp/Cliques: paid only (vw_mkt_overview); Leads/+12: todos canais (overview);
# Agendam/Comparec/Vendas: atribuído via mart (cobertura primária Meta).
# ---------------------------------------------------------------------------
section_title(
    "Funil · do investimento à venda",
    "7 etapas · drop-off entre etapas · gargalo destacado",
)

labels, values = growth_funil_etapas(k)

if all(v == 0 for v in values):
    st.info("Sem dados no período selecionado.")
else:
    # drop-offs entre etapas consecutivas: encontrar o maior pra destacar
    drops = []
    for i in range(len(labels) - 1):
        a, b = values[i], values[i + 1]
        d = (1 - b / a) * 100 if a > 0 else 0.0
        drops.append(d)
    bottleneck_idx = int(max(range(len(drops)), key=lambda i: drops[i])) if drops else -1

    # Cards lado a lado (7 colunas) — mesmo padrão do _creative_card_html
    def _step_card(idx: int, label: str, value: float,
                   prev_value: float | None) -> str:
        # % do TOPO (Impressões = 100%)
        topo = values[0] if values[0] > 0 else 1
        pct_topo = (value / topo) * 100 if topo > 0 else 0
        # % vs etapa anterior (mantém)
        pct_step = (value / prev_value * 100) if prev_value and prev_value > 0 else None

        # Highlight do gargalo: bordo wine + fundo wine_soft sutil
        is_bottleneck = (idx > 0 and (idx - 1) == bottleneck_idx)
        border_color = PALETTE["wine_light"] if is_bottleneck else PALETTE["border"]
        bg_color = PALETTE["wine_soft"] if is_bottleneck else PALETTE["card"]

        # Step value formatado
        if value >= 100_000:
            value_fmt = brl_short(value).replace("R$ ", "")  # "1,7M" → reusa
            value_fmt = f"{value / 1_000_000:.1f}M".replace(".", ",") if value >= 1_000_000 else f"{value / 1_000:.0f}K"
        else:
            value_fmt = int_br(int(value))

        pct_step_fmt = f"{pct_step:.1f}%".replace(".", ",") if pct_step is not None else "—"
        pct_topo_fmt = f"{pct_topo:.2f}%".replace(".", ",")

        return (
            f'<div style="background:{bg_color};'
            f'border:1px solid {border_color};border-radius:10px;'
            f'padding:12px 10px;height:100%;'
            f'font-family:Inter,sans-serif;text-align:center;">'
            f'<div style="font-size:0.62em;color:{PALETTE["muted"]};'
            f'text-transform:uppercase;letter-spacing:0.06em;'
            f'margin-bottom:6px;font-weight:600;">'
            f'{html_lib.escape(label)}</div>'
            f'<div style="font-size:1.35em;font-weight:700;'
            f'color:{PALETTE["gold"] if is_bottleneck else PALETTE["text"]};'
            f'line-height:1.1;font-variant-numeric:tabular-nums;'
            f'margin-bottom:6px;">{html_lib.escape(value_fmt)}</div>'
            f'<div style="font-size:0.7em;'
            f'color:{PALETTE["text_subtle"]};'
            f'font-variant-numeric:tabular-nums;">'
            f'<div>{html_lib.escape(pct_topo_fmt)} do topo</div>'
            f'<div style="margin-top:2px;'
            f'color:{PALETTE["wine_light"] if is_bottleneck else PALETTE["muted"]};">'
            f'{"vs anterior: " + html_lib.escape(pct_step_fmt) if idx > 0 else "topo do funil"}'
            f'</div>'
            f'</div>'
            f'</div>'
        )

    funnel_cols = st.columns(7, gap="small")
    for i, col in enumerate(funnel_cols):
        with col:
            prev_v = values[i - 1] if i > 0 else None
            st.markdown(_step_card(i, labels[i], values[i], prev_v),
                        unsafe_allow_html=True)

    # Insight do gargalo
    if bottleneck_idx >= 0:
        gargalo_label = (
            f"{labels[bottleneck_idx]} → {labels[bottleneck_idx + 1]}"
        )
        drop_fmt = f"{drops[bottleneck_idx]:.1f}%".replace(".", ",")
        st.markdown(
            f'<div style="margin-top:14px;padding:10px 14px;'
            f'background:{PALETTE["wine_soft"]};'
            f'border:1px solid {PALETTE["wine_light"]};'
            f'border-radius:10px;font-size:0.88em;'
            f'color:{PALETTE["text"]};">'
            f'<strong style="color:{PALETTE["wine_light"]};">'
            f'Maior gargalo · {html_lib.escape(gargalo_label)} '
            f'(−{html_lib.escape(drop_fmt)}).</strong> '
            f'Etapa com a maior queda relativa do funil — alvo prioritário '
            f'de otimização.'
            f'</div>',
            unsafe_allow_html=True,
        )

# Caption do funil — caveats de fonte + cobertura dinâmica do filtro de canal
# na mart (proeminente porque % real costuma ser baixo nesta janela).
_pct_canal = cob_canal["pct_com_canal_agend"]
_pct_canal_fmt = f"{_pct_canal:.0f}%".replace(".", ",")
_total_agend_mart = int(cob_canal["total_agend"])
_agend_com_canal = int(cob_canal["agend_com_canal"])
_agend_sem_canal = int(cob_canal["agend_sem_canal"])

if filtro_todos_canais:
    _filter_msg = (
        f"Filtro **Todos canais** aplicado · agendamentos da mart somam "
        f"{_total_agend_mart} (inclui {_agend_sem_canal} linhas sem "
        f"`campaign_id` rastreável)."
    )
else:
    _filter_msg = (
        f"⚠ Filtro de canal aplicado (**{', '.join(canais_sel)}**). "
        f"Apenas {_pct_canal_fmt} dos {_total_agend_mart} agendamentos da "
        f"mart no período têm `campaign_id` rastreável; "
        f"{_agend_sem_canal} linhas sem campaign_id ficam fora do filtro "
        f"e aparecem apenas em **Todos canais**."
    )

st.caption(
    "**Fontes (alinhamento oficial).** "
    "Impressões e Cliques: mídia paga (`bi.vw_mkt_overview`). "
    "**Leads e Leads +12**: regra oficial via "
    "`bi_mkt.vw_visao_geral_canal_base` (canal-aware, classif canônica "
    "last_row do e-mail). "
    "**Agendamentos e Comparecimentos**: **leads únicos** com pelo menos "
    "uma activity em `zoho_activities` "
    "(`activity_type IN ('Consulta','Indicação')`, "
    "`start_datetime` na janela; comparecimento exige "
    "`status_reuniao='Concluída'`). Match canal via priority "
    "`zoho_id > session_id > email`. "
    "**Vendas**: apenas `tipo_venda = 'Novo cliente'` em `zoho_deals` "
    "(stages Ganho/Fechado Ganho) com priority match por canal — "
    "ascensão / renovação / indicação ficam fora do funil de aquisição. "
    "Atividades/reuniões podem ser maiores que leads únicos quando o "
    "mesmo lead reagenda — o funil prioriza avanço de leads. "
    "⚠ **Receita e ROAS** ainda incluem ascensão/renovação/indicação "
    "(`SUM(receita)` de todos os deals Ganho); CAC já usa só vendas "
    "novas — pendente alinhar receita/ROAS com a mesma regra. "
    f"{_filter_msg}"
)

# ---------------------------------------------------------------------------
# Seção 3 — Tendência diária: Investimento + Leads + Leads MA 7d
# ---------------------------------------------------------------------------
section_title(
    "Tendência diária",
    "Investimento (barra) · Leads diários · Leads MA 7 dias",
)

di = growth_diario_overview(df_overview, ma_window=7)
if di.empty:
    st.info("Sem dados diários no período.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=di["data_ref"], y=di["investimento"], name="Investimento",
        marker=dict(color=PALETTE["gold"],
                    line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=di["data_ref"], y=di["leads"], name="Leads",
        line=dict(color=PALETTE["wine_light"], width=2.0),
        mode="lines+markers", marker=dict(size=5),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=di["data_ref"], y=di["leads_ma"], name="Leads · MA 7d",
        line=dict(color=PALETTE["gold_bright"], width=2.2, dash="dash"),
        mode="lines+text",
        text=last_point_text(di["leads_ma"], lambda v: f"{v:.0f}"),
        textposition="top right",
        textfont=dict(color=PALETTE["gold_bright"], size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>MA7 %{y:.1f} leads<extra></extra>",
    ))
    fig.update_layout(
        height=360,
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
# Seção 4 — Eficiência diária: CPL · CAC · ROAS (3 mini-charts)
# Escalas muito diferentes → 3 charts separados (CPL ~R$ 100, CAC ~R$ 13k,
# ROAS ~1×). Mais legível que dois eixos no mesmo gráfico.
# ---------------------------------------------------------------------------
section_title(
    "Eficiência diária",
    "CPL · CAC · ROAS recalculados sobre agregados (não média de taxas)",
)

ef = growth_eficiencia_diaria(df_roas)
if ef.empty:
    st.info("Sem dados de eficiência no período (mv_mkt_roas vazio).")
else:
    def _eficiencia_chart(df, col, title, color, prefix="R$ ", suffix="",
                          decimals=2):
        fig = go.Figure()
        # Mostra zero para dias sem vendas (CAC) ou sem receita (ROAS) — é
        # zero real (mart trouxe vendas=0/receita=0), não ausência.
        fig.add_trace(go.Scatter(
            x=df["data_ref"], y=df[col], name=title,
            line=dict(color=color, width=2.2),
            mode="lines+markers", marker=dict(size=5),
            hovertemplate=(
                f"<b>%{{x|%d/%m/%Y}}</b><br>{title}: "
                f"{prefix}%{{y:,.{decimals}f}}{suffix}<extra></extra>"
            ),
        ))
        fig.update_layout(
            height=240,
            margin=dict(l=8, r=8, t=8, b=8),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor=PALETTE["card"],
            font=dict(color=PALETTE["text"], family="Inter", size=11),
            showlegend=False,
            hovermode="x unified",
            hoverlabel=dict(bgcolor=PALETTE["bg_soft"],
                            bordercolor=PALETTE["border_strong"],
                            font=dict(color=PALETTE["text"], family="Inter")),
            yaxis=dict(gridcolor=PALETTE["border"],
                       tickfont=dict(color=PALETTE["text_subtle"])),
            xaxis=dict(gridcolor=PALETTE["border"],
                       tickfont=dict(color=PALETTE["text_subtle"])),
        )
        return fig

    e_col1, e_col2, e_col3 = st.columns(3, gap="medium")
    with e_col1:
        st.markdown(
            f'<div style="font-size:0.78rem;color:{PALETTE["muted"]};'
            f'text-transform:uppercase;letter-spacing:0.04em;'
            f'font-weight:600;margin-bottom:4px;">CPL · invest ÷ leads</div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _eficiencia_chart(ef, "cpl", "CPL", PALETTE["wine_light"]),
            use_container_width=True,
        )
    with e_col2:
        st.markdown(
            f'<div style="font-size:0.78rem;color:{PALETTE["muted"]};'
            f'text-transform:uppercase;letter-spacing:0.04em;'
            f'font-weight:600;margin-bottom:4px;">CAC · invest ÷ vendas</div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _eficiencia_chart(ef, "cac", "CAC", PALETTE["yellow"]),
            use_container_width=True,
        )
    with e_col3:
        st.markdown(
            f'<div style="font-size:0.78rem;color:{PALETTE["muted"]};'
            f'text-transform:uppercase;letter-spacing:0.04em;'
            f'font-weight:600;margin-bottom:4px;">ROAS · receita ÷ invest</div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _eficiencia_chart(ef, "roas", "ROAS", PALETTE["gold_bright"],
                              prefix="", suffix="x", decimals=2),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Seção 5 — Scatter Leads × Agendamentos com Pearson r
# Leve ponte entre topo e meio do funil — confirma se a aquisição prevê
# agendamento dia-a-dia, ou se há ruído de hand-off.
# ---------------------------------------------------------------------------
section_title(
    "Correlação · Leads × Agendamentos diários",
    "ponte topo → meio do funil · Pearson r",
)

df_xy, r_pearson, n_pares = growth_scatter_leads_agend(df_overview, df_growth_mart)

if df_xy.empty or r_pearson is None:
    st.info(
        f"Não há pares suficientes pra calcular correlação "
        f"(n={n_pares} · mínimo 3 com variância > 0)."
    )
else:
    # Interpretação do r — força + direção
    abs_r = abs(r_pearson)
    if abs_r >= 0.7:
        forca = "forte"
        forca_color = PALETTE["green"]
    elif abs_r >= 0.4:
        forca = "moderada"
        forca_color = PALETTE["gold"]
    elif abs_r >= 0.2:
        forca = "fraca"
        forca_color = PALETTE["yellow"]
    else:
        forca = "muito fraca / inexistente"
        forca_color = PALETTE["muted"]
    sentido = "positiva" if r_pearson > 0 else ("negativa" if r_pearson < 0 else "nula")
    r_fmt = f"{r_pearson:.3f}".replace(".", ",")

    st.markdown(
        f'<div style="display:flex;gap:18px;align-items:center;'
        f'margin-bottom:8px;font-size:0.88rem;">'
        f'<span style="color:{PALETTE["muted"]};">'
        f'r de Pearson</span> '
        f'<span style="color:{forca_color};font-weight:700;'
        f'font-variant-numeric:tabular-nums;font-size:1.1rem;">'
        f'{html_lib.escape(r_fmt)}</span>'
        f'<span style="color:{PALETTE["text_subtle"]};">'
        f'· correlação <strong style="color:{forca_color};">{forca}</strong> '
        f'· {sentido} · n={n_pares} pares</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    fig_sc = go.Figure()
    fig_sc.add_trace(go.Scatter(
        x=df_xy["leads"], y=df_xy["agendamentos"],
        mode="markers",
        marker=dict(color=PALETTE["gold"], size=9,
                    line=dict(color=PALETTE["gold_bright"], width=1)),
        text=df_xy["data_ref"].dt.strftime("%d/%m/%Y"),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Leads: %{x:,.0f}<br>"
            "Agendamentos: %{y:,.0f}<extra></extra>"
        ),
        name="Dia",
    ))

    # Linha de regressão simples (não exibe se variância zero)
    if df_xy["leads"].std() > 0 and df_xy["agendamentos"].std() > 0:
        x = df_xy["leads"].astype(float)
        y = df_xy["agendamentos"].astype(float)
        slope = ((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()
        intercept = y.mean() - slope * x.mean()
        x_line = [float(x.min()), float(x.max())]
        y_line = [intercept + slope * xi for xi in x_line]
        fig_sc.add_trace(go.Scatter(
            x=x_line, y=y_line, mode="lines",
            line=dict(color=PALETTE["wine_light"], width=1.6, dash="dot"),
            name=f"Tendência",
            hoverinfo="skip",
        ))

    fig_sc.update_layout(
        height=340,
        margin=dict(l=12, r=12, t=12, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PALETTE["card"],
        font=dict(color=PALETTE["text"], family="Inter", size=12),
        showlegend=False,
        xaxis=dict(title="Leads / dia", gridcolor=PALETTE["border"],
                   tickfont=dict(color=PALETTE["text_subtle"])),
        yaxis=dict(title="Agendamentos / dia", gridcolor=PALETTE["border"],
                   tickfont=dict(color=PALETTE["text_subtle"])),
    )
    st.plotly_chart(fig_sc, use_container_width=True)

# ---------------------------------------------------------------------------
# Comparar páginas / variantes (MVP — só leads, sem visit-tracking)
# ---------------------------------------------------------------------------
section_title("Comparar páginas / variantes",
              "geração e qualidade de leads por (page_pathname, lp_variante) "
              "— filtre por campanha/criativo abaixo")

# DF email-level — base pros filtros e pra agregação Python.
df_pv_raw = safe_run(
    lambda: get_mkt_paginas_variantes(ctx.data_ini, ctx.data_fim),
    view_label="ext_reconecta.leads (email-level)",
)

# Opções de filtro — vêm do DF email-level no período. Helper local pra
# manter o boilerplate de "Todas/Todos" curto e consistente.
def _opts(col: str, default: str = "Todas") -> list[str]:
    if df_pv_raw.empty or col not in df_pv_raw.columns:
        return [default]
    vals = sorted(df_pv_raw[col].dropna().astype(str).unique().tolist())
    return [default] + vals

# Filtros que afetam SOMENTE essa seção. Linha 1: Campanha, Origem, Mídia.
# Linha 2: Fuso/região, Dispositivo. Help reforça isolamento dos KPIs do topo.
_HELP = ("Filtra apenas a comparação de páginas/variantes — não afeta "
         "os KPIs principais da página Growth.")

flt_l1_a, flt_l1_b, flt_l1_c = st.columns(3, gap="small")
with flt_l1_a:
    sel_campanha = st.selectbox(
        "Campanha", options=_opts("utm_campaign", "Todas"),
        index=0, key="cmp_pv_campanha", help=_HELP,
    )
with flt_l1_b:
    sel_origem = st.selectbox(
        "Origem", options=_opts("utm_source", "Todas"),
        index=0, key="cmp_pv_origem", help=_HELP,
    )
with flt_l1_c:
    sel_midia = st.selectbox(
        "Mídia", options=_opts("utm_medium", "Todas"),
        index=0, key="cmp_pv_midia", help=_HELP,
    )

flt_l2_a, flt_l2_b = st.columns(2, gap="small")
with flt_l2_a:
    sel_timezone = st.selectbox(
        "Fuso / região", options=_opts("timezone", "Todos"),
        index=0, key="cmp_pv_timezone", help=_HELP,
    )
with flt_l2_b:
    sel_device = st.selectbox(
        "Dispositivo", options=_opts("device_type", "Todos"),
        index=0, key="cmp_pv_device", help=_HELP,
    )

# Agrega após aplicar os filtros — produz DF (path, variante) com origem.
df_pv = agregar_paginas_variantes(
    df_pv_raw,
    campanha=sel_campanha,
    origem=sel_origem,
    midia=sel_midia,
    timezone=sel_timezone,
    device_type=sel_device,
)
pv_list = lista_paginas_variantes(df_pv)

if pv_list.empty:
    st.caption("Sem páginas/variantes para os filtros selecionados.")
else:
    options = pv_list["chave"].tolist()
    labels_map = dict(zip(pv_list["chave"], pv_list["label"]))
    idx_default_b = 1 if len(options) > 1 else 0

    sel_col_a, sel_col_b = st.columns(2, gap="small")
    with sel_col_a:
        sel_a = st.selectbox(
            "Página A",
            options=options,
            format_func=lambda c: labels_map.get(c, "—"),
            index=0,
            key="cmp_pagina_a",
        )
    with sel_col_b:
        sel_b = st.selectbox(
            "Página B",
            options=options,
            format_func=lambda c: labels_map.get(c, "—"),
            index=idx_default_b,
            key="cmp_pagina_b",
        )

    kA = pagina_variante_kpis(df_pv, sel_a)
    kB = pagina_variante_kpis(df_pv, sel_b)
    cmp_pv = compara_paginas_variantes(kA, kB)

    # Formatação por métrica — taxas em %, contagens em int_br, principais
    # como string, "—" para None / NaN / vazio.
    _PV_PCT = {"Taxa qualificação", "Taxa +12",
               "Cobertura CRM", "Taxa Lead → Ganho"}
    _PV_INT = {"Leads totais", "Leads qualificados", "Leads +12",
               "Leads -12", "Não atua",
               "Leads no CRM", "Leads ganhos",
               "Qtd. campanhas", "Qtd. criativos"}
    _PV_STR = {"Campanha principal", "Criativo principal", "URL exemplo"}

    def _fmt_pv_value(metrica: str, val) -> str:
        if val is None:
            return "—"
        if isinstance(val, float) and val != val:  # NaN
            return "—"
        if metrica in _PV_STR:
            s = str(val).strip()
            return s if s else "—"
        if metrica in _PV_PCT:
            return pct(float(val), casas=2)
        if metrica in _PV_INT:
            return int_br(float(val))
        return str(val)

    def _fmt_pv_delta(d) -> str:
        if d is None:
            return "—"
        try:
            if d != d:  # NaN
                return "—"
        except Exception:
            pass
        sign = "+" if d > 0 else ""
        return f"{sign}{d:.1f}%".replace(".", ",")

    def _fmt_pv_vencedor(v: str) -> str:
        return f"✓ {v}" if v else ""

    view = cmp_pv.assign(
        valor_a_fmt=cmp_pv.apply(
            lambda r: _fmt_pv_value(r["metrica"], r["valor_a"]), axis=1
        ),
        valor_b_fmt=cmp_pv.apply(
            lambda r: _fmt_pv_value(r["metrica"], r["valor_b"]), axis=1
        ),
        delta_fmt=cmp_pv["delta_pct"].apply(_fmt_pv_delta),
        vencedor_fmt=cmp_pv["vencedor"].apply(_fmt_pv_vencedor),
    )[["metrica", "valor_a_fmt", "valor_b_fmt", "delta_fmt", "vencedor_fmt"]]

    st.dataframe(
        view, use_container_width=True, hide_index=True,
        column_config={
            "metrica": "Métrica",
            "valor_a_fmt": "Página A",
            "valor_b_fmt": "Página B",
            "delta_fmt": st.column_config.TextColumn(
                "Δ%",
                help="(B − A) / A × 100. — quando A=0, valor categórico, "
                     "ou algum lado vazio.",
            ),
            "vencedor_fmt": st.column_config.TextColumn(
                "Vencedor",
                help="Maior é melhor para Leads totais/qualificados/+12, "
                     "Taxas e Qtd. campanhas/criativos. Leads -12, Não atua "
                     "e principais (categóricos) não destacam vencedor.",
            ),
        },
    )

    # Links clicáveis pra abrir as URLs em nova aba (st.dataframe não
    # transforma a string da linha "URL exemplo" em link). Só renderiza
    # quando a URL é válida — None/NaN/vazio/"—" são suprimidos.
    def _url_valido(u) -> str | None:
        if u is None:
            return None
        if isinstance(u, float) and u != u:  # NaN
            return None
        s = str(u).strip()
        if not s or s == "—":
            return None
        if not (s.startswith("http://") or s.startswith("https://")):
            return None
        return s

    url_a = _url_valido(kA.get("page_url_exemplo"))
    url_b = _url_valido(kB.get("page_url_exemplo"))
    partes = []
    if url_a:
        partes.append(f"[Abrir URL da Página A]({url_a})")
    if url_b:
        partes.append(f"[Abrir URL da Página B]({url_b})")
    if partes:
        # Streamlit abre links externos em nova aba por padrão.
        st.markdown(" · ".join(partes))

    st.caption(
        "Este comparativo usa **leads gerados por página/variante**. "
        "Ainda **não representa conversão real da página**, pois não há "
        "fonte de visitas/sessões disponível no banco. Quando houver, "
        "passamos a calcular `leads / visitas` por (page_pathname, "
        "lp_variante). "
        "**Cobertura CRM** e **Taxa Lead → Ganho** são conversões do "
        "lead dentro do funil comercial (`zoho_deals`), não da landing "
        "page."
    )

    # ---------------------- Expander: Detalhamento de origem ---------------
    with st.expander("Detalhamento de origem da página/variante"):
        det = df_pv[[
            "page_pathname", "lp_variante", "page_url_exemplo",
            "canais", "midias", "campanhas", "criativos",
            "fusos", "dispositivos",
            "qtd_campanhas", "qtd_criativos",
            # CRM / Zoho
            "leads_no_crm", "cobertura_crm",
            "leads_ganhos", "taxa_lead_ganho",
        ]].copy()
        # Listas → string separada por vírgula. Sem dropar — listas vazias
        # viram "—" na coluna (mais explícito que vazio).
        for c in ("canais", "midias", "campanhas", "criativos",
                  "fusos", "dispositivos"):
            det[c] = det[c].apply(
                lambda lst: ", ".join(lst) if isinstance(lst, list) and lst else "—"
            )
        det["page_url_exemplo"] = det["page_url_exemplo"].fillna("—")
        st.dataframe(
            det, use_container_width=True, hide_index=True,
            column_config={
                "page_pathname":     "Página",
                "lp_variante":       "Variante",
                "page_url_exemplo":  "URL exemplo",
                # "Canais" foi renomeado pra "Origens" — alinha com o
                # filtro Origem (utm_source) introduzido nessa seção.
                "canais":            "Origens",
                "midias":            "Mídias",
                "campanhas":         "Campanhas",
                "criativos":         "Criativos",
                "fusos":             "Fusos / regiões",
                "dispositivos":      "Dispositivos",
                "qtd_campanhas":     st.column_config.NumberColumn(
                    "Qtd. campanhas", format="%d"),
                "qtd_criativos":     st.column_config.NumberColumn(
                    "Qtd. criativos", format="%d"),
                "leads_no_crm":      st.column_config.NumberColumn(
                    "Leads no CRM", format="%d"),
                "cobertura_crm":     st.column_config.NumberColumn(
                    "Cobertura CRM", format="%.2f%%"),
                "leads_ganhos":      st.column_config.NumberColumn(
                    "Leads ganhos", format="%d"),
                "taxa_lead_ganho":   st.column_config.NumberColumn(
                    "Taxa Lead → Ganho", format="%.2f%%"),
            },
        )

# ---------------------------------------------------------------------------
# Caption técnica final — discreta, sem placeholders visíveis
# ---------------------------------------------------------------------------
st.caption(
    "Fontes: `bi.vw_mkt_overview` (invest, imp, cliques, leads, +12) · "
    "`odam.mart_ad_funnel_daily` agregada por (data_ref × canal) via "
    "`mkt_growth_daily_by_canal.sql` com canal derivado por JOIN com "
    "`bi.vw_mkt_campanhas` (agendamentos, comparecimentos, no-shows, "
    "vendas, receita) · `bi.mv_mkt_roas` agregada por data_ref (CPL/CAC/"
    "ROAS recalculados sobre agregados). "
    "Filtro por **Landing Page** depende de integração/field mapping de "
    "GA / Pixel / eventos de página — fora desta V1. "
    "Seções de engajamento, scroll depth e form abandonment do mock "
    "original também ficam pra V2 (mesma dependência)."
)
