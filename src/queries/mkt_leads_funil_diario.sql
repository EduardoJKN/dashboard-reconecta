-- =============================================================================
-- Leads totais validados (lp_form) — só usado na Visão Geral Marketing.
--
-- bi.vw_funil_leads_diario.leads_lp_unicos é a fonte canônica para "Leads
-- totais" no período. Não tem grão de canal — por isso só é consumida
-- quando o filtro de canal está em "todos canais". Caso contrário a página
-- cai para bi.vw_mkt_overview.leads (canal-aware mas levemente inflado em
-- períodos com lead duplicado entre dias).
--
-- Não confundir com src/queries/funil_leads_diario.sql (mesma view, mas
-- consumida pelas Vendas via repositories.get_funil_leads_diario).
-- =============================================================================
SELECT
    data_ref,
    leads_lp_unicos
FROM bi.vw_funil_leads_diario
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY data_ref;
