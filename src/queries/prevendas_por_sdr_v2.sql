-- =============================================================================
-- Pré-vendas — agregado por SDR (regra HÍBRIDA) — V2 candidata CP3-A.
-- =============================================================================
-- Mesmas colunas finais e regras de negócio de `prevendas_por_sdr.sql`.
-- Otimizações (sem alterar semântica):
--   1. Mantém dois scans de `zoho_activities` com filtro de data simples
--      (start_datetime / created_time) — o planner usa melhor que OR único.
--   2. `ext_reconecta.leads` deduplicado só para deals do universo do
--      período (activities + vendas), não para a tabela inteira.
--   3. Classificação de deals (`deal_classif`) só para deals relevantes.
-- =============================================================================
WITH acts_agendamento AS (
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
    LEFT JOIN zoho_deals d ON d.id = a.what_id
    LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta', 'Indicação')
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
    LEFT JOIN zoho_deals d ON d.id = a.what_id
    LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta', 'Indicação')
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
relevant_deal_ids AS (
    SELECT DISTINCT aa.deal_id
    FROM acts_agendamento aa
    WHERE aa.deal_id IS NOT NULL
    UNION
    SELECT DISTINCT ac.deal_id
    FROM acts_criacao ac
    WHERE ac.deal_id IS NOT NULL
    UNION
    SELECT dd.deal_id FROM deals_direct dd
),
ext_leads_dedup AS (
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text  AS deal_id,
        l.classificado   AS ext_classif
    FROM ext_reconecta.leads l
    INNER JOIN relevant_deal_ids rdi
        ON l.zoho_id::text = rdi.deal_id::text
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY l.zoho_id::text, l."timestamp" DESC NULLS LAST, l.id DESC
),
deal_classif_raw AS (
    SELECT
        d.id                                              AS deal_id,
        CASE
            WHEN NULLIF(btrim(d.lead_classification), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.lead_classification), '')
            WHEN NULLIF(btrim(d.qualificacao), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.qualificacao), '')
            WHEN NULLIF(btrim(d.classificado_cal), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.classificado_cal), '')
            WHEN NULLIF(btrim(eld.ext_classif), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(eld.ext_classif), '')
            ELSE 'Sem classificação'
        END                                               AS classif_final
    FROM zoho_deals d
    INNER JOIN relevant_deal_ids rdi ON d.id = rdi.deal_id
    LEFT JOIN ext_leads_dedup eld ON eld.deal_id = d.id::text
),
deal_classif AS (
    SELECT
        deal_id,
        classif_final,
        (classif_final = 'Atua +12') AS tem_mais_12,
        (classif_final = 'Atua -12') AS tem_menos_12
    FROM deal_classif_raw
),
acts_created_agg AS (
    SELECT
        sdr, fonte_sdr,
        COUNT(DISTINCT activity_id)::bigint                      AS agendamentos_criados
    FROM acts_criacao
    GROUP BY sdr, fonte_sdr
),
acts_agg AS (
    SELECT
        a.sdr,
        a.fonte_sdr,
        COUNT(DISTINCT a.activity_id)::bigint                    AS agendamentos,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE COALESCE(dc.tem_mais_12, FALSE)
        )::bigint                                                AS agendamentos_mais_12,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE COALESCE(dc.tem_menos_12, FALSE)
        )::bigint                                                AS agendamentos_menos_12,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE a.status_reuniao IN ('Concluída', 'Concluído')
        )::bigint                                                AS comparecimentos,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
        )::bigint                                                AS cancelamentos,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE a.status_reuniao = 'Vencida'
        )::bigint                                                AS vencidos
    FROM acts_agendamento a
    LEFT JOIN deal_classif dc ON dc.deal_id = a.deal_id
    GROUP BY a.sdr, a.fonte_sdr
),
deals_agg AS (
    SELECT
        sdr, fonte_sdr,
        COUNT(DISTINCT deal_id)::bigint                          AS vendas,
        COUNT(DISTINCT deal_id)::bigint                          AS vendas_novas,
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
