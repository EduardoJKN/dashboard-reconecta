SELECT
    data_ref,
    canal,
    investimento,
    impressoes,
    cliques,
    alcance,
    leads,
    leads_qualificados,
    leads_qualif_mais_12,
    leads_qualif_menos_12
FROM bi.vw_mkt_overview
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref, canal;
