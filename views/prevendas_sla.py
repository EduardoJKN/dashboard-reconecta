"""Pré-vendas — SLA & Tempo de Resposta (AMOSTRA PARCIAL).

⚠ Página com cobertura limitada. O campo `ext_reconecta.leads.sla` está
preenchido em ~39% dos leads (validado abr/2026: 341 de 884). Os
agregados aqui são **indicativos** — não usar como ranking individual de
SDR nem como SLA contratual. Quando a fonte/regra de SLA for
formalizada, plugamos as métricas que faltam (% dentro do SLA, ranking
por SDR, alertas)."""
import streamlit as st

from src.prevendas_transforms import (
    prevendas_sla_buckets_df,
    prevendas_sla_kpis,
)
from src.repositories import get_prevendas_sla
from src.ui.charts import bar_simple
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import int_br, pct

ctx = start_page(
    title="SLA & Tempo de Resposta",
    subtitle="Tempo de resposta ao lead · cobertura parcial",
    filters=["sdr", "tipo_sdr"],
)

try:
    df_sla = get_prevendas_sla(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar SLA: {e}")
    st.stop()

k = prevendas_sla_kpis(df_sla)

# ---------------------------------------------------------------------------
# Aviso prominente sobre cobertura parcial
# ---------------------------------------------------------------------------
st.warning(
    f"⚠ **Amostra parcial.** Dos **{int_br(k['total_leads'])}** leads do "
    f"período, **{int_br(k['leads_com_sla'])} ({pct(k['cobertura_pct'])})** "
    f"têm `sla` preenchido em `ext_reconecta.leads`. Os agregados abaixo "
    f"são **indicativos**, não devem ser usados como ranking individual "
    f"de SDR nem como SLA contratual."
)

# ---------------------------------------------------------------------------
# Resumo do período
# ---------------------------------------------------------------------------
section_title(
    "Resumo do período (amostra)",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)


def _fmt_minutos(m: float) -> str:
    if not m:
        return "—"
    if m < 60:
        return f"{m:.0f} min".replace(".0 min", " min")
    if m < 1440:
        return f"{m / 60:.1f}h".replace(".", ",")
    return f"{m / 1440:.1f}d".replace(".", ",")


c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2(
        "Tempo médio (amostra)",
        _fmt_minutos(k["tempo_medio_min"]),
        hint=f"mediana {_fmt_minutos(k['tempo_p50_min'])} · "
             f"p90 {_fmt_minutos(k['tempo_p90_min'])}",
        accent=True,
    )
with c2:
    metric_card_v2(
        "% dentro do SLA", "—",
        hint="meta de SLA a definir com o time",
    )
with c3:
    metric_card_v2(
        "Pior tempo registrado",
        _fmt_minutos(k["tempo_max_min"]),
        hint="amostra · maior valor de `sla`",
    )
with c4:
    metric_card_v2(
        "Leads sem SLA registrado",
        int_br(k["leads_sem_sla"]),
        hint=f"de {int_br(k['total_leads'])} leads totais",
    )

# ---------------------------------------------------------------------------
# Distribuição em faixas
# ---------------------------------------------------------------------------
section_title(
    "Distribuição de tempos (amostra)",
    "leads com `sla` preenchido por faixa",
)
buckets = prevendas_sla_buckets_df(k)
if buckets.empty or buckets["qtd"].sum() == 0:
    st.info("Sem leads com SLA preenchido no período.")
else:
    st.plotly_chart(
        bar_simple(buckets, x="faixa", y="qtd", height=280),
        use_container_width=True,
    )
    with st.expander("Tabela de faixas"):
        st.dataframe(
            buckets, use_container_width=True, hide_index=True,
            column_config={
                "faixa": "Faixa",
                "qtd":   st.column_config.NumberColumn("Leads", format="%d"),
            },
        )

# ---------------------------------------------------------------------------
# Ranking por SDR — placeholder
# ---------------------------------------------------------------------------
section_title("Ranking por SDR", "tempo médio · % dentro do SLA por SDR")
st.info(
    "🚧 Ranking individual indisponível na primeira versão. O campo "
    "`sla` em `ext_reconecta.leads` não tem associação direta com o SDR "
    "(nem `sdr_ss` nem `prevendas` da activity). Pra produzir um "
    "ranking confiável precisamos definir: **(a)** qual evento marca o "
    "'1º contato' (qual SDR responde o lead?), **(b)** qual a meta de "
    "SLA, **(c)** se a coluna `sla` é populada de forma uniforme entre "
    "fontes."
)

# ---------------------------------------------------------------------------
# Alertas — placeholder
# ---------------------------------------------------------------------------
section_title("Alertas de SLA", "leads sem resposta dentro do limite")
st.info(
    "🚧 Alertas em tempo real ficam pendentes até definirmos a meta de "
    "SLA e o evento de 1º contato (ex.: timestamp da primeira activity "
    "vinculada ao lead, ou primeiro outbound/inbound contábil)."
)

st.caption(
    "Fonte: `ext_reconecta.leads.sla` (text com inteiros — assumido em "
    "minutos). Cobertura validada em abr/2026: ~39%. Campos correlatos "
    "investigados (`tempo_resposta_lead`, `timestamp_message`, "
    "`dt_hr_agendamento`) não foram úteis: o primeiro está praticamente "
    "vazio, o segundo é o epoch UTC do form submission (mesmo instante "
    "de `created_at`), o terceiro está vazio em abril."
)
