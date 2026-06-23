-- =============================================================================
-- One Page — regra legada do Looker (v2 — otimizada para Funil / período).
-- =============================================================================
-- Equivalente semântico a `one_page_legacy_diario.sql` (v1).
--
-- Otimizações (sem mudar regra de negócio):
--   1. `leads_email_zoho` — só e-mails com aplicação no período (não varre
--      toda a tabela de leads).
--   2. `deals_com_agendamento` — EXISTS só nos deals ligados a esses e-mails
--      (não materializa todos os deals com agendamento histórico).
-- =============================================================================
WITH
-- ---------------------------------------------------------------------------
-- Leads (ext_reconecta.leads) — daily-distinct por e-mail.
-- ---------------------------------------------------------------------------
leads_clean AS (
    SELECT
        l.created_at::date     AS data,
        lower(btrim(l.email))  AS email_norm
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_dia AS (
    SELECT data, COUNT(DISTINCT email_norm)::bigint AS novos_leads
    FROM leads_clean
    GROUP BY data
),

-- ---------------------------------------------------------------------------
-- Aplicações (fdw_reconecta.typeform_aplicacoes) — regra Looker:
--   created_at::date · LOWER(TRIM(email)) · dados_completos = TRUE
--   · e-mails únicos no período (cards usam *_periodo)
-- Filtros de teste quando :excluir_testes_aplicacoes = 1 (padrão na UI).
-- ---------------------------------------------------------------------------
aplicacoes_clean AS (
    SELECT
        ta.created_at::date                            AS data,
        lower(btrim(ta.email))                         AS email_norm,
        lower(btrim(coalesce(ta.classificado, '')))    AS classif_norm
    FROM fdw_reconecta.typeform_aplicacoes ta
    WHERE ta.created_at::date BETWEEN :data_ini AND :data_fim
      AND ta.dados_completos IS TRUE
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
-- 1 e-mail por dia (flags ±12 agregadas com BOOL_OR nas submissões do dia).
aplicacoes_dia_email AS (
    SELECT
        data,
        email_norm,
        BOOL_OR(classif_norm IN ('atua +12', 'atua+12', '+12'))  AS tem_mais_12,
        BOOL_OR(classif_norm IN ('atua -12', 'atua-12', '-12'))  AS tem_menos_12,
        BOOL_OR(classif_norm IN ('não atua', 'nao atua'))        AS tem_nao_atua
    FROM aplicacoes_clean
    GROUP BY data, email_norm
),
aplicacoes_dia AS (
    SELECT
        data,
        COUNT(*)::bigint                              AS novas_aplicacoes,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint     AS aplicacoes_mais_12,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint    AS aplicacoes_menos_12,
        COUNT(*) FILTER (WHERE tem_nao_atua)::bigint    AS aplicacoes_nao_atua
    FROM aplicacoes_dia_email
    GROUP BY data
),
-- 1 e-mail no período (dedupe para cards KPI — não somar dias).
aplicacoes_email_periodo AS (
    SELECT
        email_norm,
        BOOL_OR(classif_norm IN ('atua +12', 'atua+12', '+12'))  AS tem_mais_12,
        BOOL_OR(classif_norm IN ('atua -12', 'atua-12', '-12'))  AS tem_menos_12,
        BOOL_OR(classif_norm IN ('não atua', 'nao atua'))        AS tem_nao_atua
    FROM aplicacoes_clean
    GROUP BY email_norm
),
-- COUNT(*) aqui = COUNT(DISTINCT email_norm) — 1 linha por e-mail no período.
aplicacoes_periodo AS (
    SELECT
        COUNT(*)::bigint                              AS novas_aplicacoes_periodo,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint     AS aplicacoes_mais_12_periodo,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint    AS aplicacoes_menos_12_periodo,
        COUNT(*) FILTER (WHERE tem_nao_atua)::bigint    AS aplicacoes_nao_atua_periodo
    FROM aplicacoes_email_periodo
),

-- ---------------------------------------------------------------------------
-- Agendamentos (zoho_activities) — Consulta/Indicação criadas no período.
-- O e-mail vem do deal pareado por `what_id`. Activities sem deal pareado
-- ficam de fora — não há como cruzar com aplicação por e-mail.
-- ---------------------------------------------------------------------------
acts AS (
    SELECT
        a.id                  AS activity_id,
        a.what_id             AS deal_id,
        a.created_time::date  AS data
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.created_time::date BETWEEN :data_ini AND :data_fim
),
acts_emails AS (
    SELECT
        a.data,
        a.activity_id,
        lower(btrim(zd.email))  AS email_norm
    FROM acts a
    LEFT JOIN zoho_deals zd ON zd.id = a.deal_id
    WHERE zd.email IS NOT NULL
      AND btrim(zd.email) <> ''
),
agendamentos_dia AS (
    SELECT
        data,
        COUNT(DISTINCT activity_id)::bigint AS agendamentos,
        COUNT(DISTINCT email_norm)::bigint  AS emails_com_agendamento
    FROM acts_emails
    GROUP BY data
),

-- ---------------------------------------------------------------------------
-- Aplicação × Agendamento — REGRA REVISADA: jornada
-- aplicação → lead → deal → agendamento, via `leads.zoho_id`.
--
-- Mudança vs versão anterior (match direto `aplicacao.email = deal.email`
-- exigindo data igual):
--   • robustez a divergência de e-mail entre aplicação e deal (lead
--     corrige o e-mail no Zoho, mas a aplicação no Typeform mantém o
--     original — antes esses casos eram perdidos);
--   • captura jornada completa — `Opção A` confirmada com user:
--     agendamento pode ter sido marcado DEPOIS do fim do período da
--     One Page e ainda assim contar. A pergunta respondida é:
--     "Das aplicações DO PERÍODO, quantas viraram agendamento (em
--     qualquer momento)?"
--
-- Dedupe da ponte email → zoho_id: versão MAIS RECENTE por e-mail
-- (`ORDER BY timestamp DESC NULLS LAST, id DESC`) — mesmo padrão usado
-- em outras SQLs do projeto (vd. `one_page_prevendas_por_fonte.sql`).
-- ---------------------------------------------------------------------------

-- Ponte e-mail → zoho_id — apenas e-mails com aplicação no período.
aplicacoes_emails_universo AS (
    SELECT DISTINCT email_norm
    FROM aplicacoes_clean
),
leads_email_zoho AS (
    SELECT DISTINCT ON (lower(btrim(l.email)))
        lower(btrim(l.email))   AS email_norm,
        l.zoho_id::text         AS deal_id
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
    ORDER BY lower(btrim(l.email)),
             l."timestamp" DESC NULLS LAST,
             l.id DESC
),
-- Deals com agendamento — só para deals ligados às aplicações do período.
deals_com_agendamento AS (
    SELECT DISTINCT zd.id::text AS deal_id
    FROM leads_email_zoho lez
    INNER JOIN zoho_deals zd ON zd.id::text = lez.deal_id
    INNER JOIN zoho_activities a ON a.what_id = zd.id
        AND a.activity_type IN ('Consulta', 'Indicação')
),
-- Match final aplicação → lead → deal → agendamento (e-mail único/dia).
apl_com_ag AS (
    SELECT
        ad.data,
        COUNT(DISTINCT ad.email_norm)::bigint                         AS aplicacoes_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_mais_12)::bigint
                                                                      AS aplicacoes_mais_12_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_menos_12)::bigint
                                                                      AS aplicacoes_menos_12_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_nao_atua)::bigint
                                                                      AS aplicacoes_nao_atua_com_agendamento
    FROM aplicacoes_dia_email     ad
    JOIN leads_email_zoho       lez ON lez.email_norm = ad.email_norm
    JOIN deals_com_agendamento  dca ON dca.deal_id = lez.deal_id
    GROUP BY ad.data
),
-- Mesma jornada, dedupe no período (denominador dos % Agendamento nos cards).
apl_com_ag_periodo AS (
    SELECT
        COUNT(DISTINCT ap.email_norm)::bigint                         AS aplicacoes_com_agendamento_periodo,
        COUNT(DISTINCT ap.email_norm) FILTER (WHERE ap.tem_mais_12)::bigint
                                                                      AS aplicacoes_mais_12_com_agendamento_periodo,
        COUNT(DISTINCT ap.email_norm) FILTER (WHERE ap.tem_menos_12)::bigint
                                                                      AS aplicacoes_menos_12_com_agendamento_periodo,
        COUNT(DISTINCT ap.email_norm) FILTER (WHERE ap.tem_nao_atua)::bigint
                                                                      AS aplicacoes_nao_atua_com_agendamento_periodo
    FROM aplicacoes_email_periodo ap
    JOIN leads_email_zoho         lez ON lez.email_norm = ap.email_norm
    JOIN deals_com_agendamento    dca ON dca.deal_id = lez.deal_id
),

-- ---------------------------------------------------------------------------
-- Investimento (fdw_reconecta.anuncios) — exclui campanhas REL_02*.
-- NULL campaign_name é mantido (mídia não atribuída a campanha específica).
-- ---------------------------------------------------------------------------
invest_dia AS (
    SELECT
        date_start         AS data,
        SUM(spend)::numeric AS investimento
    FROM fdw_reconecta.anuncios
    WHERE date_start BETWEEN :data_ini AND :data_fim
      AND (campaign_name IS NULL OR campaign_name NOT LIKE 'REL_02%')
    GROUP BY date_start
),

-- ---------------------------------------------------------------------------
-- Universo de datas — UNION das fontes.
-- ---------------------------------------------------------------------------
keys AS (
    SELECT data FROM leads_dia
    UNION SELECT data FROM aplicacoes_dia
    UNION SELECT data FROM agendamentos_dia
    UNION SELECT data FROM invest_dia
)
SELECT
    k.data                                                            AS data_ref,
    COALESCE(ld.novos_leads, 0)::bigint                               AS novos_leads,
    COALESCE(ad.novas_aplicacoes, 0)::bigint                          AS novas_aplicacoes,
    COALESCE(ad.aplicacoes_mais_12, 0)::bigint                        AS aplicacoes_mais_12,
    COALESCE(ad.aplicacoes_menos_12, 0)::bigint                       AS aplicacoes_menos_12,
    COALESCE(ad.aplicacoes_nao_atua, 0)::bigint                       AS aplicacoes_nao_atua,
    COALESCE(agd.agendamentos, 0)::bigint                             AS agendamentos,
    COALESCE(agd.emails_com_agendamento, 0)::bigint                   AS emails_com_agendamento,
    COALESCE(aca.aplicacoes_com_agendamento, 0)::bigint               AS aplicacoes_com_agendamento,
    COALESCE(aca.aplicacoes_mais_12_com_agendamento, 0)::bigint       AS aplicacoes_mais_12_com_agendamento,
    COALESCE(aca.aplicacoes_menos_12_com_agendamento, 0)::bigint      AS aplicacoes_menos_12_com_agendamento,
    COALESCE(aca.aplicacoes_nao_atua_com_agendamento, 0)::bigint      AS aplicacoes_nao_atua_com_agendamento,
    COALESCE(inv.investimento, 0)::numeric                            AS investimento,
    COALESCE(ap.novas_aplicacoes_periodo, 0)::bigint                  AS novas_aplicacoes_periodo,
    COALESCE(ap.aplicacoes_mais_12_periodo, 0)::bigint                AS aplicacoes_mais_12_periodo,
    COALESCE(ap.aplicacoes_menos_12_periodo, 0)::bigint               AS aplicacoes_menos_12_periodo,
    COALESCE(ap.aplicacoes_nao_atua_periodo, 0)::bigint               AS aplicacoes_nao_atua_periodo,
    COALESCE(acp.aplicacoes_com_agendamento_periodo, 0)::bigint       AS aplicacoes_com_agendamento_periodo,
    COALESCE(acp.aplicacoes_mais_12_com_agendamento_periodo, 0)::bigint
                                                                      AS aplicacoes_mais_12_com_agendamento_periodo,
    COALESCE(acp.aplicacoes_menos_12_com_agendamento_periodo, 0)::bigint
                                                                      AS aplicacoes_menos_12_com_agendamento_periodo,
    COALESCE(acp.aplicacoes_nao_atua_com_agendamento_periodo, 0)::bigint
                                                                      AS aplicacoes_nao_atua_com_agendamento_periodo
FROM keys k
LEFT JOIN leads_dia        ld  USING (data)
LEFT JOIN aplicacoes_dia   ad  USING (data)
LEFT JOIN agendamentos_dia agd USING (data)
LEFT JOIN apl_com_ag       aca USING (data)
LEFT JOIN invest_dia       inv USING (data)
CROSS JOIN aplicacoes_periodo ap
CROSS JOIN apl_com_ag_periodo acp
ORDER BY k.data;
