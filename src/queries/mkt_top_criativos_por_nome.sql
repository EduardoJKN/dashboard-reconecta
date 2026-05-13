-- =============================================================================
-- Top Criativos por nome normalizado (ad_name / utm_content)
--
-- Mídia: fdw_reconecta.anuncios agregada por LOWER(TRIM(ad_name)).
-- Leads reais: ext_reconecta.leads (mesmo universo que lp_form no Railway;
-- o role do app costuma não ter permissão em lp_form.leads).
-- Join APÓS agregação — evita multiplicar leads por múltiplos ad_id.
--
-- Classificação (valores reais no banco, case-insensitive):
--   Atua +12, Atua -12, Não atua, ...
-- Leads: e-mail único por dia (COUNT DISTINCT chave email|dia).
--
-- CPL real = investimento / leads_reais
-- CPL +12  = investimento / leads_mais_12
-- CPL Meta = investimento / leads_meta   (actions_lead somado no grão)
-- =============================================================================
WITH leads AS (
    SELECT
        LOWER(TRIM(l.utm_content)) AS ad_name_norm,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.created_at::date)::text))
            AS leads_reais,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.created_at::date)::text)) FILTER (
            WHERE LOWER(TRIM(l.classificado)) = 'atua +12'
        ) AS leads_mais_12,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.created_at::date)::text)) FILTER (
            WHERE LOWER(TRIM(l.classificado)) = 'atua -12'
        ) AS leads_menos_12,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.created_at::date)::text)) FILTER (
            WHERE LOWER(TRIM(l.classificado)) = 'não atua'
        ) AS leads_nao_atua

    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.utm_content IS NOT NULL
      AND TRIM(l.utm_content) <> ''
      AND l.email IS NOT NULL
      AND TRIM(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    GROUP BY LOWER(TRIM(l.utm_content))
),

midia AS (
    SELECT
        LOWER(TRIM(ad_name)) AS ad_name_norm,
        MAX(ad_name)         AS ad_name,
        MAX(campaign_name)   AS campaign_name,

        COUNT(DISTINCT ad_id)::bigint           AS qtd_ad_ids,
        COUNT(DISTINCT campaign_name)::bigint AS qtd_campaigns,
        COUNT(DISTINCT adset_name)::bigint    AS qtd_adsets,

        SUM(spend)::numeric                AS investimento,
        SUM(impressions)::bigint           AS impressoes,
        SUM(reach)::bigint                 AS alcance,
        SUM(clicks)::bigint                AS cliques,
        SUM(inline_link_clicks)::bigint    AS cliques_link,
        SUM(actions_landing_page_view)::bigint AS lp_views,
        SUM(actions_lead)::bigint          AS leads_meta,

        CASE WHEN SUM(impressions) > 0
             THEN 100.0 * SUM(clicks)::double precision / SUM(impressions)::double precision
        END AS ctr,

        CASE WHEN SUM(clicks) > 0
             THEN SUM(spend)::numeric / NULLIF(SUM(clicks)::numeric, 0)
        END AS cpc

    FROM fdw_reconecta.anuncios
    WHERE date_start::date BETWEEN :data_ini AND :data_fim
      AND ad_name IS NOT NULL
      AND TRIM(ad_name) <> ''
    GROUP BY LOWER(TRIM(ad_name))
)

SELECT
    m.ad_name_norm,
    m.ad_name,
    m.campaign_name,

    m.qtd_ad_ids,
    m.qtd_campaigns,
    m.qtd_adsets,

    m.investimento,
    m.impressoes,
    m.alcance,
    m.cliques,
    m.cliques_link,
    m.lp_views,
    m.leads_meta,
    m.ctr,
    m.cpc,

    COALESCE(l.leads_reais, 0)::bigint     AS leads_reais,
    COALESCE(l.leads_mais_12, 0)::bigint   AS leads_mais_12,
    COALESCE(l.leads_menos_12, 0)::bigint AS leads_menos_12,
    COALESCE(l.leads_nao_atua, 0)::bigint AS leads_nao_atua,

    CASE
        WHEN COALESCE(l.leads_reais, 0) > 0
        THEN m.investimento / NULLIF(l.leads_reais::numeric, 0)
    END AS cpl_real,

    CASE
        WHEN COALESCE(l.leads_mais_12, 0) > 0
        THEN m.investimento / NULLIF(l.leads_mais_12::numeric, 0)
    END AS cpl_mais_12,

    CASE
        WHEN COALESCE(m.leads_meta, 0) > 0
        THEN m.investimento / NULLIF(m.leads_meta::numeric, 0)
    END AS cpl_meta

FROM midia m
LEFT JOIN leads l ON l.ad_name_norm = m.ad_name_norm
ORDER BY leads_reais DESC NULLS LAST, m.investimento DESC NULLS LAST;
