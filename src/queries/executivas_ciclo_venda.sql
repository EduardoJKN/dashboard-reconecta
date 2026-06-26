-- =============================================================================
-- Tempo de ciclo de venda — 1 row por deal ganho no período (Executivas/Vendas).
-- =============================================================================
-- Reutiliza a mesma base de `jornada_lead_venda.sql` (timestamps por deal) e
-- enriquece com closer, time, classificação e funil para agregações no Python.
--
-- Universo: stage = 'Ganho', tipo_venda = 'Novo cliente', data_hora_compra
-- no período — mesma regra de vendas ganhas em prevendas_leads_detalhe_diario.
--
-- Timestamps:
--   ts_venda          = data_hora_compra (data oficial de ganho)
--   ts_lead           = lead mais antigo casado (zoho_id > session_id > email)
--   ts_deal           = zoho_deals.created_at
--   ts_comparecimento = primeira reunião Concluída/Concluído ANTES do ganho
--                       (start_datetime da activity Consulta/Indicação)
--
-- O Python calcula:
--   ciclo_entrada = ts_venda - COALESCE(ts_lead, ts_deal)
--   ciclo_call    = ts_venda - ts_comparecimento  (só quando ts_comparecimento
--                   preenchido e <= ts_venda)
-- =============================================================================
WITH deals_ganhos AS (
    SELECT
        zd.id::text                  AS deal_id,
        zd.email                     AS deal_email,
        zd.session_id                AS deal_session_id,
        zd.created_at                AS ts_deal,
        zd.data_hora_compra          AS ts_venda,
        zd.executiva_vendas::text    AS closer_id,
        NULLIF(btrim(zd.lead_classification), '') AS classificacao_crm,
        NULLIF(btrim(zd.fonte_de_lead), '')      AS fonte_de_lead
    FROM zoho_deals zd
    WHERE zd.stage = 'Ganho'
      AND zd.tipo_venda = 'Novo cliente'
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
all_lead_matches AS (
    SELECT dg.deal_id,
           l.created_at AS ts_lead,
           l.classificado,
           1 AS prio
    FROM deals_ganhos dg
    JOIN ext_reconecta.leads l
      ON NULLIF(btrim(l.zoho_id), '') = dg.deal_id
    WHERE l.email IS NOT NULL AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    UNION ALL
    SELECT dg.deal_id, l.created_at, l.classificado, 2
    FROM deals_ganhos dg
    JOIN ext_reconecta.leads l
      ON l.session_id = dg.deal_session_id::text
    WHERE l.email IS NOT NULL AND btrim(l.email) <> ''
      AND dg.deal_session_id IS NOT NULL
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    UNION ALL
    SELECT dg.deal_id, l.created_at, l.classificado, 3
    FROM deals_ganhos dg
    JOIN ext_reconecta.leads l
      ON lower(btrim(l.email)) = lower(btrim(dg.deal_email))
    WHERE l.email IS NOT NULL AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
lead_pick AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        ts_lead,
        classificado
    FROM all_lead_matches
    ORDER BY deal_id, prio, ts_lead ASC
),
leads_funil AS (
    SELECT DISTINCT ON (l.zoho_id::text)
        l.zoho_id::text                                              AS lead_zoho_id,
        COALESCE(NULLIF(btrim(l.funil_origem), ''), 'Sem origem')    AS funil_origem
    FROM ext_reconecta.leads l
    WHERE l.zoho_id IS NOT NULL
      AND btrim(l.zoho_id::text) <> ''
    ORDER BY l.zoho_id::text, l.timestamp DESC NULLS LAST, l.id DESC
),
acts_consulta AS (
    SELECT
        a.id                           AS activity_id,
        a.what_id                      AS what_id_raw,
        CASE
            WHEN a.what_id ~ '^\{.*\}$'
                THEN (a.what_id::json ->> 'id')::text
            ELSE regexp_replace(COALESCE(a.what_id, ''), '\D', '', 'g')
        END                            AS deal_id,
        a.start_datetime               AS ts_reuniao_agendada,
        a.status_reuniao               AS status_reuniao
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
      AND a.status_reuniao IS NOT NULL
),
-- Primeira reunião concluída ANTES do ganho (regra de comparecimento).
act_compareceu AS (
    SELECT DISTINCT ON (ac.deal_id)
        ac.deal_id,
        ac.ts_reuniao_agendada         AS ts_comparecimento
    FROM acts_consulta ac
    INNER JOIN deals_ganhos dg ON dg.deal_id = ac.deal_id
    WHERE ac.deal_id IS NOT NULL
      AND ac.status_reuniao IN ('Concluída', 'Concluído')
      AND ac.ts_reuniao_agendada IS NOT NULL
      AND ac.ts_reuniao_agendada <= dg.ts_venda
    ORDER BY ac.deal_id, ac.ts_reuniao_agendada ASC, ac.activity_id ASC
),
closer_resolved AS (
    SELECT
        uc.id::text                                                 AS closer_id,
        NULLIF(TRIM(uc.first_name || ' ' || uc.last_name), '')      AS closer_name,
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
        END                                                         AS time_vendas
    FROM zoho_users uc
)
SELECT
    dg.deal_id,
    lp.ts_lead,
    dg.ts_deal,
    acomp.ts_comparecimento,
    dg.ts_venda,
    COALESCE(cr.closer_name, 'Sem Closer')                          AS closer,
    COALESCE(cr.time_vendas, 'Sem time definido')                   AS time_vendas,
    dg.classificacao_crm,
    lp.classificado,
    COALESCE(lf.funil_origem, 'Sem origem')                           AS funil_origem,
    CASE
        WHEN dg.fonte_de_lead = 'Fábrica de Contatos' THEN 'SS/Fábrica'
        ELSE 'Inbound'
    END                                                             AS canal_origem
FROM deals_ganhos dg
LEFT JOIN lead_pick      lp    ON lp.deal_id    = dg.deal_id
LEFT JOIN act_compareceu acomp ON acomp.deal_id = dg.deal_id
LEFT JOIN closer_resolved cr   ON cr.closer_id  = dg.closer_id
LEFT JOIN leads_funil    lf    ON lf.lead_zoho_id = dg.deal_id
ORDER BY dg.ts_venda DESC NULLS LAST;
