"""Pré-vendas — Visão Geral.

Cards consolidados + Tendência diária + Funil 4 etapas + Top SDRs.
SDR primário = `zoho_activities.prevendas` (NULL → 'Sem SDR').
Vendas atribuídas via `what_id` da activity → deal Ganho/Fechado Ganho
+ tipo_venda='Novo cliente' (mesma regra Visão Geral)."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import get_mkt_visao_geral_periodo
from src.prevendas_transforms import (
    prevendas_agregar_por_granularidade,
    prevendas_anotar_sdr,
    prevendas_anotar_tipo_sdr_detalhe,
    prevendas_auditoria_agendamentos_bruto_dia,
    prevendas_detalhe_mask_por_metrica,
    prevendas_diario_filtrado_por_sdr,
    prevendas_funil_etapas,
    prevendas_normalizar_detalhe,
    prevendas_overview_kpis,
    prevendas_ranking_sdr_oficiais,
    prevendas_ranking_sdr,
    prevendas_sdrs_brutos_para_oficial,
)
from src.repositories import (
    get_investimento_diario,
    get_prevendas_cohort_agendamentos,
    get_prevendas_cohort_leads,
    get_prevendas_leads_detalhe_diario,
    get_prevendas_leads_por_origem,
    get_prevendas_oportunidades_sdr,
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
    get_prevendas_sdrs_oficiais,
)
from src.transforms import _safe_div
from src.team_classification import classify_sdr, is_known_sdr
from src.ui.charts import bar_ranked, funnel
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.prevendas_ranking_cost import (
    INDICADORES_OPORT_METRIC_COLS,
    RANKING_AVG_COST_LABELS,
    augment_ranking_plot_with_cost,
    custos_medios_indicadores_oport,
    fmt_celula_indicador_com_custo,
    init_ranking_metric_col_state,
    investimento_estimado_sdr,
    render_ranking_metric_controls,
)
from src.ui.theme import PALETTE, fmt_currency_br, fmt_percent_br, int_br

# Colunas de tabela que recebem formatação pt-BR nesta página.
_TABLE_MONEY_COLS = ("Montante", "Receita", "Ticket médio")
_TABLE_PCT_COLS = (
    "% Lead → Agend.", "% Agend. → Comp.", "% Comp. → Venda",
    "% Lead +12 → Agend. +12", "% Agend. +12 → Comp. +12",
    "% Comp. +12 → Venda +12",
    "% Agendamento", "% Ag. +12", "% Ag. -12", "% Ag. Não atua",
    "% Conversão", "% Conversão +12",
)


def _format_table_br(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica fmt_currency_br / fmt_percent_br nas colunas monetárias e %."""
    out = df.copy()
    for col in _TABLE_MONEY_COLS:
        if col in out.columns:
            out[col] = out[col].apply(
                lambda v: fmt_currency_br(v) if pd.notna(v) else ""
            )
    for col in _TABLE_PCT_COLS:
        if col in out.columns:
            out[col] = out[col].apply(
                lambda v: fmt_percent_br(v) if pd.notna(v) else ""
            )
    return out

ctx = start_page(
    title="Visão Geral Pré-vendas",
    subtitle="Performance consolidada do setor",
    filters=["sdr", "tipo_sdr"],
)


try:
    df_diario = get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim)
    df_detalhe = get_prevendas_leads_detalhe_diario(ctx.data_ini, ctx.data_fim)
    df_sdr    = get_prevendas_por_sdr(ctx.data_ini, ctx.data_fim)
    df_sdrs_oficiais = get_prevendas_sdrs_oficiais()
except Exception as e:
    st.error(f"Falha ao consultar Pré-vendas: {e}")
    st.stop()

# Leads quebrados por funil_origem (daily-distinct, mesma regra do card
# "Leads totais"). Alimenta o breakdown acoplado ao card. Falha silenciosa:
# se a query nova quebrar, breakdown some sem derrubar a página.
try:
    df_leads_origem = get_prevendas_leads_por_origem(
        ctx.data_ini, ctx.data_fim
    )
except Exception:
    df_leads_origem = pd.DataFrame()

# Recortes de classificação do card "Leads totais" — mesma fonte/regra da
# Visão Geral Marketing (mkt_visao_geral_periodo.sql, period-distinct por
# bucket). Falha silenciosa: se o Marketing estiver indisponível, o hint
# do card cai pra "—" sem quebrar a página.
try:
    df_leads_periodo = get_mkt_visao_geral_periodo(ctx.data_ini, ctx.data_fim)
    if df_leads_periodo is not None and not df_leads_periodo.empty:
        row = df_leads_periodo.iloc[0]
        leads_mais_12_card = int(row.get("leads_mais_12", 0) or 0)
        leads_menos_12_card = int(row.get("leads_menos_12", 0) or 0)
        leads_nao_atua_card = int(row.get("leads_nao_atua", 0) or 0)
    else:
        leads_mais_12_card = leads_menos_12_card = leads_nao_atua_card = None
except Exception:
    leads_mais_12_card = leads_menos_12_card = leads_nao_atua_card = None

# Investido — `bi.vw_investimento_diario` (soma do período + dias distintos).
# CP2: dias vêm da própria série de investimento (equivalente à contagem
# via `dashboard_executivas`, validado nos períodos de teste).
# Não responde a filtros de SDR/Tipo SDR (investimento é global).
try:
    df_inv_periodo = get_investimento_diario(ctx.data_ini, ctx.data_fim)
    if df_inv_periodo is not None and not df_inv_periodo.empty:
        k_investido = {
            "investimento": float(df_inv_periodo["investimento_total"].sum()),
            "dias": int(
                pd.to_datetime(df_inv_periodo["data_ref"]).dt.date.nunique()
            ),
        }
    else:
        k_investido = {"investimento": 0, "dias": 0}
except Exception:
    k_investido = {"investimento": 0, "dias": 0}

df_sdr_anotado = prevendas_anotar_sdr(df_sdr)
df_sdr_filt = ctx.apply_filters(
    df_sdr_anotado,
    {"sdr": "sdr", "tipo_sdr": "tipo_sdr"},
)

# -- Filtros globais aplicados ao restante da página -----------------------
# `df_diario` é agregado sem grão de SDR, então não responde a filtros
# globais. Quando o usuário seleciona SDR/Tipo SDR no header, recompomos
# o df_diario a partir do df_detalhe (que tem SDR atribuído por activity
# e por venda), preservando os totais de Leads (não atribuíveis a SDR).
# Normalização única — reutilizada em ranking, tabela e auditoria local.
df_det_norm_base = prevendas_normalizar_detalhe(df_detalhe)
df_det_norm_global = prevendas_anotar_tipo_sdr_detalhe(df_det_norm_base)
sdr_sel_global      = list(ctx.selections.get("sdr") or [])
tipo_sdr_sel_global = list(ctx.selections.get("tipo_sdr") or [])
filtros_globais_ativos = bool(sdr_sel_global or tipo_sdr_sel_global)

if filtros_globais_ativos and df_det_norm_global is not None and not df_det_norm_global.empty:
    df_diario_view = prevendas_diario_filtrado_por_sdr(
        df_det_norm_global, df_diario,
        sdr_sel_global, tipo_sdr_sel_global,
        ctx.data_ini, ctx.data_fim,
    )

    # df_detalhe pré-filtrado pelos globais para o Detalhamento Top SDR
    # e o expander "Ver leads/agendamentos detalhados". O expander
    # "Ver dados do período" segue usando df_detalhe puro (filtros locais
    # próprios devem desacoplar dos globais).
    _mask_global_det = pd.Series(True, index=df_det_norm_global.index)
    if sdr_sel_global:
        _mask_global_det &= df_det_norm_global["sdr_filtro"].isin(sdr_sel_global)
    if tipo_sdr_sel_global:
        _mask_global_det &= df_det_norm_global["tipo_sdr_filtro"].isin(tipo_sdr_sel_global)
    df_detalhe_view = df_detalhe.loc[_mask_global_det].copy().reset_index(drop=True)
    df_det_norm_view = (
        df_det_norm_global.loc[_mask_global_det].copy().reset_index(drop=True)
    )
else:
    df_diario_view = df_diario
    df_detalhe_view = df_detalhe
    df_det_norm_view = df_det_norm_global

k = prevendas_overview_kpis(df_diario_view)
agendamentos_brutos = int(k["agendamentos"])
agendamentos_vencidos = int(k.get("vencidas", 0))
agendamentos_exibidos = int(k.get("agendamentos_exibidos",
                                  max(agendamentos_brutos - agendamentos_vencidos, 0)))
# `k_funil` original ficava aqui pra alimentar o Funil de pré-vendas;
# agora o Funil usa `k_funil_origem` (computado mais abaixo, depois do
# filtro de Funil de Origem). Mantemos só o `k` pros cards do Resumo.

# ---------------------------------------------------------------------------
# Breakdown por funil_origem acoplado aos cards "Leads totais" e
# "Agendamentos criados" do Resumo do período.
#
# Regra de exibição:
#   - Ordem fixa: VSL, SE, AG, <outras alfabéticas>, Sem origem.
#   - Só exibe origens com leads > 0 no período (esconde linhas zeradas).
#   - Conversão usa leads como denominador (origens sem leads ⇒ skip,
#     evita divisão por zero e linhas inúteis).
#
# Quando o usuário aplica SDR/Tipo SDR no header, o breakdown de leads
# segue mostrando o total geral (leads não são atribuíveis a SDR — mesma
# regra do hint atual do card); o breakdown de agendamentos respeita o
# filtro de SDR aplicando mask sobre o detalhe normalizado.
# ---------------------------------------------------------------------------
leads_origem_map: dict[str, int] = {}
leads_mais12_origem_map: dict[str, int] = {}
if df_leads_origem is not None and not df_leads_origem.empty:
    leads_origem_map = {
        str(r["funil_origem"]): int(r["leads"] or 0)
        for _, r in df_leads_origem.iterrows()
    }
    if "leads_mais_12" in df_leads_origem.columns:
        leads_mais12_origem_map = {
            str(r["funil_origem"]): int(r["leads_mais_12"] or 0)
            for _, r in df_leads_origem.iterrows()
        }

# Detalhe normalizado já filtrado pelos filtros globais SDR/Tipo SDR.
# Reaproveitado por todos os mapas de origem abaixo — alinha as
# quebras com o universo dos cards do Resumo.
if df_det_norm_global is None or df_det_norm_global.empty:
    _df_det_para_origens = (
        df_det_norm_global if df_det_norm_global is not None else pd.DataFrame()
    )
else:
    _df_det_para_origens = df_det_norm_global
    if sdr_sel_global:
        _df_det_para_origens = _df_det_para_origens[
            _df_det_para_origens["sdr_filtro"].isin(sdr_sel_global)
        ]
    if (tipo_sdr_sel_global
            and "tipo_sdr_filtro" in _df_det_para_origens.columns):
        _df_det_para_origens = _df_det_para_origens[
            _df_det_para_origens["tipo_sdr_filtro"].isin(tipo_sdr_sel_global)
        ]


def _por_origem(df_norm: pd.DataFrame,
                mask: pd.Series,
                unidade_col: str) -> dict[str, int]:
    """COUNT(DISTINCT <unidade>) no detalhe normalizado, agrupado por
    funil_origem_filtro. `mask` é uma Series booleana sobre `df_norm`."""
    if df_norm is None or df_norm.empty:
        return {}
    sub = df_norm.loc[mask]
    if sub.empty or unidade_col not in sub.columns:
        return {}
    sub = sub.drop_duplicates(subset=[unidade_col])
    return sub.groupby("funil_origem_filtro").size().astype(int).to_dict()


# Máscaras-base do detalhe (atividade / venda / janela de datas)
if not _df_det_para_origens.empty:
    _ini_ts = pd.Timestamp(ctx.data_ini)
    _fim_ts = pd.Timestamp(ctx.data_fim)
    _det = _df_det_para_origens
    _is_ativ = _det["tipo_registro_base_filtro"] == "Atividade"
    _is_vend = _det["tipo_registro_base_filtro"] == "Venda"
    _em_cria = (
        _det["data_criacao"].notna()
        & _det["data_criacao"].between(_ini_ts, _fim_ts, inclusive="both")
    )
    _em_agen = (
        _det["data_agendamento"].notna()
        & _det["data_agendamento"].between(_ini_ts, _fim_ts, inclusive="both")
    )
    _em_vend = (
        _det["data_venda"].notna()
        & _det["data_venda"].between(_ini_ts, _fim_ts, inclusive="both")
    )
    _is_concl   = _det["status_filtro"].isin(["Concluída", "Concluído"])
    _is_venc    = _det["status_filtro"] == "Vencida"
    _is_mais_12 = (
        (_det.get("classificacao_crm_filtro",
                  pd.Series("", index=_det.index)) == "Atua +12")
        | (_det["classificacao_filtro"] == "Atua +12")
    )

    # Agendamentos criados (data_criacao no período)
    ag_criados_origem_map = _por_origem(
        _det, _is_ativ & _em_cria, "activity_id",
    )
    # Agendamentos bruto + vencidos (data_agendamento no período)
    _ag_bruto_origem  = _por_origem(_det, _is_ativ & _em_agen, "activity_id")
    _ag_venc_origem   = _por_origem(_det, _is_ativ & _em_agen & _is_venc, "activity_id")
    # Agendamentos exibidos = bruto − vencidos (por origem, sem ficar negativo)
    ag_exibidos_origem_map = {
        o: max(_ag_bruto_origem.get(o, 0) - _ag_venc_origem.get(o, 0), 0)
        for o in set(_ag_bruto_origem) | set(_ag_venc_origem)
    }
    ag_mais12_origem_map = _por_origem(
        _det, _is_ativ & _em_agen & _is_mais_12, "activity_id",
    )
    comp_origem_map = _por_origem(
        _det, _is_ativ & _em_agen & _is_concl, "activity_id",
    )
    vendas_origem_map = _por_origem(
        _det, _is_vend & _em_vend, "deal_id",
    )
else:
    ag_criados_origem_map  = {}
    ag_exibidos_origem_map = {}
    ag_mais12_origem_map   = {}
    comp_origem_map        = {}
    vendas_origem_map      = {}

_CHIPS_PRIORIDADE = ("VSL", "SE", "AG")


def _origens_block_volume(qtd_map: dict[str, int],
                          title: str = "Por origem") -> dict | None:
    """Bloco de chips de VOLUME (Leads totais). Mostra valor absoluto
    por origem; 'Sem origem' cai na linha muted abaixo."""
    if not qtd_map:
        return None
    chips = [(o, int_br(int(qtd_map.get(o, 0))))
             for o in _CHIPS_PRIORIDADE]
    muted = None
    if qtd_map.get("Sem origem", 0) > 0:
        muted = ("Sem origem", int_br(int(qtd_map["Sem origem"])))
    return {"title": title, "chips": chips, "muted": muted}


def _origens_block_pct(num_map: dict[str, int],
                       den_map: dict[str, int],
                       title: str) -> dict | None:
    """Bloco de chips de CONVERSÃO (num / den) por origem. `—` quando o
    denominador da origem é zero, `0,00%` quando há denominador mas zero
    numerador. 'Sem origem' aparece como linha muted formatada
    'N/D · %' (ou apenas '—' quando D=0). Devolve None se ambos os
    mapas estiverem vazios."""
    if not num_map and not den_map:
        return None

    def _conv_str(label: str) -> str:
        d = den_map.get(label, 0)
        if d <= 0:
            return "—"
        return fmt_percent_br(num_map.get(label, 0) / d * 100.0)

    chips = [(o, _conv_str(o)) for o in _CHIPS_PRIORIDADE]
    muted = None
    d_so = den_map.get("Sem origem", 0)
    n_so = num_map.get("Sem origem", 0)
    if d_so > 0:
        muted = (
            "Sem origem",
            f"{int_br(n_so)}/{int_br(d_so)} · "
            f"{fmt_percent_br(n_so / d_so * 100.0)}",
        )
    return {"title": title, "chips": chips, "muted": muted}


origens_block_leads        = _origens_block_volume(
    leads_origem_map, title="Por origem"
)
origens_block_ag_criados   = _origens_block_pct(
    ag_criados_origem_map,  leads_origem_map,
    title="Conv. lead → ag. criado",
)
origens_block_ag_exibidos  = _origens_block_pct(
    ag_exibidos_origem_map, leads_origem_map,
    title="Conv. lead → agendamento",
)
origens_block_ag_mais_12   = _origens_block_pct(
    ag_mais12_origem_map,   leads_mais12_origem_map,
    title="Conv. lead +12 → ag. +12",
)
origens_block_comp         = _origens_block_pct(
    comp_origem_map,        ag_exibidos_origem_map,
    title="Conv. ag. → compar.",
)
origens_block_vendas       = _origens_block_pct(
    vendas_origem_map,      ag_exibidos_origem_map,
    title="Conv. ag. → venda",
)

# Custos unitários — investido global (One Page) ÷ quantidade da etapa no card.
_investido_total = float(k_investido.get("investimento") or 0)


def _custo_por_etapa(qtd) -> str:
    return fmt_currency_br(_safe_div(_investido_total, qtd))


# ---------------------------------------------------------------------------
# Resumo do período
# ---------------------------------------------------------------------------
section_title(
    "Resumo do período",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

if filtros_globais_ativos:
    _partes_filtro = []
    if sdr_sel_global:
        _partes_filtro.append(f"SDR: {', '.join(sdr_sel_global)}")
    if tipo_sdr_sel_global:
        _partes_filtro.append(f"Tipo SDR: {', '.join(tipo_sdr_sel_global)}")
    st.caption(
        "🔎 Filtros globais aplicados — "
        + " · ".join(_partes_filtro)
        + ". Cards, Funil, Tendência diária, Top SDRs e Detalhamento "
        "refletem essa seleção. Leads continua mostrando o total geral "
        "(lead não é atribuível a SDR no momento do form)."
    )

c0, c1, c2, c3, c4, c5 = st.columns(6, gap="small")
with c0:
    if leads_mais_12_card is not None:
        leads_hint = (
            f"+12: {int_br(leads_mais_12_card)} · "
            f"-12: {int_br(leads_menos_12_card)} · "
            f"Não atua: {int_br(leads_nao_atua_card)}"
        )
    else:
        leads_hint = "Recortes indisponíveis (Marketing)"
    if filtros_globais_ativos:
        leads_hint += " · total geral (sem filtro de SDR)"
    metric_card_v2(
        "Leads totais",
        int_br(k["leads"]),
        hint=leads_hint,
        breakdown=[("Custo / Lead", _custo_por_etapa(k["leads"]))],
        origens=origens_block_leads,
        variant="resumo",
    )
with c1:
    metric_card_v2(
        "Agendamentos criados",
        int_br(k["agendamentos_criados"]),
        accent=True,
        breakdown=[("Custo / Ag. criado",
                    _custo_por_etapa(k["agendamentos_criados"]))],
        origens=origens_block_ag_criados,
        variant="resumo",
        help=(
            "zoho_activities.created_time::date · "
            "status_reuniao IS NOT NULL"
        ),
    )
with c2:
    metric_card_v2(
        "Agendamentos",
        int_br(agendamentos_exibidos),
        hint=(
            f"Bruto: {int_br(agendamentos_brutos)} · "
            f"Vencidos removidos: {int_br(agendamentos_vencidos)} · "
            f"Exibido: {int_br(agendamentos_exibidos)}"
        ),
        breakdown=[("Custo / Agend.",
                    _custo_por_etapa(agendamentos_exibidos))],
        origens=origens_block_ag_exibidos,
        variant="resumo",
    )
with c3:
    metric_card_v2(
        "Agendamentos +12",
        int_br(k["agendamentos_mais_12"]),
        breakdown=[("Custo / Ag. +12",
                    _custo_por_etapa(k["agendamentos_mais_12"]))],
        origens=origens_block_ag_mais_12,
        variant="resumo",
        help="classificado = 'Atua +12' via ext_reconecta.leads",
    )
with c4:
    metric_card_v2(
        "Comparecimentos",
        int_br(k["comparecimentos"]),
        breakdown=[("Custo / Comp.",
                    _custo_por_etapa(k["comparecimentos"]))],
        origens=origens_block_comp,
        variant="resumo",
        help="status_reuniao IN ('Concluída','Concluído')",
    )
with c5:
    metric_card_v2(
        "Vendas",
        int_br(k["vendas"]),
        origens=origens_block_vendas,
        variant="resumo",
        breakdown_placeholder=True,
        help=(
            "zoho_deals.stage = 'Ganho' · "
            "tipo_venda = 'Novo cliente'"
        ),
    )

# Linha 2 — financeiro / eficiência
r2c1, r2c2, r2c3, r2c4, r2c5 = st.columns(5, gap="small")
_fin_card = dict(card_class="prevendas-finance")
with r2c1:
    metric_card_v2("Montante",
                   fmt_currency_br(k["montante"]),
                   hint="SUM(amount) da base_dados",
                   **_fin_card)
with r2c2:
    metric_card_v2(
        "Investido",
        fmt_currency_br(k_investido["investimento"]),
        hint=f"{int_br(k_investido['dias'])} dias",
        **_fin_card,
    )
with r2c3:
    metric_card_v2("Receita",
                   fmt_currency_br(k["receita"]),
                   hint="SUM(receita) da base_dados",
                   **_fin_card)
with r2c4:
    metric_card_v2("Taxa de comparecimento",
                   fmt_percent_br(k["taxa_comparecimento"]),
                   hint="comparecimentos ÷ agendamentos exibidos (bruto - vencidas)",
                   **_fin_card)
with r2c5:
    metric_card_v2("Ticket médio",
                   fmt_currency_br(k["ticket_medio"]),
                   hint="montante ÷ vendas",
                   **_fin_card)

# ---------------------------------------------------------------------------
# Auditoria temporária — Agendamentos 10/06/2026 (não altera o card)
# ---------------------------------------------------------------------------
_AUDITORIA_AG_DIA = date(2026, 6, 10)
_AUDITORIA_MES_INI = date(_AUDITORIA_AG_DIA.year, _AUDITORIA_AG_DIA.month, 1)
_AUDITORIA_MES_FIM = date(_AUDITORIA_AG_DIA.year, _AUDITORIA_AG_DIA.month, 30)
_periodo_cobre_mes_auditoria = (
    ctx.data_ini <= _AUDITORIA_MES_INI and ctx.data_fim >= _AUDITORIA_MES_FIM
)
carregar_auditoria = st.checkbox(
    "Carregar auditoria de agendamentos jun/2026",
    value=False,
    key="prevendas_overview_carregar_auditoria",
    help=(
        "Consulta o detalhe de jun/2026 só quando ativado. "
        "Se o período selecionado já cobre jun/2026 inteiro, reutiliza os "
        "dados já carregados."
    ),
)
with st.expander(
    f"🔎 Auditoria temporária — Agendamentos {_AUDITORIA_AG_DIA.strftime('%d/%m/%Y')}",
    expanded=False,
):
    st.caption(
        "Conferência entre o dashboard e o sistema da gestora. "
        "Lista as activities que entram no **bruto** do card "
        "(reunião na data · Consulta/Indicação · status preenchido). "
        "O **exibido** segue a regra atual: bruto − vencidas "
        "(canceladas permanecem no exibido). "
        "Referência esperada pela gestora: **27** exibidos."
    )
    if not carregar_auditoria:
        st.info(
            "Ative **Carregar auditoria de agendamentos jun/2026** acima "
            "para executar a consulta."
        )
        tabela_audit = pd.DataFrame()
    else:
        try:
            if _periodo_cobre_mes_auditoria:
                _det_audit = df_det_norm_base
            else:
                # Mês inteiro — captura activities criadas antes da reunião.
                _df_audit = get_prevendas_leads_detalhe_diario(
                    _AUDITORIA_MES_INI,
                    _AUDITORIA_MES_FIM,
                )
                _det_audit = prevendas_normalizar_detalhe(_df_audit)
            tabela_audit = prevendas_auditoria_agendamentos_bruto_dia(
                _det_audit, _AUDITORIA_AG_DIA,
            )
        except Exception as _e_audit:
            st.error(f"Falha ao montar auditoria: {_e_audit}")
            tabela_audit = pd.DataFrame()

    if not carregar_auditoria:
        pass
    elif tabela_audit.empty:
        st.info("Nenhuma activity encontrada na base bruta para essa data.")
    else:
        n_bruto = len(tabela_audit)
        n_venc = int((tabela_audit["É vencido"] == "Sim").sum())
        n_canc = int((tabela_audit["É cancelado"] == "Sim").sum())
        n_exib = int((tabela_audit["Entra no card (exibido)"] == "Sim").sum())
        delta_exib = n_exib - 27
        delta_exib_txt = int_br(delta_exib)
        if delta_exib > 0:
            delta_exib_txt = f"+{delta_exib_txt}"
        st.markdown(
            f"**Resumo:** {int_br(n_bruto)} brutos · "
            f"{int_br(n_venc)} vencidos removidos · "
            f"{int_br(n_canc)} cancelados no CRM (ainda no exibido) · "
            f"**{int_br(n_exib)} exibidos** · gestora: **27** · "
            f"Δ {delta_exib_txt}"
        )
        st.dataframe(
            tabela_audit,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Data/hora da reunião": st.column_config.TextColumn(
                    "Data/hora da reunião", width="medium",
                ),
                "Nome do deal": st.column_config.TextColumn(
                    "Nome do deal", width="large",
                ),
                "SDR": st.column_config.TextColumn("SDR", width="medium"),
                "Motivo": st.column_config.TextColumn("Motivo", width="large"),
            },
        )

# ---------------------------------------------------------------------------
# Filtro local de Funil de Origem (VSL / SE / AG / Sem origem).
# Afeta Funil, Tendência diária e Indicadores por Pré-vendas. Cards do
# Resumo seguem com o total do período (sem filtro de origem) — o filtro
# desce a partir daqui. Coluna `funil_origem` ativada em 25/05/2026 em
# `ext_reconecta.leads`; entradas anteriores caem em 'Sem origem'.
# ---------------------------------------------------------------------------
if (df_det_norm_global is not None
        and not df_det_norm_global.empty
        and "funil_origem_filtro" in df_det_norm_global.columns):
    # Ordem fixa (VSL/SE/AG primeiro, 'Sem origem' por último) — sem
    # depender do data-driven sort, pra UX previsível conforme novos
    # códigos surgirem (entram em ordem alfabética antes de 'Sem origem').
    _origens_vistas = (
        df_det_norm_global["funil_origem_filtro"]
        .dropna().astype(str).unique().tolist()
    )
    _ord_prio = ["VSL", "SE", "AG"]
    _outras   = sorted(o for o in _origens_vistas
                       if o not in _ord_prio and o != "Sem origem")
    _sem_orig = ["Sem origem"] if "Sem origem" in _origens_vistas else []
    opcoes_funil_origem = (
        [o for o in _ord_prio if o in _origens_vistas]
        + _outras
        + _sem_orig
    )
else:
    opcoes_funil_origem = []

funil_origem_sel = st.multiselect(
    "Funil de Origem (afeta Funil, Tendência diária e Indicadores por "
    "Pré-vendas)",
    options=opcoes_funil_origem,
    default=[],
    placeholder="Todos",
    key="prevendas_overview_funil_origem_local",
    help="Filtra leads pelo `funil_origem` em `ext_reconecta.leads`. "
         "Cards do Resumo do período seguem com o total geral.",
)
funil_origem_ativo = bool(funil_origem_sel)

# Recompõe o diário aplicando o filtro de funil (preserva os filtros
# globais de SDR/Tipo SDR). Quando nenhum filtro local de origem está
# ativo, mantém `df_diario_view` original (computado no topo da página).
if funil_origem_ativo and df_det_norm_global is not None and not df_det_norm_global.empty:
    df_diario_view_funil = prevendas_diario_filtrado_por_sdr(
        df_det_norm_global,
        df_diario,
        sdr_sel_global,
        tipo_sdr_sel_global,
        ctx.data_ini,
        ctx.data_fim,
        funis_origem_filtro=funil_origem_sel,
    )
else:
    df_diario_view_funil = df_diario_view

k_origem = prevendas_overview_kpis(df_diario_view_funil)
_ag_brutos_o   = int(k_origem["agendamentos"])
_ag_vencidos_o = int(k_origem.get("vencidas", 0))
_ag_exibidos_o = int(k_origem.get(
    "agendamentos_exibidos",
    max(_ag_brutos_o - _ag_vencidos_o, 0),
))
k_funil_origem = dict(k_origem)
k_funil_origem["agendamentos"] = _ag_exibidos_o

if funil_origem_ativo:
    st.caption(
        "🔎 Filtro de origem aplicado: "
        + ", ".join(funil_origem_sel)
        + ". Funil, Tendência diária e Indicadores por Pré-vendas "
        "abaixo respeitam essa seleção; o Resumo do período no topo "
        "continua mostrando o total geral."
    )

# ---------------------------------------------------------------------------
# Funil — 4 etapas
# ---------------------------------------------------------------------------
section_title("Funil de pré-vendas",
              "agendamentos criados → agendamentos → comparecimentos → vendas")

labels, values = prevendas_funil_etapas(k_funil_origem)
if all(v == 0 for v in values):
    st.info("Sem dados no período.")
else:
    st.plotly_chart(
        funnel(labels, values, height=320, show_dropoff=True, pct_casas=2),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Tendência diária
# ---------------------------------------------------------------------------
section_title("Tendência diária",
              "agendamentos criados × agendamentos × comparecimentos")

if df_diario_view_funil.empty:
    st.info("Sem dados diários no período.")
else:
    df_diario_plot = df_diario_view_funil.copy()
    if {"agendamentos", "vencidas"}.issubset(df_diario_plot.columns):
        df_diario_plot["agendamentos_liquidos"] = (
            df_diario_plot["agendamentos"].fillna(0)
            - df_diario_plot["vencidas"].fillna(0)
        ).clip(lower=0)
    else:
        df_diario_plot["agendamentos_liquidos"] = df_diario_plot["agendamentos"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_diario_plot["data_ref"],
        y=df_diario_plot["agendamentos_criados"],
        name="Agendamentos criados",
        line=dict(color=PALETTE["gold"], width=2.8),
        mode="lines+markers",
        marker=dict(size=6),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} agendamentos criados<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df_diario_plot["data_ref"],
        y=df_diario_plot["agendamentos_liquidos"],
        name="Agendamentos",
        line=dict(color=PALETTE["wine_light"], width=2.8, dash="dot"),
        mode="lines+markers",
        marker=dict(size=6),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} agendamentos líquidos<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df_diario_plot["data_ref"],
        y=df_diario_plot["comparecimentos"],
        name="Comparecimentos",
        line=dict(color="#7C3AED", width=2.4, dash="dash"),
        mode="lines+markers",
        marker=dict(size=6, color="#7C3AED"),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} comparecimentos<extra></extra>",
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=12, r=12, t=18, b=12),
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
        yaxis=dict(title="Quantidade", gridcolor=PALETTE["border"]),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"],
                     tickfont=dict(color=PALETTE["text_subtle"], size=11))
    st.plotly_chart(
        fig,
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Top SDRs — gráfico à esquerda, painel retrátil de detalhe à direita
# ---------------------------------------------------------------------------
ranking_metric_options = {
    "Agendamentos criados": "agendamentos_criados",
    "Agendamentos": "agendamentos",
    "Agendamentos +12": "agendamentos_mais_12",
    "Agendamentos -12": "agendamentos_menos_12",
    "Comparecimentos": "comparecimentos",
    "Vendas": "vendas",
    "Cancelados": "cancelados",
    "Vencidos": "vencidos",
}
_RANKING_LABEL_BY_COL = {
    col: label for label, col in ranking_metric_options.items()
}
_col_atual_ranking = init_ranking_metric_col_state(
    ranking_metric_options,
    "Agendamentos",
    "prevendas_overview_ranking_metric_col",
    "prevendas_overview_ranking_metric",
)
_label_atual = _RANKING_LABEL_BY_COL[_col_atual_ranking]
section_title("Top SDRs", f"ranking do período · {_label_atual.lower()}")

ranking = prevendas_ranking_sdr_oficiais(df_sdr_filt, df_sdrs_oficiais)

col_grafico, col_detalhe = st.columns([1.45, 1], gap="large")

# ===========================================================================
# COLUNA ESQUERDA — métrica + gráfico clicável
# ===========================================================================
with col_grafico:
    ranking_metric_col, ranking_metric_label, mostrar_custo_grafico = (
        render_ranking_metric_controls(
            metric_options=ranking_metric_options,
            default_metric_label="Agendamentos",
            key_prefix="prevendas_overview",
            investido_total=_investido_total,
            kpis=k,
            df_rank_base=df_sdr_filt,
            agendamentos_exibidos=agendamentos_exibidos,
        )
    )

    ranking_plot = ranking[ranking[ranking_metric_col].fillna(0) > 0].copy()
    chart_state = None

    if ranking_plot.empty:
        st.info(f"Sem {ranking_metric_label.lower()} no período.")
    else:
        ranking_plot, _custo_medio_num, _custo_medio_fmt = (
            augment_ranking_plot_with_cost(
                ranking_plot,
                ranking_metric_col,
                df_sdr_filt,
                _investido_total,
                k,
                agendamentos_exibidos=agendamentos_exibidos,
            )
        )
        fig_top = bar_ranked(
            ranking_plot,
            "sdr",
            ranking_metric_col,
            top_n=12,
            height=320,
            metric_label=ranking_metric_label,
            cost_col="_inv_estimado_sdr",
            cost_label=RANKING_AVG_COST_LABELS.get(
                ranking_metric_col, "Custo médio",
            ),
            avg_cost_display=_custo_medio_fmt,
            show_cost_on_bar=mostrar_custo_grafico,
        )
        chart_state = st.plotly_chart(
            fig_top,
            use_container_width=True,
            key="prevendas_overview_top_sdrs_chart",
            on_select="rerun",
            selection_mode="points",
        )

# ===========================================================================
# COLUNA DIREITA — painel retrátil "Detalhe da SDR selecionada"
# ===========================================================================
with col_detalhe:
    if ranking_plot.empty or df_detalhe_view is None or df_detalhe_view.empty:
        with st.expander("Detalhe da SDR selecionada", expanded=False):
            st.caption(
                "Sem dados de ranking ou de detalhe no período para esses "
                "filtros."
            )
    else:
        sdrs_disponiveis = ranking_plot["sdr"].dropna().astype(str).tolist()
        OPCAO_TODAS = "Todas"

        # ---- Sincronia clique-no-gráfico ↔ selectbox ----------------------
        # Lê o ponto clicado em `chart_state` e propaga pro session_state do
        # selectbox ANTES do widget renderizar. Detecta clique novo via
        # `_last_click_key` para que mudanças manuais no selectbox em runs
        # subsequentes não sejam sobrescritas pela seleção persistida do
        # gráfico (Streamlit mantém o ponto selecionado entre reruns).
        SELECTBOX_KEY  = "prevendas_overview_top_sdr_detalhe"
        LAST_CLICK_KEY = "_prevendas_overview_top_sdr_last_chart_pick"

        clicked_sdr = None
        try:
            pts = (chart_state or {}).get("selection", {}).get("points", [])
        except Exception:
            pts = []
        if pts:
            cd = pts[0].get("customdata")
            if isinstance(cd, (list, tuple)) and cd:
                clicked_sdr = str(cd[0])
            elif isinstance(cd, str):
                clicked_sdr = cd
            elif pts[0].get("y") is not None:
                y_clicked = str(pts[0]["y"])
                clicked_sdr = next(
                    (s for s in sdrs_disponiveis if s == y_clicked
                     or s.startswith(y_clicked.rstrip("…"))),
                    None,
                )

        if (clicked_sdr
                and clicked_sdr in sdrs_disponiveis
                and clicked_sdr != st.session_state.get(LAST_CLICK_KEY)):
            st.session_state[SELECTBOX_KEY]  = clicked_sdr
            st.session_state[LAST_CLICK_KEY] = clicked_sdr

        if st.session_state.get(SELECTBOX_KEY) not in (
                [OPCAO_TODAS] + sdrs_disponiveis):
            st.session_state[SELECTBOX_KEY] = OPCAO_TODAS

        # Título dinâmico do expander reflete a seleção atual. Streamlit não
        # permite reabrir programaticamente entre reruns; o painel começa
        # FECHADO por default (preferência do user) — o conteúdo dentro
        # ainda atualiza coerentemente quando o user reabre depois de
        # clicar numa barra ou trocar o selectbox.
        sdr_atual = st.session_state.get(SELECTBOX_KEY, OPCAO_TODAS)
        titulo_expander = (
            "Detalhe da SDR selecionada"
            if sdr_atual == OPCAO_TODAS
            else f"Detalhe — {sdr_atual}"
        )

        with st.expander(titulo_expander, expanded=False):
            st.caption(
                "💡 **Clique numa barra do gráfico** para detalhar aquele SDR — "
                "ou use o seletor abaixo. 'Todas' mostra o consolidado."
            )
            sdr_escolhido = st.selectbox(
                "SDR para detalhar",
                options=[OPCAO_TODAS] + sdrs_disponiveis,
                key=SELECTBOX_KEY,
            )

            df_det_norm = df_det_norm_view
            mask_metrica = prevendas_detalhe_mask_por_metrica(
                df_det_norm, ranking_metric_col, ctx.data_ini, ctx.data_fim
            )

            if sdr_escolhido == OPCAO_TODAS:
                contagem_grafico = int(
                    ranking_plot[ranking_metric_col].fillna(0).sum()
                )
                mask_sdr = pd.Series(True, index=df_det_norm.index)
            else:
                contagem_grafico = int(
                    ranking_plot.loc[
                        ranking_plot["sdr"] == sdr_escolhido, ranking_metric_col
                    ].iloc[0]
                )
                sdrs_brutos = prevendas_sdrs_brutos_para_oficial(
                    df_det_norm, sdr_escolhido, df_sdrs_oficiais
                )
                mask_sdr = df_det_norm["sdr_filtro"].isin(sdrs_brutos)

            linhas_brutas = df_det_norm[mask_sdr & mask_metrica].copy()

            # Unidade da métrica: vendas conta deal_id distinto; resto conta
            # activity_id distinto. Fan-out em activity_rows do SQL (base_dados
            # LEFT JOIN ext_reconecta.leads multiplica activities quando o
            # mesmo zoho_id tem N linhas de lead) é removido aqui.
            unidade_col = "deal_id" if ranking_metric_col == "vendas" else "activity_id"

            if unidade_col in linhas_brutas.columns:
                contagem_tabela = int(linhas_brutas[unidade_col].nunique(dropna=False))
                linhas = linhas_brutas.drop_duplicates(
                    subset=[unidade_col], keep="first"
                ).copy()
            else:
                contagem_tabela = len(linhas_brutas)
                linhas = linhas_brutas.copy()

            linhas_duplicadas = len(linhas_brutas) - len(linhas)

            # ---------------- Mini-cards de resumo ----------------------
            # Lê do `ranking` (1 row por SDR oficial) para a SDR escolhida
            # ou soma do ranking_plot para "Todas".
            if sdr_escolhido == OPCAO_TODAS:
                fonte = ranking_plot
            else:
                fonte = ranking_plot.loc[ranking_plot["sdr"] == sdr_escolhido]

            def _sum_col(col: str) -> int:
                if col in fonte.columns:
                    return int(fonte[col].fillna(0).sum())
                return 0

            def _sum_money(col: str) -> float:
                if col in fonte.columns:
                    return float(fonte[col].fillna(0).sum())
                return 0.0

            st.markdown(
                f"**{sdr_escolhido}** · {ranking_metric_label}: "
                f"gráfico {int_br(contagem_grafico)} · "
                f"tabela {int_br(contagem_tabela)}"
            )

            mc1, mc2, mc3 = st.columns(3, gap="small")
            with mc1:
                metric_card_v2(
                    "Agendamentos",
                    int_br(_sum_col("agendamentos")),
                    hint="Atividades Consulta/Indicação (bruto)",
                )
            with mc2:
                metric_card_v2(
                    "Agendamentos +12",
                    int_br(_sum_col("agendamentos_mais_12")),
                    hint="classificação combinada lead+CRM",
                )
            with mc3:
                metric_card_v2(
                    "Comparecimentos",
                    int_br(_sum_col("comparecimentos")),
                    hint="status_reuniao = 'Concluída'",
                )

            mc4, mc5 = st.columns(2, gap="small")
            with mc4:
                metric_card_v2(
                    "Vendas",
                    int_br(_sum_col("vendas")),
                    hint="deals ganhos no período",
                    accent=True,
                )
            with mc5:
                receita_val = _sum_money("receita")
                if receita_val == 0:
                    receita_val = _sum_money("montante")
                    label_receita = "Montante"
                else:
                    label_receita = "Receita"
                metric_card_v2(
                    label_receita,
                    fmt_currency_br(receita_val),
                    hint=("receita dos deals ganhos"
                          if label_receita == "Receita"
                          else "montante dos deals ganhos"),
                )

            # ---------------- Avisos de divergência ---------------------
            _card_metric_map = {
                "agendamentos_criados": k.get("agendamentos_criados"),
                "agendamentos":          k.get("agendamentos"),
                "agendamentos_mais_12":  k.get("agendamentos_mais_12"),
                "comparecimentos":       k.get("comparecimentos"),
                "vendas":                k.get("vendas"),
            }
            if (sdr_escolhido == OPCAO_TODAS
                    and ranking_metric_col in _card_metric_map):
                valor_card = int(_card_metric_map[ranking_metric_col] or 0)
                soma_ranking = int(ranking_plot[ranking_metric_col].fillna(0).sum())
                diff = valor_card - soma_ranking
                if diff == 0:
                    st.caption(
                        f"✓ Soma do ranking ({int_br(soma_ranking)}) bate com o "
                        f"card de **{ranking_metric_label}** ({int_br(valor_card)})."
                    )
                else:
                    st.caption(
                        f"ℹ Ranking visível: {int_br(soma_ranking)} · card "
                        f"**{ranking_metric_label}**: {int_br(valor_card)} "
                        f"(Δ {int_br(diff)}). O ranking só inclui SDRs oficiais; "
                        "Letícia Garcia, Bruna Braga, 'Sem SDR' etc. contam no "
                        "card mas não aparecem aqui."
                        + (" O card de Agendamentos no topo é líquido "
                           "(bruto − vencidos); aqui usamos o bruto."
                           if ranking_metric_col == "agendamentos" else "")
                    )

            if contagem_tabela != contagem_grafico:
                delta = contagem_tabela - contagem_grafico
                if delta < 0:
                    st.warning(
                        f"Tabela: {int_br(contagem_tabela)} · gráfico: "
                        f"{int_br(contagem_grafico)} (faltam "
                        f"{int_br(abs(delta))}). O ranking inclui atividade "
                        "com SDR oficial mesmo sem deal pareado; o detalhe "
                        "exige vínculo com deal."
                    )
                else:
                    st.warning(
                        f"Tabela: {int_br(contagem_tabela)} · gráfico: "
                        f"{int_br(contagem_grafico)} (sobram "
                        f"{int_br(delta)}). Pode haver `{unidade_col}` no "
                        "detalhe não considerado pelo ranking ou fan-out "
                        "residual."
                    )

            if linhas_duplicadas > 0:
                st.caption(
                    f"⚙ Removidas {int_br(linhas_duplicadas)} duplicata(s) "
                    f"por `{unidade_col}`."
                )

            # ---------------- Tabela resumida ---------------------------
            if linhas.empty:
                st.caption("Nenhum registro encontrado para esse SDR/métrica.")
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

                # Subset resumido conforme pedido (Nome · E-mail · Classif ·
                # Status · Origem · Data agend · Closer).
                cols_map_resumo = [
                    ("#",                       "#"),
                    ("nome_cliente_view",       "Nome do cliente/lead"),
                    ("email_final_filtro",      "E-mail"),
                    ("classificacao_final_filtro", "Classificação"),
                    ("status_filtro",           "Status reunião"),
                    ("origem_fonte",            "Origem/fonte"),
                    ("funil_origem_filtro",     "Funil de Origem"),
                    ("data_agendamento",        "Data agendamento"),
                    ("closer_filtro",           "Closer"),
                ]
                cols_resumo = [c for c, _ in cols_map_resumo
                               if c in linhas.columns]
                tabela_resumo = linhas[cols_resumo].rename(
                    columns={c: lbl for c, lbl in cols_map_resumo
                             if c in cols_resumo}
                )
                cfg_resumo = {
                    "#": st.column_config.NumberColumn("#", format="%d"),
                }
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

                # Toggle "Ver tabela completa" — Streamlit não permite expander
                # aninhado dentro de expander; toggle preserva a UX retrátil.
                ver_completa = st.toggle(
                    "Ver tabela completa",
                    value=False,
                    key="prevendas_overview_top_sdr_ver_completa",
                )
                if ver_completa:
                    cols_map_top = [
                        ("#", "#"),
                        ("nome_cliente_view", "Nome do cliente/lead"),
                        ("email_final_filtro",      "E-mail"),
                        ("email_lead_filtro",       "E-mail (lead)"),
                        ("email_crm_filtro",        "E-mail (CRM)"),
                        ("sdr_filtro", "SDR"),
                        ("closer_filtro", "Closer"),
                        ("classificacao_filtro", "Classif. (lead)"),
                        ("classificacao_crm_filtro", "Classif. (CRM)"),
                        ("status_filtro", "Status reunião"),
                        ("origem_fonte", "Origem/fonte"),
                        ("funil_origem_filtro", "Funil de Origem"),
                        ("data_criacao", "Data de criação"),
                        ("data_agendamento", "Data do agendamento"),
                        ("data_venda", "Data da venda"),
                        ("deal_id", "ID do deal"),
                        ("activity_id", "ID da activity"),
                        ("montante", "Montante"),
                        ("receita", "Receita"),
                    ]
                    cols_full = [c for c, _ in cols_map_top
                                 if c in linhas.columns]
                    tabela_full = _format_table_br(
                        linhas[cols_full].rename(
                            columns={c: lbl for c, lbl in cols_map_top
                                     if c in cols_full}
                        )
                    )
                    cfg_full = {
                        "#": st.column_config.NumberColumn("#", format="%d"),
                    }
                    if "Data de criação" in tabela_full.columns:
                        cfg_full["Data de criação"] = st.column_config.DateColumn(
                            "Data de criação", format="DD/MM/YYYY"
                        )
                    if "Data do agendamento" in tabela_full.columns:
                        cfg_full["Data do agendamento"] = st.column_config.DateColumn(
                            "Data do agendamento", format="DD/MM/YYYY"
                        )
                    if "Data da venda" in tabela_full.columns:
                        cfg_full["Data da venda"] = st.column_config.DateColumn(
                            "Data da venda", format="DD/MM/YYYY"
                        )
                    if "Montante" in tabela_full.columns:
                        cfg_full["Montante"] = st.column_config.TextColumn(
                            "Montante"
                        )
                    if "Receita" in tabela_full.columns:
                        cfg_full["Receita"] = st.column_config.TextColumn(
                            "Receita"
                        )
                    st.dataframe(
                        tabela_full,
                        use_container_width=True,
                        hide_index=True,
                        column_config=cfg_full,
                    )

# ===========================================================================
# Indicadores por Pré-vendas — Oportunidades × Agendamentos × Conversão
# ===========================================================================
# Universo: deals criados no período (zoho_deals.created_at).
#   - Oportunidades = COUNT(DISTINCT deal_id) atribuídos ao SDR.
#   - Agendamentos  = COUNT(DISTINCT activity_id) Consulta/Indicação no
#     período (mesma janela das demais queries).
#   - Bucket exclusivo: +12 > -12 > Não atua > Sem classif, com a regra
#     combinada das 4 fontes (CRM + ext.leads).
#   - SDR resolvido pela cascata canônica (activity.prevendas > deal.sdr_ss).
#
# Filtra para SDRs do cadastro oficial (mesma regra do Top SDRs) e
# respeita os filtros globais SDR/Tipo SDR. Não bate com "Leads totais"
# porque o universo aqui é deal-criado-no-período e ainda exclui SDRs
# não oficiais — caption explica.
carregar_indicadores_oport = st.checkbox(
    "Carregar indicadores detalhados por Pré-vendas",
    value=False,
    key="prevendas_overview_carregar_indicadores_oport",
    help=(
        "Executa a consulta de oportunidades × agendamentos × conversão "
        "somente quando ativado."
    ),
)

if carregar_indicadores_oport:
    section_title(
        "Indicadores por Pré-vendas",
        "Oportunidades recebidas, agendamentos e conversão por classificação.",
    )

    try:
        df_oport_raw = get_prevendas_oportunidades_sdr(ctx.data_ini, ctx.data_fim)
    except Exception as e:
        st.error(f"Falha ao consultar oportunidades por SDR: {e}")
        df_oport_raw = pd.DataFrame()

    if df_oport_raw.empty:
        st.info("Sem oportunidades no período selecionado.")
    else:
        from src.prevendas_transforms import _canonical_official_name

        # 1) Mapear cada SDR cru pro nome oficial (mesma regra de
        #    prevendas_ranking_sdr_oficiais). Sem mapping → vazio → fica fora.
        if df_sdrs_oficiais is not None and not df_sdrs_oficiais.empty:
            official_names = [
                str(n).strip()
                for n in df_sdrs_oficiais["nome"].dropna().tolist()
                if str(n).strip()
            ]
        else:
            official_names = []

        df_oport = df_oport_raw.copy()
        if "comparecimentos" not in df_oport.columns:
            df_oport["comparecimentos"] = 0
        df_oport["sdr"] = df_oport["sdr"].astype(str)
        df_oport["sdr_oficial"] = df_oport["sdr"].apply(
            lambda nome: _canonical_official_name(nome, official_names)
        )
        df_oport = df_oport[df_oport["sdr_oficial"] != ""].copy()

        # Filtro de Funil de Origem (mesmo seletor que afeta Funil/Tendência).
        # Coluna `funil_origem` vem do GROUP BY da query —
        # `prevendas_oportunidades_sdr.sql` agrega por (sdr × classif × funil).
        if funil_origem_ativo and "funil_origem" in df_oport.columns:
            df_oport = df_oport[df_oport["funil_origem"].isin(funil_origem_sel)]

        if df_oport.empty:
            st.info(
                "Nenhuma oportunidade atribuída a SDR do cadastro oficial no "
                "período. Veja o Top SDRs acima — pode haver SDRs fora da "
                "composição oficial respondendo por essas oportunidades."
            )
        else:
            # 2) Pivotar (sdr × bucket) — 1 row por SDR com colunas por bucket
            #    para oportunidades, agendamentos e vendas (3 pivots paralelos).
            BUCKETS = ["+12", "-12", "Não atua", "Sem classif"]
            df_oport_g = (
                df_oport.groupby(["sdr_oficial", "classif_bucket"],
                                 as_index=False, dropna=False)
                        .agg(oport=("oportunidades", "sum"),
                             agend=("agendamentos", "sum"),
                             comp=("comparecimentos", "sum"),
                             vendas=("vendas", "sum"))
            )

            def _piv(col: str) -> pd.DataFrame:
                return (
                    df_oport_g.pivot_table(
                        index="sdr_oficial", columns="classif_bucket",
                        values=col, aggfunc="sum", fill_value=0,
                    ).reindex(columns=BUCKETS, fill_value=0)
                )

            piv_oport  = _piv("oport")
            piv_agend  = _piv("agend")
            piv_comp   = _piv("comp")
            piv_vendas = _piv("vendas")

            tabela = pd.DataFrame({
                "SDR / Pré-vendas":           piv_oport.index,
                "oport_total":                piv_oport.sum(axis=1).values,
                "oport_+12":                  piv_oport["+12"].values,
                "oport_-12":                  piv_oport["-12"].values,
                "oport_nao_atua":             piv_oport["Não atua"].values,
                "oport_sem_classif":          piv_oport["Sem classif"].values,
                "agend_+12":                  piv_agend["+12"].values,
                "agend_-12":                  piv_agend["-12"].values,
                "agend_nao_atua":             piv_agend["Não atua"].values,
                "agend_total":                piv_agend.sum(axis=1).values,
                "comp_+12":                   piv_comp["+12"].values,
                "comp_-12":                   piv_comp["-12"].values,
                "comp_nao_atua":              piv_comp["Não atua"].values,
                "comp_total":                 piv_comp.sum(axis=1).values,
                "vendas_+12":                 piv_vendas["+12"].values,
                "vendas_-12":                 piv_vendas["-12"].values,
                "vendas_nao_atua":            piv_vendas["Não atua"].values,
                "vendas_total":               piv_vendas.sum(axis=1).values,
            })

            # 3) Tipo SDR (para filtro global Tipo SDR).
            tabela["tipo_sdr"] = tabela["SDR / Pré-vendas"].apply(classify_sdr)

            # 4) Aplicar filtros globais (SDR / Tipo SDR).
            if sdr_sel_global:
                tabela = tabela[tabela["SDR / Pré-vendas"].isin(sdr_sel_global)]
            if tipo_sdr_sel_global:
                tabela = tabela[tabela["tipo_sdr"].isin(tipo_sdr_sel_global)]

            if tabela.empty:
                st.info("Sem SDRs no recorte dos filtros SDR / Tipo SDR.")
            else:
                # 5) Métricas Looker-style. Pré-calculadas pra usar tanto no
                #    modo "Percentuais" quanto nos totais do caption.
                #    % Agendamento  = Agend / Oport
                #    % Ag. +12      = Agend +12 / Oport +12
                #    % Ag. -12      = Agend -12 / Oport -12
                #    % Ag. Não atua = Agend Não atua / Oport Não atua
                #    % Conversão    = Vendas / Agendamentos       (padrão Looker)
                #    % Conv. +12    = Vendas +12 / Agend +12
                def _ratio(num, den):
                    return (num / den * 100.0) if den else None

                tabela["pct_agend"]          = tabela.apply(
                    lambda r: _ratio(r["agend_total"],   r["oport_total"]),    axis=1)
                tabela["pct_agend_+12"]      = tabela.apply(
                    lambda r: _ratio(r["agend_+12"],     r["oport_+12"]),      axis=1)
                tabela["pct_agend_-12"]      = tabela.apply(
                    lambda r: _ratio(r["agend_-12"],     r["oport_-12"]),      axis=1)
                tabela["pct_agend_nao_atua"] = tabela.apply(
                    lambda r: _ratio(r["agend_nao_atua"], r["oport_nao_atua"]), axis=1)
                tabela["pct_conversao"]      = tabela.apply(
                    lambda r: _ratio(r["vendas_total"],  r["agend_total"]),    axis=1)
                tabela["pct_conv_+12"]       = tabela.apply(
                    lambda r: _ratio(r["vendas_+12"],    r["agend_+12"]),      axis=1)

                tabela = tabela.sort_values(
                    "oport_total", ascending=False,
                ).reset_index(drop=True)

                # 6) Controles — modo de visualização + custo (só Números / híbrido).
                opcoes_view = ["Números", "Percentuais", "Números + Percentuais"]
                ctrl_modo, ctrl_custo = st.columns([2.2, 1.0], gap="medium")
                with ctrl_modo:
                    if hasattr(st, "segmented_control"):
                        modo_view = st.segmented_control(
                            "Visualizar indicadores como",
                            options=opcoes_view,
                            default="Números",
                            key="prevendas_overview_oport_modo",
                        )
                    else:
                        modo_view = st.radio(
                            "Visualizar indicadores como",
                            options=opcoes_view,
                            index=0,
                            horizontal=True,
                            key="prevendas_overview_oport_modo",
                        )
                with ctrl_custo:
                    if modo_view == "Percentuais":
                        mostrar_custo_oport = False
                        st.checkbox(
                            "Exibir custo ao lado do valor",
                            value=False,
                            disabled=True,
                            key="prevendas_overview_oport_show_cost",
                            help="Disponível nos modos Números e Números + Percentuais.",
                        )
                    else:
                        mostrar_custo_oport = st.checkbox(
                            "Exibir custo ao lado do valor",
                            value=False,
                            key="prevendas_overview_oport_show_cost",
                            help=(
                                "Investimento estimado por SDR = valor × custo "
                                "médio da métrica (investido ÷ total da coluna)."
                            ),
                        )

                if modo_view not in opcoes_view:
                    modo_view = "Números"

                custos_medios_oport = custos_medios_indicadores_oport(
                    tabela, _investido_total,
                )

                _sdr_col_cfg = st.column_config.TextColumn(
                    "SDR / Pré-vendas",
                    width=260,
                    pinned=True,
                    alignment="left",
                )
                _w_num = 145 if mostrar_custo_oport else 100
                _w_wide = 155 if mostrar_custo_oport else 125

                def _cfg_metrica(label: str, *, wide: bool = False):
                    w = _w_wide if wide else _w_num
                    if modo_view == "Números" and not mostrar_custo_oport:
                        return st.column_config.NumberColumn(
                            label, format="%d", width=w, alignment="center",
                        )
                    return st.column_config.TextColumn(
                        label, width=w, alignment="center",
                    )

                def _fmt_n_pct(n, denom) -> str:
                    """Formata 'N (P,P%)'. Denominador zero → só o número."""
                    try:
                        n_int = int(n) if pd.notna(n) else 0
                    except (TypeError, ValueError):
                        n_int = 0
                    if denom and denom > 0:
                        pct_val = n_int / float(denom) * 100.0
                        return f"{n_int} ({fmt_percent_br(pct_val)})"
                    return f"{n_int}"

                def _fmt_n_pct_cost(n, denom, label: str) -> str:
                    base = _fmt_n_pct(n, denom)
                    if not mostrar_custo_oport:
                        return base
                    try:
                        n_int = int(n) if pd.notna(n) else 0
                    except (TypeError, ValueError):
                        n_int = 0
                    if n_int <= 0:
                        return base
                    custo = custos_medios_oport.get(label, 0.0)
                    inv = investimento_estimado_sdr(n_int, custo)
                    if inv == "—":
                        return base
                    if "(" in base and base.endswith(")"):
                        num_part, pct_part = base.split(" (", 1)
                        return f"{num_part} ({inv}) ({pct_part}"
                    return f"{base} ({inv})"

                # Denominadores do modo híbrido (inalterados).
                _denom_hibrido: dict[str, pd.Series] = {
                    "Op. +12": tabela["oport_total"],
                    "Op. -12": tabela["oport_total"],
                    "Op. Não atua": tabela["oport_total"],
                    "Ag.": tabela["oport_total"],
                    "Ag. +12": tabela["oport_+12"],
                    "Ag. -12": tabela["oport_-12"],
                    "Ag. Não atua": tabela["oport_nao_atua"],
                    "Comp.": tabela["agend_total"],
                    "Comp. +12": tabela["agend_+12"],
                    "Comp. -12": tabela["agend_-12"],
                    "Comp. Não atua": tabela["agend_nao_atua"],
                    "Vendas": tabela["agend_total"],
                    "Vendas +12": tabela["agend_+12"],
                    "Vendas -12": tabela["agend_-12"],
                    "Vendas Não atua": tabela["agend_nao_atua"],
                }

                # 7) Renderização — colunas variam conforme `modo_view`.
                if modo_view == "Números":
                    dados: dict = {"SDR / Pré-vendas": tabela["SDR / Pré-vendas"]}
                    for label, col, wide in INDICADORES_OPORT_METRIC_COLS:
                        vals = tabela[col].fillna(0)
                        if mostrar_custo_oport:
                            custo = custos_medios_oport[label]
                            dados[label] = [
                                fmt_celula_indicador_com_custo(
                                    v, custo, show_cost=True,
                                )
                                for v in vals
                            ]
                        else:
                            dados[label] = vals.astype(int)
                    tabela_view = pd.DataFrame(dados)
                    column_config_oport = {
                        "SDR / Pré-vendas": _sdr_col_cfg,
                        **{
                            label: _cfg_metrica(label, wide=wide)
                            for label, _, wide in INDICADORES_OPORT_METRIC_COLS
                        },
                    }
                elif modo_view == "Percentuais":
                    tabela_view = _format_table_br(pd.DataFrame({
                        "SDR / Pré-vendas": tabela["SDR / Pré-vendas"],
                        "% Agendamento":    tabela["pct_agend"],
                        "% Ag. +12":        tabela["pct_agend_+12"],
                        "% Ag. -12":        tabela["pct_agend_-12"],
                        "% Ag. Não atua":   tabela["pct_agend_nao_atua"],
                        "% Conversão":      tabela["pct_conversao"],
                        "% Conversão +12":  tabela["pct_conv_+12"],
                    }))
                    _w_pct = 115
                    column_config_oport = {
                        "SDR / Pré-vendas": _sdr_col_cfg,
                        "% Agendamento": st.column_config.TextColumn(
                            "% Agendamento", width=_w_pct, alignment="center",
                        ),
                        "% Ag. +12": st.column_config.TextColumn(
                            "% Ag. +12", width=_w_pct, alignment="center",
                        ),
                        "% Ag. -12": st.column_config.TextColumn(
                            "% Ag. -12", width=_w_pct, alignment="center",
                        ),
                        "% Ag. Não atua": st.column_config.TextColumn(
                            "% Ag. Não atua", width=125, alignment="center",
                        ),
                        "% Conversão": st.column_config.TextColumn(
                            "% Conversão", width=_w_pct, alignment="center",
                        ),
                        "% Conversão +12": st.column_config.TextColumn(
                            "% Conversão +12", width=125, alignment="center",
                        ),
                    }
                else:  # "Números + Percentuais"
                    dados_h: dict = {"SDR / Pré-vendas": tabela["SDR / Pré-vendas"]}
                    for label, col, wide in INDICADORES_OPORT_METRIC_COLS:
                        vals = tabela[col].fillna(0)
                        if label == "Op.":
                            if mostrar_custo_oport:
                                dados_h[label] = [
                                    fmt_celula_indicador_com_custo(
                                        v, custos_medios_oport[label], show_cost=True,
                                    )
                                    for v in vals
                                ]
                            else:
                                dados_h[label] = vals.astype(int).astype(str)
                        else:
                            denom = _denom_hibrido[label]
                            dados_h[label] = [
                                _fmt_n_pct_cost(n, d, label)
                                for n, d in zip(vals, denom)
                            ]
                    tabela_view = pd.DataFrame(dados_h)
                    column_config_oport = {
                        "SDR / Pré-vendas": _sdr_col_cfg,
                        **{
                            label: _cfg_metrica(label, wide=wide)
                            for label, _, wide in INDICADORES_OPORT_METRIC_COLS
                        },
                    }

                st.dataframe(
                    tabela_view,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_config_oport,
                )

                # 7) Totais + caption explicativo.
                total_oport  = int(tabela["oport_total"].sum())
                total_agend  = int(tabela["agend_total"].sum())
                total_comp   = int(tabela["comp_total"].sum())
                total_vendas = int(tabela["vendas_total"].sum())
                pct_agend_g  = (total_agend  / total_oport  * 100.0) if total_oport  else 0.0
                pct_conv_g   = (total_vendas / total_agend  * 100.0) if total_agend  else 0.0
                st.caption(
                    f"**{int_br(len(tabela))} SDR(s)** · "
                    f"**{int_br(total_oport)} oport.** · "
                    f"**{int_br(total_agend)} agend.** · "
                    f"**{int_br(total_comp)} comp.** · "
                    f"**{int_br(total_vendas)} vendas** · "
                    f"% Agendamento **{fmt_percent_br(pct_agend_g)}** · "
                    f"% Conversão **{fmt_percent_br(pct_conv_g)}**. "
                    "**% Conversão = Vendas / Agendamentos** (padrão Looker). "
                    "Oportunidades = `zoho_deals` criados no período; "
                    "agendamentos = activities Consulta/Indicação no período; "
                    "comparecimentos = activities concluídas no período "
                    "(status Concluída/Concluído); "
                    "vendas = deals ganhos no período (stage Ganho · tipo "
                    "Novo cliente). SDR atribuído via cascata "
                    "`activity.prevendas > deal.sdr_ss`. Apenas SDRs do cadastro "
                    "oficial. Conversões com denominador zero ficam em branco."
                )

with st.expander("Ver dados do período (diário, semanal ou mensal)"):
    if df_diario.empty:
        st.caption("Sem dados diários no período.")
    else:
        # Controles locais — afetam SÓ esta tabela.
        f_gran, f_sdr, f_tipo = st.columns([1.3, 2, 2], gap="medium")

        with f_gran:
            granularidade = st.radio(
                "Visualizar por",
                options=["Dia", "Semana", "Mês"],
                index=0,
                horizontal=True,
                key="prevendas_overview_granularidade",
            )

        # Detalhe anotado com tipo_sdr — fonte das opções de filtro e da
        # recomposição da série diária quando algum filtro estiver ativo.
        df_det_norm_full = df_det_norm_global

        if df_det_norm_full is not None and not df_det_norm_full.empty:
            opcoes_sdr_local = sorted(
                df_det_norm_full["sdr_filtro"].dropna().astype(str).unique().tolist()
            )
            opcoes_tipo_sdr_local = sorted(
                df_det_norm_full["tipo_sdr_filtro"].dropna().astype(str).unique().tolist()
            )
            _origens_local = (
                df_det_norm_full["funil_origem_filtro"]
                .dropna().astype(str).unique().tolist()
                if "funil_origem_filtro" in df_det_norm_full.columns else []
            )
            opcoes_origem_local = (
                [o for o in ("VSL", "SE", "AG") if o in _origens_local]
                + sorted(o for o in _origens_local
                         if o not in ("VSL", "SE", "AG", "Sem origem"))
                + (["Sem origem"] if "Sem origem" in _origens_local else [])
            )
        else:
            opcoes_sdr_local = []
            opcoes_tipo_sdr_local = []
            opcoes_origem_local = []

        with f_sdr:
            sdrs_sel_local = st.multiselect(
                "SDR (filtra só esta tabela)",
                options=opcoes_sdr_local,
                default=[],
                placeholder="Todos",
                key="prevendas_overview_tabela_sdr",
            )
        with f_tipo:
            tipos_sel_local = st.multiselect(
                "Tipo SDR (filtra só esta tabela)",
                options=opcoes_tipo_sdr_local,
                default=[],
                placeholder="Todos",
                key="prevendas_overview_tabela_tipo_sdr",
            )

        # Filtro local de Funil de Origem — desacopla do filtro global da
        # seção (Funil/Tendência/Indicadores) pra permitir cruzes
        # diferentes nesta tabela.
        origens_sel_local = st.multiselect(
            "Funil de Origem (filtra só esta tabela)",
            options=opcoes_origem_local,
            default=[],
            placeholder="Todos",
            key="prevendas_overview_tabela_funil_origem",
        )

        filtro_local_ativo = bool(sdrs_sel_local or tipos_sel_local
                                  or origens_sel_local)
        if filtro_local_ativo and df_det_norm_full is not None and not df_det_norm_full.empty:
            # Filtros locais desacoplam dos globais — base é o df_diario
            # PURO, com filtro local aplicado.
            df_diario_expander = prevendas_diario_filtrado_por_sdr(
                df_det_norm_full,
                df_diario,
                sdrs_sel_local,
                tipos_sel_local,
                ctx.data_ini,
                ctx.data_fim,
                funis_origem_filtro=origens_sel_local,
            )
            st.caption(
                "⚙ Filtro local ativo (desacopla dos filtros globais do header) · "
                "**Leads / Leads +12 / Leads -12 não são afetados** pelos filtros "
                "de SDR/Tipo SDR/Funil de Origem (no momento do form ainda não há "
                "SDR nem origem atribuída ao lead). As demais métricas — "
                "Agendamentos, Comparecimentos, Vendas, Montante, Receita, Vencidas — "
                "refletem apenas o(s) SDR/Tipo SDR/Funil de Origem selecionado(s) aqui."
            )
        else:
            # Sem filtro local → respeita os filtros globais do header.
            df_diario_expander = df_diario_view

        tabela = prevendas_agregar_por_granularidade(df_diario_expander, granularidade)

        cols_map = [
            ("periodo", "Período"),
            # Leads
            ("leads", "Leads"),
            ("leads_mais_12", "Leads +12"),
            ("leads_menos_12", "Leads -12"),
            # Agendamentos (exibidos = bruto - vencidas)
            ("agendamentos_exibidos", "Agendamentos"),
            ("agendamentos_mais_12", "Agendamentos +12"),
            # Comparecimentos
            ("comparecimentos", "Comparecimentos"),
            ("comparecimentos_mais_12", "Comparecimentos +12"),
            # Vendas
            ("vendas", "Vendas"),
            ("vendas_mais_12", "Vendas +12"),
            # Conversões gerais
            ("pct_lead_agend", "% Lead → Agend."),
            ("pct_agend_comp", "% Agend. → Comp."),
            ("pct_comp_venda", "% Comp. → Venda"),
            # Conversões +12
            ("pct_lead_agend_12", "% Lead +12 → Agend. +12"),
            ("pct_agend_comp_12", "% Agend. +12 → Comp. +12"),
            ("pct_comp_venda_12", "% Comp. +12 → Venda +12"),
            # Financeiro
            ("montante", "Montante"),
            ("receita", "Receita"),
            ("ticket_medio", "Ticket médio"),
            ("vencidas", "Vencidas"),
        ]
        cols_presentes = [orig for orig, _ in cols_map if orig in tabela.columns]
        tabela = tabela[cols_presentes].rename(
            columns={orig: label for orig, label in cols_map if orig in cols_presentes}
        )
        tabela = _format_table_br(tabela)

        column_config = {
            "Período": st.column_config.TextColumn("Período"),
        }
        # Volumes (inteiros)
        for col_int in (
            "Leads", "Leads +12", "Leads -12",
            "Agendamentos", "Agendamentos +12",
            "Comparecimentos", "Comparecimentos +12",
            "Vendas", "Vendas +12", "Vencidas",
        ):
            if col_int in tabela.columns:
                column_config[col_int] = st.column_config.NumberColumn(
                    col_int, format="%d"
                )
        _txt_col = lambda label: st.column_config.TextColumn(label)  # noqa: E731
        for col_fmt in _TABLE_PCT_COLS + _TABLE_MONEY_COLS:
            if col_fmt in tabela.columns:
                column_config[col_fmt] = _txt_col(col_fmt)

        st.caption(
            "**Funil por período.** Volumes dedup por `activity_id` "
            "(Agendamentos/Comparecimentos/Vencidas) e `deal_id` (Vendas). "
            "**Agendamentos** = bruto − vencidas. **Recortes +12** usam regra "
            "combinada (4 fontes em OR): `zoho_deals.lead_classification`, "
            "`zoho_deals.qualificacao`, `zoho_deals.classificado_cal` e "
            "`ext_reconecta.leads.classificado`. Conversões = razão dos "
            "totais (não média das taxas diárias). Denominador 0 ⇒ 0,00%. "
            "Semana usa janela fixa 1-7 / 8-14 / 15-21 / 22-28 / 29-31."
        )
        st.dataframe(
            tabela,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )

with st.expander("Ver leads/agendamentos detalhados"):
    if df_detalhe_view.empty:
        if filtros_globais_ativos:
            st.caption(
                "Sem linhas detalhadas para a combinação de SDR/Tipo SDR "
                "selecionada no header."
            )
        else:
            st.caption("Sem linhas detalhadas no período.")
    else:
        tabela_det = df_detalhe_view.copy().sort_values(
            ["data_agendamento", "data_criacao", "data_venda", "deal_id", "activity_id"],
            na_position="last",
        ).reset_index(drop=True)

        def _series_or_default(col_name: str, default=""):
            if col_name in tabela_det.columns:
                return tabela_det[col_name]
            return pd.Series([default] * len(tabela_det), index=tabela_det.index)

        tabela_det["tipo_registro_base_filtro"] = (
            _series_or_default("tipo_registro_base", "Atividade")
            .fillna("Atividade")
            .astype(str)
            .str.strip()
            .replace("", "Atividade")
        )
        tabela_det["classificacao_filtro"] = (
            _series_or_default("classificacao", "")
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Sem classificação")
        )
        tabela_det["classificacao_crm_filtro"] = (
            _series_or_default("classificacao_crm", "")
            .fillna("")
            .astype(str)
            .str.strip()
        )
        tabela_det["sdr_filtro"] = (
            _series_or_default("sdr", "")
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Sem SDR")
        )
        tabela_det["closer_filtro"] = (
            _series_or_default("closer", "")
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Sem Closer")
        )
        tabela_det["status_filtro"] = (
            _series_or_default("status_reuniao", "")
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Sem status")
        )
        tabela_det["funil_origem_filtro"] = (
            _series_or_default("funil_origem", "Sem origem")
            .fillna("Sem origem")
            .astype(str)
            .str.strip()
            .replace("", "Sem origem")
        )
        tabela_det["nome_cliente_view"] = (
            _series_or_default("nome_cliente", "")
            .fillna("")
            .astype(str)
            .str.strip()
        )
        if "nome_deal" in tabela_det.columns:
            sem_nome = tabela_det["nome_cliente_view"] == ""
            tabela_det.loc[sem_nome, "nome_cliente_view"] = (
                tabela_det.loc[sem_nome, "nome_deal"]
                .fillna("")
                .astype(str)
                .str.strip()
            )

        def _build_date_options(series):
            datas = [
                dt.date()
                for dt in series.dropna().drop_duplicates().sort_values().tolist()
            ]
            return ["Todas"] + [data.strftime("%d/%m/%Y") for data in datas], datas

        def _date_mask(series, escolha, datas):
            if escolha == "Todas":
                return pd.Series(True, index=series.index)
            data_ref = next(
                data for data in datas if data.strftime("%d/%m/%Y") == escolha
            )
            return series.dt.date == data_ref

        opcoes_agendamento, datas_agendamento = _build_date_options(
            tabela_det["data_agendamento"]
        )
        opcoes_criacao, datas_criacao = _build_date_options(tabela_det["data_criacao"])
        opcoes_venda, datas_venda = _build_date_options(tabela_det["data_venda"])

        classif_unicas = tabela_det["classificacao_filtro"].drop_duplicates().tolist()
        classif_prioridade = [
            "Atua +12",
            "Atua -12",
            "Não atua",
            "Sem classificação",
        ]
        opcoes_classificacao = [
            valor for valor in classif_prioridade if valor in classif_unicas
        ] + sorted(valor for valor in classif_unicas if valor not in classif_prioridade)
        opcoes_sdr = sorted(tabela_det["sdr_filtro"].drop_duplicates().tolist())
        opcoes_closer = sorted(tabela_det["closer_filtro"].drop_duplicates().tolist())
        opcoes_status = sorted(tabela_det["status_filtro"].drop_duplicates().tolist())
        _origens_det = tabela_det["funil_origem_filtro"].drop_duplicates().tolist()
        opcoes_funil_origem_det = (
            [o for o in ("VSL", "SE", "AG") if o in _origens_det]
            + sorted(o for o in _origens_det
                     if o not in ("VSL", "SE", "AG", "Sem origem"))
            + (["Sem origem"] if "Sem origem" in _origens_det else [])
        )
        opcoes_tipos_registro = [
            "Agendamentos criados",
            "Agendamentos",
            "Agendamentos +12",
            "Agendamentos -12",
            "Comparecimentos",
            "Vendas",
            "Cancelados",
            "Vencidos",
        ]

        f1, f2, f3 = st.columns(3)
        with f1:
            data_agendamento_sel = st.selectbox(
                "Data do agendamento",
                options=opcoes_agendamento,
                index=0,
                key="prevendas_overview_detalhe_data_agendamento",
            )
        with f2:
            data_criacao_sel = st.selectbox(
                "Data de criação / Agend. criados",
                options=opcoes_criacao,
                index=0,
                key="prevendas_overview_detalhe_data_criacao",
            )
        with f3:
            data_venda_sel = st.selectbox(
                "Data da venda",
                options=opcoes_venda,
                index=0,
                key="prevendas_overview_detalhe_data_venda",
            )

        f4, f5, f6 = st.columns(3)
        with f4:
            tipo_registro_sel = st.multiselect(
                "Tipo de registro",
                options=opcoes_tipos_registro,
                default=[],
                key="prevendas_overview_detalhe_tipo_registro",
            )
        with f5:
            classif_sel = st.multiselect(
                "Classificação",
                options=opcoes_classificacao,
                default=[],
                key="prevendas_overview_detalhe_classificacao",
            )
        with f6:
            status_sel = st.multiselect(
                "Status reunião",
                options=opcoes_status,
                default=[],
                key="prevendas_overview_detalhe_status",
            )

        f7, f8, f9 = st.columns(3)
        with f7:
            sdr_sel = st.multiselect(
                "SDR",
                options=opcoes_sdr,
                default=[],
                key="prevendas_overview_detalhe_sdr",
            )
        with f8:
            closer_sel = st.multiselect(
                "Closer",
                options=opcoes_closer,
                default=[],
                key="prevendas_overview_detalhe_closer",
            )
        with f9:
            funil_origem_det_sel = st.multiselect(
                "Funil de Origem",
                options=opcoes_funil_origem_det,
                default=[],
                key="prevendas_overview_detalhe_funil_origem",
            )

        base_mask = pd.Series(True, index=tabela_det.index)
        if classif_sel:
            base_mask &= tabela_det["classificacao_filtro"].isin(classif_sel)
        if sdr_sel:
            base_mask &= tabela_det["sdr_filtro"].isin(sdr_sel)
        if closer_sel:
            base_mask &= tabela_det["closer_filtro"].isin(closer_sel)
        if status_sel:
            base_mask &= tabela_det["status_filtro"].isin(status_sel)
        if funil_origem_det_sel:
            base_mask &= tabela_det["funil_origem_filtro"].isin(funil_origem_det_sel)

        mask_data_agendamento = _date_mask(
            tabela_det["data_agendamento"], data_agendamento_sel, datas_agendamento
        )
        mask_data_criacao = _date_mask(
            tabela_det["data_criacao"], data_criacao_sel, datas_criacao
        )
        mask_data_venda = _date_mask(
            tabela_det["data_venda"], data_venda_sel, datas_venda
        )
        mask_atividade = tabela_det["tipo_registro_base_filtro"] == "Atividade"
        mask_venda = tabela_det["tipo_registro_base_filtro"] == "Venda"

        record_masks = {
            "Agendamentos criados": base_mask & mask_atividade & mask_data_criacao,
            "Agendamentos": base_mask & mask_atividade & mask_data_agendamento,
            "Agendamentos +12": (
                base_mask
                & mask_atividade
                & mask_data_agendamento
                & ((tabela_det["classificacao_crm_filtro"] == "Atua +12")
                   | (tabela_det["classificacao_filtro"]    == "Atua +12"))
            ),
            "Agendamentos -12": (
                base_mask
                & mask_atividade
                & mask_data_agendamento
                & ((tabela_det["classificacao_crm_filtro"] == "Atua -12")
                   | (tabela_det["classificacao_filtro"]    == "Atua -12"))
            ),
            "Comparecimentos": (
                base_mask
                & mask_atividade
                & mask_data_agendamento
                & tabela_det["status_filtro"].isin(["Concluída", "Concluído"])
            ),
            "Vendas": base_mask & mask_venda & mask_data_venda,
            "Cancelados": (
                base_mask
                & mask_atividade
                & mask_data_agendamento
                & tabela_det["status_filtro"].isin(["Cancelada", "Cancelado"])
            ),
            "Vencidos": (
                base_mask
                & mask_atividade
                & mask_data_agendamento
                & (tabela_det["status_filtro"] == "Vencida")
            ),
        }

        if tipo_registro_sel:
            final_mask = pd.Series(False, index=tabela_det.index)
            for tipo in tipo_registro_sel:
                final_mask |= record_masks[tipo]
        else:
            final_mask = base_mask & (
                (mask_atividade & mask_data_agendamento & mask_data_criacao)
                | (mask_venda & mask_data_venda)
            )

        tabela_det = tabela_det[final_mask].reset_index(drop=True)

        mask_criados = (
            (tabela_det["tipo_registro_base_filtro"] == "Atividade")
            & tabela_det["data_criacao"].notna()
        )
        mask_agendamentos = (
            (tabela_det["tipo_registro_base_filtro"] == "Atividade")
            & tabela_det["data_agendamento"].notna()
        )
        mask_mais_12 = mask_agendamentos & (
            (tabela_det["classificacao_crm_filtro"] == "Atua +12")
            | (tabela_det["classificacao_filtro"]    == "Atua +12")
        )
        mask_menos_12 = mask_agendamentos & (
            (tabela_det["classificacao_crm_filtro"] == "Atua -12")
            | (tabela_det["classificacao_filtro"]    == "Atua -12")
        )
        mask_comparecimentos = mask_agendamentos & (
            tabela_det["status_filtro"].isin(["Concluída", "Concluído"])
        )
        mask_vendas = (
            (tabela_det["tipo_registro_base_filtro"] == "Venda")
            & tabela_det["data_venda"].notna()
        )
        mask_vencidos = mask_agendamentos & (
            tabela_det["status_filtro"] == "Vencida"
        )
        mask_cancelados = mask_agendamentos & (
            tabela_det["status_filtro"].isin(["Cancelada", "Cancelado"])
        )

        st.caption("Resumo do recorte filtrado")
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Total de linhas", int_br(len(tabela_det)))
        s2.metric("Agend. criados", int_br(int(mask_criados.sum())))
        s3.metric("Agendamentos", int_br(int(mask_agendamentos.sum())))
        s4.metric("Comparecimentos", int_br(int(mask_comparecimentos.sum())))
        s5.metric("Vendas", int_br(int(mask_vendas.sum())))

        s6, s7, s8, s9 = st.columns(4)
        s6.metric("Agend. +12", int_br(int(mask_mais_12.sum())))
        s7.metric("Agend. -12", int_br(int(mask_menos_12.sum())))
        s8.metric("Cancelados", int_br(int(mask_cancelados.sum())))
        s9.metric("Vencidos", int_br(int(mask_vencidos.sum())))

        tabela_view = tabela_det.copy()
        tabela_view.insert(0, "#", range(1, len(tabela_view) + 1))

        cols_map_det = [
            ("#", "#"),
            ("tipo_registro_base_filtro", "Tipo base"),
            ("data_agendamento", "Data do agendamento"),
            ("data_criacao", "Data de criação"),
            ("data_venda", "Data da venda"),
            ("nome_cliente_view", "Nome do cliente/lead"),
            ("email_final_filtro",      "E-mail"),
            ("email_lead_filtro",       "E-mail (lead)"),
            ("email_crm_filtro",        "E-mail (CRM)"),
            ("classificacao_filtro", "Classif. (lead)"),
            ("classificacao_crm_filtro", "Classif. (CRM)"),
            ("status_filtro", "Status reunião"),
            ("origem_fonte", "Origem/fonte"),
            ("funil_origem_filtro", "Funil de Origem"),
            ("sdr_filtro", "SDR"),
            ("closer_filtro", "Closer"),
            ("montante", "Montante"),
            ("receita", "Receita"),
            ("deal_id", "ID do deal"),
            ("activity_id", "ID da activity"),
        ]
        cols_det_presentes = [
            orig for orig, _ in cols_map_det if orig in tabela_view.columns
        ]
        tabela_view = _format_table_br(
            tabela_view[cols_det_presentes].rename(
                columns={
                    orig: label
                    for orig, label in cols_map_det
                    if orig in cols_det_presentes
                }
            )
        )

        column_config_det = {
            "#": st.column_config.NumberColumn("#", format="%d"),
        }
        if "Data do agendamento" in tabela_view.columns:
            column_config_det["Data do agendamento"] = st.column_config.DateColumn(
                "Data do agendamento", format="DD/MM/YYYY"
            )
        if "Data de criação" in tabela_view.columns:
            column_config_det["Data de criação"] = st.column_config.DateColumn(
                "Data de criação", format="DD/MM/YYYY"
            )
        if "Data da venda" in tabela_view.columns:
            column_config_det["Data da venda"] = st.column_config.DateColumn(
                "Data da venda", format="DD/MM/YYYY"
            )
        if "Montante" in tabela_view.columns:
            column_config_det["Montante"] = st.column_config.TextColumn(
                "Montante"
            )
        if "Receita" in tabela_view.columns:
            column_config_det["Receita"] = st.column_config.TextColumn(
                "Receita"
            )

        st.caption(f"{len(tabela_view)} linha(s) no recorte exibido.")
        st.dataframe(
            tabela_view,
            use_container_width=True,
            hide_index=True,
            column_config=column_config_det,
        )

# ===========================================================================
# Cohort de agendamentos por dia de geração
# ===========================================================================
# Toggle Leads (default) vs Oportunidades. Linha por data de geração ·
# Colunas D0..D7 acumuladas (% do cohort que teve primeiro agendamento
# até D+n). Filtros globais SDR/Tipo SDR aplicados em Python.
carregar_cohort = st.checkbox(
    "Carregar análise de cohort",
    value=False,
    key="prevendas_overview_carregar_cohort",
    help=(
        "Executa a consulta de cohort de agendamentos somente quando ativado."
    ),
)
with st.expander(
    "Cohort de agendamentos por dia de geração", expanded=False
):
    if not carregar_cohort:
        st.info(
            "Ative **Carregar análise de cohort** acima para executar a "
            "consulta e exibir a tabela."
        )
    else:
        # Toggle de base — Leads = visão principal.
        base_opcoes = ["Leads", "Oportunidades"]
        if hasattr(st, "segmented_control"):
            cohort_base = st.segmented_control(
                "Base do cohort",
                options=base_opcoes,
                default="Leads",
                key="prevendas_overview_cohort_base",
            )
        else:
            cohort_base = st.radio(
                "Base do cohort",
                options=base_opcoes,
                index=0,
                horizontal=True,
                key="prevendas_overview_cohort_base",
            )
        if cohort_base not in base_opcoes:
            cohort_base = "Leads"

        # Carrega a fonte conforme escolha. Cada loader devolve grão "1 row
        # por unidade (lead-daily-distinct ou deal) com (data_geracao, sdr,
        # lag_dias)". Padronizamos as colunas para a lógica de pivot ser igual.
        try:
            if cohort_base == "Leads":
                df_cohort_raw = get_prevendas_cohort_leads(
                    ctx.data_ini, ctx.data_fim
                )
                data_col_origem = "data_lead"
                denom_label = "Leads"
            else:
                df_cohort_raw = get_prevendas_cohort_agendamentos(
                    ctx.data_ini, ctx.data_fim
                )
                data_col_origem = "data_geracao"
                denom_label = "Oportunidades"
        except Exception as e:
            st.error(f"Falha ao consultar cohort: {e}")
            df_cohort_raw = pd.DataFrame()
            data_col_origem = "data_lead"
            denom_label = "Leads"

        if df_cohort_raw.empty:
            st.info(f"Sem {denom_label.lower()} no período selecionado.")
        else:
            # Filtros globais SDR/Tipo SDR — mesma regra das demais seções.
            df_coh = df_cohort_raw.copy()
            df_coh["sdr"] = df_coh["sdr"].astype(str)
            df_coh["tipo_sdr"] = df_coh["sdr"].apply(classify_sdr)

            if sdr_sel_global:
                df_coh = df_coh[df_coh["sdr"].isin(sdr_sel_global)]
            if tipo_sdr_sel_global:
                df_coh = df_coh[df_coh["tipo_sdr"].isin(tipo_sdr_sel_global)]

            if df_coh.empty:
                st.info(
                    f"Sem {denom_label.lower()} no recorte dos filtros "
                    "SDR / Tipo SDR."
                )
            else:
                from datetime import date as _date_cls
                hoje = _date_cls.today()
                COHORT_DIAS = list(range(0, 8))  # D0..D7

                # Padroniza coluna de data — ambas as fontes ficam como `data_ref`.
                df_coh["data_ref"] = pd.to_datetime(
                    df_coh[data_col_origem]
                ).dt.date
                # Negativo → 0 (clip em D0). NaN (sem agendamento) → None.
                df_coh["lag_dias_eff"] = df_coh["lag_dias"].apply(
                    lambda v: int(max(v, 0)) if pd.notna(v) else None
                )

                # Por (data_ref): conta unidades e quantas agendaram até D_n.
                grupos = df_coh.groupby("data_ref", dropna=False)
                linhas = []
                for dt, g in grupos:
                    denom = len(g)
                    lags = g["lag_dias_eff"].dropna()
                    row = {"cohort_dt": dt, denom_label: denom}
                    idade_dias = (hoje - dt).days if isinstance(
                        dt, _date_cls) else None
                    for n in COHORT_DIAS:
                        if idade_dias is not None and idade_dias < n:
                            row[f"D{n}"] = None  # ainda não maturou
                        elif denom == 0:
                            row[f"D{n}"] = None
                        else:
                            row[f"D{n}"] = int((lags <= n).sum()) / denom * 100.0
                    linhas.append(row)

                cohort_df = pd.DataFrame(linhas).sort_values(
                    "cohort_dt", ascending=False
                ).reset_index(drop=True)

                # Overall — denominador ajustado por maturidade.
                total_uni = len(df_coh)
                overall = {"cohort_dt": None,
                           denom_label: total_uni,
                           "Cohort": "Overall"}
                for n in COHORT_DIAS:
                    maturos_mask = df_coh["data_ref"].apply(
                        lambda d: (hoje - d).days >= n
                                  if isinstance(d, _date_cls) else False
                    )
                    denom = int(maturos_mask.sum())
                    if denom == 0:
                        overall[f"D{n}"] = None
                    else:
                        num = int(
                            (df_coh.loc[maturos_mask, "lag_dias_eff"]
                                    .fillna(99999) <= n).sum()
                        )
                        overall[f"D{n}"] = num / denom * 100.0

                cohort_df["Cohort"] = cohort_df["cohort_dt"].apply(
                    lambda d: d.strftime("%d/%m") if isinstance(d, _date_cls) else "—"
                )

                cols_ordem = ["Cohort", denom_label] + [
                    f"D{n}" for n in COHORT_DIAS]
                cohort_view = pd.concat(
                    [pd.DataFrame([overall]), cohort_df],
                    ignore_index=True,
                )[cols_ordem]

                # ----- Formatação de percentual (pt-BR, 2 casas) -----
                # NaN / não maturado → "" (célula vazia). 0% → "0,00%" (não
                # confunde com vazio, recebe cor clara).
                def _fmt_pct(v):
                    if v is None or pd.isna(v):
                        return ""
                    return fmt_percent_br(v)

                # ----- Paleta azul progressiva (claro → escuro) -----
                # NaN → "" (fundo padrão escuro do dataframe).
                # 0% exato → azul quase branco (#EFF6FF).
                # Texto: quase-preto nas faixas claras, branco bold a partir
                # do azul médio (50%).
                def _bg_color(v):
                    if v is None or pd.isna(v):
                        return ""
                    if v == 0:
                        return "background-color: #EFF6FF; color: #0F172A"
                    if v <= 10:
                        return "background-color: #DBEAFE; color: #0F172A"
                    if v <= 20:
                        return "background-color: #BFDBFE; color: #0F172A"
                    if v <= 35:
                        return "background-color: #93C5FD; color: #0F172A"
                    if v <= 50:
                        return "background-color: #60A5FA; color: #0F172A"
                    if v <= 65:
                        return ("background-color: #3B82F6; color: #ffffff; "
                                "font-weight: 600")
                    if v <= 80:
                        return ("background-color: #2563EB; color: #ffffff; "
                                "font-weight: 600")
                    return ("background-color: #1D4ED8; color: #ffffff; "
                            "font-weight: 700")

                cols_pct = [f"D{n}" for n in COHORT_DIAS]

                # ----- Estratégia robusta: pré-formatar células em string -----
                # Algumas versões/contextos do Streamlit ignoram Styler.format
                # quando o subset cobre colunas de dtype 'object' com mistura
                # float/None. Para garantir que a célula renderize SEMPRE como
                # texto "6,83%" (e nunca como "6.831120"), formato as colunas
                # D_n diretamente para string no DataFrame de exibição. Mantém
                # `cohort_view` com valores numéricos para alimentar a paleta.
                cohort_display = cohort_view.copy()
                for c in cols_pct:
                    cohort_display[c] = cohort_view[c].apply(_fmt_pct)

                # Cor por célula puxando o valor NUMÉRICO de cohort_view via
                # DataFrame paralelo. `Styler.apply(axis=0)` recebe a Series
                # da coluna e devolve list[str] de CSS, uma por linha.
                def _color_col(s_display):
                    nums = cohort_view[s_display.name]
                    return [_bg_color(v) for v in nums]

                styler = (
                    cohort_display.style
                        .format({denom_label: "{:,.0f}".format})
                        .apply(_color_col, subset=cols_pct, axis=0)
                )

                st.caption(
                    "**Bases.** *Leads* = **todos os leads válidos** que entraram "
                    "no funil (daily-distinct por email, sem filtro de "
                    "classificação). *Oportunidades* = leads/deals classificados "
                    "como **Atua +12 ou Atua -12** (regra combinada das 4 fontes: "
                    "`lead_classification` / `qualificacao` / `classificado_cal` / "
                    "`ext.classificado`). **Não atua** e **sem classificação** "
                    "ficam fora da base Oportunidades."
                )
                st.caption(
                    f"**Como ler.** Linha = data de geração do {denom_label[:-1].lower() if denom_label.endswith('s') else denom_label.lower()}. "
                    "**D_n** = % daquele cohort que teve **primeiro agendamento "
                    "até D+n** (acumulado). Linha **Overall** consolida todos os "
                    "cohorts do período, com denominador ajustado por maturidade "
                    "(cohorts ainda não maturados não entram em D_n). Células "
                    "em branco = cohort ainda não maturou para esse D_n."
                )

                st.dataframe(
                    styler,
                    use_container_width=True,
                    hide_index=True,
                )

                if cohort_base == "Leads":
                    rodape = (
                        f"**{int_br(total_uni)} lead(s)** no recorte. "
                        "Universo: `ext_reconecta.leads` daily-distinct por "
                        "`(dia, email)` com filtros canônicos de e-mail teste/"
                        "interno. Lead pareado ao deal via cascata `zoho_id > "
                        "session_id > email`. Agendamento = `MIN(start_datetime)` "
                        "de activity Consulta/Indicação com `status_reuniao IS "
                        "NOT NULL`. Leads sem deal pareado ficam com `sdr = "
                        "'Sem SDR'` — saem do recorte quando o filtro de SDR "
                        "específico está ativo."
                    )
                else:
                    rodape = (
                        f"**{int_br(total_uni)} oportunidade(s)** no recorte. "
                        "Universo: `zoho_deals` criados no período **classificados "
                        "como Atua +12 ou Atua -12** pela regra combinada das 4 "
                        "fontes (CRM + ext.leads). Deals em **Não atua** ou **sem "
                        "classificação** ficam de fora. "
                        "Agendamento = 1ª activity Consulta/Indicação com "
                        "`status_reuniao IS NOT NULL`, deduplicada por "
                        "`activity_id`, ordenada por `start_datetime ASC`. "
                    "`lag_dias` negativos (agendamento datado antes do "
                    "deal) são tratados como D0."
                )
            st.caption(rodape)

st.caption(
    "**Regras canônicas (consistência entre cards, ranking e detalhe).** "
    "Base principal em `zoho_deals`, com `LEFT JOIN ext_reconecta.leads`. "
    "Activities ligadas via `what_id` normalizado, filtradas em "
    "`activity_type IN ('Consulta','Indicação')` com `status_reuniao IS NOT NULL`. "
    "**Contagens de activity** usam `COUNT(DISTINCT activity_id)` (neutraliza "
    "fan-out do JOIN com leads). **Agendamentos +12 / -12** usam regra "
    "combinada: `zoho_deals.lead_classification = 'Atua +12'` OR "
    "`ext_reconecta.leads.classificado = 'Atua +12'` (CRM é fonte preferencial; "
    "ext entra como fallback). **Vendas** = `COUNT(DISTINCT deal_id)` com "
    "`stage = 'Ganho'` e `tipo_venda = 'Novo cliente'`. **Leads totais** = "
    "soma diária de e-mails únicos no período (`ext_reconecta.leads`). "
    "Os filtros `SDR` / `Tipo SDR` aplicam ao ranking Top SDRs e à tabela "
    "de detalhamento; os cards do topo refletem o total do período."
)
