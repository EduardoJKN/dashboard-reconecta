-- =============================================================================
-- bi.vw_mkt_roas    ⚠ DEPENDE DE bi.vw_mkt_overview — criar 01 antes desta
-- -----------------------------------------------------------------------------
-- Granularidade: 1 linha por (data_ref, canal).
-- Junta o investimento + leads (de bi.vw_mkt_overview) com vendas atribuídas
-- (de odam.v_attribution_lead_to_deal). A "data_ref" representa:
--   * para investimento/leads: o dia em que aconteceram (vw_mkt_overview)
--   * para vendas: o dia em que a venda FECHOU (deal_data_compra)
-- Isso é a convenção padrão de ROAS diário ("receita do dia / spend do dia"),
-- com a ressalva de que vendas podem refletir spend de dias anteriores.
--
-- Métricas derivadas (NULL quando denominador zero):
--   * cpl              = invest / leads
--   * cpl_qualificado  = invest / leads_qualificados
--   * cac              = invest / vendas
--   * roas             = valor_receita / invest
--
-- Dependências:
--   BI  : bi.vw_mkt_overview              ⚠
--   ODAM: odam.v_attribution_lead_to_deal
-- =============================================================================

CREATE OR REPLACE VIEW bi.vw_mkt_roas AS
WITH base AS (
    SELECT
        data_ref,
        canal,
        investimento,
        leads,
        leads_qualificados,
        leads_qualif_mais_12,
        leads_qualif_menos_12
    FROM bi.vw_mkt_overview
),
vendas_atribuidas AS (
    SELECT
        deal_data_compra::date AS data_ref,
        CASE
            WHEN LOWER(COALESCE(lead_utm_source, '')) IN
                 ('ig','meta','fb','an','facebook','instagram') THEN 'Meta'
            WHEN LOWER(COALESCE(lead_utm_source, '')) = 'google'    THEN 'Google'
            WHEN LOWER(COALESCE(lead_utm_source, '')) = 'pinterest' THEN 'Pinterest'
            ELSE 'Organico'
        END AS canal,
        COUNT(DISTINCT deal_id)            AS vendas,
        SUM(deal_valor_venda)::numeric     AS valor_venda,
        SUM(deal_valor_receita)::numeric   AS valor_receita
    FROM odam.v_attribution_lead_to_deal
    WHERE deal_stage = 'Ganho'
      AND deal_data_compra IS NOT NULL
    GROUP BY 1, 2
)
SELECT
    COALESCE(b.data_ref, v.data_ref)        AS data_ref,
    COALESCE(b.canal,    v.canal)           AS canal,
    COALESCE(b.investimento, 0)             AS investimento,
    COALESCE(b.leads, 0)                    AS leads,
    COALESCE(b.leads_qualificados, 0)       AS leads_qualificados,
    COALESCE(v.vendas, 0)                   AS vendas,
    COALESCE(v.valor_venda, 0)              AS valor_venda,
    COALESCE(v.valor_receita, 0)            AS valor_receita,
    CASE WHEN COALESCE(b.leads, 0) > 0
         THEN b.investimento / b.leads END                          AS cpl,
    CASE WHEN COALESCE(b.leads_qualificados, 0) > 0
         THEN b.investimento / b.leads_qualificados END             AS cpl_qualificado,
    CASE WHEN COALESCE(v.vendas, 0) > 0
         THEN COALESCE(b.investimento, 0) / v.vendas END            AS cac,
    CASE WHEN COALESCE(b.investimento, 0) > 0
         THEN COALESCE(v.valor_receita, 0) / b.investimento END     AS roas
FROM base b
FULL OUTER JOIN vendas_atribuidas v
       ON b.data_ref = v.data_ref AND b.canal = v.canal;
