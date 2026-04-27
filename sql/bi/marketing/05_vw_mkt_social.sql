-- =============================================================================
-- bi.vw_mkt_social
-- -----------------------------------------------------------------------------
-- Granularidade: 1 linha por post do Instagram orgânico.
-- Adiciona métricas derivadas (engajamento, taxa de engajamento) e enriquece
-- com followers do perfil (assume-se um único perfil; se houver mais, pega
-- o de maior número de seguidores).
--
-- Dependências (RAW): fdw_reconecta.instagram_posts,
--                     fdw_reconecta.instagram_profile
-- =============================================================================

CREATE OR REPLACE VIEW bi.vw_mkt_social AS
WITH profile AS (
    SELECT username, name, followers_count, profile_picture_url
    FROM fdw_reconecta.instagram_profile
    ORDER BY followers_count DESC NULLS LAST
    LIMIT 1
)
SELECT
    p.id::text                                  AS post_id,
    p.timestamp::timestamptz                    AS publicado_em,
    p.timestamp::date                           AS data_ref,
    p.media_type::text                          AS tipo_midia,
    p.permalink::text                           AS permalink,
    COALESCE(p.reach, 0)::bigint                AS alcance,
    COALESCE(p.likes, 0)::bigint                AS curtidas,
    COALESCE(p.comments, 0)::bigint             AS comentarios,
    COALESCE(p.saved, 0)::bigint                AS salvamentos,
    (COALESCE(p.likes, 0)
     + COALESCE(p.comments, 0)
     + COALESCE(p.saved, 0))::bigint            AS engajamento,
    prof.username,
    prof.name,
    prof.followers_count,
    CASE
        WHEN prof.followers_count IS NULL OR prof.followers_count = 0 THEN NULL
        ELSE
            ((COALESCE(p.likes, 0)
              + COALESCE(p.comments, 0)
              + COALESCE(p.saved, 0))::numeric
             / prof.followers_count) * 100
    END AS taxa_engajamento_pct
FROM fdw_reconecta.instagram_posts p
CROSS JOIN profile prof;
