"""Pré-vendas — SDRs & Times.

Ranking individual + consolidação por tipo (Pré-vendas / Social Seller /
SDR não classificado / Sem SDR). Classificação canônica reutilizada
de `team_classification.classify_sdr` (mesma usada em SDR × Closer
do Time de Vendas)."""
import streamlit as st

from src.prevendas_transforms import (
    HINT_COM_PRE,
    HINT_NAO_QUALIF,
    HINT_PRE_MAIS_NAO_QUAL,
    QUALIF_LEGENDA_ABA,
    prevendas_anotar_sdr,
    prevendas_detalhe_sdr_por_fonte,
    prevendas_overview_kpis,
    prevendas_por_tipo,
    prevendas_qualif_chart_agendamentos,
    prevendas_qualif_chart_comparecimentos,
    prevendas_qualif_comparecimento_kpis,
    prevendas_qualif_comparecimento_por_sdr,
    prevendas_qualif_detalhe_pre_mais_nao_qual,
    prevendas_qualif_resumo_splits,
    prevendas_ranking_sdr,
)
from src.repositories import (
    get_prevendas_leads_detalhe_diario,
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
    get_prevendas_qualif_comparecimento,
    get_prevendas_sdrs_oficiais,
)
from src.ui.charts import bar_qualif_pre_split, bar_simple
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.prevendas_components import render_top_sdr_interativo
from src.ui.theme import brl, int_br, pct

ctx = start_page(
    title="SDRs & Times",
    subtitle="Ranking por SDR e consolidação por tipo de SDR",
    filters=["sdr", "tipo_sdr"],
)

try:
    df_sdr           = get_prevendas_por_sdr(ctx.data_ini, ctx.data_fim)
    df_diario        = get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim)
    df_detalhe       = get_prevendas_leads_detalhe_diario(ctx.data_ini, ctx.data_fim)
    df_qualif        = get_prevendas_qualif_comparecimento(ctx.data_ini, ctx.data_fim)
    df_sdrs_oficiais = get_prevendas_sdrs_oficiais()
except Exception as e:
    st.error(f"Falha ao consultar Pré-vendas: {e}")
    st.stop()

# Aplica filtros do header (sdr e tipo_sdr) — anota tipo antes pra que o
# filtro de tipo funcione mesmo no df_sdr (que originalmente não tem essa
# coluna).
df_sdr_anotado = prevendas_anotar_sdr(df_sdr)
df_sdr_filt = ctx.apply_filters(df_sdr_anotado,
                                {"sdr": "sdr", "tipo_sdr": "tipo_sdr"})

df_qualif_anotado = prevendas_anotar_sdr(df_qualif)
df_qualif_filt = ctx.apply_filters(
    df_qualif_anotado,
    {"sdr": "sdr", "tipo_sdr": "tipo_sdr"},
)

k = prevendas_overview_kpis(df_diario)
_splits_resumo = prevendas_qualif_resumo_splits(df_qualif)

# ---------------------------------------------------------------------------
# Resumo do período (totais, sem filtro fino — referência cross-SDR)
# ---------------------------------------------------------------------------
section_title("Resumo do período")

c1, c2, c3, c4, c5, c6, c7 = st.columns(7, gap="small")
with c1:
    metric_card_v2("Leads", int_br(k["leads"]), accent=True,
                   hint="cross-SDR · referência")
with c2:
    metric_card_v2(
        "Agendamentos",
        int_br(k["agendamentos"]),
        hint="período · activities Consulta/Indicação",
        qual_split=_splits_resumo["agend"],
    )
with c3:
    metric_card_v2(
        "Comparecimentos",
        int_br(k["comparecimentos"]),
        hint="status_reuniao = 'Concluída'",
        qual_split=_splits_resumo["comparec"],
    )
with c4:
    metric_card_v2("Vendas novas", int_br(k["vendas_novas"]),
                   hint="tipo_venda = 'Novo cliente'")
with c5:
    metric_card_v2("Conversão", pct(k["taxa_lead_venda_nova"]),
                   hint="vendas novas ÷ leads")
with c6:
    metric_card_v2("Ticket médio",
                   brl(k["ticket_medio"]) if k["ticket_medio"] else "—",
                   hint="montante ÷ vendas novas")
with c7:
    metric_card_v2("Montante",
                   brl(k["montante"]) if k["montante"] else "—",
                   hint="SUM(amount) das vendas atribuídas")

st.caption(f"{HINT_COM_PRE} · {HINT_NAO_QUALIF}")

# ---------------------------------------------------------------------------
# Tabs — Ranking SDR / Por tipo / Evolução / Qualificação
# ---------------------------------------------------------------------------
tab_rank, tab_tipo, tab_temp, tab_qualif = st.tabs([
    "Ranking SDR",
    "Por tipo de SDR",
    "Evolução",
    "Qualificação & Comparecimento",
])

with tab_rank:
    render_top_sdr_interativo(
        df_sdr_filt=df_sdr_filt,
        df_sdrs_oficiais=df_sdrs_oficiais,
        df_detalhe=df_detalhe,
        metric_options={
            "Agendamentos":         "agendamentos",
            "Agendamentos +12":     "agendamentos_mais_12",
            "Agendamentos -12":     "agendamentos_menos_12",
            "Comparecimentos":      "comparecimentos",
            "Vendas":               "vendas",
            "Cancelados":           "cancelados",
            "Vencidos":             "vencidos",
        },
        default_metric_label="Agendamentos",
        data_ini=ctx.data_ini,
        data_fim=ctx.data_fim,
        key_prefix="prevendas_sdrs_times",
        section_title_text="Ranking por SDR",
    )

    ranking_bruto = prevendas_ranking_sdr(df_sdr_filt)
    if not ranking_bruto.empty:
        with st.expander("Tabela completa (consolidado por SDR — bruto)"):
            st.dataframe(
                ranking_bruto, use_container_width=True, hide_index=True,
                column_config={
                    "sdr": "SDR",
                    "tipo_sdr": "Tipo",
                    "fonte_sdr": st.column_config.TextColumn(
                        "Fonte SDR",
                        help="Caminho do COALESCE que creditou o SDR: "
                             "`activity.prevendas` (preferida), `deal.sdr_ss` "
                             "(fallback) ou ambas."),
                    "agendamentos": st.column_config.NumberColumn(
                        "Agend.", format="%d"),
                    "comparecimentos": st.column_config.NumberColumn(
                        "Compar.", format="%d"),
                    "cancelamentos": st.column_config.NumberColumn(
                        "Cancel.", format="%d"),
                    "vendas": st.column_config.NumberColumn(
                        "Vendas", format="%d"),
                    "vendas_novas": st.column_config.NumberColumn(
                        "Vendas novas", format="%d"),
                    "montante": st.column_config.NumberColumn(
                        "Montante", format="R$ %.0f"),
                    "receita": st.column_config.NumberColumn(
                        "Receita", format="R$ %.0f"),
                    "taxa_comparecimento": st.column_config.NumberColumn(
                        "% Compar.", format="%.1f%%"),
                    "taxa_lead_venda": st.column_config.NumberColumn(
                        "% Venda nova", format="%.1f%%"),
                    "ticket_medio": st.column_config.NumberColumn(
                        "Ticket médio", format="R$ %.0f"),
                },
            )

        with st.expander("Auditoria: detalhe por (SDR, fonte)"):
            st.caption(
                "Linhas separadas por origem do crédito do SDR. Útil pra "
                "ver quanto da operação está vindo do **fallback** "
                "`deal.sdr_ss` (deveria ser pequeno; alto = problema de "
                "preenchimento de `activity.prevendas` no Zoho)."
            )
            detalhe = prevendas_detalhe_sdr_por_fonte(df_sdr_filt)
            if detalhe is None or detalhe.empty:
                st.caption("Sem dados.")
            else:
                st.dataframe(
                    detalhe, use_container_width=True, hide_index=True,
                    column_config={
                        "sdr": "SDR",
                        "tipo_sdr": "Tipo",
                        "fonte_sdr": "Fonte SDR",
                        "agendamentos": st.column_config.NumberColumn(
                            "Agend.", format="%d"),
                        "comparecimentos": st.column_config.NumberColumn(
                            "Compar.", format="%d"),
                        "cancelamentos": st.column_config.NumberColumn(
                            "Cancel.", format="%d"),
                        "vendas": st.column_config.NumberColumn(
                            "Vendas", format="%d"),
                        "vendas_novas": st.column_config.NumberColumn(
                            "Vendas novas", format="%d"),
                        "montante": st.column_config.NumberColumn(
                            "Montante", format="R$ %.0f"),
                        "receita": st.column_config.NumberColumn(
                            "Receita", format="R$ %.0f"),
                        "taxa_comparecimento": st.column_config.NumberColumn(
                            "% Compar.", format="%.1f%%"),
                    },
                )

with tab_tipo:
    section_title("Consolidação por tipo de SDR",
                  "Pré-vendas · Social Seller · SDR não classificado · Sem SDR")
    por_tipo = prevendas_por_tipo(df_sdr_filt)
    if por_tipo.empty:
        st.info("Sem dados.")
    else:
        cgr1, cgr2 = st.columns(2, gap="large")
        with cgr1:
            st.plotly_chart(
                bar_simple(por_tipo, x="tipo_sdr", y="vendas_novas",
                           height=300, rotate_x=True),
                use_container_width=True,
            )
        with cgr2:
            st.plotly_chart(
                bar_simple(por_tipo, x="tipo_sdr", y="comparecimentos",
                           height=300, rotate_x=True),
                use_container_width=True,
            )
        with st.expander("Tabela detalhada por tipo"):
            st.dataframe(
                por_tipo, use_container_width=True, hide_index=True,
                column_config={
                    "tipo_sdr": "Tipo",
                    "agendamentos": st.column_config.NumberColumn(
                        "Agend.", format="%d"),
                    "comparecimentos": st.column_config.NumberColumn(
                        "Compar.", format="%d"),
                    "cancelamentos": st.column_config.NumberColumn(
                        "Cancel.", format="%d"),
                    "vendas": st.column_config.NumberColumn(
                        "Vendas", format="%d"),
                    "vendas_novas": st.column_config.NumberColumn(
                        "Vendas novas", format="%d"),
                    "montante": st.column_config.NumberColumn(
                        "Montante", format="R$ %.0f"),
                    "receita": st.column_config.NumberColumn(
                        "Receita", format="R$ %.0f"),
                    "taxa_comparecimento": st.column_config.NumberColumn(
                        "% Compar.", format="%.1f%%"),
                    "ticket_medio": st.column_config.NumberColumn(
                        "Ticket médio", format="R$ %.0f"),
                },
            )

with tab_temp:
    section_title("Evolução diária", "agendamentos × comparecimentos × vendas novas")
    if df_diario.empty:
        st.info("Sem série diária no período.")
    else:
        from src.ui.charts import line
        st.plotly_chart(
            line(df_diario, x="data_ref",
                 y=["agendamentos", "comparecimentos", "vendas_novas"],
                 height=320),
            use_container_width=True,
        )

with tab_qualif:
    section_title(
        "Qualificação & Comparecimento",
        "atuação do Pré × Não Qualificados (Recepção)",
    )
    st.markdown(QUALIF_LEGENDA_ABA)

    with st.expander("Ver colunas usadas na regra"):
        st.markdown(
            "- **Pré identificada** = `activity.prevendas` preenchido ou "
            "fallback via `zoho_deals.sdr_ss` → `zoho_users`\n"
            "- **Não Qualificado** = `zoho_deals.stage = 'Recepção'`\n"
            "- **Com Pré + Não Qualificados** = interseção das duas condições "
            "acima no mesmo agendamento\n"
            "- **Comparecimento** = `status_reuniao IN ('Concluída', 'Concluído')`\n"
            "- **Agendamento válido** = `activity_type IN ('Consulta', 'Indicação')`, "
            "`status_reuniao` preenchido e diferente de `Vencida`"
        )

    kq = prevendas_qualif_comparecimento_kpis(df_qualif_filt)
    if kq["total_agendamentos"] == 0:
        st.info("Sem agendamentos no período (Consulta/Indicação, sem Vencida).")
    else:
        section_title("Agendamentos", "com Pré identificada vs Não Qualificados")
        ra1, ra2, ra3, ra4, ra5 = st.columns(5, gap="small")
        with ra1:
            metric_card_v2(
                "Total agendamentos",
                int_br(kq["total_agendamentos"]),
                accent=True,
            )
        with ra2:
            metric_card_v2(
                "Com Pré",
                int_br(kq["agend_com_pre"]),
                hint=HINT_COM_PRE,
            )
        with ra3:
            metric_card_v2(
                "% Com Pré",
                pct(kq["pct_agend_com_pre"]),
                hint="com Pré ÷ total agendamentos",
            )
        with ra4:
            metric_card_v2(
                "Não Qualif.",
                int_br(kq["agend_nao_qualificados"]),
                hint=HINT_NAO_QUALIF,
            )
        with ra5:
            metric_card_v2(
                "% Não Qualif.",
                pct(kq["pct_agend_nao_qualificados"]),
                hint="Recepção ÷ total agendamentos",
            )

        ri1, ri2, ri3 = st.columns(3, gap="small")
        with ri1:
            metric_card_v2(
                "Com Pré + Não Qualif.",
                int_br(kq["agend_pre_mais_nao_qual"]),
                hint=HINT_PRE_MAIS_NAO_QUAL,
                accent=True,
            )
        with ri2:
            metric_card_v2(
                "% sobre total agend.",
                pct(kq["pct_agend_pre_mais_nao_qual"])
                if kq["total_agendamentos"] else "—",
                hint="interseção ÷ total de agendamentos",
            )
        with ri3:
            metric_card_v2(
                "Comparec. interseção",
                int_br(kq["comp_pre_mais_nao_qual"]),
                hint=f"{int_br(kq['comp_pre_mais_nao_qual'])} de "
                     f"{int_br(kq['agend_pre_mais_nao_qual'])} agendamentos",
                qual_split=[
                    (
                        "% Comp.",
                        pct(kq["pct_comparec_pre_mais_nao_qual"])
                        if kq["agend_pre_mais_nao_qual"] else "—",
                    ),
                ],
            )

        section_title("Comparecimentos", "com Pré identificada vs Não Qualificados")
        rc1, rc2, rc3, rc4, rc5 = st.columns(5, gap="small")
        with rc1:
            metric_card_v2(
                "Total comparecimentos",
                int_br(kq["total_comparecimentos"]),
                accent=True,
            )
        with rc2:
            metric_card_v2(
                "Com Pré",
                int_br(kq["comp_com_pre"]),
                hint=HINT_COM_PRE,
            )
        with rc3:
            metric_card_v2(
                "% Com Pré",
                pct(kq["pct_comp_com_pre"]),
                hint="com Pré ÷ total comparecimentos",
            )
        with rc4:
            metric_card_v2(
                "Não Qualif.",
                int_br(kq["comp_nao_qualificados"]),
                hint=HINT_NAO_QUALIF,
            )
        with rc5:
            metric_card_v2(
                "% Não Qualif.",
                pct(kq["pct_comp_nao_qualificados"]),
                hint="Recepção ÷ total comparecimentos",
            )

        cg1, cg2 = st.columns(2, gap="large")
        with cg1:
            st.markdown("**Agendamentos — Com Pré vs Não Qualif.**")
            st.plotly_chart(
                bar_qualif_pre_split(
                    prevendas_qualif_chart_agendamentos(df_qualif_filt),
                    height=300,
                ),
                use_container_width=True,
                key="prev_sdrs_qualif_agend",
            )
        with cg2:
            st.markdown("**Comparecimentos — Com Pré vs Não Qualif.**")
            st.plotly_chart(
                bar_qualif_pre_split(
                    prevendas_qualif_chart_comparecimentos(df_qualif_filt),
                    height=300,
                ),
                use_container_width=True,
                key="prev_sdrs_qualif_comp",
            )

        section_title("Por SDR", "atuação do Pré e Não Qualificados no período")
        tbl_sdr = prevendas_qualif_comparecimento_por_sdr(df_qualif_filt)
        if tbl_sdr.empty:
            st.caption("Sem dados por SDR no recorte.")
        else:
            st.dataframe(
                tbl_sdr,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "sdr": "SDR",
                    "agendamentos_total": st.column_config.NumberColumn(
                        "Agend. total", format="%d"),
                    "agend_com_pre": st.column_config.NumberColumn(
                        "Agend. com Pré", format="%d"),
                    "pct_agend_com_pre": st.column_config.NumberColumn(
                        "% Agend. com Pré", format="%.1f%%"),
                    "comparecimentos_total": st.column_config.NumberColumn(
                        "Comp. total", format="%d"),
                    "comp_com_pre": st.column_config.NumberColumn(
                        "Comp. com Pré", format="%d"),
                    "pct_comp_com_pre": st.column_config.NumberColumn(
                        "% Comp. com Pré", format="%.1f%%"),
                    "agend_nao_qualificados": st.column_config.NumberColumn(
                        "Agend. Não Qualif.", format="%d"),
                    "comp_nao_qualificados": st.column_config.NumberColumn(
                        "Comp. Não Qualif.", format="%d"),
                    "pct_comparec_nao_qualificados": st.column_config.NumberColumn(
                        "% Comp. Não Qualif.", format="%.1f%%"),
                    "pct_comparecimento_geral": st.column_config.NumberColumn(
                        "% Comp. geral", format="%.1f%%"),
                },
            )

        section_title(
            "Detalhe — Com Pré + Não Qualificados",
            "agendamentos na interseção (pré identificada e stage Recepção)",
        )
        st.caption(
            "Cada linha parte de `zoho_activities`; o deal é pareado por "
            "`what_id` normalizado → `zoho_deals.id`. As colunas de conferência "
            "validam se a activity e o deal existem nos dois lados."
        )
        tbl_det = prevendas_qualif_detalhe_pre_mais_nao_qual(df_qualif_filt)
        if tbl_det.empty:
            st.caption("Nenhum agendamento na interseção no recorte.")
        else:
            st.dataframe(
                tbl_det,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "data_reuniao_fmt": "Data da reunião",
                    "activity_id": "Activity ID",
                    "what_id_raw": "what_id (activity)",
                    "deal_id": "Deal ID",
                    "existe_em_activities": "Existe em activities?",
                    "existe_em_deals": "Existe em deals?",
                    "vinculo_activity_deal": "Vínculo activity → deal",
                    "deal_name": "Nome do deal",
                    "sdr": "SDR resolvida",
                    "fonte_sdr": "Fonte SDR",
                    "prevendas_raw": "activity.prevendas",
                    "deal_sdr_ss_id": "deal.sdr_ss (id)",
                    "deal_sdr_ss_nome": "deal.sdr_ss (nome)",
                    "stage": "Stage",
                    "status_reuniao": "Status reunião",
                    "compareceu": "Compareceu?",
                    "activity_type": "Activity type",
                    "activity_owner_nome": "Owner activity",
                    "activity_created_time_fmt": "Created time (activity)",
                    "deal_created_at_fmt": "Created time (deal)",
                },
            )

st.caption(
    "Classificação de SDR (`Pré-vendas` / `Social Seller` / `SDR não "
    "classificado`) reusa `src/team_classification.py`. Ranking ordenado "
    "por agendamentos. Filtros do header aplicam sobre `sdr` e `tipo_sdr` "
    "na aba Qualificação & Comparecimento."
)
