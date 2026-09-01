"""Pré-vendas — Comparecimentos & Oportunidades.

Quebra de leads únicos por classificação (+12 / -12 / Não atua / Sem
classif). Funil agendamentos → comparecimentos → vendas novas. No-show
fica como placeholder até definição da regra (ver caption)."""
import streamlit as st

from src.prevendas_transforms import (
    prevendas_anotar_sdr,
    prevendas_anotar_tipo_sdr_detalhe,
    prevendas_classif_kpis,
    prevendas_diario_filtrado_por_sdr,
    prevendas_normalizar_detalhe,
    prevendas_overview_kpis,
)
from src.parallel_fetch import fetch_named
from src.repositories import (
    get_prevendas_comparecimentos_classif,
    get_prevendas_leads_detalhe_diario,
    get_prevendas_overview_diario,
    get_prevendas_por_sdr,
    get_prevendas_sdrs_oficiais,
)
from src.ui.charts import funnel
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.prevendas_components import render_top_sdr_interativo
from src.ui.theme import int_br, pct

ctx = start_page(
    title="Comparecimentos & Oportunidades",
    subtitle="Reuniões, qualificação +12/-12 e taxas",
    filters=["sdr", "tipo_sdr"],
)

_r, _e = fetch_named({
    "classif": (get_prevendas_comparecimentos_classif, (ctx.data_ini, ctx.data_fim)),
    "diario": (get_prevendas_overview_diario, (ctx.data_ini, ctx.data_fim)),
    "sdr": (get_prevendas_por_sdr, (ctx.data_ini, ctx.data_fim)),
    "detalhe": (get_prevendas_leads_detalhe_diario, (ctx.data_ini, ctx.data_fim)),
    "sdrs_oficiais": (get_prevendas_sdrs_oficiais, ()),
})
if _e:
    _err = next(iter(_e.values()))
    st.error(f"Falha ao consultar Pré-vendas: {_err}")
    st.stop()
df_classif = _r["classif"]
df_diario = _r["diario"]
df_sdr = _r["sdr"]
df_detalhe = _r["detalhe"]
df_sdrs_oficiais = _r["sdrs_oficiais"]

df_sdr = prevendas_anotar_sdr(df_sdr)
df_sdr_filt = ctx.apply_filters(df_sdr, {"sdr": "sdr", "tipo_sdr": "tipo_sdr"})

df_classif_anotado = prevendas_anotar_sdr(df_classif)
df_classif_filt = ctx.refilter(
    df_classif_anotado if df_classif_anotado is not None else df_classif,
    {"sdr": "sdr", "tipo_sdr": "tipo_sdr"},
)

# `df_diario` é agregado sem grão de SDR — recompõe quando há filtro.
df_det_norm = prevendas_anotar_tipo_sdr_detalhe(
    prevendas_normalizar_detalhe(df_detalhe)
)
sdr_sel = list(ctx.selections.get("sdr") or [])
tipo_sdr_sel = list(ctx.selections.get("tipo_sdr") or [])
filtros_header_ativos = bool(sdr_sel or tipo_sdr_sel)

if filtros_header_ativos and df_det_norm is not None and not df_det_norm.empty:
    df_diario_view = prevendas_diario_filtrado_por_sdr(
        df_det_norm, df_diario,
        sdr_sel, tipo_sdr_sel,
        ctx.data_ini, ctx.data_fim,
    )
else:
    df_diario_view = df_diario

ko = prevendas_overview_kpis(df_diario_view)
kc = prevendas_classif_kpis(df_classif_filt)

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
    cancel = (
        int(df_sdr_filt["cancelamentos"].sum())
        if not df_sdr_filt.empty and "cancelamentos" in df_sdr_filt.columns
        else 0
    )
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
    if df_classif_filt is None or df_classif_filt.empty:
        st.caption("Sem leads classificados no período.")
    else:
        st.dataframe(
            df_classif_filt, use_container_width=True, hide_index=True,
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
# Ranking por SDR — modelo unificado (helper compartilhado com Visão Geral
# Pré-vendas e SDRs & Times). Gráfico clicável + painel retrátil de
# detalhe. Default = Comparecimentos (foco da página).
# ---------------------------------------------------------------------------
render_top_sdr_interativo(
    df_sdr_filt=df_sdr_filt,
    df_sdrs_oficiais=df_sdrs_oficiais,
    df_detalhe=df_detalhe,
    metric_options={
        "Comparecimentos":      "comparecimentos",
        "Agendamentos":         "agendamentos",
        "Agendamentos +12":     "agendamentos_mais_12",
        "Agendamentos -12":     "agendamentos_menos_12",
        "Vendas":               "vendas",
        "Cancelados":           "cancelados",
    },
    default_metric_label="Comparecimentos",
    data_ini=ctx.data_ini,
    data_fim=ctx.data_fim,
    key_prefix="prevendas_comparecimentos",
    section_title_text="Ranking por SDR",
    section_subtitle="agendamentos · comparecimentos · % comparecimento",
)

st.caption(
    "**Bucket** = última classificação do e-mail no período "
    "(`classif_final`): +12 / -12 / Não atua / Sem classif. Conta leads "
    "**únicos** (não soma de activities) — um lead que reagendou aparece "
    "1× no agendamento. Vendas atribuídas pela activity → deal → "
    "mix de tipo_venda (mesmo do card Ganhos). **No-show** mantido como `—` "
    "porque o status `Vencida` aparece apenas em meses correntes (em "
    "abril/2026 fechado: 0 Vencidas) — o CRM provavelmente converte pra "
    "Cancelada/Concluída depois. Definição precisa do time. "
    "Filtros do header (SDR / Tipo SDR) aplicam ao Resumo, Funil, "
    "Quebra por classificação e Ranking."
)
