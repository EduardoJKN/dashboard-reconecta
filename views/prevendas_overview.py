"""Pré-vendas — Visão Geral.

Cards consolidados + Tendência diária + Funil 4 etapas + Top SDRs.
SDR primário = `zoho_activities.prevendas` (NULL → 'Sem SDR').
Vendas atribuídas via `what_id` da activity → deal Ganho/Fechado Ganho
+ tipo_venda='Novo cliente' (mesma regra Visão Geral)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.prevendas_transforms import (
    prevendas_anotar_sdr,
    prevendas_funil_etapas,
    prevendas_overview_kpis,
    prevendas_ranking_sdr_oficiais,
    prevendas_ranking_sdr,
)
from src.repositories import (
    get_prevendas_leads_detalhe_diario,
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
    get_prevendas_sdrs_oficiais,
)
from src.ui.charts import bar_ranked, funnel
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, int_br, pct

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

df_sdr_anotado = prevendas_anotar_sdr(df_sdr)
df_sdr_filt = ctx.apply_filters(
    df_sdr_anotado,
    {"sdr": "sdr", "tipo_sdr": "tipo_sdr"},
)
k = prevendas_overview_kpis(df_diario)
agendamentos_brutos = int(k["agendamentos"])
agendamentos_vencidos = int(k.get("vencidas", 0))
agendamentos_exibidos = int(k.get("agendamentos_exibidos",
                                  max(agendamentos_brutos - agendamentos_vencidos, 0)))
k_funil = dict(k)
k_funil["agendamentos"] = agendamentos_exibidos

# ---------------------------------------------------------------------------
# Resumo do período
# ---------------------------------------------------------------------------
section_title(
    "Resumo do período",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4, c5 = st.columns(5, gap="small")
with c1:
    metric_card_v2("Agendamentos criados", int_br(k["agendamentos_criados"]),
                   hint="zoho_activities.created_time::date · status_reuniao IS NOT NULL",
                   accent=True)
with c2:
    metric_card_v2(
        "Agendamentos",
        int_br(agendamentos_exibidos),
        hint=(
            f"Bruto: {int_br(agendamentos_brutos)} · "
            f"Vencidos removidos: {int_br(agendamentos_vencidos)} · "
            f"Exibido: {int_br(agendamentos_exibidos)}"
        ),
    )
with c3:
    metric_card_v2("Agendamentos +12", int_br(k["agendamentos_mais_12"]),
                   hint="classificado = 'Atua +12' via ext_reconecta.leads")
with c4:
    metric_card_v2("Comparecimentos", int_br(k["comparecimentos"]),
                   hint="status_reuniao IN ('Concluída','Concluído')")
with c5:
    metric_card_v2("Vendas", int_br(k["vendas"]),
                   hint="zoho_deals.stage = 'Ganho' · tipo_venda = 'Novo cliente'")

# Linha 2 — financeiro / eficiência
r2c1, r2c2, r2c3, r2c4 = st.columns(4, gap="small")
with r2c1:
    metric_card_v2("Montante",
                   brl(k["montante"]) if k["montante"] else "—",
                   hint="SUM(amount) da base_dados")
with r2c2:
    metric_card_v2("Receita",
                   brl(k["receita"]) if k["receita"] else "—",
                   hint="SUM(receita) da base_dados")
with r2c3:
    metric_card_v2("Taxa de comparecimento",
                   pct(k["taxa_comparecimento"]) if k["taxa_comparecimento"] else "—",
                   hint="comparecimentos ÷ agendamentos exibidos (bruto - vencidas)")
with r2c4:
    metric_card_v2("Ticket médio",
                   brl(k["ticket_medio"]) if k["ticket_medio"] else "—",
                   hint="montante ÷ vendas")

# ---------------------------------------------------------------------------
# Funil — 4 etapas
# ---------------------------------------------------------------------------
section_title("Funil de pré-vendas",
              "agendamentos criados → agendamentos → comparecimentos → vendas")

labels, values = prevendas_funil_etapas(k_funil)
if all(v == 0 for v in values):
    st.info("Sem dados no período.")
else:
    st.plotly_chart(
        funnel(labels, values, height=320, show_dropoff=True),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Tendência diária
# ---------------------------------------------------------------------------
section_title("Tendência diária",
              "agendamentos criados × agendamentos × comparecimentos")

if df_diario.empty:
    st.info("Sem dados diários no período.")
else:
    df_diario_plot = df_diario.copy()
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
# Top SDRs
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
ranking_metric_label = st.selectbox(
    "Métrica do ranking",
    options=list(ranking_metric_options.keys()),
    index=1,
    key="prevendas_overview_ranking_metric",
)
ranking_metric_col = ranking_metric_options[ranking_metric_label]
section_title("Top SDRs", f"ranking do período · {ranking_metric_label.lower()}")

ranking = prevendas_ranking_sdr_oficiais(df_sdr_filt, df_sdrs_oficiais)
ranking_plot = ranking[ranking[ranking_metric_col].fillna(0) > 0].copy()
if ranking_plot.empty:
    st.info(f"Sem {ranking_metric_label.lower()} no período.")
else:
    st.plotly_chart(
        bar_ranked(ranking_plot, "sdr", ranking_metric_col, top_n=12, height=320),
        use_container_width=True,
    )

with st.expander("Ver dados diários da regra legada"):
    if df_diario.empty:
        st.caption("Sem dados diários no período.")
    else:
        tabela = df_diario.copy().sort_values("data_ref").reset_index(drop=True)

        if {"agendamentos", "vencidas"}.issubset(tabela.columns):
            tabela["agendamentos_exibidos"] = (
                tabela["agendamentos"].fillna(0) - tabela["vencidas"].fillna(0)
            ).clip(lower=0)

        if {"comparecimentos", "agendamentos_exibidos"}.issubset(tabela.columns):
            denom = tabela["agendamentos_exibidos"].where(
                tabela["agendamentos_exibidos"] != 0
            )
            tabela["taxa_comparecimento"] = (
                tabela["comparecimentos"].astype(float)
                .div(denom)
                .fillna(0)
                * 100
            )

        if {"montante", "vendas"}.issubset(tabela.columns):
            denom_vendas = tabela["vendas"].where(tabela["vendas"] != 0)
            tabela["ticket_medio"] = (
                tabela["montante"].astype(float)
                .div(denom_vendas)
                .fillna(0)
            )

        cols_map = [
            ("data_ref", "Data"),
            ("agendamentos_criados", "Agendamentos criados"),
            ("agendamentos", "Agendamentos (bruto)"),
            ("vencidas", "Vencidas"),
            ("agendamentos_exibidos", "Agendamentos exibidos"),
            ("agendamentos_mais_12", "Agendamentos +12"),
            ("comparecimentos", "Comparecimentos"),
            ("vendas", "Vendas"),
            ("montante", "Montante"),
            ("receita", "Receita"),
            ("taxa_comparecimento", "Taxa de comparecimento"),
            ("ticket_medio", "Ticket médio"),
        ]
        cols_presentes = [orig for orig, _ in cols_map if orig in tabela.columns]
        tabela = tabela[cols_presentes].rename(
            columns={orig: label for orig, label in cols_map if orig in cols_presentes}
        )

        column_config = {}
        if "Data" in tabela.columns:
            column_config["Data"] = st.column_config.DateColumn(
                "Data", format="DD/MM/YYYY"
            )
        if "Montante" in tabela.columns:
            column_config["Montante"] = st.column_config.NumberColumn(
                "Montante", format="R$ %.2f"
            )
        if "Receita" in tabela.columns:
            column_config["Receita"] = st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"
            )
        if "Taxa de comparecimento" in tabela.columns:
            column_config["Taxa de comparecimento"] = st.column_config.NumberColumn(
                "Taxa de comparecimento", format="%.2f%%"
            )
        if "Ticket médio" in tabela.columns:
            column_config["Ticket médio"] = st.column_config.NumberColumn(
                "Ticket médio", format="R$ %.2f"
            )

        st.caption(
            "Nesta tabela, `Agendamentos (bruto)` segue a regra legada original. "
            "`Agendamentos exibidos` = bruto - vencidas, alinhado ao card, funil e tendência."
        )
        st.dataframe(
            tabela,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )

with st.expander("Ver leads/agendamentos detalhados"):
    if df_detalhe.empty:
        st.caption("Sem linhas detalhadas no período.")
    else:
        tabela_det = df_detalhe.copy().sort_values(
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

        f7, f8 = st.columns(2)
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

        base_mask = pd.Series(True, index=tabela_det.index)
        if classif_sel:
            base_mask &= tabela_det["classificacao_filtro"].isin(classif_sel)
        if sdr_sel:
            base_mask &= tabela_det["sdr_filtro"].isin(sdr_sel)
        if closer_sel:
            base_mask &= tabela_det["closer_filtro"].isin(closer_sel)
        if status_sel:
            base_mask &= tabela_det["status_filtro"].isin(status_sel)

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
                & (tabela_det["classificacao_filtro"] == "Atua +12")
            ),
            "Agendamentos -12": (
                base_mask
                & mask_atividade
                & mask_data_agendamento
                & (tabela_det["classificacao_filtro"] == "Atua -12")
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
            tabela_det["classificacao_filtro"] == "Atua +12"
        )
        mask_menos_12 = mask_agendamentos & (
            tabela_det["classificacao_filtro"] == "Atua -12"
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
            ("email_lead", "E-mail do lead"),
            ("classificacao_filtro", "Classificação"),
            ("status_filtro", "Status reunião"),
            ("origem_fonte", "Origem/fonte"),
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
        tabela_view = tabela_view[cols_det_presentes].rename(
            columns={
                orig: label
                for orig, label in cols_map_det
                if orig in cols_det_presentes
            }
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
            column_config_det["Montante"] = st.column_config.NumberColumn(
                "Montante", format="R$ %.2f"
            )
        if "Receita" in tabela_view.columns:
            column_config_det["Receita"] = st.column_config.NumberColumn(
                "Receita", format="R$ %.2f"
            )

        st.caption(f"{len(tabela_view)} linha(s) no recorte exibido.")
        st.dataframe(
            tabela_view,
            use_container_width=True,
            hide_index=True,
            column_config=column_config_det,
        )

st.caption(
    "**Regra legada fiel nesta etapa.** Base principal em `zoho_deals`, "
    "com `LEFT JOIN ext_reconecta.leads ON d.id::text = l.zoho_id::text`. "
    "Activities ligadas ao deal via `what_id` normalizado e filtradas em "
    "`activity_type IN ('Consulta','Indicação')` com "
    "`status_reuniao IS NOT NULL`. **Agendamentos criados** usam "
    "`created_time::date`; **Agendamentos** usam `start_datetime::date`; "
    "**Agendamentos +12** contam `classificado = 'Atua +12'`; "
    "**Comparecimentos** usam `status_reuniao IN ('Concluída','Concluído')`. "
    "**Vendas** usam `zoho_deals.data_hora_compra::date` com "
    "`stage = 'Ganho'` e `tipo_venda = 'Novo cliente'`. Nesta etapa, os "
    "filtros `SDR` / `Tipo SDR` seguem aplicando ao ranking `Top SDRs`; os "
    "cards do topo usam a série setorial do legado."
)
