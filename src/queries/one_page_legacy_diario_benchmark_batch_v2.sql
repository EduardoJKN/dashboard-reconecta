-- =============================================================================
-- Legacy diário — benchmark batch (múltiplas janelas, dedupe por period_key).
-- =============================================================================
-- Equivalente a N execuções de `one_page_legacy_diario_v2.sql`, uma por janela.
-- Parâmetro :periods_json — array JSON:
--   [{"period_key":"0","data_ini":"2026-03-16","data_fim":"2026-03-22"}, ...]
-- =============================================================================
WITH
periodos AS (
    SELECT
        p.period_key,
        p.data_ini::date AS data_ini,
        p.data_fim::date AS data_fim
    FROM jsonb_to_recordset(CAST(:periods_json AS jsonb)) AS p(
        period_key text,
        data_ini date,
        data_fim date
    )
),
leads_clean AS (
    SELECT
        p.period_key,
        l.created_at::date     AS data,
        lower(btrim(l.email))  AS email_norm
    FROM periodos p
    JOIN ext_reconecta.leads l
      ON l.created_at::date BETWEEN p.data_ini AND p.data_fim
    WHERE l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_dia AS (
    SELECT period_key, data, COUNT(DISTINCT email_norm)::bigint AS novos_leads
    FROM leads_clean
    GROUP BY period_key, data
),
aplicacoes_clean AS (
    SELECT
        p.period_key,
        ta.created_at::date                         AS data,
        lower(btrim(ta.email))                      AS email_norm,
        lower(btrim(coalesce(ta.classificado, ''))) AS classif_norm
    FROM periodos p
    JOIN fdw_reconecta.typeform_aplicacoes ta
      ON ta.created_at::date BETWEEN p.data_ini AND p.data_fim
    WHERE ta.dados_completos IS TRUE
      AND ta.email IS NOT NULL
      AND btrim(ta.email) <> ''
      AND (
          :excluir_testes_aplicacoes = 0
          OR (
              lower(ta.email) NOT LIKE '%@teste%'
              AND lower(ta.email) NOT LIKE 'teste@%'
              AND lower(ta.email) NOT LIKE '%smarts%'
              AND lower(ta.email) NOT LIKE '%reconecta%'
          )
      )
),
aplicacoes_dia_email AS (
    SELECT
        period_key,
        data,
        email_norm,
        BOOL_OR(classif_norm IN ('atua +12', 'atua+12', '+12')) AS tem_mais_12,
        BOOL_OR(classif_norm IN ('atua -12', 'atua-12', '-12')) AS tem_menos_12,
        BOOL_OR(classif_norm IN ('não atua', 'nao atua'))       AS tem_nao_atua
    FROM aplicacoes_clean
    GROUP BY period_key, data, email_norm
),
aplicacoes_dia AS (
    SELECT
        period_key,
        data,
        COUNT(*)::bigint                            AS novas_aplicacoes,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint   AS aplicacoes_mais_12,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint  AS aplicacoes_menos_12,
        COUNT(*) FILTER (WHERE tem_nao_atua)::bigint  AS aplicacoes_nao_atua
    FROM aplicacoes_dia_email
    GROUP BY period_key, data
),
aplicacoes_email_periodo AS (
    SELECT
        period_key,
        email_norm,
        BOOL_OR(classif_norm IN ('atua +12', 'atua+12', '+12')) AS tem_mais_12,
        BOOL_OR(classif_norm IN ('atua -12', 'atua-12', '-12')) AS tem_menos_12,
        BOOL_OR(classif_norm IN ('não atua', 'nao atua'))       AS tem_nao_atua
    FROM aplicacoes_clean
    GROUP BY period_key, email_norm
),
aplicacoes_periodo AS (
    SELECT
        period_key,
        COUNT(*)::bigint                            AS novas_aplicacoes_periodo,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint   AS aplicacoes_mais_12_periodo,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint  AS aplicacoes_menos_12_periodo,
        COUNT(*) FILTER (WHERE tem_nao_atua)::bigint  AS aplicacoes_nao_atua_periodo
    FROM aplicacoes_email_periodo
    GROUP BY period_key
),
acts AS (
    SELECT
        p.period_key,
        a.id                 AS activity_id,
        a.what_id            AS deal_id,
        a.created_time::date AS data
    FROM periodos p
    JOIN zoho_activities a
      ON a.activity_type IN ('Consulta', 'Indicação')
     AND a.created_time::date BETWEEN p.data_ini AND p.data_fim
),
acts_emails AS (
    SELECT
        a.period_key,
        a.data,
        a.activity_id,
        lower(btrim(zd.email)) AS email_norm
    FROM acts a
    LEFT JOIN zoho_deals zd ON zd.id = a.deal_id
    WHERE zd.email IS NOT NULL
      AND btrim(zd.email) <> ''
),
agendamentos_dia AS (
    SELECT
        period_key,
        data,
        COUNT(DISTINCT activity_id)::bigint AS agendamentos,
        COUNT(DISTINCT email_norm)::bigint  AS emails_com_agendamento
    FROM acts_emails
    GROUP BY period_key, data
),
aplicacoes_emails_universo AS (
    SELECT DISTINCT period_key, email_norm
    FROM aplicacoes_clean
),
leads_email_zoho_ranked AS (
    SELECT
        u.period_key,
        lower(btrim(l.email)) AS email_norm,
        l.zoho_id::text        AS deal_id,
        ROW_NUMBER() OVER (
            PARTITION BY u.period_key, lower(btrim(l.email))
            ORDER BY l."timestamp" DESC NULLS LAST, l.id DESC
        ) AS rn
    FROM ext_reconecta.leads l
    INNER JOIN aplicacoes_emails_universo u
        ON lower(btrim(l.email)) = u.email_norm
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_email_zoho AS (
    SELECT period_key, email_norm, deal_id
    FROM leads_email_zoho_ranked
    WHERE rn = 1
),
deals_com_agendamento AS (
    SELECT DISTINCT lez.period_key, zd.id::text AS deal_id
    FROM leads_email_zoho lez
    INNER JOIN zoho_deals zd ON zd.id::text = lez.deal_id
    INNER JOIN zoho_activities a ON a.what_id = zd.id
        AND a.activity_type IN ('Consulta', 'Indicação')
),
apl_com_ag AS (
    SELECT
        ad.period_key,
        ad.data,
        COUNT(DISTINCT ad.email_norm)::bigint AS aplicacoes_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_mais_12)::bigint
            AS aplicacoes_mais_12_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_menos_12)::bigint
            AS aplicacoes_menos_12_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_nao_atua)::bigint
            AS aplicacoes_nao_atua_com_agendamento
    FROM aplicacoes_dia_email ad
    JOIN leads_email_zoho lez
      ON lez.period_key = ad.period_key AND lez.email_norm = ad.email_norm
    JOIN deals_com_agendamento dca
      ON dca.period_key = ad.period_key AND dca.deal_id = lez.deal_id
    GROUP BY ad.period_key, ad.data
),
apl_com_ag_periodo AS (
    SELECT
        ap.period_key,
        COUNT(DISTINCT ap.email_norm)::bigint AS aplicacoes_com_agendamento_periodo,
        COUNT(DISTINCT ap.email_norm) FILTER (WHERE ap.tem_mais_12)::bigint
            AS aplicacoes_mais_12_com_agendamento_periodo,
        COUNT(DISTINCT ap.email_norm) FILTER (WHERE ap.tem_menos_12)::bigint
            AS aplicacoes_menos_12_com_agendamento_periodo,
        COUNT(DISTINCT ap.email_norm) FILTER (WHERE ap.tem_nao_atua)::bigint
            AS aplicacoes_nao_atua_com_agendamento_periodo
    FROM aplicacoes_email_periodo ap
    JOIN leads_email_zoho lez
      ON lez.period_key = ap.period_key AND lez.email_norm = ap.email_norm
    JOIN deals_com_agendamento dca
      ON dca.period_key = ap.period_key AND dca.deal_id = lez.deal_id
    GROUP BY ap.period_key
),
invest_dia AS (
    SELECT
        p.period_key,
        a.date_start AS data,
        SUM(a.spend)::numeric AS investimento
    FROM periodos p
    JOIN fdw_reconecta.anuncios a
      ON a.date_start BETWEEN p.data_ini AND p.data_fim
     AND (a.campaign_name IS NULL OR a.campaign_name NOT LIKE 'REL_02%')
    GROUP BY p.period_key, a.date_start
),
keys AS (
    SELECT period_key, data FROM leads_dia
    UNION SELECT period_key, data FROM aplicacoes_dia
    UNION SELECT period_key, data FROM agendamentos_dia
    UNION SELECT period_key, data FROM invest_dia
)
SELECT
    k.period_key,
    k.data                                              AS data_ref,
    COALESCE(ld.novos_leads, 0)::bigint                 AS novos_leads,
    COALESCE(ad.novas_aplicacoes, 0)::bigint            AS novas_aplicacoes,
    COALESCE(ad.aplicacoes_mais_12, 0)::bigint          AS aplicacoes_mais_12,
    COALESCE(ad.aplicacoes_menos_12, 0)::bigint         AS aplicacoes_menos_12,
    COALESCE(ad.aplicacoes_nao_atua, 0)::bigint         AS aplicacoes_nao_atua,
    COALESCE(agd.agendamentos, 0)::bigint               AS agendamentos,
    COALESCE(agd.emails_com_agendamento, 0)::bigint     AS emails_com_agendamento,
    COALESCE(aca.aplicacoes_com_agendamento, 0)::bigint  AS aplicacoes_com_agendamento,
    COALESCE(aca.aplicacoes_mais_12_com_agendamento, 0)::bigint
        AS aplicacoes_mais_12_com_agendamento,
    COALESCE(aca.aplicacoes_menos_12_com_agendamento, 0)::bigint
        AS aplicacoes_menos_12_com_agendamento,
    COALESCE(aca.aplicacoes_nao_atua_com_agendamento, 0)::bigint
        AS aplicacoes_nao_atua_com_agendamento,
    COALESCE(inv.investimento, 0)::numeric               AS investimento,
    COALESCE(ap.novas_aplicacoes_periodo, 0)::bigint    AS novas_aplicacoes_periodo,
    COALESCE(ap.aplicacoes_mais_12_periodo, 0)::bigint  AS aplicacoes_mais_12_periodo,
    COALESCE(ap.aplicacoes_menos_12_periodo, 0)::bigint AS aplicacoes_menos_12_periodo,
    COALESCE(ap.aplicacoes_nao_atua_periodo, 0)::bigint AS aplicacoes_nao_atua_periodo,
    COALESCE(acp.aplicacoes_com_agendamento_periodo, 0)::bigint
        AS aplicacoes_com_agendamento_periodo,
    COALESCE(acp.aplicacoes_mais_12_com_agendamento_periodo, 0)::bigint
        AS aplicacoes_mais_12_com_agendamento_periodo,
    COALESCE(acp.aplicacoes_menos_12_com_agendamento_periodo, 0)::bigint
        AS aplicacoes_menos_12_com_agendamento_periodo,
    COALESCE(acp.aplicacoes_nao_atua_com_agendamento_periodo, 0)::bigint
        AS aplicacoes_nao_atua_com_agendamento_periodo
FROM keys k
LEFT JOIN leads_dia ld
       ON ld.period_key = k.period_key AND ld.data = k.data
LEFT JOIN aplicacoes_dia ad
       ON ad.period_key = k.period_key AND ad.data = k.data
LEFT JOIN agendamentos_dia agd
       ON agd.period_key = k.period_key AND agd.data = k.data
LEFT JOIN apl_com_ag aca
       ON aca.period_key = k.period_key AND aca.data = k.data
LEFT JOIN invest_dia inv
       ON inv.period_key = k.period_key AND inv.data = k.data
LEFT JOIN aplicacoes_periodo ap ON ap.period_key = k.period_key
LEFT JOIN apl_com_ag_periodo acp ON acp.period_key = k.period_key
ORDER BY k.period_key, k.data;
