"""Componentes reutilizáveis das páginas de Pré-vendas.

`render_top_sdr_interativo` encapsula o bloco "Top SDRs" da Visão Geral
Pré-vendas (gráfico clicável + painel lateral retrátil + selectbox de
fallback + mini-cards + tabela resumida + tabela completa). Reutilizado
em SDRs & Times e Comparecimentos & Oportunidades para garantir
consistência visual e de regras de cálculo.

A Visão Geral mantém sua própria implementação por enquanto — tem
warnings de divergência específicos (ranking × card, tabela × gráfico)
que não são genéricos. Refatoração para também usar este helper fica
para um momento futuro.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.prevendas_transforms import (
    prevendas_detalhe_mask_por_metrica,
    prevendas_normalizar_detalhe,
    prevendas_ranking_sdr_oficiais,
    prevendas_sdrs_brutos_para_oficial,
)
from src.ui.charts import bar_ranked
from src.ui.components import metric_card_v2, section_title
from src.ui.prevendas_ranking_cost import (
    RANKING_AVG_COST_LABELS,
    augment_ranking_plot_with_cost,
    init_ranking_metric_col_state,
    render_ranking_metric_controls,
)
from src.ui.theme import int_br


def render_top_sdr_interativo(
    *,
    df_sdr_filt: pd.DataFrame,
    df_sdrs_oficiais: pd.DataFrame,
    df_detalhe: pd.DataFrame,
    metric_options: dict[str, str],
    default_metric_label: str,
    data_ini: date,
    data_fim: date,
    key_prefix: str,
    section_title_text: str = "Top SDRs",
    section_subtitle: str | None = None,
    column_grid: tuple[float, float] = (1.45, 1.0),
    investido_total: float | None = None,
    kpis: dict | None = None,
    agendamentos_exibidos: int | None = None,
) -> None:
    """Bloco completo Top SDR interativo — gráfico à esquerda, painel
    retrátil à direita.

    - `df_sdr_filt`: 1 row por (sdr, fonte_sdr) já filtrado pelos filtros
      globais da página (vem de `get_prevendas_por_sdr` + `apply_filters`).
    - `df_detalhe`: detalhe linha-a-linha (`get_prevendas_leads_detalhe_diario`),
      idealmente JÁ filtrado pelos filtros globais.
    - `df_sdrs_oficiais`: cadastro oficial de SDRs (`get_prevendas_sdrs_oficiais`).
    - `metric_options`: dict `label_humano -> nome_coluna_no_ranking`.
      Ex.: `{"Agendamentos": "agendamentos", "Vendas": "vendas"}`.
    - `key_prefix`: usado pra prefixar todas as keys de widgets desta
      página — evita colisão entre as 3 páginas que usam o helper.
    - `investido_total` + `kpis`: quando informados, habilita checkbox de
      custo, seletor com custo médio e tooltip/bar labels como na Visão Geral.
    """
    metric_labels = list(metric_options.keys())
    label_by_col = {col: label for label, col in metric_options.items()}
    ranking_com_custo = investido_total is not None and kpis is not None

    if ranking_com_custo:
        col_state_key = f"{key_prefix}_ranking_metric_col"
        legacy_label_key = f"{key_prefix}_ranking_metric"
        _col_header = init_ranking_metric_col_state(
            metric_options, default_metric_label, col_state_key, legacy_label_key,
        )
        _label_atual = label_by_col[_col_header]
    else:
        metric_state_key = f"{key_prefix}_ranking_metric"
        _label_atual = st.session_state.get(metric_state_key, default_metric_label)
        if _label_atual not in metric_options:
            _label_atual = default_metric_label

    subtitle = (
        section_subtitle
        if section_subtitle is not None
        else f"ranking do período · {_label_atual.lower()}"
    )
    section_title(section_title_text, subtitle)

    # --- Ranking sobre SDRs oficiais (mesma regra da Visão Geral) ---
    ranking = prevendas_ranking_sdr_oficiais(df_sdr_filt, df_sdrs_oficiais)

    col_grafico, col_detalhe = st.columns(list(column_grid), gap="large")

    # =======================================================================
    # COLUNA ESQUERDA — métrica + gráfico clicável
    # =======================================================================
    with col_grafico:
        if ranking_com_custo:
            ranking_metric_col, ranking_metric_label, mostrar_custo = (
                render_ranking_metric_controls(
                    metric_options=metric_options,
                    default_metric_label=default_metric_label,
                    key_prefix=key_prefix,
                    investido_total=float(investido_total),
                    kpis=kpis,
                    df_rank_base=df_sdr_filt,
                    agendamentos_exibidos=agendamentos_exibidos,
                )
            )
        else:
            default_idx = (metric_labels.index(default_metric_label)
                           if default_metric_label in metric_labels else 0)
            metric_state_key = f"{key_prefix}_ranking_metric"
            ranking_metric_label = st.selectbox(
                "Métrica do ranking",
                options=metric_labels,
                index=default_idx,
                key=metric_state_key,
            )
            ranking_metric_col = metric_options[ranking_metric_label]
            mostrar_custo = False

        ranking_plot = ranking[
            ranking[ranking_metric_col].fillna(0) > 0
        ].copy() if (
            ranking is not None and not ranking.empty
            and ranking_metric_col in ranking.columns
        ) else pd.DataFrame()
        chart_state = None

        if ranking_plot.empty:
            st.info(f"Sem {ranking_metric_label.lower()} no período.")
        else:
            bar_kwargs: dict = {}
            plot_data = ranking_plot
            if ranking_com_custo:
                plot_data, _custo_num, _custo_fmt = (
                    augment_ranking_plot_with_cost(
                        ranking_plot,
                        ranking_metric_col,
                        df_sdr_filt,
                        float(investido_total),
                        kpis,
                        agendamentos_exibidos=agendamentos_exibidos,
                    )
                )
                bar_kwargs = dict(
                    metric_label=ranking_metric_label,
                    cost_col="_inv_estimado_sdr",
                    cost_label=RANKING_AVG_COST_LABELS.get(
                        ranking_metric_col, "Custo médio",
                    ),
                    avg_cost_display=_custo_fmt,
                    show_cost_on_bar=mostrar_custo,
                )
            fig_top = bar_ranked(
                plot_data, "sdr", ranking_metric_col,
                top_n=12, height=320,
                **bar_kwargs,
            )
            chart_state = st.plotly_chart(
                fig_top,
                use_container_width=True,
                key=f"{key_prefix}_top_sdrs_chart",
                on_select="rerun",
                selection_mode="points",
            )

    # =======================================================================
    # COLUNA DIREITA — painel retrátil "Detalhe da SDR selecionada"
    # =======================================================================
    with col_detalhe:
        if (ranking_plot.empty
                or df_detalhe is None or df_detalhe.empty):
            with st.expander("Detalhe da SDR selecionada", expanded=False):
                st.caption(
                    "Sem dados de ranking ou de detalhe no período para "
                    "esses filtros."
                )
            return

        sdrs_disponiveis = ranking_plot["sdr"].dropna().astype(str).tolist()
        OPCAO_TODAS = "Todas"

        # ----- Sincronia clique-no-gráfico ↔ selectbox ---------------------
        SELECTBOX_KEY  = f"{key_prefix}_top_sdr_detalhe"
        LAST_CLICK_KEY = f"_{key_prefix}_top_sdr_last_chart_pick"

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

        sdr_atual = st.session_state.get(SELECTBOX_KEY, OPCAO_TODAS)
        titulo_expander = (
            "Detalhe da SDR selecionada"
            if sdr_atual == OPCAO_TODAS
            else f"Detalhe — {sdr_atual}"
        )

        with st.expander(titulo_expander, expanded=False):
            st.caption(
                "💡 **Clique numa barra do gráfico** para detalhar aquele "
                "SDR — ou use o seletor abaixo. 'Todas' mostra o consolidado."
            )
            sdr_escolhido = st.selectbox(
                "SDR para detalhar",
                options=[OPCAO_TODAS] + sdrs_disponiveis,
                key=SELECTBOX_KEY,
            )

            df_det_norm = prevendas_normalizar_detalhe(df_detalhe)
            mask_metrica = prevendas_detalhe_mask_por_metrica(
                df_det_norm, ranking_metric_col, data_ini, data_fim
            )

            if sdr_escolhido == OPCAO_TODAS:
                contagem_grafico = int(
                    ranking_plot[ranking_metric_col].fillna(0).sum()
                )
                mask_sdr = pd.Series(True, index=df_det_norm.index)
            else:
                contagem_grafico = int(
                    ranking_plot.loc[
                        ranking_plot["sdr"] == sdr_escolhido,
                        ranking_metric_col,
                    ].iloc[0]
                )
                sdrs_brutos = prevendas_sdrs_brutos_para_oficial(
                    df_det_norm, sdr_escolhido, df_sdrs_oficiais
                )
                mask_sdr = df_det_norm["sdr_filtro"].isin(sdrs_brutos)

            linhas_brutas = df_det_norm[mask_sdr & mask_metrica].copy()

            # Vendas conta deal_id; resto conta activity_id.
            unidade_col = (
                "deal_id" if ranking_metric_col == "vendas" else "activity_id"
            )
            if unidade_col in linhas_brutas.columns:
                contagem_tabela = int(
                    linhas_brutas[unidade_col].nunique(dropna=False)
                )
                linhas = linhas_brutas.drop_duplicates(
                    subset=[unidade_col], keep="first"
                ).copy()
            else:
                contagem_tabela = len(linhas_brutas)
                linhas = linhas_brutas.copy()

            # ----- Mini-cards de resumo (5 métricas-padrão) ----------------
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
                    hint="classificação combinada (4 fontes)",
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
                    f"R$ {receita_val:,.0f}".replace(",", "."),
                    hint=(
                        "receita dos deals ganhos"
                        if label_receita == "Receita"
                        else "montante dos deals ganhos"
                    ),
                )

            # ----- Aviso discreto de divergência tabela × gráfico ----------
            if contagem_tabela != contagem_grafico:
                delta = contagem_tabela - contagem_grafico
                st.caption(
                    f"ℹ Tabela: {int_br(contagem_tabela)} · Gráfico: "
                    f"{int_br(contagem_grafico)} (Δ {int_br(delta)}). "
                    "Divergência típica entre ranking (LEFT JOIN com deal) "
                    "e detalhe (INNER JOIN); auditável em "
                    "`prevendas_leads_detalhe_diario.sql`."
                )

            # ----- Tabela resumida -----------------------------------------
            if linhas.empty:
                st.caption("Nenhum registro encontrado para esse SDR/métrica.")
                return

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
                ("#",                       "#"),
                ("nome_cliente_view",       "Nome do cliente/lead"),
                ("email_lead",              "E-mail"),
                ("classificacao_filtro",    "Classificação"),
                ("status_filtro",           "Status reunião"),
                ("origem_fonte",            "Origem/fonte"),
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

            # ----- Toggle "Ver tabela completa" ----------------------------
            ver_completa = st.toggle(
                "Ver tabela completa",
                value=False,
                key=f"{key_prefix}_top_sdr_ver_completa",
            )
            if ver_completa:
                cols_map_top = [
                    ("#", "#"),
                    ("nome_cliente_view", "Nome do cliente/lead"),
                    ("email_lead", "E-mail"),
                    ("sdr_filtro", "SDR"),
                    ("closer_filtro", "Closer"),
                    ("classificacao_filtro", "Classif. (lead)"),
                    ("classificacao_crm_filtro", "Classif. (CRM)"),
                    ("status_filtro", "Status reunião"),
                    ("origem_fonte", "Origem/fonte"),
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
                tabela_full = linhas[cols_full].rename(
                    columns={c: lbl for c, lbl in cols_map_top
                             if c in cols_full}
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
                    cfg_full["Montante"] = st.column_config.NumberColumn(
                        "Montante", format="R$ %.2f"
                    )
                if "Receita" in tabela_full.columns:
                    cfg_full["Receita"] = st.column_config.NumberColumn(
                        "Receita", format="R$ %.2f"
                    )
                st.dataframe(
                    tabela_full,
                    use_container_width=True,
                    hide_index=True,
                    column_config=cfg_full,
                )
