"""Charts Plotly padronizados — dark/gold/wine, hover unificado, altura generosa."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .theme import PALETTE

# Paleta sequencial curada: dourados + vinhos + secundárias
_SEQ = [
    PALETTE["gold"],
    PALETTE["wine_light"],
    PALETTE["gold_bright"],
    PALETTE["wine"],
    PALETTE["blue"],
    PALETTE["green"],
    PALETTE["yellow"],
    PALETTE["red"],
    PALETTE["gold_soft"],
]


def _base_layout(height: int = 320, unified: bool = False) -> dict:
    return dict(
        height=height,
        margin=dict(l=12, r=12, t=20, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PALETTE["card"],
        font=dict(
            color=PALETTE["text"],
            family="Inter, system-ui, sans-serif",
            size=12,
        ),
        colorway=_SEQ,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=-0.22,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=PALETTE["text_subtle"], size=11),
        ),
        hoverlabel=dict(
            bgcolor=PALETTE["bg_soft"],
            bordercolor=PALETTE["border_strong"],
            font=dict(color=PALETTE["text"], family="Inter"),
        ),
        hovermode="x unified" if unified else "closest",
    )


def _style_axes(fig: go.Figure, money_axis: str | None = None) -> None:
    axis_style = dict(
        gridcolor=PALETTE["border"],
        zerolinecolor=PALETTE["border"],
        linecolor=PALETTE["border"],
        tickfont=dict(color=PALETTE["text_subtle"], size=11),
        title_font=dict(color=PALETTE["muted"], size=11),
        automargin=True,  # garante que tick labels longos não sejam cortados
    )
    fig.update_xaxes(**axis_style, showspikes=False)
    fig.update_yaxes(**axis_style, showspikes=False)
    if money_axis == "y":
        fig.update_yaxes(tickprefix="R$ ", separatethousands=True)
    if money_axis == "x":
        fig.update_xaxes(tickprefix="R$ ", separatethousands=True)


def _truncate(s, max_len: int = 26) -> str:
    s = str(s)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _fig(**kwargs) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**_base_layout(**kwargs))
    return fig


# ---------------------------------------------------------------------------
# Line
# ---------------------------------------------------------------------------

def line(df: pd.DataFrame, x: str, y: str | list[str],
         height: int = 320, money_axis: str | None = None,
         unified: bool = True) -> go.Figure:
    fig = px.line(df, x=x, y=y, markers=True)
    fig.update_traces(line=dict(width=2.5), marker=dict(size=6))
    fig.update_layout(**_base_layout(height=height, unified=unified))
    _style_axes(fig, money_axis=money_axis)
    return fig


def area(df: pd.DataFrame, x: str, y: str,
         height: int = 280, money_axis: str | None = None) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y],
        fill="tozeroy",
        line=dict(color=PALETTE["gold"], width=2.5),
        fillcolor="rgba(201,168,76,0.18)",
        mode="lines+markers",
        marker=dict(size=5),
    ))
    fig.update_layout(**_base_layout(height=height, unified=True))
    _style_axes(fig, money_axis=money_axis)
    return fig


def dual_line(df: pd.DataFrame, x: str, y_left: str, y_right: str,
              label_left: str, label_right: str,
              height: int = 360) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y_left], name=label_left,
        line=dict(color=PALETTE["gold"], width=2.8),
        mode="lines+markers", marker=dict(size=6),
    ))
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y_right], name=label_right,
        line=dict(color=PALETTE["wine_light"], width=2.8, dash="dot"),
        mode="lines+markers", marker=dict(size=6),
        yaxis="y2",
    ))
    fig.update_layout(
        **_base_layout(height=height, unified=True),
        yaxis=dict(title=label_left, gridcolor=PALETTE["border"],
                   tickfont=dict(color=PALETTE["gold"])),
        yaxis2=dict(title=label_right, overlaying="y", side="right",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=PALETTE["wine_light"])),
    )
    _style_axes(fig)
    return fig


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

def bar_ranked(df: pd.DataFrame, category: str, value: str,
               top_n: int = 15, money: bool = False,
               height: int | None = None,
               label_max_len: int = 26) -> go.Figure:
    data = df.nlargest(top_n, value).sort_values(value, ascending=True)
    h = height or max(260, 26 * len(data) + 60)
    text_vals = data[value].map(
        lambda v: f"R$ {v:,.0f}".replace(",", ".") if money else f"{v:,.0f}".replace(",", ".")
    )
    full_labels = data[category].astype(str)
    y_labels = full_labels.apply(lambda s: _truncate(s, label_max_len))

    # Cor do texto INTERNO acompanha a luminosidade da barra (mesmo colorscale):
    # barras douradas (norm >= 0.75) -> preto;  barras vinho/escuras -> branco.
    vals = data[value].astype(float).tolist()
    vmin, vmax = (min(vals), max(vals)) if vals else (0.0, 0.0)
    if vmax > vmin:
        norm = [(v - vmin) / (vmax - vmin) for v in vals]
    else:
        norm = [0.0] * len(vals)
    inside_text_colors = ["#1a1410" if n >= 0.75 else "#ffffff" for n in norm]

    fig = go.Figure(go.Bar(
        y=y_labels,
        x=data[value],
        orientation="h",
        marker=dict(
            color=data[value],
            colorscale=[[0, PALETTE["wine_soft"]], [0.5, PALETTE["wine"]], [1, PALETTE["gold"]]],
            line=dict(color=PALETTE["border_strong"], width=0.5),
        ),
        text=text_vals,
        # auto: barra grande -> dentro (anchored end); pequena -> fora
        textposition="auto",
        insidetextanchor="end",
        insidetextfont=dict(color=inside_text_colors, size=10, family="Inter"),
        outsidetextfont=dict(color=PALETTE["text_subtle"], size=10, family="Inter"),
        cliponaxis=False,
        customdata=full_labels.to_numpy(dtype=object).reshape(-1, 1),
        hovertemplate="<b>%{customdata[0]}</b><br>%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(height=h))
    fig.update_layout(
        showlegend=False,
        # margin direita modesta — labels grandes vão DENTRO da barra
        margin=dict(l=12, r=24, t=18, b=12),
        bargap=0.32,  # mais respiro entre as barras
    )
    _style_axes(fig, money_axis="x" if money else None)
    return fig


def bar_simple(df: pd.DataFrame, x: str, y: str,
               height: int = 280, money: bool = False,
               rotate_x: bool = False) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=df[x].astype(str),
        y=df[y],
        marker=dict(
            color=PALETTE["gold"],
            line=dict(color=PALETTE["border_strong"], width=0.5),
        ),
        hovertemplate="<b>%{x}</b><br>%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(height=height))
    fig.update_layout(showlegend=False)
    if rotate_x:
        fig.update_xaxes(tickangle=-30)
    _style_axes(fig, money_axis="y" if money else None)
    return fig


# ---------------------------------------------------------------------------
# Donut / Pie
# ---------------------------------------------------------------------------

def donut(df: pd.DataFrame, names: str, values: str,
          height: int = 280, total_label: str | None = None) -> go.Figure:
    fig = go.Figure(go.Pie(
        labels=df[names],
        values=df[values],
        hole=0.62,
        marker=dict(colors=_SEQ, line=dict(color=PALETTE["bg"], width=2)),
        textfont=dict(color="#1a1410", size=11, family="Inter"),
        texttemplate="<b>%{percent}</b>",
        textposition="inside",
        insidetextorientation="horizontal",
        sort=False,
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} (%{percent})<extra></extra>",
    ))
    fig.update_layout(**_base_layout(height=height))
    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.02,
            xanchor="center", x=0.5,
            font=dict(color=PALETTE["text_subtle"], size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        # margem inferior maior pra acomodar a legenda
        margin=dict(l=12, r=12, t=12, b=36),
    )
    if total_label:
        total = df[values].sum()
        fig.add_annotation(
            text=f"<b style='color:{PALETTE['gold']};font-size:1.15rem'>{total:,.0f}</b>"
                 f"<br><span style='color:{PALETTE['muted']};font-size:0.7rem'>"
                 f"{total_label.upper()}</span>",
            x=0.5, y=0.5, showarrow=False, font=dict(family="Inter"),
        )
    return fig


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------

def funnel(labels: list[str], values: list[float], height: int = 320) -> go.Figure:
    colors = [PALETTE["gold_bright"], PALETTE["gold"], PALETTE["wine_light"], PALETTE["wine"]]
    # se houver mais estágios, interpola
    while len(colors) < len(labels):
        colors.append(PALETTE["wine_soft"])
    fig = go.Figure(go.Funnel(
        y=labels,
        x=values,
        marker=dict(
            color=colors[:len(labels)],
            line=dict(color=PALETTE["bg"], width=2),
        ),
        textinfo="value+percent initial",
        textfont=dict(color=PALETTE["bg"], family="Inter", size=13),
        connector=dict(line=dict(color=PALETTE["border"], width=1)),
    ))
    fig.update_layout(**_base_layout(height=height))
    _style_axes(fig)
    return fig


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

def receita_vs_meta_mensal(df_m: pd.DataFrame, height: int = 400) -> go.Figure:
    """Barras de Receita + linha de Meta por mês, com rótulo MoM% sobre as barras."""
    fig = go.Figure()
    meses_fmt = pd.to_datetime(df_m["mes"]).dt.strftime("%b/%y").str.capitalize()

    # rótulos MoM na ponta da barra
    mom_txt = df_m["var_mom_pct"].apply(
        lambda v: "" if pd.isna(v) else f"{v:+.1f}%".replace(".", ",")
    )

    fig.add_trace(go.Bar(
        x=meses_fmt,
        y=df_m["receita"],
        name="Receita",
        marker=dict(
            color=PALETTE["gold"],
            line=dict(color=PALETTE["gold_soft"], width=0.8),
        ),
        text=mom_txt,
        textposition="outside",
        textfont=dict(color=PALETTE["text_subtle"], size=11, family="Inter"),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Receita: R$ %{y:,.0f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=meses_fmt,
        y=df_m["meta"],
        name="Meta",
        mode="lines+markers",
        line=dict(color=PALETTE["wine_light"], width=2.5, dash="dash"),
        marker=dict(size=8, symbol="diamond",
                    color=PALETTE["wine_light"],
                    line=dict(color=PALETTE["bg"], width=1.5)),
        hovertemplate="<b>%{x}</b><br>Meta: R$ %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(**_base_layout(height=height, unified=True))
    fig.update_layout(
        bargap=0.35,
        # top maior pra acomodar rótulos MoM acima das barras
        margin=dict(l=12, r=12, t=44, b=12),
    )
    _style_axes(fig, money_axis="y")
    return fig


def heatmap(matrix: pd.DataFrame, height: int = 440,
            label_x: str = "Closer", label_y: str = "SDR",
            metric: str = "Valor") -> go.Figure:
    fig = go.Figure(data=go.Heatmap(
        z=matrix.values,
        x=matrix.columns.astype(str),
        y=matrix.index.astype(str),
        colorscale=[
            [0.0, PALETTE["card"]],
            [0.25, PALETTE["wine_soft"]],
            [0.6, PALETTE["wine"]],
            [0.85, PALETTE["wine_light"]],
            [1.0, PALETTE["gold"]],
        ],
        colorbar=dict(
            title=dict(text=metric, font=dict(color=PALETTE["text_subtle"])),
            tickfont=dict(color=PALETTE["text_subtle"]),
            outlinecolor=PALETTE["border"],
        ),
        hovertemplate=f"<b>{label_y}:</b> %{{y}}<br><b>{label_x}:</b> %{{x}}"
                      f"<br><b>{metric}:</b> %{{z:,.0f}}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(height=height))
    _style_axes(fig)
    return fig
