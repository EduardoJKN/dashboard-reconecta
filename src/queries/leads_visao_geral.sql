-- =============================================================================
-- Leads Totais — fonte oficial da Visão Geral, com closer/time atribuídos.
-- =============================================================================
-- Substitui `bi.vw_funil_leads_diario` no card "Leads Totais" da página
-- Visão Geral comercial (`views/home.py`). Devolve 1 row por (data_ref,
-- email_norm) — daily-distinct — com `executiva` e `time_vendas` quando
-- conseguirmos atribuir via lead → deal pareado.
--
-- Por que este formato:
--   - Total `Todos` = COUNT(*) = leads únicos/dia (mesma regra que a Visão
--     Geral Marketing já usa em `mkt_visao_geral_diario.sql`). Em abr/2026
--     bate 854. Funis Criativos/Campanhas usam `timestamp::date` em
--     `ext_reconecta.leads` (regra Looker).
--   - Filtros de closer/time da página são aplicados em Python via
--     `ctx.refilter` sobre as colunas `executiva` / `time_vendas`. Leads
--     com deal-sem-closer ou sem deal nenhum aparecem com `NULL` nessas
--     colunas — entram quando filtro = Todos, saem quando filtro é
--     específico (comportamento padrão do `_apply_selections`).
--
-- Cobertura medida abr/2026 (854 leads):
--   - 357 com closer atribuído (lead → deal com executiva_vendas)
--   - 488 com deal pareado MAS sem executiva_vendas
--   -   9 sem nenhum deal pareado
--
-- Match lead → deal: priority `zoho_id > session_id > email`. Mesma regra
-- usada em mkt_visao_geral_kpis_canal / mkt_growth_atividades_canal /
-- compatibilidade_sdr_closer (versão zoho-direta).
--
-- ⚠ Manutenção: o CASE de `time_vendas` espelha o CASE da view
-- `bi.vw_dashboard_comercial_executivas_rw`. Se um closer novo entrar e
-- precisar virar Time da Leidianne / Time do Marcelo, atualizar nos DOIS
-- lugares (ou refatorar pra fonte única de classificação — fora de escopo
-- agora).
-- =============================================================================
WITH leads_clean AS (
    -- 1 row por (data_ref, email_norm) — daily-distinct alinhado com a
    -- regra oficial Visão Geral Marketing.
    SELECT DISTINCT ON (l.timestamp::date, lower(btrim(l.email)))
        l.timestamp::date              AS data_ref,
        lower(btrim(l.email))           AS email_norm,
        NULLIF(btrim(l.zoho_id), '')    AS lead_zoho_id,
        l.session_id                    AS lead_session_id,
        l.timestamp
    FROM ext_reconecta.leads l
    WHERE l.timestamp::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY l.timestamp::date, lower(btrim(l.email)), l.timestamp
),
all_deal_matches AS (
    -- UNION ALL de 3 INNER JOINs index-friendly (em vez de OR-predicate
    -- cartesiano). DISTINCT ON pelo `prio` em lead_with_deal resolve a
    -- prioridade zoho_id > session_id > email.
    SELECT lc.data_ref, lc.email_norm, zd.id AS deal_id,
           zd.executiva_vendas, zd.created_at AS deal_created_at, 1 AS prio
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_zoho_id = zd.id
    WHERE lc.lead_zoho_id IS NOT NULL
    UNION ALL
    SELECT lc.data_ref, lc.email_norm, zd.id, zd.executiva_vendas,
           zd.created_at, 2
    FROM leads_clean lc
    JOIN zoho_deals zd ON lc.lead_session_id::text = zd.session_id
    WHERE lc.lead_session_id IS NOT NULL
    UNION ALL
    SELECT lc.data_ref, lc.email_norm, zd.id, zd.executiva_vendas,
           zd.created_at, 3
    FROM leads_clean lc
    JOIN zoho_deals zd ON lower(btrim(zd.email)) = lc.email_norm
),
lead_with_deal AS (
    -- 1 deal por (data_ref, email_norm). Empate dentro da mesma prioridade
    -- → deal mais recente por created_at (mesma regra das outras páginas).
    SELECT DISTINCT ON (data_ref, email_norm)
        data_ref,
        email_norm,
        deal_id,
        executiva_vendas
    FROM all_deal_matches
    ORDER BY data_ref, email_norm, prio, deal_created_at DESC NULLS LAST
)
SELECT
    lc.data_ref,
    lc.email_norm,
    -- Closer (executiva) — resolve nome via zoho_users. NULL quando o
    -- deal não tem executiva_vendas atribuída ou quando o lead não casou
    -- com nenhum deal.
    NULLIF(TRIM(u.first_name || ' ' || u.last_name), '')      AS executiva,
    -- time_vendas espelha o CASE da view bi.vw_dashboard_comercial_executivas_rw.
    -- NULL quando não há closer (= não há time atribuível).
    CASE
        WHEN u.first_name ILIKE 'Andrezza%'
          OR u.first_name ILIKE 'Hawinne%'
          OR u.first_name ILIKE 'Nathally%'
          OR u.first_name ILIKE 'Thaís%'
          OR u.first_name ILIKE 'Thais%'
          OR u.first_name ILIKE 'Stefany%'
            THEN 'Time da Leidianne'
        WHEN u.first_name ILIKE 'Leandro%'
          OR u.first_name ILIKE 'Leonardo%'
          OR u.first_name ILIKE 'Nathan%'
          OR u.first_name ILIKE 'Camile%'
          OR u.first_name ILIKE 'Henrique%'
            THEN 'Time do Marcelo'
        WHEN u.first_name IS NOT NULL
            THEN 'Sem time definido'
        ELSE NULL
    END                                                       AS time_vendas
FROM leads_clean lc
LEFT JOIN lead_with_deal lwd USING (data_ref, email_norm)
LEFT JOIN zoho_users u ON u.id::text = lwd.executiva_vendas::text
ORDER BY lc.data_ref, lc.email_norm;
