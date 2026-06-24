-- Cópia legada (duplo scan em ext_reconecta.leads) — somente para validação de equivalência.
-- Não usar em produção; ver mkt_top_criativos_por_nome.sql.
WITH leads AS (
    SELECT
        LOWER(TRIM(l.utm_content)) AS ad_name_norm,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.timestamp::date)::text))
            AS leads_reais,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.timestamp::date)::text)) FILTER (
            WHERE LOWER(TRIM(l.classificado)) = 'atua +12'
        ) AS leads_mais_12,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.timestamp::date)::text)) FILTER (
            WHERE LOWER(TRIM(l.classificado)) = 'atua -12'
        ) AS leads_menos_12,

        COUNT(DISTINCT (LOWER(TRIM(l.email)) || '|' || (l.timestamp::date)::text)) FILTER (
            WHERE LOWER(TRIM(l.classificado)) = 'não atua'
        ) AS leads_nao_atua

    FROM ext_reconecta.leads l
    WHERE l.timestamp::date BETWEEN :data_ini AND :data_fim
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

leads_emails AS (
    SELECT DISTINCT
        LOWER(TRIM(l.utm_content)) AS ad_name_norm,
        LOWER(TRIM(l.email))       AS email_norm
    FROM ext_reconecta.leads l
    WHERE l.timestamp::date BETWEEN :data_ini AND :data_fim
      AND l.utm_content IS NOT NULL
      AND TRIM(l.utm_content) <> ''
      AND l.email IS NOT NULL
      AND TRIM(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),

aplicacoes_dedup AS (
    SELECT
        email_norm,
        classificado_norm
    FROM (
        SELECT
            LOWER(TRIM(ta.email)) AS email_norm,
            LOWER(TRIM(ta.classificado)) AS classificado_norm,
            ROW_NUMBER() OVER (
                PARTITION BY LOWER(TRIM(ta.email)),
                             ta.created_at::date
                ORDER BY ta.created_at DESC
            ) AS rn
        FROM fdw_reconecta.typeform_aplicacoes ta
        WHERE ta.created_at::date BETWEEN :data_ini AND :data_fim
          AND ta.dados_completos IS TRUE
          AND ta.email IS NOT NULL
          AND TRIM(ta.email) <> ''
          AND LOWER(TRIM(ta.email)) NOT LIKE '%@teste%'
          AND LOWER(TRIM(ta.email)) NOT LIKE '%teste@%'
          AND LOWER(TRIM(ta.email)) NOT LIKE '%smarts%'
          AND LOWER(TRIM(ta.email)) NOT LIKE '%reconecta%'
    ) sub
    WHERE rn = 1
),

aplicacoes AS (
    SELECT
        le.ad_name_norm,
        COUNT(DISTINCT a.email_norm) AS aplicacoes,
        COUNT(DISTINCT CASE
            WHEN a.classificado_norm IN ('atua +12', 'atua+12', '+12')
            THEN a.email_norm
        END) AS aplicacoes_mais_12,
        COUNT(DISTINCT CASE
            WHEN a.classificado_norm IN ('atua -12', 'atua-12', '-12')
            THEN a.email_norm
        END) AS aplicacoes_menos_12
    FROM leads_emails le
    INNER JOIN aplicacoes_dedup a ON a.email_norm = le.email_norm
    GROUP BY le.ad_name_norm
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

    COALESCE(a.aplicacoes, 0)::bigint         AS aplicacoes,
    COALESCE(a.aplicacoes_mais_12, 0)::bigint AS aplicacoes_mais_12,
    COALESCE(a.aplicacoes_menos_12, 0)::bigint AS aplicacoes_menos_12,

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
LEFT JOIN aplicacoes a ON a.ad_name_norm = m.ad_name_norm
ORDER BY leads_reais DESC NULLS LAST, m.investimento DESC NULLS LAST;
