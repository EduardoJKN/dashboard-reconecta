"""Benchmark histórico do funil — mesmas fontes/regras que `load_one_page_funnel`."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import streamlit as st

from src.one_page_funnel import FunnelSnapshot, load_one_page_funnel

# Período histórico (independente do filtro principal da página).
HISTORICO_PERIODOS: dict[str, dict[str, Any]] = {
    "30": {"label": "Último mês", "days": 30},
    "90": {"label": "Últimos 3 meses", "days": 90},
    "180": {"label": "Últimos 6 meses", "days": 180},
    "365": {"label": "Últimos 12 meses", "days": 365},
}

# Métricas do benchmark, tags históricas e tabela (mesma base / mesma média).
BENCHMARK_TAG_SPECS: tuple[tuple[str, str, bool, str], ...] = (
    ("investimento", "Investimento", True, "money"),
    ("custo_lead", "Custo por Lead", False, "money"),
    ("leads", "Leads", True, "count"),
    ("pct_la", "% Lead → Aplicação", True, "pct"),
    ("aplicacoes", "Aplicações", True, "count"),
    ("pct_a_ag", "% Aplicação → Agendamento", True, "pct"),
    ("agendamentos", "Agendamentos", True, "count"),
    ("pct_ag_c", "% Agendamento → Comparecimento", True, "pct"),
    ("comparecimento", "Comparecimentos", True, "count"),
    ("pct_c_v", "% Comparecimento → Venda", True, "pct"),
    ("vendas", "Vendas", True, "count"),
    ("ticket", "Ticket Médio", True, "money"),
    ("pct_recebimento", "% Receita sobre Montante", True, "pct100"),
)

# Cenários automáticos no Simulador (apenas taxas + CPL + ticket).
BENCHMARK_METRIC_SPECS: tuple[tuple[str, str, bool, str], ...] = tuple(
    row for row in BENCHMARK_TAG_SPECS
    if row[0] in {
        "custo_lead", "pct_la", "pct_a_ag", "pct_ag_c", "pct_c_v", "ticket",
    }
)


def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    return nxt - timedelta(days=1)


def resolve_historical_window(page_data_ini: date, days: int) -> tuple[date, date] | None:
    """Janela histórica imediatamente anterior ao período principal (sem sobreposição)."""
    hist_end = page_data_ini - timedelta(days=1)
    hist_start = hist_end - timedelta(days=days - 1)
    if hist_end < hist_start:
        return None
    return hist_start, hist_end


def month_ranges_in_period(start: date, end: date) -> list[tuple[date, date, str]]:
    """Recortes por mês civil dentro de [start, end]."""
    ranges: list[tuple[date, date, str]] = []
    cur = start.replace(day=1)
    while cur <= end:
        month_start = max(cur, start)
        month_end = min(_last_day_of_month(cur), end)
        if month_start <= month_end:
            label = f"{cur.month:02d}/{cur.year % 100:02d}"
            ranges.append((month_start, month_end, label))
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return ranges


def _metric_from_snapshot(snapshot: FunnelSnapshot, key: str) -> float:
    return float(getattr(snapshot, key))


def _aggregate_values(
    values: list[float],
    labels: list[str],
    *,
    higher_is_better: bool,
) -> dict[str, Any]:
    if not values:
        return {}
    mean = statistics.mean(values)
    median = statistics.median(values)
    if len(values) >= 4:
        qs = statistics.quantiles(values, n=4)
        p25, p75 = qs[0], qs[2]
    else:
        p25, p75 = min(values), max(values)

    if higher_is_better:
        best_i = max(range(len(values)), key=lambda i: values[i])
        worst_i = min(range(len(values)), key=lambda i: values[i])
    else:
        best_i = min(range(len(values)), key=lambda i: values[i])
        worst_i = max(range(len(values)), key=lambda i: values[i])

    return {
        "mean": mean,
        "median": median,
        "p25": p25,
        "p75": p75,
        "best": values[best_i],
        "worst": values[worst_i],
        "best_period": labels[best_i],
        "worst_period": labels[worst_i],
        "n_months": len(values),
    }


@dataclass
class FunilBenchmarkResult:
    hist_ini: date
    hist_fim: date
    days_key: str
    metrics: dict[str, dict[str, Any]]
    monthly_count: int
    error: str | None = None


@st.cache_data(ttl=600, show_spinner=False)
def compute_funil_benchmark(
    hist_ini_iso: str,
    hist_fim_iso: str,
    days_key: str,
    excluir_testes_aplicacoes: bool,
) -> dict[str, Any]:
    """Carrega snapshots mensais e agrega estatísticas (média, melhor/pior mês, p25/p75)."""
    hist_ini = date.fromisoformat(hist_ini_iso)
    hist_fim = date.fromisoformat(hist_fim_iso)
    ranges = month_ranges_in_period(hist_ini, hist_fim)
    snapshots: list[FunnelSnapshot] = []
    labels: list[str] = []

    for ini, fim, label in ranges:
        try:
            snapshots.append(
                load_one_page_funnel(
                    ini,
                    fim,
                    excluir_testes_aplicacoes=excluir_testes_aplicacoes,
                )
            )
            labels.append(label)
        except Exception:
            continue

    metrics: dict[str, dict[str, Any]] = {}
    for key, _label, higher_is_better, kind in BENCHMARK_TAG_SPECS:
        vals = [_metric_from_snapshot(s, key) for s in snapshots]
        agg = _aggregate_values(vals, labels, higher_is_better=higher_is_better)
        if agg:
            agg["higher_is_better"] = higher_is_better
            agg["kind"] = kind
            metrics[key] = agg

    return {
        "hist_ini": hist_ini_iso,
        "hist_fim": hist_fim_iso,
        "days_key": days_key,
        "metrics": metrics,
        "monthly_count": len(snapshots),
        "error": None if snapshots else "Sem dados históricos no intervalo.",
    }


def classify_realism(
    value: float,
    mean: float,
    *,
    higher_is_better: bool,
) -> tuple[str, str]:
    """Retorna (rótulo, classe CSS)."""
    if mean <= 0:
        return "—", "neutral"
    ratio = float(value) / float(mean)
    if higher_is_better:
        if ratio < 0.8:
            return "Muito abaixo do histórico", "bad"
        if ratio < 0.95:
            return "Abaixo do histórico", "warn"
        if ratio <= 1.10:
            return "Dentro do histórico", "ok"
        if ratio <= 1.30:
            return "Acima do histórico", "warn"
        return "Muito agressivo", "bad"
    if ratio < 0.8:
        return "Melhor que histórico", "good"
    if ratio <= 1.10:
        return "Dentro do histórico", "ok"
    if ratio <= 1.30:
        return "Acima do histórico", "warn"
    return "Muito alto", "bad"


def scenario_field_value(
    metric: dict[str, Any],
    mode: str,
) -> float:
    """Valor sugerido para o Simulador a partir do benchmark."""
    mean = float(metric["mean"])
    higher = bool(metric["higher_is_better"])
    if mode == "conservador":
        return mean * 0.9 if higher else mean * 1.1
    if mode == "provavel":
        return float(metric.get("median", mean))
    if mode == "otimista":
        if higher:
            return float(metric.get("p75", mean * 1.1))
        return float(metric.get("p25", mean * 0.9))
    return mean
