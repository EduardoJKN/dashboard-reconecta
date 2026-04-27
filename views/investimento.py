import streamlit as st

from src.repositories import get_executivas, get_investimento_diario
from src.transforms import investimento_totais, roas_diario, roas_resumo
from src.ui.charts import area, dual_line, line
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, brl_short, int_br

ctx = start_page(
    title="Investimento & ROAS",
    subtitle="Mídia × receita do comercial",
    right_text="Eficiência de mídia",
)

try:
    df_inv = get_investimento_diario(ctx.data_ini, ctx.data_fim)
    df_exec = get_executivas(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar: {e}")
    st.stop()

if df_inv.empty:
    st.warning("Sem investimento registrado no período.")
    st.stop()

tot = investimento_totais(df_inv)
r = roas_resumo(df_inv, df_exec)

# ---------------------------------------------------------------------------
# KPIs principais
# ---------------------------------------------------------------------------
section_title("Resumo do período")
c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2("ROAS", f"{r['roas']:.2f}x",
                   hint=f"R$ {r['roas']:.2f} / R$ 1 investido", accent=True)
with c2:
    metric_card_v2("Investimento total", brl(r["investimento"]),
                   hint=f"{tot['dias']} dias · média {brl_short(tot['media_dia'])}/dia")
with c3:
    metric_card_v2("Receita atribuída", brl(r["receita"]),
                   hint=f"{int_br(r['vendas'])} vendas")
with c4:
    metric_card_v2("CPA", brl(r["cac"]) if r["cac"] else "—",
                   hint="investimento ÷ vendas")

# ---------------------------------------------------------------------------
# Série principal
# ---------------------------------------------------------------------------
section_title("Investimento × Receita", "duplo eixo para comparar magnitude")

merged = roas_diario(df_inv, df_exec)
if merged.empty:
    st.info("Sem intersecção entre investimento e receita no período.")
else:
    st.plotly_chart(
        dual_line(merged, "data_ref", "receita", "investimento_total",
                  "Receita", "Investimento", height=360),
        use_container_width=True,
    )

section_title("ROAS e CPA no tempo")
cA, cB = st.columns(2, gap="large")
with cA:
    st.markdown("<div class='sec-title' style='margin-top:0;border:none'>"
                "ROAS diário <span class='sub'>maior = melhor</span></div>",
                unsafe_allow_html=True)
    if not merged.empty:
        st.plotly_chart(area(merged, "data_ref", "roas", height=260),
                        use_container_width=True)
with cB:
    st.markdown("<div class='sec-title' style='margin-top:0;border:none'>"
                "CPA diário <span class='sub'>menor = melhor</span></div>",
                unsafe_allow_html=True)
    if not merged.empty:
        st.plotly_chart(
            line(merged, "data_ref", "cac", height=260, money_axis="y"),
            use_container_width=True,
        )

with st.expander("Detalhamento diário (tabela completa)"):
    tabela = merged if not merged.empty else df_inv
    st.dataframe(
        tabela, use_container_width=True, hide_index=True,
        column_config={
            "data_ref": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "investimento_total": st.column_config.NumberColumn("Investimento", format="R$ %.2f"),
            "receita": st.column_config.NumberColumn("Receita", format="R$ %.0f"),
            "montante": st.column_config.NumberColumn("Montante", format="R$ %.0f"),
            "vendas": st.column_config.NumberColumn("Vendas", format="%d"),
            "roas": st.column_config.NumberColumn("ROAS", format="%.2fx"),
            "cac": st.column_config.NumberColumn("CPA", format="R$ %.0f"),
        },
    )
