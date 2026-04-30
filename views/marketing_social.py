"""Social — Instagram orgânico (alcance, engajamento, posts).

Consome `bi.vw_mkt_social` (versão TZ-corrigida que normaliza o `timestamp`
para America/Sao_Paulo). Página de orgânico — sem investimento, foco em
volume e qualidade de engajamento."""
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import get_mkt_social
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    social_diario,
    social_kpis,
    social_recentes,
    social_top_posts,
)
from src.transforms import delta_pct
from src.ui.charts import bar_ranked
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, int_br, pct

# ---------------------------------------------------------------------------
# Header + filtros (período + tipo de mídia)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Social",
    subtitle="Instagram orgânico · alcance e engajamento",
    filters=["tipo_midia"],
)
col_map = {"tipo_midia": "tipo_midia"}

# ---------------------------------------------------------------------------
# Carga (período atual + período anterior para deltas)
# ---------------------------------------------------------------------------
df_all = safe_run(
    lambda: get_mkt_social(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_social",
)
df = ctx.apply_filters(df_all, col_map) if not df_all.empty else df_all

dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_prev_all = safe_run(
    lambda: get_mkt_social(prev_ini, prev_fim),
    view_label="bi.vw_mkt_social",
)
df_prev = (
    ctx.refilter(df_prev_all, col_map) if not df_prev_all.empty else df_prev_all
)

k = social_kpis(df)
kp = social_kpis(df_prev)

# Display username @perfil — pega da 1ª linha (CROSS JOIN no SQL replica em todas)
username_label = "—"
if not df.empty and "username" in df.columns:
    val = df.iloc[0].get("username")
    if val:
        username_label = f"@{val}"

# ---------------------------------------------------------------------------
# KPIs — bloco 1 (volumes principais)
# ---------------------------------------------------------------------------
section_title(
    "Resumo do perfil",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2(
        "Seguidores",
        int_br(k["seguidores"]),
        delta_pct=delta_pct(k["seguidores"], kp["seguidores"]),
        hint=username_label,
        accent=True,
    )
with c2:
    metric_card_v2(
        "Posts publicados",
        int_br(k["posts"]),
        delta_pct=delta_pct(k["posts"], kp["posts"]),
        hint="no período filtrado",
    )
with c3:
    metric_card_v2(
        "Alcance total",
        int_br(k["alcance_total"]),
        delta_pct=delta_pct(k["alcance_total"], kp["alcance_total"]),
        hint="soma dos alcances dos posts",
    )
with c4:
    metric_card_v2(
        "Engajamento",
        int_br(k["engajamento_total"]),
        delta_pct=delta_pct(k["engajamento_total"], kp["engajamento_total"]),
        hint="curtidas + comentários + saves",
    )

# ---------------------------------------------------------------------------
# KPIs — bloco 2 (eficiência por post + retenção)
# ---------------------------------------------------------------------------
s1, s2, s3, s4 = st.columns(4, gap="small")
with s1:
    metric_card_v2(
        "Taxa de engajamento",
        pct(k["taxa_engajamento"], casas=2),
        delta_pct=delta_pct(k["taxa_engajamento"], kp["taxa_engajamento"]),
        hint="eng ÷ (posts × seguidores)",
    )
with s2:
    metric_card_v2(
        "Alcance médio/post",
        int_br(k["alcance_medio"]),
        delta_pct=delta_pct(k["alcance_medio"], kp["alcance_medio"]),
        hint="alcance ÷ posts",
    )
with s3:
    metric_card_v2(
        "Engajamento médio/post",
        int_br(k["engajamento_medio"]),
        delta_pct=delta_pct(k["engajamento_medio"], kp["engajamento_medio"]),
        hint="eng ÷ posts",
    )
with s4:
    metric_card_v2(
        "Salvamentos",
        int_br(k["saves_totais"]),
        delta_pct=delta_pct(k["saves_totais"], kp["saves_totais"]),
        hint="indicador de retenção",
    )

# ---------------------------------------------------------------------------
# Evolução diária — alcance × engajamento (linhas) + posts (barra)
# ---------------------------------------------------------------------------
section_title("Evolução diária", "alcance × engajamento × posts")

diario = social_diario(df)
if diario.empty:
    st.info("Sem posts no período para os filtros aplicados.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["posts"], name="Posts",
        marker=dict(color=PALETTE["wine"],
                    line=dict(color=PALETTE["wine_soft"], width=0.6)),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:.0f} posts<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["alcance"], name="Alcance",
        line=dict(color=PALETTE["gold"], width=2.5),
        mode="lines+markers", marker=dict(size=6),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} alcance<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["engajamento"], name="Engajamento",
        line=dict(color=PALETTE["green"], width=2.2, dash="dot"),
        mode="lines+markers", marker=dict(size=6),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} eng<extra></extra>",
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
        bargap=0.35,
        yaxis=dict(title="Alcance / Engajamento",
                   gridcolor=PALETTE["border"],
                   tickfont=dict(color=PALETTE["gold"]),
                   separatethousands=True),
        yaxis2=dict(title="Posts", overlaying="y", side="right",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=PALETTE["wine_light"])),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"],
                     tickfont=dict(color=PALETTE["text_subtle"], size=11))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Top posts — ranking por métrica escolhida
# ---------------------------------------------------------------------------
TOP_OPTIONS = {
    "Alcance":     "alcance",
    "Engajamento": "engajamento",
    "Curtidas":    "curtidas",
    "Comentários": "comentarios",
    "Salvamentos": "salvamentos",
}

head_l, head_r = st.columns([3, 1.2], vertical_alignment="bottom")
with head_l:
    section_title("Top 10 posts", "ranking pela métrica selecionada")
with head_r:
    sort_choice = st.selectbox(
        "Ordenar por",
        list(TOP_OPTIONS.keys()),
        index=0, key="social_top_sort",
        label_visibility="collapsed",
    )

sort_field = TOP_OPTIONS[sort_choice]
top = social_top_posts(df, sort_by=sort_field, top_n=10)

if top.empty:
    st.info("Sem posts no período para o ranking.")
else:
    top_chart = top.copy()
    top_chart["label"] = (
        top_chart["data_ref"].dt.strftime("%d/%m") + " · "
        + top_chart["tipo_midia"].fillna("—").astype(str)
    )
    # desambigua se houver labels duplicados (mesmo dia + tipo)
    if top_chart["label"].duplicated().any():
        top_chart["label"] = (
            top_chart["label"] + " · "
            + top_chart["post_id"].astype(str).str.slice(-4)
        )

    st.plotly_chart(
        bar_ranked(top_chart, category="label", value=sort_field,
                   top_n=10, money=False, height=380),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Posts recentes — tabela com link para o Instagram
# ---------------------------------------------------------------------------
section_title("Posts recentes", "20 mais recentes no período")

recentes = social_recentes(df, n=20)
if recentes.empty:
    st.info("Sem posts no período.")
else:
    cols_show = [c for c in ["publicado_em", "tipo_midia", "alcance",
                              "curtidas", "comentarios", "salvamentos",
                              "engajamento", "taxa_engajamento_pct",
                              "permalink"]
                 if c in recentes.columns]

    st.dataframe(
        recentes[cols_show],
        use_container_width=True, hide_index=True,
        column_config={
            "publicado_em": st.column_config.DatetimeColumn(
                "Publicado em", format="DD/MM/YYYY HH:mm"),
            "tipo_midia": "Tipo",
            "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
            "curtidas": st.column_config.NumberColumn("Curtidas", format="%d"),
            "comentarios": st.column_config.NumberColumn(
                "Comentários", format="%d"),
            "salvamentos": st.column_config.NumberColumn("Saves", format="%d"),
            "engajamento": st.column_config.NumberColumn(
                "Engajamento", format="%d"),
            "taxa_engajamento_pct": st.column_config.NumberColumn(
                "Tx Eng.", format="%.2f%%"),
            "permalink": st.column_config.LinkColumn(
                "Instagram", display_text="abrir"),
        },
    )
