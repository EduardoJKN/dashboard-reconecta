-- =============================================================================
-- Visão Geral Marketing — KPIs completos POR CANAL (financeiro + leads + invest).
-- =============================================================================
-- Substitui o uso parcial do mkt_visao_geral_canal.sql (só leads) quando o
-- usuário filtra canal: agora os blocos Visão executiva, Geração de leads e
-- Eficiência inteiros podem ser recalculados sobre a parcela atribuída.
--
-- Fontes:
--   - investimento_total_geral  ← bi.vw_mkt_overview (mídia paga, por canal)
--   - leads_*                   ← bi_mkt.vw_visao_geral_canal_base
--                                 (mesma regra de mkt_visao_geral_canal.sql)
--   - vendas/montante/receita   ← zoho_deals atribuídos via lead
--                                 (zoho_id > session_id > email)
--                                 deals sem lead match → canal = 'Sem canal'
--
-- Normalização: 'Orgânico' → 'Organico' em invest_canal e em base_leads
-- (a view devolve com acento; o filtro do dashboard usa sem acento).
--
-- Regra oficial de atribuição (validada com o time):
--   Para cada deal, encontra o lead canônico via prioridade
--   zoho_id (1) > session_id (2) > email (3); o canal sai da row daquele
--   lead específico em bi_mkt.vw_visao_geral_canal_base. Por isso o canal
--   é definido pelo MATCH (session_id no caso de tracking pixel), e NÃO
--   pela "última linha" do e-mail no período — um e-mail que aparece em
--   Meta (com session_id) e depois Organico (orgânico) atribui ao Meta
--   se o deal carregar o session_id do row Meta.
--
-- Validação abril/2026 (regra oficial · prioridade match por session_id):
--   Total: investimento 102199.89 · leads 854 · qualif 701 (+12 259 / -12 442)
--          vendas 57 · novas 50 · montante 1216572 · receita 774182
--   Por canal:
--     Meta:      invest 102185.30 · leads 690 · qualif 578 · vendas 27 · novas 25 · montante 534000 · receita 385500
--     Google:    invest 14.59     · leads 0   · vendas 0
--     Organico:  invest 0         · leads 133 · qualif 101 · vendas 9  · novas 9  · montante 241000 · receita 132300
--     Outros:    invest 0         · leads 30  · qualif 21  · vendas 2  · novas 1  · montante 32500  · receita 30000
--     Pinterest: invest 0         · leads 1   · qualif 1   · vendas 0
--     Sem canal: invest 0         · leads 0   · vendas 19 · novas 15 · montante 409072 · receita 226382
-- =============================================================================
WITH
-- -----------------------------------------------------------------------------
-- 1) Investimento por canal — bi.vw_mkt_overview (mídia paga consolidada).
-- -----------------------------------------------------------------------------
invest_canal AS (
    SELECT
        CASE WHEN canal = 'Orgânico' THEN 'Organico' ELSE canal END AS canal,
        SUM(investimento) AS investimento_total_geral
    FROM bi.vw_mkt_overview
    WHERE data_ref BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),

-- -----------------------------------------------------------------------------
-- 2) Leads/canal — replica mkt_visao_geral_canal.sql.
-- -----------------------------------------------------------------------------
base_leads AS (
    SELECT
        data_ref,
        CASE WHEN canal = 'Orgânico' THEN 'Organico' ELSE canal END AS canal,
        email_normalizado,
        classificado,
        created_at
    FROM bi_mkt.vw_visao_geral_canal_base
    WHERE data_ref BETWEEN :data_ini AND :data_fim
),
last_row_lead AS (
    SELECT DISTINCT ON (email_normalizado)
        email_normalizado,
        canal        AS canal_final,
        classificado AS classif_final
    FROM base_leads
    ORDER BY email_normalizado, created_at DESC
),
leads_canal AS (
    SELECT canal, COUNT(*) AS leads_totais
    FROM base_leads
    GROUP BY canal
),
classif_canal AS (
    SELECT
        canal_final AS canal,
        COUNT(*) FILTER (
            WHERE classif_final ILIKE '%+12%' OR classif_final ILIKE '%-12%'
        )                                                       AS leads_qualificados,
        COUNT(*) FILTER (WHERE classif_final ILIKE '%+12%')     AS leads_mais_12,
        COUNT(*) FILTER (WHERE classif_final ILIKE '%-12%')     AS leads_menos_12,
        COUNT(*) FILTER (WHERE classif_final = 'Não atua')      AS leads_nao_atua
    FROM last_row_lead
    GROUP BY canal_final
),

-- -----------------------------------------------------------------------------
-- 3) Atribuição financeira — zoho_deals → lead → canal.
-- Best lead per deal: prioridade zoho_id (1) > session_id (2) > email (3),
-- desempate por l.created_at ASC. Guarda data_ref e email do lead matched
-- pra resolver canal direto contra a view (mesmo se o lead for fora da
-- janela do dashboard).
-- -----------------------------------------------------------------------------
deal_lead AS (
    SELECT DISTINCT ON (zd.id)
        zd.id                                  AS deal_id,
        zd.amount::numeric                     AS amount_num,
        zd.receita::numeric                    AS receita_num,
        zd.tipo_venda,
        l.created_at::date                     AS lead_data_ref,
        lower(btrim(l.email))                  AS email_norm
    FROM zoho_deals zd
    LEFT JOIN ext_reconecta.leads l
      ON (l.zoho_id    IS NOT NULL AND l.zoho_id        = zd.id)
      OR (l.session_id IS NOT NULL AND l.session_id::text = zd.session_id)
      OR (l.email      IS NOT NULL
          AND lower(btrim(l.email)) = lower(btrim(zd.email)))
    WHERE zd.stage IN ('Ganho', 'Fechado Ganho')
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
    ORDER BY zd.id,
        CASE
            WHEN l.zoho_id    IS NOT NULL AND l.zoho_id    = zd.id            THEN 1
            WHEN l.session_id IS NOT NULL AND l.session_id::text = zd.session_id THEN 2
            WHEN l.email      IS NOT NULL
                 AND lower(btrim(l.email)) = lower(btrim(zd.email))           THEN 3
            ELSE 9
        END,
        l.created_at DESC NULLS LAST
),
-- Canal do deal = canal da row exata (lead_data_ref, email_norm) na view,
-- ou seja, da linha de lead que casou pela prioridade
-- zoho_id > session_id > email definida em deal_lead acima. É essa
-- semântica "canal do lead matched" que faz o session_id do tracking
-- pixel ganhar do e-mail/última linha — alinhada com a regra oficial.
--
-- Lookup sem filtro de data pra que leads anteriores à janela do
-- dashboard ainda atribuam corretamente.
deal_canal AS (
    SELECT
        dl.deal_id,
        dl.amount_num,
        dl.receita_num,
        dl.tipo_venda,
        COALESCE(
            CASE WHEN bl.canal = 'Orgânico' THEN 'Organico' ELSE bl.canal END,
            'Sem canal'
        ) AS canal_final
    FROM deal_lead dl
    LEFT JOIN bi_mkt.vw_visao_geral_canal_base bl
           ON bl.email_normalizado = dl.email_norm
          AND bl.data_ref          = dl.lead_data_ref
),
deals_canal_agg AS (
    SELECT
        canal_final                                                            AS canal,
        COUNT(DISTINCT deal_id)                                                AS vendas_total_geral,
        COUNT(DISTINCT deal_id) FILTER (
            WHERE tipo_venda = 'Novo cliente'
        )                                                                      AS vendas_novas_total_geral,
        SUM(amount_num)                                                        AS montante_total_geral,
        SUM(receita_num)                                                       AS receita_total_geral
    FROM deal_canal
    GROUP BY 1
),

-- -----------------------------------------------------------------------------
-- 4) Universo de canais — UNION das fontes (qualquer canal com ≥1 fonte).
-- -----------------------------------------------------------------------------
canais AS (
    SELECT canal FROM invest_canal
    UNION SELECT canal FROM leads_canal
    UNION SELECT canal FROM classif_canal
    UNION SELECT canal FROM deals_canal_agg
)

SELECT
    c.canal,
    COALESCE(ic.investimento_total_geral, 0)::numeric    AS investimento_total_geral,
    COALESCE(lc.leads_totais, 0)::bigint                 AS leads_totais,
    COALESCE(cc.leads_qualificados, 0)::bigint           AS leads_qualificados,
    COALESCE(cc.leads_mais_12, 0)::bigint                AS leads_mais_12,
    COALESCE(cc.leads_menos_12, 0)::bigint               AS leads_menos_12,
    COALESCE(cc.leads_nao_atua, 0)::bigint               AS leads_nao_atua,
    COALESCE(dca.vendas_total_geral, 0)::bigint          AS vendas_total_geral,
    COALESCE(dca.vendas_novas_total_geral, 0)::bigint    AS vendas_novas_total_geral,
    COALESCE(dca.montante_total_geral, 0)::numeric       AS montante_total_geral,
    COALESCE(dca.receita_total_geral, 0)::numeric        AS receita_total_geral,
    -- Derivados — recalculados sobre os SUMs do canal (Python recalcula
    -- de novo quando agrega múltiplos canais via SUM e ratio).
    CASE WHEN COALESCE(ic.investimento_total_geral, 0) = 0 THEN 0::numeric
         ELSE COALESCE(dca.montante_total_geral, 0) / ic.investimento_total_geral
    END AS roas_total_geral,
    CASE WHEN COALESCE(lc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ic.investimento_total_geral, 0) / lc.leads_totais
    END AS cpl,
    CASE WHEN COALESCE(cc.leads_qualificados, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ic.investimento_total_geral, 0) / cc.leads_qualificados
    END AS cpl_qualificado,
    CASE WHEN COALESCE(cc.leads_mais_12, 0) = 0 THEN 0::numeric
         ELSE COALESCE(ic.investimento_total_geral, 0) / cc.leads_mais_12
    END AS cpl_mais_12,
    CASE WHEN COALESCE(lc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(cc.leads_qualificados, 0)::numeric / lc.leads_totais * 100
    END AS taxa_qualificacao,
    CASE WHEN COALESCE(lc.leads_totais, 0) = 0 THEN 0::numeric
         ELSE COALESCE(cc.leads_mais_12, 0)::numeric / lc.leads_totais * 100
    END AS taxa_qualificacao_mais_12,
    CASE WHEN COALESCE(dca.vendas_total_geral, 0) = 0 THEN 0::numeric
         ELSE COALESCE(dca.montante_total_geral, 0) / dca.vendas_total_geral
    END AS ticket_medio
FROM canais c
LEFT JOIN invest_canal     ic  USING (canal)
LEFT JOIN leads_canal      lc  USING (canal)
LEFT JOIN classif_canal    cc  USING (canal)
LEFT JOIN deals_canal_agg  dca USING (canal)
ORDER BY investimento_total_geral DESC, leads_totais DESC NULLS LAST;
