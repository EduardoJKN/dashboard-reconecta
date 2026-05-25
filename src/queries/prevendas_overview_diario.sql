-- =============================================================================
-- Pré-vendas — série diária consolidada (Visão Geral Pré-vendas).
-- =============================================================================
-- Regra fiel do dashboard legado validada manualmente no pgAdmin:
--   - base principal em `zoho_deals`
--   - LEFT JOIN `ext_reconecta.leads` ON d.id::text = l.zoho_id::text
--   - activities ligadas ao deal via `what_id` normalizado
--   - considerar apenas activities com `status_reuniao IS NOT NULL`
--
-- Métricas diárias (todas dedup por activity_id ou deal_id pra neutralizar
-- fan-out do LEFT JOIN com ext_reconecta.leads):
--   - leads / leads_mais_12 / leads_menos_12 → daily-distinct sobre
--                            ext_reconecta.leads (BOOL_OR por (dia, email)).
--   - agendamentos_criados = COUNT(DISTINCT activity_id) por created_time::date
--   - agendamentos         = COUNT(DISTINCT activity_id) por start_datetime::date
--   - comparecimentos      = COUNT(DISTINCT activity_id) FILTER status concluído
--   - vencidas             = COUNT(DISTINCT activity_id) FILTER status vencida
--   - vendas               = COUNT(DISTINCT deal_id) FILTER stage='Ganho'
--                            AND tipo_venda='Novo cliente' por data_hora_compra
--   - montante / receita   = soma após DEDUP por deal_id (corrige fan-out
--                            antigo que somava o montante várias vezes quando
--                            o mesmo deal tinha N leads pareados)
--
-- Regra +12 COMBINADA (4 fontes em OR):
--   1. zoho_deals.lead_classification = 'Atua +12'
--   2. zoho_deals.qualificacao        = 'Atua +12'  (fonte manual da gestoria)
--   3. zoho_deals.classificado_cal    = 'Atua +12'
--   4. ext_reconecta.leads.classificado = 'Atua +12'
-- Aplicada em: agendamentos_mais_12, comparecimentos_mais_12, vendas_mais_12.
-- Regra -12 idem trocando '+12' por '-12' (usada só em leads_menos_12).
--
-- Compatibilidade com páginas ainda não migradas:
--   - `novos_agendamentos` = alias de `agendamentos_criados`
--   - `vendas_novas`       = alias de `vendas`
-- =============================================================================
WITH leads_clean AS (
    -- Filtros canônicos (mesma regra do leads_diario antigo + mkt).
    SELECT
        l.created_at::date                          AS data_ref,
        lower(btrim(l.email))                       AS email_norm,
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
leads_dia_email AS (
    -- Daily-distinct por (dia, email) com flags de classificação. BOOL_OR
    -- garante que +12 e -12 sejam contados sem dupla contagem do mesmo
    -- email no mesmo dia.
    SELECT
        data_ref,
        email_norm,
        BOOL_OR(classif_norm = 'atua +12') AS tem_mais_12,
        BOOL_OR(classif_norm = 'atua -12') AS tem_menos_12
    FROM leads_clean
    GROUP BY data_ref, email_norm
),
leads_diario AS (
    SELECT
        data_ref,
        COUNT(*)::bigint                                          AS leads,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint               AS leads_mais_12,
        COUNT(*) FILTER (WHERE tem_menos_12)::bigint              AS leads_menos_12
    FROM leads_dia_email
    GROUP BY data_ref
),
-- ext.leads DEDUPLICADO por zoho_id — mesma técnica das demais SQLs
-- (prevendas_leads_detalhe_diario.sql, prevendas_leads_por_origem.sql,
-- one_page_prevendas_por_fonte.sql). Antes o LEFT JOIN sem dedup criava
-- fan-out (mesmo deal × N rows ext.leads) e o `classificado` antigo
-- bastava pra inflar +12/-12 via COUNT(DISTINCT) FILTER. Hoje pega só
-- a linha MAIS RECENTE — saneamento de 1-5 unidades em mai/2026 sem
-- alterar a regra das 3 colunas CRM.
ext_leads_dedup AS (
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text  AS deal_id,
        l.classificado   AS classificado
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
    ORDER BY l.zoho_id::text, l."timestamp" DESC NULLS LAST, l.id DESC
),
base_dados AS (
    SELECT
        d.id AS deal_id,
        d.data_hora_compra::date AS data_venda_ref,
        d.stage,
        d.tipo_venda,
        CASE
            WHEN NULLIF(btrim(d.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END AS montante,
        CASE
            WHEN NULLIF(btrim(d.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END AS receita,
        eld.classificado,
        -- 3 fontes de classificação direto do deal. Todas no Zoho (CRM),
        -- editáveis pela gestoria depois que o lead entra. Sem fan-out
        -- agora que ext.leads vem deduplicado via ext_leads_dedup.
        d.lead_classification,
        d.qualificacao,
        d.classificado_cal
    FROM zoho_deals d
    LEFT JOIN ext_leads_dedup eld ON d.id::text = eld.deal_id
),
acts AS (
    SELECT
        bd.deal_id,
        bd.classificado,
        bd.lead_classification,
        bd.qualificacao,
        bd.classificado_cal,
        a.created_time::date AS data_criacao_ref,
        a.start_datetime::date AS data_reuniao_ref,
        a.status_reuniao,
        a.id AS activity_id
    FROM base_dados bd
    JOIN zoho_activities a
      ON regexp_replace(COALESCE(a.what_id::text, ''), '[^0-9A-Za-z]', '', 'g')
       = regexp_replace(bd.deal_id::text, '[^0-9A-Za-z]', '', 'g')
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
      AND (
          a.created_time::date BETWEEN :data_ini AND :data_fim
          OR a.start_datetime::date BETWEEN :data_ini AND :data_fim
      )
),
-- O fan-out histórico (mesma activity replicada em N linhas pelo LEFT
-- JOIN com ext_reconecta.leads) foi eliminado na origem ao trocar o
-- JOIN por `ext_leads_dedup` — 1 row por zoho_id, sempre a mais recente.
-- COUNT(DISTINCT activity_id) segue sendo a regra correta (idempotente
-- aqui, mantida por hábito e por defesa contra eventuais fontes futuras).
-- A `classificado` ext.leads usada nos FILTER de +12 abaixo é a versão
-- atual do lead, não mais "qualquer versão histórica".
agendamentos_criados_diario AS (
    SELECT
        data_criacao_ref AS data_ref,
        COUNT(DISTINCT activity_id)::bigint AS agendamentos_criados
    FROM acts
    WHERE data_criacao_ref BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),
agendamentos_diario AS (
    -- Regra +12 COMBINADA (4 fontes em OR): lead_classification (CRM) OR
    -- qualificacao (CRM, manual da gestoria) OR classificado_cal (CRM) OR
    -- classificado (ext_reconecta.leads). Aplicada também em
    -- comparecimentos_mais_12.
    SELECT
        data_reuniao_ref AS data_ref,
        COUNT(DISTINCT activity_id)::bigint AS agendamentos,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE lead_classification = 'Atua +12'
               OR qualificacao        = 'Atua +12'
               OR classificado_cal    = 'Atua +12'
               OR classificado        = 'Atua +12'
        )::bigint AS agendamentos_mais_12,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao IN ('Concluída', 'Concluído')
        )::bigint AS comparecimentos,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao IN ('Concluída', 'Concluído')
              AND (
                  lead_classification = 'Atua +12'
                  OR qualificacao    = 'Atua +12'
                  OR classificado_cal = 'Atua +12'
                  OR classificado    = 'Atua +12'
              )
        )::bigint AS comparecimentos_mais_12,
        COUNT(DISTINCT activity_id) FILTER (
            WHERE status_reuniao = 'Vencida'
        )::bigint AS vencidas
    FROM acts
    WHERE data_reuniao_ref BETWEEN :data_ini AND :data_fim
    GROUP BY 1
),
deals_ganhos_dedup AS (
    -- Dedup explícito por deal_id ANTES de somar montante/receita.
    -- Antes essa CTE era `vendas_diario` somando direto de base_dados,
    -- o que inflava montante/receita pelo fan-out do LEFT JOIN com leads.
    -- bool_or da regra +12 combinada agrega TODAS as linhas-lead pareadas:
    -- basta uma delas ter +12 (em qualquer das 4 fontes) pra o deal contar.
    SELECT
        bd.deal_id,
        MAX(bd.data_venda_ref)             AS data_venda_ref,
        MAX(bd.montante)                    AS montante,
        MAX(bd.receita)                     AS receita,
        bool_or(
            bd.lead_classification = 'Atua +12'
            OR bd.qualificacao    = 'Atua +12'
            OR bd.classificado_cal = 'Atua +12'
            OR bd.classificado    = 'Atua +12'
        )                                   AS tem_mais_12
    FROM base_dados bd
    WHERE bd.stage = 'Ganho'
      AND bd.tipo_venda = 'Novo cliente'
      AND bd.data_venda_ref BETWEEN :data_ini AND :data_fim
    GROUP BY bd.deal_id
),
vendas_diario AS (
    SELECT
        data_venda_ref                          AS data_ref,
        COUNT(*)::bigint                        AS vendas,
        COUNT(*) FILTER (WHERE tem_mais_12)::bigint AS vendas_mais_12,
        SUM(montante)::numeric                  AS montante,
        SUM(receita)::numeric                   AS receita
    FROM deals_ganhos_dedup
    GROUP BY 1
),
keys AS (
    SELECT data_ref FROM leads_diario
    UNION
    SELECT data_ref FROM agendamentos_criados_diario
    UNION
    SELECT data_ref FROM agendamentos_diario
    UNION
    SELECT data_ref FROM vendas_diario
)
SELECT
    k.data_ref,
    COALESCE(l.leads, 0)::bigint AS leads,
    COALESCE(l.leads_mais_12, 0)::bigint AS leads_mais_12,
    COALESCE(l.leads_menos_12, 0)::bigint AS leads_menos_12,
    COALESCE(c.agendamentos_criados, 0)::bigint AS agendamentos_criados,
    COALESCE(c.agendamentos_criados, 0)::bigint AS novos_agendamentos,
    COALESCE(a.agendamentos, 0)::bigint AS agendamentos,
    COALESCE(a.agendamentos, 0)::bigint AS reunioes_marcadas,
    COALESCE(a.agendamentos_mais_12, 0)::bigint AS agendamentos_mais_12,
    COALESCE(a.comparecimentos, 0)::bigint AS comparecimentos,
    COALESCE(a.comparecimentos_mais_12, 0)::bigint AS comparecimentos_mais_12,
    COALESCE(a.comparecimentos, 0)::bigint AS concluidas,
    0::bigint AS canceladas,
    COALESCE(a.vencidas, 0)::bigint AS vencidas,
    0::bigint AS agendadas_pendentes,
    COALESCE(v.vendas, 0)::bigint AS vendas,
    COALESCE(v.vendas, 0)::bigint AS vendas_novas,
    COALESCE(v.vendas_mais_12, 0)::bigint AS vendas_mais_12,
    COALESCE(v.montante, 0)::numeric AS montante,
    COALESCE(v.receita, 0)::numeric AS receita
FROM keys k
LEFT JOIN leads_diario l USING (data_ref)
LEFT JOIN agendamentos_criados_diario c USING (data_ref)
LEFT JOIN agendamentos_diario a USING (data_ref)
LEFT JOIN vendas_diario v USING (data_ref)
ORDER BY k.data_ref;
