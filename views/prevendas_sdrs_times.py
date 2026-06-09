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
    HINT_PCT_COMP_COM_PRE,
    HINT_PCT_COMP_INTERSECAO,
    HINT_PCT_COMP_NAO_QUALIF,
    QUALIF_LEGENDA_ABA,
    QUALIF_LEGENDA_LEONARDO,
    prevendas_anotar_sdr,
    prevendas_qualif_anotar_leonardo,
    prevendas_qualif_aplicar_filtro_leonardo,
    prevendas_detalhe_sdr_por_fonte,
    prevendas_overview_kpis,
    prevendas_por_tipo,
    prevendas_qualif_chart_agendamentos,
    prevendas_qualif_chart_comparecimentos,
    prevendas_qualif_comparecimento_kpis,
    prevendas_qualif_comparecimento_por_sdr,
    prevendas_qualif_detalhe_display,
    prevendas_qualif_detalhe_filtrar,
    prevendas_qualif_detalhe_kpis,
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

_LEONARDO_ROSSO_SESSION_KEY = "prev_sdrs_excluir_leonardo"

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

if _LEONARDO_ROSSO_SESSION_KEY not in st.session_state:
    st.session_state[_LEONARDO_ROSSO_SESSION_KEY] = True

excluir_lr_global = bool(st.session_state[_LEONARDO_ROSSO_SESSION_KEY])

df_qualif_anotado = prevendas_qualif_anotar_leonardo(
    prevendas_anotar_sdr(df_qualif)
)
df_qualif_sem_lr = prevendas_qualif_aplicar_filtro_leonardo(
    df_qualif_anotado,
    excluir=excluir_lr_global,
)
df_qualif_filt = ctx.apply_filters(
    df_qualif_sem_lr,
    {"sdr": "sdr", "tipo_sdr": "tipo_sdr"},
)
df_qualif_filt_audit = ctx.apply_filters(
    df_qualif_anotado,
    {"sdr": "sdr", "tipo_sdr": "tipo_sdr"},
)

k = prevendas_overview_kpis(df_diario)
if excluir_lr_global:
    kq_resumo_lr = prevendas_qualif_comparecimento_kpis(df_qualif_sem_lr)
    k = {
        **k,
        "agendamentos": kq_resumo_lr["total_agendamentos"],
        "comparecimentos": kq_resumo_lr["total_comparecimentos"],
    }
    _splits_resumo = prevendas_qualif_resumo_splits(df_qualif_sem_lr)
else:
    _splits_resumo = prevendas_qualif_resumo_splits(df_qualif_anotado)

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
        qual_split=_splits_resumo["agend"],
    )
with c3:
    metric_card_v2(
        "Comparecimentos",
        int_br(k["comparecimentos"]),
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

    st.checkbox(
        "Excluir Leonardo Rosso",
        help="Remove registros em que o nome do deal contém "
             "'Leonardo Rosso' das métricas operacionais.",
        key=_LEONARDO_ROSSO_SESSION_KEY,
    )
    excluir_lr_global = bool(st.session_state[_LEONARDO_ROSSO_SESSION_KEY])
    if excluir_lr_global:
        st.caption(QUALIF_LEGENDA_LEONARDO)

    with st.expander("Ver colunas usadas na regra"):
        st.markdown(
            "- **Pré identificada** = `activity.prevendas` preenchido ou "
            "fallback via `zoho_deals.sdr_ss` → `zoho_users`\n"
            "- **Com Pré (operacional)** = pré identificada e "
            "`stage <> 'Recepção'`\n"
            "- **Não Qualificado** = `zoho_deals.stage = 'Recepção'`\n"
            "- **Com Pré + Não Qualificados** = pré identificada em "
            "Recepção (auditoria; não entra no Com Pré operacional)\n"
            "- **Comparecimento** = `status_reuniao IN ('Concluída', 'Concluído')`, "
            "aplicado sobre a mesma base classificada dos agendamentos\n"
            "- **% Comp.** = comparecimentos da dimensão ÷ agendamentos da dimensão\n"
            "- **Agendamento válido** = `activity_type IN ('Consulta', 'Indicação')`, "
            "`status_reuniao` preenchido e diferente de `Vencida`\n"
            "- **E-mail do deal** = `zoho_deals.email` ou, se vazio, "
            "`zoho_deals.email_secundario` (somente auditoria; pareamento "
            "continua por `what_id` → `zoho_deals.id`)\n"
            "- **Excluir Leonardo Rosso** = `deal_name` contendo "
            "'Leonardo Rosso' (normalizado) removido das métricas "
            "operacionais; a tabela de detalhe pode reexibir esses "
            "registros com o filtro local desativado"
        )

    kq = prevendas_qualif_comparecimento_kpis(df_qualif_filt)
    if kq["total_agendamentos"] == 0:
        st.info("Sem agendamentos no período (Consulta/Indicação, sem Vencida).")
    else:
        section_title(
            "Agendamentos",
            "Com Pré operacional (stage ≠ Recepção) vs Não Qualificados",
        )
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
                hint="Com Pré real ÷ total agendamentos",
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

        section_title(
            "Comparecimentos",
            "quantos agendamentos classificados chegaram à etapa de comparecimento",
        )
        rc1, rc2, rc3, rc4 = st.columns(4, gap="small")
        with rc1:
            metric_card_v2(
                "Total comparecimentos",
                int_br(kq["total_comparecimentos"]),
                accent=True,
                hint=f"{pct(kq['pct_comparecimento_geral'])} do total de agendamentos",
            )
        with rc2:
            metric_card_v2(
                "Comp. Com Pré",
                int_br(kq["comp_com_pre"]),
                hint=HINT_COM_PRE,
            )
        with rc3:
            metric_card_v2(
                "% Comp. Com Pré",
                pct(kq["pct_comp_com_pre"]) if kq["agend_com_pre"] else "—",
                hint=HINT_PCT_COMP_COM_PRE,
            )
        with rc4:
            metric_card_v2(
                "Comp. Não Qualif.",
                int_br(kq["comp_nao_qualificados"]),
                hint=HINT_NAO_QUALIF,
            )

        rc5, rc6, rc7 = st.columns(3, gap="small")
        with rc5:
            metric_card_v2(
                "% Comp. Não Qualif.",
                pct(kq["pct_comp_nao_qualificados"])
                if kq["agend_nao_qualificados"] else "—",
                hint=HINT_PCT_COMP_NAO_QUALIF,
            )
        with rc6:
            metric_card_v2(
                "Comp. Com Pré + Não Qualif.",
                int_br(kq["comp_pre_mais_nao_qual"]),
                hint=HINT_PRE_MAIS_NAO_QUAL,
            )
        with rc7:
            metric_card_v2(
                "% Comp. Interseção",
                pct(kq["pct_comparec_pre_mais_nao_qual"])
                if kq["agend_pre_mais_nao_qual"] else "—",
                hint=HINT_PCT_COMP_INTERSECAO,
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
                    pct_mode="avanco",
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
                        "Agend. Com Pré real", format="%d",
                        help="Pré identificada e stage ≠ Recepção"),
                    "pct_agend_com_pre": st.column_config.NumberColumn(
                        "% Agend. Com Pré", format="%.1f%%"),
                    "agend_pre_mais_nao_qual": st.column_config.NumberColumn(
                        "Agend. Com Pré + Não Qualif.", format="%d",
                        help="Auditoria: pré em Recepção"),
                    "comparecimentos_total": st.column_config.NumberColumn(
                        "Comp. total", format="%d"),
                    "comp_com_pre": st.column_config.NumberColumn(
                        "Comp. Com Pré real", format="%d"),
                    "comp_pre_mais_nao_qual": st.column_config.NumberColumn(
                        "Comp. Com Pré + Não Qualif.", format="%d"),
                    "pct_comp_com_pre": st.column_config.NumberColumn(
                        "% Comp. com Pré (÷ agend.)", format="%.1f%%"),
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
            "`what_id` normalizado → `zoho_deals.id`. Filtros abaixo afetam "
            "somente este bloco de auditoria — não alteram os cards da aba."
        )
        tbl_base = prevendas_qualif_detalhe_pre_mais_nao_qual(df_qualif_filt_audit)
        if tbl_base.empty:
            st.caption("Nenhum agendamento na interseção no recorte.")
        else:
            opcoes_data = sorted(
                tbl_base["data_reuniao_label"].dropna().unique().tolist(),
                reverse=True,
            )
            opcoes_deal = sorted(
                tbl_base["deal_name"].dropna().astype(str).unique().tolist()
            )
            opcoes_sdr_det = sorted(
                tbl_base["sdr"].dropna().astype(str).unique().tolist()
            )
            stage_col = (
                "stage_tratado"
                if "stage_tratado" in tbl_base.columns
                else "stage"
            )
            opcoes_stage = sorted(
                tbl_base[stage_col].map(
                    lambda v: v if str(v).strip() else "Sem etapa"
                ).unique().tolist()
            )

            fd1, fd2, fd3, fd4 = st.columns(4, gap="small")
            with fd1:
                datas_sel = st.multiselect(
                    "Data da reunião",
                    options=opcoes_data,
                    default=[],
                    placeholder="Todas",
                    key="prev_sdrs_qualif_det_data",
                )
            with fd2:
                deals_sel = st.multiselect(
                    "Nome do deal",
                    options=opcoes_deal,
                    default=[],
                    placeholder="Todos",
                    key="prev_sdrs_qualif_det_deal",
                )
            with fd3:
                sdrs_sel = st.multiselect(
                    "SDR resolvida",
                    options=opcoes_sdr_det,
                    default=[],
                    placeholder="Todas",
                    key="prev_sdrs_qualif_det_sdr",
                )
            with fd4:
                stages_sel = st.multiselect(
                    "Stage",
                    options=opcoes_stage,
                    default=[],
                    placeholder="Todos",
                    key="prev_sdrs_qualif_det_stage",
                )

            fb1, fb2 = st.columns([2, 1], gap="small")
            with fb1:
                busca_deal = st.text_input(
                    "Buscar no nome do deal",
                    value="",
                    placeholder="Ex.: Leonardo Rosso, Letícia…",
                    key="prev_sdrs_qualif_det_busca",
                )
            with fb2:
                excluir_leonardo = st.checkbox(
                    "Excluir Leonardo Rosso (detalhe)",
                    value=excluir_lr_global,
                    help="Filtro local da tabela de auditoria. Desative para "
                         "ver registros do CEO mesmo com a exclusão global ativa.",
                    key="prev_sdrs_qualif_det_excl_lr",
                )

            tbl_local = prevendas_qualif_detalhe_filtrar(
                tbl_base,
                datas_reuniao=datas_sel or None,
                deals=deals_sel or None,
                sdrs=sdrs_sel or None,
                stages=stages_sel or None,
                busca_deal=busca_deal,
                excluir_leonardo_rosso=False,
            )
            leonardo_count = (
                int(tbl_local["eh_leonardo_rosso"].sum())
                if not tbl_local.empty and "eh_leonardo_rosso" in tbl_local.columns
                else 0
            )
            tbl_view = prevendas_qualif_detalhe_filtrar(
                tbl_local,
                excluir_leonardo_rosso=excluir_leonardo,
            )
            kd = prevendas_qualif_detalhe_kpis(
                tbl_view,
                excluir_leonardo_rosso=excluir_leonardo,
            )
            kd["leonardo_rosso"] = leonardo_count
            kd["mostrar_leonardo_rosso"] = not excluir_leonardo

            k1, k2, k3, k4 = st.columns(4, gap="small")
            with k1:
                metric_card_v2(
                    "Registros",
                    int_br(kd["total_registros"]),
                    accent=True,
                )
            with k2:
                metric_card_v2("Deals únicos", int_br(kd["deals_unicos"]))
            with k3:
                metric_card_v2("Activities únicas", int_br(kd["activities_unicas"]))
            with k4:
                metric_card_v2("SDRs únicas", int_br(kd["sdrs_unicas"]))

            k5, k6, k7, k8 = st.columns(4, gap="small")
            with k5:
                metric_card_v2(
                    "Comparecimentos",
                    int_br(kd["comparecimentos"]),
                )
            with k6:
                metric_card_v2(
                    "% Comparecimento",
                    pct(kd["pct_comparecimento"])
                    if kd["total_registros"] else "—",
                )
            with k7:
                metric_card_v2(
                    "Vínculo OK",
                    int_br(kd["vinculo_ok"]),
                    hint="what_id encontrou deal correspondente",
                )
            with k8:
                metric_card_v2(
                    "Sem deal ligado",
                    int_br(kd["sem_deal_ligado"]),
                    hint="what_id preenchido, mas sem deal pareado",
                )

            if kd["mostrar_leonardo_rosso"]:
                metric_card_v2(
                    "Leonardo Rosso",
                    int_br(kd["leonardo_rosso"]),
                    hint="registros com esse nome no deal (antes da exclusão)",
                )

            tbl_det = prevendas_qualif_detalhe_display(tbl_view)
            if tbl_det.empty:
                st.caption("Nenhum registro após os filtros locais.")
            else:
                st.dataframe(
                    tbl_det,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "data_reuniao_fmt": "Data da reunião",
                        "sdr": "SDR resolvida",
                        "deal_name": "Nome do deal",
                        "deal_email": "E-mail principal",
                        "activity_id": "Activity ID",
                        "what_id_raw": "what_id (activity)",
                        "deal_id": "Deal ID",
                        "existe_em_activities": "Existe em activities?",
                        "existe_em_deals": "Existe em deals?",
                        "vinculo_activity_deal": "Vínculo activity → deal",
                        "fonte_sdr": "Fonte SDR",
                        "deal_email_secundario": "E-mail secundário",
                        "email_preenchido": "E-mail preenchido?",
                        "sdr_aparece_no_deal": "SDR aparece no nome do deal?",
                        "possivel_registro_interno": "Possível registro interno?",
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
