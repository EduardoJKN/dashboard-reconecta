#!/usr/bin/env python
"""Auditoria CRM × dashboard — Time de Vendas → Executivas & Times.

Identifica, por closer e período, reuniões que podem divergir entre CRM e
o ranking atual (bi.vw_dashboard_comercial_executivas_rw).

Uso:
  python scripts/audit_executivas_crm_dashboard.py
  python scripts/audit_executivas_crm_dashboard.py --preset semana_atual
  python scripts/audit_executivas_crm_dashboard.py --data-ini 2026-06-01 --data-fim 2026-06-24
  python scripts/audit_executivas_crm_dashboard.py --preset mes_atual --csv out/auditoria.csv
  python scripts/audit_executivas_crm_dashboard.py --closer "Leonardo Melo Patriota"

Somente leitura — não altera métricas do dashboard.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.db import run_sql_file  # noqa: E402

HOJE = date.today()

PRESETS: dict[str, tuple[date, date]] = {
    "semana_atual": (HOJE - timedelta(days=HOJE.weekday()), HOJE),
    "mes_atual": (HOJE.replace(day=1), HOJE),
    "ultimos_7_dias": (HOJE - timedelta(days=6), HOJE),
    "ultimos_30_dias": (HOJE - timedelta(days=29), HOJE),
}


def _bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return df[col].fillna(False).astype(bool)


def _impacto_por_executiva(df: pd.DataFrame, col_exec: str) -> pd.DataFrame:
    """Agrega impacto por coluna de executiva (owner ou closer do deal)."""
    if df.empty:
        return pd.DataFrame()

    work = df.copy()
    status_lc = work["status_reuniao"].astype(str).str.lower().str.strip()
    stage_lc = work["deal_stage"].astype(str).str.lower()

    work["_divergente"] = (
        ~_bool_col(work, "flag_comparecimento_dashboard")
        & work["motivos_divergencia"].notna()
        & (work["motivos_divergencia"].astype(str).str.len() > 0)
    )
    work["_agendada_nao"] = (
        ~_bool_col(work, "flag_comparecimento_dashboard")
        & status_lc.isin(["agendada", "agendado"])
    )
    work["_vencida"] = status_lc == "vencida"
    work["_cancelada"] = status_lc.isin(["cancelada", "cancelado"])
    work["_deal_reuniao_nao_act"] = (
        ~_bool_col(work, "flag_comparecimento_dashboard")
        & stage_lc.str.contains("reuni", na=False)
        & stage_lc.str.contains("conclu", na=False)
    )
    work["_fallback_uniao"] = (
        _bool_col(work, "flag_comparecimento_fallback_stage")
        | _bool_col(work, "flag_comparecimento_fallback_triagem")
    )

    g = work.groupby(col_exec, dropna=False)
    out = pd.DataFrame({
        "activities_periodo": g.size(),
        "agendamentos_dashboard": g["flag_agendamento_dashboard"].sum(),
        "comparecimentos_dashboard": g["flag_comparecimento_dashboard"].sum(),
        "vendas_deal_periodo": g["flag_venda_dashboard"].sum(),
        "divergentes_crm": g["_divergente"].sum(),
        "extra_se_fallback_stage": g["flag_comparecimento_fallback_stage"].sum(),
        "extra_se_fallback_triagem": g["flag_comparecimento_fallback_triagem"].sum(),
        "extra_se_fallback_stage_ou_triagem": g["_fallback_uniao"].sum(),
        "closer_owner_divergente": g["flag_closer_owner_divergente"].sum(),
        "agendada_nao_concluida": g["_agendada_nao"].sum(),
        "vencida": g["_vencida"].sum(),
        "cancelada": g["_cancelada"].sum(),
        "deal_reuniao_concluida_activity_nao": g["_deal_reuniao_nao_act"].sum(),
    })
    out["comparecimentos_se_fallback_stage"] = (
        out["comparecimentos_dashboard"] + out["extra_se_fallback_stage"]
    )
    out["comparecimentos_se_fallback_triagem"] = (
        out["comparecimentos_dashboard"] + out["extra_se_fallback_triagem"]
    )
    out["comparecimentos_se_fallback_uniao"] = (
        out["comparecimentos_dashboard"] + out["extra_se_fallback_stage_ou_triagem"]
    )
    out["delta_fallback_uniao"] = out["extra_se_fallback_stage_ou_triagem"]
    return out.sort_values("delta_fallback_uniao", ascending=False)


def _print_divergentes(df: pd.DataFrame, limit: int = 25) -> None:
  cols = [
      "data_reuniao", "closer_deal", "owner_activity", "nome_lead", "email",
      "deal_stage", "triagem", "status_reuniao",
      "flag_comparecimento_dashboard",
      "flag_comparecimento_fallback_stage",
      "flag_comparecimento_fallback_triagem",
      "motivos_divergencia",
  ]
  cols = [c for c in cols if c in df.columns]
  mask = (
      df["motivos_divergencia"].notna()
      & (df["motivos_divergencia"].astype(str).str.len() > 0)
  )
  div = df.loc[mask, cols].head(limit)
  if div.empty:
      print("\n(Nenhuma linha com motivos de divergência no recorte.)")
      return
  print(f"\n=== Amostra de divergências (até {limit} linhas) ===")
  print(div.to_string(index=False))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preset", choices=sorted(PRESETS), default="semana_atual")
    p.add_argument("--data-ini", type=date.fromisoformat)
    p.add_argument("--data-fim", type=date.fromisoformat)
    p.add_argument("--closer", help="Filtra por nome (ILIKE) em closer_deal ou owner_activity")
    p.add_argument("--csv", type=Path, help="Exporta detalhe completo para CSV")
    p.add_argument("--limit-sample", type=int, default=25)
    args = p.parse_args()

    if args.data_ini and args.data_fim:
        data_ini, data_fim = args.data_ini, args.data_fim
    else:
        data_ini, data_fim = PRESETS[args.preset]

    print(f"Auditoria Executivas & Times — {data_ini} a {data_fim}")
    print("(regras atuais do dashboard — sem alteração de métrica)\n")

    df = run_sql_file(
        "executivas_auditoria_crm_dashboard.sql",
        {"data_ini": data_ini, "data_fim": data_fim},
    )

    if args.closer:
        pat = args.closer.lower()
        df = df[
            df["closer_deal"].astype(str).str.lower().str.contains(pat, na=False)
            | df["owner_activity"].astype(str).str.lower().str.contains(pat, na=False)
        ]

    print(f"Total de activities no período: {len(df)}")

    if df.empty:
        return 0

    # Totais globais
    tot = {
        "agendamentos_dashboard": int(_bool_col(df, "flag_agendamento_dashboard").sum()),
        "comparecimentos_dashboard": int(_bool_col(df, "flag_comparecimento_dashboard").sum()),
        "extra_fallback_stage": int(_bool_col(df, "flag_comparecimento_fallback_stage").sum()),
        "extra_fallback_triagem": int(_bool_col(df, "flag_comparecimento_fallback_triagem").sum()),
        "extra_fallback_uniao": int(
            (_bool_col(df, "flag_comparecimento_fallback_stage")
             | _bool_col(df, "flag_comparecimento_fallback_triagem")).sum()
        ),
        "closer_owner_divergente": int(_bool_col(df, "flag_closer_owner_divergente").sum()),
    }
    tot["comparecimentos_se_fallback_uniao"] = (
        tot["comparecimentos_dashboard"] + tot["extra_fallback_uniao"]
    )
    print("\n=== Totais globais (activities) ===")
    for k, v in tot.items():
        print(f"  {k}: {v}")

    print("\n=== Impacto por closer do DEAL (visão CRM) ===")
    by_deal = _impacto_por_executiva(df, "closer_deal")
    print(by_deal.to_string())

    print("\n=== Impacto por OWNER da activity (atribuição do ranking/dashboard) ===")
    by_owner = _impacto_por_executiva(df, "owner_activity")
    print(by_owner.to_string())

    # Closers com maior delta potencial
    top = by_deal[by_deal["delta_fallback_uniao"] > 0].head(10)
    if not top.empty:
        print("\n=== Top closers (deal) — ganho potencial com fallback stage/triagem ===")
        print(top[["comparecimentos_dashboard", "extra_se_fallback_stage_ou_triagem",
                   "comparecimentos_se_fallback_uniao", "agendada_nao_concluida",
                   "deal_reuniao_concluida_activity_nao"]].to_string())

    _print_divergentes(df, limit=args.limit_sample)

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\nCSV gravado: {args.csv.resolve()}")

    print(
        "\n--- Nota sobre colunas do ranking ---\n"
        "  oportunidades   = deals criados no período (created_at)\n"
        "  agendamentos    = reuniões no período (start_datetime), líquido de Vencida\n"
        "  comparecimentos = subset com status_reuniao Concluída/Concluído\n"
        "  O ranking atribui agend./comparec. pelo OWNER da activity, não pelo closer do deal.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
