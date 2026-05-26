-- =============================================================================
-- One Page — regra legada do Looker (Aplicações vs Leads vs Agendamentos).
-- =============================================================================
-- Replica a fonte oficial do One Page do Looker antigo, validada com o CEO.
-- A diferença CHAVE em relação a `mkt_visao_geral_*` é que "Aplicações" não
-- vem de `ext_reconecta.leads.classificado` (regra qualifiers do funil de
-- Marketing) — vem da tabela específica `fdw_reconecta.typeform_aplicacoes`.
--
-- Fontes:
--   Leads        → ext_reconecta.leads             (created_at::date, email)
--   Aplicações   → fdw_reconecta.typeform_aplicacoes (created_at::date, email,
--                                                    classificado)
--   Agendamentos → public.zoho_activities          (activity_type IN
--                                                   ('Consulta','Indicação'),
--                                                   created_time::date)
--   E-mail do agendamento → public.zoho_deals via what_id (deal.email)
--   Investimento → fdw_reconecta.anuncios          (date_start, spend),
--                                                  excluindo campanhas REL_02*
--
-- Regras de classificação (literais do typeform · lowercased + btrim):
--   +12  : ('atua +12', 'atua+12', '+12')
--   -12  : ('atua -12', 'atua-12', '-12')
--   Não atua: ('não atua', 'nao atua')
--
-- Cruzamento "Aplicação com Agendamento" (REGRA REVISADA):
--   jornada `aplicação.email → leads.email → leads.zoho_id → deal.id
--   → activity.what_id`. Aplicação no período + esse deal teve algum
--   agendamento em qualquer momento (sem exigir mesmo dia, e sem
--   restringir o agendamento ao período). Substitui a versão antiga
--   que casava `aplicacao.email = deal.email` no MESMO dia — frágil
--   a divergência de e-mail e perdia casos de aplicação→agendamento
--   com defasagem temporal. Ver CTE `apl_com_ag` abaixo.
--
-- Filtro de e-mails internos/testes alinhado com o resto do projeto
-- (`%@teste%`, `teste@%`, `%smarts%`, `%reconecta%`) — aplicado em ambas
-- as bases (leads e typeform).
--
-- Grão: 1 row por `data_ref` (dia).
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
-- Aplicações (fdw_reconecta.typeform_aplicacoes) — daily-distinct por e-mail,
-- com flags +12/-12/não atua agregadas via BOOL_OR (mesmo email no mesmo dia
-- pode ter múltiplas submissões; uma com '+12' já marca o bucket).
-- ---------------------------------------------------------------------------
aplicacoes_clean AS (
    SELECT
        ta.created_at::date                            AS data,
        lower(btrim(ta.email))                         AS email_norm,
        lower(btrim(coalesce(ta.classificado, '')))    AS classif_norm
    FROM fdw_reconecta.typeform_aplicacoes ta
    WHERE ta.created_at::date BETWEEN :data_ini AND :data_fim
      AND ta.email IS NOT NULL
      AND btrim(ta.email) <> ''
      AND lower(ta.email) NOT LIKE '%@teste%'
      AND lower(ta.email) NOT LIKE 'teste@%'
      AND lower(ta.email) NOT LIKE '%smarts%'
      AND lower(ta.email) NOT LIKE '%reconecta%'
),
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
        COUNT(*)::bigint                                        AS novas_aplicacoes,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint             AS aplicacoes_mais_12,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint            AS aplicacoes_menos_12,
        COUNT(*) FILTER (WHERE tem_nao_atua)::bigint            AS aplicacoes_nao_atua
    FROM aplicacoes_dia_email
    GROUP BY data
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

-- Ponte e-mail → zoho_id via `ext_reconecta.leads`, dedup pela versão
-- mais recente. Filtros de e-mail de teste idênticos ao resto da SQL.
leads_email_zoho AS (
    SELECT DISTINCT ON (lower(btrim(l.email)))
        lower(btrim(l.email))   AS email_norm,
        l.zoho_id::text         AS deal_id
    FROM ext_reconecta.leads l
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
-- Deals que tiveram pelo menos 1 activity de Consulta/Indicação em
-- qualquer momento. SEM filtro de data (Opção A) — captura jornada
-- completa mesmo que o agendamento tenha sido marcado depois do
-- fim do período. Mesmo critério de `activity_type` usado em
-- `one_page_prevendas_por_fonte.sql` e `prevendas_overview_diario.sql`.
deals_com_agendamento AS (
    SELECT DISTINCT zd.id::text AS deal_id
    FROM zoho_activities a
    JOIN zoho_deals zd ON zd.id = a.what_id
    WHERE a.activity_type IN ('Consulta', 'Indicação')
),
-- Match final aplicação → lead → deal → agendamento.
apl_com_ag AS (
    SELECT
        ad.data,
        COUNT(DISTINCT ad.email_norm)::bigint                           AS aplicacoes_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_mais_12)::bigint
                                                                         AS aplicacoes_mais_12_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_menos_12)::bigint
                                                                         AS aplicacoes_menos_12_com_agendamento,
        COUNT(DISTINCT ad.email_norm) FILTER (WHERE ad.tem_nao_atua)::bigint
                                                                         AS aplicacoes_nao_atua_com_agendamento
    FROM aplicacoes_dia_email ad
    JOIN leads_email_zoho      lez USING (email_norm)
    JOIN deals_com_agendamento dca USING (deal_id)
    GROUP BY ad.data
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
    COALESCE(inv.investimento, 0)::numeric                            AS investimento
FROM keys k
LEFT JOIN leads_dia        ld  USING (data)
LEFT JOIN aplicacoes_dia   ad  USING (data)
LEFT JOIN agendamentos_dia agd USING (data)
LEFT JOIN apl_com_ag       aca USING (data)
LEFT JOIN invest_dia       inv USING (data)
ORDER BY k.data;
