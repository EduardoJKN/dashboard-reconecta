"""Transforms / KPIs do dashboard de Marketing.

Recebe DataFrames lidos via `marketing_queries.py` e devolve dicts/DataFrames
prontos para a UI. Sem SQL aqui."""
from __future__ import annotations

import pandas as pd

from .transforms import _safe_div  # reutiliza helper de vendas


CANAIS_PADRAO = ("Meta", "Google", "Pinterest", "Organico")
CANAIS_PAGOS = ("Meta", "Google", "Pinterest")

# Lista expandida só do filtro da Visão Geral Marketing — os 3 últimos
# (LinkedIn, TikTok, YouTube) ainda NÃO existem como categoria em
# bi.vw_mkt_overview e ficam zerados quando filtrados isoladamente. YouTube
# hoje cai dentro do bucket 'Google' na fonte (utm_source='google' agrega
# Search + YouTube Ads) — separar quando o time validar a coluna de canal
# certa em lp_form.leads.
CANAIS_VISIVEIS_OVERVIEW = (
    "Meta", "Google", "YouTube", "Pinterest", "Organico", "LinkedIn", "TikTok",
)


def filtro_canal_ativo(canais_sel: list[str] | None) -> bool:
    """True quando o usuário restringiu a um subconjunto real de canais.

    Lista vazia (= widget “Todos”) e seleção igual a CANAIS_VISIVEIS_OVERVIEW
    representam o total geral — filtro inativo."""
    canais = list(canais_sel or [])
    return bool(canais) and set(canais) != set(CANAIS_VISIVEIS_OVERVIEW)


def filtro_canais_padrao(canais: tuple[str, ...] = CANAIS_PADRAO) -> pd.DataFrame:
    """DataFrame sintético — 1 linha por canal — usado para popular o filtro
    de canal mesmo quando algum canal está sem dados no período. Garante que
    Pinterest/Google continuem visíveis na UI quando zerados."""
    return pd.DataFrame({"canal": list(canais)})

_OVERVIEW_ZEROS = {
    "investimento": 0, "impressoes": 0, "cliques": 0, "alcance": 0,
    "leads": 0, "leads_qualificados": 0,
    "leads_qualif_mais_12": 0, "leads_qualif_menos_12": 0,
    "leads_qualif_ambiguos": 0,
    "cpl": 0, "cpl_qualificado": 0, "cpl_mais_12": 0,
    "ctr": 0, "taxa_qualif": 0, "cpc": 0,
    "vendas": 0, "valor_venda": 0, "valor_receita": 0,
    "cac": 0, "roas": 0,
    "investimento_dia": 0, "dias_com_invest": 0,
}


def overview_kpis(df: pd.DataFrame,
                  df_roas: pd.DataFrame | None = None,
                  df_lp_funil: pd.DataFrame | None = None,
                  df_classif: pd.DataFrame | None = None) -> dict:
    """KPIs consolidados para o período já filtrado.

    Fórmulas (recalculadas no agregado, não média de taxas diárias):
      cpl              = invest / leads
      cpl_qualificado  = invest / leads_qualificados
      ctr              = cliques / impressoes * 100
      cpc              = invest / cliques
      taxa_qualif      = leads_qualificados / leads * 100
      cac              = invest / vendas               (se df_roas)
      roas             = valor_receita / invest        (se df_roas)

    Sobrescritas opcionais (Visão Geral Marketing, quando filtro = todos canais):
    - `df_lp_funil` (de `bi.vw_funil_leads_diario`) sobrescreve `leads` pelo
      SUM(leads_lp_unicos). CPL e taxa_qualif são recalculados.
    - `df_classif` (de `bi.vw_mkt_leads_classificacao`) sobrescreve
      `leads_qualif_mais_12`, `leads_qualif_menos_12`, `leads_qualif_ambiguos`
      e `leads_qualificados = +12 + -12` (ambíguos ficam fora). CPL qualificado
      e taxa_qualif são recalculados com o qualif corrigido.
    """
    if df.empty:
        return dict(_OVERVIEW_ZEROS)

    invest = float(df["investimento"].sum())
    imp = float(df["impressoes"].sum())
    clk = float(df["cliques"].sum())
    alc = float(df["alcance"].fillna(0).sum()) if "alcance" in df.columns else 0.0
    leads = float(df["leads"].sum())
    qualif = float(df["leads_qualificados"].sum())
    q_mais = float(df["leads_qualif_mais_12"].sum())
    q_menos = float(df["leads_qualif_menos_12"].sum())

    # dias com invest > 0 — denominador de "Investimento / dia"
    df_pos = df[df["investimento"] > 0]
    dias_invest = int(df_pos["data_ref"].nunique()) if not df_pos.empty else 0

    out = {
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "alcance": alc,
        "leads": leads,
        "leads_qualificados": qualif,
        "leads_qualif_mais_12": q_mais,
        "leads_qualif_menos_12": q_menos,
        "leads_qualif_ambiguos": 0,  # sobrescrito por df_classif quando disponível
        "cpl": _safe_div(invest, leads),
        "cpl_qualificado": _safe_div(invest, qualif),
        "ctr": _safe_div(clk, imp) * 100,
        "cpc": _safe_div(invest, clk),
        "taxa_qualif": _safe_div(qualif, leads) * 100,
        "dias_com_invest": dias_invest,
        "investimento_dia": _safe_div(invest, dias_invest),
    }

    # Substitui leads pela fonte validada (lp_form) quando df_lp_funil é
    # fornecido — usado na Visão Geral Marketing quando o filtro está em
    # "todos canais". Recalcula CPL e taxa_qualif com o denominador correto.
    if (df_lp_funil is not None
            and not df_lp_funil.empty
            and "leads_lp_unicos" in df_lp_funil.columns):
        leads_validado = float(df_lp_funil["leads_lp_unicos"].sum())
        out["leads"] = leads_validado
        out["cpl"] = _safe_div(invest, leads_validado)
        out["taxa_qualif"] = _safe_div(qualif, leads_validado) * 100

    # Substitui +12 / -12 / qualificados pela fonte com dedupe correto
    # (vw_mkt_leads_classificacao) — usado quando filtro = todos canais.
    # Ambíguos ficam fora de leads_qualificados, mas são expostos para hint.
    if (df_classif is not None
            and not df_classif.empty
            and "lead_mais_12" in df_classif.columns
            and "lead_menos_12" in df_classif.columns):
        q_mais_v = float(df_classif["lead_mais_12"].sum())
        q_menos_v = float(df_classif["lead_menos_12"].sum())
        ambiguos_v = (
            float(df_classif["lead_ambiguo"].sum())
            if "lead_ambiguo" in df_classif.columns else 0.0
        )
        qualif_v = q_mais_v + q_menos_v
        out["leads_qualif_mais_12"] = q_mais_v
        out["leads_qualif_menos_12"] = q_menos_v
        out["leads_qualif_ambiguos"] = ambiguos_v
        out["leads_qualificados"] = qualif_v
        out["cpl_qualificado"] = _safe_div(invest, qualif_v)
        out["taxa_qualif"] = _safe_div(qualif_v, out["leads"]) * 100

    if df_roas is not None and not df_roas.empty:
        vendas = float(df_roas["vendas"].sum())
        valor_v = float(df_roas["valor_venda"].sum()) if "valor_venda" in df_roas.columns else 0.0
        valor_r = float(df_roas["valor_receita"].sum()) if "valor_receita" in df_roas.columns else 0.0
        out.update({
            "vendas": vendas,
            "valor_venda": valor_v,
            "valor_receita": valor_r,
            "cac": _safe_div(invest, vendas),
            "roas": _safe_div(valor_r, invest),
        })
    else:
        out.update({"vendas": 0, "valor_venda": 0, "valor_receita": 0,
                    "cac": 0, "roas": 0})

    # CPL +12 = invest / leads_qualif_mais_12 — calculado por último para usar
    # o valor possivelmente sobrescrito por df_classif.
    out["cpl_mais_12"] = _safe_div(out["investimento"], out["leads_qualif_mais_12"])

    return out


def overview_por_canal(
    df: pd.DataFrame,
    df_roas: pd.DataFrame | None = None,
    df_classif_canal: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Sumariza KPIs por canal — base da tabela de breakdown.

    Fontes de dados por coluna:
      - Investimento, Impressões, Cliques, CTR  ← `df` (vw_mkt_overview)
      - Vendas, CAC, ROAS                       ← `df_roas` (mv_mkt_roas)
      - Leads, Qualif., Qualif +12, CPL, CPL Qualif., CPL +12,
        Tx Qualif., Tx Qualif +12              ← `df_classif_canal`
        (vw_mkt_leads_classificacao com grão de canal — fonte deduplicada
        OFICIAL e validada para todas as métricas de lead).

    ⚠ POLÍTICA DE FALLBACK (V1 — temporária):
        Se `df_classif_canal` chegar None/vazio (view indisponível, erro de
        SQL engolido pelo safe_run, etc.), a função cai temporariamente para
        os valores de `df` (vw_mkt_overview), que tem dedupe inflado por dia
        e produz números maiores que o real. Esse fallback é defensivo —
        prefere mostrar algo (com warning de safe_run) a deixar a tabela
        zerada na V1. Quando o dashboard estabilizar, trocar para "zera
        tudo se dedup indisponível" (Opção B).

    Estrutura: OUTER JOIN entre `df` (paid) e `df_classif_canal` (dedup) por
    canal — preserva canais que existem só num lado:
      - canal só em paid (sem leads rastreados no dedup) → leads/qualif = 0
      - canal só no dedup (organic-only sem spend)       → invest = 0
    Todas as divisões usam `_safe_div` (zero quando denominador zero)."""
    cols = ["canal", "investimento", "impressoes", "cliques",
            "leads", "leads_qualificados", "leads_qualif_mais_12",
            "cpl", "cpl_qualificado", "cpl_mais_12",
            "taxa_qualif", "tx_qualif_mais_12", "ctr",
            "vendas", "cac", "roas"]

    has_paid = not df.empty
    has_dedup = (
        df_classif_canal is not None
        and not df_classif_canal.empty
        and {"canal", "lead_mais_12", "lead_menos_12", "leads_unicos_canal"}
            .issubset(df_classif_canal.columns)
    )

    if not has_paid and not has_dedup:
        return pd.DataFrame(columns=cols)

    # --- 1) Agregação do lado pago (vw_mkt_overview) -----------------------
    paid_cols = ["canal", "investimento", "impressoes", "cliques",
                 "leads_overview", "leads_qualificados_overview",
                 "leads_qualif_mais_12_overview"]
    if has_paid:
        paid = df.groupby("canal", as_index=False).agg(
            investimento=("investimento", "sum"),
            impressoes=("impressoes", "sum"),
            cliques=("cliques", "sum"),
            leads_overview=("leads", "sum"),
            leads_qualificados_overview=("leads_qualificados", "sum"),
            leads_qualif_mais_12_overview=("leads_qualif_mais_12", "sum"),
        )
    else:
        paid = pd.DataFrame(columns=paid_cols)

    # --- 2) Lado deduplicado (vw_mkt_leads_classificacao por canal) --------
    if has_dedup:
        dedup = df_classif_canal[
            ["canal", "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
        ].copy()
    else:
        dedup = pd.DataFrame(
            columns=["canal", "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
        )

    # --- 3) OUTER JOIN — preserva canais de qualquer lado ------------------
    agg = paid.merge(dedup, on="canal", how="outer")
    for c in ("investimento", "impressoes", "cliques",
              "leads_overview", "leads_qualificados_overview",
              "leads_qualif_mais_12_overview",
              "leads_unicos_canal", "lead_mais_12", "lead_menos_12"):
        if c in agg.columns:
            agg[c] = agg[c].fillna(0)

    # --- 4) Escolha de fonte para métricas de leads ------------------------
    # Caminho padrão: TODAS as métricas de leads vêm do dedup oficial
    # (vw_mkt_leads_classificacao). Esse é o número validado, dedupe-por-janela.
    #
    # Caminho de fallback (só para resiliência da V1): se o dedup chegar
    # None/vazio (view fora do ar, erro silenciado pelo safe_run), cai para
    # os valores de vw_mkt_overview — que TEM CONTAGEM INFLADA por
    # duplicação cross-day. O usuário vê o warning do safe_run logo acima da
    # tabela. Quando V2: trocar este `else` por zerar tudo (Opção B).
    if has_dedup:
        agg["leads"] = agg["leads_unicos_canal"]
        agg["leads_qualif_mais_12"] = agg["lead_mais_12"]
        # Qualif. consolidado = +12 + -12 (ambíguos OUT por construção do dedup)
        agg["leads_qualificados"] = agg["lead_mais_12"] + agg["lead_menos_12"]
    else:
        # ⚠ FALLBACK: valores INFLADOS — só temporário enquanto V1.
        agg["leads"] = agg["leads_overview"]
        agg["leads_qualif_mais_12"] = agg["leads_qualif_mais_12_overview"]
        agg["leads_qualificados"] = agg["leads_qualificados_overview"]

    # --- 5) Métricas derivadas — todas usam o leads/qualif escolhido acima -
    agg["cpl"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads"]), axis=1
    )
    agg["cpl_qualificado"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_qualificados"]), axis=1
    )
    agg["cpl_mais_12"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_qualif_mais_12"]), axis=1
    )
    agg["taxa_qualif"] = agg.apply(
        lambda r: _safe_div(r["leads_qualificados"], r["leads"]) * 100, axis=1
    )
    agg["tx_qualif_mais_12"] = agg.apply(
        lambda r: _safe_div(r["leads_qualif_mais_12"], r["leads"]) * 100, axis=1
    )
    agg["ctr"] = agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )

    # --- 6) Limpa colunas auxiliares ---------------------------------------
    helper_cols = ["leads_overview", "leads_qualificados_overview",
                   "leads_qualif_mais_12_overview",
                   "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
    agg = agg.drop(columns=[c for c in helper_cols if c in agg.columns])

    # --- 7) ROAS (vendas/cac/roas vêm de mv_mkt_roas, fonte intacta) -------
    if df_roas is not None and not df_roas.empty:
        roas_agg = df_roas.groupby("canal", as_index=False).agg(
            vendas=("vendas", "sum"),
            valor_receita=("valor_receita", "sum"),
        )
        agg = agg.merge(roas_agg, on="canal", how="left")
        agg["vendas"] = agg["vendas"].fillna(0)
        agg["valor_receita"] = agg["valor_receita"].fillna(0)
        agg["cac"] = agg.apply(
            lambda r: _safe_div(r["investimento"], r["vendas"]), axis=1
        )
        agg["roas"] = agg.apply(
            lambda r: _safe_div(r["valor_receita"], r["investimento"]), axis=1
        )
    else:
        agg["vendas"] = 0
        agg["cac"] = 0
        agg["roas"] = 0

    return agg.sort_values("investimento", ascending=False).reset_index(drop=True)


def overview_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Soma todas as linhas por dia (independente de canal) para a tendência."""
    if df.empty:
        return df
    return (df.groupby("data_ref", as_index=False)
              .agg(investimento=("investimento", "sum"),
                   leads=("leads", "sum"),
                   leads_qualificados=("leads_qualificados", "sum"))
              .sort_values("data_ref"))


# ---------------------------------------------------------------------------
# Visão Geral Marketing — versão executiva (regra validada em pgAdmin)
# ---------------------------------------------------------------------------
# Fonte: mkt_visao_geral_diario.sql (1 linha por data_ref, sem canal).
# Métricas absolutas viram SUM. Ratios (ROAS / CPL / Taxa / Ticket) são
# recalculados sobre o agregado do período — nunca média de ratios diários.

_VISAO_GERAL_ZEROS = {
    "investimento_total_geral": 0.0,
    "leads_totais": 0,
    "leads_qualificados": 0,
    "leads_mais_12": 0,
    "leads_menos_12": 0,
    "leads_nao_atua": 0,
    "vendas_total_geral": 0,
    "vendas_novas_total_geral": 0,
    "montante_total_geral": 0.0,
    "receita_total_geral": 0.0,
    # Derivados (recalculados sobre SUMs)
    "roas_total_geral": 0.0,
    "cpl": 0.0,
    "cpl_qualificado": 0.0,
    "taxa_qualificacao": 0.0,
    "ticket_medio": 0.0,
}

_VISAO_GERAL_SUM_COLS = (
    "investimento_total_geral",
    "leads_totais", "leads_qualificados", "leads_mais_12", "leads_menos_12",
    "leads_nao_atua",
    "vendas_total_geral", "vendas_novas_total_geral",
    "montante_total_geral", "receita_total_geral",
)


def visao_geral_kpis(df: pd.DataFrame) -> dict:
    """KPIs executivos da Visão Geral Marketing.

    Fórmulas (recalculadas sobre SUMs do período):
      roas_total_geral   = SUM(montante_total_geral)   / SUM(investimento_total_geral)
      cpl                = SUM(investimento_total_geral) / SUM(leads_totais)
      cpl_qualificado    = SUM(investimento_total_geral) / SUM(leads_qualificados)
      taxa_qualificacao  = SUM(leads_qualificados) / SUM(leads_totais) * 100
      ticket_medio       = SUM(montante_total_geral) / SUM(vendas_total_geral)
    """
    if df.empty:
        return dict(_VISAO_GERAL_ZEROS)

    s = {c: float(df[c].sum()) for c in _VISAO_GERAL_SUM_COLS if c in df.columns}

    out = dict(_VISAO_GERAL_ZEROS)
    out.update(s)

    invest = s.get("investimento_total_geral", 0.0)
    leads = s.get("leads_totais", 0)
    qualif = s.get("leads_qualificados", 0)
    montante = s.get("montante_total_geral", 0.0)
    vendas = s.get("vendas_total_geral", 0)

    out["roas_total_geral"] = _safe_div(montante, invest)
    out["cpl"] = _safe_div(invest, leads)
    out["cpl_qualificado"] = _safe_div(invest, qualif)
    out["taxa_qualificacao"] = _safe_div(qualif, leads) * 100
    out["ticket_medio"] = _safe_div(montante, vendas)

    return out


def visao_geral_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Série diária para o gráfico de tendência da Visão Geral Marketing.
    Projeção direta — a fonte já é 1 linha por data_ref.

    Inclui `leads_mais_12` e `leads_menos_12` por dia para que a tendência
    possa exibir a quebra +12 / -12 quando útil. A SQL fonte
    (`mkt_visao_geral_diario.sql`) calcula esses campos pela classificação
    da própria linha do dia (`COUNT(DISTINCT email_norm)` por data). Isso
    difere dos cards do período, que deduplicam os e-mails classificados no
    período inteiro."""
    cols = ["data_ref", "investimento_total_geral",
            "leads_totais", "leads_qualificados",
            "leads_mais_12", "leads_menos_12"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.copy()
    for c in cols[1:]:
        if c not in out.columns:
            out[c] = 0
    return out[cols].sort_values("data_ref").reset_index(drop=True)


_VISAO_GERAL_CANAL_LEAD_COLS = (
    "leads_totais", "leads_qualificados", "leads_mais_12",
    "leads_menos_12", "leads_nao_atua",
)


def visao_geral_canal_kpis(df: pd.DataFrame,
                           canais: list[str] | None = None) -> dict:
    """Agrega `mkt_visao_geral_canal.sql` somando os canais selecionados.

    Recebe DataFrame com 1 linha por canal e a lista de canais a considerar
    (vinda de `ctx.selections["canal"]`). Lista vazia ou None = todos os
    canais. Usado pra sobrescrever os cards de Geração de leads quando o
    usuário filtra canal — os demais cards (financeiro / eficiência)
    continuam vindo de `visao_geral_kpis` (total geral comercial).
    """
    out = {c: 0 for c in _VISAO_GERAL_CANAL_LEAD_COLS}
    if df.empty:
        return out

    sub = df if not canais else df[df["canal"].isin(canais)]
    if sub.empty:
        return out

    for c in _VISAO_GERAL_CANAL_LEAD_COLS:
        if c in sub.columns:
            out[c] = int(sub[c].sum())
    return out


def visao_geral_kpis_canal(df: pd.DataFrame,
                           canais: list[str] | None = None) -> dict:
    """Agrega KPIs completos por canal (`mkt_visao_geral_kpis_canal.sql`).

    Soma os absolutos dos canais selecionados (lista vazia/None = todos os
    canais) e recalcula os ratios sobre os SUMs — exatamente como
    `visao_geral_kpis` faz na fonte sem grão de canal. Saída tem o MESMO
    shape de `visao_geral_kpis` (mais `leads_nao_atua`) pra que o page
    code possa fazer drop-in replacement quando o filtro de canal estiver
    ativo.

    Inclui 'Sem canal' como um canal selecionável, p/ permitir focar
    apenas em deals não atribuídos quando útil.
    """
    out = dict(_VISAO_GERAL_ZEROS)
    out["leads_nao_atua"] = 0  # presente apenas no canal-grain

    if df.empty:
        return out

    sub = df if not canais else df[df["canal"].isin(canais)]
    if sub.empty:
        return out

    abs_cols = (
        "investimento_total_geral",
        "leads_totais", "leads_qualificados",
        "leads_mais_12", "leads_menos_12", "leads_nao_atua",
        "vendas_total_geral", "vendas_novas_total_geral",
        "montante_total_geral", "receita_total_geral",
    )
    for c in abs_cols:
        if c in sub.columns:
            out[c] = float(sub[c].sum())

    # Cast inteiros pra display
    for c in ("leads_totais", "leads_qualificados", "leads_mais_12",
              "leads_menos_12", "leads_nao_atua",
              "vendas_total_geral", "vendas_novas_total_geral"):
        out[c] = int(out[c])

    invest = out["investimento_total_geral"]
    leads = out["leads_totais"]
    qualif = out["leads_qualificados"]
    montante = out["montante_total_geral"]
    vendas = out["vendas_total_geral"]

    out["roas_total_geral"] = _safe_div(montante, invest)
    out["cpl"] = _safe_div(invest, leads)
    out["cpl_qualificado"] = _safe_div(invest, qualif)
    out["taxa_qualificacao"] = _safe_div(qualif, leads) * 100
    out["ticket_medio"] = _safe_div(montante, vendas)

    return out


# ---------------------------------------------------------------------------
# Visão Geral V2 — fonte única bi.vw_mkt_overview_daily_v2 (legado)
# ---------------------------------------------------------------------------
# Diferente da V1: não tem canal (grão = data_ref). Sem fallback condicional —
# a view já consolida tudo. Métricas absolutas viram SUM; ratios (CPL/ROAS/Tx)
# são recalculados sobre o agregado do período (não média de ratios diários).
# Ainda exportado pra outras páginas; a Visão Geral Marketing migrou para
# `visao_geral_kpis` acima.

_OVERVIEW_V2_ZEROS = {
    # Mídia
    "investimento_midia": 0.0, "impressoes": 0, "alcance": 0,
    "cliques": 0, "inline_link_clicks": 0,
    # Atribuído
    "leads_meta": 0, "pixel_lead": 0, "agendamentos_meta": 0,
    "leads_reais": 0, "leads_qualificados": 0,
    "leads_mais_12": 0, "leads_menos_12": 0, "leads_nao_atua": 0,
    "deals_atribuidos": 0, "ganhos_atribuidos": 0,
    "montante_atribuido": 0.0, "receita_atribuida": 0.0,
    # Total geral comercial
    "investimento_total_geral": 0.0,
    "montante_total_geral": 0.0, "receita_total_geral": 0.0,
    "vendas_novas_total_geral": 0, "vendas_total_geral": 0,
    "oportunidades_total_geral": 0,
    "perdidos_total_geral": 0, "cancelados_total_geral": 0,
    # Ratios derivados (recalculados sobre SUMs)
    "roas_montante_atribuido": 0.0, "roas_receita_atribuida": 0.0,
    "roas_montante_total_geral": 0.0, "roas_receita_total_geral": 0.0,
    "cpl_real": 0.0, "cpl_qualificado": 0.0, "cpl_mais_12": 0.0,
    "taxa_qualif": 0.0,
    "cobertura_montante": 0.0, "cobertura_receita": 0.0,
    "dias_com_invest": 0, "investimento_dia": 0.0,
}

_OVERVIEW_V2_SUM_COLS = (
    "investimento_midia", "impressoes", "alcance", "cliques", "inline_link_clicks",
    "leads_meta", "pixel_lead", "agendamentos_meta",
    "leads_reais", "leads_qualificados", "leads_mais_12", "leads_menos_12",
    "leads_nao_atua",
    "deals_atribuidos", "ganhos_atribuidos",
    "montante_atribuido", "receita_atribuida",
    "investimento_total_geral",
    "montante_total_geral", "receita_total_geral",
    "vendas_novas_total_geral", "vendas_total_geral", "oportunidades_total_geral",
    "perdidos_total_geral", "cancelados_total_geral",
)


def overview_v2_kpis(df: pd.DataFrame) -> dict:
    """KPIs consolidados da Visão Geral V2 para o período.

    Fonte única: `bi.vw_mkt_overview_daily_v2` (grão data_ref, sem canal).
    Métricas absolutas = SUM. Ratios (ROAS/CPL/Taxa/Cobertura) NÃO somam —
    recalculados sobre os agregados:

      cpl_real         = SUM(investimento_midia) / SUM(leads_reais)
      cpl_qualificado  = SUM(investimento_midia) / SUM(leads_qualificados)
      cpl_mais_12      = SUM(investimento_midia) / SUM(leads_mais_12)
      taxa_qualif      = SUM(leads_qualificados) / SUM(leads_reais) * 100

      roas_montante_atribuido    = SUM(montante_atribuido) / SUM(investimento_midia)
      roas_receita_atribuida     = SUM(receita_atribuida)  / SUM(investimento_midia)
      roas_montante_total_geral  = SUM(montante_total_geral) / SUM(investimento_total_geral)
      roas_receita_total_geral   = SUM(receita_total_geral)  / SUM(investimento_total_geral)

      cobertura_montante = SUM(montante_atribuido) / SUM(montante_total_geral) * 100
      cobertura_receita  = SUM(receita_atribuida)  / SUM(receita_total_geral)  * 100
    """
    if df.empty:
        return dict(_OVERVIEW_V2_ZEROS)

    s = {c: float(df[c].sum()) for c in _OVERVIEW_V2_SUM_COLS if c in df.columns}

    df_pos = df[df.get("investimento_midia", 0) > 0]
    dias_invest = int(df_pos["data_ref"].nunique()) if not df_pos.empty else 0

    out = dict(_OVERVIEW_V2_ZEROS)
    out.update(s)
    out["dias_com_invest"] = dias_invest
    out["investimento_dia"] = _safe_div(s.get("investimento_midia", 0), dias_invest)

    invest_midia = s.get("investimento_midia", 0)
    invest_geral = s.get("investimento_total_geral", 0)

    out["cpl_real"] = _safe_div(invest_midia, s.get("leads_reais", 0))
    out["cpl_qualificado"] = _safe_div(invest_midia, s.get("leads_qualificados", 0))
    out["cpl_mais_12"] = _safe_div(invest_midia, s.get("leads_mais_12", 0))
    out["taxa_qualif"] = _safe_div(s.get("leads_qualificados", 0),
                                   s.get("leads_reais", 0)) * 100

    out["roas_montante_atribuido"] = _safe_div(s.get("montante_atribuido", 0), invest_midia)
    out["roas_receita_atribuida"] = _safe_div(s.get("receita_atribuida", 0), invest_midia)
    out["roas_montante_total_geral"] = _safe_div(s.get("montante_total_geral", 0), invest_geral)
    out["roas_receita_total_geral"] = _safe_div(s.get("receita_total_geral", 0), invest_geral)

    out["cobertura_montante"] = _safe_div(s.get("montante_atribuido", 0),
                                          s.get("montante_total_geral", 0)) * 100
    out["cobertura_receita"] = _safe_div(s.get("receita_atribuida", 0),
                                         s.get("receita_total_geral", 0)) * 100

    return out


def overview_v2_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Série diária para o gráfico de tendência. Projeção direta — a fonte já
    é 1 linha por data_ref. Garante presença das colunas consumidas pelo
    gráfico e ordem cronológica."""
    cols = ["data_ref", "investimento_midia", "leads_reais", "leads_qualificados"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.copy()
    for c in cols[1:]:
        if c not in out.columns:
            out[c] = 0
    return out[cols].sort_values("data_ref").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------

_CAMPANHAS_ZEROS = {
    "investimento": 0.0, "investimento_dia": 0.0,
    "impressoes": 0.0, "cliques": 0.0,
    "leads": 0.0, "leads_qualificados": 0.0,
    "leads_qualif_mais_12": 0.0, "leads_qualif_menos_12": 0.0,
    "cpl": 0.0, "cpl_qualificado": 0.0,
    "ctr": 0.0, "cpc": 0.0,
    "dias_com_invest": 0,
}


def campanhas_kpis(df_camp: pd.DataFrame,
                   df_funil: pd.DataFrame,
                   df_classif_canal: pd.DataFrame | None = None) -> dict:
    """KPIs consolidados para a página de Campanhas.

    Investimento/impressões/cliques vêm do grão de campanhas
    (`bi.vw_mkt_campanhas`); leads e qualificados vêm do funil
    (`bi.vw_mkt_funil`) — porque a view de campanhas não tem leads.

    Fórmulas:
      investimento_dia = invest_total / nº de dias DISTINTOS com invest > 0
      cpl              = invest / leads
      cpl_qualificado  = invest / leads_qualificados
      ctr              = cliques / impressoes * 100
      cpc              = invest / cliques

    Sobrescrita opcional: quando `df_classif_canal` é passado (já filtrado por
    canal no chamador), as métricas de leads (`leads`, `leads_qualif_mais_12`,
    `leads_qualif_menos_12`, `leads_qualificados`) e seus derivados (`cpl`,
    `cpl_qualificado`) usam SUM dessa fonte deduplicada por canal — em vez do
    funil inflado. Ambíguos ficam fora do `leads_qualificados` por construção
    do dedup. Política V1: se `df_classif_canal` for None/vazio, fallback
    automático para os valores do funil.
    """
    out = dict(_CAMPANHAS_ZEROS)

    if not df_camp.empty:
        invest = float(df_camp["investimento"].sum())
        imp = float(df_camp["impressoes"].sum())
        clk = float(df_camp["cliques"].sum())
        # dias com invest > 0 — denominador do "investimento por dia"
        df_pos = df_camp[df_camp["investimento"] > 0]
        dias_invest = int(df_pos["data_ref"].nunique()) if not df_pos.empty else 0
        out.update({
            "investimento": invest,
            "impressoes": imp,
            "cliques": clk,
            "investimento_dia": _safe_div(invest, dias_invest),
            "ctr": _safe_div(clk, imp) * 100,
            "cpc": _safe_div(invest, clk),
            "dias_com_invest": dias_invest,
        })

    has_dedup_canal = (
        df_classif_canal is not None
        and not df_classif_canal.empty
        and {"lead_mais_12", "lead_menos_12", "leads_unicos_canal"}
            .issubset(df_classif_canal.columns)
    )

    if has_dedup_canal:
        # Fonte oficial: dedup por canal, somada nos canais filtrados.
        leads = float(df_classif_canal["leads_unicos_canal"].sum())
        q_mais = float(df_classif_canal["lead_mais_12"].sum())
        q_menos = float(df_classif_canal["lead_menos_12"].sum())
        qualif = q_mais + q_menos
        out.update({
            "leads": leads,
            "leads_qualif_mais_12": q_mais,
            "leads_qualif_menos_12": q_menos,
            "leads_qualificados": qualif,
            "cpl": _safe_div(out["investimento"], leads),
            "cpl_qualificado": _safe_div(out["investimento"], qualif),
        })
    elif not df_funil.empty:
        # ⚠ FALLBACK V1: vw_mkt_funil tem contagem inflada por dia-duplicado.
        leads = float(df_funil["leads"].sum())
        q_mais = float(df_funil["leads_qualif_mais_12"].sum())
        q_menos = float(df_funil["leads_qualif_menos_12"].sum())
        qualif = q_mais + q_menos
        out.update({
            "leads": leads,
            "leads_qualif_mais_12": q_mais,
            "leads_qualif_menos_12": q_menos,
            "leads_qualificados": qualif,
            "cpl": _safe_div(out["investimento"], leads),
            "cpl_qualificado": _safe_div(out["investimento"], qualif),
        })
    return out


def campanhas_diario(df_camp: pd.DataFrame, df_funil: pd.DataFrame) -> pd.DataFrame:
    """Série diária combinando invest (de campanhas) com leads/qualif (do funil)
    via outer join em `data_ref`. Sempre retorna `[data_ref, investimento,
    leads, leads_qualificados]`, com 0 onde houver gap."""
    cols = ["data_ref", "investimento", "leads", "leads_qualificados"]
    if df_camp.empty and df_funil.empty:
        return pd.DataFrame(columns=cols)

    if df_camp.empty:
        invest_diario = pd.DataFrame(columns=["data_ref", "investimento"])
    else:
        invest_diario = (df_camp.groupby("data_ref", as_index=False)
                                .agg(investimento=("investimento", "sum")))

    if df_funil.empty:
        leads_diario = pd.DataFrame(columns=["data_ref", "leads",
                                              "leads_qualificados"])
    else:
        f = (df_funil.groupby("data_ref", as_index=False)
                     .agg(leads=("leads", "sum"),
                          q_mais=("leads_qualif_mais_12", "sum"),
                          q_menos=("leads_qualif_menos_12", "sum")))
        f["leads_qualificados"] = f["q_mais"] + f["q_menos"]
        leads_diario = f[["data_ref", "leads", "leads_qualificados"]]

    out = invest_diario.merge(leads_diario, on="data_ref", how="outer")
    for c in ("investimento", "leads", "leads_qualificados"):
        if c in out.columns:
            out[c] = out[c].fillna(0)
        else:
            out[c] = 0
    return out[cols].sort_values("data_ref").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Campanhas — leads canal-aware via fonte oficial bi_mkt.vw_visao_geral_canal_base
# ---------------------------------------------------------------------------
# Substitui a regra antiga de leads (bi.vw_mkt_leads_classificacao + BOOL_OR
# cross-day) pelos números da Visão Geral Marketing — que aplica canal_final
# (last_row do e-mail) + classif_final canônica. As funções abaixo consomem
# o DataFrame produzido por `mkt_campanhas_leads_canal_diario.sql`.

_CAMPANHAS_LEADS_CANAL_ZEROS = {
    "leads_totais": 0,
    "leads_qualificados": 0,
    "leads_mais_12": 0,
    "leads_menos_12": 0,
    "leads_nao_atua": 0,
}


def campanhas_leads_canal_kpis(df: pd.DataFrame,
                               canais: list[str] | None = None) -> dict:
    """Agrega o DF diário-por-canal para o período, filtrando os canais
    selecionados pelo header da página. `canais=None` ou lista vazia agrega
    todos os canais presentes no DF (Meta + Google + Pinterest no caso da
    página Campanhas, já que o filtro de canais é restrito a esses).

    Saída: dict com leads_totais, leads_qualificados, leads_mais_12,
    leads_menos_12, leads_nao_atua (ints). Ratios (CPL/CPL qualif) são
    recalculados pelo chamador, que tem o investimento."""
    out = dict(_CAMPANHAS_LEADS_CANAL_ZEROS)
    if df.empty:
        return out

    sub = df if not canais else df[df["canal"].isin(canais)]
    if sub.empty:
        return out

    for c in _CAMPANHAS_LEADS_CANAL_ZEROS:
        if c in sub.columns:
            out[c] = int(sub[c].sum())
    return out


def campanhas_diario_v2(df_camp: pd.DataFrame,
                        df_leads_canal_diario: pd.DataFrame,
                        canais: list[str] | None = None) -> pd.DataFrame:
    """Tendência diária — investimento (de bi.vw_mkt_campanhas) +
    leads/qualif (de mkt_campanhas_leads_canal_diario.sql).

    Substitui `campanhas_diario(df_camp, df_funil)` que usava bi.mv_mkt_funil
    inflado. Aqui leads/qualif vêm da fonte oficial canal-aware, filtrada
    pelos canais selecionados, agregada por data_ref. Outer join com
    investimento diário; lacunas viram 0.

    Retorna `[data_ref, investimento, leads, leads_qualificados]` —
    schema compatível com o chart existente (basta atualizar a chamada)."""
    cols = ["data_ref", "investimento", "leads", "leads_qualificados"]
    if df_camp.empty and df_leads_canal_diario.empty:
        return pd.DataFrame(columns=cols)

    if df_camp.empty:
        invest_diario = pd.DataFrame(columns=["data_ref", "investimento"])
    else:
        invest_diario = (df_camp.groupby("data_ref", as_index=False)
                                .agg(investimento=("investimento", "sum")))

    if df_leads_canal_diario.empty:
        leads_diario = pd.DataFrame(columns=["data_ref", "leads",
                                              "leads_qualificados"])
    else:
        sub = (df_leads_canal_diario if not canais
               else df_leads_canal_diario[df_leads_canal_diario["canal"].isin(canais)])
        leads_diario = (sub.groupby("data_ref", as_index=False)
                           .agg(leads=("leads_totais", "sum"),
                                leads_qualificados=("leads_qualificados", "sum")))

    out = invest_diario.merge(leads_diario, on="data_ref", how="outer")
    for c in ("investimento", "leads", "leads_qualificados"):
        if c in out.columns:
            out[c] = out[c].fillna(0)
        else:
            out[c] = 0
    return out[cols].sort_values("data_ref").reset_index(drop=True)


def campanhas_objetivo(df_camp: pd.DataFrame) -> pd.DataFrame:
    """Distribuição de investimento por objetivo. NULL/'' → 'Não informado'."""
    if df_camp.empty:
        return pd.DataFrame(columns=["objetivo", "investimento"])
    df = df_camp.copy()
    df["objetivo"] = (df["objetivo"]
                      .fillna("Não informado")
                      .replace("", "Não informado"))
    agg = (df.groupby("objetivo", as_index=False)
             .agg(investimento=("investimento", "sum")))
    # Só mostra grupos com invest > 0 — manter NULL+0 polui o donut
    agg = agg[agg["investimento"] > 0]
    return agg.sort_values("investimento", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# ROAS / CAC
# ---------------------------------------------------------------------------

_ROAS_ZEROS = {
    "investimento": 0.0,
    "leads": 0.0, "leads_qualificados": 0.0,
    "vendas": 0.0, "vendas_novas": 0.0,
    "valor_venda": 0.0, "montante": 0.0, "valor_receita": 0.0,
    "roas": 0.0, "cac": 0.0,
    "cpl": 0.0, "cpl_qualificado": 0.0,
    "ticket_medio": 0.0,
}


def roas_kpis(df_kpc: pd.DataFrame,
              df_leads_canal_diario: pd.DataFrame | None = None,
              canais: list[str] | None = None,
              todos_canais: bool = True) -> dict:
    """KPIs ROAS/CAC alinhados com a Visão Geral oficial.

    Fonte unificada (mesma da Visão Geral / Growth):
      - df_kpc: `mkt_visao_geral_kpis_canal.sql` — 1 linha por canal com
        invest, vendas, vendas_novas, montante, receita atribuídos via
        priority match `zoho_id > session_id > email`. Inclui 'Sem canal'
        para deals não atribuídos.
      - df_leads_canal_diario: `mkt_campanhas_leads_canal_diario.sql` —
        leads/qualif por (data_ref, canal) via regra last_row + canal_final
        (mesma fonte usada em Visão Geral / Campanhas).

    Fórmulas (recalculadas no agregado, não média):
      roas           = montante / invest
      cac            = invest / vendas_novas       (caminho de aquisição)
      cpl            = invest / leads
      cpl_qualif     = invest / qualif
      ticket_medio   = receita / vendas

    `todos_canais=True` soma TODAS as rows (incluindo 'Sem canal') — bate
    com o agregado da Visão Geral. Senão, soma apenas os canais
    selecionados."""
    out = dict(_ROAS_ZEROS)
    if df_kpc is None or df_kpc.empty:
        return out

    sub_kpc = df_kpc if todos_canais else df_kpc[df_kpc["canal"].isin(canais or [])]
    if not sub_kpc.empty:
        invest = float(sub_kpc["investimento_total_geral"].sum())
        vendas = float(sub_kpc["vendas_total_geral"].sum())
        vendas_novas = float(sub_kpc["vendas_novas_total_geral"].sum())
        montante = float(sub_kpc["montante_total_geral"].sum())
        receita = float(sub_kpc["receita_total_geral"].sum())

        out["investimento"] = invest
        out["vendas"] = vendas
        out["vendas_novas"] = vendas_novas
        out["valor_venda"] = montante
        out["montante"] = montante
        out["valor_receita"] = receita
        out["roas"] = _safe_div(montante, invest)
        out["cac"] = _safe_div(invest, vendas_novas)
        out["ticket_medio"] = _safe_div(receita, vendas)

    # Leads/qualif vêm do canal-diario (regra last_row + canal_final).
    # Se não passado, cai para os leads do próprio kpc (mesma fonte por canal,
    # apenas sem grão diário) — mantém saída consistente.
    if df_leads_canal_diario is not None and not df_leads_canal_diario.empty:
        sub_l = (
            df_leads_canal_diario if todos_canais
            else df_leads_canal_diario[df_leads_canal_diario["canal"].isin(canais or [])]
        )
        if not sub_l.empty:
            out["leads"] = float(sub_l["leads_totais"].sum())
            out["leads_qualificados"] = float(sub_l["leads_qualificados"].sum())
    elif not sub_kpc.empty:
        out["leads"] = float(sub_kpc["leads_totais"].sum())
        out["leads_qualificados"] = float(sub_kpc["leads_qualificados"].sum())

    invest_d = out["investimento"]
    out["cpl"] = _safe_div(invest_d, out["leads"])
    out["cpl_qualificado"] = _safe_div(invest_d, out["leads_qualificados"])
    return out


def roas_por_canal(df_kpc: pd.DataFrame,
                   df_leads_canal_diario: pd.DataFrame | None = None) -> pd.DataFrame:
    """Quebra por canal — uma linha por canal alinhada com a Visão Geral.

    Invest / vendas / vendas_novas / montante / receita: `df_kpc`
    (`mkt_visao_geral_kpis_canal.sql`).
    Leads / qualificados: `df_leads_canal_diario`
    (`mkt_campanhas_leads_canal_diario.sql`) somando todas as datas por
    canal — mesma fonte usada em Visão Geral. Quando ausente, cai para os
    leads do próprio `df_kpc` (mesma fonte sem grão diário).
    """
    cols = ["canal", "investimento", "leads", "leads_qualificados",
            "vendas", "vendas_novas", "valor_venda", "valor_receita",
            "roas", "cac", "cpl", "cpl_qualificado"]

    has_kpc = df_kpc is not None and not df_kpc.empty
    has_leads = (df_leads_canal_diario is not None
                 and not df_leads_canal_diario.empty)
    if not has_kpc and not has_leads:
        return pd.DataFrame(columns=cols)

    if has_kpc:
        kpc = df_kpc[["canal",
                      "investimento_total_geral",
                      "leads_totais",
                      "leads_qualificados",
                      "vendas_total_geral",
                      "vendas_novas_total_geral",
                      "montante_total_geral",
                      "receita_total_geral"]].copy()
        kpc = kpc.rename(columns={
            "investimento_total_geral": "investimento",
            "leads_totais": "leads_kpc",
            "leads_qualificados": "leads_qualificados_kpc",
            "vendas_total_geral": "vendas",
            "vendas_novas_total_geral": "vendas_novas",
            "montante_total_geral": "valor_venda",
            "receita_total_geral": "valor_receita",
        })
    else:
        kpc = pd.DataFrame(columns=["canal", "investimento", "leads_kpc",
                                     "leads_qualificados_kpc", "vendas",
                                     "vendas_novas", "valor_venda",
                                     "valor_receita"])

    if has_leads:
        leads_canal = (df_leads_canal_diario.groupby("canal", as_index=False)
                       .agg(leads=("leads_totais", "sum"),
                            leads_qualificados=("leads_qualificados", "sum")))
    else:
        leads_canal = pd.DataFrame(columns=["canal", "leads",
                                             "leads_qualificados"])

    agg = kpc.merge(leads_canal, on="canal", how="outer")
    if "leads" not in agg.columns:
        agg["leads"] = 0.0
    if "leads_qualificados" not in agg.columns:
        agg["leads_qualificados"] = 0.0
    # Fallback para canais que existem em kpc mas não no daily (ou vice-versa)
    agg["leads"] = agg["leads"].fillna(agg.get("leads_kpc", 0)).fillna(0)
    agg["leads_qualificados"] = (
        agg["leads_qualificados"].fillna(agg.get("leads_qualificados_kpc", 0))
                                  .fillna(0)
    )
    for c in ("investimento", "vendas", "vendas_novas",
              "valor_venda", "valor_receita"):
        if c not in agg.columns:
            agg[c] = 0.0
        agg[c] = agg[c].fillna(0)

    agg["roas"] = agg.apply(
        lambda r: _safe_div(r["valor_venda"], r["investimento"]), axis=1
    )
    agg["cac"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["vendas_novas"]), axis=1
    )
    agg["cpl"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads"]), axis=1
    )
    agg["cpl_qualificado"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_qualificados"]), axis=1
    )

    return (agg[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


def roas_diario(df_vg: pd.DataFrame) -> pd.DataFrame:
    """Série diária consolidada para a Tendência diária da página ROAS/CAC.

    Fonte: `mkt_visao_geral_diario.sql` (mesma usada na Visão Geral) — já 1
    linha por `data_ref` com investimento total geral e financeiro
    (montante / receita) de zoho_deals. Como o grão é só por data, a série
    é sempre **total geral** (não filtra por canal) — alinhado com a
    política da Visão Geral. Filtros de canal afetam cards e tabela por
    canal abaixo, não a tendência."""
    cols = ["data_ref", "investimento", "valor_receita", "vendas", "roas"]
    if df_vg is None or df_vg.empty:
        return pd.DataFrame(columns=cols)

    out = df_vg.rename(columns={
        "investimento_total_geral": "investimento",
        "receita_total_geral": "valor_receita",
        "vendas_total_geral": "vendas",
    }).copy()
    for c in ("investimento", "valor_receita", "vendas"):
        if c not in out.columns:
            out[c] = 0
        out[c] = out[c].fillna(0)
    out["roas"] = out.apply(
        lambda r: _safe_div(r["valor_receita"], r["investimento"]), axis=1
    )
    return out[cols].sort_values("data_ref").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Funil Marketing
# ---------------------------------------------------------------------------

_FUNIL_ZEROS = {
    "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0,
    "leads": 0.0, "leads_qualificados": 0.0,
    "leads_qualif_mais_12": 0.0, "leads_qualif_menos_12": 0.0,
    "deals": 0.0, "deals_ganhos": 0.0, "vendas": 0.0,
    "valor_venda": 0.0, "valor_receita": 0.0,
    "cpl": 0.0,
    "tx_qualificacao": 0.0,
    "tx_lead_deal": 0.0,
    "tx_deal_venda": 0.0,
}


def funil_kpis(df: pd.DataFrame,
               df_lp_funil: pd.DataFrame | None = None,
               df_classif: pd.DataFrame | None = None) -> dict:
    """KPIs consolidados do funil de marketing.

    Métricas derivadas (recalculadas no agregado, não média de taxas diárias):
      cpl              = invest / leads
      tx_qualificacao  = qualif / leads * 100
      tx_lead_deal     = deals / leads * 100
      tx_deal_venda    = vendas / deals * 100

    Sobrescritas opcionais (mesmo padrão da Visão Geral / ROAS-CAC):
    - `df_lp_funil` (de `bi.vw_funil_leads_diario`): sobrescreve `leads` pelo
      SUM(leads_lp_unicos) — fonte validada para Leads totais quando filtro =
      todos canais.
    - `df_classif` (de `bi.vw_mkt_leads_classificacao`): sobrescreve
      `leads_qualif_mais_12`, `leads_qualif_menos_12`, `leads_qualificados`
      (= +12 + -12, ambíguos OUT). Recalcula CPL e taxas que dependem de
      leads/qualif (cpl, tx_qualificacao, tx_lead_deal).

    `tx_deal_venda` (vendas/deals) NÃO muda — ambos vêm de mv_mkt_funil.
    """
    if df.empty:
        return dict(_FUNIL_ZEROS)

    invest = float(df["investimento"].sum())
    leads = float(df["leads"].sum())
    q_mais = float(df["leads_qualif_mais_12"].sum())
    q_menos = float(df["leads_qualif_menos_12"].sum())
    qualif = q_mais + q_menos
    deals = float(df["deals"].sum())
    deals_ganhos = float(df["deals_ganhos"].sum())
    vendas = float(df["vendas"].sum())
    valor_v = float(df["valor_venda"].sum()) if "valor_venda" in df.columns else 0.0
    valor_r = float(df["valor_receita"].sum())

    out = {
        "investimento": invest,
        "impressoes": float(df["impressoes"].sum()) if "impressoes" in df.columns else 0.0,
        "cliques": float(df["cliques"].sum()) if "cliques" in df.columns else 0.0,
        "leads": leads,
        "leads_qualif_mais_12": q_mais,
        "leads_qualif_menos_12": q_menos,
        "leads_qualificados": qualif,
        "deals": deals,
        "deals_ganhos": deals_ganhos,
        "vendas": vendas,
        "valor_venda": valor_v,
        "valor_receita": valor_r,
        "cpl": _safe_div(invest, leads),
        "tx_qualificacao": _safe_div(qualif, leads) * 100,
        "tx_lead_deal": _safe_div(deals, leads) * 100,
        "tx_deal_venda": _safe_div(vendas, deals) * 100,
    }

    # Override leads pela fonte validada lp_form quando disponível
    if (df_lp_funil is not None
            and not df_lp_funil.empty
            and "leads_lp_unicos" in df_lp_funil.columns):
        leads_validado = float(df_lp_funil["leads_lp_unicos"].sum())
        out["leads"] = leads_validado
        # CPL e taxas que usam leads no denominador são recalculados
        out["cpl"] = _safe_div(invest, leads_validado)
        out["tx_qualificacao"] = _safe_div(out["leads_qualificados"], leads_validado) * 100
        out["tx_lead_deal"] = _safe_div(deals, leads_validado) * 100

    # Override +12/-12/qualif pela fonte deduplicada (ambíguos OUT)
    if (df_classif is not None
            and not df_classif.empty
            and "lead_mais_12" in df_classif.columns
            and "lead_menos_12" in df_classif.columns):
        q_mais_v = float(df_classif["lead_mais_12"].sum())
        q_menos_v = float(df_classif["lead_menos_12"].sum())
        qualif_v = q_mais_v + q_menos_v
        out["leads_qualif_mais_12"] = q_mais_v
        out["leads_qualif_menos_12"] = q_menos_v
        out["leads_qualificados"] = qualif_v
        # tx_qualificacao recalcula com qualif novo / leads (já possivelmente
        # sobrescrito por df_lp_funil acima)
        out["tx_qualificacao"] = _safe_div(qualif_v, out["leads"]) * 100

    return out


def funil_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Série diária consolidada (todos canais filtrados): invest, leads,
    deals, vendas — para o gráfico de evolução."""
    cols = ["data_ref", "investimento", "leads", "deals", "vendas"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    agg = df.groupby("data_ref", as_index=False).agg(
        investimento=("investimento", "sum"),
        leads=("leads", "sum"),
        deals=("deals", "sum"),
        vendas=("vendas", "sum"),
    )
    return agg[cols].sort_values("data_ref").reset_index(drop=True)


def funil_estagios(k: dict) -> tuple[list[str], list[float]]:
    """A partir do dict de KPIs do funil, devolve (labels, values) para o
    componente de funil visual: 5 estágios."""
    labels = ["Leads", "Qualificados", "Deals", "Deals Ganhos", "Vendas"]
    values = [
        float(k.get("leads", 0)),
        float(k.get("leads_qualificados", 0)),
        float(k.get("deals", 0)),
        float(k.get("deals_ganhos", 0)),
        float(k.get("vendas", 0)),
    ]
    return labels, values


def funil_por_canal(df: pd.DataFrame,
                    canais_visiveis: list[str] | None = None,
                    df_classif_canal: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tabela por canal — invest, leads, qualif, deals, vendas, receita,
    conversoes_pct (= vendas / leads * 100, taxa lead → venda).

    Quando `canais_visiveis` é fornecido, garante que cada canal aparece
    como linha (zerada se sem dados). Mantém Pinterest/Google na UI
    mesmo quando não há volume.

    Quando `df_classif_canal` é passado (de `bi.vw_mkt_leads_classificacao`
    com grão de canal), `leads` e `leads_qualificados` vêm da fonte
    deduplicada validada (mesmo padrão de overview/roas). `conversoes_pct`
    é recalculada com leads dedup como denominador. Deals, vendas, receita
    continuam de `mv_mkt_funil` (CRM, sem dedup de leads).

    Estrutura: OUTER JOIN entre paid (mv_mkt_funil) e dedup — preserva canais
    que existem só num lado.

    ⚠ Política V1: se `df_classif_canal` chegar None/vazio, leads/qualif caem
    para os valores INFLADOS de mv_mkt_funil (fallback)."""
    cols = ["canal", "investimento", "leads", "leads_qualificados",
            "deals", "vendas", "valor_receita", "conversoes_pct"]

    has_paid = not df.empty
    has_dedup = (
        df_classif_canal is not None
        and not df_classif_canal.empty
        and {"canal", "lead_mais_12", "lead_menos_12", "leads_unicos_canal"}
            .issubset(df_classif_canal.columns)
    )

    # Caso totalmente vazio (sem paid e sem dedup) — respeita canais_visiveis
    if not has_paid and not has_dedup:
        if not canais_visiveis:
            return pd.DataFrame(columns=cols)
        out = pd.DataFrame({"canal": canais_visiveis})
        for c in cols[1:]:
            out[c] = 0.0
        return out

    # --- 1) Lado paid (mv_mkt_funil) — invest/deals/vendas/receita + leads_overview
    if has_paid:
        df_calc = df.copy()
        df_calc["leads_qualificados_overview"] = (
            df_calc["leads_qualif_mais_12"].fillna(0)
            + df_calc["leads_qualif_menos_12"].fillna(0)
        )
        paid = df_calc.groupby("canal", as_index=False).agg(
            investimento=("investimento", "sum"),
            leads_overview=("leads", "sum"),
            leads_qualificados_overview=("leads_qualificados_overview", "sum"),
            deals=("deals", "sum"),
            vendas=("vendas", "sum"),
            valor_receita=("valor_receita", "sum"),
        )
    else:
        paid = pd.DataFrame(columns=["canal", "investimento", "leads_overview",
                                       "leads_qualificados_overview",
                                       "deals", "vendas", "valor_receita"])

    # --- 2) Lado dedup (vw_mkt_leads_classificacao com canal)
    if has_dedup:
        dedup = df_classif_canal[
            ["canal", "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
        ].copy()
    else:
        dedup = pd.DataFrame(
            columns=["canal", "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
        )

    # --- 3) OUTER JOIN — preserva canais de qualquer lado
    agg = paid.merge(dedup, on="canal", how="outer")
    for c in ("investimento", "leads_overview", "leads_qualificados_overview",
              "deals", "vendas", "valor_receita",
              "leads_unicos_canal", "lead_mais_12", "lead_menos_12"):
        if c in agg.columns:
            agg[c] = agg[c].fillna(0)

    # --- 4) Escolha de fonte para leads/qualif: dedup quando disponível
    if has_dedup:
        agg["leads"] = agg["leads_unicos_canal"]
        # Qualif. = +12 + -12 (ambíguos OUT por construção do dedup)
        agg["leads_qualificados"] = agg["lead_mais_12"] + agg["lead_menos_12"]
    else:
        # ⚠ FALLBACK V1: valores INFLADOS de mv_mkt_funil
        agg["leads"] = agg["leads_overview"]
        agg["leads_qualificados"] = agg["leads_qualificados_overview"]

    # Garante canais visíveis na lista (mesmo zerados) — se fornecido
    if canais_visiveis:
        seed = pd.DataFrame({"canal": list(canais_visiveis)})
        agg = seed.merge(agg, on="canal", how="left")
        for c in ("investimento", "leads", "leads_qualificados",
                  "deals", "vendas", "valor_receita"):
            if c in agg.columns:
                agg[c] = agg[c].fillna(0)

    # --- 5) conversoes_pct = vendas / leads (denominador dedup quando ativo)
    agg["conversoes_pct"] = agg.apply(
        lambda r: _safe_div(r["vendas"], r["leads"]) * 100, axis=1
    )

    # --- 6) Limpa helpers
    helper_cols = ["leads_overview", "leads_qualificados_overview",
                   "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
    agg = agg.drop(columns=[c for c in helper_cols if c in agg.columns])

    return (agg[cols]
            .sort_values("valor_receita", ascending=False)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Funil Marketing — versão "oficial" alinhada com Visão Geral / Growth
# ---------------------------------------------------------------------------
# Substitui os transforms `funil_*` que dependiam de bi.mv_mkt_funil. Lê das
# fontes oficiais já validadas:
#   - mkt_visao_geral_kpis_canal.sql      (invest, leads, qualif, +12, -12,
#                                          vendas total, vendas novas,
#                                          montante, receita por canal)
#   - mkt_campanhas_leads_canal_diario.sql(leads/+12/-12 diários por canal —
#                                          opcional pra séries por canal-dia)
#   - mkt_growth_atividades_canal.sql     (agendamentos / comparecimentos
#                                          por canal — versão otimizada)
#   - mkt_visao_geral_diario.sql          (série diária total geral pra
#                                          tendência — mesma política da
#                                          Visão Geral / ROAS-CAC)
# Os transforms antigos (funil_kpis, funil_diario, etc.) continuam neste
# arquivo porque `views/marketing_campaigns.py` ainda os consome; apenas a
# página Funil deixa de usá-los.

_FUNIL_OFICIAL_ZEROS = {
    "investimento": 0.0,
    "leads": 0, "leads_qualificados": 0,
    "leads_mais_12": 0, "leads_menos_12": 0,
    "agendamentos": 0, "comparecimentos": 0,
    "vendas": 0,                  # = vendas_total_geral (Ganho/Fechado Ganho)
    "vendas_novas": 0,            # = vendas_novas_total_geral (Novo cliente)
    "montante": 0.0, "valor_receita": 0.0,
    "tx_qualificacao": 0.0,
    "tx_lead_agend": 0.0, "tx_agend_compar": 0.0,
    "tx_compar_venda": 0.0, "tx_lead_venda": 0.0,
    "cpl": 0.0, "cpl_qualificado": 0.0,
    "ticket_medio": 0.0,
}


def funil_kpis_oficial(df_kpc: pd.DataFrame,
                       df_atividades_canal: pd.DataFrame | None = None,
                       canais: list[str] | None = None,
                       todos_canais: bool = True) -> dict:
    """KPIs do funil de marketing alinhados com a regra oficial.

    Fontes (mesmas das outras páginas):
      - df_kpc: `mkt_visao_geral_kpis_canal.sql` — invest + leads + financeiro
        por canal (incluindo 'Sem canal' para deals não atribuídos).
      - df_atividades_canal: `mkt_growth_atividades_canal.sql` — leads únicos
        com activity Consulta/Indicação ligada via deal pareado.

    Quando `todos_canais=True`, soma TODAS as rows (inclusive 'Sem canal') —
    bate com o agregado da Visão Geral. Senão soma só os canais selecionados.

    Taxas recalculadas no agregado, não média de taxas:
      tx_qualificacao   = qualif / leads * 100
      tx_lead_agend     = agend / leads * 100
      tx_agend_compar   = compar / agend * 100
      tx_compar_venda   = vendas_novas / compar * 100
      tx_lead_venda     = vendas_novas / leads * 100
      cpl               = invest / leads
      cpl_qualificado   = invest / qualif
      ticket_medio      = receita / vendas
    """
    out = dict(_FUNIL_OFICIAL_ZEROS)
    if df_kpc is None or df_kpc.empty:
        return out

    sub_kpc = df_kpc if todos_canais else df_kpc[df_kpc["canal"].isin(canais or [])]
    if not sub_kpc.empty:
        out["investimento"]       = float(sub_kpc["investimento_total_geral"].sum())
        out["leads"]              = int(sub_kpc["leads_totais"].sum())
        out["leads_qualificados"] = int(sub_kpc["leads_qualificados"].sum())
        out["leads_mais_12"]      = int(sub_kpc["leads_mais_12"].sum())
        out["leads_menos_12"]     = int(sub_kpc["leads_menos_12"].sum())
        out["vendas"]             = int(sub_kpc["vendas_total_geral"].sum())
        out["vendas_novas"]       = int(sub_kpc["vendas_novas_total_geral"].sum())
        out["montante"]           = float(sub_kpc["montante_total_geral"].sum())
        out["valor_receita"]      = float(sub_kpc["receita_total_geral"].sum())

    # Atividades — leads únicos por activity Consulta/Indicação
    if df_atividades_canal is not None and not df_atividades_canal.empty:
        sub_act = (df_atividades_canal if todos_canais
                   else df_atividades_canal[df_atividades_canal["canal"].isin(canais or [])])
        if not sub_act.empty:
            out["agendamentos"] = int(sub_act["leads_com_agendamento"].sum())
            out["comparecimentos"] = int(sub_act["leads_com_comparecimento"].sum())

    invest, leads, qualif, agend, compar = (
        out["investimento"], out["leads"], out["leads_qualificados"],
        out["agendamentos"], out["comparecimentos"],
    )
    novas, vendas, receita = (
        out["vendas_novas"], out["vendas"], out["valor_receita"]
    )

    out["tx_qualificacao"] = _safe_div(qualif, leads) * 100
    out["tx_lead_agend"]   = _safe_div(agend, leads) * 100
    out["tx_agend_compar"] = _safe_div(compar, agend) * 100
    out["tx_compar_venda"] = _safe_div(novas, compar) * 100
    out["tx_lead_venda"]   = _safe_div(novas, leads) * 100
    out["cpl"]             = _safe_div(invest, leads)
    out["cpl_qualificado"] = _safe_div(invest, qualif)
    out["ticket_medio"]    = _safe_div(receita, vendas)
    return out


def funil_estagios_oficial(k: dict) -> tuple[list[str], list[float]]:
    """6 etapas do funil de marketing oficial:
        Investimento → Leads → Qualificados → Agendamentos →
        Comparecimentos → Vendas novas

    Investimento entra como R$ (escala diferente das contagens) — a UI
    decide se renderiza como Plotly funnel separado ou como um valor de
    contexto. Mesma estrutura de `funil_estagios` legado, apenas com etapas
    alinhadas à regra oficial Visão Geral / Growth (Vendas = Novo cliente)."""
    labels = ["Investimento", "Leads", "Qualificados",
              "Agendamentos", "Comparecimentos", "Vendas novas"]
    values = [
        float(k.get("investimento", 0) or 0),
        float(k.get("leads", 0) or 0),
        float(k.get("leads_qualificados", 0) or 0),
        float(k.get("agendamentos", 0) or 0),
        float(k.get("comparecimentos", 0) or 0),
        float(k.get("vendas_novas", 0) or 0),
    ]
    return labels, values


def funil_diario_oficial(df_vg_diario: pd.DataFrame) -> pd.DataFrame:
    """Série diária pra tendência do Funil Marketing.

    Fonte: `mkt_visao_geral_diario.sql` — 1 linha por data_ref com invest,
    leads, qualif, vendas (totais + novas), montante e receita do total
    geral. Mesma política da Visão Geral / ROAS-CAC: tendência diária NÃO
    filtra por canal (é total geral). Filtros de canal afetam cards e
    tabela por canal."""
    cols = ["data_ref", "investimento", "leads", "leads_qualificados",
            "vendas", "vendas_novas", "valor_receita"]
    if df_vg_diario is None or df_vg_diario.empty:
        return pd.DataFrame(columns=cols)
    out = df_vg_diario.rename(columns={
        "investimento_total_geral": "investimento",
        "leads_totais": "leads",
        "vendas_total_geral": "vendas",
        "vendas_novas_total_geral": "vendas_novas",
        "receita_total_geral": "valor_receita",
    }).copy()
    for c in ("investimento", "leads", "leads_qualificados",
              "vendas", "vendas_novas", "valor_receita"):
        if c not in out.columns:
            out[c] = 0
        out[c] = out[c].fillna(0)
    return out[cols].sort_values("data_ref").reset_index(drop=True)


def funil_por_canal_oficial(
    df_kpc: pd.DataFrame,
    df_atividades_canal: pd.DataFrame | None = None,
    canais_visiveis: list[str] | None = None,
) -> pd.DataFrame:
    """Tabela por canal — 1 linha por canal alinhada com Visão Geral.

    Invest / leads / qualif / +12 / -12 / vendas / vendas_novas / montante /
    receita: `df_kpc` (`mkt_visao_geral_kpis_canal.sql`).
    Agendamentos / comparecimentos: `df_atividades_canal`
    (`mkt_growth_atividades_canal.sql` otimizada).

    `canais_visiveis` força reindex pra preservar canais sem dado (ex.:
    Pinterest com invest mas sem vendas) — mesma política das outras
    tabelas. Quando None, devolve só os canais com dados."""
    cols = ["canal", "investimento", "leads", "leads_qualificados",
            "leads_mais_12", "leads_menos_12",
            "agendamentos", "comparecimentos",
            "vendas", "vendas_novas",
            "montante", "valor_receita",
            "cpl", "tx_qualificacao", "tx_lead_venda"]

    has_kpc = df_kpc is not None and not df_kpc.empty
    has_act = (df_atividades_canal is not None
               and not df_atividades_canal.empty)
    if not has_kpc and not has_act:
        return pd.DataFrame(columns=cols)

    if has_kpc:
        agg = df_kpc[["canal",
                      "investimento_total_geral",
                      "leads_totais", "leads_qualificados",
                      "leads_mais_12", "leads_menos_12",
                      "vendas_total_geral", "vendas_novas_total_geral",
                      "montante_total_geral", "receita_total_geral"]].copy()
        agg = agg.rename(columns={
            "investimento_total_geral": "investimento",
            "leads_totais": "leads",
            "vendas_total_geral": "vendas",
            "vendas_novas_total_geral": "vendas_novas",
            "montante_total_geral": "montante",
            "receita_total_geral": "valor_receita",
        })
    else:
        agg = pd.DataFrame(columns=["canal", "investimento", "leads",
                                     "leads_qualificados",
                                     "leads_mais_12", "leads_menos_12",
                                     "vendas", "vendas_novas",
                                     "montante", "valor_receita"])

    if has_act:
        act = df_atividades_canal[["canal", "leads_com_agendamento",
                                    "leads_com_comparecimento"]].copy()
        act = act.rename(columns={
            "leads_com_agendamento": "agendamentos",
            "leads_com_comparecimento": "comparecimentos",
        })
        agg = agg.merge(act, on="canal", how="outer")
    else:
        agg["agendamentos"] = 0
        agg["comparecimentos"] = 0

    if canais_visiveis:
        seed = pd.DataFrame({"canal": list(canais_visiveis)})
        agg = seed.merge(agg, on="canal", how="left")

    for c in ("investimento", "leads", "leads_qualificados",
              "leads_mais_12", "leads_menos_12",
              "agendamentos", "comparecimentos",
              "vendas", "vendas_novas",
              "montante", "valor_receita"):
        if c in agg.columns:
            agg[c] = agg[c].fillna(0)

    agg["cpl"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads"]), axis=1
    )
    agg["tx_qualificacao"] = agg.apply(
        lambda r: _safe_div(r["leads_qualificados"], r["leads"]) * 100, axis=1
    )
    agg["tx_lead_venda"] = agg.apply(
        lambda r: _safe_div(r["vendas_novas"], r["leads"]) * 100, axis=1
    )

    return (agg[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Criativos (Meta-only)
# ---------------------------------------------------------------------------

# Mapeamento Meta API → labels PT-BR. Valores cobrem o que a Meta documenta hoje;
# qualquer valor desconhecido cai em fallback "como veio" para não inventar dado.
_STATUS_MAP = {
    "ACTIVE":               "Ativo",
    "PAUSED":               "Pausado",
    "LEARNING":             "Aprendendo",
    "IN_PROCESS":           "Em processamento",
    "DELETED":              "Excluído",
    "ARCHIVED":             "Arquivado",
    "DISAPPROVED":          "Reprovado",
    "PENDING_REVIEW":       "Em revisão",
    "PREAPPROVED":          "Pré-aprovado",
    "PENDING_BILLING_INFO": "Aguardando pagamento",
    "CAMPAIGN_PAUSED":      "Campanha pausada",
    "ADSET_PAUSED":         "Conjunto pausado",
    "WITH_ISSUES":          "Com problemas",
}

_QUALITY_MAP = {
    "ABOVE_AVERAGE":            "Acima da média",
    "AVERAGE":                  "Média",
    "BELOW_AVERAGE_10":         "Abaixo da média",
    "BELOW_AVERAGE_20":         "Abaixo da média",
    "BELOW_AVERAGE_35":         "Abaixo da média",
    "BELOW_AVERAGE_BOTTOM_10":  "Abaixo da média",
    "BELOW_AVERAGE_BOTTOM_20":  "Abaixo da média",
    "BELOW_AVERAGE_BOTTOM_35":  "Abaixo da média",
    "UNKNOWN":                  "Desconhecido",
}


def normalize_status(raw) -> str:
    if raw is None or (isinstance(raw, float) and raw != raw):  # NaN
        return "Não informado"
    s = str(raw).strip()
    if not s:
        return "Não informado"
    return _STATUS_MAP.get(s.upper(), s)


def normalize_quality(raw) -> str:
    if raw is None or (isinstance(raw, float) and raw != raw):
        return "Não informado"
    s = str(raw).strip()
    if not s:
        return "Não informado"
    return _QUALITY_MAP.get(s.upper(), s)


_CRIATIVOS_ZEROS = {
    # Plataforma (vw_mkt_criativos)
    "anuncios_ativos": 0,
    "investimento": 0.0,
    "impressoes": 0.0,
    "cliques": 0.0,
    "alcance": 0.0,
    "ctr": 0.0,
    "cpc": 0.0,
    "frequencia": 0.0,
    # Resultado (mart) — None ("—") quando ausente
    "tem_resultados": False,
    "leads_total": None, "leads_mais_12": None, "leads_menos_12": None,
    "leads_nao_atua": None,
    "agendamentos": None, "comparecimentos": None, "no_shows": None,
    "deals": None, "deals_ganhos": None,
    "vendas": None, "valor_venda": None, "valor_receita": None,
    # Derivadas (invest oficial / contagens mart)
    "cpl": None, "cpl_mais_12": None, "cac": None, "roas": None,
}


def criativos_kpis(df: pd.DataFrame,
                   df_resultados: pd.DataFrame | None = None) -> dict:
    """KPIs consolidados de Criativos (Meta-only).

    Plataforma vem de `df` (`bi.vw_mkt_criativos`, fonte oficial).
    Resultado vem de `df_resultados` (`odam.mart_ad_funnel_daily` agregado por
    ad_id). Quando `df_resultados` não chega ou vem vazio, métricas de
    resultado e derivadas ficam None ("—" no formatador).

    Derivadas usam INVEST OFICIAL (df) sobre numerador da mart:
      cpl       = invest / leads_total
      cpl_+12   = invest / leads_mais_12
      cac       = invest / vendas
      roas      = valor_receita / invest
    Denominador zero → None ("—" honesto, em vez de R$ 0)."""
    out = dict(_CRIATIVOS_ZEROS)

    if df.empty:
        return out

    invest = float(df["investimento"].sum())
    imp = float(df["impressoes"].sum())
    clk = float(df["cliques"].sum())
    alc = float(df["alcance"].fillna(0).sum()) if "alcance" in df.columns else 0.0

    ativos_mask = df["investimento"] > 0
    ativos = int(df.loc[ativos_mask, "ad_id"].nunique())

    out.update({
        "anuncios_ativos": ativos,
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "alcance": alc,
        "ctr": _safe_div(clk, imp) * 100,
        "cpc": _safe_div(invest, clk),
        "frequencia": _safe_div(imp, alc),
    })

    # Resultado (mart) — soma todas as linhas de ad_id presentes no df_resultados
    has_results = (
        df_resultados is not None
        and not df_resultados.empty
        and "ad_id" in df_resultados.columns
    )
    if has_results:
        leads_total = float(df_resultados["leads_total"].sum())
        leads_mais_12 = float(df_resultados["leads_mais_12"].sum())
        leads_menos_12 = float(df_resultados["leads_menos_12"].sum())
        leads_nao_atua = float(df_resultados["leads_nao_atua"].sum())
        agend = float(df_resultados["agendamentos"].sum())
        comp = float(df_resultados["comparecimentos"].sum())
        no_shows = float(df_resultados["no_shows"].sum())
        deals = float(df_resultados["deals"].sum())
        deals_g = float(df_resultados["deals_ganhos"].sum())
        vendas = float(df_resultados["vendas"].sum())
        valor_v = float(df_resultados["valor_venda"].sum())
        valor_r = float(df_resultados["valor_receita"].sum())

        out["tem_resultados"] = True
        out["leads_total"] = leads_total
        out["leads_mais_12"] = leads_mais_12
        out["leads_menos_12"] = leads_menos_12
        out["leads_nao_atua"] = leads_nao_atua
        out["agendamentos"] = agend
        out["comparecimentos"] = comp
        out["no_shows"] = no_shows
        out["deals"] = deals
        out["deals_ganhos"] = deals_g
        out["vendas"] = vendas
        out["valor_venda"] = valor_v
        out["valor_receita"] = valor_r

        # Derivadas — None se denominador zero
        out["cpl"] = (invest / leads_total) if leads_total > 0 else None
        out["cpl_mais_12"] = (invest / leads_mais_12) if leads_mais_12 > 0 else None
        out["cac"] = (invest / vendas) if vendas > 0 else None
        out["roas"] = (valor_r / invest) if invest > 0 else None

    return out


def criativos_por_status(df: pd.DataFrame) -> pd.DataFrame:
    """Donut: investimento por status normalizado (apenas status com invest > 0)."""
    if df.empty:
        return pd.DataFrame(columns=["status_label", "investimento"])
    d = df.copy()
    d["status_label"] = d["effective_status"].apply(normalize_status)
    agg = (d.groupby("status_label", as_index=False)
             .agg(investimento=("investimento", "sum")))
    agg = agg[agg["investimento"] > 0]
    return agg.sort_values("investimento", ascending=False).reset_index(drop=True)


def criativos_por_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Donut: investimento por quality_ranking normalizado."""
    if df.empty:
        return pd.DataFrame(columns=["quality_label", "investimento"])
    d = df.copy()
    d["quality_label"] = d["quality_ranking"].apply(normalize_quality)
    agg = (d.groupby("quality_label", as_index=False)
             .agg(investimento=("investimento", "sum")))
    agg = agg[agg["investimento"] > 0]
    return agg.sort_values("investimento", ascending=False).reset_index(drop=True)


def criativos_ranking(df: pd.DataFrame,
                      sort_by: str = "investimento",
                      ascending: bool = False,
                      top_n: int = 12,
                      df_resultados: pd.DataFrame | None = None) -> pd.DataFrame:
    """Top N criativos com invest > 0 no período, agregados por ad_id.

    `sort_by` aceita:
      - Plataforma: investimento, impressoes, cliques, alcance, ctr, cpc
      - Resultado (se df_resultados disponível): leads_total, leads_mais_12,
        leads_menos_12, leads_nao_atua, agendamentos, vendas, valor_receita
      - Derivadas: cpl, cpl_mais_12, cac, roas

    Para CPC/CPL/CPL+12/CAC, passe `ascending=True` (menor é melhor).

    Quando `df_resultados` é fornecido, faz LEFT MERGE por ad_id — anúncios
    sem linha na mart aparecem com métricas de resultado/derivadas como
    NaN/None. Para sort por essas métricas, NaN vai pro fim por padrão do
    pandas (na_position='last')."""
    cols_base = ["ad_id", "ad_name", "campaign_name",
                 "investimento", "impressoes", "cliques", "alcance",
                 "ctr", "cpc",
                 "thumbnail_url", "image_url", "permalink_url",
                 "effective_status", "status_label"]
    cols_resultado = ["leads_total", "leads_mais_12", "leads_menos_12",
                      "leads_nao_atua",
                      "agendamentos", "comparecimentos", "no_shows",
                      "deals", "deals_ganhos", "vendas", "valor_receita",
                      "cpl", "cpl_mais_12", "cac", "roas"]
    cols = cols_base + cols_resultado

    if df.empty:
        return pd.DataFrame(columns=cols)

    agg = df.groupby("ad_id", as_index=False).agg(
        ad_name=("ad_name", "first"),
        campaign_name=("campaign_name", "first"),
        investimento=("investimento", "sum"),
        impressoes=("impressoes", "sum"),
        cliques=("cliques", "sum"),
        alcance=("alcance", "sum"),
        thumbnail_url=("thumbnail_url", "first"),
        image_url=("image_url", "first"),
        permalink_url=("permalink_url", "first"),
        effective_status=("effective_status", "first"),
    )
    agg = agg[agg["investimento"] > 0].copy()
    if agg.empty:
        return pd.DataFrame(columns=cols)

    agg["ctr"] = agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )
    agg["cpc"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["cliques"]), axis=1
    )
    agg["status_label"] = agg["effective_status"].apply(normalize_status)

    # Merge com resultados da mart por ad_id — LEFT preserva ads sem mart
    has_results = (
        df_resultados is not None
        and not df_resultados.empty
        and "ad_id" in df_resultados.columns
    )
    if has_results:
        # Garante que ad_id tenha o mesmo dtype dos dois lados (string)
        agg["ad_id"] = agg["ad_id"].astype(str)
        res = df_resultados.copy()
        res["ad_id"] = res["ad_id"].astype(str)
        agg = agg.merge(
            res[["ad_id", "leads_total", "leads_mais_12", "leads_menos_12",
                 "leads_nao_atua",
                 "agendamentos", "comparecimentos", "no_shows",
                 "deals", "deals_ganhos", "vendas", "valor_receita"]],
            on="ad_id", how="left",
        )
        # Derivadas por linha — NaN se denominador zero/ausente
        def _safe_or_nan(num, den):
            if pd.isna(num) or pd.isna(den) or den == 0:
                return float("nan")
            return float(num) / float(den)
        agg["cpl"] = agg.apply(
            lambda r: _safe_or_nan(r["investimento"], r.get("leads_total")),
            axis=1,
        )
        agg["cpl_mais_12"] = agg.apply(
            lambda r: _safe_or_nan(r["investimento"], r.get("leads_mais_12")),
            axis=1,
        )
        agg["cac"] = agg.apply(
            lambda r: _safe_or_nan(r["investimento"], r.get("vendas")),
            axis=1,
        )
        agg["roas"] = agg.apply(
            lambda r: _safe_or_nan(r.get("valor_receita"), r["investimento"]),
            axis=1,
        )
    else:
        # Sem mart — colunas de resultado/derivadas viram NaN
        for c in cols_resultado:
            agg[c] = float("nan")

    if sort_by not in agg.columns:
        sort_by = "investimento"
    return (agg.sort_values(sort_by, ascending=ascending, na_position="last")
              .head(top_n)[cols]
              .reset_index(drop=True))


def _ad_name_norm_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.lower()


def criativos_top_por_nome_ranking(
    df: pd.DataFrame,
    df_top_nome: pd.DataFrame,
    df_resultados: pd.DataFrame | None,
    sort_by: str = "investimento",
    ascending: bool = False,
    top_n: int = 12,
) -> pd.DataFrame:
    """Top N criativos por nome normalizado (utm_content = ad_name).

    **Base obrigatória:** `df_top_nome` (`mkt_top_criativos_por_nome.sql`).
    Não exige `bi.vw_mkt_criativos` nem mart para listar criativos.

    `df` (view filtrada) e `df_resultados` são só enriquecimento e filtro
    opcional de campanha/status: merge sempre **à esquerda** a partir da base
    fdw+lp_form; se não houver match, o card segue sem thumb/status."""
    cols_base = ["ad_id", "ad_name", "campaign_name",
                 "investimento", "impressoes", "cliques", "alcance",
                 "ctr", "cpc",
                 "thumbnail_url", "image_url", "permalink_url",
                 "effective_status", "status_label"]
    cols_extra = ["qtd_ad_ids", "qtd_campaigns", "qtd_adsets", "leads_meta", "cpl_meta"]
    cols_aplicacoes = ["aplicacoes", "aplicacoes_mais_12", "aplicacoes_menos_12"]
    cols_resultado = ["leads_total", "leads_mais_12", "leads_menos_12",
                      "leads_nao_atua",
                      "agendamentos", "comparecimentos", "no_shows",
                      "deals", "deals_ganhos", "vendas", "valor_receita",
                      "cpl", "cpl_mais_12", "cac", "roas"]
    cols = cols_base + cols_extra + cols_aplicacoes + cols_resultado

    empty = pd.DataFrame(columns=cols)
    if df_top_nome is None or df_top_nome.empty:
        return empty
    if "ad_name_norm" not in df_top_nome.columns:
        return empty

    base = df_top_nome.copy()
    base["ad_name_norm"] = base["ad_name_norm"].astype(str)

    base["investimento"] = pd.to_numeric(
        base.get("investimento"), errors="coerce"
    ).fillna(0)
    if "leads_reais" in base.columns:
        base["leads_total"] = pd.to_numeric(
            base["leads_reais"], errors="coerce"
        ).fillna(0)
    else:
        base["leads_total"] = 0.0

    for lc in ("leads_mais_12", "leads_menos_12", "leads_nao_atua"):
        if lc in base.columns:
            base[lc] = pd.to_numeric(base[lc], errors="coerce").fillna(0)
        else:
            base[lc] = 0.0

    for ac in cols_aplicacoes:
        if ac in base.columns:
            base[ac] = pd.to_numeric(base[ac], errors="coerce").fillna(0)
        else:
            base[ac] = 0.0

    if "cpl_real" in base.columns:
        base["cpl"] = pd.to_numeric(base["cpl_real"], errors="coerce")
    else:
        lt = base["leads_total"]
        base["cpl"] = base["investimento"] / lt.where(lt > 0)

    if "cpl_mais_12" in base.columns:
        base["cpl_mais_12"] = pd.to_numeric(base["cpl_mais_12"], errors="coerce")
    else:
        lm = base["leads_mais_12"]
        base["cpl_mais_12"] = base["investimento"] / lm.where(lm > 0)

    for c in ("ctr", "cpc", "impressoes", "cliques", "alcance", "leads_meta"):
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce")

    base = base.loc[base["investimento"] > 0].copy()
    if base.empty:
        return empty

    # Filtro opcional por campanha/status (via vw): só restringe se houver
    # interseção não vazia — nunca esvazia o Top 12 por falta de match na BI.
    df_work: pd.DataFrame | None = None
    if (
        df is not None
        and not df.empty
        and "ad_name" in df.columns
        and "ad_id" in df.columns
    ):
        df_work = df.copy()
        df_work["ad_name_norm"] = _ad_name_norm_series(df_work["ad_name"])
        inv_vw = (
            df_work.groupby("ad_name_norm", as_index=False)["investimento"]
            .sum()
        )
        allowed_vw = set(
            inv_vw.loc[inv_vw["investimento"] > 0, "ad_name_norm"].astype(str)
        )
        if allowed_vw:
            cand = base[base["ad_name_norm"].isin(allowed_vw)].copy()
            if not cand.empty:
                base = cand

    rep_cols = [
        "ad_name_norm", "ad_id", "thumbnail_url", "image_url", "permalink_url",
        "effective_status", "status_label",
    ]
    rep_rows: list[dict] = []
    if df_work is not None:
        for norm, sub in df_work.groupby("ad_name_norm"):
            nstr = str(norm)
            by_ad = (
                sub.groupby("ad_id", as_index=False)["investimento"]
                .sum()
                .sort_values("investimento", ascending=False)
            )
            if by_ad.empty:
                continue
            top_ad_id = by_ad.iloc[0]["ad_id"]
            one = sub[sub["ad_id"].astype(str) == str(top_ad_id)]
            if one.empty:
                continue
            r = one.iloc[0]
            eff = r.get("effective_status")
            rep_rows.append({
                "ad_name_norm": nstr,
                "ad_id": str(top_ad_id),
                "thumbnail_url": r.get("thumbnail_url"),
                "image_url": r.get("image_url"),
                "permalink_url": r.get("permalink_url"),
                "effective_status": eff,
                "status_label": normalize_status(eff),
            })

    rep_df = (
        pd.DataFrame(rep_rows, columns=rep_cols)
        if rep_rows else pd.DataFrame(columns=rep_cols)
    )

    out = base.merge(rep_df, on="ad_name_norm", how="left")
    out["ad_id"] = out["ad_id"].fillna("").astype(str)

    mask_sl = out["status_label"].isna() | (out["status_label"].astype(str).str.strip() == "")
    if mask_sl.any():
        out.loc[mask_sl, "status_label"] = (
            out.loc[mask_sl, "effective_status"].map(normalize_status)
        )

    mart_cols = [
        "agendamentos", "comparecimentos", "no_shows",
        "deals", "deals_ganhos", "vendas", "valor_receita",
    ]
    if (
        df_work is not None
        and df_resultados is not None
        and not df_resultados.empty
        and "ad_id" in df_resultados.columns
    ):
        m = df_work[["ad_id", "ad_name_norm"]].drop_duplicates()
        m["ad_id"] = m["ad_id"].astype(str)
        res = df_resultados.copy()
        res["ad_id"] = res["ad_id"].astype(str)
        avail = [c for c in mart_cols if c in res.columns]
        if avail:
            mr = m.merge(res[["ad_id", *avail]], on="ad_id", how="left")
            mart_norm = mr.groupby("ad_name_norm", as_index=False)[avail].sum()
            out = out.merge(mart_norm, on="ad_name_norm", how="left")

    for c in mart_cols:
        if c not in out.columns:
            out[c] = float("nan")

    inv = pd.to_numeric(out["investimento"], errors="coerce")
    v_vendas = pd.to_numeric(out["vendas"], errors="coerce")
    v_rec = pd.to_numeric(out["valor_receita"], errors="coerce")
    out["cac"] = inv / v_vendas.where(v_vendas > 0)
    out["roas"] = v_rec / inv.where(inv > 0)

    for c in cols:
        if c not in out.columns:
            out[c] = float("nan")

    sort_col = sort_by
    if sort_col not in out.columns:
        sort_col = "leads_total" if "leads_total" in out.columns else "investimento"
    else:
        mart_only = {
            "agendamentos", "comparecimentos", "no_shows", "deals", "deals_ganhos",
            "vendas", "valor_receita", "cac", "roas",
        }
        if sort_col in mart_only and out[sort_col].notna().sum() == 0:
            sort_col = (
                "leads_total"
                if bool((out["leads_total"] > 0).any())
                else "investimento"
            )
        elif (
            sort_col == "leads_nao_atua"
            and out["leads_nao_atua"].notna().sum() == 0
        ):
            sort_col = (
                "leads_total"
                if "leads_total" in out.columns
                and out["leads_total"].notna().sum() > 0
                else "investimento"
            )

    return (out.sort_values(sort_col, ascending=ascending, na_position="last")
              .head(top_n)[cols]
              .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Cobertura da atribuição POR ad_id (diagnóstico para Criativos)
# ---------------------------------------------------------------------------

_COBERTURA_CRIATIVOS_ZEROS = {
    "total_leads": 0, "leads_com": 0, "leads_sem": 0, "pct_leads_com": 0.0,
    "total_vendas": 0, "vendas_com": 0, "vendas_sem": 0, "pct_vendas_com": 0.0,
    "total_receita": 0.0, "receita_com": 0.0, "receita_sem": 0.0,
    "pct_receita_com": 0.0,
    "nivel": "sem_dados",
}


def cobertura_criativos_kpis(df_cob: pd.DataFrame) -> dict:
    """Cobertura da atribuição da mart por presença de ad_id (diagnóstico
    da página Criativos). Mesma estrutura/níveis de
    `cobertura_atribuicao_kpis` (que faz por campaign_id)."""
    if df_cob is None or df_cob.empty:
        return dict(_COBERTURA_CRIATIVOS_ZEROS)

    r = df_cob.iloc[0]
    total_leads = int(r.get("total_leads_mart", 0) or 0)
    leads_com = int(r.get("leads_com_ad", 0) or 0)
    leads_sem = int(r.get("leads_sem_ad", 0) or 0)
    total_vendas = int(r.get("total_vendas_mart", 0) or 0)
    vendas_com = int(r.get("vendas_com_ad", 0) or 0)
    vendas_sem = int(r.get("vendas_sem_ad", 0) or 0)
    total_receita = float(r.get("total_receita_mart", 0) or 0)
    receita_com = float(r.get("receita_com_ad", 0) or 0)
    receita_sem = float(r.get("receita_sem_ad", 0) or 0)

    pct_leads_com = _safe_div(leads_com, total_leads) * 100
    pct_vendas_com = _safe_div(vendas_com, total_vendas) * 100
    pct_receita_com = _safe_div(receita_com, total_receita) * 100

    if total_leads == 0:
        nivel = "sem_dados"
    elif pct_leads_com >= 80:
        nivel = "alta"
    elif pct_leads_com >= 50:
        nivel = "media"
    else:
        nivel = "baixa"

    return {
        "total_leads": total_leads,
        "leads_com": leads_com,
        "leads_sem": leads_sem,
        "pct_leads_com": pct_leads_com,
        "total_vendas": total_vendas,
        "vendas_com": vendas_com,
        "vendas_sem": vendas_sem,
        "pct_vendas_com": pct_vendas_com,
        "total_receita": total_receita,
        "receita_com": receita_com,
        "receita_sem": receita_sem,
        "pct_receita_com": pct_receita_com,
        "nivel": nivel,
    }


def criativos_tabela(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela detalhada — 1 linha por ad_id agregado, ordenada por invest desc."""
    cols = ["ad_name", "campaign_name", "adset_name", "account_label",
            "status_label",
            "investimento", "impressoes", "alcance", "cliques", "link_clicks",
            "ctr", "cpc", "frequencia",
            "quality_label", "engagement_ranking", "conversion_ranking",
            "permalink_url"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    agg = df.groupby("ad_id", as_index=False).agg(
        ad_name=("ad_name", "first"),
        campaign_name=("campaign_name", "first"),
        adset_name=("adset_name", "first"),
        account_label=("account_label", "first"),
        effective_status=("effective_status", "first"),
        quality_ranking=("quality_ranking", "first"),
        engagement_ranking=("engagement_ranking", "first"),
        conversion_ranking=("conversion_ranking", "first"),
        investimento=("investimento", "sum"),
        impressoes=("impressoes", "sum"),
        alcance=("alcance", "sum"),
        cliques=("cliques", "sum"),
        link_clicks=("link_clicks", "sum"),
        permalink_url=("permalink_url", "first"),
    )
    agg["ctr"] = agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )
    agg["cpc"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["cliques"]), axis=1
    )
    agg["frequencia"] = agg.apply(
        lambda r: _safe_div(r["impressoes"], r["alcance"]), axis=1
    )
    agg["status_label"] = agg["effective_status"].apply(normalize_status)
    agg["quality_label"] = agg["quality_ranking"].apply(normalize_quality)

    return (agg[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Comparação de criativos (V1 — plataforma + resultado atribuído via mart)
# Mesma arquitetura de Comparar campanhas, mas com chave ad_id e identidade
# Campanha/Status/rankings no topo. Plataforma vem de bi.vw_mkt_criativos;
# resultado vem de odam.mart_ad_funnel_daily agregado por ad_id; derivadas
# usam invest oficial (vw) sobre contagens da mart.
# ---------------------------------------------------------------------------

_CRIATIVO_KPIS_ZEROS = {
    # Identidade
    "ad_name": "—", "campaign_name": "—", "status_label": "—",
    "quality_label": "—", "engagement_label": "—", "conversion_label": "—",
    # Plataforma (vw_mkt_criativos)
    "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0,
    "link_clicks": 0.0, "alcance": 0.0,
    "ctr": 0.0, "cpc": 0.0, "frequencia": 0.0,
    # Resultado (mart) — None ("—") quando ausente
    "tem_resultados": False,
    "leads_total": None, "leads_mais_12": None, "leads_menos_12": None,
    "leads_nao_atua": None,
    "agendamentos": None, "comparecimentos": None, "no_shows": None,
    "deals": None, "deals_ganhos": None,
    "vendas": None, "valor_venda": None, "valor_receita": None,
    # Derivadas — None se denominador zero
    "cpl": None, "cpl_mais_12": None, "cac": None, "roas": None,
}


def lista_criativos(df: pd.DataFrame,
                    df_resultados: pd.DataFrame | None = None,
                    sort_by: str = "investimento",
                    ascending: bool = False) -> pd.DataFrame:
    """Lista de criativos para popular os selectboxes da comparação.

    Reaproveita a lógica de `criativos_ranking` (agg por ad_id, merge com
    mart, derivadas), mas devolve TODOS os ad_ids com invest > 0 ordenados
    pelo mesmo `sort_by/ascending` que o usuário escolheu no Top 12.

    Default da seção: top 1 e top 2 dessa lista. Se o ranking estiver por
    investimento, compara os 2 maiores invest; se estiver por ROAS, os 2
    maiores ROAS; etc.

    Colunas:
      ad_id, ad_name, campaign_name, status_label, investimento,
      tem_resultados (bool — se a mart tem linha pra esse ad_id),
      label ('ad_name · campaign · status · R$ XX')."""
    cols = ["ad_id", "ad_name", "campaign_name", "status_label",
            "investimento", "tem_resultados", "label"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    rk = criativos_ranking(
        df, sort_by=sort_by, ascending=ascending, top_n=10**9,
        df_resultados=df_resultados,
    )
    if rk.empty:
        return pd.DataFrame(columns=cols)

    # tem_resultados: linha existe na mart para esse ad_id (ainda que com 0)
    if (df_resultados is not None and not df_resultados.empty
            and "ad_id" in df_resultados.columns):
        ads_com_mart = set(df_resultados["ad_id"].astype(str).unique())
    else:
        ads_com_mart = set()
    rk["ad_id"] = rk["ad_id"].astype(str)
    rk["tem_resultados"] = rk["ad_id"].isin(ads_com_mart)

    def _label(r):
        nome = (r.get("ad_name") or "").strip() or "(sem nome)"
        nome = nome[:55] + ("…" if len(nome) > 55 else "")
        camp = (r.get("campaign_name") or "").strip() or "(sem campanha)"
        camp = camp[:30] + ("…" if len(camp) > 30 else "")
        status = r.get("status_label") or "—"
        invest = float(r.get("investimento") or 0)
        # R$ formatado com separador BR — mantém o select compacto
        return f"{nome} · {camp} · {status} · R$ {invest:,.0f}".replace(
            ",", "."
        )

    rk["label"] = rk.apply(_label, axis=1)
    return rk[cols].reset_index(drop=True)


def criativo_kpis(df: pd.DataFrame,
                  ad_id: str | None,
                  df_resultados: pd.DataFrame | None = None) -> dict:
    """KPIs de UM criativo específico (chave ad_id).

    Plataforma (`bi.vw_mkt_criativos`): invest, imp, cliques, link_clicks,
    alcance, ctr, cpc, frequência, status, quality/engagement/conversion
    rankings (normalizados via _QUALITY_MAP — Meta usa a mesma escala
    `ABOVE_AVERAGE`/`AVERAGE`/`BELOW_AVERAGE_*` para os 3 rankings).

    Resultado (`odam.mart_ad_funnel_daily` agregado por ad_id):
      `tem_resultados=True` se houver linha pro ad_id.
      Sem linha → métricas de resultado e derivadas ficam None ("—" no
      formatador). Linha com 0 real → mostra 0.

    Derivadas usam INVEST OFICIAL (df) sobre contagens da mart. Denominador
    zero → None ("—"), não R$ 0,00."""
    out = dict(_CRIATIVO_KPIS_ZEROS)

    if df.empty or not ad_id:
        return out

    df_one = df[df["ad_id"].astype(str) == str(ad_id)]
    if df_one.empty:
        return out

    # ---- Identidade ------------------------------------------------------
    out["ad_name"] = (df_one["ad_name"].iloc[0]
                      if "ad_name" in df_one.columns
                      and pd.notna(df_one["ad_name"].iloc[0])
                      else "—")
    out["campaign_name"] = (df_one["campaign_name"].iloc[0]
                            if "campaign_name" in df_one.columns
                            and pd.notna(df_one["campaign_name"].iloc[0])
                            else "—")
    if "status_label" in df_one.columns:
        out["status_label"] = df_one["status_label"].iloc[0]
    elif "effective_status" in df_one.columns:
        out["status_label"] = normalize_status(
            df_one["effective_status"].iloc[0]
        )
    out["quality_label"] = (
        normalize_quality(df_one["quality_ranking"].iloc[0])
        if "quality_ranking" in df_one.columns else "—"
    )
    out["engagement_label"] = (
        normalize_quality(df_one["engagement_ranking"].iloc[0])
        if "engagement_ranking" in df_one.columns else "—"
    )
    out["conversion_label"] = (
        normalize_quality(df_one["conversion_ranking"].iloc[0])
        if "conversion_ranking" in df_one.columns else "—"
    )

    # ---- Plataforma ------------------------------------------------------
    invest = float(df_one["investimento"].sum())
    imp = float(df_one["impressoes"].sum())
    clk = float(df_one["cliques"].sum())
    alc = (float(df_one["alcance"].fillna(0).sum())
           if "alcance" in df_one.columns else 0.0)
    link_clk = (float(df_one["link_clicks"].fillna(0).sum())
                if "link_clicks" in df_one.columns else 0.0)

    out.update({
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "link_clicks": link_clk,
        "alcance": alc,
        "ctr": _safe_div(clk, imp) * 100,
        "cpc": _safe_div(invest, clk),
        "frequencia": _safe_div(imp, alc),
    })

    # ---- Resultado (mart) — match interno por ad_id ---------------------
    has_results = (
        df_resultados is not None
        and not df_resultados.empty
        and "ad_id" in df_resultados.columns
    )
    if has_results:
        res = df_resultados.copy()
        res["ad_id"] = res["ad_id"].astype(str)
        match = res[res["ad_id"] == str(ad_id)]
        if not match.empty:
            r = match.iloc[0]
            leads_total = float(r.get("leads_total", 0) or 0)
            leads_mais_12 = float(r.get("leads_mais_12", 0) or 0)
            leads_menos_12 = float(r.get("leads_menos_12", 0) or 0)
            leads_nao_atua = float(r.get("leads_nao_atua", 0) or 0)
            agend = float(r.get("agendamentos", 0) or 0)
            comp = float(r.get("comparecimentos", 0) or 0)
            no_shows = float(r.get("no_shows", 0) or 0)
            deals = float(r.get("deals", 0) or 0)
            deals_g = float(r.get("deals_ganhos", 0) or 0)
            vendas = float(r.get("vendas", 0) or 0)
            valor_v = float(r.get("valor_venda", 0) or 0)
            valor_r = float(r.get("valor_receita", 0) or 0)

            out["tem_resultados"] = True
            out["leads_total"] = leads_total
            out["leads_mais_12"] = leads_mais_12
            out["leads_menos_12"] = leads_menos_12
            out["leads_nao_atua"] = leads_nao_atua
            out["agendamentos"] = agend
            out["comparecimentos"] = comp
            out["no_shows"] = no_shows
            out["deals"] = deals
            out["deals_ganhos"] = deals_g
            out["vendas"] = vendas
            out["valor_venda"] = valor_v
            out["valor_receita"] = valor_r

            # Derivadas — denominador zero → None ("—" honesto)
            out["cpl"] = (invest / leads_total) if leads_total > 0 else None
            out["cpl_mais_12"] = (
                (invest / leads_mais_12) if leads_mais_12 > 0 else None
            )
            out["cac"] = (invest / vendas) if vendas > 0 else None
            out["roas"] = (valor_r / invest) if invest > 0 else None

    return out


# Métricas da tabela comparativa (label, key, regra, bloco).
# Investimento: sem vencedor (alocação ≠ performance — mesma decisão de
# campanhas).
# Frequência: sem vencedor (diagnóstico, não desempenho).
# Quality/Engagement/Conversion: categóricos — entram como identidade no topo.
_COMPARA_CRIATIVO_METRICAS = [
    # Plataforma
    ("Investimento",     "investimento",    None,    "plataforma"),
    ("Impressões",       "impressoes",      "higher","plataforma"),
    ("Cliques",          "cliques",         "higher","plataforma"),
    ("Link clicks",      "link_clicks",     "higher","plataforma"),
    ("Alcance",          "alcance",         "higher","plataforma"),
    ("CTR",              "ctr",             "higher","plataforma"),
    ("CPC",              "cpc",             "lower", "plataforma"),
    ("Frequência",       "frequencia",      None,    "plataforma"),
    # Resultado (mart)
    ("Leads",            "leads_total",     "higher","resultado"),
    ("Leads +12",        "leads_mais_12",   "higher","resultado"),
    ("Leads -12",        "leads_menos_12",  "higher","resultado"),
    ("Agendamentos",     "agendamentos",    "higher","resultado"),
    ("Comparecimentos",  "comparecimentos", "higher","resultado"),
    ("No-shows",         "no_shows",        "lower", "resultado"),
    ("Deals",            "deals",           "higher","resultado"),
    ("Deals ganhos",     "deals_ganhos",    "higher","resultado"),
    ("Vendas",           "vendas",          "higher","resultado"),
    ("Receita",          "valor_receita",   "higher","resultado"),
    # Derivadas (mistas: invest oficial / contagem mart)
    ("CPL",              "cpl",             "lower", "derivada"),
    ("CPL +12",          "cpl_mais_12",     "lower", "derivada"),
    ("CAC",              "cac",             "lower", "derivada"),
    ("ROAS",             "roas",            "higher","derivada"),
]


def compara_criativos(kA: dict, kB: dict) -> pd.DataFrame:
    """Tabela comparativa entre 2 criativos.

    Mesma estrutura de `compara_campanhas` (colunas metrica, valor_a,
    valor_b, delta_pct, vencedor, bloco), com:
    - Identidade no topo: Campanha, Status, Quality/Engagement/Conversion
      ranking (categóricas — sem delta, sem vencedor).
    - Plataforma + Resultado + Derivadas em seguida (numéricas).
    - "—" quando lado é None; vencedor vazio quando algum lado é None
      (não premiar criativo por ausência de atribuição)."""
    rows = [
        {"metrica": "Campanha",
         "valor_a": kA.get("campaign_name"),
         "valor_b": kB.get("campaign_name"),
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
        {"metrica": "Status",
         "valor_a": kA.get("status_label"),
         "valor_b": kB.get("status_label"),
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
        {"metrica": "Quality ranking",
         "valor_a": kA.get("quality_label"),
         "valor_b": kB.get("quality_label"),
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
        {"metrica": "Engagement ranking",
         "valor_a": kA.get("engagement_label"),
         "valor_b": kB.get("engagement_label"),
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
        {"metrica": "Conversion ranking",
         "valor_a": kA.get("conversion_label"),
         "valor_b": kB.get("conversion_label"),
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
    ]

    for label, key, regra, bloco in _COMPARA_CRIATIVO_METRICAS:
        a = kA.get(key)
        b = kB.get(key)
        if a is not None and b is not None and a != 0:
            delta = (b - a) / a * 100
        else:
            delta = None
        rows.append({
            "metrica": label,
            "valor_a": a,
            "valor_b": b,
            "delta_pct": delta,
            "vencedor": _venc_numerico(a, b, regra),
            "bloco": bloco,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Funil POR CRIATIVO (Criativos · seção "Funil do criativo selecionado")
# ---------------------------------------------------------------------------
# Consome `mkt_criativo_funil.sql` — 1 linha por `ad_name_norm` com mídia +
# leads + funil até venda nova. Match `ad_name = utm_content`; granularidade
# `ad_name` consolida múltiplos `ad_id` do mesmo criativo. Caveats explicados
# na caption obrigatória da página.

_CRI_FUNIL_ZEROS = {
    "ad_name_norm": "",
    "ad_name": "",
    "campaign_name": None, "adset_name": None,
    "effective_status": None,
    "quality_ranking": None, "engagement_ranking": None, "conversion_ranking": None,
    "thumbnail_url": None, "image_url": None, "permalink_url": None,
    "qtd_adids": 0,
    "investimento": 0.0, "impressoes": 0, "cliques": 0,
    "link_clicks": 0, "alcance": 0,
    "ctr": 0.0, "cpc": 0.0,
    "leads_totais": 0, "leads_qualificados": 0,
    "leads_mais_12": 0, "leads_menos_12": 0, "leads_nao_atua": 0,
    "agendamentos": 0, "comparecimentos": 0, "vendas_novas": 0,
    "agendamentos_leads_periodo": 0, "agendamentos_leads_historico": 0,
    "comparecimentos_leads_periodo": 0, "comparecimentos_leads_historico": 0,
    "vendas_leads_periodo": 0, "vendas_leads_historico": 0,
    "aplicacoes": 0, "aplicacoes_mais_12": 0, "aplicacoes_menos_12": 0,
    "aplicacoes_nao_atua": 0,
    "agendamentos_apl_periodo": 0, "agendamentos_apl_historico": 0,
    "agendamentos_apl": 0, "comparecimentos_apl": 0, "vendas_aplicacoes": 0,
    "taxa_qualificacao": 0.0, "taxa_mais_12": 0.0,
    "taxa_lead_agendamento": 0.0, "taxa_lead_agendamento_periodo": 0.0,
    "taxa_lead_agendamento_historico": 0.0,
    "taxa_lead_comparecimento": 0.0,
    "taxa_lead_venda_nova": 0.0,
    "taxa_aplicacao_mais_12": 0.0,
    "taxa_apl_agendamento": 0.0, "taxa_apl_agendamento_periodo": 0.0,
    "taxa_apl_agendamento_historico": 0.0,
    "taxa_apl_comparecimento": 0.0,
    "taxa_apl_venda_nova": 0.0,
    "cpl": 0.0, "cpl_mais_12": 0.0, "cac": 0.0,
}


_TODOS_AD_NAME_NORM = "__todos__"
_VINCULADOS_AD_NAME_NORM = "__vinculados__"
_SEM_CRIATIVO_AD_NAME_NORM = "__sem_criativo_identificado__"
_SEM_CAMPANHA_NAME_NORM = "__sem_campanha_identificada__"


def _fmt_inv_funil(v: float) -> str:
    return f"R$ {v:,.0f}".replace(",", ".") if v >= 1 else "R$ 0"


def formatar_label_funil_opcao(
    nome: str,
    invest: float,
    leads: int,
    aplicacoes: int,
    vendas: int,
) -> str:
    """Label unificado do selectbox do funil (lista + valor selecionado).

    Formato: ``Nome · R$ X · Y leads · Z apl. · W vendas``."""
    return (
        f"{nome} · {_fmt_inv_funil(invest)} · "
        f"{leads} lead{'s' if leads != 1 else ''} · "
        f"{aplicacoes} apl. · "
        f"{vendas} venda{'s' if vendas != 1 else ''}"
    )


def formatar_label_funil_row(row) -> str:
    """Monta label a partir de uma row do df_funil ou opções sintéticas."""
    nome = (row.get("ad_name") or row.get("ad_name_norm") or "(sem nome)")
    nome_short = nome if len(str(nome)) <= 56 else str(nome)[:53] + "…"
    return formatar_label_funil_opcao(
        nome_short,
        float(row.get("investimento") or 0),
        int(row.get("leads_totais") or 0),
        int(row.get("aplicacoes") or 0),
        int(row.get("vendas_novas") or 0),
    )


def _recompute_comp_vendas_decomp(out: dict) -> None:
    """Decomposição comparecimentos/vendas: período = aplicação no período; histórico = restante."""
    compar = int(out.get("comparecimentos") or 0)
    cp = int(out.get("comparecimentos_leads_periodo") or 0)
    ch = int(out.get("comparecimentos_leads_historico") or 0)
    if compar > 0 and cp + ch != compar:
        ch = max(0, compar - cp)
        out["comparecimentos_leads_historico"] = ch
    out["pct_comp_leads_periodo"] = (cp / compar * 100) if compar > 0 else None
    out["pct_comp_leads_historico"] = (ch / compar * 100) if compar > 0 else None

    vendas = int(out.get("vendas_novas") or 0)
    vp = int(out.get("vendas_leads_periodo") or 0)
    vh = int(out.get("vendas_leads_historico") or 0)
    if vendas > 0 and vp + vh != vendas:
        vh = max(0, vendas - vp)
        out["vendas_leads_historico"] = vh
    out["pct_vendas_leads_periodo"] = (vp / vendas * 100) if vendas > 0 else None
    out["pct_vendas_leads_historico"] = (vh / vendas * 100) if vendas > 0 else None


def _recompute_funil_decomp(out: dict) -> None:
    """Recalcula decomposições período/histórico de agend., comp. e vendas."""
    _recompute_agend_decomp(out)
    _recompute_comp_vendas_decomp(out)


def _close_funil_decomp_on_totals(out: dict) -> None:
    """Garante período + histórico = total antes de recalcular %."""
    for total_key, periodo_key, historico_key in (
        ("agendamentos", "agendamentos_leads_periodo", "agendamentos_leads_historico"),
        ("comparecimentos", "comparecimentos_leads_periodo", "comparecimentos_leads_historico"),
        ("vendas_novas", "vendas_leads_periodo", "vendas_leads_historico"),
    ):
        total = int(out.get(total_key) or 0)
        periodo = int(out.get(periodo_key) or 0)
        if total > 0:
            if periodo > total:
                periodo = total
                out[periodo_key] = periodo
            out[historico_key] = total - periodo
    _recompute_funil_decomp(out)


def _recompute_agend_decomp(out: dict) -> None:
    """Decomposição agendamentos: período = aplicação no período; histórico = restante."""
    agend = int(out.get("agendamentos") or 0)
    ap = int(out.get("agendamentos_leads_periodo") or 0)
    ah = int(out.get("agendamentos_leads_historico") or 0)
    if agend > 0 and ap + ah != agend:
        ah = max(0, agend - ap)
        out["agendamentos_leads_historico"] = ah
    out["pct_agend_leads_periodo"] = (ap / agend * 100) if agend > 0 else None
    out["pct_agend_leads_historico"] = (ah / agend * 100) if agend > 0 else None

    leads = int(out.get("leads_totais") or 0)
    out["taxa_lead_agendamento"] = (agend / leads * 100) if leads > 0 else 0.0
    out["taxa_lead_agendamento_periodo"] = out["pct_agend_leads_periodo"] or 0.0
    out["taxa_lead_agendamento_historico"] = out["pct_agend_leads_historico"] or 0.0

    agend_apl = int(out.get("agendamentos_apl") or 0)
    aap = int(out.get("agendamentos_apl_periodo") or 0)
    aah = int(out.get("agendamentos_apl_historico") or 0)
    if agend_apl > 0 and aap + aah != agend_apl:
        aah = max(0, agend_apl - aap)
        out["agendamentos_apl_historico"] = aah
    out["pct_agend_apl_periodo"] = (aap / agend_apl * 100) if agend_apl > 0 else None
    out["pct_agend_apl_historico"] = (aah / agend_apl * 100) if agend_apl > 0 else None

    apl = int(out.get("aplicacoes") or 0)
    out["taxa_apl_agendamento"] = (agend_apl / apl * 100) if apl > 0 else 0.0
    out["taxa_apl_agendamento_periodo"] = out["pct_agend_apl_periodo"] or 0.0
    out["taxa_apl_agendamento_historico"] = out["pct_agend_apl_historico"] or 0.0


def _recompute_aplicacoes_taxas(out: dict) -> None:
    """Taxas do funil de aplicações — denominador = aplicacoes."""
    apl = int(out.get("aplicacoes") or 0)
    apl12 = int(out.get("aplicacoes_mais_12") or 0)
    compar = int(out.get("comparecimentos_apl") or 0)
    vendas = int(out.get("vendas_aplicacoes") or 0)
    out["taxa_aplicacao_mais_12"] = (apl12 / apl * 100) if apl > 0 else 0.0
    out["taxa_apl_comparecimento"] = (compar / apl * 100) if apl > 0 else 0.0
    out["taxa_apl_venda_nova"] = (vendas / apl * 100) if apl > 0 else 0.0
    _recompute_funil_decomp(out)


def _comp_vendas_decomp_from_row(row: dict | pd.Series, scope: str) -> dict:
    """Decomposição comparecimentos/vendas (globais/vinculados) da 1ª row."""
    if scope == "vinculados":
        return {
            "comparecimentos_leads_periodo": int(
                row.get("comparecimentos_leads_periodo_vinculados") or 0
            ),
            "comparecimentos_leads_historico": int(
                row.get("comparecimentos_leads_historico_vinculados") or 0
            ),
            "vendas_leads_periodo": int(
                row.get("vendas_leads_periodo_vinculados") or 0
            ),
            "vendas_leads_historico": int(
                row.get("vendas_leads_historico_vinculados") or 0
            ),
        }
    return {
        "comparecimentos_leads_periodo": int(
            row.get("comparecimentos_leads_periodo_globais") or 0
        ),
        "comparecimentos_leads_historico": int(
            row.get("comparecimentos_leads_historico_globais") or 0
        ),
        "vendas_leads_periodo": int(
            row.get("vendas_leads_periodo_globais") or 0
        ),
        "vendas_leads_historico": int(
            row.get("vendas_leads_historico_globais") or 0
        ),
    }


def _aplicacoes_kpis_from_row(row: dict | pd.Series, prefix: str) -> dict:
    """Extrai KPIs de aplicações de colunas globais/vinculados (1ª row do df)."""
    sfx = f"_{prefix}" if prefix else ""
    return {
        "aplicacoes": int(row.get(f"aplicacoes{sfx}") or 0),
        "aplicacoes_mais_12": int(row.get(f"aplicacoes_mais_12{sfx}") or 0),
        "aplicacoes_menos_12": int(row.get(f"aplicacoes_menos_12{sfx}") or 0),
        "aplicacoes_nao_atua": int(row.get(f"aplicacoes_nao_atua{sfx}") or 0),
        "agendamentos_apl": int(row.get(f"agendamentos_apl{sfx}") or 0),
        "comparecimentos_apl": int(row.get(f"comparecimentos_apl{sfx}") or 0),
        "vendas_aplicacoes": int(row.get(f"vendas_aplicacoes{sfx}") or 0),
    }


def _agend_decomp_from_row(row: dict | pd.Series, scope: str) -> dict:
    """Decomposição agendamentos (globais/vinculados) da 1ª row do df_funil."""
    if scope == "vinculados":
        return {
            "agendamentos": int(row.get("agendamentos_vinculados") or 0),
            "agendamentos_leads_periodo": int(
                row.get("agendamentos_leads_periodo_vinculados") or 0
            ),
            "agendamentos_leads_historico": int(
                row.get("agendamentos_leads_historico_vinculados") or 0
            ),
            "agendamentos_apl": int(row.get("agendamentos_apl_vinculados") or 0),
            "agendamentos_apl_periodo": int(
                row.get("agendamentos_apl_periodo_vinculados") or 0
            ),
            "agendamentos_apl_historico": int(
                row.get("agendamentos_apl_historico_vinculados") or 0
            ),
        }
    return {
        "agendamentos": int(row.get("agendamentos_globais") or 0),
        "agendamentos_leads_periodo": int(
            row.get("agendamentos_leads_periodo_globais") or 0
        ),
        "agendamentos_leads_historico": int(
            row.get("agendamentos_leads_historico_globais") or 0
        ),
        "agendamentos_apl": int(row.get("agendamentos_apl_globais") or 0),
        "agendamentos_apl_periodo": int(
            row.get("agendamentos_apl_periodo_globais") or 0
        ),
        "agendamentos_apl_historico": int(
            row.get("agendamentos_apl_historico_globais") or 0
        ),
    }


def _overlay_aplicacoes_kpis(out: dict, df_funil: pd.DataFrame, scope: str) -> dict:
    """Sobrepõe KPIs de aplicações a partir de colunas globais do SQL.

    scope ``globais`` (opção "Todos os resultados"): todas as aplicações
    Typeform válidas no período — igual One Page; não exige lead.
    scope ``vinculados``: só aplicações com e-mail presente em leads do período.
    Criativo/campanha específica: contagens por linha do SQL (lead ∩ typeform).
    """
    if df_funil is None or df_funil.empty:
        return out
    row = df_funil.iloc[0]
    apl = _aplicacoes_kpis_from_row(row, scope)
    out.update(apl)
    out.update(_agend_decomp_from_row(row, scope))
    out.update(_comp_vendas_decomp_from_row(row, scope))
    _recompute_aplicacoes_taxas(out)
    return out


def lista_criativos_funil(
    df_funil: pd.DataFrame,
    sort_by: str = "investimento",
    leads_totais_oficial: int | None = None,
    vendas_novas_oficial: int | None = None,
    investimento_oficial: float | None = None,
) -> pd.DataFrame:
    """Opções para o selectbox da seção "Funil do criativo selecionado".

    Retorna `(ad_name_norm, ad_name, label)` ordenado por `investimento`
    desc (default) ou `leads_totais` desc. Label sugerido:
        "ad_name · R$ invest · X leads"

    Mai/2026: prepend de até 3 opções sintéticas:
      1. `__todos__`: total OFICIAL do período (Visão Geral) — leads
         daily-distinct por email, vendas novas do CRM, investimento total
         de mídia. Quando os 3 params oficiais vêm None, cai pra
         agregação do df (mesmo comportamento legado).
      2. `__vinculados__`: agrega per-criativo do df_funil — só o que foi
         de fato vinculado/atribuído na lógica do funil. Útil pra
         auditoria do que casou vs. universo bruto do período.
      3. `__sem_criativo_identificado__`: bucket do funil SQL — leads sem
         utm_content + vendas sem lead atribuível. Aparece se vendas > 0
         OU leads > 0 no bucket.
    Criativos individuais (com algum sinal de mídia/leads/vendas) seguem
    ordenados por sort_by."""
    if df_funil is None or df_funil.empty:
        return pd.DataFrame(columns=["ad_name_norm", "ad_name", "label"])

    df = df_funil.copy()
    # Mantém criativos com algum sinal (mídia OU leads OU vendas — vendas
    # cross-período entram mesmo sem leads no período).
    mask = (
        (df["investimento"].fillna(0) > 0)
        | (df["leads_totais"].fillna(0) > 0)
        | (df.get("vendas_novas", pd.Series(0, index=df.index)).fillna(0) > 0)
    )
    df = df[mask]
    if df.empty:
        return pd.DataFrame(columns=["ad_name_norm", "ad_name", "label"])

    def _fmt_inv(v: float) -> str:
        return _fmt_inv_funil(v)

    def _apl_globais(source: pd.DataFrame) -> int:
        if source is None or source.empty:
            return 0
        row = source.iloc[0]
        if "aplicacoes_globais" in row.index:
            return int(row.get("aplicacoes_globais") or 0)
        return 0

    def _apl_vinculados(source: pd.DataFrame) -> int:
        if source is None or source.empty:
            return 0
        row = source.iloc[0]
        if "aplicacoes_vinculados" in row.index:
            return int(row.get("aplicacoes_vinculados") or 0)
        return 0

    def _label(row) -> str:
        return formatar_label_funil_row(row)

    # Agregados do df:
    #   - "Todos" (fallback do df quando não vêm oficiais) inclui TUDO.
    #   - "Vinculados" exclui o bucket `__sem_*_identificad{o,a}__` para
    #     refletir só o universo rastreável por origem de marketing.
    df_vinc = _excluir_bucket_sem_identificado(df)
    invest_sum_todos = float(df["investimento"].fillna(0).sum())
    leads_sum_todos  = int(df["leads_totais"].fillna(0).sum())
    vendas_sum_todos = int(df.get("vendas_novas", pd.Series(0)).fillna(0).sum())
    invest_sum_vinc  = float(df_vinc["investimento"].fillna(0).sum())
    leads_sum_vinc   = int(df_vinc["leads_totais"].fillna(0).sum())
    vendas_sum_vinc  = int(df_vinc.get("vendas_novas", pd.Series(0)).fillna(0).sum())

    # --- Opções sintéticas (prepend) -----------------------------------
    sinteticas: list[dict] = []

    # 1) "Todos os resultados" — totais OFICIAIS do período. Cai pra soma
    # do df quando o caller não passa os 3 oficiais (fallback legado).
    invest_t = (float(investimento_oficial) if investimento_oficial is not None
                else invest_sum_todos)
    leads_t  = (int(leads_totais_oficial) if leads_totais_oficial is not None
                else leads_sum_todos)
    vendas_t = (int(vendas_novas_oficial) if vendas_novas_oficial is not None
                else vendas_sum_todos)
    apl_t = _apl_globais(df)
    sinteticas.append({
        "ad_name_norm": _TODOS_AD_NAME_NORM,
        "ad_name":      "Todos os resultados",
        "label":        formatar_label_funil_opcao(
            "Todos os resultados", invest_t, leads_t, apl_t, vendas_t,
        ),
    })

    # 2) "Totais vinculados aos leads" — soma per-criativo do df_funil,
    # EXCLUINDO o bucket sem identificado. Universo rastreável por origem
    # de marketing. Por construção: vinculados ≤ todos.
    apl_vinc = _apl_vinculados(df)
    sinteticas.append({
        "ad_name_norm": _VINCULADOS_AD_NAME_NORM,
        "ad_name":      "Totais vinculados aos leads",
        "label":        formatar_label_funil_opcao(
            "Totais vinculados aos leads",
            invest_sum_vinc, leads_sum_vinc, apl_vinc, vendas_sum_vinc,
        ),
    })

    # "Sem criativo/campanha identificad{o,a}" — aparece quando o bucket
    # tem vendas OU leads (a partir de mai/2026 leads sem utm também caem
    # nesse bucket via SQL). Detecta ambos os valores possíveis — o df de
    # campanha entra renomeado como ad_name_norm, mas o VALOR do bucket é
    # '__sem_campanha_identificada__'.
    bucket_candidates = (
        (_SEM_CRIATIVO_AD_NAME_NORM, "Sem criativo identificado"),
        (_SEM_CAMPANHA_NAME_NORM,    "Sem campanha identificada"),
    )
    for bucket_norm, bucket_label in bucket_candidates:
        sem_mask = df["ad_name_norm"] == bucket_norm
        if not sem_mask.any():
            continue
        row_sc = df[sem_mask].iloc[0]
        vendas_sc = int(row_sc.get("vendas_novas") or 0)
        leads_sc  = int(row_sc.get("leads_totais") or 0)
        apl_sc    = int(row_sc.get("aplicacoes") or 0)
        if vendas_sc > 0 or leads_sc > 0 or apl_sc > 0:
            invest_sc = float(row_sc.get("investimento") or 0)
            sinteticas.append({
                "ad_name_norm": bucket_norm,
                "ad_name":      bucket_label,
                "label":        formatar_label_funil_opcao(
                    bucket_label, invest_sc, leads_sc, apl_sc, vendas_sc,
                ),
            })
        break

    # --- Criativos individuais (excluindo o bucket sintético, que já entrou
    # como opção própria acima) ----------------------------------------
    df_indiv = df[
        ~df["ad_name_norm"].isin([_SEM_CRIATIVO_AD_NAME_NORM,
                                  _SEM_CAMPANHA_NAME_NORM])
    ].copy()
    if not df_indiv.empty:
        sort_col = sort_by if sort_by in df_indiv.columns else "investimento"
        df_indiv = df_indiv.sort_values(
            [sort_col, "leads_totais", "ad_name"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        df_indiv["label"] = df_indiv.apply(_label, axis=1)
        df_indiv = df_indiv[["ad_name_norm", "ad_name", "label"]]
    else:
        df_indiv = pd.DataFrame(columns=["ad_name_norm", "ad_name", "label"])

    return pd.concat(
        [pd.DataFrame(sinteticas), df_indiv],
        ignore_index=True,
    )[["ad_name_norm", "ad_name", "label"]]


def _kpis_funil_agregado(
    df_funil: pd.DataFrame,
    ad_name_norm_out: str,
    ad_name_out: str,
    leads_totais_oficial: int | None = None,
    vendas_novas_oficial: int | None = None,
    investimento_oficial: float | None = None,
) -> dict:
    """Núcleo compartilhado entre 'Todos os resultados' e 'Totais
    vinculados'. Soma absolutos do df_funil; aceita overrides opcionais
    para leads / vendas / investimento (usados pela opção "Todos os
    resultados" para refletir os totais oficiais do período). Recomputa
    todas as taxas e CPL/CAC a partir dos valores finais (com overrides
    aplicados)."""
    out = dict(_CRI_FUNIL_ZEROS)
    out["tem_dados"] = True
    out["ad_name_norm"] = ad_name_norm_out
    out["ad_name"] = ad_name_out

    int_cols = ("qtd_adids", "impressoes", "cliques", "link_clicks", "alcance",
                "leads_totais", "leads_qualificados", "leads_mais_12",
                "leads_menos_12", "leads_nao_atua",
                "agendamentos", "comparecimentos", "vendas_novas")
    for c in int_cols:
        if c in df_funil.columns:
            out[c] = int(df_funil[c].fillna(0).sum())

    if "investimento" in df_funil.columns:
        out["investimento"] = float(df_funil["investimento"].fillna(0).sum())

    # Overrides oficiais (aplicados ANTES de derivar taxas/CPL/CAC pra
    # manter o denominador coerente com os números exibidos).
    if leads_totais_oficial is not None and leads_totais_oficial >= 0:
        out["leads_totais"] = int(leads_totais_oficial)
    if vendas_novas_oficial is not None and vendas_novas_oficial >= 0:
        out["vendas_novas"] = int(vendas_novas_oficial)
    if investimento_oficial is not None and investimento_oficial >= 0:
        out["investimento"] = float(investimento_oficial)

    # Taxas / CPL / CAC / CTR / CPC recomputados a partir dos somatórios
    inv = float(out["investimento"] or 0)
    imp = int(out["impressoes"] or 0)
    clk = int(out["cliques"] or 0)
    leads = int(out["leads_totais"] or 0)
    leads_12 = int(out["leads_mais_12"] or 0)
    agend = int(out["agendamentos"] or 0)
    compar = int(out["comparecimentos"] or 0)
    vendas = int(out["vendas_novas"] or 0)
    leads_q = int(out["leads_qualificados"] or 0)

    out["ctr"]  = (clk / imp * 100) if imp > 0 else 0.0
    out["cpc"]  = (inv / clk) if clk > 0 else 0.0
    out["taxa_qualificacao"]         = (leads_q / leads * 100) if leads > 0 else 0.0
    out["taxa_mais_12"]              = (leads_12 / leads * 100) if leads > 0 else 0.0
    out["taxa_lead_comparecimento"]  = (compar / leads * 100) if leads > 0 else 0.0
    out["taxa_lead_venda_nova"]      = (vendas / leads * 100) if leads > 0 else 0.0
    out["cpl"]                       = (inv / leads)    if leads > 0    else 0.0
    out["cpl_mais_12"]               = (inv / leads_12) if leads_12 > 0 else 0.0
    out["cac"]                       = (inv / vendas)   if vendas > 0   else 0.0
    return out


def _apply_funil_one_page_kpis(
    out: dict,
    df_funil: pd.DataFrame | None,
    *,
    agendamentos_oficial: int | None = None,
    comparecimentos_oficial: int | None = None,
    vendas_oficial: int | None = None,
) -> dict:
    """Totais One Page (agend/comp/vendas) + decomposição período/histórico."""
    if df_funil is not None and not df_funil.empty:
        row0 = df_funil.iloc[0]
        out.update(_agend_decomp_from_row(row0, "globais"))
        out.update(_comp_vendas_decomp_from_row(row0, "globais"))

    for total_key, official, periodo_key, historico_key in (
        ("agendamentos", agendamentos_oficial,
         "agendamentos_leads_periodo", "agendamentos_leads_historico"),
        ("comparecimentos", comparecimentos_oficial,
         "comparecimentos_leads_periodo", "comparecimentos_leads_historico"),
        ("vendas_novas", vendas_oficial,
         "vendas_leads_periodo", "vendas_leads_historico"),
    ):
        if official is not None and official >= 0:
            out[total_key] = int(official)
        total = int(out.get(total_key) or 0)
        periodo = int(out.get(periodo_key) or 0)
        if total > 0:
            if periodo > total:
                periodo = total
                out[periodo_key] = periodo
            out[historico_key] = total - periodo

    _recompute_funil_decomp(out)
    return out


def _apply_agendamentos_one_page_kpis(
    out: dict,
    df_funil: pd.DataFrame | None,
    agendamentos_oficial: int | None = None,
) -> dict:
    """Alias legado — delega para ``_apply_funil_one_page_kpis``."""
    return _apply_funil_one_page_kpis(
        out, df_funil, agendamentos_oficial=agendamentos_oficial,
    )


def agendamentos_one_page_oficial(
    df_prevendas_diario: pd.DataFrame | None,
) -> int | None:
    """Total exibido de agendamentos — mesma regra da One Page."""
    if df_prevendas_diario is None or df_prevendas_diario.empty:
        return None
    from src.prevendas_transforms import prevendas_overview_kpis
    k = prevendas_overview_kpis(df_prevendas_diario)
    return int(k.get("agendamentos_exibidos") or 0)


def comparecimentos_one_page_oficial(
    df_prevendas_diario: pd.DataFrame | None,
) -> int | None:
    """Total de comparecimentos — mesma regra da One Page / Pré-vendas."""
    if df_prevendas_diario is None or df_prevendas_diario.empty:
        return None
    from src.prevendas_transforms import prevendas_overview_kpis
    k = prevendas_overview_kpis(df_prevendas_diario)
    return int(k.get("comparecimentos") or 0)


def vendas_one_page_oficial(
    df_prevendas_diario: pd.DataFrame | None,
) -> int | None:
    """Total de vendas novas — mesma regra da One Page / Pré-vendas."""
    if df_prevendas_diario is None or df_prevendas_diario.empty:
        return None
    from src.prevendas_transforms import prevendas_overview_kpis
    k = prevendas_overview_kpis(df_prevendas_diario)
    return int(k.get("vendas_novas") or k.get("vendas") or 0)


def _criativo_funil_kpis_todos(
    df_funil: pd.DataFrame,
    leads_totais_oficial: int | None = None,
    vendas_novas_oficial: int | None = None,
    investimento_oficial: float | None = None,
    agendamentos_oficial: int | None = None,
    comparecimentos_oficial: int | None = None,
    vendas_oficial: int | None = None,
) -> dict:
    """KPIs da opção sintética 'Todos os resultados'.

    Representa os TOTAIS OFICIAIS do período (alinhados com a Visão Geral):
    `leads_totais_oficial` = daily-distinct por e-mail
    (`COUNT(DISTINCT (timestamp::date, lower(trim(email))))`);
    `vendas_novas_oficial` = total CRM (stage Ganho + Novo cliente);
    `investimento_oficial` = total de mídia do período.
    `agendamentos_oficial` = `agendamentos_exibidos` da Pré-vendas / One Page.
    `comparecimentos_oficial` / `vendas_oficial` = totais Pré-vendas / One Page.
    Quando algum oficial vem `None` (fallback p/ cache indisponível), cai
    pra soma do df."""
    out = _kpis_funil_agregado(
        df_funil,
        ad_name_norm_out=_TODOS_AD_NAME_NORM,
        ad_name_out="Todos os resultados",
        leads_totais_oficial=leads_totais_oficial,
        vendas_novas_oficial=vendas_novas_oficial,
        investimento_oficial=investimento_oficial,
    )
    out = _overlay_aplicacoes_kpis(out, df_funil, "globais")
    vendas_final = (
        vendas_oficial if vendas_oficial is not None else vendas_novas_oficial
    )
    return _apply_funil_one_page_kpis(
        out, df_funil,
        agendamentos_oficial=agendamentos_oficial,
        comparecimentos_oficial=comparecimentos_oficial,
        vendas_oficial=vendas_final,
    )


def _criativo_funil_kpis_vinculados(df_funil: pd.DataFrame) -> dict:
    """KPIs da opção sintética 'Totais vinculados aos leads'.

    Soma per-criativo/campanha do df_funil **excluindo** o bucket
    `__sem_criativo_identificado__` / `__sem_campanha_identificada__` —
    representa só o universo rastreável por origem de marketing
    (linhas com utm preenchido). Sem overrides. Por construção, esse
    total nunca fica maior que 'Todos os resultados'."""
    df = _excluir_bucket_sem_identificado(df_funil)
    out = _kpis_funil_agregado(
        df,
        ad_name_norm_out=_VINCULADOS_AD_NAME_NORM,
        ad_name_out="Totais vinculados aos leads",
    )
    out = _overlay_aplicacoes_kpis(out, df_funil, "vinculados")
    if df_funil is not None and not df_funil.empty:
        row0 = df_funil.iloc[0]
        out["agendamentos"] = int(row0.get("agendamentos_vinculados") or out.get("agendamentos") or 0)
    _close_funil_decomp_on_totals(out)
    return out


def _excluir_bucket_sem_identificado(df_funil: pd.DataFrame) -> pd.DataFrame:
    """Filtra fora as linhas dos buckets `__sem_*_identificad{o,a}__`.

    Funciona pros DOIS grãos (criativo e campanha): mesmo após o rename de
    `_campanha_df_como_criativo`, a coluna canônica é `ad_name_norm` e os
    valores possíveis dos buckets não colidem entre si — então excluir os
    dois é seguro em ambos os casos."""
    if df_funil is None or df_funil.empty or "ad_name_norm" not in df_funil.columns:
        return df_funil
    return df_funil[
        ~df_funil["ad_name_norm"].isin(
            [_SEM_CRIATIVO_AD_NAME_NORM, _SEM_CAMPANHA_NAME_NORM]
        )
    ]


def criativo_funil_kpis(df_funil: pd.DataFrame,
                        ad_name_norm: str | None,
                        leads_totais_oficial: int | None = None,
                        vendas_novas_oficial: int | None = None,
                        investimento_oficial: float | None = None,
                        agendamentos_oficial: int | None = None,
                        comparecimentos_oficial: int | None = None,
                        vendas_oficial: int | None = None) -> dict:
    """Projeção da row do criativo selecionado num dict pronto pra UI.

    Retorna dict com TODAS as colunas do SQL (mídia + leads + funil +
    derivadas), mais `tem_dados=True/False` indicando se a seleção bateu
    em alguma row. Quando `ad_name_norm` é None ou não existe no df, devolve
    o dict de zeros.

    Mai/2026: duas opções sintéticas roteadas aqui:
      * `__todos__` ('Todos os resultados') — totais OFICIAIS do período,
        com overrides via `leads_totais_oficial` / `vendas_novas_oficial`
        / `investimento_oficial`.
      * `__vinculados__` ('Totais vinculados aos leads') — soma pura
        per-criativo do df_funil (auditoria do que foi vinculado).
    Criativo individual cai no caminho-padrão (lê a row do df)."""
    out = dict(_CRI_FUNIL_ZEROS)
    out["tem_dados"] = False
    if df_funil is None or df_funil.empty or not ad_name_norm:
        return out

    if ad_name_norm == _TODOS_AD_NAME_NORM:
        return _criativo_funil_kpis_todos(
            df_funil,
            leads_totais_oficial=leads_totais_oficial,
            vendas_novas_oficial=vendas_novas_oficial,
            investimento_oficial=investimento_oficial,
            agendamentos_oficial=agendamentos_oficial,
            comparecimentos_oficial=comparecimentos_oficial,
            vendas_oficial=vendas_oficial,
        )
    if ad_name_norm == _VINCULADOS_AD_NAME_NORM:
        return _criativo_funil_kpis_vinculados(df_funil)

    sub = df_funil[df_funil["ad_name_norm"] == ad_name_norm]
    if sub.empty:
        return out

    row = sub.iloc[0].to_dict()
    out["tem_dados"] = True
    int_cols = ("qtd_adids", "impressoes", "cliques", "link_clicks", "alcance",
                "leads_totais", "leads_qualificados", "leads_mais_12",
                "leads_menos_12", "leads_nao_atua",
                "agendamentos", "comparecimentos", "vendas_novas",
                "aplicacoes", "aplicacoes_mais_12", "aplicacoes_menos_12",
                "aplicacoes_nao_atua",
                "agendamentos_apl", "comparecimentos_apl", "vendas_aplicacoes")
    decomp_cols = (
        "agendamentos_leads_periodo", "agendamentos_leads_historico",
        "comparecimentos_leads_periodo", "comparecimentos_leads_historico",
        "vendas_leads_periodo", "vendas_leads_historico",
        "agendamentos_apl_periodo", "agendamentos_apl_historico",
    )
    float_cols = ("investimento", "ctr", "cpc",
                  "taxa_qualificacao", "taxa_mais_12",
                  "taxa_lead_agendamento", "taxa_lead_agendamento_periodo",
                  "taxa_lead_agendamento_historico",
                  "taxa_lead_comparecimento", "taxa_lead_venda_nova",
                  "taxa_aplicacao_mais_12", "taxa_apl_agendamento",
                  "taxa_apl_agendamento_periodo", "taxa_apl_agendamento_historico",
                  "taxa_apl_comparecimento", "taxa_apl_venda_nova",
                  "cpl", "cpl_mais_12", "cac")
    for c in row:
        if c in int_cols or c in decomp_cols:
            out[c] = int(row[c]) if row[c] is not None else 0
        elif c in float_cols:
            out[c] = float(row[c]) if row[c] is not None else 0.0
        else:
            out[c] = row[c]
    _close_funil_decomp_on_totals(out)
    _recompute_aplicacoes_taxas(out)
    return out


def criativo_funil_etapas(k: dict) -> tuple[list[str], list[float]]:
    """7 etapas do funil de um criativo: Impressões → Cliques → Leads →
    Leads +12 → Agendamentos → Comparecimentos → Vendas novas.

    Mesma forma de `growth_funil_etapas` (a UI reusa o renderer), mas a
    última etapa é **Vendas novas** (`tipo_venda='Novo cliente'`) — caminho
    de aquisição alinhado com Visão Geral / Growth."""
    labels = ["Impressões", "Cliques", "Leads", "Leads +12",
              "Agendamentos", "Comparecimentos", "Vendas novas"]
    values = [
        float(k.get("impressoes", 0) or 0),
        float(k.get("cliques", 0) or 0),
        float(k.get("leads_totais", 0) or 0),
        float(k.get("leads_mais_12", 0) or 0),
        float(k.get("agendamentos", 0) or 0),
        float(k.get("comparecimentos", 0) or 0),
        float(k.get("vendas_novas", 0) or 0),
    ]
    return labels, values


def build_funil_trilha_leads_steps(k: dict) -> list[dict]:
    """5 etapas do funil de Marketing: Leads → Aplicações → Agend. → Comp. → Vendas."""
    leads = float(k.get("leads_totais") or 0)
    apl = float(k.get("aplicacoes") or 0)
    agend = float(k.get("agendamentos") or 0)
    pct_apl = (apl / leads * 100) if leads > 0 else None
    return [
        {
            "label": "Leads",
            "value": leads,
            "is_base": True,
        },
        {
            "label": "Aplicações",
            "value": apl,
            "is_aplicacoes": True,
            "pct_of_leads": pct_apl,
        },
        {
            "label": "Agendamentos",
            "value": agend,
            "dual_decomp": True,
            "decomp_scope": "agendamentos",
            "count_periodo": int(k.get("agendamentos_leads_periodo") or 0),
            "count_historico": int(k.get("agendamentos_leads_historico") or 0),
            "pct_periodo": k.get("pct_agend_leads_periodo"),
            "pct_historico": k.get("pct_agend_leads_historico"),
        },
        {
            "label": "Comparecimentos",
            "value": float(k.get("comparecimentos") or 0),
            "dual_decomp": True,
            "decomp_scope": "comparecimentos",
            "count_periodo": int(k.get("comparecimentos_leads_periodo") or 0),
            "count_historico": int(k.get("comparecimentos_leads_historico") or 0),
            "pct_periodo": k.get("pct_comp_leads_periodo"),
            "pct_historico": k.get("pct_comp_leads_historico"),
        },
        {
            "label": "Vendas",
            "value": float(k.get("vendas_novas") or 0),
            "dual_decomp": True,
            "decomp_scope": "vendas",
            "count_periodo": int(k.get("vendas_leads_periodo") or 0),
            "count_historico": int(k.get("vendas_leads_historico") or 0),
            "pct_periodo": k.get("pct_vendas_leads_periodo"),
            "pct_historico": k.get("pct_vendas_leads_historico"),
        },
    ]


def build_funil_trilha_aplicacoes_steps(k: dict) -> list[dict]:
    """4 etapas principais do funil de aplicações (sem +12 como etapa sequencial)."""
    agend_apl = float(k.get("agendamentos_apl") or 0)
    return [
        {
            "label": "Aplicações",
            "value": float(k.get("aplicacoes") or 0),
            "mais_12": int(k.get("aplicacoes_mais_12") or 0),
            "menos_12": int(k.get("aplicacoes_menos_12") or 0),
            "is_base": True,
        },
        {
            "label": "Agend. apl.",
            "value": agend_apl,
            "dual_decomp": True,
            "count_periodo": int(k.get("agendamentos_apl_periodo") or 0),
            "count_historico": int(k.get("agendamentos_apl_historico") or 0),
            "pct_periodo": k.get("pct_agend_apl_periodo"),
            "pct_historico": k.get("pct_agend_apl_historico"),
        },
        {"label": "Comp. apl.", "value": float(k.get("comparecimentos_apl") or 0)},
        {"label": "Vendas apl.", "value": float(k.get("vendas_aplicacoes") or 0)},
    ]


# Mantido para compatibilidade / backend. UI usa funil único via
# ``build_funil_trilha_leads_steps`` + contexto de aplicações no bloco Leads.
_FUNIL_APL_KPI_KEYS = (
    "aplicacoes",
    "aplicacoes_mais_12",
    "agendamentos_apl",
    "comparecimentos_apl",
    "vendas_aplicacoes",
)


def criativo_funil_etapas_aplicacoes(k: dict) -> tuple[list[str], list[float]]:
    """Legado — trilha de aplicações (backend); não renderizada na UI principal."""
    steps = build_funil_trilha_aplicacoes_steps(k)
    return [s["label"] for s in steps], [s["value"] for s in steps]


# ---------------------------------------------------------------------------
# Campanha — espelho de criativo, mas com grão `campaign_name`. As funções
# delegam para as de criativo renomeando as 2 colunas-chave do DataFrame
# (campaign_name_norm → ad_name_norm, campaign_name → ad_name). Mantém uma
# única implementação de lógica; reduz risco de divergência futura.
# ---------------------------------------------------------------------------
def _campanha_df_como_criativo(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia 2 colunas pra reusar as funções de criativo sem alterar a
    lógica. Devolve uma cópia (não muta o df original)."""
    if df is None or df.empty:
        return df
    return df.rename(columns={
        "campaign_name_norm": "ad_name_norm",
        "campaign_name":      "ad_name",
    })


def lista_campanhas_funil(
    df_funil: pd.DataFrame,
    sort_by: str = "investimento",
    leads_totais_oficial: int | None = None,
    vendas_novas_oficial: int | None = None,
    investimento_oficial: float | None = None,
) -> pd.DataFrame:
    """Opções para o selectbox da seção "Funil da campanha selecionada".
    Retorna `(campaign_name_norm, campaign_name, label)`. Lógica idêntica
    à `lista_criativos_funil` — mesmo formato de label, mesmas 3 opções
    sintéticas no topo."""
    inner = lista_criativos_funil(
        _campanha_df_como_criativo(df_funil),
        sort_by=sort_by,
        leads_totais_oficial=leads_totais_oficial,
        vendas_novas_oficial=vendas_novas_oficial,
        investimento_oficial=investimento_oficial,
    )
    if inner is None or inner.empty:
        return pd.DataFrame(
            columns=["campaign_name_norm", "campaign_name", "label"]
        )
    return inner.rename(columns={
        "ad_name_norm": "campaign_name_norm",
        "ad_name":      "campaign_name",
    })


def campanha_funil_kpis(df_funil: pd.DataFrame,
                        campaign_name_norm: str | None,
                        leads_totais_oficial: int | None = None,
                        vendas_novas_oficial: int | None = None,
                        investimento_oficial: float | None = None,
                        agendamentos_oficial: int | None = None,
                        comparecimentos_oficial: int | None = None,
                        vendas_oficial: int | None = None) -> dict:
    """Projeção da row da campanha selecionada num dict. Reusa
    `criativo_funil_kpis` — mesmo shape de chaves (investimento, leads_*,
    agendamentos, vendas_novas, cpl, cac, taxa_*, etc.). Os overrides
    oficiais são propagados pra rota `__todos__`."""
    return criativo_funil_kpis(
        _campanha_df_como_criativo(df_funil), campaign_name_norm,
        leads_totais_oficial=leads_totais_oficial,
        vendas_novas_oficial=vendas_novas_oficial,
        investimento_oficial=investimento_oficial,
        agendamentos_oficial=agendamentos_oficial,
        comparecimentos_oficial=comparecimentos_oficial,
        vendas_oficial=vendas_oficial,
    )


def campanha_funil_etapas(k: dict) -> tuple[list[str], list[float]]:
    """7 etapas do funil de uma campanha — idêntico a
    `criativo_funil_etapas` (depende só do dict de kpis, não do grão)."""
    return criativo_funil_etapas(k)


def campanha_funil_etapas_aplicacoes(k: dict) -> tuple[list[str], list[float]]:
    """Trilha de aplicações da campanha — mesmo shape que criativos."""
    return criativo_funil_etapas_aplicacoes(k)


# ---------------------------------------------------------------------------
# Social (Instagram orgânico)
# ---------------------------------------------------------------------------

_SOCIAL_ZEROS = {
    "seguidores": 0,
    "alcance_total": 0.0,
    "engajamento_total": 0.0,
    "taxa_engajamento": 0.0,
    "posts": 0,
    "alcance_medio": 0.0,
    "engajamento_medio": 0.0,
    "saves_totais": 0.0,
    "curtidas_totais": 0.0,
    "comentarios_totais": 0.0,
}


def social_kpis(df: pd.DataFrame) -> dict:
    """KPIs consolidados do Instagram orgânico.

    taxa_engajamento = engajamento_total / (posts × seguidores) × 100
    (mesma fórmula do backend NestJS — `eng / (posts × followers)` em %)."""
    if df.empty:
        return dict(_SOCIAL_ZEROS)

    posts = int(len(df))
    seguidores = (
        int(df["followers_count"].max()) if "followers_count" in df.columns else 0
    )
    alcance = float(df["alcance"].sum())
    engajamento = float(df["engajamento"].sum())
    curtidas = float(df["curtidas"].sum()) if "curtidas" in df.columns else 0.0
    comentarios = float(df["comentarios"].sum()) if "comentarios" in df.columns else 0.0
    saves = float(df["salvamentos"].sum()) if "salvamentos" in df.columns else 0.0

    if seguidores > 0 and posts > 0:
        taxa = (engajamento / (posts * seguidores)) * 100
    else:
        taxa = 0.0

    return {
        "seguidores": seguidores,
        "alcance_total": alcance,
        "engajamento_total": engajamento,
        "taxa_engajamento": taxa,
        "posts": posts,
        "alcance_medio": _safe_div(alcance, posts),
        "engajamento_medio": _safe_div(engajamento, posts),
        "saves_totais": saves,
        "curtidas_totais": curtidas,
        "comentarios_totais": comentarios,
    }


def social_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Evolução diária: alcance, engajamento, posts (count)."""
    cols = ["data_ref", "alcance", "engajamento", "posts"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    agg = df.groupby("data_ref", as_index=False).agg(
        alcance=("alcance", "sum"),
        engajamento=("engajamento", "sum"),
        posts=("post_id", "count"),
    )
    return agg[cols].sort_values("data_ref").reset_index(drop=True)


def social_top_posts(df: pd.DataFrame,
                     sort_by: str = "alcance",
                     top_n: int = 10) -> pd.DataFrame:
    """Top N posts por métrica escolhida (alcance/engajamento/curtidas/...).
    Maior é melhor para todas as métricas suportadas."""
    if df.empty:
        return df.iloc[0:0]
    if sort_by not in df.columns:
        sort_by = "alcance"
    return (df.sort_values(sort_by, ascending=False)
              .head(top_n)
              .reset_index(drop=True))


def social_recentes(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """N posts mais recentes — ordenados por publicado_em desc."""
    if df.empty:
        return df
    sort_col = "publicado_em" if "publicado_em" in df.columns else "data_ref"
    return (df.sort_values(sort_col, ascending=False)
              .head(n)
              .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Comparação de campanhas (V1 — só métricas de plataforma)
# ---------------------------------------------------------------------------

def lista_campanhas(df_camp: pd.DataFrame) -> pd.DataFrame:
    """Lista única de campanhas para popular os selectboxes da comparação.

    Colunas: campaign_id, canal, campaign_name, label ('Canal · Nome'),
    investimento (para ordenar default por maior invest)."""
    cols = ["campaign_id", "canal", "campaign_name", "label", "investimento"]
    if df_camp.empty:
        return pd.DataFrame(columns=cols)

    agg = df_camp.groupby(
        ["campaign_id", "canal", "campaign_name"],
        as_index=False, dropna=False,
    ).agg(investimento=("investimento", "sum"))

    agg["label"] = (
        agg["canal"].fillna("?").astype(str)
        + " · "
        + agg["campaign_name"].fillna("(sem nome)").astype(str)
    )
    return (agg[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


_CAMPANHA_KPIS_ZEROS = {
    # Plataforma (vw_mkt_campanhas) — defaults numéricos zero
    "canal": "—", "campaign_name": "—", "objetivo": "—",
    "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0,
    "alcance": 0.0, "ctr": 0.0, "cpc": 0.0,
    # Resultado (mart) — defaults None ("sem atribuição")
    "tem_resultados": False,
    "leads_total": None, "leads_mais_12": None, "leads_menos_12": None,
    "leads_nao_atua": None,
    "agendamentos": None, "comparecimentos": None, "no_shows": None,
    "deals": None, "deals_ganhos": None,
    "vendas": None, "valor_venda": None, "valor_receita": None,
    # Derivadas — None quando denominador zero ou sem atribuição
    "cpl": None, "cpl_mais_12": None, "cac": None, "roas": None,
}


def campanha_kpis(df_camp: pd.DataFrame,
                  campaign_id: str | None,
                  df_resultados: pd.DataFrame | None = None,
                  df_leads_por_utm: pd.DataFrame | None = None) -> dict:
    """KPIs de UMA campanha específica.

    Plataforma vem de `df_camp` (vw_mkt_campanhas, fonte oficial de invest/
    imp/cliques/alcance).

    **Leads, Leads +12, Leads -12, CPL e CPL +12** vêm de `df_leads_por_utm`
    (`mkt_campanhas_leads_por_utm.sql`) via match
    `LOWER(BTRIM(campaign_name)) = campaign_norm`. Quando o nome da campanha
    não casa com nenhum `utm_campaign`, esses 5 campos ficam como `None`
    ("—" no formatador).

    Demais métricas de resultado (Agendamentos, Comparecimentos, No-shows,
    Deals, Deals ganhos, Vendas, Receita) e derivadas (CAC, ROAS) continuam
    vindo de `df_resultados` (mart `odam.mart_ad_funnel_daily` agregada por
    `campaign_id`). `tem_resultados` = True quando a mart tem linha pra
    aquela campanha; controla o badge "✓ resultados atribuídos" /
    "⚠ sem atribuição no mart" no app.

    Derivadas (CPL/CPL+12/CAC/ROAS) usam INVEST OFICIAL (df_camp) sobre
    contagens da fonte canônica de leads (UTM ou mart) — NUNCA o
    `valor_venda` ou spend da mart como investimento."""
    out = dict(_CAMPANHA_KPIS_ZEROS)

    if df_camp.empty or not campaign_id:
        return out

    df_one = df_camp[df_camp["campaign_id"] == campaign_id]
    if df_one.empty:
        return out

    # ---- Plataforma (vw_mkt_campanhas) -----------------------------------
    canal = (df_one["canal"].iloc[0]
             if "canal" in df_one.columns else "—")
    name = (df_one["campaign_name"].iloc[0]
            if "campaign_name" in df_one.columns else "—")
    obj = (df_one["objetivo"].iloc[0]
           if "objetivo" in df_one.columns else None)
    obj = obj if (pd.notna(obj) and obj) else "—"

    invest = float(df_one["investimento"].sum())
    imp = float(df_one["impressoes"].sum())
    clk = float(df_one["cliques"].sum())
    alc = (float(df_one["alcance"].fillna(0).sum())
           if "alcance" in df_one.columns else 0.0)

    out.update({
        "canal": canal,
        "campaign_name": name,
        "objetivo": obj,
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "alcance": alc,
        "ctr": _safe_div(clk, imp) * 100,
        "cpc": _safe_div(invest, clk),
    })

    # ---- Resultado (mart) — agendamentos/vendas/receita/CAC/ROAS --------
    # Leads/+12/-12/CPL/CPL+12 são SOBRESCRITOS abaixo pelo source UTM
    # quando houver match — a mart entra apenas como fallback pra leads
    # quando o nome da campanha não casa com nenhum utm_campaign.
    has_results = (
        df_resultados is not None
        and not df_resultados.empty
        and "campaign_id" in df_resultados.columns
    )
    if has_results:
        match = df_resultados[df_resultados["campaign_id"] == campaign_id]
        if not match.empty:
            r = match.iloc[0]
            leads_total = float(r.get("leads_total", 0) or 0)
            leads_mais_12 = float(r.get("leads_mais_12", 0) or 0)
            leads_menos_12 = float(r.get("leads_menos_12", 0) or 0)
            leads_nao_atua = float(r.get("leads_nao_atua", 0) or 0)
            agend = float(r.get("agendamentos", 0) or 0)
            comp = float(r.get("comparecimentos", 0) or 0)
            no_shows = float(r.get("no_shows", 0) or 0)
            deals = float(r.get("deals", 0) or 0)
            deals_g = float(r.get("deals_ganhos", 0) or 0)
            vendas = float(r.get("vendas", 0) or 0)
            valor_v = float(r.get("valor_venda", 0) or 0)
            valor_r = float(r.get("valor_receita", 0) or 0)

            out["tem_resultados"] = True
            out["leads_total"] = leads_total
            out["leads_mais_12"] = leads_mais_12
            out["leads_menos_12"] = leads_menos_12
            out["leads_nao_atua"] = leads_nao_atua
            out["agendamentos"] = agend
            out["comparecimentos"] = comp
            out["no_shows"] = no_shows
            out["deals"] = deals
            out["deals_ganhos"] = deals_g
            out["vendas"] = vendas
            out["valor_venda"] = valor_v
            out["valor_receita"] = valor_r

            # Derivadas mart — denominador zero vira None ("—" no formatador)
            out["cpl"] = (invest / leads_total) if leads_total > 0 else None
            out["cpl_mais_12"] = (invest / leads_mais_12) if leads_mais_12 > 0 else None
            out["cac"] = (invest / vendas) if vendas > 0 else None
            out["roas"] = (valor_r / invest) if invest > 0 else None

    # ---- Override de leads via UTM (fonte canônica alinhada com a tabela
    # "Campanhas ativas" e com a Visão Geral). Acontece DEPOIS do bloco
    # mart pra que substitua tanto valores existentes (mart presente)
    # quanto preencha quando mart não tinha linha. Se UTM também não bate,
    # leads/CPL ficam None (sem fallback pra mart aqui — coerente com o
    # comportamento da tabela "Campanhas ativas").
    has_utm_leads = (
        df_leads_por_utm is not None
        and not df_leads_por_utm.empty
        and "campaign_norm" in df_leads_por_utm.columns
    )
    if has_utm_leads and isinstance(name, str) and name:
        name_norm = name.strip().lower()
        match_utm = df_leads_por_utm[df_leads_por_utm["campaign_norm"] == name_norm]
        if not match_utm.empty:
            r_utm = match_utm.iloc[0]
            leads_total_utm   = float(r_utm.get("leads_totais", 0) or 0)
            leads_mais_12_utm = float(r_utm.get("leads_mais_12", 0) or 0)
            leads_menos_12_utm = float(r_utm.get("leads_menos_12", 0) or 0)

            out["leads_total"]    = leads_total_utm
            out["leads_mais_12"]  = leads_mais_12_utm
            out["leads_menos_12"] = leads_menos_12_utm
            out["cpl"] = (
                invest / leads_total_utm if leads_total_utm > 0 else None
            )
            out["cpl_mais_12"] = (
                invest / leads_mais_12_utm if leads_mais_12_utm > 0 else None
            )
        else:
            # Nome não casou com nenhum utm_campaign — força "—" pra que o
            # comparativo deixe explícito que UTM não atribuiu (em vez de
            # mostrar resíduos da mart, que poderiam confundir).
            out["leads_total"]    = None
            out["leads_mais_12"]  = None
            out["leads_menos_12"] = None
            out["cpl"]            = None
            out["cpl_mais_12"]    = None

    return out


# Para cada métrica, define a regra do "vencedor":
#   higher → maior é melhor; lower → menor é melhor; None → sem vencedor.
# Investimento intencionalmente sem vencedor — alocação ≠ performance.
_COMPARA_CAMP_METRICAS = [
    # (label, key_no_kpis, regra, bloco)
    # Plataforma
    ("Investimento",     "investimento",   None,    "plataforma"),
    ("Impressões",       "impressoes",     "higher","plataforma"),
    ("Cliques",          "cliques",        "higher","plataforma"),
    ("Alcance",          "alcance",        "higher","plataforma"),
    ("CTR",              "ctr",            "higher","plataforma"),
    ("CPC",              "cpc",            "lower", "plataforma"),
    # Resultado (mart)
    ("Leads",            "leads_total",    "higher","resultado"),
    ("Leads +12",        "leads_mais_12",  "higher","resultado"),
    ("Leads -12",        "leads_menos_12", "higher","resultado"),
    ("Agendamentos",     "agendamentos",   "higher","resultado"),
    ("Comparecimentos",  "comparecimentos","higher","resultado"),
    ("No-shows",         "no_shows",       "lower", "resultado"),
    ("Deals",            "deals",          "higher","resultado"),
    ("Deals ganhos",     "deals_ganhos",   "higher","resultado"),
    ("Vendas",           "vendas",         "higher","resultado"),
    ("Receita",          "valor_receita",  "higher","resultado"),
    # Derivadas (mistas: invest oficial / mart)
    ("CPL",              "cpl",            "lower", "derivada"),
    ("CPL +12",          "cpl_mais_12",    "lower", "derivada"),
    ("CAC",              "cac",            "lower", "derivada"),
    ("ROAS",             "roas",           "higher","derivada"),
]


def _venc_numerico(a, b, regra: str | None) -> str:
    """Decide vencedor entre 2 valores numéricos.
    - None de qualquer lado → '' (incompleto, conservador)
    - Ambos 0 → '' (empate trivial)
    - regra=None → '' (sem vencedor)"""
    if regra is None:
        return ""
    if a is None or b is None:
        return ""
    if a == 0 and b == 0:
        return ""
    if regra == "higher":
        return "A" if a > b else ("B" if b > a else "")
    if regra == "lower":
        # Quem está em zero não "vence" lower (zero não é melhor que valor real)
        if a == 0:
            return "B"
        if b == 0:
            return "A"
        return "A" if a < b else ("B" if b < a else "")
    return ""


# ---------------------------------------------------------------------------
# Comparar páginas / variantes (MVP — só leads, sem visitas/conversão real)
# ---------------------------------------------------------------------------
# Fonte: mkt_paginas_variantes.sql (email-level: 1 row por lead submission
# com classif_final, page_url, utm_*, *_id já normalizados).
# Filter (campanha, criativo) + aggregate por (page_pathname, lp_variante)
# acontece em Python via `agregar_paginas_variantes()`. As funções
# `lista_paginas_variantes`, `pagina_variante_kpis` e
# `compara_paginas_variantes` consomem a tabela JÁ AGREGADA.
# Sem visit-tracking ligável a leads no DB hoje — esse bloco mostra apenas
# geração/qualidade/origem de leads, não conversão da página.

# Separador na chave composta. Improvável em paths/variantes reais.
_PV_SEP = "||"


def _pv_chave(page_pathname: str | None, lp_variante: str | None) -> str:
    p = page_pathname if (page_pathname and str(page_pathname).strip()) else "(sem path)"
    v = lp_variante if (lp_variante and str(lp_variante).strip()) else "(sem variante)"
    return f"{p}{_PV_SEP}{v}"


def _uniq(g: pd.DataFrame, col: str) -> list:
    """Lista distinta ordenada da coluna `col` em `g`. Vazia se col ausente."""
    if col not in g.columns:
        return []
    return sorted(g[col].dropna().unique().tolist())


def _principal(g: pd.DataFrame, col: str):
    """Valor de `col` com mais e-mails distintos no grupo. None se ausente."""
    if col not in g.columns:
        return None
    s = g.dropna(subset=[col]).groupby(col)["email_norm"].nunique()
    return s.sort_values(ascending=False).index[0] if not s.empty else None


def _pv_classif_flags(classif_series: pd.Series) -> dict:
    """Conta distintos (já é distinto por construção quando vem de
    drop_duplicates email_norm) por categoria de classificação.
    Regras idênticas à Visão Geral / Campanhas."""
    s = classif_series.fillna("")
    is_mais = s.str.contains(r"\+12", regex=True, na=False)
    is_menos = s.str.contains(r"-12", regex=True, na=False)
    is_nao_atua = s.str.contains("não atua", case=False, regex=False, na=False)
    return {
        "leads_qualificados": int((is_mais | is_menos).sum()),
        "leads_mais_12":      int(is_mais.sum()),
        "leads_menos_12":     int(is_menos.sum()),
        "leads_nao_atua":     int(is_nao_atua.sum()),
    }


def agregar_paginas_variantes(df_raw: pd.DataFrame,
                              campanha: str | None = None,
                              origem: str | None = None,
                              midia: str | None = None,
                              timezone: str | None = None,
                              device_type: str | None = None,
                              criativo: str | None = None,
                              ) -> pd.DataFrame:
    """Aplica filtros opcionais e agrega o DF email-level por
    (page_pathname, lp_variante). Para cada kwarg, valor `None` ou
    "Todas"/"Todos" desliga o filtro.

    Filtros mapeiam pra colunas do DF:
        campanha     → utm_campaign
        origem       → utm_source
        midia        → utm_medium
        timezone     → timezone
        device_type  → device_type
        criativo     → utm_content (mantido p/ compat futura — UI atual
                       não expõe mais; o detalhamento de criativos está
                       só no expander)

    Saída — 1 row por (path, variante) com:
      leads_totais, leads_qualificados, leads_mais_12, leads_menos_12,
      leads_nao_atua, taxa_qualificacao, taxa_mais_12,
      page_url_exemplo,
      canais / origens (list utm_source distintos — SEMPRE iguais),
      campanhas, criativos, midias, fusos, dispositivos (listas distintas),
      qtd_campanhas, qtd_criativos, qtd_midias, qtd_fusos, qtd_dispositivos,
      campanha_principal, criativo_principal (mais e-mails distintos).

    Period-distinct: contagens de e-mail usam `nunique()` após filtrar.
    Classificações: cada e-mail entra com a classif_final (já canônica
    no SQL — ÚLTIMA row do e-mail no período)."""
    cols = ["page_pathname", "lp_variante",
            "leads_totais", "leads_qualificados",
            "leads_mais_12", "leads_menos_12", "leads_nao_atua",
            "taxa_qualificacao", "taxa_mais_12",
            # CRM / Zoho
            "leads_no_crm", "leads_ganhos",
            "cobertura_crm", "taxa_lead_ganho",
            # Origem
            "page_url_exemplo",
            "canais", "campanhas", "criativos",
            "midias", "fusos", "dispositivos",
            "qtd_campanhas", "qtd_criativos",
            "qtd_midias", "qtd_fusos", "qtd_dispositivos",
            "campanha_principal", "criativo_principal"]
    if df_raw.empty:
        return pd.DataFrame(columns=cols)

    sub = df_raw.copy()
    sub["page_pathname"] = sub["page_pathname"].fillna("(sem path)")
    sub["lp_variante"]   = sub["lp_variante"].fillna("(sem variante)")

    # Filtros — None ou "Todas/Todos" são no-op. A coluna correspondente
    # precisa existir no DF (proteção contra schema desatualizado).
    _SENT = {None, "", "Todas", "Todos"}
    pares = (
        (campanha,    "utm_campaign"),
        (origem,      "utm_source"),
        (midia,       "utm_medium"),
        (timezone,    "timezone"),
        (device_type, "device_type"),
        (criativo,    "utm_content"),
    )
    for valor, col in pares:
        if valor not in _SENT and col in sub.columns:
            sub = sub[sub[col] == valor]

    if sub.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for (path, variante), g in sub.groupby(["page_pathname", "lp_variante"],
                                            dropna=False):
        # E-mails distintos no grupo + sua classif_final canônica
        emails_classif = g.drop_duplicates("email_norm")[["email_norm",
                                                          "classif_final"]]
        leads_totais = len(emails_classif)
        flags = _pv_classif_flags(emails_classif["classif_final"])

        # CRM/Zoho — flags são por lead submission no SQL; um e-mail é
        # considerado "no CRM" se QUALQUER de suas submissões pareou com
        # deal (any() sobre o flag por email).
        if "flag_tem_deal" in g.columns and "flag_ganho" in g.columns:
            email_flags = (
                g.groupby("email_norm")[["flag_tem_deal", "flag_ganho"]]
                 .any()
            )
            leads_no_crm = int(email_flags["flag_tem_deal"].sum())
            leads_ganhos = int(email_flags["flag_ganho"].sum())
        else:
            leads_no_crm = 0
            leads_ganhos = 0

        # URL exemplo = mais recente do grupo
        page_url_exemplo = (
            g.sort_values("created_at", ascending=False).iloc[0].get("page_url")
        )
        if pd.isna(page_url_exemplo):
            page_url_exemplo = None

        canais       = _uniq(g, "utm_source")
        campanhas    = _uniq(g, "utm_campaign")
        criativos    = _uniq(g, "utm_content")
        midias       = _uniq(g, "utm_medium")
        fusos        = _uniq(g, "timezone")
        dispositivos = _uniq(g, "device_type")

        rows.append({
            "page_pathname": path,
            "lp_variante":   variante,
            "leads_totais":  int(leads_totais),
            **flags,
            "taxa_qualificacao": _safe_div(flags["leads_qualificados"], leads_totais) * 100,
            "taxa_mais_12":      _safe_div(flags["leads_mais_12"], leads_totais) * 100,
            # CRM/Zoho
            "leads_no_crm":   leads_no_crm,
            "leads_ganhos":   leads_ganhos,
            "cobertura_crm":     _safe_div(leads_no_crm, leads_totais) * 100,
            "taxa_lead_ganho":   _safe_div(leads_ganhos, leads_totais) * 100,
            "page_url_exemplo": page_url_exemplo,
            "canais": canais,
            "campanhas": campanhas,
            "criativos": criativos,
            "midias": midias,
            "fusos": fusos,
            "dispositivos": dispositivos,
            "qtd_campanhas":     len(campanhas),
            "qtd_criativos":     len(criativos),
            "qtd_midias":        len(midias),
            "qtd_fusos":         len(fusos),
            "qtd_dispositivos":  len(dispositivos),
            "campanha_principal": _principal(g, "utm_campaign"),
            "criativo_principal": _principal(g, "utm_content"),
        })

    return (pd.DataFrame(rows, columns=cols)
              .sort_values("leads_totais", ascending=False)
              .reset_index(drop=True))


def lista_paginas_variantes(df_agg: pd.DataFrame) -> pd.DataFrame:
    """Lista única para popular os selectboxes Página A/B. Espera o DF
    JÁ AGREGADO por `agregar_paginas_variantes()`.

    Colunas: chave, page_pathname, lp_variante, label, leads_totais.
    Label: "<path> · <variante> · <N> leads"."""
    cols = ["chave", "page_pathname", "lp_variante", "label", "leads_totais"]
    if df_agg.empty:
        return pd.DataFrame(columns=cols)

    out = df_agg.copy()
    out["chave"] = out.apply(
        lambda r: _pv_chave(r["page_pathname"], r["lp_variante"]), axis=1
    )
    out["label"] = (
        out["page_pathname"].astype(str) + " · "
        + out["lp_variante"].astype(str) + " · "
        + out["leads_totais"].astype("int64").astype(str) + " leads"
    )
    return (out[cols]
            .sort_values("leads_totais", ascending=False)
            .reset_index(drop=True))


_PAGINA_VARIANTE_ZEROS = {
    "page_pathname": "—", "lp_variante": "—",
    "leads_totais": 0,
    "leads_qualificados": 0,
    "leads_mais_12": 0,
    "leads_menos_12": 0,
    "leads_nao_atua": 0,
    "taxa_qualificacao": 0.0,
    "taxa_mais_12": 0.0,
    # CRM / Zoho
    "leads_no_crm": 0,
    "leads_ganhos": 0,
    "cobertura_crm": 0.0,
    "taxa_lead_ganho": 0.0,
    # Origem (preenchidos quando a chave é encontrada na DF agregada)
    "qtd_campanhas": 0,
    "qtd_criativos": 0,
    "qtd_midias": 0,
    "qtd_fusos": 0,
    "qtd_dispositivos": 0,
    "campanha_principal": None,
    "criativo_principal": None,
    "page_url_exemplo": None,
    "canais": [],
    "campanhas": [],
    "criativos": [],
    "midias": [],
    "fusos": [],
    "dispositivos": [],
}


def pagina_variante_kpis(df_agg: pd.DataFrame, chave: str | None) -> dict:
    """KPIs de UMA (page_pathname, lp_variante) identificada pela chave
    composta. Espera DF JÁ AGREGADO. Inclui campanha/criativo principal
    e contagens de origem além das métricas de lead/classif."""
    out = dict(_PAGINA_VARIANTE_ZEROS)
    if df_agg.empty or not chave:
        return out

    sub = df_agg.copy()
    sub["chave"] = sub.apply(
        lambda r: _pv_chave(r["page_pathname"], r["lp_variante"]), axis=1
    )
    match = sub[sub["chave"] == chave]
    if match.empty:
        return out

    r = match.iloc[0]
    out.update({
        "page_pathname": str(r["page_pathname"]),
        "lp_variante":   str(r["lp_variante"]),
        "leads_totais":       int(r["leads_totais"]),
        "leads_qualificados": int(r["leads_qualificados"]),
        "leads_mais_12":      int(r["leads_mais_12"]),
        "leads_menos_12":     int(r["leads_menos_12"]),
        "leads_nao_atua":     int(r["leads_nao_atua"]),
        "taxa_qualificacao":  float(r["taxa_qualificacao"]),
        "taxa_mais_12":       float(r["taxa_mais_12"]),
        "leads_no_crm":       int(r.get("leads_no_crm", 0) or 0),
        "leads_ganhos":       int(r.get("leads_ganhos", 0) or 0),
        "cobertura_crm":      float(r.get("cobertura_crm", 0) or 0),
        "taxa_lead_ganho":    float(r.get("taxa_lead_ganho", 0) or 0),
        "qtd_campanhas":      int(r.get("qtd_campanhas", 0) or 0),
        "qtd_criativos":      int(r.get("qtd_criativos", 0) or 0),
        "qtd_midias":         int(r.get("qtd_midias", 0) or 0),
        "qtd_fusos":          int(r.get("qtd_fusos", 0) or 0),
        "qtd_dispositivos":   int(r.get("qtd_dispositivos", 0) or 0),
        "campanha_principal": r.get("campanha_principal"),
        "criativo_principal": r.get("criativo_principal"),
        "page_url_exemplo":   r.get("page_url_exemplo"),
        "canais":       list(r.get("canais") or []),
        "campanhas":    list(r.get("campanhas") or []),
        "criativos":    list(r.get("criativos") or []),
        "midias":       list(r.get("midias") or []),
        "fusos":        list(r.get("fusos") or []),
        "dispositivos": list(r.get("dispositivos") or []),
    })
    return out


# (label, key, regra de vencedor)
# Maior é melhor: leads totais, qualificados, +12, taxas, qtd campanhas/criativos.
# Sem vencedor para Leads -12, Não atua (interpretação ambígua) e para
# Campanha/Criativo principal (categóricos).
_COMPARA_PV_METRICAS = [
    ("Leads totais",         "leads_totais",       "higher"),
    ("Leads qualificados",   "leads_qualificados", "higher"),
    ("Leads +12",            "leads_mais_12",      "higher"),
    ("Leads -12",            "leads_menos_12",     None),
    ("Não atua",             "leads_nao_atua",     None),
    ("Taxa qualificação",    "taxa_qualificacao",  "higher"),
    ("Taxa +12",             "taxa_mais_12",       "higher"),
    # CRM / Zoho — conversão lead → funil comercial (NÃO conversão de página).
    ("Leads no CRM",         "leads_no_crm",       "higher"),
    ("Cobertura CRM",        "cobertura_crm",      "higher"),
    ("Leads ganhos",         "leads_ganhos",       "higher"),
    ("Taxa Lead → Ganho",    "taxa_lead_ganho",    "higher"),
    # Origem
    ("Qtd. campanhas",       "qtd_campanhas",      "higher"),
    ("Qtd. criativos",       "qtd_criativos",      "higher"),
    ("Campanha principal",   "campanha_principal", None),
    ("Criativo principal",   "criativo_principal", None),
    ("URL exemplo",          "page_url_exemplo",   None),
]


def compara_paginas_variantes(kA: dict, kB: dict) -> pd.DataFrame:
    """Tabela comparativa A vs B no estilo `compara_campanhas`.

    Colunas: metrica, valor_a, valor_b, delta_pct, vencedor.
    Δ% = (B - A) / A × 100; None quando A=0, algum lado None, ou métrica
    categórica (Campanha/Criativo principal). Vencedor segue
    `_venc_numerico` (reusado de Comparar campanhas)."""
    rows = []
    for label, key, regra in _COMPARA_PV_METRICAS:
        a = kA.get(key)
        b = kB.get(key)
        # Δ% só calcula entre valores numéricos
        delta = None
        if (a is not None and b is not None
                and isinstance(a, (int, float))
                and isinstance(b, (int, float))
                and a != 0):
            delta = (b - a) / a * 100
        rows.append({
            "metrica": label,
            "valor_a": a,
            "valor_b": b,
            "delta_pct": delta,
            "vencedor": _venc_numerico(a, b, regra),
        })
    return pd.DataFrame(rows)


def compara_campanhas(kA: dict, kB: dict) -> pd.DataFrame:
    """Tabela comparativa entre 2 campanhas.

    Colunas: metrica, valor_a, valor_b, delta_pct, vencedor, bloco.
    - Categóricos (Canal, Objetivo): delta=None, vencedor=''.
    - Numéricos (plataforma + resultado + derivadas):
        valor pode ser número (incl. 0 real) ou None ("—" no formatador).
    - Δ%: None quando algum lado é None ou A=0.
    - Vencedor: '' quando algum lado é None (conservador, evita destacar
      campanha por ausência de atribuição). Para regras higher/lower, segue
      a regra padrão entre números."""
    rows = [
        {"metrica": "Canal", "valor_a": kA["canal"], "valor_b": kB["canal"],
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
        {"metrica": "Objetivo", "valor_a": kA["objetivo"], "valor_b": kB["objetivo"],
         "delta_pct": None, "vencedor": "", "bloco": "identidade"},
    ]

    for label, key, regra, bloco in _COMPARA_CAMP_METRICAS:
        a = kA.get(key)
        b = kB.get(key)
        # Δ% só calcula se ambos numéricos e A != 0
        if a is not None and b is not None and a != 0:
            delta = (b - a) / a * 100
        else:
            delta = None
        rows.append({
            "metrica": label,
            "valor_a": a,
            "valor_b": b,
            "delta_pct": delta,
            "vencedor": _venc_numerico(a, b, regra),
            "bloco": bloco,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Comparar campanhas POR UTM — modelo herdado de "Comparar páginas / variantes"
# ---------------------------------------------------------------------------
# Substitui o comparativo antigo (campaign_id + odam.mart) por uma versão
# baseada em utm_campaign + Zoho. Fonte primária: mkt_campanhas_leads_por_utm.sql
# (já enriquecido com leads/CRM/vendas_novas via priority match). Plataforma
# (invest/imp/cliques/alcance) vem de bi.vw_mkt_campanhas agregada por
# campaign_name normalizado (LOWER+BTRIM) — mesmo match que enriquece
# "Campanhas ativas".

def agregar_campanhas_por_utm(df_pv_raw: pd.DataFrame,
                              df_camp: pd.DataFrame,
                              origem: str | None = None,
                              midia: str | None = None,
                              timezone: str | None = None,
                              device_type: str | None = None) -> pd.DataFrame:
    """Agrega o DF email-level (`mkt_paginas_variantes.sql`) por
    `utm_campaign` e merge com plataforma de `df_camp`. Filtros opcionais
    aplicam ANTES da agregação — afetam só esse bloco da página.

    Saída — 1 row por utm_campaign (entre as que têm plataforma + leads):
      campaign_norm, utm_campaign, canal,
      investimento, impressoes, cliques, alcance, ctr, cpc,
      leads_totais, leads_qualificados, leads_mais_12, leads_menos_12,
      leads_nao_atua, taxa_qualificacao, taxa_mais_12,
      leads_no_crm, leads_ganhos, vendas_novas, taxa_lead_venda_nova,
      pagina_principal, variante_principal, criativo_principal,
      page_url_exemplo,
      paginas, variantes, criativos, origens, midias, fusos, dispositivos,
      qtd_paginas, qtd_variantes, qtd_criativos.

    Espelha `agregar_paginas_variantes` da Growth, mas com grão
    utm_campaign + métricas de plataforma."""
    cols = ["campaign_norm", "utm_campaign", "canal",
            "investimento", "impressoes", "cliques", "alcance", "ctr", "cpc",
            "leads_totais", "leads_qualificados",
            "leads_mais_12", "leads_menos_12", "leads_nao_atua",
            "taxa_qualificacao", "taxa_mais_12",
            "leads_no_crm", "leads_ganhos", "vendas_novas",
            "taxa_lead_venda_nova",
            "pagina_principal", "variante_principal", "criativo_principal",
            "page_url_exemplo",
            "paginas", "variantes", "criativos",
            "origens", "midias", "fusos", "dispositivos",
            "qtd_paginas", "qtd_variantes", "qtd_criativos"]

    if df_pv_raw is None or df_pv_raw.empty:
        return pd.DataFrame(columns=cols)

    sub = df_pv_raw.copy()
    # Só leads com utm_campaign (caso contrário, "Sem utm" não faz sentido aqui)
    sub = sub[sub["utm_campaign"].notna()
              & (sub["utm_campaign"].astype(str).str.strip() != "")]
    sub["campaign_norm"] = (
        sub["utm_campaign"].astype(str).str.strip().str.lower()
    )

    # Filtros (None ou "Todas/Todos" são no-op).
    _SENT = {None, "", "Todas", "Todos"}
    pares = (
        (origem,      "utm_source"),
        (midia,       "utm_medium"),
        (timezone,    "timezone"),
        (device_type, "device_type"),
    )
    for valor, col in pares:
        if valor not in _SENT and col in sub.columns:
            sub = sub[sub[col] == valor]

    if sub.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for (cn, utm_disp), g in sub.groupby(
            ["campaign_norm", "utm_campaign"], dropna=False):
        # E-mails distintos no grupo + flags de classif/deal.
        # Cada e-mail aparece com 1 deal (priority match) → drop_duplicates
        # é seguro pra extrair flag_ganho/deal_tipo_venda únicos por e-mail.
        emails = g.drop_duplicates("email_norm")[
            ["email_norm", "classif_final",
             "flag_tem_deal", "flag_ganho", "deal_tipo_venda"]
        ]
        leads_totais = len(emails)
        flags = _pv_classif_flags(emails["classif_final"])

        leads_no_crm = int(emails["flag_tem_deal"].fillna(False).sum())
        leads_ganhos = int(emails["flag_ganho"].fillna(False).sum())
        vendas_novas = int(
            (emails["flag_ganho"].fillna(False)
             & (emails["deal_tipo_venda"] == "Novo cliente")).sum()
        )

        # URL exemplo = mais recente do grupo
        url_recente = (
            g.sort_values("created_at", ascending=False).iloc[0].get("page_url")
        )
        if pd.isna(url_recente):
            url_recente = None

        paginas      = _uniq(g, "page_pathname")
        variantes    = _uniq(g, "lp_variante")
        criativos    = _uniq(g, "utm_content")
        origens      = _uniq(g, "utm_source")
        midias       = _uniq(g, "utm_medium")
        fusos        = _uniq(g, "timezone")
        dispositivos = _uniq(g, "device_type")

        rows.append({
            "campaign_norm": cn,
            "utm_campaign":  utm_disp,
            "leads_totais":      int(leads_totais),
            **flags,
            "taxa_qualificacao": _safe_div(flags["leads_qualificados"], leads_totais) * 100,
            "taxa_mais_12":      _safe_div(flags["leads_mais_12"], leads_totais) * 100,
            "leads_no_crm":      leads_no_crm,
            "leads_ganhos":      leads_ganhos,
            "vendas_novas":      vendas_novas,
            "taxa_lead_venda_nova": _safe_div(vendas_novas, leads_totais) * 100,
            "pagina_principal":  _principal(g, "page_pathname"),
            "variante_principal": _principal(g, "lp_variante"),
            "criativo_principal": _principal(g, "utm_content"),
            "page_url_exemplo":  url_recente,
            "paginas": paginas, "variantes": variantes, "criativos": criativos,
            "origens": origens, "midias": midias, "fusos": fusos,
            "dispositivos": dispositivos,
            "qtd_paginas":    len(paginas),
            "qtd_variantes":  len(variantes),
            "qtd_criativos":  len(criativos),
        })

    df_agg = pd.DataFrame(rows)
    if df_agg.empty:
        return pd.DataFrame(columns=cols)

    # Plataforma — só inclui campanhas que existem em df_camp (canal-filtered).
    # Inner join descarta UTMs sem invest na plataforma (foco em paid).
    if df_camp is None or df_camp.empty:
        return pd.DataFrame(columns=cols)

    camp = df_camp.copy()
    camp["campaign_norm"] = (
        camp["campaign_name"].fillna("").astype(str).str.strip().str.lower()
    )
    plat = camp.groupby("campaign_norm", as_index=False).agg(
        investimento=("investimento", "sum"),
        impressoes=("impressoes",   "sum"),
        cliques=("cliques",         "sum"),
        alcance=("alcance",         "sum"),
    )
    canal_per = (
        camp.dropna(subset=["canal"])
            .groupby("campaign_norm")["canal"]
            .first()
            .reset_index()
    )
    plat = plat.merge(canal_per, on="campaign_norm", how="left")
    plat["ctr"] = plat.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )
    plat["cpc"] = plat.apply(
        lambda r: _safe_div(r["investimento"], r["cliques"]), axis=1
    )

    df_agg = df_agg.merge(plat, on="campaign_norm", how="inner")
    return (df_agg[cols]
            .sort_values("leads_totais", ascending=False)
            .reset_index(drop=True))


def lista_campanhas_por_utm(df_agg: pd.DataFrame) -> pd.DataFrame:
    """Lista de utm_campaign para popular selectboxes A/B.

    Espera o DF agregado por `agregar_campanhas_por_utm`. Colunas:
    campaign_norm, utm_campaign, label, leads_totais."""
    cols = ["campaign_norm", "utm_campaign", "label", "leads_totais"]
    if df_agg is None or df_agg.empty:
        return pd.DataFrame(columns=cols)
    out = df_agg.copy()
    out["label"] = (
        out["utm_campaign"].astype(str) + " · "
        + out["leads_totais"].astype("int64").astype(str) + " leads"
    )
    return (out[cols]
            .sort_values("leads_totais", ascending=False)
            .reset_index(drop=True))


_CAMPANHA_UTM_ZEROS = {
    "campaign_norm": "—", "utm_campaign": "—", "canal": "—",
    # Plataforma
    "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0,
    "alcance": 0.0, "ctr": 0.0, "cpc": 0.0,
    # Leads (regra Visão Geral)
    "leads_totais": 0, "leads_qualificados": 0,
    "leads_mais_12": 0, "leads_menos_12": 0, "leads_nao_atua": 0,
    "taxa_qualificacao": 0.0, "taxa_mais_12": 0.0,
    # CRM/Zoho
    "leads_no_crm": 0, "leads_ganhos": 0,
    "vendas_novas": 0, "taxa_lead_venda_nova": 0.0,
    # Origem (página/variante/criativo + listas)
    "pagina_principal": None, "variante_principal": None,
    "criativo_principal": None, "page_url_exemplo": None,
    "paginas": [], "variantes": [], "criativos": [],
    "origens": [], "midias": [], "fusos": [], "dispositivos": [],
    "qtd_paginas": 0, "qtd_variantes": 0, "qtd_criativos": 0,
}


def campanha_utm_kpis(df_agg: pd.DataFrame,
                      campaign_norm: str | None) -> dict:
    """KPIs de UMA utm_campaign do DF agregado por
    `agregar_campanhas_por_utm`."""
    out = dict(_CAMPANHA_UTM_ZEROS)
    if df_agg is None or df_agg.empty or not campaign_norm:
        return out
    match = df_agg[df_agg["campaign_norm"] == campaign_norm]
    if match.empty:
        return out
    r = match.iloc[0]
    out.update({
        "campaign_norm": str(r["campaign_norm"]),
        "utm_campaign":  str(r["utm_campaign"]),
        "canal":         str(r.get("canal") or "—"),
        # Plataforma
        "investimento":  float(r.get("investimento", 0) or 0),
        "impressoes":    float(r.get("impressoes", 0) or 0),
        "cliques":       float(r.get("cliques", 0) or 0),
        "alcance":       float(r.get("alcance", 0) or 0),
        "ctr":           float(r.get("ctr", 0) or 0),
        "cpc":           float(r.get("cpc", 0) or 0),
        # Leads
        "leads_totais":       int(r["leads_totais"]),
        "leads_qualificados": int(r["leads_qualificados"]),
        "leads_mais_12":      int(r["leads_mais_12"]),
        "leads_menos_12":     int(r["leads_menos_12"]),
        "leads_nao_atua":     int(r["leads_nao_atua"]),
        "taxa_qualificacao":  float(r["taxa_qualificacao"]),
        "taxa_mais_12":       float(r["taxa_mais_12"]),
        # CRM
        "leads_no_crm":       int(r["leads_no_crm"]),
        "leads_ganhos":       int(r["leads_ganhos"]),
        "vendas_novas":       int(r["vendas_novas"]),
        "taxa_lead_venda_nova": float(r["taxa_lead_venda_nova"]),
        # Origem
        "pagina_principal":   r.get("pagina_principal"),
        "variante_principal": r.get("variante_principal"),
        "criativo_principal": r.get("criativo_principal"),
        "page_url_exemplo":   r.get("page_url_exemplo"),
        "paginas":      list(r.get("paginas") or []),
        "variantes":    list(r.get("variantes") or []),
        "criativos":    list(r.get("criativos") or []),
        "origens":      list(r.get("origens") or []),
        "midias":       list(r.get("midias") or []),
        "fusos":        list(r.get("fusos") or []),
        "dispositivos": list(r.get("dispositivos") or []),
        "qtd_paginas":   int(r.get("qtd_paginas", 0) or 0),
        "qtd_variantes": int(r.get("qtd_variantes", 0) or 0),
        "qtd_criativos": int(r.get("qtd_criativos", 0) or 0),
    })
    return out


# (label, key, regra de vencedor) — espelha _COMPARA_PV_METRICAS, adaptada.
_COMPARA_CAMP_UTM_METRICAS = [
    # Identidade — categórico, sem vencedor
    ("Canal",                "canal",              None),
    # Plataforma
    ("Investimento",         "investimento",       None),
    ("Impressões",           "impressoes",         "higher"),
    ("Cliques",              "cliques",            "higher"),
    ("Alcance",              "alcance",            "higher"),
    ("CTR",                  "ctr",                "higher"),
    ("CPC",                  "cpc",                "lower"),
    # Leads (regra Visão Geral)
    ("Leads totais",         "leads_totais",       "higher"),
    ("Leads qualificados",   "leads_qualificados", "higher"),
    ("Leads +12",            "leads_mais_12",      "higher"),
    ("Leads -12",            "leads_menos_12",     None),
    ("Não atua",             "leads_nao_atua",     None),
    ("Taxa qualificação",    "taxa_qualificacao",  "higher"),
    ("Taxa +12",             "taxa_mais_12",       "higher"),
    # CRM/Zoho
    ("Vendas novas",         "vendas_novas",       "higher"),
    ("Taxa Lead → Venda nova", "taxa_lead_venda_nova", "higher"),
    # Origem (categóricos + qtd)
    ("Página principal",     "pagina_principal",   None),
    ("Variante principal",   "variante_principal", None),
    ("Qtd. páginas",         "qtd_paginas",        "higher"),
    ("Qtd. variantes",       "qtd_variantes",      "higher"),
    ("URL exemplo",          "page_url_exemplo",   None),
]


def compara_campanhas_utm(kA: dict, kB: dict) -> pd.DataFrame:
    """Tabela comparativa A vs B de utm_campaign — espelha
    `compara_paginas_variantes` da Growth, mas com métricas adicionais
    de plataforma (Invest/Imp/Cliques/Alcance/CTR/CPC).

    Colunas: metrica, valor_a, valor_b, delta_pct, vencedor.
    Δ% só calcula entre valores numéricos."""
    rows = []
    for label, key, regra in _COMPARA_CAMP_UTM_METRICAS:
        a = kA.get(key)
        b = kB.get(key)
        delta = None
        if (a is not None and b is not None
                and isinstance(a, (int, float))
                and isinstance(b, (int, float))
                and a != 0):
            delta = (b - a) / a * 100
        rows.append({
            "metrica": label,
            "valor_a": a,
            "valor_b": b,
            "delta_pct": delta,
            "vencedor": _venc_numerico(a, b, regra),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Comparar criativos — espelha o modelo de Campanhas, mas grão `utm_content`
# (= `ad_name` na plataforma). Match: lower(btrim(ad_name)) =
# lower(btrim(utm_content)). Mesma fonte de filtros (df_pv_raw =
# mkt_paginas_variantes.sql) usada em "Comparar campanhas".
# ---------------------------------------------------------------------------

def agregar_criativos_por_utm_content(
    df_pv_raw: pd.DataFrame,
    df_criativos: pd.DataFrame,
    origem: str | None = None,
    midia: str | None = None,
    timezone: str | None = None,
    device_type: str | None = None,
) -> pd.DataFrame:
    """Agrega o DF email-level (`mkt_paginas_variantes.sql`) por
    `utm_content` e cruza com a plataforma de criativos
    (`bi.vw_mkt_criativos`) por `lower(btrim(ad_name)) =
    lower(btrim(utm_content))`. Filtros opcionais aplicam ANTES da
    agregação — afetam só esse bloco da página.

    Saída — 1 row por ad_name_norm (entre os que têm plataforma + leads):
      ad_name_norm, ad_name, ad_name_display, qtd_adids,
      campanha_principal, adset_principal, status,
      quality_ranking, engagement_ranking, conversion_ranking,
      thumbnail_url, image_url, permalink_url, page_url_exemplo,
      investimento, impressoes, cliques, link_clicks, alcance, ctr, cpc,
      frequencia,
      leads_totais, leads_qualificados, leads_mais_12, leads_menos_12,
      leads_nao_atua, taxa_qualificacao, taxa_mais_12,
      leads_no_crm, leads_ganhos, vendas_novas, taxa_lead_venda_nova,
      cpl, cpl_mais_12, cac,
      origens, midias, fusos, dispositivos.
    """
    cols = [
        "ad_name_norm", "ad_name", "ad_name_display", "qtd_adids",
        "campanha_principal", "adset_principal", "status",
        "quality_ranking", "engagement_ranking", "conversion_ranking",
        "thumbnail_url", "image_url", "permalink_url", "page_url_exemplo",
        "investimento", "impressoes", "cliques", "link_clicks",
        "alcance", "ctr", "cpc", "frequencia",
        "leads_totais", "leads_qualificados",
        "leads_mais_12", "leads_menos_12", "leads_nao_atua",
        "taxa_qualificacao", "taxa_mais_12",
        "leads_no_crm", "leads_ganhos", "vendas_novas",
        "taxa_lead_venda_nova",
        "cpl", "cpl_mais_12", "cac",
        "origens", "midias", "fusos", "dispositivos",
    ]

    if df_pv_raw is None or df_pv_raw.empty:
        return pd.DataFrame(columns=cols)

    # 1) Email-level filtrado: só leads com utm_content válido +
    #    filtros de origem/mídia/fuso/dispositivo aplicados.
    sub = df_pv_raw.copy()
    sub = sub[sub["utm_content"].notna()
              & (sub["utm_content"].astype(str).str.strip() != "")]
    sub["ad_name_norm"] = (
        sub["utm_content"].astype(str).str.strip().str.lower()
    )

    _SENT = {None, "", "Todas", "Todos"}
    pares = (
        (origem,      "utm_source"),
        (midia,       "utm_medium"),
        (timezone,    "timezone"),
        (device_type, "device_type"),
    )
    for valor, col in pares:
        if valor not in _SENT and col in sub.columns:
            sub = sub[sub[col] == valor]

    if sub.empty:
        return pd.DataFrame(columns=cols)

    # 2) Agrega por ad_name_norm (= utm_content normalizado).
    rows = []
    for ad_norm, g in sub.groupby("ad_name_norm", dropna=False):
        emails = g.drop_duplicates("email_norm")[
            ["email_norm", "classif_final",
             "flag_tem_deal", "flag_ganho", "deal_tipo_venda"]
        ]
        leads_totais = len(emails)
        flags = _pv_classif_flags(emails["classif_final"])

        leads_no_crm = int(emails["flag_tem_deal"].fillna(False).sum())
        leads_ganhos = int(emails["flag_ganho"].fillna(False).sum())
        vendas_novas = int(
            (emails["flag_ganho"].fillna(False)
             & (emails["deal_tipo_venda"] == "Novo cliente")).sum()
        )

        url_recente = (
            g.sort_values("created_at", ascending=False).iloc[0].get("page_url")
        )
        if pd.isna(url_recente):
            url_recente = None

        # Forma original do utm_content (case preservado, mais legível
        # nos selects e tabelas).
        utm_display = g["utm_content"].dropna().astype(str).str.strip()
        ad_name_display = utm_display.iloc[0] if not utm_display.empty else ad_norm

        rows.append({
            "ad_name_norm": ad_norm,
            "ad_name_display": ad_name_display,
            "leads_totais":      int(leads_totais),
            **flags,
            "taxa_qualificacao": _safe_div(flags["leads_qualificados"], leads_totais) * 100,
            "taxa_mais_12":      _safe_div(flags["leads_mais_12"], leads_totais) * 100,
            "leads_no_crm":      leads_no_crm,
            "leads_ganhos":      leads_ganhos,
            "vendas_novas":      vendas_novas,
            "taxa_lead_venda_nova": _safe_div(vendas_novas, leads_totais) * 100,
            "page_url_exemplo":  url_recente,
            "origens":      _uniq(g, "utm_source"),
            "midias":       _uniq(g, "utm_medium"),
            "fusos":        _uniq(g, "timezone"),
            "dispositivos": _uniq(g, "device_type"),
        })

    df_agg = pd.DataFrame(rows)
    if df_agg.empty:
        return pd.DataFrame(columns=cols)

    # 3) Plataforma — agrega `bi.vw_mkt_criativos` por ad_name_norm
    #    (mesma chave de match). Inner join descarta utm_content sem
    #    nenhum ad_name correspondente na plataforma.
    if df_criativos is None or df_criativos.empty:
        return pd.DataFrame(columns=cols)

    cri = df_criativos.copy()
    cri["ad_name_norm"] = (
        cri["ad_name"].fillna("").astype(str).str.strip().str.lower()
    )

    plat_agg = cri.groupby("ad_name_norm", as_index=False).agg(
        ad_name=("ad_name", "first"),
        qtd_adids=("ad_id", lambda s: s.nunique()),
        investimento=("investimento", "sum"),
        impressoes=("impressoes", "sum"),
        cliques=("cliques", "sum"),
        link_clicks=("link_clicks", "sum")
            if "link_clicks" in cri.columns else ("cliques", "sum"),
        alcance=("alcance", "sum"),
    )
    if "link_clicks" not in cri.columns:
        plat_agg["link_clicks"] = 0

    # "Principal" por ad_name_norm = row do ad_id com maior invest.
    cri_sorted = cri.sort_values("investimento", ascending=False, na_position="last")
    plat_principal = (
        cri_sorted.drop_duplicates("ad_name_norm")
            .set_index("ad_name_norm")[[
                "campaign_name", "adset_name",
                "quality_ranking", "engagement_ranking", "conversion_ranking",
                "thumbnail_url", "image_url", "permalink_url",
            ]]
    )
    if "status_label" in cri.columns:
        plat_principal["status"] = (
            cri_sorted.drop_duplicates("ad_name_norm")
                .set_index("ad_name_norm")["status_label"]
        )
    elif "effective_status" in cri.columns:
        plat_principal["status"] = (
            cri_sorted.drop_duplicates("ad_name_norm")
                .set_index("ad_name_norm")["effective_status"]
        )
    else:
        plat_principal["status"] = None

    plat_agg = plat_agg.merge(
        plat_principal.reset_index(), on="ad_name_norm", how="left"
    ).rename(columns={
        "campaign_name": "campanha_principal",
        "adset_name":    "adset_principal",
    })
    plat_agg["ctr"] = plat_agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )
    plat_agg["cpc"] = plat_agg.apply(
        lambda r: _safe_div(r["investimento"], r["cliques"]), axis=1
    )
    plat_agg["frequencia"] = plat_agg.apply(
        lambda r: _safe_div(r["impressoes"], r["alcance"]), axis=1
    )

    df_agg = df_agg.merge(plat_agg, on="ad_name_norm", how="inner")

    # Derivadas finais (CPL/CPL+12/CAC).
    df_agg["cpl"] = df_agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_totais"]), axis=1
    )
    df_agg["cpl_mais_12"] = df_agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_mais_12"]), axis=1
    )
    df_agg["cac"] = df_agg.apply(
        lambda r: _safe_div(r["investimento"], r["vendas_novas"]), axis=1
    )

    return (df_agg[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


def lista_criativos_utm_content(df_agg: pd.DataFrame) -> pd.DataFrame:
    """Lista de criativos (utm_content/ad_name) pra popular selects A/B.
    Espera o DF agregado por `agregar_criativos_por_utm_content`."""
    cols = ["ad_name_norm", "ad_name_display", "label", "investimento"]
    if df_agg is None or df_agg.empty:
        return pd.DataFrame(columns=cols)
    out = df_agg.copy()
    invest_int = out["investimento"].fillna(0).astype(float).round(0).astype(int)
    out["label"] = (
        out["ad_name_display"].astype(str)
        + " · R$ " + invest_int.map(lambda v: f"{v:,}".replace(",", "."))
        + " · " + out["leads_totais"].astype("int64").astype(str) + " leads"
    )
    return (out[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


_CRIATIVO_UTM_ZEROS = {
    "ad_name_norm": "—", "ad_name_display": "—", "qtd_adids": 0,
    "campanha_principal": None, "adset_principal": None, "status": None,
    "quality_ranking": None, "engagement_ranking": None,
    "conversion_ranking": None,
    "thumbnail_url": None, "image_url": None, "permalink_url": None,
    "page_url_exemplo": None,
    "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0,
    "link_clicks": 0.0, "alcance": 0.0, "ctr": 0.0, "cpc": 0.0,
    "frequencia": 0.0,
    "leads_totais": 0, "leads_qualificados": 0,
    "leads_mais_12": 0, "leads_menos_12": 0, "leads_nao_atua": 0,
    "taxa_qualificacao": 0.0, "taxa_mais_12": 0.0,
    "leads_no_crm": 0, "leads_ganhos": 0,
    "vendas_novas": 0, "taxa_lead_venda_nova": 0.0,
    "cpl": 0.0, "cpl_mais_12": 0.0, "cac": 0.0,
    "origens": [], "midias": [], "fusos": [], "dispositivos": [],
}


def criativo_utm_content_kpis(df_agg: pd.DataFrame,
                              ad_name_norm: str | None) -> dict:
    """KPIs de UM criativo (ad_name_norm) do DF agregado por
    `agregar_criativos_por_utm_content`."""
    out = dict(_CRIATIVO_UTM_ZEROS)
    if df_agg is None or df_agg.empty or not ad_name_norm:
        return out
    match = df_agg[df_agg["ad_name_norm"] == ad_name_norm]
    if match.empty:
        return out
    r = match.iloc[0]
    int_keys = ("qtd_adids", "leads_totais", "leads_qualificados",
                "leads_mais_12", "leads_menos_12", "leads_nao_atua",
                "leads_no_crm", "leads_ganhos", "vendas_novas")
    float_keys = ("investimento", "impressoes", "cliques", "link_clicks",
                  "alcance", "ctr", "cpc", "frequencia",
                  "taxa_qualificacao", "taxa_mais_12",
                  "taxa_lead_venda_nova", "cpl", "cpl_mais_12", "cac")
    for k in int_keys:
        out[k] = int(r[k]) if pd.notna(r.get(k)) else 0
    for k in float_keys:
        v = r.get(k)
        out[k] = float(v) if pd.notna(v) else 0.0
    for k in ("ad_name_norm", "ad_name_display",
              "campanha_principal", "adset_principal", "status",
              "quality_ranking", "engagement_ranking", "conversion_ranking",
              "thumbnail_url", "image_url", "permalink_url",
              "page_url_exemplo"):
        v = r.get(k)
        out[k] = v if (v is not None and not (isinstance(v, float) and pd.isna(v))) else None
    for k in ("origens", "midias", "fusos", "dispositivos"):
        out[k] = list(r.get(k) or [])
    return out


# (label, key, regra de vencedor) — espelha _COMPARA_CAMP_UTM_METRICAS,
# adaptado para o grão criativo.
_COMPARA_CRIATIVO_UTM_METRICAS = [
    # Identidade — categórico, sem vencedor
    ("Campanha principal",  "campanha_principal",  None),
    ("Adset principal",     "adset_principal",     None),
    ("Status",              "status",              None),
    ("Quality ranking",     "quality_ranking",     None),
    ("Engagement ranking",  "engagement_ranking",  None),
    ("Conversion ranking",  "conversion_ranking",  None),
    ("Qtd. ad_ids",         "qtd_adids",           None),
    # Plataforma
    ("Investimento",        "investimento",        None),
    ("Impressões",          "impressoes",          "higher"),
    ("Cliques",             "cliques",             "higher"),
    ("Link clicks",         "link_clicks",         "higher"),
    ("Alcance",             "alcance",             "higher"),
    ("CTR",                 "ctr",                 "higher"),
    ("CPC",                 "cpc",                 "lower"),
    ("Frequência",          "frequencia",          "lower"),
    # Leads (regra Visão Geral)
    ("Leads totais",        "leads_totais",        "higher"),
    ("Leads qualificados",  "leads_qualificados",  "higher"),
    ("Leads +12",           "leads_mais_12",       "higher"),
    ("Leads -12",           "leads_menos_12",      None),
    ("Não atua",            "leads_nao_atua",      None),
    ("Taxa qualificação",   "taxa_qualificacao",   "higher"),
    ("Taxa +12",            "taxa_mais_12",        "higher"),
    # CRM/Zoho
    ("Leads no CRM",        "leads_no_crm",        "higher"),
    ("Vendas novas",        "vendas_novas",        "higher"),
    ("Taxa Lead → Venda nova", "taxa_lead_venda_nova", "higher"),
    # Derivadas
    ("CPL",                 "cpl",                 "lower"),
    ("CPL +12",             "cpl_mais_12",         "lower"),
    ("CAC",                 "cac",                 "lower"),
    # URL exemplo
    ("URL exemplo",         "page_url_exemplo",    None),
]


def compara_criativos_utm_content(kA: dict, kB: dict) -> pd.DataFrame:
    """Tabela comparativa A vs B de criativo (ad_name) — mesmo shape de
    `compara_campanhas_utm` (colunas metrica/valor_a/valor_b/delta_pct/
    vencedor). Δ% só calcula entre numéricos. Vencedor segue a regra
    declarada em `_COMPARA_CRIATIVO_UTM_METRICAS`."""
    rows = []
    for label, key, regra in _COMPARA_CRIATIVO_UTM_METRICAS:
        a = kA.get(key)
        b = kB.get(key)
        delta = None
        if (a is not None and b is not None
                and isinstance(a, (int, float))
                and isinstance(b, (int, float))
                and a != 0):
            delta = (b - a) / a * 100
        rows.append({
            "metrica": label,
            "valor_a": a,
            "valor_b": b,
            "delta_pct": delta,
            "vencedor": _venc_numerico(a, b, regra),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Cobertura da atribuição (diagnóstico do mart por presença de campaign_id)
# ---------------------------------------------------------------------------

_COBERTURA_ZEROS = {
    "total_leads": 0, "leads_com": 0, "leads_sem": 0, "pct_leads_com": 0.0,
    "total_vendas": 0, "vendas_com": 0, "vendas_sem": 0, "pct_vendas_com": 0.0,
    "total_receita": 0.0, "receita_com": 0.0, "receita_sem": 0.0,
    "pct_receita_com": 0.0,
    "nivel": "sem_dados",
}


def cobertura_atribuicao_kpis(df_cob: pd.DataFrame) -> dict:
    """Processa o resultado de `get_mkt_campanha_cobertura` e calcula níveis.

    Retorna dict com totais + com/sem campaign_id + percentuais para leads,
    vendas, receita; mais um campo `nivel` com base em `pct_leads_com`:
      - >= 80%   → 'alta'
      - 50–80%   → 'media'
      - < 50%    → 'baixa'
      - sem dados → 'sem_dados'
    """
    if df_cob is None or df_cob.empty:
        return dict(_COBERTURA_ZEROS)

    r = df_cob.iloc[0]
    total_leads = int(r.get("total_leads_mart", 0) or 0)
    leads_com = int(r.get("leads_com_campaign", 0) or 0)
    leads_sem = int(r.get("leads_sem_campaign", 0) or 0)
    total_vendas = int(r.get("total_vendas_mart", 0) or 0)
    vendas_com = int(r.get("vendas_com_campaign", 0) or 0)
    vendas_sem = int(r.get("vendas_sem_campaign", 0) or 0)
    total_receita = float(r.get("total_receita_mart", 0) or 0)
    receita_com = float(r.get("receita_com_campaign", 0) or 0)
    receita_sem = float(r.get("receita_sem_campaign", 0) or 0)

    pct_leads_com = _safe_div(leads_com, total_leads) * 100
    pct_vendas_com = _safe_div(vendas_com, total_vendas) * 100
    pct_receita_com = _safe_div(receita_com, total_receita) * 100

    if total_leads == 0:
        nivel = "sem_dados"
    elif pct_leads_com >= 80:
        nivel = "alta"
    elif pct_leads_com >= 50:
        nivel = "media"
    else:
        nivel = "baixa"

    return {
        "total_leads": total_leads,
        "leads_com": leads_com,
        "leads_sem": leads_sem,
        "pct_leads_com": pct_leads_com,
        "total_vendas": total_vendas,
        "vendas_com": vendas_com,
        "vendas_sem": vendas_sem,
        "pct_vendas_com": pct_vendas_com,
        "total_receita": total_receita,
        "receita_com": receita_com,
        "receita_sem": receita_sem,
        "pct_receita_com": pct_receita_com,
        "nivel": nivel,
    }


def campanhas_tabela_ativas(df_camp: pd.DataFrame,
                            df_leads_por_utm: pd.DataFrame | None = None,
                            ) -> pd.DataFrame:
    """Tabela de campanhas com `investimento > 0` no período, agregadas por
    `(campaign_id, campaign_name, canal, objetivo)` e ordenadas por invest desc.

    Quando `df_leads_por_utm` for passado (vindo de
    `mkt_campanhas_leads_por_utm.sql`), enriquece a tabela com leads /
    qualificados / +12 / -12 / CPL / CPL +12 / Tx Qualif +12. O match é
    `LOWER(BTRIM(campaign_name)) = campaign_norm` (norm já aplicado na SQL).
    Campanhas sem correspondência de UTM ficam com leads = 0 (e ratios = 0).
    """
    cols = ["campaign_name", "canal", "objetivo",
            "investimento", "impressoes", "cliques",
            "ctr", "cpc", "alcance"]
    cols_leads = ["leads", "leads_qualificados",
                  "leads_mais_12", "leads_menos_12",
                  "cpl", "cpl_mais_12", "tx_qualif_mais_12"]

    has_leads = (
        df_leads_por_utm is not None
        and not df_leads_por_utm.empty
        and "campaign_norm" in df_leads_por_utm.columns
    )
    out_cols = cols + cols_leads if has_leads else cols

    if df_camp.empty:
        return pd.DataFrame(columns=out_cols)

    df = df_camp.copy()
    df["objetivo"] = (df["objetivo"]
                      .fillna("Não informado")
                      .replace("", "Não informado"))

    agg = (df.groupby(["campaign_id", "campaign_name", "canal", "objetivo"],
                      as_index=False, dropna=False)
             .agg(investimento=("investimento", "sum"),
                  impressoes=("impressoes", "sum"),
                  cliques=("cliques", "sum"),
                  alcance=("alcance", "sum")))
    agg = agg[agg["investimento"] > 0].copy()
    if agg.empty:
        return pd.DataFrame(columns=out_cols)

    agg["ctr"] = agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )
    agg["cpc"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["cliques"]), axis=1
    )

    if has_leads:
        # Match LOWER+BTRIM(campaign_name) ↔ campaign_norm (já normalizado na SQL)
        agg["_campaign_norm"] = (
            agg["campaign_name"].fillna("").astype(str).str.strip().str.lower()
        )
        leads_df = df_leads_por_utm[
            ["campaign_norm", "leads_totais", "leads_qualificados",
             "leads_mais_12", "leads_menos_12"]
        ].rename(columns={"campaign_norm": "_campaign_norm",
                          "leads_totais":  "leads"})
        agg = agg.merge(leads_df, on="_campaign_norm", how="left")
        for c in ("leads", "leads_qualificados",
                  "leads_mais_12", "leads_menos_12"):
            agg[c] = agg[c].fillna(0).astype("int64")

        # Ratios — _safe_div retorna 0 quando denominador zero.
        agg["cpl"] = agg.apply(
            lambda r: _safe_div(r["investimento"], r["leads"]), axis=1
        )
        agg["cpl_mais_12"] = agg.apply(
            lambda r: _safe_div(r["investimento"], r["leads_mais_12"]), axis=1
        )
        agg["tx_qualif_mais_12"] = agg.apply(
            lambda r: _safe_div(r["leads_mais_12"], r["leads"]) * 100, axis=1
        )
        agg = agg.drop(columns=["_campaign_norm"])

    return (agg[out_cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


def campanhas_tabela_total_row(ativas: pd.DataFrame) -> pd.DataFrame:
    """Constrói a row "Total" pra anexar ao final de `Campanhas ativas`.

    Regras (recalculadas no agregado, NÃO média de taxas):
      CTR             = SUM(cliques) / SUM(impressoes) * 100
      CPC             = SUM(invest)  / SUM(cliques)
      CPL             = SUM(invest)  / SUM(leads)
      CPL +12         = SUM(invest)  / SUM(+12)
      Tx Qualif +12   = SUM(+12)     / SUM(leads) * 100

    Soma dedup por `campaign_name` para os campos de leads. Quando o mesmo
    `campaign_name` aparece em mais de uma row (porque tem múltiplos
    `campaign_id` na plataforma — caveat documentado na caption), a SQL
    repete o total de leads em cada row. Se somasse direto, o total ficaria
    inflado (dupla contagem). Investimento / impressões / cliques / alcance
    são por `campaign_id`, então somam direto.

    Retorna DataFrame com 1 linha e as MESMAS colunas de `ativas`. Quando
    `ativas` está vazia, devolve 0 rows."""
    if ativas is None or ativas.empty:
        return ativas.iloc[0:0] if ativas is not None else pd.DataFrame()

    out_cols = list(ativas.columns)

    # Soma direta (campos por campaign_id — sem risco de duplicação)
    invest = float(ativas["investimento"].sum()) if "investimento" in ativas else 0.0
    imp    = float(ativas["impressoes"].sum())   if "impressoes"   in ativas else 0.0
    clk    = float(ativas["cliques"].sum())      if "cliques"      in ativas else 0.0
    alc    = float(ativas["alcance"].sum())      if "alcance"      in ativas else 0.0

    # Dedup por campaign_name antes de somar leads (evita dupla contagem
    # quando 1 campaign_name tem múltiplos campaign_id).
    dedup = (ativas.drop_duplicates(subset=["campaign_name"])
             if "campaign_name" in ativas.columns else ativas)

    def _sum(col: str) -> float:
        return float(dedup[col].sum()) if col in dedup.columns else 0.0

    leads        = _sum("leads")
    qualif       = _sum("leads_qualificados")
    mais_12      = _sum("leads_mais_12")
    menos_12     = _sum("leads_menos_12")

    row = {c: None for c in out_cols}
    if "campaign_name" in row: row["campaign_name"] = "Total"
    if "canal"         in row: row["canal"]         = "—"
    if "objetivo"      in row: row["objetivo"]      = "—"
    if "investimento"  in row: row["investimento"]  = invest
    if "impressoes"    in row: row["impressoes"]    = int(imp)
    if "cliques"       in row: row["cliques"]       = int(clk)
    if "alcance"       in row: row["alcance"]       = int(alc)
    if "ctr"           in row: row["ctr"]           = _safe_div(clk, imp) * 100
    if "cpc"           in row: row["cpc"]           = _safe_div(invest, clk)
    if "leads"              in row: row["leads"]              = int(leads)
    if "leads_qualificados" in row: row["leads_qualificados"] = int(qualif)
    if "leads_mais_12"      in row: row["leads_mais_12"]      = int(mais_12)
    if "leads_menos_12"     in row: row["leads_menos_12"]     = int(menos_12)
    if "cpl"                in row: row["cpl"]                = _safe_div(invest, leads)
    if "cpl_mais_12"        in row: row["cpl_mais_12"]        = _safe_div(invest, mais_12)
    if "tx_qualif_mais_12"  in row: row["tx_qualif_mais_12"]  = _safe_div(mais_12, leads) * 100

    return pd.DataFrame([row], columns=out_cols)


# ---------------------------------------------------------------------------
# Growth — visão consolidada "do investimento à venda" (V1)
# Sem filtro de canal: invest/leads vêm de bi.vw_mkt_overview agregado por
# data_ref; agendamentos/comparecimentos/no_shows/vendas/receita vêm de
# odam.mart_ad_funnel_daily agregado por data_ref (cobertura primária Meta).
# ---------------------------------------------------------------------------

_GROWTH_KPIS_ZEROS = {
    # Plataforma (vw_mkt_overview)
    "investimento": 0.0, "impressoes": 0.0, "cliques": 0.0,
    "leads": 0.0, "leads_mais_12": 0.0, "leads_menos_12": 0.0,
    # Resultado (mart agregada)
    "agendamentos": 0.0, "comparecimentos": 0.0, "no_shows": 0.0,
    "vendas": 0.0, "valor_receita": 0.0,
    # Derivadas
    "cpl": 0.0, "cpl_mais_12": 0.0, "cac": 0.0, "roas": 0.0,
}


def growth_kpis(df_overview: pd.DataFrame,
                df_growth_mart: pd.DataFrame | None = None) -> dict:
    """KPIs do período para a página Growth.

    `df_overview` (de `bi.vw_mkt_overview`): investimento/impressões/cliques/
    leads/leads_qualif_mais_12/leads_qualif_menos_12 — somados sobre o
    período (todos canais). Fonte oficial de invest e leads totais.

    `df_growth_mart` (de `mkt_growth_daily.sql` — `odam.mart_ad_funnel_daily`
    agregada por data_ref): agendamentos/comparecimentos/no_shows/vendas/
    receita — atribuição via mart (cobertura primária Meta).

    Derivadas usam **invest oficial** (overview) sobre numerador atribuído
    (mart) — denominador zero → 0.0 (mantém esquema do dict; UI decide
    formatador). CAC/ROAS: se mart vier vazia, ficam 0.0."""
    out = dict(_GROWTH_KPIS_ZEROS)

    if df_overview is None or df_overview.empty:
        return out

    invest = float(df_overview["investimento"].sum())
    imp = float(df_overview["impressoes"].sum()) if "impressoes" in df_overview.columns else 0.0
    clk = float(df_overview["cliques"].sum()) if "cliques" in df_overview.columns else 0.0
    leads = float(df_overview["leads"].sum())
    q_mais = (float(df_overview["leads_qualif_mais_12"].sum())
              if "leads_qualif_mais_12" in df_overview.columns else 0.0)
    q_menos = (float(df_overview["leads_qualif_menos_12"].sum())
               if "leads_qualif_menos_12" in df_overview.columns else 0.0)

    out.update({
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "leads": leads,
        "leads_mais_12": q_mais,
        "leads_menos_12": q_menos,
        "cpl": _safe_div(invest, leads),
        "cpl_mais_12": _safe_div(invest, q_mais),
    })

    if df_growth_mart is not None and not df_growth_mart.empty:
        agend = float(df_growth_mart["agendamentos"].sum())
        comp = float(df_growth_mart["comparecimentos"].sum())
        no_shows = float(df_growth_mart["no_shows"].sum())
        vendas = float(df_growth_mart["vendas"].sum())
        receita = float(df_growth_mart["valor_receita"].sum())
        out.update({
            "agendamentos": agend,
            "comparecimentos": comp,
            "no_shows": no_shows,
            "vendas": vendas,
            "valor_receita": receita,
            "cac": _safe_div(invest, vendas),
            "roas": _safe_div(receita, invest),
        })

    return out


def growth_funil_etapas(k: dict) -> tuple[list[str], list[float]]:
    """Funil 7 etapas adaptado: Impressões → Cliques → Leads → Leads +12 →
    Agendamentos → Comparecimentos → Vendas. Imp/Cliques são paid only
    (overview); Leads em diante somam todos os canais (até Leads +12) e
    a partir de Agendamentos vêm da mart (cobertura primária Meta) — caption
    da UI explica o caveat ao usuário."""
    labels = ["Impressões", "Cliques", "Leads", "Leads +12",
              "Agendamentos", "Comparecimentos", "Vendas"]
    values = [
        float(k.get("impressoes", 0) or 0),
        float(k.get("cliques", 0) or 0),
        float(k.get("leads", 0) or 0),
        float(k.get("leads_mais_12", 0) or 0),
        float(k.get("agendamentos", 0) or 0),
        float(k.get("comparecimentos", 0) or 0),
        float(k.get("vendas", 0) or 0),
    ]
    return labels, values


def growth_diario_overview(df_overview: pd.DataFrame,
                           ma_window: int = 7) -> pd.DataFrame:
    """Série diária consolidada (todos canais): invest, leads, leads_ma7.
    Usada na seção 'Tendência diária'."""
    cols = ["data_ref", "investimento", "leads", "leads_ma"]
    if df_overview is None or df_overview.empty:
        return pd.DataFrame(columns=cols)
    agg = (df_overview.groupby("data_ref", as_index=False)
                      .agg(investimento=("investimento", "sum"),
                           leads=("leads", "sum"))
                      .sort_values("data_ref")
                      .reset_index(drop=True))
    agg["leads_ma"] = (agg["leads"]
                       .rolling(window=ma_window, min_periods=1)
                       .mean())
    return agg[cols]


def growth_eficiencia_diaria(df_roas: pd.DataFrame) -> pd.DataFrame:
    """Série diária consolidada (todos canais): cpl, cac, roas — recalculados
    a partir dos numeradores/denominadores do `mv_mkt_roas` agrupados por
    data_ref. NÃO faz média das taxas diárias por canal (isso introduziria
    viés de canal), mas re-calcula sobre os agregados — `cpl = SUM(invest) /
    SUM(leads)` etc."""
    cols = ["data_ref", "investimento", "leads", "vendas", "valor_receita",
            "cpl", "cac", "roas"]
    if df_roas is None or df_roas.empty:
        return pd.DataFrame(columns=cols)
    agg = (df_roas.groupby("data_ref", as_index=False)
                  .agg(investimento=("investimento", "sum"),
                       leads=("leads", "sum"),
                       vendas=("vendas", "sum"),
                       valor_receita=("valor_receita", "sum"))
                  .sort_values("data_ref")
                  .reset_index(drop=True))
    agg["cpl"] = agg.apply(lambda r: _safe_div(r["investimento"], r["leads"]),
                           axis=1)
    agg["cac"] = agg.apply(lambda r: _safe_div(r["investimento"], r["vendas"]),
                           axis=1)
    agg["roas"] = agg.apply(
        lambda r: _safe_div(r["valor_receita"], r["investimento"]), axis=1
    )
    return agg[cols]


def growth_scatter_leads_agend(df_overview: pd.DataFrame,
                               df_growth_mart: pd.DataFrame
                               ) -> tuple[pd.DataFrame, float | None, int]:
    """Pareia leads diários (overview) com agendamentos diários (mart)
    pelo `data_ref`. Devolve (df_xy, pearson_r, n_pares).

    pearson_r = None quando há menos de 3 pares ou variância zero em
    qualquer eixo (não dá pra calcular correlação significativa).
    """
    if (df_overview is None or df_overview.empty
            or df_growth_mart is None or df_growth_mart.empty):
        return pd.DataFrame(columns=["data_ref", "leads", "agendamentos"]), None, 0

    leads_diario = (df_overview.groupby("data_ref", as_index=False)
                              .agg(leads=("leads", "sum")))
    # df_growth_mart pode vir do `mkt_growth_daily_by_canal.sql` com várias
    # linhas por data_ref (uma por canal). Re-agrupa por data_ref antes
    # do merge — robusto pra ambas as formas (com/sem canal).
    agend_diario = (df_growth_mart.groupby("data_ref", as_index=False)
                                  .agg(agendamentos=("agendamentos", "sum")))

    df_xy = (leads_diario.merge(agend_diario, on="data_ref", how="inner")
                         .sort_values("data_ref")
                         .reset_index(drop=True))
    n = len(df_xy)
    if n < 3 or df_xy["leads"].std() == 0 or df_xy["agendamentos"].std() == 0:
        return df_xy, None, n

    r = float(df_xy["leads"].corr(df_xy["agendamentos"]))
    return df_xy, r, n


# ---------------------------------------------------------------------------
# Filtro de canal na Growth — Opção A.
# ---------------------------------------------------------------------------
# `bi.vw_mkt_overview` e `bi.mv_mkt_roas` têm `canal` nativo, então ctx.refilter
# resolve. A `odam.mart_ad_funnel_daily` NÃO tem canal direto: derivamos via
# JOIN com `bi.vw_mkt_campanhas` por `campaign_id` (query
# `mkt_growth_daily_by_canal.sql`). Linhas da mart com `campaign_id` NULL
# vêm com `canal=NaN` e ficam fora do filtro, entrando apenas no agregado
# "todos canais".
#
# IMPACTO REAL no período-base (abril/2026): das 206 agendamentos da mart,
# só ~10% têm campaign_id rastreável. A caption da view exibe esse % em
# tempo real para o usuário entender que filtrar canal ENCURTA o fundo do
# funil dramaticamente.

def growth_mart_filtrar(df_by_canal: pd.DataFrame,
                        canais_selecionados: tuple[str, ...] | list[str] | None,
                        todos_canais: bool) -> pd.DataFrame:
    """Re-agrega `df_by_canal` (grão data_ref × canal) para 1 linha por
    data_ref, aplicando filtro de canal:

    - `todos_canais=True` → soma tudo (inclusive linhas com canal=NaN da
      mart sem campaign_id).
    - `todos_canais=False` → filtra `canal IN canais_selecionados`. Linhas
      com canal=NaN ficam de fora.

    Retorna DataFrame no MESMO esquema do `mkt_growth_daily.sql`
    (data_ref + colunas de mart sem coluna `canal`)."""
    cols_metric = ["leads_mais_12", "leads_menos_12", "leads_nao_atua",
                   "agendamentos", "comparecimentos", "no_shows",
                   "deals", "deals_ganhos", "vendas",
                   "valor_venda", "valor_receita"]
    out_cols = ["data_ref"] + cols_metric

    if df_by_canal is None or df_by_canal.empty:
        return pd.DataFrame(columns=out_cols)

    if todos_canais:
        df = df_by_canal
    else:
        if not canais_selecionados:
            return pd.DataFrame(columns=out_cols)
        df = df_by_canal[df_by_canal["canal"].isin(list(canais_selecionados))]
        if df.empty:
            return pd.DataFrame(columns=out_cols)

    agg_kwargs = {c: (c, "sum") for c in cols_metric if c in df.columns}
    return (df.groupby("data_ref", as_index=False)
              .agg(**agg_kwargs)
              [out_cols]
              .sort_values("data_ref")
              .reset_index(drop=True))


def growth_cobertura_canal(df_by_canal: pd.DataFrame) -> dict:
    """Diagnóstico da cobertura do filtro de canal: que fração dos
    agendamentos/vendas/receita da mart no período tem `canal` rastreável
    (campaign_id casa com vw_mkt_campanhas) vs `canal=NaN` (campaign_id
    NULL ou não-encontrado).

    Devolve dict com:
      total_*  · com_canal_*  · sem_canal_*  · pct_com_canal_*
    para cada uma de agend, vendas, receita.
    """
    zeros = {
        "total_agend": 0, "agend_com_canal": 0, "agend_sem_canal": 0,
        "pct_com_canal_agend": 0.0,
        "total_vendas": 0, "vendas_com_canal": 0, "vendas_sem_canal": 0,
        "pct_com_canal_vendas": 0.0,
        "total_receita": 0.0, "receita_com_canal": 0.0,
        "receita_sem_canal": 0.0, "pct_com_canal_receita": 0.0,
    }
    if df_by_canal is None or df_by_canal.empty:
        return zeros

    com = df_by_canal["canal"].notna()
    sem = ~com

    def _sum(mask, col):
        if col not in df_by_canal.columns:
            return 0
        v = df_by_canal.loc[mask, col].sum()
        return float(v) if v == v else 0.0

    a_total = _sum(slice(None), "agendamentos")
    a_com = _sum(com, "agendamentos")
    v_total = _sum(slice(None), "vendas")
    v_com = _sum(com, "vendas")
    r_total = _sum(slice(None), "valor_receita")
    r_com = _sum(com, "valor_receita")

    return {
        "total_agend": a_total,
        "agend_com_canal": a_com,
        "agend_sem_canal": a_total - a_com,
        "pct_com_canal_agend": _safe_div(a_com, a_total) * 100,
        "total_vendas": v_total,
        "vendas_com_canal": v_com,
        "vendas_sem_canal": v_total - v_com,
        "pct_com_canal_vendas": _safe_div(v_com, v_total) * 100,
        "total_receita": r_total,
        "receita_com_canal": r_com,
        "receita_sem_canal": r_total - r_com,
        "pct_com_canal_receita": _safe_div(r_com, r_total) * 100,
    }
