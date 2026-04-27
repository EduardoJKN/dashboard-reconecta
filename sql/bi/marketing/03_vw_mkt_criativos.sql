-- =============================================================================
-- bi.vw_mkt_criativos
-- -----------------------------------------------------------------------------
-- Granularidade: 1 linha por (data_ref, ad_id) — só Meta (Google/Pinterest
-- não expõem grão de criativo no FDW).
-- Junta dados diários do anúncio com o cache de criativos Meta para enriquecer
-- com thumbnail/permalink/status.
--
-- Dependências:
--   RAW : fdw_reconecta.anuncios
--   ODAM: odam.meta_ads_creatives  (cache populado por sync-meta-creatives.ts)
-- =============================================================================

CREATE OR REPLACE VIEW bi.vw_mkt_criativos AS
WITH ads_daily AS (
    SELECT
        a.date_start::date                 AS data_ref,
        a.ad_id::text                      AS ad_id,
        a.ad_name::text                    AS ad_name,
        a.adset_id::text                   AS adset_id,
        a.adset_name::text                 AS adset_name,
        a.campaign_id::text                AS campaign_id,
        a.campaign_name::text              AS campaign_name,
        SUM(a.spend)::numeric              AS investimento,
        SUM(a.impressions)::bigint         AS impressoes,
        SUM(a.reach)::bigint               AS alcance,
        SUM(a.unique_clicks)::bigint       AS cliques,
        SUM(a.inline_link_clicks)::bigint  AS link_clicks,
        -- rankings categóricos: pega o último valor observado no grão
        MAX(a.quality_ranking)::text         AS quality_ranking,
        MAX(a.engagement_rate_ranking)::text AS engagement_ranking,
        MAX(a.conversion_rate_ranking)::text AS conversion_ranking
    FROM fdw_reconecta.anuncios a
    WHERE a.date_start IS NOT NULL
      AND a.ad_id IS NOT NULL
      AND a.campaign_id <> '120234100785340241'
      AND COALESCE(a.campaign_name, '') NOT ILIKE 'REL_02%'
    GROUP BY 1, 2, 3, 4, 5, 6, 7
)
SELECT
    d.data_ref,
    d.ad_id,
    d.ad_name,
    d.adset_id,
    d.adset_name,
    d.campaign_id,
    d.campaign_name,
    d.investimento,
    d.impressoes,
    d.alcance,
    d.cliques,
    d.link_clicks,
    d.quality_ranking,
    d.engagement_ranking,
    d.conversion_ranking,
    c.thumbnail_url,
    c.image_url,
    c.permalink_url,
    c.effective_status,
    c.account_label
FROM ads_daily d
LEFT JOIN odam.meta_ads_creatives c
       ON c.ad_id = d.ad_id;
