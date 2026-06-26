"""Charts Plotly padronizados — dark/gold/wine, hover unificado, altura generosa."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .theme import PALETTE, brl, brl_short, int_br, pct

def _seq_colors() -> list[str]:
    """Paleta sequencial curada: dourados + vinhos + secundárias."""
    return [
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
        colorway=_seq_colors(),
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


# ---------------------------------------------------------------------------
# Formatação de rótulos — fonte única p/ barras, linhas e scatter
# ---------------------------------------------------------------------------

ChartLabelFormat = str  # "money" | "integer" | "days" | "percent"


def format_days_display(v: float) -> str:
    """Dias arredondados para exibição (rótulo/tooltip/tabela). Dados permanecem float."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and (v != v or np.isnan(v)):
            return ""
    except Exception:
        return ""
    return f"{int(float(v) + 0.5)} dias"


def format_chart_label(v: float, fmt: ChartLabelFormat = "integer") -> str:
    """Formata valor numérico para rótulo visível no gráfico (não altera dados)."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and (v != v or np.isnan(v)):
            return ""
    except Exception:
        return ""
    vf = float(v)
    if fmt == "money":
        return brl_short(vf) if abs(vf) >= 1_000_000 else brl(vf)
    if fmt == "days":
        return format_days_display(vf)
    if fmt == "percent":
        return pct(vf, casas=2)
    return int_br(round(vf))


def _resolve_label_format(
    *,
    money: bool = False,
    days_format: bool = False,
    percent_format: bool = False,
    value_format: ChartLabelFormat | None = None,
) -> ChartLabelFormat:
    if value_format:
        return value_format
    if money:
        return "money"
    if days_format:
        return "days"
    if percent_format:
        return "percent"
    return "integer"


def _bar_h_text_positions(values: list[float], inside_threshold: float = 0.22) -> list[str]:
    """Posição do rótulo em barras horizontais (inside vs outside)."""
    vmax = max(values) if values else 1.0
    if vmax <= 0:
        return ["outside"] * len(values)
    return [
        "inside" if float(v) >= vmax * inside_threshold else "outside"
        for v in values
    ]


def _bar_v_text_positions(values: list[float], inside_threshold: float = 0.15) -> list[str]:
    """Posição do rótulo em barras verticais (inside vs outside)."""
    vmax = max(values) if values else 1.0
    if vmax <= 0:
        return ["outside"] * len(values)
    return [
        "inside" if float(v) >= vmax * inside_threshold else "outside"
        for v in values
    ]


def _short_display_name(name: str, max_tokens: int = 2, max_len: int = 28) -> str:
    """Encurta nomes longos para rótulos de gráfico (tooltip mantém nome completo)."""
    raw = (name or "").strip()
    if not raw:
        return ""
    parts = raw.split()
    if len(parts) > max_tokens:
        raw = " ".join(parts[:max_tokens])
    return _truncate(raw, max_len)


_CICLO_LABEL_DIRECTIONS: tuple[tuple[str, int, int, str, str], ...] = (
    ("top center", 0, 1, "center", "bottom"),
    ("bottom center", 0, -1, "center", "top"),
    ("middle right", 1, 0, "left", "middle"),
    ("middle left", -1, 0, "right", "middle"),
    ("top right", 1, 1, "left", "bottom"),
    ("top left", -1, 1, "right", "bottom"),
    ("bottom right", 1, -1, "left", "top"),
    ("bottom left", -1, -1, "right", "top"),
)

_CICLO_OFFSETS_PX: tuple[int, ...] = (10, 12, 14, 16, 18, 22, 26)
_CICLO_MAX_OFFSET_PX = 26
_CICLO_ARROW_MIN_PX = 18


def _ciclo_direction_shift_px(dx: int, dy: int, dist_px: int) -> tuple[int, int]:
    """Deslocamento em pixels a partir do ponto — diagonal ligeiramente menor."""
    scale = 0.78 if dx and dy else 1.0
    return int(dx * dist_px * scale), int(dy * dist_px * scale)


def _ciclo_anchor_norm(
    nx: float,
    ny: float,
    xshift_px: int,
    yshift_px: int,
    *,
    plot_w_px: int,
    plot_h_px: int,
) -> tuple[float, float]:
    """Posição normalizada do anchor do rótulo em relação ao ponto."""
    return nx + xshift_px / plot_w_px, ny + yshift_px / plot_h_px


def _ciclo_ordered_label_directions(
    nx: float,
    ny: float,
    *,
    avg_ny: float | None = None,
) -> list[tuple[str, int, int, str, str]]:
    """Prioriza direções próximas ao ponto conforme bordas e linha de média."""
    all_dirs = list(_CICLO_LABEL_DIRECTIONS)
    if nx > 0.72:
        preferred = [d for d in all_dirs if "left" in d[0]]
    elif nx < 0.28:
        preferred = [d for d in all_dirs if "right" in d[0]]
    elif ny > 0.72:
        preferred = [d for d in all_dirs if "bottom" in d[0]]
    elif ny < 0.28:
        preferred = [d for d in all_dirs if "top" in d[0]]
    else:
        preferred = all_dirs

    if avg_ny is not None and abs(ny - avg_ny) < 0.12:
        if ny <= avg_ny:
            line_pref = [d for d in all_dirs if "top" in d[0] or "middle" in d[0]]
        else:
            line_pref = [d for d in all_dirs if "bottom" in d[0] or "middle" in d[0]]
        preferred = line_pref + [d for d in preferred if d not in line_pref]

    seen: set[tuple[str, int, int, str, str]] = set()
    ordered: list[tuple[str, int, int, str, str]] = []
    for direction in preferred + all_dirs:
        if direction not in seen:
            ordered.append(direction)
            seen.add(direction)
    return ordered


def _ciclo_label_bbox(
    lx: float,
    ly: float,
    width: float,
    height: float,
    xanchor: str,
    yanchor: str,
) -> tuple[float, float, float, float]:
    """Retângulo normalizado (x0, y0, x1, y1) da caixa do rótulo."""
    if xanchor == "center":
        x0, x1 = lx - width / 2, lx + width / 2
    elif xanchor == "left":
        x0, x1 = lx, lx + width
    else:
        x0, x1 = lx - width, lx
    if yanchor == "middle":
        y0, y1 = ly - height / 2, ly + height / 2
    elif yanchor == "bottom":
        y0, y1 = ly, ly + height
    else:
        y0, y1 = ly - height, ly
    return x0, y0, x1, y1


def _ciclo_labels_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    margin: float = 0.016,
) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (
        ax1 + margin < bx0
        or bx1 + margin < ax0
        or ay1 + margin < by0
        or by1 + margin < ay0
    )


def _ciclo_estimate_label_size(text: str, *, two_lines: bool) -> tuple[float, float]:
    """Largura/altura normalizadas aproximadas da caixa de texto."""
    plain = text.replace("<br>", "\n")
    lines = [ln for ln in plain.split("\n") if ln]
    n_lines = max(len(lines), 1)
    max_len = max((len(ln) for ln in lines), default=8)
    width = min(0.42, max_len * 0.0072 + 0.028)
    height = 0.042 * n_lines + (0.014 if two_lines else 0.010)
    return width, height


def _scatter_ciclo_prepare_label_parts(
    df: pd.DataFrame,
    label_col: str,
    x_col: str,
    y_col: str,
    *,
    x_is_percent: bool = False,
) -> list[tuple[str, str]]:
    """Nome curto + métricas por ponto (sempre com vendas/dias)."""
    parts: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        full_name = str(row[label_col]).strip()
        name = _short_display_name(full_name, max_tokens=2, max_len=26)
        metrics = _scatter_ciclo_label_metrics(
            float(row[x_col]), float(row[y_col]), x_is_percent=x_is_percent,
        )
        parts.append((name, metrics))
    return parts


def _scatter_ciclo_layout_annotations(
    xs: list[float],
    ys: list[float],
    label_parts: list[tuple[str, str]],
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    avg_y: float | None = None,
    chart_height: int = 420,
) -> list[dict]:
    """Posiciona rótulos colados ao ponto; afasta só o necessário p/ evitar colisão."""
    y_lo, y_hi = y_range
    y_span = y_hi - y_lo if y_hi > y_lo else max(abs(y_hi), 1.0)
    avg_ny: float | None = None
    if avg_y is not None and not pd.isna(avg_y):
        avg_ny = (float(avg_y) - y_lo) / y_span

    plot_h_px = max(chart_height - 112, 240)
    plot_w_px = int(plot_h_px * 1.45)

    placed_boxes: list[tuple[float, float, float, float]] = []
    layouts: list[dict] = []
    n = len(xs)

    crowded: set[int] = set()
    for i in range(n):
        for j in range(i + 1, n):
            xi, yi = _scatter_norm_xy(xs[i], ys[i], x_range, y_range)
            xj, yj = _scatter_norm_xy(xs[j], ys[j], x_range, y_range)
            if ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5 < 0.11:
                crowded.add(i)
                crowded.add(j)

    for i, (x, y) in enumerate(zip(xs, ys)):
        nx, ny = _scatter_norm_xy(x, y, x_range, y_range)
        name, metrics = label_parts[i]
        directions = _ciclo_ordered_label_directions(nx, ny, avg_ny=avg_ny)

        name_variants = [name]
        if i in crowded:
            first = name.split()[0] if name.split() else name
            if first not in name_variants:
                name_variants.append(first)

        line_modes = [True] if i in crowded else [False, True]
        resolved: dict | None = None

        for use_two_lines in line_modes:
            if resolved:
                break
            for variant in name_variants:
                text = _scatter_ciclo_format_label(
                    variant, metrics, two_lines=use_two_lines,
                )
                width, height = _ciclo_estimate_label_size(text, two_lines=use_two_lines)
                candidates: list[dict] = []

                for dir_idx, (_dir_name, dx, dy, xanchor, yanchor) in enumerate(directions):
                    for dist_px in _CICLO_OFFSETS_PX:
                        if dist_px > _CICLO_MAX_OFFSET_PX:
                            continue
                        xshift, yshift = _ciclo_direction_shift_px(dx, dy, dist_px)
                        lx, ly = _ciclo_anchor_norm(
                            nx, ny, xshift, yshift,
                            plot_w_px=plot_w_px, plot_h_px=plot_h_px,
                        )
                        box = _ciclo_label_bbox(lx, ly, width, height, xanchor, yanchor)
                        if box[0] < 0.02 or box[2] > 0.98 or box[1] < 0.02 or box[3] > 0.98:
                            continue
                        if any(_ciclo_labels_overlap(box, prev) for prev in placed_boxes):
                            continue
                        candidates.append({
                            "x": float(x),
                            "y": float(y),
                            "text": text,
                            "xanchor": xanchor,
                            "yanchor": yanchor,
                            "xshift": xshift,
                            "yshift": yshift,
                            "dist_px": dist_px,
                            "dir_idx": dir_idx,
                            "box": box,
                        })

                if candidates:
                    candidates.sort(key=lambda c: (c["dist_px"], c["dir_idx"]))
                    resolved = candidates[0]
                    break
            if resolved:
                break

        if resolved is None:
            text = _scatter_ciclo_format_label(
                name_variants[-1], metrics, two_lines=True,
            )
            dist_px = _CICLO_MAX_OFFSET_PX
            xshift, yshift = 0, dist_px
            lx, ly = _ciclo_anchor_norm(
                nx, ny, xshift, yshift,
                plot_w_px=plot_w_px, plot_h_px=plot_h_px,
            )
            resolved = {
                "x": float(x),
                "y": float(y),
                "text": text,
                "xanchor": "center",
                "yanchor": "bottom",
                "xshift": xshift,
                "yshift": yshift,
                "dist_px": dist_px,
                "dir_idx": 99,
                "box": _ciclo_label_bbox(lx, ly, 0.30, 0.10, "center", "bottom"),
            }

        dist_px = int(resolved.pop("dist_px", 10))
        resolved.pop("dir_idx", None)
        box = resolved.pop("box")
        resolved["showarrow"] = dist_px >= _CICLO_ARROW_MIN_PX
        placed_boxes.append(box)
        layouts.append(resolved)

    return layouts


def _text_anchor_offset(pos: str) -> tuple[float, float]:
    """Offset normalizado aproximado do rótulo em relação ao ponto."""
    return {
        "top center": (0.0, 0.18),
        "bottom center": (0.0, -0.18),
        "middle right": (0.18, 0.0),
        "middle left": (-0.18, 0.0),
        "top left": (-0.14, 0.16),
        "top right": (0.14, 0.16),
        "bottom left": (-0.14, -0.16),
        "bottom right": (0.14, -0.16),
    }.get(pos, (0.0, 0.16))


def _scatter_ciclo_label_coords(
    xs: list[float],
    ys: list[float],
    positions: list[str],
    x_range: tuple[float, float],
    y_range: tuple[float, float],
) -> tuple[list[float], list[float], list[str]]:
    """Desloca rótulos em coordenadas de dados — texto ao lado/acima/abaixo do ponto."""
    x_lo, x_hi = x_range
    y_lo, y_hi = y_range
    x_span = max(x_hi - x_lo, 1e-9)
    y_span = max(y_hi - y_lo, 1e-9)
    ox = x_span * 0.034
    oy = y_span * 0.046

    tx: list[float] = []
    ty: list[float] = []
    tpos: list[str] = []
    for x, y, pos in zip(xs, ys, positions):
        xf, yf = float(x), float(y)
        if pos == "top center":
            tx.append(xf); ty.append(yf + oy); tpos.append("bottom center")
        elif pos == "bottom center":
            tx.append(xf); ty.append(yf - oy); tpos.append("top center")
        elif pos == "middle right":
            tx.append(xf + ox); ty.append(yf); tpos.append("middle left")
        elif pos == "middle left":
            tx.append(xf - ox); ty.append(yf); tpos.append("middle right")
        elif pos == "top left":
            tx.append(xf - ox * 0.9); ty.append(yf + oy); tpos.append("bottom right")
        elif pos == "top right":
            tx.append(xf + ox * 0.9); ty.append(yf + oy); tpos.append("bottom left")
        elif pos == "bottom left":
            tx.append(xf - ox * 0.9); ty.append(yf - oy); tpos.append("top right")
        elif pos == "bottom right":
            tx.append(xf + ox * 0.9); ty.append(yf - oy); tpos.append("top left")
        else:
            tx.append(xf); ty.append(yf + oy); tpos.append("bottom center")
    return tx, ty, tpos


def _scatter_norm_xy(
    x: float,
    y: float,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
) -> tuple[float, float]:
    """Normaliza coordenadas do ponto para 0–1 dentro do range visível do eixo."""
    x_lo, x_hi = x_range
    y_lo, y_hi = y_range
    x_span = x_hi - x_lo if x_hi > x_lo else 1.0
    y_span = y_hi - y_lo if y_hi > y_lo else 1.0
    return (float(x) - x_lo) / x_span, (float(y) - y_lo) / y_span


def _scatter_adaptive_textpositions(
    xs: list[float],
    ys: list[float],
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    avg_y: float | None = None,
) -> list[str]:
    """Posição adaptativa dos rótulos — bordas, sobreposição e linha de média."""
    if not xs:
        return []

    y_lo, y_hi = y_range
    y_span = y_hi - y_lo if y_hi > y_lo else max(abs(y_hi), 1.0)
    avg_ny: float | None = None
    if avg_y is not None and not pd.isna(avg_y):
        avg_ny = (float(avg_y) - y_lo) / y_span

    pos_cycle = [
        "middle right", "middle left",
        "top left", "top right", "bottom left", "bottom right",
        "top center", "bottom center",
    ]
    positions: list[str] = []
    used_anchors: list[tuple[float, float]] = []

    for x, y in zip(xs, ys):
        nx, ny = _scatter_norm_xy(x, y, x_range, y_range)

        if nx > 0.72:
            candidates = ["middle left", "top left", "bottom left", "bottom center"]
        elif nx < 0.28:
            candidates = ["middle right", "top right", "bottom right", "bottom center"]
        elif ny > 0.72:
            candidates = ["bottom center", "bottom left", "bottom right", "middle left", "middle right"]
        elif ny < 0.28:
            candidates = ["top center", "top left", "top right", "middle left", "middle right"]
        else:
            candidates = list(pos_cycle)

        if avg_ny is not None and abs(ny - avg_ny) < 0.12:
            if ny <= avg_ny:
                preferred = ["top center", "top left", "top right", "middle right", "middle left"]
            else:
                preferred = ["bottom center", "bottom left", "bottom right", "middle right", "middle left"]
            candidates = preferred + [c for c in candidates if c not in preferred]

        best = candidates[0]
        best_score = -999.0
        for cand in candidates:
            ax, ay = _text_anchor_offset(cand)
            lx, ly = nx + ax, ny + ay

            score = 0.0
            if lx < 0.06:
                score -= (0.06 - lx) * 120
            elif lx > 0.94:
                score -= (lx - 0.94) * 120
            if ly < 0.06:
                score -= (0.06 - ly) * 120
            elif ly > 0.94:
                score -= (ly - 0.94) * 120

            if used_anchors:
                min_dist = min(
                    ((lx - ux) ** 2 + (ly - uy) ** 2) ** 0.5
                    for ux, uy in used_anchors
                )
                score += min_dist * 80
            else:
                score += 1.0

            if avg_ny is not None:
                line_penalty = max(0.0, 0.14 - abs(ny - avg_ny)) * 40
                if cand in ("top center", "bottom center") and line_penalty > 0:
                    score -= line_penalty
                if cand in ("middle left", "middle right"):
                    score += 8

            if cand in ("top center", "bottom center"):
                score -= 5

            if score > best_score:
                best_score = score
                best = cand

        positions.append(best)
        ax, ay = _text_anchor_offset(best)
        used_anchors.append((nx + ax, ny + ay))

    return positions


def _scatter_ciclo_label_metrics(
    x_val: float,
    y_val: float,
    *,
    x_is_percent: bool = False,
) -> str:
    """Parte fixa do rótulo: vendas/% + dias (sempre exibida no gráfico)."""
    y_d = format_chart_label(float(y_val), "days")
    if x_is_percent:
        return f"{pct(float(x_val), casas=1)} / {y_d}"
    x_n = int(float(x_val) + 0.5)
    return f"{int_br(x_n)} vendas / {y_d}"


def _scatter_ciclo_format_label(
    name: str,
    metrics: str,
    *,
    two_lines: bool = False,
) -> str:
    """Monta rótulo do scatter — nome + métricas; quebra linha se necessário."""
    safe_name = " ".join(str(name or "").split())
    if not metrics:
        return safe_name
    if two_lines:
        return f"{safe_name}<br>{metrics}"
    return f"{safe_name} — {metrics}"


def _scatter_ciclo_detect_crowded_indices(
    xs: list[float],
    ys: list[float],
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    proximity: float = 0.11,
) -> set[int]:
    """Índices de pontos com vizinho muito próximo no plano normalizado."""
    crowded: set[int] = set()
    n = len(xs)
    for i in range(n):
        for j in range(i + 1, n):
            xi, yi = _scatter_norm_xy(xs[i], ys[i], x_range, y_range)
            xj, yj = _scatter_norm_xy(xs[j], ys[j], x_range, y_range)
            if ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5 < proximity:
                crowded.add(i)
                crowded.add(j)
    return crowded


def _scatter_ciclo_separate_close_pairs(
    positions: list[str],
    xs: list[float],
    ys: list[float],
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    proximity: float = 0.11,
) -> list[str]:
    """Para pares próximos, alterna posição (acima/abaixo ou esquerda/direita)."""
    out = list(positions)
    n = len(xs)
    for i in range(n):
        for j in range(i + 1, n):
            xi, yi = _scatter_norm_xy(xs[i], ys[i], x_range, y_range)
            xj, yj = _scatter_norm_xy(xs[j], ys[j], x_range, y_range)
            if ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5 >= proximity:
                continue
            if abs(yi - yj) <= abs(xi - xj) * 0.85:
                out[i] = "top center"
                out[j] = "bottom center"
            else:
                out[i] = "middle left"
                out[j] = "middle right"
    return out


def _scatter_ciclo_build_labels(
    df: pd.DataFrame,
    label_col: str,
    x_col: str,
    y_col: str,
    *,
    x_is_percent: bool = False,
    crowded_indices: set[int] | None = None,
) -> list[str]:
    """Rótulos do scatter — nome + métricas; em aglomerados, nome curto + quebra."""
    crowded = crowded_indices or set()
    labels: list[str] = []
    for pos, (_, row) in enumerate(df.iterrows()):
        full_name = str(row[label_col]).strip()
        name = _short_display_name(full_name, max_tokens=2, max_len=26)
        metrics = _scatter_ciclo_label_metrics(
            float(row[x_col]), float(row[y_col]), x_is_percent=x_is_percent,
        )
        if pos in crowded:
            labels.append(_scatter_ciclo_format_label(name, metrics, two_lines=True))
        else:
            labels.append(_scatter_ciclo_format_label(name, metrics, two_lines=False))
    return labels


def _format_scatter_hover_value(col: str, val) -> str:
    """Formata um valor do hover do scatter conforme o tipo da coluna."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    try:
        if pd.isna(val):
            return "—"
    except (TypeError, ValueError):
        pass

    col_s = str(col).lower()

    if any(k in col_s for k in (
        "nome", "closer", "executiva", "time", "funil", "canal",
        "classificacao", "segmento",
    )):
        s = str(val).strip()
        return s if s else "—"

    if "pct" in col_s or "percentual" in col_s or "%" in str(col):
        num = pd.to_numeric(val, errors="coerce")
        if pd.isna(num):
            return "—"
        return pct(float(num), casas=1)

    if any(k in col_s for k in ("vendas", "quantidade", "qtd", "n_ciclo", "n_")):
        num = pd.to_numeric(val, errors="coerce")
        if pd.isna(num):
            return "—"
        return int_br(int(float(num) + 0.5))

    if "medio_dias" in col_s or col_s.endswith("_dias"):
        num = pd.to_numeric(val, errors="coerce")
        if pd.isna(num):
            return "—"
        return format_days_display(float(num))

    num = pd.to_numeric(val, errors="coerce")
    if not pd.isna(num):
        return str(num)
    s = str(val).strip()
    return s if s else "—"


def _scatter_ciclo_point_labels(
    df: pd.DataFrame,
    label_col: str,
    x_col: str,
    y_col: str,
    *,
    x_is_percent: bool = False,
    crowded_indices: set[int] | None = None,
    max_with_value: int = 6,
) -> list[str]:
    """Rótulos do scatter: nome + métricas; legado — use _scatter_ciclo_build_labels."""
    _ = max_with_value
    return _scatter_ciclo_build_labels(
        df, label_col, x_col, y_col,
        x_is_percent=x_is_percent,
        crowded_indices=crowded_indices,
    )


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
         unified: bool = True,
         show_value_labels: bool = False) -> go.Figure:
    fig = px.line(df, x=x, y=y, markers=True)
    fig.update_traces(line=dict(width=2.5), marker=dict(size=6))
    y_list = [y] if isinstance(y, str) else list(y)
    if show_value_labels:
        for i, col in enumerate(y_list):
            if col not in df.columns:
                continue
            fmt: ChartLabelFormat = (
                "money" if money_axis == "y" and col in ("receita", "montante")
                else "integer"
            )
            texts = annotate_adaptive(
                df[col].tolist(),
                formatter=lambda v, f=fmt: format_chart_label(v, f),
            )
            fig.data[i].update(
                mode="lines+markers+text",
                text=texts,
                textposition="top center",
                textfont=dict(size=9, color=PALETTE["text_subtle"], family="Inter"),
            )
        top_margin = 40
    else:
        top_margin = 20
    fig.update_layout(**_base_layout(height=height, unified=unified))
    fig.update_layout(margin=dict(l=12, r=12, t=top_margin, b=12))
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

def _coerce_plot_value_column(df: pd.DataFrame, value: str) -> pd.DataFrame:
    """Converte coluna de métrica para float; remove inf/NaN antes de ranquear."""
    df_plot = df.copy()
    if value not in df_plot.columns:
        return df_plot.iloc[0:0]
    ser = df_plot[value]
    if ser.dtype == object:
        ser = (
            ser.astype(str)
            .str.replace("dias", "", regex=False)
            .str.strip()
            .str.replace(",", ".", regex=False)
        )
    df_plot[value] = pd.to_numeric(ser, errors="coerce")
    df_plot[value] = df_plot[value].replace([np.inf, -np.inf], np.nan)
    return df_plot.dropna(subset=[value])


def bar_ranked(df: pd.DataFrame, category: str, value: str,
               top_n: int = 15, money: bool = False,
               days_format: bool = False,
               percent_format: bool = False,
               value_format: ChartLabelFormat | None = None,
               lower_is_better: bool = False,
               height: int | None = None,
               label_max_len: int = 26,
               metric_label: str | None = None,
               cost_col: str | None = None,
               cost_label: str | None = None,
               show_cost_on_bar: bool = False,
               avg_cost_display: str | None = None) -> go.Figure:
    h_default = height or 260
    df_plot = _coerce_plot_value_column(df, value) if df is not None else pd.DataFrame()
    if df_plot.empty or category not in df_plot.columns:
        fig = go.Figure()
        fig.update_layout(**_base_layout(height=h_default))
        _style_axes(fig)
        return fig

    if lower_is_better:
        data = df_plot.nsmallest(top_n, value).sort_values(value, ascending=True)
    else:
        data = df_plot.nlargest(top_n, value).sort_values(value, ascending=True)
    h = height or max(260, 26 * len(data) + 60)

    lbl_fmt = _resolve_label_format(
        money=money,
        days_format=days_format,
        percent_format=percent_format,
        value_format=value_format,
    )
    vals = data[value].astype(float).tolist()
    text_positions = _bar_h_text_positions(vals)

    if (show_cost_on_bar and cost_col and cost_col in data.columns):
        text_vals = [
            (
                f"{format_chart_label(v, lbl_fmt)} ({c})"
                if str(c).strip() and str(c).strip() != "—"
                else format_chart_label(v, lbl_fmt)
            )
            for v, c in zip(data[value], data[cost_col])
        ]
        bar_text_size = 10
    else:
        text_vals = [format_chart_label(v, lbl_fmt) for v in data[value]]
        bar_text_size = 11
    full_labels = data[category].astype(str)
    y_labels = full_labels.apply(lambda s: _truncate(s, label_max_len))

    # Cor do texto INTERNO acompanha a luminosidade da barra (mesmo colorscale):
    # barras douradas (norm >= 0.75) -> preto;  barras vinho/escuras -> branco.
    vmin, vmax = (min(vals), max(vals)) if vals else (0.0, 0.0)
    if vmax > vmin:
        norm = [(v - vmin) / (vmax - vmin) for v in vals]
    else:
        norm = [0.0] * len(vals)
    inside_text_colors = ["#1a1410" if n >= 0.75 else "#ffffff" for n in norm]

    if cost_col and cost_col in data.columns and cost_label:
        metric_name = metric_label or value
        if avg_cost_display is not None:
            customdata = list(zip(
                full_labels.tolist(),
                [avg_cost_display] * len(data),
                data[cost_col].astype(str).tolist(),
            ))
            hovertemplate = (
                f"<b>%{{customdata[0]}}</b><br>"
                f"{metric_name}: %{{x:,.0f}}<br>"
                f"{cost_label}: %{{customdata[1]}}<br>"
                f"Investimento estimado: %{{customdata[2]}}"
                f"<extra></extra>"
            )
        else:
            customdata = list(zip(
                full_labels.tolist(),
                data[cost_col].astype(str).tolist(),
            ))
            hovertemplate = (
                f"<b>%{{customdata[0]}}</b><br>"
                f"{metric_name}: %{{x:,.0f}}<br>"
                f"{cost_label}: %{{customdata[1]}}"
                f"<extra></extra>"
            )
    else:
        customdata = list(zip(
            full_labels.tolist(),
            text_vals,
        ))
        hovertemplate = (
            "<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"
        )

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
        textposition=text_positions,
        insidetextanchor="end",
        insidetextfont=dict(color=inside_text_colors, size=bar_text_size, family="Inter"),
        outsidetextfont=dict(color=PALETTE["text"], size=bar_text_size, family="Inter"),
        cliponaxis=False,
        customdata=customdata,
        hovertemplate=hovertemplate,
    ))
    x_pad = vmax * 1.22 if vmax > 0 else 1.0
    fig.update_layout(**_base_layout(height=h))
    fig.update_layout(
        showlegend=False,
        margin=dict(l=12, r=88, t=28, b=12),
        bargap=0.32,
        xaxis=dict(range=[0, x_pad]),
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


def bar_qualif_pre_split(
    df: pd.DataFrame,
    *,
    height: int = 280,
    pct_mode: str = "share",
) -> go.Figure:
    """Barras Com Pré vs Não Qualif. com rótulo `valor (percentual)`.

    pct_mode:
      - ``share``: percentual do total do gráfico (agendamentos)
      - ``avanco``: taxa comparecimentos ÷ agendamentos da dimensão
    """
    data = df.copy()
    ymax = float(data["valor"].max() or 1)
    labels: list[str] = []
    positions: list[str] = []
    colors = [PALETTE["gold_bright"], PALETTE["wine_light"]]
    for _, row in data.iterrows():
        v = int(row["valor"] or 0)
        p = float(row["pct_total"] or 0)
        pct_s = f"{p:.1f}".replace(".", ",") + "%"
        labels.append(f"<b>{int_br(v)} ({pct_s})</b>")
        positions.append("inside" if v >= ymax * 0.18 else "outside")

    fig = go.Figure(go.Bar(
        x=data["tipo"].astype(str),
        y=data["valor"],
        text=labels,
        textposition=positions,
        insidetextfont=dict(color="#1a1410", size=13, family="Inter"),
        outsidetextfont=dict(color=PALETTE["text"], size=13, family="Inter"),
        cliponaxis=False,
        marker=dict(
            color=colors[: len(data)],
            line=dict(color=PALETTE["border_strong"], width=0.5),
        ),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "%{y:,.0f} · %{customdata}<extra></extra>"
        ),
        customdata=[
            (
                f"{float(p):.1f}% comp. sobre agend.".replace(".", ",")
                if pct_mode == "avanco"
                else f"{float(p):.1f}% do total".replace(".", ",")
            )
            for p in data["pct_total"]
        ],
    ))
    fig.update_layout(**_base_layout(height=height))
    fig.update_layout(
        showlegend=False,
        margin=dict(l=12, r=12, t=32, b=48),
    )
    fig.update_yaxes(range=[0, ymax * 1.14])
    _style_axes(fig)
    return fig


def bar_simple(df: pd.DataFrame, x: str, y: str,
               height: int = 280, money: bool = False,
               days_format: bool = False,
               percent_format: bool = False,
               value_format: ChartLabelFormat | None = None,
               rotate_x: bool = False,
               x_title: str | None = None,
               y_title: str | None = None) -> go.Figure:
    lbl_fmt = _resolve_label_format(
        money=money,
        days_format=days_format,
        percent_format=percent_format,
        value_format=value_format,
    )
    y_vals = pd.to_numeric(df[y], errors="coerce").fillna(0)
    ymax = float(y_vals.max() or 1)
    labels = [format_chart_label(float(v), lbl_fmt) for v in y_vals]
    positions = _bar_v_text_positions(y_vals.tolist())

    fig = go.Figure(go.Bar(
        x=df[x].astype(str),
        y=y_vals,
        marker=dict(
            color=PALETTE["gold"],
            line=dict(color=PALETTE["border_strong"], width=0.5),
        ),
        text=labels,
        textposition=positions,
        insidetextfont=dict(color="#1a1410", size=11, family="Inter"),
        outsidetextfont=dict(color=PALETTE["text"], size=11, family="Inter"),
        cliponaxis=False,
        customdata=labels,
        hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(height=height))
    fig.update_layout(
        showlegend=False,
        margin=dict(l=48, r=24, t=36, b=56 if rotate_x else 24),
    )
    fig.update_yaxes(range=[0, ymax * 1.18])
    if rotate_x:
        fig.update_xaxes(tickangle=-30)
    if x_title:
        fig.update_xaxes(title=x_title)
    if y_title:
        fig.update_yaxes(title=y_title)
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
        marker=dict(colors=_seq_colors(), line=dict(color=PALETTE["bg"], width=2)),
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
           show_dropoff: bool = False, pct_casas: int = 1) -> go.Figure:
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
                    f"↓ {pct(drop, casas=pct_casas)} queda"
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
# Scatter — tempo de ciclo × volume de vendas
# ---------------------------------------------------------------------------

def scatter_ciclo_venda(
    df: pd.DataFrame,
    x_col: str = "x_valor",
    y_col: str = "y_valor",
    label_col: str = "executiva",
    avg_y: float | None = None,
    x_title: str = "Quantidade de vendas",
    y_title: str = "Tempo médio (dias)",
    height: int = 420,
    x_is_percent: bool = False,
    max_labels_with_value: int = 6,
) -> go.Figure:
    """Scatter XY: volume (X) × tempo médio de fechamento (Y), 1 ponto por closer."""
    fig = go.Figure()
    if df is None or df.empty:
        fig.update_layout(**_base_layout(height=height), showlegend=False)
        _style_axes(fig)
        return fig

    df_plot = df.copy()
    for col in (x_col, y_col):
        if col in df_plot.columns:
            ser = df_plot[col]
            if ser.dtype == object:
                ser = (
                    ser.astype(str)
                    .str.replace("dias", "", regex=False)
                    .str.strip()
                    .str.replace(",", ".", regex=False)
                )
            df_plot[col] = pd.to_numeric(ser, errors="coerce")
    df_plot = df_plot.replace([np.inf, -np.inf], np.nan).dropna(subset=[x_col, y_col])
    if df_plot.empty:
        fig.update_layout(**_base_layout(height=height), showlegend=False)
        _style_axes(fig)
        return fig

    n_pts = len(df_plot)
    xs = df_plot[x_col].astype(float).tolist()
    ys = df_plot[y_col].astype(float).tolist()

    x_min = float(df_plot[x_col].min())
    x_max = float(df_plot[x_col].max())
    y_min = 0.0
    y_max = float(df_plot[y_col].max())
    x_span = x_max - x_min if x_max > x_min else max(abs(x_max), 1.0)
    y_span = y_max - y_min if y_max > y_min else max(abs(y_max), 1.0)
    x_pad = x_span * 0.20
    y_pad = y_span * 0.28
    x_range = (x_min - x_pad, x_max + x_pad)
    y_range = (max(0.0, y_min - y_pad * 0.10), y_max + y_pad)

    label_parts = _scatter_ciclo_prepare_label_parts(
        df_plot, label_col, x_col, y_col, x_is_percent=x_is_percent,
    )
    label_layouts = _scatter_ciclo_layout_annotations(
        xs, ys, label_parts,
        x_range=x_range,
        y_range=y_range,
        avg_y=avg_y,
        chart_height=height,
    )
    text_size = 10 if n_pts <= 6 else (9 if n_pts <= 10 else 8)
    marker_size = 7 if n_pts <= 8 else 6

    col_map = {
        "time_vendas": "Time",
        "vendas_ciclo": "Vendas",
        "pct_vendas_ciclo": "% vendas",
        "ciclo_entrada_medio_dias": "Entrada → ganho",
        "ciclo_call_medio_dias": "Call → ganho",
    }
    extra_cols = [c for c in col_map if c in df_plot.columns]
    custom_rows: list[list[str]] = []
    for _, row in df_plot.iterrows():
        row_data = [_format_scatter_hover_value(label_col, row[label_col])]
        for src in extra_cols:
            row_data.append(_format_scatter_hover_value(src, row[src]))
        custom_rows.append(row_data)

    hover_parts = ["<b>%{customdata[0]}</b>"]
    for i, src in enumerate(extra_cols, start=1):
        hover_parts.append(f"{col_map[src]}: %{{customdata[{i}]}}")
    hovertemplate = "<br>".join(hover_parts) + "<extra></extra>"

    if avg_y is not None and not pd.isna(avg_y):
        fig.add_hline(
            y=float(avg_y),
            line=dict(color=PALETTE["wine_light"], dash="dash", width=1.5),
            layer="below",
            annotation_text=f"Média geral: {format_chart_label(avg_y, 'days')}",
            annotation_font=dict(color=PALETTE["text_subtle"], size=11),
            annotation_position="top left",
        )

    fig.add_trace(go.Scatter(
        x=df_plot[x_col],
        y=df_plot[y_col],
        mode="markers",
        name="",
        showlegend=False,
        marker=dict(
            size=marker_size,
            color=PALETTE["card"],
            line=dict(width=1.4, color=PALETTE["gold"]),
            opacity=0.88,
        ),
        customdata=custom_rows,
        hovertemplate=hovertemplate,
        cliponaxis=False,
    ))

    for spec in label_layouts:
        ann_kwargs = dict(
            x=spec["x"],
            y=spec["y"],
            text=spec["text"],
            showarrow=spec.get("showarrow", False),
            xref="x",
            yref="y",
            xanchor=spec["xanchor"],
            yanchor=spec["yanchor"],
            xshift=spec["xshift"],
            yshift=spec["yshift"],
            font=dict(size=text_size, color=PALETTE["text"], family="Inter"),
            bgcolor="rgba(22, 19, 17, 0.72)",
            borderpad=3,
            opacity=0.98,
        )
        if spec.get("showarrow"):
            ann_kwargs.update(
                ax=spec["x"],
                ay=spec["y"],
                arrowhead=2,
                arrowsize=0.65,
                arrowwidth=0.8,
                arrowcolor=PALETTE["text_subtle"],
            )
        fig.add_annotation(**ann_kwargs)

    layout = _base_layout(height=height)
    layout["margin"] = dict(l=60, r=148, t=64, b=48)
    fig.update_layout(
        **layout,
        showlegend=False,
        xaxis=dict(
            title=x_title,
            range=list(x_range),
        ),
        yaxis=dict(
            title=y_title,
            range=list(y_range),
        ),
    )
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
