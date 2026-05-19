import pandas as pd
import streamlit as st

from src.repositories import get_executivas, get_vendas_leads_detalhe_diario
from src.transforms import (
    executivas_kpis,
    executivas_por_dia,
    executivas_por_time,
    executivas_ranking,
    vendas_detalhe_filtrar_closer,
    vendas_detalhe_filtrar_time,
    vendas_detalhe_mask_por_metrica,
    vendas_normalizar_detalhe,
)
from src.ui.charts import bar_ranked, bar_simple, line
from src.ui.components import metric_card_v2, section_title
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

df = ctx.apply_filters(df_all, {"times": "time_vendas"})

if df.empty:
    st.warning("Sem dados para o filtro atual.")
    st.stop()

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
k = executivas_kpis(df)

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
    "leads → reunião agendada → reunião concluída → cancelados → ganhos → perdidos"
    if is_todas
    else f"oportunidades {classif_sel} → reunião agendada → reunião concluída → "
         f"cancelados (total geral) → ganhos → perdidos (total geral)"
)
section_title("Funil (absolutos)", _funil_hint)
f1, f2, f3, f4, f5, f6 = st.columns(6, gap="small")
with f1: metric_card_v2(_leads_label, int_br(opor_v))
with f2: metric_card_v2("Reunião Agendada", int_br(agen_v))
with f3: metric_card_v2("Reunião Concluída", int_br(comp_v))
with f4: metric_card_v2(
    "Cancelados", int_br(k["cancelados"]),
    hint=None if is_todas else "total geral · sem quebra por classif.",
)
with f5: metric_card_v2("Ganhos", int_br(vend_v))
with f6: metric_card_v2(
    "Perdidos", int_br(k["perdidos"]),
    hint=None if is_todas else "total geral · sem quebra por classif.",
)

# ---------------------------------------------------------------------------
# Tabs — Ranking / Por time / Evolução
# ---------------------------------------------------------------------------
tab_rank, tab_time, tab_temp = st.tabs(["Ranking executivas", "Por time", "Evolução"])

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
    _METRICAS_NEUTRAS = {"receita", "montante", "vendas",
                         "agendamentos", "comparecimentos"}
    _METRICAS_FINANCEIRAS = {"receita", "montante",
                             "receita_mais_12", "receita_menos_12", "receita_nao_atua",
                             "montante_mais_12", "montante_menos_12", "montante_nao_atua"}

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
    # já filtra `df`, mas não toca em `df_detalhe`). Usa o helper canônico
    # com OR entre múltiplas seleções.
    _times_sel_global = list(ctx.selections.get("times") or [])
    if (det_norm is not None and not det_norm.empty
            and _times_sel_global
            and "time_vendas_filtro" in det_norm.columns):
        _mask_times = pd.Series(False, index=det_norm.index)
        for _t in _times_sel_global:
            _mask_times |= vendas_detalhe_filtrar_time(det_norm, _t)
        det_norm = det_norm.loc[_mask_times].copy()

    # ------------------------------------------------------------------------
    # Ranking enriquecido — base vem da view (executivas_ranking) com bucket
    # do classif aplicado; coluna `vencidos` é injetada via detalhe porque
    # a view bi.vw_dashboard_comercial_executivas_rw ainda não expõe vencidos
    # (estão lumpadas em `agendamentos`). Mesmo padrão usado em prevendas.
    # ------------------------------------------------------------------------
    ranking_raw = executivas_ranking(df)
    if ranking_raw.empty:
        ranking = ranking_raw
    else:
        ranking = _apply_classif(ranking_raw, cmap)
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

        # Injeta `vencidos` a partir do detalhe (groupby closer_filtro). Match
        # ranking.executiva == det_norm.closer_filtro — ambos usam
        # TRIM(first_name||' '||last_name) via zoho_users.
        if det_norm is not None and not det_norm.empty and "activity_id" in det_norm.columns:
            _mask_venc = vendas_detalhe_mask_por_metrica(
                det_norm, "vencidos", ctx.data_ini, ctx.data_fim)
            _agg_venc = (det_norm.loc[_mask_venc]
                         .groupby("closer_filtro", as_index=False)
                         .agg(vencidos=("activity_id", "nunique")))
            _agg_venc = _agg_venc.rename(columns={"closer_filtro": "executiva"})
            ranking = ranking.merge(_agg_venc, on="executiva", how="left").fillna({"vencidos": 0})
        else:
            ranking["vencidos"] = 0

    # ------------------------------------------------------------------------
    # Header — label da métrica precisa ser resolvido ANTES das colunas
    # (o selectbox vive em col_grafico, mas o título fica acima das duas).
    # ------------------------------------------------------------------------
    _SELECTBOX_METRIC_KEY = "executivas_ranking_metric"
    _label_atual = st.session_state.get(_SELECTBOX_METRIC_KEY, "Receita")
    if _label_atual not in _RANKING_METRIC_OPTIONS:
        _label_atual = "Receita"
    section_title("Top Closers", f"ranking do período · {_label_atual.lower()} · {classif_sel}")

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
            metric_label = st.selectbox(
                "Métrica do ranking",
                options=list(_RANKING_METRIC_OPTIONS.keys()),
                index=list(_RANKING_METRIC_OPTIONS.keys()).index(_label_atual),
                key=_SELECTBOX_METRIC_KEY,
            )
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
                ranking_plot = ranking[ranking[metric_col].fillna(0) > 0].copy()
                ranking_plot = ranking_plot.sort_values(metric_col, ascending=False)

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

                    mask_metrica = vendas_detalhe_mask_por_metrica(
                        det_norm, metric_col, ctx.data_ini, ctx.data_fim,
                    )
                    detalhe_disponivel = bool(mask_metrica.any())

                    if closer_escolhido == OPCAO_TODAS:
                        contagem_grafico = int(ranking_plot[metric_col].fillna(0).sum())
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

                    # Dedup pela unidade da métrica: vendas/montante/receita
                    # contam deal distinto; resto conta activity distinct.
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
                            "comparecimentos, vendas/ganhos, montante/receita, cancelados, vencidos)."
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
                            c for c in ("data_agendamento", "data_criacao",
                                        "data_venda", "deal_id", "activity_id")
                            if c in linhas.columns
                        ]
                        linhas = linhas.sort_values(
                            sort_cols, na_position="last",
                        ).reset_index(drop=True)
                        linhas.insert(0, "#", range(1, len(linhas) + 1))

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
        # Expander auxiliar fora das 2 colunas — ranking completo
        # ===================================================================
        with st.expander("Ver ranking completo (todas as colunas/closers)"):
            st.dataframe(ranking, use_container_width=True, hide_index=True)

with tab_time:
    por_time_raw = executivas_por_time(df)
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
    diario_raw = executivas_por_dia(df)
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
