"""Transforms e cálculos de KPI a partir das views reais (schema bi).

Toda função aqui recebe DataFrames já carregados pelos repositories e retorna
DataFrames/dicts prontos para a UI. Nenhum SQL aqui."""
from __future__ import annotations

import pandas as pd

from .team_classification import (
    classify_closer,
    classify_sdr,
    is_known_closer,
    is_known_sdr,
)

# ---------------------------------------------------------------------------
# Utilitários genéricos
# ---------------------------------------------------------------------------

def describe_df(df: pd.DataFrame) -> dict:
    return {
        "rows": len(df),
        "cols": df.shape[1],
        "columns": list(df.columns),
        "numeric_columns": df.select_dtypes(include="number").columns.tolist(),
        "date_columns": df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist(),
    }


def _safe_div(num: float, den: float) -> float:
    if den in (0, None) or pd.isna(den):
        return 0.0
    return float(num) / float(den)


def delta_pct(curr: float, prev: float) -> float | None:
    """Delta percentual com sentinela None quando não há base válida."""
    if prev in (0, None) or pd.isna(prev):
        return None
    return (float(curr) - float(prev)) / float(prev) * 100


# ---------------------------------------------------------------------------
# Meta semanal (regra Looker)
# ---------------------------------------------------------------------------

META_SEMANAL = 625_000.0  # R$ por semana

def meta_periodo(df_exec: pd.DataFrame) -> float:
    """Meta proporcional ao número de dias distintos na view (regra Looker:
    COUNT_DISTINCT(data_ref) * 625000/7)."""
    if df_exec.empty or "data_ref" not in df_exec.columns:
        return 0.0
    dias = int(pd.to_datetime(df_exec["data_ref"]).dt.date.nunique())
    return dias * (META_SEMANAL / 7.0)


# ---------------------------------------------------------------------------
# vw_dashboard_comercial_executivas_rw
# ---------------------------------------------------------------------------

_EXEC_SUM = [
    "oportunidades", "agendamentos", "comparecimentos", "vendas",
    "montante", "receita", "perdidos", "cancelados",
    "novos", "ascensoes", "renovacoes", "indicacoes",
    "lead_in_consultoria_gratuita",
]


def executivas_kpis(df: pd.DataFrame) -> dict:
    """Totais e taxas recalculadas a partir dos absolutos (não média das %).

    Fórmulas (validadas com a operação):
      pct_agendamento    = agendamentos / oportunidades
      pct_comparecimento = comparecimentos / agendamentos
      pct_conversao      = vendas / agendamentos     (NÃO vendas/comparecimentos)
      pct_vendas         = vendas / comparecimentos  (taxa de fechamento "show-to-close")
      pct_venda_lead     = vendas / oportunidades    (atalho do funil completo)
      ticket_medio       = montante / vendas
      pct_recebimento    = receita / montante
    """
    if df.empty:
        return {k: 0 for k in (
            "oportunidades", "agendamentos", "comparecimentos", "vendas",
            "montante", "receita", "perdidos", "cancelados",
            "novos", "ascensoes", "renovacoes", "indicacoes",
            "pct_agendamento", "pct_comparecimento", "pct_conversao",
            "pct_vendas", "pct_venda_lead", "ticket_medio", "pct_recebimento",
        )}

    totais = {c: float(df[c].sum()) for c in _EXEC_SUM if c in df.columns}

    opor = totais.get("oportunidades", 0)
    ag = totais.get("agendamentos", 0)
    comp = totais.get("comparecimentos", 0)
    vend = totais.get("vendas", 0)
    montante = totais.get("montante", 0)
    receita = totais.get("receita", 0)

    return {
        **totais,
        "pct_agendamento":    _safe_div(ag, opor) * 100,
        "pct_comparecimento": _safe_div(comp, ag) * 100,
        "pct_conversao":      _safe_div(vend, ag) * 100,    # vendas / agendamentos
        "pct_vendas":         _safe_div(vend, comp) * 100,  # vendas / comparecimentos
        "pct_venda_lead":     _safe_div(vend, opor) * 100,  # vendas / oportunidades (funil completo)
        "ticket_medio":       _safe_div(montante, vend),
        "pct_recebimento":    _safe_div(receita, montante) * 100,
    }


def executivas_por_dia(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in _EXEC_SUM if c in df.columns]
    return df.groupby("data_ref", as_index=False)[cols].sum().sort_values("data_ref")


def executivas_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """Ranking por executiva: absolutos + taxas recalculadas."""
    if df.empty:
        return df
    cols = [c for c in _EXEC_SUM if c in df.columns]
    agg = df.groupby("executiva", as_index=False)[cols].sum()
    agg["pct_agendamento"] = agg.apply(
        lambda r: _safe_div(r["agendamentos"], r["oportunidades"]) * 100, axis=1
    )
    agg["pct_comparecimento"] = agg.apply(
        lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100, axis=1
    )
    agg["pct_conversao"] = agg.apply(
        lambda r: _safe_div(r["vendas"], r["agendamentos"]) * 100, axis=1
    )
    agg["pct_vendas"] = agg.apply(
        lambda r: _safe_div(r["vendas"], r["comparecimentos"]) * 100, axis=1
    )
    agg["ticket_medio"] = agg.apply(
        lambda r: _safe_div(r["montante"], r["vendas"]), axis=1
    )
    return agg.sort_values("receita", ascending=False)


def executivas_por_time(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "time_vendas" not in df.columns:
        return pd.DataFrame()
    cols = [c for c in _EXEC_SUM if c in df.columns]
    agg = df.groupby("time_vendas", as_index=False)[cols].sum()
    agg["pct_conversao"] = agg.apply(
        lambda r: _safe_div(r["vendas"], r["agendamentos"]) * 100, axis=1
    )
    agg["pct_vendas"] = agg.apply(
        lambda r: _safe_div(r["vendas"], r["comparecimentos"]) * 100, axis=1
    )
    agg["ticket_medio"] = agg.apply(
        lambda r: _safe_div(r["montante"], r["vendas"]), axis=1
    )
    return agg.sort_values("receita", ascending=False)


def executivas_mix_venda(df: pd.DataFrame) -> pd.DataFrame:
    """Distribuição entre novos / ascensões / renovações / indicações."""
    if df.empty:
        return pd.DataFrame()
    cols = [c for c in ("novos", "ascensoes", "renovacoes", "indicacoes") if c in df.columns]
    totals = df[cols].sum().reset_index()
    totals.columns = ["tipo", "quantidade"]
    total_geral = totals["quantidade"].sum()
    totals["pct"] = totals["quantidade"].apply(lambda q: _safe_div(q, total_geral) * 100)
    return totals


# ---------------------------------------------------------------------------
# vw_compatibilidade_sdr_closer
# ---------------------------------------------------------------------------

def annotate_and_clean_sdr_closer(df: pd.DataFrame) -> pd.DataFrame:
    """Sobrescreve `tipo_sdr` e `time_closer` com a classificação canônica
    (`src/team_classification.py`) e remove linhas onde:
      - o valor de `sdr` é um Closer conhecido
      - o valor de `closer` é um SDR conhecido
    Esses casos são misclassifications cruzadas — não devem aparecer na matriz.
    Pessoas em `Sem Time Definido` permanecem (podem ser qualquer um dos dois)."""
    if df.empty:
        return df
    df = df.copy()
    df["tipo_sdr"] = df["sdr"].apply(classify_sdr)
    df["time_closer"] = df["closer"].apply(classify_closer)
    drop = df["sdr"].apply(is_known_closer) | df["closer"].apply(is_known_sdr)
    return df.loc[~drop].reset_index(drop=True)


def sdr_closer_totais(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"leads": 0, "ganhos": 0, "taxa_conversao": 0,
                "receita_total": 0, "ticket_medio": 0}
    leads = float(df["leads_recebidos"].sum())
    ganhos = float(df["ganhos"].sum())
    receita = float(df["receita_total"].sum())
    montante = float(df["montante_total"].sum()) if "montante_total" in df.columns else 0
    return {
        "leads": leads,
        "ganhos": ganhos,
        "taxa_conversao": _safe_div(ganhos, leads) * 100,
        "receita_total": receita,
        "montante_total": montante,
        "ticket_medio": _safe_div(montante, ganhos),
    }


def sdr_closer_matriz(df: pd.DataFrame, metrica: str = "ganhos") -> pd.DataFrame:
    """Matriz SDR × Closer — uma célula por par, valor configurável."""
    if df.empty or metrica not in df.columns:
        return pd.DataFrame()
    pivot = df.pivot_table(
        index="sdr", columns="closer", values=metrica, aggfunc="sum", fill_value=0,
    )
    return pivot


def sdr_ranking(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    agg = df.groupby("sdr", as_index=False).agg(
        leads=("leads_recebidos", "sum"),
        ganhos=("ganhos", "sum"),
        receita=("receita_total", "sum"),
        montante=("montante_total", "sum"),
    )
    agg["taxa_conversao"] = agg.apply(
        lambda r: _safe_div(r["ganhos"], r["leads"]) * 100, axis=1
    )
    agg["ticket_medio"] = agg.apply(
        lambda r: _safe_div(r["montante"], r["ganhos"]), axis=1
    )
    return agg.sort_values("receita", ascending=False)


def closer_ranking(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    agg = df.groupby("closer", as_index=False).agg(
        leads=("leads_recebidos", "sum"),
        ganhos=("ganhos", "sum"),
        receita=("receita_total", "sum"),
        montante=("montante_total", "sum"),
    )
    agg["taxa_conversao"] = agg.apply(
        lambda r: _safe_div(r["ganhos"], r["leads"]) * 100, axis=1
    )
    agg["ticket_medio"] = agg.apply(
        lambda r: _safe_div(r["montante"], r["ganhos"]), axis=1
    )
    return agg.sort_values("receita", ascending=False)


# ---------------------------------------------------------------------------
# vw_investimento_diario + executivas → ROAS / CAC
# ---------------------------------------------------------------------------

def investimento_totais(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"total": 0, "media_dia": 0, "dias": 0}
    return {
        "total": float(df["investimento_total"].sum()),
        "media_dia": float(df["investimento_total"].mean()),
        "dias": int(df["data_ref"].nunique()),
    }


def roas_diario(df_invest: pd.DataFrame, df_exec: pd.DataFrame) -> pd.DataFrame:
    """Junta investimento diário com receita/vendas diárias por data_ref."""
    if df_invest.empty:
        return pd.DataFrame()
    exec_diario = executivas_por_dia(df_exec)
    merged = df_invest.merge(exec_diario, on="data_ref", how="left").fillna(0)
    merged["roas"] = merged.apply(
        lambda r: _safe_div(r.get("receita", 0), r["investimento_total"]), axis=1
    )
    merged["cac"] = merged.apply(
        lambda r: _safe_div(r["investimento_total"], r.get("vendas", 0)), axis=1
    )
    return merged.sort_values("data_ref")


def roas_resumo(df_invest: pd.DataFrame, df_exec: pd.DataFrame) -> dict:
    totais_inv = investimento_totais(df_invest)
    totais_exec = executivas_kpis(df_exec)
    receita = totais_exec.get("receita", 0)
    vendas = totais_exec.get("vendas", 0)
    invest = totais_inv.get("total", 0)
    return {
        "investimento": invest,
        "receita": receita,
        "vendas": vendas,
        "roas": _safe_div(receita, invest),
        "cac": _safe_div(invest, vendas),
        "dias": totais_inv.get("dias", 0),
    }


# ---------------------------------------------------------------------------
# Visão Geral (home) — espelha os campos calculados do Looker atual
# ---------------------------------------------------------------------------

def visao_geral_kpis(df_exec: pd.DataFrame, df_inv: pd.DataFrame) -> dict:
    """Calcula os KPIs da home aplicando exatamente as fórmulas do Looker:

    - meta                = COUNT_DISTINCT(data_ref) * (625000/7)
    - ticket_medio        = SUM(montante) / SUM(vendas)
    - conversao_global    = SUM(vendas) / (SUM(vendas)+SUM(perdidos)+SUM(cancelados))
    - cpa                 = SUM(investimento_total) / SUM(vendas)
    - pct_recebimento     = SUM(receita) / SUM(montante)
    - pct_atingimento     = SUM(receita) / meta
    - media_movel_diaria  = SUM(receita) / COUNT_DISTINCT(data_ref)
    """
    if df_exec.empty:
        return {
            "receita": 0, "montante": 0, "vendas": 0,
            "oportunidades": 0, "leads_totais": 0,
            "novos": 0, "ascensoes": 0, "renovacoes": 0, "indicacoes": 0,
            "perdidos": 0, "cancelados": 0,
            "meta": 0, "pct_atingimento": 0, "meta_status": "sem_dados",
            "pct_recebimento": 0, "ticket_medio": 0,
            "conversao_global": 0, "cpa": 0, "media_movel_diaria": 0,
            "investimento": 0, "dias": 0,
        }

    receita = float(df_exec["receita"].sum())
    montante = float(df_exec["montante"].sum())
    vendas = float(df_exec["vendas"].sum())
    perdidos = float(df_exec["perdidos"].sum()) if "perdidos" in df_exec.columns else 0
    cancelados = float(df_exec["cancelados"].sum()) if "cancelados" in df_exec.columns else 0

    oport = float(df_exec["oportunidades"].sum()) if "oportunidades" in df_exec.columns else 0
    leads = oport  # mapeamento: leads totais == oportunidades na view

    novos = float(df_exec["novos"].sum()) if "novos" in df_exec.columns else 0
    ascensoes = float(df_exec["ascensoes"].sum()) if "ascensoes" in df_exec.columns else 0
    renovacoes = float(df_exec["renovacoes"].sum()) if "renovacoes" in df_exec.columns else 0
    indicacoes = float(df_exec["indicacoes"].sum()) if "indicacoes" in df_exec.columns else 0

    investimento = float(df_inv["investimento_total"].sum()) if not df_inv.empty else 0.0

    meta = meta_periodo(df_exec)
    pct_ating = _safe_div(receita, meta) * 100
    dias = int(pd.to_datetime(df_exec["data_ref"]).dt.date.nunique())

    if meta == 0:
        status = "sem_meta"
    elif receita >= meta:
        status = "acima"
    elif receita >= 0.8 * meta:
        status = "proximo"
    else:
        status = "abaixo"

    return {
        # totais absolutos
        "receita": receita,
        "montante": montante,
        "vendas": vendas,
        "oportunidades": oport,
        "leads_totais": leads,
        "novos": novos,
        "ascensoes": ascensoes,
        "renovacoes": renovacoes,
        "indicacoes": indicacoes,
        "perdidos": perdidos,
        "cancelados": cancelados,
        "investimento": investimento,
        "dias": dias,
        # campos calculados (fórmulas Looker)
        "meta": meta,
        "pct_atingimento": pct_ating,
        "meta_status": status,
        "pct_recebimento": _safe_div(receita, montante) * 100,
        "ticket_medio": _safe_div(montante, vendas),
        "conversao_global": _safe_div(vendas, vendas + perdidos + cancelados) * 100,
        "cpa": _safe_div(investimento, vendas),
        "media_movel_diaria": _safe_div(receita, dias),
    }


def leads_totais_lp(df_leads: pd.DataFrame) -> float:
    """Total de leads únicos vindos de LP — fonte: bi.vw_funil_leads_diario."""
    if df_leads.empty or "leads_lp_unicos" not in df_leads.columns:
        return 0.0
    return float(df_leads["leads_lp_unicos"].sum())


def receita_por_mes(df_exec: pd.DataFrame) -> pd.DataFrame:
    """Série mensal: receita, meta (regra Looker) e variação mês-a-mês."""
    if df_exec.empty:
        return pd.DataFrame(columns=["mes", "receita", "meta", "dias",
                                      "pct_meta", "var_mom_pct"])
    base = df_exec.copy()
    base["data_ref"] = pd.to_datetime(base["data_ref"])
    base["mes"] = base["data_ref"].dt.to_period("M").dt.to_timestamp()

    agg = base.groupby("mes", as_index=False).agg(
        receita=("receita", "sum"),
        dias=("data_ref", lambda s: s.dt.date.nunique()),
    )
    agg["meta"] = agg["dias"] * (META_SEMANAL / 7.0)
    agg["pct_meta"] = agg.apply(
        lambda r: _safe_div(r["receita"], r["meta"]) * 100, axis=1
    )
    agg["var_mom_pct"] = (agg["receita"].pct_change() * 100).round(1)
    return agg.sort_values("mes")
