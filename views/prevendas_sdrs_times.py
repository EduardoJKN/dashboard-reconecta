"""Pré-vendas — SDRs & Times.

Ranking individual + consolidação por tipo (Pré-vendas / Social Seller /
SDR não classificado / Sem SDR). Classificação canônica reutilizada
de `team_classification.classify_sdr` (mesma usada em SDR × Closer
do Time de Vendas)."""
import streamlit as st

from src.prevendas_transforms import (
    prevendas_anotar_sdr,
    prevendas_detalhe_sdr_por_fonte,
    prevendas_overview_kpis,
    prevendas_por_tipo,
    prevendas_ranking_sdr,
)
from src.repositories import (
    get_prevendas_leads_detalhe_diario,
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
    get_prevendas_sdrs_oficiais,
)
from src.ui.charts import bar_simple
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

k = prevendas_overview_kpis(df_diario)

# ---------------------------------------------------------------------------
# Resumo do período (totais, sem filtro fino — referência cross-SDR)
# ---------------------------------------------------------------------------
section_title("Resumo do período")

c1, c2, c3, c4, c5, c6, c7 = st.columns(7, gap="small")
with c1:
    metric_card_v2("Leads", int_br(k["leads"]), accent=True,
                   hint="cross-SDR · referência")
with c2:
    metric_card_v2("Agendamentos", int_br(k["agendamentos"]),
                   hint="período · activities Consulta/Indicação")
with c3:
    metric_card_v2("Comparecimentos", int_br(k["comparecimentos"]),
                   hint="status_reuniao = 'Concluída'")
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

# ---------------------------------------------------------------------------
# Tabs — Ranking SDR / Por tipo / Evolução
# ---------------------------------------------------------------------------
tab_rank, tab_tipo, tab_temp = st.tabs(
    ["Ranking SDR", "Por tipo de SDR", "Evolução"]
)

with tab_rank:
    # Modelo unificado de Top SDR — mesmo helper da Visão Geral
    # Pré-vendas e Comparecimentos & Oportunidades. Gráfico clicável
    # à esquerda, painel retrátil de detalhe à direita.
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

    # Tabela auxiliar (consolidado bruto) — mantida para auditoria,
    # agora como expander secundário.
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

st.caption(
    "Classificação de SDR (`Pré-vendas` / `Social Seller` / `SDR não "
    "classificado`) reusa `src/team_classification.py`. Ranking ordenado "
    "por agendamentos. Filtros do header aplicam sobre `sdr` e `tipo_sdr` "
    "diretamente."
)
