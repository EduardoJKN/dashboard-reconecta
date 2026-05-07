-- =============================================================================
-- Visão Geral Marketing — KPIs de geração de leads POR CANAL.
-- =============================================================================
-- Fonte: bi_mkt.vw_visao_geral_canal_base — 1 linha por (data_ref, canal,
-- email_normalizado), com prioridade Meta > Google > Pinterest > LinkedIn >
-- TikTok > YouTube > Organico > Outros aplicada quando o mesmo e-mail aparece
-- em mais de um canal no MESMO dia.
--
-- IMPORTANTE — normalização do nome do canal:
--   A view bi_mkt.vw_visao_geral_canal_base devolve 'Orgânico' (com acento),
--   mas o filtro do dashboard / CANAIS_VISIVEIS_OVERVIEW usam 'Organico'
--   (sem acento) como label canônico. Sem o alias abaixo, selecionar
--   'Organico' no header não casa nenhuma linha e os cards de Geração de
--   leads ficam mostrando o total geral. Normalizamos aqui pra não tocar
--   na view (que pode ser consumida por outras queries).
--
-- Regras (validadas em pgAdmin · abril/2026):
--   leads_totais (canal)         = COUNT(*) das linhas do canal — soma a 854
--   leads_qualif/+12/-12/nao_atua = canal e classif vêm da ÚLTIMA linha do
--                                   e-mail no período (created_at DESC).
--                                   Cada e-mail entra em exatamente 1 canal.
--                                   Soma cross-canais bate com a Visão Geral
--                                   (qualif=701, +12=259, -12=442).
--
-- Esperado abril/2026:
--   Meta:      690 | qualif 578 | +12 199 | -12 379 | não atua 83
--   Organico:  133 | qualif 101 | +12 48  | -12 53  | não atua 23
--   Outros:    30  | qualif 21  | +12 11  | -12 10  | não atua 8
--   Pinterest: 1   | qualif 1   | +12 1   | -12 0   | não atua 0
-- =============================================================================
WITH
base AS (
    SELECT
        data_ref,
        CASE WHEN canal = 'Orgânico' THEN 'Organico' ELSE canal END AS canal,
        email_normalizado,
        classificado,
        created_at
    FROM bi_mkt.vw_visao_geral_canal_base
    WHERE data_ref BETWEEN :data_ini AND :data_fim
),
-- Última linha do e-mail no período → canal_final + classif_final canônicos.
last_row AS (
    SELECT DISTINCT ON (email_normalizado)
        email_normalizado,
        canal        AS canal_final,
        classificado AS classif_final
    FROM base
    ORDER BY email_normalizado, created_at DESC
),
-- leads_totais por canal: COUNT(*) das linhas (data_ref, canal, email).
leads_canal AS (
    SELECT canal, COUNT(*) AS leads_totais
    FROM base
    GROUP BY canal
),
-- Classificação canônica por canal: 1 e-mail = 1 canal_final.
classif_canal AS (
    SELECT
        canal_final AS canal,
        COUNT(*) FILTER (
            WHERE classif_final ILIKE '%+12%' OR classif_final ILIKE '%-12%'
        )                                                          AS leads_qualificados,
        COUNT(*) FILTER (WHERE classif_final ILIKE '%+12%')        AS leads_mais_12,
        COUNT(*) FILTER (WHERE classif_final ILIKE '%-12%')        AS leads_menos_12,
        COUNT(*) FILTER (WHERE classif_final = 'Não atua')         AS leads_nao_atua
    FROM last_row
    GROUP BY canal_final
)
SELECT
    COALESCE(lc.canal, cc.canal)                AS canal,
    COALESCE(lc.leads_totais, 0)::bigint        AS leads_totais,
    COALESCE(cc.leads_qualificados, 0)::bigint  AS leads_qualificados,
    COALESCE(cc.leads_mais_12, 0)::bigint       AS leads_mais_12,
    COALESCE(cc.leads_menos_12, 0)::bigint      AS leads_menos_12,
    COALESCE(cc.leads_nao_atua, 0)::bigint      AS leads_nao_atua
FROM leads_canal lc
FULL OUTER JOIN classif_canal cc USING (canal)
ORDER BY leads_totais DESC NULLS LAST;
