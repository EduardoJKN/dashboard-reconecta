SELECT
    data_ref,
    executiva,
    time_vendas,
    oportunidades,
    agendamentos,
    comparecimentos,
    vendas,
    montante,
    receita,
    pct_recebimento,
    pct_conversao,
    pct_venda,
    pct_comparecimento,
    perdidos,
    cancelados,
    novos,
    ascensoes,
    renovacoes,
    indicacoes,
    variacao_receita_mes_pct,
    lead_in_consultoria_gratuita
FROM bi.vw_dashboard_comercial_executivas_rw
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref;
