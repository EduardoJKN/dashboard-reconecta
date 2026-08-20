-- =============================================================================
-- One Page — Indicações por tipo de venda (info adicional nos cards).
-- =============================================================================
-- Conta deals ganhos com `fonte_de_lead = 'Indicação'`, quebrados pelo
-- `tipo_venda` (não é um tipo de venda em si — é origem do lead).
--
-- Buckets alinhados ao mix de cards da One Page:
--   novos       → 'Novo cliente'
--   ascensoes   → 'Ascensão'
--   renovacoes  → 'Renovação' | 'Renovação antecipada'
--   upgrades    → 'Upgrade'
--   eventos     → 'Novo cliente EVENTO'
--   ingressos   → tipo LIKE 'Ingresso%'
--   total       → todas as indicações (qualquer tipo)
--
-- Janela: data_hora_compra::date IN [:data_ini, :data_fim]
-- E-mail: nulo/vazio excluído + filtros canônicos de teste (One Page).
-- =============================================================================
SELECT
    COUNT(DISTINCT d.id)::bigint AS total,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.tipo_venda = 'Novo cliente'
    )::bigint AS novos,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.tipo_venda = 'Ascensão'
    )::bigint AS ascensoes,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.tipo_venda IN ('Renovação', 'Renovação antecipada')
    )::bigint AS renovacoes,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.tipo_venda = 'Upgrade'
    )::bigint AS upgrades,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.tipo_venda = 'Novo cliente EVENTO'
    )::bigint AS eventos,
    COUNT(DISTINCT d.id) FILTER (
        WHERE d.tipo_venda LIKE 'Ingresso%'
    )::bigint AS ingressos
FROM zoho_deals d
WHERE d.stage IN ('Ganho', 'Fechado Ganho')
  AND d.data_hora_compra::date BETWEEN :data_ini AND :data_fim
  AND d.fonte_de_lead = 'Indicação'
  AND d.email IS NOT NULL
  AND btrim(d.email) <> ''
  AND lower(d.email) NOT LIKE '%@teste%'
  AND lower(d.email) NOT LIKE 'teste@%'
  AND lower(d.email) NOT LIKE '%smarts%'
  AND lower(d.email) NOT LIKE '%reconecta%';
