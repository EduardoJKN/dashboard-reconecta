-- =============================================================================
-- Cohort de agendamentos por dia de geração — OPORTUNIDADES (deals +12/-12).
-- =============================================================================
-- Grão devolvido: 1 row por oportunidade (deal criado no período com
-- classificação ATUA +12 OU ATUA -12). O Python pivota por
-- (data_geracao, lag_dias_bucket) e acumula D0..D7.
--
-- Universo (alinhamento com a gestora — mai/2026):
--   - **Leads** (visão paralela, `prevendas_cohort_leads.sql`) = TODOS
--     os leads válidos do funil (sem filtro de classificação).
--   - **Oportunidades** (esta query) = subconjunto **classificado +12 ou -12**
--     pela regra combinada das 4 fontes. Não atua e Sem classificação
--     ficam de fora.
-- A intenção é deixar Oportunidades como "leads/deals que valem o esforço
-- do SDR", sem inflar o denominador com leads que nunca seriam atendidos.
--
-- Filtro aplicado a `deals_periodo`:
--   d.created_at::date BETWEEN :data_ini AND :data_fim
--   AND (tem_mais_12 OR tem_menos_12)  -- pela regra combinada abaixo
--
-- Regra COMBINADA de classificação (4 fontes, mesma de
-- prevendas_overview_diario.sql / prevendas_por_sdr.sql):
--   1. zoho_deals.lead_classification
--   2. zoho_deals.qualificacao
--   3. zoho_deals.classificado_cal
--   4. ext_reconecta.leads.classificado
-- bool_or agrega TODOS os leads pareados ao deal; basta UMA fonte indicar
-- +12 ou -12 pra o deal entrar. Prioridade exclusiva +12 > -12 (não muda
-- o universo aqui, mas mantemos a coluna `classif_bucket` por simetria
-- com prevendas_oportunidades_sdr.sql, caso o Python queira separar D_n
-- por bucket no futuro).
-- Filtro de e-mails internos no JOIN com ext.leads (regra canônica).
--
-- Atribuição de SDR — cascata canônica:
--   1) activity.prevendas mais recente do deal (Consulta/Indicação)
--   2) deal.sdr_ss → zoho_users
--   3) 'Sem SDR'
--
-- Primeiro agendamento por deal:
--   - activity_type IN ('Consulta','Indicação')
--   - status_reuniao IS NOT NULL
--   - start_datetime IS NOT NULL
--   - dedup por DISTINCT ON (deal_id) ORDER BY start_datetime ASC, id ASC
-- lag_dias = (data_agend - data_geracao). Negativos clipados em 0 (D0)
-- pelo Python.
-- =============================================================================
WITH deals_periodo_bruto AS (
    -- Universo bruto (todos os deals do período). Filtragem por +12/-12
    -- acontece DEPOIS de calcular a classif combinada, na CTE final
    -- `deals_periodo`. Mantemos sdr_ss aqui pra reusar no SELECT final.
    SELECT
        d.id::text             AS deal_id,
        d.created_at::date     AS data_geracao,
        d.sdr_ss::text         AS sdr_ss_id
    FROM zoho_deals d
    WHERE d.created_at::date BETWEEN :data_ini AND :data_fim
),
deal_classif AS (
    -- bool_or sobre as 4 fontes por deal. JOIN com ext.leads filtra
    -- e-mails de teste (regra canônica) pra não distorcer a classif.
    SELECT
        dpb.deal_id,
        bool_or(
            d.lead_classification = 'Atua +12'
            OR d.qualificacao     = 'Atua +12'
            OR d.classificado_cal = 'Atua +12'
            OR l.classificado     = 'Atua +12'
        )                                       AS tem_mais_12,
        bool_or(
            d.lead_classification = 'Atua -12'
            OR d.qualificacao     = 'Atua -12'
            OR d.classificado_cal = 'Atua -12'
            OR l.classificado     = 'Atua -12'
        )                                       AS tem_menos_12
    FROM deals_periodo_bruto dpb
    JOIN zoho_deals d           ON d.id::text = dpb.deal_id
    LEFT JOIN ext_reconecta.leads l
                                ON d.id::text = l.zoho_id::text
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
    GROUP BY dpb.deal_id
),
deals_periodo AS (
    -- Filtragem ao universo Oportunidades: somente deals +12 OU -12.
    -- Não atua e sem classificação ficam fora.
    SELECT
        dpb.deal_id,
        dpb.data_geracao,
        dpb.sdr_ss_id,
        CASE
            WHEN COALESCE(dc.tem_mais_12,  FALSE) THEN '+12'
            WHEN COALESCE(dc.tem_menos_12, FALSE) THEN '-12'
        END                                     AS classif_bucket
    FROM deals_periodo_bruto dpb
    JOIN deal_classif dc ON dc.deal_id = dpb.deal_id
    WHERE COALESCE(dc.tem_mais_12, FALSE)
       OR COALESCE(dc.tem_menos_12, FALSE)
),
sdr_via_activity AS (
    -- SDR primário = activity.prevendas mais recente do deal (com ou sem
    -- status_reuniao — queremos captar SDR mesmo de activity pendente).
    SELECT DISTINCT ON (a.what_id)
        a.what_id::text                  AS deal_id,
        NULLIF(btrim(a.prevendas), '')   AS prevendas
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND NULLIF(btrim(a.prevendas), '') IS NOT NULL
      AND a.what_id IS NOT NULL
    ORDER BY a.what_id, a.created_time DESC NULLS LAST, a.id DESC
),
acts_validas AS (
    -- Universo de agendamentos válidos. Normaliza what_id (json|texto)
    -- igual prevendas_leads_detalhe_diario.sql.
    SELECT
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END                              AS deal_id,
        a.start_datetime::date           AS data_agend,
        a.start_datetime                 AS start_datetime,
        a.id                             AS activity_id
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND a.start_datetime IS NOT NULL
),
primeiro_agend AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        data_agend
    FROM acts_validas
    WHERE deal_id IS NOT NULL AND deal_id <> ''
    ORDER BY deal_id, start_datetime ASC, activity_id ASC
)
SELECT
    dp.deal_id,
    dp.data_geracao,
    COALESCE(
        sva.prevendas,
        NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
        'Sem SDR'
    )                                    AS sdr,
    dp.classif_bucket                    AS classif_bucket,
    pa.data_agend                        AS data_agend,
    CASE
        WHEN pa.data_agend IS NULL THEN NULL
        ELSE (pa.data_agend - dp.data_geracao)::int
    END                                  AS lag_dias
FROM deals_periodo dp
LEFT JOIN sdr_via_activity sva ON sva.deal_id = dp.deal_id
LEFT JOIN zoho_users        u  ON u.id::text  = dp.sdr_ss_id
LEFT JOIN primeiro_agend    pa ON pa.deal_id  = dp.deal_id
ORDER BY dp.data_geracao DESC, dp.deal_id;
