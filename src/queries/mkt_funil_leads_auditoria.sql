-- =============================================================================
-- Auditoria nome-a-nome das VENDAS de um criativo OU campanha selecionado.
-- =============================================================================
-- 1 linha por deal ganho no período, exibindo deal + lead atribuído + tipo
-- de match. Espelha exatamente a regra de atribuição usada em
-- mkt_criativo_funil.sql / mkt_campanha_funil.sql (cross-período por deal,
-- prioridade email > telefone, desempate origem_util DESC + lead mais
-- recente antes da venda).
--
-- Params:
--   :data_ini, :data_fim    — janela de vendas (data_hora_compra::date)
--   :nivel                  — 'criativo' ou 'campanha' (determina a coluna
--                              filtrada: utm_content vs utm_campaign)
--   :item_norm              — valor do bucket selecionado no funil.
--                              Pode ser um `utm_content`/`utm_campaign`
--                              normalizado (lower+btrim), os buckets
--                              sintéticos '__sem_criativo_identificado__'
--                              / '__sem_campanha_identificada__' (vendas
--                              sem lead atribuído ou sem o utm relevante),
--                              ou '__todos__' (todas as vendas do período,
--                              sem filtro de criativo/campanha).
--
-- IMPORTANTE: 1 linha por deal_id. Não faz JOIN com `zoho_activities` —
-- montante/data_venda vêm direto de `zoho_deals`, evitando multiplicação
-- por múltiplas atividades do mesmo deal.
-- =============================================================================
WITH
deals_ganhos AS (
    SELECT
        d.id::text                                              AS deal_id,
        d.data_hora_compra                                      AS data_venda_ts,
        d.data_hora_compra::date                                AS data_venda,
        d.deal_name                                             AS deal_name,
        d.email                                                 AS deal_email,
        d.telefone                                              AS deal_telefone,
        lower(btrim(d.email))                                   AS deal_email_norm,
        regexp_replace(COALESCE(d.telefone, ''), '\D', '', 'g') AS deal_phone_clean,
        CASE
            WHEN NULLIF(btrim(d.amount), '') IS NULL THEN 0::numeric
            ELSE replace(replace(regexp_replace(btrim(d.amount),
                 '[^0-9,.-]', '', 'g'), '.', ''), ',', '.')::numeric
        END                                                     AS montante
    FROM zoho_deals d
    WHERE d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
leads_atribuicao_vendas AS (
    -- Mesma regra das queries de funil (mkt_criativo_funil /
    -- mkt_campanha_funil). Replicada literalmente pra a auditoria refletir
    -- 1:1 a atribuição usada no gráfico/tabela do funil.
    SELECT
        l.id::text                                                   AS lead_id,
        l.created_at                                                 AS lead_created_at,
        l.first_name                                                 AS lead_first_name,
        l.email                                                      AS lead_email,
        l.phone_number                                               AS lead_phone_number,
        l.classificado                                               AS lead_classificado,
        l.utm_source                                                 AS lead_utm_source,
        l.utm_medium                                                 AS lead_utm_medium,
        l.utm_campaign                                               AS lead_utm_campaign,
        l.utm_content                                                AS lead_utm_content,
        lower(btrim(l.email))                                        AS email_norm,
        regexp_replace(COALESCE(l.phone_number, ''), '\D', '', 'g')  AS phone_clean,
        lower(btrim(l.utm_content))                                  AS utm_content_norm,
        lower(btrim(l.utm_campaign))                                 AS utm_campaign_norm,
        CASE
            WHEN NULLIF(btrim(l.utm_campaign), '') IS NOT NULL THEN 1
            WHEN NULLIF(btrim(l.utm_content), '')  IS NOT NULL THEN 1
            WHEN lower(btrim(COALESCE(l.utm_content, ''))) = 'link_in_bio' THEN 1
            WHEN lower(COALESCE(l.utm_source, '')) IN ('linkbio','link_in_bio') THEN 1
            WHEN lower(COALESCE(l.utm_medium, '')) = 'social' THEN 1
            ELSE 0
        END                                                          AS origem_util
    FROM ext_reconecta.leads l
    WHERE l.created_at::date <= :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
deal_lead_matches AS (
    -- email primário, telefone fallback, cross-período por deal.
    SELECT g.deal_id, l.lead_id, l.lead_created_at, l.origem_util,
           1 AS prio_match, 'email'::text AS tipo_match
    FROM deals_ganhos g
    JOIN leads_atribuicao_vendas l
      ON l.email_norm = g.deal_email_norm
     AND g.deal_email_norm <> ''
     AND l.lead_created_at <= g.data_venda_ts

    UNION ALL

    SELECT g.deal_id, l.lead_id, l.lead_created_at, l.origem_util,
           2 AS prio_match, 'telefone'::text AS tipo_match
    FROM deals_ganhos g
    JOIN leads_atribuicao_vendas l
      ON length(l.phone_clean) >= 8
     AND length(g.deal_phone_clean) >= 8
     AND l.phone_clean = g.deal_phone_clean
     AND l.lead_created_at <= g.data_venda_ts
),
deal_attributed_lead AS (
    SELECT DISTINCT ON (deal_id)
        deal_id, lead_id, tipo_match, origem_util, lead_created_at
    FROM deal_lead_matches
    ORDER BY deal_id, prio_match,
             origem_util DESC,
             lead_created_at DESC,
             lead_id
),
linhas AS (
    -- Junta deal + lead atribuído. Deals sem lead → tipo_match='sem_match'.
    SELECT
        g.data_venda,
        g.deal_name                                             AS nome_deal,
        g.deal_email                                            AS email_deal,
        g.deal_telefone                                         AS telefone_deal,
        g.montante,
        l.lead_created_at::date                                 AS data_lead,
        CASE
            WHEN l.lead_created_at IS NULL THEN NULL
            ELSE (g.data_venda - l.lead_created_at::date)
        END                                                     AS dias_lead_venda,
        l.lead_first_name                                       AS nome_lead,
        l.lead_email                                            AS email_lead,
        l.lead_phone_number                                     AS telefone_lead,
        l.lead_classificado                                     AS classificacao,
        CASE
            WHEN l.lead_id IS NULL
                THEN 'Sem origem identificada'
            WHEN NULLIF(btrim(l.lead_utm_content), '') IS NOT NULL
              OR NULLIF(btrim(l.lead_utm_campaign), '') IS NOT NULL
                THEN 'Campanha/criativo identificado'
            WHEN lower(btrim(COALESCE(l.lead_utm_content, ''))) = 'link_in_bio'
              OR lower(COALESCE(l.lead_utm_source, '')) IN ('linkbio','link_in_bio')
                THEN 'Link in bio'
            WHEN lower(COALESCE(l.lead_utm_medium, '')) = 'social'
              OR lower(COALESCE(l.lead_utm_source, '')) IN
                 ('instagram','facebook','meta','tiktok','linkedin','youtube')
                THEN 'Social sem campanha/criativo'
            ELSE 'Sem origem identificada'
        END                                                     AS tipo_origem,
        l.lead_utm_source                                       AS utm_source,
        l.lead_utm_medium                                       AS utm_medium,
        l.lead_utm_campaign                                     AS campanha_atribuida,
        l.lead_utm_content                                      AS criativo_atribuido,
        COALESCE(dal.tipo_match, 'sem_match')                   AS tipo_match,
        'priority email>telefone · cross-período · '
        'desempate origem_util DESC + lead mais recente antes da venda'
                                                                AS regra_atribuicao,
        -- chaves internas pra WHERE
        l.utm_content_norm,
        l.utm_campaign_norm,
        dal.lead_id                                             AS dal_lead_id
    FROM deals_ganhos g
    LEFT JOIN deal_attributed_lead dal     ON dal.deal_id = g.deal_id
    LEFT JOIN leads_atribuicao_vendas l    ON l.lead_id   = dal.lead_id
)
SELECT
    data_venda,
    nome_deal,
    email_deal,
    telefone_deal,
    montante,
    data_lead,
    dias_lead_venda,
    nome_lead,
    email_lead,
    telefone_lead,
    classificacao,
    tipo_origem,
    utm_source,
    utm_medium,
    campanha_atribuida,
    criativo_atribuido,
    tipo_match,
    regra_atribuicao
FROM linhas
WHERE
    -- Todos os resultados: retorna todas as vendas do período sem filtro.
    :item_norm = '__todos__'

    -- Bucket sintético: vendas sem lead atribuído OU lead sem o utm do nível.
    OR (
        :item_norm IN ('__sem_criativo_identificado__',
                       '__sem_campanha_identificada__')
        AND (
            dal_lead_id IS NULL
            OR (:nivel = 'criativo' AND COALESCE(utm_content_norm, '') = '')
            OR (:nivel = 'campanha' AND COALESCE(utm_campaign_norm, '') = '')
        )
    )
    -- Criativo selecionado (utm_content_norm = :item_norm)
    OR (
        :nivel = 'criativo'
        AND :item_norm NOT IN ('__todos__',
                                '__sem_criativo_identificado__',
                                '__sem_campanha_identificada__')
        AND utm_content_norm = :item_norm
    )
    -- Campanha selecionada (utm_campaign_norm = :item_norm)
    OR (
        :nivel = 'campanha'
        AND :item_norm NOT IN ('__todos__',
                                '__sem_criativo_identificado__',
                                '__sem_campanha_identificada__')
        AND utm_campaign_norm = :item_norm
    )
ORDER BY data_venda DESC, nome_deal;
