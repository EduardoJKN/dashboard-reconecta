-- =============================================================================
-- Criativos — auditoria bruta fdw_reconecta.anuncios (período do dashboard).
-- Uma linha por linha de fato na fonte Meta (grão diário / snapshot do FDW).
-- Filtro de campanha/status na página aplica-se no app (via ad_ids da vw).
-- =============================================================================
SELECT *
FROM fdw_reconecta.anuncios a
WHERE a.date_start::date BETWEEN :data_ini AND :data_fim
ORDER BY
    a.date_start NULLS LAST,
    a.campaign_name NULLS LAST,
    a.adset_name NULLS LAST,
    a.ad_name NULLS LAST,
    a.ad_id NULLS LAST;
