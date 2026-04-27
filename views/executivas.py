import streamlit as st

from src.repositories import get_executivas
from src.transforms import (
    executivas_kpis,
    executivas_por_dia,
    executivas_por_time,
    executivas_ranking,
)
from src.ui.charts import bar_ranked, bar_simple, line
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, int_br, pct

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

k = executivas_kpis(df)

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
section_title("Resumo do período")
c1, c2, c3, c4, c5, c6, c7 = st.columns(7, gap="small")
with c1:
    metric_card_v2("Receita", brl(k["receita"]),
                   hint=f"{int_br(k['vendas'])} vendas", accent=True)
with c2:
    metric_card_v2("Ticket Médio", brl(k["ticket_medio"]),
                   hint="montante ÷ vendas")
with c3:
    metric_card_v2("% Conversão", pct(k["pct_conversao"]),
                   hint="vendas ÷ agendamentos")
with c4:
    metric_card_v2("% Comparecimento", pct(k["pct_comparecimento"]),
                   hint="comparec. ÷ agendamentos")
with c5:
    metric_card_v2("% Agendamento", pct(k["pct_agendamento"]),
                   hint="agend. ÷ oportunidades")
with c6:
    metric_card_v2("% Vendas", pct(k["pct_vendas"]),
                   hint="vendas ÷ comparecimentos")
with c7:
    metric_card_v2("% Recebimento", pct(k["pct_recebimento"]),
                   hint="receita ÷ montante")

section_title("Funil (absolutos)", "leads → reunião agendada → reunião concluída → cancelados → ganhos → perdidos")
f1, f2, f3, f4, f5, f6 = st.columns(6, gap="small")
with f1: metric_card_v2("Leads", int_br(k["oportunidades"]))
with f2: metric_card_v2("Reunião Agendada", int_br(k["agendamentos"]))
with f3: metric_card_v2("Reunião Concluída", int_br(k["comparecimentos"]))
with f4: metric_card_v2("Cancelados", int_br(k["cancelados"]))
with f5: metric_card_v2("Ganhos", int_br(k["vendas"]))
with f6: metric_card_v2("Perdidos", int_br(k["perdidos"]))

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_rank, tab_time, tab_temp = st.tabs(["Ranking executivas", "Por time", "Evolução"])

with tab_rank:
    section_title("Ranking por receita", "top 15 no período")
    ranking = executivas_ranking(df)
    if ranking.empty:
        st.info("Sem dados.")
    else:
        st.plotly_chart(
            bar_ranked(ranking, "executiva", "receita", top_n=15, money=True),
            use_container_width=True,
        )
        visible = ranking.head(10)
        cols_visible = [
            "executiva",
            "vendas", "receita", "ticket_medio",
            "agendamentos", "comparecimentos",
            "pct_conversao", "pct_comparecimento",
            "pct_vendas", "pct_recebimento",
        ]
        st.dataframe(
            visible[cols_visible],
            use_container_width=True, hide_index=True,
            column_config={
                "executiva":          st.column_config.TextColumn("Executiva", width="medium"),
                "vendas":             st.column_config.NumberColumn("Vendas", format="%d"),
                "receita":            st.column_config.NumberColumn("Receita", format="R$ %.0f"),
                "ticket_medio":       st.column_config.NumberColumn("Ticket médio", format="R$ %.0f"),
                "agendamentos":       st.column_config.NumberColumn("Agendamentos", format="%d"),
                "comparecimentos":    st.column_config.NumberColumn("Comparecimentos", format="%d"),
                "pct_conversao":      st.column_config.NumberColumn("% Conversão",   format="%.1f%%"),
                "pct_comparecimento": st.column_config.NumberColumn("% Comparec.",   format="%.1f%%"),
                "pct_vendas":         st.column_config.NumberColumn("% Vendas",      format="%.1f%%"),
                "pct_recebimento":    st.column_config.NumberColumn("% Recebimento", format="%.1f%%"),
            },
        )
        with st.expander("Ver ranking completo"):
            st.dataframe(ranking, use_container_width=True, hide_index=True)

with tab_time:
    por_time = executivas_por_time(df)
    if por_time.empty:
        st.info("Sem dados de time no filtro atual.")
    else:
        section_title("Consolidação por time")
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.plotly_chart(
                bar_simple(por_time, "time_vendas", "receita", money=True, rotate_x=True),
                use_container_width=True,
            )
        with c2:
            st.plotly_chart(
                bar_simple(por_time, "time_vendas", "vendas", rotate_x=True),
                use_container_width=True,
            )
        with st.expander("Tabela detalhada por time"):
            st.dataframe(por_time, use_container_width=True, hide_index=True)

with tab_temp:
    diario = executivas_por_dia(df)
    section_title("Funil diário (absolutos)")
    st.plotly_chart(
        line(diario, "data_ref",
             ["oportunidades", "agendamentos", "comparecimentos", "vendas"],
             height=340),
        use_container_width=True,
    )
    section_title("Receita × Montante (diário)")
    st.plotly_chart(
        line(diario, "data_ref", ["receita", "montante"],
             height=280, money_axis="y"),
        use_container_width=True,
    )
