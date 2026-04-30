SELECT
    data_ref,
    canal,
    campaign_id,
    campaign_name,
    objetivo,
    investimento,
    impressoes,
    cliques,
    alcance
FROM bi.vw_mkt_campanhas
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref, canal, campaign_id;
