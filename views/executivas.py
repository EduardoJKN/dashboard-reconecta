import pandas as pd
import streamlit as st

from src.repositories import (
    get_executivas,
    get_executivas_churn_pos_venda,
    get_executivas_ciclo_venda,
    get_executivas_comparecimento_ajustado,
    get_executivas_funil_agendamentos,
    get_executivas_lead_in_triagem,
    get_executivas_oficiais,
    get_executivas_oficiais_todas,
    get_executivas_pos_vendas_oficiais,
    get_leads_visao_geral,
    get_vendas_leads_detalhe_diario,
)
from src.transforms import (
    CHURN_POS_SEM_IDENTIFICADO,
    EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS,
    EXECUTIVAS_RANKING_METRICAS_CICLO,
    EXECUTIVAS_RANKING_METRICAS_NEUTRAS,
    EXECUTIVAS_RANKING_METRIC_OPTIONS,
    RANKING_EXIBICAO_ATIVOS,
    RANKING_EXIBICAO_HISTORICO,
    cancelamentos_pos_filtrar_times,
    churn_pos_filtrar_periodo,
    churn_pos_kpis,
    churn_pos_ranking,
    churn_pos_venda_aplicar_cadastro,
    comparecimento_ajustado_bundle,
    comparecimento_ajustado_filtrar_conferencia,
    comparecimento_ajustado_filtrar_executiva,
    comparecimento_ajustado_merge_ranking,
    comparecimento_ajustado_validacao,
    ciclo_venda_agregar_por_closer,
    ciclo_venda_filtrar,
    ciclo_venda_merge_ranking,
    ciclo_venda_opcoes_funil,
    ciclo_venda_preparar,
    ciclo_venda_tabela_por_time,
    ciclo_venda_validacao,
    ciclo_venda_xy_dataset,
    COMPARECIMENTO_AJUSTADO_HELP,
    COMPARECIMENTO_CONFERENCIA_CLASSIF_OPCOES,
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
    triagem_aplicar_exibicao,
    triagem_contar_leads,
    triagem_kpis,
    triagem_por_etapa,
    triagem_por_executiva,
    triagem_preparar_deals,
    funil_agendamentos_kpis,
    funil_agendamentos_por_executiva,
    funil_agendamentos_por_stage,
    STAGE_HINT_CLASSIFICAVEL,
    STAGE_HINT_NAO_QUALIFICADOS,
    STAGE_HINT_OUTRAS_ETAPAS,
    STAGE_HINT_PCT_QUALIFICADOS,
    STAGE_HINT_QUALIFICADOS,
    STAGE_LABEL_NAO_QUALIFICADOS,
    STAGE_LABEL_QUALIFICADOS,
    vendas_detalhe_mask_por_metrica,
    vendas_forma_venda_breakdown,
    vendas_forma_venda_breakdown_rows,
    vendas_normalizar_detalhe,
)
from src.ui.charts import bar_etapa_distribuicao, bar_ranked, bar_simple, line, scatter_ciclo_venda
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

# Mapa do `classif_sel` (radio) → valor armazenado em `classif_final` no SQL
# `executivas_comparecimento_ajustado.sql` (cascata canônica
# lead_classification → qualificacao → classificado_cal → ext.classificado).
# "Todas" não tem entrada porque significa "sem filtro".
_CLASSIF_SEL_TO_FINAL = {
    "+12":               "Atua +12",
    "-12":               "Atua -12",
    "Não atua":          "Não atua",
    "Sem classificação": "Sem classificação",
}


def _filtrar_comp_aj_por_classif(df_comp_aj: pd.DataFrame,
                                 classif_sel: str) -> pd.DataFrame:
    """Filtra `_df_comp_aj` pelo bucket de `classif_sel` (sem aplicar filtro
    de flag/categoria). Reaproveitado pelos cards f3 (Reunião Concluída)
    e f4 (Reunião Cancelada) — garante mesma cascata e tratamento de NaN
    em todos os pontos.

    Comportamento:
      - `classif_sel == "Todas"`: devolve `df_comp_aj` (cópia).
      - `classif_sel != "Todas"` e `classif_final` ausente do df: devolve
        vazio (defensivo — evita divergência silenciosa entre card e
        tabela quando SQL legado não trouxe a coluna).
      - Caso normal: filtra `classif_final == target` (NaN → "Sem
        classificação" antes da comparação).
    """
    if df_comp_aj is None or df_comp_aj.empty:
        return pd.DataFrame()
    if classif_sel == "Todas":
        return df_comp_aj.copy()
    if "classif_final" not in df_comp_aj.columns:
        return df_comp_aj.iloc[0:0]
    target = _CLASSIF_SEL_TO_FINAL.get(classif_sel)
    if target is None:
        return df_comp_aj.copy()
    return df_comp_aj[
        df_comp_aj["classif_final"].fillna("Sem classificação").eq(target)
    ].copy()


def _comp_zoho_por_classif(df_comp_aj: pd.DataFrame,
                           classif_sel: str) -> pd.DataFrame:
    """Base do card "Reunião Concluída no Zoho" filtrada por classificação.

    Devolve só as activities com `flag_comparecimento_zoho == True` E cuja
    `classif_final` casa com o bucket selecionado. Mesma base é usada para
    o número principal do card e para a tabela de detalhe — garantindo
    contagem == #linhas.
    """
    base = _filtrar_comp_aj_por_classif(df_comp_aj, classif_sel)
    if base.empty:
        return base
    return base[base["flag_comparecimento_zoho"].fillna(False)].copy()


def _churn_por_classif(df_churn_recorte: pd.DataFrame,
                       classif_sel: str) -> pd.DataFrame:
    """Filtra `_df_churn_recorte` pelo bucket de `classif_sel` usando a
    coluna `classif_final` que passou a vir do SQL `executivas_churn_pos_venda.sql`
    (mesma cascata canônica dos demais cards).

    Mesmas regras defensivas de `_filtrar_comp_aj_por_classif`:
    - `Todas` → devolve o recorte inteiro.
    - `classif_final` ausente (SQL antigo em cache) → devolve vazio, exceto
      em `Todas`, pra evitar divergência silenciosa.
    """
    if df_churn_recorte is None or df_churn_recorte.empty:
        return pd.DataFrame()
    if classif_sel == "Todas":
        return df_churn_recorte.copy()
    if "classif_final" not in df_churn_recorte.columns:
        return df_churn_recorte.iloc[0:0]
    target = _CLASSIF_SEL_TO_FINAL.get(classif_sel)
    if target is None:
        return df_churn_recorte.copy()
    return df_churn_recorte[
        df_churn_recorte["classif_final"].fillna("Sem classificação").eq(target)
    ].copy()


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


def _safe_pct_vec(num_s: pd.Series, den_s: pd.Series) -> pd.Series:
    """Versão vetorizada de `_safe_pct` para colunas numéricas.

    Equivalência validada em scripts/validate_apply_vectorization_equivalence.py contra
    a versão escalar (DataFrame.apply lambda) com casos extremos: NaN, 0,
    grandes magnitudes e negativos. Em colunas numéricas (saída de
    `groupby.sum`) o resultado é byte-a-byte idêntico ao apply original.
    """
    num = pd.to_numeric(num_s, errors="coerce")
    den = pd.to_numeric(den_s, errors="coerce")
    ratio = (num / den) * 100.0
    return ratio.where(den != 0, 0.0)


def _ticket_medio_vec(montante_s: pd.Series, vendas_s: pd.Series) -> pd.Series:
    """`montante/vendas` quando `vendas > 0`; 0.0 caso contrário.

    Mesma semântica do lambda original (incluindo tratamento de NaN/0/neg
    em vendas → 0.0). Validado em scripts/validate_apply_vectorization_equivalence.py.
    """
    montante = pd.to_numeric(montante_s, errors="coerce")
    vendas = pd.to_numeric(vendas_s, errors="coerce")
    ratio = montante / vendas
    return ratio.where(vendas > 0, 0.0)


def _col_or_zero(df: pd.DataFrame, col: str) -> pd.Series:
    """Equivalente vetorizado de `row.get(col, 0)`: devolve a coluna ou
    uma Series de zeros do mesmo índice se a coluna não existir."""
    if col in df.columns:
        return df[col]
    return pd.Series(0.0, index=df.index)


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
# da aba Clientes Cancelados com Pós Vendas — deals stage = 'Churn'.
_times_sel_churn = list(ctx.selections.get("times") or [])
try:
    _df_churn_all = get_executivas_churn_pos_venda()
except Exception:
    _df_churn_all = pd.DataFrame()
_df_churn_recorte = executivas_churn_filtrar_recorte(
    _df_churn_all, ctx.data_ini, ctx.data_fim, _times_sel_churn,
)
_churn_funil_total = executivas_churn_total(_df_churn_recorte)

# Comparecimento ajustado (teste) — activities com flags; não substitui a view.
try:
    _df_comp_aj_raw = get_executivas_comparecimento_ajustado(
        ctx.data_ini, ctx.data_fim,
    )
except Exception:
    _df_comp_aj_raw = pd.DataFrame()
_times_comp_aj = list(ctx.selections.get("times") or [])
_df_comp_aj_raw = cancelamentos_pos_filtrar_times(_df_comp_aj_raw, _times_comp_aj)
_comp_aj_bundle = comparecimento_ajustado_bundle(
    _df_comp_aj_raw,
    _df_oficiais,
)
_kpi_comp_aj = _comp_aj_bundle["kpis"]
_df_comp_aj = _comp_aj_bundle["linhas"]
_comp_aj_agg = _comp_aj_bundle["agg"]
_comp_aj_debug = _comp_aj_bundle["debug"]
_comp_aj_debug_horario = _comp_aj_bundle["debug_horario"]
_comp_aj_resumo_ocorridas = _comp_aj_bundle["resumo_ocorridas"]
_comp_aj_conferencia = _comp_aj_bundle["conferencia"]
_comp_aj_validacao = _comp_aj_bundle["validacao"]

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

# Breakdown do card Reunião Agendada — mesma base da aba Lead In & Agendamentos
# (zoho_activities + stage do deal; não usa deals criados no período).
_times_sel_funil_card = list(ctx.selections.get("times") or [])
try:
    # `_df_funil_ag_raw` é reaproveitado no `tab_lead_triagem` (ver linha
    # ~2005) — evita repetir o lookup no `@st.cache_data` no mesmo rerun.
    # `_df_funil_ag_error` propaga a exceção para o ponto downstream que
    # antes refazia a query e exibia `st.error(...)` (preserva o feedback
    # visual original sem refazer a chamada).
    _df_funil_ag_raw = get_executivas_funil_agendamentos(ctx.data_ini, ctx.data_fim)
    _df_funil_ag_error = None
except Exception as _exc:
    _df_funil_ag_raw = pd.DataFrame()
    _df_funil_ag_error = _exc
_df_funil_ag_card = cancelamentos_pos_filtrar_times(
    _df_funil_ag_raw, _times_sel_funil_card,
)
_kpi_funil_ag_card = funil_agendamentos_kpis(_df_funil_ag_card)
_funil_qual_split = None
if is_todas and int(_kpi_funil_ag_card.get("total", 0) or 0) > 0:
    _funil_qual_split = [
        (STAGE_LABEL_QUALIFICADOS, int_br(_kpi_funil_ag_card["reuniao_agendada"])),
        (STAGE_LABEL_NAO_QUALIFICADOS, int_br(_kpi_funil_ag_card["recepcao"])),
    ]

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
    "leads → reunião agendada → reunião concluída → reunião cancelada → "
    "clientes cancelados → ganhos → perdidos"
    if is_todas
    else f"oportunidades {classif_sel} → reunião agendada → reunião concluída → "
         f"reunião cancelada (total geral) → clientes cancelados (total geral) → "
         f"ganhos → perdidos (total geral)"
)
section_title("Funil (absolutos)", _funil_hint)
f1, f2, f3, f4, f5, f6, f7 = st.columns(7, gap="small")
with f1:
    metric_card_v2(_leads_label, int_br(opor_v))
with f2:
    metric_card_v2(
        "Reunião Agendada",
        int_br(agen_v),
        qual_split=_funil_qual_split,
    )
with f3:
    # Base do card "Reunião Concluída" — filtrada pela classificação ativa.
    # Mesma base alimenta o expander de detalhes (linha ~480), garantindo
    # `valor do card == #linhas da tabela`.
    _df_card_reuniao_zoho = _comp_zoho_por_classif(_df_comp_aj, classif_sel)
    _qtd_card_reuniao_zoho = len(_df_card_reuniao_zoho)

    _comp_bd: list[tuple[str, str]] = [
        # "Agendadas c/ horário encerrado" e "Em andamento"/"Futuras" são
        # totais GLOBAIS do período (não filtram por classif), informativos —
        # NÃO somam no número principal. O "+" anterior foi removido pra
        # não sugerir adição.
        (
            "Agendadas c/ horário encerrado",
            f"{int_br(_kpi_comp_aj['agendadas_horario_encerrado'])} fora do total",
        ),
        (
            "Em andamento",
            f"{int_br(_kpi_comp_aj['agendadas_em_andamento'])} fora do total",
        ),
        (
            "Futuras",
            f"{int_br(_kpi_comp_aj['agendadas_futuras'])} fora do total",
        ),
    ]
    _hint_card = (
        "classificação 'Concluída no Zoho'"
        if is_todas
        else f"'Concluída no Zoho' · classif {classif_sel}"
    )
    metric_card_v2(
        "Reunião Concluída",
        int_br(_qtd_card_reuniao_zoho),
        hint=_hint_card,
        help=COMPARECIMENTO_AJUSTADO_HELP,
        breakdown=_comp_bd,
        accent=True,
    )
with f4:
    # Mesma base do f3 (Reunião Concluída): _df_comp_aj filtrado por classif
    # (período + times já aplicados upstream em `_df_comp_aj_raw`). Conta as
    # flags `noshow` e `cancelada` no recorte, em vez de usar
    # `_kpi_comp_aj[...]` (que ignora classif por design).
    _df_cancel_por_classif = _filtrar_comp_aj_por_classif(_df_comp_aj, classif_sel)
    if _df_cancel_por_classif.empty:
        _n_noshow = 0
        _n_canceladas = 0
    else:
        _n_noshow = int(
            _df_cancel_por_classif["flag_noshow"].fillna(False).sum()
        )
        _n_canceladas = int(
            _df_cancel_por_classif["flag_cancelada"].fillna(False).sum()
        )
    _n_cancel_total = _n_noshow + _n_canceladas
    _cancel_bd: list[tuple[str, str]] = [
        ("No-show", int_br(_n_noshow)),
        ("Canceladas", int_br(_n_canceladas)),
    ]
    _hint_cancel = (
        f"Regra view: {int_br(k['cancelados'])}"
        if is_todas
        else f"classif {classif_sel} · view total geral: {int_br(k['cancelados'])}"
    )
    metric_card_v2(
        "Reunião Cancelada",
        int_br(_n_cancel_total),
        hint=_hint_cancel,
        breakdown=_cancel_bd,
    )
with f5:
    # Filtra o mesmo recorte de churn (período + times) pela classif.
    # `classif_final` vem do SQL (cascata canônica). Em "Todas" o valor é
    # idêntico ao anterior (`_churn_funil_total`).
    _df_churn_por_classif = _churn_por_classif(_df_churn_recorte, classif_sel)
    _churn_qtd_classif = executivas_churn_total(_df_churn_por_classif)
    _hint_churn = (
        None
        if is_todas
        else f"classif {classif_sel} · total geral: {int_br(_churn_funil_total)}"
    )
    metric_card_v2("Clientes Cancelados", int_br(_churn_qtd_classif),
                   hint=_hint_churn)
with f6: metric_card_v2("Ganhos", int_br(vend_v))
with f7: metric_card_v2(
    "Perdidos", int_br(k["perdidos"]),
    hint=None if is_todas else "total geral · sem quebra por classif.",
)

# ---------------------------------------------------------------------------
# Detalhe — linhas que compõem o card "Reunião Concluída". Usa EXATAMENTE
# a mesma base do número principal (`_df_card_reuniao_zoho`), então
# `len(tabela) == valor do card` para todos os filtros (período, times,
# classificação).
# ---------------------------------------------------------------------------
with st.expander(
    f"Ver detalhes — Reuniões concluídas no Zoho "
    f"({int_br(_qtd_card_reuniao_zoho)})",
    expanded=False,
):
    if _df_card_reuniao_zoho.empty:
        st.caption(
            "Sem reuniões concluídas no Zoho no recorte atual "
            "(período / times / classificação)."
        )
    else:
        _COLUNAS_DETALHE_CARD = [
            ("start_datetime",  "Data/Hora"),
            ("executiva",       "Closer"),
            ("time_vendas",     "Time"),
            ("nome_lead",       "Nome do cliente"),
            ("email",           "E-mail"),
            ("classif_final",   "Classificação"),
            ("status_reuniao",  "Status"),
        ]
        _cols_disp = [c for c, _ in _COLUNAS_DETALHE_CARD
                      if c in _df_card_reuniao_zoho.columns]
        _rename = {c: lbl for c, lbl in _COLUNAS_DETALHE_CARD if c in _cols_disp}
        _tabela_detalhe = (
            _df_card_reuniao_zoho[_cols_disp]
            .sort_values("start_datetime", ascending=False, na_position="last")
            .rename(columns=_rename)
            .reset_index(drop=True)
        )
        st.dataframe(
            _tabela_detalhe,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Data/Hora": st.column_config.DatetimeColumn(
                    "Data/Hora", format="DD/MM/YYYY HH:mm",
                ),
            },
        )
        st.caption(
            f"{int_br(len(_tabela_detalhe))} linha(s) · "
            f"mesmos filtros do card (período, times, classificação)."
        )

with st.expander(
    "Debug comparecimento ajustado (teste)",
    expanded=False,
):
    _agora_dbg = _kpi_comp_aj.get("agora_brt")
    st.markdown(
        f"**agora_brt (comparação):** "
        f"`{_agora_dbg.strftime('%d/%m/%Y %H:%M:%S') if _agora_dbg is not None else '—'}` "
        f"· `start_datetime` / `end_datetime`: timestamp without time zone (horário BRT)"
    )

    if _comp_aj_debug_horario["qtd_violacoes_futuro"] > 0:
        st.error(
            f"Violação temporal: {_comp_aj_debug_horario['qtd_violacoes_futuro']} "
            "reunião(ões) Agendada(s) com início futuro mal classificada(s)."
        )
        st.dataframe(
            _comp_aj_debug_horario["violacoes_futuro"],
            use_container_width=True,
            hide_index=True,
        )
    if _comp_aj_debug_horario.get("qtd_violacoes_andamento_como_encerrado", 0) > 0:
        st.error(
            f"Violação temporal: "
            f"{_comp_aj_debug_horario['qtd_violacoes_andamento_como_encerrado']} "
            "reunião(ões) em andamento classificada(s) como horário encerrado."
        )
        st.dataframe(
            _comp_aj_debug_horario.get("violacoes_andamento_como_encerrado", pd.DataFrame()),
            use_container_width=True,
            hide_index=True,
        )
    if _comp_aj_debug_horario.get("qtd_violacoes_encerrado_como_andamento", 0) > 0:
        st.error(
            f"Violação temporal: "
            f"{_comp_aj_debug_horario['qtd_violacoes_encerrado_como_andamento']} "
            "reunião(ões) com horário encerrado classificada(s) como em andamento."
        )
        st.dataframe(
            _comp_aj_debug_horario.get("violacoes_encerrado_como_andamento", pd.DataFrame()),
            use_container_width=True,
            hide_index=True,
        )
    if _comp_aj_debug_horario.get("qtd_violacoes_passado_como_futuro", 0) > 0:
        st.error(
            f"Violação temporal: "
            f"{_comp_aj_debug_horario['qtd_violacoes_passado_como_futuro']} "
            "reunião(ões) já iniciada(s) classificada(s) como futura."
        )
        st.dataframe(
            _comp_aj_debug_horario.get("violacoes_passado_como_futuro", pd.DataFrame()),
            use_container_width=True,
            hide_index=True,
        )
    if (
        _comp_aj_debug_horario["qtd_violacoes_futuro"] == 0
        and _comp_aj_debug_horario.get("qtd_violacoes_passado_como_futuro", 0) == 0
        and _comp_aj_debug_horario.get("qtd_violacoes_andamento_como_encerrado", 0) == 0
        and _comp_aj_debug_horario.get("qtd_violacoes_encerrado_como_andamento", 0) == 0
    ):
        st.success(
            "✓ Classificação temporal consistente: futura / andamento / encerrado."
        )

    _val_dbg = _comp_aj_validacao
    st.markdown(
        f"**Cards:** Reunião Concluída (ajustado) **"
        f"{int_br(_val_dbg['card_comparecimento_ajustado'])}** · "
        f"Reunião Cancelada **{int_br(_val_dbg.get('card_reuniao_cancelada', 0))}**"
    )
    if _val_dbg.get("card_bate_agg"):
        st.caption(
            f"✓ Card Reunião Concluída = soma por closer "
            f"({int_br(_val_dbg['soma_comparecimentos_ajustado_agg'])}) · "
            "conferência com ranking na aba Top Closers"
        )
    if _val_dbg.get("card_bate_cancelada"):
        st.caption(
            f"✓ Card Reunião Cancelada = no-show + canceladas "
            f"({int_br(_val_dbg.get('soma_noshow_agg', 0))} + "
            f"{int_br(_val_dbg.get('soma_canceladas_agg', 0))})"
        )
    if _val_dbg.get("resumo_bate_card_concluida"):
        st.caption(
            "✓ Resumo: concluídas + agendadas c/ horário encerrado = card Reunião Concluída "
            "(futuras e em andamento não entram)"
        )
    if _val_dbg.get("resumo_bate_card_cancelada"):
        st.caption("✓ Resumo: no-show + canceladas = card Reunião Cancelada")
    if (
        _val_dbg.get("futura_fora_ajustado")
        and _val_dbg.get("andamento_fora_ajustado")
        and _val_dbg.get("futura_fora_cancelada")
        and _val_dbg.get("andamento_fora_cancelada")
    ):
        st.caption(
            "✓ Agendadas futuras e em andamento fora do comparecimento ajustado "
            "e da reunião cancelada"
        )

    st.markdown("**Resumo das reuniões do período por status**")
    st.caption("Todas as reuniões do período filtrado, por classificação única.")
    st.dataframe(
        _comp_aj_resumo_ocorridas,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("**Conferência de reuniões do período**")
    _closers_conf = (
        sorted(_comp_aj_conferencia["closer"].dropna().astype(str).unique().tolist())
        if _comp_aj_conferencia is not None and not _comp_aj_conferencia.empty
        else []
    )
    _fc1, _fc2, _fc3 = st.columns([1.4, 1.1, 1.5])
    with _fc1:
        _filt_classif = st.selectbox(
            "Classificação",
            COMPARECIMENTO_CONFERENCIA_CLASSIF_OPCOES,
            key="executivas_comp_aj_conf_classif",
        )
    with _fc2:
        _filt_closer = st.selectbox(
            "Closer",
            ["Todos"] + _closers_conf,
            key="executivas_comp_aj_conf_closer",
        )
    with _fc3:
        _filt_busca = st.text_input(
            "Buscar nome ou e-mail",
            key="executivas_comp_aj_conf_busca",
            placeholder="Opcional",
        )
    _tbl_conf = comparecimento_ajustado_filtrar_conferencia(
        _comp_aj_conferencia,
        classificacao=_filt_classif,
        closer=_filt_closer,
        busca=_filt_busca,
    )
    st.caption(
        f"{int_br(len(_tbl_conf))} reunião(ões) · classificação única por linha"
    )
    st.dataframe(
        _tbl_conf,
        use_container_width=True,
        hide_index=True,
        column_config={
            "data_hora_criacao_agendamento": st.column_config.DatetimeColumn(
                "Data/hora criação do agendamento",
                format="DD/MM/YYYY HH:mm",
            ),
            "data_hora_reuniao": st.column_config.TextColumn(
                "Data/hora da reunião",
            ),
            "entra_comparecimento_ajustado": st.column_config.CheckboxColumn(
                "Entra comparec. ajustado",
            ),
            "entra_reuniao_cancelada": st.column_config.CheckboxColumn(
                "Entra reunião cancelada",
            ),
        },
    )

    st.markdown("**Comparecimento ajustado por closer (ranking)**")
    st.dataframe(
        _comp_aj_debug,
        use_container_width=True,
        hide_index=True,
        column_config={
            "comparecimentos_zoho": st.column_config.NumberColumn("Zoho"),
            "agendadas_horario_encerrado": st.column_config.NumberColumn("+horário encerrado"),
            "comparecimentos_ajustado": st.column_config.NumberColumn("Ajustado"),
            "diferenca_ajustado_menos_zoho": st.column_config.NumberColumn("Δ ajust−zoho"),
        },
    )

# ---------------------------------------------------------------------------
# Tabs — Ranking / Por time / Evolução
# ---------------------------------------------------------------------------
tab_rank, tab_time, tab_temp, tab_cancel_pos, tab_lead_triagem = st.tabs(
    [
        "Ranking executivas",
        "Por time",
        "Evolução",
        "Clientes Cancelados com Pós Vendas",
        "Lead In & Agendamentos",
    ]
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
    if _default_metric == "Churn":
        _default_metric = "Clientes Cancelados"
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
        # Vetorizado — equivalência com o `apply` lambda anterior validada
        # em scripts/validate_apply_vectorization_equivalence.py.
        _vendas         = _col_or_zero(ranking, "vendas")
        _agendamentos   = _col_or_zero(ranking, "agendamentos")
        _comparecimentos = _col_or_zero(ranking, "comparecimentos")
        ranking["pct_conversao"]      = _safe_pct_vec(_vendas, _agendamentos)
        ranking["pct_comparecimento"] = _safe_pct_vec(_comparecimentos, _agendamentos)
        ranking["pct_vendas"]         = _safe_pct_vec(_vendas, _comparecimentos)
        if tem_fin:
            ranking["pct_recebimento"] = _safe_pct_vec(
                _col_or_zero(ranking, "receita"),
                _col_or_zero(ranking, "montante"),
            )
            ranking["ticket_medio"]    = _ticket_medio_vec(
                _col_or_zero(ranking, "montante"),
                _vendas,
            )
        else:
            ranking["pct_recebimento"] = 0.0
            ranking["ticket_medio"]    = 0.0

    if ranking is not None and not ranking.empty:
        ranking = comparecimento_ajustado_merge_ranking(ranking, _comp_aj_agg)
        _validacao_comp_aj = comparecimento_ajustado_validacao(
            _kpi_comp_aj,
            _comp_aj_agg,
            _comp_aj_resumo_ocorridas,
            _comp_aj_conferencia,
            ranking,
            linhas=_df_comp_aj,
        )
        if not _validacao_comp_aj["card_bate_ranking"]:
            st.warning(
                "Divergência card × ranking no comparecimento ajustado: "
                f"card {_validacao_comp_aj['card_comparecimento_ajustado']} · "
                f"soma ranking {_validacao_comp_aj['soma_comparecimentos_ajustado_ranking']}."
            )
        else:
            st.caption(
                f"✓ Comparecimento ajustado: card "
                f"{int_br(_validacao_comp_aj['card_comparecimento_ajustado'])} = "
                f"soma ranking "
                f"{int_br(_validacao_comp_aj['soma_comparecimentos_ajustado_ranking'])} "
                f"(Zoho {int_br(_validacao_comp_aj['soma_comparecimentos_zoho_ranking'])} · "
                f"+encerrado "
                f"{int_br(_validacao_comp_aj.get('soma_agendadas_horario_encerrado_ranking', _validacao_comp_aj.get('soma_agendadas_horario_passado_ranking', 0)))})."
            )
        if _validacao_comp_aj.get("card_bate_cancelada"):
            st.caption(
                f"✓ Reunião Cancelada: card "
                f"{int_br(_validacao_comp_aj.get('card_reuniao_cancelada', 0))} = "
                f"no-show {int_br(_validacao_comp_aj.get('soma_noshow_agg', 0))} + "
                f"canceladas {int_br(_validacao_comp_aj.get('soma_canceladas_agg', 0))}"
            )

    # -------------------------------------------------------------------------
    # Tempo de ciclo de venda — deals ganhos (SQL dedicado + agregação Python)
    # -------------------------------------------------------------------------
    try:
        _df_ciclo_raw = get_executivas_ciclo_venda(ctx.data_ini, ctx.data_fim)
    except Exception as e:
        st.error(f"Falha ao carregar tempo de ciclo de venda: {e}")
        _df_ciclo_raw = pd.DataFrame()
    _df_ciclo_prep = ciclo_venda_preparar(_df_ciclo_raw)
    _seg_ciclo_rank = (
        classif_sel
        if classif_sel in ("+12", "-12", "Não atua", "Sem classificação")
        else "Todas"
    )
    _df_ciclo_base = ciclo_venda_filtrar(
        _df_ciclo_prep,
        segmentacao=_seg_ciclo_rank,
        funil="Todos",
        times_sel=_times_sel_global or None,
    )
    _ciclo_por_closer = ciclo_venda_agregar_por_closer(
        _df_ciclo_base, _df_cadastro_ranking,
    )
    if ranking is not None and not ranking.empty:
        ranking = ciclo_venda_merge_ranking(ranking, _ciclo_por_closer)
    _n_vendas_ranking = (
        int(ranking["vendas"].fillna(0).sum())
        if ranking is not None and not ranking.empty and "vendas" in ranking.columns
        else 0
    )
    _validacao_ciclo = ciclo_venda_validacao(
        len(_df_ciclo_base),
        _n_vendas_ranking,
        _ciclo_por_closer,
    )

    section_title(
        "Top Closers",
        f"ranking do período · {metric_label.lower()} · {classif_sel} · "
        f"{_exibicao_label.lower()}",
    )
    st.caption(
        "**Oportunidades** = deals criados no período · **Agendamentos** = reuniões "
        "na data da call (exc. Vencida) · **Comparecimentos** = status Concluída. "
        "Agendamentos e comparecimentos seguem o *owner* da activity no CRM; "
        "oportunidades e vendas seguem o closer do deal."
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
            is_ciclo = metric_col in EXECUTIVAS_RANKING_METRICAS_CICLO

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
                elif is_ciclo:
                    ranking_plot = ranking[ranking[metric_col].notna()].copy()
                    ranking_plot = ranking_plot.sort_values(metric_col, ascending=True)
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
                        top_n=12, height=320,
                        money=is_money,
                        days_format=is_ciclo,
                        lower_is_better=is_ciclo,
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
            elif (
                metric_col not in ("churn", "comparecimentos_ajustado")
                and metric_col not in EXECUTIVAS_RANKING_METRICAS_CICLO
                and (det_norm is None or det_norm.empty)
            ):
                with st.expander("Detalhe do closer selecionado", expanded=False):
                    st.caption(
                        "Detalhe linha-a-linha indisponível — "
                        "`get_vendas_leads_detalhe_diario` não devolveu linhas."
                    )
            elif metric_col in EXECUTIVAS_RANKING_METRICAS_CICLO:
                with st.expander("Detalhe do closer selecionado", expanded=False):
                    st.caption(
                        "Tempo de ciclo é calculado por deal ganho "
                        "(`executivas_ciclo_venda.sql`). Use o gráfico XY abaixo "
                        "e as colunas de ciclo no ranking completo."
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
                    elif metric_col == "comparecimentos_ajustado":
                        detalhe_disponivel = (
                            _df_comp_aj is not None and not _df_comp_aj.empty
                        )
                        if closer_escolhido == OPCAO_TODAS:
                            contagem_grafico = int(
                                ranking_plot[metric_col].fillna(0).sum()
                            )
                            linhas_brutas = (
                                _df_comp_aj.copy() if detalhe_disponivel
                                else pd.DataFrame()
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
                            linhas_brutas = comparecimento_ajustado_filtrar_executiva(
                                _df_comp_aj, closer_escolhido,
                            )
                        unidade_col = "activity_id"
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

                    contagem_ajustado = None
                    if (
                        metric_col == "comparecimentos_ajustado"
                        and "flag_comparecimento_ajustado" in linhas_brutas.columns
                    ):
                        contagem_ajustado = int(
                            linhas_brutas["flag_comparecimento_ajustado"]
                            .fillna(False)
                            .sum()
                        )

                    # ---------- Mini-cards de resumo (5 cards: 3+2) -------
                    if closer_escolhido == OPCAO_TODAS:
                        fonte = ranking_plot
                    else:
                        fonte = ranking_plot.loc[ranking_plot["executiva"] == closer_escolhido]

                    def _sum_col(col):
                        return int(fonte[col].fillna(0).sum()) if col in fonte.columns else 0

                    def _sum_money(col):
                        return float(fonte[col].fillna(0).sum()) if col in fonte.columns else 0.0

                    _forma_vendas_breakdown = None
                    if (det_norm is not None and not det_norm.empty
                            and "forma_venda" in det_norm.columns):
                        _closer_forma = (
                            None if closer_escolhido == OPCAO_TODAS
                            else closer_escolhido
                        )
                        _forma_bd = vendas_forma_venda_breakdown(
                            det_norm, ctx.data_ini, ctx.data_fim,
                            closer=_closer_forma,
                        )
                        _forma_vendas_breakdown = [
                            (lbl, int_br(val))
                            for lbl, val in vendas_forma_venda_breakdown_rows(_forma_bd)
                        ]

                    if contagem_ajustado is not None:
                        st.markdown(
                            f"**{closer_escolhido}** · {metric_label}: "
                            f"gráfico {int_br(contagem_grafico)} (ajustado) · "
                            f"tabela {int_br(contagem_tabela)} linhas "
                            f"({int_br(contagem_ajustado)} no total ajustado)"
                        )
                    else:
                        st.markdown(
                            f"**{closer_escolhido}** · {metric_label}: "
                            f"gráfico {int_br(contagem_grafico)} · "
                            f"tabela {int_br(contagem_tabela)}"
                        )

                    mc1, mc2, mc3 = st.columns(3, gap="small")
                    with mc1:
                        metric_card_v2(
                            "Vendas", int_br(_sum_col("vendas")),
                            hint="deals ganhos · Novo cliente",
                            accent=True,
                            breakdown=_forma_vendas_breakdown,
                        )
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
                    elif (
                        metric_col != "comparecimentos_ajustado"
                        and contagem_tabela != contagem_grafico
                    ):
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
                    if metric_col == "comparecimentos_ajustado" and not linhas.empty:
                        st.caption(
                            "A tabela lista todas as reuniões do período (owner da "
                            "activity). A coluna **Tipo (teste)** indica se entra no "
                            "comparecimento ajustado ou fica fora do total."
                        )

                    # ---------- Tabela resumida nome-a-nome ---------------
                    if linhas.empty:
                        st.caption(
                            "Nenhum registro nome-a-nome encontrado para esse closer/métrica."
                        )
                    else:
                        sort_cols = [
                            c for c in ("start_datetime", "data_churn",
                                        "data_agendamento", "data_criacao",
                                        "data_venda", "deal_id", "activity_id")
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
                        elif metric_col == "comparecimentos_ajustado":
                            cols_map_resumo = [
                                ("#",                    "#"),
                                ("nome_lead",            "Nome do cliente/lead"),
                                ("email",                "E-mail"),
                                ("tipo_comparecimento",  "Tipo (teste)"),
                                ("status_reuniao",       "Status reunião"),
                                ("deal_stage",           "Stage do deal"),
                                ("start_datetime",       "Data/hora reunião"),
                                ("closer_deal",          "Closer (deal)"),
                                ("executiva",            "Owner activity"),
                            ]
                        else:
                            cols_map_resumo = [
                                ("#",                    "#"),
                                ("nome_cliente_view",    "Nome do cliente/lead"),
                                ("email_final_filtro",   "E-mail"),
                                ("classificacao_final_filtro", "Classificação"),
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
                        if "Data/hora reunião" in tabela_resumo.columns:
                            cfg_resumo["Data/hora reunião"] = (
                                st.column_config.DatetimeColumn(
                                    "Data/hora reunião",
                                    format="DD/MM/YYYY HH:mm",
                                )
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

    # =========================================================================
    # Gráfico XY — tempo de ciclo × volume (complementar ao Top Closers)
    # =========================================================================
    section_title(
        "Tempo de ciclo de venda por closer",
        "relação entre volume de vendas e tempo médio de fechamento",
    )
    st.caption(
        "Universo: vendas ganhas (stage Ganho · Novo cliente · data de compra no "
        "período). **Entrada → ganho** = compra − lead/deal; **Call → ganho** = "
        "compra − 1ª reunião concluída antes do ganho. Deals sem data suficiente "
        "são ignorados no tempo médio (ver contagem no ranking completo)."
    )
    if _validacao_ciclo["bate_ranking"]:
        st.caption(
            f"✓ Vendas consideradas no ciclo: {int_br(_validacao_ciclo['n_deals_ciclo'])} "
            f"= soma ranking ({int_br(_validacao_ciclo['n_vendas_ranking'])})."
        )
    elif _validacao_ciclo["n_deals_ciclo"] > 0:
        st.warning(
            "Divergência vendas ciclo × ranking: "
            f"SQL {int_br(_validacao_ciclo['n_deals_ciclo'])} · "
            f"ranking {int_br(_validacao_ciclo['n_vendas_ranking'])} · "
            f"soma closers {int_br(_validacao_ciclo['soma_vendas_por_closer'])}. "
            "Pode ocorrer por diferença de classificação (+12/-12) entre view e "
            "detalhe ou closers sem match no cadastro."
        )

    if _df_ciclo_prep is None or _df_ciclo_prep.empty:
        st.info("Sem vendas ganhas no período para calcular tempo de ciclo.")
    else:
        _c1, _c2, _c3, _c4 = st.columns(4, gap="small")
        with _c1:
            _ciclo_tipo = st.radio(
                "Tipo de ciclo",
                ("Entrada do lead → ganho", "Call → ganho"),
                horizontal=False,
                key="executivas_ciclo_tipo",
            )
        with _c2:
            _ciclo_eixo_x = st.radio(
                "Eixo X",
                ("Quantidade de vendas", "% das vendas"),
                horizontal=False,
                key="executivas_ciclo_eixo_x",
            )
        with _c3:
            _ciclo_segment = st.radio(
                "Segmentação",
                ("Todas", "+12", "-12"),
                horizontal=False,
                key="executivas_ciclo_segment",
            )
        with _c4:
            _funil_opts = ciclo_venda_opcoes_funil(_df_ciclo_prep)
            _ciclo_funil = st.selectbox(
                "Funil / canal",
                _funil_opts,
                key="executivas_ciclo_funil",
            )

        _df_ciclo_xy = ciclo_venda_filtrar(
            _df_ciclo_prep,
            segmentacao=_ciclo_segment,
            funil=_ciclo_funil,
            times_sel=_times_sel_global or None,
        )
        _ciclo_xy_agg = ciclo_venda_agregar_por_closer(
            _df_ciclo_xy, _df_cadastro_ranking,
        )
        _tipo_key = "entrada" if "Entrada" in _ciclo_tipo else "call"
        _eixo_key = "percentual" if "%" in _ciclo_eixo_x else "quantidade"
        _df_xy_plot = ciclo_venda_xy_dataset(
            _ciclo_xy_agg, _tipo_key, _eixo_key,
        )
        if _df_xy_plot.empty:
            st.info("Sem closers com tempo de ciclo calculável neste recorte.")
        else:
            _y_col = (
                "ciclo_entrada_medio_dias" if _tipo_key == "entrada"
                else "ciclo_call_medio_dias"
            )
            _avg_y = float(_df_xy_plot[_y_col].mean())
            _x_title = (
                "% das vendas no recorte"
                if _eixo_key == "percentual"
                else "Quantidade de vendas"
            )
            _y_title = (
                "Tempo médio entrada → ganho (dias)"
                if _tipo_key == "entrada"
                else "Tempo médio call → ganho (dias)"
            )
            st.plotly_chart(
                scatter_ciclo_venda(
                    _df_xy_plot,
                    x_title=_x_title,
                    y_title=_y_title,
                    avg_y=_avg_y,
                    x_is_percent=_eixo_key == "percentual",
                ),
                use_container_width=True,
                key="executivas_ciclo_scatter",
            )

with tab_time:
    por_time_raw = executivas_por_time(df_filtrado)
    if por_time_raw.empty:
        st.info("Sem dados de time no filtro atual.")
    else:
        por_time = _apply_classif(por_time_raw, cmap)
        # Recalcula pcts/ticket no bucket selecionado (mesmo padrão do ranking).
        # Vetorizado — equivalência validada em validate_apply_vectorization_equivalence.py.
        _pt_vendas         = _col_or_zero(por_time, "vendas")
        _pt_agendamentos   = _col_or_zero(por_time, "agendamentos")
        _pt_comparecimentos = _col_or_zero(por_time, "comparecimentos")
        por_time["pct_conversao"] = _safe_pct_vec(_pt_vendas, _pt_agendamentos)
        por_time["pct_vendas"]    = _safe_pct_vec(_pt_vendas, _pt_comparecimentos)
        if tem_fin:
            por_time["ticket_medio"] = _ticket_medio_vec(
                _col_or_zero(por_time, "montante"),
                _pt_vendas,
            )
        else:
            por_time["ticket_medio"] = 0.0

        section_title("Consolidação por time", classif_sel)
        c1, c2 = st.columns(2, gap="large")
        with c1:
            if tem_fin:
                st.markdown("**Receita por time**")
                st.caption("Soma da receita de vendas ganhas no período")
                st.plotly_chart(
                    bar_simple(
                        por_time, "time_vendas", "receita",
                        money=True, rotate_x=True,
                        x_title="Time", y_title="Receita",
                        height=320,
                    ),
                    use_container_width=True,
                )
            else:
                st.info(
                    "Receita não disponível para **Sem classificação** — "
                    "a view só expõe valores financeiros nos buckets +12, -12 e Não atua."
                )
        with c2:
            st.markdown("**Vendas por time**")
            st.caption("Quantidade de vendas ganhas no período")
            st.plotly_chart(
                bar_simple(
                    por_time, "time_vendas", "vendas",
                    rotate_x=True,
                    x_title="Time", y_title="Vendas",
                    height=320,
                ),
                use_container_width=True,
            )
        with st.expander("Tabela detalhada por time"):
            st.dataframe(por_time, use_container_width=True, hide_index=True)

        # --- Tempo de ciclo consolidado por time ---------------------------
        if _df_ciclo_prep is not None and not _df_ciclo_prep.empty:
            section_title(
                "Tempo de ciclo de venda por time",
                f"{classif_sel} · vendas ganhas no período",
            )
            _df_ciclo_time = ciclo_venda_filtrar(
                _df_ciclo_prep,
                segmentacao=classif_sel if classif_sel in ("+12", "-12") else "Todas",
                funil="Todos",
                times_sel=_times_sel_global or None,
            )
            _tabela_ciclo_time = ciclo_venda_tabela_por_time(_df_ciclo_time)
            if _tabela_ciclo_time.empty:
                st.info("Sem vendas ganhas para ciclo neste recorte de times.")
            else:
                _tc1, _tc2 = st.columns(2, gap="small")
                with _tc1:
                    _tipo_time = st.radio(
                        "Tipo de ciclo (gráfico)",
                        ("Entrada → ganho", "Call → ganho"),
                        horizontal=True,
                        key="executivas_ciclo_time_tipo",
                    )
                with _tc2:
                    _eixo_time = st.radio(
                        "Eixo X (gráfico)",
                        ("Quantidade", "Percentual"),
                        horizontal=True,
                        key="executivas_ciclo_time_eixo",
                    )
                _plot_time = _tabela_ciclo_time.rename(columns={
                    "time_vendas": "executiva",
                    "vendas": "vendas_ciclo",
                    "pct_vendas": "pct_vendas_ciclo",
                    "ciclo_entrada_medio_dias": "ciclo_entrada_medio_dias",
                    "ciclo_call_medio_dias": "ciclo_call_medio_dias",
                })
                _tipo_t = "entrada" if "Entrada" in _tipo_time else "call"
                _eixo_t = "percentual" if _eixo_time == "Percentual" else "quantidade"
                _df_xy_time = ciclo_venda_xy_dataset(_plot_time, _tipo_t, _eixo_t)
                if not _df_xy_time.empty:
                    _y_ct = (
                        "ciclo_entrada_medio_dias" if _tipo_t == "entrada"
                        else "ciclo_call_medio_dias"
                    )
                    st.plotly_chart(
                        scatter_ciclo_venda(
                            _df_xy_time,
                            label_col="executiva",
                            x_title="Quantidade de vendas" if _eixo_t == "quantidade" else "% das vendas",
                            y_title=_y_ct.replace("_", " "),
                            avg_y=float(_df_xy_time[_y_ct].mean()),
                            height=360,
                            x_is_percent=_eixo_t == "percentual",
                        ),
                        use_container_width=True,
                        key="executivas_ciclo_time_scatter",
                    )
                with st.expander("Tabela de ciclo por time (+12 / -12)"):
                    st.dataframe(
                        _tabela_ciclo_time,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "time_vendas": st.column_config.TextColumn("Time", pinned=True),
                            "vendas": st.column_config.NumberColumn("Vendas", format="%d"),
                            "pct_vendas": st.column_config.NumberColumn("% vendas", format="%.1f%%"),
                            "ciclo_entrada_medio_dias": st.column_config.NumberColumn(
                                "Entrada → ganho (d)", format="%.0f",
                            ),
                            "ciclo_call_medio_dias": st.column_config.NumberColumn(
                                "Call → ganho (d)", format="%.0f",
                            ),
                            "vendas_mais_12": st.column_config.NumberColumn("Vendas +12", format="%d"),
                            "ciclo_entrada_mais_12": st.column_config.NumberColumn(
                                "Entrada +12 (d)", format="%.0f",
                            ),
                            "ciclo_call_mais_12": st.column_config.NumberColumn(
                                "Call +12 (d)", format="%.0f",
                            ),
                            "vendas_menos_12": st.column_config.NumberColumn("Vendas -12", format="%d"),
                            "ciclo_entrada_menos_12": st.column_config.NumberColumn(
                                "Entrada -12 (d)", format="%.0f",
                            ),
                            "ciclo_call_menos_12": st.column_config.NumberColumn(
                                "Call -12 (d)", format="%.0f",
                            ),
                        },
                    )

with tab_temp:
    diario_raw = executivas_por_dia(df_filtrado)
    diario = _apply_classif(diario_raw, cmap)
    section_title(f"Funil diário (absolutos) · {classif_sel}")
    st.plotly_chart(
        line(diario, "data_ref",
             ["oportunidades", "agendamentos", "comparecimentos", "vendas"],
             height=340, show_value_labels=True),
        use_container_width=True,
    )
    if tem_fin:
        section_title("Receita × Montante (diário)")
        st.plotly_chart(
            line(diario, "data_ref", ["receita", "montante"],
                 height=280, money_axis="y", show_value_labels=True),
            use_container_width=True,
        )
    else:
        st.caption(
            "📊 Receita × Montante não disponível para **Sem classificação** — "
            "a view só expõe valores financeiros para os buckets +12, -12 e Não atua."
        )

with tab_cancel_pos:
    # =========================================================================
    # Clientes Cancelados com Pós Vendas — deals `stage = 'Churn'` (churn real).
    # Card Cancelados (reuniões) e Top Closers não são alterados.
    # =========================================================================
    _CHURN_TAB_VISAO_KEY = "executivas_churn_tab_visao"
    visao_churn_tab = st.radio(
        "Visão",
        ["Período selecionado", "Histórico total"],
        horizontal=True,
        key=_CHURN_TAB_VISAO_KEY,
        help="Período usa o filtro global de datas (data do churn). "
             "Histórico lista todos os deals em stage Churn "
             "(respeitando filtro de Times do header, quando ativo).",
    )
    visao_periodo = visao_churn_tab == "Período selecionado"

    try:
        df_churn_raw = get_executivas_churn_pos_venda()
    except Exception as e:
        st.error(f"Falha ao carregar churns: {e}")
        df_churn_raw = None

    _falha_cadastro_pos = False
    try:
        _df_pos_oficiais = get_executivas_pos_vendas_oficiais()
    except Exception:
        _df_pos_oficiais = None
        _falha_cadastro_pos = True

    if _falha_cadastro_pos or _df_pos_oficiais is None or _df_pos_oficiais.empty:
        st.caption(
            "⚠ Cadastro `assistencial.executivas_pos_vendas` indisponível — "
            "nomes canônicos e flag Ativo? usam fallback (`zoho_users` / activities)."
        )
        _df_pos_oficiais = _df_pos_oficiais if _df_pos_oficiais is not None else pd.DataFrame()

    if df_churn_raw is None or df_churn_raw.empty:
        st.info("Sem deals em stage Churn para exibir.")
        kpi_periodo = churn_pos_kpis(pd.DataFrame())
        kpi_hist = kpi_periodo
        df_churn_hist = pd.DataFrame()
        df_churn_periodo = pd.DataFrame()
        df_churn_view = pd.DataFrame()
    else:
        df_churn_hist = churn_pos_venda_aplicar_cadastro(
            df_churn_raw, _df_pos_oficiais,
        )
        df_churn_hist = cancelamentos_pos_filtrar_times(
            df_churn_hist, _times_sel_churn,
        )
        df_churn_periodo = churn_pos_filtrar_periodo(
            df_churn_hist, ctx.data_ini, ctx.data_fim,
        )
        df_churn_view = df_churn_periodo if visao_periodo else df_churn_hist

        kpi_periodo = churn_pos_kpis(df_churn_periodo)
        kpi_hist = churn_pos_kpis(df_churn_hist)

        if df_churn_view.empty:
            st.info(
                "Nenhum Churn no recorte atual."
                if visao_periodo
                else "Nenhum deal em stage Churn na base (com filtros atuais)."
            )

        if not df_churn_view.empty:
            _cap_visao = (
                f"{ctx.data_ini:%d/%m/%Y} – {ctx.data_fim:%d/%m/%Y} · data do churn"
                if visao_periodo
                else "todos os deals stage = Churn (Times aplicado)"
            )
            section_title("Clientes Cancelados com Pós Vendas", _cap_visao)
            st.caption(
                "Fonte: `zoho_deals` com **stage = Churn**. "
                "Vínculo principal: `executiva_contas` → cadastro "
                "`assistencial.executivas_pos_vendas`. "
                "Reforços: activities de pós, `zoho_acompanhamentos`. "
                "Data: `stage_modified_time` → `modified_time` → `data_hora_compra`."
            )

            tem_fin = kpi_periodo["montante"] > 0 or kpi_periodo["receita"] > 0

            if visao_periodo:
                c1, c2, c3, c4 = st.columns(4, gap="small")
                with c1:
                    metric_card_v2(
                        "Clientes cancelados no período",
                        int_br(kpi_periodo["total"]),
                        accent=True,
                    )
                with c2:
                    metric_card_v2(
                        "Com pós-venda identificado",
                        int_br(kpi_periodo["com_pos"]),
                        hint=f"{pct(kpi_periodo['pct_com_pos'])} do período",
                    )
                with c3:
                    metric_card_v2(
                        "Sem pós-venda identificado",
                        int_br(kpi_periodo["sem_pos"]),
                    )
                with c4:
                    metric_card_v2(
                        "% com pós-venda identificado",
                        pct(kpi_periodo["pct_com_pos"]),
                    )

                h1, h2, h3, h4, h5 = st.columns(5, gap="small")
                with h1:
                    metric_card_v2(
                        "Pós-vendas com cancelamentos",
                        int_br(kpi_periodo["pos_com_cancelamentos"]),
                    )
                with h2:
                    metric_card_v2(
                        "Cancelamentos históricos",
                        int_br(kpi_hist["total"]),
                    )
                with h3:
                    metric_card_v2(
                        "Hist. com pós",
                        int_br(kpi_hist["com_pos"]),
                    )
                with h4:
                    metric_card_v2(
                        "Hist. sem pós",
                        int_br(kpi_hist["sem_pos"]),
                    )
                with h5:
                    metric_card_v2(
                        "% hist. com pós",
                        pct(kpi_hist["pct_com_pos"]),
                    )
            else:
                c1, c2, c3, c4, c5 = st.columns(5, gap="small")
                with c1:
                    metric_card_v2(
                        "Cancelamentos históricos",
                        int_br(kpi_hist["total"]),
                        accent=True,
                    )
                with c2:
                    metric_card_v2(
                        "Com pós-venda identificado",
                        int_br(kpi_hist["com_pos"]),
                    )
                with c3:
                    metric_card_v2(
                        "Sem pós-venda identificado",
                        int_br(kpi_hist["sem_pos"]),
                    )
                with c4:
                    metric_card_v2(
                        "% com pós-venda identificado",
                        pct(kpi_hist["pct_com_pos"]),
                    )
                with c5:
                    metric_card_v2(
                        "Pós-vendas com cancelamentos",
                        int_br(kpi_hist["pos_com_cancelamentos"]),
                    )

            if tem_fin:
                kpi_fin = kpi_periodo if visao_periodo else kpi_hist
                f1, f2, f3 = st.columns(3, gap="small")
                with f1:
                    metric_card_v2("Montante cancelado", brl(kpi_fin["montante"]))
                with f2:
                    metric_card_v2("Receita cancelada", brl(kpi_fin["receita"]))
                with f3:
                    metric_card_v2(
                        "Ticket médio",
                        brl(kpi_fin["ticket_medio"]) if kpi_fin["ticket_medio"] else "—",
                        hint="montante ÷ churns no recorte",
                    )

            ranking_pos = churn_pos_ranking(df_churn_periodo, df_churn_hist)
            if not ranking_pos.empty:
                _metric_graf = st.selectbox(
                    "Métrica do gráfico",
                    [
                        "Clientes cancelados no período",
                        "Clientes cancelados históricos",
                    ],
                    key="executivas_churn_tab_metric_graf",
                )
                col_y = (
                    "churns_periodo"
                    if _metric_graf == "Clientes cancelados no período"
                    else "churns_historicos"
                )
                section_title(
                    "Top Pós-vendas por clientes cancelados",
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
                        key="executivas_churn_tab_chart",
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
                    "churns_periodo": "Clientes cancelados no período",
                    "pct_churn_periodo": "% dos cancelamentos",
                    "churns_historicos": "Cancelamentos históricos",
                    "ultimo_contato_pos": "Último contato pós",
                    "qtd_contatos_pos": "Qtd. contatos pós",
                    "montante_churn": "Montante cancelado",
                    "receita_churn": "Receita cancelada",
                    "ticket_medio": "Ticket médio",
                })
                cfg_rank = {}
                if "Último contato pós" in rank_display.columns:
                    cfg_rank["Último contato pós"] = st.column_config.DatetimeColumn(
                        format="DD/MM/YYYY",
                    )
                if "% dos cancelamentos" in rank_display.columns:
                    cfg_rank["% dos cancelamentos"] = st.column_config.NumberColumn(
                        format="%.2f%%",
                    )
                for col_m in ("Montante cancelado", "Receita cancelada", "Ticket médio"):
                    if col_m in rank_display.columns:
                        cfg_rank[col_m] = st.column_config.NumberColumn(format="R$ %.0f")
                st.dataframe(
                    rank_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config=cfg_rank,
                )

            section_title("Detalhe linha a linha", _cap_visao)
            det = df_churn_view.copy()
            det["pos_ativo_label"] = det["pos_ativo"].apply(
                lambda a: (
                    "Sim" if str(a).lower() == "y"
                    else ("Não" if str(a).lower() == "n" else "—")
                )
            )
            cols_map = [
                ("deal_id", "Deal ID"),
                ("nome_cliente", "Cliente"),
                ("email", "Email"),
                ("data_churn", "Data do Churn"),
                ("data_churn_fonte", "Fonte data churn"),
                ("closer_nome", "Closer/executiva de venda"),
                ("pos_venda", "Pós-venda identificado"),
                ("pos_ativo_label", "Ativo no pós?"),
                ("origem_vinculo", "Origem do vínculo"),
                ("ultimo_contato_pos", "Último contato pós"),
                ("qtd_contatos_pos", "Qtd. contatos pós"),
                ("stage", "Stage"),
                ("montante", "Montante"),
                ("receita", "Receita"),
                ("motivo_perda", "Motivo perda/cancelamento"),
            ]
            cols_ok = [c for c, _ in cols_map if c in det.columns]
            tabela = det[cols_ok].rename(
                columns={c: lbl for c, lbl in cols_map if c in cols_ok}
            )
            cfg_det = {}
            if "Data do Churn" in tabela.columns:
                cfg_det["Data do Churn"] = st.column_config.DateColumn(format="DD/MM/YYYY")
            if "Último contato pós" in tabela.columns:
                cfg_det["Último contato pós"] = st.column_config.DatetimeColumn(
                    format="DD/MM/YYYY HH:mm",
                )
            for col_m in ("Montante", "Receita"):
                if col_m in tabela.columns:
                    cfg_det[col_m] = st.column_config.NumberColumn(format="R$ %.0f")
            st.dataframe(
                tabela,
                use_container_width=True,
                hide_index=True,
                column_config=cfg_det,
            )

        with st.expander("Diagnóstico / validação"):
            _soma_partes = kpi_periodo["com_pos"] + kpi_periodo["sem_pos"]
            _bate_funil = kpi_periodo["total"] == _churn_funil_total
            _bate_soma = _soma_partes == kpi_periodo["total"]
            st.markdown(
                f"- Card **Churn** (funil): **{int_br(_churn_funil_total)}**\n"
                f"- Aba no período: **{int_br(kpi_periodo['total'])}** "
                f"({'✓ bate' if _bate_funil else '⚠ diverge — ver filtros/data'})\n"
                f"- Histórico (Times aplicado): **{int_br(len(df_churn_hist))}**\n"
                f"- Com pós + sem pós (período): **{int_br(_soma_partes)}** "
                f"({'✓ bate total' if _bate_soma else '⚠'})\n"
                f"- Sem pós (`{CHURN_POS_SEM_IDENTIFICADO}`): "
                f"**{int_br(kpi_periodo['sem_pos'])}** período · "
                f"**{int_br(kpi_hist['sem_pos'])}** histórico\n"
                f"- Cadastro oficial: "
                f"{'OK' if not _falha_cadastro_pos and _df_pos_oficiais is not None and not _df_pos_oficiais.empty else 'indisponível'}"
            )
            if not _bate_funil:
                st.caption(
                    "A aba e o card usam `zoho_deals.stage = Churn` com data "
                    "`stage_modified_time` → `modified_time` → `data_hora_compra` "
                    "e o mesmo filtro de Times. Divergência costuma indicar "
                    "diferença de recorte de data ou time_vendas no deal."
                )
            if "origem_vinculo" in df_churn_hist.columns and not df_churn_hist.empty:
                st.caption("Origem do vínculo com pós (histórico):")
                _vc_origem = (
                    df_churn_hist["origem_vinculo"]
                    .replace("", CHURN_POS_SEM_IDENTIFICADO)
                    .value_counts()
                    .reset_index()
                )
                _vc_origem.columns = ["origem", "qtd"]
                st.dataframe(_vc_origem, hide_index=True)
            if "data_churn_fonte" in df_churn_hist.columns and not df_churn_hist.empty:
                st.caption("Fonte da data do churn (histórico):")
                _vc_fonte = (
                    df_churn_hist["data_churn_fonte"]
                    .value_counts()
                    .reset_index()
                )
                _vc_fonte.columns = ["fonte", "qtd"]
                st.dataframe(_vc_fonte, hide_index=True)

with tab_lead_triagem:
    # =========================================================================
    # Visão principal: classificação dos agendamentos do funil (card Reunião
    # Agendada). Visão complementar de oportunidades criadas no período fica
    # no expander abaixo.
    # =========================================================================
    _times_sel_triagem = list(ctx.selections.get("times") or [])

    # Comparativo: oportunidades com closer (Ativos) — base diferente, só o total.
    # `_df_triagem_raw` é reaproveitado pelo expander "Visão complementar"
    # (linha ~2190) — evita 2ª chamada de `get_executivas_lead_in_triagem`
    # no mesmo rerun (tabs e expanders do Streamlit renderizam o corpo
    # mesmo quando inativos/colapsados, então as duas chamadas co-fire).
    # `_df_triagem_error` propaga a exceção para o expander downstream que
    # antes refazia a query e exibia `st.error(...)`.
    try:
        _df_triagem_raw = get_executivas_lead_in_triagem(ctx.data_ini, ctx.data_fim)
        _df_triagem_error = None
    except Exception as _exc:
        _df_triagem_raw = pd.DataFrame()
        _df_triagem_error = _exc
    _df_opp_cmp = triagem_aplicar_exibicao(
        cancelamentos_pos_filtrar_times(
            triagem_preparar_deals(_df_triagem_raw), _times_sel_triagem,
        ),
        RANKING_EXIBICAO_ATIVOS,
        _df_oficiais,
        _df_oficiais_todas,
    )
    _opp_com_closer_cmp = len(_df_opp_cmp)

    _agen_funil_total = float(k.get("agendamentos", 0) or 0)
    _agen_funil_card = float(k.get(cmap["agendamentos"], 0) or 0)
    # Reaproveita o raw carregado no card "Reunião Agendada" (linha ~289).
    # Mesmo período e cache — o conteúdo é idêntico ao que viria de uma
    # segunda chamada de `get_executivas_funil_agendamentos`. Se a primeira
    # chamada falhou, propaga o mesmo `st.error(...)` que o bloco anterior
    # exibia — preserva feedback visual sem refazer a query.
    if _df_funil_ag_error is not None:
        st.error(f"Falha ao carregar agendamentos do funil: {_df_funil_ag_error}")
    df_funil_ag_raw = _df_funil_ag_raw

    df_funil_ag = cancelamentos_pos_filtrar_times(
        df_funil_ag_raw, _times_sel_triagem,
    )
    kpi_funil_ag = funil_agendamentos_kpis(df_funil_ag)
    _bate_funil_ag = int(kpi_funil_ag["total"]) == int(_agen_funil_total)

    section_title(
        "Classificação dos agendamentos do funil",
        f"{ctx.data_ini:%d/%m/%Y} – {ctx.data_fim:%d/%m/%Y} · "
        "mesma regra do card Reunião Agendada",
    )
    st.caption(
        "Classificação oficial: `zoho_activities` (Consulta/Indicação) ligadas ao deal "
        "via `what_id` → **`zoho_deals.stage`** atual. "
        f"**{STAGE_LABEL_QUALIFICADOS}** ({STAGE_HINT_QUALIFICADOS}) · "
        f"**{STAGE_LABEL_NAO_QUALIFICADOS}** ({STAGE_HINT_NAO_QUALIFICADOS}). "
        "**Data:** `start_datetime` (reunião no período). "
        "Respeita filtro de **Times** do header — **não** usa o toggle "
        "Ativos/Histórico (igual ao Funil absoluto). "
        f"Card do funil ({classif_sel}): **{int_br(int(_agen_funil_card))}** · "
        f"universo Todas: **{int_br(int(_agen_funil_total))}** · "
        f"esta seção: **{int_br(kpi_funil_ag['total'])}** "
        f"({'✓ bate' if _bate_funil_ag else '⚠ diverge'})."
    )

    if df_funil_ag.empty:
        st.info("Sem agendamentos do funil no recorte atual.")
    else:
        c1, c2, c3, c4 = st.columns(4, gap="small")
        with c1:
            metric_card_v2(
                "Total de agendamentos do funil",
                int_br(kpi_funil_ag["total"]),
                accent=True,
            )
        with c2:
            metric_card_v2(
                STAGE_LABEL_NAO_QUALIFICADOS,
                int_br(kpi_funil_ag["recepcao"]),
                hint=STAGE_HINT_NAO_QUALIFICADOS,
            )
        with c3:
            metric_card_v2(
                STAGE_LABEL_QUALIFICADOS,
                int_br(kpi_funil_ag["reuniao_agendada"]),
                hint=STAGE_HINT_QUALIFICADOS,
            )
        with c4:
            metric_card_v2(
                "Total classificável",
                int_br(kpi_funil_ag["total_classificavel"]),
                hint=STAGE_HINT_CLASSIFICAVEL,
            )

        c5, c6, c7, c8 = st.columns(4, gap="small")
        with c5:
            metric_card_v2(
                "% Qualificados",
                pct(kpi_funil_ag["pct_qualificados"]),
                hint=STAGE_HINT_PCT_QUALIFICADOS,
            )
        with c6:
            metric_card_v2(
                "Outras etapas",
                int_br(kpi_funil_ag["outras_etapas"]),
                hint=STAGE_HINT_OUTRAS_ETAPAS,
            )
        with c7:
            metric_card_v2(
                "Sem deal ligado",
                int_br(kpi_funil_ag["sem_deal"]),
                hint="activity sem what_id válido",
            )
        with c8:
            metric_card_v2(
                "Oportunidades com Closer",
                int_br(_opp_com_closer_cmp),
                hint="comparativo · zoho_deals.created_at · base diferente",
            )

        por_stage_funil = funil_agendamentos_por_stage(df_funil_ag)
        if not por_stage_funil.empty:
            section_title(
                "Distribuição por etapa",
                "onde estão hoje os deals dos agendamentos do funil",
            )
            st.plotly_chart(
                bar_etapa_distribuicao(
                    por_stage_funil,
                    "etapa",
                    "total_agendamentos",
                    "pct_agendamentos",
                    height=max(320, 32 * len(por_stage_funil) + 100),
                ),
                use_container_width=True,
                key="executivas_funil_ag_stage_chart",
            )

        por_exec_funil = funil_agendamentos_por_executiva(df_funil_ag)
        if not por_exec_funil.empty:
            section_title(
                "Classificação dos agendamentos por executiva",
                "filtro Times do header",
            )
            tbl_exec_funil = por_exec_funil.rename(columns={
                "executiva": "Executiva",
                "total_agendamentos": "Total de agendamentos do funil",
                "nao_qualificados": STAGE_LABEL_NAO_QUALIFICADOS,
                "qualificados": STAGE_LABEL_QUALIFICADOS,
                "total_classificavel": "Total classificável",
                "pct_qualificados": "% Qualificados",
                "reuniao_concluida": "Reunião Concluída",
                "no_show": "No-show",
                "ganho": "Ganho",
                "lead_in": "Lead-in",
                "outras_etapas": "Outras etapas",
            })
            cfg_exec_funil = ranking_column_config(
                tbl_exec_funil, pin_column="Executiva",
            )
            if "% Qualificados" in tbl_exec_funil.columns:
                cfg_exec_funil["% Qualificados"] = st.column_config.NumberColumn(
                    format="%.1f%%",
                )
            st.dataframe(
                tbl_exec_funil,
                use_container_width=True,
                hide_index=True,
                column_config=cfg_exec_funil,
            )

        with st.expander("Como o funil calcula Reunião Agendada"):
            st.markdown(
                "- **Query da página:** `get_executivas()` → "
                "`bi.vw_dashboard_comercial_executivas_rw` → coluna `agendamentos`\n"
                "- **Helper:** `executivas_kpis(df_bruto)` soma `agendamentos` "
                "(ou bucket por classificação no topo da página)\n"
                "- **Fonte real:** `zoho_activities` com `activity_type` "
                "Consulta/Indicação\n"
                "- **Data:** `start_datetime::date` (reunião marcada no período)\n"
                "- **Filtro:** `status_reuniao IS NOT NULL` e `<> Vencida`\n"
                "- **Ligação deal:** `what_id` normalizado → `zoho_deals.id`\n"
                "- **Por que difere de oportunidades criadas:** deals usam "
                "`created_at`; agendamentos usam `start_datetime`"
            )

    # =========================================================================
    # Visão complementar — oportunidades/deals criados no período (outra base).
    # =========================================================================
    with st.expander(
        "Visão complementar: oportunidades criadas no período",
        expanded=False,
    ):
        st.caption(
            "Base **diferente** da classificação dos agendamentos do funil: "
            "`zoho_deals` com `created_at` no período (oportunidades criadas). "
            "Não é a mesma regra do card **Reunião Agendada** do Funil absoluto "
            "(que usa `zoho_activities` + `start_datetime`). "
            "O toggle **Ativos/Histórico** abaixo aplica-se apenas a esta visão."
        )
        _TRIAGEM_EXIBICAO_KEY = "executivas_triagem_modo_exibicao"
        _triagem_exib_label = st.radio(
            "Exibição",
            options=("Ativos", "Todos / Histórico"),
            index=0,
            horizontal=True,
            key=_TRIAGEM_EXIBICAO_KEY,
            help=(
                "Ativos: apenas closers com `ativo='y'` no cadastro oficial.\n"
                "Todos / Histórico: todos os deals criados no período, inclusive "
                "closers inativos. O filtro de TIMES do header vale nos dois modos."
            ),
        )
        exibicao_triagem = (
            RANKING_EXIBICAO_HISTORICO
            if _triagem_exib_label == "Todos / Histórico"
            else RANKING_EXIBICAO_ATIVOS
        )

        # Reaproveita o raw carregado no início da tab (linha ~1989). Se a
        # primeira chamada falhou, propaga o mesmo `st.error(...)` que o
        # bloco anterior exibia — preserva feedback visual sem refazer a query.
        if _df_triagem_error is not None:
            st.error(f"Falha ao carregar deals: {_df_triagem_error}")
        df_triagem_raw = _df_triagem_raw

        try:
            df_leads_triagem = get_leads_visao_geral(ctx.data_ini, ctx.data_fim)
        except Exception as e:
            st.warning(f"Falha ao carregar leads: {e}")
            df_leads_triagem = pd.DataFrame()

        df_triagem_prep = triagem_preparar_deals(df_triagem_raw)
        df_triagem_prep = cancelamentos_pos_filtrar_times(
            df_triagem_prep, _times_sel_triagem,
        )
        df_triagem_view = triagem_aplicar_exibicao(
            df_triagem_prep,
            exibicao_triagem,
            _df_oficiais,
            _df_oficiais_todas,
        )
        total_leads_triagem = triagem_contar_leads(
            df_leads_triagem,
            _times_sel_triagem,
            exibicao_triagem,
            _df_oficiais,
            _df_oficiais_todas,
        )
        kpi_triagem = triagem_kpis(df_triagem_view, total_leads_triagem)

        _cap_opp = (
            f"{ctx.data_ini:%d/%m/%Y} – {ctx.data_fim:%d/%m/%Y} · "
            f"created_at · {_triagem_exib_label.lower()}"
        )
        section_title("Oportunidades criadas no período", _cap_opp)

        if df_triagem_view.empty and total_leads_triagem == 0:
            st.info("Sem leads nem oportunidades no recorte atual.")
        else:
            o1, o2, o3, o4 = st.columns(4, gap="small")
            with o1:
                metric_card_v2(
                    "Total de Leads",
                    int_br(kpi_triagem["total_leads"]),
                    accent=True,
                )
            with o2:
                metric_card_v2(
                    "Oportunidades com Closer",
                    int_br(kpi_triagem["total_deals"]),
                    hint="zoho_deals.created_at · closer no cadastro",
                )
            with o3:
                metric_card_v2(
                    "Total classificável",
                    int_br(kpi_triagem["total_agendamentos_classificaveis"]),
                    hint=STAGE_HINT_CLASSIFICAVEL,
                )
            with o4:
                metric_card_v2(
                    "Outras etapas",
                    int_br(kpi_triagem["outras_etapas"]),
                    hint=STAGE_HINT_OUTRAS_ETAPAS,
                )

            o5, o6, o7, o8 = st.columns(4, gap="small")
            with o5:
                metric_card_v2(
                    "Lead-in",
                    int_br(kpi_triagem["lead_in"]),
                    hint="stage = Lead-in",
                )
            with o6:
                metric_card_v2(
                    STAGE_LABEL_NAO_QUALIFICADOS,
                    int_br(kpi_triagem["agendamentos_nao_qualificados"]),
                    hint=STAGE_HINT_NAO_QUALIFICADOS,
                )
            with o7:
                metric_card_v2(
                    STAGE_LABEL_QUALIFICADOS,
                    int_br(kpi_triagem["agendamentos_qualificados"]),
                    hint=STAGE_HINT_QUALIFICADOS,
                )
            with o8:
                metric_card_v2(
                    "% Qualificados",
                    pct(kpi_triagem["pct_qualificados"]),
                    hint=STAGE_HINT_PCT_QUALIFICADOS,
                )

            o9, _, _, _ = st.columns(4, gap="small")
            with o9:
                metric_card_v2(
                    "Reuniões concluídas",
                    int_br(kpi_triagem["reunioes_concluidas"]),
                    hint="stage = Reunião Concluída",
                )

            por_etapa = triagem_por_etapa(df_triagem_view)
            if not por_etapa.empty:
                section_title(
                    "Quebra por etapa",
                    f"oportunidades criadas · fora de "
                    f"{STAGE_LABEL_NAO_QUALIFICADOS}/{STAGE_LABEL_QUALIFICADOS}",
                )
                st.plotly_chart(
                    bar_simple(
                        por_etapa,
                        "etapa",
                        "total_deals",
                        height=max(300, 28 * len(por_etapa) + 80),
                        rotate_x=True,
                    ),
                    use_container_width=True,
                    key="executivas_etapa_chart",
                )
                tbl_tri = por_etapa.copy()
                tbl_tri["entra_classificavel"] = tbl_tri["entra_classificavel"].map(
                    {True: "Sim", False: "Não"}
                )
                tbl_tri = tbl_tri.rename(columns={
                    "etapa": "Etapa",
                    "entra_classificavel": "Entra no classificável?",
                    "total_deals": "Total de deals",
                    "pct_deals": "% sobre total",
                    "triagem_nao_iniciada": "Triagem não iniciada",
                    "triagem_concluida": "Triagem concluída",
                    "triagem_lead_qualificado": "Lead qualificado",
                    "triagem_lead_desqualificado": "Lead desqualificado",
                    "triagem_sem_info": "Sem informação",
                })
                cfg_tri = {"% sobre total": st.column_config.NumberColumn(format="%.1f%%")}
                st.dataframe(
                    tbl_tri,
                    use_container_width=True,
                    hide_index=True,
                    column_config=cfg_tri,
                )

            por_exec = triagem_por_executiva(df_triagem_view)
            if not por_exec.empty:
                section_title("Quebra por executiva", _triagem_exib_label.lower())
                tbl_exec = por_exec.rename(columns={
                    "executiva": "Executiva",
                    "total_deals": "Total de deals",
                    "lead_in": "Lead-in",
                    "agendamentos_nao_qualificados": STAGE_LABEL_NAO_QUALIFICADOS,
                    "agendamentos_qualificados": STAGE_LABEL_QUALIFICADOS,
                    "total_classificavel": "Total classificável",
                    "pct_qualificados": "% Qualificados",
                    "reuniao_concluida": "Reunião concluída",
                    "no_show": "No-show",
                    "ganho": "Ganho",
                    "perdido": "Perdido",
                })
                cfg_exec = {
                    "% Qualificados": st.column_config.NumberColumn(format="%.1f%%"),
                }
                st.dataframe(
                    tbl_exec,
                    use_container_width=True,
                    hide_index=True,
                    column_config=cfg_exec,
                )
