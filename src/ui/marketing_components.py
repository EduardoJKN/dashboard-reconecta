"""Componentes reutilizáveis das páginas de Marketing.

`render_funil_selecionado` encapsula o bloco "Funil do {entidade}
selecionado(a)" — selectbox + 6 mini-cards + esteira Mídia → Funil de
Marketing (Leads → Agendamentos → Comparecimentos → Vendas), com dados
de aplicações acoplados ao bloco de Leads.
"""
from __future__ import annotations

import html as html_lib
from datetime import date
from typing import Callable

import pandas as pd
import streamlit as st

from src.marketing_queries import get_mkt_funil_leads_auditoria
from src.ui.components import metric_card_v2, section_title
from src.ui.theme import PALETTE, brl, int_br, pct


def _fmt_value(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".", ",")
    if v >= 100_000:
        return f"{v / 1_000:.0f}K"
    return int_br(int(v))


def _track_funnel_inner_layout() -> str:
    """Linha principal do funil — etapas distribuídas com gap moderado."""
    return (
        "display:flex;align-items:flex-start;justify-content:space-evenly;"
        "gap:6px;width:100%;flex-wrap:nowrap;padding:4px 0 2px;"
    )


def _track_step_flex() -> str:
    return "flex:1 1 0;min-width:58px;max-width:108px;"


def _funil_aplicacoes_leads_subline(kf: dict) -> str:
    """Linha única de aplicações dentro do bloco Leads."""
    leads = int(kf.get("leads_totais") or 0)
    apl = int(kf.get("aplicacoes") or 0)
    pct_apl = pct((apl / leads) * 100, casas=1) if leads > 0 else "—"
    return f"Aplicações: {int_br(apl)} · {pct_apl}"


def _funil_aplicacoes_summary_pills(kf: dict) -> list[str]:
    """Pílulas acopladas à base do card Funil de Marketing."""
    inv = float(kf.get("investimento") or 0)
    apl = int(kf.get("aplicacoes") or 0)
    apl12 = int(kf.get("aplicacoes_mais_12") or 0)
    apl_menos = int(kf.get("aplicacoes_menos_12") or 0)
    cpa = brl(inv / apl, casas=2) if apl > 0 else "—"
    cpa12 = brl(inv / apl12, casas=2) if apl12 > 0 else "—"
    return [
        f"Apl. +12: {int_br(apl12)}",
        f"Apl. -12: {int_br(apl_menos)}",
        f"CPA: {cpa}",
        f"CPA +12: {cpa12}",
    ]


def _aplicacoes_context_html(kf: dict, *, compact: bool = False) -> str:
    """Legenda de aplicações abaixo do número de Leads (apenas total + %)."""
    subline = _funil_aplicacoes_leads_subline(kf)
    fs = "0.58em" if compact else "0.62em"
    mt = "4px" if compact else "5px"
    return (
        f'<div style="font-size:{fs};color:{PALETTE["text_subtle"]};'
        f'margin-top:{mt};font-variant-numeric:tabular-nums;'
        f'text-align:center;width:100%;line-height:1.3;">'
        f'{html_lib.escape(subline)}</div>'
    )


def _funnel_summary_pills_html(items: list[str]) -> str:
    """Linha inferior discreta — métricas auxiliares em pílulas."""
    if not items:
        return ""
    pill_bg = PALETTE.get("bg_soft", PALETTE["card"])
    pills: list[str] = []
    for item in items:
        pills.append(
            f'<span style="display:inline-block;font-size:0.62em;'
            f'color:{PALETTE["text_subtle"]};background:{pill_bg};'
            f'border:1px solid {PALETTE["border"]};border-radius:999px;'
            f'padding:3px 9px;line-height:1.25;'
            f'font-variant-numeric:tabular-nums;white-space:nowrap;">'
            f'{html_lib.escape(item)}</span>'
        )
    return (
        f'<div style="display:flex;flex-wrap:wrap;gap:5px 6px;'
        f'margin-top:7px;padding-top:6px;'
        f'border-top:1px solid {PALETTE["border"]};'
        f'justify-content:flex-start;align-items:center;">'
        f'{"".join(pills)}</div>'
    )


def _step_html(label: str, value: float,
               bucket_topo: float,
               is_bucket_topo: bool,
               bucket_topo_label: str,
               *, compact: bool = False) -> str:
    value_fmt = _fmt_value(value)
    pct_bt = (value / bucket_topo) * 100 if bucket_topo > 0 else 0
    pct_bt_fmt = (
        f"{pct_bt:.1f}% de {bucket_topo_label}".replace(".", ",")
    )
    sub_html = (
        f'<div style="font-size:0.58em;color:{PALETTE["muted"]};'
        f'margin-top:1px;">topo do grupo</div>'
        if is_bucket_topo else
        f'<div style="font-size:0.58em;color:{PALETTE["text_subtle"]};'
        f'margin-top:1px;font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(pct_bt_fmt)}</div>'
    ) if compact else (
        f'<div style="font-size:0.66em;color:{PALETTE["muted"]};'
        f'margin-top:2px;">topo do grupo</div>'
        if is_bucket_topo else
        f'<div style="font-size:0.66em;color:{PALETTE["text_subtle"]};'
        f'margin-top:2px;font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(pct_bt_fmt)}</div>'
    )
    step_flex = _track_step_flex() if compact else "min-width:78px;"
    pad = "4px 2px" if compact else "6px 4px"
    val_fs = "1.02em" if compact else "1.15em"
    lbl_fs = "0.58em" if compact else "0.6em"
    lbl_mb = "2px" if compact else "4px"
    lbl_min_h = "" if compact else "min-height:1.2em;"
    lbl_lh = "1.05" if compact else "1.1"
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;'
        f'{step_flex}padding:{pad};text-align:center;">'
        f'<div style="font-size:{lbl_fs};color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.04em;'
        f'font-weight:600;line-height:{lbl_lh};margin-bottom:{lbl_mb};'
        f'{lbl_min_h}">'
        f'{html_lib.escape(label)}</div>'
        f'<div style="font-size:{val_fs};font-weight:700;'
        f'color:{PALETTE["text"]};line-height:1.05;'
        f'font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(value_fmt)}</div>'
        f'{sub_html}'
        f'</div>'
    )


def _arrow_html(prev_value: float, value: float,
                emphatic: bool = False,
                *, compact: bool = False) -> str:
    if prev_value > 0:
        pct_step = (value / prev_value) * 100
        pct_step_fmt = f"{pct_step:.1f}%".replace(".", ",")
    else:
        pct_step_fmt = "—"
    color = PALETTE["wine_light"] if emphatic else PALETTE["text_subtle"]
    arrow_size = "1.05em" if compact else ("1.2em" if emphatic else "1.05em")
    mw = "8px" if compact else "50px"
    pad = "0" if compact else "0 1px"
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;'
        f'padding:{pad};min-width:{mw};flex:0 0 {mw};">'
        f'<div style="font-size:{arrow_size};color:{color};'
        f'line-height:1;">→</div>'
        f'<div style="font-size:0.58em;color:{color};'
        f'margin-top:1px;font-variant-numeric:tabular-nums;'
        f'font-weight:600;">{html_lib.escape(pct_step_fmt)}</div>'
        f'</div>'
    )


def _bucket_html(bucket_label: str, indices: list[int],
                 labels_f: list[str], values_f: list[float],
                 *, full_width: bool = True, compact: bool = False) -> str:
    bt_idx = indices[0]
    bt_val = values_f[bt_idx] if values_f[bt_idx] > 0 else 1.0
    bt_label = labels_f[bt_idx].lower()
    inner: list[str] = []
    for n, i in enumerate(indices):
        if n > 0:
            inner.append(_arrow_html(values_f[i - 1], values_f[i], compact=compact))
        inner.append(
            _step_html(
                labels_f[i], values_f[i],
                bucket_topo=bt_val,
                is_bucket_topo=(n == 0),
                bucket_topo_label=bt_label,
                compact=compact,
            )
        )
    if compact:
        size_css = "width:100%;"
        pad = "8px 10px 6px"
        title_mb = "4px"
        radius = "8px"
        inner_layout = _track_funnel_inner_layout()
    else:
        size_css = "flex:1;" if full_width else "width:100%;min-width:168px;"
        pad = "8px 10px"
        title_mb = "6px"
        radius = "10px"
        inner_layout = (
            "display:flex;align-items:stretch;"
            "justify-content:space-between;flex-wrap:nowrap;"
        )
    return (
        f'<div style="{size_css}display:flex;flex-direction:column;'
        f'background:{PALETTE["card"]};'
        f'border:1px solid {PALETTE["border"]};border-radius:{radius};'
        f'padding:{pad};box-sizing:border-box;">'
        f'<div style="font-size:0.58em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.07em;'
        f'font-weight:600;margin-bottom:{title_mb};line-height:1;">'
        f'{html_lib.escape(bucket_label)}</div>'
        f'<div style="{inner_layout}">'
        f'{"".join(inner)}'
        f'</div>'
        f'</div>'
    )


def _arrow_simple_html(*, compact: bool = False) -> str:
    """Seta entre etapas — sem % etapa-a-etapa (leitura principal = % da base)."""
    color = PALETTE["text_subtle"]
    mw = "12px" if compact else "28px"
    fs = "1em" if compact else "1.05em"
    return (
        f'<div style="display:flex;align-items:center;justify-content:center;'
        f'padding:0 2px;min-width:{mw};flex:0 0 {mw};align-self:center;">'
        f'<div style="font-size:{fs};color:{color};line-height:1;">→</div>'
        f'</div>'
    )


def _step_leads_base_html(
    label: str,
    value: float,
    kf: dict,
    *,
    compact: bool = False,
) -> str:
    """Etapa Leads — total + contexto de aplicações acoplado."""
    value_fmt = _fmt_value(value)
    step_flex = (
        "flex:1.35 1 0;min-width:88px;max-width:148px;"
        if compact else "min-width:120px;max-width:160px;"
    )
    pad = "4px 3px" if compact else "6px 4px"
    lbl_mb = "4px" if compact else "4px"
    val_fs = "1.1em" if compact else "1.15em"
    ctx_html = _aplicacoes_context_html(kf, compact=compact)
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:flex-start;'
        f'{step_flex}padding:{pad};text-align:center;">'
        f'<div style="font-size:0.6em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.04em;'
        f'font-weight:600;line-height:1.15;margin-bottom:{lbl_mb};'
        f'min-height:2.2em;display:flex;align-items:flex-end;'
        f'justify-content:center;">'
        f'{html_lib.escape(label)}</div>'
        f'<div style="font-size:{val_fs};font-weight:700;'
        f'color:{PALETTE["text"]};line-height:1.1;'
        f'font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(value_fmt)}</div>'
        f'{ctx_html}'
        f'</div>'
    )


def _step_track_base_html(
    label: str,
    value: float,
    *,
    compact: bool = False,
) -> str:
    """Etapa base da trilha — título + número (sem subinfo na linha principal)."""
    value_fmt = _fmt_value(value)
    step_flex = _track_step_flex() if compact else "min-width:88px;"
    pad = "4px 2px" if compact else "6px 4px"
    lbl_mb = "4px" if compact else "4px"
    val_fs = "1.1em" if compact else "1.15em"
    sub_spacer = (
        '<div style="min-height:15px;margin-top:3px;"></div>'
        if compact else
        '<div style="min-height:18px;margin-top:3px;"></div>'
    )
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:flex-start;'
        f'{step_flex}padding:{pad};text-align:center;">'
        f'<div style="font-size:0.6em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.04em;'
        f'font-weight:600;line-height:1.15;margin-bottom:{lbl_mb};'
        f'min-height:2.2em;display:flex;align-items:flex-end;'
        f'justify-content:center;">'
        f'{html_lib.escape(label)}</div>'
        f'<div style="font-size:{val_fs};font-weight:700;'
        f'color:{PALETTE["text"]};line-height:1.1;'
        f'font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(value_fmt)}</div>'
        f'{sub_spacer}'
        f'</div>'
    )


def _step_conv_subline_html(
    step: dict,
    base_value: float,
    base_noun: str,
) -> str:
    """Subtítulo de conversão — taxa única ou decomposição período/histórico."""
    if step.get("dual_decomp"):
        total = float(step.get("value") or 0)
        if total <= 0:
            return html_lib.escape("—")
        cp = int(step.get("count_periodo") or 0)
        ch = int(step.get("count_historico") or 0)
        pp = step.get("pct_periodo")
        ph = step.get("pct_historico")
        pps = pct(pp, casas=1) if pp is not None else "—"
        phs = pct(ph, casas=1) if ph is not None else "—"
        line1 = f"Período: {int_br(cp)} · {pps}"
        line2 = f"Histórico: {int_br(ch)} · {phs}"
        scope = step.get("decomp_scope", "agendamentos")
        if scope == "comparecimentos":
            tip = (
                "Dos comparecimentos no período: quantidade e % com lead "
                "criado no período vs. lead criado antes do período."
            )
        elif scope == "vendas":
            tip = (
                "Das vendas no período: quantidade e % com lead criado "
                "no período vs. lead criado antes do período."
            )
        elif "aplic" in base_noun:
            tip = (
                "Dos agendamentos de aplicações no período: quantidade e % "
                "com aplicação criada no período vs. aplicação anterior."
            )
        else:
            tip = (
                "Dos agendamentos no período: quantidade e % com lead criado "
                "no período vs. lead criado antes do período."
            )
        return (
            f'<div title="{html_lib.escape(tip)}">'
            f'{html_lib.escape(line1)}<br>{html_lib.escape(line2)}'
            f'</div>'
        )
    if base_value > 0:
        return html_lib.escape(
            f"{pct((float(step.get('value') or 0) / base_value) * 100, casas=1)} "
            f"de {base_noun}"
        )
    return html_lib.escape(f"— de {base_noun}")


def _step_conv_base_html(
    label: str,
    value: float,
    base_value: float,
    base_noun: str,
    *,
    step: dict | None = None,
    compact: bool = False,
) -> str:
    """Etapa downstream — total + % em relação à base da trilha (leads/aplicações)."""
    value_fmt = _fmt_value(value)
    step_ctx = step if step is not None else {"value": value}
    sub = _step_conv_subline_html(step_ctx, base_value, base_noun)
    step_flex = _track_step_flex() if compact else "min-width:88px;"
    pad = "4px 2px" if compact else "6px 4px"
    lbl_mb = "4px" if compact else "4px"
    val_fs = "1.1em" if compact else "1.15em"
    sub_mt = "3px" if compact else "3px"
    sub_fs = "0.62em" if compact else "0.62em"
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:flex-start;'
        f'{step_flex}padding:{pad};text-align:center;">'
        f'<div style="font-size:0.6em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.04em;'
        f'font-weight:600;line-height:1.15;margin-bottom:{lbl_mb};'
        f'min-height:2.2em;display:flex;align-items:flex-end;'
        f'justify-content:center;">'
        f'{html_lib.escape(label)}</div>'
        f'<div style="font-size:{val_fs};font-weight:700;'
        f'color:{PALETTE["text"]};line-height:1.1;'
        f'font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(value_fmt)}</div>'
        f'<div style="font-size:{sub_fs};color:{PALETTE["text_subtle"]};'
        f'margin-top:{sub_mt};font-variant-numeric:tabular-nums;'
        f'line-height:1.25;min-height:{"28px" if step_ctx.get("dual_decomp") else "15px"};">'
        f'{sub}</div>'
        f'</div>'
    )


def _funnel_track_bucket_html(
    bucket_label: str,
    steps: list[dict],
    *,
    base_noun: str,
    full_width: bool = True,
    compact: bool = False,
    summary_items: list[str] | None = None,
    kf: dict | None = None,
) -> str:
    """Bucket de trilha — linha principal + resumo auxiliar opcional abaixo."""
    base_value = float(steps[0]["value"]) if steps else 0.0
    inner: list[str] = []
    for i, step in enumerate(steps):
        if i > 0:
            inner.append(_arrow_simple_html(compact=compact))
        if step.get("is_base"):
            if kf is not None:
                inner.append(_step_leads_base_html(
                    step["label"],
                    float(step["value"]),
                    kf,
                    compact=compact,
                ))
            else:
                inner.append(_step_track_base_html(
                    step["label"],
                    float(step["value"]),
                    compact=compact,
                ))
        else:
            inner.append(_step_conv_base_html(
                step["label"],
                float(step["value"]),
                base_value,
                base_noun,
                step=step,
                compact=compact,
            ))
    summary_html = (
        _funnel_summary_pills_html(summary_items)
        if summary_items else ""
    )
    if compact:
        size_css = "width:100%;"
        pad = "8px 12px 7px"
        title_mb = "5px"
        radius = "8px"
        inner_layout = _track_funnel_inner_layout()
    else:
        size_css = "flex:1;" if full_width else "width:100%;min-width:168px;"
        pad = "8px 10px"
        title_mb = "6px"
        radius = "10px"
        inner_layout = (
            "display:flex;align-items:stretch;"
            "justify-content:space-between;flex-wrap:nowrap;"
        )
    return (
        f'<div style="{size_css}display:flex;flex-direction:column;'
        f'background:{PALETTE["card"]};'
        f'border:1px solid {PALETTE["border"]};border-radius:{radius};'
        f'padding:{pad};box-sizing:border-box;">'
        f'<div style="font-size:0.58em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.07em;'
        f'font-weight:600;margin-bottom:{title_mb};line-height:1;">'
        f'{html_lib.escape(bucket_label)}</div>'
        f'<div style="{inner_layout}">'
        f'{"".join(inner)}'
        f'</div>'
        f'{summary_html}'
        f'</div>'
    )


def _media_to_funnel_arrow_html(
    pct_label: str | None = None,
    *,
    branch: str = "leads",
    compact: bool = False,
) -> str:
    """Seta da mídia em direção ao Funil de Marketing (Leads / Cliques)."""
    color = PALETTE["wine_light"] if branch == "leads" else PALETTE["text_subtle"]
    arrow = "→"
    pct_html = ""
    pct_fs = "0.55em" if compact else "0.6em"
    if pct_label:
        pct_html = (
            f'<div style="font-size:{pct_fs};color:{PALETTE["muted"]};'
            f'margin-top:1px;font-variant-numeric:tabular-nums;'
            f'white-space:nowrap;line-height:1.1;">'
            f'{html_lib.escape(pct_label)}</div>'
        )
    arrow_fs = "1.05em" if compact else "1.15em"
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;'
        f'padding:0;width:100%;">'
        f'<div style="font-size:{arrow_fs};color:{color};line-height:1;">'
        f'{arrow}</div>'
        f'{pct_html}'
        f'</div>'
    )


def _render_funil_marketing_html(
    *,
    kf: dict,
    labels_f: list[str],
    values_f: list[float],
) -> str:
    """Layout Mídia → Funil de Marketing (trilha única baseada em Leads)."""
    from src.marketing_transforms import build_funil_trilha_leads_steps

    midia_html = _bucket_html(
        "Mídia", [0, 1], labels_f, values_f, full_width=False, compact=True,
    )
    funnel_html = _funnel_track_bucket_html(
        "Funil de Marketing",
        build_funil_trilha_leads_steps(kf),
        base_noun="leads",
        compact=True,
        kf=kf,
        summary_items=_funil_aplicacoes_summary_pills(kf),
    )
    cliques_leads_pct = (
        pct((values_f[2] / values_f[1]) * 100, casas=1)
        if values_f[1] > 0 else None
    )
    arrow_html = _media_to_funnel_arrow_html(
        cliques_leads_pct, branch="leads", compact=True,
    )

    return (
        f'<div style="display:grid;'
        f'grid-template-columns:minmax(118px,16%) 22px 1fr;'
        f'grid-template-rows:1fr;'
        f'column-gap:4px;align-items:center;'
        f'font-family:Inter,sans-serif;margin-top:0;">'
        f'<div style="grid-column:1;display:flex;align-items:center;'
        f'justify-content:center;min-width:0;">{midia_html}</div>'
        f'<div style="grid-column:2;display:flex;align-items:center;'
        f'justify-content:center;">{arrow_html}</div>'
        f'<div style="grid-column:3;min-width:0;">{funnel_html}</div>'
        f'</div>'
    )


def _normalize_funil_select_state(
    state_key: str,
    options_norm: list[str],
    labels_map: dict[str, str],
) -> None:
    """Garante que o session_state guarda a norm key, não o label legado.

    Antes das aplicações no label, o widget podia persistir o texto completo
    (ex.: ``Todos os resultados · R$ … · 76 leads · 3 vendas``). Nesse caso
    ``format_func`` devolvia o valor antigo no campo fechado."""
    cur = st.session_state.get(state_key)
    if cur is None or cur in options_norm:
        return
    if isinstance(cur, str):
        for norm, lbl in labels_map.items():
            if cur == lbl:
                st.session_state[state_key] = norm
                return
        cur_prefix = cur.split(" · ")[0]
        for norm, lbl in labels_map.items():
            if lbl.split(" · ")[0] == cur_prefix:
                st.session_state[state_key] = norm
                return
    if options_norm:
        st.session_state[state_key] = options_norm[0]


def render_funil_selecionado(
    *,
    df_funil: pd.DataFrame,
    key_col: str,                          # ex.: "ad_name_norm" | "campaign_name_norm"
    entity_label: str,                     # ex.: "Criativo" | "Campanha"
    section_title_text: str,               # ex.: "Funil do criativo selecionado"
    section_subtitle: str = "investimento → vendas novas",
    sel_state_key: str = "funil_selecionado",
    lista_fn: Callable[[pd.DataFrame, str], pd.DataFrame] | None = None,
    kpis_fn: Callable[[pd.DataFrame, str | None], dict] | None = None,
    etapas_fn: Callable[[dict], tuple[list[str], list[float]]] | None = None,
    etapas_aplicacoes_fn: Callable[[dict], tuple[list[str], list[float]]] | None = None,
    marketing_funil_unico: bool = False,
    empty_msg: str | None = None,
    caption: str | None = None,
    expander_md: str | None = None,
    # Auditoria (opcional) — quando data_ini/data_fim/nivel passados,
    # renderiza tabela "Conferir leads e vendas deste funil" abaixo dos
    # cards e ACIMA do expander "Como este funil é calculado?".
    data_ini: date | None = None,
    data_fim: date | None = None,
    nivel: str | None = None,              # 'criativo' | 'campanha'
    auditoria_state_key: str = "funil_auditoria",
) -> None:
    """Bloco "Funil do {entidade} selecionado(a)" — UI completa.

    Renderiza section_title → selectbox de entidade → 6 mini-cards
    (Investimento · Leads · Leads +12 · Não atua · Agendamentos · Vendas
    novas) → esteira Mídia → Funil de Marketing (trilha única).
    """
    section_title(section_title_text, section_subtitle)

    if df_funil is None or df_funil.empty:
        st.info(empty_msg or f"Sem {entity_label.lower()}s no período.")
        return
    if lista_fn is None or kpis_fn is None or etapas_fn is None:
        st.error(
            "Helper render_funil_selecionado: lista_fn/kpis_fn/etapas_fn "
            "são obrigatórios."
        )
        return

    funil_opts = lista_fn(df_funil, "investimento")
    if funil_opts is None or funil_opts.empty:
        st.info(empty_msg or f"Sem {entity_label.lower()}s com "
                              "investimento ou leads no período.")
        return

    options_norm = funil_opts[key_col].tolist()
    labels_map = dict(zip(funil_opts[key_col], funil_opts["label"], strict=False))

    _normalize_funil_select_state(sel_state_key, options_norm, labels_map)

    def _format_funil_select_label(norm: str) -> str:
        return labels_map.get(str(norm), str(norm))

    sel = st.selectbox(
        entity_label,
        options=options_norm,
        format_func=_format_funil_select_label,
        index=0,
        key=sel_state_key,
    )

    kf = kpis_fn(df_funil, sel)

    # 6 cards
    rs1, rs2, rs3, rs4, rs5, rs6 = st.columns(6, gap="small")
    with rs1:
        metric_card_v2(
            "Investimento",
            brl(kf["investimento"], casas=2),
            hint=f"{kf.get('qtd_adids', 0)} "
                 f"{'campaign_id' if entity_label.lower() == 'campanha' else 'ad_id'}"
                 f"{'s' if (kf.get('qtd_adids', 0) or 0) != 1 else ''} consolidado"
                 f"{'s' if (kf.get('qtd_adids', 0) or 0) != 1 else ''}",
            accent=True,
        )
    with rs2:
        metric_card_v2(
            "Leads",
            int_br(kf["leads_totais"]),
            hint=f"CPL {brl(kf['cpl'], casas=2) if kf['cpl'] else '—'}",
        )
    with rs3:
        metric_card_v2(
            "Leads +12",
            int_br(kf["leads_mais_12"]),
            hint=f"taxa {pct(kf['taxa_mais_12'], casas=1)}",
        )
    with rs4:
        metric_card_v2(
            "Não atua",
            int_br(int(kf.get("leads_nao_atua") or 0)),
            hint="leads classificados como não atua",
        )
    with rs5:
        _ag = int(kf.get("agendamentos") or 0)
        if _ag > 0:
            _hint_ag = (
                f"Período: {int_br(kf.get('agendamentos_leads_periodo', 0))} · "
                f"{pct(kf.get('pct_agend_leads_periodo'), casas=1)} · "
                f"Histórico: {int_br(kf.get('agendamentos_leads_historico', 0))} · "
                f"{pct(kf.get('pct_agend_leads_historico'), casas=1)}"
            )
        else:
            _hint_ag = "—"
        metric_card_v2(
            "Agendamentos",
            int_br(_ag),
            hint=_hint_ag,
        )
    with rs6:
        metric_card_v2(
            "Vendas novas",
            int_br(kf["vendas_novas"]),
            hint=f"CAC {brl(kf['cac'], casas=2) if kf['cac'] else '—'}",
            accent=True,
        )

    # Esteira Mídia → Funil de Marketing
    labels_f, values_f = etapas_fn(kf)

    if all(v == 0 for v in values_f):
        st.info(f"Sem dados de funil para esta {entity_label.lower()} no período.")
    elif marketing_funil_unico or etapas_aplicacoes_fn is not None:
        st.markdown(
            _render_funil_marketing_html(
                kf=kf,
                labels_f=labels_f,
                values_f=values_f,
            ),
            unsafe_allow_html=True,
        )
    else:
        midia_html = _bucket_html("Mídia", [0, 1], labels_f, values_f)

        # Conector Cliques → Leads (entre buckets)
        connector_html = (
            f'<div style="display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;padding:0 4px;'
            f'min-width:36px;">'
            f'<div style="font-size:1.05em;color:{PALETTE["text_subtle"]};'
            f'line-height:1;">→</div>'
            f'<div style="font-size:0.6em;color:{PALETTE["muted"]};'
            f'margin-top:2px;font-variant-numeric:tabular-nums;">'
            + (
                (f"{(values_f[2] / values_f[1] * 100):.1f}%".replace(".", ","))
                if values_f[1] > 0 else "—"
            )
            + '</div></div>'
        )

        leads_html = _bucket_html(
            "Funil de leads", [2, 3, 4, 5, 6], labels_f, values_f,
        )

        st.markdown(
            f'<div style="display:flex;align-items:stretch;gap:0;'
            f'font-family:Inter,sans-serif;margin-top:4px;">'
            f'{midia_html}{connector_html}{leads_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if caption:
        st.caption(caption)

    # ----------------------------------------------------------------------
    # Tabela de auditoria — "Conferir leads e vendas deste funil"
    # ----------------------------------------------------------------------
    if data_ini is not None and data_fim is not None and nivel in ("criativo", "campanha"):
        _render_funil_auditoria_block(
            data_ini=data_ini,
            data_fim=data_fim,
            nivel=nivel,
            item_norm=sel,
            entity_label=entity_label,
            state_key=auditoria_state_key,
        )

    if expander_md:
        with st.expander(f"Como este funil é calculado?"):
            st.markdown(expander_md)


# ============================================================================
# Bloco auxiliar — tabela "Conferir leads e vendas deste funil"
# ============================================================================

_AUDIT_STATUS_OPCOES = (
    "Todos", "+12", "-12", "Não atua", "Ganhos",
    "Com agendamento", "Com comparecimento", "Sem venda",
)


def _render_funil_auditoria_block(
    *,
    data_ini: date,
    data_fim: date,
    nivel: str,                # 'criativo' | 'campanha'
    item_norm: str | None,     # ad_name_norm | campaign_name_norm | sintéticos
    entity_label: str,         # "Criativo" | "Campanha"
    state_key: str,
) -> None:
    """Renderiza expansor "Conferir leads e vendas deste funil" com filtros
    locais (status/classificação + busca) e tabela.

    Dados vêm de `get_mkt_funil_leads_auditoria(data_ini, data_fim, nivel,
    item_norm)`. A query é deal-centric (1 linha por deal ganho atribuído
    ao item selecionado) — "Sem venda" e "Com agendamento/comparecimento"
    funcionam APENAS se a query devolver os flags correspondentes; caso
    contrário a opção continua aparecendo no selectbox mas não filtra
    nada (futura iteração extende a SQL)."""
    if not item_norm:
        return

    with st.expander("Conferir leads e vendas deste funil", expanded=False):
        try:
            df_aud = get_mkt_funil_leads_auditoria(
                data_ini, data_fim, nivel, str(item_norm),
            )
        except Exception as e:
            st.error(f"Falha ao carregar auditoria: {e}")
            return

        if df_aud is None or df_aud.empty:
            st.caption(
                f"Nenhuma venda atribuída para este(a) {entity_label.lower()} "
                "no período."
            )
            return

        # ------------- Filtros locais (acima da tabela) -----------------
        fc1, fc2 = st.columns([1, 2], gap="small")
        with fc1:
            status_sel = st.selectbox(
                "Status / Classificação",
                options=_AUDIT_STATUS_OPCOES,
                index=0,
                key=f"{state_key}_status",
            )
        with fc2:
            busca = st.text_input(
                "Buscar nome ou e-mail",
                value="",
                placeholder="ex.: maria silva, maria@gmail.com",
                key=f"{state_key}_busca",
            )

        # ------------- Aplica filtros -----------------------------------
        df_view = df_aud.copy()

        # Status/Classificação
        classif_col = df_view.get("classificacao", pd.Series("", index=df_view.index))
        classif_norm = classif_col.fillna("").astype(str).str.lower()
        tipo_match_col = df_view.get("tipo_match", pd.Series("", index=df_view.index)).fillna("").astype(str)

        if status_sel == "+12":
            df_view = df_view[classif_norm.str.contains("+12", regex=False, na=False)]
        elif status_sel == "-12":
            df_view = df_view[classif_norm.str.contains("-12", regex=False, na=False)]
        elif status_sel == "Não atua":
            df_view = df_view[classif_norm.str.contains("não atua", na=False)]
        elif status_sel == "Ganhos":
            # Query deal-centric: todos os rows são vendas com tipo_match em
            # ('email','telefone','sem_match'). "Ganhos" = todos. No-op.
            pass
        elif status_sel == "Sem venda":
            # Query atual NÃO tem rows sem venda — todas são deals ganhos.
            # Filtro vira no-op visual; aviso pro user.
            st.caption(
                "ℹ A auditoria atual mostra somente vendas atribuídas. "
                "Filtro 'Sem venda' não tem efeito até a query incluir "
                "leads do período sem venda."
            )
        elif status_sel in ("Com agendamento", "Com comparecimento"):
            st.caption(
                f"ℹ Filtro '{status_sel}' requer colunas de agendamento/"
                "comparecimento na query — não disponíveis ainda. "
                "Próxima iteração."
            )

        # Busca por nome/e-mail (qualquer um dos 4 campos)
        if busca.strip():
            q = busca.strip().lower()
            mask = pd.Series(False, index=df_view.index)
            for col in ("nome_lead", "email_lead", "nome_deal", "email_deal"):
                if col in df_view.columns:
                    mask |= df_view[col].fillna("").astype(str).str.lower().str.contains(q, regex=False, na=False)
            df_view = df_view[mask]

        if df_view.empty:
            st.caption(
                f"Nenhum registro casa com filtros (status='{status_sel}'"
                + (f", busca='{busca}'" if busca.strip() else "")
                + ")."
            )
            return

        # ------------- Caption de contagem ------------------------------
        st.caption(
            f"{len(df_view)} registro(s) · "
            f"{int(df_view['tipo_match'].eq('email').sum())} por e-mail · "
            f"{int(df_view['tipo_match'].eq('telefone').sum())} por telefone · "
            f"{int(df_view['tipo_match'].eq('sem_match').sum())} sem match"
        )

        # ------------- Tabela -------------------------------------------
        # Reordena colunas: lead primeiro, depois venda, depois match/regra.
        cols_ordem = [
            ("data_lead",          "Data lead"),
            ("nome_lead",          "Nome lead"),
            ("email_lead",         "E-mail lead"),
            ("telefone_lead",      "Telefone lead"),
            ("classificacao",      "Classificação"),
            ("tipo_origem",        "Tipo de origem"),
            ("utm_source",         "UTM source"),
            ("utm_medium",         "UTM medium"),
            ("campanha_atribuida", "Campanha atribuída"),
            ("criativo_atribuido", "Criativo atribuído"),
            ("data_venda",         "Data venda"),
            ("dias_lead_venda",    "Dias lead→venda"),
            ("nome_deal",          "Nome deal"),
            ("email_deal",         "E-mail deal"),
            ("telefone_deal",      "Telefone deal"),
            ("montante",           "Montante"),
            ("tipo_match",         "Tipo de match"),
            ("regra_atribuicao",   "Regra de atribuição"),
        ]
        cols_disp = [c for c, _ in cols_ordem if c in df_view.columns]
        df_show = df_view[cols_disp].rename(
            columns={c: lbl for c, lbl in cols_ordem if c in cols_disp}
        )
        cfg: dict = {}
        for date_lbl in ("Data lead", "Data venda"):
            if date_lbl in df_show.columns:
                cfg[date_lbl] = st.column_config.DateColumn(
                    date_lbl, format="DD/MM/YYYY",
                )
        if "Montante" in df_show.columns:
            cfg["Montante"] = st.column_config.NumberColumn(
                "Montante", format="R$ %.0f",
            )
        if "Dias lead→venda" in df_show.columns:
            cfg["Dias lead→venda"] = st.column_config.NumberColumn(
                "Dias lead→venda", format="%d",
            )
        st.dataframe(
            df_show,
            use_container_width=True,
            hide_index=True,
            column_config=cfg,
        )
