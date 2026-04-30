SELECT
    post_id,
    publicado_em,
    data_ref,
    tipo_midia,
    permalink,
    alcance,
    curtidas,
    comentarios,
    salvamentos,
    engajamento,
    username,
    name,
    followers_count,
    taxa_engajamento_pct
FROM bi.vw_mkt_social
WHERE data_ref BETWEEN :data_ini AND :data_fim
ORDER BY publicado_em DESC NULLS LAST;
