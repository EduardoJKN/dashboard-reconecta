-- =============================================================================
-- Pré-vendas — SLA (amostra parcial de `ext_reconecta.leads.sla`).
-- =============================================================================
-- ⚠ Cobertura PARCIAL. Em abr/2026: 341 de 884 leads (~39%) têm `sla`
-- preenchido. O significado exato do campo (em minutos? em segundos?
-- desde quando até quando?) ainda precisa ser confirmado com o time.
-- Os números agregados aqui são INDICATIVOS, não devem ser usados como
-- ranking individual nem como base de SLA contratual.
--
-- Devolve métricas agregadas:
--   total_leads        — total de leads válidos no período (filtro padrão)
--   leads_com_sla      — leads com `sla` numérico preenchido
--   leads_sem_sla      — `total_leads - leads_com_sla`
--   tempo_medio_min    — AVG(sla::int) (em minutos, assumindo)
--   tempo_p50_min      — mediana
--   tempo_p90_min      — percentil 90
--   tempo_max_min      — pior tempo registrado
-- + faixas (bucket_0_5, bucket_6_15, bucket_16_60, bucket_1_4h,
--           bucket_4_24h, bucket_mais_24h).
--
-- Tudo em UMA row para facilitar consumo no Python (sem precisar pivotar).
-- =============================================================================
WITH leads_clean AS (
    SELECT
        lower(btrim(l.email)) AS email_norm,
        l.sla
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
sla_num AS (
    SELECT (sla::int) AS s
    FROM leads_clean
    WHERE sla IS NOT NULL AND btrim(sla) <> '' AND sla ~ '^[0-9]+$'
)
SELECT
    (SELECT COUNT(*) FROM leads_clean)::bigint                AS total_leads,
    (SELECT COUNT(*) FROM sla_num)::bigint                    AS leads_com_sla,
    ((SELECT COUNT(*) FROM leads_clean) - (SELECT COUNT(*) FROM sla_num))::bigint
                                                              AS leads_sem_sla,
    COALESCE((SELECT AVG(s) FROM sla_num), 0)::numeric        AS tempo_medio_min,
    COALESCE((SELECT PERCENTILE_CONT(0.50)
              WITHIN GROUP (ORDER BY s) FROM sla_num), 0)::numeric
                                                              AS tempo_p50_min,
    COALESCE((SELECT PERCENTILE_CONT(0.90)
              WITHIN GROUP (ORDER BY s) FROM sla_num), 0)::numeric
                                                              AS tempo_p90_min,
    COALESCE((SELECT MAX(s) FROM sla_num), 0)::numeric        AS tempo_max_min,
    -- Faixas
    (SELECT COUNT(*) FROM sla_num WHERE s <= 5)::bigint                AS bucket_0_5,
    (SELECT COUNT(*) FROM sla_num WHERE s BETWEEN 6 AND 15)::bigint    AS bucket_6_15,
    (SELECT COUNT(*) FROM sla_num WHERE s BETWEEN 16 AND 60)::bigint   AS bucket_16_60,
    (SELECT COUNT(*) FROM sla_num WHERE s BETWEEN 61 AND 240)::bigint  AS bucket_1_4h,
    (SELECT COUNT(*) FROM sla_num WHERE s BETWEEN 241 AND 1440)::bigint AS bucket_4_24h,
    (SELECT COUNT(*) FROM sla_num WHERE s > 1440)::bigint              AS bucket_mais_24h;
