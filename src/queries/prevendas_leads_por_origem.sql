-- =============================================================================
-- Pré-vendas — leads daily-distinct quebrados por funil_origem.
-- =============================================================================
-- Espelha a regra dos cards "Leads totais" e "Leads +12" em
-- prevendas_overview_diario.sql: daily-distinct por (dia, email), mesmos
-- filtros canônicos de e-mails de teste/internos. Aqui agrupamos por
-- funil_origem para alimentar os breakdowns acoplados aos cards.
--
-- Quando o mesmo email aparece N vezes no mesmo dia:
--   * funil_origem: DISTINCT ON escolhe UM por (dia, email), priorizando
--     entradas populadas (≠ 'Sem origem'), depois timestamp DESC. Garante
--     que SUM(leads) por funil bata com o card geral.
--   * leads_mais_12 / leads_menos_12: BOOL_OR sobre TODAS as linhas do
--     (dia, email), igual a prevendas_overview_diario.sql:51-61. Um email
--     conta como +12 se qualquer linha do dia tiver classificado='atua +12'.
--
-- `funil_origem` foi ativada em ext_reconecta.leads em 25/05/2026 —
-- entradas anteriores caem em 'Sem origem'.
-- =============================================================================
WITH leads_clean AS (
    SELECT
        l.created_at::date                                            AS data_ref,
        lower(btrim(l.email))                                         AS email_norm,
        NULLIF(btrim(l.funil_origem), '')                             AS funil_origem_raw,
        lower(btrim(coalesce(l.classificado, '')))                    AS classif_norm,
        l."timestamp"                                                 AS ts,
        l.id                                                          AS lid
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
),
leads_origem_pick AS (
    -- 1 row por (data, email): escolhe funil_origem por prioridade
    -- (populado primeiro, depois timestamp DESC). Determinístico.
    SELECT DISTINCT ON (data_ref, email_norm)
        data_ref,
        email_norm,
        COALESCE(funil_origem_raw, 'Sem origem')                      AS funil_origem
    FROM leads_clean
    ORDER BY data_ref, email_norm,
        (CASE WHEN funil_origem_raw IS NOT NULL THEN 0 ELSE 1 END),
        ts DESC NULLS LAST,
        lid DESC
),
leads_classif AS (
    -- 1 row por (data, email): BOOL_OR garante que +12/-12 não dependa
    -- de qual linha o DISTINCT ON acima escolheu para funil_origem.
    SELECT
        data_ref,
        email_norm,
        BOOL_OR(classif_norm = 'atua +12')                            AS tem_mais_12,
        BOOL_OR(classif_norm = 'atua -12')                            AS tem_menos_12
    FROM leads_clean
    GROUP BY data_ref, email_norm
)
SELECT
    p.funil_origem,
    COUNT(*)::bigint                                                   AS leads,
    COUNT(*) FILTER (WHERE c.tem_mais_12)::bigint                      AS leads_mais_12,
    COUNT(*) FILTER (WHERE c.tem_menos_12)::bigint                     AS leads_menos_12
FROM leads_origem_pick p
JOIN leads_classif c
  ON c.data_ref  = p.data_ref
 AND c.email_norm = p.email_norm
GROUP BY p.funil_origem
ORDER BY
    (CASE p.funil_origem
         WHEN 'VSL'        THEN 1
         WHEN 'SE'         THEN 2
         WHEN 'AG'         THEN 3
         WHEN 'Sem origem' THEN 99
         ELSE 50
     END),
    p.funil_origem;
