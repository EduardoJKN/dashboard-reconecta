-- =============================================================================
-- Executivas — Lead In & Agendamentos (1 linha por deal criado no período).
-- =============================================================================
-- Universo: oportunidades/deals com `created_at::date` no período filtrado.
-- Classificação de agendamentos: coluna `stage` (Recepção / Reunião Agendada).
-- Coluna `triagem` traz apenas informação complementar do CRM.
--
-- `triagem_tratada`: COALESCE(NULLIF(TRIM(triagem), ''), 'Sem informação')
-- Closer/time: mesma regra CASE de prevendas_leads_detalhe_diario /
-- bi.vw_dashboard_comercial_executivas_rw (filtro TIMES no dashboard).
-- =============================================================================
WITH deals_periodo AS (
    SELECT
        d.id::text AS deal_id,
        d.created_at::date AS data_criacao,
        d.stage,
        COALESCE(NULLIF(TRIM(d.triagem), ''), 'Sem informação') AS triagem_tratada,
        d.executiva_vendas::text AS closer_id,
        NULLIF(btrim(d.email), '') AS email
    FROM zoho_deals d
    WHERE d.created_at::date BETWEEN :data_ini AND :data_fim
),
closer_resolved AS (
    SELECT
        dp.deal_id,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '') AS executiva,
        CASE
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Andrezza Ayuso Serpa%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Hawinne Cristina%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Nathally Pereira dos Santos%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Thaís Cadó%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Thais Cado%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Stefany Campinas%'
                THEN 'Time da Leidianne'
            WHEN TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leandro Alves%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leonardo Melo Patriota%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Leonardo Patriota%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Nathan Carloto%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Camile Silveira%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Henrique Gonçalves%'
              OR TRIM(uc.first_name || ' ' || uc.last_name) ILIKE 'Henrique Goncalves%'
                THEN 'Time do Marcelo'
            ELSE 'Sem time definido'
        END AS time_vendas
    FROM deals_periodo dp
    LEFT JOIN zoho_users uc ON uc.id::text = dp.closer_id
)
SELECT
    dp.deal_id,
    dp.data_criacao,
    dp.stage,
    dp.triagem_tratada,
    COALESCE(cr.executiva, 'Sem Closer') AS executiva,
    COALESCE(cr.time_vendas, 'Sem time definido') AS time_vendas,
    dp.email
FROM deals_periodo dp
LEFT JOIN closer_resolved cr ON cr.deal_id = dp.deal_id
ORDER BY dp.data_criacao DESC, dp.deal_id;
