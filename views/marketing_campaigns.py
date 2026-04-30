"""Campanhas — performance por campanha em mídia paga (Meta, Google, Pinterest).

Consome:
    bi.vw_mkt_campanhas — invest/imp/cliques/alcance/objetivo por campanha
    bi.vw_mkt_funil     — leads/qualif por canal (preenche KPIs e gráfico)

Os 3 canais pagos sempre aparecem no filtro, mesmo quando zerados — Pinterest
e Google podem não ter volume hoje, e o time pediu para preservar a estrutura
da página em qualquer cenário."""
import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import (
    get_mkt_campanha_cobertura,
    get_mkt_campanha_resultados,
    get_mkt_campanhas,
    get_mkt_funil,
    get_mkt_leads_classif_canal,
)
from src.marketing_safe import safe_run
from src.marketing_transforms import (
    CANAIS_PAGOS,
    campanha_kpis,
    campanhas_diario,
    campanhas_kpis,
    campanhas_objetivo,
    campanhas_tabela_ativas,
    cobertura_atribuicao_kpis,
    compara_campanhas,
    filtro_canais_padrao,
    lista_campanhas,
)
from src.ui.charts import donut, last_point_text
from src.ui.components import metric_card_v2, section_title
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
# Fonte deduplicada por canal — KPIs de leads usam isso quando disponível.
# Sem grão de canal próprio? Tem sim — `df_classif_canal` traz `canal` e nós
# refiltramos pelos canais selecionados pelo usuário antes de somar.
df_classif_canal_all = safe_run(
    lambda: get_mkt_leads_classif_canal(ctx.data_ini, ctx.data_fim),
    view_label="bi.vw_mkt_leads_classificacao (canal)",
)
# Resultados atribuídos por campanha (V1.5 da seção Comparar campanhas).
# Vem de odam.mart_ad_funnel_daily agregado por campaign_id. Cobertura
# primária Meta — Google/Pinterest geralmente sem linha aqui.
df_resultados_camp = safe_run(
    lambda: get_mkt_campanha_resultados(ctx.data_ini, ctx.data_fim),
    view_label="odam.mart_ad_funnel_daily (por campanha)",
)

df_camp = (
    ctx.refilter(df_camp_all, col_map) if not df_camp_all.empty else df_camp_all
)
df_funil = (
    ctx.refilter(df_funil_all, col_map) if not df_funil_all.empty else df_funil_all
)
df_classif_canal = (
    ctx.refilter(df_classif_canal_all, col_map)
    if not df_classif_canal_all.empty else df_classif_canal_all
)

# ---------------------------------------------------------------------------
# KPIs financeiros
# ---------------------------------------------------------------------------
# Quando df_classif_canal está disponível, leads/qualif vêm dele (deduplicado
# por canal+email na janela). Senão, fallback automático para df_funil (V1).
k = campanhas_kpis(df_camp, df_funil, df_classif_canal)

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
        hint=f"{k['dias_com_invest']} dias com invest > 0",
    )
with c3:
    metric_card_v2(
        "CPL",
        brl(k["cpl"], casas=2),
        hint="invest ÷ leads (mesmos canais)",
    )
with c4:
    metric_card_v2(
        "CPL qualificado",
        brl(k["cpl_qualificado"], casas=2),
        hint="invest ÷ leads (Atua +12 ou -12)",
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
        hint="únicos via lp_form.leads",
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
# Tendência diária — invest (barra) + leads + leads qualif (linhas)
# ---------------------------------------------------------------------------
section_title("Tendência diária", "investimento × leads × leads qualificados")

diario = campanhas_diario(df_camp, df_funil)
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
    ativas = campanhas_tabela_ativas(df_camp)
    if ativas.empty:
        st.info("Nenhuma campanha ativa para os canais selecionados.")
    else:
        st.dataframe(
            ativas, use_container_width=True, hide_index=True,
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
            },
        )

# ---------------------------------------------------------------------------
# Comparar campanhas (V1.5 — plataforma + resultado atribuído via mart)
# Plataforma: bi.vw_mkt_campanhas (oficial)
# Resultado:  odam.mart_ad_funnel_daily agregado por campaign_id (atribuído)
# Derivadas:  invest oficial / contagens da mart
# ---------------------------------------------------------------------------
section_title("Comparar campanhas",
              "plataforma + resultado atribuído · lado a lado")

camp_list = lista_campanhas(df_camp)
if camp_list.empty:
    st.caption("Sem campanhas no período selecionado para comparar.")
else:
    options = camp_list["campaign_id"].tolist()
    labels_map = dict(zip(camp_list["campaign_id"], camp_list["label"]))

    # Defaults: top 1 e top 2 por investimento (já vêm ordenados)
    idx_default_b = 1 if len(options) > 1 else 0

    sel_col_a, sel_col_b = st.columns(2, gap="small")
    with sel_col_a:
        sel_a = st.selectbox(
            "Campanha A",
            options=options,
            format_func=lambda cid: labels_map.get(cid, "—"),
            index=0,
            key="cmp_campanha_a",
        )
    with sel_col_b:
        sel_b = st.selectbox(
            "Campanha B",
            options=options,
            format_func=lambda cid: labels_map.get(cid, "—"),
            index=idx_default_b,
            key="cmp_campanha_b",
        )

    kA = campanha_kpis(df_camp, sel_a, df_resultados_camp)
    kB = campanha_kpis(df_camp, sel_b, df_resultados_camp)

    # Badge sutil sob cada selectbox indicando se a campanha tem resultado
    # atribuído na mart. Ajuda o usuário a interpretar "—" nas linhas de
    # resultado/derivadas.
    bdg_col_a, bdg_col_b = st.columns(2, gap="small")
    with bdg_col_a:
        st.caption(
            "✓ resultados atribuídos" if kA["tem_resultados"]
            else "⚠ sem atribuição no mart"
        )
    with bdg_col_b:
        st.caption(
            "✓ resultados atribuídos" if kB["tem_resultados"]
            else "⚠ sem atribuição no mart"
        )

    cmp = compara_campanhas(kA, kB)

    # ---- Formatadores -----------------------------------------------------
    # None → "—" para qualquer métrica numérica (sem atribuição OU
    # denominador zero em derivada).
    _MONEY_METRICS = {"Investimento", "CPC", "CPL", "CPL +12", "CAC", "Receita"}
    _PCT_METRICS = {"CTR"}
    _ROAS_METRIC = {"ROAS"}

    def _fmt_value(metrica: str, val) -> str:
        if val is None:
            return "—"
        try:
            if isinstance(val, float) and val != val:  # NaN
                return "—"
        except Exception:
            pass
        if metrica in ("Canal", "Objetivo"):
            return str(val) if val else "—"
        if metrica in _MONEY_METRICS:
            return brl(float(val), casas=2)
        if metrica in _PCT_METRICS:
            return pct(float(val), casas=2)
        if metrica in _ROAS_METRIC:
            return f"{float(val):.2f}x".replace(".", ",")
        # Inteiros (Impressões, Cliques, Alcance, Leads, +12, -12,
        # Agendamentos, Comparecimentos, No-shows, Deals, Deals ganhos, Vendas)
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
                "Δ%", help="(B − A) / A × 100. — quando A=0 ou algum lado "
                          "sem dado."),
            "vencedor_fmt": st.column_config.TextColumn(
                "Vencedor",
                help="Maior em métricas de volume/qualidade; menor em "
                     "CPL/CPC/CAC/No-shows. Sem vencedor quando algum "
                     "lado é '—' (atribuição incompleta) ou em "
                     "Investimento/Canal/Objetivo."),
        },
    )

    st.caption(
        "Métricas de plataforma (Invest., Impressões, Cliques, Alcance, "
        "CTR, CPC, Canal, Objetivo) vêm de **`bi.vw_mkt_campanhas`** "
        "(fonte oficial). "
        "Métricas de resultado (Leads, +12, -12, Agendamentos, "
        "Comparecimentos, No-shows, Deals, Deals ganhos, Vendas, Receita) "
        "são **atribuídas via `odam.mart_ad_funnel_daily`** — cobertura "
        "primária para Meta. "
        "Derivadas (CPL, CPL +12, CAC, ROAS) usam **investimento oficial** "
        "sobre numerador atribuído. "
        "\"—\" indica ausência de atribuição na mart ou denominador zero "
        "(ex.: CPL sem leads, ROAS sem invest)."
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
