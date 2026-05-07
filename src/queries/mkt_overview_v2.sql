-- =============================================================================
-- Visão Geral Marketing (V2) — query parametrizada com early-filter por data.
-- =============================================================================
-- Substitui o SELECT direto de bi.vw_mkt_overview_daily_v2 (que estava em ~107s
-- no EXPLAIN ANALYZE) por 4 CTEs com filtro de data aplicado JÁ NO COMEÇO,
-- consolidadas via UNION de keys + LEFT JOIN. Schema de saída idêntico ao da
-- view V2 — get_mkt_overview_v2() e overview_v2_kpis() não precisam mudar.
--
-- Fontes:
--   bi.stg_mkt_ads_daily               → mídia (investimento + entregáveis Meta)
--   ext_reconecta.leads                → leads brutos (bypass de
--                                        odam.v_attribution_lead_to_deal e
--                                        bi.stg_mkt_lead_tracking — ambas
--                                        estavam pesadas)
--   zoho_deals                         → deals (LATERAL JOIN c/ prioridade
--                                        zoho_id > session_id > email,
--                                        replicando o DISTINCT ON da view)
--   fdw_reconecta.anuncios             → ad_lookup (utm_content→ad_id) +
--                                        ads_id_set (match p/ tipo_atribuicao)
--   bi.vw_dashboard_comercial_executivas_rw → total geral comercial (CRM)
--   bi.vw_investimento_diario          → investimento total (mídia consolidada)
--
-- Por que rápido: cada CTE filtra a janela de data ANTES do GROUP BY (leads
-- usa l.created_at >= ts_ini AND < ts_fim+1d para permitir índice). Em vez
-- do JOIN com OR + DISTINCT ON (que escaneia o mundo todo), usamos LATERAL
-- JOIN ... LIMIT 1 — o planner faz N lookups indexados em zoho_deals (um por
-- lead do mês, ordem de magnitude milhares).
--
-- Os ratios (cpl_*/roas_*) ficam no SELECT final por linha; a agregação do
-- período é recalculada em Python via overview_v2_kpis() sobre os SUMs.
-- =============================================================================
WITH
ads_daily AS (
    SELECT
        data_ref,
        SUM(investimento)               AS investimento_midia,
        SUM(impressoes)                 AS impressoes,
        SUM(alcance)                    AS alcance,
        SUM(cliques)                    AS cliques,
        SUM(inline_link_clicks)         AS inline_link_clicks,
        SUM(actions_lead)               AS leads_meta,
        SUM(pixel_lead)                 AS pixel_lead,
        SUM(conversions_schedule_total) AS agendamentos_meta
    FROM bi.stg_mkt_ads_daily
    WHERE data_ref BETWEEN :data_ini AND :data_fim
    GROUP BY data_ref
),
-- -----------------------------------------------------------------------------
-- Bypass das views intermediárias de leads (stg_mkt_lead_tracking ~100s e
-- v_attribution_lead_to_deal lenta + divergente). Reimplementa a parte
-- necessária lendo direto de ext_reconecta.leads, zoho_deals e
-- fdw_reconecta.anuncios.
--
-- Estratégia:
--   1) ad_lookup = utm_content → ad_id (igual à view original; DISTINCT ON
--      ad_name desempata pelo menor ad_id).
--   2) ads_id_set = universo de ad_ids existentes (pra distinguir
--      ad_id_enriquecido_ads vs ad_id_sem_match_ads).
--   3) leads_base = ext_reconecta.leads filtrado por janela de timestamp
--      (sem cast em created_at no WHERE — preserva uso de índice em
--      created_at). Limpeza de email aplicada aqui pra reduzir o universo
--      antes do LATERAL JOIN com zoho_deals.
--   4) leads_resolved = LATERAL JOIN com zoho_deals (LIMIT 1 por lead, com
--      a mesma prioridade do DISTINCT ON da view: zoho_id=1 > session_id=2 >
--      email=3 > else=9, desempate por d.created_at ASC NULLS LAST).
--   5) leads_atrib = adiciona flags + tipo_atribuicao + prioridade_atribuicao.
--   6) leads_canonico = ROW_NUMBER pra deduplicar por (data_lead, email) e
--      por deal_id (este último só pra linhas com deal_id NOT NULL).
-- -----------------------------------------------------------------------------
ad_lookup AS (
    -- utm_content → ad_id (mesma lógica da odam.v_attribution_lead_to_deal).
    SELECT DISTINCT ON (ad_name) ad_name, ad_id
    FROM fdw_reconecta.anuncios
    WHERE ad_name IS NOT NULL AND ad_name <> ''
    ORDER BY ad_name, ad_id
),
ads_id_set AS (
    -- Universo de ad_ids da fonte — distingue 'ad_id_enriquecido_ads'
    -- (lead.ad_id casa com algum ad conhecido) de 'ad_id_sem_match_ads'
    -- (ad_id órfão). Sem filtro de data — o lead pode vir de ad fora
    -- da janela do dashboard.
    SELECT DISTINCT ad_id::text AS ad_id
    FROM fdw_reconecta.anuncios
    WHERE ad_id IS NOT NULL AND btrim(ad_id::text) <> ''
),
leads_base AS (
    -- Lê direto de ext_reconecta.leads. Filtro de data via timestamp puro
    -- (NÃO usa l.created_at::date no WHERE — isso quebraria índice em
    -- created_at). Email cleanup já aqui pra reduzir o universo do JOIN
    -- com zoho_deals adiante.
    SELECT
        l.id::text                                    AS lead_id,
        l.email                                       AS lead_email,
        lower(btrim(l.email))                         AS lead_email_normalizado,
        l.session_id                                  AS lead_session_id,
        l.zoho_id                                     AS lead_zoho_id,
        COALESCE(NULLIF(l.ad_id, ''), al.ad_id::text) AS lead_ad_id,
        NULLIF(l.adset_id, '')                        AS lead_adset_id,
        NULLIF(l.campaign_id, '')                     AS lead_campaign_id,
        l.utm_source                                  AS lead_utm_source,
        l.utm_medium                                  AS lead_utm_medium,
        l.utm_campaign                                AS lead_utm_campaign,
        l.utm_content                                 AS lead_utm_content,
        l.placement                                   AS lead_placement,
        l.classificado                                AS lead_classificacao,
        l.scheduled                                   AS lead_scheduled,
        l.created_at                                  AS lead_created_at,
        l.created_at::date                            AS data_lead
    FROM ext_reconecta.leads l
    LEFT JOIN ad_lookup al ON al.ad_name = l.utm_content
    WHERE l.created_at >= CAST(:data_ini AS timestamp)
      AND l.created_at <  (CAST(:data_fim AS date) + INTERVAL '1 day')
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_resolved AS (
    -- LATERAL JOIN com zoho_deals: para cada lead, pega o melhor deal pela
    -- mesma prioridade da odam.v_attribution_lead_to_deal:
    --   zoho_id (1) > session_id (2) > lower(email) (3) > else (9)
    --   desempate por d.created_at ASC NULLS LAST.
    -- Conversões de amount/receita reproduzem o regex sanitizador da view.
    SELECT
        lb.*,
        d.deal_id,
        d.deal_created_at,
        d.deal_stage,
        d.deal_data_compra,
        d.deal_valor_venda,
        d.deal_valor_receita
    FROM leads_base lb
    LEFT JOIN LATERAL (
        SELECT
            zd.id                AS deal_id,
            zd.created_at        AS deal_created_at,
            zd.stage             AS deal_stage,
            zd.data_hora_compra  AS deal_data_compra,
            CASE WHEN NULLIF(btrim(zd.amount), '') IS NULL THEN 0::numeric
                 ELSE replace(replace(regexp_replace(btrim(zd.amount), '[^0-9,.-]', '', 'g'),
                                       '.', ''), ',', '.')::numeric
            END                  AS deal_valor_venda,
            CASE WHEN NULLIF(btrim(zd.receita), '') IS NULL THEN 0::numeric
                 ELSE replace(replace(regexp_replace(btrim(zd.receita), '[^0-9,.-]', '', 'g'),
                                       '.', ''), ',', '.')::numeric
            END                  AS deal_valor_receita
        FROM zoho_deals zd
        WHERE
             (lb.lead_zoho_id    IS NOT NULL AND lb.lead_zoho_id   = zd.id)
          OR (lb.lead_session_id IS NOT NULL AND lb.lead_session_id::text = zd.session_id)
          OR (lb.lead_email      IS NOT NULL AND lower(lb.lead_email) = lower(zd.email))
        ORDER BY
            CASE
                WHEN lb.lead_zoho_id    IS NOT NULL AND lb.lead_zoho_id   = zd.id            THEN 1
                WHEN lb.lead_session_id IS NOT NULL AND lb.lead_session_id::text = zd.session_id THEN 2
                WHEN lb.lead_email      IS NOT NULL AND lower(lb.lead_email) = lower(zd.email) THEN 3
                ELSE 9
            END,
            zd.created_at ASC NULLS LAST
        LIMIT 1
    ) d ON TRUE
),
leads_atrib AS (
    -- Flags + tipo_atribuicao + prioridade. Usa ads_id_set pra distinguir
    -- 'ad_id_enriquecido_ads' (match em fdw) de 'ad_id_sem_match_ads' (órfão).
    SELECT
        r.*,
        (r.lead_classificacao IN ('Atua +12','Atua -12'))   AS flag_qualificado,
        (r.lead_classificacao =  'Atua +12')                AS flag_mais_12,
        (r.lead_classificacao =  'Atua -12')                AS flag_menos_12,
        (r.lead_classificacao =  'Não atua')                AS flag_nao_atua,
        (r.deal_id IS NOT NULL)                             AS flag_tem_deal,
        (r.deal_stage = 'Ganho')                            AS flag_ganho,
        (COALESCE(r.deal_valor_receita, 0) > 0)             AS flag_tem_receita,
        CASE
            WHEN r.lead_ad_id IS NOT NULL AND ai.ad_id IS NOT NULL THEN 'ad_id_enriquecido_ads'
            WHEN r.lead_ad_id IS NOT NULL AND ai.ad_id IS NULL     THEN 'ad_id_sem_match_ads'
            WHEN r.lead_ad_id IS NULL AND r.lead_campaign_id IS NOT NULL THEN 'campaign_id'
            WHEN r.lead_ad_id IS NULL AND r.lead_campaign_id IS NULL
                 AND (r.lead_utm_source   IS NOT NULL
                   OR r.lead_utm_campaign IS NOT NULL
                   OR r.lead_utm_content  IS NOT NULL) THEN 'utm_only'
            ELSE 'sem_atribuicao'
        END AS tipo_atribuicao,
        CASE
            WHEN r.lead_ad_id IS NOT NULL AND ai.ad_id IS NOT NULL THEN 1
            WHEN r.lead_ad_id IS NOT NULL AND ai.ad_id IS NULL     THEN 2
            WHEN r.lead_ad_id IS NULL AND r.lead_campaign_id IS NOT NULL THEN 3
            WHEN r.lead_ad_id IS NULL AND r.lead_campaign_id IS NULL
                 AND (r.lead_utm_source   IS NOT NULL
                   OR r.lead_utm_campaign IS NOT NULL
                   OR r.lead_utm_content  IS NOT NULL) THEN 4
            ELSE 5
        END AS prioridade_atribuicao
    FROM leads_resolved r
    LEFT JOIN ads_id_set ai ON ai.ad_id = r.lead_ad_id
),
leads_canonico AS (
    -- rn_lead_canonico: 1 lead canônico por (data_lead, email).
    -- rn_deal_canonico: 1 linha canônica POR DEAL — só calcula quando
    -- deal_id IS NOT NULL pra evitar janela monstro com todos os NULLs.
    SELECT
        l.*,
        ROW_NUMBER() OVER (
            PARTITION BY l.data_lead, l.lead_email_normalizado
            ORDER BY
                l.flag_ganho             DESC,
                l.flag_tem_receita       DESC,
                l.flag_tem_deal          DESC,
                l.prioridade_atribuicao  ASC,
                (l.lead_ad_id       IS NOT NULL) DESC,
                (l.lead_campaign_id IS NOT NULL) DESC,
                l.lead_created_at        DESC,
                l.lead_id
        ) AS rn_lead_canonico,
        CASE WHEN l.deal_id IS NOT NULL THEN
            ROW_NUMBER() OVER (
                PARTITION BY l.deal_id
                ORDER BY
                    l.flag_ganho             DESC,
                    l.flag_tem_receita       DESC,
                    l.prioridade_atribuicao  ASC,
                    (l.lead_ad_id       IS NOT NULL) DESC,
                    (l.lead_campaign_id IS NOT NULL) DESC,
                    l.deal_data_compra       DESC NULLS LAST,
                    l.lead_created_at        DESC,
                    l.lead_id
            )
        END AS rn_deal_canonico
    FROM leads_atrib l
),
leads_daily AS (
    SELECT
        data_lead AS data_ref,
        COUNT(*) FILTER (WHERE rn_lead_canonico = 1)                              AS leads_reais,
        COUNT(*) FILTER (WHERE rn_lead_canonico = 1 AND flag_qualificado)         AS leads_qualificados,
        COUNT(*) FILTER (WHERE rn_lead_canonico = 1 AND flag_mais_12)             AS leads_mais_12,
        COUNT(*) FILTER (WHERE rn_lead_canonico = 1 AND flag_menos_12)            AS leads_menos_12,
        COUNT(*) FILTER (WHERE rn_lead_canonico = 1 AND flag_nao_atua)            AS leads_nao_atua,
        COUNT(*) FILTER (WHERE rn_deal_canonico = 1)                              AS deals_atribuidos,
        COUNT(*) FILTER (WHERE rn_deal_canonico = 1 AND flag_ganho)               AS ganhos_atribuidos,
        SUM(deal_valor_venda)   FILTER (WHERE rn_deal_canonico = 1)               AS montante_atribuido,
        SUM(deal_valor_receita) FILTER (WHERE rn_deal_canonico = 1)               AS receita_atribuida
    FROM leads_canonico
    GROUP BY data_lead
),
comercial_daily AS (
    SELECT
        data_ref,
        SUM(montante)      AS montante_total_geral,
        SUM(receita)       AS receita_total_geral,
        SUM(novos)         AS vendas_novas_total_geral,
        SUM(vendas)        AS vendas_total_geral,
        SUM(oportunidades) AS oportunidades_total_geral,
        SUM(perdidos)      AS perdidos_total_geral,
        SUM(cancelados)    AS cancelados_total_geral
    FROM bi.vw_dashboard_comercial_executivas_rw
    WHERE data_ref BETWEEN :data_ini AND :data_fim
    GROUP BY data_ref
),
investimento_geral_daily AS (
    SELECT
        data_ref,
        SUM(investimento_total) AS investimento_total_geral
    FROM bi.vw_investimento_diario
    WHERE data_ref BETWEEN :data_ini AND :data_fim
    GROUP BY data_ref
),
keys AS (
    SELECT data_ref FROM ads_daily
    UNION
    SELECT data_ref FROM leads_daily
    UNION
    SELECT data_ref FROM comercial_daily
    UNION
    SELECT data_ref FROM investimento_geral_daily
)
SELECT
    k.data_ref,
    -- Bloco mídia
    COALESCE(a.investimento_midia, 0)::numeric        AS investimento_midia,
    COALESCE(a.impressoes, 0)::bigint                 AS impressoes,
    COALESCE(a.alcance, 0)::bigint                    AS alcance,
    COALESCE(a.cliques, 0)::bigint                    AS cliques,
    COALESCE(a.inline_link_clicks, 0)::bigint         AS inline_link_clicks,
    COALESCE(a.leads_meta, 0)::bigint                 AS leads_meta,
    COALESCE(a.pixel_lead, 0)::bigint                 AS pixel_lead,
    COALESCE(a.agendamentos_meta, 0)::bigint          AS agendamentos_meta,
    -- Bloco resultado atribuído (lead_tracking)
    COALESCE(l.leads_reais, 0)::bigint                AS leads_reais,
    COALESCE(l.leads_qualificados, 0)::bigint         AS leads_qualificados,
    COALESCE(l.leads_mais_12, 0)::bigint              AS leads_mais_12,
    COALESCE(l.leads_menos_12, 0)::bigint             AS leads_menos_12,
    COALESCE(l.leads_nao_atua, 0)::bigint             AS leads_nao_atua,
    COALESCE(l.deals_atribuidos, 0)::bigint           AS deals_atribuidos,
    COALESCE(l.ganhos_atribuidos, 0)::bigint          AS ganhos_atribuidos,
    COALESCE(l.montante_atribuido, 0)::numeric        AS montante_atribuido,
    COALESCE(l.receita_atribuida, 0)::numeric         AS receita_atribuida,
    -- Bloco total geral comercial (CRM)
    COALESCE(i.investimento_total_geral, 0)::numeric  AS investimento_total_geral,
    COALESCE(c.montante_total_geral, 0)::numeric      AS montante_total_geral,
    COALESCE(c.receita_total_geral, 0)::numeric       AS receita_total_geral,
    COALESCE(c.vendas_novas_total_geral, 0)::bigint   AS vendas_novas_total_geral,
    COALESCE(c.vendas_total_geral, 0)::bigint         AS vendas_total_geral,
    COALESCE(c.oportunidades_total_geral, 0)::bigint  AS oportunidades_total_geral,
    COALESCE(c.perdidos_total_geral, 0)::bigint       AS perdidos_total_geral,
    COALESCE(c.cancelados_total_geral, 0)::bigint     AS cancelados_total_geral,
    -- Ratios diários (recalculados sobre SUM no agregado do período pelo Python)
    CASE WHEN COALESCE(a.investimento_midia, 0) = 0 THEN 0::numeric
         ELSE COALESCE(l.montante_atribuido, 0) / a.investimento_midia
    END AS roas_montante_atribuido,
    CASE WHEN COALESCE(a.investimento_midia, 0) = 0 THEN 0::numeric
         ELSE COALESCE(l.receita_atribuida, 0)  / a.investimento_midia
    END AS roas_receita_atribuida,
    CASE WHEN COALESCE(i.investimento_total_geral, 0) = 0 THEN 0::numeric
         ELSE COALESCE(c.montante_total_geral, 0) / i.investimento_total_geral
    END AS roas_montante_total_geral,
    CASE WHEN COALESCE(i.investimento_total_geral, 0) = 0 THEN 0::numeric
         ELSE COALESCE(c.receita_total_geral, 0)  / i.investimento_total_geral
    END AS roas_receita_total_geral,
    CASE WHEN COALESCE(l.leads_reais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.investimento_midia, 0) / l.leads_reais
    END AS cpl_real,
    CASE WHEN COALESCE(l.leads_qualificados, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.investimento_midia, 0) / l.leads_qualificados
    END AS cpl_qualificado,
    CASE WHEN COALESCE(l.leads_mais_12, 0) = 0 THEN 0::numeric
         ELSE COALESCE(a.investimento_midia, 0) / l.leads_mais_12
    END AS cpl_mais_12
FROM keys k
LEFT JOIN ads_daily               a USING (data_ref)
LEFT JOIN leads_daily             l USING (data_ref)
LEFT JOIN comercial_daily         c USING (data_ref)
LEFT JOIN investimento_geral_daily i USING (data_ref)
ORDER BY k.data_ref;
