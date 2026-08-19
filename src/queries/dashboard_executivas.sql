-- =============================================================================
-- Executivas — KPIs diários por closer (Visão Geral / Executivas & Times).
-- Fonte principal: bi.vw_dashboard_comercial_executivas_rw
--
-- Tipos extras (Upgrade, Novo cliente EVENTO, Ingresso) NÃO existem ainda
-- na view BI. Agregamos à parte a partir de bi.trat_negocios_rw com a MESMA
-- regra do CTE `tipos_venda` da view (data_compra + stage Ganho + nome da
-- executiva via zoho_users).
-- =============================================================================
WITH tipos_extra AS (
    SELECT
        n.data_compra AS data_ref,
        COALESCE(
            NULLIF(TRIM(BOTH FROM (u.first_name || ' ' || u.last_name)), ''),
            n.executiva_vendas,
            'SEM_EXECUTIVA'
        ) AS executiva,
        COUNT(*) FILTER (WHERE n.tipo_venda = 'Upgrade')::bigint
            AS upgrades,
        COUNT(*) FILTER (WHERE n.tipo_venda = 'Novo cliente EVENTO')::bigint
            AS eventos,
        COUNT(*) FILTER (WHERE n.tipo_venda LIKE 'Ingresso%')::bigint
            AS ingressos
    FROM bi.trat_negocios_rw n
    LEFT JOIN zoho_users u
           ON n.executiva_vendas = u.id
    WHERE n.data_compra IS NOT NULL
      AND n.stage = 'Ganho'
      AND n.data_compra BETWEEN :data_ini AND :data_fim
      AND (
          n.tipo_venda IN ('Upgrade', 'Novo cliente EVENTO')
          OR n.tipo_venda LIKE 'Ingresso%'
      )
    GROUP BY 1, 2
)
SELECT
    v.data_ref,
    v.executiva,
    v.time_vendas,
    v.oportunidades,
    v.agendamentos,
    v.comparecimentos,
    v.vendas,
    v.montante,
    v.receita,
    v.pct_recebimento,
    v.pct_conversao,
    v.pct_venda,
    v.pct_comparecimento,
    v.perdidos,
    v.cancelados,
    -- vencidos: a view agora expõe direto. Convenção pós-mai/2026:
    -- `agendamentos` já vem LÍQUIDO de `Vencida`; o bruto se reconstrói
    -- via `agendamentos + vencidos`. A coluna entra no ranking como
    -- complementar (não é re-injetada via detalhe).
    v.vencidos,
    v.novos,
    v.ascensoes,
    v.renovacoes,
    v.indicacoes,
    COALESCE(x.upgrades, 0)::bigint AS upgrades,
    COALESCE(x.eventos, 0)::bigint AS eventos,
    COALESCE(x.ingressos, 0)::bigint AS ingressos,
    v.variacao_receita_mes_pct,
    v.lead_in_consultoria_gratuita,
    -- leads_lp_form: agregado por data na view (lp_classificacao só agrupa
    -- por data, não por executiva). Logo o valor se REPETE entre
    -- executivas do mesmo dia — não somar entre executivas (ver
    -- comentário em src/transforms.py:_EXEC_SUM).
    v.leads_lp_form,
    -- ====================================================================
    -- Buckets de classificação (regra canônica +12 > -12 > Não atua > Sem
    -- classif, combinada das 4 fontes lead_classification, qualificacao,
    -- classificado_cal, ext_reconecta.leads.classificado).
    -- Para `montante_*` / `receita_*` a view também trava `tipo_venda =
    -- 'Novo cliente'` (só vendas novas classificadas).
    -- ====================================================================
    v.oportunidades_mais_12,
    v.oportunidades_menos_12,
    v.oportunidades_nao_atua,
    v.oportunidades_sem_classificacao,
    v.agendamentos_mais_12,
    v.agendamentos_menos_12,
    v.agendamentos_nao_atua,
    v.agendamentos_sem_classificacao,
    v.comparecimentos_mais_12,
    v.comparecimentos_menos_12,
    v.comparecimentos_nao_atua,
    v.comparecimentos_sem_classificacao,
    v.ganhos_mais_12,
    v.ganhos_menos_12,
    v.ganhos_nao_atua,
    v.ganhos_sem_classificacao,
    v.montante_mais_12,
    v.montante_menos_12,
    v.montante_nao_atua,
    v.receita_mais_12,
    v.receita_menos_12,
    v.receita_nao_atua
FROM bi.vw_dashboard_comercial_executivas_rw v
LEFT JOIN tipos_extra x
       ON x.data_ref = v.data_ref
      AND x.executiva = v.executiva
WHERE v.data_ref BETWEEN :data_ini AND :data_fim
ORDER BY v.data_ref;
