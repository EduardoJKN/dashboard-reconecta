-- =============================================================================
-- bi.vw_mkt_campanhas
-- -----------------------------------------------------------------------------
-- Granularidade: 1 linha por (data_ref, canal, campaign_id).
-- Performance diária por campanha em cada canal pago. UNION ALL puro
-- (sem JOIN com leads — a atribuição lead→campanha vai em vw_mkt_funil).
--
-- Dependências (RAW): fdw_reconecta.anuncios, fdw_reconecta.google_ads,
--                     fdw_reconecta.pinterest_ads
-- =============================================================================

CREATE OR REPLACE VIEW bi.vw_mkt_campanhas AS
WITH meta AS (
    SELECT
        date_start::date            AS data_ref,
        'Meta'::text                AS canal,
        campaign_id::text           AS campaign_id,
        campaign_name::text         AS campaign_name,
        NULLIF(MAX(objective::text), '') AS objetivo,
        SUM(spend)::numeric         AS investimento,
        SUM(impressions)::bigint    AS impressoes,
        SUM(unique_clicks)::bigint  AS cliques,
        SUM(reach)::bigint          AS alcance
    FROM fdw_reconecta.anuncios
    WHERE date_start IS NOT NULL
      AND campaign_id IS NOT NULL
      AND campaign_id <> '120234100785340241'
      AND COALESCE(campaign_name, '') NOT ILIKE 'REL_02%'
    GROUP BY 1, 2, 3, 4
),
google AS (
    SELECT
        date::date                AS data_ref,
        'Google'::text            AS canal,
        campaign_id::text         AS campaign_id,
        campaign_name::text       AS campaign_name,
        NULL::text                AS objetivo,
        SUM(cost)::numeric        AS investimento,
        SUM(impressions)::bigint  AS impressoes,
        SUM(clicks)::bigint       AS cliques,
        NULL::bigint              AS alcance
    FROM fdw_reconecta.google_ads
    WHERE date IS NOT NULL
      AND campaign_id IS NOT NULL
    GROUP BY 1, 2, 3, 4
),
pinterest AS (
    SELECT
        date::date                AS data_ref,
        'Pinterest'::text         AS canal,
        campaign_id::text         AS campaign_id,
        campaign_name::text       AS campaign_name,
        NULL::text                AS objetivo,
        SUM(spend)::numeric       AS investimento,
        SUM(impressions)::bigint  AS impressoes,
        SUM(clicks)::bigint       AS cliques,
        NULL::bigint              AS alcance
    FROM fdw_reconecta.pinterest_ads
    WHERE date IS NOT NULL
      AND campaign_id IS NOT NULL
    GROUP BY 1, 2, 3, 4
)
SELECT * FROM meta
UNION ALL SELECT * FROM google
UNION ALL SELECT * FROM pinterest;
