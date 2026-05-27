-- =============================================================================
-- Oportunidades × Agendamentos × Vendas por SDR/Pré-vendas — base
-- "Indicadores por Pré-vendas" na Visão Geral Pré-vendas.
-- =============================================================================
-- Grão devolvido: 1 row por (sdr, classif_bucket).
--   - oportunidades = COUNT(DISTINCT deal_id) criados no período
--   - agendamentos  = COUNT(DISTINCT activity_id) Consulta/Indicação no período
--   - vendas        = COUNT(DISTINCT deal_id) ganhos no período
-- O Python pivota para 1 row por SDR com colunas por bucket e calcula:
--   % Agendamento = Agend / Oport
--   % Conversão   = Vendas / Agendamentos  (padrão Looker)
--
-- Universos INDEPENDENTES por métrica — não restringimos vendas/agendamentos
-- a "deals criados no período". Isso replica o padrão Looker
-- (SUM(vendas) / SUM(agendamentos) ambos do período, sem amarrar a um
-- universo único). Consequência: % Agend. +12 ou % Agend. -12 podem
-- passar de 100% quando o agendamento cai no período mas a oportunidade
-- que o originou foi criada antes — o usuário aceita esse comportamento
-- enquanto o foco é nomear corretamente cada métrica.
--
-- Atribuição de SDR — cascata canônica do projeto:
--   1) activity.prevendas mais recente do deal (Consulta/Indicação)
--   2) deal.sdr_ss → zoho_users (TRIM(first_name || ' ' || last_name))
--   3) 'Sem SDR'
-- SDR é resolvido NO NÍVEL DO DEAL (não da activity individual) — assim
-- todas as métricas do mesmo deal são atribuídas ao mesmo SDR. Diverge
-- ligeiramente de prevendas_por_sdr.sql, que resolve por activity; o
-- impacto prático é mínimo (um deal raramente tem activities com
-- prevendas distintas) e o ganho é coerência: oportunidade, agendamentos
-- e venda do mesmo deal somam para o mesmo SDR.
--
-- Classificação +12 / -12 / Não atua / Sem classif — PRIORIDADE EXCLUSIVA
-- (substitui o OR combinado que duplicava deals em +12 e -12 quando CRM
-- e ext.leads divergiam). Ordem das fontes:
--   1. zoho_deals.lead_classification
--   2. zoho_deals.qualificacao         (CRM, manual da gestoria)
--   3. zoho_deals.classificado_cal
--   4. ext_reconecta.leads.classificado (ext, dedup por zoho_id)
-- Primeira fonte com valor IN ('Atua +12','Atua -12','Não atua') decide.
-- Sem nenhum válido → 'Sem classificação'. Buckets mutuamente exclusivos.
--
-- Agendamentos: activities Consulta/Indicação com status_reuniao IS NOT
-- NULL cujo `created_time::date` OU `start_datetime::date` cai no
-- período. Mesma janela usada em prevendas_overview_diario.sql:123-126.
--
-- Vendas: deals com stage IN ('Ganho','Fechado Ganho') AND tipo_venda =
-- 'Novo cliente' AND data_hora_compra::date no período. Mesma regra de
-- prevendas_overview_diario_por_sdr.sql.
-- =============================================================================
WITH deals_periodo AS (
    -- Universo de oportunidades: deals criados no período.
    SELECT d.id::text AS deal_id
    FROM zoho_deals d
    WHERE d.created_at::date BETWEEN :data_ini AND :data_fim
),
acts_no_periodo AS (
    -- Activities (= agendamentos) no período. Normaliza what_id (Zoho às
    -- vezes embrulha o id num JSON pequeno; mesma normalização de
    -- prevendas_leads_detalhe_diario.sql).
    SELECT
        a.id::text                              AS activity_id,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END                                     AS deal_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND (
          a.created_time::date     BETWEEN :data_ini AND :data_fim
          OR a.start_datetime::date BETWEEN :data_ini AND :data_fim
      )
),
deals_ganhos_periodo AS (
    -- Universo de vendas: deals ganhos novos no período (mesma regra dos
    -- cards: stage Ganho/Fechado Ganho + tipo_venda Novo cliente).
    SELECT d.id::text AS deal_id
    FROM zoho_deals d
    WHERE d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
deals_relevantes AS (
    -- União dos 3 universos. Deal participa de pelo menos uma métrica.
    -- Evita CTEs duplicadas pra deal_classif / sdr_via_activity.
    SELECT deal_id FROM deals_periodo
    UNION
    SELECT deal_id FROM acts_no_periodo
        WHERE deal_id IS NOT NULL AND deal_id <> ''
    UNION
    SELECT deal_id FROM deals_ganhos_periodo
),
-- ext.leads DEDUPLICADO por zoho_id, com filtro de e-mails teste —
-- 1 row por zoho_id, sempre a versão MAIS RECENTE.
ext_leads_dedup AS (
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text  AS deal_id,
        l.classificado   AS ext_classif
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
      AND (
          l.email IS NULL
          OR (
              btrim(l.email) <> ''
              AND lower(l.email) NOT LIKE '%@teste%'
              AND lower(l.email) NOT LIKE 'teste@%'
              AND lower(l.email) NOT LIKE '%smarts%'
              AND lower(l.email) NOT LIKE '%reconecta%'
          )
      )
    ORDER BY l.zoho_id::text, l."timestamp" DESC NULLS LAST, l.id DESC
),
deal_classif_raw AS (
    -- classif_final EXCLUSIVA via CASE prioridade. Sem fan-out: ext.leads
    -- vem 1 row por zoho_id, zoho_deals tem 1 row por deal.
    SELECT
        dr.deal_id,
        CASE
            WHEN NULLIF(btrim(d.lead_classification), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.lead_classification), '')
            WHEN NULLIF(btrim(d.qualificacao), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.qualificacao), '')
            WHEN NULLIF(btrim(d.classificado_cal), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.classificado_cal), '')
            WHEN NULLIF(btrim(eld.ext_classif), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(eld.ext_classif), '')
            ELSE 'Sem classificação'
        END                                     AS classif_final
    FROM deals_relevantes dr
    JOIN zoho_deals d           ON d.id::text = dr.deal_id
    LEFT JOIN ext_leads_dedup eld ON eld.deal_id = d.id::text
),
deal_classif AS (
    SELECT
        deal_id,
        classif_final,
        (classif_final = 'Atua +12') AS tem_mais_12,
        (classif_final = 'Atua -12') AS tem_menos_12,
        (classif_final = 'Não atua') AS tem_nao_atua
    FROM deal_classif_raw
),
leads_funil AS (
    -- Funil de origem por deal (mesma técnica de
    -- prevendas_leads_detalhe_diario.sql). DISTINCT ON (zoho_id) escolhe
    -- a entrada mais recente, evitando fan-out no JOIN com deal_attrs.
    -- `ext_reconecta.leads.funil_origem` foi ativada em 25/05/2026 —
    -- entradas anteriores caem em 'Sem origem'.
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text                                              AS lead_zoho_id,
        COALESCE(NULLIF(btrim(l.funil_origem), ''), 'Sem origem')    AS funil_origem
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
    ORDER BY l.zoho_id::text, l.timestamp DESC NULLS LAST, l.id DESC
),
sdr_via_activity AS (
    -- SDR primário do deal = activity.prevendas mais recente de qualquer
    -- atividade Consulta/Indicação desse deal.
    SELECT DISTINCT ON (a.what_id)
        a.what_id::text                          AS deal_id,
        NULLIF(btrim(a.prevendas), '')           AS prevendas
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND NULLIF(btrim(a.prevendas), '') IS NOT NULL
      AND a.what_id IS NOT NULL
    ORDER BY a.what_id, a.created_time DESC NULLS LAST, a.id DESC
),
deal_attrs AS (
    -- Para cada deal relevante: SDR canônico + bucket + funil_origem +
    -- flags de pertença aos universos. Único ponto onde resolvemos SDR,
    -- classif e funil_origem.
    SELECT
        dr.deal_id,
        COALESCE(
            sva.prevendas,
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        )                                       AS sdr,
        CASE
            WHEN COALESCE(dc.tem_mais_12,  FALSE) THEN '+12'
            WHEN COALESCE(dc.tem_menos_12, FALSE) THEN '-12'
            WHEN COALESCE(dc.tem_nao_atua, FALSE) THEN 'Não atua'
            ELSE 'Sem classif'
        END                                     AS classif_bucket,
        COALESCE(lf.funil_origem, 'Sem origem') AS funil_origem,
        (dr.deal_id IN (SELECT deal_id FROM deals_periodo))        AS is_oport,
        (dr.deal_id IN (SELECT deal_id FROM deals_ganhos_periodo)) AS is_venda
    FROM deals_relevantes dr
    LEFT JOIN deal_classif      dc  ON dc.deal_id  = dr.deal_id
    LEFT JOIN sdr_via_activity  sva ON sva.deal_id = dr.deal_id
    LEFT JOIN zoho_deals        d   ON d.id::text  = dr.deal_id
    LEFT JOIN zoho_users        u   ON u.id::text  = d.sdr_ss::text
    LEFT JOIN leads_funil       lf  ON lf.lead_zoho_id = dr.deal_id
),
agend_por_deal AS (
    -- 1 row por (deal_id, activity_id) — base para contar agendamentos
    -- por SDR via JOIN com deal_attrs depois.
    SELECT
        anp.deal_id,
        anp.activity_id
    FROM acts_no_periodo anp
    WHERE anp.deal_id IS NOT NULL AND anp.deal_id <> ''
)
SELECT
    da.sdr,
    da.classif_bucket,
    da.funil_origem,
    COUNT(DISTINCT da.deal_id) FILTER (WHERE da.is_oport)::bigint AS oportunidades,
    COUNT(DISTINCT apd.activity_id)::bigint                       AS agendamentos,
    COUNT(DISTINCT da.deal_id) FILTER (WHERE da.is_venda)::bigint AS vendas
FROM deal_attrs da
LEFT JOIN agend_por_deal apd ON apd.deal_id = da.deal_id
GROUP BY da.sdr, da.classif_bucket, da.funil_origem
ORDER BY da.sdr, da.classif_bucket, da.funil_origem;
