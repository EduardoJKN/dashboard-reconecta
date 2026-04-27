-- =============================================================================
-- bi.vw_mkt_funil
-- -----------------------------------------------------------------------------
-- Granularidade: 1 linha por (data_ref, canal).
-- Funil consolidado: investimento → impressões → cliques → leads
--                  → leads qualificados → deals → deals_ganhos → vendas.
-- A view usa odam.v_attribution_lead_to_deal (que já resolve a cascata
-- zoho_id > session_id > LOWER(email) e preenche ad_id via utm_content
-- como fallback do gap de jan/2026 da integração Meta).
--
-- Dependências:
--   RAW : fdw_reconecta.anuncios, fdw_reconecta.google_ads,
--         fdw_reconecta.pinterest_ads
--   ODAM: odam.v_attribution_lead_to_deal
-- =============================================================================

CREATE OR REPLACE VIEW bi.vw_mkt_funil AS
WITH paid AS (
    SELECT date_start::date AS data_ref, 'Meta'::text AS canal,
           SUM(spend)::numeric         AS investimento,
           SUM(impressions)::bigint    AS impressoes,
           SUM(unique_clicks)::bigint  AS cliques
    FROM fdw_reconecta.anuncios
    WHERE date_start IS NOT NULL
      AND campaign_id <> '120234100785340241'
      AND COALESCE(campaign_name, '') NOT ILIKE 'REL_02%'
    GROUP BY 1
    UNION ALL
    SELECT date::date, 'Google',
           SUM(cost)::numeric, SUM(impressions)::bigint, SUM(clicks)::bigint
    FROM fdw_reconecta.google_ads
    WHERE date IS NOT NULL
    GROUP BY 1
    UNION ALL
    SELECT date::date, 'Pinterest',
           SUM(spend)::numeric, SUM(impressions)::bigint, SUM(clicks)::bigint
    FROM fdw_reconecta.pinterest_ads
    WHERE date IS NOT NULL
    GROUP BY 1
),
leads_deals AS (
    SELECT
        lead_created_at::date AS data_ref,
        CASE
            WHEN LOWER(COALESCE(lead_utm_source, '')) IN
                 ('ig','meta','fb','an','facebook','instagram') THEN 'Meta'
            WHEN LOWER(COALESCE(lead_utm_source, '')) = 'google'    THEN 'Google'
            WHEN LOWER(COALESCE(lead_utm_source, '')) = 'pinterest' THEN 'Pinterest'
            ELSE 'Organico'
        END AS canal,
        COUNT(DISTINCT lead_id)
            AS leads,
        COUNT(DISTINCT lead_id) FILTER (WHERE lead_classificacao = 'Atua +12')
            AS leads_qualif_mais_12,
        COUNT(DISTINCT lead_id) FILTER (WHERE lead_classificacao = 'Atua -12')
            AS leads_qualif_menos_12,
        COUNT(DISTINCT deal_id)
            AS deals,
        COUNT(DISTINCT deal_id) FILTER (WHERE deal_stage = 'Ganho')
            AS deals_ganhos,
        COUNT(DISTINCT deal_id) FILTER (
            WHERE deal_stage = 'Ganho' AND deal_data_compra IS NOT NULL
        ) AS vendas,
        SUM(deal_valor_venda) FILTER (
            WHERE deal_stage = 'Ganho' AND deal_data_compra IS NOT NULL
        ) AS valor_venda,
        SUM(deal_valor_receita) FILTER (
            WHERE deal_stage = 'Ganho' AND deal_data_compra IS NOT NULL
        ) AS valor_receita
    FROM odam.v_attribution_lead_to_deal
    WHERE lead_created_at IS NOT NULL
    GROUP BY 1, 2
)
SELECT
    COALESCE(p.data_ref, l.data_ref)            AS data_ref,
    COALESCE(p.canal,    l.canal)               AS canal,
    COALESCE(p.investimento, 0)::numeric        AS investimento,
    COALESCE(p.impressoes, 0)                   AS impressoes,
    COALESCE(p.cliques, 0)                      AS cliques,
    COALESCE(l.leads, 0)                        AS leads,
    COALESCE(l.leads_qualif_mais_12, 0)         AS leads_qualif_mais_12,
    COALESCE(l.leads_qualif_menos_12, 0)        AS leads_qualif_menos_12,
    COALESCE(l.deals, 0)                        AS deals,
    COALESCE(l.deals_ganhos, 0)                 AS deals_ganhos,
    COALESCE(l.vendas, 0)                       AS vendas,
    COALESCE(l.valor_venda, 0)::numeric         AS valor_venda,
    COALESCE(l.valor_receita, 0)::numeric       AS valor_receita
FROM paid p
FULL OUTER JOIN leads_deals l
       ON p.data_ref = l.data_ref AND p.canal = l.canal;
