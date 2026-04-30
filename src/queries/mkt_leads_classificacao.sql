-- =============================================================================
-- Classificação consolidada (+12 / -12 / ambíguo) com dedupe DENTRO DA JANELA.
--
-- Fonte: bi.vw_mkt_leads_classificacao (view nova, estrutura limpa).
--   colunas expostas pela view: data_ref, email, classificado
--   a view NÃO faz mais dedupe lifetime — agrega só normalização e exclusões.
--   o dedupe por janela acontece aqui no app via BOOL_OR (BOOL_OR avalia só
--   os eventos que passaram no WHERE da CTE base).
--
-- Motivo de não consultar lp_form.leads direto: o usuário do app não tem
-- permissão na schema lp_form. A view bi.vw_mkt_leads_classificacao foi
-- criada especificamente como base limpa e segura para esse cálculo.
--
-- Retorna 1 linha com:
--   lead_mais_12        — emails com 'ATUA +12' E sem 'ATUA -12' no período
--   lead_menos_12       — emails com 'ATUA -12' E sem 'ATUA +12' no período
--   lead_ambiguo        — emails com os dois no período (ficam fora dos grupos)
--   leads_qualificados  — lead_mais_12 + lead_menos_12 (ambíguos OUT)
-- =============================================================================
WITH base AS (
  SELECT
    email,
    classificado
  FROM bi.vw_mkt_leads_classificacao
  WHERE data_ref BETWEEN :data_ini AND :data_fim
),
flags AS (
  SELECT
    email,
    bool_or(classificado = 'ATUA +12') AS tem_mais_12,
    bool_or(classificado = 'ATUA -12') AS tem_menos_12
  FROM base
  GROUP BY email
)
SELECT
  COUNT(*) FILTER (WHERE tem_mais_12 AND NOT tem_menos_12) AS lead_mais_12,
  COUNT(*) FILTER (WHERE tem_menos_12 AND NOT tem_mais_12) AS lead_menos_12,
  COUNT(*) FILTER (WHERE tem_mais_12 AND tem_menos_12)    AS lead_ambiguo,
  COUNT(*) FILTER (
    WHERE (tem_mais_12 AND NOT tem_menos_12)
       OR (tem_menos_12 AND NOT tem_mais_12)
  ) AS leads_qualificados
FROM flags;
