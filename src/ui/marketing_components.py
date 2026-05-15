"""Componentes reutilizáveis das páginas de Marketing.

`render_funil_selecionado` encapsula o bloco "Funil do {entidade}
selecionado(a)" — selectbox + 6 mini-cards + esteira horizontal (2
buckets: Mídia | Funil de leads). Reusado pela página Criativos
(`ad_name`) e pela página Campanhas (`campaign_name`), com a mesma
estrutura visual e regras de cálculo.
"""
from __future__ import annotations

import html as html_lib
from typing import Callable

import pandas as pd
import streamlit as st

from src.ui.components import metric_card_v2, section_title
from src.ui.theme import PALETTE, brl, int_br, pct


def _fmt_value(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".", ",")
    if v >= 100_000:
        return f"{v / 1_000:.0f}K"
    return int_br(int(v))


def _step_html(label: str, value: float,
               bucket_topo: float,
               is_bucket_topo: bool,
               bucket_topo_label: str) -> str:
    value_fmt = _fmt_value(value)
    pct_bt = (value / bucket_topo) * 100 if bucket_topo > 0 else 0
    pct_bt_fmt = (
        f"{pct_bt:.1f}% de {bucket_topo_label}".replace(".", ",")
    )
    sub_html = (
        f'<div style="font-size:0.66em;color:{PALETTE["muted"]};'
        f'margin-top:2px;">topo do grupo</div>'
        if is_bucket_topo else
        f'<div style="font-size:0.66em;color:{PALETTE["text_subtle"]};'
        f'margin-top:2px;font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(pct_bt_fmt)}</div>'
    )
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;'
        f'min-width:78px;padding:6px 4px;text-align:center;">'
        f'<div style="font-size:0.6em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.05em;'
        f'font-weight:600;line-height:1.1;margin-bottom:4px;'
        f'min-height:1.2em;">{html_lib.escape(label)}</div>'
        f'<div style="font-size:1.15em;font-weight:700;'
        f'color:{PALETTE["text"]};line-height:1.1;'
        f'font-variant-numeric:tabular-nums;">'
        f'{html_lib.escape(value_fmt)}</div>'
        f'{sub_html}'
        f'</div>'
    )


def _arrow_html(prev_value: float, value: float,
                emphatic: bool = False) -> str:
    if prev_value > 0:
        pct_step = (value / prev_value) * 100
        pct_step_fmt = f"{pct_step:.1f}%".replace(".", ",")
    else:
        pct_step_fmt = "—"
    color = PALETTE["wine_light"] if emphatic else PALETTE["text_subtle"]
    arrow_size = "1.2em" if emphatic else "1.05em"
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;'
        f'padding:0 6px;min-width:50px;">'
        f'<div style="font-size:{arrow_size};color:{color};'
        f'line-height:1;">→</div>'
        f'<div style="font-size:0.66em;color:{color};'
        f'margin-top:2px;font-variant-numeric:tabular-nums;'
        f'font-weight:600;">{html_lib.escape(pct_step_fmt)}</div>'
        f'</div>'
    )


def _bucket_html(bucket_label: str, indices: list[int],
                 labels_f: list[str], values_f: list[float]) -> str:
    bt_idx = indices[0]
    bt_val = values_f[bt_idx] if values_f[bt_idx] > 0 else 1.0
    bt_label = labels_f[bt_idx].lower()
    inner: list[str] = []
    for n, i in enumerate(indices):
        if n > 0:
            inner.append(_arrow_html(values_f[i - 1], values_f[i]))
        inner.append(
            _step_html(
                labels_f[i], values_f[i],
                bucket_topo=bt_val,
                is_bucket_topo=(n == 0),
                bucket_topo_label=bt_label,
            )
        )
    return (
        f'<div style="flex:1;display:flex;flex-direction:column;'
        f'background:{PALETTE["card"]};'
        f'border:1px solid {PALETTE["border"]};border-radius:10px;'
        f'padding:8px 10px;">'
        f'<div style="font-size:0.62em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.08em;'
        f'font-weight:600;margin-bottom:6px;">'
        f'{html_lib.escape(bucket_label)}</div>'
        f'<div style="display:flex;align-items:stretch;'
        f'justify-content:space-between;flex-wrap:nowrap;">'
        f'{"".join(inner)}'
        f'</div>'
        f'</div>'
    )


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
    empty_msg: str | None = None,
    caption: str | None = None,
    expander_md: str | None = None,
) -> None:
    """Bloco "Funil do {entidade} selecionado(a)" — UI completa.

    Renderiza section_title → selectbox de entidade → 6 mini-cards
    (Investimento · Leads · Leads +12 · Não atua · Agendamentos · Vendas
    novas) → esteira horizontal de 2 buckets (Mídia | Funil de leads).
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
    labels_map = dict(zip(funil_opts[key_col], funil_opts["label"]))

    sel = st.selectbox(
        entity_label,
        options=options_norm,
        format_func=lambda n: labels_map.get(n, n),
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
        metric_card_v2(
            "Agendamentos",
            int_br(kf["agendamentos"]),
            hint=f"taxa {pct(kf['taxa_lead_agendamento'], casas=1)}",
        )
    with rs6:
        metric_card_v2(
            "Vendas novas",
            int_br(kf["vendas_novas"]),
            hint=f"CAC {brl(kf['cac'], casas=2) if kf['cac'] else '—'}",
            accent=True,
        )

    # Funil horizontal (2 buckets)
    labels_f, values_f = etapas_fn(kf)

    if all(v == 0 for v in values_f):
        st.info(f"Sem dados de funil para esta {entity_label.lower()} no período.")
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

    if expander_md:
        with st.expander(f"Como este funil é calculado?"):
            st.markdown(expander_md)
