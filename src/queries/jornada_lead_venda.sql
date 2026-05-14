-- =============================================================================
-- Jornada do lead até a venda — 1 row por deal ganho no período.
-- =============================================================================
-- Devolve cinco timestamps por deal para que o Python calcule as
-- diferenças (Lead→Deal, Deal→Agendamento, Agendamento→Reunião,
-- Reunião→Venda, Lead→Venda) com média/mediana e contagem válida por
-- etapa. Não calculamos os Δt no SQL — preferimos manter as datas para
-- que a UI possa alternar entre média e mediana e filtrar por SDR sem
-- recomputar.
--
-- Universo: deals ganhos NO PERÍODO (data_hora_compra entre :data_ini e
-- :data_fim, stage IN ('Ganho','Fechado Ganho'), tipo_venda = 'Novo
-- cliente'). Mesma regra de `prevendas_overview_diario_por_sdr.sql`.
-- Cada Δt é avaliado independentemente — um deal sem comparecimento
-- aparece com `ts_comparecimento = NULL` mas contribui para Lead→Deal
-- e Lead→Venda. Isso evita misturar populações.
--
-- Match lead → deal: cascata `zoho_id > session_id > email` (mesma de
-- leads_visao_geral.sql). Aceita lead criado em QUALQUER data — só o
-- deal precisa estar dentro do período. Sem isso, deals com ciclo
-- longo cairiam fora.
--
-- SDR resolvido com a cascata canônica de prevendas:
--   1) activity.prevendas (texto livre) da activity mais antiga do
--      deal (Consulta/Indicação)
--   2) deal.sdr_ss → zoho_users
--   3) NULL (apresentado como "Sem SDR identificado" no Python).
-- =============================================================================
WITH deals_ganhos AS (
    SELECT
        zd.id                     AS deal_id,
        zd.email                  AS deal_email,
        zd.session_id             AS deal_session_id,
        zd.created_at             AS ts_deal,
        zd.data_hora_compra       AS ts_venda,
        zd.stage                  AS stage,
        zd.tipo_venda             AS tipo_venda,
        zd.sdr_ss                 AS sdr_ss
    FROM zoho_deals zd
    WHERE zd.stage IN ('Ganho', 'Fechado Ganho')
      AND zd.tipo_venda = 'Novo cliente'
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
),
-- Para cada deal ganho, captura o lead mais cedo que casa pela cascata
-- zoho_id > session_id > email. Aceita leads de qualquer data.
all_lead_matches AS (
    -- Filtro canônico de e-mails internos/testes replicado nos 3 UNION ALL
    -- pra alinhar com leads_visao_geral / prevendas_overview_diario.
    SELECT dg.deal_id,
           l.created_at AS ts_lead,
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
    SELECT dg.deal_id, l.created_at, 2
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
    SELECT dg.deal_id, l.created_at, 3
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
    -- Para cada deal: melhor lead pela prioridade; em empate, o mais
    -- antigo (que é o "primeiro contato").
    SELECT DISTINCT ON (deal_id)
        deal_id,
        ts_lead
    FROM all_lead_matches
    ORDER BY deal_id, prio, ts_lead ASC
),
-- Activities da deal: pega a primeira criada (agendamento criado) e a
-- primeira concluída (comparecimento) — independentes pra não exigir
-- que sejam a MESMA activity.
acts_consulta AS (
    SELECT
        a.id                                  AS activity_id,
        a.what_id                             AS deal_id,
        a.created_time                        AS ts_agendamento_criado,
        a.start_datetime                      AS ts_reuniao_agendada,
        a.status_reuniao                      AS status_reuniao,
        NULLIF(btrim(a.prevendas), '')        AS prevendas
    FROM zoho_activities a
    WHERE a.activity_type IN ('Consulta', 'Indicação')
),
act_criada AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        ts_agendamento_criado,
        ts_reuniao_agendada,
        activity_id
    FROM acts_consulta
    WHERE deal_id IS NOT NULL
    ORDER BY deal_id, ts_agendamento_criado ASC, activity_id ASC
),
act_compareceu AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        ts_reuniao_agendada AS ts_comparecimento
    FROM acts_consulta
    WHERE deal_id IS NOT NULL
      AND status_reuniao = 'Concluída'
    ORDER BY deal_id, ts_reuniao_agendada ASC, activity_id ASC
),
sdr_via_activity AS (
    SELECT DISTINCT ON (deal_id)
        deal_id,
        prevendas
    FROM acts_consulta
    WHERE deal_id IS NOT NULL
      AND prevendas IS NOT NULL
    ORDER BY deal_id, ts_agendamento_criado ASC, activity_id ASC
)
SELECT
    dg.deal_id                                                       AS deal_id,
    lp.ts_lead                                                       AS ts_lead,
    dg.ts_deal                                                       AS ts_deal,
    ac.ts_agendamento_criado                                         AS ts_agendamento_criado,
    ac.ts_reuniao_agendada                                           AS ts_reuniao_agendada,
    acomp.ts_comparecimento                                          AS ts_comparecimento,
    dg.ts_venda                                                      AS ts_venda,

    -- SDR canônico (mesma cascata das demais páginas)
    COALESCE(
        sva.prevendas,
        NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
    )                                                                AS sdr,

    -- Procedência da associação (debug / coluna opcional)
    CASE
        WHEN sva.prevendas IS NOT NULL
            THEN 'activity.prevendas'
        WHEN NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
            IS NOT NULL
            THEN 'deal.sdr_ss'
        ELSE 'nao_identificado'
    END                                                              AS fonte_associacao_sdr
FROM deals_ganhos dg
LEFT JOIN lead_pick      lp    ON lp.deal_id     = dg.deal_id
LEFT JOIN act_criada     ac    ON ac.deal_id     = dg.deal_id
LEFT JOIN act_compareceu acomp ON acomp.deal_id  = dg.deal_id
LEFT JOIN sdr_via_activity sva ON sva.deal_id    = dg.deal_id
LEFT JOIN zoho_users     u_sdr ON u_sdr.id::text = dg.sdr_ss::text
ORDER BY dg.ts_venda DESC NULLS LAST;
