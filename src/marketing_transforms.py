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
    "vendas": 0.0, "valor_venda": 0.0, "valor_receita": 0.0,
    "roas": 0.0, "cac": 0.0,
    "cpl": 0.0, "cpl_qualificado": 0.0,
    "ticket_medio": 0.0,
}


def roas_kpis(df: pd.DataFrame,
              df_lp_funil: pd.DataFrame | None = None,
              df_classif: pd.DataFrame | None = None) -> dict:
    """KPIs consolidados a partir de `bi.mv_mkt_roas` (já filtrada por canal/período).

    Fórmulas (recalculadas no agregado, não média de taxas diárias):
      roas           = valor_receita / investimento
      cac            = investimento / vendas
      ticket_medio   = valor_receita / vendas
      cpl            = investimento / leads
      cpl_qualificado= investimento / leads_qualificados

    Sobrescritas opcionais (mesmo padrão da Visão Geral, quando filtro = todos canais):
    - `df_lp_funil` (de `bi.vw_funil_leads_diario`): sobrescreve `leads` pelo
      SUM(leads_lp_unicos) — fonte validada para Leads totais.
    - `df_classif` (de `bi.vw_mkt_leads_classificacao`): sobrescreve
      `leads_qualificados` pelo `+12 + -12` deduplicado por janela.
    CPL e CPL qualificado são recalculados com os denominadores corrigidos."""
    if df.empty:
        return dict(_ROAS_ZEROS)

    invest = float(df["investimento"].sum())
    leads = float(df["leads"].sum())
    qualif = float(df["leads_qualificados"].sum())
    vendas = float(df["vendas"].sum())
    valor_v = float(df["valor_venda"].sum()) if "valor_venda" in df.columns else 0.0
    valor_r = float(df["valor_receita"].sum())

    out = {
        "investimento": invest,
        "leads": leads,
        "leads_qualificados": qualif,
        "vendas": vendas,
        "valor_venda": valor_v,
        "valor_receita": valor_r,
        "roas": _safe_div(valor_r, invest),
        "cac": _safe_div(invest, vendas),
        "ticket_medio": _safe_div(valor_r, vendas),
        "cpl": _safe_div(invest, leads),
        "cpl_qualificado": _safe_div(invest, qualif),
    }

    # Override leads pela fonte validada (lp_form) quando disponível
    if (df_lp_funil is not None
            and not df_lp_funil.empty
            and "leads_lp_unicos" in df_lp_funil.columns):
        leads_validado = float(df_lp_funil["leads_lp_unicos"].sum())
        out["leads"] = leads_validado
        out["cpl"] = _safe_div(invest, leads_validado)

    # Override qualif (+12+-12, ambíguos OUT) pela fonte deduplicada
    if (df_classif is not None
            and not df_classif.empty
            and "lead_mais_12" in df_classif.columns
            and "lead_menos_12" in df_classif.columns):
        q_mais = float(df_classif["lead_mais_12"].sum())
        q_menos = float(df_classif["lead_menos_12"].sum())
        qualif_v = q_mais + q_menos
        out["leads_qualificados"] = qualif_v
        out["cpl_qualificado"] = _safe_div(invest, qualif_v)

    return out


def roas_por_canal(
    df: pd.DataFrame,
    df_classif_canal: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Quebra por canal — uma linha por canal com KPIs consolidados.

    Quando `df_classif_canal` é passado, sobrescreve `leads`, `leads_qualificados`,
    `cpl` e `cpl_qualificado` pela fonte deduplicada validada
    (`bi.vw_mkt_leads_classificacao` agregada por canal). Vendas/CAC/ROAS/Receita
    continuam de `bi.mv_mkt_roas`.

    Estrutura: OUTER JOIN — preserva canais que existem só num lado.
    Mesma política de fallback V1 da Visão Geral: se `df_classif_canal` for
    None/vazio, cai para os valores INFLADOS de `mv_mkt_roas` (originados em
    `vw_mkt_overview`)."""
    cols = ["canal", "investimento", "leads", "leads_qualificados",
            "vendas", "valor_receita",
            "roas", "cac", "cpl", "cpl_qualificado"]

    has_paid = not df.empty
    has_dedup = (
        df_classif_canal is not None
        and not df_classif_canal.empty
        and {"canal", "lead_mais_12", "lead_menos_12", "leads_unicos_canal"}
            .issubset(df_classif_canal.columns)
    )

    if not has_paid and not has_dedup:
        return pd.DataFrame(columns=cols)

    # Lado paid (mv_mkt_roas) — invest/leads_overview/qualif_overview/vendas/receita
    if has_paid:
        paid = df.groupby("canal", as_index=False).agg(
            investimento=("investimento", "sum"),
            leads_overview=("leads", "sum"),
            leads_qualificados_overview=("leads_qualificados", "sum"),
            vendas=("vendas", "sum"),
            valor_receita=("valor_receita", "sum"),
        )
    else:
        paid = pd.DataFrame(columns=["canal", "investimento", "leads_overview",
                                       "leads_qualificados_overview",
                                       "vendas", "valor_receita"])

    # Lado dedup (vw_mkt_leads_classificacao com canal)
    if has_dedup:
        dedup = df_classif_canal[
            ["canal", "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
        ].copy()
    else:
        dedup = pd.DataFrame(
            columns=["canal", "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
        )

    # OUTER JOIN — preserva canais de qualquer lado
    agg = paid.merge(dedup, on="canal", how="outer")
    for c in ("investimento", "leads_overview", "leads_qualificados_overview",
              "vendas", "valor_receita",
              "leads_unicos_canal", "lead_mais_12", "lead_menos_12"):
        if c in agg.columns:
            agg[c] = agg[c].fillna(0)

    # Escolha de fonte de leads/qualif: dedup quando disponível
    if has_dedup:
        agg["leads"] = agg["leads_unicos_canal"]
        # Qualif. = +12 + -12 (ambíguos OUT por construção do dedup)
        agg["leads_qualificados"] = agg["lead_mais_12"] + agg["lead_menos_12"]
    else:
        # ⚠ FALLBACK V1: valores INFLADOS — voltar para Opção B na V2.
        agg["leads"] = agg["leads_overview"]
        agg["leads_qualificados"] = agg["leads_qualificados_overview"]

    # Métricas derivadas — usam o leads/qualif escolhido acima
    agg["roas"] = agg.apply(
        lambda r: _safe_div(r["valor_receita"], r["investimento"]), axis=1
    )
    agg["cac"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["vendas"]), axis=1
    )
    agg["cpl"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads"]), axis=1
    )
    agg["cpl_qualificado"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_qualificados"]), axis=1
    )

    # Limpa helpers
    helper_cols = ["leads_overview", "leads_qualificados_overview",
                   "leads_unicos_canal", "lead_mais_12", "lead_menos_12"]
    agg = agg.drop(columns=[c for c in helper_cols if c in agg.columns])

    return (agg[cols]
            .sort_values("valor_receita", ascending=False)
            .reset_index(drop=True))


def roas_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Série diária consolidada (todos os canais filtrados somados): invest,
    receita, vendas, ROAS por dia."""
    cols = ["data_ref", "investimento", "valor_receita", "vendas", "roas"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    agg = df.groupby("data_ref", as_index=False).agg(
        investimento=("investimento", "sum"),
        valor_receita=("valor_receita", "sum"),
        vendas=("vendas", "sum"),
    )
    agg["roas"] = agg.apply(
        lambda r: _safe_div(r["valor_receita"], r["investimento"]), axis=1
    )
    return agg[cols].sort_values("data_ref").reset_index(drop=True)


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
        agendamentos, vendas, valor_receita
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
                  df_resultados: pd.DataFrame | None = None) -> dict:
    """KPIs de UMA campanha específica.

    Plataforma vem de `df_camp` (vw_mkt_campanhas, fonte oficial de invest/
    imp/cliques/alcance). Resultado atribuído vem de `df_resultados` (de
    `odam.mart_ad_funnel_daily` agregado por campaign_id).

    Quando a campanha não tem linha em `df_resultados`:
    - `tem_resultados=False`
    - métricas de resultado e derivadas ficam como `None` (formatador
      mostra "—")

    Quando tem linha mas denominador é zero (ex.: leads=0 → CPL):
    - métrica de resultado mostra `0` (zero real, dado existe)
    - derivada com denominador zero vira `None` (formatador "—" — não
      faz sentido R$ 0,00 quando não há leads pra calcular CPL)

    Derivadas (CPL/CPL+12/CAC/ROAS) usam INVEST OFICIAL (df_camp) sobre
    contagens da mart — NUNCA o `valor_venda` ou spend da mart como
    investimento."""
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

    # ---- Resultado (mart) — merge interno por campaign_id ---------------
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

            # Derivadas — denominador zero vira None ("—" no formatador)
            out["cpl"] = (invest / leads_total) if leads_total > 0 else None
            out["cpl_mais_12"] = (invest / leads_mais_12) if leads_mais_12 > 0 else None
            out["cac"] = (invest / vendas) if vendas > 0 else None
            out["roas"] = (valor_r / invest) if invest > 0 else None

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


def campanhas_tabela_ativas(df_camp: pd.DataFrame) -> pd.DataFrame:
    """Tabela de campanhas com `investimento > 0` no período, agregadas por
    `(campaign_id, campaign_name, canal, objetivo)` e ordenadas por invest desc.
    """
    cols = ["campaign_name", "canal", "objetivo",
            "investimento", "impressoes", "cliques",
            "ctr", "cpc", "alcance"]
    if df_camp.empty:
        return pd.DataFrame(columns=cols)

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
        return pd.DataFrame(columns=cols)

    agg["ctr"] = agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )
    agg["cpc"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["cliques"]), axis=1
    )
    return (agg[cols]
            .sort_values("investimento", ascending=False)
            .reset_index(drop=True))


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
    agend_diario = df_growth_mart[["data_ref", "agendamentos"]].copy()

    df_xy = (leads_diario.merge(agend_diario, on="data_ref", how="inner")
                         .sort_values("data_ref")
                         .reset_index(drop=True))
    n = len(df_xy)
    if n < 3 or df_xy["leads"].std() == 0 or df_xy["agendamentos"].std() == 0:
        return df_xy, None, n

    r = float(df_xy["leads"].corr(df_xy["agendamentos"]))
    return df_xy, r, n
