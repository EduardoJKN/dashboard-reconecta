"""Charts Plotly padronizados — dark/gold/wine, hover unificado, altura generosa."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .theme import PALETTE, int_br, pct

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


def last_point_text(values, formatter=None) -> list[str]:
    """Constrói array de `text` com SÓ o último valor formatado — usado em
    Scatter `mode="lines+markers+text"` para anotar o ponto final de uma
    série temporal sem poluir o gráfico.

    Aceita lista, tuple, np.array ou pd.Series. Retorna ['', '', ..., 'last'].
    Quando o último valor é None/NaN, retorna lista de strings vazias.
    Quando `formatter` é None, formata como inteiro BR (`1.234`)."""
    if values is None:
        return []
    try:
        seq = list(values)
    except TypeError:
        return []
    n = len(seq)
    if n == 0:
        return []
    last = seq[-1]
    try:
        if last is None:
            return [""] * n
        if isinstance(last, float) and last != last:  # NaN
            return [""] * n
    except Exception:
        return [""] * n
    if formatter is None:
        text = f"{float(last):,.0f}".replace(",", ".")
    else:
        text = formatter(last)
    return [""] * (n - 1) + [text]


def annotate_extremes(values, formatter=None) -> list[str]:
    """`text` array para Scatter com rótulos no ÚLTIMO ponto e no maior
    valor da série (deduplicado se coincidirem). Demais pontos ficam sem
    rótulo — leitura limpa sem poluir o gráfico.

    Útil pra séries temporais onde queremos sinalizar o estado atual e o
    pico do período sem anotação em cada marker.

    `formatter` default = inteiro BR (`1.234`). Passe `brl`/`pct` quando
    a métrica for monetária/percentual.
    """
    if values is None:
        return []
    try:
        seq = list(values)
    except TypeError:
        return []
    n = len(seq)
    if n == 0:
        return []
    if formatter is None:
        formatter = lambda v: f"{float(v):,.0f}".replace(",", ".")
    # Filtra pontos válidos (descarta None/NaN)
    valid = []
    for i, v in enumerate(seq):
        if v is None:
            continue
        try:
            if isinstance(v, float) and v != v:  # NaN
                continue
        except Exception:
            continue
        valid.append((i, v))
    if not valid:
        return [""] * n
    out = [""] * n
    last_i, last_v = valid[-1]
    out[last_i] = formatter(last_v)
    max_i, max_v = max(valid, key=lambda kv: kv[1])
    if max_i != last_i:
        out[max_i] = formatter(max_v)
    return out


def annotate_adaptive(values, formatter=None,
                      max_all: int = 7,
                      max_mid: int = 15) -> list[str]:
    """`text` array adaptativo ao tamanho da série:

      • até `max_all` pontos válidos (default 7) → rótulo em CADA ponto
        (períodos curtos, ex.: 1 semana, lê valor direto sem precisar
         do hover).
      • entre `max_all + 1` e `max_mid` (default 8–15) → rótulos em
        pontos ALTERNADOS (pares no array), com garantia explícita
        do último ponto e do máximo da série.
      • acima de `max_mid` → comportamento de `annotate_extremes` (só
        último + máximo, evita poluição em períodos longos).

    NaN/None ignorados (não consomem slot de rótulo).

    Usado nos gráficos da One Page → adapta automaticamente ao período
    selecionado pelo usuário. Pra séries secundárias que queiram ser
    mais conservadoras, basta passar `max_all=0` (nunca anota todos)
    ou `max_mid=0` (sempre cai no modo "extremos").
    """
    if values is None:
        return []
    try:
        seq = list(values)
    except TypeError:
        return []
    n = len(seq)
    if n == 0:
        return []
    if formatter is None:
        formatter = lambda v: f"{float(v):,.0f}".replace(",", ".")
    valid = []
    for i, v in enumerate(seq):
        if v is None:
            continue
        try:
            if isinstance(v, float) and v != v:
                continue
        except Exception:
            continue
        valid.append((i, v))
    if not valid:
        return [""] * n

    n_valid = len(valid)
    out = [""] * n

    if n_valid <= max_all:
        for i, v in valid:
            out[i] = formatter(v)
        return out

    if n_valid <= max_mid:
        # Pontos alternados (pares no array `valid`, índice 0, 2, 4…).
        for j in range(0, n_valid, 2):
            i, v = valid[j]
            out[i] = formatter(v)
        # Garante último + máximo, mesmo que não tenham caído no slot par.
        last_i, last_v = valid[-1]
        out[last_i] = formatter(last_v)
        max_i, max_v = max(valid, key=lambda kv: kv[1])
        if not out[max_i]:
            out[max_i] = formatter(max_v)
        return out

    # Períodos longos: só extremos
    last_i, last_v = valid[-1]
    out[last_i] = formatter(last_v)
    max_i, max_v = max(valid, key=lambda kv: kv[1])
    if max_i != last_i:
        out[max_i] = formatter(max_v)
    return out


def style_temporal(fig: go.Figure, x_date: bool = True) -> go.Figure:
    """Defaults visuais p/ gráficos temporais com legenda horizontal abaixo:
    margem inferior maior pra não atropelar tick labels com a legenda, e
    formato BR no eixo X (`%d/%m` no tick, `%d/%m/%Y` no hover). Os dois
    formatos de data são ignorados pelo Plotly quando o eixo não é de
    datas, então é seguro aplicar genericamente.
    """
    fig.update_layout(
        margin=dict(l=12, r=12, t=24, b=72),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=-0.32,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=PALETTE["text_subtle"], size=11),
        ),
    )
    if x_date:
        fig.update_xaxes(tickformat="%d/%m", hoverformat="%d/%m/%Y")
    return fig


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


def bar_etapa_distribuicao(
    df: pd.DataFrame,
    etapa_col: str,
    count_col: str,
    pct_col: str,
    height: int = 300,
) -> go.Figure:
    """Barras por etapa com rótulo `valor (percentual)` — distribuição do funil."""
    data = df.copy()
    ymax = float(data[count_col].max() or 1)
    _label_size = 14
    labels: list[str] = []
    positions: list[str] = []
    for _, row in data.iterrows():
        v = int(row[count_col] or 0)
        p = float(row[pct_col] or 0)
        pct_s = f"{p:.1f}".replace(".", ",") + "%"
        labels.append(f"<b>{int_br(v)} ({pct_s})</b>")
        positions.append("inside" if v >= ymax * 0.18 else "outside")

    fig = go.Figure(go.Bar(
        x=data[etapa_col].astype(str),
        y=data[count_col],
        text=labels,
        textposition=positions,
        insidetextfont=dict(color="#1a1410", size=_label_size, family="Inter"),
        outsidetextfont=dict(color=PALETTE["text"], size=_label_size, family="Inter"),
        cliponaxis=False,
        marker=dict(
            color=PALETTE["gold"],
            line=dict(color=PALETTE["border_strong"], width=0.5),
        ),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "%{y:,.0f} · %{customdata}<extra></extra>"
        ),
        customdata=[
            f"{float(p):.1f}%".replace(".", ",")
            for p in data[pct_col]
        ],
    ))
    fig.update_layout(**_base_layout(height=height))
    fig.update_layout(
        showlegend=False,
        margin=dict(l=12, r=12, t=40, b=48),
    )
    fig.update_xaxes(tickangle=-30)
    fig.update_yaxes(range=[0, ymax * 1.12])
    _style_axes(fig)
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

def funnel(labels: list[str], values: list[float], height: int = 320,
           show_dropoff: bool = False) -> go.Figure:
    """Funil padrão do projeto.

    Quando `show_dropoff=True`, cada estágio (a partir do 2º) ganha uma linha
    secundária mostrando a queda percentual em relação ao estágio anterior:
    `↓ X,Y% queda`. Útil para identificação rápida de gargalos.

    Texto: cor por barra — claro sobre vinho (barras escuras), escuro
    sobre dourado (barras claras). Resolve o problema de contraste em
    barras vermelhas/escuras."""
    colors = [PALETTE["gold_bright"], PALETTE["gold"], PALETTE["wine_light"], PALETTE["wine"]]
    while len(colors) < len(labels):
        colors.append(PALETTE["wine_soft"])

    # Texto: claro sobre barras escuras (wine_*), escuro sobre barras claras (gold_*)
    _LIGHT_BARS = {PALETTE["gold_bright"], PALETTE["gold"]}
    text_colors = [
        "#1a1410" if c in _LIGHT_BARS else PALETTE["text"]
        for c in colors[:len(labels)]
    ]

    funnel_kwargs = dict(
        y=labels,
        x=values,
        marker=dict(
            color=colors[:len(labels)],
            line=dict(color=PALETTE["bg"], width=2),
        ),
        textfont=dict(color=text_colors, family="Inter", size=14),
        connector=dict(line=dict(color=PALETTE["border"], width=1)),
    )

    if show_dropoff:
        texts: list[str] = []
        for i, v in enumerate(values):
            valor_fmt = int_br(v)
            if i == 0:
                texts.append(f"<b>{valor_fmt}</b>")
                continue
            prev = values[i - 1]
            if prev and prev > 0:
                keep = (v / prev) * 100
                drop = 100 - keep
                texts.append(
                    f"<b>{valor_fmt}</b><br>"
                    f"<span style='font-size:0.78em;opacity:0.85'>"
                    f"↓ {pct(drop)} queda"
                    f"</span>"
                )
            else:
                texts.append(f"<b>{valor_fmt}</b>")
        funnel_kwargs["text"] = texts
        funnel_kwargs["textinfo"] = "text"
    else:
        funnel_kwargs["textinfo"] = "value+percent initial"

    fig = go.Figure(go.Funnel(**funnel_kwargs))
    fig.update_layout(**_base_layout(height=height))
    _style_axes(fig)
    return fig


def funnel_detailed(
    labels: list[str],
    values: list[float],
    texts: list[str],
    *,
    height: int = 400,
) -> go.Figure:
    """Funil com rótulos customizados por etapa — mesmo estilo do Funil Marketing."""
    colors = [
        PALETTE["gold_bright"],
        PALETTE["gold"],
        PALETTE["wine_light"],
        PALETTE["wine"],
    ]
    while len(colors) < len(labels):
        colors.append(PALETTE["wine_soft"])

    _LIGHT_BARS = {PALETTE["gold_bright"], PALETTE["gold"]}
    text_colors = [
        "#1a1410" if c in _LIGHT_BARS else PALETTE["text"]
        for c in colors[: len(labels)]
    ]

    fig = go.Figure(
        go.Funnel(
            y=labels,
            x=values,
            text=texts,
            textinfo="text",
            marker=dict(
                color=colors[: len(labels)],
                line=dict(color=PALETTE["bg"], width=2),
            ),
            textfont=dict(color=text_colors, family="Inter", size=13),
            connector=dict(line=dict(color=PALETTE["border"], width=1)),
        )
    )
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
