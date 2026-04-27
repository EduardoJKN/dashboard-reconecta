-- =============================================================================
-- bi.vw_mkt_overview
-- -----------------------------------------------------------------------------
-- Granularidade: 1 linha por (data_ref, canal).
-- Canais possíveis: 'Meta', 'Google', 'Pinterest', 'Organico'.
-- Junta investimento + impressões + cliques + alcance dos canais pagos com
-- contagem de leads (e qualificados) classificados por utm_source.
--
-- Filtros canônicos aplicados (replicam o backend NestJS):
--   * Meta: exclui campaign_id='120234100785340241' e nomes ILIKE 'REL_02%'
--   * Leads: descarta e-mails de teste (@teste, teste@, @reconecta, @mlgrupo,
--            jardelkahne)
--
-- Dependências (RAW): fdw_reconecta.anuncios, fdw_reconecta.google_ads,
--                     fdw_reconecta.pinterest_ads, lp_form.leads
-- =============================================================================

CREATE OR REPLACE VIEW bi.vw_mkt_overview AS
WITH
-- ---------- 1) Investimento dos canais pagos ----------
meta_paid AS (
    SELECT
        date_start::date          AS data_ref,
        'Meta'::text              AS canal,
        SUM(spend)::numeric       AS investimento,
        SUM(impressions)::bigint  AS impressoes,
        SUM(unique_clicks)::bigint AS cliques,
        SUM(reach)::bigint        AS alcance
    FROM fdw_reconecta.anuncios
    WHERE date_start IS NOT NULL
      AND campaign_id <> '120234100785340241'
      AND COALESCE(campaign_name, '') NOT ILIKE 'REL_02%'
    GROUP BY 1
),
google_paid AS (
    SELECT
        date::date                AS data_ref,
        'Google'::text            AS canal,
        SUM(cost)::numeric        AS investimento,
        SUM(impressions)::bigint  AS impressoes,
        SUM(clicks)::bigint       AS cliques,
        NULL::bigint              AS alcance
    FROM fdw_reconecta.google_ads
    WHERE date IS NOT NULL
    GROUP BY 1
),
pinterest_paid AS (
    SELECT
        date::date                AS data_ref,
        'Pinterest'::text         AS canal,
        SUM(spend)::numeric       AS investimento,
        SUM(impressions)::bigint  AS impressoes,
        SUM(clicks)::bigint       AS cliques,
        NULL::bigint              AS alcance
    FROM fdw_reconecta.pinterest_ads
    WHERE date IS NOT NULL
    GROUP BY 1
),
paid AS (
    SELECT * FROM meta_paid
    UNION ALL SELECT * FROM google_paid
    UNION ALL SELECT * FROM pinterest_paid
),
-- ---------- 2) Leads de lp_form.leads, classificados por canal ----------
leads_clean AS (
    SELECT
        created_at::date AS data_ref,
        LOWER(email)     AS email,
        classificado,
        CASE
            WHEN LOWER(COALESCE(utm_source, '')) IN
                 ('ig','meta','fb','an','facebook','instagram') THEN 'Meta'
            WHEN LOWER(COALESCE(utm_source, '')) = 'google'    THEN 'Google'
            WHEN LOWER(COALESCE(utm_source, '')) = 'pinterest' THEN 'Pinterest'
            ELSE 'Organico'
        END AS canal
    FROM lp_form.leads
    WHERE created_at IS NOT NULL
      AND email IS NOT NULL
      AND email <> ''
      AND email NOT ILIKE '%@teste%'
      AND email NOT ILIKE '%teste@%'
      AND email NOT ILIKE '%@reconecta%'
      AND email NOT ILIKE '%jardelkahne%'
      AND email NOT ILIKE '%@mlgrupo%'
),
leads_agg AS (
    SELECT
        data_ref,
        canal,
        COUNT(DISTINCT email)
            AS leads,
        COUNT(DISTINCT email) FILTER (WHERE classificado = 'Atua +12')
            AS leads_qualif_mais_12,
        COUNT(DISTINCT email) FILTER (WHERE classificado = 'Atua -12')
            AS leads_qualif_menos_12,
        COUNT(DISTINCT email) FILTER (WHERE classificado IN ('Atua +12','Atua -12'))
            AS leads_qualificados
    FROM leads_clean
    GROUP BY 1, 2
)
-- ---------- 3) Junta paid × leads (FULL OUTER mantém ambos os lados) ----------
SELECT
    COALESCE(p.data_ref, l.data_ref)     AS data_ref,
    COALESCE(p.canal,    l.canal)        AS canal,
    COALESCE(p.investimento, 0)::numeric AS investimento,
    COALESCE(p.impressoes, 0)            AS impressoes,
    COALESCE(p.cliques, 0)               AS cliques,
    p.alcance                            AS alcance,
    COALESCE(l.leads, 0)                 AS leads,
    COALESCE(l.leads_qualificados, 0)    AS leads_qualificados,
    COALESCE(l.leads_qualif_mais_12, 0)  AS leads_qualif_mais_12,
    COALESCE(l.leads_qualif_menos_12, 0) AS leads_qualif_menos_12
FROM paid p
FULL OUTER JOIN leads_agg l
       ON p.data_ref = l.data_ref AND p.canal = l.canal;
