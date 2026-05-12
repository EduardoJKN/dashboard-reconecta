-- =============================================================================
-- Pré-vendas — agregado por SDR (regra HÍBRIDA).
-- =============================================================================
-- Atribuição de SDR (Opção C — híbrida):
--   1. `zoho_activities.prevendas` (texto, NULL → tenta fallback)
--   2. fallback: `zoho_deals.sdr_ss` resolvido via `zoho_users` (nome)
--   3. ainda NULL → "Sem SDR"
--
-- Em abr/2026 a regra reduz "Sem SDR" de 69 (12% das atividades) para 40
-- (7%) sem distorcer atribuição: o fallback só dispara quando prevendas
-- está vazio. Quando ambos preenchidos (96% dos casos com deal pareado),
-- prevendas vence — operacionalmente correto pra Pré-vendas.
--
-- Coluna `fonte_sdr` carrega a auditoria de qual caminho foi usado
-- (`activity.prevendas` / `deal.sdr_ss` / `Sem SDR`). O grão devolvido é
-- (sdr, fonte_sdr) — quando um SDR teve atividades vindo de ambas as
-- fontes, aparecem 2 linhas. O Python consolida quando precisar exibir
-- 1 linha por SDR.
--
-- Para vendas: usar a MESMA regra do card da Visão Geral:
--   - zoho_deals
--   - data_hora_compra::date
--   - stage = 'Ganho'
--   - tipo_venda = 'Novo cliente'
--   - SDR atribuído por zoho_deals.sdr_ss -> zoho_users
-- =============================================================================
WITH deal_classif AS (
    SELECT DISTINCT ON (d.id)
        d.id AS deal_id,
        l.classificado
    FROM zoho_deals d
    LEFT JOIN ext_reconecta.leads l
           ON d.id::text = l.zoho_id::text
    ORDER BY d.id, l.created_at DESC NULLS LAST
),
acts_agendamento AS (
    SELECT
        a.id                                          AS activity_id,
        a.what_id                                     AS deal_id,
        a.start_datetime::date                        AS data_ref,
        a.status_reuniao,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            TRIM(u.first_name || ' ' || u.last_name),
            'Sem SDR'
        )                                             AS sdr,
        CASE
            WHEN NULLIF(btrim(a.prevendas), '') IS NOT NULL
                THEN 'activity.prevendas'
            WHEN TRIM(u.first_name || ' ' || u.last_name) IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END                                           AS fonte_sdr
    FROM zoho_activities a
    LEFT JOIN zoho_deals d ON d.id        = a.what_id
    LEFT JOIN zoho_users u ON u.id::text  = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta','Indicação')
      AND a.status_reuniao IS NOT NULL
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
acts_criacao AS (
    SELECT
        a.id                                          AS activity_id,
        a.what_id                                     AS deal_id,
        a.created_time::date                          AS data_ref,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            TRIM(u.first_name || ' ' || u.last_name),
            'Sem SDR'
        )                                             AS sdr,
        CASE
            WHEN NULLIF(btrim(a.prevendas), '') IS NOT NULL
                THEN 'activity.prevendas'
            WHEN TRIM(u.first_name || ' ' || u.last_name) IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END                                           AS fonte_sdr
    FROM zoho_activities a
    LEFT JOIN zoho_deals d ON d.id        = a.what_id
    LEFT JOIN zoho_users u ON u.id::text  = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta','Indicação')
      AND a.status_reuniao IS NOT NULL
      AND a.created_time::date BETWEEN :data_ini AND :data_fim
),
deals_direct AS (
    SELECT
        d.id AS deal_id,
        COALESCE(
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) AS sdr,
        CASE
            WHEN NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END AS fonte_sdr,
        CASE WHEN NULLIF(btrim(d.amount), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                    REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS montante,
        CASE WHEN NULLIF(btrim(d.receita), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                    REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS receita
    FROM zoho_deals d
    LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
    WHERE d.stage = 'Ganho'
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
acts_created_agg AS (
    SELECT
        sdr, fonte_sdr,
        COUNT(*)::bigint                                         AS agendamentos_criados
    FROM acts_criacao
    GROUP BY sdr, fonte_sdr
),
acts_agg AS (
    SELECT
        a.sdr,
        a.fonte_sdr,
        COUNT(*)::bigint                                         AS agendamentos,
        COUNT(*) FILTER (
            WHERE dc.classificado = 'Atua +12'
        )::bigint                                                AS agendamentos_mais_12,
        COUNT(*) FILTER (
            WHERE dc.classificado = 'Atua -12'
        )::bigint                                                AS agendamentos_menos_12,
        COUNT(*) FILTER (
            WHERE a.status_reuniao IN ('Concluída', 'Concluído')
        )::bigint
                                                                  AS comparecimentos,
        COUNT(*) FILTER (
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
        )::bigint                                                AS cancelamentos,
        COUNT(*) FILTER (
            WHERE a.status_reuniao = 'Vencida'
        )::bigint                                                AS vencidos
    FROM acts_agendamento a
    LEFT JOIN deal_classif dc ON dc.deal_id = a.deal_id
    GROUP BY a.sdr, a.fonte_sdr
),
deals_agg AS (
    SELECT
        sdr, fonte_sdr,
        COUNT(*)::bigint                                         AS vendas,
        COUNT(*)::bigint                                         AS vendas_novas,
        SUM(montante)::numeric                                    AS montante,
        SUM(receita)::numeric                                     AS receita
    FROM deals_direct
    GROUP BY sdr, fonte_sdr
),
pares AS (
    SELECT sdr, fonte_sdr FROM acts_created_agg
    UNION
    SELECT sdr, fonte_sdr FROM acts_agg
    UNION SELECT sdr, fonte_sdr FROM deals_agg
)
SELECT
    p.sdr,
    p.fonte_sdr,
    COALESCE(c.agendamentos_criados, 0)::bigint AS agendamentos_criados,
    COALESCE(a.agendamentos, 0)::bigint     AS agendamentos,
    COALESCE(a.agendamentos_mais_12, 0)::bigint AS agendamentos_mais_12,
    COALESCE(a.agendamentos_menos_12, 0)::bigint AS agendamentos_menos_12,
    COALESCE(a.comparecimentos, 0)::bigint  AS comparecimentos,
    COALESCE(a.cancelamentos, 0)::bigint    AS cancelamentos,
    COALESCE(a.cancelamentos, 0)::bigint    AS cancelados,
    COALESCE(a.vencidos, 0)::bigint         AS vencidos,
    COALESCE(d.vendas, 0)::bigint           AS vendas,
    COALESCE(d.vendas_novas, 0)::bigint     AS vendas_novas,
    COALESCE(d.montante, 0)::numeric        AS montante,
    COALESCE(d.receita, 0)::numeric         AS receita
FROM pares p
LEFT JOIN acts_created_agg c USING (sdr, fonte_sdr)
LEFT JOIN acts_agg  a USING (sdr, fonte_sdr)
LEFT JOIN deals_agg d USING (sdr, fonte_sdr)
ORDER BY agendamentos DESC, vendas DESC;
