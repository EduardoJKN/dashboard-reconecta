"""Diagnóstico: vínculo cancelamento ↔ pós-venda. Uso:
    python scripts/diag_churn_pos_venda.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.db import get_engine

QUERIES = [
    (
        "executivas_pos_vendas — colunas",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'fdw_reconecta'
          AND table_name = 'executivas_pos_vendas'
        ORDER BY ordinal_position
        """,
    ),
    (
        "executivas_pos_vendas — cadastro",
        """
        SELECT id, nome, email, id_crm, id_clickup, ativo
        FROM fdw_reconecta.executivas_pos_vendas
        ORDER BY ativo DESC, nome
        """,
    ),
    (
        "colunas candidatas (pos/cs/respons/owner/execut/...)",
        """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE (
            LOWER(column_name) LIKE '%pos%'
            OR LOWER(column_name) LIKE '%pós%'
            OR LOWER(column_name) LIKE '%cs%'
            OR LOWER(column_name) LIKE '%sucesso%'
            OR LOWER(column_name) LIKE '%respons%'
            OR LOWER(column_name) LIKE '%owner%'
            OR LOWER(column_name) LIKE '%user%'
            OR LOWER(column_name) LIKE '%usuario%'
            OR LOWER(column_name) LIKE '%execut%'
            OR LOWER(column_name) LIKE '%atendimento%'
            OR LOWER(column_name) LIKE '%contato%'
            OR LOWER(column_name) LIKE '%id_crm%'
            OR LOWER(column_name) LIKE '%id_clickup%'
        )
        AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name, column_name
        """,
    ),
    (
        "zoho_deals — todas colunas",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'zoho_deals'
        ORDER BY ordinal_position
        """,
    ),
    (
        "zoho_activities — todas colunas",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'zoho_activities'
        ORDER BY ordinal_position
        """,
    ),
    (
        "fdw controle_notificacao_vendas — colunas",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'fdw_reconecta'
          AND table_name = 'controle_notificacao_vendas'
        ORDER BY ordinal_position
        """,
    ),
    (
        "cancelados — activities no último ano (amostra status)",
        """
        SELECT status_reuniao, activity_type, COUNT(*) AS n
        FROM zoho_activities
        WHERE status_reuniao IN ('Cancelada', 'Cancelado')
          AND created_time >= CURRENT_DATE - INTERVAL '365 days'
        GROUP BY 1, 2
        ORDER BY n DESC
        LIMIT 20
        """,
    ),
    (
        "controle_notificacao — cs_nome preenchido",
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE cs_nome IS NOT NULL AND btrim(cs_nome) <> '') AS com_cs,
            COUNT(*) FILTER (WHERE id_negocio_pos IS NOT NULL AND btrim(id_negocio_pos::text) <> '') AS com_id_pos
        FROM fdw_reconecta.controle_notificacao_vendas
        """,
    ),
    (
        "controle_notificacao — amostra cs_nome",
        """
        SELECT cs_nome, id_negocio_pos, email, id_negocio, dt_criacao
        FROM fdw_reconecta.controle_notificacao_vendas
        WHERE cs_nome IS NOT NULL AND btrim(cs_nome) <> ''
        ORDER BY dt_criacao DESC
        LIMIT 15
        """,
    ),
    (
        "zoho_activities.owner — match cadastro pos (amostra nomes distintos)",
        """
        SELECT DISTINCT NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') AS owner_name
        FROM zoho_activities a
        JOIN zoho_users u ON u.id::text = a.owner::text
        WHERE a.created_time >= CURRENT_DATE - INTERVAL '180 days'
          AND a.owner IS NOT NULL
        ORDER BY 1
        LIMIT 40
        """,
    ),
    (
        "zoho_activities — activity_type distintos (180d)",
        """
        SELECT activity_type, COUNT(*) AS n
        FROM zoho_activities
        WHERE created_time >= CURRENT_DATE - INTERVAL '180 days'
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 30
        """,
    ),
    (
        "fdw_reconecta — foreign tables disponíveis",
        """
        SELECT foreign_table_name
        FROM information_schema.foreign_tables
        WHERE foreign_table_schema = 'fdw_reconecta'
        ORDER BY 1
        """,
    ),
    (
        "zoho_acompanhamentos — colunas",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'zoho_acompanhamentos'
        ORDER BY ordinal_position
        """,
    ),
    (
        "cancelados Consulta — deal fields (executiva_contas, status_posvendas)",
        """
        WITH canc AS (
            SELECT DISTINCT
                CASE
                    WHEN a.what_id ~ '^\\{.*\\}$' THEN (a.what_id::json ->> 'id')::text
                    ELSE regexp_replace(COALESCE(a.what_id, ''), '\\D', '', 'g')
                END AS deal_id
            FROM zoho_activities a
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
              AND a.activity_type = 'Consulta'
              AND COALESCE(a.start_datetime, a.created_time) >= CURRENT_DATE - INTERVAL '180 days'
        )
        SELECT
            COUNT(*) AS deals_cancelados,
            COUNT(*) FILTER (WHERE d.executiva_contas IS NOT NULL AND btrim(d.executiva_contas) <> '') AS com_executiva_contas,
            COUNT(*) FILTER (WHERE d.status_posvendas IS NOT NULL AND btrim(d.status_posvendas) <> '') AS com_status_posvendas,
            COUNT(*) FILTER (WHERE d.owner IS NOT NULL AND btrim(d.owner) <> '') AS com_owner_deal
        FROM canc c
        LEFT JOIN zoho_deals d ON d.id = c.deal_id
        """,
    ),
    (
        "amostra cancelados — deal + closer + executiva_contas",
        """
        WITH canc AS (
            SELECT
                a.id::text AS activity_id,
                CASE
                    WHEN a.what_id ~ '^\\{.*\\}$' THEN (a.what_id::json ->> 'id')::text
                    ELSE regexp_replace(COALESCE(a.what_id, ''), '\\D', '', 'g')
                END AS deal_id,
                COALESCE(a.start_datetime, a.created_time) AS dt_cancel,
                NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') AS owner_activity
            FROM zoho_activities a
            LEFT JOIN zoho_users u ON u.id::text = a.owner::text
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
              AND a.activity_type = 'Consulta'
              AND COALESCE(a.start_datetime, a.created_time) >= CURRENT_DATE - INTERVAL '90 days'
        )
        SELECT
            c.deal_id,
            d.email,
            d.stage,
            d.executiva_contas,
            d.status_posvendas,
            c.owner_activity,
            NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS closer_name,
            c.dt_cancel
        FROM canc c
        LEFT JOIN zoho_deals d ON d.id = c.deal_id
        LEFT JOIN zoho_users uc ON uc.id::text = d.executiva_vendas::text
        ORDER BY c.dt_cancel DESC
        LIMIT 12
        """,
    ),
    (
        "atividades pós (Onboarding/Acompanhamento) por deal cancelado",
        """
        WITH canc_deals AS (
            SELECT DISTINCT
                CASE
                    WHEN a.what_id ~ '^\\{.*\\}$' THEN (a.what_id::json ->> 'id')::text
                    ELSE regexp_replace(COALESCE(a.what_id, ''), '\\D', '', 'g')
                END AS deal_id
            FROM zoho_activities a
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
              AND a.activity_type = 'Consulta'
              AND COALESCE(a.start_datetime, a.created_time) >= CURRENT_DATE - INTERVAL '180 days'
        ),
        pos_acts AS (
            SELECT
                CASE
                    WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
                    ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g')
                END AS deal_id,
                za.activity_type,
                NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') AS owner_name
            FROM zoho_activities za
            LEFT JOIN zoho_users u ON u.id::text = za.owner::text
            WHERE za.activity_type IN ('Onboarding', 'Acompanhamento', 'Onboarding-mastermid-reconecta', 'Call-asc')
        )
        SELECT
            COUNT(DISTINCT cd.deal_id) AS deals_cancelados,
            COUNT(DISTINCT cd.deal_id) FILTER (
                WHERE EXISTS (SELECT 1 FROM pos_acts p WHERE p.deal_id = cd.deal_id)
            ) AS com_atividade_pos,
            COUNT(DISTINCT cd.deal_id) FILTER (
                WHERE EXISTS (
                    SELECT 1 FROM pos_acts p
                    WHERE p.deal_id = cd.deal_id
                      AND p.owner_name IS NOT NULL
                )
            ) AS com_owner_pos
        FROM canc_deals cd
        """,
    ),
    (
        "zoho_acompanhamentos — volume e link deal",
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE executiva_contas_name IS NOT NULL AND btrim(executiva_contas_name) <> '') AS com_exec_contas
        FROM zoho_acompanhamentos
        """,
    ),
    (
        "cs_nome distintos em notificacoes",
        """
        SELECT DISTINCT n.cs_nome
        FROM fdw_reconecta.controle_notificacao_vendas n
        WHERE n.cs_nome IS NOT NULL AND btrim(n.cs_nome) <> ''
        ORDER BY 1
        LIMIT 30
        """,
    ),
    (
        "deals Ganho com status_posvendas / executiva_contas preenchido",
        """
        SELECT
            COUNT(*) AS ganhos_total,
            COUNT(*) FILTER (WHERE executiva_contas IS NOT NULL AND btrim(executiva_contas) <> '') AS com_exec_contas,
            COUNT(*) FILTER (WHERE status_posvendas IS NOT NULL AND btrim(status_posvendas) <> '') AS com_status_pos
        FROM zoho_deals
        WHERE stage IN ('Ganho', 'Fechado Ganho')
          AND tipo_venda = 'Novo cliente'
          AND data_hora_compra >= CURRENT_DATE - INTERVAL '365 days'
        """,
    ),
    (
        "stages distintos em deals (amostra churn?)",
        """
        SELECT stage, COUNT(*) AS n
        FROM zoho_deals
        WHERE modified_time >= CURRENT_DATE - INTERVAL '365 days'
          AND (LOWER(stage) LIKE '%cancel%' OR LOWER(stage) LIKE '%churn%'
               OR LOWER(stage) LIKE '%perd%' OR LOWER(motivo_perda) LIKE '%cancel%')
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 25
        """,
    ),
    (
        "cancelados consulta — overlap email com notificacao (cs_nome)",
        """
        WITH canc AS (
            SELECT DISTINCT lower(btrim(d.email)) AS email_norm
            FROM zoho_activities a
            JOIN zoho_deals d ON d.id = CASE
                WHEN a.what_id ~ '^\\{.*\\}$' THEN (a.what_id::json ->> 'id')::text
                ELSE regexp_replace(COALESCE(a.what_id, ''), '\\D', '', 'g')
            END
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
              AND a.activity_type = 'Consulta'
              AND COALESCE(a.start_datetime, a.created_time) >= CURRENT_DATE - INTERVAL '180 days'
              AND d.email IS NOT NULL AND btrim(d.email) <> ''
        )
        SELECT
            (SELECT COUNT(*) FROM canc) AS emails_cancelados,
            (SELECT COUNT(*) FROM canc c
             JOIN fdw_reconecta.controle_notificacao_vendas n
               ON lower(btrim(n.email)) = c.email_norm) AS com_notificacao,
            (SELECT COUNT(*) FROM canc c
             JOIN fdw_reconecta.controle_notificacao_vendas n
               ON lower(btrim(n.email)) = c.email_norm
              AND n.cs_nome IS NOT NULL AND btrim(n.cs_nome) <> '') AS com_cs_nome
        """,
    ),
    (
        "última atividade pós antes cancel — 5 exemplos com owner",
        """
        WITH canc AS (
            SELECT
                CASE
                    WHEN a.what_id ~ '^\\{.*\\}$' THEN (a.what_id::json ->> 'id')::text
                    ELSE regexp_replace(COALESCE(a.what_id, ''), '\\D', '', 'g')
                END AS deal_id,
                MAX(COALESCE(a.start_datetime, a.created_time)) AS dt_cancel
            FROM zoho_activities a
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
              AND a.activity_type = 'Consulta'
            GROUP BY 1
        ),
        pos AS (
            SELECT
                CASE
                    WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
                    ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g')
                END AS deal_id,
                za.activity_type,
                COALESCE(za.start_datetime, za.created_time) AS dt_act,
                NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') AS owner_name,
                ROW_NUMBER() OVER (
                    PARTITION BY CASE
                        WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
                        ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g')
                    END
                    ORDER BY COALESCE(za.start_datetime, za.created_time) DESC
                ) AS rn
            FROM zoho_activities za
            LEFT JOIN zoho_users u ON u.id::text = za.owner::text
            WHERE za.activity_type IN ('Onboarding', 'Acompanhamento', 'Onboarding-mastermid-reconecta', 'Call-asc')
        )
        SELECT c.deal_id, c.dt_cancel, p.activity_type, p.dt_act, p.owner_name
        FROM canc c
        JOIN pos p ON p.deal_id = c.deal_id AND p.dt_act < c.dt_cancel AND p.rn = 1
        LIMIT 5
        """,
    ),
    (
        "acompanhamentos — amostra executiva_contas_name",
        """
        SELECT executiva_contas_name, owner_name, cliente_name, created_time
        FROM zoho_acompanhamentos
        ORDER BY created_time DESC
        LIMIT 8
        """,
    ),
    (
        "deals stage=Churn — campos pós e amostra",
        """
        SELECT
            COUNT(*) AS total_churn,
            COUNT(*) FILTER (WHERE executiva_contas IS NOT NULL AND btrim(executiva_contas) <> '') AS com_exec_contas,
            COUNT(*) FILTER (WHERE executiva_vendas IS NOT NULL AND btrim(executiva_vendas) <> '') AS com_closer_id,
            COUNT(*) FILTER (WHERE motivo_perda IS NOT NULL AND btrim(motivo_perda) <> '') AS com_motivo
        FROM zoho_deals
        WHERE stage = 'Churn'
        """,
    ),
    (
        "deals Churn — amostra 8 linhas",
        """
        SELECT d.id, d.email, d.stage, d.executiva_contas, d.executiva_vendas,
               d.motivo_perda, d.data_hora_compra, d.stage_modified_time,
               NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS closer_name
        FROM zoho_deals d
        LEFT JOIN zoho_users uc ON uc.id::text = d.executiva_vendas::text
        WHERE d.stage = 'Churn'
        ORDER BY d.stage_modified_time DESC NULLS LAST
        LIMIT 8
        """,
    ),
    (
        "Churn deals — atividades pós (owner)",
        """
        WITH churn AS (SELECT id::text AS deal_id FROM zoho_deals WHERE stage = 'Churn')
        SELECT
            COUNT(DISTINCT c.deal_id) AS deals_churn,
            COUNT(DISTINCT c.deal_id) FILTER (
                WHERE EXISTS (
                    SELECT 1 FROM zoho_activities za
                    LEFT JOIN zoho_users u ON u.id::text = za.owner::text
                    WHERE (CASE
                        WHEN za.what_id ~ '^\\{.*\\}$' THEN (za.what_id::json ->> 'id')::text
                        ELSE regexp_replace(COALESCE(za.what_id, ''), '\\D', '', 'g')
                    END) = c.deal_id
                      AND za.activity_type IN ('Onboarding', 'Acompanhamento',
                          'Onboarding-mastermid-reconecta', 'Call-asc')
                )
            ) AS com_atividade_pos
        FROM churn c
        """,
    ),
    (
        "Churn — overlap notificacao cs_nome",
        """
        SELECT
            COUNT(*) AS deals_churn,
            COUNT(*) FILTER (WHERE n.id IS NOT NULL) AS com_notif,
            COUNT(*) FILTER (WHERE n.cs_nome IS NOT NULL AND btrim(n.cs_nome) <> '') AS com_cs
        FROM zoho_deals d
        LEFT JOIN fdw_reconecta.controle_notificacao_vendas n
          ON lower(btrim(n.email)) = lower(btrim(d.email))
        WHERE d.stage = 'Churn' AND d.email IS NOT NULL AND btrim(d.email) <> ''
        """,
    ),
]


def main() -> None:
    eng = get_engine()
    for title, sql in QUERIES:
        print("=" * 80)
        print(title)
        print("=" * 80)
        with eng.connect() as conn:
            try:
                rows = conn.execute(text(sql)).fetchall()
                if not rows:
                    print("(vazio)\n")
                    continue
                cols = rows[0]._fields if hasattr(rows[0], "_fields") else rows[0].keys()
                print(" | ".join(str(c) for c in cols))
                print("-" * 60)
                for r in rows[:200]:
                    print(" | ".join(str(v)[:60] for v in r))
                if len(rows) > 200:
                    print(f"... (+{len(rows) - 200} linhas)")
            except Exception as e:
                print(f"ERRO: {e}")
            print()


if __name__ == "__main__":
    main()
