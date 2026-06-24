#!/usr/bin/env python
"""Cruza auditoria CRM×dashboard com amostra Leidianne (comparecimentos).

Somente leitura — não altera métricas.

Uso:
  python scripts/audit_leidianne_comparecimentos.py
  python scripts/audit_leidianne_comparecimentos.py --csv-dir out
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

from src.db import run_sql, run_sql_file  # noqa: E402

HOJE = date.today()
DATA_INI = HOJE - timedelta(days=HOJE.weekday())
DATA_FIM = HOJE

# Comparecimentos esperados — amostra Leidianne (semana atual)
LISTA_LEIDIANNE: dict[str, int] = {
    "Stefany Campinas": 10,
    "Hawinne Cristina de Oliveira Freitas": 8,
    "Leandro Alves": 6,
    "Andrezza Ayuso Serpa": 4,
    "Nathan Carloto": 4,
    "Leonardo Melo Patriota": 4,
}

# Os 3 e-mails que fecham exatamente Lista 36 vs Dash 33 (ver relatório).
EMAILS_LISTA_AGENDADA_EXTRA = frozenset({
    "drabellagiestetica@gmail.com",   # Hawinne +1
    "andressabrunhara@gmail.com",     # Leonardo +1
    "mariana.scestari@gmail.com",     # Leonardo +1
})


def _norm_name(s: str) -> str:
    return str(s or "").strip().lower()


def _match_canonical(name: str) -> str | None:
    n = _norm_name(name)
    for canon in LISTA_LEIDIANNE:
        if canon.split()[0].lower() in n:
            return canon
    return None


def _bool(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _fallback_label(row: pd.Series) -> str:
    parts: list[str] = []
    if row.get("flag_comparecimento_fallback_stage"):
        parts.append("fallback_stage (deal Reunião Concluída)")
    if row.get("flag_comparecimento_fallback_triagem"):
        parts.append("fallback_triagem (triagem Concluída/Lead qualificado)")
    email = str(row.get("email") or "").lower()
    if email in EMAILS_LISTA_AGENDADA_EXTRA:
        parts.append("lista_agendada_extra (Agendada na amostra Leidianne)")
    if not parts:
        return ""
    return "; ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=ROOT / "out",
        help="Diretório para CSVs (default: dashboard_py/out)",
    )
    args = parser.parse_args()
    args.csv_dir.mkdir(parents=True, exist_ok=True)

    print(f"Semana atual: {DATA_INI} a {DATA_FIM}\n")

    df = run_sql_file(
        "executivas_auditoria_crm_dashboard.sql",
        {"data_ini": DATA_INI, "data_fim": DATA_FIM},
    )
    df["canon_owner"] = df["owner_activity"].map(_match_canonical)

    # --- Tabela comparativa ---
    rows: list[dict] = []
    for canon, lista_n in LISTA_LEIDIANNE.items():
        sub = df[df["canon_owner"] == canon]
        dash = int(_bool(sub["flag_comparecimento_dashboard"]).sum())
        fb_stage = int(_bool(sub["flag_comparecimento_fallback_stage"]).sum())
        fb_tri = int(_bool(sub["flag_comparecimento_fallback_triagem"]).sum())
        fb_uniao = int(
            (_bool(sub["flag_comparecimento_fallback_stage"])
             | _bool(sub["flag_comparecimento_fallback_triagem"])).sum()
        )
        comp_fb_stage = dash + fb_stage
        comp_fb_tri = dash + fb_tri
        comp_fb_uniao = dash + fb_uniao

        # Regra que reproduz exatamente a amostra (diagnóstico, não produção)
        ag = sub["status_reuniao"].astype(str).str.lower().str.strip().isin(
            ["agendada", "agendado"]
        )
        lista_rule = _bool(sub["flag_comparecimento_dashboard"]) | (
            ag & sub["email"].astype(str).str.lower().isin(EMAILS_LISTA_AGENDADA_EXTRA)
        )
        comp_lista_rule = int(lista_rule.sum())

        rows.append({
            "closer": canon,
            "comparecimentos_dashboard_atual": dash,
            "comparecimentos_lista_Leidianne": lista_n,
            "delta_lista_vs_dash": lista_n - dash,
            "comparecimentos_se_fallback_stage": comp_fb_stage,
            "comparecimentos_se_fallback_triagem": comp_fb_tri,
            "comparecimentos_se_fallback_uniao": comp_fb_uniao,
            "delta_fallback_vs_lista": comp_fb_uniao - lista_n,
            "comparecimentos_regra_lista_exata": comp_lista_rule,
            "delta_regra_lista_exata": comp_lista_rule - lista_n,
        })

    cmp = pd.DataFrame(rows).sort_values("closer")
    print("=== Tabela comparativa (owner activity = atribuição dashboard) ===\n")
    print(cmp.to_string(index=False))
    print(
        f"\nTotais: dash={cmp['comparecimentos_dashboard_atual'].sum()} "
        f"lista={cmp['comparecimentos_lista_Leidianne'].sum()} "
        f"delta={cmp['delta_lista_vs_dash'].sum()}"
    )
    print(
        f"Fallback uniao: {cmp['comparecimentos_se_fallback_uniao'].sum()} "
        f"(delta vs lista: {cmp['delta_fallback_vs_lista'].sum()})"
    )
    print(
        f"Regra lista exata (Concluída + 3 Agendada): "
        f"{cmp['comparecimentos_regra_lista_exata'].sum()}"
    )

    cmp_path = args.csv_dir / "comparativo_leidianne_semana_atual.csv"
    cmp.to_csv(cmp_path, index=False, encoding="utf-8-sig")

    # --- Candidatos Hawinne +1 e Leonardo +2 ---
    targets = {
        "Hawinne Cristina de Oliveira Freitas": 1,
        "Leonardo Melo Patriota": 2,
    }
    cand_cols = [
        "activity_id", "nome_lead", "email", "closer_deal", "owner_activity",
        "deal_stage", "triagem", "status_reuniao", "start_datetime",
        "ultima_reuniao_agendada", "compromisso_concluido", "data_hora_compra",
        "flag_comparecimento_dashboard",
        "flag_comparecimento_fallback_stage",
        "flag_comparecimento_fallback_triagem",
        "motivos_divergencia",
    ]

    candidatos: list[pd.DataFrame] = []
    print("\n=== Candidatos (não contam no dashboard; closers com delta_lista > 0) ===\n")

    for canon, need in targets.items():
        sub = df[
            (df["canon_owner"] == canon)
            & (~_bool(df["flag_comparecimento_dashboard"]))
        ].copy()
        sub["motivo_nao_conta_dashboard"] = sub["motivos_divergencia"]
        sub["qual_fallback_contaria"] = sub.apply(_fallback_label, axis=1)
        sub["fecha_lista_Leidianne"] = sub["email"].astype(str).str.lower().isin(
            EMAILS_LISTA_AGENDADA_EXTRA
        )
        print(f"--- {canon} (precisa +{need}) — {len(sub)} activities não-Concluída ---")
        cols = [c for c in cand_cols if c in sub.columns] + [
            "motivo_nao_conta_dashboard", "qual_fallback_contaria", "fecha_lista_Leidianne",
        ]
        print(sub[cols].to_string(index=False))
        print()
        candidatos.append(sub.assign(closer_alvo=canon))

    if candidatos:
        cand_df = pd.concat(candidatos, ignore_index=True)
        cand_path = args.csv_dir / "candidatos_leidianne_hawinne_leonardo.csv"
        cand_df.to_csv(cand_path, index=False, encoding="utf-8-sig")
    else:
        cand_path = None

    # --- Os 3 registros exatos ---
    exact = df[
        df["email"].astype(str).str.lower().isin(EMAILS_LISTA_AGENDADA_EXTRA)
    ].copy()
    print("=== Os 3 registros que fecham Lista 36 (Concluída + estes Agendada) ===\n")
    if not exact.empty:
        show = [
            "nome_lead", "email", "owner_activity", "deal_stage", "triagem",
            "status_reuniao", "start_datetime", "motivos_divergencia",
        ]
        print(exact[show].to_string(index=False))
    exact_path = args.csv_dir / "lista36_tres_registros_exatos.csv"
    exact.to_csv(exact_path, index=False, encoding="utf-8-sig")

    # --- Hipóteses de agrupamento ---
    print("\n=== Hipóteses de agrupamento (owner activity) ===\n")
    sample = df[df["canon_owner"].notna()].copy()
    st = sample["status_reuniao"].astype(str).str.lower().str.strip()
    stage = sample["deal_stage"].astype(str).str.lower()
    tri = sample["triagem"].astype(str).str.lower().str.strip()
    concl = _bool(sample["flag_comparecimento_dashboard"])
    ag = st.isin(["agendada", "agendado"])
    venc = st == "vencida"
    tri_concl = tri.isin(["concluída", "concluida", "lead qualificado"])

    ult = pd.to_datetime(sample["ultima_reuniao_agendada"], errors="coerce").dt.date
    comp_dt = pd.to_datetime(sample["compromisso_concluido"], errors="coerce").dt.date
    di_ts, df_ts = pd.Timestamp(DATA_INI), pd.Timestamp(DATA_FIM)

    hypotheses: list[tuple[str, pd.Series]] = [
        ("H1: status Concluída (dashboard)", concl),
        ("H2: deal stage Reunião Concluída", stage.str.contains("reuni", na=False) & stage.str.contains("conclu", na=False)),
        ("H3: triagem Concluída/Lead qualificado", tri_concl),
        ("H4: compromisso_concluido no período", comp_dt.between(DATA_INI, DATA_FIM)),
        ("H5: ultima_reuniao_agendada no período", ult.between(DATA_INI, DATA_FIM)),
        ("H6: Concluída OR fallback stage", concl | _bool(sample["flag_comparecimento_fallback_stage"])),
        ("H7: Concluída OR fallback triagem", concl | _bool(sample["flag_comparecimento_fallback_triagem"])),
        ("H8: Concluída OR fallback uniao", concl | _bool(sample["flag_comparecimento_fallback_stage"]) | _bool(sample["flag_comparecimento_fallback_triagem"])),
        ("H9: Concluída OR triagem Concluída (qualquer status)", concl | tri_concl),
        ("H10: Concluída + 3 Agendada (regra lista exata)", concl | (ag & sample["email"].astype(str).str.lower().isin(EMAILS_LISTA_AGENDADA_EXTRA))),
    ]

    hyp_rows = []
    for label, mask in hypotheses:
        g = sample.loc[mask].groupby("canon_owner").size()
        total = int(g.sum())
        mism = {
            c: int(g.get(c, 0)) - LISTA_LEIDIANNE[c]
            for c in LISTA_LEIDIANNE
            if int(g.get(c, 0)) != LISTA_LEIDIANNE[c]
        }
        hyp_rows.append({
            "hipotese": label,
            "total": total,
            "bate_lista_36": total == 36 and not mism,
            "diferencas": str(mism) if mism else "OK",
        })
        mark = " ← BATE LISTA" if total == 36 and not mism else ""
        print(f"{label}: total={total} diffs={mism or 'OK'}{mark}")

    pd.DataFrame(hyp_rows).to_csv(
        args.csv_dir / "hipoteses_agrupamento_leidianne.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --- Falsos positivos do fallback uniao ---
    fb_extra = sample[
        (_bool(sample["flag_comparecimento_fallback_stage"])
         | _bool(sample["flag_comparecimento_fallback_triagem"]))
        & (~concl)
    ]
    print("\n=== Falsos positivos do fallback stage∪triagem (não estão na lista) ===\n")
    if fb_extra.empty:
        print("(nenhum)")
    else:
        cols = ["canon_owner", "nome_lead", "email", "deal_stage", "triagem", "status_reuniao"]
        print(fb_extra[cols].to_string(index=False))

    # --- Sync / cache ---
    print("\n=== Atualizações recentes no Zoho (48h) — candidatos e Concluídas ===\n")
    recent = run_sql(
        """
        WITH acts AS (
            SELECT za.id::text AS activity_id,
                   za.start_datetime,
                   za.status_reuniao,
                   za.modified_time AS act_modified,
                   TRIM(u.first_name || ' ' || u.last_name) AS owner_name,
                   CASE WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
                        ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g') END AS deal_id
            FROM zoho_activities za
            LEFT JOIN zoho_users u ON u.id::text = za.owner::text
            WHERE za.activity_type IN ('Consulta', 'Indicação')
              AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
        )
        SELECT a.activity_id, a.start_datetime, a.status_reuniao, a.act_modified,
               d.email, d.deal_name, d.modified_time AS deal_modified, a.owner_name
        FROM acts a
        LEFT JOIN zoho_deals d ON d.id::text = a.deal_id
        WHERE a.act_modified >= NOW() - INTERVAL '48 hours'
           OR d.modified_time >= NOW() - INTERVAL '48 hours'
        ORDER BY GREATEST(a.act_modified, d.modified_time) DESC NULLS LAST
        LIMIT 40
        """,
        {"data_ini": DATA_INI, "data_fim": DATA_FIM},
    )
    if recent.empty:
        print("(sem modificações nas últimas 48h)")
    else:
        print(recent.to_string(index=False))

    print(f"\nArquivos:")
    print(f"  - {cmp_path}")
    if cand_path:
        print(f"  - {cand_path}")
    print(f"  - {exact_path}")
    print(f"  - {args.csv_dir / 'hipoteses_agrupamento_leidianne.csv'}")
    print(f"  - {args.csv_dir / 'auditoria_semana_atual.csv'} (auditoria linha a linha)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
