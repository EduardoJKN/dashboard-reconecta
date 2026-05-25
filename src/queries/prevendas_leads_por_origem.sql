-- =============================================================================
-- Pré-vendas — leads daily-distinct quebrados por funil_origem.
-- =============================================================================
-- Espelha a regra do card "Leads totais" em prevendas_overview_diario.sql:
-- daily-distinct por (dia, email), mesmos filtros canônicos de e-mails de
-- teste/internos. Aqui agrupamos por funil_origem para alimentar o
-- breakdown acoplado ao card.
--
-- Quando o mesmo email aparece N vezes no mesmo dia com funis_origem
-- diferentes (raro mas possível enquanto a base está sendo populada),
-- DISTINCT ON escolhe UM funil_origem por (dia, email) priorizando:
--   1) entradas com funil_origem populado (≠ 'Sem origem');
--   2) timestamp DESC NULLS LAST;
--   3) id DESC.
-- Garante que SUM(leads) por funil bata com COUNT do card geral
-- (1 row por (dia, email) ⇒ sem dupla contagem).
--
-- `funil_origem` foi ativada em ext_reconecta.leads em 25/05/2026 —
-- entradas anteriores caem em 'Sem origem'.
-- =============================================================================
WITH leads_dedup AS (
    SELECT DISTINCT ON (l.created_at::date, lower(btrim(l.email)))
        l.created_at::date                                            AS data_ref,
        lower(btrim(l.email))                                         AS email_norm,
        COALESCE(NULLIF(btrim(l.funil_origem), ''), 'Sem origem')     AS funil_origem
    FROM ext_reconecta.leads l
    WHERE l.created_at::date BETWEEN :data_ini AND :data_fim
      AND l.email IS NOT NULL
      AND btrim(l.email) <> ''
      AND lower(l.email) NOT LIKE '%@teste%'
      AND lower(l.email) NOT LIKE 'teste@%'
      AND lower(l.email) NOT LIKE '%smarts%'
      AND lower(l.email) NOT LIKE '%reconecta%'
    ORDER BY
        l.created_at::date,
        lower(btrim(l.email)),
        (CASE WHEN NULLIF(btrim(l.funil_origem), '') IS NOT NULL
              THEN 0 ELSE 1 END),
        l."timestamp" DESC NULLS LAST,
        l.id DESC
)
SELECT
    funil_origem,
    COUNT(*)::bigint AS leads
FROM leads_dedup
GROUP BY funil_origem
ORDER BY
    (CASE funil_origem
         WHEN 'VSL'        THEN 1
         WHEN 'SE'         THEN 2
         WHEN 'AG'         THEN 3
         WHEN 'Sem origem' THEN 99
         ELSE 50
     END),
    funil_origem;
