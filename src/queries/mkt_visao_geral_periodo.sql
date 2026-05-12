-- =============================================================================
-- Visão Geral Marketing — KPIs do período (cards do topo).
-- =============================================================================
-- Separa a regra dos CARDS da regra da série diária:
--   - cards de geração de leads: e-mail deduplicado no período POR BUCKET
--     de classificação. Os buckets podem se sobrepor: se um e-mail teve
--     'Atua -12' e depois 'Atua +12' no mesmo período, conta em ambos.
--   - tendência diária: fica em `mkt_visao_geral_diario.sql` e usa a
--     classificação da própria linha do dia
--
-- Validação abril/2026 (fontes atuais do projeto):
--   leads_totais          = 854
--   leads_qualificados    = 701
--   leads_mais_12         = 259
--   leads_menos_12        = 443
--   leads_nao_atua        = 118
-- =============================================================================
WITH leads_clean AS (
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
leads_totais AS (
    SELECT COUNT(*)::bigint AS leads_totais
    FROM (
        SELECT DISTINCT data_ref, email_norm
        FROM leads_clean
    ) x
),
leads_periodo AS (
    SELECT
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm IN ('atua +12', 'atua -12')
        )::bigint AS leads_qualificados,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm = 'atua +12'
        )::bigint AS leads_mais_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm = 'atua -12'
        )::bigint AS leads_menos_12,
        COUNT(DISTINCT email_norm) FILTER (
            WHERE classif_norm IN ('não atua', 'nao atua')
        )::bigint AS leads_nao_atua
    FROM leads_clean
),
deals_periodo AS (
    SELECT
        SUM(zd.amount::numeric)::numeric                                AS montante_total_geral,
        SUM(zd.receita::numeric)::numeric                               AS receita_total_geral,
        COUNT(DISTINCT zd.id)::bigint                                   AS vendas_total_geral,
        COUNT(DISTINCT zd.id) FILTER (
            WHERE zd.tipo_venda = 'Novo cliente'
        )::bigint                                                       AS vendas_novas_total_geral
    FROM zoho_deals zd
    WHERE zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
      AND zd.stage IN ('Ganho', 'Fechado Ganho')
),
invest_periodo AS (
    SELECT
        SUM(investimento_total)::numeric AS investimento_total_geral
    FROM bi.vw_investimento_diario
    WHERE data_ref BETWEEN :data_ini AND :data_fim
)
SELECT
    COALESCE(i.investimento_total_geral, 0)::numeric    AS investimento_total_geral,
    COALESCE(lt.leads_totais, 0)::bigint                AS leads_totais,
    COALESCE(lp.leads_qualificados, 0)::bigint          AS leads_qualificados,
    COALESCE(lp.leads_mais_12, 0)::bigint               AS leads_mais_12,
    COALESCE(lp.leads_menos_12, 0)::bigint              AS leads_menos_12,
    COALESCE(lp.leads_nao_atua, 0)::bigint              AS leads_nao_atua,
    COALESCE(d.vendas_total_geral, 0)::bigint           AS vendas_total_geral,
    COALESCE(d.vendas_novas_total_geral, 0)::bigint     AS vendas_novas_total_geral,
    COALESCE(d.montante_total_geral, 0)::numeric        AS montante_total_geral,
    COALESCE(d.receita_total_geral, 0)::numeric         AS receita_total_geral
FROM invest_periodo i
CROSS JOIN leads_totais lt
CROSS JOIN leads_periodo lp
CROSS JOIN deals_periodo d;
