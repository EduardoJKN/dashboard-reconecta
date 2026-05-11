-- =============================================================================
-- Pré-vendas — Comparecimentos por classificação (+12 / -12 / Não atua).
-- =============================================================================
-- 1 linha por (sdr, fonte_sdr, bucket de classificação) com leads únicos
-- que tiveram agendamento, comparecimento e venda nova.
--
-- Atribuição de SDR (regra HÍBRIDA — Opção C):
--   1. `zoho_activities.prevendas` (nome em texto)
--   2. fallback: `zoho_deals.sdr_ss` resolvido via `zoho_users`
--   3. ainda NULL → "Sem SDR"
-- `fonte_sdr` carrega a auditoria.
--
-- Caminho:
--   activity (Consulta/Indicação) → deal (what_id) → lead matched via
--   priority `zoho_id > session_id > email` → classif_final = última
--   classificação do e-mail no período (regra Visão Geral oficial).
-- =============================================================================
WITH leads_clean AS (
    SELECT
        lower(btrim(l.email))         AS email_norm,
        l.created_at,
        NULLIF(btrim(l.zoho_id), '')  AS lead_zoho_id,
        l.session_id                  AS lead_session_id,
        l.classificado
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
last_classif AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
email_keys AS (
    SELECT DISTINCT ON (email_norm)
        email_norm, lead_zoho_id, lead_session_id
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
all_deal_matches AS (
    SELECT ek.email_norm, zd.id AS deal_id, zd.created_at AS deal_ca, 1 AS prio
    FROM email_keys ek JOIN zoho_deals zd ON ek.lead_zoho_id = zd.id
    WHERE ek.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT ek.email_norm, zd.id, zd.created_at, 2
    FROM email_keys ek JOIN zoho_deals zd ON ek.lead_session_id::text = zd.session_id
    WHERE ek.lead_session_id IS NOT NULL
    UNION ALL
    SELECT ek.email_norm, zd.id, zd.created_at, 3
    FROM email_keys ek JOIN zoho_deals zd ON lower(btrim(zd.email)) = ek.email_norm
),
lead_with_deal AS (
    SELECT DISTINCT ON (email_norm)
        email_norm, deal_id
    FROM all_deal_matches
    ORDER BY email_norm, prio, deal_ca DESC NULLS LAST
),
-- Activities atreladas ao deal pareado, com SDR híbrido + fonte_sdr.
acts AS (
    SELECT
        lwd.email_norm,
        lwd.deal_id,
        za.status_reuniao,
        COALESCE(
            NULLIF(btrim(za.prevendas), ''),
            TRIM(u.first_name || ' ' || u.last_name),
            'Sem SDR'
        ) AS sdr,
        CASE
            WHEN NULLIF(btrim(za.prevendas), '') IS NOT NULL
                THEN 'activity.prevendas'
            WHEN TRIM(u.first_name || ' ' || u.last_name) IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END AS fonte_sdr
    FROM lead_with_deal lwd
    JOIN zoho_activities za ON za.what_id = lwd.deal_id
    LEFT JOIN zoho_deals  d  ON d.id        = za.what_id
    LEFT JOIN zoho_users  u  ON u.id::text  = d.sdr_ss::text
    WHERE za.activity_type IN ('Consulta','Indicação')
      AND za.start_datetime::date BETWEEN :data_ini AND :data_fim
),
acts_lead_sdr AS (
    SELECT
        a.email_norm,
        a.sdr,
        a.fonte_sdr,
        a.deal_id,
        BOOL_OR(TRUE)                                AS teve_agend,
        BOOL_OR(a.status_reuniao = 'Concluída')      AS teve_compar
    FROM acts a
    GROUP BY a.email_norm, a.sdr, a.fonte_sdr, a.deal_id
),
deals_novos AS (
    SELECT zd.id AS deal_id
    FROM zoho_deals zd
    WHERE zd.stage IN ('Ganho','Fechado Ganho')
      AND zd.tipo_venda = 'Novo cliente'
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
final_pairs AS (
    SELECT
        als.email_norm,
        als.sdr,
        als.fonte_sdr,
        CASE
            WHEN c.classif_final ILIKE '%+12%'      THEN '+12'
            WHEN c.classif_final ILIKE '%-12%'      THEN '-12'
            WHEN c.classif_final ILIKE '%não atua%' THEN 'Não atua'
            ELSE 'Sem classif'
        END                                          AS bucket,
        als.teve_agend,
        als.teve_compar,
        (dn.deal_id IS NOT NULL)                     AS teve_venda_nova
    FROM acts_lead_sdr als
    LEFT JOIN last_classif c USING (email_norm)
    LEFT JOIN deals_novos  dn ON dn.deal_id = als.deal_id
)
SELECT
    sdr,
    fonte_sdr,
    bucket,
    COUNT(*) FILTER (WHERE teve_agend)::bigint        AS leads_com_agend,
    COUNT(*) FILTER (WHERE teve_compar)::bigint       AS leads_com_compar,
    COUNT(*) FILTER (WHERE teve_venda_nova)::bigint   AS leads_com_venda_nova
FROM final_pairs
GROUP BY sdr, fonte_sdr, bucket
ORDER BY leads_com_agend DESC, sdr, bucket;
