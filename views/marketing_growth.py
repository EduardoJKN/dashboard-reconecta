"""Growth — visão consolidada "do investimento à venda".

Página adaptada do mock `sah_growth_landing_pages.html` para usar SOMENTE
dados reais já disponíveis no projeto. As seções do mock que dependiam de
rastreador session-level (engajamento, scroll, form abandonment) ficaram
fora desta V1; quando o time conectar GA/Pixel/Mixpanel ao banco, voltam.

Fontes:
    bi.vw_mkt_overview                — invest, imp, cliques, leads, +12, -12
    odam.mart_ad_funnel_daily         — agend/comparec/no-shows/vendas/receita
                                         (consumida via mkt_growth_daily.sql,
                                         agregada por data_ref)
    bi.mv_mkt_roas                    — base para CPL/CAC/ROAS diários
"""
from __future__ import annotations

import html as html_lib
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_growth_daily,
    get_mkt_overview,
    get_mkt_roas,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    growth_diario_overview,
    growth_eficiencia_diaria,
    growth_funil_etapas,
    growth_kpis,
    growth_scatter_leads_agend,
)
from src.transforms import delta_pct
from src.ui.charts import last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, brl_short, int_br, pct

# ---------------------------------------------------------------------------
# Header — sem filtro de canal na V1: invest/leads vêm de overview (todos
# canais) e agend/comparec/vendas vêm da mart (cobertura primária Meta).
# Misturar canal filtrado entre os dois lados distorceria a narrativa.
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Growth",
    subtitle="Performance Marketing → Resultado · do investimento à venda",
    filters=[],
)

# ---------------------------------------------------------------------------
# Cargas (período atual + anterior para deltas)
# ---------------------------------------------------------------------------
df_overview = safe_run(
    lambda: get_mkt_overview(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_overview",
)
df_growth_mart = safe_run(
    lambda: get_mkt_growth_daily(ctx.data_ini, ctx.data_fim),
    view_label="odam.mart_ad_funnel_daily (growth diária)",
)
df_roas = safe_run(
    lambda: get_mkt_roas(ctx.data_ini, ctx.data_fim),
    view_label="bi.mv_mkt_roas",
)

dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_overview_prev = safe_run(
    lambda: get_mkt_overview(prev_ini, prev_fim),
    view_label="bi.vw_mkt_overview",
)
df_growth_mart_prev = safe_run(
    lambda: get_mkt_growth_daily(prev_ini, prev_fim),
    view_label="odam.mart_ad_funnel_daily (growth diária)",
)

k = growth_kpis(df_overview, df_growth_mart)
kp = growth_kpis(df_overview_prev, df_growth_mart_prev)

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

st.caption(
    "**Caveats de fonte.** Impressões e Cliques representam apenas mídia "
    "paga (Meta + Google + Pinterest). Leads e Leads +12 incluem todos os "
    "canais (paid + orgânico) via `bi.vw_mkt_overview`. Agendamentos, "
    "Comparecimentos e Vendas são atribuídos via "
    "`odam.mart_ad_funnel_daily` (cobertura primária Meta — diagnóstico "
    "completo na página Criativos)."
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
# Caption técnica final — discreta, sem placeholders visíveis
# ---------------------------------------------------------------------------
st.caption(
    "Fontes: `bi.vw_mkt_overview` (invest, imp, cliques, leads, +12) · "
    "`odam.mart_ad_funnel_daily` agregada por data_ref via "
    "`mkt_growth_daily.sql` (agendamentos, comparecimentos, no-shows, "
    "vendas, receita) · `bi.mv_mkt_roas` agregada por data_ref (CPL/CAC/"
    "ROAS recalculados sobre agregados). Seções de engajamento, scroll "
    "depth e form abandonment do mock original ficam de fora desta V1 — "
    "dependem de rastreador session-level (GA / Pixel / Mixpanel) ainda "
    "não integrado ao banco."
)
