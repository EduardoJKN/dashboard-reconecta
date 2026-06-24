from datetime import timedelta

import pandas as pd
import streamlit as st

from src.repositories import (
    get_executivas,
    get_executivas_churn_pos_venda,
    get_executivas_oficiais,
    get_executivas_oficiais_todas,
    get_investimento_diario,
    get_leads_visao_geral,
    get_media_movel_vendas,
    get_vendas_leads_detalhe_diario,
)
from src.transforms import (
    EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS,
    EXECUTIVAS_RANKING_METRIC_OPTIONS,
    delta_pct,
    executivas_churn_agregar_por_executiva,
    executivas_churn_filtrar_closer,
    executivas_churn_filtrar_recorte,
    RANKING_EXIBICAO_ATIVOS,
    RANKING_EXIBICAO_HISTORICO,
    executivas_filtrar_time_oficial,
    executivas_ranking,
    executivas_ranking_base_exibicao,
    executivas_ranking_com_churn,
    executivas_ranking_plot_churn,
    ranking_dividir_principal_detalhado,
    receita_por_mes,
    vendas_detalhe_filtrar_closer,
    vendas_detalhe_filtrar_time,
    vendas_detalhe_mask_por_metrica,
    vendas_normalizar_detalhe,
    visao_geral_kpis,
)
from src.ui.charts import bar_ranked, receita_vs_meta_mensal
from src.ui.components import (
    hero_revenue_card,
    metric_card_v2,
    ranking_column_config,
    section_title,
)
from src.ui.page import start_page
from src.ui.theme import brl, brl_short, int_br, pct

# ---------------------------------------------------------------------------
# Page header + filtros globais
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Visão Geral",
    subtitle="Performance comercial consolidada",
    filters=["closer", "times"],
    right_text="Painel Executivo",
)

col_map = {"closer": "executiva", "times": "time_vendas"}

# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
try:
    df_exec_all = get_executivas(ctx.data_ini, ctx.data_fim)
    df_inv_all = get_investimento_diario(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar Postgres: {e}")
    st.stop()

# Leads — fonte oficial (ext_reconecta.leads + lead→deal priority match
# para resolver closer/time). Substitui bi.vw_funil_leads_diario, que não
# tinha dimensão de closer/time e não respondia aos filtros da página.
# Validado abr/2026: total=854, Leidianne=156, Marcelo=180, Hawinne=63.
try:
    df_leads_all = get_leads_visao_geral(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.warning(f"Falha ao consultar leads: {e}")
    df_leads_all = None

# Média móvel de vendas (sempre últimos 21 dias absolutos)
try:
    media_movel_val = get_media_movel_vendas()
except Exception as e:
    st.warning(f"Falha ao consultar média móvel de vendas: {e}")
    media_movel_val = None

df_exec_bruto = ctx.apply_filters(df_exec_all, col_map)

# ---------------------------------------------------------------------------
# Duas bases coexistem nesta página:
#
#   `df_exec_bruto`     → todas as linhas da view, depois de aplicar SÓ os
#                         filtros globais do header (Closer / Times /
#                         Período). Inclui closers que saíram do time no
#                         meio do período — as vendas deles continuam
#                         sendo vendas reais do mês e devem aparecer nos
#                         KPIs gerais (Receita, Montante, Vendas Novas,
#                         Ticket, Conversão Global) e na Receita mensal.
#                         Casa com o número do Looker / One Page.
#
#   `df_exec_filtrado`  → bruto + `executivas_filtrar_time_oficial`
#                         (cadastro `fdw_reconecta.executivas_vendas WHERE
#                         ativo='y'`). Usado em rankings, Top Closers e
#                         tabelas onde a análise é por pessoa do time
#                         atual. Sobrescreve `executiva` pelo nome
#                         oficial canônico — depois disso, chamar
#                         `executivas_ranking_oficiais` no ranking vira
#                         no-op.
#
# Quando o usuário aplica Closer/Times no header, `apply_filters` já
# atua antes dos dois ramos — portanto o filtro do usuário propaga
# tanto pros KPIs quanto pros rankings.
#
# Fallback silencioso: FDW indisponível → `df_exec_filtrado` fica igual
# ao bruto e exibe caption avisando o ranking sem filtro de time oficial.
# ---------------------------------------------------------------------------
try:
    _df_oficiais_home = get_executivas_oficiais()
    _falha_oficiais_home = False
except Exception:
    _df_oficiais_home = None
    _falha_oficiais_home = True

try:
    _df_oficiais_todas_home = get_executivas_oficiais_todas()
except Exception:
    _df_oficiais_todas_home = None

if _df_oficiais_home is not None and not _df_oficiais_home.empty:
    df_exec_filtrado = executivas_filtrar_time_oficial(
        df_exec_bruto, _df_oficiais_home,
    )
else:
    df_exec_filtrado = df_exec_bruto
    if _falha_oficiais_home:
        st.caption(
            "⚠ Não foi possível ler `fdw_reconecta.executivas_vendas` — "
            "rankings exibidos sem o filtro do time oficial."
        )

if df_exec_bruto.empty:
    st.warning("Nenhum registro para o filtro atual.")
    st.stop()

_times_sel_home_churn = list(ctx.selections.get("times") or [])
_closers_sel_home_churn = list(ctx.selections.get("closer") or [])
try:
    _df_churn_all_home = get_executivas_churn_pos_venda()
except Exception:
    _df_churn_all_home = pd.DataFrame()

# Período anterior (mesmo tamanho) para os deltas. Mantém as duas
# bases pareadas (apples-to-apples): KPIs comparam bruto×bruto,
# rankings comparam filtrado×filtrado.
dias_periodo = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias_periodo - 1)
try:
    df_exec_prev_bruto = ctx.refilter(
        get_executivas(prev_ini, prev_fim), col_map,
    )
    if _df_oficiais_home is not None and not _df_oficiais_home.empty:
        df_exec_prev_filtrado = executivas_filtrar_time_oficial(
            df_exec_prev_bruto, _df_oficiais_home,
        )
    else:
        df_exec_prev_filtrado = df_exec_prev_bruto
    df_inv_prev = get_investimento_diario(prev_ini, prev_fim)
except Exception:
    df_exec_prev_bruto    = df_exec_bruto.iloc[0:0]
    df_exec_prev_filtrado = df_exec_filtrado.iloc[0:0]
    df_inv_prev = df_inv_all.iloc[0:0]

# Leads do período anterior (para delta) — mesmo refilter que o atual
try:
    df_leads_prev_all = (
        get_leads_visao_geral(prev_ini, prev_fim)
        if df_leads_all is not None else None
    )
except Exception:
    df_leads_prev_all = None

k = visao_geral_kpis(df_exec_bruto, df_inv_all)
kp = visao_geral_kpis(df_exec_prev_bruto, df_inv_prev)

# ---------------------------------------------------------------------------
# Bloco financeiro
# ---------------------------------------------------------------------------
section_title(
    "Financeiro",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

fc1, fc2, fc3 = st.columns([1.3, 1, 1], gap="small")
with fc1:
    hero_revenue_card(
        receita_fmt=brl(k["receita"]),
        meta_fmt=brl_short(k["meta"]),
        pct_atingimento=k["pct_atingimento"],
        status=k["meta_status"],
    )
with fc2:
    metric_card_v2(
        "Montante",
        brl(k["montante"]),
        delta_pct=delta_pct(k["montante"], kp["montante"]),
        hint=f"Recebimento: {pct(k['pct_recebimento'])}",
    )
with fc3:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"]),
        delta_pct=delta_pct(k["investimento"], kp["investimento"]),
        hint="variação vs. período anterior",
    )

# ---------------------------------------------------------------------------
# Bloco operacional
# ---------------------------------------------------------------------------
section_title("Operacional", "volume, conversão e eficiência")

s1, s2, s3, s4 = st.columns(4, gap="small")
with s1:
    if df_leads_all is not None:
        # Aplica os mesmos filtros (Closer / Times) já populados pelo
        # df_exec_all. `refilter` reaproveita as seleções renderizadas no
        # 1º apply_filters; col_map mapeia para as colunas da nova fonte.
        leads_col_map = {"closer": "executiva", "times": "time_vendas"}
        df_leads = ctx.refilter(df_leads_all, leads_col_map)
        leads_atual = len(df_leads)
        leads_prev = (
            len(ctx.refilter(df_leads_prev_all, leads_col_map))
            if df_leads_prev_all is not None else None
        )
        metric_card_v2(
            "Leads Totais",
            int_br(leads_atual),
            delta_pct=delta_pct(leads_atual, leads_prev) if leads_prev is not None else None,
            hint="leads únicos/dia · ext_reconecta.leads",
        )
    else:
        metric_card_v2("Leads Totais", "—",
                       hint="fonte de leads indisponível")
with s2:
    metric_card_v2(
        "Vendas Novas",
        int_br(k["novos"]),
        delta_pct=delta_pct(k["novos"], kp["novos"]),
        hint=f"Asc. {int_br(k['ascensoes'])} · Ren. {int_br(k['renovacoes'])} · "
             f"Ind. {int_br(k['indicacoes'])}",
    )
    if media_movel_val is not None:
        ritmo_fmt = f"{media_movel_val:.1f}".replace(".", ",")
        st.markdown(
            f'<div class="kpi-foot">Ritmo últimos 21 dias: <b>{ritmo_fmt}</b> vendas/dia</div>',
            unsafe_allow_html=True,
        )
with s3:
    metric_card_v2(
        "Ticket Médio",
        brl(k["ticket_medio"]),
        delta_pct=delta_pct(k["ticket_medio"], kp["ticket_medio"]),
        hint="montante ÷ vendas",
    )
with s4:
    metric_card_v2(
        "Conversão Global",
        pct(k["conversao_global"]),
        delta_pct=delta_pct(k["conversao_global"], kp["conversao_global"]),
        hint="vendas ÷ (vendas+perdidos+cancelados)",
    )

# ---------------------------------------------------------------------------
# Receita mensal — full width (header padronizado via section_title)
# ---------------------------------------------------------------------------
section_title("Receita mensal", "vs meta · variação mês a mês")
mensal = receita_por_mes(df_exec_bruto)
if mensal.empty:
    st.info("Sem dados mensais no período selecionado.")
else:
    st.plotly_chart(
        receita_vs_meta_mensal(mensal, height=320),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Top Closers — gráfico clicável + painel de detalhe nome a nome
# (espelha a UX do Top Closers da página Executivas & Times e do Top SDRs
# da Pré-vendas: selectbox de métrica, clique-na-barra abre detalhe).
#
# Respeita os filtros globais do header (Closer + Times + Período) tanto
# no ranking (já filtrado via ctx.apply_filters) quanto no detalhe
# (replicado abaixo via vendas_detalhe_filtrar_*).
# ---------------------------------------------------------------------------

_RANKING_METRIC_OPTIONS = EXECUTIVAS_RANKING_METRIC_OPTIONS
_METRICAS_FINANCEIRAS = EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS


def _safe_pct(num, den) -> float:
    try:
        d = float(den or 0)
        return (float(num or 0) / d) * 100 if d else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Carga do detalhe nome-a-nome — cache compartilhado com Pré-vendas via
# get_vendas_leads_detalhe_diario → get_prevendas_leads_detalhe_diario.
# ---------------------------------------------------------------------------
try:
    df_detalhe_home = get_vendas_leads_detalhe_diario(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao carregar detalhe linha-a-linha: {e}")
    df_detalhe_home = pd.DataFrame()

det_norm = vendas_normalizar_detalhe(df_detalhe_home)

# Replica os filtros globais (Closer e Times do header) no detalhe.
# Usa OR entre múltiplas seleções via helpers canônicos.
_closers_sel_home = list(ctx.selections.get("closer") or [])
_times_sel_home   = list(ctx.selections.get("times")  or [])

if det_norm is not None and not det_norm.empty:
    if _closers_sel_home and "closer_filtro" in det_norm.columns:
        _mask_c = pd.Series(False, index=det_norm.index)
        for _c in _closers_sel_home:
            _mask_c |= vendas_detalhe_filtrar_closer(det_norm, _c)
        det_norm = det_norm.loc[_mask_c].copy()
    if (_times_sel_home and not det_norm.empty
            and "time_vendas_filtro" in det_norm.columns):
        _mask_t = pd.Series(False, index=det_norm.index)
        for _t in _times_sel_home:
            _mask_t |= vendas_detalhe_filtrar_time(det_norm, _t)
        det_norm = det_norm.loc[_mask_t].copy()

# ---------------------------------------------------------------------------
# Seletores do Top Closers (só ranking + expanders; KPIs usam df_exec_bruto).
# ---------------------------------------------------------------------------
_HOME_SELECTBOX_METRIC_KEY = "home_top_closer_metric"
_metric_keys_home = list(_RANKING_METRIC_OPTIONS.keys())
_label_atual_home = st.session_state.get(_HOME_SELECTBOX_METRIC_KEY, "Receita")
if _label_atual_home == "Churn":
    _label_atual_home = "Clientes Cancelados"
if _label_atual_home not in _RANKING_METRIC_OPTIONS:
    _label_atual_home = "Receita"
metric_label_home = st.selectbox(
    "Métrica do ranking",
    options=_metric_keys_home,
    index=_metric_keys_home.index(_label_atual_home),
    key=_HOME_SELECTBOX_METRIC_KEY,
)
_exibicao_label_home = st.radio(
    "Exibição do ranking",
    options=("Ativos", "Todos / Histórico"),
    index=0,
    horizontal=True,
    key="home_ranking_modo_exibicao",
    help=(
        "Ativos: apenas executivas com `ativo='y'` no cadastro oficial.\n"
        "Todos / Histórico: closers com dados no período, inclusive "
        "inativos. O filtro de Closer/Times do header vale nos dois modos."
    ),
)
exibicao_ranking_home = (
    RANKING_EXIBICAO_HISTORICO
    if _exibicao_label_home == "Todos / Histórico"
    else RANKING_EXIBICAO_ATIVOS
)

df_ranking_base_home, _df_cadastro_ranking_home = executivas_ranking_base_exibicao(
    exibicao_ranking_home,
    df_exec_bruto,
    df_exec_filtrado,
    _df_oficiais_home,
    _df_oficiais_todas_home,
)
if (
    exibicao_ranking_home == RANKING_EXIBICAO_HISTORICO
    and (_df_oficiais_todas_home is None or _df_oficiais_todas_home.empty)
    and _falha_oficiais_home
):
    st.caption(
        "⚠ Cadastro histórico indisponível — exibindo closers da view "
        "sem normalização pelo FDW."
    )

_df_churn_home = executivas_churn_filtrar_recorte(
    _df_churn_all_home, ctx.data_ini, ctx.data_fim, _times_sel_home_churn,
)
if _closers_sel_home_churn:
    _mask_ch = pd.Series(False, index=_df_churn_home.index)
    for _c in _closers_sel_home_churn:
        _mask_ch |= executivas_churn_filtrar_closer(
            _df_churn_home, _c, _df_cadastro_ranking_home,
        )
    _df_churn_home = _df_churn_home.loc[_mask_ch].copy()

_churn_por_exec_home = executivas_churn_agregar_por_executiva(
    _df_churn_home, _df_cadastro_ranking_home,
)
ranking_home = executivas_ranking_com_churn(
    executivas_ranking(df_ranking_base_home),
    _churn_por_exec_home,
)

section_title(
    "Top Closers",
    f"ranking do período · {metric_label_home.lower()} · "
    f"{_exibicao_label_home.lower()}",
)
st.caption(
    "**Oportunidades** = deals criados no período · **Agendamentos** = reuniões "
    "na data da call (exc. Vencida) · **Comparecimentos** = status Concluída. "
    "Agendamentos e comparecimentos seguem o *owner* da activity no CRM."
)

if ranking_home is None or ranking_home.empty:
    st.info("Sem dados de ranking no período/filtros atuais.")
else:
    col_grafico_h, col_detalhe_h = st.columns([1.45, 1], gap="large")

    # =======================================================================
    # COLUNA ESQUERDA — selectbox + gráfico clicável
    # =======================================================================
    chart_state_home = None
    ranking_plot_home = pd.DataFrame()
    metric_col_home = "receita"
    with col_grafico_h:
        metric_col_home = _RANKING_METRIC_OPTIONS[metric_label_home]
        is_money_home = metric_col_home in _METRICAS_FINANCEIRAS

        if metric_col_home not in ranking_home.columns:
            st.warning(
                f"Coluna `{metric_col_home}` não está no ranking — "
                "possível schema drift na view."
            )
        else:
            if metric_col_home == "churn":
                ranking_plot_home = executivas_ranking_plot_churn(
                    _churn_por_exec_home,
                )
            else:
                ranking_plot_home = (
                    ranking_home[ranking_home[metric_col_home].fillna(0) > 0]
                    .sort_values(metric_col_home, ascending=False)
                    .copy()
                )
            if ranking_plot_home.empty:
                st.info(f"Sem **{metric_label_home.lower()}** no período.")
            else:
                fig_top_h = bar_ranked(
                    ranking_plot_home, "executiva", metric_col_home,
                    top_n=12, height=320, money=is_money_home,
                )
                chart_state_home = st.plotly_chart(
                    fig_top_h,
                    use_container_width=True,
                    key="home_top_closer_chart",
                    on_select="rerun",
                    selection_mode="points",
                )

    # =======================================================================
    # COLUNA DIREITA — painel retrátil com detalhe nome-a-nome
    # =======================================================================
    with col_detalhe_h:
        if ranking_plot_home.empty:
            with st.expander("Detalhe do closer selecionado", expanded=False):
                st.caption("Sem ranking pra detalhar nesta métrica/filtros.")
        elif det_norm is None or det_norm.empty:
            with st.expander("Detalhe do closer selecionado", expanded=False):
                st.caption(
                    "Detalhe linha-a-linha indisponível — "
                    "`get_vendas_leads_detalhe_diario` não devolveu linhas "
                    "para esse período/filtros."
                )
        else:
            closers_disp_home = (
                ranking_plot_home["executiva"].dropna().astype(str).tolist()
            )
            OPCAO_TODOS_HOME = "Todos"

            # ---- Sincronia clique-no-gráfico ↔ selectbox -------------------
            SELECTBOX_KEY_H  = "home_top_closer_detalhe"
            LAST_CLICK_KEY_H = "_home_top_closer_last_chart_pick"

            clicked_closer_h = None
            try:
                pts_h = (chart_state_home or {}).get("selection", {}).get("points", [])
            except Exception:
                pts_h = []
            if pts_h:
                cd = pts_h[0].get("customdata")
                if isinstance(cd, (list, tuple)) and cd:
                    clicked_closer_h = str(cd[0])
                elif isinstance(cd, str):
                    clicked_closer_h = cd
                elif pts_h[0].get("y") is not None:
                    y_clicked = str(pts_h[0]["y"])
                    clicked_closer_h = next(
                        (s for s in closers_disp_home
                         if s == y_clicked or s.startswith(y_clicked.rstrip("…"))),
                        None,
                    )

            if (clicked_closer_h
                    and clicked_closer_h in closers_disp_home
                    and clicked_closer_h != st.session_state.get(LAST_CLICK_KEY_H)):
                st.session_state[SELECTBOX_KEY_H]  = clicked_closer_h
                st.session_state[LAST_CLICK_KEY_H] = clicked_closer_h

            if st.session_state.get(SELECTBOX_KEY_H) not in (
                    [OPCAO_TODOS_HOME] + closers_disp_home):
                st.session_state[SELECTBOX_KEY_H] = OPCAO_TODOS_HOME

            closer_atual_h = st.session_state.get(SELECTBOX_KEY_H, OPCAO_TODOS_HOME)
            titulo_h = ("Detalhe do closer selecionado"
                        if closer_atual_h == OPCAO_TODOS_HOME
                        else f"Detalhe — {closer_atual_h}")

            with st.expander(titulo_h, expanded=False):
                st.caption(
                    "💡 **Clique numa barra do gráfico** para detalhar aquele "
                    "closer — ou use o seletor abaixo. 'Todos' mostra o consolidado."
                )
                closer_escolhido_h = st.selectbox(
                    "Closer para detalhar",
                    options=[OPCAO_TODOS_HOME] + closers_disp_home,
                    key=SELECTBOX_KEY_H,
                )

                if metric_col_home == "churn":
                    detalhe_disp_h = (
                        _df_churn_home is not None and not _df_churn_home.empty
                    )
                    if closer_escolhido_h == OPCAO_TODOS_HOME:
                        contagem_graf_h = int(
                            ranking_plot_home[metric_col_home].fillna(0).sum()
                        )
                        linhas_brutas_h = (
                            _df_churn_home.copy() if detalhe_disp_h else pd.DataFrame()
                        )
                    else:
                        try:
                            contagem_graf_h = int(
                                ranking_plot_home.loc[
                                    ranking_plot_home["executiva"] == closer_escolhido_h,
                                    metric_col_home,
                                ].iloc[0]
                            )
                        except (IndexError, KeyError):
                            contagem_graf_h = 0
                        if detalhe_disp_h:
                            _mh = executivas_churn_filtrar_closer(
                                _df_churn_home,
                                closer_escolhido_h,
                                _df_cadastro_ranking_home,
                            )
                            linhas_brutas_h = _df_churn_home.loc[_mh].copy()
                        else:
                            linhas_brutas_h = pd.DataFrame()
                    unidade_col_h = "deal_id"
                else:
                    mask_metrica_h = vendas_detalhe_mask_por_metrica(
                        det_norm, metric_col_home, ctx.data_ini, ctx.data_fim,
                    )
                    detalhe_disp_h = bool(mask_metrica_h.any())

                    if closer_escolhido_h == OPCAO_TODOS_HOME:
                        contagem_graf_h = int(
                            ranking_plot_home[metric_col_home].fillna(0).sum()
                        )
                        mask_closer_h = pd.Series(True, index=det_norm.index)
                    else:
                        try:
                            contagem_graf_h = int(
                                ranking_plot_home.loc[
                                    ranking_plot_home["executiva"] == closer_escolhido_h,
                                    metric_col_home,
                                ].iloc[0]
                            )
                        except (IndexError, KeyError):
                            contagem_graf_h = 0
                        mask_closer_h = vendas_detalhe_filtrar_closer(
                            det_norm, closer_escolhido_h,
                        )

                    linhas_brutas_h = det_norm[mask_closer_h & mask_metrica_h].copy()

                    unidade_col_h = ("deal_id"
                                     if metric_col_home in _METRICAS_FINANCEIRAS
                                        or metric_col_home.startswith("ganhos_")
                                        or metric_col_home == "vendas"
                                     else "activity_id")
                if unidade_col_h in linhas_brutas_h.columns:
                    contagem_tab_h = int(
                        linhas_brutas_h[unidade_col_h].nunique(dropna=False)
                    )
                    linhas_h = linhas_brutas_h.drop_duplicates(
                        subset=[unidade_col_h], keep="first",
                    ).copy()
                else:
                    contagem_tab_h = len(linhas_brutas_h)
                    linhas_h = linhas_brutas_h.copy()
                linhas_dup_h = len(linhas_brutas_h) - len(linhas_h)

                # ---------- Mini-cards de resumo (3+2) ---------------------
                if closer_escolhido_h == OPCAO_TODOS_HOME:
                    fonte_h = ranking_plot_home
                else:
                    fonte_h = ranking_plot_home.loc[
                        ranking_plot_home["executiva"] == closer_escolhido_h
                    ]

                def _sum_col_h(col):
                    return int(fonte_h[col].fillna(0).sum()) if col in fonte_h.columns else 0

                def _sum_money_h(col):
                    return float(fonte_h[col].fillna(0).sum()) if col in fonte_h.columns else 0.0

                st.markdown(
                    f"**{closer_escolhido_h}** · {metric_label_home}: "
                    f"gráfico {int_br(contagem_graf_h)} · "
                    f"tabela {int_br(contagem_tab_h)}"
                )

                mc1, mc2, mc3 = st.columns(3, gap="small")
                with mc1:
                    metric_card_v2("Vendas", int_br(_sum_col_h("vendas")),
                                   hint="deals ganhos · Novo cliente", accent=True)
                with mc2:
                    metric_card_v2("Agendamentos", int_br(_sum_col_h("agendamentos")),
                                   hint="status_reuniao IS NOT NULL")
                with mc3:
                    metric_card_v2("Comparecimentos", int_br(_sum_col_h("comparecimentos")),
                                   hint="status Concluída/Concluído")

                mc4, mc5 = st.columns(2, gap="small")
                with mc4:
                    rec_val_h = _sum_money_h("receita")
                    if rec_val_h == 0:
                        mont_val_h = _sum_money_h("montante")
                        label_rec_h = "Montante" if mont_val_h > 0 else "Receita"
                        val_rec_h = brl(mont_val_h) if mont_val_h > 0 else "—"
                    else:
                        label_rec_h, val_rec_h = "Receita", brl(rec_val_h)
                    metric_card_v2(label_rec_h, val_rec_h,
                                   hint="financeiro dos deals ganhos")
                with mc5:
                    vend_h = _sum_col_h("vendas")
                    mont_h = _sum_money_h("montante")
                    if vend_h > 0 and mont_h > 0:
                        metric_card_v2("Ticket médio", brl(mont_h / vend_h),
                                       hint="montante ÷ vendas")
                    else:
                        metric_card_v2("Ticket médio", "—",
                                       hint="montante ÷ vendas")

                # ---------- Avisos de divergência --------------------------
                if not detalhe_disp_h:
                    st.warning(
                        f"⚠ Métrica **{metric_label_home}** não tem detalhe "
                        "linha-a-linha disponível neste período (universos cobertos: "
                        "agendamentos, comparecimentos, vendas/ganhos, montante/receita, "
                        "cancelados, churn, vencidos)."
                    )
                elif contagem_tab_h != contagem_graf_h:
                    delta_h = contagem_tab_h - contagem_graf_h
                    if delta_h < 0:
                        st.warning(
                            f"Tabela: {int_br(contagem_tab_h)} · gráfico: "
                            f"{int_br(contagem_graf_h)} (faltam "
                            f"{int_br(abs(delta_h))}). Classificação no detalhe usa "
                            "2 fontes (CRM + ext); a view do ranking usa 4."
                        )
                    else:
                        st.warning(
                            f"Tabela: {int_br(contagem_tab_h)} · gráfico: "
                            f"{int_br(contagem_graf_h)} (sobram "
                            f"{int_br(delta_h)}). Pode haver `Cancelado` (masc.) no "
                            "detalhe que a view conta só como `Cancelada` (fem.)."
                        )

                if linhas_dup_h > 0:
                    st.caption(
                        f"⚙ Removidas {int_br(linhas_dup_h)} duplicata(s) "
                        f"por `{unidade_col_h}`."
                    )

                # ---------- Tabela resumida nome-a-nome --------------------
                if linhas_h.empty:
                    st.caption(
                        "Nenhum registro nome-a-nome encontrado para esse closer/métrica."
                    )
                else:
                    sort_cols_h = [
                        c for c in ("data_churn", "data_agendamento",
                                    "data_criacao", "data_venda",
                                    "deal_id", "activity_id")
                        if c in linhas_h.columns
                    ]
                    linhas_h = linhas_h.sort_values(
                        sort_cols_h, na_position="last",
                    ).reset_index(drop=True)
                    linhas_h.insert(0, "#", range(1, len(linhas_h) + 1))

                    if metric_col_home == "churn":
                        cols_map_resumo_h = [
                            ("#",              "#"),
                            ("nome_cliente",   "Cliente"),
                            ("email",          "E-mail"),
                            ("data_churn",     "Data churn"),
                            ("closer_nome",    "Closer"),
                            ("montante",       "Montante"),
                            ("receita",        "Receita"),
                        ]
                    else:
                        cols_map_resumo_h = [
                            ("#",                    "#"),
                            ("nome_cliente_view",    "Nome do cliente/lead"),
                            ("email_final_filtro",   "E-mail"),
                            ("classificacao_final_filtro", "Classificação"),
                            ("status_filtro",        "Status reunião"),
                            ("origem_fonte",         "Origem/fonte"),
                            ("data_agendamento",     "Data agendamento"),
                            ("sdr_filtro",           "SDR"),
                        ]
                    cols_resumo_h = [c for c, _ in cols_map_resumo_h
                                     if c in linhas_h.columns]
                    tabela_resumo_h = linhas_h[cols_resumo_h].rename(
                        columns={c: lbl for c, lbl in cols_map_resumo_h
                                 if c in cols_resumo_h}
                    )
                    cfg_resumo_h = {"#": st.column_config.NumberColumn("#", format="%d")}
                    if "Data agendamento" in tabela_resumo_h.columns:
                        cfg_resumo_h["Data agendamento"] = st.column_config.DateColumn(
                            "Data agendamento", format="DD/MM/YYYY"
                        )
                    if "Data churn" in tabela_resumo_h.columns:
                        cfg_resumo_h["Data churn"] = st.column_config.DateColumn(
                            "Data churn", format="DD/MM/YYYY"
                        )
                    for _mlh in ("Montante", "Receita"):
                        if _mlh in tabela_resumo_h.columns:
                            cfg_resumo_h[_mlh] = st.column_config.NumberColumn(
                                _mlh, format="R$ %.0f"
                            )
                    st.dataframe(
                        tabela_resumo_h,
                        use_container_width=True,
                        hide_index=True,
                        column_config=cfg_resumo_h,
                    )

                    ver_completa_h = st.toggle(
                        "Ver tabela completa",
                        value=False,
                        key="home_top_closer_ver_completa",
                    )
                    if ver_completa_h:
                        cols_map_full_h = [
                            ("#",                       "#"),
                            ("nome_cliente_view",       "Nome do cliente/lead"),
                            ("email_final_filtro",      "E-mail"),
                            ("email_lead_filtro",       "E-mail (lead)"),
                            ("email_crm_filtro",        "E-mail (CRM)"),
                            ("sdr_filtro",              "SDR"),
                            ("closer_filtro",           "Closer"),
                            ("time_vendas_filtro",      "Time"),
                            ("classificacao_filtro",    "Classif. (lead)"),
                            ("classificacao_crm_filtro","Classif. (CRM)"),
                            ("status_filtro",           "Status reunião"),
                            ("origem_fonte",            "Origem/fonte"),
                            ("data_criacao",            "Data de criação"),
                            ("data_agendamento",        "Data do agendamento"),
                            ("data_venda",              "Data da venda"),
                            ("deal_id",                 "ID do deal"),
                            ("activity_id",             "ID da activity"),
                            ("montante",                "Montante"),
                            ("receita",                 "Receita"),
                        ]
                        cols_full_h = [c for c, _ in cols_map_full_h
                                       if c in linhas_h.columns]
                        tabela_full_h = linhas_h[cols_full_h].rename(
                            columns={c: lbl for c, lbl in cols_map_full_h
                                     if c in cols_full_h}
                        )
                        cfg_full_h = {"#": st.column_config.NumberColumn("#", format="%d")}
                        for date_lbl in ("Data de criação", "Data do agendamento",
                                          "Data da venda"):
                            if date_lbl in tabela_full_h.columns:
                                cfg_full_h[date_lbl] = st.column_config.DateColumn(
                                    date_lbl, format="DD/MM/YYYY"
                                )
                        for money_lbl in ("Montante", "Receita"):
                            if money_lbl in tabela_full_h.columns:
                                cfg_full_h[money_lbl] = st.column_config.NumberColumn(
                                    money_lbl, format="R$ %.0f"
                                )
                        st.dataframe(
                            tabela_full_h,
                            use_container_width=True,
                            hide_index=True,
                            column_config=cfg_full_h,
                        )

    # =======================================================================
    # Expander fora do layout 2-cols — ranking completo agregado, dividido
    # em tabela principal (métricas-chave, ordem canônica) + tabela
    # complementar (demais colunas, p/ ex. buckets +12/-12, perdidos etc.).
    # A divisão vive em `ranking_dividir_principal_detalhado` p/ não
    # duplicar a lógica entre Visão Geral e Executivas & Times.
    # =======================================================================
    df_principal_home, df_detalhado_home = ranking_dividir_principal_detalhado(
        ranking_home
    )
    with st.expander("Ver ranking completo (todas as colunas/closers)"):
        st.dataframe(
            df_principal_home,
            use_container_width=True,
            hide_index=True,
            column_config=ranking_column_config(df_principal_home, pin_executiva=True),
        )
    if not df_detalhado_home.empty and len(df_detalhado_home.columns) > 1:
        with st.expander("Ver detalhes complementares do ranking"):
            st.dataframe(
                df_detalhado_home,
                use_container_width=True,
                hide_index=True,
                column_config=ranking_column_config(df_detalhado_home, pin_executiva=True),
            )
