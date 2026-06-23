"""Funil consolidado da One Page — fontes e regras compartilhadas.

Agrega Marketing (legacy diário), Pré-vendas (overview) e Vendas
(executivas) no mesmo recorte de datas usado pela página One Page.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import time

import pandas as pd
import streamlit as st

from src.prevendas_transforms import prevendas_overview_kpis
from src.repositories import (
    get_executivas_for_funil,
    get_investimento_diario,
    get_one_page_legacy_diario_for_funil,
    get_prevendas_overview_diario,
    LEGACY_DIARIO_COLUMNS,
)
from src.transforms import visao_geral_kpis


def safe_div(num, den) -> float:
    try:
        d = float(den or 0)
        return float(num or 0) / d if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def sum_column(df: pd.DataFrame, col: str) -> float:
    if df is None or df.empty or col not in df.columns:
        return 0.0
    return float(df[col].fillna(0).sum())


def period_column(df: pd.DataFrame, period_col: str, daily_col: str) -> float:
    """Total do período: coluna *_periodo (dedupe no intervalo) ou soma diária."""
    if df is None or df.empty:
        return 0.0
    if period_col in df.columns:
        return float(df[period_col].fillna(0).max())
    return sum_column(df, daily_col)


def aplicacoes_kpis(df_one: pd.DataFrame) -> dict:
    """KPIs de Marketing — regra LEGADA do Looker (`one_page_legacy_diario`).

    Aplicações e ±12 usam e-mails únicos no período (`*_periodo`), não a
    soma de distintos por dia (evita contar o mesmo e-mail em dias diferentes).
    """
    leads = sum_column(df_one, "novos_leads")
    aplicacoes = period_column(
        df_one, "novas_aplicacoes_periodo", "novas_aplicacoes"
    )
    apl_mais12 = period_column(
        df_one, "aplicacoes_mais_12_periodo", "aplicacoes_mais_12"
    )
    apl_menos12 = period_column(
        df_one, "aplicacoes_menos_12_periodo", "aplicacoes_menos_12"
    )
    apl_naoatua = period_column(
        df_one, "aplicacoes_nao_atua_periodo", "aplicacoes_nao_atua"
    )
    investimento = sum_column(df_one, "investimento")
    agendamentos = sum_column(df_one, "agendamentos")
    apl_total_ag = period_column(
        df_one, "aplicacoes_com_agendamento_periodo", "aplicacoes_com_agendamento"
    )
    apl_m12_ag = period_column(
        df_one,
        "aplicacoes_mais_12_com_agendamento_periodo",
        "aplicacoes_mais_12_com_agendamento",
    )
    apl_n12_ag = period_column(
        df_one,
        "aplicacoes_menos_12_com_agendamento_periodo",
        "aplicacoes_menos_12_com_agendamento",
    )

    return {
        "leads_totais": leads,
        "aplicacoes": aplicacoes,
        "aplicacoes_mais_12": apl_mais12,
        "aplicacoes_menos_12": apl_menos12,
        "aplicacoes_nao_atua": apl_naoatua,
        "pct_aplicacoes": safe_div(aplicacoes, leads) * 100,
        "investimento": investimento,
        "cpl": safe_div(investimento, leads),
        "custo_aplicacao": safe_div(investimento, aplicacoes),
        "custo_apl_mais_12": safe_div(investimento, apl_mais12),
        "custo_apl_menos_12": safe_div(investimento, apl_menos12),
        "agendamentos_legacy": agendamentos,
        # Volume total / aplicações (pode passar de 100% — não usar como conversão).
        "pct_agendamento": safe_div(agendamentos, aplicacoes) * 100,
        "aplicacoes_com_agendamento": apl_total_ag,
        # Conversão real: aplicações do período que viraram agendamento (match e-mail).
        "pct_agendamento_apl": safe_div(apl_total_ag, aplicacoes) * 100,
        "pct_agendamento_apl_mais_12": safe_div(apl_m12_ag, apl_mais12) * 100,
        "pct_agendamento_apl_menos_12": safe_div(apl_n12_ag, apl_menos12) * 100,
    }


@dataclass
class FunnelSnapshot:
    """Volumes e taxas reais do período (totais, antes de escala Mês/Sem/Dia)."""
    investimento: float
    leads: float
    aplicacoes: float
    agendamentos: float
    comparecimento: float
    vendas: float
    montante: float
    receita: float
    pct_recebimento: float
    custo_lead: float
    pct_la: float
    pct_a_ag: float
    pct_ag_c: float
    pct_c_v: float
    ticket: float


def project_receita_from_montante(montante: float, pct_recebimento: float) -> float:
    """Receita projetada — % recebimento de `visao_geral_kpis` (0–100)."""
    if montante <= 0 or pct_recebimento <= 0:
        return 0.0
    return montante * (pct_recebimento / 100.0)


def filter_df_date_range(
    df: pd.DataFrame,
    data_ini: date,
    data_fim: date,
) -> pd.DataFrame:
    """Recorte inclusivo por `data_ref` (date ou datetime)."""
    if df is None or df.empty or "data_ref" not in df.columns:
        return df
    out = df.copy()
    out["data_ref"] = pd.to_datetime(out["data_ref"])
    ini = pd.Timestamp(data_ini)
    fim = pd.Timestamp(data_fim)
    mask = (out["data_ref"] >= ini) & (out["data_ref"] <= fim)
    return out.loc[mask].copy()


def legacy_df_for_benchmark_period(
    df_batch: pd.DataFrame,
    period_key: str,
) -> pd.DataFrame:
    """Recorte in-memory de um `period_key` do legacy batch (sem a coluna auxiliar)."""
    legacy_cols = list(LEGACY_DIARIO_COLUMNS)
    if df_batch is None or df_batch.empty:
        return pd.DataFrame(columns=legacy_cols)
    if "period_key" not in df_batch.columns:
        return df_batch
    pk = str(period_key)
    out = df_batch.loc[df_batch["period_key"].astype(str) == pk].copy()
    if "period_key" in out.columns:
        out = out.drop(columns=["period_key"])
    if out.empty:
        return pd.DataFrame(columns=legacy_cols)
    if "data_ref" in out.columns:
        out["data_ref"] = pd.to_datetime(out["data_ref"])
    return out.reset_index(drop=True)


def build_funnel_snapshot(
    df_one: pd.DataFrame,
    df_prev: pd.DataFrame,
    df_exec: pd.DataFrame,
    df_inv: pd.DataFrame,
) -> FunnelSnapshot:
    """Monta snapshot a partir de DataFrames já no recorte desejado."""
    k_apl = aplicacoes_kpis(df_one)
    k_prev = prevendas_overview_kpis(df_prev)
    k_vend = visao_geral_kpis(df_exec, df_inv)

    investimento = float(k_apl["investimento"])
    leads = float(k_apl["leads_totais"])
    aplicacoes = float(k_apl["aplicacoes"])
    aplicacoes_com_agendamento = float(k_apl["aplicacoes_com_agendamento"])
    agendamentos = float(k_prev["agendamentos_exibidos"])
    comparecimento = float(k_prev["comparecimentos"])
    vendas = float(k_vend["vendas"])
    montante = float(k_vend["montante"])
    receita = float(k_vend["receita"])
    pct_recebimento = float(k_vend["pct_recebimento"])

    return FunnelSnapshot(
        investimento=investimento,
        leads=leads,
        aplicacoes=aplicacoes,
        agendamentos=agendamentos,
        comparecimento=comparecimento,
        vendas=vendas,
        montante=montante,
        receita=receita,
        pct_recebimento=pct_recebimento,
        custo_lead=safe_div(investimento, leads),
        pct_la=safe_div(aplicacoes, leads),
        pct_a_ag=safe_div(aplicacoes_com_agendamento, aplicacoes),
        pct_ag_c=safe_div(comparecimento, agendamentos),
        pct_c_v=safe_div(vendas, comparecimento),
        ticket=safe_div(montante, vendas),
    )


def _fetch_legacy_for_funil(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool,
) -> pd.DataFrame:
    """Legacy diário com v2/fallback — registra perf quando debug ativo."""
    t0 = time.perf_counter()
    df, version, fallback_error = get_one_page_legacy_diario_for_funil(
        data_ini,
        data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    elapsed = time.perf_counter() - t0
    try:
        from src.funil_reconecta_perf import perf_debug_enabled, perf_record_legacy_run

        if perf_debug_enabled():
            perf_record_legacy_run(
                data_ini,
                data_fim,
                elapsed,
                version=version,
                rows=len(df),
                fallback_error=fallback_error,
            )
    except Exception:
        pass
    return df


def _fetch_executivas_for_funil(
    data_ini: date,
    data_fim: date,
) -> pd.DataFrame:
    """Executivas com v2/fallback — registra perf quando debug ativo."""
    t0 = time.perf_counter()
    df, version, fallback_error = get_executivas_for_funil(data_ini, data_fim)
    elapsed = time.perf_counter() - t0
    try:
        from src.funil_reconecta_perf import (
            perf_debug_enabled,
            perf_record_executivas_run,
        )

        if perf_debug_enabled():
            perf_record_executivas_run(
                data_ini,
                data_fim,
                elapsed,
                version=version,
                rows=len(df),
                cols=len(df.columns) if not df.empty else 0,
                fallback_error=fallback_error,
            )
    except Exception:
        pass
    return df


def _load_one_page_funnel_impl(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool = False,
) -> FunnelSnapshot:
    """Carrega o funil real do período com as mesmas regras da One Page."""
    from src.funil_parallel_load import (
        funil_parallel_loads_enabled,
        load_one_page_funnel_frames_parallel,
    )

    if funil_parallel_loads_enabled():
        try:
            frames, report, meta = load_one_page_funnel_frames_parallel(
                data_ini,
                data_fim,
                excluir_testes_aplicacoes=excluir_testes_aplicacoes,
            )
            _record_parallel_atual_perf(
                data_ini, data_fim, report, meta, excluir_testes_aplicacoes
            )
            return build_funnel_snapshot(*frames)
        except Exception as exc:
            _record_parallel_fallback("atual", str(exc))
    df_one = _fetch_legacy_for_funil(
        data_ini,
        data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    df_prev = get_prevendas_overview_diario(data_ini, data_fim)
    df_exec = _fetch_executivas_for_funil(data_ini, data_fim)
    df_inv = get_investimento_diario(data_ini, data_fim)
    return build_funnel_snapshot(df_one, df_prev, df_exec, df_inv)


def _record_parallel_atual_perf(
    data_ini: date,
    data_fim: date,
    report,
    meta: dict,
    excluir_testes_aplicacoes: bool,
) -> None:
    try:
        from src.funil_reconecta_perf import (
            perf_debug_enabled,
            perf_record_executivas_run,
            perf_record_legacy_run,
            perf_record_parallel_load,
            perf_record_query,
        )

        if not perf_debug_enabled():
            return
        perf_record_parallel_load(
            scope="atual",
            enabled=True,
            workers=report.workers,
            mode=report.mode,
            fallback=False,
            total_seconds=report.total_seconds,
            groups=[{"name": g.name, "seconds": g.seconds} for g in report.groups],
        )
        leg = meta.get("legacy") or {}
        for g in report.groups:
            if g.name == "legacy":
                perf_record_legacy_run(
                    data_ini,
                    data_fim,
                    g.seconds,
                    version=str(leg.get("version") or "v2"),
                    rows=int(leg.get("rows") or 0),
                    fallback_error=leg.get("fallback_error"),
                )
            elif g.name == "prevendas":
                perf_record_query(
                    "prevendas_overview_diario",
                    data_ini,
                    data_fim,
                    g.seconds,
                    int(meta.get("prev_rows") or 0),
                )
            elif g.name == "executivas":
                ex = meta.get("executivas") or {}
                perf_record_executivas_run(
                    data_ini,
                    data_fim,
                    g.seconds,
                    version=str(ex.get("version") or "v2"),
                    rows=int(ex.get("rows") or 0),
                    cols=int(ex.get("cols") or 0),
                    fallback_error=ex.get("fallback_error"),
                )
            elif g.name == "investimento":
                perf_record_query(
                    "investimento_diario",
                    data_ini,
                    data_fim,
                    g.seconds,
                    int(meta.get("inv_rows") or 0),
                )
    except Exception:
        pass


def _record_parallel_fallback(scope: str, error: str) -> None:
    try:
        from src.funil_reconecta_perf import perf_debug_enabled, perf_record_parallel_load

        if perf_debug_enabled():
            perf_record_parallel_load(
                scope=scope,
                enabled=True,
                workers=0,
                mode="sequential_fallback",
                fallback=True,
                fallback_error=error,
                total_seconds=0.0,
                groups=[],
            )
    except Exception:
        pass


def _load_benchmark_shared_frames_impl(
    wide_ini: date,
    wide_fim: date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from src.funil_parallel_load import (
        funil_parallel_loads_enabled,
        load_benchmark_shared_frames_parallel,
    )

    if funil_parallel_loads_enabled():
        try:
            frames, report, meta = load_benchmark_shared_frames_parallel(
                wide_ini, wide_fim
            )
            _record_parallel_benchmark_shared_perf(wide_ini, wide_fim, report, meta)
            return frames
        except Exception as exc:
            _record_parallel_fallback("benchmark_shared", str(exc))
    df_prev = get_prevendas_overview_diario(wide_ini, wide_fim)
    df_exec = _fetch_executivas_for_funil(wide_ini, wide_fim)
    df_inv = get_investimento_diario(wide_ini, wide_fim)
    return df_prev, df_exec, df_inv


def _record_parallel_benchmark_shared_perf(
    wide_ini: date,
    wide_fim: date,
    report,
    meta: dict,
) -> None:
    try:
        from src.funil_reconecta_perf import (
            perf_debug_enabled,
            perf_record_executivas_run,
            perf_record_parallel_load,
            perf_record_query,
        )

        if not perf_debug_enabled():
            return
        perf_record_parallel_load(
            scope="benchmark_shared",
            enabled=True,
            workers=report.workers,
            mode=report.mode,
            fallback=False,
            total_seconds=report.total_seconds,
            groups=[{"name": g.name, "seconds": g.seconds} for g in report.groups],
        )
        ex = meta.get("executivas") or {}
        for g in report.groups:
            if g.name == "prevendas":
                perf_record_query(
                    "prevendas_overview_diario",
                    wide_ini,
                    wide_fim,
                    g.seconds,
                    0,
                )
            elif g.name == "executivas":
                perf_record_executivas_run(
                    wide_ini,
                    wide_fim,
                    g.seconds,
                    version=str(ex.get("version") or "v2"),
                    rows=int(ex.get("rows") or 0),
                    cols=int(ex.get("cols") or 0),
                    fallback_error=ex.get("fallback_error"),
                )
            elif g.name == "investimento":
                perf_record_query(
                    "investimento_diario",
                    wide_ini,
                    wide_fim,
                    g.seconds,
                    0,
                )
    except Exception:
        pass


@st.cache_data(ttl=600, show_spinner=False)
def load_benchmark_shared_frames(
    wide_ini_iso: str,
    wide_fim_iso: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pré-vendas, executivas e investimento no intervalo amplo do benchmark."""
    wide_ini = date.fromisoformat(wide_ini_iso)
    wide_fim = date.fromisoformat(wide_fim_iso)
    return _load_benchmark_shared_frames_impl(wide_ini, wide_fim)


def build_funnel_snapshot_for_window(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool,
    df_prev_wide: pd.DataFrame,
    df_exec_wide: pd.DataFrame,
    df_inv_wide: pd.DataFrame,
) -> FunnelSnapshot:
    """Snapshot de uma janela — legacy por recorte; demais fontes filtradas in-memory."""
    df_one = _fetch_legacy_for_funil(
        data_ini,
        data_fim,
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    df_prev = filter_df_date_range(df_prev_wide, data_ini, data_fim)
    df_exec = filter_df_date_range(df_exec_wide, data_ini, data_fim)
    df_inv = filter_df_date_range(df_inv_wide, data_ini, data_fim)
    return build_funnel_snapshot(df_one, df_prev, df_exec, df_inv)


def build_funnel_snapshot_for_window_with_legacy(
    data_ini: date,
    data_fim: date,
    *,
    df_one: pd.DataFrame,
    df_prev_wide: pd.DataFrame,
    df_exec_wide: pd.DataFrame,
    df_inv_wide: pd.DataFrame,
) -> FunnelSnapshot:
    """Snapshot de uma janela — legacy já carregado; demais fontes filtradas in-memory."""
    df_prev = filter_df_date_range(df_prev_wide, data_ini, data_fim)
    df_exec = filter_df_date_range(df_exec_wide, data_ini, data_fim)
    df_inv = filter_df_date_range(df_inv_wide, data_ini, data_fim)
    return build_funnel_snapshot(df_one, df_prev, df_exec, df_inv)


@st.cache_data(ttl=600, show_spinner=False)
def _load_one_page_funnel_cached(
    data_ini_iso: str,
    data_fim_iso: str,
    excluir_testes_aplicacoes: bool,
) -> dict:
    """Snapshot serializado — chave estável para `st.cache_data`."""
    snap = _load_one_page_funnel_impl(
        date.fromisoformat(data_ini_iso),
        date.fromisoformat(data_fim_iso),
        excluir_testes_aplicacoes=excluir_testes_aplicacoes,
    )
    return asdict(snap)


def load_one_page_funnel(
    data_ini: date,
    data_fim: date,
    *,
    excluir_testes_aplicacoes: bool = False,
) -> FunnelSnapshot:
    """Carrega o funil real do período (cache de 10 min por recorte)."""
    t0 = time.perf_counter()
    payload = _load_one_page_funnel_cached(
        data_ini.isoformat(),
        data_fim.isoformat(),
        bool(excluir_testes_aplicacoes),
    )
    elapsed = time.perf_counter() - t0
    try:
        from src.funil_reconecta_perf import perf_debug_enabled, perf_record_funnel_load

        if perf_debug_enabled():
            perf_record_funnel_load(
                data_ini,
                data_fim,
                elapsed,
                source="load_one_page_funnel",
            )
    except Exception:
        pass
    return FunnelSnapshot(**payload)


def snapshot_to_scenario_dict(snapshot: FunnelSnapshot) -> dict:
    """Converte snapshot em dict compatível com `Scenario` do Funil."""
    return {
        "investimento": snapshot.investimento,
        "custo_lead": snapshot.custo_lead,
        "pct_la": snapshot.pct_la,
        "pct_a_ag": snapshot.pct_a_ag,
        "pct_ag_c": snapshot.pct_ag_c,
        "pct_c_v": snapshot.pct_c_v,
        "ticket": snapshot.ticket,
    }


def snapshot_calc_display(
    snapshot: FunnelSnapshot,
    periodo: str,
    periodos: dict,
) -> dict:
    """Volumes do Atual na escala Mês / Semana / Dia (divisores proporcionais)."""
    div = periodos[periodo]["divisor"]
    return {
        "investimento": snapshot.investimento / div,
        "leads": snapshot.leads / div,
        "aplicacoes": snapshot.aplicacoes / div,
        "agendamentos": snapshot.agendamentos / div,
        "comparecimento": snapshot.comparecimento / div,
        "vendas": snapshot.vendas / div,
        "montante": snapshot.montante / div,
        "receita": snapshot.receita / div,
    }


def snapshot_as_dict(snapshot: FunnelSnapshot) -> dict:
    return asdict(snapshot)
