-- =============================================================================
-- Notificações de Vendas — fonte oficial da página "Notificações & Vínculo
-- Comercial" (antiga SLA & Tempo de Resposta).
-- =============================================================================
-- Origem: `fdw_reconecta.controle_notificacao_vendas` (welcome/onboarding
-- disparado pelo time de Customer Success — espelho FDW via foreign
-- server `reconecta_fdw` do schema `assistencial` no Reconecta DB).
--
-- Cruzamento opcional com o funil comercial via `zoho_deals` (tabela
-- local Railway, mesma fonte usada por compatibilidade_sdr_closer.sql,
-- leads_visao_geral.sql, etc.):
--   1. PRIMEIRO tenta por `id_negocio` da notificação = `zoho_deals.id`.
--   2. Fallback: deal mais recente com mesmo `email`
--      (LATERAL ... LIMIT 1 ORDER BY `zoho_deals.created_at` DESC). Só
--      dispara quando o match por id falhou.
--
-- Resolução de nomes:
--   - `sdr_ss` e `executiva_vendas` no Railway são IDs Zoho; resolvidos
--     via `zoho_users` (mesma regra de compatibilidade_sdr_closer.sql).
--   - `closer` operacional == `executiva_vendas` (sinônimos no projeto).
--   - `id_vendedora` da notificação → `fdw_reconecta.executivas_vendas`.
--
-- Cobertura validada no Reconecta DB (jul/2025 → mai/2026, 593 linhas):
--   - 319 casam por id direto; 380 por email; 394 (66%) por algum dos dois
--   - 310 (52%) com `sdr_ss` resolvido
--   - 276 (47%) com `executiva_vendas`
--
-- ⚠ Limitações:
--   - Social Sellers (Geovanna, Estefany, Isabella Esbell) NÃO aparecem
--     como sdr_ss desses deals — não significa ausência de atuação.
--   - 274 (~34%) sem match: provavelmente deals do pipeline pós-venda
--     (IDs Zoho separados dos deals comerciais).
--   - `owner_deal`, `origem_lead`, `funil_origem`: colunas existem em
--     `zoho.crm_negocios` no Reconecta DB mas não são usadas em nenhuma
--     outra query do projeto sobre `zoho_deals`. Mantidas no SELECT como
--     NULL com alias preservado, para não quebrar a tabela Python. Se a
--     equipe confirmar que existem mesmo no Railway, basta trocar para
--     `zd_id.<coluna>` / `zd_email.<coluna>`.
-- =============================================================================
SELECT
    n.id                                AS notif_id,
    n.dt_criacao                        AS dt_criacao,
    n.nome                              AS nome,
    n.email                             AS email,
    n.telefone                          AS telefone,
    n.id_negocio                        AS id_negocio_notif,
    n.id_vendedora                      AS id_vendedora,
    ev.nome                             AS vendedora_resolvida,
    n.tipo_venda                        AS tipo_venda_notif,
    n.venda_notificada                  AS venda_notificada,
    n.welcome                           AS welcome,
    n.cs_nome                           AS cs_nome,
    n.id_negocio_pos                    AS id_negocio_pos,

    -- Cruzamento priority `id_negocio > email`. LATERAL só roda quando
    -- match direto falhou (zd_id.id IS NULL).
    COALESCE(zd_id.id, zd_email.id)                                  AS deal_id_match,
    CASE
        WHEN zd_id.id    IS NOT NULL THEN 'id_negocio'
        WHEN zd_email.id IS NOT NULL THEN 'email'
        ELSE NULL
    END                                                              AS metodo_match,
    COALESCE(zd_id.stage,      zd_email.stage)                       AS stage_deal,
    COALESCE(zd_id.tipo_venda, zd_email.tipo_venda)                  AS tipo_venda_deal,

    -- sdr_ss / executiva_vendas: IDs resolvidos para nome via zoho_users.
    NULLIF(TRIM(u_sdr.first_name    || ' ' || u_sdr.last_name),    '')  AS sdr_ss,
    NULLIF(TRIM(u_closer.first_name || ' ' || u_closer.last_name), '')  AS closer,
    NULLIF(TRIM(u_closer.first_name || ' ' || u_closer.last_name), '')  AS executiva_vendas,

    -- Campos não confirmados em zoho_deals (Railway) — devolvidos como
    -- NULL com alias preservado para o consumidor Python.
    NULL::text                                                          AS owner_deal,
    NULL::text                                                          AS origem_lead,
    NULL::text                                                          AS funil_origem,

    -- Flags pré-computadas para evitar lógica duplicada no Python.
    (COALESCE(zd_id.id, zd_email.id) IS NOT NULL)                       AS tem_vinculo_comercial,
    (NULLIF(TRIM(u_sdr.first_name || ' ' || u_sdr.last_name), '')
        IS NOT NULL)                                                    AS tem_prevendas_identificado

FROM fdw_reconecta.controle_notificacao_vendas n
LEFT JOIN zoho_deals zd_id
       ON zd_id.id::text = n.id_negocio
LEFT JOIN LATERAL (
    SELECT zd2.id, zd2.stage, zd2.tipo_venda, zd2.sdr_ss,
           zd2.executiva_vendas, zd2.created_at
    FROM zoho_deals zd2
    WHERE zd_id.id IS NULL
      AND n.email IS NOT NULL
      AND btrim(n.email) <> ''
      AND lower(btrim(zd2.email)) = lower(btrim(n.email))
    ORDER BY zd2.created_at DESC NULLS LAST
    LIMIT 1
) zd_email ON TRUE
LEFT JOIN zoho_users u_sdr
       ON u_sdr.id::text = COALESCE(zd_id.sdr_ss, zd_email.sdr_ss)::text
LEFT JOIN zoho_users u_closer
       ON u_closer.id::text = COALESCE(zd_id.executiva_vendas,
                                       zd_email.executiva_vendas)::text
LEFT JOIN fdw_reconecta.executivas_vendas ev
       ON ev.id::text = n.id_vendedora

WHERE n.dt_criacao::date BETWEEN :data_ini AND :data_fim
ORDER BY n.dt_criacao DESC;
