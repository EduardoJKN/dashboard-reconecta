SELECT
    sdr,
    closer,
    mes_ref,
    leads_recebidos,
    ganhos,
    taxa_conversao,
    receita_total,
    montante_total,
    ticket_medio,
    dias_ate_fechamento,
    tipo_sdr,
    time_closer
FROM bi.vw_compatibilidade_sdr_closer
WHERE mes_ref BETWEEN :mes_ini AND :mes_fim
ORDER BY mes_ref, closer, sdr;
