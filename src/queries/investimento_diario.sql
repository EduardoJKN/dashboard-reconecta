SELECT
    data_ref,
    investimento_total
FROM bi.vw_investimento_diario
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref;
