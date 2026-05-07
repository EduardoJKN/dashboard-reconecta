"""Criativos — performance dos anúncios Meta.

Consome `bi.vw_mkt_criativos` (Meta-only, enriquecida com `odam.meta_ads_creatives`).
Página dedicada a análise de criativo: KPIs · distribuições · grid de
thumbnails · tabela detalhada com rankings (quality, engagement, conversion)."""
from __future__ import annotations

import html as html_lib
from datetime import timedelta

import streamlit as st

from src.marketing_queries import (
    get_mkt_criativo_funil,
    get_mkt_criativos,
    get_mkt_criativos_cobertura,
    get_mkt_criativos_resultados,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    cobertura_criativos_kpis,
    compara_criativos,
    criativo_funil_etapas,
    criativo_funil_kpis,
    criativo_kpis,
    criativos_kpis,
    criativos_por_quality,
    criativos_por_status,
    criativos_ranking,
    criativos_tabela,
    lista_criativos,
    lista_criativos_funil,
    normalize_status,
)
from src.transforms import delta_pct
from src.ui.charts import donut
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, int_br, pct

# ---------------------------------------------------------------------------
# Header + filtros (período + campanha + status)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Criativos",
    subtitle="Performance dos anúncios Meta",
    filters=["campanha", "status"],
)

# ---------------------------------------------------------------------------
# Carga (período atual + período anterior para deltas dos KPIs)
# ---------------------------------------------------------------------------
df_all = safe_run(
    lambda: get_mkt_criativos(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_criativos",
)

# normaliza status_label antes do filtro categórico — o filtro mostra labels PT
if not df_all.empty:
    df_all = df_all.copy()
    df_all["status_label"] = df_all["effective_status"].apply(normalize_status)

col_map = {"campanha": "campaign_name", "status": "status_label"}
df = ctx.apply_filters(df_all, col_map)

# Período anterior para deltas
dias = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias - 1)

df_prev_all = safe_run(
    lambda: get_mkt_criativos(prev_ini, prev_fim),
    view_label="bi.vw_mkt_criativos",
)
if not df_prev_all.empty:
    df_prev_all = df_prev_all.copy()
    df_prev_all["status_label"] = df_prev_all["effective_status"].apply(normalize_status)
df_prev = (
    ctx.refilter(df_prev_all, col_map) if not df_prev_all.empty else df_prev_all
)

# Resultados atribuídos via mart (por ad_id) — período atual e anterior
df_resultados = safe_run(
    lambda: get_mkt_criativos_resultados(ctx.data_ini, ctx.data_fim),
    view_label="odam.mart_ad_funnel_daily (criativos)",
)
df_resultados_prev = safe_run(
    lambda: get_mkt_criativos_resultados(prev_ini, prev_fim),
    view_label="odam.mart_ad_funnel_daily (criativos)",
)

# Cards gerais somam mart filtrando aos ad_ids visíveis após filtro de
# campanha/status na página. Restringimos df_resultados aos ad_ids filtrados.
def _restrict_resultados_aos_ads(df_resultados, df_view):
    if df_resultados is None or df_resultados.empty or df_view.empty:
        return df_resultados
    ads_visiveis = set(df_view["ad_id"].dropna().astype(str).unique())
    if not ads_visiveis:
        return df_resultados.iloc[0:0]
    res = df_resultados.copy()
    res["ad_id"] = res["ad_id"].astype(str)
    return res[res["ad_id"].isin(ads_visiveis)]

df_resultados_filtered = _restrict_resultados_aos_ads(df_resultados, df)
df_resultados_prev_filtered = _restrict_resultados_aos_ads(df_resultados_prev, df_prev)

k = criativos_kpis(df, df_resultados_filtered)
kp = criativos_kpis(df_prev, df_resultados_prev_filtered)

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
section_title(
    "Performance Meta",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4, c5 = st.columns(5, gap="small")
with c1:
    metric_card_v2(
        "Anúncios ativos",
        int_br(k["anuncios_ativos"]),
        delta_pct=delta_pct(k["anuncios_ativos"], kp["anuncios_ativos"]),
        hint="ad_ids distintos com invest > 0",
        accent=True,
    )
with c2:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="Meta · período filtrado",
    )
with c3:
    metric_card_v2(
        "Impressões",
        int_br(k["impressoes"]),
        delta_pct=delta_pct(k["impressoes"], kp["impressoes"]),
        hint=f"alcance: {int_br(k['alcance'])} · "
             f"freq.: {k['frequencia']:.2f}".replace(".", ","),
    )
with c4:
    metric_card_v2(
        "CTR",
        pct(k["ctr"], casas=2),
        delta_pct=delta_pct(k["ctr"], kp["ctr"]),
        hint=f"{int_br(k['cliques'])} cliques",
    )
with c5:
    metric_card_v2(
        "CPC",
        brl(k["cpc"], casas=2),
        delta_pct=delta_pct(k["cpc"], kp["cpc"]),
        hint="invest ÷ cliques",
    )

# ---------------------------------------------------------------------------
# Funil do criativo selecionado — match `ad_name = utm_content`
# Granularidade `ad_name` consolida múltiplos `ad_id` (CBO/A-B). Lead → deal
# por priority `zoho_id > session_id > email`; deal → activity via what_id
# (regra oficial Visão Geral / Growth). Caveats explicados na caption.
# ---------------------------------------------------------------------------
section_title(
    "Funil do criativo selecionado",
    "investimento → vendas novas",
)

df_cri_funil = safe_run(
    lambda: get_mkt_criativo_funil(ctx.data_ini, ctx.data_fim),
    view_label="mkt_criativo_funil",
)
funil_opts = lista_criativos_funil(df_cri_funil, sort_by="investimento")

if funil_opts.empty:
    st.info("Sem criativos com investimento ou leads no período.")
else:
    options_norm = funil_opts["ad_name_norm"].tolist()
    labels_funil = dict(zip(funil_opts["ad_name_norm"], funil_opts["label"]))

    sel_funil = st.selectbox(
        "Criativo",
        options=options_norm,
        format_func=lambda n: labels_funil.get(n, n),
        index=0,
        key="cri_funil_selecionado",
    )

    kf = criativo_funil_kpis(df_cri_funil, sel_funil)

    # ---- Resumo (5 cards: Invest, Leads, +12, Agend, Vendas novas) -------
    rs1, rs2, rs3, rs4, rs5 = st.columns(5, gap="small")
    with rs1:
        metric_card_v2(
            "Investimento",
            brl(kf["investimento"], casas=2),
            hint=f"{kf['qtd_adids']} ad_id"
                 f"{'s' if kf['qtd_adids'] != 1 else ''} consolidado"
                 f"{'s' if kf['qtd_adids'] != 1 else ''}",
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
            "Agendamentos",
            int_br(kf["agendamentos"]),
            hint=f"taxa {pct(kf['taxa_lead_agendamento'], casas=1)}",
        )
    with rs5:
        metric_card_v2(
            "Vendas novas",
            int_br(kf["vendas_novas"]),
            hint=f"CAC {brl(kf['cac'], casas=2) if kf['cac'] else '—'}",
            accent=True,
        )

    # ---- Esteira horizontal — 2 grupos (Mídia | Funil de leads) ---------
    labels_f, values_f = criativo_funil_etapas(kf)

    if all(v == 0 for v in values_f):
        st.info("Sem dados de funil para este criativo no período.")
    else:
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
            # Step que abre o bucket: rótulo "topo do grupo" em vez do %.
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

        def _bucket_html(bucket_label: str, indices: list[int]) -> str:
            # Topo do bucket = primeira etapa. % subsequente é relativo a ele.
            bt_idx = indices[0]
            bt_val = values_f[bt_idx] if values_f[bt_idx] > 0 else 1.0
            bt_label = labels_f[bt_idx].lower()
            inner = []
            for n, i in enumerate(indices):
                if n > 0:
                    # arrow entre steps DENTRO do bucket; entre buckets é o
                    # connector externo.
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

        # Mídia: índices 0,1 (Impressões, Cliques)
        midia_html = _bucket_html("Mídia", [0, 1])

        # Conector Cliques → Leads (divisória sutil + setinha entre buckets)
        connector_html = (
            f'<div style="display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;padding:0 4px;'
            f'min-width:36px;">'
            f'<div style="font-size:1.05em;color:{PALETTE["text_subtle"]};'
            f'line-height:1;">→</div>'
            f'<div style="font-size:0.6em;color:{PALETTE["muted"]};'
            f'margin-top:2px;font-variant-numeric:tabular-nums;">'
            f'{html_lib.escape((f"{(values_f[2] / values_f[1] * 100):.1f}%" .replace(".", ",")) if values_f[1] > 0 else "—")}'
            f'</div>'
            f'</div>'
        )

        # Funil de leads: índices 2..6
        leads_html = _bucket_html("Funil de leads", [2, 3, 4, 5, 6])

        st.markdown(
            f'<div style="display:flex;align-items:stretch;gap:0;'
            f'font-family:Inter,sans-serif;margin-top:4px;">'
            f'{midia_html}{connector_html}{leads_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.caption(
        "Funil por criativo usa `ad_name = utm_content`. Criativos sem "
        "match podem aparecer sem leads atribuídos."
    )

    with st.expander("Como este funil é calculado?"):
        st.markdown(
            "- **Match:** `lower(btrim(ad_name)) = lower(btrim(utm_content))`.\n"
            "- **`ad_id`** não está populado nos leads, deals nem activities — "
            "  esse é o melhor match disponível hoje.\n"
            "- **Granularidade:** consolidado por `ad_name`. Múltiplos `ad_id` "
            "  do mesmo criativo (CBO/A-B) somam mídia mas não inflam leads "
            "  (utm_content é o nome).\n"
            "- **Lead → deal:** priority match "
            "  `zoho_id > session_id > email` (mesma regra Visão Geral / "
            "  Growth / Campanhas).\n"
            "- **Agendamentos / Comparecimentos:** leads únicos com activity "
            "  `Consulta` ou `Indicação` em `zoho_activities` ligada via "
            "  `what_id = deal_id`. Comparecimento exige "
            "  `status_reuniao = 'Concluída'`.\n"
            "- **Vendas novas:** deals com `stage IN ('Ganho','Fechado Ganho')`"
            "  e `tipo_venda = 'Novo cliente'` (caminho de aquisição; "
            "  ascensão / renovação / indicação ficam fora)."
        )

# ---------------------------------------------------------------------------
# Resultado atribuído (mart) + derivadas
# ---------------------------------------------------------------------------
section_title(
    "Resultado atribuído",
    "via odam.mart_ad_funnel_daily — restrito aos ad_ids visíveis nos filtros",
)


def _val_or_dash(v, formatter, *args, **kwargs):
    """Aplica formatter em v se numérico; '—' se None ou NaN."""
    if v is None:
        return "—"
    try:
        if isinstance(v, float) and v != v:  # NaN
            return "—"
    except Exception:
        pass
    return formatter(v, *args, **kwargs) if (args or kwargs) else formatter(v)


def _delta_or_none(curr, prev):
    """delta_pct seguro com None — retorna None pra não sinalizar variação fake."""
    if curr is None or prev is None:
        return None
    if isinstance(curr, float) and curr != curr:
        return None
    if isinstance(prev, float) and prev != prev:
        return None
    return delta_pct(curr, prev)


# Linha 2: Leads, +12, Agendamentos, Comparecimentos
r2c1, r2c2, r2c3, r2c4 = st.columns(4, gap="small")
with r2c1:
    metric_card_v2(
        "Leads",
        _val_or_dash(k["leads_total"], int_br),
        delta_pct=_delta_or_none(k["leads_total"], kp["leads_total"]),
        hint="leads atribuídos · mart",
    )
with r2c2:
    metric_card_v2(
        "Leads +12",
        _val_or_dash(k["leads_mais_12"], int_br),
        delta_pct=_delta_or_none(k["leads_mais_12"], kp["leads_mais_12"]),
        hint="ATUA +12 · mart",
    )
with r2c3:
    metric_card_v2(
        "Agendamentos",
        _val_or_dash(k["agendamentos"], int_br),
        delta_pct=_delta_or_none(k["agendamentos"], kp["agendamentos"]),
        hint="zoho_activities · mart",
    )
with r2c4:
    metric_card_v2(
        "Comparecimentos",
        _val_or_dash(k["comparecimentos"], int_br),
        delta_pct=_delta_or_none(k["comparecimentos"], kp["comparecimentos"]),
        hint="status_reuniao = 'Concluída' · mart",
    )

# Linha 3: Vendas, Receita, ROAS, CAC
r3c1, r3c2, r3c3, r3c4 = st.columns(4, gap="small")
with r3c1:
    metric_card_v2(
        "Vendas",
        _val_or_dash(k["vendas"], int_br),
        delta_pct=_delta_or_none(k["vendas"], kp["vendas"]),
        hint="stage='Ganho' c/ data_compra · mart",
    )
with r3c2:
    metric_card_v2(
        "Receita",
        _val_or_dash(k["valor_receita"], brl, casas=2),
        delta_pct=_delta_or_none(k["valor_receita"], kp["valor_receita"]),
        hint="receita atribuída · mart",
    )
with r3c3:
    if k["roas"] is None:
        metric_card_v2(
            "ROAS", "—",
            hint="sem receita atribuída ou invest=0",
        )
    else:
        metric_card_v2(
            "ROAS",
            f"{k['roas']:.2f}x".replace(".", ","),
            delta_pct=_delta_or_none(k["roas"], kp["roas"]),
            hint="receita mart ÷ invest oficial",
            accent=True,
        )
with r3c4:
    metric_card_v2(
        "CAC",
        _val_or_dash(k["cac"], brl, casas=2),
        delta_pct=_delta_or_none(k["cac"], kp["cac"]),
        hint="invest oficial ÷ vendas mart",
    )

# Linha 4: CPL, CPL +12, Leads -12, No-shows
r4c1, r4c2, r4c3, r4c4 = st.columns(4, gap="small")
with r4c1:
    metric_card_v2(
        "CPL",
        _val_or_dash(k["cpl"], brl, casas=2),
        delta_pct=_delta_or_none(k["cpl"], kp["cpl"]),
        hint="invest oficial ÷ leads mart",
    )
with r4c2:
    metric_card_v2(
        "CPL +12",
        _val_or_dash(k["cpl_mais_12"], brl, casas=2),
        delta_pct=_delta_or_none(k["cpl_mais_12"], kp["cpl_mais_12"]),
        hint="invest oficial ÷ leads +12 mart",
    )
with r4c3:
    metric_card_v2(
        "Leads -12",
        _val_or_dash(k["leads_menos_12"], int_br),
        delta_pct=_delta_or_none(k["leads_menos_12"], kp["leads_menos_12"]),
        hint="ATUA -12 · mart",
    )
with r4c4:
    metric_card_v2(
        "No-shows",
        _val_or_dash(k["no_shows"], int_br),
        delta_pct=_delta_or_none(k["no_shows"], kp["no_shows"]),
        hint="agendou mas não compareceu · mart",
    )

# ---------------------------------------------------------------------------
# Distribuições — Status × Quality Ranking
# ---------------------------------------------------------------------------
col_st, col_q = st.columns(2, gap="large")

with col_st:
    section_title("Por status", "investimento agrupado por status do anúncio")
    by_status = criativos_por_status(df)
    if by_status.empty:
        st.info("Sem investimento Meta no período para os filtros aplicados.")
    else:
        st.plotly_chart(
            donut(by_status, names="status_label", values="investimento",
                  height=300, total_label="Invest. total"),
            use_container_width=True,
        )

with col_q:
    section_title("Por quality ranking",
                  "diagnóstico Meta · qualidade do criativo")
    by_q = criativos_por_quality(df)
    if by_q.empty:
        st.info("Sem dados de quality ranking no período.")
    else:
        st.plotly_chart(
            donut(by_q, names="quality_label", values="investimento",
                  height=300, total_label="Invest. total"),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Top criativos — grid 4×3 com thumbnails
# ---------------------------------------------------------------------------
SORT_OPTIONS = {
    # Plataforma (sempre disponível)
    "Investimento (maior)":     ("investimento",   False),
    "CTR (maior)":              ("ctr",            False),
    "CPC (menor)":              ("cpc",            True),
    "Impressões (maior)":       ("impressoes",     False),
    "Alcance (maior)":          ("alcance",        False),
    # Resultado / derivadas (mart) — anúncios sem mart vão pro fim
    "Leads (maior)":            ("leads_total",    False),
    "Leads +12 (maior)":        ("leads_mais_12",  False),
    "Agendamentos (maior)":     ("agendamentos",   False),
    "Vendas (maior)":           ("vendas",         False),
    "Receita (maior)":          ("valor_receita", False),
    "ROAS (maior)":             ("roas",           False),
    "CAC (menor)":              ("cac",            True),
    "CPL (menor)":              ("cpl",            True),
    "CPL +12 (menor)":          ("cpl_mais_12",    True),
}

head_l, head_r = st.columns([3, 1.2], vertical_alignment="bottom")
with head_l:
    section_title("Top 12 criativos",
                  "ranking dos anúncios com investimento no período")
with head_r:
    sort_choice = st.selectbox(
        "Ordenar por",
        list(SORT_OPTIONS.keys()),
        index=0, key="creatives_sort",
        label_visibility="collapsed",
    )

sort_field, ascending = SORT_OPTIONS[sort_choice]
top = criativos_ranking(
    df, sort_by=sort_field, ascending=ascending, top_n=12,
    df_resultados=df_resultados_filtered,
)


def _creative_card_html(row) -> str:
    # pandas devolve NaN (float) em colunas vazias. `bool(NaN) == True` em
    # Python, então `or` NÃO cai no fallback — html_lib.escape(NaN) explode
    # porque float não tem .replace. Helper local normaliza NaN/None/""→None.
    def _safe_str(v):
        if v is None:
            return None
        if isinstance(v, float) and v != v:  # NaN
            return None
        s = str(v).strip()
        return s if s else None

    thumb = _safe_str(row.get("thumbnail_url")) or _safe_str(row.get("image_url"))
    name = _safe_str(row.get("ad_name")) or "(sem nome)"
    name_safe = html_lib.escape(name[:60])

    if thumb:
        media = (
            f'<img src="{html_lib.escape(thumb)}" '
            f'style="width:100%;height:160px;object-fit:cover;'
            f'border-radius:8px 8px 0 0;display:block;border:0;" '
            f'alt="{name_safe}" loading="lazy" />'
        )
    else:
        # placeholder neutro com nome do anúncio (decisão do produto)
        placeholder_text = html_lib.escape(name[:48])
        media = (
            f'<div style="width:100%;height:160px;'
            f'background:linear-gradient(135deg,{PALETTE["bg_soft"]},{PALETTE["card_strong"]});'
            f'border-radius:8px 8px 0 0;'
            f'display:flex;align-items:center;justify-content:center;'
            f'padding:14px;text-align:center;'
            f'color:{PALETTE["text_subtle"]};font-size:0.78em;'
            f'font-family:Inter;line-height:1.4;'
            f'border-bottom:1px solid {PALETTE["border"]};">'
            f'<div><div style="opacity:0.5;font-size:0.85em;'
            f'text-transform:uppercase;letter-spacing:0.06em;'
            f'margin-bottom:6px;">Sem preview</div>'
            f'<div style="opacity:0.85;">{placeholder_text}</div></div>'
            f'</div>'
        )

    permalink = _safe_str(row.get("permalink_url"))
    if permalink:
        media = (
            f'<a href="{html_lib.escape(permalink)}" target="_blank" '
            f'rel="noopener" style="text-decoration:none;display:block;">'
            f'{media}</a>'
        )

    status = _safe_str(row.get("status_label")) or "—"
    invest = float(row.get("investimento") or 0)
    ctr = float(row.get("ctr") or 0)
    cpc = float(row.get("cpc") or 0)

    ctr_fmt = f"{ctr:.2f}%".replace(".", ",")
    cpc_fmt = brl(cpc, casas=2) if cpc else "—"
    # Investimento exibido completo (sem abreviação K/M). Quando inteiro,
    # mostra "R$ 3.000"; com centavos, "R$ 3.025,69".
    invest_fmt = (
        brl(invest, casas=0) if invest == int(invest) else brl(invest, casas=2)
    )

    # Linha 2 — Leads · +12 · CPL (mart). NaN ⇒ "—" (sem atribuição); 0 real
    # da mart ⇒ "0"; CPL com leads=0 já vem como NaN (denominador zero) e
    # cai em "—" — coerente com a regra "não inventar zero".
    def _missing(v) -> bool:
        if v is None:
            return True
        try:
            return isinstance(v, float) and v != v  # NaN
        except Exception:
            return False

    leads_raw = row.get("leads_total")
    mais12_raw = row.get("leads_mais_12")
    cpl_raw = row.get("cpl")
    leads_fmt = "—" if _missing(leads_raw) else int_br(int(leads_raw))
    mais12_fmt = "—" if _missing(mais12_raw) else int_br(int(mais12_raw))
    cpl_fmt = "—" if _missing(cpl_raw) else brl(float(cpl_raw), casas=2)

    metric_label_css = (
        f'font-size:0.62em;color:{PALETTE["muted"]};'
        f'text-transform:uppercase;letter-spacing:0.04em;'
    )
    metric_value_css = (
        f'font-weight:600;color:{PALETTE["text"]};font-size:0.95em;'
    )
    # Valores vindos da mart usam um tom levemente mais discreto pra
    # diferenciar de plataforma sem poluir.
    metric_value_mart_css = (
        f'font-weight:600;color:{PALETTE["text_subtle"]};font-size:0.95em;'
    )

    return (
        f'<div style="background:{PALETTE["card"]};'
        f'border:1px solid {PALETTE["border"]};border-radius:8px;'
        f'overflow:hidden;margin-bottom:14px;font-family:Inter,sans-serif;">'
        f'{media}'
        f'<div style="padding:10px 12px;">'
        f'<div title="{name_safe}" style="font-weight:600;'
        f'color:{PALETTE["text"]};font-size:0.82em;margin-bottom:6px;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        f'{name_safe}</div>'
        f'<div style="display:inline-block;padding:2px 9px;'
        f'border-radius:999px;background:{PALETTE["wine_soft"]};'
        f'color:{PALETTE["text_subtle"]};font-size:0.66em;'
        f'text-transform:uppercase;letter-spacing:0.04em;margin-bottom:10px;">'
        f'{html_lib.escape(status)}</div>'
        # Linha 1 — plataforma (Invest. · CTR · CPC)
        f'<div style="display:flex;gap:12px;">'
        f'<div><div style="{metric_label_css}">Invest.</div>'
        f'<div style="font-weight:600;color:{PALETTE["gold"]};font-size:0.95em;">'
        f'{html_lib.escape(invest_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">CTR</div>'
        f'<div style="{metric_value_css}">{html_lib.escape(ctr_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">CPC</div>'
        f'<div style="{metric_value_css}">{html_lib.escape(cpc_fmt)}</div></div>'
        f'</div>'
        # Linha 2 — resultado/derivada da mart (Leads · +12 · CPL)
        f'<div style="display:flex;gap:12px;margin-top:8px;'
        f'padding-top:8px;border-top:1px solid {PALETTE["border"]};">'
        f'<div><div style="{metric_label_css}">Leads</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(leads_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">+12</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(mais12_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">CPL</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(cpl_fmt)}</div></div>'
        f'</div>'
        f'</div></div>'
    )


if top.empty:
    st.info("Nenhum criativo com investimento no período para os filtros aplicados.")
else:
    rows = top.to_dict("records")
    # Renderiza em linhas de 4 colunas
    for i in range(0, len(rows), 4):
        cols_grid = st.columns(4, gap="small")
        for col, row in zip(cols_grid, rows[i:i + 4]):
            with col:
                st.markdown(_creative_card_html(row), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Comparar criativos (V1 — plataforma + resultado atribuído via mart)
# Plataforma: bi.vw_mkt_criativos (oficial) · Resultado: odam.mart_ad_funnel_daily
# Derivadas: invest oficial / contagens da mart
# Default: top 1 e top 2 do MESMO sort_by/ascending escolhido no Top 12 acima.
# ---------------------------------------------------------------------------
section_title("Comparar criativos",
              "plataforma + resultado atribuído · lado a lado")

cri_list = lista_criativos(
    df, df_resultados_filtered,
    sort_by=sort_field, ascending=ascending,
)
if cri_list.empty:
    st.caption("Sem criativos no período selecionado para comparar.")
else:
    options = cri_list["ad_id"].tolist()
    labels_map = dict(zip(cri_list["ad_id"], cri_list["label"]))

    idx_default_b = 1 if len(options) > 1 else 0

    sel_col_a, sel_col_b = st.columns(2, gap="small")
    with sel_col_a:
        sel_a = st.selectbox(
            "Criativo A",
            options=options,
            format_func=lambda aid: labels_map.get(aid, "—"),
            index=0,
            key="cmp_criativo_a",
        )
    with sel_col_b:
        sel_b = st.selectbox(
            "Criativo B",
            options=options,
            format_func=lambda aid: labels_map.get(aid, "—"),
            index=idx_default_b,
            key="cmp_criativo_b",
        )

    kA = criativo_kpis(df, sel_a, df_resultados_filtered)
    kB = criativo_kpis(df, sel_b, df_resultados_filtered)

    # Badge sutil sob cada selectbox indicando se o criativo tem resultado
    # atribuído na mart. Ajuda o usuário a interpretar "—" nas linhas de
    # resultado/derivadas.
    bdg_col_a, bdg_col_b = st.columns(2, gap="small")
    with bdg_col_a:
        st.caption(
            "✓ resultados atribuídos" if kA["tem_resultados"]
            else "⚠ sem atribuição no mart"
        )
    with bdg_col_b:
        st.caption(
            "✓ resultados atribuídos" if kB["tem_resultados"]
            else "⚠ sem atribuição no mart"
        )

    cmp = compara_criativos(kA, kB)

    # ---- Formatadores -----------------------------------------------------
    # None → "—" para qualquer métrica numérica (sem atribuição OU
    # denominador zero em derivada).
    _MONEY_METRICS_C = {"Investimento", "CPC", "CPL", "CPL +12", "CAC", "Receita"}
    _PCT_METRICS_C = {"CTR"}
    _ROAS_METRIC_C = {"ROAS"}
    _FLOAT_METRICS_C = {"Frequência"}
    _IDENT_METRICS_C = {"Campanha", "Status",
                        "Quality ranking", "Engagement ranking",
                        "Conversion ranking"}

    def _fmt_value_cri(metrica: str, val) -> str:
        if val is None:
            return "—"
        try:
            if isinstance(val, float) and val != val:  # NaN
                return "—"
        except Exception:
            pass
        if metrica in _IDENT_METRICS_C:
            return str(val) if val else "—"
        if metrica in _MONEY_METRICS_C:
            return brl(float(val), casas=2)
        if metrica in _PCT_METRICS_C:
            return pct(float(val), casas=2)
        if metrica in _ROAS_METRIC_C:
            return f"{float(val):.2f}x".replace(".", ",")
        if metrica in _FLOAT_METRICS_C:
            return f"{float(val):.2f}".replace(".", ",")
        # Inteiros (Impressões, Cliques, Link clicks, Alcance, Leads, +12,
        # -12, Agendamentos, Comparecimentos, No-shows, Deals, Deals ganhos,
        # Vendas)
        return int_br(float(val))

    def _fmt_delta_cri(d) -> str:
        import pandas as _pd
        if d is None or _pd.isna(d):
            return "—"
        sign = "+" if d > 0 else ""
        return f"{sign}{d:.1f}%".replace(".", ",")

    def _fmt_vencedor_cri(v: str) -> str:
        return f"✓ {v}" if v else ""

    view_cri = cmp.assign(
        valor_a_fmt=cmp.apply(
            lambda r: _fmt_value_cri(r["metrica"], r["valor_a"]), axis=1
        ),
        valor_b_fmt=cmp.apply(
            lambda r: _fmt_value_cri(r["metrica"], r["valor_b"]), axis=1
        ),
        delta_fmt=cmp["delta_pct"].apply(_fmt_delta_cri),
        vencedor_fmt=cmp["vencedor"].apply(_fmt_vencedor_cri),
    )[["metrica", "valor_a_fmt", "valor_b_fmt", "delta_fmt", "vencedor_fmt"]]

    st.dataframe(
        view_cri, use_container_width=True, hide_index=True,
        column_config={
            "metrica": "Métrica",
            "valor_a_fmt": "Criativo A",
            "valor_b_fmt": "Criativo B",
            "delta_fmt": st.column_config.TextColumn(
                "Δ%", help="(B − A) / A × 100. — quando A=0 ou algum lado "
                          "sem dado."),
            "vencedor_fmt": st.column_config.TextColumn(
                "Vencedor",
                help="Maior em métricas de volume (Impressões, Cliques, "
                     "Leads, Vendas, Receita, ROAS, CTR…); menor em "
                     "CPC/CPL/CPL+12/CAC/No-shows. Sem vencedor em "
                     "Investimento, Frequência, identidade (Campanha/"
                     "Status/rankings) e quando algum lado é '—'."),
        },
    )

    st.caption(
        "Métricas de **plataforma** (Invest., Impressões, Cliques, Link clicks, "
        "Alcance, CTR, CPC, Frequência, Campanha, Status, Quality/Engagement/"
        "Conversion ranking) vêm de **`bi.vw_mkt_criativos`** (fonte oficial). "
        "Métricas de **resultado** (Leads, +12, -12, Agendamentos, "
        "Comparecimentos, No-shows, Deals, Deals ganhos, Vendas, Receita) "
        "são **atribuídas via `odam.mart_ad_funnel_daily`** por `ad_id`. "
        "**Derivadas** (CPL, CPL +12, CAC, ROAS) usam **investimento oficial** "
        "sobre numerador atribuído. "
        "\"—\" indica ausência de atribuição na mart ou denominador zero "
        "(ex.: CPL sem leads, ROAS sem invest)."
    )

# ---------------------------------------------------------------------------
# Tabela detalhada (expander)
# ---------------------------------------------------------------------------
with st.expander("Tabela detalhada (todos os criativos do período)"):
    full = criativos_tabela(df)
    if full.empty:
        st.caption("Sem criativos no período.")
    else:
        st.dataframe(
            full, use_container_width=True, hide_index=True,
            column_config={
                "ad_name": "Anúncio",
                "campaign_name": "Campanha",
                "adset_name": "Conjunto",
                "account_label": "Conta",
                "status_label": "Status",
                "investimento": st.column_config.NumberColumn(
                    "Invest.", format="R$ %.2f"),
                "impressoes": st.column_config.NumberColumn(
                    "Impressões", format="%d"),
                "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
                "cliques": st.column_config.NumberColumn("Cliques", format="%d"),
                "link_clicks": st.column_config.NumberColumn(
                    "Link clicks", format="%d"),
                "ctr": st.column_config.NumberColumn("CTR", format="%.2f%%"),
                "cpc": st.column_config.NumberColumn("CPC", format="R$ %.2f"),
                "frequencia": st.column_config.NumberColumn(
                    "Freq.", format="%.2f"),
                "quality_label": "Quality",
                "engagement_ranking": "Engagement",
                "conversion_ranking": "Conversion",
                "permalink_url": st.column_config.LinkColumn(
                    "Meta Ads", display_text="abrir"),
            },
        )

# ---------------------------------------------------------------------------
# Diagnóstico de cobertura da atribuição mart por ad_id (mesmo padrão de
# Comparar campanhas — mas para o grão de criativo).
# ---------------------------------------------------------------------------
df_cob = safe_run(
    lambda: get_mkt_criativos_cobertura(ctx.data_ini, ctx.data_fim),
    view_label="odam.mart_ad_funnel_daily (cobertura ad_id)",
)
cob = cobertura_criativos_kpis(df_cob)

pct_str = f"{cob['pct_leads_com']:.0f}%".replace(".", ",")
if cob["nivel"] == "baixa":
    cob_header = (
        f"⚠ Cobertura da atribuição por anúncio: parcial ({pct_str}) — "
        f"clique para detalhes"
    )
elif cob["nivel"] == "sem_dados":
    cob_header = "🔍 Cobertura da atribuição por anúncio (sem dados)"
else:
    cob_header = f"🔍 Cobertura da atribuição por anúncio ({pct_str})"

with st.expander(cob_header):
    if cob["nivel"] == "sem_dados":
        st.caption(
            "Sem dados na mart para o período selecionado. Sem leads/"
            "vendas/receita atribuídos a anúncios."
        )
    else:
        st.markdown(
            "Os números abaixo dizem quanto da mart consegue ser "
            "atribuído a um anúncio específico. Linhas com `ad_id` NULL "
            "**não** entram nos cards de resultado, no Top 12 nem no "
            "ranking — comportamento intencional."
        )

        def _fmt_int_pct(n: int, p: float) -> str:
            return f"{int_br(n)} ({pct(p, casas=1)})"

        def _fmt_money_pct(v: float, p: float) -> str:
            return f"{brl(v, casas=2)} ({pct(p, casas=1)})"

        cob_rows = [
            {
                "Métrica": "Leads",
                "Com ad_id": _fmt_int_pct(cob["leads_com"], cob["pct_leads_com"]),
                "Sem ad_id": _fmt_int_pct(cob["leads_sem"], 100 - cob["pct_leads_com"]),
                "Total": int_br(cob["total_leads"]),
            },
            {
                "Métrica": "Vendas",
                "Com ad_id": _fmt_int_pct(cob["vendas_com"], cob["pct_vendas_com"]),
                "Sem ad_id": _fmt_int_pct(cob["vendas_sem"], 100 - cob["pct_vendas_com"]),
                "Total": int_br(cob["total_vendas"]),
            },
            {
                "Métrica": "Receita",
                "Com ad_id": _fmt_money_pct(cob["receita_com"], cob["pct_receita_com"]),
                "Sem ad_id": _fmt_money_pct(cob["receita_sem"], 100 - cob["pct_receita_com"]),
                "Total": brl(cob["total_receita"], casas=2),
            },
        ]
        import pandas as _pd
        st.dataframe(
            _pd.DataFrame(cob_rows),
            use_container_width=True, hide_index=True,
        )

        if cob["nivel"] == "baixa":
            st.caption(
                "**Cobertura baixa.** Os cards de resultado e o ranking "
                "podem parecer incompletos porque várias linhas da mart "
                "estão entrando sem o `ad_id` preenchido. Esse é um "
                "problema de dados na origem (`odam.mart_ad_funnel_daily`)."
            )
