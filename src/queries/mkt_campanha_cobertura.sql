-- =============================================================================
-- Cobertura da atribuição POR CAMPAIGN_ID na odam.mart_ad_funnel_daily.
--
-- Retorna 1 linha com 9 colunas — totais e quebras por presença de
-- campaign_id (NULL vs preenchido). Usado pelo expander de diagnóstico
-- da seção "Comparar campanhas" da página Campanhas.
--
-- Diagnóstico apenas — NÃO usar pra distribuir resultados em campanhas.
-- Linhas com campaign_id NULL não entram na comparação (decisão V1.5).
-- =============================================================================
SELECT
    -- Leads (total e quebra)
    SUM(leads_atua_mais_12 + leads_atua_menos_12 + leads_nao_atua)::bigint
        AS total_leads_mart,
    SUM(CASE WHEN campaign_id IS NOT NULL
             THEN (leads_atua_mais_12 + leads_atua_menos_12 + leads_nao_atua)
             ELSE 0 END)::bigint AS leads_com_campaign,
    SUM(CASE WHEN campaign_id IS NULL
             THEN (leads_atua_mais_12 + leads_atua_menos_12 + leads_nao_atua)
             ELSE 0 END)::bigint AS leads_sem_campaign,

    -- Vendas (total e quebra)
    SUM(vendas)::bigint AS total_vendas_mart,
    SUM(CASE WHEN campaign_id IS NOT NULL THEN vendas ELSE 0 END)::bigint
        AS vendas_com_campaign,
    SUM(CASE WHEN campaign_id IS NULL THEN vendas ELSE 0 END)::bigint
        AS vendas_sem_campaign,

    -- Receita (total e quebra)
    SUM(valor_receita)::numeric AS total_receita_mart,
    SUM(CASE WHEN campaign_id IS NOT NULL THEN valor_receita ELSE 0 END)::numeric
        AS receita_com_campaign,
    SUM(CASE WHEN campaign_id IS NULL THEN valor_receita ELSE 0 END)::numeric
        AS receita_sem_campaign
FROM odam.mart_ad_funnel_daily
WHERE data_ref BETWEEN :data_ini AND :data_fim;
