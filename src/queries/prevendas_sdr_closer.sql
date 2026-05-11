-- =============================================================================
-- Pré-vendas — matriz SDR × Closer (regra HÍBRIDA).
-- =============================================================================
-- 1 linha por par (SDR, Closer, fonte_sdr) com agendamentos,
-- comparecimentos, vendas, vendas_novas, montante, receita.
--
-- Atribuição:
--   SDR    = COALESCE(`zoho_activities.prevendas`,
--                     `zoho_deals.sdr_ss` resolvido via `zoho_users`,
--                     'Sem SDR')
--   Closer = `zoho_activities.owner` resolvido via `zoho_users`
--             (NULL → 'Sem Closer')
--   fonte_sdr = qual caminho do COALESCE foi usado (auditoria).
--
-- Para vendas, mesma regra de prevendas_por_sdr.sql: deal atrelado a
-- activity via what_id, DISTINCT ON deal_id (creditado à activity mais
-- recente). O par (SDR, Closer, fonte_sdr) vem da mesma activity creditada.
-- =============================================================================
WITH acts AS (
    SELECT
        a.id                                                AS activity_id,
        a.what_id                                            AS deal_id,
        a.start_datetime::date                               AS data_ref,
        a.status_reuniao,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            TRIM(usdr.first_name || ' ' || usdr.last_name),
            'Sem SDR'
        )                                                    AS sdr,
        CASE
            WHEN NULLIF(btrim(a.prevendas), '') IS NOT NULL
                THEN 'activity.prevendas'
            WHEN TRIM(usdr.first_name || ' ' || usdr.last_name) IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END                                                  AS fonte_sdr,
        COALESCE(
            NULLIF(TRIM(uo.first_name || ' ' || uo.last_name), ''),
            'Sem Closer'
        )                                                    AS closer
    FROM zoho_activities a
    LEFT JOIN zoho_users uo   ON uo.id::text  = a.owner::text
    LEFT JOIN zoho_deals  d   ON d.id         = a.what_id
    LEFT JOIN zoho_users  usdr ON usdr.id::text = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta','Indicação')
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
deals_acts AS (
    SELECT DISTINCT ON (zd.id)
        zd.id          AS deal_id,
        a.sdr,
        a.fonte_sdr,
        a.closer,
        zd.tipo_venda,
        CASE WHEN NULLIF(btrim(zd.amount), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                     REGEXP_REPLACE(TRIM(zd.amount), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS montante,
        CASE WHEN NULLIF(btrim(zd.receita), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                     REGEXP_REPLACE(TRIM(zd.receita), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS receita
    FROM acts a
    JOIN zoho_deals zd ON zd.id = a.deal_id
    WHERE zd.stage IN ('Ganho','Fechado Ganho')
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
    ORDER BY zd.id, a.data_ref DESC
),
acts_pair AS (
    SELECT
        sdr, fonte_sdr, closer,
        COUNT(*)::bigint                                         AS agendamentos,
        COUNT(*) FILTER (WHERE status_reuniao = 'Concluída')::bigint
                                                                  AS comparecimentos
    FROM acts
    GROUP BY sdr, fonte_sdr, closer
),
deals_pair AS (
    SELECT
        sdr, fonte_sdr, closer,
        COUNT(*)::bigint                                         AS vendas,
        COUNT(*) FILTER (WHERE tipo_venda = 'Novo cliente')::bigint
                                                                  AS vendas_novas,
        SUM(montante)::numeric                                    AS montante,
        SUM(receita)::numeric                                     AS receita
    FROM deals_acts
    GROUP BY sdr, fonte_sdr, closer
),
pares AS (
    SELECT sdr, fonte_sdr, closer FROM acts_pair
    UNION SELECT sdr, fonte_sdr, closer FROM deals_pair
)
SELECT
    p.sdr,
    p.fonte_sdr,
    p.closer,
    COALESCE(a.agendamentos, 0)::bigint    AS agendamentos,
    COALESCE(a.comparecimentos, 0)::bigint AS comparecimentos,
    COALESCE(d.vendas, 0)::bigint          AS vendas,
    COALESCE(d.vendas_novas, 0)::bigint    AS vendas_novas,
    COALESCE(d.montante, 0)::numeric       AS montante,
    COALESCE(d.receita, 0)::numeric        AS receita
FROM pares p
LEFT JOIN acts_pair  a USING (sdr, fonte_sdr, closer)
LEFT JOIN deals_pair d USING (sdr, fonte_sdr, closer)
ORDER BY agendamentos DESC, vendas DESC;
