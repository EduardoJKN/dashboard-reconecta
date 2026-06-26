"""Transforms e cálculos de KPI a partir das views reais (schema bi).

Toda função aqui recebe DataFrames já carregados pelos repositories e retorna
DataFrames/dicts prontos para a UI. Nenhum SQL aqui."""
from __future__ import annotations

from zoneinfo import ZoneInfo

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

# Buckets de classificação (regra canônica +12 > -12 > Não atua > Sem
# classif). 4 buckets pra contagens, 3 pra montante/receita (a view não
# expõe `montante_sem_classificacao` / `receita_sem_classificacao` —
# vendas sem classificação não têm financeiro quebrado).
_CLASSIF_BUCKETS_4 = ("mais_12", "menos_12", "nao_atua", "sem_classificacao")
_CLASSIF_BUCKETS_3 = ("mais_12", "menos_12", "nao_atua")

_EXEC_CLASSIF_SUM = [
    *(f"oportunidades_{b}"    for b in _CLASSIF_BUCKETS_4),
    *(f"agendamentos_{b}"     for b in _CLASSIF_BUCKETS_4),
    *(f"comparecimentos_{b}"  for b in _CLASSIF_BUCKETS_4),
    *(f"ganhos_{b}"           for b in _CLASSIF_BUCKETS_4),
    *(f"montante_{b}"         for b in _CLASSIF_BUCKETS_3),
    *(f"receita_{b}"          for b in _CLASSIF_BUCKETS_3),
]

# `leads_lp_form` é DELIBERADAMENTE omitido daqui: a view agrega só por
# data (sem executiva), então o valor se repete entre executivas do
# mesmo dia. Somar via groupby('executiva').sum() infla N×.
_EXEC_SUM = [
    "oportunidades", "agendamentos", "comparecimentos", "vendas",
    "montante", "receita", "perdidos", "cancelados",
    # vencidos vem direto da view a partir de mai/2026; `agendamentos`
    # passou a ser líquido (sem status `Vencida`). Não é re-injetado via
    # detalhe — soma normal por executiva no groupby.
    "vencidos",
    "novos", "ascensoes", "renovacoes", "indicacoes",
    "lead_in_consultoria_gratuita",
    *_EXEC_CLASSIF_SUM,
]

_EXEC_PCT_KEYS = (
    "pct_agendamento", "pct_comparecimento", "pct_conversao",
    "pct_vendas", "pct_venda_lead", "ticket_medio", "pct_recebimento",
)


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
        # Default derivado de `_EXEC_SUM` (inclui buckets) + as 7 pcts derivadas.
        # Garante que a UI possa acessar k["oportunidades_mais_12"] etc. sem KeyError
        # quando o filtro de período não retorna linhas.
        return {**{k: 0 for k in _EXEC_SUM}, **{k: 0 for k in _EXEC_PCT_KEYS}}

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


_RANKING_BASE_COLS = (
    "oportunidades", "agendamentos", "comparecimentos",
    "vendas", "montante", "receita",
    "perdidos", "cancelados", "churn", "vencidos",
    "novos", "ascensoes", "renovacoes", "indicacoes",
    "lead_in_consultoria_gratuita",
    *_EXEC_CLASSIF_SUM,
)

# Métricas do Top Closers — fonte única p/ Visão Geral e Executivas & Times.
EXECUTIVAS_RANKING_METRIC_OPTIONS: dict[str, str] = {
    "Receita":          "receita",
    "Montante":         "montante",
    "Vendas":           "vendas",
    "Agendamentos":     "agendamentos",
    "Comparecimentos":  "comparecimentos",
    "Comparecimentos (ajustado teste)": "comparecimentos_ajustado",
    "Ganhos +12":       "ganhos_mais_12",
    "Ganhos -12":       "ganhos_menos_12",
    "Ganhos Não atua":  "ganhos_nao_atua",
    "Cancelados":       "cancelados",
    "Clientes Cancelados": "churn",
    "Vencidos":         "vencidos",
}
EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS = frozenset({
    "receita", "montante",
    "receita_mais_12", "receita_menos_12", "receita_nao_atua",
    "montante_mais_12", "montante_menos_12", "montante_nao_atua",
})
EXECUTIVAS_RANKING_METRICAS_NEUTRAS = frozenset({
    "receita", "montante", "vendas", "agendamentos", "comparecimentos",
    "comparecimentos_ajustado",
})

RANKING_EXIBICAO_ATIVOS = "Somente ativos"
RANKING_EXIBICAO_HISTORICO = "Histórico geral"
RANKING_EXIBICAO_OPCOES = (RANKING_EXIBICAO_ATIVOS, RANKING_EXIBICAO_HISTORICO)
_RANKING_DERIVED_COLS = ("pct_agendamento", "pct_comparecimento",
                         "pct_conversao", "pct_vendas",
                         "pct_recebimento", "ticket_medio")
RANKING_FULL_SCHEMA = ("executiva",) + _RANKING_BASE_COLS + _RANKING_DERIVED_COLS


def executivas_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """Ranking por executiva: absolutos + taxas recalculadas.

    Sempre devolve um DataFrame com `RANKING_FULL_SCHEMA` (mesmo vazio).
    Colunas absolutas ausentes na view são preenchidas com 0 antes do cálculo
    das taxas, evitando KeyError em produção quando a view tiver schema
    levemente diferente do esperado em dev."""
    if df.empty or "executiva" not in df.columns:
        return pd.DataFrame(columns=list(RANKING_FULL_SCHEMA))

    cols = [c for c in _EXEC_SUM if c in df.columns]
    agg = df.groupby("executiva", as_index=False)[cols].sum()

    # Garante presença de TODAS as colunas absolutas usadas nas taxas.
    for c in _RANKING_BASE_COLS:
        if c not in agg.columns:
            agg[c] = 0

    agg["pct_agendamento"]    = agg.apply(lambda r: _safe_div(r["agendamentos"], r["oportunidades"]) * 100, axis=1)
    agg["pct_comparecimento"] = agg.apply(lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100, axis=1)
    agg["pct_conversao"]      = agg.apply(lambda r: _safe_div(r["vendas"], r["agendamentos"]) * 100, axis=1)
    agg["pct_vendas"]         = agg.apply(lambda r: _safe_div(r["vendas"], r["comparecimentos"]) * 100, axis=1)
    agg["pct_recebimento"]    = agg.apply(lambda r: _safe_div(r["receita"], r["montante"]) * 100, axis=1)
    agg["ticket_medio"]       = agg.apply(lambda r: _safe_div(r["montante"], r["vendas"]), axis=1)

    return agg.sort_values("receita", ascending=False).reset_index(drop=True)


def _build_executivas_oficiais_tokens(
    df_oficiais: pd.DataFrame,
) -> list[tuple[str, set[str]]]:
    oficiais_tokens: list[tuple[str, set[str]]] = []
    if df_oficiais is None or df_oficiais.empty or "nome" not in df_oficiais.columns:
        return oficiais_tokens
    for nome in df_oficiais["nome"].dropna().tolist():
        toks = set(_tokens_nome_ranking(nome))
        if toks:
            oficiais_tokens.append((nome, toks))
    return oficiais_tokens


def executivas_churn_filtrar_recorte(
    df_churn: pd.DataFrame,
    data_ini,
    data_fim,
    times_sel: list | None = None,
) -> pd.DataFrame:
    """Churns no período + filtro opcional de TIMES (`time_vendas`)."""
    if df_churn is None or df_churn.empty:
        return df_churn
    out = churn_pos_filtrar_periodo(df_churn, data_ini, data_fim)
    if not times_sel or out.empty or "time_vendas" not in out.columns:
        return out
    mask = pd.Series(False, index=out.index)
    for t in times_sel:
        mask |= out["time_vendas"].astype(str).str.strip() == str(t).strip()
    return out.loc[mask].copy()


def executivas_churn_total(df_churn: pd.DataFrame) -> int:
    if df_churn is None or df_churn.empty or "deal_id" not in df_churn.columns:
        return 0
    return int(df_churn["deal_id"].nunique())


def executivas_churn_resolver_closer(
    nome,
    df_oficiais: pd.DataFrame | None,
) -> str:
    """Closer do deal Churn — cadastro oficial por tokens; senão nome do Zoho."""
    raw = (nome if isinstance(nome, str) else "") or ""
    raw = raw.strip()
    if not raw:
        return CHURN_SEM_CLOSER
    tokens = _build_executivas_oficiais_tokens(df_oficiais)
    if tokens:
        canon = _match_oficial_por_tokens(raw, tokens)
        if canon:
            return canon
    return raw


def _executivas_churn_nomes_casam(nome_a: str, nome_b: str) -> bool:
    """True quando os dois nomes são o mesmo closer (exato ou por tokens)."""
    a = (nome_a or "").strip()
    b = (nome_b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    ta = set(_tokens_nome_ranking(a))
    tb = set(_tokens_nome_ranking(b))
    if not ta or not tb:
        return False
    return ta == tb or ta.issubset(tb) or tb.issubset(ta)


def executivas_churn_agregar_por_executiva(
    df_churn: pd.DataFrame,
    df_oficiais: pd.DataFrame | None,
) -> pd.DataFrame:
    """COUNT DISTINCT deal_id por closer — mesma base do card Churn."""
    if df_churn is None or df_churn.empty:
        return pd.DataFrame(columns=["executiva", "churn"])
    tmp = df_churn.copy()
    tmp["executiva"] = tmp["closer_nome"].apply(
        lambda n: executivas_churn_resolver_closer(n, df_oficiais)
    )
    return (
        tmp.groupby("executiva", as_index=False)
        .agg(churn=("deal_id", "nunique"))
        .sort_values("churn", ascending=False)
        .reset_index(drop=True)
    )


def executivas_churn_contagem_para_executiva(
    executiva: str,
    churn_por_executiva: pd.DataFrame,
) -> int:
    """Soma churns do agg que casam com `executiva` (nome do ranking)."""
    if churn_por_executiva is None or churn_por_executiva.empty:
        return 0
    total = 0
    for _, row in churn_por_executiva.iterrows():
        if _executivas_churn_nomes_casam(executiva, str(row["executiva"])):
            total += int(row["churn"] or 0)
    return total


def executivas_ranking_com_churn(
    ranking: pd.DataFrame,
    churn_por_executiva: pd.DataFrame,
) -> pd.DataFrame:
    """Injeta `churn` no ranking e inclui closers que só têm churn no período."""
    if churn_por_executiva is None or churn_por_executiva.empty:
        if ranking is None or ranking.empty:
            return ranking
        out = ranking.copy()
        out["churn"] = 0
        return out

    if ranking is None or ranking.empty:
        out = churn_por_executiva.copy()
        for col in _RANKING_BASE_COLS:
            if col not in out.columns:
                out[col] = 0
        return out

    out = ranking.copy()
    out["churn"] = out["executiva"].apply(
        lambda ex: executivas_churn_contagem_para_executiva(ex, churn_por_executiva)
    )

    # Closers presentes só no churn (ex.: sem linha na view no período).
    extra_rows: list[dict] = []
    for _, row in churn_por_executiva.iterrows():
        nom = str(row["executiva"])
        if int(row["churn"] or 0) <= 0:
            continue
        if any(_executivas_churn_nomes_casam(ex, nom) for ex in out["executiva"]):
            continue
        extra = {c: 0 for c in out.columns}
        extra["executiva"] = nom
        extra["churn"] = int(row["churn"])
        extra_rows.append(extra)

    if extra_rows:
        out = pd.concat([out, pd.DataFrame(extra_rows)], ignore_index=True)

    return out


def executivas_ranking_plot_churn(churn_por_executiva: pd.DataFrame) -> pd.DataFrame:
    """DataFrame pronto pro gráfico Top Closers > Churn (mesma base do card)."""
    if churn_por_executiva is None or churn_por_executiva.empty:
        return pd.DataFrame(columns=["executiva", "churn"])
    plot = churn_por_executiva[churn_por_executiva["churn"].fillna(0) > 0].copy()
    return plot.sort_values("churn", ascending=False).reset_index(drop=True)


def executivas_churn_filtrar_closer(
    df_churn: pd.DataFrame,
    closer_nome: str,
    df_oficiais: pd.DataFrame | None,
) -> pd.Series:
    """Mask de linhas de churn do closer (nome canônico ou exibido no ranking)."""
    if df_churn is None or df_churn.empty:
        idx = df_churn.index if df_churn is not None else []
        return pd.Series(False, index=idx)
    nome = (closer_nome or "").strip()
    if not nome:
        return pd.Series(False, index=df_churn.index)

    resolved = df_churn["closer_nome"].apply(
        lambda n: executivas_churn_resolver_closer(n, df_oficiais)
    )
    alvo = executivas_churn_resolver_closer(nome, df_oficiais)
    return resolved.astype(str).str.strip() == alvo.strip()


# ---------------------------------------------------------------------------
# Ranking — partição principal × complementar (consumido por Time de Vendas
# → Visão Geral e Executivas & Times). Mantém uma fonte única para a ordem
# e a regra de partição, pra evitar drift entre as duas páginas.
# ---------------------------------------------------------------------------

COLUNAS_PRINCIPAIS_RANKING = [
    "executiva",
    "oportunidades",
    "agendamentos",
    "comparecimentos",
    "vendas",
    "montante",
    "receita",
    "pct_comparecimento",
    "pct_conversao",
    "pct_vendas",
    "pct_recebimento",
    "ticket_medio",
]


# Conectores de nome ("Maria DE Lima", "Pedro DA Silva") — descartados na
# tokenização para o match com o cadastro oficial. Lista fechada
# propositalmente curta: só conectores PT-BR que aparecem em nomes
# próprios. NÃO incluir sobrenomes curtos tipo "Sá" ou "Lê".
_RANKING_CONECTORES_NOME = frozenset({"de", "da", "do", "das", "dos", "e"})


def _normalize_nome_ranking(nome) -> str:
    """NFD + lowercase + collapse de espaços. Mantém só letras/dígitos/espaços."""
    if not isinstance(nome, str):
        return ""
    import unicodedata
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _tokens_nome_ranking(nome) -> list[str]:
    """Tokens relevantes do nome (sem acentos, sem conectores PT-BR)."""
    norm = _normalize_nome_ranking(nome)
    if not norm:
        return []
    return [t for t in norm.split() if t and t not in _RANKING_CONECTORES_NOME]


def _match_oficial_por_tokens(nome_ranking: str,
                              oficiais_tokens: list[tuple[str, set[str]]]) -> str:
    """Devolve o nome oficial canônico quando o ranking name casa por tokens.

    Regra: todos os tokens relevantes do nome do ranking precisam estar
    presentes no conjunto de tokens do oficial. Trata abreviações comuns
    (`Nathan Carloto` ↔ `Nathan Carloto Ferreira Dos Santos`) sem aceitar
    match só pelo primeiro nome (que seria ambíguo entre 2 oficiais com
    mesmo primeiro nome). Devolve `""` quando 0 ou >1 oficiais batem."""
    raw_tokens = _tokens_nome_ranking(nome_ranking)
    if not raw_tokens:
        return ""
    raw_set = set(raw_tokens)
    matches = [
        nome_oficial for nome_oficial, off_tokens in oficiais_tokens
        if raw_set.issubset(off_tokens)
    ]
    if len(matches) == 1:
        return matches[0]
    # Desempate: match exato em todos os tokens (sem extras no oficial).
    if len(matches) > 1:
        exatos = [
            n for n, off_tokens in oficiais_tokens
            if n in matches and off_tokens == raw_set
        ]
        if len(exatos) == 1:
            return exatos[0]
    return ""


# Overrides de `time_vendas` por closer — espelha o CASE da view quando o
# cadastro ainda não reflete o time correto (ex.: Stefany Campinas).
_EXECUTIVA_TIME_OVERRIDES: list[tuple[frozenset[str], str]] = [
    (frozenset({"stefany", "campinas"}), "Time da Leidianne"),
]


def executivas_aplicar_time_vendas_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Ajusta `time_vendas` por match de tokens no nome da executiva."""
    if df is None or df.empty or "executiva" not in df.columns:
        return df
    if "time_vendas" not in df.columns:
        return df
    out = df.copy()
    for idx, nome in out["executiva"].items():
        if not isinstance(nome, str) or not nome.strip():
            continue
        toks = set(_tokens_nome_ranking(nome))
        if not toks:
            continue
        for required, time_nome in _EXECUTIVA_TIME_OVERRIDES:
            if required.issubset(toks):
                out.at[idx, "time_vendas"] = time_nome
                break
    return out


def executivas_filtrar_time_oficial(
    df: pd.DataFrame,
    df_oficiais: pd.DataFrame,
) -> pd.DataFrame:
    """Filtra `df` linha-a-linha — só mantém rows cuja `executiva` pertence
    ao cadastro oficial ativo do Vendas (`fdw_reconecta.executivas_vendas`).

    Grão de entrada: 1 row por `(data_ref × executiva × time_vendas × …)`,
    saída de `get_executivas()`. Aplica a mesma regra de tokens usada em
    `executivas_ranking_oficiais` (subset de tokens normalizados, sem
    conectores PT-BR) e sobrescreve `executiva` pelo nome OFICIAL canônico
    já no nível das linhas — assim `executivas_kpis`, `executivas_por_dia`,
    `executivas_por_time` e `executivas_ranking`, que vão consumir esse
    `df` depois, operam todos no mesmo universo e com a mesma grafia.

    Depois desse filtro, chamar de novo `executivas_ranking_oficiais` no
    ranking agregado vira no-op (todo nome já é oficial). Mantida como
    função pública para casos onde só o ranking pré-agregado existe (ex.:
    fontes que vêm de outras queries).

    Fallback: `df_oficiais` None/vazio ou sem coluna `nome` → devolve `df`
    intacto. Caller decide se exibe aviso.
    """
    if df is None or df.empty or "executiva" not in df.columns:
        return df
    if (df_oficiais is None or df_oficiais.empty
            or "nome" not in df_oficiais.columns):
        return df

    oficiais_tokens: list[tuple[str, set[str]]] = []
    for nome in df_oficiais["nome"].dropna().tolist():
        toks = set(_tokens_nome_ranking(nome))
        if toks:
            oficiais_tokens.append((nome, toks))
    if not oficiais_tokens:
        return df

    out = df.copy()
    out["_nome_oficial"] = out["executiva"].apply(
        lambda nome: _match_oficial_por_tokens(nome, oficiais_tokens)
    )
    out = out[out["_nome_oficial"] != ""].copy()
    if out.empty:
        return out.drop(columns=["_nome_oficial"])
    out["executiva"] = out["_nome_oficial"]
    return out.drop(columns=["_nome_oficial"]).reset_index(drop=True)


def executivas_canonicalizar_executivas(
    df: pd.DataFrame,
    df_oficiais: pd.DataFrame,
) -> pd.DataFrame:
    """Normaliza `executiva` pelo cadastro oficial sem remover linhas.

    Modo histórico do Top Closers: mantém qualquer closer com dados no
    período (já filtrados por TIMES no header) e só troca o nome quando
    há match por tokens no cadastro (ativo ou inativo).
    """
    if df is None or df.empty or "executiva" not in df.columns:
        return df
    oficiais_tokens = _build_executivas_oficiais_tokens(df_oficiais)
    if not oficiais_tokens:
        return df

    out = df.copy()

    def _nome_exibicao(nome) -> str:
        raw = (nome if isinstance(nome, str) else "") or ""
        raw = raw.strip()
        if not raw:
            return raw
        canon = _match_oficial_por_tokens(raw, oficiais_tokens)
        return canon if canon else raw

    out["executiva"] = out["executiva"].apply(_nome_exibicao)
    return out.reset_index(drop=True)


def executivas_ranking_base_exibicao(
    exibicao: str,
    df_bruto: pd.DataFrame,
    df_filtrado: pd.DataFrame,
    df_oficiais_ativos: pd.DataFrame | None,
    df_oficiais_todos: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Base linha-a-linha do ranking + cadastro usado no match de nomes."""
    if exibicao == RANKING_EXIBICAO_HISTORICO:
        cadastro = df_oficiais_todos
        if cadastro is None or cadastro.empty:
            cadastro = df_oficiais_ativos
        base = executivas_canonicalizar_executivas(df_bruto, cadastro)
        return base, cadastro

    return df_filtrado, df_oficiais_ativos


def executivas_ranking_oficiais(
    df_ranking: pd.DataFrame,
    df_oficiais: pd.DataFrame,
) -> pd.DataFrame:
    """Mantém no ranking só executivas presentes no cadastro oficial ativo.

    Fluxo:
    1. Tokeniza cada `executiva` do ranking e cada `nome` do cadastro
       oficial (remove acentos, lowercase, descarta conectores PT-BR).
    2. Considera match quando todos os tokens do ranking estão contidos
       nos tokens do oficial — cobre `Nathan Carloto` ↔ `Nathan Carloto
       Ferreira Dos Santos`, `Leandro Alves` ↔ `Leandro Marcelino Alves`
       e `Thaís Cadó` ↔ `Thaís Salgado Cadó` (validado em mai/2026).
    3. Quando 1 oficial bate, sobrescreve `executiva` pelo nome oficial
       (canônico) — padroniza grafia entre as duas páginas.

    Fallback intencional: se `df_oficiais` vier vazio/None, devolve o
    ranking SEM filtro. A view chamadora decide se exibe aviso. Isso
    evita derrubar o dashboard quando a FDW está indisponível.

    Não usa `id_crm` ainda porque a view `bi.vw_dashboard_comercial_
    executivas_rw` não expõe o ID Zoho da executiva — só o nome
    resolvido via `zoho_users`. Evolução futura: passar a query para
    fontes diretas (zoho_deals + zoho_users) expondo o ID e trocar este
    filtro por INNER JOIN em `id_crm`.
    """
    if df_ranking is None or df_ranking.empty:
        return df_ranking
    if (df_oficiais is None or df_oficiais.empty
            or "nome" not in df_oficiais.columns
            or "executiva" not in df_ranking.columns):
        return df_ranking

    oficiais_tokens = []
    for nome in df_oficiais["nome"].dropna().tolist():
        toks = set(_tokens_nome_ranking(nome))
        if toks:
            oficiais_tokens.append((nome, toks))
    if not oficiais_tokens:
        return df_ranking

    out = df_ranking.copy()
    out["_nome_oficial"] = out["executiva"].apply(
        lambda nome: _match_oficial_por_tokens(nome, oficiais_tokens)
    )
    out = out[out["_nome_oficial"] != ""].copy()
    if out.empty:
        return out.drop(columns=["_nome_oficial"])
    out["executiva"] = out["_nome_oficial"]
    return out.drop(columns=["_nome_oficial"]).reset_index(drop=True)


def ranking_dividir_principal_detalhado(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide o ranking em `(principal, detalhado)`.

    `principal` segue a ordem de `COLUNAS_PRINCIPAIS_RANKING`, descartando
    silenciosamente qualquer coluna ausente — a UI não quebra quando a
    view sofre schema drift. `detalhado` traz `executiva` como 1ª coluna
    (quando existir) seguida das demais colunas que ficaram de fora da
    principal, preservando a ordem original do df de entrada."""
    if df is None or df.empty:
        empty = pd.DataFrame()
        return empty, empty

    cols_principais = [c for c in COLUNAS_PRINCIPAIS_RANKING if c in df.columns]
    df_principal = df[cols_principais].copy() if cols_principais else pd.DataFrame()

    cols_resto = [c for c in df.columns if c not in cols_principais]
    if "executiva" in df.columns and cols_resto:
        cols_detalhe = ["executiva"] + [c for c in cols_resto if c != "executiva"]
    else:
        cols_detalhe = cols_resto
    df_detalhado = df[cols_detalhe].copy() if cols_detalhe else pd.DataFrame()

    return df_principal, df_detalhado


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
# Detalhe linha-a-linha de Vendas — alimenta o Top Closers de Executivas &
# Times e da Visão Geral. Fonte: prevendas_leads_detalhe_diario.sql (a
# mesma query é consumida pelas duas áreas; cache é compartilhado via
# get_vendas_leads_detalhe_diario → get_prevendas_leads_detalhe_diario).
#
# Pré-vendas tem helpers próprios em src/prevendas_transforms.py; os de
# Vendas vivem aqui pra não atravessar fronteira de módulo. O normalizador
# de Vendas reaproveita o de Pré-vendas e só acrescenta `time_vendas_filtro`.
# ---------------------------------------------------------------------------

def vendas_normalizar_detalhe(df_det: pd.DataFrame) -> pd.DataFrame:
    """Enriquece o detalhe diário pra consumo no Top Closers de Vendas.

    Aplica a normalização canônica (mesmas colunas `*_filtro` que
    `prevendas_normalizar_detalhe` produz: classificacao_filtro,
    classificacao_crm_filtro, classificacao_final_filtro, email_lead_filtro,
    email_crm_filtro, email_final_filtro, sdr_filtro, closer_filtro, status_filtro,
    tipo_registro_base_filtro, nome_cliente_view) e acrescenta
    `time_vendas_filtro` — disponível após a inclusão de `time_vendas` em
    prevendas_leads_detalhe_diario.sql.

    Import de `prevendas_normalizar_detalhe` é lazy/local porque
    `prevendas_transforms` importa `_safe_div` daqui — top-level criaria
    ciclo. Como a função é chamada em runtime (request da página, não na
    importação), o lazy import resolve antes de qualquer uso real.
    """
    if df_det is None or df_det.empty:
        return df_det
    from .prevendas_transforms import (
        prevendas_normalizar_detalhe as _prevendas_normalizar_detalhe,
    )
    out = _prevendas_normalizar_detalhe(df_det)
    if out is None or out.empty:
        return out
    if "time_vendas" in out.columns:
        out["time_vendas_filtro"] = (
            out["time_vendas"].fillna("").astype(str).str.strip()
            .replace("", "Sem time definido")
        )
    else:
        out["time_vendas_filtro"] = "Sem time definido"
    return out


def vendas_detalhe_mask_por_metrica(df_det_norm: pd.DataFrame,
                                    metrica: str,
                                    data_ini,
                                    data_fim) -> pd.Series:
    """Mask booleana sobre o detalhe normalizado pra Vendas, por métrica.

    Universo do detalhe (`activity_rows` ∪ `sales_rows`) cobre:
      - agendamentos / mais_12 / menos_12 / nao_atua / sem_classificacao
      - comparecimentos / <buckets>
      - vendas (sinônimo: ganhos) / <buckets>
      - montante  / <buckets>            (universo = vendas)
      - receita   / <buckets>            (universo = vendas)
      - cancelados, vencidos             (status_reuniao)

    Métricas SEM cobertura no detalhe → devolve all-False:
      oportunidades, perdidos, lead_in_consultoria_gratuita,
      novos/ascensoes/renovacoes/indicacoes, leads_lp_form.

    ⚠ Classificação no detalhe usa 2 fontes (`lead_classification` CRM +
    `classificado` ext.leads), enquanto a view usa 4 fontes
    (adiciona `qualificacao` + `classificado_cal`). Pode haver pequena
    divergência quando um deal está classificado apenas pelas 2 fontes
    extras. A UI deve avisar nessas seções (`if contagem_tabela ≠
    contagem_grafico:` no padrão do Top SDRs de Pré-vendas).
    """
    if df_det_norm is None or df_det_norm.empty:
        idx = df_det_norm.index if df_det_norm is not None else []
        return pd.Series(False, index=idx)

    ini = pd.Timestamp(data_ini)
    fim = pd.Timestamp(data_fim)

    base_atividade = df_det_norm["tipo_registro_base_filtro"] == "Atividade"
    base_venda     = df_det_norm["tipo_registro_base_filtro"] == "Venda"

    em_agend = (
        df_det_norm["data_agendamento"].notna()
        & df_det_norm["data_agendamento"].between(ini, fim, inclusive="both")
    )
    em_vnd = (
        df_det_norm["data_venda"].notna()
        & df_det_norm["data_venda"].between(ini, fim, inclusive="both")
    )

    classif_crm = df_det_norm.get(
        "classificacao_crm_filtro",
        pd.Series("", index=df_det_norm.index),
    )
    classif_ext = df_det_norm["classificacao_filtro"]

    flag_mais_12  = (classif_crm == "Atua +12") | (classif_ext == "Atua +12")
    flag_menos_12 = (classif_crm == "Atua -12") | (classif_ext == "Atua -12")
    flag_nao_atua = (classif_crm == "Não atua")  | (classif_ext == "Não atua")

    # Bucket exclusivo +12 > -12 > Não atua > Sem classif (espelha view).
    is_mais_12  = flag_mais_12
    is_menos_12 = ~flag_mais_12 & flag_menos_12
    is_nao_atua = ~flag_mais_12 & ~flag_menos_12 & flag_nao_atua
    is_sem_clf  = ~flag_mais_12 & ~flag_menos_12 & ~flag_nao_atua

    status_concluida = df_det_norm["status_filtro"].isin(["Concluída", "Concluído"])
    status_cancelada = df_det_norm["status_filtro"].isin(["Cancelada", "Cancelado"])
    status_vencida   = df_det_norm["status_filtro"] == "Vencida"

    # ----- agendamentos
    if metrica == "agendamentos":
        return base_atividade & em_agend
    if metrica == "agendamentos_mais_12":
        return base_atividade & em_agend & is_mais_12
    if metrica == "agendamentos_menos_12":
        return base_atividade & em_agend & is_menos_12
    if metrica == "agendamentos_nao_atua":
        return base_atividade & em_agend & is_nao_atua
    if metrica == "agendamentos_sem_classificacao":
        return base_atividade & em_agend & is_sem_clf

    # ----- comparecimentos
    if metrica == "comparecimentos":
        return base_atividade & em_agend & status_concluida
    if metrica == "comparecimentos_mais_12":
        return base_atividade & em_agend & status_concluida & is_mais_12
    if metrica == "comparecimentos_menos_12":
        return base_atividade & em_agend & status_concluida & is_menos_12
    if metrica == "comparecimentos_nao_atua":
        return base_atividade & em_agend & status_concluida & is_nao_atua
    if metrica == "comparecimentos_sem_classificacao":
        return base_atividade & em_agend & status_concluida & is_sem_clf

    # ----- vendas / ganhos (sinônimos no contexto do detalhe)
    if metrica in ("vendas", "ganhos"):
        return base_venda & em_vnd
    if metrica in ("ganhos_mais_12", "vendas_mais_12"):
        return base_venda & em_vnd & is_mais_12
    if metrica in ("ganhos_menos_12", "vendas_menos_12"):
        return base_venda & em_vnd & is_menos_12
    if metrica in ("ganhos_nao_atua", "vendas_nao_atua"):
        return base_venda & em_vnd & is_nao_atua
    if metrica in ("ganhos_sem_classificacao", "vendas_sem_classificacao"):
        return base_venda & em_vnd & is_sem_clf

    # ----- financeiros: mesmo universo de vendas (caller soma montante/receita)
    if metrica in ("montante", "receita"):
        return base_venda & em_vnd
    if metrica in ("montante_mais_12", "receita_mais_12"):
        return base_venda & em_vnd & is_mais_12
    if metrica in ("montante_menos_12", "receita_menos_12"):
        return base_venda & em_vnd & is_menos_12
    if metrica in ("montante_nao_atua", "receita_nao_atua"):
        return base_venda & em_vnd & is_nao_atua

    # ----- status auxiliares
    if metrica == "cancelados":
        return base_atividade & em_agend & status_cancelada
    if metrica == "churn":
        # Churn (stage Churn) não vem do detalhe de activities — caller usa
        # `executivas_churn_filtrar_closer` sobre o dataset de churn deals.
        return pd.Series(False, index=df_det_norm.index)
    if metrica == "vencidos":
        return base_atividade & em_agend & status_vencida

    return pd.Series(False, index=df_det_norm.index)


# Valores canônicos de `zoho_deals.forma_venda` — espelham
# one_page_novos_forma_venda.sql (card Novos da One Page).
FORMA_VENDA_EM_CALL = "Em call"
FORMA_VENDA_FOLLOW_UP = "Follow up"


def vendas_forma_venda_breakdown(
    df_det_norm: pd.DataFrame,
    data_ini,
    data_fim,
    closer: str | None = None,
) -> dict[str, int]:
    """Contagem Em call / Follow up no universo de vendas do Top Closers.

    Usa o detalhe linha-a-linha (`tipo_registro_base = Venda`, compra no
    período) com os mesmos filtros de closer/time já aplicados em
    `df_det_norm`. A classificação segue `forma_venda` do deal — mesma
    regra do card Novos na One Page (`one_page_novos_forma_venda.sql`).

    O total principal do card Vendas continua vindo do ranking; este dict
    alimenta apenas o detalhamento. `sem_classificacao` cobre deals sem
    `forma_venda` reconhecida (null, vazio ou valor fora de Em call/Follow).
    """
    empty = {
        "em_call": 0,
        "follow": 0,
        "sem_classificacao": 0,
        "detalhe_total": 0,
    }
    if df_det_norm is None or df_det_norm.empty:
        return empty

    mask = vendas_detalhe_mask_por_metrica(df_det_norm, "vendas", data_ini, data_fim)
    if closer is not None:
        mask &= vendas_detalhe_filtrar_closer(df_det_norm, closer)

    vendas_df = df_det_norm.loc[mask]
    if vendas_df.empty or "deal_id" not in vendas_df.columns:
        return empty

    deals = vendas_df.drop_duplicates(subset=["deal_id"], keep="first")
    detalhe_total = int(deals["deal_id"].nunique(dropna=False))

    forma_col = deals.get("forma_venda", pd.Series("", index=deals.index))
    forma = forma_col.fillna("").astype(str).str.strip()

    em_call = int((forma == FORMA_VENDA_EM_CALL).sum())
    follow = int((forma == FORMA_VENDA_FOLLOW_UP).sum())
    sem_classificacao = max(0, detalhe_total - em_call - follow)

    return {
        "em_call": em_call,
        "follow": follow,
        "sem_classificacao": sem_classificacao,
        "detalhe_total": detalhe_total,
    }


def vendas_forma_venda_breakdown_rows(
    breakdown: dict[str, int],
) -> list[tuple[str, int]]:
    """Linhas (rótulo, contagem bruta) para o breakdown do card Vendas."""
    rows: list[tuple[str, int]] = [
        ("Em call", int(breakdown.get("em_call", 0))),
        ("Follow up", int(breakdown.get("follow", 0))),
    ]
    sem = int(breakdown.get("sem_classificacao", 0))
    if sem > 0:
        rows.append(("Sem forma", sem))
    return rows


# ---------------------------------------------------------------------------
# Comparecimento ajustado (teste operacional — Executivas & Times)
# ---------------------------------------------------------------------------

_COMPARECIMENTO_AJUSTADO_TZ = ZoneInfo("America/Sao_Paulo")

COMPARECIMENTO_AJUSTADO_HELP = (
    "Comparecimento ajustado = status Concluída/Concluído + reuniões ainda "
    "Agendada cujo horário previsto já encerrou (fim da reunião ≤ agora, "
    "America/Sao_Paulo). Em andamento e futuras não entram. Canceladas, "
    "No-show e Vencidas não entram."
)

_COMPARECIMENTO_AJUSTADO_AGG_COLS = (
    "comparecimentos_zoho",
    "agendadas_horario_encerrado",
    "comparecimentos_ajustado",
    "noshow",
    "canceladas",
)

COMPARECIMENTO_CONFERENCIA_CLASSIF_OPCOES: tuple[str, ...] = (
    "Todas",
    "Concluídas no Zoho",
    "Agendadas futuras",
    "Agendadas em andamento",
    "Agendadas com horário encerrado",
    "No-show",
    "Canceladas",
    "Vencidas",
)

_COMPARECIMENTO_CLASSIF_DASHBOARD_LABELS: dict[str, str] = {
    "Concluídas no Zoho": "Concluída no Zoho",
    "Agendadas futuras": "Agendada futura",
    "Agendadas em andamento": "Agendada em andamento",
    "Agendadas com horário encerrado": "Agendada com horário encerrado",
    "No-show": "No-show",
    "Canceladas": "Cancelada",
    "Vencidas": "Vencida",
}

_COMPARECIMENTO_OBSERVACAO: dict[str, str] = {
    "Concluída no Zoho": "Status oficial concluído",
    "Agendada futura": "Reunião ainda não iniciada",
    "Agendada em andamento": "Reunião em curso (entre início e fim previstos)",
    "Agendada com horário encerrado": (
        "Possível reunião realizada ainda não atualizada no Zoho"
    ),
    "No-show": "Marcada como No-show",
    "Cancelada": "Reunião cancelada",
    "Vencida": "Reunião vencida/pendente fora da regra",
    "Outro": "Fora das classificações do teste",
}

LISTA_LEIDIANNE_COMPARECIMENTOS: dict[str, int] = {
    "Stefany Campinas": 10,
    "Hawinne Cristina de Oliveira Freitas": 8,
    "Leandro Alves": 6,
    "Andrezza Ayuso Serpa": 4,
    "Nathan Carloto": 4,
    "Leonardo Melo Patriota": 4,
}


def comparecimento_ajustado_agora_brt() -> pd.Timestamp:
    """Instante atual em America/Sao_Paulo, sem tz (pareado com start_datetime)."""
    return pd.Timestamp.now(tz=_COMPARECIMENTO_AJUSTADO_TZ).tz_localize(None)


def _comparecimento_ajustado_ts_naive_brt(series: pd.Series) -> pd.Series:
    """`timestamp without time zone` = horário de parede BRT."""
    st = pd.to_datetime(series, errors="coerce")
    if getattr(st.dt, "tz", None) is not None:
        st = st.dt.tz_convert(_COMPARECIMENTO_AJUSTADO_TZ).dt.tz_localize(None)
    return st


def _comparecimento_ajustado_start_naive_brt(series: pd.Series) -> pd.Series:
    """Alias para `start_datetime` / `end_datetime` sem tz."""
    return _comparecimento_ajustado_ts_naive_brt(series)


def _comparecimento_ajustado_fim_reuniao_ref(
    df: pd.DataFrame,
    *,
    start: pd.Series | None = None,
) -> pd.Series:
    """COALESCE(end_datetime, start_datetime + 1 hour) em horário BRT."""
    if start is None:
        start = _comparecimento_ajustado_start_naive_brt(df["start_datetime"])
    if "end_datetime" in df.columns:
        end = _comparecimento_ajustado_ts_naive_brt(df["end_datetime"])
    else:
        end = pd.Series(pd.NaT, index=df.index)
    return end.where(end.notna(), start + pd.Timedelta(hours=1))


def _comparecimento_ajustado_format_data_hora_reuniao(
    start: pd.Series,
    end: pd.Series | None = None,
) -> pd.Series:
    """Exibição: `24/06/2026 · 17:30 - 18:30` (fim com fallback +1h se nulo)."""
    st = _comparecimento_ajustado_ts_naive_brt(start)
    if end is not None:
        en = _comparecimento_ajustado_ts_naive_brt(end)
    else:
        en = pd.Series(pd.NaT, index=st.index)
    fim = en.where(en.notna(), st + pd.Timedelta(hours=1))
    out = pd.Series("", index=st.index, dtype=object)
    mask = st.notna()
    if mask.any():
        out.loc[mask] = (
            st.loc[mask].dt.strftime("%d/%m/%Y")
            + " · "
            + st.loc[mask].dt.strftime("%H:%M")
            + " - "
            + fim.loc[mask].dt.strftime("%H:%M")
        )
    return out


def _comparecimento_ajustado_stage_is_noshow(stage: pd.Series) -> pd.Series:
    """No-show pelo stage do deal (inclui 'Não compareceu' e variações)."""
    norm = stage.fillna("").astype(str).map(_normalize_nome_ranking)
    return (
        norm.str.contains("no-show", na=False)
        | norm.str.contains("no show", na=False)
        | norm.str.contains("nao compareceu", na=False)
    )


def comparecimento_ajustado_classificacao_dashboard(
    df: pd.DataFrame,
    agora_brt: pd.Timestamp,
) -> pd.Series:
    """Classificação única por linha — prioridade: No-show > Cancelada > Vencida >
    Concluída no Zoho > Agendada futura > Agendada em andamento >
    Agendada com horário encerrado > Outro."""
    start = _comparecimento_ajustado_start_naive_brt(df["start_datetime"])
    fim = _comparecimento_ajustado_fim_reuniao_ref(df, start=start)
    status = df["status_reuniao"].astype(str).str.strip()
    status_lower = status.str.lower()
    stage = df.get("deal_stage", pd.Series("", index=df.index)).fillna("").astype(str)

    is_noshow = _comparecimento_ajustado_stage_is_noshow(stage)
    is_cancel = status_lower.isin(["cancelada", "cancelado"])
    is_vencida = status_lower.eq("vencida")
    is_zoho = status.isin(["Concluída", "Concluído"])
    is_agendada = status.isin(["Agendada", "Agendado"])
    has_start = start.notna()
    is_futura = is_agendada & has_start & (start > agora_brt)
    is_andamento = (
        is_agendada & has_start & (start <= agora_brt) & fim.notna() & (fim > agora_brt)
    )
    is_encerrado = is_agendada & has_start & fim.notna() & (fim <= agora_brt)

    cls = pd.Series("Outro", index=df.index, dtype=object)
    cls = cls.mask(is_encerrado, "Agendada com horário encerrado")
    cls = cls.mask(is_andamento, "Agendada em andamento")
    cls = cls.mask(is_futura, "Agendada futura")
    cls = cls.mask(is_zoho, "Concluída no Zoho")
    cls = cls.mask(is_vencida, "Vencida")
    cls = cls.mask(is_cancel & ~is_noshow, "Cancelada")
    cls = cls.mask(is_noshow, "No-show")
    return cls


def comparecimento_ajustado_aplicar_flags(
    df: pd.DataFrame,
    agora_brt: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Fonte única das flags — compara data+hora completas em BRT.

    `start_datetime` no banco é `timestamp without time zone` (horário BRT).
    Não usar comparação com `now()` timestamptz (sessão UTC distorce o dia).
    """
    if df is None or df.empty:
        return df
    if agora_brt is None:
        agora_brt = comparecimento_ajustado_agora_brt()
    else:
        agora_brt = pd.Timestamp(agora_brt).tz_localize(None)

    out = df.copy()
    start = _comparecimento_ajustado_start_naive_brt(out["start_datetime"])
    fim = _comparecimento_ajustado_fim_reuniao_ref(out, start=start)
    ja_ocorreu = start.notna() & (start < agora_brt)

    out["agora_brt"] = agora_brt
    out["fim_reuniao_ref"] = fim
    out["flag_ja_ocorridas"] = ja_ocorreu
    out["classificacao_dashboard"] = comparecimento_ajustado_classificacao_dashboard(
        out, agora_brt,
    )
    cls = out["classificacao_dashboard"]

    out["flag_comparecimento_zoho"] = cls.eq("Concluída no Zoho")
    out["flag_agendada_horario_encerrado"] = cls.eq("Agendada com horário encerrado")
    out["flag_agendada_em_andamento"] = cls.eq("Agendada em andamento")
    out["flag_agendada_futura"] = cls.eq("Agendada futura")
    out["flag_noshow"] = cls.eq("No-show")
    out["flag_cancelada"] = cls.eq("Cancelada")
    out["flag_fora_vencida"] = cls.eq("Vencida")
    out["flag_comparecimento_ajustado"] = cls.isin([
        "Concluída no Zoho",
        "Agendada com horário encerrado",
    ])
    out["entra_comparecimento_ajustado"] = out["flag_comparecimento_ajustado"]
    out["entra_reuniao_cancelada"] = cls.isin(["No-show", "Cancelada"])
    out["observacao"] = cls.map(_COMPARECIMENTO_OBSERVACAO).fillna(
        _COMPARECIMENTO_OBSERVACAO["Outro"],
    )

    out["tipo_comparecimento"] = cls.replace({
        "Concluída no Zoho": "Concluída Zoho",
        "Agendada com horário encerrado": "Agendada com horário encerrado",
        "Agendada em andamento": "Agendada em andamento",
        "Agendada futura": "Agendada futura",
        "No-show": "Fora: No-show",
        "Cancelada": "Fora: Cancelada",
        "Vencida": "Fora: Vencida",
    }).fillna("Outro")
    return out


def comparecimento_ajustado_preparar(
    df_raw: pd.DataFrame,
    df_cadastro: pd.DataFrame | None,
    *,
    filtrar_oficial: bool = False,
) -> pd.DataFrame:
    """Normaliza `executiva` (owner da activity) com o mesmo match de tokens
    do ranking e, opcionalmente, restringe ao cadastro oficial ativo."""
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
    out = executivas_canonicalizar_executivas(df_raw, df_cadastro)
    if filtrar_oficial and df_cadastro is not None and not df_cadastro.empty:
        out = executivas_filtrar_time_oficial(out, df_cadastro)
    return out


def comparecimento_ajustado_kpis(df: pd.DataFrame) -> dict:
    """Totais do funil para os cards Reunião Concluída / Reunião Cancelada."""
    empty = {
        "comparecimento_zoho": 0,
        "agendadas_horario_encerrado": 0,
        "agendadas_em_andamento": 0,
        "agendadas_futuras": 0,
        "comparecimento_ajustado": 0,
        "noshow": 0,
        "canceladas": 0,
        "reuniao_cancelada_total": 0,
        "agora_brt": comparecimento_ajustado_agora_brt(),
    }
    if df is None or df.empty:
        return empty
    zoho = int(df["flag_comparecimento_zoho"].fillna(False).sum())
    encerrado = int(df["flag_agendada_horario_encerrado"].fillna(False).sum())
    andamento = int(df["flag_agendada_em_andamento"].fillna(False).sum())
    futuras = int(df["flag_agendada_futura"].fillna(False).sum())
    ajust = int(df["flag_comparecimento_ajustado"].fillna(False).sum())
    noshow = int(df["flag_noshow"].fillna(False).sum())
    canceladas = int(df["flag_cancelada"].fillna(False).sum())
    agora = df["agora_brt"].iloc[0] if "agora_brt" in df.columns else comparecimento_ajustado_agora_brt()
    return {
        "comparecimento_zoho": zoho,
        "agendadas_horario_encerrado": encerrado,
        "agendadas_em_andamento": andamento,
        "agendadas_futuras": futuras,
        "comparecimento_ajustado": ajust,
        "noshow": noshow,
        "canceladas": canceladas,
        "reuniao_cancelada_total": noshow + canceladas,
        "agora_brt": agora,
    }


def comparecimento_ajustado_filtrar_ja_ocorridas(df: pd.DataFrame) -> pd.DataFrame:
    """Somente reuniões com start_datetime < agora_brt (timestamp completo)."""
    if df is None or df.empty:
        return pd.DataFrame()
    if "flag_ja_ocorridas" in df.columns:
        return df.loc[df["flag_ja_ocorridas"].fillna(False)].copy()
    agora = (
        pd.Timestamp(df["agora_brt"].iloc[0]).tz_localize(None)
        if "agora_brt" in df.columns and df["agora_brt"].notna().any()
        else comparecimento_ajustado_agora_brt()
    )
    start = _comparecimento_ajustado_start_naive_brt(df["start_datetime"])
    return df.loc[start.notna() & (start < agora)].copy()


def comparecimento_ajustado_resumo_periodo_por_status(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Resumo por closer/owner — todas as reuniões do período filtrado."""
    cols = [
        "closer",
        "concluídas_no_zoho",
        "agendadas_com_horario_encerrado",
        "agendadas_em_andamento",
        "agendadas_futuras",
        "no_show",
        "canceladas",
        "vencidas",
        "total_reunioes_periodo",
    ]
    if df is None or df.empty or "executiva" not in df.columns:
        return pd.DataFrame(columns=cols)
    if "classificacao_dashboard" not in df.columns:
        return pd.DataFrame(columns=cols)

    def _cnt(label: str) -> pd.Series:
        return (df["classificacao_dashboard"] == label).astype(int)

    base = df.copy()
    base["_zoho"] = _cnt("Concluída no Zoho")
    base["_enc"] = _cnt("Agendada com horário encerrado")
    base["_and"] = _cnt("Agendada em andamento")
    base["_fut"] = _cnt("Agendada futura")
    base["_ns"] = _cnt("No-show")
    base["_canc"] = _cnt("Cancelada")
    base["_venc"] = _cnt("Vencida")

    agg = (
        base.groupby("executiva", as_index=False)
        .agg(
            concluídas_no_zoho=("_zoho", "sum"),
            agendadas_com_horario_encerrado=("_enc", "sum"),
            agendadas_em_andamento=("_and", "sum"),
            agendadas_futuras=("_fut", "sum"),
            no_show=("_ns", "sum"),
            canceladas=("_canc", "sum"),
            vencidas=("_venc", "sum"),
            total_reunioes_periodo=("activity_id", "count"),
        )
        .rename(columns={"executiva": "closer"})
    )
    for c in cols[1:]:
        agg[c] = agg[c].fillna(0).astype(int)
    agg = agg.sort_values("total_reunioes_periodo", ascending=False).reset_index(drop=True)
    total = {c: int(agg[c].sum()) for c in cols[1:]}
    total["closer"] = "TOTAL"
    return pd.concat([agg, pd.DataFrame([total])], ignore_index=True)


def comparecimento_ajustado_resumo_ocorridas_por_status(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Alias legado — usa resumo do período completo."""
    return comparecimento_ajustado_resumo_periodo_por_status(df)


def comparecimento_ajustado_conferencia_periodo(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela linha a linha — todas as reuniões do período filtrado."""
    cols = [
        "closer",
        "nome_lead",
        "email",
        "data_hora_criacao_agendamento",
        "data_hora_reuniao",
        "status_reuniao",
        "deal_stage",
        "classificacao_dashboard",
        "entra_comparecimento_ajustado",
        "entra_reuniao_cancelada",
        "observacao",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    criacao = df["created_time"] if "created_time" in df.columns else df.get("created_at")
    end_col = df["end_datetime"] if "end_datetime" in df.columns else None

    out = pd.DataFrame({
        "closer": df["executiva"],
        "nome_lead": df.get("nome_lead", ""),
        "email": df.get("email", ""),
        "data_hora_criacao_agendamento": criacao,
        "data_hora_reuniao": _comparecimento_ajustado_format_data_hora_reuniao(
            df["start_datetime"], end_col,
        ),
        "status_reuniao": df.get("status_reuniao", ""),
        "deal_stage": df.get("deal_stage", ""),
        "classificacao_dashboard": df.get("classificacao_dashboard", "Outro"),
        "entra_comparecimento_ajustado": df.get(
            "entra_comparecimento_ajustado", False,
        ),
        "entra_reuniao_cancelada": df.get("entra_reuniao_cancelada", False),
        "observacao": df.get("observacao", ""),
    })
    sort_start = _comparecimento_ajustado_ts_naive_brt(df["start_datetime"])
    return out.iloc[sort_start.sort_values(ascending=False).index].reset_index(drop=True)


def comparecimento_ajustado_conferencia_ocorridas(df: pd.DataFrame) -> pd.DataFrame:
    """Alias legado — conferência do período completo."""
    return comparecimento_ajustado_conferencia_periodo(df)


def comparecimento_ajustado_filtrar_conferencia(
    df: pd.DataFrame,
    *,
    classificacao: str = "Todas",
    closer: str = "Todos",
    busca: str = "",
) -> pd.DataFrame:
    """Filtros da tabela de conferência (classificação, closer, nome/email)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if classificacao and classificacao != "Todas":
        label = _COMPARECIMENTO_CLASSIF_DASHBOARD_LABELS.get(classificacao, classificacao)
        out = out.loc[out["classificacao_dashboard"].astype(str) == label]
    if closer and closer != "Todos" and "closer" in out.columns:
        out = out.loc[out["closer"].astype(str).str.strip() == str(closer).strip()]
    termo = (busca or "").strip().lower()
    if termo:
        nome = out.get("nome_lead", pd.Series("", index=out.index)).fillna("").astype(str).str.lower()
        email = out.get("email", pd.Series("", index=out.index)).fillna("").astype(str).str.lower()
        out = out.loc[nome.str.contains(termo, na=False) | email.str.contains(termo, na=False)]
    return out.reset_index(drop=True)


def comparecimento_ajustado_por_executiva(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega por `executiva` (owner da activity = ranking dashboard)."""
    cols = list(_COMPARECIMENTO_AJUSTADO_AGG_COLS)
    if df is None or df.empty or "executiva" not in df.columns:
        return pd.DataFrame(columns=["executiva"] + cols)
    return (
        df.groupby("executiva", as_index=False)
        .agg(
            comparecimentos_zoho=("flag_comparecimento_zoho", "sum"),
            agendadas_horario_encerrado=("flag_agendada_horario_encerrado", "sum"),
            comparecimentos_ajustado=("flag_comparecimento_ajustado", "sum"),
            noshow=("flag_noshow", "sum"),
            canceladas=("flag_cancelada", "sum"),
        )
    )


def comparecimento_ajustado_debug_horario(df: pd.DataFrame) -> dict:
    """Validação temporal: futura / andamento / encerrado vs agora BRT."""
    agora = comparecimento_ajustado_agora_brt()
    empty_cols = [
        "executiva", "nome_lead", "email", "start_datetime", "end_datetime",
        "status_reuniao", "deal_stage", "classificacao_dashboard",
    ]
    if df is None or df.empty:
        return {
            "agora_brt": agora,
            "lista_encerrado": pd.DataFrame(),
            "violacoes_futuro": pd.DataFrame(),
            "violacoes_andamento_como_encerrado": pd.DataFrame(),
            "violacoes_encerrado_como_andamento": pd.DataFrame(),
            "violacoes_passado_como_futuro": pd.DataFrame(),
            "qtd_violacoes_futuro": 0,
            "qtd_violacoes_andamento_como_encerrado": 0,
            "qtd_violacoes_encerrado_como_andamento": 0,
            "qtd_violacoes_passado_como_futuro": 0,
        }
    if "agora_brt" in df.columns and df["agora_brt"].notna().any():
        agora = pd.Timestamp(df["agora_brt"].iloc[0]).tz_localize(None)

    cols = [c for c in empty_cols if c in df.columns]
    status = df["status_reuniao"].astype(str).str.strip()
    is_agendada = status.isin(["Agendada", "Agendado"])
    start = _comparecimento_ajustado_start_naive_brt(df["start_datetime"])
    fim = (
        _comparecimento_ajustado_fim_reuniao_ref(df, start=start)
        if "fim_reuniao_ref" not in df.columns
        else _comparecimento_ajustado_ts_naive_brt(df["fim_reuniao_ref"])
    )
    cls = df["classificacao_dashboard"].astype(str)

    encerrado = df.loc[cls == "Agendada com horário encerrado", cols].copy()
    viol_futuro = df.loc[
        is_agendada & start.notna() & (start > agora)
        & (cls != "Agendada futura"),
        cols,
    ].copy()
    viol_andamento_como_encerrado = df.loc[
        is_agendada & start.notna() & fim.notna()
        & (start <= agora) & (fim > agora)
        & (cls == "Agendada com horário encerrado"),
        cols,
    ].copy()
    viol_encerrado_como_andamento = df.loc[
        is_agendada & fim.notna() & (fim <= agora)
        & (cls == "Agendada em andamento"),
        cols,
    ].copy()
    viol_passado_como_futuro = df.loc[
        is_agendada & start.notna() & (start <= agora)
        & (cls == "Agendada futura"),
        cols,
    ].copy()

    sort_col = "start_datetime" if "start_datetime" in encerrado.columns else None
    if sort_col and not encerrado.empty:
        encerrado = encerrado.sort_values(sort_col)
    return {
        "agora_brt": agora,
        "lista_encerrado": encerrado,
        "lista_pendente": encerrado,
        "violacoes_futuro": viol_futuro,
        "violacoes_andamento_como_encerrado": viol_andamento_como_encerrado,
        "violacoes_encerrado_como_andamento": viol_encerrado_como_andamento,
        "violacoes_passado_como_futuro": viol_passado_como_futuro,
        "qtd_violacoes_futuro": len(viol_futuro),
        "qtd_violacoes_andamento_como_encerrado": len(viol_andamento_como_encerrado),
        "qtd_violacoes_encerrado_como_andamento": len(viol_encerrado_como_andamento),
        "qtd_violacoes_passado_como_futuro": len(viol_passado_como_futuro),
    }


def comparecimento_ajustado_debug_tabela(agg: pd.DataFrame) -> pd.DataFrame:
    """Debug por closer: zoho, pendente, ajustado e Δ ajustado−zoho + TOTAL."""
    cols = [
        "executiva",
        "comparecimentos_zoho",
        "agendadas_horario_encerrado",
        "comparecimentos_ajustado",
        "diferenca_ajustado_menos_zoho",
    ]
    if agg is None or agg.empty:
        return pd.DataFrame(columns=cols)
    out = agg.copy()
    out["diferenca_ajustado_menos_zoho"] = (
        out["comparecimentos_ajustado"].fillna(0).astype(int)
        - out["comparecimentos_zoho"].fillna(0).astype(int)
    )
    out = out[cols].sort_values(
        "comparecimentos_ajustado", ascending=False,
    ).reset_index(drop=True)
    total = {
        "executiva": "TOTAL",
        "comparecimentos_zoho": int(out["comparecimentos_zoho"].sum()),
        "agendadas_horario_encerrado": int(out["agendadas_horario_encerrado"].sum()),
        "comparecimentos_ajustado": int(out["comparecimentos_ajustado"].sum()),
        "diferenca_ajustado_menos_zoho": int(
            out["diferenca_ajustado_menos_zoho"].sum(),
        ),
    }
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)


def comparecimento_ajustado_validacao(
    kpis: dict,
    agg: pd.DataFrame,
    resumo_ocorridas: pd.DataFrame | None = None,
    conferencia: pd.DataFrame | None = None,
    ranking: pd.DataFrame | None = None,
    linhas: pd.DataFrame | None = None,
) -> dict:
    """Confere invariantes card ↔ agregados ↔ resumo ↔ conferência."""
    card_ajustado = int((kpis or {}).get("comparecimento_ajustado", 0) or 0)
    card_cancel = int((kpis or {}).get("reuniao_cancelada_total", 0) or 0)
    soma_zoho = int(agg["comparecimentos_zoho"].sum()) if agg is not None and not agg.empty else 0
    soma_enc = int(agg["agendadas_horario_encerrado"].sum()) if agg is not None and not agg.empty else 0
    soma_ajustado_agg = int(agg["comparecimentos_ajustado"].sum()) if agg is not None and not agg.empty else 0
    soma_noshow_agg = int(agg["noshow"].sum()) if agg is not None and not agg.empty and "noshow" in agg.columns else 0
    soma_canceladas_agg = int(agg["canceladas"].sum()) if agg is not None and not agg.empty and "canceladas" in agg.columns else 0
    soma_ajustado_ranking = 0
    if ranking is not None and not ranking.empty and "comparecimentos_ajustado" in ranking.columns:
        soma_ajustado_ranking = int(ranking["comparecimentos_ajustado"].fillna(0).sum())

    resumo_zoho = resumo_enc = resumo_ns = resumo_canc = 0
    if resumo_ocorridas is not None and not resumo_ocorridas.empty:
        tot = resumo_ocorridas.loc[resumo_ocorridas["closer"].astype(str) == "TOTAL"]
        if not tot.empty:
            r = tot.iloc[0]
            resumo_zoho = int(r.get("concluídas_no_zoho", 0) or 0)
            resumo_enc = int(r.get("agendadas_com_horario_encerrado", 0) or 0)
            resumo_ns = int(r.get("no_show", 0) or 0)
            resumo_canc = int(r.get("canceladas", 0) or 0)

    agora = pd.Timestamp((kpis or {}).get("agora_brt")).tz_localize(None) if (kpis or {}).get("agora_brt") is not None else None
    viol_futuro_mal = viol_andamento_como_encerrado = viol_encerrado_como_andamento = 0
    viol_passado_como_futuro = 0
    futura_entra_ajustado = andamento_entra_ajustado = futura_entra_cancelada = 0
    andamento_entra_cancelada = 0
    ref = linhas if linhas is not None and not linhas.empty else conferencia
    if ref is not None and not ref.empty and agora is not None:
        if linhas is not None and not linhas.empty and "start_datetime" in linhas.columns:
            start = _comparecimento_ajustado_ts_naive_brt(linhas["start_datetime"])
            fim = _comparecimento_ajustado_fim_reuniao_ref(linhas, start=start)
        else:
            start = _comparecimento_ajustado_ts_naive_brt(ref["data_hora_inicio_reuniao"])
            end_raw = (
                _comparecimento_ajustado_ts_naive_brt(ref["data_hora_fim_reuniao"])
                if "data_hora_fim_reuniao" in ref.columns
                else pd.Series(pd.NaT, index=ref.index)
            )
            fim = end_raw.where(end_raw.notna(), start + pd.Timedelta(hours=1))
        cls = ref["classificacao_dashboard"].astype(str)
        status = ref.get("status_reuniao", pd.Series("", index=ref.index))
        is_agendada = status.astype(str).str.strip().isin(["Agendada", "Agendado"])

        viol_futuro_mal = int(
            (is_agendada & start.notna() & (start > agora) & (cls != "Agendada futura")).sum(),
        )
        viol_andamento_como_encerrado = int(
            (
                is_agendada & start.notna() & fim.notna()
                & (start <= agora) & (fim > agora)
                & (cls == "Agendada com horário encerrado")
            ).sum(),
        )
        viol_encerrado_como_andamento = int(
            (
                is_agendada & fim.notna() & (fim <= agora)
                & (cls == "Agendada em andamento")
            ).sum(),
        )
        viol_passado_como_futuro = int(
            (is_agendada & start.notna() & (start <= agora) & (cls == "Agendada futura")).sum(),
        )
        fut_mask = cls == "Agendada futura"
        and_mask = cls == "Agendada em andamento"
        futura_entra_ajustado = int(
            (fut_mask & ref["entra_comparecimento_ajustado"].fillna(False)).sum(),
        )
        andamento_entra_ajustado = int(
            (and_mask & ref["entra_comparecimento_ajustado"].fillna(False)).sum(),
        )
        futura_entra_cancelada = int(
            (fut_mask & ref["entra_reuniao_cancelada"].fillna(False)).sum(),
        )
        andamento_entra_cancelada = int(
            (and_mask & ref["entra_reuniao_cancelada"].fillna(False)).sum(),
        )

    soma_cancel_card_parts = int((kpis or {}).get("noshow", 0) or 0) + int(
        (kpis or {}).get("canceladas", 0) or 0,
    )
    return {
        "card_comparecimento_ajustado": card_ajustado,
        "soma_comparecimentos_zoho_ranking": soma_zoho,
        "soma_agendadas_horario_encerrado_ranking": soma_enc,
        "soma_agendadas_horario_passado_ranking": soma_enc,
        "soma_comparecimentos_ajustado_agg": soma_ajustado_agg,
        "soma_comparecimentos_ajustado_ranking": soma_ajustado_ranking,
        "card_bate_agg": card_ajustado == soma_ajustado_agg,
        "card_bate_ranking": card_ajustado == soma_ajustado_ranking,
        "agg_bate_ranking": soma_ajustado_agg == soma_ajustado_ranking,
        "card_reuniao_cancelada": card_cancel,
        "soma_noshow_agg": soma_noshow_agg,
        "soma_canceladas_agg": soma_canceladas_agg,
        "card_bate_cancelada": card_cancel == soma_noshow_agg + soma_canceladas_agg,
        "card_bate_cancelada_kpis": card_cancel == soma_cancel_card_parts,
        "resumo_bate_card_concluida": (resumo_zoho + resumo_enc) == card_ajustado,
        "resumo_bate_card_cancelada": (resumo_ns + resumo_canc) == card_cancel,
        "sem_futuro_mal_classificado": viol_futuro_mal == 0,
        "sem_andamento_como_encerrado": viol_andamento_como_encerrado == 0,
        "sem_encerrado_como_andamento": viol_encerrado_como_andamento == 0,
        "sem_futuro_como_passado": viol_andamento_como_encerrado == 0,
        "sem_passado_como_futuro": viol_passado_como_futuro == 0,
        "futura_fora_ajustado": futura_entra_ajustado == 0,
        "andamento_fora_ajustado": andamento_entra_ajustado == 0,
        "futura_fora_cancelada": futura_entra_cancelada == 0,
        "andamento_fora_cancelada": andamento_entra_cancelada == 0,
        "agora_brt": (kpis or {}).get("agora_brt"),
    }


def comparecimento_ajustado_bundle(
    df_raw: pd.DataFrame,
    df_cadastro: pd.DataFrame | None,
    *,
    filtrar_oficial: bool = False,
    agora_brt: pd.Timestamp | None = None,
) -> dict:
    """Fonte única: linhas preparadas, KPIs do card, agregado e debug."""
    agora = agora_brt or comparecimento_ajustado_agora_brt()
    linhas = comparecimento_ajustado_preparar(
        df_raw, df_cadastro, filtrar_oficial=filtrar_oficial,
    )
    linhas = comparecimento_ajustado_aplicar_flags(linhas, agora_brt=agora)
    kpis = comparecimento_ajustado_kpis(linhas)
    agg = comparecimento_ajustado_por_executiva(linhas)
    debug = comparecimento_ajustado_debug_tabela(agg)
    debug_horario = comparecimento_ajustado_debug_horario(linhas)
    resumo_periodo = comparecimento_ajustado_resumo_periodo_por_status(linhas)
    conferencia = comparecimento_ajustado_conferencia_periodo(linhas)
    validacao = comparecimento_ajustado_validacao(
        kpis, agg, resumo_periodo, conferencia, linhas=linhas,
    )
    validacao["horario_sem_violacoes"] = (
        debug_horario["qtd_violacoes_futuro"] == 0
        and debug_horario.get("qtd_violacoes_passado_como_futuro", 0) == 0
        and debug_horario.get("qtd_violacoes_andamento_como_encerrado", 0) == 0
        and debug_horario.get("qtd_violacoes_encerrado_como_andamento", 0) == 0
    )
    return {
        "linhas": linhas,
        "kpis": kpis,
        "agg": agg,
        "debug": debug,
        "debug_horario": debug_horario,
        "resumo_periodo": resumo_periodo,
        "resumo_ocorridas": resumo_periodo,
        "conferencia": conferencia,
        "validacao": validacao,
        "agora_brt": agora,
    }


def comparecimento_ajustado_merge_ranking(
    ranking: pd.DataFrame,
    agg: pd.DataFrame,
) -> pd.DataFrame:
    """Anexa colunas do teste ao ranking sem remover `comparecimentos`."""
    if ranking is None or ranking.empty:
        return ranking
    ranking = ranking.copy()
    for c in _COMPARECIMENTO_AJUSTADO_AGG_COLS:
        if c in ranking.columns:
            ranking = ranking.drop(columns=[c])
    if agg is None or agg.empty:
        for c in _COMPARECIMENTO_AJUSTADO_AGG_COLS:
            ranking[c] = 0
        return ranking
    merged = ranking.merge(agg, on="executiva", how="left")
    for c in _COMPARECIMENTO_AJUSTADO_AGG_COLS:
        if c in merged.columns:
            merged[c] = merged[c].fillna(0).astype(int)
    if "comparecimentos_zoho" in merged.columns and "comparecimentos_ajustado" in merged.columns:
        viol = merged["comparecimentos_ajustado"] < merged["comparecimentos_zoho"]
        if viol.any():
            merged.loc[viol, "comparecimentos_ajustado"] = merged.loc[
                viol, "comparecimentos_zoho",
            ]
    return merged


def comparecimento_ajustado_filtrar_executiva(
    df: pd.DataFrame,
    executiva_nome: str,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    nome = str(executiva_nome or "").strip()
    return df.loc[df["executiva"].astype(str).str.strip() == nome].copy()


def comparecimento_ajustado_tabela_leidianne(
    agg: pd.DataFrame,
) -> pd.DataFrame:
    """Comparativo semana atual: ajustado vs amostra Leidianne."""
    rows: list[dict] = []
    for closer, lista_n in LISTA_LEIDIANNE_COMPARECIMENTOS.items():
        if agg is not None and not agg.empty:
            m = agg["executiva"].astype(str).str.strip() == closer
            row = agg.loc[m]
            if not row.empty:
                r = row.iloc[0]
                zoho = int(r.get("comparecimentos_zoho", 0) or 0)
                pend = int(r.get("agendadas_horario_encerrado", 0) or 0)
                ajust = int(r.get("comparecimentos_ajustado", 0) or 0)
            else:
                zoho = pend = ajust = 0
        else:
            zoho = pend = ajust = 0
        rows.append({
            "closer": closer,
            "comparecimentos_zoho": zoho,
            "agendadas_horario_encerrado": pend,
            "comparecimentos_ajustado": ajust,
            "lista_leidianne": lista_n,
            "diferenca_ajustado_vs_lista": ajust - lista_n,
        })
    if not rows:
        return pd.DataFrame(
            columns=[
                "closer", "comparecimentos_zoho", "agendadas_horario_encerrado",
                "comparecimentos_ajustado", "lista_leidianne",
                "diferenca_ajustado_vs_lista",
            ],
        )
    out = pd.DataFrame(rows)
    out = pd.concat(
        [
            out,
            pd.DataFrame([{
                "closer": "TOTAL",
                "comparecimentos_zoho": int(out["comparecimentos_zoho"].sum()),
                "agendadas_horario_encerrado": int(
                    out["agendadas_horario_encerrado"].sum(),
                ),
                "comparecimentos_ajustado": int(out["comparecimentos_ajustado"].sum()),
                "lista_leidianne": int(out["lista_leidianne"].sum()),
                "diferenca_ajustado_vs_lista": int(
                    out["diferenca_ajustado_vs_lista"].sum(),
                ),
            }]),
        ],
        ignore_index=True,
    )
    return out


def vendas_detalhe_filtrar_closer(df_det_norm: pd.DataFrame,
                                  closer_nome: str) -> pd.Series:
    """Mask booleana — linhas do detalhe cujo `closer_filtro` casa com
    `closer_nome` (match exato, espaços normalizados).

    O ranking de Vendas expõe `executiva` = `TRIM(first_name||' '||last_name)`
    via zoho_users (com fallback pro owner_id quando não pareia); o detalhe
    expõe `closer_filtro` com a mesma fórmula (fallback 'Sem Closer'). Match
    string-exato funciona pra todos os closers cadastrados em zoho_users.
    Também produz `classificacao_final_filtro` (CRM > lead/ext) para a
    coluna resumida "Classificação" nas tabelas de detalhe.
    Edge case: um closer cujo `executiva_vendas` é ID sem user pareado
    aparece no ranking como o ID raw e no detalhe como 'Sem Closer' — essa
    linha do ranking não terá detalhe disponível (caller deve sinalizar).
    """
    if df_det_norm is None or df_det_norm.empty:
        idx = df_det_norm.index if df_det_norm is not None else []
        return pd.Series(False, index=idx)
    nome = (closer_nome or "").strip()
    if not nome:
        return pd.Series(False, index=df_det_norm.index)
    return df_det_norm["closer_filtro"].astype(str).str.strip() == nome


def vendas_detalhe_filtrar_time(df_det_norm: pd.DataFrame,
                                time_nome: str) -> pd.Series:
    """Mask booleana — linhas do detalhe cujo `time_vendas_filtro` casa.

    Útil pro filtro global de Times da página (header da view): quando
    o usuário seleciona 'Time da Leidianne', o detalhe é pré-filtrado
    pra refletir o mesmo recorte do ranking. Match exato, espaços
    normalizados.
    """
    if df_det_norm is None or df_det_norm.empty:
        idx = df_det_norm.index if df_det_norm is not None else []
        return pd.Series(False, index=idx)
    nome = (time_nome or "").strip()
    if not nome:
        return pd.Series(False, index=df_det_norm.index)
    return df_det_norm["time_vendas_filtro"].astype(str).str.strip() == nome


# ---------------------------------------------------------------------------
# vw_compatibilidade_sdr_closer
# ---------------------------------------------------------------------------

def annotate_and_clean_sdr_closer(df: pd.DataFrame) -> pd.DataFrame:
    """Sobrescreve `tipo_sdr` e `time_closer` com a classificação canônica
    (`src/team_classification.py`) e remove linhas onde:
      - o valor de `sdr` é um Closer conhecido
      - o valor de `closer` é um SDR conhecido
    Esses casos são misclassifications cruzadas — não devem aparecer na matriz.
    Pessoas em `SDR não classificado` / `Closer não classificado` permanecem
    (podem ser qualquer um dos dois — sem evidência pra dropar). `Sem SDR`
    e `Sem Closer` (placeholders do SQL) também permanecem como categoria
    própria."""
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


def roas_diario(df_invest: pd.DataFrame, df_exec: pd.DataFrame,
                taxa_recebimento: float | None = None) -> pd.DataFrame:
    """Junta investimento diário com receita/vendas diárias por data_ref.

    Devolve as colunas originais + `roas` (realizado, receita/invest) +
    `roas_realizado` (alias explícito) + `roas_projetado` (montante × taxa
    de recebimento esperada / invest). Quando `taxa_recebimento` é None,
    cai pra `roas_projetado == roas_realizado` (sem projeção).

    A taxa é aplicada uniformemente em todos os dias do período — usar a
    taxa de cada dia individual seria ruidoso (deals novos ainda não
    recebidos no mesmo dia).
    """
    if df_invest.empty:
        return pd.DataFrame()
    exec_diario = executivas_por_dia(df_exec)
    merged = df_invest.merge(exec_diario, on="data_ref", how="left").fillna(0)

    merged["roas"] = merged.apply(
        lambda r: _safe_div(r.get("receita", 0), r["investimento_total"]), axis=1)
    # alias explícito p/ legendas de gráfico (`roas` puro confunde)
    merged["roas_realizado"] = merged["roas"]

    taxa = taxa_recebimento if taxa_recebimento is not None else None
    merged["roas_projetado"] = merged.apply(
        lambda r: _safe_div(
            r.get("montante", 0) * taxa if taxa is not None else r.get("receita", 0),
            r["investimento_total"],
        ),
        axis=1,
    )

    merged["cac"] = merged.apply(
        lambda r: _safe_div(r["investimento_total"], r.get("vendas", 0)), axis=1
    )
    return merged.sort_values("data_ref")


def roas_resumo(df_invest: pd.DataFrame, df_exec: pd.DataFrame,
                taxa_recebimento: float | None = None) -> dict:
    """Totais consolidados de ROAS / CAC.

    `taxa_recebimento` (entre 0 e 1) é a expectativa de recebimento aplicada
    sobre o montante pra estimar receita futura. Quando None, `roas_projetado`
    cai para o `roas_realizado` (sem ganho informacional).

    Campos retornados:
      - `roas_realizado`   = receita já paga ÷ investimento
      - `roas_projetado`   = (montante × taxa) ÷ investimento
      - `receita_projetada` = montante × taxa
      - `taxa_aplicada`    = taxa usada no cálculo (0..1) — só pra exibir no hint
      - `taxa_periodo`     = receita/montante do próprio período (0..1) —
                              informacional; **não** usado no projetado pra
                              evitar circularidade
      - `roas`             = alias backward-compat para `roas_realizado`
    """
    totais_inv = investimento_totais(df_invest)
    totais_exec = executivas_kpis(df_exec)
    receita = totais_exec.get("receita", 0)
    montante = totais_exec.get("montante", 0)
    vendas = totais_exec.get("vendas", 0)
    invest = totais_inv.get("total", 0)

    taxa_periodo = _safe_div(receita, montante)
    taxa_aplicada = taxa_recebimento if taxa_recebimento is not None else taxa_periodo
    receita_projetada = float(montante) * float(taxa_aplicada)

    roas_realizado = _safe_div(receita, invest)
    roas_projetado = (_safe_div(receita_projetada, invest)
                      if taxa_recebimento is not None else roas_realizado)

    return {
        # backward compat — antigos consumidores leem `r["roas"]`
        "roas": roas_realizado,
        # novos campos
        "roas_realizado":     roas_realizado,
        "roas_projetado":     roas_projetado,
        "receita_projetada":  receita_projetada,
        "taxa_aplicada":      taxa_aplicada,
        "taxa_periodo":       taxa_periodo,
        # campos existentes
        "investimento":       invest,
        "receita":            receita,
        "montante":           montante,
        "vendas":             vendas,
        "cac":                _safe_div(invest, vendas),
        "dias":               totais_inv.get("dias", 0),
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


# ---------------------------------------------------------------------------
# Churn por Pós-venda (deals stage = 'Churn') — Executivas & Times
# ---------------------------------------------------------------------------

CHURN_POS_SEM_IDENTIFICADO = "Sem pós-venda identificado"
CHURN_SEM_CLOSER = "Sem closer identificado"


def _build_pos_venda_oficiais_maps(
    df_oficiais: pd.DataFrame,
) -> tuple[dict[str, tuple[str, str]], list[tuple[str, set[str], str]]]:
    """Retorna (by_id_crm → (nome, ativo), lista (nome, tokens, ativo))."""
    by_crm: dict[str, tuple[str, str]] = {}
    tokens_list: list[tuple[str, set[str], str]] = []
    if df_oficiais is None or df_oficiais.empty or "nome" not in df_oficiais.columns:
        return by_crm, tokens_list
    for row in df_oficiais.itertuples(index=False):
        nome = getattr(row, "nome", None)
        if not isinstance(nome, str) or not nome.strip():
            continue
        ativo = str(getattr(row, "ativo", "") or "").strip().lower() or ""
        cid = getattr(row, "id_crm", None)
        if cid is not None and str(cid).strip():
            by_crm[str(cid).strip()] = (nome, ativo)
        toks = set(_tokens_nome_ranking(nome))
        if toks:
            tokens_list.append((nome, toks, ativo))
    return by_crm, tokens_list


def _match_pos_oficial(
    *,
    id_crm: str | None,
    nome_candidato: str | None,
    by_crm: dict[str, tuple[str, str]],
    tokens_list: list[tuple[str, set[str], str]],
) -> tuple[str, str, str] | None:
    """Devolve (nome_canônico, ativo, origem) ou None se não casou cadastro."""
    if id_crm and str(id_crm).strip() in by_crm:
        nome, ativo = by_crm[str(id_crm).strip()]
        return nome, ativo, "executiva_contas (id_crm)"
    if nome_candidato and str(nome_candidato).strip():
        canon = _match_oficial_por_tokens(
            str(nome_candidato),
            [(n, t) for n, t, _a in tokens_list],
        )
        if canon:
            ativo = next((a for n, _t, a in tokens_list if n == canon), "")
            return canon, ativo, "executiva_contas (nome)"
    return None


def churn_pos_venda_aplicar_cadastro(
    df: pd.DataFrame,
    df_oficiais: pd.DataFrame,
) -> pd.DataFrame:
    """Resolve pós-venda canônico, ativo e origem do vínculo por deal Churn."""
    if df is None or df.empty:
        return df
    out = df.copy()
    by_crm, tokens_list = _build_pos_venda_oficiais_maps(df_oficiais)

    pos_venda: list[str] = []
    pos_ativo: list[str] = []
    origem: list[str] = []

    for row in out.itertuples(index=False):
        contas_id = getattr(row, "executiva_contas_id", None)
        user_nome = getattr(row, "pos_user_nome", None)
        owner_pos = getattr(row, "ultimo_owner_pos_nome", None)
        acomp = getattr(row, "acomp_pos_nome", None)

        resolved: tuple[str, str, str] | None = None
        if contas_id is not None and str(contas_id).strip():
            resolved = _match_pos_oficial(
                id_crm=str(contas_id).strip(),
                nome_candidato=user_nome if isinstance(user_nome, str) else None,
                by_crm=by_crm,
                tokens_list=tokens_list,
            )
            if resolved is None and user_nome and str(user_nome).strip():
                pos_venda.append(str(user_nome).strip())
                pos_ativo.append("")
                origem.append("executiva_contas (zoho_users)")
                continue

        if resolved is None and owner_pos and str(owner_pos).strip():
            resolved = _match_pos_oficial(
                id_crm=None,
                nome_candidato=str(owner_pos),
                by_crm=by_crm,
                tokens_list=tokens_list,
            )
            if resolved is None:
                pos_venda.append(str(owner_pos).strip())
                pos_ativo.append("")
                origem.append("atividade pós-venda")
                continue

        if resolved is None and acomp and str(acomp).strip():
            resolved = _match_pos_oficial(
                id_crm=None,
                nome_candidato=str(acomp),
                by_crm=by_crm,
                tokens_list=tokens_list,
            )
            if resolved is None:
                pos_venda.append(str(acomp).strip())
                pos_ativo.append("")
                origem.append("acompanhamento")
                continue

        if resolved:
            pos_venda.append(resolved[0])
            pos_ativo.append(resolved[1])
            origem.append(resolved[2])
        else:
            pos_venda.append(CHURN_POS_SEM_IDENTIFICADO)
            pos_ativo.append("")
            origem.append("")

    out["pos_venda"] = pos_venda
    out["pos_ativo"] = pos_ativo
    out["origem_vinculo"] = origem
    out["identificado_pos"] = out["pos_venda"] != CHURN_POS_SEM_IDENTIFICADO
    if "data_churn" in out.columns:
        out["data_churn"] = pd.to_datetime(out["data_churn"], errors="coerce")
    if "ultimo_contato_pos" in out.columns:
        out["ultimo_contato_pos"] = pd.to_datetime(
            out["ultimo_contato_pos"], errors="coerce"
        )
    return out


def churn_pos_filtrar_periodo(
    df: pd.DataFrame,
    data_ini,
    data_fim,
) -> pd.DataFrame:
    if df is None or df.empty or "data_churn" not in df.columns:
        return df
    ini = pd.Timestamp(data_ini)
    fim = pd.Timestamp(data_fim)
    mask = df["data_churn"].notna() & (df["data_churn"] >= ini) & (df["data_churn"] <= fim)
    return df.loc[mask].copy()


def churn_pos_kpis(df: pd.DataFrame) -> dict:
    """KPIs sobre um subconjunto de churns (período ou histórico)."""
    empty = {
        "total": 0,
        "com_pos": 0,
        "sem_pos": 0,
        "pct_com_pos": 0.0,
        "pos_com_cancelamentos": 0,
        "montante": 0.0,
        "receita": 0.0,
        "ticket_medio": None,
    }
    if df is None or df.empty:
        return empty
    total = len(df)
    com = int(df["identificado_pos"].sum()) if "identificado_pos" in df.columns else 0
    mont = float(df["montante"].fillna(0).sum()) if "montante" in df.columns else 0.0
    rec = float(df["receita"].fillna(0).sum()) if "receita" in df.columns else 0.0
    ticket = (mont / total) if total and mont else None
    pos_distintos = 0
    if "pos_venda" in df.columns and "identificado_pos" in df.columns:
        pos_distintos = int(df.loc[df["identificado_pos"], "pos_venda"].nunique())
    return {
        "total": total,
        "com_pos": com,
        "sem_pos": total - com,
        "pct_com_pos": _safe_div(com, total) * 100,
        "pos_com_cancelamentos": pos_distintos,
        "montante": mont,
        "receita": rec,
        "ticket_medio": ticket,
    }


def churn_pos_ranking(
    df_periodo: pd.DataFrame,
    df_historico: pd.DataFrame,
) -> pd.DataFrame:
    """Ranking por pós-venda: métricas do período + churns históricos totais."""
    cols = [
        "pos_venda",
        "pos_ativo",
        "churns_periodo",
        "pct_churn_periodo",
        "churns_historicos",
        "ultimo_contato_pos",
        "qtd_contatos_pos",
        "montante_churn",
        "receita_churn",
        "ticket_medio",
    ]
    if df_periodo is None or df_periodo.empty:
        return pd.DataFrame(columns=cols)

    total_periodo = len(df_periodo)
    g = df_periodo.groupby("pos_venda", as_index=False).agg(
        churns_periodo=("deal_id", "count"),
        ultimo_contato_pos=("ultimo_contato_pos", "max"),
        qtd_contatos_pos=("qtd_contatos_pos", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
        montante_churn=("montante", "sum"),
        receita_churn=("receita", "sum"),
    )
    g["pct_churn_periodo"] = g["churns_periodo"].apply(
        lambda n: _safe_div(n, total_periodo) * 100
    )

    if df_historico is not None and not df_historico.empty:
        hist = (
            df_historico.groupby("pos_venda", as_index=False)
            .agg(churns_historicos=("deal_id", "count"))
        )
        g = g.merge(hist, on="pos_venda", how="left")
    else:
        g["churns_historicos"] = 0
    g["churns_historicos"] = g["churns_historicos"].fillna(0).astype(int)

    ativo_map: dict[str, str] = {}
    if "pos_ativo" in df_periodo.columns:
        for pos in g["pos_venda"]:
            rows = df_periodo.loc[df_periodo["pos_venda"] == pos, "pos_ativo"]
            vals = [v for v in rows.dropna().astype(str) if v.strip()]
            ativo_map[pos] = vals[0] if vals else ""
    g["pos_ativo"] = g["pos_venda"].map(ativo_map).fillna("")

    vendas_pos = g["churns_periodo"].replace(0, pd.NA)
    g["ticket_medio"] = (g["montante_churn"] / vendas_pos).fillna(0.0)

    return g.sort_values("churns_periodo", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Cancelamentos por Pós-venda (activities Consulta canceladas) — Executivas
# ---------------------------------------------------------------------------

CANCEL_POS_SEM_IDENTIFICADO = CHURN_POS_SEM_IDENTIFICADO


def _cancelamentos_pos_to_naive_datetime_series(s) -> pd.Series:
    """Normaliza série de datas para naive (comparação na aba Cancelamentos por Pós)."""
    return pd.to_datetime(s, errors="coerce", utc=True).dt.tz_localize(None)


def _cancelamentos_pos_to_naive_timestamp(v):
    """Normaliza valor escalar para Timestamp naive ou NaT."""
    ts = pd.to_datetime(v, errors="coerce", utc=True)
    if pd.isna(ts):
        return pd.NaT
    return ts.tz_localize(None)


def _cancelamentos_pos_pick_contato(
    contatos: pd.DataFrame,
    dt_cancel: pd.Timestamp | None,
) -> tuple[str | None, pd.Timestamp | None, int, str]:
    """Escolhe contato pós: preferência até a data do cancelamento; senão o mais recente."""
    if contatos is None or contatos.empty:
        return None, None, 0, ""
    c = contatos.copy()
    c["dt_contato"] = _cancelamentos_pos_to_naive_datetime_series(c["dt_contato"])
    c = c[c["pos_nome_candidato"].notna() & (c["pos_nome_candidato"].astype(str).str.strip() != "")]
    if c.empty:
        return None, None, 0, ""
    qtd = len(c)
    dt_cancel = _cancelamentos_pos_to_naive_timestamp(dt_cancel)
    pool = c
    if pd.notna(dt_cancel):
        antes = c[c["dt_contato"].notna() & (c["dt_contato"] <= dt_cancel)]
        if not antes.empty:
            pool = antes
    pool = pool.sort_values("dt_contato", ascending=False, na_position="last")
    row = pool.iloc[0]
    return (
        str(row["pos_nome_candidato"]).strip(),
        row["dt_contato"],
        qtd,
        str(row.get("origem", "") or ""),
    )


def _cancelamentos_pos_resolver_nome_pos(
    nome_candidato: str | None,
    by_crm: dict,
    tokens_list: list,
) -> tuple[str, str, str]:
    """Devolve (nome_exibicao, ativo, origem_cadastro)."""
    if not nome_candidato or not str(nome_candidato).strip():
        return CANCEL_POS_SEM_IDENTIFICADO, "", ""
    resolved = _match_pos_oficial(
        id_crm=None,
        nome_candidato=str(nome_candidato),
        by_crm=by_crm,
        tokens_list=tokens_list,
    )
    if resolved:
        return resolved[0], resolved[1], resolved[2]
    return str(nome_candidato).strip(), "", "nome bruto (sem match cadastro)"


def cancelamentos_pos_processar(
    df_atividades: pd.DataFrame,
    df_contatos_pos: pd.DataFrame,
    df_oficiais: pd.DataFrame,
) -> pd.DataFrame:
    """Agrega activities canceladas por e-mail e cruza com contatos de pós."""
    cols = [
        "email_norm",
        "email",
        "nome_cliente",
        "deal_id",
        "qtd_cancelamentos",
        "data_cancelamento",
        "motivo_cancelamento",
        "closer_nome",
        "time_vendas",
        "status_reuniao",
        "pos_venda",
        "pos_ativo",
        "origem_vinculo",
        "identificado_pos",
        "ultimo_contato_pos",
        "qtd_contatos_pos",
    ]
    if df_atividades is None or df_atividades.empty:
        return pd.DataFrame(columns=cols)

    acts = df_atividades.copy()
    acts["email_norm"] = acts.get("email_norm", pd.Series(dtype=object)).astype(str).str.strip().str.lower()
    acts = acts[acts["email_norm"].notna() & (acts["email_norm"] != "")]
    if acts.empty:
        return pd.DataFrame(columns=cols)

    for col in ("data_cancelamento", "ts_cancelamento"):
        if col in acts.columns:
            acts[col] = pd.to_datetime(acts[col], errors="coerce")

    contatos = df_contatos_pos.copy() if df_contatos_pos is not None else pd.DataFrame()
    if not contatos.empty and "email_norm" in contatos.columns:
        contatos["email_norm"] = contatos["email_norm"].astype(str).str.strip().str.lower()
        contatos["dt_contato"] = pd.to_datetime(contatos["dt_contato"], errors="coerce")

    by_crm, tokens_list = _build_pos_venda_oficiais_maps(df_oficiais)
    rows: list[dict] = []

    for email_norm, grp in acts.groupby("email_norm", sort=False):
        grp = grp.sort_values(
            ["ts_cancelamento", "data_cancelamento", "activity_id"],
            ascending=False,
            na_position="last",
        )
        ult = grp.iloc[0]
        dt_cancel = ult.get("ts_cancelamento") or ult.get("data_cancelamento")
        if pd.isna(dt_cancel):
            dt_cancel = grp["data_cancelamento"].max()

        sub_pos = (
            contatos.loc[contatos["email_norm"] == email_norm]
            if not contatos.empty
            else pd.DataFrame()
        )
        nome_bruto, dt_pos, qtd_pos, origem_bruta = _cancelamentos_pos_pick_contato(
            sub_pos, dt_cancel if pd.notna(dt_cancel) else None,
        )
        pos_nome, pos_ativo, origem_cad = _cancelamentos_pos_resolver_nome_pos(
            nome_bruto, by_crm, tokens_list,
        )
        origem_final = origem_cad or origem_bruta
        if pos_nome == CANCEL_POS_SEM_IDENTIFICADO:
            origem_final = ""

        rows.append({
            "email_norm": email_norm,
            "email": ult.get("email") or email_norm,
            "nome_cliente": ult.get("nome_cliente"),
            "deal_id": ult.get("deal_id"),
            "qtd_cancelamentos": int(len(grp)),
            "data_cancelamento": grp["data_cancelamento"].max(),
            "motivo_cancelamento": ult.get("motivo_cancelamento"),
            "closer_nome": ult.get("closer_nome"),
            "time_vendas": ult.get("time_vendas"),
            "status_reuniao": ult.get("status_reuniao"),
            "pos_venda": pos_nome,
            "pos_ativo": pos_ativo,
            "origem_vinculo": origem_final,
            "identificado_pos": pos_nome != CANCEL_POS_SEM_IDENTIFICADO,
            "ultimo_contato_pos": dt_pos,
            "qtd_contatos_pos": qtd_pos,
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out["data_cancelamento"] = pd.to_datetime(
            out["data_cancelamento"], errors="coerce"
        )
        out["ultimo_contato_pos"] = pd.to_datetime(
            out["ultimo_contato_pos"], errors="coerce"
        )
    return out


def cancelamentos_pos_venda_aplicar_cadastro(
    df: pd.DataFrame,
    df_oficiais: pd.DataFrame,
) -> pd.DataFrame:
    """Compat: se receber activities sem cruzamento, devolve vazio (use processar)."""
    if df is None or df.empty:
        return df
    if "email_norm" in df.columns and "qtd_cancelamentos" in df.columns:
        return df
    return cancelamentos_pos_processar(df, pd.DataFrame(), df_oficiais)


def cancelamentos_pos_filtrar_periodo(
    df: pd.DataFrame,
    data_ini,
    data_fim,
) -> pd.DataFrame:
    """Filtra por data do cancelamento (activity ou e-mail agregado)."""
    if df is None or df.empty or "data_cancelamento" not in df.columns:
        return df
    out = df.copy()
    out["data_cancelamento"] = pd.to_datetime(out["data_cancelamento"], errors="coerce")
    ini = pd.Timestamp(data_ini)
    fim = pd.Timestamp(data_fim)
    mask = (
        out["data_cancelamento"].notna()
        & (out["data_cancelamento"] >= ini)
        & (out["data_cancelamento"] <= fim)
    )
    return out.loc[mask].copy()


def cancelamentos_pos_filtrar_periodo_atividades(
    df_atividades: pd.DataFrame,
    data_ini,
    data_fim,
) -> pd.DataFrame:
    return cancelamentos_pos_filtrar_periodo(df_atividades, data_ini, data_fim)


def cancelamentos_pos_filtrar_times(
    df: pd.DataFrame,
    times_sel: list | None,
) -> pd.DataFrame:
    if df is None or df.empty or not times_sel or "time_vendas" not in df.columns:
        return df
    mask = pd.Series(False, index=df.index)
    for t in times_sel:
        mask |= df["time_vendas"].astype(str).str.strip() == str(t).strip()
    return df.loc[mask].copy()


def cancelamentos_pos_kpis(df: pd.DataFrame) -> dict:
    """KPIs da aba Cancelamentos por Pós-venda."""
    empty = {
        "total": 0,
        "com_pos": 0,
        "sem_pos": 0,
        "pct_com_pos": 0.0,
        "pos_com_cancelamentos": 0,
    }
    if df is None or df.empty:
        return empty
    total = len(df)
    com = int(df["identificado_pos"].sum()) if "identificado_pos" in df.columns else 0
    pos_distintos = 0
    if "pos_venda" in df.columns and "identificado_pos" in df.columns:
        pos_distintos = int(
            df.loc[df["identificado_pos"], "pos_venda"].nunique()
        )
    return {
        "total": total,
        "com_pos": com,
        "sem_pos": total - com,
        "pct_com_pos": _safe_div(com, total) * 100,
        "pos_com_cancelamentos": pos_distintos,
    }


def _mode_or_first(series: pd.Series):
    s = series.dropna().astype(str)
    s = s[s.str.strip() != ""]
    if s.empty:
        return ""
    modes = s.mode()
    return modes.iloc[0] if not modes.empty else s.iloc[0]


def cancelamentos_pos_ranking(
    df_periodo: pd.DataFrame,
    df_historico: pd.DataFrame,
) -> pd.DataFrame:
    """Ranking por pós-venda: e-mails cancelados (período + histórico)."""
    cols = [
        "pos_venda",
        "pos_ativo",
        "emails_periodo",
        "pct_emails_periodo",
        "emails_historicos",
        "ultimo_contato_pos",
        "qtd_contatos_pos",
        "origem_principal",
    ]
    if df_periodo is None or df_periodo.empty:
        return pd.DataFrame(columns=cols)

    total_periodo = len(df_periodo)
    g = df_periodo.groupby("pos_venda", as_index=False).agg(
        emails_periodo=("email_norm", "count"),
        ultimo_contato_pos=("ultimo_contato_pos", "max"),
        qtd_contatos_pos=(
            "qtd_contatos_pos",
            lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        ),
        origem_principal=("origem_vinculo", _mode_or_first),
    )
    g["pct_emails_periodo"] = g["emails_periodo"].apply(
        lambda n: _safe_div(n, total_periodo) * 100
    )

    if df_historico is not None and not df_historico.empty:
        hist = (
            df_historico.groupby("pos_venda", as_index=False)
            .agg(emails_historicos=("email_norm", "count"))
        )
        g = g.merge(hist, on="pos_venda", how="left")
    else:
        g["emails_historicos"] = 0
    g["emails_historicos"] = g["emails_historicos"].fillna(0).astype(int)

    ativo_map: dict[str, str] = {}
    if "pos_ativo" in df_periodo.columns:
        for pos in g["pos_venda"]:
            rows = df_periodo.loc[df_periodo["pos_venda"] == pos, "pos_ativo"]
            vals = [v for v in rows.dropna().astype(str) if v.strip()]
            ativo_map[pos] = vals[0] if vals else ""
    g["pos_ativo"] = g["pos_venda"].map(ativo_map).fillna("")

    return g.sort_values("emails_periodo", ascending=False).reset_index(drop=True)


def cancelamentos_pos_diagnostico(
    df_atividades: pd.DataFrame | None,
    df_emails: pd.DataFrame | None,
) -> dict:
    """Contagens para validação: activities ≠ deals ≠ e-mails."""
    acts = df_atividades if df_atividades is not None else pd.DataFrame()
    emails = df_emails if df_emails is not None else pd.DataFrame()
    sem_email = 0
    if not acts.empty and "email_norm" in acts.columns:
        en = acts["email_norm"].astype(str).str.strip().str.lower()
        sem_email = int((en.isna() | (en == "")).sum())
    return {
        "qtd_activities": int(len(acts)),
        "qtd_deals": int(acts["deal_id"].nunique()) if not acts.empty and "deal_id" in acts.columns else 0,
        "qtd_emails_unicos": int(emails["email_norm"].nunique()) if not emails.empty and "email_norm" in emails.columns else 0,
        "activities_sem_email": sem_email,
        "qtd_emails_com_pos": int(emails["identificado_pos"].sum()) if not emails.empty and "identificado_pos" in emails.columns else 0,
        "qtd_emails_sem_pos": int((~emails["identificado_pos"]).sum()) if not emails.empty and "identificado_pos" in emails.columns else 0,
    }


# ---------------------------------------------------------------------------
# Lead In & Agendamentos (aba Executivas & Times)
# Classificação de agendamentos: coluna `stage` de zoho_deals (validado
# jun/2026). `triagem` é apenas informação complementar do CRM.
# ---------------------------------------------------------------------------

TRIAGEM_EXIBICAO_MAP = {
    "Sem informação": "Sem informação",
    "Não iniciada": "Não iniciada",
    "Concluída": "Triagem concluída",
    "Lead qualificado": "Lead qualificado",
    "Lead desqualificado": "Lead desqualificado",
}

_STAGE_LEAD_IN = "Lead-in"
_STAGE_RECEPCAO = "Recepção"
_STAGE_REUNIAO_AGENDADA = "Reunião Agendada"
_STAGE_REUNIAO_CONCLUIDA = "Reunião Concluída"
_STAGES_CLASSIFICAVEIS = frozenset({_STAGE_RECEPCAO, _STAGE_REUNIAO_AGENDADA})

# Rótulos amigáveis para `stage` (aba Lead In & Agendamentos).
STAGE_EXIBICAO_MAP = {
    _STAGE_RECEPCAO: "Não Qualificados",
    _STAGE_REUNIAO_AGENDADA: "Qualificados",
}
STAGE_LABEL_NAO_QUALIFICADOS = "Não Qualificados"
STAGE_LABEL_QUALIFICADOS = "Qualificados"
STAGE_HINT_NAO_QUALIFICADOS = "Não Qualificados = stage Recepção"
STAGE_HINT_QUALIFICADOS = "Qualificados = stage Reunião Agendada"
STAGE_HINT_CLASSIFICAVEL = "Não Qualificados + Qualificados"
STAGE_HINT_PCT_QUALIFICADOS = "Qualificados ÷ total classificável"
STAGE_HINT_OUTRAS_ETAPAS = "fora de Não Qualificados/Qualificados"
STAGE_ETAPA_CHART_ORDER = [STAGE_LABEL_NAO_QUALIFICADOS, STAGE_LABEL_QUALIFICADOS]
_STAGE_NO_SHOW = frozenset({"No-show", "Não compareceu"})
_STAGE_GANHO = frozenset({"Ganho", "Fechado Ganho"})
_STAGE_PERDIDO = frozenset({"Perdido"})


def _stage_norm(stage_series: pd.Series) -> pd.Series:
    return stage_series.astype(str).str.strip()


def _count_stage(stage_series: pd.Series, stage_value: str) -> int:
    return int((_stage_norm(stage_series) == stage_value).sum())


def _count_stages(stage_series: pd.Series, stage_values: set[str] | frozenset[str]) -> int:
    return int(_stage_norm(stage_series).isin(stage_values).sum())


def _triagem_agg_complemento(df: pd.DataFrame) -> dict[str, int]:
    """Contagens por `triagem` — dimensão complementar à etapa (`stage`)."""
    tri = (
        df["triagem_tratada"].astype(str)
        if "triagem_tratada" in df.columns
        else pd.Series(dtype=str)
    )
    return {
        "triagem_nao_iniciada": int((tri == "Não iniciada").sum()),
        "triagem_concluida": int((tri == "Concluída").sum()),
        "triagem_lead_qualificado": int((tri == "Lead qualificado").sum()),
        "triagem_lead_desqualificado": int((tri == "Lead desqualificado").sum()),
        "triagem_sem_info": int((tri == "Sem informação").sum()),
    }


def triagem_preparar_deals(df: pd.DataFrame) -> pd.DataFrame:
    """Enriquece deals com rótulos amigáveis de triagem."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if "triagem_tratada" in out.columns:
        out["triagem_exibicao"] = out["triagem_tratada"].map(
            TRIAGEM_EXIBICAO_MAP
        ).fillna(out["triagem_tratada"].astype(str))
    if "data_criacao" in out.columns:
        out["data_criacao"] = pd.to_datetime(out["data_criacao"], errors="coerce")
    return out


def triagem_aplicar_exibicao(
    df: pd.DataFrame,
    exibicao: str,
    df_oficiais_ativos: pd.DataFrame | None,
    df_oficiais_todos: pd.DataFrame | None,
) -> pd.DataFrame:
    """Ativos: só closers do cadastro oficial. Histórico: todos, nomes canônicos."""
    if df is None or df.empty or "executiva" not in df.columns:
        return df
    if exibicao == RANKING_EXIBICAO_HISTORICO:
        cadastro = df_oficiais_todos
        if cadastro is None or cadastro.empty:
            cadastro = df_oficiais_ativos
        return executivas_canonicalizar_executivas(df, cadastro)
    return executivas_filtrar_time_oficial(df, df_oficiais_ativos)


def triagem_contar_leads(
    df_leads: pd.DataFrame,
    times_sel: list | None,
    exibicao: str,
    df_oficiais_ativos: pd.DataFrame | None,
    df_oficiais_todos: pd.DataFrame | None,
) -> int:
    """Total de leads no período (fonte leads_visao_geral), com filtros da aba."""
    if df_leads is None or df_leads.empty:
        return 0
    out = df_leads.copy()
    out = cancelamentos_pos_filtrar_times(out, times_sel)
    out = triagem_aplicar_exibicao(
        out,
        exibicao,
        df_oficiais_ativos,
        df_oficiais_todos,
    )
    return len(out)


def triagem_kpis(df_deals: pd.DataFrame, total_leads: int) -> dict:
    """Resumo geral: leads, deals e agendamentos por `stage`."""
    empty = {
        "total_leads": total_leads,
        "total_deals": 0,
        "lead_in": 0,
        "agendamentos_nao_qualificados": 0,
        "agendamentos_qualificados": 0,
        "total_agendamentos_classificaveis": 0,
        "outras_etapas": 0,
        "pct_qualificados": 0.0,
        "reunioes_concluidas": 0,
    }
    if df_deals is None or df_deals.empty:
        return empty
    stage = df_deals["stage"] if "stage" in df_deals.columns else pd.Series(dtype=str)
    ag_nao_qual = _count_stage(stage, _STAGE_RECEPCAO)
    ag_qual = _count_stage(stage, _STAGE_REUNIAO_AGENDADA)
    total_class = ag_nao_qual + ag_qual
    total_deals = len(df_deals)
    return {
        "total_leads": total_leads,
        "total_deals": total_deals,
        "lead_in": _count_stage(stage, _STAGE_LEAD_IN),
        "agendamentos_nao_qualificados": ag_nao_qual,
        "agendamentos_qualificados": ag_qual,
        "total_agendamentos_classificaveis": total_class,
        "outras_etapas": total_deals - total_class,
        "pct_qualificados": _safe_div(ag_qual, total_class) * 100,
        "reunioes_concluidas": _count_stage(stage, _STAGE_REUNIAO_CONCLUIDA),
    }


def _stage_raw(stage_raw) -> str:
    if stage_raw is None or (isinstance(stage_raw, float) and pd.isna(stage_raw)):
        return ""
    return str(stage_raw).strip()


def _etapa_exibicao(stage_raw) -> str:
    raw = _stage_raw(stage_raw)
    if not raw:
        return "Sem etapa"
    return STAGE_EXIBICAO_MAP.get(raw, raw)


def _etapa_entra_classificavel(stage_raw) -> bool:
    return _stage_raw(stage_raw) in _STAGES_CLASSIFICAVEIS


def _etapa_sort_key(etapa: str) -> int:
    order = {v: i for i, v in enumerate(STAGE_ETAPA_CHART_ORDER)}
    return order.get(etapa, 99)


def triagem_por_etapa(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela agregada por `stage` com triagem como complemento informativo.

    Lista todas as etapas presentes no recorte (inclui deals fora de
    Recepção/Reunião Agendada) para explicar a diferença entre Total de
    Deals e Total classificável.
    """
    cols = [
        "etapa",
        "entra_classificavel",
        "total_deals",
        "pct_deals",
        "triagem_nao_iniciada",
        "triagem_concluida",
        "triagem_lead_qualificado",
        "triagem_lead_desqualificado",
        "triagem_sem_info",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    total = len(df)
    rows = []
    for etapa_raw, grp in df.groupby("stage", dropna=False):
        triagem = _triagem_agg_complemento(grp)
        n = len(grp)
        etapa = _etapa_exibicao(etapa_raw)
        rows.append({
            "etapa": etapa,
            "entra_classificavel": _etapa_entra_classificavel(etapa_raw),
            "total_deals": n,
            "pct_deals": _safe_div(n, total) * 100,
            **triagem,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=cols)
    out["_ord_class"] = out["entra_classificavel"].map({True: 0, False: 1})
    out["_ord_etapa"] = out["etapa"].map(_etapa_sort_key)
    return out.sort_values(
        ["_ord_class", "_ord_etapa", "total_deals", "etapa"],
        ascending=[True, True, False, True],
    ).drop(columns=["_ord_class", "_ord_etapa"]).reset_index(drop=True)


def triagem_por_executiva(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela por executiva/closer — agendamentos por `stage`."""
    cols = [
        "executiva",
        "total_deals",
        "lead_in",
        "agendamentos_nao_qualificados",
        "agendamentos_qualificados",
        "total_classificavel",
        "pct_qualificados",
        "reuniao_concluida",
        "no_show",
        "ganho",
        "perdido",
    ]
    if df is None or df.empty or "executiva" not in df.columns:
        return pd.DataFrame(columns=cols)

    rows = []
    for executiva, grp in df.groupby("executiva", dropna=False):
        stage = grp["stage"] if "stage" in grp.columns else pd.Series(dtype=str)
        ag_nao_qual = _count_stage(stage, _STAGE_RECEPCAO)
        ag_qual = _count_stage(stage, _STAGE_REUNIAO_AGENDADA)
        total_class = ag_nao_qual + ag_qual
        rows.append({
            "executiva": executiva,
            "total_deals": len(grp),
            "lead_in": _count_stage(stage, _STAGE_LEAD_IN),
            "agendamentos_nao_qualificados": ag_nao_qual,
            "agendamentos_qualificados": ag_qual,
            "total_classificavel": total_class,
            "pct_qualificados": _safe_div(ag_qual, total_class) * 100,
            "reuniao_concluida": _count_stage(stage, _STAGE_REUNIAO_CONCLUIDA),
            "no_show": _count_stages(stage, _STAGE_NO_SHOW),
            "ganho": _count_stages(stage, _STAGE_GANHO),
            "perdido": _count_stages(stage, _STAGE_PERDIDO),
        })
    out = pd.DataFrame(rows)
    return out.sort_values("total_deals", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Agendamentos do Funil absoluto (bi.vw_dashboard_comercial_executivas_rw)
# ---------------------------------------------------------------------------

def funil_agendamentos_kpis(df: pd.DataFrame) -> dict:
    """KPIs sobre activities do funil cruzadas com zoho_deals.stage atual."""
    empty = {
        "total": 0,
        "recepcao": 0,
        "reuniao_agendada": 0,
        "total_classificavel": 0,
        "outras_etapas": 0,
        "pct_qualificados": 0.0,
        "sem_deal": 0,
    }
    if df is None or df.empty:
        return empty
    stage = df["stage"] if "stage" in df.columns else pd.Series(dtype=str)
    recepcao = _count_stage(stage, _STAGE_RECEPCAO)
    reuniao_ag = _count_stage(stage, _STAGE_REUNIAO_AGENDADA)
    total_class = recepcao + reuniao_ag
    total = len(df)
    sem_deal = 0
    if "deal_id" in df.columns:
        sem_deal = int(
            (df["deal_id"].isna() | (df["deal_id"].astype(str).str.strip() == "")).sum()
        )
    return {
        "total": total,
        "recepcao": recepcao,
        "reuniao_agendada": reuniao_ag,
        "total_classificavel": total_class,
        "outras_etapas": total - total_class,
        "pct_qualificados": _safe_div(reuniao_ag, total_class) * 100,
        "sem_deal": sem_deal,
    }


def funil_agendamentos_por_stage(df: pd.DataFrame) -> pd.DataFrame:
    """Distribuição dos agendamentos do funil por stage atual do deal."""
    cols = [
        "etapa",
        "entra_classificavel",
        "total_agendamentos",
        "pct_agendamentos",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    total = len(df)
    rows = []
    for etapa_raw, grp in df.groupby("stage", dropna=False):
        etapa = _etapa_exibicao(etapa_raw)
        n = len(grp)
        rows.append({
            "etapa": etapa,
            "entra_classificavel": _etapa_entra_classificavel(etapa_raw),
            "total_agendamentos": n,
            "pct_agendamentos": _safe_div(n, total) * 100,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=cols)
    out["_ord_class"] = out["entra_classificavel"].map({True: 0, False: 1})
    out["_ord_etapa"] = out["etapa"].map(_etapa_sort_key)
    return out.sort_values(
        ["_ord_class", "_ord_etapa", "total_agendamentos", "etapa"],
        ascending=[True, True, False, True],
    ).drop(columns=["_ord_class", "_ord_etapa"]).reset_index(drop=True)


def funil_agendamentos_por_executiva(df: pd.DataFrame) -> pd.DataFrame:
    """Agendamentos do funil por executiva — classificação por `stage` do deal."""
    cols = [
        "executiva",
        "total_agendamentos",
        "nao_qualificados",
        "qualificados",
        "total_classificavel",
        "pct_qualificados",
        "reuniao_concluida",
        "no_show",
        "ganho",
        "lead_in",
        "outras_etapas",
    ]
    if df is None or df.empty or "executiva" not in df.columns:
        return pd.DataFrame(columns=cols)

    rows = []
    for executiva, grp in df.groupby("executiva", dropna=False):
        stage = grp["stage"] if "stage" in grp.columns else pd.Series(dtype=str)
        nao_qual = _count_stage(stage, _STAGE_RECEPCAO)
        qual = _count_stage(stage, _STAGE_REUNIAO_AGENDADA)
        total_class = nao_qual + qual
        total = len(grp)
        rows.append({
            "executiva": executiva,
            "total_agendamentos": total,
            "nao_qualificados": nao_qual,
            "qualificados": qual,
            "total_classificavel": total_class,
            "pct_qualificados": _safe_div(qual, total_class) * 100,
            "reuniao_concluida": _count_stage(stage, _STAGE_REUNIAO_CONCLUIDA),
            "no_show": _count_stages(stage, _STAGE_NO_SHOW),
            "ganho": _count_stages(stage, _STAGE_GANHO),
            "lead_in": _count_stage(stage, _STAGE_LEAD_IN),
            "outras_etapas": total - total_class,
        })
    out = pd.DataFrame(rows)
    return out.sort_values(
        ["total_agendamentos", "qualificados", "executiva"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
