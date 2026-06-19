"""Campanhas — performance por campanha em mídia paga (Meta, Google, Pinterest).

Consome:
    bi.vw_mkt_campanhas — invest/imp/cliques/alcance/objetivo por campanha
    mkt_campanha_funil — funil por campaign_name_norm

Os 3 canais pagos sempre aparecem no filtro, mesmo quando zerados — Pinterest
e Google podem não ter volume hoje, e o time pediu para preservar a estrutura
da página em qualquer cenário."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Callable

import pandas as pd
import streamlit as st

from src.marketing_perf import (
    PAGE_CAMPAIGNS,
    perf_debug_enabled,
    perf_finalize_page,
    perf_mark_funil_rendered,
    perf_mark_kpi_rendered,
    perf_mark_selector_rendered,
    perf_record_query,
    perf_render_panel,
    perf_reset_run,
    perf_set_context,
    perf_timed_block,
)
from src.marketing_queries import (
    get_mkt_campanha_cobertura,
    get_mkt_campanha_funil,
    get_mkt_campanhas,
    get_mkt_campanhas_leads_canal_diario,
    get_mkt_campanhas_leads_por_utm,
    get_mkt_paginas_variantes,
)
from src.marketing_safe import safe_run
from src.repositories import (
    get_investimento_diario,
    get_leads_visao_geral,
    get_mkt_campanhas_vendas_oficiais,
    get_prevendas_overview_diario,
)
from src.marketing_transforms import (
    CANAIS_PAGOS,
    agendamentos_one_page_oficial,
    comparecimentos_one_page_oficial,
    vendas_one_page_oficial,
    agregar_campanhas_por_utm,
    campanha_funil_etapas,
    campanha_funil_kpis,
    campanha_utm_kpis,
    campanhas_diario_v2,
    campanhas_kpis,
    campanhas_leads_canal_kpis,
    campanhas_objetivo,
    campanhas_tabela_ativas,
    campanhas_tabela_total_row,
    cobertura_atribuicao_kpis,
    compara_campanhas_utm,
    filtro_canais_padrao,
    lista_campanhas_funil,
    lista_campanhas_por_utm,
)
from src.transforms import _safe_div
from src.ui.charts import donut, last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.marketing_components import render_funil_selecionado
from src.ui.page import PageContext, start_page
from src.ui.theme import PALETTE, brl, int_br, pct

logger = logging.getLogger("reconecta.marketing.campaigns")

_TODOS_NORM = "__todos__"

_FUNIL_EXPANDER_MD = (
    "- **Universo do funil:** `ext_reconecta.leads` no período, com "
    "  `utm_campaign` definindo a campanha do lead.\n"
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
    "- **'Totais vinculados aos leads':** soma per-campanha do funil "
    "  — só o que foi de fato vinculado/atribuído (útil pra auditoria "
    "  vs. universo oficial).\n"
    "- **Leads / +12 / -12 / Agendamentos / Comparecimentos:** "
    "  lead-centric, 1 e-mail conta 1× por campanha "
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
    "- **Aplicações (etapa do funil):** `fdw_reconecta.typeform_aplicacoes` "
    "  cruzado por e-mail dos leads da campanha (`utm_campaign`); "
    "`dados_completos = TRUE`, dedupe e-mail/dia; leads `timestamp::date`, "
    "typeform `created_at::date`. Em **Todos os resultados**, aplicações = todas do Typeform no período "
    "(igual One Page); em campanha específica, só com lead na campanha. "
    "Exibimos total, % sobre leads, +12/-12, CPA e CPA +12.\n"
    "- **Filtros de e-mail de teste:** `@teste`, `teste@`, `smarts`, "
    "  `reconecta` removidos do universo de leads em todas as etapas."
)


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
            page=PAGE_CAMPAIGNS, cols=cols, error=err,
        )
    return df, err


def _load_primary_data(
    ctx: PageContext,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str | None]:
    """P1: campanhas + leads canal diario."""
    errors: list[str] = []
    df_camp_all, e1 = _fetch_df(
        "bi.vw_mkt_campanhas",
        lambda: get_mkt_campanhas(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    df_leads_canal_diario_all, e2 = _fetch_df(
        "bi_mkt.vw_visao_geral_canal_base (canal-diario)",
        lambda: get_mkt_campanhas_leads_canal_diario(ctx.data_ini, ctx.data_fim),
        ctx.data_ini, ctx.data_fim,
    )
    if e1:
        errors.append(e1)
    if e2:
        errors.append(e2)
    col_map = {"canal": "canal"}
    df_camp = (
        ctx.refilter(df_camp_all, col_map) if not df_camp_all.empty else df_camp_all
    )
    return df_camp, df_leads_canal_diario_all, df_camp_all, "; ".join(errors) or None


def _compute_top_kpis(
    df_camp: pd.DataFrame,
    df_leads_canal_diario_all: pd.DataFrame,
    canais_sel: list[str],
    data_ini: date,
    data_fim: date,
) -> dict:
    k = campanhas_kpis(df_camp, pd.DataFrame(), None)
    kc = campanhas_leads_canal_kpis(df_leads_canal_diario_all, canais_sel)
    k["leads"] = kc["leads_totais"]
    k["leads_qualificados"] = kc["leads_qualificados"]
    k["leads_qualif_mais_12"] = kc["leads_mais_12"]
    k["leads_qualif_menos_12"] = kc["leads_menos_12"]
    k["cpl"] = _safe_div(k["investimento"], k["leads"])
    k["cpl_qualificado"] = _safe_div(k["investimento"], k["leads_qualificados"])
    total_dias = (data_fim - data_ini).days + 1
    k["investimento_dia"] = _safe_div(k["investimento"], total_dias)
    return k


def _render_financeiro_volume(
    ctx: PageContext,
    k: dict,
    total_dias: int,
) -> None:
    section_title(
        "Financeiro",
        f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
    )
    c1, c2, c3, c4 = st.columns(4, gap="small")
    with c1:
        metric_card_v2(
            "Investimento",
            brl(k["investimento"], casas=2),
            hint="Meta + Google + Pinterest (canais filtrados)",
            accent=True,
        )
    with c2:
        metric_card_v2(
            "Investimento / dia",
            brl(k["investimento_dia"], casas=2),
            hint=f"invest ÷ {total_dias} dia{'s' if total_dias != 1 else ''}",
        )
    with c3:
        metric_card_v2(
            "CPL",
            brl(k["cpl"], casas=2),
            hint="invest ÷ leads totais",
        )
    with c4:
        metric_card_v2(
            "CPL qualificado",
            brl(k["cpl_qualificado"], casas=2),
            hint="invest ÷ qualificados (+12 ou -12)",
        )

    section_title("Volume", "leads e impressões no período")
    s1, s2, s3 = st.columns(3, gap="small")
    with s1:
        metric_card_v2(
            "Leads totais",
            int_br(k["leads"]),
            hint="bi_mkt.vw_visao_geral_canal_base · canal-aware",
        )
    with s2:
        metric_card_v2(
            "Leads qualificados",
            int_br(k["leads_qualificados"]),
            hint=f"+12: {int_br(k['leads_qualif_mais_12'])} · "
                 f"-12: {int_br(k['leads_qualif_menos_12'])}",
        )
    with s3:
        metric_card_v2(
            "Impressões",
            int_br(k["impressoes"]),
            hint=f"CTR {pct(k['ctr'], casas=2)} · CPC {brl(k['cpc'], casas=2)}",
        )


def _resolve_vendas_novas_oficial(
    vendas_count: int | None,
    *,
    leads_totais: int | None,
    investimento: float | None,
    agendamentos: int | None,
    comparecimentos: int | None,
) -> int | None:
    """Preserva None quando a fonte falha ou o periodo nao tem dados oficiais."""
    if vendas_count is None:
        return None
    if vendas_count == 0 and all(
        v is None
        for v in (leads_totais, investimento, agendamentos, comparecimentos)
    ):
        return None
    return vendas_count


def _load_oficiais_todos(ctx: PageContext) -> dict:
    """Carrega as 4 fontes oficiais — somente para __todos__."""
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
    """Retorna loader chamado apos o selectbox — so executa SQL para __todos__."""

    def _loader(sel: str) -> dict:
        if sel != _TODOS_NORM:
            return {}
        with st.spinner("Carregando totais oficiais do período…"):
            with perf_timed_block("Fontes oficiais (__todos__)", page=PAGE_CAMPAIGNS):
                return _load_oficiais_todos(ctx)

    return _loader


def _render_funil_section(ctx: PageContext) -> None:
    try:
        with st.spinner("Carregando funil por campanha…"):
            with perf_timed_block("Funil campanha_funil", page=PAGE_CAMPAIGNS):
                df_camp_funil, err = _fetch_df(
                    "mkt_campanha_funil",
                    lambda: get_mkt_campanha_funil(ctx.data_ini, ctx.data_fim),
                    ctx.data_ini, ctx.data_fim,
                )
        if err:
            section_title(
                "Funil da campanha selecionada",
                "investimento → vendas novas",
            )
            st.error(
                "Não foi possível carregar o funil de campanhas. "
                "Os cards superiores permanecem disponíveis."
            )
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {err}")
            return

        render_funil_selecionado(
            df_funil=df_camp_funil,
            key_col="campaign_name_norm",
            entity_label="Campanha",
            section_title_text="Funil da campanha selecionada",
            sel_state_key="camp_funil_selecionado",
            lista_fn=lambda df, sb: lista_campanhas_funil(df, sb),
            kpis_fn=campanha_funil_kpis,
            etapas_fn=campanha_funil_etapas,
            oficiais_loader=_oficiais_loader_factory(ctx),
            on_selector_rendered=lambda: perf_mark_selector_rendered(PAGE_CAMPAIGNS),
            on_funil_cards_rendered=lambda: perf_mark_funil_rendered(PAGE_CAMPAIGNS),
            marketing_funil_unico=True,
            data_ini=ctx.data_ini,
            data_fim=ctx.data_fim,
            nivel="campanha",
            auditoria_state_key="camp_funil_auditoria",
            empty_msg="Sem campanhas com investimento ou leads no período.",
            caption=(
                "Campanhas usam `utm_campaign` como origem principal. Vendas são "
                "atribuídas ao lead histórico por e-mail/telefone antes da compra."
            ),
            expander_md=_FUNIL_EXPANDER_MD,
        )
    except Exception as exc:
        logger.exception("Falha na seção Funil da campanha")
        section_title(
            "Funil da campanha selecionada",
            "investimento → vendas novas",
        )
        st.error("Não foi possível renderizar o funil da campanha selecionada.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")


def _render_tendencia(
    df_camp: pd.DataFrame,
    df_leads_canal_diario_all: pd.DataFrame,
    canais_sel: list[str],
) -> None:
    import plotly.graph_objects as go

    section_title("Tendência diária", "investimento × leads × leads qualificados")
    try:
        diario = campanhas_diario_v2(df_camp, df_leads_canal_diario_all, canais_sel)
        if diario.empty:
            st.info("Sem dados no período para os canais selecionados.")
            return

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=diario["data_ref"], y=diario["investimento"], name="Investimento",
            marker=dict(color=PALETTE["gold"],
                        line=dict(color=PALETTE["gold_soft"], width=0.6)),
            yaxis="y",
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=diario["data_ref"], y=diario["leads"], name="Leads",
            line=dict(color=PALETTE["wine_light"], width=2.5),
            mode="lines+markers+text", marker=dict(size=6),
            text=last_point_text(diario["leads"], int_br),
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
    except Exception as exc:
        logger.exception("Falha na seção Tendência diária")
        st.error("Não foi possível carregar a tendência diária.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")


def _render_objetivo_e_tabela(
    ctx: PageContext,
    df_camp: pd.DataFrame,
) -> None:
    col_obj, col_tab = st.columns([1, 1.6], gap="large")

    with col_obj:
        section_title("Por objetivo", "investimento agrupado")
        try:
            obj = campanhas_objetivo(df_camp)
            if obj.empty:
                st.info("Sem investimento no período para os canais selecionados.")
            else:
                st.plotly_chart(
                    donut(obj, names="objetivo", values="investimento",
                          height=300, total_label="Invest. total"),
                    use_container_width=True,
                )
        except Exception as exc:
            logger.exception("Falha na seção Por objetivo")
            st.error("Não foi possível carregar a distribuição por objetivo.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {exc}")

    with col_tab:
        section_title(
            "Campanhas ativas",
            "investimento > 0 no período · ordenadas por invest. desc",
        )
        try:
            with perf_timed_block("Tabela campanhas ativas", page=PAGE_CAMPAIGNS):
                df_leads_por_utm, err = _fetch_df(
                    "ext_reconecta.leads (por utm_campaign)",
                    lambda: get_mkt_campanhas_leads_por_utm(
                        ctx.data_ini, ctx.data_fim,
                    ),
                    ctx.data_ini, ctx.data_fim,
                )
            if err:
                st.error("Não foi possível carregar leads por campanha para a tabela.")
                if perf_debug_enabled():
                    st.caption(f"Detalhe técnico: {err}")
                return

            ativas = campanhas_tabela_ativas(df_camp, df_leads_por_utm)
            if ativas.empty:
                st.info("Nenhuma campanha ativa para os canais selecionados.")
            else:
                ativas_view = pd.concat(
                    [ativas, campanhas_tabela_total_row(ativas)],
                    ignore_index=True,
                )
                st.dataframe(
                    ativas_view, use_container_width=True, hide_index=True,
                    column_config={
                        "campaign_name": "Campanha",
                        "canal": "Canal",
                        "objetivo": "Objetivo",
                        "investimento": st.column_config.NumberColumn(
                            "Invest.", format="R$ %.2f"),
                        "impressoes": st.column_config.NumberColumn(
                            "Impressões", format="%d"),
                        "cliques": st.column_config.NumberColumn("Cliques", format="%d"),
                        "ctr": st.column_config.NumberColumn("CTR", format="%.2f%%"),
                        "cpc": st.column_config.NumberColumn("CPC", format="R$ %.2f"),
                        "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
                        "leads": st.column_config.NumberColumn("Leads", format="%d"),
                        "leads_qualificados": st.column_config.NumberColumn(
                            "Qualificados", format="%d"),
                        "leads_mais_12": st.column_config.NumberColumn(
                            "+12", format="%d"),
                        "leads_menos_12": st.column_config.NumberColumn(
                            "-12", format="%d"),
                        "cpl": st.column_config.NumberColumn(
                            "CPL", format="R$ %.2f"),
                        "cpl_mais_12": st.column_config.NumberColumn(
                            "CPL +12", format="R$ %.2f"),
                        "tx_qualif_mais_12": st.column_config.NumberColumn(
                            "Tx Qualif +12", format="%.2f%%"),
                    },
                )
                st.caption(
                    "Leads por campanha são associados via `campaign_name = "
                    "utm_campaign`. Campanhas sem correspondência de UTM aparecem "
                    "com 0 até padronização. Quando o mesmo `campaign_name` tem "
                    "mais de um `campaign_id` na plataforma, o total de leads "
                    "do nome é repetido em cada linha (não há como atribuir leads "
                    "a um `campaign_id` específico via UTM)."
                )
        except Exception as exc:
            logger.exception("Falha na tabela Campanhas ativas")
            st.error("Não foi possível carregar a tabela de campanhas ativas.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {exc}")


def _render_comparar_campanhas(ctx: PageContext, df_camp: pd.DataFrame) -> None:
    section_title(
        "Comparar campanhas",
        "plataforma + leads/CRM + origem da campanha · grão utm_campaign",
    )
    try:
        with perf_timed_block("Comparar campanhas", page=PAGE_CAMPAIGNS):
            df_pv_raw, err = _fetch_df(
                "ext_reconecta.leads (email-level pra Comparar campanhas)",
                lambda: get_mkt_paginas_variantes(ctx.data_ini, ctx.data_fim),
                ctx.data_ini, ctx.data_fim,
            )
        if err:
            st.error("Não foi possível carregar dados para comparar campanhas.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {err}")
            return

        def _opts(col: str, default: str = "Todas") -> list[str]:
            if df_pv_raw.empty or col not in df_pv_raw.columns:
                return [default]
            vals = sorted(df_pv_raw[col].dropna().astype(str).unique().tolist())
            return [default] + vals

        _HELP = (
            "Filtra apenas a comparação de campanhas — não afeta os cards "
            "superiores, tabela 'Campanhas ativas' nem donut 'Por objetivo'."
        )

        flt_l1_a, flt_l1_b = st.columns(2, gap="small")
        with flt_l1_a:
            sel_origem = st.selectbox(
                "Origem", options=_opts("utm_source", "Todas"),
                index=0, key="cmp_camp_origem", help=_HELP,
            )
        with flt_l1_b:
            sel_midia = st.selectbox(
                "Mídia", options=_opts("utm_medium", "Todas"),
                index=0, key="cmp_camp_midia", help=_HELP,
            )
        flt_l2_a, flt_l2_b = st.columns(2, gap="small")
        with flt_l2_a:
            sel_timezone = st.selectbox(
                "Fuso / região", options=_opts("timezone", "Todos"),
                index=0, key="cmp_camp_timezone", help=_HELP,
            )
        with flt_l2_b:
            sel_device = st.selectbox(
                "Dispositivo", options=_opts("device_type", "Todos"),
                index=0, key="cmp_camp_device", help=_HELP,
            )

        df_camp_utm_agg = agregar_campanhas_por_utm(
            df_pv_raw, df_camp,
            origem=sel_origem, midia=sel_midia,
            timezone=sel_timezone, device_type=sel_device,
        )
        camp_list = lista_campanhas_por_utm(df_camp_utm_agg)

        if camp_list.empty:
            st.caption("Sem campanhas para os filtros selecionados.")
            return

        options = camp_list["campaign_norm"].tolist()
        labels_map = dict(zip(camp_list["campaign_norm"], camp_list["label"]))
        idx_default_b = 1 if len(options) > 1 else 0

        sel_col_a, sel_col_b = st.columns(2, gap="small")
        with sel_col_a:
            sel_a = st.selectbox(
                "Campanha A",
                options=options,
                format_func=lambda c: labels_map.get(c, "—"),
                index=0,
                key="cmp_campanha_a",
            )
        with sel_col_b:
            sel_b = st.selectbox(
                "Campanha B",
                options=options,
                format_func=lambda c: labels_map.get(c, "—"),
                index=idx_default_b,
                key="cmp_campanha_b",
            )

        kA = campanha_utm_kpis(df_camp_utm_agg, sel_a)
        kB = campanha_utm_kpis(df_camp_utm_agg, sel_b)
        cmp = compara_campanhas_utm(kA, kB)

        _MONEY_METRICS = {"Investimento", "CPC"}
        _PCT_METRICS = {"CTR", "Taxa qualificação", "Taxa +12",
                        "Taxa Lead → Venda nova"}
        _STR_METRICS = {"Canal", "Página principal", "Variante principal",
                        "URL exemplo"}

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
            return int_br(float(val))

        def _fmt_delta(d) -> str:
            if d is None or pd.isna(d):
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
                "valor_a_fmt": "Campanha A",
                "valor_b_fmt": "Campanha B",
                "delta_fmt": st.column_config.TextColumn("Δ%"),
                "vencedor_fmt": st.column_config.TextColumn("Vencedor"),
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
        partes = []
        if url_a:
            partes.append(f"[Abrir URL da Campanha A]({url_a})")
        if url_b:
            partes.append(f"[Abrir URL da Campanha B]({url_b})")
        if partes:
            st.markdown(" · ".join(partes))

        st.caption(
            "Métricas de **plataforma** (Invest., Impressões, Cliques, "
            "Alcance, CTR, CPC, Canal) vêm de **`bi.vw_mkt_campanhas`**, "
            "agregadas por `campaign_name` normalizado. "
            "**Leads, qualificados, +12, -12, Não atua, Taxas** e métricas "
            "de origem (página/variante/URL) vêm de "
            "`mkt_paginas_variantes.sql` (email-level) agregado por "
            "`utm_campaign` — mesma regra da Visão Geral. "
            "**Vendas novas** = `zoho_deals` (Ganho/Fechado Ganho) com "
            "`tipo_venda = 'Novo cliente'`, atribuído ao lead via priority "
            "`zoho_id > session_id > email` (mesma regra do funil Growth — "
            "ascensão/renovação/indicação ficam de fora do caminho de "
            "aquisição)."
        )

        with st.expander("Detalhamento de origem da campanha"):
            det = df_camp_utm_agg[[
                "utm_campaign", "pagina_principal", "variante_principal",
                "page_url_exemplo",
                "origens", "midias", "criativos",
                "fusos", "dispositivos",
                "qtd_paginas", "qtd_variantes", "qtd_criativos",
                "criativo_principal",
            ]].copy()
            for c in ("origens", "midias", "criativos", "fusos", "dispositivos"):
                det[c] = det[c].apply(
                    lambda lst: ", ".join(lst) if isinstance(lst, list) and lst else "—"
                )
            det["page_url_exemplo"] = det["page_url_exemplo"].fillna("—")
            det["pagina_principal"] = det["pagina_principal"].fillna("—")
            det["variante_principal"] = det["variante_principal"].fillna("—")
            det["criativo_principal"] = det["criativo_principal"].fillna("—")
            st.dataframe(
                det, use_container_width=True, hide_index=True,
                column_config={
                    "utm_campaign": "Campanha",
                    "pagina_principal": "Página principal",
                    "variante_principal": "Variante principal",
                    "page_url_exemplo": "URL exemplo",
                    "origens": "Origens",
                    "midias": "Mídias",
                    "criativos": "Criativos",
                    "fusos": "Fusos / regiões",
                    "dispositivos": "Dispositivos",
                    "qtd_paginas": st.column_config.NumberColumn(
                        "Qtd. páginas", format="%d"),
                    "qtd_variantes": st.column_config.NumberColumn(
                        "Qtd. variantes", format="%d"),
                    "qtd_criativos": st.column_config.NumberColumn(
                        "Qtd. criativos", format="%d"),
                    "criativo_principal": "Criativo principal",
                },
            )

        _render_cobertura_lazy(ctx)

    except Exception as exc:
        logger.exception("Falha na seção Comparar campanhas")
        st.error("Não foi possível carregar a comparação de campanhas.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")


def _render_cobertura_lazy(ctx: PageContext) -> None:
    exp = st.expander(
        "Cobertura da atribuicao (clique para detalhes)",
        expanded=False,
        on_change="rerun",
    )
    if not exp.open:
        return

    with exp:
        try:
            with st.spinner("Carregando diagnóstico de cobertura…"):
                df_cob, err = _fetch_df(
                    "odam.mart_ad_funnel_daily (cobertura)",
                    lambda: get_mkt_campanha_cobertura(ctx.data_ini, ctx.data_fim),
                    ctx.data_ini, ctx.data_fim,
                )
            if err:
                st.error("Não foi possível carregar a cobertura da atribuição.")
                if perf_debug_enabled():
                    st.caption(f"Detalhe técnico: {err}")
                return

            cob = cobertura_atribuicao_kpis(df_cob)
            if cob["nivel"] == "sem_dados":
                st.caption(
                    "Sem dados na mart para o período selecionado. "
                    "Sem leads/vendas/receita atribuídos."
                )
                return

            st.markdown(
                "Os números abaixo dizem quanto da mart consegue ser "
                "atribuído a uma campanha específica. Linhas com "
                "`campaign_id` NULL **não** entram na comparação por "
                "campanha — comportamento intencional (não distribuímos "
                "resultado sem chave clara)."
            )

            def _fmt_int_pct(n: int, p: float) -> str:
                return f"{int_br(n)} ({pct(p, casas=1)})"

            def _fmt_money_pct(v: float, p: float) -> str:
                return f"{brl(v, casas=2)} ({pct(p, casas=1)})"

            cob_rows = [
                {
                    "Métrica": "Leads",
                    "Com campaign_id": _fmt_int_pct(
                        cob["leads_com"], cob["pct_leads_com"]),
                    "Sem campaign_id": _fmt_int_pct(
                        cob["leads_sem"], 100 - cob["pct_leads_com"]),
                    "Total": int_br(cob["total_leads"]),
                },
                {
                    "Métrica": "Vendas",
                    "Com campaign_id": _fmt_int_pct(
                        cob["vendas_com"], cob["pct_vendas_com"]),
                    "Sem campaign_id": _fmt_int_pct(
                        cob["vendas_sem"], 100 - cob["pct_vendas_com"]),
                    "Total": int_br(cob["total_vendas"]),
                },
                {
                    "Métrica": "Receita",
                    "Com campaign_id": _fmt_money_pct(
                        cob["receita_com"], cob["pct_receita_com"]),
                    "Sem campaign_id": _fmt_money_pct(
                        cob["receita_sem"], 100 - cob["pct_receita_com"]),
                    "Total": brl(cob["total_receita"], casas=2),
                },
            ]
            st.dataframe(
                pd.DataFrame(cob_rows),
                use_container_width=True, hide_index=True,
            )

            if cob["nivel"] == "baixa":
                st.caption(
                    "**Cobertura baixa.** A comparação por campanha pode "
                    "parecer incompleta porque várias linhas da mart "
                    "estão entrando sem o `campaign_id` preenchido. "
                    "Esse é um problema de dados na origem "
                    "(`odam.mart_ad_funnel_daily`), não do dashboard."
                )
        except Exception as exc:
            logger.exception("Falha no expander de cobertura")
            st.error("Não foi possível carregar a cobertura da atribuição.")
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {exc}")


def main() -> None:
    if perf_debug_enabled():
        perf_reset_run(PAGE_CAMPAIGNS)

    ctx = start_page(
        title="Campanhas",
        subtitle="Performance por campanha em mídia paga",
        filters=["canal"],
    )
    col_map = {"canal": "canal"}
    ctx.apply_filters(filtro_canais_padrao(CANAIS_PAGOS), col_map)

    canais_sel: list[str] = list(ctx.selections.get("canal") or list(CANAIS_PAGOS))
    total_dias = (ctx.data_fim - ctx.data_ini).days + 1

    perf_set_context(
        PAGE_CAMPAIGNS,
        data_ini=ctx.data_ini,
        data_fim=ctx.data_fim,
        canais=canais_sel,
        funil_item=st.session_state.get("camp_funil_selecionado"),
    )

    # --- P1: Financeiro + Volume ---
    k: dict = {}
    df_camp = pd.DataFrame()
    df_leads_canal_diario_all = pd.DataFrame()
    try:
        with perf_timed_block("Financeiro e Volume", page=PAGE_CAMPAIGNS):
            df_camp, df_leads_canal_diario_all, _, p1_err = _load_primary_data(ctx)
        if p1_err:
            st.error(
                "Não foi possível carregar os indicadores superiores. "
                "Os cards podem exibir zeros até a consulta ser concluída."
            )
            if perf_debug_enabled():
                st.caption(f"Detalhe técnico: {p1_err}")
        k = _compute_top_kpis(
            df_camp, df_leads_canal_diario_all, canais_sel,
            ctx.data_ini, ctx.data_fim,
        )
        _render_financeiro_volume(ctx, k, total_dias)
        perf_mark_kpi_rendered(PAGE_CAMPAIGNS)
    except Exception as exc:
        logger.exception("Falha nos cards Financeiro/Volume")
        st.error("Não foi possível renderizar Financeiro e Volume.")
        if perf_debug_enabled():
            st.caption(f"Detalhe técnico: {exc}")

    # --- P2: Funil (campanha_funil + oficiais condicionais) ---
    _render_funil_section(ctx)

    # --- P3: Tendência (memória) ---
    _render_tendencia(df_camp, df_leads_canal_diario_all, canais_sel)

    # --- P4: Objetivo + tabela (leads_por_utm deferido) ---
    _render_objetivo_e_tabela(ctx, df_camp)

    # --- P5: Comparar campanhas (paginas_variantes deferido) ---
    _render_comparar_campanhas(ctx, df_camp)

    perf_finalize_page(PAGE_CAMPAIGNS)
    perf_render_panel(PAGE_CAMPAIGNS)


main()
