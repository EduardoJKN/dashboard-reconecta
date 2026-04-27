SELECT
    data_ref,
    leads_lp_unicos
FROM bi.vw_funil_leads_diario
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref;
