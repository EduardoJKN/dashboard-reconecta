import streamlit as st

from src.repositories import get_executivas, get_investimento_diario
from src.transforms import investimento_totais, roas_diario, roas_resumo
from src.ui.charts import line
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, brl_short, int_br, pct

# ---------------------------------------------------------------------------
# Taxa de recebimento esperada — aplicada sobre o montante pra estimar
# receita futura. NÃO usar a taxa do próprio período como cálculo (vira
# circular: montante × receita/montante = receita); pode aparecer só como
# referência informacional. Default editável via st.number_input abaixo.
# ---------------------------------------------------------------------------
_TAXA_RECEBIMENTO_DEFAULT_PCT = 85.0  # 85% — calibrado pela operação
_TAXA_KEY = "investimento_taxa_recebimento_pct"

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

# ---------------------------------------------------------------------------
# Controle de taxa esperada
# ---------------------------------------------------------------------------
taxa_pct = st.number_input(
    "Taxa de recebimento esperada (%)",
    min_value=0.0, max_value=100.0,
    value=_TAXA_RECEBIMENTO_DEFAULT_PCT,
    step=1.0,
    key=_TAXA_KEY,
    help=(
        "Aplicada sobre o montante (SUM dos deals ganhos) pra estimar a "
        "receita futura — base do ROAS Projetado. Default 85% (calibração "
        "histórica). Não confundir com a taxa de recebimento do próprio "
        "período: essa última é apenas referência, e usá-la no cálculo "
        "deixaria o ROAS Projetado idêntico ao Realizado."
    ),
)
taxa = taxa_pct / 100.0

tot = investimento_totais(df_inv)
r = roas_resumo(df_inv, df_exec, taxa_recebimento=taxa)

# ---------------------------------------------------------------------------
# KPIs principais — linha 1: ROAS + Investimento + CPA
# ---------------------------------------------------------------------------
section_title(
    "Resumo do período",
    f"taxa esperada aplicada: {taxa_pct:.0f}% · "
    f"taxa realizada no período (referência): {r['taxa_periodo']*100:.1f}%",
)

c1, c2, c3, c4, c5 = st.columns(5, gap="small")
with c1:
    metric_card_v2(
        "ROAS Projetado",
        f"{r['roas_projetado']:.2f}x",
        hint=f"(montante × {taxa_pct:.0f}%) ÷ investimento",
        accent=True,
    )
with c2:
    metric_card_v2(
        "ROAS Realizado",
        f"{r['roas_realizado']:.2f}x",
        hint="receita já paga ÷ investimento",
    )
with c3:
    metric_card_v2(
        "Investimento total",
        brl(r["investimento"]),
        hint=f"{tot['dias']} dias · média {brl_short(tot['media_dia'])}/dia",
    )
with c4:
    metric_card_v2(
        "Receita Projetada",
        brl(r["receita_projetada"]) if r["receita_projetada"] else "—",
        hint=f"montante × {taxa_pct:.0f}%",
    )
with c5:
    metric_card_v2(
        "CPA",
        brl(r["cac"]) if r["cac"] else "—",
        hint="investimento ÷ vendas",
    )

# Linha 2 — receita realizada, montante e taxa do período (informativos)
c6, c7, c8 = st.columns(3, gap="small")
with c6:
    metric_card_v2(
        "Receita Realizada",
        brl(r["receita"]) if r["receita"] else "—",
        hint=f"receita já recebida · {int_br(r['vendas'])} vendas",
    )
with c7:
    metric_card_v2(
        "Montante",
        brl(r["montante"]) if r["montante"] else "—",
        hint="SUM(montante) · período filtrado",
    )
with c8:
    metric_card_v2(
        "Taxa do período",
        pct(r["taxa_periodo"] * 100),
        hint="receita ÷ montante · só referência; não usada no Projetado",
    )

# ---------------------------------------------------------------------------
# Série principal — Investimento × Receita Projetada × Receita Realizada
# ---------------------------------------------------------------------------
section_title(
    "Investimento × Receita",
    "investimento, receita projetada e receita já realizada no tempo",
)

merged = roas_diario(df_inv, df_exec, taxa_recebimento=taxa)
if merged.empty:
    st.info("Sem intersecção entre investimento e receita no período.")
else:
    # Receita projetada por dia = montante do dia × taxa.
    merged["receita_projetada"] = merged["montante"] * taxa
    st.plotly_chart(
        line(merged, "data_ref",
             ["receita_projetada", "receita", "investimento_total"],
             height=360, money_axis="y"),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# ROAS Projetado × Realizado (mesmo gráfico) + CPA
# ---------------------------------------------------------------------------
section_title("ROAS e CPA no tempo")
cA, cB = st.columns(2, gap="large")
with cA:
    st.markdown(
        "<div class='sec-title' style='margin-top:0;border:none'>"
        "ROAS diário <span class='sub'>projetado vs realizado · maior = melhor</span></div>",
        unsafe_allow_html=True,
    )
    if not merged.empty:
        st.plotly_chart(
            line(merged, "data_ref", ["roas_projetado", "roas_realizado"], height=260),
            use_container_width=True,
        )
with cB:
    st.markdown(
        "<div class='sec-title' style='margin-top:0;border:none'>"
        "CPA diário <span class='sub'>menor = melhor</span></div>",
        unsafe_allow_html=True,
    )
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
            "data_ref":            st.column_config.DateColumn("Data", format="DD/MM/YYYY", pinned=True),
            "investimento_total":  st.column_config.NumberColumn("Investimento", format="R$ %.2f"),
            "receita":             st.column_config.NumberColumn("Receita realizada", format="R$ %.0f"),
            "receita_projetada":   st.column_config.NumberColumn("Receita projetada", format="R$ %.0f"),
            "montante":            st.column_config.NumberColumn("Montante", format="R$ %.0f"),
            "vendas":              st.column_config.NumberColumn("Vendas", format="%d"),
            "roas":                st.column_config.NumberColumn("ROAS Realizado", format="%.2fx"),
            "roas_realizado":      st.column_config.NumberColumn("ROAS Realizado (alias)", format="%.2fx"),
            "roas_projetado":      st.column_config.NumberColumn("ROAS Projetado", format="%.2fx"),
            "cac":                 st.column_config.NumberColumn("CPA", format="R$ %.0f"),
        },
    )
