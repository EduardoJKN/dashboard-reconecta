-- =============================================================================
-- Visão Geral Marketing — KPIs diários (regra oficial validada em pgAdmin).
-- =============================================================================
-- Fonte enxuta para os cards principais. Substitui mkt_overview_v2.sql nessa
-- página. Não usa LATERAL JOIN com zoho_deals (que estava pesado) — agrega
-- direto cada fonte.
--
-- Regras:
--   investimento_total_geral = 102.199,89   ← bi.vw_investimento_diario
--   leads_totais             = e-mails únicos/dia via ext_reconecta.leads
--   leads_qualificados       = e-mails únicos/dia com classificado do PRÓPRIO dia
--                               em ('Atua +12','Atua -12')
--   leads_mais_12            = e-mails únicos/dia com classificado = 'Atua +12'
--   leads_menos_12           = e-mails únicos/dia com classificado = 'Atua -12'
--   leads_nao_atua           = e-mails únicos/dia com classificado = 'Não atua'
--   vendas_total_geral       = 57           ← zoho_deals (Ganho/Fechado Ganho)
--   vendas_novas_total_geral = 50           ← tipo_venda = 'Novo cliente'
--   montante_total_geral     = 1.216.572    ← SUM(amount::numeric)
--   receita_total_geral      = 774.182      ← SUM(receita::numeric)
-- =============================================================================
WITH
-- -----------------------------------------------------------------------------
-- Leads — base limpa: filtra janela e exclui e-mails de teste/internos.
-- created_at::date é o eixo canônico (mesma regra usada em pgAdmin / Looker).
-- A classificação usada nos buckets (+12 / -12 / Não atua) é a da PRÓPRIA
-- linha do dia. Não há classificação canônica no período nem `rn_email = 1`.
-- -----------------------------------------------------------------------------
leads_clean AS (
    SELECT
        l.created_at::date                AS data_ref,
        lower(btrim(l.email))             AS email_norm,
        lower(btrim(coalesce(l.classificado, ''))) AS classif_norm
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_daily AS (
    SELECT
        data_ref,
        COUNT(DISTINCT email_norm)                                 AS leads_totais,
        COUNT(*) FILTER (
            WHERE classif_norm IN ('atua +12', 'atua -12')
        )                                                          AS linhas_qualificadas,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm IN ('atua +12', 'atua -12')
        )                                                          AS leads_qualificados,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm = 'atua +12'
        )                                                          AS leads_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm = 'atua -12'
        )                                                          AS leads_menos_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm IN ('não atua', 'nao atua')
        )                                                          AS leads_nao_atua
    FROM leads_clean
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
    COALESCE(l.leads_nao_atua, 0)::bigint               AS leads_nao_atua,
    COALESCE(d.vendas_total_geral, 0)::bigint           AS vendas_total_geral,
    COALESCE(d.vendas_novas_total_geral, 0)::bigint     AS vendas_novas_total_geral,
    COALESCE(d.montante_total_geral, 0)::numeric        AS montante_total_geral,
    COALESCE(d.receita_total_geral, 0)::numeric         AS receita_total_geral
FROM keys k
LEFT JOIN leads_daily   l USING (data_ref)
LEFT JOIN deals_daily   d USING (data_ref)
LEFT JOIN invest_daily  i USING (data_ref)
ORDER BY k.data_ref;
