"""Analise pos-otimizacao Campanhas — script temporario (nao commitar)."""
from __future__ import annotations

import inspect
import statistics
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.db import run_sql_file
from src.marketing_queries import (
    get_mkt_campanha_funil,
    get_mkt_campanhas,
    get_mkt_campanhas_leads_canal_diario,
    get_mkt_campanhas_leads_por_utm,
    get_mkt_paginas_variantes,
)
from src.marketing_transforms import (
    CANAIS_PAGOS,
    agendamentos_one_page_oficial,
    agregar_campanhas_por_utm,
    campanha_funil_kpis,
    campanhas_diario_v2,
    campanhas_kpis,
    campanhas_leads_canal_kpis,
    campanhas_tabela_ativas,
    comparecimentos_one_page_oficial,
    lista_campanhas_funil,
    vendas_one_page_oficial,
)
from src.repositories import (
    get_executivas,
    get_investimento_diario,
    get_leads_visao_geral,
    get_prevendas_overview_diario,
)
from src.transforms import _safe_div

DATA_INI = date(2026, 4, 1)
DATA_FIM = date(2026, 4, 30)
P = {"data_ini": DATA_INI, "data_fim": DATA_FIM}

TRANSFORMS = [
    "campanhas_kpis",
    "campanhas_leads_canal_kpis",
    "campanhas_diario_v2",
    "campanha_funil_kpis",
    "lista_campanhas_funil",
]

SQL_QUERIES = [
    ("get_mkt_campanhas", "mkt_campanhas.sql"),
    ("get_mkt_campanhas_leads_canal_diario", "mkt_campanhas_leads_canal_diario.sql"),
    ("mkt_campanha_funil", "mkt_campanha_funil.sql"),
    ("mkt_funil_agend_one_page_globais", "mkt_funil_agend_one_page_globais.sql"),
    ("get_executivas", "dashboard_executivas.sql"),
    ("get_leads_visao_geral", "leads_visao_geral.sql"),
    ("get_investimento_diario", "investimento_diario.sql"),
    ("get_prevendas_overview_diario", "prevendas_overview_diario.sql"),
    ("get_mkt_campanhas_leads_por_utm", "mkt_campanhas_leads_por_utm.sql"),
    ("get_mkt_paginas_variantes", "mkt_paginas_variantes.sql"),
]

PRODUCTION_REFS = {
    "campanhas_kpis": "views/marketing_campaigns.py:183 — campanhas_kpis(df_camp, pd.DataFrame(), None)",
    "campanhas_leads_canal_kpis": "views/marketing_campaigns.py:184 — campanhas_leads_canal_kpis(df_leads_canal_diario_all, canais_sel)",
    "campanhas_diario_v2": "views/marketing_campaigns.py:406 — campanhas_diario_v2(df_camp, df_leads_canal_diario_all, canais_sel)",
    "lista_campanhas_funil": "views/marketing_campaigns.py:368 — lista_campanhas_funil(df, sb)",
    "campanha_funil_kpis": "views/marketing_campaigns.py:371 + marketing_components via oficiais_loader kwargs",
    "campanhas_tabela_ativas": "views/marketing_campaigns.py:518 — campanhas_tabela_ativas(df_camp, df_leads_por_utm)",
    "agregar_campanhas_por_utm": "views/marketing_campaigns.py:622 — agregar_campanhas_por_utm(df_pv_raw, df_camp, ...)",
}


def mem_mb(df: pd.DataFrame | None) -> float:
    if df is None or df.empty:
        return 0.0
    return df.memory_usage(deep=True).sum() / 1024 / 1024


def print_signatures() -> None:
    import src.marketing_transforms as mt

    print("=== ASSINATURAS CONFIRMADAS (inspect.signature) ===")
    for name in TRANSFORMS:
        fn = getattr(mt, name)
        sig = inspect.signature(fn)
        print(f"  {name}{sig}")
        print(f"    ref: {PRODUCTION_REFS[name]}")


def bench_sql(name: str, fname: str, n: int = 3) -> dict:
    times: list[float] = []
    df = pd.DataFrame()
    for _ in range(n):
        t0 = time.perf_counter()
        df = run_sql_file(fname, P)
        times.append(time.perf_counter() - t0)
    return {
        "name": name,
        "db_p50": statistics.median(times),
        "rows": len(df),
        "cols": len(df.columns) if not df.empty else 0,
        "mem_mb": round(mem_mb(df), 3),
    }


def load_dataframes() -> dict:
    """Carrega DFs reais (fora da medicao de transforms)."""
    import streamlit as st

    st.cache_data.clear()
    df_camp = get_mkt_campanhas(DATA_INI, DATA_FIM)
    df_lcd = get_mkt_campanhas_leads_canal_diario(DATA_INI, DATA_FIM)
    df_funil = get_mkt_campanha_funil(DATA_INI, DATA_FIM)
    df_leads_vg = get_leads_visao_geral(DATA_INI, DATA_FIM)
    df_exec = get_executivas(DATA_INI, DATA_FIM)
    df_inv = get_investimento_diario(DATA_INI, DATA_FIM)
    df_prev = get_prevendas_overview_diario(DATA_INI, DATA_FIM)
    df_utm = get_mkt_campanhas_leads_por_utm(DATA_INI, DATA_FIM)
    df_pv = get_mkt_paginas_variantes(DATA_INI, DATA_FIM)

    assert isinstance(df_camp, pd.DataFrame)
    assert isinstance(df_lcd, pd.DataFrame)
    assert isinstance(df_funil, pd.DataFrame)

    oficiais = {
        "leads_totais_oficial": int(len(df_leads_vg)) if not df_leads_vg.empty else None,
        "vendas_novas_oficial": (
            int(df_exec["vendas"].fillna(0).sum())
            if not df_exec.empty and "vendas" in df_exec.columns
            else None
        ),
        "investimento_oficial": (
            float(df_inv["investimento_total"].fillna(0).sum())
            if not df_inv.empty and "investimento_total" in df_inv.columns
            else None
        ),
        "agendamentos_oficial": agendamentos_one_page_oficial(df_prev),
        "comparecimentos_oficial": comparecimentos_one_page_oficial(df_prev),
        "vendas_oficial": vendas_one_page_oficial(df_prev),
    }
    return {
        "df_camp": df_camp,
        "df_lcd": df_lcd,
        "df_funil": df_funil,
        "df_utm": df_utm,
        "df_pv": df_pv,
        "oficiais": oficiais,
        "canais_sel": list(CANAIS_PAGOS),
    }


def measure_transforms(data: dict) -> None:
    df_camp = data["df_camp"]
    df_lcd = data["df_lcd"]
    df_funil = data["df_funil"]
    df_utm = data["df_utm"]
    df_pv = data["df_pv"]
    canais_sel = data["canais_sel"]
    oficiais = data["oficiais"]

    assert isinstance(df_camp, pd.DataFrame)
    assert isinstance(df_lcd, pd.DataFrame)
    assert isinstance(df_funil, pd.DataFrame)

    print("\n=== TRANSFORMS PYTHON (DFs pre-carregados, sem SQL) ===")
    print("Tipos: df_camp=%s df_lcd=%s df_funil=%s canais_sel=%s" % (
        type(df_camp).__name__, type(df_lcd).__name__,
        type(df_funil).__name__, type(canais_sel).__name__,
    ))

    # Ref: _compute_top_kpis marketing_campaigns.py:183-192
    t0 = time.perf_counter()
    k = campanhas_kpis(df_camp, pd.DataFrame(), None)
    kc = campanhas_leads_canal_kpis(df_lcd, canais_sel)
    k["leads"] = kc["leads_totais"]
    k["leads_qualificados"] = kc["leads_qualificados"]
    k["leads_qualif_mais_12"] = kc["leads_mais_12"]
    k["leads_qualif_menos_12"] = kc["leads_menos_12"]
    k["cpl"] = _safe_div(k["investimento"], k["leads"])
    k["cpl_qualificado"] = _safe_div(k["investimento"], k["leads_qualificados"])
    t_top = (time.perf_counter() - t0) * 1000
    print(f"  _compute_top_kpis (campanhas_kpis + leads_canal + merge): {t_top:.2f}ms")

    # Ref: marketing_campaigns.py:406
    t0 = time.perf_counter()
    diario = campanhas_diario_v2(df_camp, df_lcd, canais_sel)
    t_diario = (time.perf_counter() - t0) * 1000
    print(f"  campanhas_diario_v2: {t_diario:.2f}ms rows={len(diario)}")

    opts = lista_campanhas_funil(df_funil)
    norms = opts["campaign_name_norm"].tolist()
    camp_ind = next(
        (n for n in norms if n not in ("__todos__", "__vinculados__", "__sem_campanha_identificada__")),
        norms[0] if norms else None,
    )

    for label, sel, extra in [
        ("__todos__", "__todos__", oficiais),
        ("__vinculados__", "__vinculados__", {}),
        ("__sem_campanha_identificada__", "__sem_campanha_identificada__", {}),
        ("campanha_individual", camp_ind, {}),
    ]:
        t0 = time.perf_counter()
        if sel == "__todos__":
            campanha_funil_kpis(df_funil, sel, **extra)
        else:
            campanha_funil_kpis(df_funil, sel)
        print(f"  campanha_funil_kpis({label}): {(time.perf_counter()-t0)*1000:.2f}ms")

    t0 = time.perf_counter()
    campanhas_tabela_ativas(df_camp, df_utm)
    print(f"  campanhas_tabela_ativas: {(time.perf_counter()-t0)*1000:.2f}ms")

    t0 = time.perf_counter()
    agregar_campanhas_por_utm(df_pv, df_camp)
    print(f"  agregar_campanhas_por_utm: {(time.perf_counter()-t0)*1000:.2f}ms")


def measure_plot_build(diario: pd.DataFrame) -> float:
    """Ref: _render_tendencia marketing_campaigns.py:411-440 (somente Figure)."""
    import plotly.graph_objects as go

    from src.ui.charts import last_point_text
    from src.ui.theme import PALETTE, int_br

    t0 = time.perf_counter()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=diario["data_ref"], y=diario["investimento"], name="Investimento",
        marker=dict(color=PALETTE["gold"], line=dict(color=PALETTE["gold_soft"], width=0.6)),
        yaxis="y",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads"], name="Leads",
        line=dict(color=PALETTE["wine_light"], width=2.5),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["leads"], int_br),
        yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        x=diario["data_ref"], y=diario["leads_qualificados"],
        name="Leads qualificados",
        line=dict(color="#7C3AED", width=2.5, dash="dot"),
        mode="lines+markers+text", marker=dict(size=6),
        text=last_point_text(diario["leads_qualificados"], int_br),
        yaxis="y2",
    ))
    fig.update_layout(height=360, margin=dict(l=12, r=12, t=20, b=12))
    return (time.perf_counter() - t0) * 1000


def measure_flows(sql_times: dict[str, float]) -> None:
    print("\n=== FLUXO TOTAL (soma SQL medida + transforms medidos) ===")

    def sum_keys(keys: list[str]) -> float:
        return sum(sql_times[k] for k in keys)

    p1_keys = ["get_mkt_campanhas", "get_mkt_campanhas_leads_canal_diario"]
    sel_keys = p1_keys + ["mkt_campanha_funil", "mkt_funil_agend_one_page_globais"]
    todos_off = [
        "get_leads_visao_geral", "get_executivas",
        "get_investimento_diario", "get_prevendas_overview_diario",
    ]
    defer_keys = ["get_mkt_campanhas_leads_por_utm", "get_mkt_paginas_variantes"]

    scenarios = {
        "__todos__ (ate funil, lazy fechados)": sel_keys + todos_off,
        "__todos__ (pagina completa P1-P5)": sel_keys + todos_off + defer_keys,
        "campanha_individual (ate funil)": sel_keys,
        "__vinculados__ / __sem_campanha__ (SQL)": sel_keys,
    }
    for label, keys in scenarios.items():
        total_sql = sum_keys(keys)
        print(f"  {label}: SQL~{total_sql:.2f}s")
        if keys:
            dom = max(((k, sql_times[k]) for k in keys), key=lambda x: x[1])
            print(f"    dominante: {dom[0]} {dom[1]:.2f}s ({100*dom[1]/total_sql:.0f}%)")


def main() -> None:
    print_signatures()

    print("\n=== TEMPO SQL (run_sql_file, n=3, PG buffers nao controlados) ===")
    sql_results = [bench_sql(n, f) for n, f in SQL_QUERIES]
    sql_times = {r["name"]: r["db_p50"] for r in sql_results}
    for r in sql_results:
        print(
            f"  {r['name']}: p50={r['db_p50']:.3f}s "
            f"rows={r['rows']} cols={r['cols']} mem={r['mem_mb']}MB"
        )

    data = load_dataframes()
    measure_transforms(data)

    diario = campanhas_diario_v2(data["df_camp"], data["df_lcd"], data["canais_sel"])
    t_plot = measure_plot_build(diario)
    print(f"\n=== GRAFICO PLOTLY (Figure build, sem st.plotly_chart) ===")
    print(f"  tendencia Figure: {t_plot:.2f}ms")

    measure_flows(sql_times)

    df_exec = run_sql_file("dashboard_executivas.sql", P)
    consumed = {"vendas"}
    print(f"\nget_executivas: cols={len(df_exec.columns)} consumidas={sorted(consumed)} "
          f"nao_usadas={len(df_exec.columns)-len(consumed)}")


if __name__ == "__main__":
    main()
