"""Pré-vendas — Notificações de Vendas (substitui a antiga SLA & Tempo de Resposta).

Origem:
  - `assistencial.controle_notificacao_vendas` (welcome/onboarding
    disparado pelo Customer Success) + cruzamento opcional com
    `zoho.crm_negocios` (priority `id_negocio > email`).
  - `ext_reconecta.leads` (mesma base de "Leads totais" da Visão Geral)
    com tentativa de associação ao SDR via `zoho_activities.prevendas`
    e `zoho_deals.sdr_ss`. Detalhes em
    `src/queries/notificacoes_leads_sdr.sql`.

⚠ Esta página NÃO mede SLA real nem tempo de resposta — só notificações,
leads repassados, e o vínculo desses registros com o funil comercial.
A entrada no menu segue como "SLA & Tempo de Resposta" para preservar a
navegação; o título dentro da página é fiel à fonte.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.repositories import (
    get_jornada_lead_venda,
    get_notificacoes_leads_sdr,
    get_prevendas_notificacoes_vendas,
)
from src.team_classification import SEM_SDR_LABEL, classify_sdr
from src.ui.charts import bar_simple
from src.ui.components import metric_card_v2, section_title
from src.ui.page import start_page
from src.ui.theme import PALETTE, int_br, pct

SEM_SDR_DISPLAY = "Sem SDR identificado"


def _anotar_sdr(df: pd.DataFrame, sdr_col: str = "sdr") -> pd.DataFrame:
    """Preenche `sdr` ausente com 'Sem SDR identificado' e deriva
    `tipo_sdr` via classificação canônica. O `tipo_sdr` mantém o label
    oficial `Sem SDR` (alinhado com as demais páginas) para que o filtro
    global de Tipo SDR funcione igual em todo o dashboard."""
    if df is None or df.empty:
        return df
    out = df.copy()
    serie = out[sdr_col] if sdr_col in out.columns else pd.Series(
        [None] * len(out), index=out.index
    )
    out["sdr"] = serie.apply(
        lambda s: s if isinstance(s, str) and s.strip() else SEM_SDR_DISPLAY
    )
    out["tipo_sdr"] = out["sdr"].apply(
        lambda s: SEM_SDR_LABEL if s == SEM_SDR_DISPLAY else classify_sdr(s)
    )
    return out


# ---------------------------------------------------------------------------
# Helpers da seção "Jornada do lead até a venda"
# ---------------------------------------------------------------------------
ETAPAS_JORNADA: list[tuple[str, str, str]] = [
    # (label, ts_origem, ts_destino)
    ("Lead → Deal",            "ts_lead",              "ts_deal"),
    ("Deal → Agendamento",     "ts_deal",              "ts_agendamento_criado"),
    ("Agendamento → Reunião",  "ts_agendamento_criado", "ts_reuniao_agendada"),
    ("Reunião → Venda",        "ts_comparecimento",    "ts_venda"),
    ("Lead → Venda (total)",   "ts_lead",              "ts_venda"),
]


def _formatar_duracao(dias: float | None) -> str:
    """Recebe duração em DIAS (float) e devolve string curta humana."""
    if dias is None or pd.isna(dias):
        return "—"
    if dias < 0:
        return "—"
    if dias < 1:
        horas = dias * 24
        if horas < 1:
            mins = max(1, int(round(horas * 60)))
            return f"{mins} min"
        return f"{horas:.1f} h"
    if dias < 30:
        return f"{dias:.1f} d"
    meses = dias / 30
    return f"{meses:.1f} mês"


def _jornada_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula média, mediana, n válido e % cobertura por etapa.
    Devolve 1 row por etapa, na ordem fixa de ETAPAS_JORNADA."""
    universo = len(df) if df is not None else 0
    rows = []
    for label, origem, destino in ETAPAS_JORNADA:
        if (df is None or df.empty
                or origem not in df.columns or destino not in df.columns):
            rows.append({
                "etapa": label,
                "media_dias": None,
                "mediana_dias": None,
                "n_validos": 0,
                "pct_cobertura": 0.0,
            })
            continue
        delta = (df[destino] - df[origem]).dt.total_seconds() / 86400.0
        delta = delta[delta.notna() & (delta >= 0)]
        n = int(len(delta))
        rows.append({
            "etapa": label,
            "media_dias": float(delta.mean()) if n else None,
            "mediana_dias": float(delta.median()) if n else None,
            "n_validos": n,
            "pct_cobertura": (n / universo * 100) if universo else 0.0,
        })
    return pd.DataFrame(rows)


def _render_jornada_chart(stats: pd.DataFrame, metric_col: str) -> go.Figure:
    """Barras horizontais com a duração em dias. Ordem = ordem de
    ETAPAS_JORNADA (Plotly inverte y por padrão; usamos
    autorange='reversed' pra manter ordem visual top→bottom)."""
    labels = stats["etapa"].tolist()
    vals = [float(v) if pd.notna(v) else 0.0 for v in stats[metric_col]]
    text = [_formatar_duracao(v) for v in stats[metric_col]]
    is_total = [lbl.startswith("Lead → Venda") for lbl in labels]
    colors = [PALETTE["wine"] if t else PALETTE["gold"] for t in is_total]

    fig = go.Figure(go.Bar(
        y=labels,
        x=vals,
        orientation="h",
        marker=dict(color=colors,
                    line=dict(color=PALETTE["border_strong"], width=0.5)),
        text=text,
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{x:.2f} dias<extra></extra>",
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=12, r=80, t=20, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PALETTE["card"],
        font=dict(color=PALETTE["text"], family="Inter", size=12),
        showlegend=False,
    )
    fig.update_yaxes(autorange="reversed", showgrid=False,
                     color=PALETTE["text_subtle"])
    fig.update_xaxes(showgrid=True, gridcolor=PALETTE["border"],
                     color=PALETTE["text_subtle"],
                     title="dias")
    return fig


ctx = start_page(
    title="Notificações de Vendas",
    subtitle="Notificações + leads repassados, com tentativa de associação ao SDR",
    filters=["sdr", "tipo_sdr"],
)

try:
    df_notif_raw = get_prevendas_notificacoes_vendas(ctx.data_ini, ctx.data_fim)
    df_leads_raw = get_notificacoes_leads_sdr(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar dados: {e}")
    st.stop()

df_leads = _anotar_sdr(df_leads_raw, sdr_col="sdr")
df_notif = _anotar_sdr(df_notif_raw, sdr_col="sdr_ss")

# Renderiza os filtros do header usando o universo de SDR da nova tabela
# (lp_form.leads + deals do período — superset razoável). df_notif usa
# `refilter` para reaproveitar as mesmas seleções sem re-renderizar.
df_leads_filt = ctx.apply_filters(df_leads, {"sdr": "sdr", "tipo_sdr": "tipo_sdr"})
df_notif_filt = ctx.refilter(df_notif, {"sdr": "sdr", "tipo_sdr": "tipo_sdr"})

# ---------------------------------------------------------------------------
# Disclaimer permanente — explicar fonte e limitações antes dos números.
# ---------------------------------------------------------------------------
st.info(
    "Esta página combina duas fontes. **Notificações registradas** vêm de "
    "`assistencial.controle_notificacao_vendas` (welcome/onboarding do CS) "
    "com vínculo opcional ao funil comercial via `zoho.crm_negocios`. "
    "**Leads repassados para SDRs** vêm de `ext_reconecta.leads` (mesma base "
    "de 'Leads totais' da Visão Geral), com tentativa de associação ao SDR "
    "via deal/atividade Zoho. **Registros sem vínculo / sem SDR identificado "
    "não significam ausência de atuação comercial** — alguns leads/deals podem "
    "ainda não estar registrados ou podem pertencer a fluxos de Social "
    "Selling/pós-venda que não passam pelas esteiras de welcome/atividade."
)

# ===========================================================================
# Seção 1 — Leads repassados para SDRs (NOVA)
# ===========================================================================
section_title(
    "Leads repassados para SDRs",
    "Leads recebidos no período com tentativa de associação ao SDR responsável.",
)

st.caption(
    "A associação ao SDR depende de vínculo com CRM/deal ou regra de "
    "repasse disponível. Leads sem vínculo aparecem como **Sem SDR "
    "identificado**. SDR primário: atividade Zoho (`activity.prevendas`). "
    "Fallback: `zoho_deals.sdr_ss` resolvido pelo `zoho_users`."
)

if df_leads.empty:
    st.info("Sem leads no período selecionado.")
else:
    total_leads = len(df_leads)
    com_sdr     = int(df_leads["tem_sdr_identificado"].fillna(False).sum())
    com_deal    = int(df_leads["tem_deal_crm"].fillna(False).sum())
    sem_sdr     = total_leads - com_sdr
    pct_sdr     = (com_sdr / total_leads * 100) if total_leads else 0.0
    pct_deal    = (com_deal / total_leads * 100) if total_leads else 0.0

    l1, l2, l3, l4, l5 = st.columns(5, gap="small")
    with l1:
        metric_card_v2("Leads no período", int_br(total_leads), accent=True,
                       hint="daily-distinct (data, email) — mesma regra da Visão Geral")
    with l2:
        metric_card_v2("Com deal pareado", int_br(com_deal),
                       hint="lead → deal por zoho_id > session_id > email")
    with l3:
        metric_card_v2("% com deal", pct(pct_deal),
                       hint="com deal ÷ total")
    with l4:
        metric_card_v2("Com SDR identificado", int_br(com_sdr),
                       hint="activity.prevendas ou deal.sdr_ss preenchido")
    with l5:
        metric_card_v2("Sem SDR identificado", int_br(sem_sdr),
                       hint="nem atividade nem deal trouxeram SDR")

    st.caption(
        f"{int_br(len(df_leads_filt))} de {int_br(total_leads)} leads "
        f"no recorte filtrado (SDR / Tipo SDR no header)."
    )

    if df_leads_filt.empty:
        st.info("Sem leads no recorte filtrado.")
    else:
        tabela_leads = df_leads_filt.copy()
        tabela_leads = tabela_leads.sort_values("created_at", ascending=False)
        tabela_leads.insert(0, "#", range(1, len(tabela_leads) + 1))

        cols_map_leads = [
            ("#",                    "#"),
            ("created_at",           "Data/hora"),
            ("nome",                 "Nome"),
            ("email",                "E-mail"),
            ("telefone",             "Telefone"),
            ("classificado",         "Classificado"),
            ("sdr",                  "SDR"),
            ("tipo_sdr",             "Tipo SDR"),
            ("fonte_associacao_sdr", "Fonte da associação"),
            ("stage",                "Stage"),
            ("tipo_venda",           "Tipo venda"),
            ("lead_classification",  "Lead classification"),
            ("qualificacao",         "Qualificação"),
            ("executiva_vendas",     "Executiva de vendas"),
            ("utm_source",           "utm_source"),
            ("utm_medium",           "utm_medium"),
            ("utm_campaign",         "utm_campaign"),
            ("utm_content",          "utm_content"),
            ("utm_term",             "utm_term"),
            ("page_pathname",        "Página"),
            ("lead_source",          "Origem"),
            ("lp_variante",          "LP variante"),
            ("zoho_id",              "Zoho ID (lead)"),
            ("session_id",           "Session ID"),
            ("deal_id",              "Deal ID"),
        ]
        cols_presentes = [c for c, _ in cols_map_leads if c in tabela_leads.columns]
        tabela_leads_view = tabela_leads[cols_presentes].rename(
            columns={c: lbl for c, lbl in cols_map_leads if c in cols_presentes}
        )

        column_config_leads = {
            "#": st.column_config.NumberColumn("#", format="%d"),
        }
        if "Data/hora" in tabela_leads_view.columns:
            column_config_leads["Data/hora"] = st.column_config.DatetimeColumn(
                "Data/hora", format="DD/MM/YYYY HH:mm"
            )

        st.dataframe(
            tabela_leads_view,
            use_container_width=True,
            hide_index=True,
            column_config=column_config_leads,
        )

# ===========================================================================
# Seção intermediária — Jornada do lead até a venda (NOVA)
# ===========================================================================
section_title(
    "Jornada do lead até a venda",
    "Tempo médio em cada etapa — considera apenas deals ganhos no período "
    "(stage Ganho/Fechado Ganho · tipo_venda Novo cliente).",
)

try:
    df_jornada_raw = get_jornada_lead_venda(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.error(f"Falha ao consultar jornada: {e}")
    df_jornada_raw = pd.DataFrame()

df_jornada = _anotar_sdr(df_jornada_raw, sdr_col="sdr")
df_jornada_filt = ctx.refilter(df_jornada, {"sdr": "sdr", "tipo_sdr": "tipo_sdr"})

n_deals = len(df_jornada_filt)

st.caption(
    "Etapas com **n < 10** ou **cobertura < 20%** ficam marcadas como "
    "pouco confiáveis. Lead→Venda só considera deals ganhos com lead pareado; "
    "etapas intermediárias usam apenas registros com os dois timestamps preenchidos."
)

if df_jornada.empty:
    st.info(
        "Sem deals ganhos no período selecionado — não há jornada para calcular."
    )
elif df_jornada_filt.empty:
    st.info("Sem deals ganhos no recorte dos filtros SDR / Tipo SDR.")
else:
    metric_choice = st.radio(
        "Métrica",
        options=["Média", "Mediana"],
        horizontal=True,
        index=0,
        key="jornada_metric",
    )
    metric_col = "media_dias" if metric_choice == "Média" else "mediana_dias"

    stats = _jornada_stats(df_jornada_filt)

    # Cards — um por etapa
    cols_cards = st.columns(len(ETAPAS_JORNADA), gap="small")
    for i, (col, row) in enumerate(zip(cols_cards, stats.itertuples(index=False))):
        with col:
            val = row.media_dias if metric_choice == "Média" else row.mediana_dias
            confiavel = (row.n_validos >= 10 and row.pct_cobertura >= 20.0)
            valor_str = _formatar_duracao(val) if confiavel else "—"
            hint = (
                f"n={int_br(row.n_validos)} · cobertura {pct(row.pct_cobertura)}"
                if confiavel
                else f"pouco confiável (n={row.n_validos}, "
                     f"cobertura {pct(row.pct_cobertura)})"
            )
            metric_card_v2(
                row.etapa,
                valor_str,
                accent=row.etapa.startswith("Lead → Venda"),
                hint=hint,
            )

    st.caption(
        f"{int_br(n_deals)} deals ganhos no recorte "
        f"({metric_choice.lower()}). Valores em dias quando ≥ 1d, "
        "horas/minutos abaixo disso."
    )

    # Gráfico
    st.plotly_chart(
        _render_jornada_chart(stats, metric_col),
        use_container_width=True,
    )

    # Tabela detalhada
    tabela_stats = stats.copy()
    tabela_stats["Etapa"]            = tabela_stats["etapa"]
    tabela_stats["Média"]            = tabela_stats["media_dias"].apply(_formatar_duracao)
    tabela_stats["Mediana"]          = tabela_stats["mediana_dias"].apply(_formatar_duracao)
    tabela_stats["n válidos"]        = tabela_stats["n_validos"].apply(int_br)
    tabela_stats["% cobertura"]      = tabela_stats["pct_cobertura"].apply(pct)
    tabela_stats["Confiável"]        = tabela_stats.apply(
        lambda r: (r["n_validos"] >= 10 and r["pct_cobertura"] >= 20.0),
        axis=1,
    )
    st.dataframe(
        tabela_stats[["Etapa", "Média", "Mediana",
                      "n válidos", "% cobertura", "Confiável"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Confiável": st.column_config.CheckboxColumn("Confiável"),
        },
    )

# ===========================================================================
# Seção 2 — Notificações registradas (existente)
# ===========================================================================
if df_notif.empty:
    st.caption("Não há notificações em controle_notificacao_vendas para o período.")
else:
    # ---------------------------------------------------------------------------
    # Filtros locais (acima da tabela e dos gráficos de notificações)
    # ---------------------------------------------------------------------------
    section_title(
        "Filtros das notificações",
        "aplicam-se à tabela e aos gráficos de notificações abaixo",
    )

    cs_options    = sorted(df_notif_filt["cs_nome"].dropna().astype(str).unique().tolist())
    stage_options = sorted(df_notif_filt["stage_deal"].dropna().astype(str).unique().tolist())

    f1, f2, f3 = st.columns(3, gap="small")
    with f1:
        status_vinculo = st.selectbox(
            "Status de vínculo",
            options=["Todos", "Com vínculo comercial", "Sem vínculo comercial"],
            index=0,
            key="notif_status_vinculo",
        )
    with f2:
        status_prevendas = st.selectbox(
            "Pré-vendas",
            options=["Todos", "Apenas com Pré-vendas identificado",
                     "Sem Pré-vendas identificado"],
            index=0,
            key="notif_status_prevendas",
        )
    with f3:
        tipo_venda_sel = st.multiselect(
            "Tipo de venda",
            options=["Novo cliente", "Ascensão", "Renovação",
                     "Renovação antecipada", "Não informado"],
            default=[],
            key="notif_tipo_venda",
        )

    f4, f5 = st.columns(2, gap="small")
    with f4:
        cs_sel = st.multiselect(
            "CS",
            options=cs_options,
            default=[],
            key="notif_cs",
        )
    with f5:
        stage_sel = st.multiselect(
            "Stage do deal",
            options=stage_options,
            default=[],
            key="notif_stage",
        )

    # Aplica filtros locais SOBRE o df já recortado pelos filtros do header
    mask = pd.Series(True, index=df_notif_filt.index)
    if status_vinculo == "Com vínculo comercial":
        mask &= df_notif_filt["tem_vinculo_comercial"].fillna(False)
    elif status_vinculo == "Sem vínculo comercial":
        mask &= ~df_notif_filt["tem_vinculo_comercial"].fillna(False)

    if status_prevendas == "Apenas com Pré-vendas identificado":
        mask &= df_notif_filt["tem_prevendas_identificado"].fillna(False)
    elif status_prevendas == "Sem Pré-vendas identificado":
        mask &= ~df_notif_filt["tem_prevendas_identificado"].fillna(False)

    if tipo_venda_sel:
        tipo_norm = df_notif_filt["tipo_venda_notif"].fillna("Não informado").astype(str)
        mask &= tipo_norm.isin(tipo_venda_sel)

    if cs_sel:
        mask &= df_notif_filt["cs_nome"].astype(str).isin(cs_sel)

    if stage_sel:
        mask &= df_notif_filt["stage_deal"].astype(str).isin(stage_sel)

    df_view = df_notif_filt[mask].copy()
    st.caption(
        f"{int_br(len(df_view))} de {int_br(len(df_notif))} notificações "
        "no recorte filtrado (header + filtros locais)."
    )

    # ---------------------------------------------------------------------------
    # Tabela principal — notificações
    # ---------------------------------------------------------------------------
    section_title(
        "Notificações registradas",
        "Registros de notificações/vendas vindos da controle_notificacao_vendas.",
    )

    if df_view.empty:
        st.info("Sem notificações no recorte filtrado.")
    else:
        tabela = df_view.copy()
        tabela.insert(0, "#", range(1, len(tabela) + 1))

        cols_map = [
            ("#", "#"),
            ("dt_criacao", "Data/hora"),
            ("nome", "Nome"),
            ("email", "E-mail"),
            ("telefone", "Telefone"),
            ("tipo_venda_notif", "Tipo venda (notif)"),
            ("welcome", "Welcome"),
            ("venda_notificada", "Venda notif."),
            ("cs_nome", "CS"),
            ("vendedora_resolvida", "Vendedora (id_vendedora)"),
            ("metodo_match", "Match"),
            ("deal_id_match", "Deal Zoho pareado"),
            ("stage_deal", "Stage"),
            ("tipo_venda_deal", "Tipo venda (deal)"),
            ("sdr_ss", "SDR/Pré-vendas"),
            ("tipo_sdr", "Tipo SDR"),
            ("closer", "Closer"),
            ("executiva_vendas", "Executiva de vendas"),
            ("owner_deal", "Owner do deal"),
            ("origem_lead", "Origem do lead"),
            ("funil_origem", "Funil origem"),
            ("id_negocio_notif", "ID negócio (notif)"),
            ("id_negocio_pos", "ID negócio (pós)"),
        ]
        cols_presentes = [orig for orig, _ in cols_map if orig in tabela.columns]
        tabela_view = tabela[cols_presentes].rename(
            columns={orig: label for orig, label in cols_map if orig in cols_presentes}
        )

        column_config = {
            "#": st.column_config.NumberColumn("#", format="%d"),
        }
        if "Data/hora" in tabela_view.columns:
            column_config["Data/hora"] = st.column_config.DatetimeColumn(
                "Data/hora", format="DD/MM/YYYY HH:mm"
            )
        if "Welcome" in tabela_view.columns:
            column_config["Welcome"] = st.column_config.CheckboxColumn("Welcome")

        st.dataframe(
            tabela_view,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )

    # ---------------------------------------------------------------------------
    # Gráficos — notificações
    # ---------------------------------------------------------------------------
    section_title("Notificações por dia", "recorte filtrado")

    if df_view.empty:
        st.caption("Sem dados para o gráfico no recorte atual.")
    else:
        por_dia = (
            df_view.assign(data=df_view["dt_criacao"].dt.date)
                    .groupby("data", as_index=False)
                    .size()
                    .rename(columns={"size": "qtd"})
                    .sort_values("data")
        )
        st.plotly_chart(
            bar_simple(por_dia, x="data", y="qtd", height=260),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Rodapé — limitações documentadas
# ---------------------------------------------------------------------------
st.caption(
    "**Limitações.** *Notificações*: cruzamento com `zoho.crm_negocios` por "
    "priority `id_negocio > email` cobre ~66% das notificações no histórico "
    "completo; **Social Sellers** (Geovanna Souza, Estefany Nascimento, "
    "Isabella Esbell) raramente aparecem como `sdr_ss` desses deals — não "
    "significa ausência de atuação. *Leads repassados*: SDR vem da cascata "
    "`activity.prevendas > deal.sdr_ss`; leads que ainda não viraram deal "
    "ou cuja atividade ainda não foi registrada aparecem como **Sem SDR "
    "identificado**. **Esta página não mede SLA real** (tempo de resposta "
    "SDR → lead). Quando uma fonte confiável de SLA for definida, criamos "
    "uma página dedicada."
)
