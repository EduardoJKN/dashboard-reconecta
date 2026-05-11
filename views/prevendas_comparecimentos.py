"""Pré-vendas — Comparecimentos & Oportunidades.

Quebra de leads únicos por classificação (+12 / -12 / Não atua / Sem
classif). Funil agendamentos → comparecimentos → vendas novas. No-show
fica como placeholder até definição da regra (ver caption)."""
import streamlit as st

from src.prevendas_transforms import (
    prevendas_anotar_sdr,
    prevendas_classif_kpis,
    prevendas_overview_kpis,
    prevendas_ranking_sdr,
)
from src.repositories import (
    get_prevendas_comparecimentos_classif,
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
)
from src.ui.charts import bar_ranked, funnel
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import int_br, pct

ctx = start_page(
    title="Comparecimentos & Oportunidades",
    subtitle="Reuniões, qualificação +12/-12 e taxas",
    filters=["sdr", "tipo_sdr"],
)

try:
    df_classif = get_prevendas_comparecimentos_classif(ctx.data_ini, ctx.data_fim)
    df_diario  = get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim)
    df_sdr     = get_prevendas_por_sdr(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar Pré-vendas: {e}")
    st.stop()

df_sdr = prevendas_anotar_sdr(df_sdr)
df_sdr_filt = ctx.apply_filters(df_sdr, {"sdr": "sdr", "tipo_sdr": "tipo_sdr"})

ko = prevendas_overview_kpis(df_diario)
kc = prevendas_classif_kpis(df_classif)

# ---------------------------------------------------------------------------
# Resumo do período
# ---------------------------------------------------------------------------
section_title("Resumo do período")

c1, c2, c3, c4, c5 = st.columns(5, gap="small")
with c1:
    metric_card_v2("Agendamentos", int_br(ko["agendamentos"]),
                   hint="activities Consulta/Indicação", accent=True)
with c2:
    metric_card_v2("Comparecimentos", int_br(ko["comparecimentos"]),
                   hint="status_reuniao = 'Concluída'")
with c3:
    metric_card_v2("Taxa de comparecimento",
                   pct(ko["taxa_comparecimento"]) if ko["taxa_comparecimento"] else "—",
                   hint="comparec ÷ agend")
with c4:
    # Cancelamentos: somar `cancelamentos` do df_sdr (já agregado)
    cancel = int(df_sdr["cancelamentos"].sum()) if not df_sdr.empty else 0
    metric_card_v2("Cancelamentos", int_br(cancel),
                   hint="status_reuniao = 'Cancelada'")
with c5:
    metric_card_v2("No-shows", "—",
                   hint="regra a definir · `Vencida` aparece só em mês "
                        "corrente; CRM converte depois")

# ---------------------------------------------------------------------------
# Funil — etapas absolutas (reuniões/leads únicos)
# ---------------------------------------------------------------------------
section_title("Funil de comparecimento",
              "agendamentos → comparecimentos → vendas novas")

labels = ["Agendamentos", "Comparecimentos", "Vendas novas"]
values = [
    float(ko["agendamentos"]),
    float(ko["comparecimentos"]),
    float(ko["vendas_novas"]),
]
if all(v == 0 for v in values):
    st.info("Sem dados no período.")
else:
    st.plotly_chart(
        funnel(labels, values, height=300, show_dropoff=True),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Quebra por classificação (+12 / -12 / Não atua)
# ---------------------------------------------------------------------------
section_title("Quebra por classificação",
              "leads únicos com agend / comparec / venda nova por bucket")

q1, q2, q3, q4 = st.columns(4, gap="small")
with q1:
    metric_card_v2("Comparec. +12", int_br(kc["comparec_mais_12"]),
                   hint=f"de {int_br(kc['agend_mais_12'])} agendamentos +12")
with q2:
    metric_card_v2("Comparec. -12", int_br(kc["comparec_menos_12"]),
                   hint=f"de {int_br(kc['agend_menos_12'])} agendamentos -12")
with q3:
    metric_card_v2("Taxa conversão +12",
                   pct(kc["taxa_venda_mais_12"]) if kc["taxa_venda_mais_12"] else "—",
                   hint="vendas novas +12 ÷ comparec +12", accent=True)
with q4:
    metric_card_v2("Taxa conversão -12",
                   pct(kc["taxa_venda_menos_12"]) if kc["taxa_venda_menos_12"] else "—",
                   hint="vendas novas -12 ÷ comparec -12")

# Tabela detalhada por (sdr, bucket)
with st.expander("Tabela detalhada — SDR × bucket de classificação"):
    if df_classif is None or df_classif.empty:
        st.caption("Sem leads classificados no período.")
    else:
        st.dataframe(
            df_classif, use_container_width=True, hide_index=True,
            column_config={
                "sdr": "SDR",
                "classif_final": "Classif. crua",
                "bucket": "Bucket",
                "leads_com_agend": st.column_config.NumberColumn(
                    "Leads c/ agend.", format="%d"),
                "leads_com_compar": st.column_config.NumberColumn(
                    "Leads c/ compar.", format="%d"),
                "leads_com_venda_nova": st.column_config.NumberColumn(
                    "Leads c/ venda nova", format="%d"),
            },
        )

# ---------------------------------------------------------------------------
# Ranking por SDR — agendamentos · comparec · taxa
# ---------------------------------------------------------------------------
section_title("Ranking por SDR",
              "agendamentos · comparecimentos · % comparecimento")

ranking = prevendas_ranking_sdr(df_sdr_filt)
if ranking.empty:
    st.info("Sem dados pra os filtros aplicados.")
else:
    st.plotly_chart(
        bar_ranked(ranking, "sdr", "comparecimentos", top_n=12, height=320),
        use_container_width=True,
    )

st.caption(
    "**Bucket** = última classificação do e-mail no período "
    "(`classif_final`): +12 / -12 / Não atua / Sem classif. Conta leads "
    "**únicos** (não soma de activities) — um lead que reagendou aparece "
    "1× no agendamento. Vendas novas atribuídas pela activity → deal → "
    "filtro tipo_venda='Novo cliente'. **No-show** mantido como `—` "
    "porque o status `Vencida` aparece apenas em meses correntes (em "
    "abril/2026 fechado: 0 Vencidas) — o CRM provavelmente converte pra "
    "Cancelada/Concluída depois. Definição precisa do time."
)
