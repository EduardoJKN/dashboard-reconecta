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
),

-- -----------------------------------------------------------------------------
-- Aplicações (Typeform) — bloco "Aplicações" da Visão Geral Marketing.
-- -----------------------------------------------------------------------------
-- Regra oficial (Looker, validada no schema real do ambiente):
--   fonte:        fdw_reconecta.typeform_aplicacoes
--   dedupe:       (email_norm, created_at::date) — mais recente por dia (rn=1)
--   granularidade: PRESERVADA em (email_norm, data_ref) — o mesmo e-mail em
--     dois dias diferentes do período conta como DUAS aplicações. Nunca
--     colapsar para COUNT(DISTINCT email_norm) sozinho.
--   exclusões: e-mail no evento de agosto (global, existe em leads em
--     qualquer data) + lead do mesmo dia com campanha de diagnóstico +
--     lead do mesmo dia com funil_origem = QUIZ.
--   orgânico/tráfego: BOOL_OR(utm_campaign preenchida) nos leads do mesmo
--     (email, dia); sem lead correspondente no dia = orgânico.
aplicacoes_dedup AS (
    SELECT email_norm, data_ref, classificado_norm
    FROM (
        SELECT
            lower(btrim(ta.email))        AS email_norm,
            ta.created_at::date           AS data_ref,
            lower(btrim(ta.classificado)) AS classificado_norm,
            ROW_NUMBER() OVER (
                PARTITION BY lower(btrim(ta.email)), ta.created_at::date
                ORDER BY ta.created_at DESC
            ) AS rn
        FROM fdw_reconecta.typeform_aplicacoes ta
        WHERE ta.created_at::date BETWEEN :data_ini AND :data_fim
          AND ta.dados_completos IS TRUE
          AND ta.email IS NOT NULL
          AND btrim(ta.email) <> ''
          AND lower(btrim(ta.email)) NOT LIKE '%teste%'
          AND lower(btrim(ta.email)) NOT LIKE '%smarts%'
          AND lower(btrim(ta.email)) NOT LIKE '%smartscale%'
          AND lower(btrim(ta.email)) NOT LIKE '%reconecta%'
    ) sub
    WHERE rn = 1
),
-- Leads consolidados por (e-mail, dia) no período — mesmos filtros oficiais
-- de e-mail usados em aplicacoes_dedup, para não haver assimetria entre as
-- duas bases. Usado para: tráfego×orgânico, exclusão de diagnóstico e QUIZ.
-- MATERIALIZED: força o Postgres a resolver esta CTE UMA VEZ e agregar em
-- hash join. Sem essa dica, o planner empurra o LEFT JOIN abaixo pra dentro
-- do foreign scan de ext_reconecta.leads e reexecuta a agregação via nested
-- loop — 1 round-trip FDW por linha de aplicação (~700 loops, ~15s). Com
-- MATERIALIZED cai pra ~0,3s (validado abr/2026, EXPLAIN ANALYZE).
leads_dia_aplicacoes AS MATERIALIZED (
    SELECT
        lower(btrim(l.email)) AS email_norm,
        l.created_at::date    AS data_ref,
        BOOL_OR(NULLIF(btrim(l.utm_campaign), '') IS NOT NULL) AS tem_campanha,
        BOOL_OR(
            lower(btrim(l.utm_campaign)) LIKE '%diagnóstico | teste | cbo | purchase%'
            OR lower(btrim(l.utm_campaign)) LIKE '%diagnostico | teste | cbo | purchase%'
        ) AS tem_campanha_diagnostico,
        BOOL_OR(upper(btrim(l.funil_origem)) = 'QUIZ') AS tem_quiz
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(btrim(l.email)) NOT LIKE '%teste%'
      AND lower(btrim(l.email)) NOT LIKE '%smarts%'
      AND lower(btrim(l.email)) NOT LIKE '%smartscale%'
      AND lower(btrim(l.email)) NOT LIKE '%reconecta%'
    GROUP BY 1, 2
),
-- E-mails a excluir globalmente: cadastrados no evento de agosto/26 E
-- existentes em ext_reconecta.leads em QUALQUER data (sem corte de período).
-- MATERIALIZED pelo mesmo motivo do CTE acima — evita re-scan da FDW por
-- linha de aplicação no NOT EXISTS mais abaixo.
emails_evento_confirmados AS MATERIALIZED (
    SELECT DISTINCT lower(btrim(c.email)) AS email_norm
    FROM fdw_reconecta.evento_agosto_26_cadastro c
    WHERE c.email IS NOT NULL
      AND btrim(c.email) <> ''
      AND EXISTS (
          SELECT 1
          FROM ext_reconecta.leads l
          WHERE lower(btrim(l.email)) = lower(btrim(c.email))
            AND l.email IS NOT NULL
            AND btrim(l.email) <> ''
            AND lower(btrim(l.email)) NOT LIKE '%teste%'
            AND lower(btrim(l.email)) NOT LIKE '%smarts%'
            AND lower(btrim(l.email)) NOT LIKE '%smartscale%'
            AND lower(btrim(l.email)) NOT LIKE '%reconecta%'
      )
),
-- Aplicações válidas finais — 1 linha por (email_norm, data_ref), com o
-- flag de campanha (tráfego×orgânico) do lead do mesmo dia.
aplicacoes_finais AS (
    SELECT
        ad.email_norm,
        ad.data_ref,
        ad.classificado_norm,
        COALESCE(ld.tem_campanha, FALSE) AS tem_campanha
    FROM aplicacoes_dedup ad
    LEFT JOIN leads_dia_aplicacoes ld
           ON ld.email_norm = ad.email_norm
          AND ld.data_ref   = ad.data_ref
    WHERE NOT EXISTS (
        SELECT 1 FROM emails_evento_confirmados eec
        WHERE eec.email_norm = ad.email_norm
    )
    AND COALESCE(ld.tem_campanha_diagnostico, FALSE) = FALSE
    AND COALESCE(ld.tem_quiz, FALSE) = FALSE
),
aplicacoes_periodo AS (
    SELECT
        COUNT(*)::bigint                                                  AS aplicacoes_totais,
        COUNT(*) FILTER (
            WHERE classificado_norm IN ('atua +12', 'atua+12', '+12')
        )::bigint                                                         AS aplicacoes_mais_12,
        COUNT(*) FILTER (
            WHERE classificado_norm IN ('atua -12', 'atua-12', '-12')
        )::bigint                                                         AS aplicacoes_menos_12,
        COUNT(*) FILTER (WHERE NOT tem_campanha)::bigint                  AS aplicacoes_organicas,
        COUNT(*) FILTER (WHERE tem_campanha)::bigint                      AS aplicacoes_trafego
    FROM aplicacoes_finais
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
    COALESCE(d.receita_total_geral, 0)::numeric         AS receita_total_geral,
    COALESCE(ap.aplicacoes_totais, 0)::bigint           AS aplicacoes_totais,
    COALESCE(ap.aplicacoes_mais_12, 0)::bigint          AS aplicacoes_mais_12,
    COALESCE(ap.aplicacoes_menos_12, 0)::bigint         AS aplicacoes_menos_12,
    COALESCE(ap.aplicacoes_organicas, 0)::bigint        AS aplicacoes_organicas,
    COALESCE(ap.aplicacoes_trafego, 0)::bigint          AS aplicacoes_trafego
FROM invest_periodo i
CROSS JOIN leads_totais lt
CROSS JOIN leads_periodo lp
CROSS JOIN deals_periodo d
CROSS JOIN aplicacoes_periodo ap;
