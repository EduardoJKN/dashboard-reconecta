-- =============================================================================
-- Cohort de agendamentos por dia de geração — base LEADS
-- =============================================================================
-- Grão devolvido: 1 row por (data_lead, email_norm) — daily-distinct.
-- O Python pivota por (data_lead, lag_dias_bucket) e acumula D0..D7.
--
-- Universo: leads únicos por (dia, email) em ext_reconecta.leads no
-- período. **Mesma regra canônica de "Leads totais"** — a soma de
-- linhas devolvidas tem que bater 1:1 com a métrica `leads` de
-- prevendas_overview_diario.sql quando o filtro = Todos.
--
-- Match lead → deal (cascata revisada, com prioridade TEMPORAL):
--   1) `lead.zoho_id = deal.id`     — quando existe, é o vínculo
--      mais autoritativo (foi o próprio Zoho que registrou o lead
--      como aquele deal).
--   2) `deal.email = lead.email` AND `deal.created_at >= lead.created_at`
--      — primeiro deal "do mesmo dia ou posterior" do mesmo email.
--      É a regra mais coerente para cohort: o deal representa esta
--      entrada de lead, não um histórico anterior.
--   3) FALLBACK: deal mais recente por email com `deal.created_at <
--      lead.created_at` — o deal "anterior". `fonte_match_deal =
--      'email_anterior'` para auditoria. O `lag_dias` resultante pode
--      ficar negativo; o Python clipa em 0 (= D0).
-- Cada lead diário vira no máximo 1 row.
--
-- Match deal → primeiro agendamento:
--   - activity_type IN ('Consulta','Indicação')
--   - status_reuniao IS NOT NULL
--   - start_datetime IS NOT NULL
--   - `what_id` normalizado (json|texto), mesma regex de
--     prevendas_leads_detalhe_diario.sql
--   - `MIN(start_datetime)` deduplicado por activity_id
--   - lag_dias = data_agend - data_lead
--
-- SDR: herdado do deal pareado pela cascata canônica
--   activity.prevendas > deal.sdr_ss > 'Sem SDR'
-- =============================================================================
WITH leads_clean AS (
    SELECT
        l.created_at::date              AS data_lead,
        lower(btrim(l.email))           AS email_norm,
        NULLIF(btrim(l.zoho_id), '')    AS lead_zoho_id,
        l.created_at                    AS lead_created_at
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_unique AS (
    -- Daily-distinct (data_lead, email). Pega o registro mais recente
    -- do dia pra herdar zoho_id da melhor versão (mesma estratégia de
    -- prevendas_overview_diario.sql).
    SELECT DISTINCT ON (data_lead, email_norm)
        data_lead,
        email_norm,
        lead_zoho_id,
        lead_created_at
    FROM leads_clean
    ORDER BY data_lead, email_norm, lead_created_at DESC
),
match_zoho_id AS (
    -- Prioridade 1: zoho_id casa direto com deal.id.
    SELECT
        lu.data_lead, lu.email_norm,
        zd.id                                  AS deal_id,
        zd.created_at                          AS deal_created_at,
        'zoho_id'::text                        AS fonte_match_deal
    FROM leads_unique lu
    JOIN zoho_deals zd ON zd.id = lu.lead_zoho_id
    WHERE lu.lead_zoho_id IS NOT NULL
),
match_email_posterior AS (
    -- Prioridade 2: deal do mesmo email criado no MESMO DIA do lead
    -- ou DEPOIS. Em empate, o mais antigo (o que primeiro existiu
    -- após o lead chegar). Só roda quando o lead não bateu por zoho_id.
    SELECT DISTINCT ON (lu.data_lead, lu.email_norm)
        lu.data_lead, lu.email_norm,
        zd.id                                  AS deal_id,
        zd.created_at                          AS deal_created_at,
        'email_posterior'::text                AS fonte_match_deal
    FROM leads_unique lu
    JOIN zoho_deals zd
      ON lower(btrim(zd.email)) = lu.email_norm
     AND zd.created_at::date >= lu.data_lead
    WHERE NOT EXISTS (
        SELECT 1 FROM match_zoho_id m
        WHERE m.data_lead  = lu.data_lead
          AND m.email_norm = lu.email_norm
    )
    ORDER BY lu.data_lead, lu.email_norm, zd.created_at ASC, zd.id
),
match_email_anterior AS (
    -- Prioridade 3 (fallback): deal mais recente do mesmo email
    -- criado ANTES do lead. Marcado pra auditoria; lag_dias pode ficar
    -- negativo (clip pra D0 no Python).
    SELECT DISTINCT ON (lu.data_lead, lu.email_norm)
        lu.data_lead, lu.email_norm,
        zd.id                                  AS deal_id,
        zd.created_at                          AS deal_created_at,
        'email_anterior'::text                 AS fonte_match_deal
    FROM leads_unique lu
    JOIN zoho_deals zd
      ON lower(btrim(zd.email)) = lu.email_norm
     AND zd.created_at::date < lu.data_lead
    WHERE NOT EXISTS (
        SELECT 1 FROM match_zoho_id m1
        WHERE m1.data_lead  = lu.data_lead
          AND m1.email_norm = lu.email_norm
    )
    AND NOT EXISTS (
        SELECT 1 FROM match_email_posterior m2
        WHERE m2.data_lead  = lu.data_lead
          AND m2.email_norm = lu.email_norm
    )
    ORDER BY lu.data_lead, lu.email_norm, zd.created_at DESC NULLS LAST, zd.id
),
lead_with_deal AS (
    -- União das 3 prioridades. Como cada CTE de prioridade já filtra
    -- "lead que ainda não casou", a união garante 1 row por lead único.
    SELECT data_lead, email_norm, deal_id, deal_created_at, fonte_match_deal
    FROM match_zoho_id
    UNION ALL
    SELECT data_lead, email_norm, deal_id, deal_created_at, fonte_match_deal
    FROM match_email_posterior
    UNION ALL
    SELECT data_lead, email_norm, deal_id, deal_created_at, fonte_match_deal
    FROM match_email_anterior
),
sdr_via_activity AS (
    -- SDR primário do deal = activity.prevendas mais recente
    -- (Consulta/Indicação).
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
    -- 1ª activity do deal por start_datetime ascendente, deduplicada
    -- por activity_id.
    SELECT DISTINCT ON (deal_id)
        deal_id,
        data_agend
    FROM acts_validas
    WHERE deal_id IS NOT NULL AND deal_id <> ''
    ORDER BY deal_id, start_datetime ASC, activity_id ASC
)
SELECT
    lu.data_lead,
    lu.email_norm,
    COALESCE(
        sva.prevendas,
        NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
        'Sem SDR'
    )                                    AS sdr,
    pa.data_agend                        AS data_agend,
    CASE
        WHEN pa.data_agend IS NULL THEN NULL
        ELSE (pa.data_agend - lu.data_lead)::int
    END                                  AS lag_dias,
    lwd.fonte_match_deal                 AS fonte_match_deal
FROM leads_unique lu
LEFT JOIN lead_with_deal lwd USING (data_lead, email_norm)
LEFT JOIN sdr_via_activity sva ON sva.deal_id = lwd.deal_id::text
LEFT JOIN zoho_deals       d   ON d.id        = lwd.deal_id
LEFT JOIN zoho_users       u   ON u.id::text  = d.sdr_ss::text
LEFT JOIN primeiro_agend   pa  ON pa.deal_id  = lwd.deal_id::text
ORDER BY lu.data_lead DESC, lu.email_norm;
