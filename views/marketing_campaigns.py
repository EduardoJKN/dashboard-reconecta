"""Campanhas — performance por campanha em mídia paga (Meta, Google, Pinterest).

Consome:
    bi.vw_mkt_campanhas — invest/imp/cliques/alcance/objetivo por campanha
    bi.vw_mkt_funil     — leads/qualif por canal (preenche KPIs e gráfico)

Os 3 canais pagos sempre aparecem no filtro, mesmo quando zerados — Pinterest
e Google podem não ter volume hoje, e o time pediu para preservar a estrutura
da página em qualquer cenário."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_campanha_cobertura,
    get_mkt_campanha_funil,
    get_mkt_campanhas,
    get_mkt_campanhas_leads_canal_diario,
    get_mkt_campanhas_leads_por_utm,
    get_mkt_funil,
    get_mkt_paginas_variantes,
)
from src.marketing_safe import safe_run
from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_leads_visao_geral,
)
from src.marketing_transforms import (
    CANAIS_PAGOS,
    agregar_campanhas_por_utm,
    campanha_funil_etapas,
    campanha_funil_kpis,
    campanha_utm_kpis,
    campanhas_diario_v2,
    campanhas_kpis,
    campanhas_leads_canal_kpis,
    campanhas_objetivo,
    campanhas_tabela_ativas,
    campanhas_tabela_total_row,
    cobertura_atribuicao_kpis,
    compara_campanhas_utm,
    filtro_canais_padrao,
    lista_campanhas_funil,
    lista_campanhas_por_utm,
)
from src.transforms import _safe_div
from src.ui.charts import donut, last_point_text
from src.ui.components import metric_card_v2, section_title
from src.ui.marketing_components import render_funil_selecionado
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, int_br, pct

# ---------------------------------------------------------------------------
# Header + filtros (período + canal — só os 3 pagos)
# ---------------------------------------------------------------------------
ctx = start_page(
    title="Campanhas",
    subtitle="Performance por campanha em mídia paga",
    filters=["canal"],
)

col_map = {"canal": "canal"}

# Força os 3 canais pagos a aparecerem no filtro mesmo quando algum estiver
# sem dados no período. Sem isso, Pinterest/Google sumiriam da UI quando
# zerados, e o usuário pediu explicitamente para preservar a estrutura.
ctx.apply_filters(filtro_canais_padrao(CANAIS_PAGOS), col_map)

# ---------------------------------------------------------------------------
# Carga (com fallback defensivo se views ausentes)
# ---------------------------------------------------------------------------
df_camp_all = safe_run(
    lambda: get_mkt_campanhas(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_campanhas",
)
df_funil_all = safe_run(
    lambda: get_mkt_funil(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_funil",
)
# Fonte oficial alinhada com Visão Geral — leads/qualif por canal pela regra
# canal_final (last_row do e-mail). Substitui bi.vw_mkt_leads_classificacao
# nos cards de Volume e CPL e na Tendência diária. NÃO afeta tabela
# "Campanhas ativas" / donut "Por objetivo" / seção "Comparar campanhas",
# que continuam usando bi.vw_mkt_campanhas e a mart de atribuição.
df_leads_canal_diario_all = safe_run(
    lambda: get_mkt_campanhas_leads_canal_diario(ctx.data_ini, ctx.data_fim),
    view_label="bi_mkt.vw_visao_geral_canal_base (canal-diario)",
)
# Leads por campanha — match campaign_name = utm_campaign para enriquecer
# a tabela "Campanhas ativas". Sem grão de canal (1 linha por utm_campaign
# normalizado). Não afeta cards/Tendência diária/Comparar campanhas.
df_leads_por_utm = safe_run(
    lambda: get_mkt_campanhas_leads_por_utm(ctx.data_ini, ctx.data_fim),
    view_label="ext_reconecta.leads (por utm_campaign)",
)
df_camp = (
    ctx.refilter(df_camp_all, col_map) if not df_camp_all.empty else df_camp_all
)
df_funil = (
    ctx.refilter(df_funil_all, col_map) if not df_funil_all.empty else df_funil_all
)
# Lista de canais selecionados no header — base do filtro do novo source.
# `canais_sel` vazio = todos os canais pagos seedados pelo filtro.
canais_sel: list[str] = list(ctx.selections.get("canal") or list(CANAIS_PAGOS))

# ---------------------------------------------------------------------------
# KPIs financeiros
# ---------------------------------------------------------------------------
# campanhas_kpis() carrega invest/impressões/cliques/CTR/CPC do grão de
# campanhas (`bi.vw_mkt_campanhas`). Os campos de leads e CPL produzidos
# por essa função (e que vinham de bi.vw_mkt_leads_classificacao / vw_mkt_funil)
# são SOBRESCRITOS abaixo pelos números canal-aware da fonte oficial Visão
# Geral. `investimento_dia` também é recalculado com denominador =
# `(data_fim - data_ini).days + 1` (total de dias do período), substituindo
# a regra antiga "dias com invest > 0".
k = campanhas_kpis(df_camp, df_funil, None)  # df_classif_canal=None → ignora fallback antigo

# Override leads/qualif/+12/-12 com a fonte oficial (mesma regra da
# Visão Geral por canal). canais_sel já restrito a Meta/Google/Pinterest.
kc = campanhas_leads_canal_kpis(df_leads_canal_diario_all, canais_sel)
k["leads"]                 = kc["leads_totais"]
k["leads_qualificados"]    = kc["leads_qualificados"]
k["leads_qualif_mais_12"]  = kc["leads_mais_12"]
k["leads_qualif_menos_12"] = kc["leads_menos_12"]
k["cpl"]                   = _safe_div(k["investimento"], k["leads"])
k["cpl_qualificado"]       = _safe_div(k["investimento"], k["leads_qualificados"])

# Investimento / dia → denominador = total de dias do período (mesma regra
# da Visão Geral). Antes era "nº de dias com invest > 0".
total_dias = (ctx.data_fim - ctx.data_ini).days + 1
k["investimento_dia"] = _safe_div(k["investimento"], total_dias)

section_title(
    "Financeiro",
    f"{ctx.data_ini.strftime('%d/%m/%Y')} → {ctx.data_fim.strftime('%d/%m/%Y')}",
)

c1, c2, c3, c4 = st.columns(4, gap="small")
with c1:
    metric_card_v2(
        "Investimento",
        brl(k["investimento"], casas=2),
        hint="Meta + Google + Pinterest (canais filtrados)",
        accent=True,
    )
with c2:
    metric_card_v2(
        "Investimento / dia",
        brl(k["investimento_dia"], casas=2),
        hint=f"invest ÷ {total_dias} dia{'s' if total_dias != 1 else ''}",
    )
with c3:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2),
        hint="invest ÷ leads totais",
    )
with c4:
    metric_card_v2(
        "CPL qualificado",
        brl(k["cpl_qualificado"], casas=2),
        hint="invest ÷ qualificados (+12 ou -12)",
    )

# ---------------------------------------------------------------------------
# KPIs operacionais
# ---------------------------------------------------------------------------
section_title("Volume", "leads e impressões no período")

s1, s2, s3 = st.columns(3, gap="small")
with s1:
    metric_card_v2(
        "Leads totais",
        int_br(k["leads"]),
        hint="bi_mkt.vw_visao_geral_canal_base · canal-aware",
    )
with s2:
    metric_card_v2(
        "Leads qualificados",
        int_br(k["leads_qualificados"]),
        hint=f"+12: {int_br(k['leads_qualif_mais_12'])} · "
             f"-12: {int_br(k['leads_qualif_menos_12'])}",
    )
with s3:
    metric_card_v2(
        "Impressões",
        int_br(k["impressoes"]),
        hint=f"CTR {pct(k['ctr'], casas=2)} · CPC {brl(k['cpc'], casas=2)}",
    )

# ---------------------------------------------------------------------------
# Funil da campanha selecionada — usa o mesmo helper compartilhado com a
# página Criativos, só muda o grão (campaign_name vs ad_name) e a chave de
# match (utm_campaign vs utm_content). Mesmas regras: e-mail-único por
# entidade; lead → deal priority `zoho_id > session_id > email`;
# deal → activity via what_id; venda nova = stage Ganho/Fechado Ganho +
# tipo_venda Novo cliente.
# ---------------------------------------------------------------------------
df_camp_funil = safe_run(
    lambda: get_mkt_campanha_funil(ctx.data_ini, ctx.data_fim),
    view_label="mkt_campanha_funil",
)

# Totais OFICIAIS do período — mesma lógica documentada em
# views/marketing_creatives.py. Cache compartilhado com Visão Geral.
_df_leads_oficial_camp = safe_run(
    lambda: get_leads_visao_geral(ctx.data_ini, ctx.data_fim),
    view_label="leads_visao_geral",
)
_leads_totais_oficial_camp = (
    int(len(_df_leads_oficial_camp))
    if _df_leads_oficial_camp is not None and not _df_leads_oficial_camp.empty
    else None
)

_df_exec_oficial_camp = safe_run(
    lambda: get_executivas(ctx.data_ini, ctx.data_fim),
    view_label="dashboard_executivas",
)
_vendas_novas_oficial_camp = (
    int(_df_exec_oficial_camp["vendas"].fillna(0).sum())
    if (_df_exec_oficial_camp is not None and not _df_exec_oficial_camp.empty
        and "vendas" in _df_exec_oficial_camp.columns) else None
)

_df_inv_oficial_camp = safe_run(
    lambda: get_investimento_diario(ctx.data_ini, ctx.data_fim),
    view_label="investimento_diario",
)
_investimento_oficial_camp = (
    float(_df_inv_oficial_camp["investimento_total"].fillna(0).sum())
    if (_df_inv_oficial_camp is not None and not _df_inv_oficial_camp.empty
        and "investimento_total" in _df_inv_oficial_camp.columns) else None
)

render_funil_selecionado(
    df_funil=df_camp_funil,
    key_col="campaign_name_norm",
    entity_label="Campanha",
    section_title_text="Funil da campanha selecionada",
    sel_state_key="camp_funil_selecionado",
    lista_fn=lambda df, sb: lista_campanhas_funil(
        df, sb,
        leads_totais_oficial=_leads_totais_oficial_camp,
        vendas_novas_oficial=_vendas_novas_oficial_camp,
        investimento_oficial=_investimento_oficial_camp,
    ),
    kpis_fn=lambda df, sel: campanha_funil_kpis(
        df, sel,
        leads_totais_oficial=_leads_totais_oficial_camp,
        vendas_novas_oficial=_vendas_novas_oficial_camp,
        investimento_oficial=_investimento_oficial_camp,
    ),
    etapas_fn=campanha_funil_etapas,
    data_ini=ctx.data_ini,
    data_fim=ctx.data_fim,
    nivel="campanha",
    auditoria_state_key="camp_funil_auditoria",
    empty_msg="Sem campanhas com investimento ou leads no período.",
    caption=(
        "Campanhas usam `utm_campaign` como origem principal. Vendas são "
        "atribuídas ao lead histórico por e-mail/telefone antes da compra."
    ),
    expander_md=(
        "- **Universo do funil:** `ext_reconecta.leads` no período, com "
        "  `utm_campaign` definindo a campanha do lead.\n"
        "- **Match lead → deal (vendas):** prioridade `e-mail` "
        "  (primário) → `telefone` limpo ≥ 8 dígitos (fallback). "
        "  `zoho_id` e `session_id` foram REMOVIDOS — operação validou "
        "  que e-mail é mais confiável.\n"
        "- **Atribuição cross-período:** a venda fica no período de "
        "  `data_hora_compra`, mas o lead atribuído pode ter sido criado "
        "  ANTES. Para cada deal ganho, o sistema busca o lead histórico "
        "  com `created_at <= data_hora_compra`.\n"
        "- **Desempate quando >1 lead casa o mesmo deal:**\n"
        "  1. match por e-mail vence telefone;\n"
        "  2. lead com origem útil (utm/link_in_bio/social) vence;\n"
        "  3. aparição mais recente antes da venda;\n"
        "  4. `lead_id` (determinístico).\n"
        "- **'Todos os resultados':** totais oficiais do período — leads "
        "  daily-distinct por e-mail (regra Visão Geral), vendas novas do "
        "  CRM, investimento total de mídia.\n"
        "- **'Totais vinculados aos leads':** soma per-campanha do funil "
        "  — só o que foi de fato vinculado/atribuído (útil pra auditoria "
        "  vs. universo oficial).\n"
        "- **Leads / +12 / -12 / Agendamentos / Comparecimentos:** "
        "  lead-centric, 1 e-mail conta 1× por campanha "
        "  (`COUNT(DISTINCT email_norm)`).\n"
        "- **Agendamentos:** atividades `Consulta` ou `Indicação` em "
        "  `zoho_activities` no período, **excluindo `status_reuniao` "
        "  vencido** (`COALESCE(status_reuniao,'') NOT ILIKE '%vencid%'`) — "
        "  alinhado com a regra da Visão Geral comercial.\n"
        "- **Comparecimentos:** subset dos agendamentos com "
        "  `status_reuniao = 'Concluída'`.\n"
        "- **Vendas novas:** deal-centric — 1 row por deal (sem "
        "  duplicação), `stage IN ('Ganho','Fechado Ganho')` e "
        "  `tipo_venda = 'Novo cliente'`.\n"
        "- **Filtros de e-mail de teste:** `@teste`, `teste@`, `smarts`, "
        "  `reconecta` removidos do universo de leads em todas as etapas."
    ),
)

# ---------------------------------------------------------------------------
# Tendência diária — invest (barra) + leads + leads qualif (linhas)
# ---------------------------------------------------------------------------
section_title("Tendência diária", "investimento × leads × leads qualificados")

# Leads/qualif diários da fonte canal-aware (mesma regra dos cards).
# Investimento diário continua de bi.vw_mkt_campanhas via df_camp.
diario = campanhas_diario_v2(df_camp, df_leads_canal_diario_all, canais_sel)
if diario.empty:
    st.info("Sem dados no período para os canais selecionados.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["investimento"], name="Investimento",
        marker=dict(color=PALETTE["gold"],
                    line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>R$ %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads"], name="Leads",
        line=dict(color=PALETTE["wine_light"], width=2.5),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["leads"], int_br),
        textposition="top center",
        textfont=dict(color=PALETTE["wine_light"], size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} leads<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_qualificados"],
        name="Leads qualificados",
        # Roxo vibrante (#7C3AED) — alinhado com Visão Geral. Distingue
        # bem do vinho (Leads) e do dourado (barras de Investimento).
        line=dict(color="#7C3AED", width=2.5, dash="dot"),
        mode="lines+markers+text", marker=dict(size=6, color="#7C3AED"),
        text=last_point_text(diario["leads_qualificados"], int_br),
        textposition="top center",
        textfont=dict(color="#7C3AED", size=11, family="Inter"),
        yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} qualif<extra></extra>",
    ))
    fig.update_layout(
        height=360,
        margin=dict(l=12, r=12, t=20, b=12),
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
        bargap=0.32,
        yaxis=dict(title="Investimento (R$)",
                   gridcolor=PALETTE["border"],
                   tickfont=dict(color=PALETTE["gold"]),
                   tickprefix="R$ ", separatethousands=True),
        yaxis2=dict(title="Leads", overlaying="y", side="right",
                    gridcolor="rgba(0,0,0,0)",
                    tickfont=dict(color=PALETTE["wine_light"])),
    )
    fig.update_xaxes(gridcolor=PALETTE["border"],
                     tickfont=dict(color=PALETTE["text_subtle"], size=11))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Distribuição por objetivo + tabela de campanhas ativas
# ---------------------------------------------------------------------------
col_obj, col_tab = st.columns([1, 1.6], gap="large")

with col_obj:
    section_title("Por objetivo", "investimento agrupado")
    obj = campanhas_objetivo(df_camp)
    if obj.empty:
        st.info("Sem investimento no período para os canais selecionados.")
    else:
        st.plotly_chart(
            donut(obj, names="objetivo", values="investimento",
                  height=300, total_label="Invest. total"),
            use_container_width=True,
        )

with col_tab:
    section_title("Campanhas ativas",
                  "investimento > 0 no período · ordenadas por invest. desc")
    ativas = campanhas_tabela_ativas(df_camp, df_leads_por_utm)
    if ativas.empty:
        st.info("Nenhuma campanha ativa para os canais selecionados.")
    else:
        # Linha "Total" no final — taxas (CTR/CPC/CPL/CPL+12/Tx Qualif)
        # recalculadas a partir das somas, não média das taxas. Leads
        # deduplicados por campaign_name antes de somar (evita dupla
        # contagem quando 1 campaign_name tem múltiplos campaign_id).
        ativas_view = pd.concat(
            [ativas, campanhas_tabela_total_row(ativas)],
            ignore_index=True,
        )
        st.dataframe(
            ativas_view, use_container_width=True, hide_index=True,
            column_config={
                "campaign_name": "Campanha",
                "canal": "Canal",
                "objetivo": "Objetivo",
                "investimento": st.column_config.NumberColumn(
                    "Invest.", format="R$ %.2f"),
                "impressoes": st.column_config.NumberColumn(
                    "Impressões", format="%d"),
                "cliques": st.column_config.NumberColumn("Cliques", format="%d"),
                "ctr": st.column_config.NumberColumn("CTR", format="%.2f%%"),
                "cpc": st.column_config.NumberColumn("CPC", format="R$ %.2f"),
                "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
                "leads": st.column_config.NumberColumn("Leads", format="%d"),
                "leads_qualificados": st.column_config.NumberColumn(
                    "Qualificados", format="%d"),
                "leads_mais_12": st.column_config.NumberColumn(
                    "+12", format="%d"),
                "leads_menos_12": st.column_config.NumberColumn(
                    "-12", format="%d"),
                "cpl": st.column_config.NumberColumn(
                    "CPL", format="R$ %.2f"),
                "cpl_mais_12": st.column_config.NumberColumn(
                    "CPL +12", format="R$ %.2f"),
                "tx_qualif_mais_12": st.column_config.NumberColumn(
                    "Tx Qualif +12", format="%.2f%%"),
            },
        )
        st.caption(
            "Leads por campanha são associados via `campaign_name = "
            "utm_campaign`. Campanhas sem correspondência de UTM aparecem "
            "com 0 até padronização. Quando o mesmo `campaign_name` tem "
            "mais de um `campaign_id` na plataforma, o total de leads "
            "do nome é repetido em cada linha (não há como atribuir leads "
            "a um `campaign_id` específico via UTM)."
        )

# ---------------------------------------------------------------------------
# Comparar campanhas (V2 — UTM + Zoho, modelo herdado do "Comparar páginas
# / variantes" da Growth)
# Plataforma: bi.vw_mkt_campanhas agregada por campaign_name normalizado.
# Leads/CRM:  ext_reconecta.leads + zoho_deals (priority match
#             zoho_id > session_id > email).
# Vendas:     apenas tipo_venda='Novo cliente' (caminho de aquisição).
# Cobertura mart abaixo continua como diagnóstico.
# ---------------------------------------------------------------------------
section_title("Comparar campanhas",
              "plataforma + leads/CRM + origem da campanha · grão utm_campaign")

# DF email-level — base pros filtros desta seção e pra agregação Python.
df_pv_raw = safe_run(
    lambda: get_mkt_paginas_variantes(ctx.data_ini, ctx.data_fim),
    view_label="ext_reconecta.leads (email-level pra Comparar campanhas)",
)

# Opções de filtro vêm do DF email-level no período.
def _opts(col: str, default: str = "Todas") -> list[str]:
    if df_pv_raw.empty or col not in df_pv_raw.columns:
        return [default]
    vals = sorted(df_pv_raw[col].dropna().astype(str).unique().tolist())
    return [default] + vals

# Filtros que afetam SOMENTE essa seção (não tocam cards/tabela/donut).
_HELP = ("Filtra apenas a comparação de campanhas — não afeta os cards "
         "superiores, tabela 'Campanhas ativas' nem donut 'Por objetivo'.")

flt_l1_a, flt_l1_b = st.columns(2, gap="small")
with flt_l1_a:
    sel_origem = st.selectbox(
        "Origem", options=_opts("utm_source", "Todas"),
        index=0, key="cmp_camp_origem", help=_HELP,
    )
with flt_l1_b:
    sel_midia = st.selectbox(
        "Mídia", options=_opts("utm_medium", "Todas"),
        index=0, key="cmp_camp_midia", help=_HELP,
    )
flt_l2_a, flt_l2_b = st.columns(2, gap="small")
with flt_l2_a:
    sel_timezone = st.selectbox(
        "Fuso / região", options=_opts("timezone", "Todos"),
        index=0, key="cmp_camp_timezone", help=_HELP,
    )
with flt_l2_b:
    sel_device = st.selectbox(
        "Dispositivo", options=_opts("device_type", "Todos"),
        index=0, key="cmp_camp_device", help=_HELP,
    )

df_camp_utm_agg = agregar_campanhas_por_utm(
    df_pv_raw, df_camp,
    origem=sel_origem, midia=sel_midia,
    timezone=sel_timezone, device_type=sel_device,
)
camp_list = lista_campanhas_por_utm(df_camp_utm_agg)

if camp_list.empty:
    st.caption("Sem campanhas para os filtros selecionados.")
else:
    options = camp_list["campaign_norm"].tolist()
    labels_map = dict(zip(camp_list["campaign_norm"], camp_list["label"]))

    # Defaults: top 1 e top 2 por leads (lista já vem ordenada)
    idx_default_b = 1 if len(options) > 1 else 0

    sel_col_a, sel_col_b = st.columns(2, gap="small")
    with sel_col_a:
        sel_a = st.selectbox(
            "Campanha A",
            options=options,
            format_func=lambda c: labels_map.get(c, "—"),
            index=0,
            key="cmp_campanha_a",
        )
    with sel_col_b:
        sel_b = st.selectbox(
            "Campanha B",
            options=options,
            format_func=lambda c: labels_map.get(c, "—"),
            index=idx_default_b,
            key="cmp_campanha_b",
        )

    kA = campanha_utm_kpis(df_camp_utm_agg, sel_a)
    kB = campanha_utm_kpis(df_camp_utm_agg, sel_b)
    cmp = compara_campanhas_utm(kA, kB)

    # ---- Formatadores -----------------------------------------------------
    _MONEY_METRICS = {"Investimento", "CPC"}
    _PCT_METRICS   = {"CTR", "Taxa qualificação", "Taxa +12",
                       "Taxa Lead → Venda nova"}
    _STR_METRICS   = {"Canal", "Página principal", "Variante principal",
                       "URL exemplo"}

    def _fmt_value(metrica: str, val) -> str:
        if val is None:
            return "—"
        try:
            if isinstance(val, float) and val != val:  # NaN
                return "—"
        except Exception:
            pass
        if metrica in _STR_METRICS:
            s = str(val).strip()
            return s if s and s != "—" else "—"
        if metrica in _MONEY_METRICS:
            return brl(float(val), casas=2)
        if metrica in _PCT_METRICS:
            return pct(float(val), casas=2)
        # Inteiros — Impressões/Cliques/Alcance/Leads*/Vendas novas
        return int_br(float(val))

    def _fmt_delta(d) -> str:
        import pandas as _pd
        if d is None or _pd.isna(d):
            return "—"
        sign = "+" if d > 0 else ""
        return f"{sign}{d:.1f}%".replace(".", ",")

    def _fmt_vencedor(v: str) -> str:
        return f"✓ {v}" if v else ""

    view = cmp.assign(
        valor_a_fmt=cmp.apply(
            lambda r: _fmt_value(r["metrica"], r["valor_a"]), axis=1
        ),
        valor_b_fmt=cmp.apply(
            lambda r: _fmt_value(r["metrica"], r["valor_b"]), axis=1
        ),
        delta_fmt=cmp["delta_pct"].apply(_fmt_delta),
        vencedor_fmt=cmp["vencedor"].apply(_fmt_vencedor),
    )[["metrica", "valor_a_fmt", "valor_b_fmt", "delta_fmt", "vencedor_fmt"]]

    st.dataframe(
        view, use_container_width=True, hide_index=True,
        column_config={
            "metrica": "Métrica",
            "valor_a_fmt": "Campanha A",
            "valor_b_fmt": "Campanha B",
            "delta_fmt": st.column_config.TextColumn(
                "Δ%", help="(B − A) / A × 100. — quando A=0, valor "
                          "categórico, ou algum lado vazio."),
            "vencedor_fmt": st.column_config.TextColumn(
                "Vencedor",
                help="Maior em volume/qualidade/CTR/Vendas novas/Taxas; "
                     "menor em CPC. Investimento, Canal, Leads -12 e Não "
                     "atua não destacam vencedor."),
        },
    )

    # Links clicáveis pra abrir as URLs em nova aba (st.dataframe não
    # transforma a string da linha "URL exemplo" em link).
    def _url_valido(u) -> str | None:
        if u is None:
            return None
        if isinstance(u, float) and u != u:  # NaN
            return None
        s = str(u).strip()
        if not s or s == "—":
            return None
        if not (s.startswith("http://") or s.startswith("https://")):
            return None
        return s

    url_a = _url_valido(kA.get("page_url_exemplo"))
    url_b = _url_valido(kB.get("page_url_exemplo"))
    partes = []
    if url_a:
        partes.append(f"[Abrir URL da Campanha A]({url_a})")
    if url_b:
        partes.append(f"[Abrir URL da Campanha B]({url_b})")
    if partes:
        st.markdown(" · ".join(partes))

    st.caption(
        "Métricas de **plataforma** (Invest., Impressões, Cliques, "
        "Alcance, CTR, CPC, Canal) vêm de **`bi.vw_mkt_campanhas`**, "
        "agregadas por `campaign_name` normalizado. "
        "**Leads, qualificados, +12, -12, Não atua, Taxas** e métricas "
        "de origem (página/variante/URL) vêm de "
        "`mkt_paginas_variantes.sql` (email-level) agregado por "
        "`utm_campaign` — mesma regra da Visão Geral. "
        "**Vendas novas** = `zoho_deals` (Ganho/Fechado Ganho) com "
        "`tipo_venda = 'Novo cliente'`, atribuído ao lead via priority "
        "`zoho_id > session_id > email` (mesma regra do funil Growth — "
        "ascensão/renovação/indicação ficam de fora do caminho de "
        "aquisição)."
    )

    # ---------------------- Expander: Detalhamento de origem ---------------
    with st.expander("Detalhamento de origem da campanha"):
        det = df_camp_utm_agg[[
            "utm_campaign", "pagina_principal", "variante_principal",
            "page_url_exemplo",
            "origens", "midias", "criativos",
            "fusos", "dispositivos",
            "qtd_paginas", "qtd_variantes", "qtd_criativos",
            "criativo_principal",
        ]].copy()
        # Listas → string separada por vírgula. Listas vazias → "—".
        for c in ("origens", "midias", "criativos",
                  "fusos", "dispositivos"):
            det[c] = det[c].apply(
                lambda lst: ", ".join(lst) if isinstance(lst, list) and lst else "—"
            )
        det["page_url_exemplo"]   = det["page_url_exemplo"].fillna("—")
        det["pagina_principal"]   = det["pagina_principal"].fillna("—")
        det["variante_principal"] = det["variante_principal"].fillna("—")
        det["criativo_principal"] = det["criativo_principal"].fillna("—")
        st.dataframe(
            det, use_container_width=True, hide_index=True,
            column_config={
                "utm_campaign":        "Campanha",
                "pagina_principal":    "Página principal",
                "variante_principal":  "Variante principal",
                "page_url_exemplo":    "URL exemplo",
                "origens":             "Origens",
                "midias":              "Mídias",
                "criativos":           "Criativos",
                "fusos":               "Fusos / regiões",
                "dispositivos":        "Dispositivos",
                "qtd_paginas":         st.column_config.NumberColumn(
                    "Qtd. páginas", format="%d"),
                "qtd_variantes":       st.column_config.NumberColumn(
                    "Qtd. variantes", format="%d"),
                "qtd_criativos":       st.column_config.NumberColumn(
                    "Qtd. criativos", format="%d"),
                "criativo_principal":  "Criativo principal",
            },
        )

    # ---------- Diagnóstico de cobertura da atribuição (expander) -----------
    df_cob = safe_run(
        lambda: get_mkt_campanha_cobertura(ctx.data_ini, ctx.data_fim),
        view_label="odam.mart_ad_funnel_daily (cobertura)",
    )
    cob = cobertura_atribuicao_kpis(df_cob)

    # Header dinâmico baseado no nível
    pct_str = f"{cob['pct_leads_com']:.0f}%".replace(".", ",")
    if cob["nivel"] == "baixa":
        cob_header = (
            f"⚠ Cobertura da atribuição: parcial ({pct_str}) — "
            f"clique para detalhes"
        )
    elif cob["nivel"] == "sem_dados":
        cob_header = "🔍 Cobertura da atribuição (sem dados)"
    else:
        cob_header = f"🔍 Cobertura da atribuição ({pct_str})"

    with st.expander(cob_header):
        if cob["nivel"] == "sem_dados":
            st.caption(
                "Sem dados na mart para o período selecionado. "
                "Sem leads/vendas/receita atribuídos."
            )
        else:
            st.markdown(
                "Os números abaixo dizem quanto da mart consegue ser "
                "atribuído a uma campanha específica. Linhas com "
                "`campaign_id` NULL **não** entram na comparação por "
                "campanha — comportamento intencional (não distribuímos "
                "resultado sem chave clara)."
            )

            def _fmt_int_pct(n: int, p: float) -> str:
                return f"{int_br(n)} ({pct(p, casas=1)})"

            def _fmt_money_pct(v: float, p: float) -> str:
                return f"{brl(v, casas=2)} ({pct(p, casas=1)})"

            cob_rows = [
                {
                    "Métrica": "Leads",
                    "Com campaign_id": _fmt_int_pct(
                        cob["leads_com"], cob["pct_leads_com"]),
                    "Sem campaign_id": _fmt_int_pct(
                        cob["leads_sem"], 100 - cob["pct_leads_com"]),
                    "Total": int_br(cob["total_leads"]),
                },
                {
                    "Métrica": "Vendas",
                    "Com campaign_id": _fmt_int_pct(
                        cob["vendas_com"], cob["pct_vendas_com"]),
                    "Sem campaign_id": _fmt_int_pct(
                        cob["vendas_sem"], 100 - cob["pct_vendas_com"]),
                    "Total": int_br(cob["total_vendas"]),
                },
                {
                    "Métrica": "Receita",
                    "Com campaign_id": _fmt_money_pct(
                        cob["receita_com"], cob["pct_receita_com"]),
                    "Sem campaign_id": _fmt_money_pct(
                        cob["receita_sem"], 100 - cob["pct_receita_com"]),
                    "Total": brl(cob["total_receita"], casas=2),
                },
            ]
            import pandas as _pd
            st.dataframe(
                _pd.DataFrame(cob_rows),
                use_container_width=True, hide_index=True,
            )

            if cob["nivel"] == "baixa":
                st.caption(
                    "**Cobertura baixa.** A comparação por campanha pode "
                    "parecer incompleta porque várias linhas da mart "
                    "estão entrando sem o `campaign_id` preenchido. "
                    "Esse é um problema de dados na origem "
                    "(`odam.mart_ad_funnel_daily`), não do dashboard."
                )
