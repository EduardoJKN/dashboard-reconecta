-- =============================================================================
-- Campanhas — leads diários POR CANAL pela regra oficial da Visão Geral.
-- =============================================================================
-- Substitui o uso de bi.vw_mkt_leads_classificacao + bi.mv_mkt_funil nos
-- cards de leads / CPL e na Tendência diária da página Campanhas.
--
-- Fonte: bi_mkt.vw_visao_geral_canal_base (1 linha por (data_ref, canal,
--        email_normalizado), com prioridade Meta > Google > Pinterest >
--        LinkedIn > TikTok > YouTube > Organico > Outros já aplicada).
--
-- Regras (mesma semântica de mkt_visao_geral_canal.sql, mas com grão diário):
--   leads_totais (data_ref × canal) = COUNT(*) das linhas do canal no dia
--                                     → soma daily ↔ totais por canal
--                                       (Meta 690, Pinterest 1).
--   leads_qualif/+12/-12/nao_atua   = canal e classif vêm da ÚLTIMA row do
--                                     e-mail no período (created_at DESC) —
--                                     "canal_final" + "classif_final".
--                                     Cada e-mail é atribuído ao PRIMEIRO
--                                     dia em que aparece no seu canal_final.
--                                     → soma daily ↔ canal_final period
--                                       (Meta 578 qualif, +12 199, -12 379).
--
-- Normalização: 'Orgânico' (com acento, como vem da view) → 'Organico'.
-- =============================================================================
WITH base AS (
    SELECT
        data_ref,
        CASE WHEN canal = 'Orgânico' THEN 'Organico' ELSE canal END AS canal,
        email_normalizado,
        classificado,
        created_at
    FROM bi_mkt.vw_visao_geral_canal_base
    WHERE data_ref BETWEEN :data_ini AND :data_fim
),
last_row AS (
    -- Última row do e-mail no período → canal_final + classif_final canônicos
    SELECT DISTINCT ON (email_normalizado)
        email_normalizado,
        canal        AS canal_final,
        classificado AS classif_final
    FROM base
    ORDER BY email_normalizado, created_at DESC
),
qualif_atribuicao AS (
    -- 1 linha por e-mail no canal_final, atribuída ao primeiro dia em que
    -- o e-mail aparece NO canal_final. Garante que a soma das contagens
    -- diárias bate com o agregado canal_final do período.
    SELECT
        b.email_normalizado,
        lr.canal_final,
        lr.classif_final,
        MIN(b.data_ref) AS data_ref_first
    FROM base b
    JOIN last_row lr
      ON lr.email_normalizado = b.email_normalizado
     AND lr.canal_final       = b.canal
    GROUP BY b.email_normalizado, lr.canal_final, lr.classif_final
),
leads_totais_diario AS (
    SELECT
        data_ref,
        canal,
        COUNT(*) AS leads_totais
    FROM (SELECT DISTINCT data_ref, canal, email_normalizado FROM base) b
    GROUP BY data_ref, canal
),
classif_diario AS (
    SELECT
        data_ref_first AS data_ref,
        canal_final    AS canal,
        COUNT(*) FILTER (
            WHERE classif_final ILIKE '%+12%' OR classif_final ILIKE '%-12%'
        )                                                       AS leads_qualificados,
        COUNT(*) FILTER (WHERE classif_final ILIKE '%+12%')     AS leads_mais_12,
        COUNT(*) FILTER (WHERE classif_final ILIKE '%-12%')     AS leads_menos_12,
        COUNT(*) FILTER (WHERE classif_final = 'Não atua')      AS leads_nao_atua
    FROM qualif_atribuicao
    GROUP BY data_ref_first, canal_final
),
keys AS (
    SELECT data_ref, canal FROM leads_totais_diario
    UNION SELECT data_ref, canal FROM classif_diario
)
SELECT
    k.data_ref,
    k.canal,
    COALESCE(ltd.leads_totais, 0)::bigint        AS leads_totais,
    COALESCE(cd.leads_qualificados, 0)::bigint   AS leads_qualificados,
    COALESCE(cd.leads_mais_12, 0)::bigint        AS leads_mais_12,
    COALESCE(cd.leads_menos_12, 0)::bigint       AS leads_menos_12,
    COALESCE(cd.leads_nao_atua, 0)::bigint       AS leads_nao_atua
FROM keys k
LEFT JOIN leads_totais_diario ltd USING (data_ref, canal)
LEFT JOIN classif_diario      cd  USING (data_ref, canal)
ORDER BY data_ref, canal;
