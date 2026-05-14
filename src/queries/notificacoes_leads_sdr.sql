-- =============================================================================
-- Leads repassados para SDRs — alimenta a seção "Leads repassados para SDRs"
-- da página "Notificações de Vendas".
-- =============================================================================
-- Origem: `ext_reconecta.leads` (mesma fonte de leads_visao_geral.sql /
-- prevendas_overview_diario_por_sdr.sql) com tentativa de associar cada
-- lead a um SDR via CRM.
--
-- Grão: 1 row por lead daily-distinct (data_ref, email_norm) — alinhado
-- com a regra oficial de "Leads totais" da Visão Geral. Não devolve
-- repetições do mesmo email no mesmo dia.
--
-- Resolução de SDR (mesma cascata de prevendas_overview_diario_por_sdr):
--   1) activity.prevendas — texto livre na atividade mais recente do
--      deal (`zoho_activities` filtrado por activity_type IN
--      ('Consulta','Indicação')). Captura SDR mesmo em deals sem
--      executiva atribuída.
--   2) deal.sdr_ss → zoho_users (`first_name || ' ' || last_name`).
--   3) NULL → exibido como "Sem SDR identificado" no Python.
--
-- `fonte_associacao_sdr` documenta qual caminho casou:
--   - 'activity.prevendas'
--   - 'deal.sdr_ss'
--   - 'nao_identificado'
--
-- Match lead → deal: priority `zoho_id > session_id > email` (mesma regra
-- usada em leads_visao_geral.sql, mkt_visao_geral_kpis_canal etc).
-- =============================================================================
WITH leads_clean AS (
    SELECT DISTINCT ON (l.created_at::date, lower(btrim(l.email)))
        l.created_at::date              AS data_ref,
        l.created_at                    AS created_at,
        lower(btrim(l.email))           AS email_norm,
        NULLIF(btrim(l.zoho_id), '')    AS lead_zoho_id,
        l.session_id                    AS lead_session_id,
        l.first_name                    AS nome,
        l.email                         AS email,
        l.phone_number                  AS telefone,
        l.classificado                  AS classificado,
        l.utm_source                    AS utm_source,
        l.utm_medium                    AS utm_medium,
        l.utm_campaign                  AS utm_campaign,
        l.utm_content                   AS utm_content,
        l.utm_term                      AS utm_term,
        l.page_url                      AS page_url,
        l.page_pathname                 AS page_pathname,
        l.lead_source                   AS lead_source,
        l.lp_variante                   AS lp_variante
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY l.created_at::date, lower(btrim(l.email)), l.created_at DESC
),
all_deal_matches AS (
    -- UNION ALL de 3 INNER JOINs index-friendly (mesma estratégia de
    -- leads_visao_geral.sql) — DISTINCT ON pelo `prio` resolve a
    -- prioridade zoho_id > session_id > email.
    SELECT lc.data_ref, lc.email_norm,
           zd.id AS deal_id, zd.created_at AS deal_ca, 1 AS prio
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_zoho_id = zd.id
    WHERE lc.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT lc.data_ref, lc.email_norm,
           zd.id, zd.created_at, 2
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_session_id::text = zd.session_id
    WHERE lc.lead_session_id IS NOT NULL
    UNION ALL
    SELECT lc.data_ref, lc.email_norm,
           zd.id, zd.created_at, 3
    FROM leads_clean lc
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = lc.email_norm
),
lead_with_deal AS (
    SELECT DISTINCT ON (data_ref, email_norm)
        data_ref,
        email_norm,
        deal_id
    FROM all_deal_matches
    ORDER BY data_ref, email_norm, prio, deal_ca DESC NULLS LAST
),
acts_periodo AS (
    -- SDR primário: atividade mais recente do deal no mesmo recorte.
    -- Filtro de tipo replica prevendas_overview_diario_por_sdr.
    SELECT
        a.id                                  AS activity_id,
        a.what_id                             AS deal_id,
        a.start_datetime,
        NULLIF(btrim(a.prevendas), '')        AS prevendas
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
deal_sdr_pick AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        prevendas
    FROM acts_periodo
    WHERE deal_id IS NOT NULL
      AND prevendas IS NOT NULL
    ORDER BY deal_id, start_datetime DESC, activity_id DESC
)
SELECT
    lc.created_at                                                       AS created_at,
    lc.data_ref                                                         AS data_ref,
    lc.nome                                                             AS nome,
    lc.email                                                            AS email,
    lc.telefone                                                         AS telefone,
    lc.classificado                                                     AS classificado,
    lc.utm_source                                                       AS utm_source,
    lc.utm_medium                                                       AS utm_medium,
    lc.utm_campaign                                                     AS utm_campaign,
    lc.utm_content                                                      AS utm_content,
    lc.utm_term                                                         AS utm_term,
    lc.page_url                                                         AS page_url,
    lc.page_pathname                                                    AS page_pathname,
    lc.lead_source                                                      AS lead_source,
    lc.lp_variante                                                      AS lp_variante,
    lc.lead_zoho_id                                                     AS zoho_id,
    lc.lead_session_id                                                  AS session_id,

    -- Vínculo com CRM/deal
    lwd.deal_id                                                         AS deal_id,
    zd.stage                                                            AS stage,
    zd.tipo_venda                                                       AS tipo_venda,
    zd.lead_classification                                              AS lead_classification,
    zd.qualificacao                                                     AS qualificacao,
    NULLIF(TRIM(u_closer.first_name || ' ' || u_closer.last_name), '')  AS executiva_vendas,

    -- SDR resolvido com cascata
    COALESCE(
        dsp.prevendas,
        NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
    )                                                                   AS sdr,

    -- Procedência da associação
    CASE
        WHEN dsp.prevendas IS NOT NULL
            THEN 'activity.prevendas'
        WHEN NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
            IS NOT NULL
            THEN 'deal.sdr_ss'
        ELSE 'nao_identificado'
    END                                                                 AS fonte_associacao_sdr,

    (lwd.deal_id IS NOT NULL)                                           AS tem_deal_crm,
    (
        dsp.prevendas IS NOT NULL
        OR NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
           IS NOT NULL
    )                                                                   AS tem_sdr_identificado
FROM leads_clean lc
LEFT JOIN lead_with_deal lwd USING (data_ref, email_norm)
LEFT JOIN zoho_deals    zd       ON zd.id = lwd.deal_id
LEFT JOIN deal_sdr_pick dsp      ON dsp.deal_id = lwd.deal_id
LEFT JOIN zoho_users    u_sdr    ON u_sdr.id::text    = zd.sdr_ss::text
LEFT JOIN zoho_users    u_closer ON u_closer.id::text = zd.executiva_vendas::text
ORDER BY lc.created_at DESC;
