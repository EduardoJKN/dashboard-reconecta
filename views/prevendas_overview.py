"""Pré-vendas — Visão Geral.

Cards consolidados + Tendência diária + Funil 4 etapas + Top SDRs.
SDR primário = `zoho_activities.prevendas` (NULL → 'Sem SDR').
Vendas atribuídas via `what_id` da activity → deal Ganho/Fechado Ganho
+ tipo_venda='Novo cliente' (mesma regra Visão Geral)."""
import streamlit as st

from src.prevendas_transforms import (
    prevendas_funil_etapas,
    prevendas_overview_kpis,
    prevendas_ranking_sdr,
)
from src.repositories import (
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
)
from src.ui.charts import bar_ranked, dual_line, funnel
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import brl, int_br, pct

ctx = start_page(
    title="Visão Geral Pré-vendas",
    subtitle="Performance consolidada do setor",
    filters=["sdr", "tipo_sdr"],
)

try:
    df_diario = get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim)
    df_sdr    = get_prevendas_por_sdr(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar Pré-vendas: {e}")
    st.stop()

k = prevendas_overview_kpis(df_diario)

# ---------------------------------------------------------------------------
# Resumo do período
# ---------------------------------------------------------------------------
section_title(
    "Resumo do período",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4, c5 = st.columns(5, gap="small")
with c1:
    metric_card_v2("Leads recebidos", int_br(k["leads"]),
                   hint="ext_reconecta.leads · únicos por e-mail",
                   accent=True)
with c2:
    metric_card_v2("Consultas no período", int_br(k["agendamentos"]),
                   hint="zoho_activities · Consulta + Indicação")
with c3:
    metric_card_v2("Comparecimentos", int_br(k["comparecimentos"]),
                   hint="status_reuniao = 'Concluída'")
with c4:
    metric_card_v2("Vendas novas", int_br(k["vendas_novas"]),
                   hint="tipo_venda = 'Novo cliente'")
with c5:
    metric_card_v2("Vendas (totais)", int_br(k["vendas"]),
                   hint="todos os tipos · Ganho/Fechado Ganho")

# Linha 2 — financeiro / eficiência
r2c1, r2c2, r2c3, r2c4, r2c5 = st.columns(5, gap="small")
with r2c1:
    metric_card_v2("Faturado / Montante",
                   brl(k["montante"]) if k["montante"] else "—",
                   hint="SUM(amount) zoho_deals")
with r2c2:
    metric_card_v2("Receita",
                   brl(k["receita"]) if k["receita"] else "—",
                   hint="SUM(receita) zoho_deals")
with r2c3:
    metric_card_v2("Ticket médio",
                   brl(k["ticket_medio"]) if k["ticket_medio"] else "—",
                   hint="montante ÷ vendas novas")
with r2c4:
    metric_card_v2("Média móvel (período)",
                   f"{k['media_movel_21d']:.1f}".replace(".", ","),
                   hint="vendas novas ÷ dias do período")
with r2c5:
    metric_card_v2("Taxa de comparecimento",
                   pct(k["taxa_comparecimento"]) if k["taxa_comparecimento"] else "—",
                   hint="comparec ÷ agendamentos")

# ---------------------------------------------------------------------------
# Funil — 4 etapas
# ---------------------------------------------------------------------------
section_title("Funil de pré-vendas",
              "leads → agendamentos → comparecimentos → vendas novas")

labels, values = prevendas_funil_etapas(k)
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
              "agendamentos × comparecimentos × vendas novas")

if df_diario.empty:
    st.info("Sem dados diários no período.")
else:
    st.plotly_chart(
        dual_line(
            df_diario, x="data_ref",
            y_left="agendamentos", y_right="comparecimentos",
            label_left="Agendamentos", label_right="Comparecimentos",
            height=320,
        ),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Top SDRs
# ---------------------------------------------------------------------------
section_title("Top SDRs", "ranking do período · agendamentos")

ranking = prevendas_ranking_sdr(df_sdr)
if ranking.empty:
    st.info("Sem agendamentos no período.")
else:
    st.plotly_chart(
        bar_ranked(ranking, "sdr", "agendamentos", top_n=12, height=320),
        use_container_width=True,
    )

st.caption(
    "**Fontes oficiais.** Leads: `ext_reconecta.leads` (regra Visão "
    "Geral Marketing — daily-distinct por e-mail). Agendamentos / "
    "Comparecimentos: `zoho_activities` `Consulta`/`Indicação` no "
    "período. Vendas: `zoho_deals` Ganho/Fechado Ganho atrelado à "
    "activity via `what_id`. SDR primário: `zoho_activities.prevendas` — "
    "leads/atividades sem SDR atribuído entram como **Sem SDR** "
    "no ranking."
)
