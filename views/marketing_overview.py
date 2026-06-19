"""Visão Geral Marketing — KPIs executivos validados em pgAdmin.

Cards principais lêem `mkt_visao_geral_diario.sql` (regra oficial: investimento
total geral + leads por e-mail único/dia + zoho_deals Ganho/Fechado Ganho).
Tabela "Por canal" e detalhamento continuam usando `bi.vw_mkt_overview` /
`bi.mv_mkt_roas` / `bi.vw_mkt_leads_classificacao`."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd
import streamlit as st

from src.marketing_perf import (
    PAGE_OVERVIEW,
    perf_debug_enabled,
    perf_finalize_page,
    perf_mark_kpi_rendered,
    perf_record_query,
    perf_render_panel,
    perf_reset_run,
    perf_timed_block,
)
from src.marketing_queries import (
    get_mkt_overview,
    get_mkt_visao_geral_diario,
    get_mkt_visao_geral_kpis_canal,
    get_mkt_visao_geral_periodo,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_VISIVEIS_OVERVIEW,
    filtro_canal_ativo,
    filtro_canais_padrao,
    visao_geral_diario,
    visao_geral_kpis,
    visao_geral_kpis_canal,
)
from src.transforms import delta_pct
from src.ui.charts import donut, last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.page import PageContext, start_page
from src.ui.theme import PALETTE, brl, int_br, pct

logger = logging.getLogger("reconecta.marketing.overview")

_OVERVIEW_DETAIL_CACHE = "_mkt_overview_detail_cache"


def _fetch_df(
    name: str,
    fetch_fn: Callable[[], pd.DataFrame],
    data_ini: date,
    data_fim: date,
) -> tuple[pd.DataFrame, str | None]:
    """Executa consulta com `safe_run`, registra perf e devolve (df, erro)."""
    t0 = time.perf_counter()
    err: str | None = None
    df = pd.DataFrame()
    try:
        df = safe_run(fetch_fn, view_label=name)
    except Exception as exc:
        err = str(exc)
        logger.exception("Falha em %s", name)
    elapsed = time.perf_counter() - t0
    if perf_debug_enabled():
        perf_record_query(
            name, data_ini, data_fim, elapsed, len(df),
            page=PAGE_OVERVIEW, error=err,
        )
    return df, err


def _detail_cache_key(data_ini: date, data_fim: date, canais_sel: list[str]) -> str:
    return f"{data_ini.isoformat()}|{data_fim.isoformat()}|{','.join(sorted(canais_sel))}"


def _load_primary_kpis(
    ctx: PageContext,
    prev_ini: date,
    prev_fim: date,
    canal_ativo: bool,
) -> tuple[dict, dict, pd.DataFrame | None, str | None]:
    """Carrega fontes dos KPIs (atual + anterior). Reutiliza kpis_canal se canal ativo."""
    errors: list[str] = []

    if canal_ativo:
        df_kpc_cur, e1 = _fetch_df(
            "mkt_visao_geral_kpis_canal",
            lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
            ctx.data_ini, ctx.data_fim,
        )
        df_kpc_prev, e2 = _fetch_df(
            "mkt_visao_geral_kpis_canal",
            lambda: get_mkt_visao_geral_kpis_canal(prev_ini, prev_fim),
            prev_ini, prev_fim,
        )
        if e1:
            errors.append(e1)
        if e2:
            errors.append(e2)
        canais_sel = list(ctx.selections.get("canal") or [])
        k = visao_geral_kpis_canal(df_kpc_cur, canais_sel)
        kp = visao_geral_kpis_canal(df_kpc_prev, canais_sel)
        return k, kp, df_kpc_cur, "; ".join(errors) or None

    df_period_cur, e1 = _fetch_df(
        "mkt_visao_geral_periodo",
        lambda: get_mkt_visao_geral_periodo(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    df_period_prev, e2 = _fetch_df(
        "mkt_visao_geral_periodo",
        lambda: get_mkt_visao_geral_periodo(prev_ini, prev_fim),
        prev_ini, prev_fim,
    )
    if e1:
        errors.append(e1)
    if e2:
        errors.append(e2)
    k = visao_geral_kpis(df_period_cur)
    kp = visao_geral_kpis(df_period_prev)
    return k, kp, None, "; ".join(errors) or None


def _load_daily_trend(ctx: PageContext) -> tuple[pd.DataFrame, str | None]:
    return _fetch_df(
        "mkt_visao_geral_diario",
        lambda: get_mkt_visao_geral_diario(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )


def _load_channel_breakdown(ctx: PageContext) -> tuple[pd.DataFrame, str | None]:
    return _fetch_df(
        "mkt_visao_geral_kpis_canal",
        lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )


def _load_overview_detail(
    ctx: PageContext,
    canais_sel: list[str],
) -> tuple[pd.DataFrame, str | None]:
    cache_key = _detail_cache_key(ctx.data_ini, ctx.data_fim, canais_sel)
    cached = st.session_state.get(_OVERVIEW_DETAIL_CACHE)
    if (
        isinstance(cached, dict)
        and cached.get("key") == cache_key
        and isinstance(cached.get("df"), pd.DataFrame)
    ):
        return cached["df"], None

    df, err = _fetch_df(
        "bi.vw_mkt_overview",
        lambda: get_mkt_overview(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    if err is None:
        st.session_state[_OVERVIEW_DETAIL_CACHE] = {"key": cache_key, "df": df}
    return df, err


def _render_captions(canal_ativo: bool) -> None:
    if canal_ativo:
        st.caption(
            "ℹ️ Quando há filtro de canal, os KPIs exibem a parcela atribuída "
            "aos canais selecionados. Vendas sem correspondência de lead entram "
            "como **Sem canal**. A **Tendência diária** continua mostrando o "
            "total geral comercial."
        )
    else:
        st.caption(
            "ℹ️ Os KPIs do topo seguem o total geral comercial. Em Geração de "
            "leads, os cards deduplicam o e-mail no período para classificados "
            "(+12 / -12). A Tendência diária continua mostrando a classificação "
            "da própria linha do dia."
        )


def _render_visao_executiva(
    ctx: PageContext,
    k: dict,
    kp: dict,
    dias: int,
) -> None:
    section_title(
        "Visão executiva",
        f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')} · "
        "investimento total + zoho_deals (Ganho/Fechado Ganho)",
    )
    v1, v2, v3, v4, v5, v6 = st.columns(6, gap="small")
    with v1:
        metric_card_v2(
            "Investimento total geral",
            brl(k["investimento_total_geral"], casas=2),
            delta_pct=delta_pct(k["investimento_total_geral"],
                                kp["investimento_total_geral"]),
            hint="Meta + Google + Pinterest",
            accent=True,
        )
    with v2:
        invest_dia = k["investimento_total_geral"] / dias if dias else 0
        invest_dia_prev = kp["investimento_total_geral"] / dias if dias else 0
        metric_card_v2(
            "Investimento / dia",
            brl(invest_dia, casas=2),
            delta_pct=delta_pct(invest_dia, invest_dia_prev),
            hint=f"invest total ÷ {dias} dia{'s' if dias != 1 else ''}",
        )
    with v3:
        metric_card_v2(
            "Vendas novas",
            int_br(k["vendas_novas_total_geral"]),
            delta_pct=delta_pct(k["vendas_novas_total_geral"],
                                kp["vendas_novas_total_geral"]),
            hint="tipo_venda = 'Novo cliente'",
        )
    with v4:
        metric_card_v2(
            "Montante total geral",
            brl(k["montante_total_geral"], casas=2),
            delta_pct=delta_pct(k["montante_total_geral"], kp["montante_total_geral"]),
            hint="SUM(amount) · zoho_deals",
        )
    with v5:
        metric_card_v2(
            "Receita total geral",
            brl(k["receita_total_geral"], casas=2),
            delta_pct=delta_pct(k["receita_total_geral"], kp["receita_total_geral"]),
            hint="SUM(receita) · zoho_deals",
        )
    with v6:
        if k["investimento_total_geral"] > 0:
            metric_card_v2(
                "ROAS total geral",
                f"{k['roas_total_geral']:.2f}x".replace(".", ","),
                delta_pct=delta_pct(k["roas_total_geral"],
                                    kp["roas_total_geral"]),
                hint="montante total ÷ invest total",
                accent=True,
            )
        else:
            metric_card_v2("ROAS total geral", "—",
                           hint="sem investimento no período")
    st.caption(
        "**Total geral comercial** = resultado oficial do CRM/vendas. Inclui "
        "vendas de fontes ainda não totalmente rastreáveis por anúncio "
        "(orgânico, social sellers, direct, link in bio)."
    )


def _render_geracao_leads(
    k: dict,
    kp: dict,
    canal_ativo: bool,
    canais_sel: list[str],
) -> None:
    hint_canal = (
        f"canal: {', '.join(canais_sel)}" if canal_ativo
        else "todos os canais"
    )
    section_title(
        "Geração de leads",
        f"cards: e-mail deduplicado no período por bucket (+12/-12 podem sobrepor) · tendência: classificação da linha do dia · {hint_canal}",
    )
    g1, g2, g3, g4, g5 = st.columns(5, gap="small")
    with g1:
        metric_card_v2(
            "Leads totais",
            int_br(k["leads_totais"]),
            delta_pct=delta_pct(k["leads_totais"], kp["leads_totais"]),
            hint="ext_reconecta.leads · sem testes/internos",
        )
    with g2:
        metric_card_v2(
            "Leads qualificados",
            int_br(k["leads_qualificados"]),
            delta_pct=delta_pct(k["leads_qualificados"], kp["leads_qualificados"]),
            hint="+12 ou -12 · e-mail único no período",
        )
    with g3:
        metric_card_v2(
            "Leads +12",
            int_br(k["leads_mais_12"]),
            delta_pct=delta_pct(k["leads_mais_12"], kp["leads_mais_12"]),
            hint="e-mail com pelo menos uma linha 'Atua +12' no período",
        )
    with g4:
        metric_card_v2(
            "Leads -12",
            int_br(k["leads_menos_12"]),
            delta_pct=delta_pct(k["leads_menos_12"], kp["leads_menos_12"]),
            hint="e-mail com pelo menos uma linha 'Atua -12' no período",
        )
    with g5:
        metric_card_v2(
            "Leads Não atua",
            int_br(k["leads_nao_atua"]),
            delta_pct=delta_pct(k["leads_nao_atua"], kp["leads_nao_atua"]),
            hint="e-mail com pelo menos uma linha 'Não atua' no período",
        )


def _render_eficiencia(k: dict, kp: dict) -> None:
    section_title(
        "Eficiência",
        "CPL e taxa de qualificação calculados sobre o investimento total geral",
    )
    e1, e2, e3 = st.columns(3, gap="small")
    with e1:
        metric_card_v2(
            "CPL",
            brl(k["cpl"], casas=2),
            delta_pct=delta_pct(k["cpl"], kp["cpl"]),
            hint="invest total geral ÷ leads totais",
        )
    with e2:
        metric_card_v2(
            "CPL qualificado",
            brl(k["cpl_qualificado"], casas=2),
            delta_pct=delta_pct(k["cpl_qualificado"], kp["cpl_qualificado"]),
            hint="invest total geral ÷ leads qualificados",
        )
    with e3:
        metric_card_v2(
            "Taxa de qualificação",
            pct(k["taxa_qualificacao"], casas=2),
            delta_pct=delta_pct(k["taxa_qualificacao"], kp["taxa_qualificacao"]),
            hint="qualificados ÷ leads totais",
        )


def _render_tendencia_diaria(df_vg_all: pd.DataFrame) -> None:
    import plotly.graph_objects as go

    section_title("Tendência diária",
                  "investimento × leads totais × leads qualificados × leads +12")
    st.caption(
        "Na tendência diária, `Leads +12 / -12 / Não atua` usam a classificação "
        "da própria linha do dia com e-mail único por dia. Nos cards do período, "
        "os buckets `+12 / -12 / Não atua` são contados por e-mail único dentro "
        "de cada classificação e podem se sobrepor."
    )
    diario = visao_geral_diario(df_vg_all)
    if diario.empty:
        st.info("Sem dados diários no período.")
        return

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["investimento_total_geral"],
        name="Investimento total",
        marker=dict(color=PALETTE["gold"],
                    line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_totais"], name="Leads totais",
        line=dict(color=PALETTE["wine_light"], width=2.5),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["leads_totais"], int_br),
        textposition="top center",
        textfont=dict(color=PALETTE["wine_light"], size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_qualificados"],
        name="Leads qualificados",
        line=dict(color="#7C3AED", width=2.5, dash="dot"),
        mode="lines+markers+text", marker=dict(size=6, color="#7C3AED"),
        text=last_point_text(diario["leads_qualificados"], int_br),
        textposition="top center",
        textfont=dict(color="#7C3AED", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} qualif<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_mais_12"],
        name="Leads +12",
        line=dict(color="#1D4ED8", width=2.2, dash="dash"),
        mode="lines+markers+text", marker=dict(size=6, color="#1D4ED8"),
        text=last_point_text(diario["leads_mais_12"], int_br),
        textposition="bottom center",
        textfont=dict(color="#1D4ED8", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads +12<extra></extra>",
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
        yaxis2=dict(title="Leads", overlaying="y", side="right",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=PALETTE["wine_light"])),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"],
                     tickfont=dict(color=PALETTE["text_subtle"], size=11))
    st.plotly_chart(fig, use_container_width=True)


def _render_por_canal(
    df_kpc_all: pd.DataFrame,
    canal_ativo: bool,
    canais_sel: list[str],
) -> None:
    section_title("Por canal",
                  "investimento + leads + financeiro atribuído por canal")
    if canal_ativo:
        df_canal = (
            df_kpc_all.set_index("canal")
                      .reindex(canais_sel, fill_value=0)
                      .reset_index()
        )
    else:
        df_canal = df_kpc_all.copy()

    col_donut, col_tab = st.columns([1, 2], gap="large")
    with col_donut:
        donut_data = (
            df_canal[df_canal["leads_totais"] > 0][["canal", "leads_totais"]].copy()
        )
        if donut_data.empty:
            st.caption("Sem leads no período/filtro.")
        else:
            st.plotly_chart(
                donut(donut_data, names="canal", values="leads_totais",
                      height=300, total_label="Leads"),
                use_container_width=True,
            )
    with col_tab:
        if df_canal.empty:
            st.caption("Sem canais no período selecionado.")
        else:
            cols_show = [
                "canal", "investimento_total_geral",
                "leads_totais", "leads_qualificados",
                "leads_mais_12", "leads_menos_12", "leads_nao_atua",
                "vendas_total_geral", "vendas_novas_total_geral",
                "montante_total_geral", "receita_total_geral",
                "roas_total_geral", "cpl", "cpl_qualificado", "cpl_mais_12",
                "taxa_qualificacao", "taxa_qualificacao_mais_12",
                "ticket_medio",
            ]
            col_cfg = {
                "canal": "Canal",
                "investimento_total_geral": st.column_config.NumberColumn(
                    "Investimento", format="R$ %.2f"),
                "leads_totais": st.column_config.NumberColumn(
                    "Leads", format="%d"),
                "leads_qualificados": st.column_config.NumberColumn(
                    "Qualificados", format="%d"),
                "leads_mais_12": st.column_config.NumberColumn(
                    "+12", format="%d"),
                "leads_menos_12": st.column_config.NumberColumn(
                    "-12", format="%d"),
                "leads_nao_atua": st.column_config.NumberColumn(
                    "Não atua", format="%d"),
                "vendas_total_geral": st.column_config.NumberColumn(
                    "Vendas", format="%d"),
                "vendas_novas_total_geral": st.column_config.NumberColumn(
                    "Vendas novas", format="%d"),
                "montante_total_geral": st.column_config.NumberColumn(
                    "Montante", format="R$ %.2f"),
                "receita_total_geral": st.column_config.NumberColumn(
                    "Receita", format="R$ %.2f"),
                "roas_total_geral": st.column_config.NumberColumn(
                    "ROAS", format="%.2fx"),
                "cpl": st.column_config.NumberColumn(
                    "CPL", format="R$ %.2f"),
                "cpl_qualificado": st.column_config.NumberColumn(
                    "CPL qualificado", format="R$ %.2f"),
                "cpl_mais_12": st.column_config.NumberColumn(
                    "CPL +12", format="R$ %.2f"),
                "taxa_qualificacao": st.column_config.NumberColumn(
                    "Taxa qualificação", format="%.2f%%"),
                "taxa_qualificacao_mais_12": st.column_config.NumberColumn(
                    "Tx Qualif +12", format="%.2f%%"),
                "ticket_medio": st.column_config.NumberColumn(
                    "Ticket médio", format="R$ %.2f"),
            }
            st.dataframe(
                df_canal[cols_show].sort_values(
                    "investimento_total_geral", ascending=False
                ),
                use_container_width=True, hide_index=True,
                column_config=col_cfg,
            )


def _render_detalhamento(
    ctx: PageContext,
    col_map: dict[str, str],
    canais_sel: list[str],
) -> None:
    detail_exp = st.expander(
        "Detalhamento por dia × canal (tabela completa)",
        on_change="rerun",
    )
    if not detail_exp.open:
        return

    with detail_exp:
        try:
            with st.spinner("Carregando detalhamento…"):
                df_ov_all, err = _load_overview_detail(ctx, canais_sel)
            if err:
                st.error(
                    "Não foi possível carregar o detalhamento por dia × canal. "
                    "Tente novamente ou altere o período."
                )
                if perf_debug_enabled():
                    st.caption(f"Detalhe técnico: {err}")
                return
            df_ov = ctx.refilter(df_ov_all, col_map)
            st.dataframe(
                df_ov.sort_values(["data_ref", "canal"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "data_ref": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "canal": "Canal",
                    "investimento": st.column_config.NumberColumn(
                        "Invest.", format="R$ %.2f"),
                    "impressoes": st.column_config.NumberColumn("Impressões", format="%d"),
                    "cliques": st.column_config.NumberColumn("Cliques", format="%d"),
                    "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
                    "leads": st.column_config.NumberColumn("Leads", format="%d"),
                    "leads_qualificados": st.column_config.NumberColumn(
                        "Qualif.", format="%d"),
                    "leads_qualif_mais_12": st.column_config.NumberColumn(
                        "+12", format="%d"),
                    "leads_qualif_menos_12": st.column_config.NumberColumn(
                        "-12", format="%d"),
                },
            )
        except Exception as exc:
            logger.exception("Falha ao renderizar detalhamento")
            st.error(
                "Não foi possível carregar o detalhamento por dia × canal."
            )
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {exc}")


def _has_period_data(k: dict) -> bool:
    return any(
        k.get(c, 0)
        for c in (
            "investimento_total_geral",
            "leads_totais",
            "vendas_total_geral",
            "montante_total_geral",
            "receita_total_geral",
        )
    )


def main() -> None:
    if perf_debug_enabled():
        perf_reset_run(PAGE_OVERVIEW)

    ctx = start_page(
        title="Visão Geral Marketing",
        subtitle="Investimento, leads e resultado oficial CRM/comercial",
        filters=["canal"],
    )
    col_map = {"canal": "canal"}

    ctx.apply_filters(filtro_canais_padrao(CANAIS_VISIVEIS_OVERVIEW), col_map)

    canais_sel: list[str] = list(ctx.selections.get("canal") or [])
    canal_ativo = filtro_canal_ativo(canais_sel)

    dias = (ctx.data_fim - ctx.data_ini).days + 1
    prev_fim = ctx.data_ini - timedelta(days=1)
    prev_ini = prev_fim - timedelta(days=dias - 1)

    # --- P1/P2: KPIs principais ---
    kpi_err: str | None = None
    df_kpc_reuse: pd.DataFrame | None = None
    try:
        with perf_timed_block("KPIs principais", page=PAGE_OVERVIEW):
            k, kp, df_kpc_reuse, kpi_err = _load_primary_kpis(
                ctx, prev_ini, prev_fim, canal_ativo,
            )
    except Exception as exc:
        logger.exception("Falha ao carregar KPIs principais")
        k = visao_geral_kpis(pd.DataFrame())
        kp = visao_geral_kpis(pd.DataFrame())
        kpi_err = str(exc)

    if kpi_err:
        st.error(
            "Não foi possível carregar os indicadores principais. "
            "Os cards podem exibir zeros até a consulta ser concluída."
        )
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {kpi_err}")

    if not _has_period_data(k) and (df_kpc_reuse is None or df_kpc_reuse.empty):
        st.warning("Sem dados para o período selecionado.")
        perf_finalize_page(PAGE_OVERVIEW)
        perf_render_panel(PAGE_OVERVIEW)
        st.stop()

    _render_captions(canal_ativo)
    perf_mark_kpi_rendered(PAGE_OVERVIEW)

    _render_visao_executiva(ctx, k, kp, dias)
    _render_geracao_leads(k, kp, canal_ativo, canais_sel)
    _render_eficiencia(k, kp)

    # --- P3: Tendência ---
    df_vg_all = pd.DataFrame()
    try:
        with st.spinner("Carregando tendência diária…"):
            with perf_timed_block("Tendência diária", page=PAGE_OVERVIEW):
                df_vg_all, trend_err = _load_daily_trend(ctx)
        if trend_err:
            st.error("Não foi possível carregar a tendência diária.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {trend_err}")
        else:
            _render_tendencia_diaria(df_vg_all)
    except Exception as exc:
        logger.exception("Falha na seção Tendência diária")
        section_title("Tendência diária",
                      "investimento × leads totais × leads qualificados × leads +12")
        st.error("Não foi possível carregar a tendência diária.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")

    # --- P4: Por canal ---
    df_kpc_all = df_kpc_reuse if canal_ativo else pd.DataFrame()
    if not canal_ativo:
        try:
            with perf_timed_block("Por canal", page=PAGE_OVERVIEW):
                df_kpc_all, canal_err = _load_channel_breakdown(ctx)
            if canal_err:
                section_title("Por canal",
                              "investimento + leads + financeiro atribuído por canal")
                st.error("Não foi possível carregar a seção Por canal.")
                if perf_debug_enabled():
                    st.caption(f"Detalhe técnico: {canal_err}")
            else:
                _render_por_canal(df_kpc_all, canal_ativo, canais_sel)
        except Exception as exc:
            logger.exception("Falha na seção Por canal")
            section_title("Por canal",
                          "investimento + leads + financeiro atribuído por canal")
            st.error("Não foi possível carregar a seção Por canal.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {exc}")
    else:
        _render_por_canal(df_kpc_all, canal_ativo, canais_sel)

    # --- P5: Detalhamento on-demand ---
    _render_detalhamento(ctx, col_map, canais_sel)

    perf_finalize_page(PAGE_OVERVIEW)
    perf_render_panel(PAGE_OVERVIEW)


main()
