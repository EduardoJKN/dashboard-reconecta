-- =============================================================================
-- Visão Geral Marketing — KPIs diários (regra oficial validada em pgAdmin).
-- =============================================================================
-- Fonte enxuta para os cards principais. Substitui mkt_overview_v2.sql nessa
-- página. Não usa LATERAL JOIN com zoho_deals (que estava pesado) — agrega
-- direto cada fonte.
--
-- Regras (abril/2026 esperado):
--   investimento_total_geral = 102.199,89   ← bi.vw_investimento_diario
--   leads_totais             = 854          ← ext_reconecta.leads (e-mails únicos/dia)
--   leads_qualificados       = 701          ← +12 ou -12, classificação canônica do e-mail no período
--   leads_mais_12            = 259
--   leads_menos_12           = 442
--   vendas_total_geral       = 57           ← zoho_deals (Ganho/Fechado Ganho)
--   vendas_novas_total_geral = 50           ← tipo_venda = 'Novo cliente'
--   montante_total_geral     = 1.216.572    ← SUM(amount::numeric)
--   receita_total_geral      = 774.182      ← SUM(receita::numeric)
-- =============================================================================
WITH
-- -----------------------------------------------------------------------------
-- Leads — base limpa: filtra janela e exclui e-mails de teste/internos.
-- created_at::date é o eixo canônico (mesma regra usada em pgAdmin).
-- -----------------------------------------------------------------------------
leads_clean AS (
    SELECT
        l.created_at::date                AS data_ref,
        lower(btrim(l.email))             AS email_norm,
        l.created_at,
        l.classificado
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
-- Última classificação POR E-MAIL dentro do período (created_at DESC).
-- Cada e-mail tem 1 classificação canônica no período inteiro — vale tanto
-- pra +12 quanto pra -12.
last_classif AS (
    SELECT DISTINCT ON (email_norm)
        email_norm,
        classificado AS classif_final
    FROM leads_clean
    ORDER BY email_norm, created_at DESC
),
-- 1 linha por (data_ref, e-mail). rn_email = 1 marca a PRIMEIRA aparição do
-- e-mail no período — usado pra que o lead qualificado conte 1× só (no
-- período inteiro), enquanto leads_totais continua somando aparições diárias.
-- É essa assimetria que casa o validation:
--   leads_totais (soma diária)             = 854
--   leads_qualificados (distinct no período) = 701
--   leads_mais_12 (distinct no período)      = 259
--   leads_menos_12 (distinct no período)     = 442
leads_dia_email AS (
    SELECT
        lde.data_ref,
        lde.email_norm,
        cf.classif_final,
        ROW_NUMBER() OVER (
            PARTITION BY lde.email_norm
            ORDER BY lde.data_ref ASC
        ) AS rn_email
    FROM (
        SELECT DISTINCT data_ref, email_norm
        FROM leads_clean
    ) lde
    LEFT JOIN last_classif cf USING (email_norm)
),
leads_daily AS (
    SELECT
        data_ref,
        COUNT(*)                                                   AS leads_totais,
        COUNT(*) FILTER (
            WHERE rn_email = 1
              AND (classif_final ILIKE '%+12%' OR classif_final ILIKE '%-12%')
        )                                                          AS leads_qualificados,
        COUNT(*) FILTER (WHERE rn_email = 1 AND classif_final ILIKE '%+12%')
                                                                   AS leads_mais_12,
        COUNT(*) FILTER (WHERE rn_email = 1 AND classif_final ILIKE '%-12%')
                                                                   AS leads_menos_12
    FROM leads_dia_email
    GROUP BY data_ref
),
-- -----------------------------------------------------------------------------
-- Financeiro — direto de zoho_deals com data_hora_compra::date.
-- Inclui ambos os labels usados no Zoho ('Ganho' e 'Fechado Ganho').
-- amount/receita já vêm como numeric no FDW; o ::numeric é defensivo.
-- -----------------------------------------------------------------------------
deals_daily AS (
    SELECT
        zd.data_hora_compra::date                                   AS data_ref,
        SUM(zd.amount::numeric)                                     AS montante_total_geral,
        SUM(zd.receita::numeric)                                    AS receita_total_geral,
        COUNT(DISTINCT zd.id)                                       AS vendas_total_geral,
        COUNT(DISTINCT zd.id) FILTER (
            WHERE zd.tipo_venda = 'Novo cliente'
        )                                                           AS vendas_novas_total_geral
    FROM zoho_deals zd
    WHERE zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
      AND zd.stage IN ('Ganho', 'Fechado Ganho')
    GROUP BY zd.data_hora_compra::date
),
-- Investimento total geral — fonte validada da empresa.
invest_daily AS (
    SELECT
        data_ref,
        SUM(investimento_total) AS investimento_total_geral
    FROM bi.vw_investimento_diario
    WHERE data_ref BETWEEN :data_ini AND :data_fim
    GROUP BY data_ref
),
keys AS (
    SELECT data_ref FROM leads_daily
    UNION SELECT data_ref FROM deals_daily
    UNION SELECT data_ref FROM invest_daily
)
SELECT
    k.data_ref,
    COALESCE(i.investimento_total_geral, 0)::numeric    AS investimento_total_geral,
    COALESCE(l.leads_totais, 0)::bigint                 AS leads_totais,
    COALESCE(l.leads_qualificados, 0)::bigint           AS leads_qualificados,
    COALESCE(l.leads_mais_12, 0)::bigint                AS leads_mais_12,
    COALESCE(l.leads_menos_12, 0)::bigint               AS leads_menos_12,
    COALESCE(d.vendas_total_geral, 0)::bigint           AS vendas_total_geral,
    COALESCE(d.vendas_novas_total_geral, 0)::bigint     AS vendas_novas_total_geral,
    COALESCE(d.montante_total_geral, 0)::numeric        AS montante_total_geral,
    COALESCE(d.receita_total_geral, 0)::numeric         AS receita_total_geral
FROM keys k
LEFT JOIN leads_daily   l USING (data_ref)
LEFT JOIN deals_daily   d USING (data_ref)
LEFT JOIN invest_daily  i USING (data_ref)
ORDER BY k.data_ref;
