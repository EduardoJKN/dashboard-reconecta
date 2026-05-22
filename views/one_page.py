"""One Page — visão executiva consolidada (Marketing + Pré-vendas + Vendas).

Recriação fiel do One Page legado do Looker em Streamlit. Pensada
para o CEO bater o olho rapidamente: leads, aplicações, agendamentos,
comparecimentos, vendas, montante/receita e investimento, com cortes
por fonte de lead, executiva e SDR×Closer.

MVP — opção pelo CEO:
  - filtro de período apenas (sem closer/times/canal no header).
  - Cards e gráficos de Marketing usam a regra LEGADA do Looker via
    `get_one_page_legacy_diario`. Aplicações vêm de
    `fdw_reconecta.typeform_aplicacoes` (não de `leads_qualificados`)
    e investimento vem de `fdw_reconecta.anuncios` (REL_02* excluído).
    Esse investimento pode diferir em ~R$ 10–20 de
    `bi.vw_investimento_diario` (Google Ads não está na fdw da Meta).
  - Tabela "Por Fonte de Lead" mostra só as colunas confiáveis hoje.
    Agendamentos / Comparecimentos / %Conversão / %Venda /
    %Comparecimento por canal ficam no backlog (precisa atribuir
    activities/deals por canal — não existe view nem chave de match).

Fontes:
  - get_one_page_legacy_diario                          (Marketing One Page)
  - get_executivas / get_investimento_diario            (Vendas)
  - get_media_movel_vendas                              (Vendas)
  - get_mkt_visao_geral_kpis_canal                      (tabela "Por Fonte")
  - get_prevendas_overview_diario / _por_sdr / _sdr_closer (Pré-vendas)

Performance via `@st.cache_data(ttl=600)` em todos os repositories.
"""
from __future__ import annotations

import html
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.marketing_queries import get_mkt_visao_geral_kpis_canal
from src.marketing_safe import safe_run
from src.prevendas_transforms import prevendas_overview_kpis
from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_media_movel_vendas,
    get_one_page_legacy_diario,
    get_one_page_prevendas_por_fonte,
    get_prevendas_overview_diario,
    get_prevendas_sdr_closer,
)
from src.transforms import (
    delta_pct,
    executivas_ranking,
    visao_geral_kpis,
)
from src.ui.charts import _base_layout, _style_axes, area
from src.ui.components import (
    metric_card_v2,
    ranking_column_config,
    section_title,
)
from src.ui.page import start_page
from src.ui.theme import PALETTE, brl, brl_short, int_br, pct

# =============================================================================
# Helpers locais — específicos da One Page. Mantidos aqui (não em
# `src/transforms.py`) por preferência do user: agrupar transforms perto do
# bloco da página que os consome.
# =============================================================================


def _safe_div(num, den):
    try:
        d = float(den or 0)
        return float(num or 0) / d if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def _sum(df: pd.DataFrame, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(df[col].fillna(0).sum())


def _aplicacoes_kpis(df_one: pd.DataFrame) -> dict:
    """KPIs de Marketing do bloco superior — regra LEGADA do Looker.

    Agrega `get_one_page_legacy_diario` no período. "Aplicações" =
    submissões únicas/dia em `fdw_reconecta.typeform_aplicacoes`. CPL,
    Custo/Aplicação e Custo/Aplicação +12 usam o investimento da MESMA
    query (anuncios, sem campanhas REL_02*) — mantém coerência com o
    Looker e evita misturar fontes de mídia.
    """
    leads        = _sum(df_one, "novos_leads")
    aplicacoes   = _sum(df_one, "novas_aplicacoes")
    apl_mais12   = _sum(df_one, "aplicacoes_mais_12")
    apl_menos12  = _sum(df_one, "aplicacoes_menos_12")
    apl_naoatua  = _sum(df_one, "aplicacoes_nao_atua")
    investimento = _sum(df_one, "investimento")
    agendamentos = _sum(df_one, "agendamentos")

    return {
        "leads_totais":         leads,
        "aplicacoes":           aplicacoes,
        "aplicacoes_mais_12":   apl_mais12,
        "aplicacoes_menos_12":  apl_menos12,
        "aplicacoes_nao_atua":  apl_naoatua,
        "pct_aplicacoes":       _safe_div(aplicacoes, leads) * 100,
        "investimento":         investimento,
        "cpl":                  _safe_div(investimento, leads),
        "custo_aplicacao":      _safe_div(investimento, aplicacoes),
        "custo_apl_mais_12":    _safe_div(investimento, apl_mais12),
        # Agendamentos da própria query legada (zoho_activities por
        # created_time::date, regra Looker). Permite que % Agendamento
        # seja recalculado sobre a MESMA base de aplicações — alinhado
        # com a definição do CEO.
        "agendamentos_legacy":  agendamentos,
        "pct_agendamento":      _safe_div(agendamentos, aplicacoes) * 100,
    }


# Rótulos canônicos da classificação por FONTE (regra `origem_final` do
# Looker legado). INBOUND = `fonte = 'Inbound'`; SS = `fonte = 'Fábrica'`.
# Outbound existe na SQL (`fonte = 'Outbound'`) mas não vira card próprio
# nesta versão — fica disponível pra futuras seções/tabelas.
_FONTE_INBOUND = "Inbound"
_FONTE_SS = "Fábrica"


def _prev_por_fonte(df_fonte: pd.DataFrame) -> dict:
    """Soma métricas de Pré-vendas por `fonte` (regra origem_final Looker).

    Devolve dict `{fonte: {metric: valor}}` com chaves `'Inbound'` e
    `'Fábrica'` sempre presentes — quando o df vem vazio ou uma das
    fontes não tem linhas no período, devolve zeros (cards exibem "0"
    em vez de "—").
    """
    base = {
        m: 0.0
        for m in ("agendamentos", "agendamentos_vencidos",
                  "agendamentos_mais_12", "agendamentos_menos_12",
                  "agendamentos_criados", "agendamentos_ate_hoje",
                  "agendamentos_mais_12_ate_hoje",
                  "agendamentos_menos_12_ate_hoje",
                  "comparecimentos", "comparecimentos_ate_hoje",
                  "vendas", "montante", "receita")
    }
    out = {_FONTE_INBOUND: dict(base), _FONTE_SS: dict(base)}

    if df_fonte is None or df_fonte.empty or "fonte" not in df_fonte.columns:
        return out

    sum_cols = [c for c in base if c in df_fonte.columns]
    agg = df_fonte.groupby("fonte", as_index=False, dropna=False)[sum_cols].sum()
    for _, row in agg.iterrows():
        f = str(row.get("fonte") or "")
        if f in out:
            for c in sum_cols:
                out[f][c] = float(row.get(c, 0) or 0)
    return out


def _df_evolucao_aplicacoes(df_one: pd.DataFrame) -> pd.DataFrame:
    """Série diária pro gráfico de evolução leads × aplicações (regra legada).

    Aceita o df de `get_one_page_legacy_diario` e renomeia para a
    nomenclatura do gráfico. `leads_totais` ← `novos_leads`,
    `aplicacoes` ← `novas_aplicacoes`."""
    if df_one is None or df_one.empty:
        return pd.DataFrame()
    use = [c for c in ("data_ref", "novos_leads", "novas_aplicacoes",
                       "aplicacoes_mais_12", "aplicacoes_menos_12")
           if c in df_one.columns]
    out = df_one[use].copy().rename(columns={
        "novos_leads":      "leads_totais",
        "novas_aplicacoes": "aplicacoes",
    }).sort_values("data_ref")
    return out


def _tabela_por_fonte(df_kpc: pd.DataFrame) -> pd.DataFrame:
    """Tabela "Por Fonte de Lead" — colunas confiáveis hoje.

    Mantém apenas o que o `mkt_visao_geral_kpis_canal` já entrega por
    canal (invest + leads + financeiro atribuído + derivadas). Colunas
    do briefing que dependem de atribuição de activities por canal —
    Agendamentos / Comparecimentos / %Recebimento por canal /
    %Conversão / %Venda / %Comparecimento — ficam de fora desta versão.
    BACKLOG: criar view `bi.vw_atividades_por_canal` (deal→lead→canal +
    activities) e fazer merge aqui.
    """
    if df_kpc is None or df_kpc.empty:
        return pd.DataFrame()
    cols_in = [
        "canal",
        "leads_totais",
        "leads_mais_12",
        "leads_menos_12",
        "leads_qualificados",
        "vendas_total_geral",
        "vendas_novas_total_geral",
        "montante_total_geral",
        "receita_total_geral",
        "investimento_total_geral",
        "cpl",
        "cpl_qualificado",
        "ticket_medio",
        "roas_total_geral",
    ]
    use = [c for c in cols_in if c in df_kpc.columns]
    out = df_kpc[use].copy()

    # % qualificação +12 / -12 (sobre leads_totais do canal)
    if {"leads_totais", "leads_mais_12"}.issubset(out.columns):
        out["pct_mais_12"] = out.apply(
            lambda r: _safe_div(r["leads_mais_12"], r["leads_totais"]) * 100,
            axis=1,
        )
    if {"leads_totais", "leads_menos_12"}.issubset(out.columns):
        out["pct_menos_12"] = out.apply(
            lambda r: _safe_div(r["leads_menos_12"], r["leads_totais"]) * 100,
            axis=1,
        )
    # % Recebimento por canal (receita/montante) — único derivado seguro
    if {"montante_total_geral", "receita_total_geral"}.issubset(out.columns):
        out["pct_recebimento"] = out.apply(
            lambda r: _safe_div(r["receita_total_geral"],
                                r["montante_total_geral"]) * 100,
            axis=1,
        )

    # Ordem final / renomeação amigável
    rename = {
        "canal":                     "Fonte",
        "leads_totais":              "Leads",
        "leads_mais_12":             "Leads +12",
        "pct_mais_12":               "% +12",
        "leads_menos_12":            "Leads -12",
        "pct_menos_12":              "% -12",
        "leads_qualificados":        "Aplicações",
        "vendas_total_geral":        "Vendas (atrib.)",
        "vendas_novas_total_geral":  "Vendas novas",
        "montante_total_geral":      "Montante",
        "receita_total_geral":       "Receita",
        "pct_recebimento":           "% Recebimento",
        "investimento_total_geral":  "Investimento",
        "cpl":                       "CPL",
        "cpl_qualificado":           "Custo / Aplicação",
        "ticket_medio":              "Ticket médio",
        "roas_total_geral":          "ROAS",
    }
    ordered = [c for c in rename if c in out.columns]
    out = out[ordered].rename(columns=rename)
    if "Leads" in out.columns:
        out = out.sort_values("Leads", ascending=False)
    return out.reset_index(drop=True)


def _tabela_sdr_closer(df_sc: pd.DataFrame) -> pd.DataFrame:
    """Consolida SDR × Closer com derivadas. Inclui apenas pares com
    pelo menos um agendamento ou venda (descarta linhas zeradas)."""
    if df_sc is None or df_sc.empty:
        return pd.DataFrame()
    use_cols = [c for c in (
        "sdr", "closer",
        "agendamentos", "comparecimentos", "vendas",
        "montante", "receita",
    ) if c in df_sc.columns]
    out = df_sc[use_cols].copy()
    # Mesma derivada do prevendas: % comparecimento, conversão, vendas,
    # recebimento. Fórmulas iguais a `executivas_ranking` pra coerência.
    if {"agendamentos", "comparecimentos"}.issubset(out.columns):
        out["pct_comparecimento"] = out.apply(
            lambda r: _safe_div(r["comparecimentos"], r["agendamentos"]) * 100,
            axis=1,
        )
    if {"agendamentos", "vendas"}.issubset(out.columns):
        out["pct_conversao"] = out.apply(
            lambda r: _safe_div(r["vendas"], r["agendamentos"]) * 100,
            axis=1,
        )
    if {"comparecimentos", "vendas"}.issubset(out.columns):
        out["pct_vendas"] = out.apply(
            lambda r: _safe_div(r["vendas"], r["comparecimentos"]) * 100,
            axis=1,
        )
    if {"montante", "receita"}.issubset(out.columns):
        out["pct_recebimento"] = out.apply(
            lambda r: _safe_div(r["receita"], r["montante"]) * 100,
            axis=1,
        )
    # Mantém só pares com atividade
    if {"agendamentos", "vendas"}.issubset(out.columns):
        out = out[(out["agendamentos"] > 0) | (out["vendas"] > 0)]
    if "agendamentos" in out.columns:
        out = out.sort_values(["agendamentos", "vendas"], ascending=False)
    return out.reset_index(drop=True)


def _tabela_semanal(df_one: pd.DataFrame,
                    df_prev_dia: pd.DataFrame,
                    df_exec: pd.DataFrame) -> pd.DataFrame:
    """Indicadores semanais consolidados.

    Marketing (`df_one`) vem da regra LEGADA do Looker — leads/aplicações/
    investimento direto dela. Pré-vendas e Vendas mantêm suas fontes
    próprias. Agregação Pandas por ISO-week.
    """
    def _by_week(df: pd.DataFrame, agg_map: dict) -> pd.DataFrame:
        if df is None or df.empty or "data_ref" not in df.columns:
            return pd.DataFrame(columns=["semana"] + list(agg_map.keys()))
        d = df.copy()
        d["data_ref"] = pd.to_datetime(d["data_ref"])
        iso = d["data_ref"].dt.isocalendar()
        d["semana"] = (iso["year"].astype(str)
                       + "-W"
                       + iso["week"].astype(int).map("{:02d}".format))
        keep = [c for c in agg_map if c in d.columns]
        return (d.groupby("semana", as_index=False)[keep]
                 .agg({c: agg_map[c] for c in keep}))

    # Marketing → leads, aplicações (regra legada)
    sem_mkt = _by_week(df_one, {
        "novos_leads": "sum",
        "novas_aplicacoes": "sum",
        "aplicacoes_mais_12": "sum",
    }).rename(columns={
        "novos_leads":       "leads_totais",
        "novas_aplicacoes":  "leads_qualificados",
        "aplicacoes_mais_12": "leads_mais_12",
    })

    # Pré-vendas → agendamentos, comparecimentos, +12
    sem_prev = _by_week(df_prev_dia, {
        "agendamentos": "sum",
        "agendamentos_mais_12": "sum",
        "comparecimentos": "sum",
    })

    # Vendas → vendas/montante/receita (vem da view executivas)
    sem_vend = _by_week(df_exec, {
        "vendas": "sum",
        "montante": "sum",
        "receita": "sum",
    })

    # Merge progressivo — outer pra não perder semana com 1 fonte
    semanas = pd.DataFrame({"semana": []})
    for src in (sem_mkt, sem_prev, sem_vend):
        if not src.empty:
            semanas = (src if semanas.empty
                       else semanas.merge(src, on="semana", how="outer"))
    if semanas.empty:
        return semanas
    semanas = semanas.fillna(0).sort_values("semana")

    # Derivadas — todas defensivas (col pode não existir se uma fonte falhou)
    def _col(c):
        return semanas[c] if c in semanas.columns else pd.Series(0, index=semanas.index)

    semanas["pct_agendamento"] = (
        _col("agendamentos") / _col("leads_qualificados").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_mais_12"] = (
        _col("agendamentos_mais_12") / _col("agendamentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_comparecimento"] = (
        _col("comparecimentos") / _col("agendamentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_conversao"] = (
        _col("vendas") / _col("agendamentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["pct_vendas"] = (
        _col("vendas") / _col("comparecimentos").replace(0, pd.NA) * 100
    ).fillna(0)
    semanas["ticket_medio"] = (
        _col("montante") / _col("vendas").replace(0, pd.NA)
    ).fillna(0)
    semanas["pct_recebimento"] = (
        _col("receita") / _col("montante").replace(0, pd.NA) * 100
    ).fillna(0)

    # Rename amigável
    rename = {
        "semana":               "Semana",
        "leads_totais":         "Leads",
        "agendamentos":         "Agendamentos",
        "pct_agendamento":      "% Agend.",
        "agendamentos_mais_12": "Agend. +12",
        "pct_mais_12":          "% +12",
        "comparecimentos":      "Comparec.",
        "pct_comparecimento":   "% Comparec.",
        "vendas":               "Vendas",
        "pct_conversao":        "% Conversão",
        "pct_vendas":           "% Vendas",
        "montante":             "Montante",
        "ticket_medio":         "Ticket médio",
        "receita":              "Receita",
        "pct_recebimento":      "% Recebimento",
    }
    ordered = [c for c in rename if c in semanas.columns]
    return semanas[ordered].rename(columns=rename).reset_index(drop=True)


# Ordem das métricas + tipo de formatação — espelha o One Page do Looker.
# Tuplas (label_no_df, kind ∈ {int, money, pct}). Itens fora do df_semanal
# atual são pulados silenciosamente (graceful degrade).
_SEMANAL_LINHAS: list[tuple[str, str]] = [
    ("Leads",         "int"),
    ("Agendamentos",  "int"),
    ("% Agend.",      "pct"),
    ("Agend. +12",    "int"),
    ("% +12",         "pct"),
    ("Comparec.",     "int"),
    ("% Comparec.",   "pct"),
    ("Vendas",        "int"),
    ("% Conversão",   "pct"),
    ("% Vendas",      "pct"),
    ("Montante",      "money"),
    ("Ticket médio",  "money"),
    ("Receita",       "money"),
    ("% Recebimento", "pct"),
]


def _fmt_semanal(v, kind: str) -> str:
    """Formata célula da matriz semanal por tipo. NaN/None → '—'."""
    if v is None:
        return "—"
    try:
        if isinstance(v, float) and v != v:  # NaN
            return "—"
    except Exception:
        pass
    if kind == "money":
        return brl(v)
    if kind == "pct":
        return pct(v)
    return int_br(v)


def _label_semana(semana_str: str, mostrar_ano: bool) -> str:
    """`'2026-W18'` → `'SEMANA_18'`. Se o período cruzar ano (mostrar_ano
    True) acrescenta o ano: `'SEMANA_52_2025'`. Fallback: devolve o
    valor original sem quebrar a renderização."""
    try:
        ano, sem = str(semana_str).split("-W")
        n = int(sem)
        return f"SEMANA_{n:02d}_{ano}" if mostrar_ano else f"SEMANA_{n:02d}"
    except (ValueError, AttributeError):
        return str(semana_str)


_SEMANAL_CSS = """
<style>
.op-semanal-wrap { overflow-x: auto; margin-top: 4px; padding-bottom: 6px; }
.op-semanal {
    width: 100%;
    border-collapse: collapse;
    font-family: Inter, system-ui, sans-serif;
    color: var(--color-text);
}
.op-semanal thead th {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-gold);
    padding: 14px 22px;
    border-bottom: 1px solid var(--color-border-strong);
    text-align: right;
    white-space: nowrap;
    background: var(--color-bg-soft);
}
.op-semanal thead th.op-corner {
    text-align: left;
    color: var(--color-text-subtle);
    min-width: 200px;
}
.op-semanal tbody td {
    padding: 16px 22px;
    border-bottom: 1px solid var(--color-border);
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
    font-size: 0.95rem;
}
.op-semanal tbody td.op-metric {
    text-align: left;
    font-weight: 500;
    color: var(--color-text-subtle);
    background: var(--color-card);
    position: sticky;
    left: 0;
    z-index: 1;
    min-width: 200px;
    border-right: 1px solid var(--color-border-strong);
}
.op-semanal tbody tr:last-child td { border-bottom: none; }
.op-semanal tbody tr:hover td:not(.op-metric) {
    background: rgba(201, 168, 76, 0.06);
}
.op-semanal tbody tr.op-row-emphasis td:not(.op-metric) {
    color: var(--color-gold-bright);
    font-weight: 600;
}
</style>
"""


def _render_indicadores_semanais(df_semanal: pd.DataFrame) -> None:
    """Renderiza a seção 'Indicadores semanais' como matriz executiva:
    semanas no topo (`SEMANA_19`, `SEMANA_20`…), métricas na lateral.
    Formato fiel ao One Page do Looker. Não toca na lógica de agregação
    — só na camada de apresentação.
    """
    if (df_semanal is None or df_semanal.empty
            or "Semana" not in df_semanal.columns):
        st.info("Sem dados semanais no período.")
        return

    # Ordem cronológica pelo identificador YYYY-Www.
    df = df_semanal.sort_values("Semana").reset_index(drop=True)

    # Se o período cruzar ano, mostra o ano no label pra evitar colisão
    # ('SEMANA_52_2025' vs 'SEMANA_01_2026').
    anos = {str(s).split("-W")[0] for s in df["Semana"]}
    cruza_ano = len(anos) > 1
    semanas = [_label_semana(s, cruza_ano) for s in df["Semana"]]

    # Só inclui linhas cuja métrica veio do _tabela_semanal — schema drift
    # ou fontes parcialmente vazias caem fora sem quebrar.
    linhas = [(m, kind) for m, kind in _SEMANAL_LINHAS if m in df.columns]
    if not linhas:
        st.info("Sem métricas disponíveis para a matriz semanal.")
        return

    # Linhas que ganham destaque (gold-bright bold) — métricas-âncora do
    # CEO. Não afeta layout, só legibilidade.
    _ENFASE = {"Leads", "Vendas", "Receita", "Montante"}

    head_cells = "".join(f"<th>{html.escape(w)}</th>" for w in semanas)
    body_rows: list[str] = []
    for metric, kind in linhas:
        cells = "".join(
            f"<td>{html.escape(_fmt_semanal(df.iloc[i][metric], kind))}</td>"
            for i in range(len(df))
        )
        cls = ' class="op-row-emphasis"' if metric in _ENFASE else ""
        body_rows.append(
            f'<tr{cls}>'
            f'<td class="op-metric">{html.escape(metric)}</td>'
            f'{cells}'
            f'</tr>'
        )

    table_html = (
        '<div class="op-semanal-wrap">'
        '<table class="op-semanal">'
        '<thead><tr>'
        '<th class="op-corner">Semana / Métrica</th>'
        f'{head_cells}'
        '</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        '</table></div>'
    )

    # CSS é idempotente (`<style>` repetido apenas substitui as regras),
    # mas mesmo assim injeta uma única vez por render — antes da tabela.
    st.markdown(_SEMANAL_CSS + table_html, unsafe_allow_html=True)


# =============================================================================
# Header — período apenas (decisão MVP: não usar canal nem
# closer/times no header pra manter a visão executiva limpa).
# =============================================================================
ctx = start_page(
    title="One Page",
    subtitle="Visão executiva consolidada — Marketing × Pré-vendas × Vendas",
)

# =============================================================================
# Carga
# =============================================================================
dias_periodo = (ctx.data_fim - ctx.data_ini).days + 1
prev_fim = ctx.data_ini - timedelta(days=1)
prev_ini = prev_fim - timedelta(days=dias_periodo - 1)

# Vendas (executivas + investimento) — fontes oficiais
try:
    df_exec      = get_executivas(ctx.data_ini, ctx.data_fim)
    df_inv       = get_investimento_diario(ctx.data_ini, ctx.data_fim)
    df_exec_prev = get_executivas(prev_ini, prev_fim)
    df_inv_prev  = get_investimento_diario(prev_ini, prev_fim)
except Exception as e:
    st.error(f"Falha ao consultar Vendas (executivas/investimento): {e}")
    st.stop()

# Marketing — regra LEGADA do One Page (typeform_aplicacoes + anuncios).
# Substitui `mkt_visao_geral_periodo`/`_diario` nos cards e gráficos —
# Aplicações deixam de ser `leads_qualificados` e passam a vir do
# typeform específico do Looker.
try:
    df_one      = get_one_page_legacy_diario(ctx.data_ini, ctx.data_fim)
    df_one_prev = get_one_page_legacy_diario(prev_ini, prev_fim)
except Exception as e:
    st.error(f"Falha ao consultar One Page legado: {e}")
    df_one      = pd.DataFrame()
    df_one_prev = pd.DataFrame()

# Tabela "Por Fonte de Lead" — segue na visão por canal do Marketing
# (atribuição financeira oficial), não substituível pela query legada.
df_kpc = safe_run(
    lambda: get_mkt_visao_geral_kpis_canal(ctx.data_ini, ctx.data_fim),
    view_label="mkt_visao_geral_kpis_canal",
)

# Pré-vendas
# - `df_prev_dia`: alimenta o card consolidado de Agendamentos e a
#   % Comparecimento via `prevendas_overview_kpis` (regra oficial).
# - `df_prev_fonte`: alimenta os cards INBOUND/SS (regra origem_final do
#   Looker — quebra por `zoho_deals.fonte_de_lead`, não por tipo de SDR).
# - `df_prev_sc`:  tabela SDR × Closer (visualização separada).
try:
    df_prev_dia   = get_prevendas_overview_diario(ctx.data_ini, ctx.data_fim)
    df_prev_fonte = get_one_page_prevendas_por_fonte(ctx.data_ini, ctx.data_fim)
    df_prev_sc    = get_prevendas_sdr_closer(ctx.data_ini, ctx.data_fim)
except Exception as e:
    st.warning(f"Falha ao consultar Pré-vendas: {e}")
    df_prev_dia   = pd.DataFrame()
    df_prev_fonte = pd.DataFrame()
    df_prev_sc    = pd.DataFrame()

# Média móvel — sempre últimos 21 dias (regra Looker)
try:
    media_movel_val = get_media_movel_vendas()
except Exception:
    media_movel_val = None

# =============================================================================
# KPIs base
# =============================================================================
k_apl      = _aplicacoes_kpis(df_one)
k_apl_prev = _aplicacoes_kpis(df_one_prev)

# Reaproveita o KPI oficial da Pré-vendas Visão Geral
# (`src/prevendas_transforms.py`): garante que "Agendamentos" exiba
# `agendamentos_exibidos = bruto - vencidas` e que `taxa_comparecimento`
# use `comparecimentos / agendamentos_exibidos` — mesma regra validada
# na página Pré-vendas. Evita re-implementar a fórmula localmente.
k_prev = prevendas_overview_kpis(df_prev_dia)

por_fonte = _prev_por_fonte(df_prev_fonte)

k_vendas      = visao_geral_kpis(df_exec, df_inv)
k_vendas_prev = visao_geral_kpis(df_exec_prev, df_inv_prev)

# =============================================================================
# Painel executivo — 3 colunas (Marketing | Pré-vendas | Vendas).
# Aproxima a leitura do One Page do Looker: cards mais próximos, blocos
# alinhados em paralelo, menos altura desperdiçada. Os 3 section_titles
# são curtos para não poluir o topo; a explicação completa das fontes
# vive nas SQLs (`one_page_legacy_diario.sql`, `one_page_prevendas_por_
# fonte.sql`) e nos hints dos próprios cards.
# =============================================================================
inb = por_fonte[_FONTE_INBOUND]
ss  = por_fonte[_FONTE_SS]

# Agendamentos consolidado (regra Pré-vendas Visão Geral)
ag_bruto = int(k_prev.get("agendamentos", 0))
ag_venc  = int(k_prev.get("vencidas", 0))
ag_exib  = int(k_prev.get("agendamentos_exibidos", max(ag_bruto - ag_venc, 0)))

col_mkt, col_prev, col_vendas = st.columns([1.0, 1.05, 1.0], gap="medium")

# -----------------------------------------------------------------------------
# Coluna esquerda — Marketing / Aplicações
# -----------------------------------------------------------------------------
with col_mkt:
    section_title("Marketing", "leads × aplicações · regra Looker")

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Leads totais",
            int_br(k_apl["leads_totais"]),
            delta_pct=delta_pct(k_apl["leads_totais"],
                                k_apl_prev["leads_totais"]),
            hint="ext_reconecta.leads",
        )
    with r[1]:
        metric_card_v2(
            "Aplicações",
            int_br(k_apl["aplicacoes"]),
            delta_pct=delta_pct(k_apl["aplicacoes"], k_apl_prev["aplicacoes"]),
            hint="typeform_aplicacoes",
            accent=True,
        )

    r = st.columns(3, gap="small")
    with r[0]:
        metric_card_v2(
            "% Apl / Leads",
            pct(k_apl["pct_aplicacoes"]),
            delta_pct=delta_pct(k_apl["pct_aplicacoes"],
                                k_apl_prev["pct_aplicacoes"]),
            hint="aplicações ÷ leads",
        )
    with r[1]:
        metric_card_v2(
            "Apl. -12",
            int_br(k_apl["aplicacoes_menos_12"]),
            delta_pct=delta_pct(k_apl["aplicacoes_menos_12"],
                                k_apl_prev["aplicacoes_menos_12"]),
            hint="Atua -12",
        )
    with r[2]:
        metric_card_v2(
            "Apl. +12",
            int_br(k_apl["aplicacoes_mais_12"]),
            delta_pct=delta_pct(k_apl["aplicacoes_mais_12"],
                                k_apl_prev["aplicacoes_mais_12"]),
            hint="Atua +12",
            accent=True,
        )

    metric_card_v2(
        "% Agendamento",
        pct(k_apl["pct_agendamento"]),
        delta_pct=delta_pct(k_apl["pct_agendamento"],
                            k_apl_prev["pct_agendamento"]),
        hint="agendamentos ÷ aplicações",
    )

    r = st.columns(3, gap="small")
    with r[0]:
        metric_card_v2(
            "CPL",
            brl(k_apl["cpl"], casas=2),
            delta_pct=delta_pct(k_apl["cpl"], k_apl_prev["cpl"]),
            hint="invest ÷ leads",
        )
    with r[1]:
        metric_card_v2(
            "Custo / Apl.",
            brl(k_apl["custo_aplicacao"], casas=2),
            delta_pct=delta_pct(k_apl["custo_aplicacao"],
                                k_apl_prev["custo_aplicacao"]),
            hint="invest ÷ aplicações",
        )
    with r[2]:
        metric_card_v2(
            "Custo / Apl. +12",
            brl(k_apl["custo_apl_mais_12"], casas=2),
            delta_pct=delta_pct(k_apl["custo_apl_mais_12"],
                                k_apl_prev["custo_apl_mais_12"]),
            hint="invest ÷ apl. +12",
        )

# -----------------------------------------------------------------------------
# Coluna central — Pré-vendas (INBOUND / SS por origem_final)
# -----------------------------------------------------------------------------
with col_prev:
    section_title("Pré-vendas", "agendamentos líquidos por fonte")

    r = st.columns(3, gap="small")
    with r[0]:
        metric_card_v2(
            "Agendamentos",
            int_br(ag_exib),
            hint=(f"bruto: {int_br(ag_bruto)} · "
                  f"venc: {int_br(ag_venc)} · "
                  f"exib: {int_br(ag_exib)}"),
            accent=True,
        )
    with r[1]:
        metric_card_v2(
            "Cons. INBOUND",
            int_br(inb["agendamentos"]),
            hint="fonte = Inbound",
        )
    with r[2]:
        metric_card_v2(
            "Cons. SS",
            int_br(ss["agendamentos"]),
            hint="fonte = Fábrica",
        )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Comp. INBOUND",
            int_br(inb["comparecimentos"]),
            hint="Concluída/Concluído · Inbound",
        )
    with r[1]:
        metric_card_v2(
            "Comp. SS",
            int_br(ss["comparecimentos"]),
            hint="Concluída/Concluído · Fábrica",
        )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Agend. -12 IN",
            int_br(inb["agendamentos_menos_12"]),
            hint="Atua -12 · Inbound",
        )
    with r[1]:
        metric_card_v2(
            "Agend. +12 IN",
            int_br(inb["agendamentos_mais_12"]),
            hint="Atua +12 · Inbound",
            accent=True,
        )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Agend. -12 SS",
            int_br(ss["agendamentos_menos_12"]),
            hint="Atua -12 · Fábrica",
        )
    with r[1]:
        metric_card_v2(
            "Agend. +12 SS",
            int_br(ss["agendamentos_mais_12"]),
            hint="Atua +12 · Fábrica",
            accent=True,
        )

    metric_card_v2(
        "% Comparecimento",
        pct(k_prev.get("taxa_comparecimento", 0.0)),
        hint="comparec ÷ agendamentos exibidos",
    )

# -----------------------------------------------------------------------------
# Coluna direita — Vendas / Financeiro
# (hero_revenue_card substituído por card compacto com meta no hint —
# decisão do CEO pra ganhar leitura executiva.)
# -----------------------------------------------------------------------------
with col_vendas:
    section_title("Vendas / Financeiro",
                  "R$ 625k/sem · meta proporcional ao período")

    # Receita — card hero compactado: meta + atingimento no hint
    receita_hint = (
        f"meta: {brl_short(k_vendas['meta'])} · "
        f"atingimento: {pct(k_vendas['pct_atingimento'])}"
    )
    metric_card_v2(
        "Receita",
        brl(k_vendas["receita"]),
        delta_pct=delta_pct(k_vendas["receita"], k_vendas_prev["receita"]),
        hint=receita_hint,
        accent=True,
    )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Vendas novas",
            int_br(k_vendas["novos"]),
            delta_pct=delta_pct(k_vendas["novos"], k_vendas_prev["novos"]),
            hint="Novo cliente",
            accent=True,
        )
    with r[1]:
        metric_card_v2(
            "Ascensões",
            int_br(k_vendas["ascensoes"]),
            delta_pct=delta_pct(k_vendas["ascensoes"],
                                k_vendas_prev["ascensoes"]),
            hint="tipo_venda = Ascensão",
        )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Renovações",
            int_br(k_vendas["renovacoes"]),
            delta_pct=delta_pct(k_vendas["renovacoes"],
                                k_vendas_prev["renovacoes"]),
            hint="tipo_venda = Renovação",
        )
    with r[1]:
        metric_card_v2(
            "Indicações",
            int_br(k_vendas["indicacoes"]),
            delta_pct=delta_pct(k_vendas["indicacoes"],
                                k_vendas_prev["indicacoes"]),
            hint="origem = Indicação",
        )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Montante",
            brl(k_vendas["montante"]),
            delta_pct=delta_pct(k_vendas["montante"],
                                k_vendas_prev["montante"]),
            hint=f"receb: {pct(k_vendas['pct_recebimento'])}",
        )
    with r[1]:
        metric_card_v2(
            "Investido",
            brl(k_vendas["investimento"]),
            delta_pct=delta_pct(k_vendas["investimento"],
                                k_vendas_prev["investimento"]),
            hint=f"{int_br(k_vendas['dias'])} dias",
        )

    r = st.columns(2, gap="small")
    with r[0]:
        metric_card_v2(
            "Ticket médio",
            brl(k_vendas["ticket_medio"]) if k_vendas["ticket_medio"] else "—",
            delta_pct=delta_pct(k_vendas["ticket_medio"],
                                k_vendas_prev["ticket_medio"]),
            hint="montante ÷ vendas",
        )
    with r[1]:
        metric_card_v2(
            "CPA",
            brl(k_vendas["cpa"]) if k_vendas["cpa"] else "—",
            delta_pct=delta_pct(k_vendas["cpa"], k_vendas_prev["cpa"]),
            hint="invest ÷ vendas",
        )

    # Média móvel — linha inline, sem ocupar card próprio
    if media_movel_val is not None:
        ritmo_fmt = f"{media_movel_val:.1f}".replace(".", ",")
        st.markdown(
            f'<div class="kpi-foot">Ritmo 21d: '
            f'<b>{ritmo_fmt}</b> vendas/dia</div>',
            unsafe_allow_html=True,
        )

# =============================================================================
# Gráficos
# =============================================================================
section_title("Tendências diárias", "evolução de leads, investimento e funil")

g_left, g_right = st.columns(2, gap="large")

# ---- 1. Evolução leads × aplicações ----------------------------------------
with g_left:
    st.markdown("**Leads × Aplicações** (regra Looker)")
    df_evo = _df_evolucao_aplicacoes(df_one)
    if df_evo.empty:
        st.info("Sem série diária de Marketing no período.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_evo["data_ref"], y=df_evo["leads_totais"], name="Leads",
            line=dict(color=PALETTE["gold"], width=2.5),
            mode="lines+markers", marker=dict(size=5),
        ))
        fig.add_trace(go.Scatter(
            x=df_evo["data_ref"], y=df_evo["aplicacoes"], name="Aplicações",
            line=dict(color=PALETTE["wine_light"], width=2.5),
            mode="lines+markers", marker=dict(size=5),
        ))
        fig.add_trace(go.Scatter(
            x=df_evo["data_ref"], y=df_evo["aplicacoes_mais_12"],
            name="Apl. +12",
            line=dict(color="#1D4ED8", width=2, dash="dash"),
            mode="lines+markers", marker=dict(size=4),
        ))
        fig.add_trace(go.Scatter(
            x=df_evo["data_ref"], y=df_evo["aplicacoes_menos_12"],
            name="Apl. -12",
            line=dict(color="#7C3AED", width=2, dash="dot"),
            mode="lines+markers", marker=dict(size=4),
        ))
        fig.update_layout(**_base_layout(height=320, unified=True))
        _style_axes(fig)
        st.plotly_chart(fig, use_container_width=True)

# ---- 2. Investimento por dia (mesma base do CPL: anuncios sem REL_02*) ----
with g_right:
    st.markdown("**Investimento por dia** (regra Looker · sem REL_02*)")
    if df_one is None or df_one.empty or "investimento" not in df_one.columns:
        st.info("Sem investimento registrado no período.")
    else:
        df_inv_one = df_one[["data_ref", "investimento"]].sort_values("data_ref")
        fig = area(df_inv_one, x="data_ref", y="investimento", money_axis="y")
        st.plotly_chart(fig, use_container_width=True)

g_left2, g_right2 = st.columns(2, gap="large")

# ---- 3. Evolução de agendamentos -------------------------------------------
with g_left2:
    st.markdown("**Agendamentos × +12 / -12**")
    if df_prev_dia is None or df_prev_dia.empty:
        st.info("Sem série diária de Pré-vendas no período.")
    else:
        df_pd = df_prev_dia.sort_values("data_ref").copy()
        # Agendamentos -12: na série diária só temos `agendamentos_mais_12`.
        # Deriva o complemento como (total - +12) — aproximação aceitável
        # para visualização (regra +12/-12 não é mutuamente exclusiva no
        # detalhe, mas no agregado a sobreposição é marginal).
        df_pd["agendamentos_menos_12_aprox"] = (
            df_pd["agendamentos"] - df_pd["agendamentos_mais_12"]
        ).clip(lower=0)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_pd["data_ref"], y=df_pd["agendamentos"], name="Agendamentos",
            line=dict(color=PALETTE["gold"], width=2.5),
            mode="lines+markers", marker=dict(size=5),
        ))
        fig.add_trace(go.Scatter(
            x=df_pd["data_ref"], y=df_pd["agendamentos_mais_12"], name="Ag. +12",
            line=dict(color="#1D4ED8", width=2, dash="dash"),
            mode="lines+markers", marker=dict(size=4),
        ))
        fig.add_trace(go.Scatter(
            x=df_pd["data_ref"], y=df_pd["agendamentos_menos_12_aprox"],
            name="Ag. -12 (aprox.)",
            line=dict(color="#7C3AED", width=2, dash="dot"),
            mode="lines+markers", marker=dict(size=4),
        ))
        fig.update_layout(**_base_layout(height=320, unified=True))
        _style_axes(fig)
        st.plotly_chart(fig, use_container_width=True)

# ---- 4. Volumes (ag/comp/vendas) -------------------------------------------
with g_right2:
    st.markdown("**Agendamentos × Comparecimentos × Vendas**")
    if df_prev_dia is None or df_prev_dia.empty or df_exec is None or df_exec.empty:
        st.info("Sem dados de Pré-vendas e/ou Vendas no período.")
    else:
        # Junta vendas (df_exec.vendas) à série diária de Pré-vendas.
        # As duas séries usam `data_ref` no mesmo grão (1 row/dia).
        vendas_dia = (df_exec.groupby("data_ref", as_index=False)["vendas"]
                      .sum())
        merged = (df_prev_dia[["data_ref", "agendamentos", "comparecimentos"]]
                  .merge(vendas_dia, on="data_ref", how="outer")
                  .fillna(0)
                  .sort_values("data_ref"))
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=merged["data_ref"], y=merged["agendamentos"], name="Agendamentos",
            line=dict(color=PALETTE["gold"], width=2.5),
            mode="lines+markers", marker=dict(size=5),
        ))
        fig.add_trace(go.Scatter(
            x=merged["data_ref"], y=merged["comparecimentos"], name="Comparec.",
            line=dict(color=PALETTE["wine_light"], width=2.5),
            mode="lines+markers", marker=dict(size=5),
        ))
        fig.add_trace(go.Scatter(
            x=merged["data_ref"], y=merged["vendas"], name="Vendas",
            line=dict(color=PALETTE["green"], width=2.5, dash="dot"),
            mode="lines+markers", marker=dict(size=5),
        ))
        fig.update_layout(**_base_layout(height=320, unified=True))
        _style_axes(fig)
        st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# Tabelas
# =============================================================================

# ---- Tabela por Fonte ------------------------------------------------------
section_title(
    "Por Fonte de Lead",
    "atribuição financeira: zoho_id > session_id > email (regra oficial)",
)
st.caption(
    "ℹ️ Colunas de Agendamentos / Comparecimentos / % Conversão / % Venda / "
    "% Comparecimento por canal estão no backlog — dependem de atribuir "
    "activities/deals por canal de lead (não existe view/chave de match hoje)."
)
tab_fonte = _tabela_por_fonte(df_kpc)
if tab_fonte.empty:
    st.info("Sem atribuição por canal no período.")
else:
    cfg_fonte = {}
    for col_money in ("Montante", "Receita", "Investimento", "CPL",
                      "Custo / Aplicação", "Ticket médio"):
        if col_money in tab_fonte.columns:
            cfg_fonte[col_money] = st.column_config.NumberColumn(
                col_money, format="R$ %.2f"
            )
    for col_pct in ("% +12", "% -12", "% Recebimento"):
        if col_pct in tab_fonte.columns:
            cfg_fonte[col_pct] = st.column_config.NumberColumn(
                col_pct, format="%.2f%%"
            )
    if "ROAS" in tab_fonte.columns:
        cfg_fonte["ROAS"] = st.column_config.NumberColumn("ROAS", format="%.2fx")
    st.dataframe(
        tab_fonte,
        use_container_width=True,
        hide_index=True,
        column_config=cfg_fonte,
    )

# ---- Tabela por Executiva --------------------------------------------------
section_title(
    "Por Executiva",
    "ranking consolidado · view bi.vw_dashboard_comercial_executivas_rw",
)
rank_exec = executivas_ranking(df_exec)
if rank_exec is None or rank_exec.empty:
    st.info("Sem ranking de executivas no período.")
else:
    # Subconjunto de colunas pedido no briefing
    cols_exec = [c for c in (
        "executiva", "agendamentos", "comparecimentos", "vendas",
        "montante", "receita",
        "pct_recebimento", "pct_conversao", "pct_vendas", "pct_comparecimento",
    ) if c in rank_exec.columns]
    tab_exec = rank_exec[cols_exec].copy()
    tab_exec = tab_exec.rename(columns={
        "executiva":          "Executiva",
        "agendamentos":       "Agendamentos",
        "comparecimentos":    "Comparec.",
        "vendas":             "Vendas",
        "montante":           "Montante",
        "receita":            "Receita",
        "pct_recebimento":    "% Recebimento",
        "pct_conversao":      "% Conversão",
        "pct_vendas":         "% Vendas",
        "pct_comparecimento": "% Comparec.",
    })
    cfg_exec = {}
    for c in ("Montante", "Receita"):
        if c in tab_exec.columns:
            cfg_exec[c] = st.column_config.NumberColumn(c, format="R$ %.0f")
    for c in ("% Recebimento", "% Conversão", "% Vendas", "% Comparec."):
        if c in tab_exec.columns:
            cfg_exec[c] = st.column_config.NumberColumn(c, format="%.2f%%")
    st.dataframe(
        tab_exec,
        use_container_width=True,
        hide_index=True,
        column_config=cfg_exec,
    )

# ---- Tabela por SDR × Closer -----------------------------------------------
# TODO/backlog: inconsistência de "Comparecimentos" entre as fontes.
# `prevendas_sdr_closer.sql:81` filtra apenas `status_reuniao = 'Concluída'`
# (feminino), enquanto `prevendas_overview_diario.sql:160` e
# `prevendas_por_sdr.sql:195` usam `status_reuniao IN ('Concluída',
# 'Concluído')`. A coluna "Comparec." desta tabela pode subcontar quando
# o status estiver gravado no masculino. Não corrigir agora — a SQL é
# consumida também por `views/prevendas_sdr_closer.py`; precisa validar
# impacto cruzado antes de unificar.
section_title(
    "Por SDR × Closer",
    "pares com pelo menos um agendamento ou venda no período",
)
tab_sc = _tabela_sdr_closer(df_prev_sc)
if tab_sc.empty:
    st.info("Sem pares SDR × Closer com atividade no período.")
else:
    tab_sc_disp = tab_sc.rename(columns={
        "sdr":                "SDR",
        "closer":             "Closer",
        "agendamentos":       "Agendamentos",
        "comparecimentos":    "Comparec.",
        "vendas":             "Vendas",
        "montante":           "Montante",
        "receita":            "Receita",
        "pct_recebimento":    "% Recebimento",
        "pct_conversao":      "% Conversão",
        "pct_vendas":         "% Vendas",
        "pct_comparecimento": "% Comparec.",
    })
    cfg_sc = {}
    for c in ("Montante", "Receita"):
        if c in tab_sc_disp.columns:
            cfg_sc[c] = st.column_config.NumberColumn(c, format="R$ %.0f")
    for c in ("% Recebimento", "% Conversão", "% Vendas", "% Comparec."):
        if c in tab_sc_disp.columns:
            cfg_sc[c] = st.column_config.NumberColumn(c, format="%.2f%%")
    st.dataframe(
        tab_sc_disp,
        use_container_width=True,
        hide_index=True,
        column_config=cfg_sc,
    )

# ---- Tabela semanal (matriz executiva no formato Looker) -------------------
section_title(
    "Indicadores semanais",
    "matriz executiva · semanas no topo · métricas na lateral",
)
tab_sem = _tabela_semanal(df_one, df_prev_dia, df_exec)
_render_indicadores_semanais(tab_sem)
