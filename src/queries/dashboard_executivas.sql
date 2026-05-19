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
    lead_in_consultoria_gratuita,
    -- leads_lp_form: agregado por data na view (lp_classificacao só agrupa
    -- por data, não por executiva). Logo o valor se REPETE entre
    -- executivas do mesmo dia — não somar entre executivas (ver
    -- comentário em src/transforms.py:_EXEC_SUM).
    leads_lp_form,
    -- ====================================================================
    -- Buckets de classificação (regra canônica +12 > -12 > Não atua > Sem
    -- classif, combinada das 4 fontes lead_classification, qualificacao,
    -- classificado_cal, ext_reconecta.leads.classificado).
    -- Para `montante_*` / `receita_*` a view também trava `tipo_venda =
    -- 'Novo cliente'` (só vendas novas classificadas).
    -- ====================================================================
    oportunidades_mais_12,
    oportunidades_menos_12,
    oportunidades_nao_atua,
    oportunidades_sem_classificacao,
    agendamentos_mais_12,
    agendamentos_menos_12,
    agendamentos_nao_atua,
    agendamentos_sem_classificacao,
    comparecimentos_mais_12,
    comparecimentos_menos_12,
    comparecimentos_nao_atua,
    comparecimentos_sem_classificacao,
    ganhos_mais_12,
    ganhos_menos_12,
    ganhos_nao_atua,
    ganhos_sem_classificacao,
    montante_mais_12,
    montante_menos_12,
    montante_nao_atua,
    receita_mais_12,
    receita_menos_12,
    receita_nao_atua
FROM bi.vw_dashboard_comercial_executivas_rw
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref;
