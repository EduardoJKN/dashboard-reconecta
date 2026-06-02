-- =============================================================================
-- Funil POR CRIATIVO (grão `ad_name` consolidado).
-- =============================================================================
-- 1 linha por `ad_name_norm` no período, com mídia + funil completo até venda
-- nova. Alimenta a seção "Funil do criativo selecionado" da página Criativos.
--
-- Match único viável: `lower(btrim(criativos.ad_name)) =
-- lower(btrim(leads.utm_content))`. Validado em pgAdmin: `ad_id` está vazio
-- em ext_reconecta.leads / zoho_deals / zoho_activities (0 preenchidos
-- em abr/2026), então não dá pra cruzar por id. Fuzzy/normalização extra
-- não compensa — utm_content é token estruturado.
--
-- Granularidade `ad_name`, NÃO `ad_id`. Mesmo criativo replicado em
-- vários ad_ids (CBO/A-B; média 4,9 ad_ids/ad_name em abr/2026, máx 51).
-- Soma mídia (invest/imp/cliques) dos ad_ids de mesmo nome; leads não
-- inflam porque utm_content é o nome.
--
-- ────────────────────────────────────────────────────────────────────────────
-- Mai/2026 — REVISÃO da atribuição lead↔deal e vendas deal-centric
-- (regra validada com a operação no período 10–16/mai):
--   * Match deal→lead: `email > telefone(>=8 dígitos)`. zoho_id REMOVIDO
--     (menos confiável que o e-mail na operação). session_id também
--     removido em iteração anterior.
--   * Atribuição CROSS-PERÍODO POR DEAL: para cada deal ganho, buscar
--     leads com `l.created_at <= d.data_hora_compra` em
--     `leads_atribuicao_vendas` (sem corte inferior — uma venda
--     pode atribuir a lead de qualquer tempo anterior). Antes,
--     `leads_atribuicao` restringia a `<= :data_fim` global e ainda
--     filtrava `utm_content IS NOT NULL`, inflando o bucket sintético.
--   * Desempate quando múltiplos leads pareiam o mesmo deal:
--       1. prio_match (email vence telefone)
--       2. origem_util DESC (leads com utm/link_in_bio/social vencem)
--       3. lead_created_at DESC (lead MAIS RECENTE antes da venda)
--       4. lead_id (determinístico)
--   * Vendas/montante/receita são DEAL-CENTRIC: percorremos os deals
--     ganhos no período e atribuímos cada um a 1 lead via DISTINCT ON.
--   * Bucket sintético `__sem_criativo_identificado__` agrega vendas sem
--     vínculo a lead com utm_content. UI exibe como "Sem criativo
--     identificado".
--   * Leads / +12-12-NA / agendamentos / comparecimentos continuam
--     LEAD-CENTRIC (igual antes) — universo do período por
--     (utm_content, email) via `leads_clean`.
--   * Dedup CRÍTICA: agregações de activities NÃO somam montante/receita
--     (essas vêm direto de deals_ganhos, evitando multiplicação por N
--     atividades do mesmo deal).
--
-- Deal → activity: zoho_activities.what_id = deal_id, activity_type IN
-- ('Consulta','Indicação'), start_datetime na janela. Comparecimento
-- exige status_reuniao='Concluída'.
-- Venda nova: deal stage IN ('Ganho','Fechado Ganho') AND
-- tipo_venda='Novo cliente'.
--
-- Validação abr/2026 (cross-checks alvo, regra ANTIGA — referência):
--   2025_SEM50_AD05            invest 16.967 · imp 191k · clk 2410 · qtd 51
--                              leads 155 · +12 55 · agend 49 · compar 29 · novas 4
--   2025_SEM40_AD02_1          leads 101 · +12 16 · agend 30 · compar 23 · novas 2
--   [26][16][AD013_1][AB] - Fazendo tudo sozinha
--                              leads 64  · +12 10 · agend 10 · compar 7  · novas 0
-- =============================================================================
WITH
-- -----------------------------------------------------------------------------
-- 1) Mídia consolidada por ad_name (soma os múltiplos ad_ids do mesmo nome).
-- -----------------------------------------------------------------------------
criativos AS (
    SELECT
        lower(btrim(ad_name))               AS ad_name_norm,
        ad_id,
        ad_name,
        campaign_name,
        adset_name,
        effective_status,
        quality_ranking,
        engagement_ranking,
        conversion_ranking,
        thumbnail_url,
        image_url,
        permalink_url,
        investimento,
        impressoes,
        cliques,
        link_clicks,
        alcance
    FROM bi.vw_mkt_criativos
    WHERE data_ref BETWEEN :data_ini AND :data_fim
      AND ad_name IS NOT NULL
      AND btrim(ad_name) <> ''
),
midia_agg AS (
    SELECT
        ad_name_norm,
        MAX(ad_name)                            AS ad_name,
        COUNT(DISTINCT ad_id)                   AS qtd_adids,
        SUM(investimento)::numeric              AS investimento,
        SUM(impressoes)::bigint                 AS impressoes,
        SUM(cliques)::bigint                    AS cliques,
        SUM(link_clicks)::bigint                AS link_clicks,
        SUM(alcance)::bigint                    AS alcance
    FROM criativos
    GROUP BY ad_name_norm
),
-- "Principal" por ad_name = a row do ad_id com maior investimento. Quebra
-- empate por max(data_ref) só pra ser determinístico.
midia_principal AS (
    SELECT DISTINCT ON (ad_name_norm)
        ad_name_norm,
        campaign_name                            AS campaign_name_principal,
        adset_name                               AS adset_name_principal,
        effective_status                         AS effective_status_principal,
        quality_ranking                          AS quality_ranking_principal,
        engagement_ranking                       AS engagement_ranking_principal,
        conversion_ranking                       AS conversion_ranking_principal,
        thumbnail_url,
        image_url,
        permalink_url
    FROM criativos
    ORDER BY ad_name_norm, investimento DESC NULLS LAST, ad_id
),

-- -----------------------------------------------------------------------------
-- 2) Leads — base limpa filtrada por utm_content casável com algum ad_name.
-- -----------------------------------------------------------------------------
-- `leads_clean`: base do PERÍODO. Usada para contagens lead-centric
-- (leads/+12-12-NA/agendamentos/comparecimentos do criativo no período).
-- A partir de mai/2026 NÃO filtra `utm_content IS NOT NULL` — leads sem
-- utm_content viram o bucket sintético `__sem_criativo_identificado__` via
-- COALESCE em `distinct_email_criativo`. Antes esses leads sumiam do
-- somatório do funil; agora aparecem como cidadãos próprios.
leads_clean AS (
    SELECT
        l.id::text                                              AS lead_id,
        lower(btrim(l.email))                                   AS email_norm,
        NULLIF(btrim(l.zoho_id), '')                            AS lead_zoho_id,
        regexp_replace(COALESCE(l.phone_number, ''), '\D', '', 'g') AS phone_clean,
        l.classificado,
        l.created_at,
        NULLIF(lower(btrim(l.utm_content)), '')                 AS utm_content_norm
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
-- `leads_atribuicao_vendas`: base CROSS-PERÍODO (até :data_fim como
-- pré-filtro de performance; restrição precisa `l.created_at <= d.data_hora_compra`
-- aplicada no JOIN de `deal_lead_matches`).
--
-- Diferença vs `leads_clean`:
--   * Sem corte inferior de período (lead pode ter vindo meses/anos antes).
--   * SEM filtro `utm_content IS NOT NULL` — queremos TODOS os leads pra
--     atribuir vendas. Leads sem utm_content acabam atribuindo a venda ao
--     bucket sintético '__sem_criativo_identificado__'; leads com
--     `utm_content='link_in_bio'` (ou similares) viram criativos próprios.
--   * Carrega `origem_util` (regra validada com a operação): considera útil
--     leads com utm_campaign OR utm_content preenchidos, ou explicitamente
--     link_in_bio / utm_source='linkbio' / utm_medium='social'.
leads_atribuicao_vendas AS (
    SELECT
        l.id::text                                                   AS lead_id,
        l.created_at                                                 AS lead_created_at,
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
-- 1 linha por (utm_content_norm, e-mail) — period-distinct. Permite que o
-- mesmo e-mail conte 1× em CADA criativo onde apareceu. Leads sem
-- utm_content caem no bucket `__sem_criativo_identificado__` via COALESCE
-- (leads_clean já entrega utm_content_norm como NULL quando ausente).
distinct_email_criativo AS (
    SELECT DISTINCT
        COALESCE(utm_content_norm, '__sem_criativo_identificado__')
                                                            AS utm_content_norm,
        email_norm
    FROM leads_clean
),
-- Última classificação POR E-MAIL no período (regra global, igual à
-- Visão Geral). Não depende do criativo — vale pra todas as rows do e-mail.
last_classif AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- Chaves do lead (zoho_id / phone_clean) pra alimentar o priority match.
-- Pega a row mais recente por e-mail (consistente com last_classif).
-- Nota: `session_id` foi REMOVIDO; nova prioridade é `email > zoho_id > phone`.
email_lead_keys AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        lead_zoho_id,
        phone_clean
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- Leads por ad_name (todos os filtros + classificação).
leads_por_criativo AS (
    SELECT
        dec.utm_content_norm                                    AS ad_name_norm,
        COUNT(*)::bigint                                        AS leads_totais,
        COUNT(*) FILTER (
            WHERE c.classif_final ILIKE '%+12%' OR c.classif_final ILIKE '%-12%'
        )::bigint                                               AS leads_qualificados,
        COUNT(*) FILTER (WHERE c.classif_final ILIKE '%+12%')::bigint
                                                                AS leads_mais_12,
        COUNT(*) FILTER (WHERE c.classif_final ILIKE '%-12%')::bigint
                                                                AS leads_menos_12,
        COUNT(*) FILTER (
            WHERE c.classif_final ILIKE '%não atua%'
        )::bigint                                               AS leads_nao_atua
    FROM distinct_email_criativo dec
    LEFT JOIN last_classif c USING (email_norm)
    GROUP BY dec.utm_content_norm
),

-- -----------------------------------------------------------------------------
-- 2b) Aplicações (typeform) — cruzamento por e-mail dos leads do criativo.
--     Universo: só e-mails com aplicação completa no período (dedupe/dia).
--     Agend./compar./vendas: subset desse universo (não todos os leads).
-- -----------------------------------------------------------------------------
aplicacoes_dedup AS (
    SELECT
        email_norm,
        classificado_norm
    FROM (
        SELECT
            lower(btrim(ta.email))              AS email_norm,
            lower(btrim(ta.classificado))       AS classificado_norm,
            ROW_NUMBER() OVER (
                PARTITION BY lower(btrim(ta.email)),
                             (ta.created_at - INTERVAL '3 hours')::date
                ORDER BY ta.created_at DESC
            ) AS rn
        FROM fdw_reconecta.typeform_aplicacoes ta
        WHERE (ta.created_at - INTERVAL '3 hours')::date BETWEEN :data_ini AND :data_fim
          AND ta.dados_completos IS TRUE
          AND ta.email IS NOT NULL
          AND btrim(ta.email) <> ''
          AND lower(btrim(ta.email)) NOT LIKE '%@teste%'
          AND lower(btrim(ta.email)) NOT LIKE '%teste@%'
          AND lower(btrim(ta.email)) NOT LIKE '%smarts%'
          AND lower(btrim(ta.email)) NOT LIKE '%reconecta%'
    ) sub
    WHERE rn = 1
),
-- (criativo, e-mail) — lead do período com utm_content + aplicação typeform.
aplicacoes_email_criativo AS (
    SELECT DISTINCT
        dec.utm_content_norm                                    AS ad_name_norm,
        ad.email_norm,
        ad.classificado_norm
    FROM distinct_email_criativo dec
    INNER JOIN aplicacoes_dedup ad USING (email_norm)
),
aplicacoes_por_criativo AS (
    SELECT
        ad_name_norm,
        COUNT(DISTINCT email_norm)::bigint                      AS aplicacoes,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua +12', 'atua+12', '+12')
        )::bigint                                               AS aplicacoes_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua -12', 'atua-12', '-12')
        )::bigint                                               AS aplicacoes_menos_12
    FROM aplicacoes_email_criativo
    GROUP BY ad_name_norm
),
-- Totais globais — e-mails distintos com lead + aplicação no período.
aplicacoes_emails_globais AS (
    SELECT DISTINCT
        ad.email_norm,
        ad.classificado_norm
    FROM leads_clean lc
    INNER JOIN aplicacoes_dedup ad ON ad.email_norm = lc.email_norm
),
aplicacoes_emails_vinculados AS (
    SELECT DISTINCT
        ad.email_norm,
        ad.classificado_norm
    FROM leads_clean lc
    INNER JOIN aplicacoes_dedup ad ON ad.email_norm = lc.email_norm
    WHERE lc.utm_content_norm IS NOT NULL
),
aplicacoes_globais AS (
    SELECT
        COUNT(DISTINCT email_norm)::bigint                      AS aplicacoes,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua +12', 'atua+12', '+12')
        )::bigint                                               AS aplicacoes_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua -12', 'atua-12', '-12')
        )::bigint                                               AS aplicacoes_menos_12
    FROM aplicacoes_emails_globais
),
aplicacoes_vinculados AS (
    SELECT
        COUNT(DISTINCT email_norm)::bigint                      AS aplicacoes,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua +12', 'atua+12', '+12')
        )::bigint                                               AS aplicacoes_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classificado_norm IN ('atua -12', 'atua-12', '-12')
        )::bigint                                               AS aplicacoes_menos_12
    FROM aplicacoes_emails_vinculados
),

-- -----------------------------------------------------------------------------
-- 3) Lead → Deal (lead-centric) — usado APENAS por agendamentos/comparecimentos.
--    Nova prioridade `email > zoho_id > phone_clean (>=8 dígitos)`.
--    `lead_zoho_id` e `phone_clean` continuam como fallback; e-mail é primário.
-- -----------------------------------------------------------------------------
all_deal_matches AS (
    -- prio 1: email normalizado (chave principal segundo a operação)
    SELECT elk.email_norm, zd.id AS deal_id, zd.stage AS deal_stage,
           zd.tipo_venda AS deal_tipo_venda, zd.created_at AS deal_created_at,
           1 AS prio
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = elk.email_norm
    WHERE elk.email_norm IS NOT NULL AND elk.email_norm <> ''

    UNION ALL

    -- prio 2: zoho_id (fallback)
    SELECT elk.email_norm, zd.id, zd.stage, zd.tipo_venda, zd.created_at, 2
    FROM email_lead_keys elk
    JOIN zoho_deals zd ON zd.id = elk.lead_zoho_id
    WHERE elk.lead_zoho_id IS NOT NULL

    UNION ALL

    -- prio 3: telefone limpo (fallback final; mínimo 8 dígitos pra evitar
    --         match espúrio em telefones curtos/mal preenchidos)
    SELECT elk.email_norm, zd.id, zd.stage, zd.tipo_venda, zd.created_at, 3
    FROM email_lead_keys elk
    JOIN zoho_deals zd
      ON length(elk.phone_clean) >= 8
     AND regexp_replace(COALESCE(zd.telefone, ''), '\D', '', 'g') = elk.phone_clean
),
leads_with_deal AS (
    -- 1 deal por e-mail. Prioridade + deal mais recente como tiebreaker.
    SELECT DISTINCT ON (email_norm)
        email_norm,
        deal_id,
        deal_stage,
        deal_tipo_venda
    FROM all_deal_matches
    ORDER BY email_norm, prio, deal_created_at DESC NULLS LAST
),

-- -----------------------------------------------------------------------------
-- 4) Activities (agendamentos / comparecimentos) — lead-centric, igual antes.
--    Mantém COUNT(DISTINCT email_norm). NÃO soma montante/receita aqui — esses
--    valores vêm direto de `deals_ganhos` (deal-centric, sem inflar por
--    múltiplas atividades do mesmo deal).
-- -----------------------------------------------------------------------------
activities_in_window AS (
    -- Exclui atividades com `status_reuniao` vencido (qualquer variação
    -- de grafia — "Vencida", "Vencido", etc.). Alinha com a regra da
    -- view bi.vw_dashboard_comercial_executivas_rw pós-mai/2026:
    -- `agendamentos` é líquido de Vencida. `status_reuniao = NULL` passa
    -- (defensivo — activity sem status definido pode ser agendamento
    -- futuro). Comparecimento exige explicitamente 'Concluída', então
    -- vencidos já estariam fora do compar — o filtro só pesa em
    -- `agendamentos`.
    SELECT
        lwd.email_norm,
        za.id            AS activity_id,
        za.status_reuniao
    FROM leads_with_deal lwd
    JOIN zoho_activities za ON za.what_id = lwd.deal_id
    WHERE lwd.deal_id IS NOT NULL
      AND za.activity_type IN ('Consulta', 'Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
      AND COALESCE(za.status_reuniao, '') NOT ILIKE '%vencid%'
),
agend_compar_por_criativo AS (
    SELECT
        dec.utm_content_norm                                    AS ad_name_norm,
        COUNT(DISTINCT a.email_norm)::bigint                    AS agendamentos,
        COUNT(DISTINCT a.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos
    FROM distinct_email_criativo dec
    LEFT JOIN activities_in_window a USING (email_norm)
    GROUP BY dec.utm_content_norm
),
agend_compar_aplicacoes AS (
    SELECT
        aec.ad_name_norm,
        COUNT(DISTINCT aec.email_norm) FILTER (
            WHERE a.activity_id IS NOT NULL
        )::bigint                                               AS agendamentos_apl,
        COUNT(DISTINCT aec.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos_apl
    FROM aplicacoes_email_criativo aec
    LEFT JOIN activities_in_window a ON a.email_norm = aec.email_norm
    GROUP BY aec.ad_name_norm
),
agend_compar_aplicacoes_globais AS (
    SELECT
        COUNT(DISTINCT aeg.email_norm) FILTER (
            WHERE a.activity_id IS NOT NULL
        )::bigint                                               AS agendamentos_apl,
        COUNT(DISTINCT aeg.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos_apl
    FROM aplicacoes_emails_globais aeg
    LEFT JOIN activities_in_window a ON a.email_norm = aeg.email_norm
),
agend_compar_aplicacoes_vinculados AS (
    SELECT
        COUNT(DISTINCT aev.email_norm) FILTER (
            WHERE a.activity_id IS NOT NULL
        )::bigint                                               AS agendamentos_apl,
        COUNT(DISTINCT aev.email_norm) FILTER (
            WHERE a.status_reuniao = 'Concluída'
        )::bigint                                               AS comparecimentos_apl
    FROM aplicacoes_emails_vinculados aev
    LEFT JOIN activities_in_window a ON a.email_norm = aev.email_norm
),

-- -----------------------------------------------------------------------------
-- 5) ✨ VENDAS deal-centric — percorre os deals ganhos no período e atribui
--    cada um a UM lead (DISTINCT ON deal_id, prioridade email > zoho_id >
--    phone, tiebreaker `lead mais antigo`). Deals sem lead pareável → bucket
--    sintético `__sem_criativo_identificado__`.
-- -----------------------------------------------------------------------------
deals_ganhos AS (
    SELECT
        d.id::text                                              AS deal_id,
        d.data_hora_compra                                      AS data_venda_ts,
        d.data_hora_compra::date                                AS data_venda,
        lower(btrim(d.email))                                   AS deal_email_norm,
        regexp_replace(COALESCE(d.telefone, ''), '\D', '', 'g') AS deal_phone_clean
    FROM zoho_deals d
    WHERE d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
deal_lead_matches AS (
    -- Regra validada na operação (10-16/mai/2026):
    --   * Match: email primário, telefone como fallback (zoho_id removido —
    --     menos confiável que o e-mail).
    --   * Restrição cross-período: `l.created_at <= g.data_venda_ts` por
    --     deal (não restringe ao período do dashboard) — uma venda do
    --     período pode ter vindo de um lead criado em qualquer momento
    --     antes dela.
    --   * Carrega `tipo_match` ('email'/'telefone') pra auditoria e
    --     `origem_util` (boolean→int) pra desempate.
    --
    -- prio 1: email
    SELECT g.deal_id, l.lead_id, l.utm_content_norm,
           l.lead_created_at, l.origem_util,
           1 AS prio_match, 'email'::text AS tipo_match
    FROM deals_ganhos g
    JOIN leads_atribuicao_vendas l
      ON l.email_norm = g.deal_email_norm
     AND g.deal_email_norm <> ''
     AND l.lead_created_at <= g.data_venda_ts

    UNION ALL

    -- prio 2: telefone limpo (>=8 dígitos em ambos os lados)
    SELECT g.deal_id, l.lead_id, l.utm_content_norm,
           l.lead_created_at, l.origem_util,
           2 AS prio_match, 'telefone'::text AS tipo_match
    FROM deals_ganhos g
    JOIN leads_atribuicao_vendas l
      ON length(l.phone_clean) >= 8
     AND length(g.deal_phone_clean) >= 8
     AND l.phone_clean = g.deal_phone_clean
     AND l.lead_created_at <= g.data_venda_ts
),
deal_attributed_lead AS (
    -- 1 lead por deal. Ordem:
    --   1. prio_match (email=1 antes de telefone=2)
    --   2. origem_util DESC (leads com utm/link_in_bio/social vencem)
    --   3. lead_created_at DESC (lead MAIS RECENTE antes da venda)
    --   4. lead_id (desempate determinístico final)
    SELECT DISTINCT ON (deal_id)
        deal_id, lead_id, utm_content_norm, prio_match, tipo_match,
        origem_util, lead_created_at
    FROM deal_lead_matches
    ORDER BY deal_id, prio_match,
             origem_util DESC,
             lead_created_at DESC,
             lead_id
),
-- Vendas por criativo via atribuição deal→lead.
-- Deals sem lead pareável (LEFT JOIN sem match) caem no bucket sintético.
vendas_por_criativo AS (
    SELECT
        COALESCE(dal.utm_content_norm, '__sem_criativo_identificado__')
                                                                AS ad_name_norm,
        COUNT(DISTINCT g.deal_id)::bigint                       AS vendas_novas
    FROM deals_ganhos g
    LEFT JOIN deal_attributed_lead dal USING (deal_id)
    GROUP BY 1
),

vendas_aplicacoes_por_criativo AS (
    SELECT
        aec.ad_name_norm,
        COUNT(DISTINCT g.deal_id)::bigint                       AS vendas_aplicacoes
    FROM deals_ganhos g
    INNER JOIN deal_attributed_lead dal USING (deal_id)
    INNER JOIN leads_atribuicao_vendas l ON l.lead_id = dal.lead_id
    INNER JOIN aplicacoes_email_criativo aec
        ON aec.email_norm = l.email_norm
       AND aec.ad_name_norm = COALESCE(
               dal.utm_content_norm, '__sem_criativo_identificado__'
           )
    GROUP BY aec.ad_name_norm
),
vendas_aplicacoes_globais AS (
    SELECT COUNT(DISTINCT g.deal_id)::bigint                    AS vendas_aplicacoes
    FROM deals_ganhos g
    INNER JOIN deal_attributed_lead dal USING (deal_id)
    INNER JOIN leads_atribuicao_vendas l ON l.lead_id = dal.lead_id
    WHERE l.email_norm IN (SELECT email_norm FROM aplicacoes_emails_globais)
),
vendas_aplicacoes_vinculados AS (
    SELECT COUNT(DISTINCT g.deal_id)::bigint                    AS vendas_aplicacoes
    FROM deals_ganhos g
    INNER JOIN deal_attributed_lead dal USING (deal_id)
    INNER JOIN leads_atribuicao_vendas l ON l.lead_id = dal.lead_id
    WHERE l.email_norm IN (SELECT email_norm FROM aplicacoes_emails_vinculados)
),

-- -----------------------------------------------------------------------------
-- 6) Universo: união dos ad_names — preserva criativos com invest mas sem
--    leads (funil zerado pós-clique) e o bucket sintético de vendas sem
--    criativo identificado.
-- -----------------------------------------------------------------------------
universo AS (
    SELECT ad_name_norm FROM midia_agg
    UNION
    SELECT ad_name_norm FROM leads_por_criativo
    UNION
    SELECT ad_name_norm FROM vendas_por_criativo
)

SELECT
    u.ad_name_norm,
    -- Identificação
    COALESCE(
        ma.ad_name,
        CASE WHEN u.ad_name_norm = '__sem_criativo_identificado__'
             THEN 'Sem criativo identificado'
             ELSE u.ad_name_norm
        END
    )                                                           AS ad_name,
    mp.campaign_name_principal                                  AS campaign_name,
    mp.adset_name_principal                                     AS adset_name,
    mp.effective_status_principal                               AS effective_status,
    mp.quality_ranking_principal                                AS quality_ranking,
    mp.engagement_ranking_principal                             AS engagement_ranking,
    mp.conversion_ranking_principal                             AS conversion_ranking,
    mp.thumbnail_url                                            AS thumbnail_url,
    mp.image_url                                                AS image_url,
    mp.permalink_url                                            AS permalink_url,
    COALESCE(ma.qtd_adids, 0)::bigint                           AS qtd_adids,
    -- Mídia
    COALESCE(ma.investimento, 0)::numeric                       AS investimento,
    COALESCE(ma.impressoes, 0)::bigint                          AS impressoes,
    COALESCE(ma.cliques, 0)::bigint                             AS cliques,
    COALESCE(ma.link_clicks, 0)::bigint                         AS link_clicks,
    COALESCE(ma.alcance, 0)::bigint                             AS alcance,
    CASE WHEN COALESCE(ma.impressoes, 0) = 0 THEN 0::numeric
         ELSE ma.cliques::numeric / ma.impressoes * 100
    END                                                         AS ctr,
    CASE WHEN COALESCE(ma.cliques, 0) = 0 THEN 0::numeric
         ELSE ma.investimento / ma.cliques
    END                                                         AS cpc,
    -- Leads (lead-centric)
    COALESCE(lpc.leads_totais, 0)::bigint                       AS leads_totais,
    COALESCE(lpc.leads_qualificados, 0)::bigint                 AS leads_qualificados,
    COALESCE(lpc.leads_mais_12, 0)::bigint                      AS leads_mais_12,
    COALESCE(lpc.leads_menos_12, 0)::bigint                     AS leads_menos_12,
    COALESCE(lpc.leads_nao_atua, 0)::bigint                     AS leads_nao_atua,
    -- Funil — agend/compar (lead-centric) + vendas (deal-centric)
    COALESCE(acpc.agendamentos, 0)::bigint                      AS agendamentos,
    COALESCE(acpc.comparecimentos, 0)::bigint                   AS comparecimentos,
    COALESCE(vpc.vendas_novas, 0)::bigint                       AS vendas_novas,
    -- Funil de aplicações (typeform → subset com agend/compar/venda)
    COALESCE(apc.aplicacoes, 0)::bigint                         AS aplicacoes,
    COALESCE(apc.aplicacoes_mais_12, 0)::bigint                  AS aplicacoes_mais_12,
    COALESCE(apc.aplicacoes_menos_12, 0)::bigint                 AS aplicacoes_menos_12,
    COALESCE(aapl.agendamentos_apl, 0)::bigint                  AS agendamentos_apl,
    COALESCE(aapl.comparecimentos_apl, 0)::bigint               AS comparecimentos_apl,
    COALESCE(vapl.vendas_aplicacoes, 0)::bigint                 AS vendas_aplicacoes,
    -- Totais globais de aplicações (repetidos em cada row — UI usa em opções sintéticas)
    ag.aplicacoes::bigint                                       AS aplicacoes_globais,
    ag.aplicacoes_mais_12::bigint                               AS aplicacoes_mais_12_globais,
    ag.aplicacoes_menos_12::bigint                              AS aplicacoes_menos_12_globais,
    acag.agendamentos_apl::bigint                               AS agendamentos_apl_globais,
    acag.comparecimentos_apl::bigint                            AS comparecimentos_apl_globais,
    vag.vendas_aplicacoes::bigint                               AS vendas_aplicacoes_globais,
    av.aplicacoes::bigint                                       AS aplicacoes_vinculados,
    av.aplicacoes_mais_12::bigint                               AS aplicacoes_mais_12_vinculados,
    av.aplicacoes_menos_12::bigint                              AS aplicacoes_menos_12_vinculados,
    acav.agendamentos_apl::bigint                               AS agendamentos_apl_vinculados,
    acav.comparecimentos_apl::bigint                            AS comparecimentos_apl_vinculados,
    vav.vendas_aplicacoes::bigint                               AS vendas_aplicacoes_vinculados,
    -- Derivadas
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(lpc.leads_qualificados, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_qualificacao,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(lpc.leads_mais_12, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_mais_12,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(acpc.agendamentos, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_agendamento,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(acpc.comparecimentos, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_comparecimento,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(vpc.vendas_novas, 0)::numeric / lpc.leads_totais * 100
    END                                                         AS taxa_lead_venda_nova,
    CASE WHEN COALESCE(lpc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / lpc.leads_totais
    END                                                         AS cpl,
    CASE WHEN COALESCE(lpc.leads_mais_12, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / lpc.leads_mais_12
    END                                                         AS cpl_mais_12,
    CASE WHEN COALESCE(vpc.vendas_novas, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ma.investimento, 0) / vpc.vendas_novas
    END                                                         AS cac,
    -- Derivadas — funil de aplicações (denominador = aplicacoes)
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(apc.aplicacoes_mais_12, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_aplicacao_mais_12,
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(aapl.agendamentos_apl, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_apl_agendamento,
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(aapl.comparecimentos_apl, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_apl_comparecimento,
    CASE WHEN COALESCE(apc.aplicacoes, 0) = 0 THEN 0::numeric
         ELSE COALESCE(vapl.vendas_aplicacoes, 0)::numeric / apc.aplicacoes * 100
    END                                                         AS taxa_apl_venda_nova
FROM universo u
CROSS JOIN aplicacoes_globais ag
CROSS JOIN aplicacoes_vinculados av
CROSS JOIN agend_compar_aplicacoes_globais acag
CROSS JOIN agend_compar_aplicacoes_vinculados acav
CROSS JOIN vendas_aplicacoes_globais vag
CROSS JOIN vendas_aplicacoes_vinculados vav
LEFT JOIN midia_agg                  ma   USING (ad_name_norm)
LEFT JOIN midia_principal            mp   USING (ad_name_norm)
LEFT JOIN leads_por_criativo         lpc  USING (ad_name_norm)
LEFT JOIN agend_compar_por_criativo  acpc USING (ad_name_norm)
LEFT JOIN vendas_por_criativo        vpc  USING (ad_name_norm)
LEFT JOIN aplicacoes_por_criativo    apc  USING (ad_name_norm)
LEFT JOIN agend_compar_aplicacoes    aapl USING (ad_name_norm)
LEFT JOIN vendas_aplicacoes_por_criativo vapl USING (ad_name_norm)
ORDER BY investimento DESC NULLS LAST, vendas_novas DESC NULLS LAST,
         leads_totais DESC NULLS LAST;
