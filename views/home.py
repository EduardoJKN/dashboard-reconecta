from datetime import timedelta

import pandas as pd
import streamlit as st

from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_leads_visao_geral,
    get_media_movel_vendas,
    get_vendas_leads_detalhe_diario,
)
from src.transforms import (
    delta_pct,
    executivas_ranking,
    receita_por_mes,
    vendas_detalhe_filtrar_closer,
    vendas_detalhe_filtrar_time,
    vendas_detalhe_mask_por_metrica,
    vendas_normalizar_detalhe,
    visao_geral_kpis,
)
from src.ui.charts import bar_ranked, receita_vs_meta_mensal
from src.ui.components import hero_revenue_card, metric_card_v2, section_title
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

df_exec = ctx.apply_filters(df_exec_all, col_map)

if df_exec.empty:
    st.warning("Nenhum registro para o filtro atual.")
    st.stop()

# Período anterior (mesmo tamanho) para os deltas
dias_periodo = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias_periodo - 1)
try:
    df_exec_prev = ctx.refilter(get_executivas(prev_ini, prev_fim), col_map)
    df_inv_prev = get_investimento_diario(prev_ini, prev_fim)
except Exception:
    df_exec_prev = df_exec.iloc[0:0]
    df_inv_prev = df_inv_all.iloc[0:0]

# Leads do período anterior (para delta) — mesmo refilter que o atual
try:
    df_leads_prev_all = (
        get_leads_visao_geral(prev_ini, prev_fim)
        if df_leads_all is not None else None
    )
except Exception:
    df_leads_prev_all = None

k = visao_geral_kpis(df_exec, df_inv_all)
kp = visao_geral_kpis(df_exec_prev, df_inv_prev)

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
mensal = receita_por_mes(df_exec)
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

_RANKING_METRIC_OPTIONS = {
    "Receita":          "receita",
    "Montante":         "montante",
    "Vendas":           "vendas",
    "Agendamentos":     "agendamentos",
    "Comparecimentos":  "comparecimentos",
    "Ganhos +12":       "ganhos_mais_12",
    "Ganhos -12":       "ganhos_menos_12",
    "Ganhos Não atua":  "ganhos_nao_atua",
    "Cancelados":       "cancelados",
    "Vencidos":         "vencidos",
}
_METRICAS_FINANCEIRAS = {
    "receita", "montante",
    "receita_mais_12", "receita_menos_12", "receita_nao_atua",
    "montante_mais_12", "montante_menos_12", "montante_nao_atua",
}


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
# Ranking enriquecido — base vem da view (executivas_ranking) e a coluna
# `vencidos` é injetada via detalhe (a view bi.vw_dashboard_comercial_
# executivas_rw ainda não expõe vencidos — estão lumpadas em agendamentos).
# ---------------------------------------------------------------------------
ranking_raw = executivas_ranking(df_exec)
if ranking_raw is None or ranking_raw.empty:
    ranking_home = ranking_raw
else:
    ranking_home = ranking_raw.copy()
    # Pcts/ticket já vêm calculados de executivas_ranking; aqui só
    # garantimos a coluna `vencidos`.
    if (det_norm is not None and not det_norm.empty
            and "activity_id" in det_norm.columns):
        _mask_v = vendas_detalhe_mask_por_metrica(
            det_norm, "vencidos", ctx.data_ini, ctx.data_fim,
        )
        _agg_v = (det_norm.loc[_mask_v]
                  .groupby("closer_filtro", as_index=False)
                  .agg(vencidos=("activity_id", "nunique")))
        _agg_v = _agg_v.rename(columns={"closer_filtro": "executiva"})
        ranking_home = ranking_home.merge(
            _agg_v, on="executiva", how="left",
        ).fillna({"vencidos": 0})
    else:
        ranking_home["vencidos"] = 0

# ---------------------------------------------------------------------------
# Header — label da métrica precisa ser resolvido ANTES das colunas
# (mesmo padrão do tab_rank de Executivas e do Top SDRs de Pré-vendas).
# ---------------------------------------------------------------------------
_HOME_SELECTBOX_METRIC_KEY = "home_top_closer_metric"
_label_atual_home = st.session_state.get(_HOME_SELECTBOX_METRIC_KEY, "Receita")
if _label_atual_home not in _RANKING_METRIC_OPTIONS:
    _label_atual_home = "Receita"
section_title("Top Closers", f"ranking do período · {_label_atual_home.lower()}")

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
        metric_label_home = st.selectbox(
            "Métrica do ranking",
            options=list(_RANKING_METRIC_OPTIONS.keys()),
            index=list(_RANKING_METRIC_OPTIONS.keys()).index(_label_atual_home),
            key=_HOME_SELECTBOX_METRIC_KEY,
        )
        metric_col_home = _RANKING_METRIC_OPTIONS[metric_label_home]
        is_money_home = metric_col_home in _METRICAS_FINANCEIRAS

        if metric_col_home not in ranking_home.columns:
            st.warning(
                f"Coluna `{metric_col_home}` não está no ranking — "
                "possível schema drift na view."
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
                        "cancelados, vencidos)."
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
                        c for c in ("data_agendamento", "data_criacao",
                                    "data_venda", "deal_id", "activity_id")
                        if c in linhas_h.columns
                    ]
                    linhas_h = linhas_h.sort_values(
                        sort_cols_h, na_position="last",
                    ).reset_index(drop=True)
                    linhas_h.insert(0, "#", range(1, len(linhas_h) + 1))

                    cols_map_resumo_h = [
                        ("#",                    "#"),
                        ("nome_cliente_view",    "Nome do cliente/lead"),
                        ("email_lead",           "E-mail"),
                        ("classificacao_filtro", "Classificação"),
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
                            ("email_lead",              "E-mail"),
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
    # Expander fora do layout 2-cols — ranking completo agregado
    # =======================================================================
    with st.expander("Ver ranking completo (todas as colunas/closers)"):
        st.dataframe(ranking_home, use_container_width=True, hide_index=True)
