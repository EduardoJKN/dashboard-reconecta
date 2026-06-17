"""Benchmark histórico do funil — mesmas fontes/regras que `load_one_page_funnel`."""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import streamlit as st

from src.one_page_funnel import FunnelSnapshot, load_one_page_funnel

# Período histórico (independente do filtro principal da página).
HISTORICO_CUSTOM_KEY = "custom"

HISTORICO_PERIODOS: dict[str, dict[str, Any]] = {
    "30": {"label": "Último mês", "months": 1},
    "90": {"label": "Últimos 3 meses", "months": 3},
    "180": {"label": "Últimos 6 meses", "months": 6},
    "365": {"label": "Últimos 12 meses", "months": 12},
    HISTORICO_CUSTOM_KEY: {"label": "Personalizado"},
}

HISTORICO_GRANULARIDADES: dict[str, str] = {
    "mes": "Mês",
    "semana": "Semana",
    "dia": "Dia",
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


def is_full_closed_month(period_ini: date, period_fim: date) -> bool:
    """Período atual cobre um mês civil fechado (dia 1 até o último dia do mês)."""
    if period_ini > period_fim:
        return False
    return (
        period_ini.day == 1
        and period_ini.year == period_fim.year
        and period_ini.month == period_fim.month
        and period_fim.day == _last_day_of_month(period_fim).day
    )


def effective_same_interval(
    period_ini: date,
    period_fim: date,
    same_interval: bool,
) -> bool:
    """Checkbox sem efeito quando o período atual já é um mês fechado."""
    if is_full_closed_month(period_ini, period_fim):
        return False
    return bool(same_interval)


def _add_months(d: date, months: int) -> date:
    """Desloca `d` em meses civis, ajustando o dia em meses mais curtos."""
    y, m = d.year, d.month + months
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    last_day = _last_day_of_month(date(y, m, 1)).day
    return date(y, m, min(d.day, last_day))


def _fmt_br_range(ini: date, fim: date) -> str:
    return f"{ini.strftime('%d/%m/%Y')}–{fim.strftime('%d/%m/%Y')}"


def _period_short_label(d: date) -> str:
    """Identificador curto do período para a tabela (MM/AA)."""
    return f"{d.month:02d}/{d.year % 100:02d}"


def period_windows_from_ranges(
    ranges: list[tuple[date, date, str]],
) -> list[dict[str, str]]:
    """Janelas para legenda: identificador curto + intervalo completo."""
    ordered = sorted(ranges, key=lambda item: item[0])
    return [
        {
            "short": _period_short_label(ini),
            "full": _fmt_br_range(ini, fim),
        }
        for ini, fim, _ in ordered
    ]


def build_fixed_preset_month_ranges(
    anchor_ini: date,
    n_months: int,
) -> list[tuple[date, date, str]]:
    """Meses civis completos fechados imediatamente anteriores ao mês de `anchor_ini`."""
    return build_full_previous_month_ranges(anchor_ini, n_months)


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


def build_equivalent_month_ranges(
    current_ini: date,
    current_fim: date,
    n_periods: int,
) -> list[tuple[date, date, str]]:
    """Mesmo recorte de dias do período atual, deslocado para N meses anteriores."""
    if n_periods < 1 or current_ini > current_fim:
        return []
    ranges: list[tuple[date, date, str]] = []
    for months_back in range(1, n_periods + 1):
        ini = _add_months(current_ini, -months_back)
        fim = _add_months(current_fim, -months_back)
        if ini > fim:
            continue
        label = _period_short_label(ini)
        ranges.append((ini, fim, label))
    return ranges


def build_full_previous_month_ranges(
    anchor_ini: date,
    n_periods: int,
) -> list[tuple[date, date, str]]:
    """N meses civis fechados imediatamente anteriores ao mês de `anchor_ini`."""
    if n_periods < 1:
        return []
    ranges: list[tuple[date, date, str]] = []
    month_start = anchor_ini.replace(day=1)
    for _ in range(n_periods):
        prev_end = month_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        label = f"{prev_start.month:02d}/{prev_start.year % 100:02d}"
        ranges.insert(0, (prev_start, prev_end, label))
        month_start = prev_start
    return ranges


def _custom_interval_summary(
    current_ini: date,
    current_fim: date,
    n_periods: int,
    *,
    same_interval: bool,
) -> str:
    if same_interval:
        if current_ini.day == 1 and current_fim.day < _last_day_of_month(current_fim).day:
            return f"primeiros {current_fim.day} dias dos últimos {n_periods} meses"
        if current_ini.day == current_fim.day:
            return f"dia {current_ini.day} dos últimos {n_periods} meses"
        return (
            f"intervalo {current_ini.day}–{current_fim.day} "
            f"dos últimos {n_periods} meses"
        )
    return f"últimos {n_periods} meses fechados"


@dataclass
class HistoricalBaseSpec:
    ranges: list[tuple[date, date, str]]
    hist_ini: date
    hist_fim: date
    base_key: str
    base_label: str
    summary: str
    window_detail: str
    requested_periods: int
    custom_granularity: str | None = None
    same_interval: bool | None = None
    error: str | None = None


def resolve_historical_base(
    page_data_ini: date,
    page_data_fim: date,
    *,
    base_key: str,
    custom_granularity: str = "mes",
    custom_n_periods: int = 3,
    same_interval: bool = True,
) -> HistoricalBaseSpec:
    """Monta recortes históricos conforme preset ou modo personalizado."""
    use_same_interval = effective_same_interval(
        page_data_ini, page_data_fim, same_interval,
    )

    if base_key == HISTORICO_CUSTOM_KEY:
        if custom_granularity != "mes":
            return HistoricalBaseSpec(
                ranges=[],
                hist_ini=page_data_ini,
                hist_fim=page_data_fim,
                base_key=base_key,
                base_label=HISTORICO_PERIODOS[base_key]["label"],
                summary="",
                window_detail="",
                requested_periods=custom_n_periods,
                custom_granularity=custom_granularity,
                same_interval=use_same_interval,
                error=(
                    "Modo personalizado por Semana ou Dia ainda não disponível. "
                    "Use **Mês** por enquanto."
                ),
            )
        if use_same_interval:
            ranges = build_equivalent_month_ranges(
                page_data_ini, page_data_fim, custom_n_periods,
            )
        else:
            ranges = build_full_previous_month_ranges(
                page_data_ini, custom_n_periods,
            )
        if not ranges:
            return HistoricalBaseSpec(
                ranges=[],
                hist_ini=page_data_ini,
                hist_fim=page_data_fim,
                base_key=base_key,
                base_label=HISTORICO_PERIODOS[base_key]["label"],
                summary="",
                window_detail="",
                requested_periods=custom_n_periods,
                custom_granularity=custom_granularity,
                same_interval=use_same_interval,
                error="Não foi possível montar períodos históricos equivalentes.",
            )
        hist_ini = min(r[0] for r in ranges)
        hist_fim = max(r[1] for r in ranges)
        short = _custom_interval_summary(
            page_data_ini,
            page_data_fim,
            custom_n_periods,
            same_interval=use_same_interval,
        )
        window_detail = ", ".join(
            _fmt_br_range(ini, fim)
            for ini, fim, _ in sorted(ranges, key=lambda item: item[0])
        )
        return HistoricalBaseSpec(
            ranges=ranges,
            hist_ini=hist_ini,
            hist_fim=hist_fim,
            base_key=base_key,
            base_label=HISTORICO_PERIODOS[base_key]["label"],
            summary=f"{HISTORICO_PERIODOS[base_key]['label']} · {short}",
            window_detail=window_detail,
            requested_periods=custom_n_periods,
            custom_granularity=custom_granularity,
            same_interval=use_same_interval,
        )

    months = int(HISTORICO_PERIODOS[base_key]["months"])
    if use_same_interval:
        ranges = build_equivalent_month_ranges(
            page_data_ini, page_data_fim, months,
        )
    else:
        ranges = build_full_previous_month_ranges(page_data_ini, months)
    if not ranges:
        return HistoricalBaseSpec(
            ranges=[],
            hist_ini=page_data_ini,
            hist_fim=page_data_fim,
            base_key=base_key,
            base_label=HISTORICO_PERIODOS[base_key]["label"],
            summary="",
            window_detail="",
            requested_periods=0,
            same_interval=use_same_interval,
            error="Período principal sem histórico anterior suficiente.",
        )
    hist_ini = ranges[0][0]
    hist_fim = ranges[-1][1]
    short = _custom_interval_summary(
        page_data_ini,
        page_data_fim,
        months,
        same_interval=use_same_interval,
    )
    window_detail = ", ".join(
        _fmt_br_range(ini, fim)
        for ini, fim, _ in sorted(ranges, key=lambda item: item[0])
    )
    return HistoricalBaseSpec(
        ranges=ranges,
        hist_ini=hist_ini,
        hist_fim=hist_fim,
        base_key=base_key,
        base_label=HISTORICO_PERIODOS[base_key]["label"],
        summary=f"{HISTORICO_PERIODOS[base_key]['label']} · {short}",
        window_detail=window_detail,
        requested_periods=len(ranges),
        same_interval=use_same_interval,
    )


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
    ranges_json: str = "",
) -> dict[str, Any]:
    """Carrega snapshots por recorte e agrega estatísticas (média, melhor/pior, p25/p75)."""
    hist_ini = date.fromisoformat(hist_ini_iso)
    hist_fim = date.fromisoformat(hist_fim_iso)
    if ranges_json:
        raw_ranges = json.loads(ranges_json)
        ranges = [
            (date.fromisoformat(ini), date.fromisoformat(fim), label)
            for ini, fim, label in raw_ranges
        ]
    else:
        ranges = month_ranges_in_period(hist_ini, hist_fim)

    snapshots: list[FunnelSnapshot] = []
    labels: list[str] = []
    loaded_ranges: list[tuple[date, date, str]] = []

    for ini, fim, label in ranges:
        try:
            snapshots.append(
                load_one_page_funnel(
                    ini,
                    fim,
                    excluir_testes_aplicacoes=excluir_testes_aplicacoes,
                )
            )
            short_label = _period_short_label(ini)
            labels.append(short_label)
            loaded_ranges.append((ini, fim, short_label))
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

    requested = len(ranges)
    available = len(snapshots)
    error: str | None = None
    if not snapshots:
        error = "Sem dados históricos no intervalo."
    elif available < requested:
        error = None

    return {
        "hist_ini": hist_ini_iso,
        "hist_fim": hist_fim_iso,
        "days_key": days_key,
        "metrics": metrics,
        "monthly_count": available,
        "requested_period_count": requested,
        "period_windows": period_windows_from_ranges(
            loaded_ranges if loaded_ranges else ranges,
        ),
        "error": error,
    }


def ranges_to_cache_json(ranges: list[tuple[date, date, str]]) -> str:
    return json.dumps(
        [(ini.isoformat(), fim.isoformat(), label) for ini, fim, label in ranges]
    )


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
            return "Dentro do histórico", "within"
        if ratio <= 1.30:
            return "Acima do histórico", "above"
        return "Muito acima da média", "very-high"
    if ratio < 0.8:
        return "Melhor que histórico", "good"
    if ratio <= 1.10:
        return "Dentro do histórico", "within"
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
