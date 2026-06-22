"""Criativos — performance dos anúncios Meta.

Consome `bi.vw_mkt_criativos` (Meta-only, enriquecida com `odam.meta_ads_creatives`).
Página dedicada a análise de criativo: KPIs · distribuições · grid de
thumbnails · tabela detalhada com rankings (quality, engagement, conversion)."""
from __future__ import annotations

import html as html_lib
import logging
import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd
import streamlit as st

from src.marketing_perf import (
    PAGE_CREATIVES,
    perf_debug_enabled,
    perf_finalize_page,
    perf_mark_funil_rendered,
    perf_mark_kpi_rendered,
    perf_mark_selector_rendered,
    perf_mark_top12_rendered,
    perf_record_query,
    perf_render_panel,
    perf_reset_run,
    perf_set_context,
    perf_timed_block,
)
from src.marketing_queries import (
    get_mkt_criativo_funil,
    get_mkt_criativos,
    get_mkt_criativos_anuncios_fdw,
    get_mkt_criativos_leads_utm_audit,
    get_mkt_criativos_resultados,
    get_mkt_paginas_variantes,
    get_mkt_top_criativos_por_nome,
)
from src.marketing_safe import safe_run
from src.repositories import (
    get_investimento_diario,
    get_leads_visao_geral,
    get_mkt_campanhas_vendas_oficiais,
    get_prevendas_overview_diario,
)
from src.marketing_transforms import (
    agendamentos_one_page_oficial,
    comparecimentos_one_page_oficial,
    vendas_one_page_oficial,
    agregar_criativos_por_utm_content,
    compara_criativos_utm_content,
    criativo_funil_etapas,
    criativo_funil_kpis,
    criativo_utm_content_kpis,
    criativos_kpis,
    criativos_por_quality,
    criativos_por_status,
    criativos_ranking,
    criativos_top_por_nome_ranking,
    lista_criativos_funil,
    lista_criativos_utm_content,
    normalize_status,
)
from src.transforms import delta_pct
from src.ui.charts import donut
from src.ui.components import metric_card_v2, section_title
from src.ui.marketing_components import render_funil_selecionado
from src.ui.page import PageContext, start_page
from src.ui.theme import PALETTE, brl, int_br, pct

logger = logging.getLogger("reconecta.marketing.creatives")

_TODOS_NORM = "__todos__"

_COL_MAP = {"campanha": "campaign_name", "status": "status_label"}

_FUNIL_EXPANDER_MD = (
    "- **Universo do funil:** `ext_reconecta.leads` no período, com "
    "  `utm_content` definindo o criativo do lead.\n"
    "- **Match lead → deal (vendas):** prioridade `e-mail` "
    "  (primário) → `telefone` limpo ≥ 8 dígitos (fallback). "
    "  `zoho_id` e `session_id` foram REMOVIDOS — operação validou "
    "  que e-mail é mais confiável.\n"
    "- **Atribuição cross-período:** a venda fica no período de "
    "  `data_hora_compra`, mas o lead atribuído pode ter sido criado "
    "  ANTES. Para cada deal ganho, o sistema busca o lead histórico "
    "  com `created_at <= data_hora_compra`.\n"
    "- **Desempate quando >1 lead casa o mesmo deal:**\n"
    "  1. match por e-mail vence telefone;\n"
    "  2. lead com origem útil (utm/link_in_bio/social) vence;\n"
    "  3. aparição mais recente antes da venda;\n"
    "  4. `lead_id` (determinístico).\n"
    "- **'Todos os resultados':** totais oficiais do período — leads "
    "  daily-distinct por e-mail (regra Visão Geral), vendas novas do "
    "  CRM, investimento total de mídia.\n"
    "- **'Totais vinculados aos leads':** soma per-criativo do funil "
    "  — só o que foi de fato vinculado/atribuído (útil pra auditoria "
    "  vs. universo oficial).\n"
    "- **Leads / +12 / -12 / Agendamentos / Comparecimentos:** "
    "  lead-centric, 1 e-mail conta 1× por criativo "
    "  (`COUNT(DISTINCT email_norm)`).\n"
    "- **Agendamentos:** atividades `Consulta` ou `Indicação` em "
    "  `zoho_activities` no período, **excluindo `status_reuniao` "
    "  vencido** (`COALESCE(status_reuniao,'') NOT ILIKE '%vencid%'`) — "
    "  alinhado com a regra da Visão Geral comercial.\n"
    "- **Comparecimentos:** subset dos agendamentos com "
    "  `status_reuniao = 'Concluída'`.\n"
    "- **Vendas novas:** deal-centric — 1 row por deal (sem "
    "  duplicação), `stage IN ('Ganho','Fechado Ganho')` e "
    "  `tipo_venda = 'Novo cliente'`.\n"
    "- **Filtros de e-mail de teste:** `@teste`, `teste@`, `smarts`, "
    "  `reconecta` removidos do universo de leads em todas as etapas.\n"
    "- **Aplicações (etapa do funil):** "
    "`fdw_reconecta.typeform_aplicacoes` cruzado por e-mail dos leads "
    "do criativo/seleção (`dados_completos = TRUE`, dedupe e-mail/dia; "
    "leads `timestamp::date`, typeform `created_at::date`). Em **Todos os resultados**, "
    "aplicações = todas do Typeform no período (igual One Page); em "
    "criativo específico, só aplicações com lead no criativo. "
    "Exibimos total, % sobre leads, +12/-12, CPA e CPA +12."
)


def _restrict_resultados_aos_ads(
    df_resultados: pd.DataFrame | None,
    df_view: pd.DataFrame,
) -> pd.DataFrame:
    if df_resultados is None or df_resultados.empty or df_view.empty:
        return df_resultados if df_resultados is not None else pd.DataFrame()
    ads_visiveis = set(df_view["ad_id"].dropna().astype(str).unique())
    if not ads_visiveis:
        return df_resultados.iloc[0:0]
    res = df_resultados.copy()
    res["ad_id"] = res["ad_id"].astype(str)
    return res[res["ad_id"].isin(ads_visiveis)]


def _fetch_df(
    name: str,
    fetch_fn: Callable[[], pd.DataFrame],
    data_ini: date,
    data_fim: date,
) -> tuple[pd.DataFrame, str | None]:
    """Executa consulta com safe_run, registra perf e devolve (df, erro)."""
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
        cols = len(df.columns) if not df.empty else 0
        perf_record_query(
            name, data_ini, data_fim, elapsed, len(df),
            page=PAGE_CREATIVES, cols=cols, error=err,
        )
    return df, err


def _prev_period(data_ini: date, data_fim: date) -> tuple[date, date]:
    dias = (data_fim - data_ini).days + 1
    prev_fim = data_ini - timedelta(days=1)
    prev_ini = prev_fim - timedelta(days=dias - 1)
    return prev_ini, prev_fim


def _normalize_criativos_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["status_label"] = out["effective_status"].apply(normalize_status)
    return out


def _load_p1_data(
    ctx: PageContext,
) -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame,
    pd.DataFrame, pd.DataFrame, dict, dict, str | None,
]:
    """Performance Meta: view + mart (atual e anterior para deltas)."""
    errors: list[str] = []
    prev_ini, prev_fim = _prev_period(ctx.data_ini, ctx.data_fim)

    df_all, e1 = _fetch_df(
        "bi.vw_mkt_criativos",
        lambda: get_mkt_criativos(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    df_all = _normalize_criativos_df(df_all)
    df = ctx.apply_filters(df_all, _COL_MAP)

    df_prev_all, e2 = _fetch_df(
        "bi.vw_mkt_criativos (periodo anterior)",
        lambda: get_mkt_criativos(prev_ini, prev_fim),
        prev_ini, prev_fim,
    )
    df_prev_all = _normalize_criativos_df(df_prev_all)
    df_prev = (
        ctx.refilter(df_prev_all, _COL_MAP)
        if not df_prev_all.empty else df_prev_all
    )

    df_resultados, e3 = _fetch_df(
        "odam.mart_ad_funnel_daily (criativos)",
        lambda: get_mkt_criativos_resultados(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    df_resultados_prev, e4 = _fetch_df(
        "odam.mart_ad_funnel_daily (criativos, periodo anterior)",
        lambda: get_mkt_criativos_resultados(prev_ini, prev_fim),
        prev_ini, prev_fim,
    )
    for e in (e1, e2, e3, e4):
        if e:
            errors.append(e)

    df_res_f = _restrict_resultados_aos_ads(df_resultados, df)
    df_res_prev_f = _restrict_resultados_aos_ads(df_resultados_prev, df_prev)
    k = criativos_kpis(df, df_res_f)
    kp = criativos_kpis(df_prev, df_res_prev_f)
    return (
        df_all, df, df_prev, df_res_f, df_res_prev_f,
        df_resultados, k, kp, "; ".join(errors) or None,
    )


def _resolve_vendas_novas_oficial(
    vendas_count: int | None,
    *,
    leads_totais: int | None,
    investimento: float | None,
    agendamentos: int | None,
    comparecimentos: int | None,
) -> int | None:
    if vendas_count is None:
        return None
    if vendas_count == 0 and all(
        v is None
        for v in (leads_totais, investimento, agendamentos, comparecimentos)
    ):
        return None
    return vendas_count


def _load_oficiais_todos(ctx: PageContext) -> dict:
    """Fontes oficiais — somente para __todos__."""
    _df_leads, _ = _fetch_df(
        "leads_visao_geral",
        lambda: get_leads_visao_geral(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    _leads_totais = (
        int(len(_df_leads))
        if _df_leads is not None and not _df_leads.empty
        else None
    )

    _df_vendas, err_vendas = _fetch_df(
        "mkt_campanhas_vendas_oficiais",
        lambda: get_mkt_campanhas_vendas_oficiais(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    _vendas_count: int | None = None
    if (
        not err_vendas
        and _df_vendas is not None
        and not _df_vendas.empty
        and "vendas" in _df_vendas.columns
    ):
        _vendas_count = int(_df_vendas["vendas"].fillna(0).iloc[0])

    _df_inv, _ = _fetch_df(
        "investimento_diario",
        lambda: get_investimento_diario(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    _df_prev, _ = _fetch_df(
        "prevendas_overview_diario",
        lambda: get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    _agendamentos = agendamentos_one_page_oficial(_df_prev)
    _comparecimentos = comparecimentos_one_page_oficial(_df_prev)
    _vendas = vendas_one_page_oficial(_df_prev)
    _investimento = (
        float(_df_inv["investimento_total"].fillna(0).sum())
        if (_df_inv is not None and not _df_inv.empty
            and "investimento_total" in _df_inv.columns)
        else None
    )
    _vendas_novas = _resolve_vendas_novas_oficial(
        _vendas_count,
        leads_totais=_leads_totais,
        investimento=_investimento,
        agendamentos=_agendamentos,
        comparecimentos=_comparecimentos,
    )

    _oficiais_status = [
        ("leads", _leads_totais),
        ("vendas", _vendas_novas),
        ("investimento", _investimento),
        ("agendamentos", _agendamentos),
        ("comparecimentos", _comparecimentos),
        ("vendas", _vendas or _vendas_novas),
    ]
    _faltando = [k for k, v in _oficiais_status if v is None]
    if _faltando:
        st.caption(
            "⚠ Fonte oficial indisponível para: "
            + ", ".join(f"`{k}`" for k in _faltando)
            + ". 'Todos os resultados' está em modo soma do df (= 'Totais "
            "vinculados aos leads')."
        )

    return {
        "leads_totais_oficial": _leads_totais,
        "vendas_novas_oficial": _vendas_novas,
        "investimento_oficial": _investimento,
        "agendamentos_oficial": _agendamentos,
        "comparecimentos_oficial": _comparecimentos,
        "vendas_oficial": _vendas,
    }


def _oficiais_loader_factory(ctx: PageContext) -> Callable[[str], dict]:
    def _loader(sel: str) -> dict:
        if sel != _TODOS_NORM:
            return {}
        with st.spinner("Carregando totais oficiais do período…"):
            with perf_timed_block("Fontes oficiais (__todos__)", page=PAGE_CREATIVES):
                return _load_oficiais_todos(ctx)

    return _loader


def _render_performance_meta(
    ctx: PageContext,
    k: dict,
    kp: dict,
) -> None:
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


def _render_funil_section(ctx: PageContext) -> None:
    try:
        with st.spinner("Carregando funil por criativo…"):
            with perf_timed_block("Funil criativo_funil", page=PAGE_CREATIVES):
                df_cri_funil, err = _fetch_df(
                    "mkt_criativo_funil",
                    lambda: get_mkt_criativo_funil(ctx.data_ini, ctx.data_fim),
                    ctx.data_ini, ctx.data_fim,
                )
        if err:
            section_title(
                "Funil do criativo selecionado",
                "investimento → vendas novas",
            )
            st.error(
                "Não foi possível carregar o funil de criativos. "
                "Os cards superiores permanecem disponíveis."
            )
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {err}")
            return

        render_funil_selecionado(
            df_funil=df_cri_funil,
            key_col="ad_name_norm",
            entity_label="Criativo",
            section_title_text="Funil do criativo selecionado",
            sel_state_key="cri_funil_selecionado",
            lista_fn=lambda df, sb: lista_criativos_funil(df, sb),
            kpis_fn=criativo_funil_kpis,
            etapas_fn=criativo_funil_etapas,
            oficiais_loader=_oficiais_loader_factory(ctx),
            on_selector_rendered=lambda: perf_mark_selector_rendered(PAGE_CREATIVES),
            on_funil_cards_rendered=lambda: perf_mark_funil_rendered(PAGE_CREATIVES),
            marketing_funil_unico=True,
            data_ini=ctx.data_ini,
            data_fim=ctx.data_fim,
            nivel="criativo",
            auditoria_state_key="cri_funil_auditoria",
            empty_msg="Sem criativos com investimento ou leads no período.",
            caption=(
                "Criativos usam `utm_content` como origem principal. Vendas são "
                "atribuídas ao lead histórico por e-mail/telefone antes da compra."
            ),
            expander_md=_FUNIL_EXPANDER_MD,
        )
    except Exception as exc:
        logger.exception("Falha na secao Funil do criativo")
        section_title(
            "Funil do criativo selecionado",
            "investimento → vendas novas",
        )
        st.error("Não foi possível renderizar o funil do criativo selecionado.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")


def _render_distribuicoes(df: pd.DataFrame) -> None:
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
    "Não atua (maior)":         ("leads_nao_atua", False),
    "Aplicações (maior)":       ("aplicacoes",     False),
    "Apl. +12 (maior)":         ("aplicacoes_mais_12", False),
    "Apl. -12 (maior)":         ("aplicacoes_menos_12", False),
    "Agendamentos (maior)":     ("agendamentos",   False),
    "Vendas (maior)":           ("vendas",         False),
    "Receita (maior)":          ("valor_receita", False),
    "ROAS (maior)":             ("roas",           False),
    "CAC (menor)":              ("cac",            True),
    "CPL (menor)":              ("cpl",            True),
    "CPL +12 (menor)":          ("cpl_mais_12",    True),
}


def _render_resultado_atribuido_top12(top: pd.DataFrame) -> None:
    """Resumo consolidado das linhas do `top` — só métricas presentes no ranking."""
    st.markdown(
        '<div style="height:2rem" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    section_title(
        "Resultado atribuído",
        "soma dos criativos exibidos no Top 12 atual",
    )

    resultado_base = top.copy()

    def _usable_series(df: pd.DataFrame, col: str) -> pd.Series | None:
        if col not in df.columns:
            return None
        ser = pd.to_numeric(df[col], errors="coerce")
        if not ser.notna().any():
            return None
        return ser

    def _sum_series(ser: pd.Series | None) -> float | None:
        if ser is None:
            return None
        return float(ser.fillna(0).sum())

    def _emit_row(items: list[tuple[str, str, str | None]]) -> None:
        if not items:
            return
        cols = st.columns(len(items), gap="small")
        for col, (label, value, hint) in zip(cols, items):
            with col:
                metric_card_v2(label, value, hint=hint)

    invest_s = _usable_series(resultado_base, "investimento")
    invest_t = _sum_series(invest_s)

    leads_reais_s = _usable_series(resultado_base, "leads_reais")
    if leads_reais_s is None:
        leads_reais_s = _usable_series(resultado_base, "leads_total")
    leads_reais_t = _sum_series(leads_reais_s)

    leads_meta_s = _usable_series(resultado_base, "leads_meta")
    leads_meta_t = _sum_series(leads_meta_s)

    lm12_s = _usable_series(resultado_base, "leads_mais_12")
    lm12_t = _sum_series(lm12_s)

    lmen12_s = _usable_series(resultado_base, "leads_menos_12")
    lmen12_t = _sum_series(lmen12_s)

    lnao_s = _usable_series(resultado_base, "leads_nao_atua")
    lnao_t = _sum_series(lnao_s)

    imp_s = _usable_series(resultado_base, "impressoes")
    imp_t = _sum_series(imp_s)

    cli_s = _usable_series(resultado_base, "cliques")
    cli_t = _sum_series(cli_s) if cli_s is not None else None
    if imp_s is not None and cli_s is None:
        cli_t = 0.0

    row1: list[tuple[str, str, str | None]] = []
    if invest_t is not None and invest_t > 0:
        inv_fmt = (
            brl(invest_t, casas=0)
            if invest_t == int(invest_t)
            else brl(invest_t, casas=2)
        )
        row1.append((
            "Investimento total",
            inv_fmt,
            "Σ investimento dos criativos visíveis no ranking",
        ))
    if leads_reais_t is not None:
        row1.append((
            "Leads reais",
            int_br(int(round(leads_reais_t))),
            "Σ leads reais (ou leads_total) dos cards",
        ))
    if leads_meta_t is not None:
        row1.append((
            "Leads Meta",
            int_br(int(round(leads_meta_t))),
            "Σ leads_meta dos cards",
        ))
    if lm12_t is not None:
        row1.append((
            "Leads +12",
            int_br(int(round(lm12_t))),
            "Σ classificado Atua +12",
        ))
    if lmen12_t is not None:
        row1.append((
            "Leads -12",
            int_br(int(round(lmen12_t))),
            "Σ classificado Atua -12",
        ))
    if lnao_t is not None:
        row1.append((
            "Não atua",
            int_br(int(round(lnao_t))),
            "Σ classificado Não atua",
        ))

    apl_s = _usable_series(resultado_base, "aplicacoes")
    apl_t = _sum_series(apl_s)

    apl12_s = _usable_series(resultado_base, "aplicacoes_mais_12")
    apl12_t = _sum_series(apl12_s)

    aplmen12_s = _usable_series(resultado_base, "aplicacoes_menos_12")
    aplmen12_t = _sum_series(aplmen12_s)

    if apl_t is not None:
        row1.append((
            "Aplicações",
            int_br(int(round(apl_t))),
            "Σ aplicações typeform (e-mail cruzado com leads do criativo)",
        ))
    if apl12_t is not None:
        row1.append((
            "Apl. +12",
            int_br(int(round(apl12_t))),
            "Σ classificado Atua +12 (typeform)",
        ))
    if aplmen12_t is not None:
        row1.append((
            "Apl. -12",
            int_br(int(round(aplmen12_t))),
            "Σ classificado Atua -12 (typeform)",
        ))

    _emit_row(row1)

    row2: list[tuple[str, str, str | None]] = []
    if (
        invest_t is not None
        and invest_t > 0
        and leads_reais_t is not None
        and leads_reais_t > 0
    ):
        row2.append((
            "CPL real",
            brl(invest_t / leads_reais_t, casas=2),
            "Σ invest ÷ Σ leads reais",
        ))
    if invest_t is not None and invest_t > 0 and lm12_t is not None and lm12_t > 0:
        row2.append((
            "CPL +12",
            brl(invest_t / lm12_t, casas=2),
            "Σ invest ÷ Σ leads +12",
        ))
    if invest_t is not None and invest_t > 0 and leads_meta_t is not None and leads_meta_t > 0:
        row2.append((
            "CPL Meta",
            brl(invest_t / leads_meta_t, casas=2),
            "Σ invest ÷ Σ leads Meta",
        ))
    if imp_t is not None and imp_t > 0 and cli_t is not None:
        ctr_pct = (cli_t / imp_t) * 100.0
        row2.append((
            "CTR",
            pct(ctr_pct, casas=2),
            "Σ cliques ÷ Σ impressões (totais no ranking)",
        ))
    if invest_t is not None and invest_t > 0 and cli_t is not None and cli_t > 0:
        row2.append((
            "CPC",
            brl(invest_t / cli_t, casas=2),
            "Σ invest ÷ Σ cliques",
        ))

    ci_parts: list[str] = []
    ci_hints: list[str] = []
    if cli_s is not None and cli_t is not None:
        ci_parts.append(int_br(int(round(cli_t))))
        ci_hints.append("Cliques")
    if imp_s is not None and imp_t is not None:
        ci_parts.append(int_br(int(round(imp_t))))
        ci_hints.append("Impressões")
    if ci_parts:
        row2.append((
            "Cliques / Impressões",
            " · ".join(ci_parts),
            " · ".join(ci_hints) + " (totais no ranking)",
        ))

    _emit_row(row2)


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

    # Linha 2 — Leads · +12 · Não atua · CPL (lp_form + fdw). NaN ⇒ "—" (sem
    # atribuição); Não atua cai em 0 quando ausente/nulo; CPL com leads=0
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
    nao_atua_raw = row.get("leads_nao_atua")
    cpl_raw = row.get("cpl")
    apl_raw = row.get("aplicacoes")
    apl12_raw = row.get("aplicacoes_mais_12")
    aplmen12_raw = row.get("aplicacoes_menos_12")
    leads_fmt = "—" if _missing(leads_raw) else int_br(int(leads_raw))
    mais12_fmt = "—" if _missing(mais12_raw) else int_br(int(mais12_raw))
    nao_atua_fmt = int_br(0 if _missing(nao_atua_raw) else int(nao_atua_raw))
    cpl_fmt = "—" if _missing(cpl_raw) else brl(float(cpl_raw), casas=2)
    apl_fmt = int_br(0 if _missing(apl_raw) else int(apl_raw))
    apl12_fmt = int_br(0 if _missing(apl12_raw) else int(apl12_raw))
    aplmen12_fmt = int_br(0 if _missing(aplmen12_raw) else int(aplmen12_raw))

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

    tip_chunks: list[str] = []
    if (
        not _missing(row.get("qtd_ad_ids"))
        and not _missing(row.get("qtd_campaigns"))
        and not _missing(row.get("qtd_adsets"))
    ):
        tip_chunks.append(
            f'{int(row["qtd_ad_ids"])} anúncios · '
            f'{int(row["qtd_campaigns"])} campanhas · '
            f'{int(row["qtd_adsets"])} conjuntos'
        )
    if not _missing(row.get("leads_meta")):
        tip_chunks.append(f'Leads Meta: {int(row["leads_meta"])}')
    if not _missing(row.get("cpl_meta")):
        tip_chunks.append(f'CPL Meta: {brl(float(row["cpl_meta"]), casas=2)}')
    tip_chunks.append("CPL = invest fdw ÷ leads reais (e-mail único/dia)")
    tip_chunks.append(
        "Apl. = typeform cruzado por e-mail dos leads do criativo (dedupe e-mail/dia)"
    )
    card_tip_esc = html_lib.escape(" · ".join(tip_chunks)[:300])

    return (
        f'<div title="{card_tip_esc}" style="background:{PALETTE["card"]};'
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
        # Linha 2 — leads (Leads · +12 · Não atua · CPL)
        f'<div style="display:flex;gap:10px;margin-top:8px;'
        f'padding-top:8px;border-top:1px solid {PALETTE["border"]};">'
        f'<div><div style="{metric_label_css}">Leads</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(leads_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">+12</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(mais12_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">Não atua</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(nao_atua_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">CPL</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(cpl_fmt)}</div></div>'
        f'</div>'
        # Linha 3 — aplicações typeform (Apl. · Apl +12 · Apl -12)
        f'<div style="display:flex;gap:10px;margin-top:6px;">'
        f'<div><div style="{metric_label_css}">Apl.</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(apl_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">Apl +12</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(apl12_fmt)}</div></div>'
        f'<div><div style="{metric_label_css}">Apl -12</div>'
        f'<div style="{metric_value_mart_css}">{html_lib.escape(aplmen12_fmt)}</div></div>'
        f'</div>'
        f'</div></div>'
    )


def _render_top12(
    ctx: PageContext,
    df: pd.DataFrame,
    df_resultados_filtered: pd.DataFrame,
) -> None:
    head_l, head_r = st.columns([3, 1.2], vertical_alignment="bottom")
    with head_l:
        section_title(
            "Top 12 criativos",
            "por nome (utm_content = ad_name) · mídia fdw + leads ext_reconecta + "
            "aplicações typeform · investimento no período",
        )
    with head_r:
        sort_choice = st.selectbox(
            "Ordenar por",
            list(SORT_OPTIONS.keys()),
            index=0, key="creatives_sort",
            label_visibility="collapsed",
        )

    sort_field, ascending = SORT_OPTIONS[sort_choice]
    top = pd.DataFrame()
    top_err: str | None = None

    try:
        with st.spinner("Carregando ranking Top 12 por nome…"):
            with perf_timed_block("Top 12 criativos", page=PAGE_CREATIVES):
                df_top_nome, top_err = _fetch_df(
                    "mkt_top_criativos_por_nome",
                    lambda: get_mkt_top_criativos_por_nome(
                        ctx.data_ini, ctx.data_fim,
                    ),
                    ctx.data_ini, ctx.data_fim,
                )
        if top_err:
            st.warning(
                "Não foi possível carregar o ranking por nome. "
                "Exibindo fallback a partir da view de criativos."
            )
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {top_err}")

        if not df_top_nome.empty:
            top = criativos_top_por_nome_ranking(
                df,
                df_top_nome,
                df_resultados_filtered,
                sort_by=sort_field,
                ascending=ascending,
                top_n=12,
            )
        else:
            top = criativos_ranking(
                df,
                sort_by=sort_field,
                ascending=ascending,
                top_n=12,
                df_resultados=df_resultados_filtered,
            )
    except Exception as exc:
        logger.exception("Falha na secao Top 12")
        st.error(
            "Não foi possível renderizar o Top 12. "
            "As seções superiores permanecem disponíveis."
        )
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")
        try:
            top = criativos_ranking(
                df,
                sort_by=sort_field,
                ascending=ascending,
                top_n=12,
                df_resultados=df_resultados_filtered,
            )
        except Exception:
            top = pd.DataFrame()
        return

    perf_mark_top12_rendered(PAGE_CREATIVES)

    if top.empty:
        st.info("Nenhum criativo com investimento no período para os filtros aplicados.")
    else:
        rows = top.to_dict("records")
        for i in range(0, len(rows), 4):
            cols_grid = st.columns(4, gap="small")
            for col, row in zip(cols_grid, rows[i:i + 4]):
                with col:
                    st.markdown(_creative_card_html(row), unsafe_allow_html=True)
        _render_resultado_atribuido_top12(top)


def _render_comparar_criativos(ctx: PageContext, df: pd.DataFrame) -> None:
    section_title("Comparar criativos",
                  "plataforma + leads/CRM · grão utm_content (= ad_name)")

    try:
        with st.spinner("Carregando base de leads para comparação…"):
            df_pv_raw_cri, cmp_err = _fetch_df(
                "ext_reconecta.leads (email-level pra Comparar criativos)",
                lambda: get_mkt_paginas_variantes(ctx.data_ini, ctx.data_fim),
                ctx.data_ini, ctx.data_fim,
            )
        if cmp_err:
            st.error("Não foi possível carregar a comparação de criativos.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {cmp_err}")
            return
    except Exception as exc:
        logger.exception("Falha ao carregar paginas_variantes")
        st.error("Não foi possível carregar a comparação de criativos.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")
        return

    def _opts_cri(col: str, default: str = "Todas") -> list[str]:
        if df_pv_raw_cri.empty or col not in df_pv_raw_cri.columns:
            return [default]
        vals = sorted(df_pv_raw_cri[col].dropna().astype(str).unique().tolist())
        return [default] + vals

    _HELP_CRI = (
        "Filtra apenas a comparação de criativos — não afeta os cards "
        "superiores, Top 12 nem Funil do criativo selecionado."
    )

    flt_cri_l1_a, flt_cri_l1_b = st.columns(2, gap="small")
    with flt_cri_l1_a:
        sel_origem_cri = st.selectbox(
            "Origem", options=_opts_cri("utm_source", "Todas"),
            index=0, key="cmp_cri_origem", help=_HELP_CRI,
        )
    with flt_cri_l1_b:
        sel_midia_cri = st.selectbox(
            "Mídia", options=_opts_cri("utm_medium", "Todas"),
            index=0, key="cmp_cri_midia", help=_HELP_CRI,
        )
    flt_cri_l2_a, flt_cri_l2_b = st.columns(2, gap="small")
    with flt_cri_l2_a:
        sel_timezone_cri = st.selectbox(
            "Fuso / região", options=_opts_cri("timezone", "Todos"),
            index=0, key="cmp_cri_timezone", help=_HELP_CRI,
        )
    with flt_cri_l2_b:
        sel_device_cri = st.selectbox(
            "Dispositivo", options=_opts_cri("device_type", "Todos"),
            index=0, key="cmp_cri_device", help=_HELP_CRI,
        )

    df_cri_utm_agg = agregar_criativos_por_utm_content(
        df_pv_raw_cri, df,
        origem=sel_origem_cri, midia=sel_midia_cri,
        timezone=sel_timezone_cri, device_type=sel_device_cri,
    )
    cri_list = lista_criativos_utm_content(df_cri_utm_agg)

    if cri_list.empty:
        st.caption("Sem criativos para os filtros selecionados.")
        return

    options = cri_list["ad_name_norm"].tolist()
    labels_map = dict(zip(cri_list["ad_name_norm"], cri_list["label"]))
    idx_default_b = 1 if len(options) > 1 else 0

    sel_col_a, sel_col_b = st.columns(2, gap="small")
    with sel_col_a:
        sel_a = st.selectbox(
            "Criativo A",
            options=options,
            format_func=lambda c: labels_map.get(c, "—"),
            index=0,
            key="cmp_criativo_a",
        )
    with sel_col_b:
        sel_b = st.selectbox(
            "Criativo B",
            options=options,
            format_func=lambda c: labels_map.get(c, "—"),
            index=idx_default_b,
            key="cmp_criativo_b",
        )

    kA = criativo_utm_content_kpis(df_cri_utm_agg, sel_a)
    kB = criativo_utm_content_kpis(df_cri_utm_agg, sel_b)

    def _tem_leads(k: dict) -> bool:
        return bool(k.get("leads_totais") or 0)

    bdg_col_a, bdg_col_b = st.columns(2, gap="small")
    with bdg_col_a:
        st.caption(
            "✓ leads atribuídos via UTM" if _tem_leads(kA)
            else "⚠ sem atribuição via UTM"
        )
    with bdg_col_b:
        st.caption(
            "✓ leads atribuídos via UTM" if _tem_leads(kB)
            else "⚠ sem atribuição via UTM"
        )

    cmp = compara_criativos_utm_content(kA, kB)

    _MONEY_METRICS = {"Investimento", "CPC", "CPL", "CPL +12", "CAC"}
    _PCT_METRICS = {"CTR", "Taxa qualificação", "Taxa +12", "Taxa Lead → Venda nova"}
    _FLOAT_METRICS = {"Frequência"}
    _STR_METRICS = {
        "Campanha principal", "Adset principal", "Status",
        "Quality ranking", "Engagement ranking",
        "Conversion ranking", "URL exemplo",
    }

    def _fmt_value(metrica: str, val) -> str:
        if val is None:
            return "—"
        try:
            if isinstance(val, float) and val != val:
                return "—"
        except Exception:
            pass
        if metrica in _STR_METRICS:
            s = str(val).strip()
            return s if s and s != "—" else "—"
        if metrica in _MONEY_METRICS:
            return brl(float(val), casas=2)
        if metrica in _PCT_METRICS:
            return pct(float(val), casas=2)
        if metrica in _FLOAT_METRICS:
            return f"{float(val):.2f}".replace(".", ",")
        return int_br(float(val))

    def _fmt_delta(d) -> str:
        import pandas as _pd
        if d is None or _pd.isna(d):
            return "—"
        sign = "+" if d > 0 else ""
        return f"{sign}{d:.1f}%".replace(".", ",")

    def _fmt_vencedor(v: str) -> str:
        return f"✓ {v}" if v else ""

    view = cmp.assign(
        valor_a_fmt=cmp.apply(
            lambda r: _fmt_value(r["metrica"], r["valor_a"]), axis=1
        ),
        valor_b_fmt=cmp.apply(
            lambda r: _fmt_value(r["metrica"], r["valor_b"]), axis=1
        ),
        delta_fmt=cmp["delta_pct"].apply(_fmt_delta),
        vencedor_fmt=cmp["vencedor"].apply(_fmt_vencedor),
    )[["metrica", "valor_a_fmt", "valor_b_fmt", "delta_fmt", "vencedor_fmt"]]

    st.dataframe(
        view, use_container_width=True, hide_index=True,
        column_config={
            "metrica": "Métrica",
            "valor_a_fmt": "Criativo A",
            "valor_b_fmt": "Criativo B",
            "delta_fmt": st.column_config.TextColumn(
                "Δ%", help="(B − A) / A × 100. — quando A=0, valor "
                          "categórico, ou algum lado vazio."),
            "vencedor_fmt": st.column_config.TextColumn(
                "Vencedor",
                help="Maior em volume/qualidade (Impressões, Cliques, "
                     "Link clicks, Alcance, CTR, Leads, +12, Vendas novas, "
                     "Taxas). Menor em CPC/CPL/CPL+12/CAC/Frequência. "
                     "Investimento, identidade (Campanha/Status/rankings), "
                     "Leads -12 e Não atua não destacam vencedor."),
        },
    )

    def _url_valido(u) -> str | None:
        if u is None:
            return None
        if isinstance(u, float) and u != u:
            return None
        s = str(u).strip()
        if not s or s == "—":
            return None
        if not (s.startswith("http://") or s.startswith("https://")):
            return None
        return s

    url_a = _url_valido(kA.get("page_url_exemplo"))
    url_b = _url_valido(kB.get("page_url_exemplo"))
    permalink_a = _url_valido(kA.get("permalink_url"))
    permalink_b = _url_valido(kB.get("permalink_url"))
    partes = []
    if url_a:
        partes.append(f"[Abrir URL da Página A]({url_a})")
    if url_b:
        partes.append(f"[Abrir URL da Página B]({url_b})")
    if permalink_a:
        partes.append(f"[Abrir Criativo A no Meta Ads]({permalink_a})")
    if permalink_b:
        partes.append(f"[Abrir Criativo B no Meta Ads]({permalink_b})")
    if partes:
        st.markdown(" · ".join(partes))

    st.caption(
        "Métricas de **plataforma** (Invest., Impressões, Cliques, Link clicks, "
        "Alcance, CTR, CPC, Frequência, Campanha, Status, Quality/Engagement/"
        "Conversion ranking) vêm de **`bi.vw_mkt_criativos`** agregadas por "
        "`ad_name` (consolida múltiplos `ad_id` do mesmo criativo). "
        "**Leads / +12 / -12 / Vendas novas / CRM**: regra oficial via "
        "`ext_reconecta.leads` filtrado por `utm_content`, com priority match "
        "lead → deal `zoho_id > session_id > email`. **Match** plataforma ↔ "
        "leads = `lower(btrim(ad_name)) = lower(btrim(utm_content))`. "
        "**Derivadas** (CPL, CPL +12, CAC) usam invest da plataforma sobre "
        "numerador atribuído via UTM. "
        "\"—\" indica ausência de atribuição via UTM ou denominador zero. "
        "**Filtros** (Origem/Mídia/Fuso/Dispositivo) afetam SOMENTE este bloco."
    )


# ---------------------------------------------------------------------------
# Tabelas de auditoria — fdw (mídia) + leads (UTM)
# ---------------------------------------------------------------------------
_ANUNCIOS_AUDIT_COLS_FIRST = [
    "date_start", "date_stop", "campaign_id", "campaign_name", "adset_id",
    "adset_name", "ad_id", "ad_name", "objective", "optimization_goal",
    "spend", "impressions", "reach", "frequency", "clicks", "unique_clicks",
    "inline_link_clicks", "unique_inline_link_clicks", "ctr", "cpc", "cpm",
    "cpp", "actions_landing_page_view", "actions_omni_landing_page_view",
    "actions_lead", "actions_onsite_web_lead",
    "actions_offsite_conversion_fb_pixel_lead", "actions_complete_registration",
    "conversions_schedule_total", "conversions_schedule_website",
    "cost_per_action_type_lead", "cost_per_action_type_onsite_web_lead",
    "cost_per_conversion_schedule_total", "quality_ranking",
    "engagement_rate_ranking", "conversion_rate_ranking", "created_time",
    "updated_time", "internacional",
]

_LEADS_AUDIT_COLS_FIRST = [
    "created_at", "timestamp", "email", "first_name", "utm_source",
    "utm_medium", "utm_campaign", "utm_content", "utm_term", "classificado",
    "scheduled", "dt_hr_agendamento", "campaign_id", "adset_id", "ad_id",
    "fbclid", "page_url", "page_pathname", "lead_source", "form_version",
    "device_type", "lp_variante", "cidade", "zoho_id",
]


def _norm_cell_utm_aud(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip().lower()
    return s


def _sn_utm(v: bool) -> str:
    return "sim" if v else "não"


def _prep_leads_utm_audit(
    df_leads: pd.DataFrame,
    df_fdw: pd.DataFrame,
    df_unfiltered: pd.DataFrame,
    ctx,
    col_map: dict[str, str],
) -> pd.DataFrame:
    if df_leads is None or df_leads.empty:
        return df_leads
    out = df_leads.copy()
    camp_norms: set[str] = set()
    ad_norms: set[str] = set()
    if df_fdw is not None and not df_fdw.empty:
        if "campaign_name" in df_fdw.columns:
            camp_norms = {
                _norm_cell_utm_aud(x)
                for x in df_fdw["campaign_name"].dropna()
                if _norm_cell_utm_aud(x)
            }
        if "ad_name" in df_fdw.columns:
            ad_norms = {
                _norm_cell_utm_aud(x)
                for x in df_fdw["ad_name"].dropna()
                if _norm_cell_utm_aud(x)
            }
    if "utm_campaign" in out.columns:
        out["utm_campaign_norm"] = out["utm_campaign"].map(_norm_cell_utm_aud)
    else:
        out["utm_campaign_norm"] = ""
    if "utm_content" in out.columns:
        out["utm_content_norm"] = out["utm_content"].map(_norm_cell_utm_aud)
    else:
        out["utm_content_norm"] = ""
    if "utm_campaign" in out.columns:
        s = out["utm_campaign"].fillna("").astype(str).str.strip()
        out["tem_utm_campaign"] = s.ne("") & s.str.lower().ne("nan")
        out["tem_utm_campaign"] = out["tem_utm_campaign"].map(_sn_utm)
    else:
        out["tem_utm_campaign"] = "não"
    if "utm_content" in out.columns:
        s2 = out["utm_content"].fillna("").astype(str).str.strip()
        out["tem_utm_content"] = (s2.ne("") & s2.str.lower().ne("nan")).map(_sn_utm)
    else:
        out["tem_utm_content"] = "não"
    if "ad_id" in out.columns:
        aid = out["ad_id"].fillna("").astype(str).str.strip()
        out["tem_ad_id"] = (
            aid.ne("")
            & aid.str.lower().ne("nan")
            & aid.str.lower().ne("none")
        ).map(_sn_utm)
    else:
        out["tem_ad_id"] = "não"
    ucn = out["utm_campaign_norm"]
    out["match_campaign_name"] = "não"
    if camp_norms:
        out.loc[ucn.ne("") & out["utm_campaign_norm"].isin(camp_norms), "match_campaign_name"] = "sim"
    utn = out["utm_content_norm"]
    out["match_ad_name"] = "não"
    if ad_norms:
        out.loc[utn.ne("") & out["utm_content_norm"].isin(ad_norms), "match_ad_name"] = "sim"

    sel = ctx.selections.get("campanha", [])
    ckey = col_map.get("campanha")
    if (
        sel
        and ckey
        and ckey in df_unfiltered.columns
        and "utm_campaign" in out.columns
    ):
        all_vals = df_unfiltered[ckey].dropna().astype(str).unique().tolist()
        if len(sel) < len(all_vals):
            want = {_norm_cell_utm_aud(x) for x in sel}
            vn = out["utm_campaign"].map(_norm_cell_utm_aud)
            out = out.loc[vn.isin(want)].copy()

    return out


def _load_fdw_audit_df(ctx: PageContext) -> pd.DataFrame:
    """FDW para auditorias — cache @st.cache_data; uma execucao real por chave."""
    df, _err = _fetch_df(
        "fdw_reconecta.anuncios (audit)",
        lambda: get_mkt_criativos_anuncios_fdw(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    return df


def _render_auditorias(
    ctx: PageContext,
    df: pd.DataFrame,
    df_all: pd.DataFrame,
) -> None:
    exp_fdw = st.expander(
        "Tabela detalhada — anúncios do período",
        expanded=False,
        on_change="rerun",
    )
    if exp_fdw.open:
        with exp_fdw:
            try:
                with st.spinner("Carregando auditoria fdw_reconecta.anuncios…"):
                    df_an_fdw = _load_fdw_audit_df(ctx)
            except Exception as exc:
                logger.exception("Falha na auditoria fdw anuncios")
                st.error("Não foi possível carregar a tabela de anúncios fdw.")
                if perf_debug_enabled():
                    st.caption(f"Detalhe técnico: {exc}")
                df_an_fdw = pd.DataFrame()

            st.caption(
                "fonte: **fdw_reconecta.anuncios** (mesma janela do dashboard)."
            )
            if df_an_fdw.empty:
                st.info(
                    "Sem linhas em fdw_reconecta.anuncios para o período "
                    "ou fonte indisponível."
                )
            else:
                df_an_disp = df_an_fdw
                if (
                    not df.empty
                    and "ad_id" in df.columns
                    and "ad_id" in df_an_fdw.columns
                ):
                    ads_ok = set(df["ad_id"].dropna().astype(str).unique())
                    df_an_disp = df_an_fdw[
                        df_an_fdw["ad_id"].astype(str).isin(ads_ok)
                    ].copy()
                    st.caption(
                        "Filtros de **campanha** e **status** da página aplicados via "
                        "interseção com os `ad_id` visíveis em `bi.vw_mkt_criativos`."
                    )
                else:
                    st.caption(
                        "Sem filtro de campanha/status (nenhum anúncio na view filtrada); "
                        "exibindo todos os registros fdw no período."
                    )
                primary = [
                    c for c in _ANUNCIOS_AUDIT_COLS_FIRST if c in df_an_disp.columns
                ]
                extra = [c for c in df_an_disp.columns if c not in primary]
                st.dataframe(
                    df_an_disp[primary] if primary else df_an_disp,
                    use_container_width=True,
                    hide_index=True,
                )
                if extra:
                    with st.expander(f"Demais colunas fdw ({len(extra)})"):
                        st.dataframe(
                            df_an_disp[extra],
                            use_container_width=True,
                            hide_index=True,
                        )

    exp_leads = st.expander(
        "Tabela de leads — UTMs e associação com criativos",
        expanded=False,
        on_change="rerun",
    )
    if exp_leads.open:
        with exp_leads:
            try:
                df_leads_raw, fonte_leads = get_mkt_criativos_leads_utm_audit(
                    ctx.data_ini, ctx.data_fim,
                )
            except Exception as exc:
                logger.exception("Falha na auditoria leads UTM")
                st.error("Não foi possível carregar a tabela de leads.")
                if perf_debug_enabled():
                    st.caption(f"Detalhe técnico: {exc}")
                return

            sub_leads = (
                f"fonte: **{fonte_leads}**; associação via `utm_campaign` ↔ "
                "`campaign_name` e `utm_content` ↔ `ad_name` "
                "(normalizado `LOWER(TRIM(·))` vs **fdw** no período)."
            )
            st.caption(sub_leads)
            if df_leads_raw.empty:
                st.info(
                    "Sem leads no período para os critérios de e-mail, "
                    "ou fonte indisponível."
                )
            else:
                df_fdw_match = _load_fdw_audit_df(ctx)
                df_leads_enr = _prep_leads_utm_audit(
                    df_leads_raw,
                    df_fdw_match,
                    df_all,
                    ctx,
                    _COL_MAP,
                )
                front = [
                    c for c in _LEADS_AUDIT_COLS_FIRST if c in df_leads_enr.columns
                ]
                tail = [
                    "utm_campaign_norm",
                    "utm_content_norm",
                    "tem_utm_campaign",
                    "tem_utm_content",
                    "tem_ad_id",
                    "match_campaign_name",
                    "match_ad_name",
                ]
                tail = [c for c in tail if c in df_leads_enr.columns]
                used = set(front) | set(tail)
                mid = [c for c in df_leads_enr.columns if c not in used]
                show_cols = front + tail
                st.dataframe(
                    df_leads_enr[show_cols],
                    use_container_width=True,
                    hide_index=True,
                )
                if mid:
                    with st.expander(f"Demais colunas de leads ({len(mid)})"):
                        st.dataframe(
                            df_leads_enr[mid],
                            use_container_width=True,
                            hide_index=True,
                        )


def main() -> None:
    if perf_debug_enabled():
        perf_reset_run(PAGE_CREATIVES)

    ctx = start_page(
        title="Criativos",
        subtitle="Performance dos anúncios Meta",
        filters=["campanha", "status"],
    )

    perf_set_context(
        PAGE_CREATIVES,
        data_ini=ctx.data_ini,
        data_fim=ctx.data_fim,
        campanha=list(ctx.selections.get("campanha") or []),
        status=list(ctx.selections.get("status") or []),
        funil_item=st.session_state.get("cri_funil_selecionado"),
    )

    df_all = pd.DataFrame()
    df = pd.DataFrame()
    df_res_f = pd.DataFrame()

    # --- P1: Performance Meta ---
    try:
        with perf_timed_block("Performance Meta (criativos + resultados)", page=PAGE_CREATIVES):
            (
                df_all, df, _df_prev, df_res_f, _df_res_prev_f,
                _df_resultados, k, kp, p1_err,
            ) = _load_p1_data(ctx)
        if p1_err:
            st.error(
                "Não foi possível carregar os indicadores superiores. "
                "Os cards podem exibir zeros até a consulta ser concluída."
            )
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {p1_err}")
        _render_performance_meta(ctx, k, kp)
        perf_mark_kpi_rendered(PAGE_CREATIVES)
    except Exception as exc:
        logger.exception("Falha nos cards Performance Meta")
        section_title(
            "Performance Meta",
            f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
        )
        st.error("Não foi possível renderizar Performance Meta.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")

    # --- Funil (deferido apos KPIs) ---
    _render_funil_section(ctx)

    # --- Distribuicoes (memoria) ---
    if not df.empty:
        _render_distribuicoes(df)

    # --- Top 12 (deferido) ---
    _render_top12(ctx, df, df_res_f)

    # --- Comparar criativos (deferido) ---
    _render_comparar_criativos(ctx, df)

    # --- Auditorias (lazy) ---
    _render_auditorias(ctx, df, df_all)

    perf_finalize_page(PAGE_CREATIVES)
    perf_render_panel(PAGE_CREATIVES)


if __name__ == "__main__":
    main()
