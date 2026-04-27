"""Transforms / KPIs do dashboard de Marketing.

Recebe DataFrames lidos via `marketing_queries.py` e devolve dicts/DataFrames
prontos para a UI. Sem SQL aqui."""
from __future__ import annotations

import pandas as pd

from .transforms import _safe_div  # reutiliza helper de vendas


CANAIS_PADRAO = ("Meta", "Google", "Pinterest", "Organico")

_OVERVIEW_ZEROS = {
    "investimento": 0, "impressoes": 0, "cliques": 0, "alcance": 0,
    "leads": 0, "leads_qualificados": 0,
    "leads_qualif_mais_12": 0, "leads_qualif_menos_12": 0,
    "cpl": 0, "cpl_qualificado": 0,
    "ctr": 0, "taxa_qualif": 0, "cpc": 0,
    "vendas": 0, "valor_venda": 0, "valor_receita": 0,
    "cac": 0, "roas": 0,
}


def overview_kpis(df: pd.DataFrame, df_roas: pd.DataFrame | None = None) -> dict:
    """KPIs consolidados para o período já filtrado.

    Fórmulas (recalculadas no agregado, não média de taxas diárias):
      cpl              = invest / leads
      cpl_qualificado  = invest / leads_qualificados
      ctr              = cliques / impressoes * 100
      cpc              = invest / cliques
      taxa_qualif      = leads_qualificados / leads * 100
      cac              = invest / vendas               (se df_roas)
      roas             = valor_receita / invest        (se df_roas)
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

    out = {
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "alcance": alc,
        "leads": leads,
        "leads_qualificados": qualif,
        "leads_qualif_mais_12": q_mais,
        "leads_qualif_menos_12": q_menos,
        "cpl": _safe_div(invest, leads),
        "cpl_qualificado": _safe_div(invest, qualif),
        "ctr": _safe_div(clk, imp) * 100,
        "cpc": _safe_div(invest, clk),
        "taxa_qualif": _safe_div(qualif, leads) * 100,
    }

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
    return out


def overview_por_canal(
    df: pd.DataFrame,
    df_roas: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Sumariza KPIs por canal — base da tabela de breakdown.

    Quando `df_roas` é passado, agrega `vendas`/`valor_receita` por canal
    e calcula `cac`/`roas` no agregado (não média de taxas diárias)."""
    cols = ["canal", "investimento", "impressoes", "cliques",
            "leads", "leads_qualificados",
            "cpl", "cpl_qualificado", "taxa_qualif", "ctr",
            "vendas", "cac", "roas"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    agg = df.groupby("canal", as_index=False).agg(
        investimento=("investimento", "sum"),
        impressoes=("impressoes", "sum"),
        cliques=("cliques", "sum"),
        leads=("leads", "sum"),
        leads_qualificados=("leads_qualificados", "sum"),
    )
    agg["cpl"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads"]), axis=1
    )
    agg["cpl_qualificado"] = agg.apply(
        lambda r: _safe_div(r["investimento"], r["leads_qualificados"]), axis=1
    )
    agg["taxa_qualif"] = agg.apply(
        lambda r: _safe_div(r["leads_qualificados"], r["leads"]) * 100, axis=1
    )
    agg["ctr"] = agg.apply(
        lambda r: _safe_div(r["cliques"], r["impressoes"]) * 100, axis=1
    )

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

    # Ordenação canônica: maior investimento primeiro
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
