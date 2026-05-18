import streamlit as st

from src.repositories import get_sdr_closer
from src.transforms import (
    annotate_and_clean_sdr_closer,
    closer_ranking,
    sdr_closer_matriz,
    sdr_closer_totais,
    sdr_ranking,
)
from src.ui.charts import bar_ranked, heatmap
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, int_br, pct

ctx = start_page(
    title="SDR × Closer",
    subtitle="Compatibilidade e performance por par",
    filters=["tipo_sdr", "time_closer", "sdr", "closer"],
    right_text="Análise de duplas",
)

try:
    df_all = get_sdr_closer(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar: {e}")
    st.stop()

# Reclassifica tipo_sdr/time_closer com a lista canônica e remove
# misclassifications (sdr que é closer e vice-versa) — antes de filtrar.
df_all = annotate_and_clean_sdr_closer(df_all)

df = ctx.apply_filters(df_all, {
    "tipo_sdr":    "tipo_sdr",
    "time_closer": "time_closer",
    "sdr":         "sdr",
    "closer":      "closer",
})

if df.empty:
    st.warning("Sem dados para o filtro atual.")
    st.stop()

t = sdr_closer_totais(df)

# ---------------------------------------------------------------------------
# KPIs — página opera sobre vendas fechadas (data_hora_compra), então
# "Leads recebidos" virou tautológico (= Ganhos) e foi removido. Sequência
# alinhada com a leitura comercial: contagem → financeiro → ticket.
# ---------------------------------------------------------------------------
section_title("Resumo do período")
c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2("Ganhos", int_br(t["ganhos"]), accent=True,
                   hint="vendas novas no período")
with c2:
    metric_card_v2("Montante", brl(t["montante_total"]),
                   hint="SUM(amount) zoho_deals")
with c3:
    metric_card_v2("Receita", brl(t["receita_total"]),
                   hint="SUM(receita) zoho_deals")
with c4:
    metric_card_v2("Ticket médio", brl(t["ticket_medio"]),
                   hint="montante ÷ ganhos")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_matrix, tab_sdr, tab_closer = st.tabs(
    ["Matriz SDR × Closer", "Ranking SDR", "Ranking Closer"]
)

with tab_matrix:
    section_title("Matriz de compatibilidade", "escolha a métrica exibida na célula")

    # Label amigável → coluna interna do df. Mantém as 4 métricas
    # originais e acrescenta repasses + classificações (mesmas opções da
    # página equivalente de Pré-vendas — colunas vêm do SQL
    # `compatibilidade_sdr_closer.sql`, classificação combinada das 4
    # fontes com prioridade exclusiva +12 > -12 > Não atua).
    METRICA_OPCOES: dict[str, str] = {
        "Ganhos":             "ganhos",
        "Montante":           "montante_total",
        "Receita":            "receita_total",
        "Ticket médio":       "ticket_medio",
        "Repasses":           "repasses",
        "Repasses +12":       "repasses_mais_12",
        "Repasses -12":       "repasses_menos_12",
        "Repasses Não atua":  "repasses_nao_atua",
        "Ganhos +12":         "ganhos_mais_12",
        "Ganhos -12":         "ganhos_menos_12",
        "Ganhos Não atua":    "ganhos_nao_atua",
    }
    metrica_label = st.selectbox(
        "Métrica",
        list(METRICA_OPCOES.keys()),
        index=0,
        label_visibility="collapsed",
        key="vendas_sdr_closer_metrica",
    )
    metrica = METRICA_OPCOES[metrica_label]

    matriz = sdr_closer_matriz(df, metrica=metrica)
    if matriz.empty:
        st.info("Sem dados para montar a matriz.")
    else:
        st.plotly_chart(heatmap(matriz, metric=metrica), use_container_width=True)

with tab_sdr:
    ranking = sdr_ranking(df)
    section_title("Top SDR por receita")
    st.plotly_chart(
        bar_ranked(ranking, "sdr", "receita", top_n=20, money=True),
        use_container_width=True,
    )
    with st.expander("Tabela completa — SDR"):
        st.dataframe(
            ranking, use_container_width=True, hide_index=True,
            column_config={
                "receita": st.column_config.NumberColumn("Receita", format="R$ %.0f"),
                "montante": st.column_config.NumberColumn("Montante", format="R$ %.0f"),
                "ticket_medio": st.column_config.NumberColumn("Ticket médio", format="R$ %.0f"),
                "taxa_conversao": st.column_config.NumberColumn("% Conversão", format="%.1f%%"),
            },
        )

with tab_closer:
    ranking = closer_ranking(df)
    section_title("Top Closers por receita")
    st.plotly_chart(
        bar_ranked(ranking, "closer", "receita", top_n=20, money=True),
        use_container_width=True,
    )
    with st.expander("Tabela completa — Closer"):
        st.dataframe(
            ranking, use_container_width=True, hide_index=True,
            column_config={
                "receita": st.column_config.NumberColumn("Receita", format="R$ %.0f"),
                "montante": st.column_config.NumberColumn("Montante", format="R$ %.0f"),
                "ticket_medio": st.column_config.NumberColumn("Ticket médio", format="R$ %.0f"),
                "taxa_conversao": st.column_config.NumberColumn("% Conversão", format="%.1f%%"),
            },
        )

st.caption(
    "**Universos independentes — padrão Looker.** "
    "**Ganhos**: `stage IN ('Ganho','Fechado Ganho') · tipo_venda='Novo "
    "cliente' · data_hora_compra::date no período`. "
    "**Repasses**: `created_at::date no período · sdr_ss IS NOT NULL · "
    "executiva_vendas IS NOT NULL`. Um deal pode ser repassado num mês e "
    "ganho em outro. "
    "**Classificação +12/-12/Não atua** = regra combinada das 4 fontes "
    "(`lead_classification` · `qualificacao` · `classificado_cal` · "
    "`ext.classificado`), prioridade exclusiva `+12 > -12 > Não atua`. "
    "**Dedup**: `COUNT(DISTINCT deal_id)` em todas as contagens."
)
