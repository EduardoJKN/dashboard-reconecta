-- =============================================================================
-- SDR × Closer — fonte direta zoho_deals + zoho_users (sem view bi.vw_*).
-- =============================================================================
-- Histórico:
-- Substitui a leitura de `bi.vw_compatibilidade_sdr_closer`, que tinha 5
-- desvios em relação à regra oficial validada para Vendas novas:
--   1. Filtrava `executiva_vendas IS NOT NULL AND (sdr_ss OR prevendas) IS NOT
--      NULL` no banco — excluía deals que deveriam aparecer como "Sem SDR" /
--      "Sem Closer".
--   2. Considerava apenas `stage = 'Ganho'` — fora `'Fechado Ganho'`.
--   3. Agrupava por `mes_ref = date_trunc('month', d.created_at)` (data do
--      lead) e a página filtrava por esse mes_ref → não pegava ganhos cuja
--      venda fechou no mês mas o lead veio antes.
--   4. Não filtrava `tipo_venda = 'Novo cliente'`.
--   5. Rotulava nulos como `SEM_SDR` / `SEM_CLOSER` em vez de `Sem SDR` /
--      `Sem Closer`.
--
-- Universo DUAL (mai/2026):
--   - GANHOS: `data_hora_compra::date BETWEEN :mes_ini AND :mes_fim`
--             AND `stage IN ('Ganho','Fechado Ganho')`
--             AND `tipo_venda = 'Novo cliente'`
--   - REPASSES: `created_at::date BETWEEN :mes_ini AND :mes_fim`
--               AND `sdr_ss IS NOT NULL`
--               AND `executiva_vendas IS NOT NULL`
--   Universos independentes — deal pode ser repassado num mês e ganho em
--   outro (padrão Looker, consistente com "Indicadores por Pré-vendas").
--   Métricas por categoria filtradas via FILTER (WHERE is_ganho / is_repasse).
--
-- Por que `created_at` e não `hora_saida_prevendas`/`data_cadastro`:
--   - `hora_saida_prevendas`: 0/1002 deals preenchidos (jun/2025+) → inútil.
--   - `data_cadastro`: ~85% preenchido (jul/2025) — parcial.
--   - `created_at`: 100% preenchido → autoritativo.
-- Vínculo SDR-Closer: ~99,4% dos deals criados desde jun/2025 têm AMBOS
-- `sdr_ss` e `executiva_vendas` preenchidos.
--
-- Classificação +12 / -12 / Não atua — PRIORIDADE EXCLUSIVA (substitui o
-- OR combinado que ainda podia classificar duplamente a fonte ext.leads
-- vs CRM). Ordem das fontes:
--   1. zoho_deals.lead_classification
--   2. zoho_deals.qualificacao
--   3. zoho_deals.classificado_cal
--   4. ext_reconecta.leads.classificado (dedup por zoho_id)
-- Primeira fonte com valor IN ('Atua +12','Atua -12','Não atua') decide.
-- Buckets mutuamente exclusivos pela classif_final.
--
-- Shape preservado para os transforms (annotate_and_clean_sdr_closer,
-- sdr_closer_totais, sdr_closer_matriz, sdr_ranking, closer_ranking).
-- 12 colunas antigas mantidas (ganhos, montante_total, receita_total,
-- ticket_medio, dias_ate_fechamento, leads_recebidos, taxa_conversao,
-- tipo_sdr, time_closer, sdr, closer, mes_ref) + 7 novas
-- (repasses, repasses_mais_12, repasses_menos_12, repasses_nao_atua,
-- ganhos_mais_12, ganhos_menos_12, ganhos_nao_atua).
-- =============================================================================
WITH ganhos_periodo AS (
    SELECT d.id::text AS deal_id
    FROM zoho_deals d
    WHERE d.data_hora_compra::date BETWEEN :mes_ini AND :mes_fim
      AND d.stage IN ('Ganho', 'Fechado Ganho')
      AND d.tipo_venda = 'Novo cliente'
),
repasses_periodo AS (
    SELECT d.id::text AS deal_id
    FROM zoho_deals d
    WHERE d.created_at::date BETWEEN :mes_ini AND :mes_fim
      AND d.sdr_ss IS NOT NULL
      AND d.executiva_vendas IS NOT NULL
),
deals_relevantes AS (
    SELECT deal_id FROM ganhos_periodo
    UNION
    SELECT deal_id FROM repasses_periodo
),
ext_leads_dedup AS (
    -- ext.leads DEDUPLICADO por zoho_id, com filtro de e-mails teste —
    -- 1 row por zoho_id, sempre a versão MAIS RECENTE.
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
deal_classif AS (
    -- 1 row por deal relevante. classif_final EXCLUSIVA via CASE
    -- prioridade lead_classification > qualificacao > classificado_cal
    -- > ext.classificado. Sem fan-out pois ext.leads vem deduplicado.
    SELECT
        dr.deal_id,
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
        END                                     AS classif_final
    FROM deals_relevantes dr
    JOIN zoho_deals d           ON d.id::text = dr.deal_id
    LEFT JOIN ext_leads_dedup eld ON eld.deal_id = dr.deal_id
),
base AS (
    -- 1 row por deal relevante, com SDR/closer resolvidos + flags de
    -- pertença aos universos + classificação.
    SELECT
        dr.deal_id,
        d.data_hora_compra::date                              AS data_ganho,
        d.created_at::date                                    AS data_lead,
        COALESCE(
            NULLIF(TRIM(sdr.first_name || ' ' || sdr.last_name), ''),
            'Sem SDR'
        )                                                     AS sdr,
        COALESCE(
            NULLIF(TRIM(closer.first_name || ' ' || closer.last_name), ''),
            'Sem Closer'
        )                                                     AS closer,
        CASE
            WHEN NULLIF(TRIM(d.amount), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.amount), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END                                                   AS montante,
        CASE
            WHEN NULLIF(TRIM(d.receita), '') IS NULL THEN 0::numeric
            ELSE REPLACE(
                     REPLACE(
                         REGEXP_REPLACE(TRIM(d.receita), '[^0-9,.-]', '', 'g'),
                         '.', ''),
                     ',', '.'
                 )::numeric
        END                                                   AS receita,
        (dr.deal_id IN (SELECT deal_id FROM ganhos_periodo))   AS is_ganho,
        (dr.deal_id IN (SELECT deal_id FROM repasses_periodo)) AS is_repasse,
        COALESCE(dc.classif_final, 'Sem classificação')        AS classif_final
    FROM deals_relevantes dr
    JOIN zoho_deals d           ON d.id::text = dr.deal_id
    LEFT JOIN zoho_users closer ON closer.id::text = d.executiva_vendas::text
    LEFT JOIN zoho_users sdr    ON sdr.id::text    = d.sdr_ss::text
    LEFT JOIN deal_classif dc   ON dc.deal_id      = dr.deal_id
)
SELECT
    sdr,
    closer,
    -- mes_ref usa data_ganho quando disponível, senão data_lead. Para
    -- deals só repassados (sem ganho), aparece o mês de criação. Em pares
    -- (sdr, closer) com deals de mes_ref diferentes, o pivot_table do
    -- Python soma — não há split visual indevido.
    DATE_TRUNC('month',
        COALESCE(
            MAX(data_ganho) FILTER (WHERE is_ganho),
            MAX(data_lead)
        )
    )::date                                                   AS mes_ref,

    -- ===== Métricas existentes (shape preservado) =====
    COUNT(DISTINCT deal_id) FILTER (WHERE is_ganho)            AS leads_recebidos,
    COUNT(DISTINCT deal_id) FILTER (WHERE is_ganho)            AS ganhos,
    100.00::numeric                                            AS taxa_conversao,
    SUM(receita)  FILTER (WHERE is_ganho)                      AS receita_total,
    SUM(montante) FILTER (WHERE is_ganho)                      AS montante_total,
    ROUND(
        SUM(montante) FILTER (WHERE is_ganho)
        / NULLIF(COUNT(DISTINCT deal_id) FILTER (WHERE is_ganho), 0)::numeric,
        2
    )                                                          AS ticket_medio,
    ROUND(
        AVG(GREATEST(data_ganho - data_lead, 0))
            FILTER (WHERE is_ganho)::numeric,
        2
    )                                                          AS dias_ate_fechamento,
    'Não classificado'::text                                   AS tipo_sdr,
    'Não classificado'::text                                   AS time_closer,

    -- ===== Novas métricas: REPASSES =====
    COUNT(DISTINCT deal_id) FILTER (WHERE is_repasse)
                                                               AS repasses,
    COUNT(DISTINCT deal_id) FILTER (
        WHERE is_repasse AND classif_final = 'Atua +12'
    )                                                          AS repasses_mais_12,
    COUNT(DISTINCT deal_id) FILTER (
        WHERE is_repasse AND classif_final = 'Atua -12'
    )                                                          AS repasses_menos_12,
    COUNT(DISTINCT deal_id) FILTER (
        WHERE is_repasse AND classif_final = 'Não atua'
    )                                                          AS repasses_nao_atua,

    -- ===== Novas métricas: GANHOS por classificação =====
    COUNT(DISTINCT deal_id) FILTER (
        WHERE is_ganho AND classif_final = 'Atua +12'
    )                                                          AS ganhos_mais_12,
    COUNT(DISTINCT deal_id) FILTER (
        WHERE is_ganho AND classif_final = 'Atua -12'
    )                                                          AS ganhos_menos_12,
    COUNT(DISTINCT deal_id) FILTER (
        WHERE is_ganho AND classif_final = 'Não atua'
    )                                                          AS ganhos_nao_atua
FROM base
GROUP BY sdr, closer
ORDER BY ganhos DESC, repasses DESC, sdr, closer;
