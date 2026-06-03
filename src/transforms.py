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
    "Ganhos +12":       "ganhos_mais_12",
    "Ganhos -12":       "ganhos_menos_12",
    "Ganhos Não atua":  "ganhos_nao_atua",
    "Cancelados":       "cancelados",
    "Churn":            "churn",
    "Vencidos":         "vencidos",
}
EXECUTIVAS_RANKING_METRICAS_FINANCEIRAS = frozenset({
    "receita", "montante",
    "receita_mais_12", "receita_menos_12", "receita_nao_atua",
    "montante_mais_12", "montante_menos_12", "montante_nao_atua",
})
EXECUTIVAS_RANKING_METRICAS_NEUTRAS = frozenset({
    "receita", "montante", "vendas", "agendamentos", "comparecimentos",
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
    classificacao_crm_filtro, sdr_filtro, closer_filtro, status_filtro,
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


def vendas_detalhe_filtrar_closer(df_det_norm: pd.DataFrame,
                                  closer_nome: str) -> pd.Series:
    """Mask booleana — linhas do detalhe cujo `closer_filtro` casa com
    `closer_nome` (match exato, espaços normalizados).

    O ranking de Vendas expõe `executiva` = `TRIM(first_name||' '||last_name)`
    via zoho_users (com fallback pro owner_id quando não pareia); o detalhe
    expõe `closer_filtro` com a mesma fórmula (fallback 'Sem Closer'). Match
    string-exato funciona pra todos os closers cadastrados em zoho_users.
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
    return {
        "total": total,
        "com_pos": com,
        "sem_pos": total - com,
        "pct_com_pos": _safe_div(com, total) * 100,
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
