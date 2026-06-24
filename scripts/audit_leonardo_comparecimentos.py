"""Auditoria pontual: Leonardo Melo Patriota — comparecimentos semana atual."""
from __future__ import annotations

from datetime import date, timedelta

from src.db import run_sql

today = date(2026, 6, 24)
data_ini = today - timedelta(days=today.weekday())
data_fim = today
leonardo_id = "6501842000086282001"

print(f"Período Semana atual: {data_ini} a {data_fim}\n")

# View definition (live)
defn = run_sql(
    "SELECT pg_get_viewdef('bi.vw_dashboard_comercial_executivas_rw'::regclass, true) AS def"
).iloc[0]["def"]
start = defn.find("atividades AS")
if start >= 0:
    print("--- view: CTE atividades (trecho) ---")
    print(defn[start : start + 3200])
    print()

params = {"data_ini": data_ini, "data_fim": data_fim, "leonardo_id": leonardo_id}

q_deals_stage = """
SELECT
  d.id,
  d.deal_name,
  d.email,
  d.stage,
  d.triagem,
  d.created_at::date AS created_at,
  d.modified_time::date AS modified_at,
  d.stage_modified_time::date AS stage_modified,
  d.compromisso_concluido::date AS compromisso_concluido,
  d.ultima_reuniao_agendada::date AS ultima_reuniao
FROM zoho_deals d
WHERE d.executiva_vendas::text = :leonardo_id
  AND (
    d.stage_modified_time::date BETWEEN :data_ini AND :data_fim
    OR d.compromisso_concluido::date BETWEEN :data_ini AND :data_fim
    OR d.ultima_reuniao_agendada::date BETWEEN :data_ini AND :data_fim
    OR d.created_at::date BETWEEN :data_ini AND :data_fim
  )
  AND (
    d.stage ILIKE '%conclu%'
    OR d.stage ILIKE '%reuni%'
    OR d.triagem ILIKE '%conclu%'
    OR d.compromisso_concluido IS NOT NULL
  )
ORDER BY COALESCE(d.stage_modified_time, d.modified_time) DESC
"""
print("=== Deals CRM (stage/datas na semana, closer=Leonardo) ===")
df = run_sql(q_deals_stage, params)
print(f"Rows: {len(df)}")
if not df.empty:
    cols = [
        "deal_name", "email", "stage", "triagem",
        "created_at", "stage_modified", "compromisso_concluido", "ultima_reuniao",
    ]
    print(df[cols].to_string(index=False))

q_stage_count = """
SELECT stage, COUNT(*)::int AS n
FROM zoho_deals d
WHERE d.executiva_vendas::text = :leonardo_id
  AND d.stage_modified_time::date BETWEEN :data_ini AND :data_fim
GROUP BY stage ORDER BY n DESC
"""
print("\n=== Deals stage_modified na semana por stage ===")
print(run_sql(q_stage_count, params).to_string(index=False))

q_mismatch = """
SELECT
  za.id AS activity_id,
  za.start_datetime::date AS data_reuniao,
  za.status_reuniao,
  d.stage AS deal_stage,
  d.deal_name,
  d.email
FROM zoho_activities za
JOIN zoho_deals d ON d.id::text = CASE
    WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
    ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g')
END
WHERE za.activity_type IN ('Consulta', 'Indicação')
  AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
  AND d.executiva_vendas::text = :leonardo_id
  AND d.stage ILIKE '%Reuni%Conclu%'
  AND za.status_reuniao NOT IN ('Concluída', 'Concluído', 'Concluida', 'Concluido')
"""
print("\n=== Mismatch: deal Reunião Concluída mas activity status != Concluída ===")
print(run_sql(q_mismatch, params).to_string(index=False))

# Excluded from comparecimento but might count in CRM
q_excluded = """
SELECT
  za.id AS activity_id,
  za.start_datetime::date AS data_reuniao,
  za.status_reuniao,
  d.stage AS deal_stage,
  d.deal_name,
  d.email,
  d.created_at::date AS deal_created_at,
  CASE
    WHEN za.status_reuniao IS NULL THEN 'status_reuniao NULL'
    WHEN lower(btrim(za.status_reuniao)) = 'vencida' THEN 'Vencida (excluída de agendamentos na regra nova)'
    WHEN za.status_reuniao IN ('Agendada', 'Agendado') THEN 'Agendada (reunião futura ou não marcada concluída)'
    WHEN za.status_reuniao IN ('Cancelada', 'Cancelado') THEN 'Cancelada'
    WHEN za.status_reuniao IN ('Concluída', 'Concluído') THEN 'CONTA no dashboard'
    ELSE 'Outro status: ' || za.status_reuniao
  END AS motivo_dashboard
FROM zoho_activities za
JOIN zoho_deals d ON d.id::text = CASE
    WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
    ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g')
END
WHERE za.activity_type IN ('Consulta', 'Indicação')
  AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
  AND za.owner::text = :leonardo_id
ORDER BY za.start_datetime
"""
print("\n=== Todas activities Leonardo (owner) — flags dashboard ===")
df_ex = run_sql(q_excluded, params)
print(df_ex.to_string(index=False))
print("\nContagem por motivo:")
print(df_ex["motivo_dashboard"].value_counts().to_string())

# Simula pipeline Python do dashboard
from src.repositories import get_executivas
from src.transforms import executivas_ranking, executivas_filtrar_time_oficial, executivas_kpis
from src.repositories import get_executivas_oficiais

df_all = get_executivas(data_ini, data_fim)
df_f = df_all[df_all["executiva"].str.contains("Leonardo Melo Patriota", case=False, na=False)]
print("\n=== Pipeline Python (get_executivas filtrado Leonardo) ===")
print(df_f[["data_ref", "oportunidades", "agendamentos", "comparecimentos", "vendas"]].to_string(index=False))
k = executivas_kpis(df_f)
print("\nKPIs agregados:", {x: int(k.get(x, 0) or 0) for x in ["oportunidades", "agendamentos", "comparecimentos", "vendas"]})
try:
    oficiais = get_executivas_oficiais()
    df_filtrado = executivas_filtrar_time_oficial(df_all, oficiais)
    rank = executivas_ranking(df_filtrado)
    leo = rank[rank["executiva"].str.contains("Leonardo Melo Patriota", case=False, na=False)]
    print("\n=== Ranking (time oficial ativo) ===")
    if not leo.empty:
        print(leo[["executiva", "oportunidades", "agendamentos", "comparecimentos", "vendas", "pct_comparecimento", "pct_conversao", "pct_vendas"]].to_string(index=False))
except Exception as e:
    print("Ranking oficial falhou:", e)

# CRM lens: deals com ultima_reuniao na semana
q_crm = """
SELECT d.deal_name, d.email, d.stage, d.ultima_reuniao_agendada::date AS ultima_reuniao,
       EXISTS (
         SELECT 1 FROM zoho_activities za
         WHERE za.activity_type IN ('Consulta', 'Indicação')
           AND za.owner::text = :leonardo_id
           AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
           AND za.status_reuniao IN ('Concluída', 'Concluído')
           AND (CASE WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
                     ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g') END) = d.id::text
       ) AS tem_activity_concluida_semana
FROM zoho_deals d
WHERE d.executiva_vendas::text = :leonardo_id
  AND d.ultima_reuniao_agendada::date BETWEEN :data_ini AND :data_fim
ORDER BY d.ultima_reuniao_agendada
"""
print("\n=== Deals com ultima_reuniao_agendada na semana (visão CRM comum) ===")
print(run_sql(q_crm, params).to_string(index=False))
