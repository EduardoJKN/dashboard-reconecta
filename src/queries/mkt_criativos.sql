SELECT
    data_ref,
    ad_id,
    ad_name,
    adset_id,
    adset_name,
    campaign_id,
    campaign_name,
    investimento,
    impressoes,
    alcance,
    cliques,
    link_clicks,
    quality_ranking,
    engagement_ranking,
    conversion_ranking,
    thumbnail_url,
    image_url,
    permalink_url,
    effective_status,
    account_label
FROM bi.vw_mkt_criativos
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref, ad_id;
