-- =============================================================================
-- Executivas oficiais — fonte de verdade do time ATIVO de Vendas.
-- =============================================================================
-- Origem: `fdw_reconecta.executivas_vendas` (espelho FDW via foreign server
-- `reconecta_fdw` do schema `assistencial` no Reconecta DB).
--
-- Uso: alimenta o filtro do ranking nas páginas Time de Vendas → Visão
-- Geral (`views/home.py`) e Executivas & Times (`views/executivas.py`).
-- O ranking calculado em `bi.vw_dashboard_comercial_executivas_rw` traz
-- closers que não pertencem ao time atual (SDRs, pessoas que saíram, ou
-- registros "Sem executiva"). Esta lista é cruzada por nome normalizado
-- (token-based, ver `executivas_ranking_oficiais` em src/transforms.py)
-- para manter no ranking apenas os 7 ativos validados em mai/2026.
--
-- ⚠ Evolução prevista: comparar por `id_crm` em vez de nome é mais
-- seguro contra variação de grafia. Hoje a view do ranking não expõe o
-- ID Zoho da executiva, então a comparação fica via nome — quando a
-- view passar a expor o ID, trocar o filtro para INNER JOIN por id_crm.
-- =============================================================================
SELECT
    id,
    nome,
    email,
    id_crm,
    ativo
FROM fdw_reconecta.executivas_vendas
WHERE ativo = 'y'
  AND nome IS NOT NULL
  AND btrim(nome) <> ''
ORDER BY nome;
