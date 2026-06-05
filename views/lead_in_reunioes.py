"""Time de Vendas — Lead In & Reuniões (v1 diagnóstica).

Painel operacional de consultas (`zoho_activities` · Consulta) com
quebra com/sem qualificação da pré. Não mistura com Churn ou pós-venda.
"""
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.lead_in_transforms import (
    AGENDA_BUCKET_CHART_COLORS,
    AGENDA_BUCKET_CHART_ORDER,
    AGENDA_CHART_STATUS_LABELS,
    AGENDA_STATUS_COLORS,
    LEAD_IN_AGENDA_OPCAO_TODO_PERIODO,
    LEAD_IN_DURACAO_PADRAO_MIN,
    SEM_PRE_IDENTIFICADA,
    TIPO_COM_PRE,
    TIPO_PRE_COM_MATCH,
    TIPO_PRE_SEM_MATCH,
    TIPO_SEM_PRE,
    LEAD_IN_CHURN_COL_HELP,
    LEAD_IN_CHURN_COL_LABEL,
    lead_in_agenda_bucket_chart_order,
    lead_in_agenda_chart_status_order,
    lead_in_agenda_datas_disponiveis,
    lead_in_agenda_now,
    lead_in_agenda_visualizar_opcoes,
    lead_in_agenda_diagnostico,
    lead_in_agenda_filtrar,
    lead_in_agenda_kpis,
    lead_in_agenda_kpis_historico,
    lead_in_agenda_periodo_inclui_hoje,
    lead_in_agenda_por_dia_pivot,
    lead_in_agenda_por_hora_pivot,
    lead_in_agenda_styler,
    lead_in_agenda_tabela,
    lead_in_aplicar_pre,
    lead_in_churn_agregar_por_pre,
    lead_in_churn_diagnostico,
    lead_in_churn_preparar,
    lead_in_diagnostico,
    lead_in_kpis,
    lead_in_matriz,
    lead_in_preparar_agenda,
    lead_in_ranking_closer_com_churn,
    lead_in_ranking_pre_com_churn,
    lead_in_resumo_closer_exibir,
    lead_in_resumo_pre_exibir,
    lead_in_resumo_styler,
    lead_in_tabela_detalhe,
)
from src.repositories import (
    get_executivas_churn_pos_venda,
    get_executivas_oficiais,
    get_lead_in_churn_deal_pre,
    get_lead_in_email_sdr_lookup,
    get_lead_in_reunioes_consultas,
    get_lead_in_reunioes_consultas_agenda,
    get_prevendas_sdrs_oficiais,
)
from src.transforms import (
    churn_pos_filtrar_periodo,
    executivas_churn_agregar_por_executiva,
)
from src.ui.charts import _base_layout, _style_axes
from src.ui.components import metric_card_v2, ranking_column_config, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, int_br, pct

ctx = start_page(
    title="Lead In & Reuniões",
    subtitle="Acompanhamento diário de reuniões, pré-vendas e autoagendamentos",
    right_text="v1 diagnóstica",
)

try:
    df_raw = get_lead_in_reunioes_consultas(ctx.data_ini, ctx.data_fim)
    df_pre = get_prevendas_sdrs_oficiais()
    df_email_sdr = get_lead_in_email_sdr_lookup(ctx.data_ini, ctx.data_fim)
    df_churn_all = get_executivas_churn_pos_venda()
    df_oficiais = get_executivas_oficiais()
    df_churn_deal_pre = get_lead_in_churn_deal_pre()
except Exception as e:
    st.error(f"Falha ao consultar Lead In & Reuniões: {e}")
    st.stop()

df_churn_period = churn_pos_filtrar_periodo(df_churn_all, ctx.data_ini, ctx.data_fim)
churn_por_executiva = executivas_churn_agregar_por_executiva(
    df_churn_period, df_oficiais,
)
df_churn_pre = lead_in_churn_preparar(
    df_churn_period, df_churn_deal_pre, df_pre, df_email_sdr,
)
churn_por_pre = lead_in_churn_agregar_por_pre(df_churn_pre)
churn_diag = lead_in_churn_diagnostico(
    df_churn_period, df_churn_pre, churn_por_executiva, churn_por_pre,
)

if df_raw.empty:
    st.warning("Sem consultas no período (activity_type = Consulta).")
    st.stop()

df = lead_in_aplicar_pre(df_raw, df_pre, df_email_sdr)
kpi = lead_in_kpis(df)
diag = lead_in_diagnostico(df, df_pre)

# ---------------------------------------------------------------------------
# Cards principais
# ---------------------------------------------------------------------------
section_title(
    "Resumo do período",
    f"data: COALESCE(start_datetime, created_time) · "
    f"com pré: {int_br(kpi['com_pre'])} · sem pré: {int_br(kpi['sem_pre'])} · "
    f"cascata email/SDR",
)

c1, c2, c3 = st.columns(3, gap="small")
with c1:
    metric_card_v2("Reuniões agendadas", int_br(kpi["agendadas"]),
                   hint="status → Agendada", accent=True)
with c2:
    metric_card_v2("Reuniões realizadas", int_br(kpi["realizadas"]),
                   hint="Concluída/Concluído (+ Realizada)")
with c3:
    metric_card_v2("Reuniões canceladas", int_br(kpi["canceladas"]),
                   hint="Cancelada/Cancelado")

c4, c5, c6 = st.columns(3, gap="small")
with c4:
    metric_card_v2(
        "Taxa de realização",
        pct(kpi["taxa_realizacao"]) if kpi["total"] else "—",
        hint="realizadas ÷ base operacional",
    )
with c5:
    metric_card_v2(
        "Taxa de cancelamento",
        pct(kpi["taxa_cancelamento"]) if kpi["total"] else "—",
        hint="canceladas ÷ base operacional",
    )
with c6:
    outros = kpi["outros"]
    metric_card_v2(
        "Outros status",
        int_br(outros) if outros else "—",
        hint="inclui status sem bucket oficial (ex.: reagendamento)",
    )

# ---------------------------------------------------------------------------
# Matriz status × tipo de qualificação
# ---------------------------------------------------------------------------
section_title(
    "Matriz principal",
    f"{TIPO_COM_PRE} vs {TIPO_SEM_PRE}",
)

matriz = lead_in_matriz(df)
st.dataframe(
    matriz,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Com qualificação da pré": st.column_config.NumberColumn(format="%d"),
        "Sem pré / autoagendamento": st.column_config.NumberColumn(format="%d"),
        "Total": st.column_config.NumberColumn(format="%d"),
    },
)

def _render_lead_in_agenda_content(
    df_ag: pd.DataFrame,
    data_ini,
    data_fim,
    ref_date_agenda,
    periodo_completo_agenda: bool,
    modo_historico: bool,
    *,
    autorefresh: bool = False,
) -> None:
    """Tabela, cards e gráfico da seção Agenda (dia ou histórico)."""
    agenda, ref_date, is_today, agenda_now, modo_historico, periodo_completo = (
        lead_in_preparar_agenda(
            df_ag,
            data_ini,
            data_fim,
            ref_date=ref_date_agenda,
            periodo_completo=periodo_completo_agenda,
            now=lead_in_agenda_now() if autorefresh else None,
        )
    )
    agenda_kpi = (
        lead_in_agenda_kpis_historico(agenda) if modo_historico else lead_in_agenda_kpis(agenda)
    )
    agenda_diag = lead_in_agenda_diagnostico(
        agenda,
        agenda_now,
        ref_date,
        is_today,
        modo_historico=modo_historico,
        periodo_completo=periodo_completo,
    )

    if modo_historico:
        if periodo_completo:
            st.caption(
                "Exibindo período completo · "
                "modo histórico (status do CRM em cada reunião)"
            )
        else:
            st.caption(
                f"Data exibida: {ref_date.strftime('%d/%m/%Y')} · "
                "modo histórico (status finais do CRM na data escolhida)"
            )
    elif autorefresh:
        st.caption(
            f"Última atualização: {agenda_now.strftime('%H:%M:%S')} · "
            f"atualização automática a cada 60s ({agenda_diag['timezone']})"
        )
    else:
        st.caption(
            f"Referência: {agenda_now.strftime('%d/%m/%Y %H:%M')} "
            f"({agenda_diag['timezone']}) · atualização automática a cada 60s"
        )

    if modo_historico:
        a1, a2, a3, a4, a5 = st.columns(5, gap="small")
        with a1:
            metric_card_v2(
                "Reuniões no período" if periodo_completo else "Reuniões do dia",
                int_br(agenda_kpi["total_dia"]),
                hint=(
                    "total no período selecionado"
                    if periodo_completo
                    else f"total em {ref_date.strftime('%d/%m/%Y')}"
                ),
                accent=True,
            )
        with a2:
            metric_card_v2("Agendadas", int_br(agenda_kpi["agendadas"]), hint="status → Agendada")
        with a3:
            metric_card_v2("Realizadas", int_br(agenda_kpi["realizadas"]), hint="Concluída/Realizada")
        with a4:
            metric_card_v2("Canceladas", int_br(agenda_kpi["canceladas"]), hint="Cancelada/Cancelado")
        with a5:
            metric_card_v2(
                "Outros status",
                int_br(agenda_kpi["outros"]) if agenda_kpi["outros"] else "—",
                hint="status fora dos buckets principais",
            )
    else:
        a1, a2, a3, a4, a5, a6 = st.columns(6, gap="small")
        with a1:
            metric_card_v2(
                "Próxima reunião",
                agenda_kpi.get("proxima_linha1", agenda_kpi["proxima_reuniao"]),
                breakdown=[("Closer", agenda_kpi.get("proxima_closer", "—"))],
                hint=agenda_kpi.get("proxima_tempo"),
                accent=True,
            )
        with a2:
            metric_card_v2(
                "Reuniões restantes hoje",
                int_br(agenda_kpi["restantes_hoje"]),
                hint="status temporal = Próxima",
            )
        with a3:
            metric_card_v2(
                "Em andamento agora",
                int_br(agenda_kpi["em_andamento"]),
                hint="dentro da janela da reunião",
            )
        with a4:
            metric_card_v2(
                "Aguardando atualização",
                int_br(agenda_kpi["aguardando"]),
                hint="passou do horário · CRM pendente",
            )
        with a5:
            metric_card_v2(
                "Concluídas hoje",
                int_br(agenda_kpi["concluidas_hoje"]),
                hint="Concluída/Concluído/Realizada",
            )
        with a6:
            metric_card_v2(
                "Canceladas hoje",
                int_br(agenda_kpi["canceladas_hoje"]),
                hint="Cancelada/Cancelado",
            )

    col_tab, col_chart = st.columns([1.8, 1.0], gap="large")

    with col_tab:
        visualizar_agenda = st.selectbox(
            "Visualizar agenda",
            options=lead_in_agenda_visualizar_opcoes(),
            index=0,
            key="lead_in_agenda_visualizar",
        )
        st.caption("Agenda do período" if periodo_completo else "Agenda do dia")
        agenda_tab = lead_in_agenda_filtrar(
            agenda, visualizar_agenda, modo_historico=modo_historico,
        )
        if agenda.empty:
            if modo_historico:
                if periodo_completo:
                    st.info("Nenhuma reunião no período selecionado.")
                else:
                    st.info(
                        f"Nenhuma reunião em {ref_date.strftime('%d/%m/%Y')} "
                        f"no período selecionado."
                    )
            else:
                st.info("Nenhuma reunião agendada para hoje no período selecionado.")
        elif agenda_tab.empty:
            _escopo = "período exibido" if periodo_completo else "dia exibido"
            st.info(f"Nenhuma reunião com filtro **{visualizar_agenda}** no {_escopo}.")
        else:
            _agenda_cols_map = [
                *(
                    [("data_reuniao_fmt", "Data da reunião")]
                    if periodo_completo
                    else []
                ),
                ("horario_reuniao", "Horário da reunião"),
                *([] if modo_historico else [("tempo_restante", "Tempo restante")]),
                ("nome_cliente", "Lead/cliente"),
                ("closer", "Closer"),
                ("pre_venda", "Pré-venda/SDR"),
                ("status_reuniao", "Status atual da reunião"),
                ("email", "Email"),
                ("telefone", "Telefone"),
                ("motivo_cancelamento", "Motivo cancelamento/não comparecimento"),
            ]
            agenda_raw = lead_in_agenda_tabela(
                agenda_tab,
                modo_historico=modo_historico,
                periodo_completo=periodo_completo,
            )
            _agenda_ok: list[str] = []
            _agenda_rename: dict[str, str] = {}
            _agenda_labels_seen: set[str] = set()
            for col, lbl in _agenda_cols_map:
                if col not in agenda_raw.columns or lbl in _agenda_labels_seen:
                    continue
                _agenda_ok.append(col)
                _agenda_labels_seen.add(lbl)
                _agenda_rename[col] = lbl
            agenda_display = agenda_raw[_agenda_ok].rename(columns=_agenda_rename)
            styled = lead_in_agenda_styler(agenda_display, agenda_tab, agenda_now)
            st.dataframe(styled, use_container_width=True, hide_index=True)

    with col_chart:
        if periodo_completo:
            st.caption("Distribuição das reuniões por dia")
            st.caption("status do CRM por data da reunião")
            chart_pivot = lead_in_agenda_por_dia_pivot(agenda)
            _chart_status_order = list(reversed(lead_in_agenda_bucket_chart_order()))
            _chart_colors = AGENDA_BUCKET_CHART_COLORS
            _chart_labels = {s: s for s in lead_in_agenda_bucket_chart_order()}
            _xaxis_title = "Data da reunião"
            _legend_rank = {
                s: i for i, s in enumerate(lead_in_agenda_bucket_chart_order())
            }
        else:
            st.caption("Distribuição das reuniões do dia por horário")
            if modo_historico and ref_date is not None:
                st.caption(f"status da data {ref_date.strftime('%d/%m/%Y')}")
            else:
                st.caption("status temporal da agenda em tempo real")
            chart_pivot = lead_in_agenda_por_hora_pivot(agenda)
            _chart_status_order = list(reversed(lead_in_agenda_chart_status_order()))
            _chart_colors = AGENDA_STATUS_COLORS
            _chart_labels = AGENDA_CHART_STATUS_LABELS
            _xaxis_title = "Horário"
            _legend_rank = {
                s: i for i, s in enumerate(lead_in_agenda_chart_status_order())
            }

        if chart_pivot.empty:
            st.info("Sem dados para o gráfico.")
        else:
            fig = go.Figure()
            for status in _chart_status_order:
                if status not in chart_pivot.columns:
                    continue
                vals = chart_pivot[status]
                fig.add_trace(
                    go.Bar(
                        name=_chart_labels.get(status, status),
                        x=chart_pivot.index.astype(str).tolist(),
                        y=vals.tolist(),
                        legendrank=_legend_rank.get(status, 99),
                        marker=dict(
                            color=_chart_colors.get(status, PALETTE["gold"]),
                            line=dict(color=PALETTE["border_strong"], width=0.5),
                        ),
                        text=[str(int(v)) if v > 0 else "" for v in vals],
                        textposition="inside",
                        insidetextanchor="middle",
                        hovertemplate=(
                            f"<b>%{{x}}</b><br>"
                            f"{_chart_labels.get(status, status)}"
                            ": %{{y}}<extra></extra>"
                        ),
                    )
                )
            fig.update_layout(**_base_layout(height=380))
            fig.update_layout(
                barmode="stack",
                bargap=0.35,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.08,
                    xanchor="left",
                    x=0,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(color=PALETTE["text_subtle"], size=10),
                    traceorder="normal",
                ),
                xaxis_title=_xaxis_title,
                yaxis_title="Reuniões",
                margin=dict(t=60, b=12, l=12, r=12),
            )
            _style_axes(fig)
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Agenda em tempo real / histórica
# ---------------------------------------------------------------------------
_modo_historico_agenda = not lead_in_agenda_periodo_inclui_hoje(
    ctx.data_ini, ctx.data_fim,
)
_periodo_completo_agenda = False
_ref_date_agenda = None
if _modo_historico_agenda:
    _datas_agenda = lead_in_agenda_datas_disponiveis(df, ctx.data_ini, ctx.data_fim)
else:
    _datas_agenda = []

hdr_l, hdr_r = st.columns([4, 1], gap="small")
with hdr_l:
    if _modo_historico_agenda:
        section_title(
            "Agenda histórica do período",
            f"duração padrão {LEAD_IN_DURACAO_PADRAO_MIN} min · status do CRM",
        )
    else:
        section_title(
            "Agenda em tempo real",
            f"reuniões de hoje · duração padrão {LEAD_IN_DURACAO_PADRAO_MIN} min",
        )
with hdr_r:
    st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
    if not _modo_historico_agenda:
        if st.button("Atualizar agora", key="lead_in_agenda_refresh", use_container_width=True):
            get_lead_in_reunioes_consultas.clear()
            get_lead_in_reunioes_consultas_agenda.clear()
            get_lead_in_email_sdr_lookup.clear()
            get_prevendas_sdrs_oficiais.clear()
            st.rerun()

if _modo_historico_agenda:
    _opcoes_agenda: list = [LEAD_IN_AGENDA_OPCAO_TODO_PERIODO, *_datas_agenda]
    _sel_agenda = st.selectbox(
        "Data da agenda",
        options=_opcoes_agenda,
        index=0,
        format_func=(
            lambda x: x
            if isinstance(x, str)
            else x.strftime("%d/%m/%Y")
        ),
        key="lead_in_agenda_data_hist",
    )
    _periodo_completo_agenda = _sel_agenda == LEAD_IN_AGENDA_OPCAO_TODO_PERIODO
    _ref_date_agenda = None if _periodo_completo_agenda else _sel_agenda
    if not _datas_agenda and _periodo_completo_agenda:
        st.caption("Nenhuma data com reuniões no período selecionado.")

if _modo_historico_agenda:
    _render_lead_in_agenda_content(
        df,
        ctx.data_ini,
        ctx.data_fim,
        _ref_date_agenda,
        _periodo_completo_agenda,
        modo_historico=True,
    )
else:

    @st.fragment(run_every=timedelta(seconds=60))
    def _lead_in_agenda_tempo_real_fragment() -> None:
        df_rt_raw = get_lead_in_reunioes_consultas_agenda(ctx.data_ini, ctx.data_fim)
        df_rt = lead_in_aplicar_pre(df_rt_raw, df_pre, df_email_sdr)
        _render_lead_in_agenda_content(
            df_rt,
            ctx.data_ini,
            ctx.data_fim,
            ref_date_agenda=None,
            periodo_completo_agenda=False,
            modo_historico=False,
            autorefresh=True,
        )

    _lead_in_agenda_tempo_real_fragment()

_agenda_diag_snap, ref_date, is_today, agenda_now, modo_historico, periodo_completo = (
    lead_in_preparar_agenda(
        df,
        ctx.data_ini,
        ctx.data_fim,
        ref_date=_ref_date_agenda if _modo_historico_agenda else None,
        periodo_completo=_periodo_completo_agenda if _modo_historico_agenda else False,
    )
)
agenda_diag = lead_in_agenda_diagnostico(
    _agenda_diag_snap,
    agenda_now,
    ref_date,
    is_today,
    modo_historico=modo_historico,
    periodo_completo=periodo_completo,
)

# ---------------------------------------------------------------------------
# Resumo por closer e pré-venda
# ---------------------------------------------------------------------------
section_title(
    "Desempenho por closer e pré-venda",
    "comparativo no período · pré identificada por cascata email/CRM",
)
st.caption(
    f"**{LEAD_IN_CHURN_COL_LABEL}** = clientes em stage = Churn · "
    "distinto de **Canceladas** (reunião cancelada no CRM)"
)

rank_closer = lead_in_ranking_closer_com_churn(df, df_churn_period, df_oficiais)
rank_pre = lead_in_ranking_pre_com_churn(
    df, df_churn_period, df_pre, df_email_sdr, df_churn_deal_pre,
)

rc1, rc2 = st.columns(2, gap="medium")

with rc1:
    st.caption("Por closer")
    if rank_closer.empty:
        st.info("Sem dados para resumo de closers.")
    else:
        closer_display = lead_in_resumo_closer_exibir(rank_closer)
        cfg_c = ranking_column_config(closer_display, pin_column="Closer")
        if LEAD_IN_CHURN_COL_LABEL in closer_display.columns:
            cfg_c[LEAD_IN_CHURN_COL_LABEL] = st.column_config.NumberColumn(
                LEAD_IN_CHURN_COL_LABEL,
                help=LEAD_IN_CHURN_COL_HELP,
                format="%d",
            )
        for col in ("% realização", "% cancelamento"):
            if col in closer_display.columns:
                cfg_c[col] = st.column_config.NumberColumn(format="%.2f%%")
        st.dataframe(
            lead_in_resumo_styler(closer_display, "Closer"),
            use_container_width=True,
            hide_index=True,
            column_config=cfg_c,
        )

with rc2:
    st.caption("Por pré-venda / SDR (com qualificação — cascata email/CRM)")
    if rank_pre.empty:
        st.info("Nenhuma SDR identificada no período (cascata activity → email → deal.sdr_ss).")
    else:
        pre_display = lead_in_resumo_pre_exibir(rank_pre)
        cfg_p = ranking_column_config(pre_display, pin_column="Pré-venda")
        if LEAD_IN_CHURN_COL_LABEL in pre_display.columns:
            cfg_p[LEAD_IN_CHURN_COL_LABEL] = st.column_config.NumberColumn(
                LEAD_IN_CHURN_COL_LABEL,
                help=LEAD_IN_CHURN_COL_HELP,
                format="%d",
            )
        if "% realização" in pre_display.columns:
            cfg_p["% realização"] = st.column_config.NumberColumn(format="%.2f%%")
        st.dataframe(
            lead_in_resumo_styler(pre_display, "Pré-venda"),
            use_container_width=True,
            hide_index=True,
            column_config=cfg_p,
        )

# ---------------------------------------------------------------------------
# Tabela detalhada
# ---------------------------------------------------------------------------
with st.expander("Ver detalhe linha a linha", expanded=False):
    st.caption("todas as consultas do período")

    det = lead_in_tabela_detalhe(df)
    cols_map = [
        ("data_reuniao", "Data da reunião"),
        ("nome_cliente", "Lead/cliente"),
        ("email", "Email"),
        ("telefone", "Telefone"),
        ("deal_id", "Deal ID"),
        ("closer", "Closer"),
        ("pre_venda_identificada", "Pré-venda/SDR identificada"),
        ("fonte_pre_venda", "Fonte da associação da pré"),
        ("data_vinculo_pre", "Data do vínculo com a pré"),
        ("status_reuniao", "Status da reunião"),
        ("status_bucket", "Status (painel)"),
        ("tipo_qualificacao", "Tipo: com pré / sem pré"),
        ("motivo_cancelamento", "Motivo cancelamento/não comparecimento"),
        ("data_criacao_agendamento", "Data criação do agendamento"),
        ("data_realizacao_ou_cancelamento", "Data realização/cancelamento"),
        ("activity_id", "Activity ID"),
    ]
    cols_ok: list[str] = []
    labels_seen: set[str] = set()
    rename_map: dict[str, str] = {}
    for col, lbl in cols_map:
        if col not in det.columns or lbl in labels_seen:
            continue
        cols_ok.append(col)
        labels_seen.add(lbl)
        rename_map[col] = lbl
    tabela = det[cols_ok].rename(columns=rename_map)
    tabela = tabela.loc[:, ~tabela.columns.duplicated()].copy()
    cfg_det = {}
    for col_d in ("Data da reunião",):
        if col_d in tabela.columns:
            cfg_det[col_d] = st.column_config.DateColumn(format="DD/MM/YYYY")
    for col_dt in (
        "Data criação do agendamento",
        "Data realização/cancelamento",
        "Data do vínculo com a pré",
    ):
        if col_dt in tabela.columns:
            cfg_det[col_dt] = st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")
    st.dataframe(
        tabela,
        use_container_width=True,
        hide_index=True,
        column_config=cfg_det,
    )

# ---------------------------------------------------------------------------
# Validação das regras e origem dos dados
# ---------------------------------------------------------------------------
with st.expander("Validação das regras e origem dos dados", expanded=False):
    st.markdown("#### Regra atual (painel principal — cascata)")
    st.markdown(
        f"- **Total de consultas:** {int_br(diag['total_consultas'])}\n"
        f"- **{TIPO_COM_PRE}:** **{int_br(diag['com_qualificacao_pre'])}**\n"
        f"- **{TIPO_SEM_PRE}:** **{int_br(diag['sem_qualificacao_pre'])}**\n"
        f"- **Soma com + sem:** **{int_br(diag['com_qualificacao_pre'] + diag['sem_qualificacao_pre'])}** "
        f"({'✓ bate total' if diag['com_qualificacao_pre'] + diag['sem_qualificacao_pre'] == diag['total_consultas'] else '⚠'})\n"
        f"- **Cadastro pré:** "
        f"{'OK · ' + str(diag['n_cadastro']) + ' nomes' if diag['cadastro_ok'] else 'indisponível'}"
    )
    st.caption(
        "Prioridade: `activity.prevendas` (match cadastro) → associação por "
        "`email_norm` (base SLA/leads repassados) → `deal.sdr_ss` → "
        f"`{SEM_PRE_IDENTIFICADA}`."
    )

    st.markdown("#### Associação da pré por fonte")
    st.markdown(
        f"- **Reuniões com e-mail encontrado:** {int_br(diag['com_email'])}\n"
        f"- **SDR via `activity.prevendas`:** {int_br(diag['sdr_via_activity'])}\n"
        f"- **SDR via associação por e-mail:** {int_br(diag['sdr_via_email'])}\n"
        f"- **SDR via `deal.sdr_ss`:** {int_br(diag['sdr_via_deal_ss'])}\n"
        f"- **Sem SDR identificada:** {int_br(diag['sem_sdr'])}\n"
        f"- **`activity.prevendas` preenchido (legado):** {int_br(diag['com_pre_campo'])}"
    )
    if not diag.get("fonte_pre_venda_dist", pd.DataFrame()).empty:
        st.caption("Distribuição `fonte_pre_venda`:")
        st.dataframe(
            diag["fonte_pre_venda_dist"],
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("#### Proposta de classificação (3 tiers — só diagnóstico)")
    st.markdown(
        f"- **{TIPO_PRE_COM_MATCH}:** {int_br(diag['pre_com_match'])}\n"
        f"- **{TIPO_PRE_SEM_MATCH}:** {int_br(diag['pre_sem_match'])} "
        f"({pct(diag['pct_ruido_pre'])} dos casos com campo pré preenchido)\n"
        f"- **`{SEM_PRE_IDENTIFICADA}`:** {int_br(diag['sem_pre_identificada'])}"
    )
    if diag["alerta_ruido_pre"]:
        st.warning(
            f"Há {int_br(diag['pre_sem_match'])} consultas com `activity.prevendas` "
            f"sem match no cadastro ({pct(diag['pct_ruido_pre'])} do campo preenchido). "
            "Revise a auditoria abaixo antes de oficializar a regra."
        )
    else:
        st.caption(
            "Ruído no campo pré dentro do esperado para v1 "
            f"(limiar de alerta: {pct(15.0)} sem match entre os preenchidos)."
        )

    if not diag["tipo_pre_dist"].empty:
        st.caption("Distribuição das 3 categorias de pré:")
        st.dataframe(diag["tipo_pre_dist"], hide_index=True, use_container_width=True)

    if not diag["matriz_pre_tiers"].empty:
        st.caption("Matriz status × 3 tiers (proposta):")
        st.dataframe(diag["matriz_pre_tiers"], hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### 1. Distribuição `status_reuniao` (CRM → bucket painel)")
    if not diag["status_dist"].empty:
        st.dataframe(diag["status_dist"], hide_index=True, use_container_width=True)
    else:
        st.caption("Sem dados de status.")

    outros_n = kpi["outros"]
    if outros_n:
        st.markdown(
            f"#### 2. Status classificados como **Outros** ({int_br(outros_n)})"
        )
        if not diag["status_outros"].empty:
            st.dataframe(diag["status_outros"], hide_index=True, use_container_width=True)
            st.caption(
                "Valores como *Vencida* permanecem fora dos 4 buckets até "
                "confirmação com a operação. Mapeamento v1 já cobre variações "
                "de Concluída, Cancelada e Agendada por substring."
            )
        else:
            st.caption("Nenhum detalhe adicional.")
    else:
        st.caption("**Outros status:** nenhum no período — mapa v1 cobre todos os valores.")

    st.markdown("---")
    st.markdown("#### 3. Fonte / identificação da pré")
    if not diag["fonte_pre_dist"].empty:
        st.dataframe(diag["fonte_pre_dist"], hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown(
        "#### 4. Auditoria `activity.prevendas` × "
        "`fdw_reconecta.executivas_pre_vendas`"
    )
    if not diag["audit_pre"].empty:
        st.caption("Todos os valores distintos no CRM (com campo pré preenchido):")
        st.dataframe(diag["audit_pre"], hide_index=True, use_container_width=True)
    else:
        st.caption("Nenhum valor em `activity.prevendas` no período.")

    ac1, ac2 = st.columns(2, gap="medium")
    with ac1:
        st.caption("Valores **sem match** no cadastro:")
        if not diag["pre_sem_match_vals"].empty:
            st.dataframe(
                diag["pre_sem_match_vals"],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("Nenhum — todos os valores batem com o cadastro.")
    with ac2:
        st.caption("Nomes do cadastro **não vistos** no CRM:")
        if not diag["cadastro_nao_usado"].empty:
            st.dataframe(
                diag["cadastro_nao_usado"],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("Todos os nomes do cadastro aparecem no período.")

    st.markdown("---")
    st.markdown("#### 5. Amostras de casos")
    sa1, sa2 = st.columns(2, gap="medium")
    with sa1:
        st.caption(f"Com `activity.prevendas` ({int_br(diag['com_pre_campo'])} no período):")
        if not diag["amostra_com_pre"].empty:
            st.dataframe(diag["amostra_com_pre"], hide_index=True, use_container_width=True)
        else:
            st.caption("Sem casos.")
    with sa2:
        st.caption(f"Sem qualificação da pré ({int_br(diag['sem_qualificacao_pre'])} no período):")
        if not diag["amostra_sem_pre"].empty:
            st.dataframe(diag["amostra_sem_pre"], hide_index=True, use_container_width=True)
        else:
            st.caption("Sem casos.")

    st.caption(f"Amostra sem SDR identificada ({int_br(diag['sem_sdr'])} no período):")
    if not diag["amostra_sem_sdr"].empty:
        st.dataframe(diag["amostra_sem_sdr"], hide_index=True, use_container_width=True)
    else:
        st.caption("Todas as reuniões têm SDR identificada.")

    st.markdown("---")
    st.markdown("#### 6. Clientes cancelados (deals `stage = Churn`)")
    st.caption(
        "Métrica de cliente/deal — distinta de **Reuniões canceladas** "
        "(status da consulta). Data: `data_churn` (stage_modified_time → "
        "modified_time → data_hora_compra)."
    )
    st.markdown(
        f"- **Total no período:** {int_br(churn_diag['total'])}\n"
        f"- **Soma por closer (ranking):** {int_br(churn_diag['por_closer_soma'])} "
        f"({'✓ bate total' if churn_diag['por_closer_soma'] == churn_diag['total'] else '⚠ revisar match de nomes'})\n"
        f"- **Soma por pré/SDR (cascata):** {int_br(churn_diag['por_pre_soma'])} "
        f"({'✓ bate total' if churn_diag['por_pre_soma'] == churn_diag['total'] else '⚠'})\n"
        f"- **Sem pré identificada:** {int_br(churn_diag['sem_pre_identificada'])}"
    )
    if not churn_diag.get("churn_por_executiva", pd.DataFrame()).empty:
        st.caption("Por closer (mesma base Executivas & Visão Geral):")
        st.dataframe(
            churn_diag["churn_por_executiva"].rename(
                columns={"executiva": "Closer", "churn": "Clientes Cancelados"},
            ),
            hide_index=True,
            use_container_width=True,
        )
    if not churn_diag.get("churn_por_pre", pd.DataFrame()).empty:
        st.caption("Por pré-venda/SDR (cascata email → deal.sdr_ss → activity.prevendas):")
        st.dataframe(
            churn_diag["churn_por_pre"].rename(
                columns={"pre_venda": "Pré-venda", "churn": "Clientes Cancelados"},
            ),
            hide_index=True,
            use_container_width=True,
        )
    if not churn_diag.get("fonte_pre_dist", pd.DataFrame()).empty:
        st.caption("Fonte da associação pré nos churns:")
        st.dataframe(
            churn_diag["fonte_pre_dist"],
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown(
        "#### 7. Agenda "
        + ("histórica do período" if agenda_diag.get("modo_historico") else "em tempo real")
    )
    if agenda_diag.get("modo_historico"):
        _data_diag = (
            "todo o período selecionado"
            if agenda_diag.get("periodo_completo")
            else ref_date.strftime("%d/%m/%Y")
        )
        st.markdown(
            f"- **Modo:** histórico (período sem data atual)\n"
            f"- **Data exibida:** {_data_diag}\n"
            f"- **Duração estimada:** {agenda_diag['duracao_padrao_min']} min "
            f"(quando `end_datetime` ausente)\n"
            f"- **Total no dia:** {int_br(agenda_diag['total_dia'])}\n"
            f"- **Aguardando atualização (CRM):** {int_br(agenda_diag['aguardando'])}\n"
            f"- **Finalizadas (concl./cancel./reag.):** {int_br(agenda_diag['finalizadas'])}"
        )
    else:
        st.markdown(
            f"- **Now do app:** {agenda_now.strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"- **Timezone:** {agenda_diag['timezone']}\n"
            f"- **Dia exibido:** {ref_date.strftime('%d/%m/%Y')} (hoje)\n"
            f"- **Duração estimada:** {agenda_diag['duracao_padrao_min']} min "
            f"(quando `end_datetime` ausente)\n"
            f"- **Total no dia:** {int_br(agenda_diag['total_dia'])}\n"
            f"- **Futuras (Próxima):** {int_br(agenda_diag['futuras'])}\n"
            f"- **Em andamento:** {int_br(agenda_diag['em_andamento'])}\n"
            f"- **Aguardando atualização:** {int_br(agenda_diag['aguardando'])}\n"
            f"- **Finalizadas (concl./cancel./reag.):** {int_br(agenda_diag['finalizadas'])}"
        )
