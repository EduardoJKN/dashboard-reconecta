import pandas as pd
import streamlit as st

from src.repositories import (
    get_executivas,
    get_executivas_cancelamentos_pos_venda,
    get_executivas_churn_pos_venda,
    get_executivas_pos_contatos_email,
    get_executivas_oficiais,
    get_executivas_oficiais_todas,
    get_executivas_pos_vendas_oficiais,
    get_vendas_leads_detalhe_diario,
)
from src.transforms import (
    CANCEL_POS_SEM_IDENTIFICADO,
    EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS,
    EXECUTIVAS_RANKING_METRICAS_NEUTRAS,
    EXECUTIVAS_RANKING_METRIC_OPTIONS,
    RANKING_EXIBICAO_ATIVOS,
    RANKING_EXIBICAO_HISTORICO,
    cancelamentos_pos_diagnostico,
    cancelamentos_pos_filtrar_periodo,
    cancelamentos_pos_filtrar_periodo_atividades,
    cancelamentos_pos_filtrar_times,
    cancelamentos_pos_kpis,
    cancelamentos_pos_processar,
    cancelamentos_pos_ranking,
    executivas_churn_agregar_por_executiva,
    executivas_churn_filtrar_closer,
    executivas_churn_filtrar_recorte,
    executivas_churn_total,
    executivas_filtrar_time_oficial,
    executivas_ranking_base_exibicao,
    executivas_kpis,
    executivas_por_dia,
    executivas_por_time,
    executivas_ranking,
    executivas_ranking_com_churn,
    executivas_ranking_plot_churn,
    ranking_dividir_principal_detalhado,
    vendas_detalhe_filtrar_closer,
    vendas_detalhe_filtrar_time,
    vendas_detalhe_mask_por_metrica,
    vendas_normalizar_detalhe,
)
from src.ui.charts import bar_ranked, bar_simple, line
from src.ui.components import metric_card_v2, ranking_column_config, section_title
from src.ui.page import start_page
from src.ui.theme import brl, int_br, pct

# ---------------------------------------------------------------------------
# Seletor local de classificação — escolhe quais colunas da view alimentam
# os cards, ranking, funil e evolução. NÃO usa o sistema global de filtros
# (que filtra linhas por valor de coluna); aqui o que muda é a COLUNA lida.
# ---------------------------------------------------------------------------
_CLASSIF_OPTIONS = ["Todas", "+12", "-12", "Não atua", "Sem classificação"]

_SUFIXOS = {
    "+12":                "mais_12",
    "-12":                "menos_12",
    "Não atua":           "nao_atua",
    "Sem classificação":  "sem_classificacao",
}


def _classif_cols(classif: str) -> dict[str, str | None]:
    """Mapa do nome 'canônico' da métrica → coluna real do df, conforme o
    bucket selecionado. Quando o bucket não existe (montante/receita p/
    Sem classificação), o valor é None — a UI deve exibir '—' ou esconder
    o gráfico financeiro."""
    if classif == "Todas":
        return {
            "oportunidades":   "oportunidades",
            "agendamentos":    "agendamentos",
            "comparecimentos": "comparecimentos",
            "vendas":          "vendas",
            "montante":        "montante",
            "receita":         "receita",
        }
    suf = _SUFIXOS[classif]
    tem_fin = suf != "sem_classificacao"
    return {
        "oportunidades":   f"oportunidades_{suf}",
        "agendamentos":    f"agendamentos_{suf}",
        "comparecimentos": f"comparecimentos_{suf}",
        "vendas":          f"ganhos_{suf}",
        "montante":        f"montante_{suf}" if tem_fin else None,
        "receita":         f"receita_{suf}"  if tem_fin else None,
    }


def _safe_pct(num, den) -> float:
    try:
        d = float(den or 0)
        return (float(num or 0) / d) * 100 if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def _apply_classif(df, cmap):
    """Sobrescreve as colunas canônicas do df (oportunidades, agendamentos,
    comparecimentos, vendas, montante, receita) pelos buckets do `cmap`.
    Quando o cmap mapeia pra None (Sem classif p/ montante/receita), zera
    a canônica — caller decide se renderiza '—' depois."""
    out = df.copy()
    for canon, real in cmap.items():
        if real is None:
            out[canon] = 0
        elif real in out.columns:
            out[canon] = out[real]
    return out


# ---------------------------------------------------------------------------
# Header + filtro global de Times
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Executivas & Times",
    subtitle="Ranking por executiva e consolidação por time",
    filters=["times"],
    right_text="Análise detalhada",
)

try:
    df_all = get_executivas(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar: {e}")
    st.stop()

df_bruto = ctx.apply_filters(df_all, {"times": "time_vendas"})

# ---------------------------------------------------------------------------
# Duas bases coexistem nesta página (mesmo padrão da Visão Geral):
#
#   `df_bruto`     → todas as linhas da view depois de aplicar SÓ os
#                    filtros globais do header (Times / Período). Inclui
#                    closers que saíram do time no meio do período — as
#                    vendas deles continuam sendo vendas reais do mês e
#                    devem aparecer no Resumo do período e no Funil
#                    (KPIs gerais da página).
#
#   `df_filtrado`  → bruto + `executivas_filtrar_time_oficial`
#                    (`fdw_reconecta.executivas_vendas WHERE ativo='y'`).
#                    Sobrescreve `executiva` pelo nome canônico (Nathan
#                    Carloto → Nathan Carloto Ferreira Dos Santos, etc.).
#                    Alimenta análises por pessoa/time atual:
#                    Top Closers, "Por time" e "Evolução".
#
# Quando o usuário aplica Times no header, `apply_filters` já roda antes
# do split — a seleção propaga pros dois ramos.
#
# Fallback silencioso: FDW indisponível → `df_filtrado` cai pro bruto e
# caption avisa que os RANKINGS estão sem o filtro do time oficial.
# ---------------------------------------------------------------------------
try:
    _df_oficiais = get_executivas_oficiais()
    _falha_oficiais = False
except Exception:
    _df_oficiais = None
    _falha_oficiais = True

try:
    _df_oficiais_todas = get_executivas_oficiais_todas()
except Exception:
    _df_oficiais_todas = None

if _df_oficiais is not None and not _df_oficiais.empty:
    df_filtrado = executivas_filtrar_time_oficial(df_bruto, _df_oficiais)
else:
    df_filtrado = df_bruto
    if _falha_oficiais:
        st.caption(
            "⚠ Não foi possível ler `fdw_reconecta.executivas_vendas` — "
            "rankings exibidos sem o filtro do time oficial."
        )

if df_bruto.empty:
    st.warning("Sem dados para o filtro atual.")
    st.stop()

# Churn (stage Churn) — card do funil + métrica do Top Closers; independente
# da aba Cancelamentos por Pós-venda (activities Consulta canceladas).
_times_sel_churn = list(ctx.selections.get("times") or [])
try:
    _df_churn_all = get_executivas_churn_pos_venda()
except Exception:
    _df_churn_all = pd.DataFrame()
_df_churn_recorte = executivas_churn_filtrar_recorte(
    _df_churn_all, ctx.data_ini, ctx.data_fim, _times_sel_churn,
)
_churn_funil_total = executivas_churn_total(_df_churn_recorte)

# ---------------------------------------------------------------------------
# Seletor local de classificação (NÃO usa ctx.apply_filters — o sistema
# global filtra linhas; aqui o que muda é a coluna lida em cada métrica).
# ---------------------------------------------------------------------------
classif_sel = st.radio(
    "Classificação do lead",
    _CLASSIF_OPTIONS,
    horizontal=True,
    key="executivas_classif_local",
    help="Troca os buckets usados em cards, funil, ranking e evolução. "
         "Não filtra linhas — só muda qual coluna da view alimenta cada métrica.",
)
cmap = _classif_cols(classif_sel)
is_todas = classif_sel == "Todas"
tem_fin = cmap["montante"] is not None

# ---------------------------------------------------------------------------
# Totais do bucket selecionado + pcts recalculados
# ---------------------------------------------------------------------------
k = executivas_kpis(df_bruto)

opor_v = float(k.get(cmap["oportunidades"], 0) or 0)
agen_v = float(k.get(cmap["agendamentos"], 0)  or 0)
comp_v = float(k.get(cmap["comparecimentos"], 0) or 0)
vend_v = float(k.get(cmap["vendas"], 0) or 0)
mont_v = float(k.get(cmap["montante"], 0) or 0) if tem_fin else None
rec_v  = float(k.get(cmap["receita"], 0) or 0)  if tem_fin else None

pct_agen  = _safe_pct(agen_v, opor_v)
pct_comp  = _safe_pct(comp_v, agen_v)
pct_conv  = _safe_pct(vend_v, agen_v)
pct_vend  = _safe_pct(vend_v, comp_v)
ticket_v  = (mont_v / vend_v) if (tem_fin and vend_v) else None
pct_receb = _safe_pct(rec_v, mont_v) if tem_fin else None

# ---------------------------------------------------------------------------
# KPIs — 2 linhas de 4 cards (linha 1: financeiro; linha 2: taxas)
# ---------------------------------------------------------------------------
_resumo_caption = (
    "todos os leads, classificados ou não" if is_todas
    else f"apenas {classif_sel}"
)
section_title("Resumo do período", _resumo_caption)

# Linha 1 — financeiro (cai pra '—' quando Sem classif)
r1c1, r1c2, r1c3, r1c4 = st.columns(4, gap="small")
with r1c1:
    metric_card_v2(
        "Receita",
        brl(rec_v) if tem_fin else "—",
        hint=f"{int_br(vend_v)} vendas" + ("" if is_todas else " · Novo cliente"),
        accent=True,
    )
with r1c2:
    metric_card_v2(
        "Montante",
        brl(mont_v) if tem_fin else "—",
        hint=("SUM(montante) · período filtrado" if is_todas
              else f"SUM(montante_{_SUFIXOS[classif_sel]}) · Novo cliente"),
    )
with r1c3:
    metric_card_v2(
        "Ticket Médio",
        brl(ticket_v) if ticket_v is not None else "—",
        hint="montante ÷ vendas",
    )
with r1c4:
    metric_card_v2(
        "% Recebimento",
        pct(pct_receb) if pct_receb is not None else "—",
        hint="receita ÷ montante",
    )

# Linha 2 — taxas do funil (sempre disponíveis: dependem só de absolutos)
r2c1, r2c2, r2c3, r2c4 = st.columns(4, gap="small")
with r2c1:
    metric_card_v2("% Agendamento", pct(pct_agen),
                   hint="agend. ÷ oportunidades")
with r2c2:
    metric_card_v2("% Comparecimento", pct(pct_comp),
                   hint="comparec. ÷ agendamentos")
with r2c3:
    metric_card_v2("% Conversão", pct(pct_conv),
                   hint="vendas ÷ agendamentos")
with r2c4:
    metric_card_v2("% Vendas", pct(pct_vend),
                   hint="vendas ÷ comparecimentos")

# ---------------------------------------------------------------------------
# Funil 6 cards — cancelados e perdidos NÃO têm bucket na view, então
# mostram o total geral mesmo com classif. ativa (com hint explicativo).
# ---------------------------------------------------------------------------
_leads_label = "Leads" if is_todas else f"Oportunidades {classif_sel}"
_funil_hint  = (
    "leads → reunião agendada → reunião concluída → cancelados → churn → ganhos → perdidos"
    if is_todas
    else f"oportunidades {classif_sel} → reunião agendada → reunião concluída → "
         f"cancelados (total geral) → churn (total geral) → ganhos → perdidos (total geral)"
)
section_title("Funil (absolutos)", _funil_hint)
f1, f2, f3, f4, f5, f6, f7 = st.columns(7, gap="small")
with f1: metric_card_v2(_leads_label, int_br(opor_v))
with f2: metric_card_v2("Reunião Agendada", int_br(agen_v))
with f3: metric_card_v2("Reunião Concluída", int_br(comp_v))
with f4: metric_card_v2("Cancelados", int_br(k["cancelados"]))
with f5: metric_card_v2("Churn", int_br(_churn_funil_total))
with f6: metric_card_v2("Ganhos", int_br(vend_v))
with f7: metric_card_v2(
    "Perdidos", int_br(k["perdidos"]),
    hint=None if is_todas else "total geral · sem quebra por classif.",
)

# ---------------------------------------------------------------------------
# Tabs — Ranking / Por time / Evolução
# ---------------------------------------------------------------------------
tab_rank, tab_time, tab_temp, tab_cancel_pos = st.tabs(
    ["Ranking executivas", "Por time", "Evolução", "Cancelamentos por Pós-venda"]
)

with tab_rank:
    # =========================================================================
    # Top Closers — gráfico clicável à esquerda + painel de detalhe nome a
    # nome à direita. Padrão idêntico ao Top SDRs de Pré-vendas (mesma UX).
    #
    # Métricas neutras (Receita / Montante / Vendas / Agendamentos /
    # Comparecimentos) respeitam o seletor local de classificação no topo
    # da página — ex.: classif='+12' faz "Vendas" virar `ganhos_mais_12`.
    # Métricas explicitamente bucketed (Ganhos +12/-12/Não atua) usam a
    # coluna fixa, ignorando o classif (a métrica explícita ganha).
    # =========================================================================

    _RANKING_METRIC_OPTIONS = EXECUTIVAS_RANKING_METRIC_OPTIONS
    _METRICAS_NEUTRAS = EXECUTIVAS_RANKING_METRICAS_NEUTRAS
    _METRICAS_FINANCEIRAS = EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS

    def _resolve_metric_col(metric_base: str) -> str:
        """Aplica o classif local nas métricas neutras (cmap mapeia opor/
        agend/comp/vendas/montante/receita pro bucket). Métricas com bucket
        explícito no nome passam direto."""
        if metric_base in _METRICAS_NEUTRAS and metric_base in cmap and cmap[metric_base]:
            return cmap[metric_base]
        return metric_base

    # ------------------------------------------------------------------------
    # Carga do detalhe nome-a-nome (mesma query do detalhe de Pré-vendas;
    # `get_vendas_leads_detalhe_diario` delega pro cache compartilhado).
    # ------------------------------------------------------------------------
    try:
        df_detalhe = get_vendas_leads_detalhe_diario(ctx.data_ini, ctx.data_fim)
    except Exception as e:
        st.error(f"Falha ao carregar detalhe linha-a-linha: {e}")
        df_detalhe = pd.DataFrame()

    det_norm = vendas_normalizar_detalhe(df_detalhe)

    # Replica filtro global de Times no detalhe (o filtro global do header
    # já filtra `df_bruto`/`df_filtrado`, mas não toca em `df_detalhe`).
    # Usa o helper canônico com OR entre múltiplas seleções.
    _times_sel_global = list(ctx.selections.get("times") or [])
    if (det_norm is not None and not det_norm.empty
            and _times_sel_global
            and "time_vendas_filtro" in det_norm.columns):
        _mask_times = pd.Series(False, index=det_norm.index)
        for _t in _times_sel_global:
            _mask_times |= vendas_detalhe_filtrar_time(det_norm, _t)
        det_norm = det_norm.loc[_mask_times].copy()

    # ------------------------------------------------------------------------
    # Seletores do Top Closers (só esta aba + expanders de ranking).
    # ------------------------------------------------------------------------
    _SELECTBOX_METRIC_KEY = "executivas_ranking_metric"
    _metric_keys = list(_RANKING_METRIC_OPTIONS.keys())
    _default_metric = st.session_state.get(_SELECTBOX_METRIC_KEY, "Receita")
    if _default_metric not in _RANKING_METRIC_OPTIONS:
        _default_metric = "Receita"
    metric_label = st.selectbox(
        "Métrica do ranking",
        options=_metric_keys,
        index=_metric_keys.index(_default_metric),
        key=_SELECTBOX_METRIC_KEY,
    )
    _exibicao_label = st.radio(
        "Exibição do ranking",
        options=("Ativos", "Todos / Histórico"),
        index=0,
        horizontal=True,
        key="executivas_ranking_modo_exibicao",
        help=(
            "Ativos: apenas executivas com `ativo='y'` no cadastro oficial.\n"
            "Todos / Histórico: closers com dados no período, inclusive "
            "inativos. O filtro de TIMES do header vale nos dois modos."
        ),
    )
    exibicao_ranking = (
        RANKING_EXIBICAO_HISTORICO
        if _exibicao_label == "Todos / Histórico"
        else RANKING_EXIBICAO_ATIVOS
    )

    df_ranking_base, _df_cadastro_ranking = executivas_ranking_base_exibicao(
        exibicao_ranking,
        df_bruto,
        df_filtrado,
        _df_oficiais,
        _df_oficiais_todas,
    )
    if (
        exibicao_ranking == RANKING_EXIBICAO_HISTORICO
        and (_df_oficiais_todas is None or _df_oficiais_todas.empty)
        and _falha_oficiais
    ):
        st.caption(
            "⚠ Cadastro histórico indisponível — exibindo closers da view "
            "sem normalização pelo FDW."
        )

    # ------------------------------------------------------------------------
    # Ranking — base vem da view (executivas_ranking) com bucket do classif
    # aplicado. `vencidos` agora vem direto da view (mai/2026) e
    # `agendamentos` já é LÍQUIDO de `Vencida`, então o bucket selecionado
    # propaga corretamente sem ajuste extra. `_apply_classif` não toca em
    # `vencidos` — preservado como veio do groupby.
    # ------------------------------------------------------------------------
    _churn_por_exec = executivas_churn_agregar_por_executiva(
        _df_churn_recorte, _df_cadastro_ranking,
    )

    ranking_raw = executivas_ranking_com_churn(
        executivas_ranking(df_ranking_base),
        _churn_por_exec,
    )
    if ranking_raw.empty:
        ranking = ranking_raw
    else:
        ranking = _apply_classif(ranking_raw, cmap)
        if "churn" in ranking_raw.columns:
            ranking["churn"] = ranking_raw["churn"]
        # Recompõe pcts e ticket pra refletir o bucket selecionado.
        ranking["pct_conversao"] = ranking.apply(
            lambda r: _safe_pct(r.get("vendas", 0), r.get("agendamentos", 0)), axis=1)
        ranking["pct_comparecimento"] = ranking.apply(
            lambda r: _safe_pct(r.get("comparecimentos", 0), r.get("agendamentos", 0)), axis=1)
        ranking["pct_vendas"] = ranking.apply(
            lambda r: _safe_pct(r.get("vendas", 0), r.get("comparecimentos", 0)), axis=1)
        if tem_fin:
            ranking["pct_recebimento"] = ranking.apply(
                lambda r: _safe_pct(r.get("receita", 0), r.get("montante", 0)), axis=1)
            ranking["ticket_medio"] = ranking.apply(
                lambda r: (float(r["montante"]) / float(r["vendas"]))
                          if float(r.get("vendas", 0) or 0) > 0 else 0.0, axis=1)
        else:
            ranking["pct_recebimento"] = 0.0
            ranking["ticket_medio"]    = 0.0

    section_title(
        "Top Closers",
        f"ranking do período · {metric_label.lower()} · {classif_sel} · "
        f"{_exibicao_label.lower()}",
    )

    if ranking is None or ranking.empty:
        st.info("Sem dados de ranking no período/filtros atuais.")
    else:
        col_grafico, col_detalhe = st.columns([1.45, 1], gap="large")

        # ===================================================================
        # COLUNA ESQUERDA — selectbox de métrica + gráfico clicável
        # ===================================================================
        chart_state = None
        ranking_plot = pd.DataFrame()
        metric_col = "receita"
        with col_grafico:
            metric_base = _RANKING_METRIC_OPTIONS[metric_label]
            metric_col = _resolve_metric_col(metric_base)
            is_money = metric_col in _METRICAS_FINANCEIRAS

            # Aviso quando o classif sobrescreve o universo de uma métrica
            # neutra (ex.: classif='+12' + métrica='Vendas' → ganhos_mais_12).
            if metric_base in _METRICAS_NEUTRAS and metric_col != metric_base:
                st.caption(
                    f"🎯 Classificação **{classif_sel}** ativa — "
                    f"{metric_label.lower()} usa a coluna `{metric_col}`."
                )

            if metric_col not in ranking.columns:
                st.warning(
                    f"Coluna `{metric_col}` não está no ranking. "
                    "Pode ser efeito do classif='Sem classificação' em métrica financeira."
                )
            else:
                if metric_col == "churn":
                    ranking_plot = executivas_ranking_plot_churn(_churn_por_exec)
                else:
                    ranking_plot = ranking[ranking[metric_col].fillna(0) > 0].copy()
                    ranking_plot = ranking_plot.sort_values(
                        metric_col, ascending=False,
                    )

                if ranking_plot.empty:
                    st.info(f"Sem **{metric_label.lower()}** no período.")
                else:
                    fig_top = bar_ranked(
                        ranking_plot, "executiva", metric_col,
                        top_n=12, height=320, money=is_money,
                    )
                    chart_state = st.plotly_chart(
                        fig_top,
                        use_container_width=True,
                        key="executivas_ranking_chart",
                        on_select="rerun",
                        selection_mode="points",
                    )

        # ===================================================================
        # COLUNA DIREITA — painel retrátil de detalhe nome a nome
        # ===================================================================
        with col_detalhe:
            if ranking_plot.empty:
                with st.expander("Detalhe do closer selecionado", expanded=False):
                    st.caption("Sem ranking pra detalhar nesta métrica/filtro.")
            elif det_norm is None or det_norm.empty:
                with st.expander("Detalhe do closer selecionado", expanded=False):
                    st.caption(
                        "Detalhe linha-a-linha indisponível — "
                        "`get_vendas_leads_detalhe_diario` não devolveu linhas."
                    )
            else:
                closers_disponiveis = ranking_plot["executiva"].dropna().astype(str).tolist()
                OPCAO_TODAS = "Todos"

                # ---- Sincronia clique-no-gráfico ↔ selectbox -------------
                # `bar_ranked` injeta customdata = [[nome_completo_executiva]].
                # Detecta clique NOVO via _last_click_key — evita que Streamlit
                # "trave" no ponto persistido quando o user mexe no selectbox.
                SELECTBOX_KEY  = "executivas_top_closer_detalhe"
                LAST_CLICK_KEY = "_executivas_top_closer_last_chart_pick"

                clicked_closer = None
                try:
                    pts = (chart_state or {}).get("selection", {}).get("points", [])
                except Exception:
                    pts = []
                if pts:
                    cd = pts[0].get("customdata")
                    if isinstance(cd, (list, tuple)) and cd:
                        clicked_closer = str(cd[0])
                    elif isinstance(cd, str):
                        clicked_closer = cd
                    elif pts[0].get("y") is not None:
                        y_clicked = str(pts[0]["y"])
                        clicked_closer = next(
                            (s for s in closers_disponiveis
                             if s == y_clicked or s.startswith(y_clicked.rstrip("…"))),
                            None,
                        )

                if (clicked_closer
                        and clicked_closer in closers_disponiveis
                        and clicked_closer != st.session_state.get(LAST_CLICK_KEY)):
                    st.session_state[SELECTBOX_KEY]  = clicked_closer
                    st.session_state[LAST_CLICK_KEY] = clicked_closer

                if st.session_state.get(SELECTBOX_KEY) not in (
                        [OPCAO_TODAS] + closers_disponiveis):
                    st.session_state[SELECTBOX_KEY] = OPCAO_TODAS

                closer_atual = st.session_state.get(SELECTBOX_KEY, OPCAO_TODAS)
                titulo = ("Detalhe do closer selecionado" if closer_atual == OPCAO_TODAS
                          else f"Detalhe — {closer_atual}")

                with st.expander(titulo, expanded=False):
                    st.caption(
                        "💡 **Clique numa barra do gráfico** para detalhar aquele "
                        "closer — ou use o seletor abaixo. 'Todos' mostra o consolidado."
                    )
                    closer_escolhido = st.selectbox(
                        "Closer para detalhar",
                        options=[OPCAO_TODAS] + closers_disponiveis,
                        key=SELECTBOX_KEY,
                    )

                    if metric_col == "churn":
                        detalhe_disponivel = (
                            _df_churn_recorte is not None
                            and not _df_churn_recorte.empty
                        )
                        if closer_escolhido == OPCAO_TODAS:
                            contagem_grafico = int(
                                ranking_plot[metric_col].fillna(0).sum()
                            )
                            linhas_brutas = (
                                _df_churn_recorte.copy()
                                if detalhe_disponivel else pd.DataFrame()
                            )
                        else:
                            try:
                                contagem_grafico = int(
                                    ranking_plot.loc[
                                        ranking_plot["executiva"] == closer_escolhido,
                                        metric_col,
                                    ].iloc[0]
                                )
                            except (IndexError, KeyError):
                                contagem_grafico = 0
                            if detalhe_disponivel:
                                _m = executivas_churn_filtrar_closer(
                                    _df_churn_recorte,
                                    closer_escolhido,
                                    _df_cadastro_ranking,
                                )
                                linhas_brutas = _df_churn_recorte.loc[_m].copy()
                            else:
                                linhas_brutas = pd.DataFrame()
                        unidade_col = "deal_id"
                    else:
                        mask_metrica = vendas_detalhe_mask_por_metrica(
                            det_norm, metric_col, ctx.data_ini, ctx.data_fim,
                        )
                        detalhe_disponivel = bool(mask_metrica.any())

                        if closer_escolhido == OPCAO_TODAS:
                            contagem_grafico = int(
                                ranking_plot[metric_col].fillna(0).sum()
                            )
                            mask_closer = pd.Series(True, index=det_norm.index)
                        else:
                            try:
                                contagem_grafico = int(
                                    ranking_plot.loc[
                                        ranking_plot["executiva"] == closer_escolhido,
                                        metric_col,
                                    ].iloc[0]
                                )
                            except (IndexError, KeyError):
                                contagem_grafico = 0
                            mask_closer = vendas_detalhe_filtrar_closer(
                                det_norm, closer_escolhido,
                            )

                        linhas_brutas = det_norm[mask_closer & mask_metrica].copy()

                        # Dedup: vendas/financeiro por deal; resto por activity.
                        unidade_col = ("deal_id"
                                       if metric_col in _METRICAS_FINANCEIRAS
                                          or metric_col.startswith("ganhos_")
                                          or metric_col == "vendas"
                                       else "activity_id")
                    if unidade_col in linhas_brutas.columns:
                        contagem_tabela = int(linhas_brutas[unidade_col].nunique(dropna=False))
                        linhas = linhas_brutas.drop_duplicates(
                            subset=[unidade_col], keep="first",
                        ).copy()
                    else:
                        contagem_tabela = len(linhas_brutas)
                        linhas = linhas_brutas.copy()
                    linhas_duplicadas = len(linhas_brutas) - len(linhas)

                    # ---------- Mini-cards de resumo (5 cards: 3+2) -------
                    if closer_escolhido == OPCAO_TODAS:
                        fonte = ranking_plot
                    else:
                        fonte = ranking_plot.loc[ranking_plot["executiva"] == closer_escolhido]

                    def _sum_col(col):
                        return int(fonte[col].fillna(0).sum()) if col in fonte.columns else 0

                    def _sum_money(col):
                        return float(fonte[col].fillna(0).sum()) if col in fonte.columns else 0.0

                    st.markdown(
                        f"**{closer_escolhido}** · {metric_label}: "
                        f"gráfico {int_br(contagem_grafico)} · "
                        f"tabela {int_br(contagem_tabela)}"
                    )

                    mc1, mc2, mc3 = st.columns(3, gap="small")
                    with mc1:
                        metric_card_v2("Vendas", int_br(_sum_col("vendas")),
                                       hint="deals ganhos · Novo cliente", accent=True)
                    with mc2:
                        metric_card_v2("Agendamentos", int_br(_sum_col("agendamentos")),
                                       hint="status_reuniao IS NOT NULL")
                    with mc3:
                        metric_card_v2("Comparecimentos", int_br(_sum_col("comparecimentos")),
                                       hint="status Concluída/Concluído")

                    mc4, mc5 = st.columns(2, gap="small")
                    with mc4:
                        rec_val = _sum_money("receita")
                        if rec_val == 0 and not tem_fin:
                            label_rec, val_rec = "Receita", "—"
                        elif rec_val == 0:
                            label_rec = "Montante"
                            val_rec = brl(_sum_money("montante"))
                        else:
                            label_rec, val_rec = "Receita", brl(rec_val)
                        metric_card_v2(label_rec, val_rec,
                                       hint="financeiro dos deals ganhos")
                    with mc5:
                        vend_v_local = _sum_col("vendas")
                        mont_v_local = _sum_money("montante")
                        if tem_fin and vend_v_local > 0:
                            tk = mont_v_local / vend_v_local
                            metric_card_v2("Ticket médio", brl(tk),
                                           hint="montante ÷ vendas")
                        else:
                            metric_card_v2("Ticket médio", "—",
                                           hint="montante ÷ vendas")

                    # ---------- Avisos de divergência ---------------------
                    if not detalhe_disponivel:
                        st.warning(
                            f"⚠ Métrica **{metric_label}** não tem detalhe linha-a-linha "
                            "disponível neste período (universos cobertos: agendamentos, "
                            "comparecimentos, vendas/ganhos, montante/receita, cancelados, "
                            "churn, vencidos)."
                        )
                    elif contagem_tabela != contagem_grafico:
                        delta = contagem_tabela - contagem_grafico
                        if delta < 0:
                            st.warning(
                                f"Tabela: {int_br(contagem_tabela)} · gráfico: "
                                f"{int_br(contagem_grafico)} (faltam {int_br(abs(delta))}). "
                                "Classificação no detalhe usa 2 fontes (CRM + ext); "
                                "o ranking da view usa 4. Diferença esperada quando "
                                "deal está classificado SÓ por `qualificacao` ou "
                                "`classificado_cal`."
                            )
                        else:
                            st.warning(
                                f"Tabela: {int_br(contagem_tabela)} · gráfico: "
                                f"{int_br(contagem_grafico)} (sobram {int_br(delta)}). "
                                "Pode haver `Cancelado` (masc.) no detalhe que a view "
                                "ainda conta só como `Cancelada` (fem.)."
                            )

                    if linhas_duplicadas > 0:
                        st.caption(
                            f"⚙ Removidas {int_br(linhas_duplicadas)} duplicata(s) "
                            f"por `{unidade_col}`."
                        )

                    # ---------- Tabela resumida nome-a-nome ---------------
                    if linhas.empty:
                        st.caption(
                            "Nenhum registro nome-a-nome encontrado para esse closer/métrica."
                        )
                    else:
                        sort_cols = [
                            c for c in ("data_churn", "data_agendamento",
                                        "data_criacao", "data_venda",
                                        "deal_id", "activity_id")
                            if c in linhas.columns
                        ]
                        linhas = linhas.sort_values(
                            sort_cols, na_position="last",
                        ).reset_index(drop=True)
                        linhas.insert(0, "#", range(1, len(linhas) + 1))

                        if metric_col == "churn":
                            cols_map_resumo = [
                                ("#",              "#"),
                                ("nome_cliente",   "Cliente"),
                                ("email",          "E-mail"),
                                ("data_churn",     "Data churn"),
                                ("closer_nome",    "Closer"),
                                ("montante",       "Montante"),
                                ("receita",        "Receita"),
                            ]
                        else:
                            cols_map_resumo = [
                                ("#",                    "#"),
                                ("nome_cliente_view",    "Nome do cliente/lead"),
                                ("email_lead",           "E-mail"),
                                ("classificacao_filtro", "Classificação"),
                                ("status_filtro",        "Status reunião"),
                                ("origem_fonte",         "Origem/fonte"),
                                ("data_agendamento",     "Data agendamento"),
                                ("sdr_filtro",           "SDR"),
                            ]
                        cols_resumo = [c for c, _ in cols_map_resumo
                                       if c in linhas.columns]
                        tabela_resumo = linhas[cols_resumo].rename(
                            columns={c: lbl for c, lbl in cols_map_resumo
                                     if c in cols_resumo}
                        )
                        cfg_resumo = {"#": st.column_config.NumberColumn("#", format="%d")}
                        if "Data agendamento" in tabela_resumo.columns:
                            cfg_resumo["Data agendamento"] = st.column_config.DateColumn(
                                "Data agendamento", format="DD/MM/YYYY"
                            )
                        if "Data churn" in tabela_resumo.columns:
                            cfg_resumo["Data churn"] = st.column_config.DateColumn(
                                "Data churn", format="DD/MM/YYYY"
                            )
                        for _ml in ("Montante", "Receita"):
                            if _ml in tabela_resumo.columns:
                                cfg_resumo[_ml] = st.column_config.NumberColumn(
                                    _ml, format="R$ %.0f"
                                )
                        st.dataframe(
                            tabela_resumo,
                            use_container_width=True,
                            hide_index=True,
                            column_config=cfg_resumo,
                        )

                        # Toggle "Ver tabela completa" (Streamlit não permite
                        # expander aninhado dentro de expander).
                        ver_completa = st.toggle(
                            "Ver tabela completa",
                            value=False,
                            key="executivas_top_closer_ver_completa",
                        )
                        if ver_completa:
                            cols_map_full = [
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
                            cols_full = [c for c, _ in cols_map_full
                                         if c in linhas.columns]
                            tabela_full = linhas[cols_full].rename(
                                columns={c: lbl for c, lbl in cols_map_full
                                         if c in cols_full}
                            )
                            cfg_full = {"#": st.column_config.NumberColumn("#", format="%d")}
                            for date_lbl in ("Data de criação", "Data do agendamento",
                                              "Data da venda"):
                                if date_lbl in tabela_full.columns:
                                    cfg_full[date_lbl] = st.column_config.DateColumn(
                                        date_lbl, format="DD/MM/YYYY"
                                    )
                            for money_lbl in ("Montante", "Receita"):
                                if money_lbl in tabela_full.columns:
                                    cfg_full[money_lbl] = st.column_config.NumberColumn(
                                        money_lbl, format="R$ %.0f"
                                    )
                            st.dataframe(
                                tabela_full,
                                use_container_width=True,
                                hide_index=True,
                                column_config=cfg_full,
                            )

        # ===================================================================
        # Expander auxiliar fora das 2 colunas — ranking completo, dividido
        # em tabela principal (métricas-chave, ordem canônica) + tabela
        # complementar (demais colunas, incluindo buckets +12/-12 etc.).
        # Mesma divisão é usada na Visão Geral (views/home.py) via
        # `ranking_dividir_principal_detalhado` em src/transforms.py.
        # ===================================================================
        df_principal, df_detalhado = ranking_dividir_principal_detalhado(ranking)
        with st.expander("Ver ranking completo (todas as colunas/closers)"):
            st.dataframe(
                df_principal,
                use_container_width=True,
                hide_index=True,
                column_config=ranking_column_config(df_principal, pin_executiva=True),
            )
        if not df_detalhado.empty and len(df_detalhado.columns) > 1:
            with st.expander("Ver detalhes complementares do ranking"):
                st.dataframe(
                    df_detalhado,
                    use_container_width=True,
                    hide_index=True,
                    column_config=ranking_column_config(df_detalhado, pin_executiva=True),
                )

with tab_time:
    por_time_raw = executivas_por_time(df_filtrado)
    if por_time_raw.empty:
        st.info("Sem dados de time no filtro atual.")
    else:
        por_time = _apply_classif(por_time_raw, cmap)
        # Recalcula pcts/ticket no bucket selecionado (mesmo padrão do ranking).
        por_time["pct_conversao"] = por_time.apply(
            lambda r: _safe_pct(r.get("vendas", 0), r.get("agendamentos", 0)), axis=1
        )
        por_time["pct_vendas"] = por_time.apply(
            lambda r: _safe_pct(r.get("vendas", 0), r.get("comparecimentos", 0)), axis=1
        )
        if tem_fin:
            por_time["ticket_medio"] = por_time.apply(
                lambda r: (float(r["montante"]) / float(r["vendas"]))
                          if float(r.get("vendas", 0) or 0) > 0 else 0.0,
                axis=1,
            )
        else:
            por_time["ticket_medio"] = 0.0

        section_title("Consolidação por time", classif_sel)
        c1, c2 = st.columns(2, gap="large")
        with c1:
            if tem_fin:
                st.plotly_chart(
                    bar_simple(por_time, "time_vendas", "receita", money=True, rotate_x=True),
                    use_container_width=True,
                )
            else:
                st.info(
                    "Receita não disponível para **Sem classificação** — "
                    "a view só expõe valores financeiros nos buckets +12, -12 e Não atua."
                )
        with c2:
            st.plotly_chart(
                bar_simple(por_time, "time_vendas", "vendas", rotate_x=True),
                use_container_width=True,
            )
        with st.expander("Tabela detalhada por time"):
            st.dataframe(por_time, use_container_width=True, hide_index=True)

with tab_temp:
    diario_raw = executivas_por_dia(df_filtrado)
    diario = _apply_classif(diario_raw, cmap)
    section_title(f"Funil diário (absolutos) · {classif_sel}")
    st.plotly_chart(
        line(diario, "data_ref",
             ["oportunidades", "agendamentos", "comparecimentos", "vendas"],
             height=340),
        use_container_width=True,
    )
    if tem_fin:
        section_title("Receita × Montante (diário)")
        st.plotly_chart(
            line(diario, "data_ref", ["receita", "montante"],
                 height=280, money_axis="y"),
            use_container_width=True,
        )
    else:
        st.caption(
            "📊 Receita × Montante não disponível para **Sem classificação** — "
            "a view só expõe valores financeiros para os buckets +12, -12 e Não atua."
        )

with tab_cancel_pos:
    # =========================================================================
    # Cancelamentos por Pós-venda — mesmo universo do card "Cancelados"
    # (Consulta + status Cancelada/Cancelado). Não altera card Churn nem
    # ranking de Churn (stage Churn em deals).
    # =========================================================================
    _CANCEL_VISAO_KEY = "executivas_cancel_pos_visao"
    visao_cancel = st.radio(
        "Visão",
        ["Período selecionado", "Histórico total"],
        horizontal=True,
        key=_CANCEL_VISAO_KEY,
        help="Período usa o filtro global de datas (data do cancelamento). "
             "Histórico lista todos os cancelamentos de consulta na base "
             "(respeitando filtro de Times do header, quando ativo).",
    )
    visao_periodo = visao_cancel == "Período selecionado"
    _cancelados_funil = int(k.get("cancelados", 0) or 0)

    try:
        df_acts_raw = get_executivas_cancelamentos_pos_venda()
    except Exception as e:
        st.error(f"Falha ao carregar cancelamentos: {e}")
        df_acts_raw = None

    try:
        df_pos_contatos = get_executivas_pos_contatos_email()
    except Exception as e:
        st.warning(f"Falha ao carregar contatos de pós por e-mail: {e}")
        df_pos_contatos = pd.DataFrame()

    _falha_cadastro_pos = False
    try:
        _df_pos_oficiais = get_executivas_pos_vendas_oficiais()
    except Exception:
        _df_pos_oficiais = None
        _falha_cadastro_pos = True

    if _falha_cadastro_pos or _df_pos_oficiais is None or _df_pos_oficiais.empty:
        st.caption(
            "⚠ Cadastro `fdw_reconecta.executivas_pos_vendas` indisponível — "
            "nomes canônicos e flag Ativo? usam fallback (activities / notificação)."
        )
        _df_pos_oficiais = _df_pos_oficiais if _df_pos_oficiais is not None else pd.DataFrame()

    if df_acts_raw is None or df_acts_raw.empty:
        st.info("Sem cancelamentos de consulta para exibir.")
        _diag = cancelamentos_pos_diagnostico(pd.DataFrame(), pd.DataFrame())
        kpi_periodo = cancelamentos_pos_kpis(pd.DataFrame())
        kpi_hist = kpi_periodo
        df_acts_periodo = pd.DataFrame()
        df_emails_periodo = pd.DataFrame()
        df_emails_hist = pd.DataFrame()
    else:
        df_acts_times = cancelamentos_pos_filtrar_times(
            df_acts_raw, _times_sel_churn,
        )
        df_acts_periodo = cancelamentos_pos_filtrar_periodo_atividades(
            df_acts_times, ctx.data_ini, ctx.data_fim,
        )
        df_emails_hist = cancelamentos_pos_processar(
            df_acts_times, df_pos_contatos, _df_pos_oficiais,
        )
        df_emails_periodo = cancelamentos_pos_processar(
            df_acts_periodo, df_pos_contatos, _df_pos_oficiais,
        )
        df_cancel_view = df_emails_periodo if visao_periodo else df_emails_hist

        kpi_periodo = cancelamentos_pos_kpis(df_emails_periodo)
        kpi_hist = cancelamentos_pos_kpis(df_emails_hist)
        _diag = cancelamentos_pos_diagnostico(df_acts_periodo, df_emails_periodo)

        if df_cancel_view.empty:
            st.info(
                "Nenhum e-mail cancelado no recorte atual."
                if visao_periodo
                else "Nenhum e-mail cancelado na base (com filtros atuais)."
            )

        if not df_cancel_view.empty:
            _cap_visao = (
                f"{ctx.data_ini:%d/%m/%Y} – {ctx.data_fim:%d/%m/%Y} · por e-mail"
                if visao_periodo
                else "histórico · correlação por e-mail (Times aplicado)"
            )
            section_title("Cancelamentos por Pós-venda", _cap_visao)
            st.caption(
                "Cancelamentos = Consulta com status Cancelada/Cancelado. "
                "A unidade da análise é o **e-mail** (deal → lead). "
                "Cruzamento com pós: `controle_notificacao_vendas`, "
                "`zoho_acompanhamentos` e activities de pós no mesmo e-mail."
            )

            if visao_periodo:
                c1, c2, c3, c4 = st.columns(4, gap="small")
                with c1:
                    metric_card_v2(
                        "E-mails cancelados no período",
                        int_br(kpi_periodo["total"]),
                        accent=True,
                        hint="1 linha por e-mail único no período",
                    )
                with c2:
                    metric_card_v2(
                        "E-mails encontrados no pós",
                        int_br(kpi_periodo["com_pos"]),
                        hint=f"{pct(kpi_periodo['pct_com_pos'])} do período",
                    )
                with c3:
                    metric_card_v2(
                        "E-mails sem vínculo com pós",
                        int_br(kpi_periodo["sem_pos"]),
                    )
                with c4:
                    metric_card_v2(
                        "% encontrados no pós",
                        pct(kpi_periodo["pct_com_pos"]),
                    )

                h1, h2, h3, h4, h5 = st.columns(5, gap="small")
                with h1:
                    metric_card_v2(
                        "Pós-vendas com e-mails cancelados",
                        int_br(kpi_periodo["pos_com_cancelamentos"]),
                    )
                with h2:
                    metric_card_v2(
                        "E-mails cancelados históricos",
                        int_br(kpi_hist["total"]),
                    )
                with h3:
                    metric_card_v2(
                        "Hist. encontrados no pós",
                        int_br(kpi_hist["com_pos"]),
                    )
                with h4:
                    metric_card_v2(
                        "Hist. sem vínculo com pós",
                        int_br(kpi_hist["sem_pos"]),
                    )
                with h5:
                    metric_card_v2(
                        "% hist. encontrados no pós",
                        pct(kpi_hist["pct_com_pos"]),
                    )
            else:
                c1, c2, c3, c4, c5 = st.columns(5, gap="small")
                with c1:
                    metric_card_v2(
                        "E-mails cancelados históricos",
                        int_br(kpi_hist["total"]),
                        accent=True,
                    )
                with c2:
                    metric_card_v2(
                        "Encontrados no pós",
                        int_br(kpi_hist["com_pos"]),
                    )
                with c3:
                    metric_card_v2(
                        "Sem vínculo com pós",
                        int_br(kpi_hist["sem_pos"]),
                    )
                with c4:
                    metric_card_v2(
                        "% encontrados no pós",
                        pct(kpi_hist["pct_com_pos"]),
                    )
                with c5:
                    metric_card_v2(
                        "Pós-vendas com e-mails cancelados",
                        int_br(kpi_hist["pos_com_cancelamentos"]),
                    )

            ranking_pos = cancelamentos_pos_ranking(
                df_emails_periodo, df_emails_hist,
            )
            if not ranking_pos.empty:
                _metric_graf = st.selectbox(
                    "Métrica do gráfico",
                    ["E-mails no período", "E-mails históricos"],
                    key="executivas_cancel_pos_metric_graf",
                )
                col_y = (
                    "emails_periodo"
                    if _metric_graf == "E-mails no período"
                    else "emails_historicos"
                )
                section_title(
                    "Top Pós-vendas por e-mails cancelados",
                    _metric_graf.lower(),
                )
                plot_df = ranking_pos[ranking_pos[col_y].fillna(0) > 0].copy()
                if plot_df.empty:
                    st.info(f"Sem dados para **{_metric_graf.lower()}**.")
                else:
                    st.plotly_chart(
                        bar_ranked(
                            plot_df, "pos_venda", col_y,
                            top_n=12, height=320, money=False,
                        ),
                        use_container_width=True,
                        key="executivas_cancel_pos_chart",
                    )

                section_title("Ranking por pós-venda", "período vs histórico")
                rank_show = ranking_pos.copy()
                rank_show["pos_ativo"] = rank_show["pos_ativo"].apply(
                    lambda a: (
                        "Sim" if str(a).lower() == "y"
                        else ("Não" if str(a).lower() == "n" else "—")
                    )
                )
                rank_display = rank_show.rename(columns={
                    "pos_venda": "Pós-venda",
                    "pos_ativo": "Ativo?",
                    "emails_periodo": "E-mails cancelados (período)",
                    "pct_emails_periodo": "% dos e-mails cancelados",
                    "emails_historicos": "E-mails históricos",
                    "ultimo_contato_pos": "Último contato pós",
                    "qtd_contatos_pos": "Qtd. contatos pós",
                    "origem_principal": "Origem principal do vínculo",
                })
                cfg_rank = {}
                if "Último contato pós" in rank_display.columns:
                    cfg_rank["Último contato pós"] = st.column_config.DatetimeColumn(
                        format="DD/MM/YYYY",
                    )
                if "% dos e-mails cancelados" in rank_display.columns:
                    cfg_rank["% dos e-mails cancelados"] = st.column_config.NumberColumn(
                        format="%.2f%%",
                    )
                st.dataframe(
                    rank_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config=cfg_rank,
                )

            section_title("Detalhe linha a linha", _cap_visao)
            det = df_cancel_view.copy()
            det["pos_ativo_label"] = det["pos_ativo"].apply(
                lambda a: (
                    "Sim" if str(a).lower() == "y"
                    else ("Não" if str(a).lower() == "n" else "—")
                )
            )
            cols_map = [
                ("email", "Email"),
                ("nome_cliente", "Cliente/lead"),
                ("deal_id", "Deal ID"),
                ("qtd_cancelamentos", "Qtd. cancelamentos no período"),
                ("data_cancelamento", "Data do último cancelamento"),
                ("motivo_cancelamento", "Motivo cancelamento"),
                ("closer_nome", "Closer"),
                ("time_vendas", "Time de vendas"),
                ("pos_venda", "Pós-venda identificado"),
                ("pos_ativo_label", "Ativo no pós?"),
                ("origem_vinculo", "Origem do vínculo"),
                ("ultimo_contato_pos", "Último contato pós"),
                ("qtd_contatos_pos", "Qtd. contatos pós"),
            ]
            cols_ok = [c for c, _ in cols_map if c in det.columns]
            tabela = det[cols_ok].rename(
                columns={c: lbl for c, lbl in cols_map if c in cols_ok}
            )
            cfg_det = {}
            if "Data do último cancelamento" in tabela.columns:
                cfg_det["Data do último cancelamento"] = st.column_config.DateColumn(
                    format="DD/MM/YYYY",
                )
            if "Qtd. cancelamentos no período" in tabela.columns:
                cfg_det["Qtd. cancelamentos no período"] = st.column_config.NumberColumn(
                    format="%d",
                )
            if "Último contato pós" in tabela.columns:
                cfg_det["Último contato pós"] = st.column_config.DatetimeColumn(
                    format="DD/MM/YYYY HH:mm",
                )
            st.dataframe(
                tabela,
                use_container_width=True,
                hide_index=True,
                column_config=cfg_det,
            )

        with st.expander("Diagnóstico / validação"):
            _soma_partes = kpi_periodo["com_pos"] + kpi_periodo["sem_pos"]
            _bate_soma = _soma_partes == kpi_periodo["total"]
            st.markdown(
                f"**Granularidade (período + Times)**\n"
                f"- Activities canceladas: **{int_br(_diag['qtd_activities'])}**\n"
                f"- Deals únicos: **{int_br(_diag['qtd_deals'])}**\n"
                f"- E-mails únicos cancelados: **{int_br(_diag['qtd_emails_unicos'])}**\n"
                f"- Activities sem e-mail resolvido: **{int_br(_diag['activities_sem_email'])}**\n\n"
                f"**Cruzamento por e-mail (período)**\n"
                f"- E-mails cancelados: **{int_br(kpi_periodo['total'])}**\n"
                f"- Encontrados no pós: **{int_br(_diag['qtd_emails_com_pos'])}**\n"
                f"- Sem vínculo com pós: **{int_br(_diag['qtd_emails_sem_pos'])}**\n"
                f"- Com pós + sem pós: **{int_br(_soma_partes)}** "
                f"({'✓ bate total' if _bate_soma else '⚠'})\n\n"
                f"**Referência funil**\n"
                f"- Card **Cancelados** (soma activities na view): **{int_br(_cancelados_funil)}**\n"
                f"- Activities canceladas nesta aba (período): **{int_br(_diag['qtd_activities'])}** "
                f"(card conta activities; aba KPI usa e-mails únicos)\n\n"
                f"- Cadastro oficial pós: "
                f"{'OK' if not _falha_cadastro_pos and _df_pos_oficiais is not None and not _df_pos_oficiais.empty else 'indisponível'}"
            )
            st.caption(
                "O card Cancelados soma **activities**; os cards principais desta aba "
                "usam **e-mails únicos** no período. Por isso o total de e-mails pode ser "
                "menor que o card quando o mesmo lead cancela mais de uma vez."
            )
            _df_orig = df_emails_hist if not df_emails_hist.empty else pd.DataFrame()
            if "origem_vinculo" in _df_orig.columns:
                st.caption("Origem do vínculo com pós (e-mails históricos):")
                _vc_origem = (
                    _df_orig["origem_vinculo"]
                    .replace("", CANCEL_POS_SEM_IDENTIFICADO)
                    .value_counts()
                    .reset_index()
                )
                _vc_origem.columns = ["origem", "qtd_emails"]
                st.dataframe(_vc_origem, hide_index=True)

            if df_acts_periodo is not None and not df_acts_periodo.empty:
                st.caption("Detalhe por activity (auditoria — período):")
                det_act = df_acts_periodo.copy()
                act_cols = [
                    ("activity_id", "Activity ID"),
                    ("email", "Email"),
                    ("deal_id", "Deal ID"),
                    ("data_cancelamento", "Data cancelamento"),
                    ("status_reuniao", "Status"),
                    ("motivo_cancelamento", "Motivo"),
                    ("closer_nome", "Closer"),
                    ("time_vendas", "Time"),
                ]
                act_ok = [c for c, _ in act_cols if c in det_act.columns]
                st.dataframe(
                    det_act[act_ok].rename(
                        columns={c: l for c, l in act_cols if c in act_ok}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
