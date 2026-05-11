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
-- Para vendas: NÃO uso priority match lead → deal aqui. A regra é
-- "deal está atrelado à activity (what_id)" → o SDR daquela activity
-- é creditado pela venda. DISTINCT ON deal_id garante que cada deal
-- conte 1× (creditado à activity mais recente).
-- =============================================================================
WITH acts AS (
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
      AND a.start_datetime::date BETWEEN :data_ini AND :data_fim
),
-- Deals associados às activities do período (via what_id), filtrados por
-- ganho na mesma janela. DISTINCT ON deal_id pra que cada deal seja
-- creditado a UM SDR (o da activity mais recente). O par (sdr, fonte_sdr)
-- segue o que foi escolhido na activity vencedora.
deals_acts AS (
    SELECT DISTINCT ON (zd.id)
        zd.id          AS deal_id,
        a.sdr,
        a.fonte_sdr,
        zd.tipo_venda,
        CASE WHEN NULLIF(btrim(zd.amount), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                     REGEXP_REPLACE(TRIM(zd.amount), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS montante,
        CASE WHEN NULLIF(btrim(zd.receita), '') IS NULL THEN 0::numeric
        ELSE REPLACE(
                 REPLACE(
                     REGEXP_REPLACE(TRIM(zd.receita), '[^0-9,.-]', '', 'g'),
                     '.', ''),
                 ',', '.'
             )::numeric
        END AS receita
    FROM acts a
    JOIN zoho_deals zd ON zd.id = a.deal_id
    WHERE zd.stage IN ('Ganho','Fechado Ganho')
      AND zd.data_hora_compra::date BETWEEN :data_ini AND :data_fim
    ORDER BY zd.id, a.data_ref DESC
),
acts_agg AS (
    SELECT
        sdr, fonte_sdr,
        COUNT(*)::bigint                                         AS agendamentos,
        COUNT(*) FILTER (WHERE status_reuniao = 'Concluída')::bigint
                                                                  AS comparecimentos,
        COUNT(*) FILTER (WHERE status_reuniao = 'Cancelada')::bigint
                                                                  AS cancelamentos
    FROM acts
    GROUP BY sdr, fonte_sdr
),
deals_agg AS (
    SELECT
        sdr, fonte_sdr,
        COUNT(*)::bigint                                         AS vendas,
        COUNT(*) FILTER (WHERE tipo_venda = 'Novo cliente')::bigint
                                                                  AS vendas_novas,
        SUM(montante)::numeric                                    AS montante,
        SUM(receita)::numeric                                     AS receita
    FROM deals_acts
    GROUP BY sdr, fonte_sdr
),
pares AS (
    SELECT sdr, fonte_sdr FROM acts_agg
    UNION SELECT sdr, fonte_sdr FROM deals_agg
)
SELECT
    p.sdr,
    p.fonte_sdr,
    COALESCE(a.agendamentos, 0)::bigint     AS agendamentos,
    COALESCE(a.comparecimentos, 0)::bigint  AS comparecimentos,
    COALESCE(a.cancelamentos, 0)::bigint    AS cancelamentos,
    COALESCE(d.vendas, 0)::bigint           AS vendas,
    COALESCE(d.vendas_novas, 0)::bigint     AS vendas_novas,
    COALESCE(d.montante, 0)::numeric        AS montante,
    COALESCE(d.receita, 0)::numeric         AS receita
FROM pares p
LEFT JOIN acts_agg  a USING (sdr, fonte_sdr)
LEFT JOIN deals_agg d USING (sdr, fonte_sdr)
ORDER BY agendamentos DESC, vendas DESC;
