-- =============================================================================
-- Pré-vendas — agregado por SDR (regra HÍBRIDA).
-- =============================================================================
-- Atribuição de SDR (Opção C — híbrida):
--   1. `zoho_activities.prevendas` (texto, NULL → tenta fallback)
--   2. fallback: `zoho_deals.sdr_ss` resolvido via `zoho_users` (nome)
--   3. ainda NULL → "Sem SDR"
--
-- Em abr/2026 a regra reduz "Sem SDR" de 69 (12% das atividades) para 40
-- (7%) sem distorcer atribuição: o fallback só dispara quando prevendas
-- está vazio. Quando ambos preenchidos (96% dos casos com deal pareado),
-- prevendas vence — operacionalmente correto pra Pré-vendas.
--
-- Coluna `fonte_sdr` carrega a auditoria de qual caminho foi usado
-- (`activity.prevendas` / `deal.sdr_ss` / `Sem SDR`). O grão devolvido é
-- (sdr, fonte_sdr) — quando um SDR teve atividades vindo de ambas as
-- fontes, aparecem 2 linhas. O Python consolida quando precisar exibir
-- 1 linha por SDR.
--
-- Para vendas: usar a MESMA regra do card da Visão Geral:
--   - zoho_deals
--   - data_hora_compra::date
--   - stage = 'Ganho'
--   - tipo_venda = 'Novo cliente'
--   - SDR atribuído por zoho_deals.sdr_ss -> zoho_users
--
-- ⚠ Alinhamento com cards (prevendas_overview_diario.sql):
--   - Todas as contagens de activity usam COUNT(DISTINCT activity_id).
--   - Vendas usa COUNT(DISTINCT deal_id).
--   - +12 / -12 usam regra COMBINADA de 4 fontes (lead_classification,
--     qualificacao, classificado_cal, ext.classificado) — espelha 1:1
--     a regra dos cards (prevendas_overview_diario.sql).
-- Diferenças residuais possíveis entre soma do ranking e o card:
--   - Filtro `prevendas_ranking_sdr_oficiais` (Python) restringe ao
--     cadastro oficial; SDRs como "Letícia Garcia", "Bruna Braga", etc.
--     ficam de fora do ranking, mas suas activities entram no card.
--   - "Sem SDR" também é filtrada antes de gerar o ranking.
--   - Match com zoho_deals: aqui é `d.id = a.what_id` direto; o card
--     usa `regexp_replace(...)` em ambos os lados. Pode divergir
--     quando o `what_id` tem chaves/JSON.
-- =============================================================================
WITH ext_leads_dedup AS (
    -- ext.leads DEDUPLICADO por zoho_id, com filtro de e-mails teste —
    -- 1 row por zoho_id, sempre a mais recente. Espelha as outras SQLs.
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text  AS deal_id,
        l.classificado   AS ext_classif
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY l.zoho_id::text, l."timestamp" DESC NULLS LAST, l.id DESC
),
deal_classif_raw AS (
    -- Classificação por deal — PRIORIDADE EXCLUSIVA (substitui o OR antigo
    -- que duplicava deals em +12 e -12 quando CRM e ext.leads divergiam):
    --   1. zoho_deals.lead_classification  (CRM, principal)
    --   2. zoho_deals.qualificacao         (CRM, manual da gestoria)
    --   3. zoho_deals.classificado_cal     (CRM)
    --   4. ext_reconecta.leads.classificado (ext, dedup)
    -- Primeira fonte com valor IN ('Atua +12','Atua -12','Não atua') decide.
    -- Sem fan-out pois ext.leads vem deduplicado.
    SELECT
        d.id                                              AS deal_id,
        CASE
            WHEN NULLIF(btrim(d.lead_classification), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.lead_classification), '')
            WHEN NULLIF(btrim(d.qualificacao), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.qualificacao), '')
            WHEN NULLIF(btrim(d.classificado_cal), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(d.classificado_cal), '')
            WHEN NULLIF(btrim(eld.ext_classif), '')
                 IN ('Atua +12','Atua -12','Não atua')
                THEN NULLIF(btrim(eld.ext_classif), '')
            ELSE 'Sem classificação'
        END                                               AS classif_final
    FROM zoho_deals d
    LEFT JOIN ext_leads_dedup eld ON eld.deal_id = d.id::text
),
deal_classif AS (
    SELECT
        deal_id,
        classif_final,
        (classif_final = 'Atua +12') AS tem_mais_12,
        (classif_final = 'Atua -12') AS tem_menos_12
    FROM deal_classif_raw
),
acts_agendamento AS (
    SELECT
        a.id                                          AS activity_id,
        a.what_id                                     AS deal_id,
        a.start_datetime::date                        AS data_ref,
        a.status_reuniao,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            TRIM(u.first_name || ' ' || u.last_name),
            'Sem SDR'
        )                                             AS sdr,
        CASE
            WHEN NULLIF(btrim(a.prevendas), '') IS NOT NULL
                THEN 'activity.prevendas'
            WHEN TRIM(u.first_name || ' ' || u.last_name) IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END                                           AS fonte_sdr
    FROM zoho_activities a
    LEFT JOIN zoho_deals d ON d.id        = a.what_id
    LEFT JOIN zoho_users u ON u.id::text  = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta','Indicação')
      AND a.status_reuniao IS NOT NULL
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
acts_criacao AS (
    SELECT
        a.id                                          AS activity_id,
        a.what_id                                     AS deal_id,
        a.created_time::date                          AS data_ref,
        COALESCE(
            NULLIF(btrim(a.prevendas), ''),
            TRIM(u.first_name || ' ' || u.last_name),
            'Sem SDR'
        )                                             AS sdr,
        CASE
            WHEN NULLIF(btrim(a.prevendas), '') IS NOT NULL
                THEN 'activity.prevendas'
            WHEN TRIM(u.first_name || ' ' || u.last_name) IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END                                           AS fonte_sdr
    FROM zoho_activities a
    LEFT JOIN zoho_deals d ON d.id        = a.what_id
    LEFT JOIN zoho_users u ON u.id::text  = d.sdr_ss::text
    WHERE a.activity_type IN ('Consulta','Indicação')
      AND a.status_reuniao IS NOT NULL
      AND a.created_time::date BETWEEN :data_ini AND :data_fim
),
deals_direct AS (
    SELECT
        d.id AS deal_id,
        COALESCE(
            NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''),
            'Sem SDR'
        ) AS sdr,
        CASE
            WHEN NULLIF(TRIM(u.first_name || ' ' || u.last_name), '') IS NOT NULL
                THEN 'deal.sdr_ss'
            ELSE 'Sem SDR'
        END AS fonte_sdr,
        CASE WHEN NULLIF(btrim(d.amount), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                    REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS montante,
        CASE WHEN NULLIF(btrim(d.receita), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                    REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS receita
    FROM zoho_deals d
    LEFT JOIN zoho_users u ON u.id::text = d.sdr_ss::text
    WHERE d.stage = 'Ganho'
      AND d.tipo_venda = 'Novo cliente'
      AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
acts_created_agg AS (
    -- COUNT(DISTINCT activity_id) defensivo: aqui não há fan-out (cada
    -- activity gera 1 row em acts_criacao), mas a regra fica alinhada
    -- com a CTE equivalente da query dos cards e protege futuros
    -- joins que possam introduzir multiplicação.
    SELECT
        sdr, fonte_sdr,
        COUNT(DISTINCT activity_id)::bigint                      AS agendamentos_criados
    FROM acts_criacao
    GROUP BY sdr, fonte_sdr
),
acts_agg AS (
    -- COUNT(DISTINCT activity_id) idem. Regra +12 / -12 = COMBINADA de 4
    -- fontes (lead_classification + qualificacao + classificado_cal +
    -- ext.classificado), agregada por deal via bool_or no deal_classif.
    -- Espelha 1:1 prevendas_overview_diario.sql.
    SELECT
        a.sdr,
        a.fonte_sdr,
        COUNT(DISTINCT a.activity_id)::bigint                    AS agendamentos,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE COALESCE(dc.tem_mais_12, FALSE)
        )::bigint                                                AS agendamentos_mais_12,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE COALESCE(dc.tem_menos_12, FALSE)
        )::bigint                                                AS agendamentos_menos_12,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE a.status_reuniao IN ('Concluída', 'Concluído')
        )::bigint                                                AS comparecimentos,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE a.status_reuniao IN ('Cancelada', 'Cancelado')
        )::bigint                                                AS cancelamentos,
        COUNT(DISTINCT a.activity_id) FILTER (
            WHERE a.status_reuniao = 'Vencida'
        )::bigint                                                AS vencidos
    FROM acts_agendamento a
    LEFT JOIN deal_classif dc ON dc.deal_id = a.deal_id
    GROUP BY a.sdr, a.fonte_sdr
),
deals_agg AS (
    -- COUNT(DISTINCT deal_id) idem ao card de Vendas (regra dedup por
    -- negócio único). Aqui não havia fan-out — cada deal gera 1 row em
    -- deals_direct — mas a troca trava a regra.
    SELECT
        sdr, fonte_sdr,
        COUNT(DISTINCT deal_id)::bigint                          AS vendas,
        COUNT(DISTINCT deal_id)::bigint                          AS vendas_novas,
        SUM(montante)::numeric                                    AS montante,
        SUM(receita)::numeric                                     AS receita
    FROM deals_direct
    GROUP BY sdr, fonte_sdr
),
pares AS (
    SELECT sdr, fonte_sdr FROM acts_created_agg
    UNION
    SELECT sdr, fonte_sdr FROM acts_agg
    UNION SELECT sdr, fonte_sdr FROM deals_agg
)
SELECT
    p.sdr,
    p.fonte_sdr,
    COALESCE(c.agendamentos_criados, 0)::bigint AS agendamentos_criados,
    COALESCE(a.agendamentos, 0)::bigint     AS agendamentos,
    COALESCE(a.agendamentos_mais_12, 0)::bigint AS agendamentos_mais_12,
    COALESCE(a.agendamentos_menos_12, 0)::bigint AS agendamentos_menos_12,
    COALESCE(a.comparecimentos, 0)::bigint  AS comparecimentos,
    COALESCE(a.cancelamentos, 0)::bigint    AS cancelamentos,
    COALESCE(a.cancelamentos, 0)::bigint    AS cancelados,
    COALESCE(a.vencidos, 0)::bigint         AS vencidos,
    COALESCE(d.vendas, 0)::bigint           AS vendas,
    COALESCE(d.vendas_novas, 0)::bigint     AS vendas_novas,
    COALESCE(d.montante, 0)::numeric        AS montante,
    COALESCE(d.receita, 0)::numeric         AS receita
FROM pares p
LEFT JOIN acts_created_agg c USING (sdr, fonte_sdr)
LEFT JOIN acts_agg  a USING (sdr, fonte_sdr)
LEFT JOIN deals_agg d USING (sdr, fonte_sdr)
ORDER BY agendamentos DESC, vendas DESC;
