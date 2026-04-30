-- =============================================================================
-- Classificação deduplicada POR CANAL (na janela do dashboard).
--
-- Mesma lógica de mkt_leads_classificacao.sql, mas agrupa por (canal, email)
-- ao invés de só email. Resultado: cada email é classificado independentemente
-- DENTRO de cada canal — email +12 em Meta e -12 em Organico conta como
-- +12 em Meta e -12 em Organico (não vira ambíguo cross-canal).
--
-- Fonte: bi.vw_mkt_leads_classificacao (já com coluna `canal` normalizada
-- via mesma regra de utm_source que a vw_mkt_overview usa).
--
-- Retorna 1 linha por canal:
--   canal               — 'Meta' / 'Google' / 'Pinterest' / 'Organico'
--   leads_unicos_canal  — emails distintos no canal × janela
--   lead_mais_12        — emails com 'ATUA +12' E sem 'ATUA -12' no canal
--   lead_menos_12       — emails com 'ATUA -12' E sem 'ATUA +12' no canal
--   lead_ambiguo        — emails com os dois no canal
-- =============================================================================
WITH base AS (
  SELECT
    canal,
    email,
    classificado
  FROM bi.vw_mkt_leads_classificacao
  WHERE data_ref BETWEEN :data_ini AND :data_fim
),
flags AS (
  SELECT
    canal,
    email,
    bool_or(classificado = 'ATUA +12') AS tem_mais_12,
    bool_or(classificado = 'ATUA -12') AS tem_menos_12
  FROM base
  GROUP BY canal, email
)
SELECT
  canal,
  COUNT(*) AS leads_unicos_canal,
  COUNT(*) FILTER (WHERE tem_mais_12 AND NOT tem_menos_12) AS lead_mais_12,
  COUNT(*) FILTER (WHERE tem_menos_12 AND NOT tem_mais_12) AS lead_menos_12,
  COUNT(*) FILTER (WHERE tem_mais_12 AND tem_menos_12)    AS lead_ambiguo
FROM flags
GROUP BY canal
ORDER BY canal;
