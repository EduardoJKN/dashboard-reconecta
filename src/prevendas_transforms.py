"""Transforms / KPIs do dashboard de Pré-vendas.

Recebe DataFrames lidos via `repositories.py` (queries
`prevendas_*.sql`) e devolve dicts/DataFrames prontos para a UI.

SDR primário vem de `zoho_activities.prevendas`. A classificação de
**tipo de SDR** (Pré-vendas / Social Seller / SDR não classificado)
reusa `team_classification.classify_sdr` — mesma fonte canônica
usada nas páginas de Vendas e na regra do SDR × Closer.
"""
from __future__ import annotations

import unicodedata

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
    "leads": 0,
    "leads_mais_12": 0,
    "leads_menos_12": 0,
    "agendamentos_criados": 0,
    "agendamentos_exibidos": 0,
    "agendamentos_mais_12": 0,
    "novos_agendamentos": 0,
    "reunioes_marcadas": 0,
    "concluidas": 0,
    "canceladas": 0,
    "vencidas": 0,
    "agendadas_pendentes": 0,
    # Aliases legados mantidos para compatibilidade com páginas ainda não migradas.
    "agendamentos": 0,
    "comparecimentos": 0,
    "comparecimentos_mais_12": 0,
    "vendas": 0, "vendas_novas": 0,
    "vendas_mais_12": 0,
    "montante": 0.0, "receita": 0.0,
    "ticket_medio": 0.0,
    "taxa_comparecimento": 0.0,
    "taxa_comparecimento_real": 0.0,
    "taxa_comparecimento_bruta": 0.0,
    "taxa_lead_venda_nova": 0.0,
    "media_movel_21d": 0.0,
}


def prevendas_overview_kpis(df_diario: pd.DataFrame) -> dict:
    """KPIs consolidados a partir do `prevendas_overview_diario.sql`.

    Taxas recalculadas no agregado, NÃO média de taxas diárias:
      taxa_comparecimento = SUM(comparecimentos) / SUM(agendamentos) * 100
      taxa_lead_venda_nova = SUM(vendas) / SUM(leads) * 100
      ticket_medio         = SUM(montante) / SUM(vendas)
    A `media_movel_21d` precisa ser calculada com base em uma janela
    independente do filtro (usar `get_media_movel_vendas` quando
    fizer sentido — aqui devolve média do próprio período como fallback)."""
    out = dict(_OVERVIEW_ZEROS)
    if df_diario is None or df_diario.empty:
        return out

    out["leads"] = int(df_diario["leads"].sum()) if "leads" in df_diario.columns else 0
    out["leads_mais_12"] = (
        int(df_diario["leads_mais_12"].sum())
        if "leads_mais_12" in df_diario.columns else 0
    )
    out["leads_menos_12"] = (
        int(df_diario["leads_menos_12"].sum())
        if "leads_menos_12" in df_diario.columns else 0
    )
    out["comparecimentos_mais_12"] = (
        int(df_diario["comparecimentos_mais_12"].sum())
        if "comparecimentos_mais_12" in df_diario.columns else 0
    )
    out["vendas_mais_12"] = (
        int(df_diario["vendas_mais_12"].sum())
        if "vendas_mais_12" in df_diario.columns else 0
    )
    out["agendamentos_criados"] = int(df_diario["agendamentos_criados"].sum()) if "agendamentos_criados" in df_diario.columns else int(df_diario["novos_agendamentos"].sum())
    out["agendamentos_mais_12"] = int(df_diario["agendamentos_mais_12"].sum()) if "agendamentos_mais_12" in df_diario.columns else 0
    out["novos_agendamentos"] = out["agendamentos_criados"]
    out["reunioes_marcadas"] = int(df_diario["reunioes_marcadas"].sum()) if "reunioes_marcadas" in df_diario.columns else int(df_diario["agendamentos"].sum())
    out["concluidas"] = int(df_diario["concluidas"].sum()) if "concluidas" in df_diario.columns else int(df_diario["comparecimentos"].sum())
    out["canceladas"] = int(df_diario["canceladas"].sum()) if "canceladas" in df_diario.columns else 0
    out["vencidas"] = int(df_diario["vencidas"].sum()) if "vencidas" in df_diario.columns else 0
    out["agendadas_pendentes"] = int(df_diario["agendadas_pendentes"].sum()) if "agendadas_pendentes" in df_diario.columns else 0
    out["agendamentos"] = out["reunioes_marcadas"]
    out["agendamentos_exibidos"] = max(out["agendamentos"] - out["vencidas"], 0)
    out["comparecimentos"] = out["concluidas"]
    out["vendas"] = int(df_diario["vendas"].sum())
    out["vendas_novas"] = int(df_diario["vendas_novas"].sum()) if "vendas_novas" in df_diario.columns else out["vendas"]
    out["montante"] = float(df_diario["montante"].sum())
    out["receita"] = float(df_diario["receita"].sum())

    out["ticket_medio"] = _safe_div(out["montante"], out["vendas"])
    out["taxa_comparecimento"] = _safe_div(
        out["comparecimentos"], out["agendamentos_exibidos"]
    ) * 100
    out["taxa_comparecimento_real"] = out["taxa_comparecimento"]
    out["taxa_comparecimento_bruta"] = out["taxa_comparecimento"]
    out["taxa_lead_venda_nova"] = _safe_div(
        out["vendas"], out["leads"]
    ) * 100

    # Média móvel do PRÓPRIO período (vendas_novas/dia). A "média móvel
    # 21d" canônica vem de get_media_movel_vendas() — aqui é só fallback
    # informativo do próprio recorte.
    n_dias = max(int(df_diario["data_ref"].nunique() or 1), 1)
    out["media_movel_21d"] = _safe_div(out["vendas"], n_dias)
    return out


_MESES_PT = [
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]


def _semana_do_mes(dia: int) -> int:
    """Semana do mês na regra fixa pedida pela operação:
    1-7=1ª, 8-14=2ª, 15-21=3ª, 22-28=4ª, 29-31=5ª."""
    return ((dia - 1) // 7) + 1


def _label_semana(ano: int, mes: int, semana: int, mostrar_ano: bool) -> str:
    base = f"{semana}ª sem ({_MESES_PT[mes - 1]}"
    return f"{base}/{ano})" if mostrar_ano else f"{base})"


def prevendas_agregar_por_granularidade(df_diario: pd.DataFrame,
                                        granularidade: str) -> pd.DataFrame:
    """Agrega `df_diario` (saída de prevendas_overview_diario.sql, já com
    métricas dedup) por granularidade visual.

    - "Dia":    devolve as linhas como vieram, com `agendamentos_exibidos`,
                `taxa_comparecimento` e `ticket_medio` derivadas.
    - "Semana": agrupa por (ano, mês, semana_do_mes) usando a regra fixa
                1-7 / 8-14 / 15-21 / 22-28 / 29-31. Label exibido inclui
                o nome do mês; quando o período abrange mais de um ano,
                acrescenta o ano.
    - "Mês":    se houver um único mês no período, devolve 1 linha
                consolidada com o nome do mês (ex.: "Maio/2026"); se
                houver múltiplos meses, devolve 1 linha por mês.

    Recalcula `taxa_comparecimento` e `ticket_medio` DEPOIS de somar
    (não é média de taxas diárias — é razão das somas).
    """
    if df_diario is None or df_diario.empty:
        return pd.DataFrame()

    df = df_diario.copy()
    df["data_ref"] = pd.to_datetime(df["data_ref"])

    sum_cols = [c for c in (
        "leads", "leads_mais_12", "leads_menos_12",
        "agendamentos_criados",
        "agendamentos", "vencidas",
        "agendamentos_mais_12",
        "comparecimentos", "comparecimentos_mais_12",
        "vendas", "vendas_mais_12",
        "montante", "receita",
    ) if c in df.columns]

    granularidade = (granularidade or "Dia").strip()

    if granularidade == "Dia":
        out = (df.sort_values("data_ref")
                 .groupby("data_ref", as_index=False)[sum_cols].sum())
        out.insert(0, "periodo", out["data_ref"].dt.strftime("%d/%m/%Y"))

    elif granularidade == "Semana":
        df["_ano"]    = df["data_ref"].dt.year
        df["_mes"]    = df["data_ref"].dt.month
        df["_semana"] = df["data_ref"].dt.day.map(_semana_do_mes)
        mostrar_ano = df["_ano"].nunique() > 1
        out = (df.groupby(["_ano", "_mes", "_semana"], as_index=False)[sum_cols]
                 .sum()
                 .sort_values(["_ano", "_mes", "_semana"]))
        out["periodo"] = out.apply(
            lambda r: _label_semana(int(r["_ano"]), int(r["_mes"]),
                                    int(r["_semana"]), mostrar_ano),
            axis=1,
        )
        out = out.drop(columns=["_ano", "_mes", "_semana"])
        cols_final = ["periodo"] + sum_cols
        out = out[cols_final]

    elif granularidade == "Mês":
        df["_ano"] = df["data_ref"].dt.year
        df["_mes"] = df["data_ref"].dt.month
        out = (df.groupby(["_ano", "_mes"], as_index=False)[sum_cols].sum()
                 .sort_values(["_ano", "_mes"]))
        out["periodo"] = out.apply(
            lambda r: f"{_MESES_PT[int(r['_mes']) - 1]}/{int(r['_ano'])}", axis=1
        )
        out = out.drop(columns=["_ano", "_mes"])
        cols_final = ["periodo"] + sum_cols
        out = out[cols_final]

    else:
        out = (df.sort_values("data_ref")
                 .groupby("data_ref", as_index=False)[sum_cols].sum())
        out.insert(0, "periodo", out["data_ref"].dt.strftime("%d/%m/%Y"))

    # Derivadas comuns a todas as granularidades.
    if {"agendamentos", "vencidas"}.issubset(out.columns):
        out["agendamentos_exibidos"] = (
            out["agendamentos"].fillna(0) - out["vencidas"].fillna(0)
        ).clip(lower=0)

    if {"comparecimentos", "agendamentos_exibidos"}.issubset(out.columns):
        denom = out["agendamentos_exibidos"].where(out["agendamentos_exibidos"] != 0)
        out["taxa_comparecimento"] = (
            out["comparecimentos"].astype(float).div(denom).fillna(0) * 100
        )

    if {"montante", "vendas"}.issubset(out.columns):
        denom_vendas = out["vendas"].where(out["vendas"] != 0)
        out["ticket_medio"] = (
            out["montante"].astype(float).div(denom_vendas).fillna(0)
        )

    # Conversões do funil (gerais + recorte +12). Denominador 0 → 0%
    # (consistente com o padrão atual do dashboard, que usa `_safe_div`).
    def _pct(num_col: str, den_col: str) -> pd.Series:
        if num_col not in out.columns or den_col not in out.columns:
            return pd.Series(0.0, index=out.index)
        denom = out[den_col].where(out[den_col] != 0)
        return out[num_col].astype(float).div(denom).fillna(0) * 100

    out["pct_lead_agend"]      = _pct("agendamentos_exibidos", "leads")
    out["pct_agend_comp"]      = _pct("comparecimentos",       "agendamentos_exibidos")
    out["pct_comp_venda"]      = _pct("vendas",                "comparecimentos")

    out["pct_lead_agend_12"]   = _pct("agendamentos_mais_12",  "leads_mais_12")
    out["pct_agend_comp_12"]   = _pct("comparecimentos_mais_12", "agendamentos_mais_12")
    out["pct_comp_venda_12"]   = _pct("vendas_mais_12",        "comparecimentos_mais_12")

    return out.reset_index(drop=True)


def prevendas_funil_etapas(k: dict) -> tuple[list[str], list[float]]:
    """4 etapas do legado: Agend. criados → Agendamentos → Comparecimentos → Vendas."""
    labels = ["Agend. criados", "Agendamentos", "Comparecimentos", "Vendas"]
    values = [
        float(k.get("agendamentos_criados", k.get("novos_agendamentos", 0)) or 0),
        float(k.get("agendamentos", 0) or 0),
        float(k.get("comparecimentos", 0) or 0),
        float(k.get("vendas", 0) or 0),
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

    sum_cols = [c for c in ("agendamentos_criados", "agendamentos",
                            "agendamentos_mais_12", "agendamentos_menos_12",
                            "comparecimentos", "cancelamentos", "cancelados",
                            "vencidos", "vendas", "vendas_novas",
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


def _normalize_name(name) -> str:
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _matches_official_name(official_name: str, raw_name: str) -> bool:
    official = _normalize_name(official_name)
    raw = _normalize_name(raw_name)
    if not official or not raw:
        return False
    if " " in official or " " in raw:
        return official in raw or raw in official
    first_name = raw.split()[0] if raw else ""
    return first_name == official


def _canonical_official_name(name, official_names: list[str]) -> str:
    matches = [
        official_name
        for official_name in official_names
        if _matches_official_name(official_name, name)
    ]
    if len(matches) == 1:
        return matches[0]
    normalized_name = _normalize_name(name)
    exact_matches = [
        official_name
        for official_name in matches
        if _normalize_name(official_name) == normalized_name
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    return ""


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
            "agendamentos_criados", "agendamentos",
            "agendamentos_mais_12", "agendamentos_menos_12",
            "comparecimentos", "cancelamentos", "cancelados", "vencidos",
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


def prevendas_ranking_sdr_oficiais(df_sdr: pd.DataFrame,
                                   df_sdrs_oficiais: pd.DataFrame) -> pd.DataFrame:
    """Ranking restrito aos nomes presentes no cadastro oficial da FDW.

    O ranking bruto continua vindo de `get_prevendas_por_sdr()`. Aqui:
    1. remove `Sem SDR`
    2. mantém apenas SDRs que casam com `fdw_reconecta.executivas_pre_vendas`
    3. padroniza o nome exibido com a coluna oficial `nome`
    """
    cols = ["sdr", "tipo_sdr", "fonte_sdr",
            "agendamentos_criados", "agendamentos",
            "agendamentos_mais_12", "agendamentos_menos_12",
            "comparecimentos", "cancelamentos", "cancelados", "vencidos",
            "vendas", "vendas_novas", "montante", "receita",
            "taxa_comparecimento", "taxa_lead_venda", "ticket_medio"]
    ranking = prevendas_ranking_sdr(df_sdr)
    if (ranking is None or ranking.empty or df_sdrs_oficiais is None
            or df_sdrs_oficiais.empty or "nome" not in df_sdrs_oficiais.columns):
        return pd.DataFrame(columns=cols)

    official_names = [
        str(nome).strip()
        for nome in df_sdrs_oficiais["nome"].dropna().tolist()
        if str(nome).strip()
    ]
    base = ranking.copy()
    base = base[base["sdr"] != SEM_SDR_LABEL].copy()
    base["sdr_oficial"] = base["sdr"].apply(
        lambda nome: _canonical_official_name(nome, official_names)
    )
    base = base[base["sdr_oficial"] != ""].copy()
    if base.empty:
        return pd.DataFrame(columns=cols)

    sum_cols = [c for c in ("agendamentos_criados", "agendamentos",
                            "agendamentos_mais_12", "agendamentos_menos_12",
                            "comparecimentos", "cancelamentos", "cancelados",
                            "vencidos", "vendas", "vendas_novas",
                            "montante", "receita")
                if c in base.columns]
    agg = base.groupby("sdr_oficial", as_index=False, dropna=False).agg(
        **{c: (c, "sum") for c in sum_cols},
        fontes=("fonte_sdr",
                lambda s: ", ".join(sorted({v for v in s.dropna() if str(v).strip()}))),
    )
    agg = agg.rename(columns={"sdr_oficial": "sdr", "fontes": "fonte_sdr"})
    agg["tipo_sdr"] = "Pré-vendas"
    agg["taxa_comparecimento"] = agg.apply(
        lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100,
        axis=1,
    )
    agg["taxa_lead_venda"] = agg.apply(
        lambda r: _safe_div(r["vendas_novas"], r["agendamentos"]) * 100,
        axis=1,
    )
    agg["ticket_medio"] = agg.apply(
        lambda r: _safe_div(r["montante"], r["vendas_novas"]),
        axis=1,
    )
    for c in cols:
        if c not in agg.columns:
            agg[c] = 0 if c not in ("sdr", "tipo_sdr", "fonte_sdr") else ""
    return (agg[cols]
            .sort_values(["agendamentos", "vendas_novas"], ascending=False)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Detalhe linha-a-linha (prevendas_leads_detalhe_diario.sql) — helpers usados
# pela tabela "Detalhamento Top SDR" da Visão Geral Pré-vendas.
# ---------------------------------------------------------------------------
def prevendas_normalizar_detalhe(df_det: pd.DataFrame) -> pd.DataFrame:
    """Enriquecimento mínimo do detalhe diário para máscaras estáveis.

    Adiciona colunas *_filtro (strings limpas, sem NaN) e `nome_cliente_view`
    (fallback `nome_deal`). Não remove nada — preserva colunas originais.
    """
    if df_det is None or df_det.empty:
        return df_det
    out = df_det.copy()

    def _series_or_default(col_name: str, default: str = "") -> pd.Series:
        if col_name in out.columns:
            return out[col_name]
        return pd.Series([default] * len(out), index=out.index)

    out["tipo_registro_base_filtro"] = (
        _series_or_default("tipo_registro_base", "Atividade")
        .fillna("Atividade").astype(str).str.strip().replace("", "Atividade")
    )
    out["classificacao_filtro"] = (
        _series_or_default("classificacao", "")
        .fillna("").astype(str).str.strip().replace("", "Sem classificação")
    )
    # classificacao_crm: vem direto de zoho_deals.lead_classification.
    # Pode ser NULL/vazio; preservado como "" para a máscara combinada.
    out["classificacao_crm_filtro"] = (
        _series_or_default("classificacao_crm", "")
        .fillna("").astype(str).str.strip()
    )
    out["sdr_filtro"] = (
        _series_or_default("sdr", "")
        .fillna("").astype(str).str.strip().replace("", "Sem SDR")
    )
    out["closer_filtro"] = (
        _series_or_default("closer", "")
        .fillna("").astype(str).str.strip().replace("", "Sem Closer")
    )
    out["status_filtro"] = (
        _series_or_default("status_reuniao", "")
        .fillna("").astype(str).str.strip().replace("", "Sem status")
    )
    out["nome_cliente_view"] = (
        _series_or_default("nome_cliente", "")
        .fillna("").astype(str).str.strip()
    )
    if "nome_deal" in out.columns:
        sem_nome = out["nome_cliente_view"] == ""
        out.loc[sem_nome, "nome_cliente_view"] = (
            out.loc[sem_nome, "nome_deal"].fillna("").astype(str).str.strip()
        )
    return out


def prevendas_anotar_tipo_sdr_detalhe(df_det_norm: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `tipo_sdr_filtro` (Pré-vendas / Social Seller / SDR não
    classificado / Sem SDR) ao detalhe normalizado. Usa a classificação
    canônica de `team_classification.classify_sdr` — mesma fonte usada
    pelo Top SDRs.
    """
    if df_det_norm is None or df_det_norm.empty or "sdr_filtro" not in df_det_norm.columns:
        return df_det_norm
    out = df_det_norm.copy()
    out["tipo_sdr_filtro"] = out["sdr_filtro"].apply(classify_sdr)
    return out


def prevendas_diario_filtrado_por_sdr(df_detalhe_norm: pd.DataFrame,
                                      df_diario: pd.DataFrame,
                                      sdrs_filtro: list[str],
                                      tipos_sdr_filtro: list[str],
                                      data_ini,
                                      data_fim) -> pd.DataFrame:
    """Recompõe a série diária aplicando filtros locais de SDR/Tipo SDR.

    Usado pelo expander "Ver dados do período" — só essa tabela é
    reconstruída; o resto da página segue com `df_diario` original.

    Regra:
      - Leads / Leads +12 / Leads -12 → preservados do df_diario (sem
        filtro). SDR não é atribuível ao lead cru (a atribuição entra
        depois, na activity ou no deal).
      - Demais métricas → recalculadas do df_detalhe filtrado, com:
            * dedup por activity_id (agendamentos / comparecimentos /
              vencidas e seus recortes +12);
            * dedup por deal_id (vendas / vendas +12 / montante / receita).
      - Datas fora do período (ctx) ignoradas; datas extras introduzidas
        pelo detalhe filtrado (ex.: activity num dia que não teve lead)
        são acrescentadas no shape final.
    """
    if (df_detalhe_norm is None or df_detalhe_norm.empty
            or df_diario is None or df_diario.empty):
        return df_diario

    df = df_detalhe_norm
    if sdrs_filtro:
        df = df[df["sdr_filtro"].isin(sdrs_filtro)]
    if (tipos_sdr_filtro
            and "tipo_sdr_filtro" in df.columns):
        df = df[df["tipo_sdr_filtro"].isin(tipos_sdr_filtro)]

    ini = pd.Timestamp(data_ini)
    fim = pd.Timestamp(data_fim)

    is_ativ = df["tipo_registro_base_filtro"] == "Atividade"
    is_vnd  = df["tipo_registro_base_filtro"] == "Venda"
    em_agend = (
        df["data_agendamento"].notna()
        & df["data_agendamento"].between(ini, fim, inclusive="both")
    )
    em_cria = (
        df["data_criacao"].notna()
        & df["data_criacao"].between(ini, fim, inclusive="both")
    )
    em_vnd_p = (
        df["data_venda"].notna()
        & df["data_venda"].between(ini, fim, inclusive="both")
    )
    flag_12 = (
        (df.get("classificacao_crm_filtro", pd.Series("", index=df.index)) == "Atua +12")
        | (df["classificacao_filtro"] == "Atua +12")
    )
    is_concluido = df["status_filtro"].isin(["Concluída", "Concluído"])

    def _conta(mask, data_col, unidade_col) -> dict:
        sub = df.loc[mask, [data_col, unidade_col]].dropna()
        if sub.empty:
            return {}
        sub = sub.drop_duplicates(subset=[unidade_col])
        return sub.groupby(sub[data_col].dt.date).size().to_dict()

    map_agend_cri = _conta(is_ativ & em_cria,                              "data_criacao",     "activity_id")
    map_agend     = _conta(is_ativ & em_agend,                              "data_agendamento", "activity_id")
    map_agend12   = _conta(is_ativ & em_agend & flag_12,                    "data_agendamento", "activity_id")
    map_compar    = _conta(is_ativ & em_agend & is_concluido,               "data_agendamento", "activity_id")
    map_compar12  = _conta(is_ativ & em_agend & is_concluido & flag_12,     "data_agendamento", "activity_id")
    map_venc      = _conta(is_ativ & em_agend & (df["status_filtro"] == "Vencida"),
                           "data_agendamento", "activity_id")

    # Vendas: dedup por deal_id, somar montante/receita
    vendas_sub = df.loc[is_vnd & em_vnd_p].drop_duplicates(subset=["deal_id"])
    if vendas_sub.empty:
        map_vendas = map_vendas12 = {}
        map_montante = map_receita = {}
    else:
        vsdg = vendas_sub.assign(_day=vendas_sub["data_venda"].dt.date)
        flag_v_12 = (
            (vsdg.get("classificacao_crm_filtro", pd.Series("", index=vsdg.index)) == "Atua +12")
            | (vsdg["classificacao_filtro"] == "Atua +12")
        )
        map_vendas   = vsdg.groupby("_day").size().to_dict()
        map_vendas12 = vsdg.loc[flag_v_12].groupby("_day").size().to_dict()
        map_montante = vsdg.groupby("_day")["montante"].sum().to_dict() if "montante" in vsdg.columns else {}
        map_receita  = vsdg.groupby("_day")["receita"].sum().to_dict()  if "receita"  in vsdg.columns else {}

    # Une datas de df_diario (preserva todas) + datas extras vindas do detalhe.
    dia_df = pd.to_datetime(df_diario["data_ref"]).dt.date
    leads_map       = dict(zip(dia_df, df_diario.get("leads",         pd.Series(0, index=df_diario.index)).fillna(0).astype(int)))
    leads_mais_map  = dict(zip(dia_df, df_diario.get("leads_mais_12", pd.Series(0, index=df_diario.index)).fillna(0).astype(int)))
    leads_menos_map = dict(zip(dia_df, df_diario.get("leads_menos_12",pd.Series(0, index=df_diario.index)).fillna(0).astype(int)))

    datas_extras = (set(map_agend_cri) | set(map_agend) | set(map_compar)
                    | set(map_venc)    | set(map_vendas))
    todas_datas = sorted(set(dia_df.tolist()) | datas_extras)

    rows = []
    for dt in todas_datas:
        rows.append({
            "data_ref":                pd.Timestamp(dt),
            "leads":                   leads_map.get(dt, 0),
            "leads_mais_12":           leads_mais_map.get(dt, 0),
            "leads_menos_12":          leads_menos_map.get(dt, 0),
            "agendamentos_criados":    int(map_agend_cri.get(dt, 0)),
            "agendamentos":            int(map_agend.get(dt, 0)),
            "agendamentos_mais_12":    int(map_agend12.get(dt, 0)),
            "comparecimentos":         int(map_compar.get(dt, 0)),
            "comparecimentos_mais_12": int(map_compar12.get(dt, 0)),
            "vencidas":                int(map_venc.get(dt, 0)),
            "vendas":                  int(map_vendas.get(dt, 0)),
            "vendas_mais_12":          int(map_vendas12.get(dt, 0)),
            "montante":                float(map_montante.get(dt, 0.0)),
            "receita":                 float(map_receita.get(dt, 0.0)),
        })
    return pd.DataFrame(rows)


def prevendas_detalhe_mask_por_metrica(df_det_norm: pd.DataFrame,
                                       metrica: str,
                                       data_ini,
                                       data_fim) -> pd.Series:
    """Mask booleana sobre o detalhe para a métrica selecionada no ranking.

    Espelha 1:1 a regra de `prevendas_por_sdr.sql`:
      - agendamentos*       → atividade + start_datetime ∈ [ini, fim]
      - agendamentos_criados → atividade + created_time ∈ [ini, fim]
      - vendas              → venda + data_hora_compra ∈ [ini, fim]
      - comparecimentos     → agendamentos + status Concluída/Concluído
      - cancelados/vencidos → agendamentos + status correspondente
    Espera `df_det_norm` passado por `prevendas_normalizar_detalhe`.
    """
    if df_det_norm is None or df_det_norm.empty:
        idx = df_det_norm.index if df_det_norm is not None else []
        return pd.Series(False, index=idx)

    ini = pd.Timestamp(data_ini)
    fim = pd.Timestamp(data_fim)

    base_atividade = df_det_norm["tipo_registro_base_filtro"] == "Atividade"
    base_venda     = df_det_norm["tipo_registro_base_filtro"] == "Venda"

    em_periodo_agend = (
        df_det_norm["data_agendamento"].notna()
        & df_det_norm["data_agendamento"].between(ini, fim, inclusive="both")
    )
    em_periodo_cria = (
        df_det_norm["data_criacao"].notna()
        & df_det_norm["data_criacao"].between(ini, fim, inclusive="both")
    )
    em_periodo_vnd = (
        df_det_norm["data_venda"].notna()
        & df_det_norm["data_venda"].between(ini, fim, inclusive="both")
    )

    if metrica == "agendamentos_criados":
        return base_atividade & em_periodo_cria
    if metrica == "agendamentos":
        return base_atividade & em_periodo_agend
    # Regra +12 / -12 combinada: CRM (zoho_deals.lead_classification) OR
    # ext (ext_reconecta.leads.classificado). Espelha a regra dos cards.
    if metrica == "agendamentos_mais_12":
        return (base_atividade & em_periodo_agend
                & ((df_det_norm["classificacao_crm_filtro"] == "Atua +12")
                   | (df_det_norm["classificacao_filtro"]     == "Atua +12")))
    if metrica == "agendamentos_menos_12":
        return (base_atividade & em_periodo_agend
                & ((df_det_norm["classificacao_crm_filtro"] == "Atua -12")
                   | (df_det_norm["classificacao_filtro"]     == "Atua -12")))
    if metrica == "comparecimentos":
        return (base_atividade & em_periodo_agend
                & df_det_norm["status_filtro"].isin(["Concluída", "Concluído"]))
    if metrica == "vendas":
        return base_venda & em_periodo_vnd
    if metrica == "cancelados":
        return (base_atividade & em_periodo_agend
                & df_det_norm["status_filtro"].isin(["Cancelada", "Cancelado"]))
    if metrica == "vencidos":
        return (base_atividade & em_periodo_agend
                & (df_det_norm["status_filtro"] == "Vencida"))
    return pd.Series(False, index=df_det_norm.index)


def prevendas_sdrs_brutos_para_oficial(df_det_norm: pd.DataFrame,
                                       sdr_oficial: str,
                                       df_sdrs_oficiais: pd.DataFrame) -> list[str]:
    """Mapeia nome canônico do ranking → valores crus de `sdr_filtro`.

    O ranking expõe o nome oficial da `fdw_reconecta.executivas_pre_vendas`
    (resolvido por `_canonical_official_name`). O detalhe traz nomes "crus"
    vindos de `activity.prevendas` / `users.first_name||last_name`. Esta
    função aplica a mesma resolução canônica sobre os valores únicos do
    detalhe e devolve aqueles que casam com `sdr_oficial`.
    """
    if df_det_norm is None or df_det_norm.empty or not sdr_oficial:
        return []
    if df_sdrs_oficiais is None or df_sdrs_oficiais.empty:
        return []
    if "nome" not in df_sdrs_oficiais.columns:
        return []
    official_names = [
        str(nome).strip()
        for nome in df_sdrs_oficiais["nome"].dropna().tolist()
        if str(nome).strip()
    ]
    brutos = df_det_norm["sdr_filtro"].dropna().astype(str).unique().tolist()
    return [
        s for s in brutos
        if _canonical_official_name(s, official_names) == sdr_oficial
    ]


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
