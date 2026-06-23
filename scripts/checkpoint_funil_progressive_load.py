#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Checkpoint CP9.2 - carregamento progressivo automatico + ordem visual.

Compara:
  1. Modo classico/eager (FUNIL_PROGRESSIVE_LOAD=0 ou BENCHMARK_MODE=classic)
  2. Progressive auto (default) - 1a dobra rapida + benchmark automatico
  3. Progressive manual (fallback) - botao opcional
  4. Warm rerun (progressive auto, benchmark em session)

Uso (PowerShell):
  Set-Location "c:\\Users\\zz\\Desktop\\Dashboards_Reconecta\\dashboard_py"
  python scripts\\checkpoint_funil_progressive_load.py
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.funil_progressive_load import (  # noqa: E402
    BENCHMARK_LOAD_BTN_KEY,
)
from src.funil_effective_period import FUNIL_MES_ATUAL_ATE_HOJE_KEY  # noqa: E402
from src.ui.page import (  # noqa: E402
    PERIOD_PRESET_KEY,
    PERIOD_RANGE_KEY,
    resolve_preset,
)

HOJE = date(2026, 6, 22)
PERF_KEY = "_funil_funil_reconecta_perf"
VIEW = ROOT / "views" / "funil_reconecta.py"

SCENARIOS: dict[str, tuple[date, date]] = {
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "mes_anterior": (date(2026, 5, 1), date(2026, 5, 31)),
    "recorte_jun_2026": (date(2026, 6, 1), date(2026, 6, 17)),
    "sem_dados": (date(2099, 1, 1), date(2099, 1, 7)),
}


@contextmanager
def _env(**kwargs: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in kwargs}
    try:
        for k, v in kwargs.items():
            os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _ss_get(at: AppTest, key: str) -> Any:
    try:
        return at.session_state[key]
    except (KeyError, AttributeError, TypeError):
        return None


def _perf_state(at: AppTest) -> dict[str, Any]:
    try:
        raw = at.session_state[PERF_KEY]
        return dict(raw) if isinstance(raw, dict) else {}
    except (KeyError, AttributeError, TypeError):
        return {}


def _block_seconds(perf: dict, *names: str) -> float | None:
    blocks = {b["block"]: b["seconds"] for b in (perf.get("blocks") or [])}
    for name in names:
        if name in blocks:
            return float(blocks[name])
    return None


def _run_apptest(
    data_ini: date,
    data_fim: date,
    *,
    warm_from: AppTest | None = None,
) -> AppTest:
    if warm_from is not None:
        at = warm_from
        at.run(timeout=900)
        return at

    at = AppTest.from_file(str(VIEW), default_timeout=900)
    at.query_params["debug_perf"] = "1"
    at.session_state[PERIOD_RANGE_KEY] = (data_ini, data_fim)
    at.session_state[PERIOD_PRESET_KEY] = "Personalizado"
    at.session_state["_global_period_initialized"] = True
    at.run(timeout=900)
    return at


def _summarize(perf: dict, *, mode: str, label: str) -> dict[str, Any]:
    prog = dict(perf.get("progressive") or {})
    milestones = perf.get("milestones") or {}
    return {
        "mode": mode,
        "scenario": label,
        "first_fold_time": (
            prog.get("first_fold_time")
            or perf.get("first_fold_seconds")
            or milestones.get("primeira dobra útil")
        ),
        "main_sections_seconds": perf.get("main_sections_seconds"),
        "full_page_time": prog.get("full_page_time"),
        "benchmark_block": _block_seconds(perf, "Benchmark histórico"),
        "benchmark_time": prog.get("benchmark_time") or prog.get("benchmark_lazy_time"),
        "progressive": prog,
        "benchmark_auto_loaded": bool(prog.get("benchmark_auto_loaded")),
        "benchmark_skipped": bool(prog.get("benchmark_skipped")),
        "referencia_skipped": bool(perf.get("referencia_skipped")),
        "export_prepared": bool(perf.get("export_prepared")),
        "funnel_loads": perf.get("funnel_loads", 0),
    }


def _markdown_blob(at: AppTest) -> str:
    parts: list[str] = []
    for m in at.markdown or []:
        val = getattr(m, "value", None) or ""
        parts.append(str(val))
    return "\n".join(parts)


def _layout_order_checks(at: AppTest) -> dict[str, bool]:
    """Valida ordem visual CP9.2: Benchmark -> Cenarios -> Comparativo."""
    blob = _markdown_blob(at)
    pos_bm = blob.find("Benchmark histórico")
    pos_cen = blob.find("Cenários no Simulador")
    pos_cmp = blob.find("Comparativo de cenários")
    order_ok = (
        pos_bm >= 0
        and pos_cen >= 0
        and pos_cmp >= 0
        and pos_bm < pos_cen < pos_cmp
    )
    btn_labels = [b.label or "" for b in (at.button or [])]
    has_conservador = any("conservador" in lbl.lower() for lbl in btn_labels)
    has_comparativo = pos_cmp >= 0
    return {
        "ordem_benchmark_cenarios_comparativo": order_ok,
        "botoes_cenario_presentes": has_conservador,
        "comparativo_presente": has_comparativo,
    }


def _visual_checks(
    at: AppTest,
    *,
    expect_benchmark_df: bool,
    allow_manual_button: bool = False,
    check_layout_order: bool = False,
) -> dict[str, bool | str]:
    errs = [e.value for e in (at.error or [])]
    excs = [e.value for e in (at.exception or [])]
    has_err = bool(errs or excs)
    btn_keys = [b.key for b in (at.button or [])]
    checks: dict[str, bool | str] = {
        "sem_erro_streamlit": not has_err,
        "controles_simulador": len(at.button) >= 3,
        "expander_perf": any(
            "performance" in (e.label or "").lower()
            or "funil da reconecta" in (e.label or "").lower()
            for e in (at.expander or [])
        ),
    }
    if expect_benchmark_df:
        checks["benchmark_dataframe_sem_clique"] = len(at.dataframe) >= 1
        checks["sem_botao_obrigatorio"] = BENCHMARK_LOAD_BTN_KEY not in btn_keys
    elif allow_manual_button:
        checks["botao_manual_presente"] = BENCHMARK_LOAD_BTN_KEY in btn_keys
    if check_layout_order:
        checks.update(_layout_order_checks(at))
    if has_err:
        checks["erro"] = "; ".join(errs + excs)
    return checks


def _session_state_keys(at: AppTest) -> list[str]:
    """Lista chaves do session_state (AppTest nao suporta iteracao direta)."""
    try:
        inner = at.session_state._state
        return [str(k) for k in inner._keys()]
    except (AttributeError, TypeError, KeyError):
        pass
    try:
        raw = at.session_state._state._new_session_state
        return [str(k) for k in raw]
    except (AttributeError, TypeError, KeyError):
        return []


def _benchmark_cache_keys(at: AppTest) -> list[str]:
    return sorted(
        k
        for k in _session_state_keys(at)
        if k.startswith("funil_benchmark_data_")
    )


def _benchmark_media_signature(at: AppTest) -> str:
    import pandas as pd

    for el in at.dataframe or []:
        val = getattr(el, "value", None)
        if isinstance(val, pd.DataFrame) and "Média histórica" in val.columns:
            return "|".join(str(x) for x in val["Média histórica"].head(8).tolist())
    return ""


def _hist_base_switch_ok(data_ini: date, data_fim: date) -> dict[str, Any]:
    """Troca base historica e confirma recalculo (nao reaproveita cache antigo)."""
    presets = [
        ("365", "Últimos 12 meses"),
        ("30", "Último mês"),
        ("180", "Últimos 6 meses"),
    ]
    with _env(
        FUNIL_PROGRESSIVE_LOAD="1",
        FUNIL_PROGRESSIVE_BENCHMARK_MODE="auto",
        FUNIL_PARALLEL_LOADS="0",
    ):
        at = _run_apptest(data_ini, data_fim)
        runs: dict[str, dict[str, Any]] = {}
        for key, label in presets:
            at.session_state["funil_hist_base"] = key
            at.run(timeout=900)
            blob = _markdown_blob(at)
            runs[key] = {
                "label": label,
                "media_sig": _benchmark_media_signature(at),
                "base_text_ok": label in blob,
                "cache_keys": _benchmark_cache_keys(at),
            }

        sig_12 = runs["365"]["media_sig"]
        sig_1 = runs["30"]["media_sig"]
        sig_6 = runs["180"]["media_sig"]
        media_changed = bool(
            sig_12 and sig_1 and sig_12 != sig_1 and sig_6 != sig_1,
        )
        keys_grow = len(runs["180"]["cache_keys"]) >= 2
        distinct_keys = len({k for r in runs.values() for k in r["cache_keys"]}) >= 2

        at.session_state["funil_hist_base"] = "180"
        at.session_state["funil_hist_same_interval"] = False
        at.run(timeout=900)
        media_same_interval_off = _benchmark_media_signature(at)
        blob_off = _markdown_blob(at)
        windows_off = "fr-benchmark-window" in blob_off
        win_excerpt_off = blob_off[blob_off.find("Janelas comparadas"):][:400]

        at.session_state["funil_hist_same_interval"] = True
        at.run(timeout=900)
        media_same_interval_on = _benchmark_media_signature(at)
        blob_on = _markdown_blob(at)
        win_excerpt_on = blob_on[blob_on.find("Janelas comparadas"):][:400]

        interval_changed = win_excerpt_off != win_excerpt_on

        for periodo in ("mes", "semana", "dia"):
            at.session_state["funil_periodo"] = periodo
            at.run(timeout=900)
            if not _layout_order_checks(at).get(
                "ordem_benchmark_cenarios_comparativo",
            ):
                return {"ok": False, "reason": f"layout_fail_{periodo}", "runs": runs}

        ok = (
            all(r["base_text_ok"] for r in runs.values())
            and media_changed
            and keys_grow
            and distinct_keys
            and interval_changed
            and windows_off
        )
        return {
            "ok": ok,
            "media_12m": sig_12[:80],
            "media_1m": sig_1[:80],
            "media_6m": sig_6[:80],
            "interval_off": media_same_interval_off[:80],
            "interval_on": media_same_interval_on[:80],
            "cache_key_count": len(runs["180"]["cache_keys"]),
            "distinct_cache_keys": len({k for r in runs.values() for k in r["cache_keys"]}),
            "runs": runs,
        }


def _perf_context(at: AppTest) -> dict[str, Any]:
    try:
        raw = at.session_state[PERF_KEY]
        return dict((raw or {}).get("context") or {})
    except (KeyError, AttributeError, TypeError):
        return {}


def _run_apptest_preset(
    preset: str,
    data_ini: date,
    data_fim: date,
    *,
    session_extra: dict[str, Any] | None = None,
) -> AppTest:
    at = AppTest.from_file(str(VIEW), default_timeout=900)
    at.query_params["debug_perf"] = "1"
    at.session_state[PERIOD_PRESET_KEY] = preset
    at.session_state[PERIOD_RANGE_KEY] = (data_ini, data_fim)
    at.session_state["_global_period_initialized"] = True
    for key, value in (session_extra or {}).items():
        at.session_state[key] = value
    at.run(timeout=900)
    return at


def _mes_atual_ate_hoje_ok() -> dict[str, Any]:
    """Mês atual até hoje: período efetivo, meta proporcional e benchmark."""
    hoje = date.today()
    mes_civil = resolve_preset("Mês atual", hoje)
    assert mes_civil is not None
    civil_ini, civil_fim = mes_civil
    custom_ini, custom_fim = hoje.replace(day=1), hoje
    dias_parcial = (custom_fim - custom_ini).days + 1
    dias_mes = (civil_fim - civil_ini).days + 1
    prop_txt = f"{dias_parcial} de {dias_mes} dias"

    with _env(
        FUNIL_PROGRESSIVE_LOAD="1",
        FUNIL_PROGRESSIVE_BENCHMARK_MODE="auto",
        FUNIL_PARALLEL_LOADS="0",
    ):
        at_on = _run_apptest_preset(
            "Mês atual",
            civil_ini,
            civil_fim,
            session_extra={FUNIL_MES_ATUAL_ATE_HOJE_KEY: True},
        )
        ctx_on = _perf_context(at_on)
        blob_on = _markdown_blob(at_on)
        media_on = _benchmark_media_signature(at_on)

        at_off = _run_apptest_preset(
            "Mês atual",
            civil_ini,
            civil_fim,
            session_extra={FUNIL_MES_ATUAL_ATE_HOJE_KEY: False},
        )
        ctx_off = _perf_context(at_off)
        media_off = _benchmark_media_signature(at_off)

        at_custom = _run_apptest_preset(
            "Personalizado",
            custom_ini,
            custom_fim,
            session_extra={FUNIL_MES_ATUAL_ATE_HOJE_KEY: True},
        )
        media_custom = _benchmark_media_signature(at_custom)

        mes_ant = resolve_preset("Último mês", hoje)
        assert mes_ant is not None
        at_prev = _run_apptest_preset(
            "Último mês",
            mes_ant[0],
            mes_ant[1],
            session_extra={FUNIL_MES_ATUAL_ATE_HOJE_KEY: True},
        )
        ctx_prev = _perf_context(at_prev)

    eff_on = ctx_on.get("periodo_efetivo", "")
    eff_off = ctx_off.get("periodo_efetivo", "")
    eff_prev = ctx_prev.get("periodo_efetivo", "")

    on_partial = (
        custom_ini.strftime("%d/%m/%Y") in eff_on
        and custom_fim.strftime("%d/%m/%Y") in eff_on
        and ctx_on.get("usar_mes_atual_ate_hoje") is True
        and (
            prop_txt in blob_on
            or ctx_on.get("dias_meta") == f"{dias_parcial}/{dias_mes}"
            or ctx_on.get("meta_proporcional") is True
        )
    )
    off_full = (
        civil_fim.strftime("%d/%m/%Y") in eff_off
        and ctx_off.get("usar_mes_atual_ate_hoje") is False
    )
    custom_matches_on = bool(media_on) and media_on == media_custom
    media_diff = bool(media_on) and media_on != media_off
    prev_unchanged = (
        ctx_prev.get("usar_mes_atual_ate_hoje") is False
        and mes_ant[0].strftime("%d/%m/%Y") in eff_prev
        and mes_ant[1].strftime("%d/%m/%Y") in eff_prev
    )
    layout_ok = _layout_order_checks(at_on).get(
        "ordem_benchmark_cenarios_comparativo",
    )

    ok = (
        on_partial
        and off_full
        and custom_matches_on
        and media_diff
        and prev_unchanged
        and layout_ok
    )
    return {
        "ok": ok,
        "eff_on": eff_on,
        "eff_off": eff_off,
        "eff_prev": eff_prev,
        "prop_txt": prop_txt,
        "media_on": media_on[:80],
        "media_off": media_off[:80],
        "media_custom": media_custom[:80],
    }


def _benchmark_table_signature(at: AppTest) -> dict[str, str]:
    """Extrai médias da tabela Benchmark histórico por métrica."""
    import pandas as pd

    out: dict[str, str] = {}
    for el in at.dataframe or []:
        val = getattr(el, "value", None)
        if not isinstance(val, pd.DataFrame):
            continue
        if "Média histórica" not in val.columns or "Métrica" not in val.columns:
            continue
        for _, row in val.iterrows():
            metric = str(row.get("Métrica", "")).strip()
            media = str(row.get("Média histórica", "")).strip()
            if metric:
                out[metric] = media
    return out


def _same_interval_benchmark_ok() -> dict[str, Any]:
    """Benchmark parcial (same_interval) não zera Agendamentos+."""
    hoje = date.today()
    mes_civil = resolve_preset("Mês atual", hoje)
    assert mes_civil is not None
    civil_ini, civil_fim = mes_civil
    with _env(
        FUNIL_PROGRESSIVE_LOAD="1",
        FUNIL_PROGRESSIVE_BENCHMARK_MODE="auto",
        FUNIL_PARALLEL_LOADS="0",
    ):
        at_on = _run_apptest_preset(
            "Mês atual",
            civil_ini,
            civil_fim,
            session_extra={
                FUNIL_MES_ATUAL_ATE_HOJE_KEY: True,
                "funil_hist_base": "90",
                "funil_hist_same_interval": True,
            },
        )
        sig_on = _benchmark_table_signature(at_on)

        at_off = _run_apptest_preset(
            "Mês atual",
            civil_ini,
            civil_fim,
            session_extra={
                FUNIL_MES_ATUAL_ATE_HOJE_KEY: True,
                "funil_hist_base": "90",
                "funil_hist_same_interval": False,
            },
        )
        sig_off = _benchmark_table_signature(at_off)

    def _num(txt: str) -> float:
        import re
        if not txt or txt in {"—", "-"}:
            return 0.0
        m = re.search(r"[\d.,]+", txt.replace(".", "").replace(",", "."))
        return float(m.group()) if m else 0.0

    ag_on = _num(sig_on.get("Agendamentos", ""))
    cmp_on = _num(sig_on.get("Comparecimentos", ""))
    vend_on = _num(sig_on.get("Vendas", ""))
    ticket_on = sig_on.get("Ticket Médio", "")
    layout_ok = _layout_order_checks(at_on).get(
        "ordem_benchmark_cenarios_comparativo",
    )
    ag_off = _num(sig_off.get("Agendamentos", ""))
    changed = ag_on > 0 and (ag_off <= 0 or ag_on != ag_off)

    ok = (
        ag_on > 0
        and cmp_on > 0
        and vend_on > 0
        and ticket_on not in {"", "—", "R$ 0,00", "R$ 0"}
        and layout_ok
        and changed
    )
    return {
        "ok": ok,
        "ag_on": sig_on.get("Agendamentos"),
        "cmp_on": sig_on.get("Comparecimentos"),
        "vendas_on": sig_on.get("Vendas"),
        "ticket_on": ticket_on,
        "ag_off": sig_off.get("Agendamentos"),
        "layout_ok": layout_ok,
    }


def _period_change_ok(data_ini: date, data_fim: date) -> dict[str, Any]:
    other_ini = data_ini - timedelta(days=30)
    other_fim = data_fim - timedelta(days=30)
    with _env(
        FUNIL_PROGRESSIVE_LOAD="1",
        FUNIL_PROGRESSIVE_BENCHMARK_MODE="auto",
    ):
        at_a = _run_apptest(data_ini, data_fim)
        keys_a = _benchmark_cache_keys(at_a)
        cache_a = _ss_get(at_a, keys_a[-1]) if keys_a else None
        at_b = AppTest.from_file(str(VIEW), default_timeout=900)
        at_b.query_params["debug_perf"] = "1"
        at_b.session_state[PERIOD_RANGE_KEY] = (other_ini, other_fim)
        at_b.session_state[PERIOD_PRESET_KEY] = "Personalizado"
        at_b.session_state["_global_period_initialized"] = True
        if cache_a is not None and keys_a:
            at_b.session_state[keys_a[-1]] = cache_a
            loaded_key = keys_a[-1].replace("funil_benchmark_data_", "funil_benchmark_loaded_", 1)
            at_b.session_state[loaded_key] = True
        at_b.run(timeout=900)
        perf_b = _perf_state(at_b)
        prog_b = perf_b.get("progressive") or {}
        keys_b = _benchmark_cache_keys(at_b)
        reused_wrong_key = bool(keys_a) and keys_a[-1] in keys_b and len(keys_b) == 1
        return {
            "other_period_cache_isolated": not reused_wrong_key,
            "benchmark_auto_other": bool(prog_b.get("benchmark_auto_loaded")),
            "ok": bool(prog_b.get("benchmark_auto_loaded")) and not reused_wrong_key,
        }


def run_scenario(label: str, data_ini: date, data_fim: date) -> dict[str, Any]:
    print(f"\n{'=' * 72}", flush=True)
    print(f"CENARIO: {label} | {data_ini} -> {data_fim}", flush=True)
    print(f"{'=' * 72}", flush=True)

    with _env(
        FUNIL_PROGRESSIVE_LOAD="1",
        FUNIL_PROGRESSIVE_BENCHMARK_MODE="auto",
        FUNIL_PARALLEL_LOADS="0",
    ):
        at_auto = _run_apptest(data_ini, data_fim)
        auto = _summarize(_perf_state(at_auto), mode="progressive_auto", label=label)
        auto["visual"] = _visual_checks(
            at_auto, expect_benchmark_df=True, check_layout_order=True,
        )

        at_warm = _run_apptest(data_ini, data_fim, warm_from=at_auto)
        warm = _summarize(_perf_state(at_warm), mode="warm_auto", label=label)

    with _env(
        FUNIL_PROGRESSIVE_LOAD="1",
        FUNIL_PROGRESSIVE_BENCHMARK_MODE="manual",
        FUNIL_PARALLEL_LOADS="0",
    ):
        at_manual = _run_apptest(data_ini, data_fim)
        manual = _summarize(
            _perf_state(at_manual), mode="progressive_manual", label=label,
        )
        manual["visual"] = _visual_checks(
            at_manual, expect_benchmark_df=False, allow_manual_button=True,
        )

    with _env(FUNIL_PROGRESSIVE_LOAD="0", FUNIL_PARALLEL_LOADS="0"):
        at_classic = _run_apptest(data_ini, data_fim)
        classic = _summarize(_perf_state(at_classic), mode="classic", label=label)
        classic["visual"] = _visual_checks(at_classic, expect_benchmark_df=True)

    period_ok = _period_change_ok(data_ini, data_fim) if label == "mes_atual" else None
    hist_base_ok = _hist_base_switch_ok(data_ini, data_fim) if label == "mes_atual" else None
    mes_ate_hoje_ok = _mes_atual_ate_hoje_ok() if label == "mes_atual" else None
    same_interval_ok = _same_interval_benchmark_ok() if label == "mes_atual" else None

    def _row(name: str, row: dict[str, Any]) -> None:
        ff = row.get("first_fold_time") or 0
        full = row.get("full_page_time") or row.get("main_sections_seconds") or 0
        bm = row.get("benchmark_block") or row.get("benchmark_time")
        bm_txt = f"  bm={bm:.3f}s" if bm is not None else "  bm=-"
        print(
            f"  {name:<22} first_fold={ff:7.3f}s  full={full:7.3f}s{bm_txt}",
            flush=True,
        )

    _row("progressive_auto", auto)
    _row("warm_auto", warm)
    _row("progressive_manual", manual)
    _row("classic", classic)

    auto_vis = all(
        v is True for k, v in auto.get("visual", {}).items() if k != "erro"
    )
    layout = auto.get("visual", {})
    print(
        f"  auto: df sem clique={'OK' if auto_vis else 'FAIL'}  "
        f"bm_auto={auto.get('benchmark_auto_loaded')}  "
        f"ordem={'OK' if layout.get('ordem_benchmark_cenarios_comparativo') else 'FAIL'}",
        flush=True,
    )
    if period_ok is not None:
        print(
            f"  troca periodo: {'OK' if period_ok.get('ok') else 'FAIL'}",
            flush=True,
        )
    if hist_base_ok is not None:
        print(
            f"  troca base hist: {'OK' if hist_base_ok.get('ok') else 'FAIL'}  "
            f"keys={hist_base_ok.get('cache_key_count')}",
            flush=True,
        )
    if mes_ate_hoje_ok is not None:
        print(
            f"  mes atual ate hoje: {'OK' if mes_ate_hoje_ok.get('ok') else 'FAIL'}  "
            f"eff={mes_ate_hoje_ok.get('eff_on', '')}",
            flush=True,
        )
    if same_interval_ok is not None:
        print(
            f"  same_interval bm: {'OK' if same_interval_ok.get('ok') else 'FAIL'}  "
            f"ag={same_interval_ok.get('ag_on')}",
            flush=True,
        )

    return {
        "scenario": label,
        "progressive_auto": auto,
        "warm_auto": warm,
        "progressive_manual": manual,
        "classic": classic,
        "period_change_validation": period_ok,
        "hist_base_switch_validation": hist_base_ok,
        "mes_atual_ate_hoje_validation": mes_ate_hoje_ok,
        "same_interval_benchmark_validation": same_interval_ok,
    }


def main() -> None:
    print("Checkpoint CP9.2 - Progressive auto + ordem visual", flush=True)
    print(
        f"Referência: {HOJE.isoformat()}  |  "
        f"FUNIL_PROGRESSIVE_BENCHMARK_MODE=auto (default)",
        flush=True,
    )

    results = [
        run_scenario(label, ini, fim) for label, (ini, fim) in SCENARIOS.items()
    ]

    print(f"\n{'#' * 72}", flush=True)
    print("# RESUMO CP9.2.1", flush=True)
    print(f"{'#' * 72}", flush=True)
    hdr = (
        f"{'cenario':<18} {'classic':>8} {'1a dobra':>8} "
        f"{'full auto':>9} {'bm auto':>8} {'warm':>8}"
    )
    print(hdr, flush=True)
    print("-" * 72, flush=True)

    for r in results:
        cl = r["classic"]
        au = r["progressive_auto"]
        wm = r["warm_auto"]
        cl_full = cl.get("main_sections_seconds") or 0
        ff = au.get("first_fold_time") or 0
        au_full = au.get("full_page_time") or au.get("main_sections_seconds") or 0
        bm = au.get("benchmark_time") or au.get("benchmark_block") or 0
        wm_full = wm.get("main_sections_seconds") or 0
        print(
            f"{r['scenario']:<18} "
            f"{cl_full:7.2f}s {ff:7.2f}s {au_full:8.2f}s "
            f"{bm:7.2f}s {wm_full:7.2f}s",
            flush=True,
        )

    payload = {
        "checkpoint": "CP9.2.1-hist-cache",
        "reference_date": HOJE.isoformat(),
        "funil_progressive_load_default": "1",
        "funil_progressive_benchmark_mode_default": "auto",
        "parallel_off": True,
        "scenarios": results,
    }
    out = ROOT / "scripts" / "checkpoint_funil_progressive_load_results.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nDetalhes salvos em: {out}", flush=True)


if __name__ == "__main__":
    main()
