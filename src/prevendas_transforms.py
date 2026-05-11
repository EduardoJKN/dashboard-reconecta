"""Transforms / KPIs do dashboard de Pré-vendas.

Recebe DataFrames lidos via `repositories.py` (queries
`prevendas_*.sql`) e devolve dicts/DataFrames prontos para a UI.

SDR primário vem de `zoho_activities.prevendas`. A classificação de
**tipo de SDR** (Pré-vendas / Social Seller / SDR não classificado)
reusa `team_classification.classify_sdr` — mesma fonte canônica
usada nas páginas de Vendas e na regra do SDR × Closer.
"""
from __future__ import annotations

import pandas as pd

from .team_classification import (
    SDR_UNKNOWN_LABEL,
    SEM_SDR_LABEL,
    classify_sdr,
)
from .transforms import _safe_div

# ---------------------------------------------------------------------------
# Visão Geral Pré-vendas
# ---------------------------------------------------------------------------
_OVERVIEW_ZEROS = {
    "leads": 0, "agendamentos": 0, "comparecimentos": 0,
    "vendas": 0, "vendas_novas": 0,
    "montante": 0.0, "receita": 0.0,
    "ticket_medio": 0.0, "taxa_comparecimento": 0.0,
    "taxa_lead_venda_nova": 0.0,
    "media_movel_21d": 0.0,
}


def prevendas_overview_kpis(df_diario: pd.DataFrame) -> dict:
    """KPIs consolidados a partir do `prevendas_overview_diario.sql`.

    Taxas recalculadas no agregado, NÃO média de taxas diárias:
      taxa_comparecimento  = SUM(comparec) / SUM(agendamentos) * 100
      taxa_lead_venda_nova = SUM(vendas_novas) / SUM(leads) * 100
      ticket_medio         = SUM(montante) / SUM(vendas_novas)
    A `media_movel_21d` precisa ser calculada com base em uma janela
    independente do filtro (usar `get_media_movel_vendas` quando
    fizer sentido — aqui devolve média do próprio período como fallback)."""
    out = dict(_OVERVIEW_ZEROS)
    if df_diario is None or df_diario.empty:
        return out

    out["leads"]           = int(df_diario["leads"].sum())
    out["agendamentos"]    = int(df_diario["agendamentos"].sum())
    out["comparecimentos"] = int(df_diario["comparecimentos"].sum())
    out["vendas"]          = int(df_diario["vendas"].sum())
    out["vendas_novas"]    = int(df_diario["vendas_novas"].sum())
    out["montante"]        = float(df_diario["montante"].sum())
    out["receita"]         = float(df_diario["receita"].sum())

    out["ticket_medio"]    = _safe_div(out["montante"], out["vendas_novas"])
    out["taxa_comparecimento"] = _safe_div(
        out["comparecimentos"], out["agendamentos"]
    ) * 100
    out["taxa_lead_venda_nova"] = _safe_div(
        out["vendas_novas"], out["leads"]
    ) * 100

    # Média móvel do PRÓPRIO período (vendas_novas/dia). A "média móvel
    # 21d" canônica vem de get_media_movel_vendas() — aqui é só fallback
    # informativo do próprio recorte.
    n_dias = max(int(df_diario["data_ref"].nunique() or 1), 1)
    out["media_movel_21d"] = _safe_div(out["vendas_novas"], n_dias)
    return out


def prevendas_funil_etapas(k: dict) -> tuple[list[str], list[float]]:
    """4 etapas: Leads → Agendamentos → Comparecimentos → Vendas novas."""
    labels = ["Leads", "Agendamentos", "Comparecimentos", "Vendas novas"]
    values = [
        float(k.get("leads", 0) or 0),
        float(k.get("agendamentos", 0) or 0),
        float(k.get("comparecimentos", 0) or 0),
        float(k.get("vendas_novas", 0) or 0),
    ]
    return labels, values


# ---------------------------------------------------------------------------
# SDRs & Times
# ---------------------------------------------------------------------------
def prevendas_anotar_sdr(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `tipo_sdr` (Pré-vendas / Social Seller / SDR não
    classificado / Sem SDR) usando a classificação canônica."""
    if df is None or df.empty or "sdr" not in df.columns:
        return df
    out = df.copy()
    out["tipo_sdr"] = out["sdr"].apply(classify_sdr)
    return out


def _consolidar_por_sdr(df_sdr: pd.DataFrame) -> pd.DataFrame:
    """Agrega o df de SDR por `sdr`, somando métricas e consolidando
    `fonte_sdr` numa string ('activity.prevendas' / 'deal.sdr_ss' /
    'ambas' / 'Sem SDR'). Quando o df NÃO tem coluna `fonte_sdr` (versão
    antiga, sem regra híbrida), apenas devolve agrupado por sdr.
    """
    if df_sdr is None or df_sdr.empty:
        return df_sdr

    sum_cols = [c for c in ("agendamentos", "comparecimentos",
                            "cancelamentos", "vendas", "vendas_novas",
                            "montante", "receita") if c in df_sdr.columns]
    if "fonte_sdr" in df_sdr.columns:
        agg = df_sdr.groupby("sdr", as_index=False, dropna=False).agg(
            **{c: (c, "sum") for c in sum_cols},
            fontes=("fonte_sdr", lambda s: sorted(set(s.dropna()))),
        )

        def _label_fontes(fontes_lista) -> str:
            f = list(fontes_lista or [])
            if not f:
                return ""
            if len(f) == 1:
                return f[0]
            # Mais de uma fonte para o mesmo SDR (raro mas existe).
            return ", ".join(f)

        agg["fonte_sdr"] = agg["fontes"].apply(_label_fontes)
        agg = agg.drop(columns=["fontes"])
    else:
        agg = df_sdr.groupby("sdr", as_index=False, dropna=False).agg(
            **{c: (c, "sum") for c in sum_cols}
        )
    return agg


def prevendas_ranking_sdr(df_sdr: pd.DataFrame) -> pd.DataFrame:
    """Ranking ordenado por agendamentos desc com derivadas:
      taxa_comparecimento = comparec / agend * 100
      taxa_lead_venda     = vendas_novas / agend * 100  (proxy do funil)
      ticket_medio        = montante / vendas_novas
    `tipo_sdr` adicionado pela classificação canônica.

    Quando o `df_sdr` vem com a coluna `fonte_sdr` (regra híbrida),
    consolida 1 linha por SDR somando métricas. A coluna `fonte_sdr` no
    output indica qual caminho do COALESCE creditou o SDR — útil pra
    auditoria. Quando um mesmo SDR teve atividades vindo de mais de uma
    fonte, exibe como ex.: `activity.prevendas, deal.sdr_ss`.
    """
    cols = ["sdr", "tipo_sdr", "fonte_sdr",
            "agendamentos", "comparecimentos", "cancelamentos",
            "vendas", "vendas_novas", "montante", "receita",
            "taxa_comparecimento", "taxa_lead_venda", "ticket_medio"]
    if df_sdr is None or df_sdr.empty:
        return pd.DataFrame(columns=cols)

    consolidado = _consolidar_por_sdr(df_sdr)
    out = prevendas_anotar_sdr(consolidado)
    out["taxa_comparecimento"] = out.apply(
        lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100,
        axis=1,
    )
    out["taxa_lead_venda"] = out.apply(
        lambda r: _safe_div(r["vendas_novas"], r["agendamentos"]) * 100,
        axis=1,
    )
    out["ticket_medio"] = out.apply(
        lambda r: _safe_div(r["montante"], r["vendas_novas"]),
        axis=1,
    )
    for c in cols:
        if c not in out.columns:
            out[c] = 0 if c not in ("sdr", "tipo_sdr", "fonte_sdr") else ""
    return (out[cols]
            .sort_values(["agendamentos", "vendas_novas"], ascending=False)
            .reset_index(drop=True))


def prevendas_detalhe_sdr_por_fonte(df_sdr: pd.DataFrame) -> pd.DataFrame:
    """Detalhe COMPLETO sem consolidar: 1 linha por (sdr, fonte_sdr).
    Usado no expander de auditoria da página SDRs & Times. Quando o df
    não tem `fonte_sdr` (versão antiga), devolve idêntico ao input com
    classificação anotada."""
    if df_sdr is None or df_sdr.empty:
        return df_sdr
    out = prevendas_anotar_sdr(df_sdr)
    out["taxa_comparecimento"] = out.apply(
        lambda r: _safe_div(r.get("comparecimentos", 0),
                            r.get("agendamentos", 0)) * 100, axis=1
    )
    return out.sort_values(
        ["agendamentos", "vendas_novas"], ascending=False
    ).reset_index(drop=True)


def prevendas_por_tipo(df_sdr: pd.DataFrame) -> pd.DataFrame:
    """Consolidação por tipo_sdr (Pré-vendas / Social Seller / etc.).
    Consolida primeiro por sdr (somando fontes) pra evitar dupla contagem
    quando o mesmo SDR teve atividades vindo de mais de uma fonte."""
    cols = ["tipo_sdr",
            "agendamentos", "comparecimentos", "cancelamentos",
            "vendas", "vendas_novas", "montante", "receita",
            "taxa_comparecimento", "ticket_medio"]
    if df_sdr is None or df_sdr.empty:
        return pd.DataFrame(columns=cols)

    consolidado = _consolidar_por_sdr(df_sdr)
    base = prevendas_anotar_sdr(consolidado)
    agg = (base.groupby("tipo_sdr", as_index=False, dropna=False)
                .agg(agendamentos=("agendamentos", "sum"),
                     comparecimentos=("comparecimentos", "sum"),
                     cancelamentos=("cancelamentos", "sum"),
                     vendas=("vendas", "sum"),
                     vendas_novas=("vendas_novas", "sum"),
                     montante=("montante", "sum"),
                     receita=("receita", "sum")))
    agg["taxa_comparecimento"] = agg.apply(
        lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100,
        axis=1,
    )
    agg["ticket_medio"] = agg.apply(
        lambda r: _safe_div(r["montante"], r["vendas_novas"]),
        axis=1,
    )
    return agg[cols].sort_values("agendamentos", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Matriz SDR × Closer
# ---------------------------------------------------------------------------
_MATRIZ_METRICAS_VALIDAS = {
    "agendamentos", "comparecimentos", "vendas", "vendas_novas",
    "montante", "receita",
}


def prevendas_matriz_sdr_closer(df_pair: pd.DataFrame,
                                metrica: str = "agendamentos") -> pd.DataFrame:
    """Pivot SDR × Closer com a métrica escolhida na célula. Métricas
    aceitas: agendamentos, comparecimentos, vendas, vendas_novas,
    montante, receita.

    `pivot_table` com `aggfunc="sum"` consolida automaticamente quando
    há múltiplas linhas pro mesmo par (sdr, closer) — caso da regra
    híbrida onde podem existir 2 linhas vindas de fontes diferentes."""
    if (df_pair is None or df_pair.empty
            or metrica not in df_pair.columns
            or metrica not in _MATRIZ_METRICAS_VALIDAS):
        return pd.DataFrame()
    return df_pair.pivot_table(
        index="sdr", columns="closer", values=metrica,
        aggfunc="sum", fill_value=0,
    )


def prevendas_pair_totais(df_pair: pd.DataFrame) -> dict:
    """Totais cross-pares (cards do topo da página SDR × Closer)."""
    z = {"agendamentos": 0, "comparecimentos": 0, "vendas": 0,
         "vendas_novas": 0, "montante": 0.0, "receita": 0.0,
         "taxa_comparecimento": 0.0, "taxa_venda": 0.0}
    if df_pair is None or df_pair.empty:
        return z
    out = dict(z)
    for k in ("agendamentos", "comparecimentos", "vendas", "vendas_novas"):
        if k in df_pair.columns:
            out[k] = int(df_pair[k].sum())
    for k in ("montante", "receita"):
        if k in df_pair.columns:
            out[k] = float(df_pair[k].sum())
    out["taxa_comparecimento"] = _safe_div(
        out["comparecimentos"], out["agendamentos"]
    ) * 100
    out["taxa_venda"] = _safe_div(
        out["vendas_novas"], out["comparecimentos"]
    ) * 100
    return out


# ---------------------------------------------------------------------------
# Comparecimentos & Oportunidades — quebra +12 / -12
# ---------------------------------------------------------------------------
def prevendas_classif_kpis(df_classif: pd.DataFrame) -> dict:
    """KPIs de comparecimentos por bucket de classificação."""
    z = {
        "agend_total": 0, "comparec_total": 0, "vendas_novas_total": 0,
        "agend_mais_12": 0, "comparec_mais_12": 0, "vendas_novas_mais_12": 0,
        "agend_menos_12": 0, "comparec_menos_12": 0, "vendas_novas_menos_12": 0,
        "agend_nao_atua": 0, "comparec_nao_atua": 0, "vendas_novas_nao_atua": 0,
        "agend_sem_classif": 0, "comparec_sem_classif": 0, "vendas_novas_sem_classif": 0,
        "taxa_comparec_mais_12": 0.0, "taxa_comparec_menos_12": 0.0,
        "taxa_venda_mais_12": 0.0,    "taxa_venda_menos_12": 0.0,
    }
    if df_classif is None or df_classif.empty:
        return z

    out = dict(z)
    for bucket, prefix in (("+12", "mais_12"), ("-12", "menos_12"),
                            ("Não atua", "nao_atua"),
                            ("Sem classif", "sem_classif")):
        sub = df_classif[df_classif["bucket"] == bucket]
        out[f"agend_{prefix}"]        = int(sub["leads_com_agend"].sum())
        out[f"comparec_{prefix}"]     = int(sub["leads_com_compar"].sum())
        out[f"vendas_novas_{prefix}"] = int(sub["leads_com_venda_nova"].sum())

    out["agend_total"]        = int(df_classif["leads_com_agend"].sum())
    out["comparec_total"]     = int(df_classif["leads_com_compar"].sum())
    out["vendas_novas_total"] = int(df_classif["leads_com_venda_nova"].sum())

    out["taxa_comparec_mais_12"]  = _safe_div(out["comparec_mais_12"], out["agend_mais_12"]) * 100
    out["taxa_comparec_menos_12"] = _safe_div(out["comparec_menos_12"], out["agend_menos_12"]) * 100
    out["taxa_venda_mais_12"]     = _safe_div(out["vendas_novas_mais_12"], out["comparec_mais_12"]) * 100
    out["taxa_venda_menos_12"]    = _safe_div(out["vendas_novas_menos_12"], out["comparec_menos_12"]) * 100
    return out


# ---------------------------------------------------------------------------
# SLA (amostra parcial)
# ---------------------------------------------------------------------------
_SLA_BUCKETS_LABELS = ["0–5 min", "6–15 min", "16–60 min",
                       "1–4 h", "4–24 h", ">24 h"]
_SLA_BUCKETS_KEYS = ["bucket_0_5", "bucket_6_15", "bucket_16_60",
                     "bucket_1_4h", "bucket_4_24h", "bucket_mais_24h"]


def prevendas_sla_kpis(df_sla: pd.DataFrame) -> dict:
    """KPIs de SLA. ⚠ AMOSTRA PARCIAL — `sla` preenchido em ~39% dos
    leads. NÃO USAR como ranking individual."""
    z = {
        "total_leads": 0, "leads_com_sla": 0, "leads_sem_sla": 0,
        "cobertura_pct": 0.0,
        "tempo_medio_min": 0.0, "tempo_p50_min": 0.0, "tempo_p90_min": 0.0,
        "tempo_max_min": 0.0,
        "buckets": [],
    }
    if df_sla is None or df_sla.empty:
        return z

    r = df_sla.iloc[0]
    out = dict(z)
    out["total_leads"]      = int(r.get("total_leads", 0) or 0)
    out["leads_com_sla"]    = int(r.get("leads_com_sla", 0) or 0)
    out["leads_sem_sla"]    = int(r.get("leads_sem_sla", 0) or 0)
    out["tempo_medio_min"]  = float(r.get("tempo_medio_min", 0) or 0)
    out["tempo_p50_min"]    = float(r.get("tempo_p50_min", 0) or 0)
    out["tempo_p90_min"]    = float(r.get("tempo_p90_min", 0) or 0)
    out["tempo_max_min"]    = float(r.get("tempo_max_min", 0) or 0)
    out["cobertura_pct"]    = _safe_div(out["leads_com_sla"], out["total_leads"]) * 100
    out["buckets"] = [
        {"faixa": label, "qtd": int(r.get(key, 0) or 0)}
        for label, key in zip(_SLA_BUCKETS_LABELS, _SLA_BUCKETS_KEYS)
    ]
    return out


def prevendas_sla_buckets_df(k: dict) -> pd.DataFrame:
    """Converte `kpis['buckets']` em DataFrame pronto para `bar_simple`."""
    return pd.DataFrame(k.get("buckets") or [],
                        columns=["faixa", "qtd"])
