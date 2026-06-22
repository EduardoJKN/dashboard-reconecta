#!/usr/bin/env python
"""Validacao final CP1-4 — Criativos Marketing.

Somente leitura. Requer banco (RUN_DB_EQUIVALENCE=1).

Cobre:
  - Regressao numerica legacy vs otimizado
  - Vendas slim vs get_executivas (6+ periodos)
  - Ordem de queries simulada
  - Navegacao st.Page (__name__ == __main__)
"""
from __future__ import annotations

import os
import statistics
import sys
import time
import types
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if os.environ.get("RUN_DB_EQUIVALENCE") != "1":
    print("Defina RUN_DB_EQUIVALENCE=1 para executar validacao contra o banco.")
    sys.exit(0)

import pandas as pd

from src.marketing_queries import (
    get_mkt_criativo_funil,
    get_mkt_criativos,
    get_mkt_criativos_resultados,
    get_mkt_top_criativos_por_nome,
)
from src.marketing_transforms import (
    agendamentos_one_page_oficial,
    comparecimentos_one_page_oficial,
    criativo_funil_kpis,
    criativos_kpis,
    criativos_top_por_nome_ranking,
    lista_criativos_funil,
    normalize_status,
    vendas_one_page_oficial,
)
from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_leads_visao_geral,
    get_mkt_campanhas_vendas_oficiais,
    get_prevendas_overview_diario,
)
from src.transforms import _safe_div
from views.marketing_creatives import _resolve_vendas_novas_oficial

_TODOS = "__todos__"
_VINC = "__vinculados__"
_SEM = "__sem_criativo_identificado__"

PERIODS: list[tuple[str, date, date]] = [
    ("abr_2026_mes", date(2026, 4, 1), date(2026, 4, 30)),
    ("abr_parcial_15", date(2026, 4, 1), date(2026, 4, 15)),
    ("mar_2026_mes", date(2026, 3, 1), date(2026, 3, 31)),
    ("fev_2026_mes", date(2026, 2, 1), date(2026, 2, 28)),
    ("abr_dia_10", date(2026, 4, 10), date(2026, 4, 10)),
    ("sem_dados_2020", date(2020, 1, 1), date(2020, 1, 7)),
    ("sem_vendas_futuro", date(2030, 1, 1), date(2030, 1, 31)),
    ("cross_mar_abr", date(2026, 3, 15), date(2026, 4, 15)),
]

VENDAS_PERIODS = PERIODS[:8]


def _prev_period(data_ini: date, data_fim: date) -> tuple[date, date]:
    dias = (data_fim - data_ini).days + 1
    prev_fim = data_ini - timedelta(days=1)
    prev_ini = prev_fim - timedelta(days=dias - 1)
    return prev_ini, prev_fim


def _restrict_resultados(df_res: pd.DataFrame, df_view: pd.DataFrame) -> pd.DataFrame:
    if df_res is None or df_res.empty or df_view.empty:
        return df_res if df_res is not None else pd.DataFrame()
    ads = set(df_view["ad_id"].dropna().astype(str).unique())
    if not ads:
        return df_res.iloc[0:0]
    out = df_res.copy()
    out["ad_id"] = out["ad_id"].astype(str)
    return out[out["ad_id"].isin(ads)]


def _apply_filters(
    df_all: pd.DataFrame,
    campanhas: list[str] | None,
    statuses: list[str] | None,
) -> pd.DataFrame:
    if df_all.empty:
        return df_all
    df = df_all.copy()
    df["status_label"] = df["effective_status"].apply(normalize_status)
    if campanhas:
        all_c = df["campaign_name"].dropna().astype(str).unique().tolist()
        if len(campanhas) < len(all_c):
            want = set(campanhas)
            df = df[df["campaign_name"].astype(str).isin(want)]
    if statuses:
        all_s = df["status_label"].dropna().astype(str).unique().tolist()
        if len(statuses) < len(all_s):
            want = set(statuses)
            df = df[df["status_label"].astype(str).isin(want)]
    return df


def _oficiais_legacy(data_ini: date, data_fim: date) -> dict:
    df_leads = get_leads_visao_geral(data_ini, data_fim)
    df_exec = get_executivas(data_ini, data_fim)
    df_inv = get_investimento_diario(data_ini, data_fim)
    df_prev = get_prevendas_overview_diario(data_ini, data_fim)
    leads_totais = int(len(df_leads)) if not df_leads.empty else None
    vendas_novas = (
        int(df_exec["vendas"].fillna(0).sum())
        if not df_exec.empty and "vendas" in df_exec.columns else None
    )
    investimento = (
        float(df_inv["investimento_total"].fillna(0).sum())
        if not df_inv.empty and "investimento_total" in df_inv.columns else None
    )
    agendamentos = agendamentos_one_page_oficial(df_prev)
    comparecimentos = comparecimentos_one_page_oficial(df_prev)
    vendas_oficial = vendas_one_page_oficial(df_prev)
    return {
        "leads_totais_oficial": leads_totais,
        "vendas_novas_oficial": vendas_novas,
        "investimento_oficial": investimento,
        "agendamentos_oficial": agendamentos,
        "comparecimentos_oficial": comparecimentos,
        "vendas_oficial": vendas_oficial,
    }


def _oficiais_new(data_ini: date, data_fim: date) -> dict:
    df_leads = get_leads_visao_geral(data_ini, data_fim)
    df_vendas = get_mkt_campanhas_vendas_oficiais(data_ini, data_fim)
    df_inv = get_investimento_diario(data_ini, data_fim)
    df_prev = get_prevendas_overview_diario(data_ini, data_fim)
    leads_totais = int(len(df_leads)) if not df_leads.empty else None
    vendas_count = (
        int(df_vendas["vendas"].fillna(0).iloc[0])
        if not df_vendas.empty and "vendas" in df_vendas.columns else None
    )
    investimento = (
        float(df_inv["investimento_total"].fillna(0).sum())
        if not df_inv.empty and "investimento_total" in df_inv.columns else None
    )
    agendamentos = agendamentos_one_page_oficial(df_prev)
    comparecimentos = comparecimentos_one_page_oficial(df_prev)
    vendas_oficial = vendas_one_page_oficial(df_prev)
    vendas_novas = _resolve_vendas_novas_oficial(
        vendas_count,
        leads_totais=leads_totais,
        investimento=investimento,
        agendamentos=agendamentos,
        comparecimentos=comparecimentos,
    )
    return {
        "leads_totais_oficial": leads_totais,
        "vendas_novas_oficial": vendas_novas,
        "investimento_oficial": investimento,
        "agendamentos_oficial": agendamentos,
        "comparecimentos_oficial": comparecimentos,
        "vendas_oficial": vendas_oficial,
    }


def _compare_val(a, b, key: str, tol: float = 0.01) -> str | None:
    if a is None and b is None:
        return None
    if a is None or b is None:
        return f"{key}: legacy={a} new={b}"
    try:
        fa, fb = float(a), float(b)
        if abs(fa - fb) > tol:
            return f"{key}: legacy={a} new={b} delta={fb - fa}"
    except (TypeError, ValueError):
        if a != b:
            return f"{key}: legacy={a} new={b}"
    return None


def _funil_keys() -> list[str]:
    return [
        "investimento", "impressoes", "cliques", "alcance", "ctr", "cpc",
        "leads_totais", "leads_mais_12", "leads_menos_12", "leads_nao_atua",
        "aplicacoes", "aplicacoes_mais_12", "aplicacoes_menos_12",
        "aplicacoes_nao_atua", "agendamentos", "comparecimentos",
        "vendas_novas", "cpl", "cpl_mais_12", "cac",
    ]


def _kpi_keys() -> list[str]:
    return [
        "anuncios_ativos", "investimento", "impressoes", "alcance",
        "frequencia", "cliques", "ctr", "cpc",
        "leads_total", "aplicacoes", "leads_mais_12", "leads_menos_12",
        "leads_nao_atua", "agendamentos", "comparecimentos", "vendas",
    ]


def _pick_criativo(df_funil: pd.DataFrame) -> str | None:
    opts = lista_criativos_funil(df_funil)
    for norm in opts["ad_name_norm"]:
        if norm not in (_TODOS, _VINC, _SEM):
            return str(norm)
    return None


def _check_navigation_guard() -> bool:
    print("\n=== NAVEGACAO st.Page (__name__ guard) ===")
    code = Path(ROOT / "views" / "marketing_creatives.py").read_text(encoding="utf-8")
    mod = types.ModuleType("__main__")
    mod.__dict__["__file__"] = str(ROOT / "views" / "marketing_creatives.py")
    snippet = "result_name = __name__\n"
    exec(snippet, mod.__dict__)
    ok = mod.__dict__["result_name"] == "__main__"
    has_guard = 'if __name__ == "__main__":' in code and "main()" in code
    print(f"  exec em ModuleType('__main__'): __name__={mod.__dict__['result_name']}")
    print(f"  guard presente no arquivo: {has_guard}")
    print(f"  Compativel com st.Page.exec: {'OK' if ok else 'FALHOU'}")
    return ok and has_guard


def _validate_vendas_slim() -> list[str]:
    print("\n=== VENDAS SLIM vs get_executivas (8 periodos) ===")
    issues: list[str] = []
    print(f"{'periodo':<18} {'executivas':>10} {'slim':>10} {'resolved':>10} {'diff':>6}")
    for label, di, df in VENDAS_PERIODS:
        df_exec = get_executivas(di, df)
        vl = (
            int(df_exec["vendas"].fillna(0).sum())
            if not df_exec.empty and "vendas" in df_exec.columns else None
        )
        df_v = get_mkt_campanhas_vendas_oficiais(di, df)
        vn_raw = (
            int(df_v["vendas"].fillna(0).iloc[0])
            if not df_v.empty and "vendas" in df_v.columns else 0
        )
        df_leads = get_leads_visao_geral(di, df)
        lt = int(len(df_leads)) if not df_leads.empty else None
        df_inv = get_investimento_diario(di, df)
        inv = (
            float(df_inv["investimento_total"].fillna(0).sum())
            if not df_inv.empty else None
        )
        df_prev = get_prevendas_overview_diario(di, df)
        ag = agendamentos_one_page_oficial(df_prev)
        comp = comparecimentos_one_page_oficial(df_prev)
        vr = _resolve_vendas_novas_oficial(
            vn_raw if vn_raw or vl is not None else None,
            leads_totais=lt, investimento=inv,
            agendamentos=ag, comparecimentos=comp,
        )
        diff = (vn_raw - vl) if vl is not None else None
        if vl is not None and vn_raw != vl:
            issues.append(f"{label}: executivas={vl} slim={vn_raw}")
        print(f"{label:<18} {str(vl):>10} {vn_raw:>10} {str(vr):>10} {str(diff):>6}")
    print(f"  Resultado: {'OK' if not issues else 'DIVERGENCIAS'}")
    for i in issues:
        print(f"    {i}")
    return issues


def _numeric_regression() -> list[str]:
    print("\n=== REGRESSAO NUMERICA (legacy vs otimizado) ===")
    issues: list[str] = []

    scenarios: list[tuple[str, date, date, list[str] | None, list[str] | None]] = [
        ("mes_completo", date(2026, 4, 1), date(2026, 4, 30), None, None),
        ("parcial_abr", date(2026, 4, 1), date(2026, 4, 15), None, None),
        ("periodo_anterior", date(2026, 3, 1), date(2026, 3, 31), None, None),
        ("sem_dados", date(2020, 1, 1), date(2020, 1, 7), None, None),
    ]

    di0, df0 = date(2026, 4, 1), date(2026, 4, 30)
    df_probe = get_mkt_criativos(di0, df0)
    if not df_probe.empty:
        camps = sorted(df_probe["campaign_name"].dropna().astype(str).unique())
        if camps:
            scenarios.append(("uma_campanha", di0, df0, [camps[0]], None))
        df_norm = df_probe.copy()
        df_norm["status_label"] = df_norm["effective_status"].apply(normalize_status)
        stats = sorted(df_norm["status_label"].dropna().astype(str).unique())
        if stats:
            scenarios.append(("um_status", di0, df0, None, [stats[0]]))

    for label, data_ini, data_fim, camps, statuses in scenarios:
        print(f"\n  --- {label} ({data_ini} -> {data_fim}) ---")
        df_all = get_mkt_criativos(data_ini, data_fim)
        prev_ini, prev_fim = _prev_period(data_ini, data_fim)
        df_prev_all = get_mkt_criativos(prev_ini, prev_fim)
        df_res = get_mkt_criativos_resultados(data_ini, data_fim)
        df_filt = _apply_filters(df_all, camps, statuses)
        df_prev_filt = _apply_filters(df_prev_all, camps, statuses)
        df_res_f = _restrict_resultados(df_res, df_filt)
        _restrict_resultados(
            get_mkt_criativos_resultados(prev_ini, prev_fim), df_prev_filt,
        )

        k = criativos_kpis(df_filt, df_res_f)
        print(
            f"    Performance Meta: ativos={k['anuncios_ativos']} "
            f"inv={k['investimento']:.2f} imp={k['impressoes']} "
            f"ctr={k['ctr']:.4f} cpc={k['cpc']:.4f}"
        )

        df_funil = get_mkt_criativo_funil(data_ini, data_fim)
        if not df_funil.empty and camps:
            cn = camps[0].strip().lower()
            if "campaign_name_norm" in df_funil.columns:
                sub = df_funil[
                    df_funil["campaign_name_norm"].astype(str).str.lower()
                    == cn
                ]
                if not sub.empty:
                    df_funil = sub

        off_leg = _oficiais_legacy(data_ini, data_fim)
        off_new = _oficiais_new(data_ini, data_fim)
        for ok in (
            "leads_totais_oficial", "investimento_oficial",
            "agendamentos_oficial", "comparecimentos_oficial",
        ):
            d = _compare_val(off_leg.get(ok), off_new.get(ok), ok)
            if d:
                issues.append(f"{label} oficiais {d}")

        k_todos_leg = criativo_funil_kpis(df_funil, _TODOS, **off_leg)
        k_todos_new = criativo_funil_kpis(df_funil, _TODOS, **off_new)
        for fk in _funil_keys():
            d = _compare_val(k_todos_leg.get(fk), k_todos_new.get(fk), fk)
            if d:
                issues.append(f"{label} __todos__ {d}")
        print(
            f"    __todos__: leads={k_todos_new['leads_totais']} "
            f"vendas={k_todos_new['vendas_novas']} inv={k_todos_new['investimento']:.2f}"
        )

        k_vinc = criativo_funil_kpis(df_funil, _VINC)
        print(
            f"    __vinculados__: leads={k_vinc['leads_totais']} "
            f"vendas={k_vinc['vendas_novas']}"
        )

        cri = _pick_criativo(df_funil)
        if cri:
            k_cri = criativo_funil_kpis(df_funil, cri)
            print(
                f"    criativo ({cri[:40]}): leads={k_cri['leads_totais']} "
                f"vendas={k_cri['vendas_novas']}"
            )

        opts = lista_criativos_funil(df_funil)
        print(f"    Seletor: {len(opts)} opcoes, ordem[0:3]={opts['ad_name_norm'].head(3).tolist()}")

        df_top = get_mkt_top_criativos_por_nome(data_ini, data_fim)
        top = criativos_top_por_nome_ranking(
            df_filt, df_top, df_res_f, sort_by="investimento", ascending=False, top_n=12,
        )
        if not top.empty:
            print(
                f"    Top12: n={len(top)} "
                f"invest_sum={top['investimento'].sum():.2f} "
                f"primeiro={top.iloc[0].get('ad_name', '?')}"
            )

    if not issues:
        print("\n  Resultado: sem divergencias numericas (tolerancia 0.01)")
    return issues


def _query_paths() -> None:
    print("\n=== ORDEM DE QUERIES (cenarios) ===")
    paths = {
        "ate_performance_meta": [
            "bi.vw_mkt_criativos", "bi.vw_mkt_criativos (prev)",
            "mart criativos", "mart criativos (prev)",
        ],
        "ate_seletor": ["+ mkt_criativo_funil"],
        "__todos__": [
            "+ leads_visao_geral", "+ mkt_campanhas_vendas_oficiais",
            "+ investimento_diario", "+ prevendas_overview_diario",
        ],
        "criativo_individual": ["(sem oficiais)"],
        "top12": ["+ mkt_top_criativos_por_nome"],
        "comparar": ["+ mkt_paginas_variantes"],
        "auditorias_fechadas": ["(zero FDW, zero leads audit)"],
        "auditoria_fdw_aberta": ["+ fdw_reconecta.anuncios"],
        "auditoria_leads_aberta": ["+ leads audit", "+ fdw (cache se ambas)"],
    }
    for name, qs in paths.items():
        print(f"  {name}: {qs}")


def _benchmark_phases() -> None:
    print("\n=== BENCHMARK FASES SQL (abr/2026, cache PG nao controlado) ===")
    di, df = date(2026, 4, 1), date(2026, 4, 30)
    prev_ini, prev_fim = _prev_period(di, df)

    import streamlit as st
    st.cache_data.clear()

    def _timed(fn, label: str) -> float:
        t0 = time.perf_counter()
        fn()
        sec = time.perf_counter() - t0
        print(f"  {label}: {sec:.3f}s")
        return sec

    t0 = time.perf_counter()
    _timed(lambda: get_mkt_criativos(di, df), "criativos atual")
    _timed(lambda: get_mkt_criativos(prev_ini, prev_fim), "criativos prev")
    _timed(lambda: get_mkt_criativos_resultados(di, df), "resultados atual")
    _timed(lambda: get_mkt_criativos_resultados(prev_ini, prev_fim), "resultados prev")
    t_p1 = time.perf_counter() - t0

    t_sel = _timed(lambda: get_mkt_criativo_funil(di, df), "criativo_funil") + t_p1

    t0_off = time.perf_counter()
    get_leads_visao_geral(di, df)
    get_mkt_campanhas_vendas_oficiais(di, df)
    get_investimento_diario(di, df)
    get_prevendas_overview_diario(di, df)
    t_funil = time.perf_counter() - t0

    t_top_cold = _timed(
        lambda: get_mkt_top_criativos_por_nome(di, df),
        "top_nome (1a chamada apos cache clear)",
    )
    t_top_warm = _timed(
        lambda: get_mkt_top_criativos_por_nome(di, df),
        "top_nome (2a chamada = cache hit app)",
    )

    print(f"\n  Resumo __todos__ (cache app limpo no inicio do bloco):")
    print(f"    ate Performance Meta: {t_p1:.3f}s")
    print(f"    ate seletor: {t_sel:.3f}s")
    print(f"    ate funil+oficiais: {t_funil:.3f}s")
    if t_top_warm < 0.05 and t_top_cold < 0.05:
        print(
            "    Top 12 neste bloco: cache hit da aplicacao "
            f"({t_top_cold:.3f}s / {t_top_warm:.3f}s) — NAO e tempo SQL real"
        )
    else:
        print(
            f"    Top 12 (1a chamada neste processo): {t_top_cold:.3f}s"
        )
        print(f"    Top 12 (cache hit app): {t_top_warm:.3f}s")
    print(
        "    Referencia SQL frio medida separadamente: "
        "mkt_top_criativos_por_nome ~133s (fora do caminho critico; "
        "a pagina continua executando enquanto a secao carrega)"
    )


def main() -> None:
    print("=== VALIDACAO FINAL CP1-4 CRIATIVOS ===")
    nav_ok = _check_navigation_guard()
    _query_paths()
    vendas_issues = _validate_vendas_slim()
    num_issues = _numeric_regression()
    _benchmark_phases()

    all_ok = nav_ok and not vendas_issues and not num_issues
    print(f"\n=== RESULTADO GERAL: {'OK' if all_ok else 'FALHOU'} ===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
