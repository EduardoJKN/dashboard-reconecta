# Relatório Final — Otimização Funil da Reconecta (CP1–CP8.1)

**Data de referência:** 2026-06-22  
**Página:** `views/funil_reconecta.py`  
**Escopo:** performance, instrumentação e carregamento — sem alteração de regra de negócio, SQL de produção (novas queries só para v2/batch experimental) nem layout.

---

## 1. Resumo executivo

A página **Funil da Reconecta** tinha tempos altos na primeira carga e reruns caros porque consultava várias fontes (legacy, pré-vendas, executivas, investimento, benchmark histórico, meta) de forma sequencial e sem cache adequado.

Após CP1–CP8.1:

- **Rerun quente (warm):** caiu para **~0,04–0,06s** (seções principais), estável em todos os checkpoints.
- **Primeira carga fria (cold):** melhorou com benchmark v2, legacy/executivas v2, cache da meta e, opcionalmente, paralelismo em staging (~**22–38%** vs CP7.1 default no cold run1 com parallel ON).
- **Equivalência numérica e visual:** mantida em todas as validações automatizadas.
- **Paralelismo:** implementado, testado (stress 20/20 OK), **OFF em produção por default**; ativação só por env em staging/local.
- **Batch legacy benchmark:** equivalente numericamente, mas **regressão forte** em cold — permanece **OFF**.

O usuário final percebe página rápida após o primeiro acesso ao período; o primeiro acesso ainda depende do banco, mas bem menor que o baseline inicial quando paralelismo está habilitado em staging.

---

## 2. Linha do tempo dos checkpoints

| CP | Foco | Resultado principal |
|----|------|---------------------|
| **CP1** | Cache de snapshot (`st.cache_data`), `?debug_perf=1`, checkpoint Streamlit | Baseline medido; warm path identificado |
| **CP2** | Referência histórica lazy; export sob demanda | Referência e export não bloqueiam vitrine |
| **CP3** | Benchmark histórico v2 (shared frames + legacy por janela) | Menos queries; cold benchmark ~6–10s |
| **CP4** | Legacy diário v2 (`one_page_legacy_diario_v2.sql`) só no Funil | Atual mais rápido; fallback v1 |
| **CP5** | Executivas v2 agregada (`dashboard_executivas_funil_v2.sql`) só no Funil | Colunas mínimas; fallback v1 |
| **CP6** | Legacy batch benchmark (1 query / N janelas) | Equivalência OK; cold **muito pior** (~93s mês atual) |
| **CP6.1** | Rollback seguro batch → default OFF | Produção estável; `per_window` |
| **CP7** | Meta oficial: `st.cache_data` + session bootstrap + invalidação save/delete | Meta warm ~0s; cache TTL 600s |
| **CP7.1** | Estabilização, mediana 3 runs, limpeza scripts | `sem_dados` 23,8s CP7 = ruído; run1 ~17,6s |
| **CP8** | Paralelismo experimental cold path (Atual + Benchmark) | Ganho 24–42% cold isolado; equiv 5/5 |
| **CP8.1** | Staging controlado, guardrails workers 1–4, stress 5 ciclos | 20/20 PASS; produção continua OFF |

---

## 3. Tabela de tempos (main sections, cold run1)

Valores em segundos — **cold run1** (primeira carga real por cenário no processo).

| Cenário | Baseline CP6.1* | CP7.1 default | CP8.1 par ON w=3 | Ganho vs CP7.1 |
|---------|----------------:|--------------:|-----------------:|---------------:|
| Últimos 7 dias | 23,5 | 23,0 | **17,8** | −23% |
| Mês atual | 9,7 | 17,4** | **10,8** | −38% |
| Mês anterior | 9,8 | 19,3** | **12,3** | −36% |
| 01/06–17/06 | 19,1 | 17,5 | **11,0** | −37% |
| Sem dados | 18,8 | 17,6 | **13,2** | −25% |

\* CP6.1 = estado estável pré-meta cache (referência histórica).  
\*\* CP7.1 com variância de cold DB; mediana de 3 runs em warm mistura cache — usar **run1** para comparar cold.

### Warm final

| Métrica | Valor |
|---------|------:|
| Warm página (checkpoint / stress) | **0,04–0,06s** |
| Meta (session/cache hit) | **~0s** |
| Stress CP8.1 (5 ciclos × 4 cenários) | **20/20 OK**, fallback false |

### Nota sobre métricas

- **Checkpoint** (`checkpoint_funil_reconecta_streamlit.py`): mede página Streamlit completa com `?debug_perf=1`.
- **Benchmark isolado** (`benchmark_funil_parallel_loads.py`): `warm_snapshot_cached` ≠ warm da página — só 2º `load_one_page_funnel` com cache do Atual.

---

## 4. Validações

| Script | Escopo | Status (última execução consolidada) |
|--------|--------|--------------------------------------|
| `validate_funil_meta_cache.py` | Cache/session/invalidação meta | OK |
| `validate_funil_benchmark_v1_v2.py` | Equivalência benchmark v1 vs v2 | OK (5 cenários) |
| `validate_funil_executivas_v1_v2.py` | Executivas v1 vs v2 Funil | OK |
| `validate_funil_legacy_v1_v2.py` | Legacy v1 vs v2 Funil | OK |
| `validate_funil_reconecta_equivalence.py` | Equivalência página | OK |
| `checkpoint_funil_reconecta_streamlit.py` | Perf + visual AppTest | OK |
| `stress_funil_parallel_staging.py` | Estabilidade parallel ON | PASS 20/20 |

Execução final: ver seção *Checklist final* ao final deste documento (atualizada após última rodada).

---

## 5. Flags e defaults (confirmados no código)

| Variável | Default produção | Onde |
|----------|------------------|------|
| `FUNIL_PARALLEL_LOADS` | **0** (OFF) | `src/funil_parallel_load.py` |
| `FUNIL_PARALLEL_WORKERS` | **3** se inválido; clamp **1–4** | `src/funil_parallel_load.py` |
| `FUNIL_LEGACY_BENCHMARK_BATCH_V2` | **0** (OFF) | `src/repositories.py` |
| `FUNIL_LEGACY_V2` | **1** (ON no Funil) | `src/repositories.py` |
| `FUNIL_EXECUTIVAS_V2` | **1** (ON no Funil) | `src/repositories.py` |
| `FUNIL_BENCHMARK_V2` | **1** (ON) | `src/funil_benchmark.py` |

### Staging/local (opcional)

```powershell
$env:FUNIL_PARALLEL_LOADS="1"
$env:FUNIL_PARALLEL_WORKERS="3"
```

### Produção (default implícito — não definir env)

```text
FUNIL_PARALLEL_LOADS=0
FUNIL_LEGACY_BENCHMARK_BATCH_V2=0
```

Benchmark ativo: **v2**, legacy benchmark mode **per_window**, batch **OFF**.

---

## 6. Riscos e observações

1. **Paralelismo:** pronto para staging; produção deve permanecer OFF até soak com tráfego real (pool `pool_size=5`, workers máx 4).
2. **Batch legacy:** numericamente equivalente, porém lento em janelas longas — **manter OFF**.
3. **View BI `vw_dashboard_comercial_executivas_rw_v2`:** rápida mas **não equivalente** à regra do Funil; não usar sem alinhamento de negócio.
4. **Meta cache:** TTL **600s**; `save`/`delete` invalida cache local corretamente.
5. **Referência histórica:** ainda pesada quando carregada (lazy), mas não bloqueia vitrine no fluxo normal.
6. **Mediana vs run1:** em checkpoint com `--runs 3`, runs 2–3 refletem cache de processo — comparar cold com **run1** ou **max**.

---

## 7. Próximas oportunidades (não implementadas)

- Soak do paralelismo em staging com uso real.
- Alinhar diferenças da view BI executivas v2 vs agregação Funil (se unificação desejada).
- Índices recomendados (documentar, não aplicar neste fechamento).
- Materialized view diária vendas/montante/receita (avaliar necessidade).
- Tuning SQL do maior bloco individual (`load_one_page_funnel` / `executivas_v2` wide range).

---

## 8. Arquivos alterados (git)

### 8.1 Código principal

| Arquivo | Papel |
|---------|-------|
| `views/funil_reconecta.py` | Página: lazy ref/export, meta, perf |
| `src/one_page_funnel.py` | Snapshot, parallel path, benchmark shared frames |
| `src/funil_benchmark.py` | Benchmark v2, legacy per_window / batch experimental |
| `src/funil_meta_store.py` | Meta cache/session/invalidação |
| `src/funil_reconecta_perf.py` | Instrumentação `?debug_perf=1` |
| `src/funil_parallel_load.py` | Paralelismo experimental (CP8) |
| `src/repositories.py` | Wrappers v2, batch, flags |
| `src/prevendas_transforms.py` | KPIs compartilhados |
| `src/transforms.py` | Ajustes executivas |
| `views/home.py`, `views/executivas.py`, `views/prevendas_overview.py` | Menores (não Funil core) |
| `src/ui/prevendas_components.py` | Menor |

### 8.2 Queries (novas — Funil v2 / experimental)

| Arquivo | Status |
|---------|--------|
| `src/queries/one_page_legacy_diario_v2.sql` | **Ativo** (Funil, flag ON) |
| `src/queries/dashboard_executivas_funil_v2.sql` | **Ativo** (Funil, flag ON) |
| `src/queries/one_page_legacy_diario_benchmark_batch_v2.sql` | **Experimental OFF** |

### 8.3 Performance / debug

- `src/funil_reconecta_perf.py`
- Query param `?debug_perf=1` na view

### 8.4 Scripts benchmark / checkpoint / validação

| Script |
|--------|
| `scripts/checkpoint_funil_reconecta_streamlit.py` |
| `scripts/validate_funil_meta_cache.py` |
| `scripts/validate_funil_benchmark_v1_v2.py` |
| `scripts/validate_funil_executivas_v1_v2.py` |
| `scripts/validate_funil_legacy_v1_v2.py` |
| `scripts/validate_funil_legacy_benchmark_batch_v1_v2.py` |
| `scripts/validate_funil_reconecta_equivalence.py` |
| `scripts/benchmark_funil_reconecta_load.py` |
| `scripts/benchmark_funil_atual_load.py` |
| `scripts/benchmark_funil_executivas_load.py` |
| `scripts/benchmark_funil_meta_load.py` |
| `scripts/benchmark_funil_parallel_loads.py` |
| `scripts/stress_funil_parallel_staging.py` |
| `scripts/explain_funil_executivas.py` |
| `scripts/explain_funil_legacy_diario.py` |

### 8.5 Resultados JSON (artefatos de medição)

- `scripts/checkpoint_funil_reconecta_results.json`
- `scripts/benchmark_funil_parallel_results.json`
- `scripts/stress_funil_parallel_staging_results.json`

### 8.6 Experimental mantido OFF

- `FUNIL_LEGACY_BENCHMARK_BATCH_V2=0`
- `FUNIL_PARALLEL_LOADS=0` (produção)
- SQL batch em `one_page_legacy_diario_benchmark_batch_v2.sql` (código mantido, não usado)

---

## 9. O que ficou experimental / OFF

| Item | Default | Notas |
|------|---------|-------|
| Paralelismo cold path | OFF | Opt-in staging; fallback sequencial |
| Legacy benchmark batch | OFF | Regressão cold; equiv OK |
| View BI executivas v2 global | Não usada no Funil | Funil usa SQL agregada própria |

---

## 10. Recomendação final

### Produção

- Manter **todos os defaults atuais** (parallel OFF, batch OFF, v2 ON).
- Não alterar env em deploy padrão.
- Monitorar `?debug_perf=1` pontualmente se necessário.

### Staging / local

```powershell
$env:FUNIL_PARALLEL_LOADS="1"
$env:FUNIL_PARALLEL_WORKERS="3"
```

- Rodar `stress_funil_parallel_staging.py` após deploy.
- Validar soak antes de considerar default ON em produção.

### Fechamento

A série CP1–CP8.1 está **concluída**. Não há CP9 planejado neste fechamento; próximos passos são operacionais (soak, tuning SQL pontual) e não novas otimizações estruturais nesta entrega.

---

## 11. Checklist final de execução

Execução final: **2026-06-23** (parallel OFF — default produção).

| Comando | Resultado |
|---------|-----------|
| `validate_funil_meta_cache.py` | **OK** (6/6) |
| `validate_funil_benchmark_v1_v2.py` | **OK** (5/5) |
| `validate_funil_executivas_v1_v2.py` | **OK** (5/5) |
| `validate_funil_legacy_v1_v2.py` | **OK** (5/5) |
| `validate_funil_reconecta_equivalence.py` | **OK** (4/4) |
| `checkpoint_funil_reconecta_streamlit.py` | **OK** — visual OK todos cenários; warm 0,04–0,10s |
| `stress_funil_parallel_staging.py` | **PASS 20/20** (CP8.1, parallel ON) — referência CP8.1 |

### Checkpoint final (default, parallel OFF)

| Cenário | Cold | Warm | Visual |
|---------|-----:|-----:|:------:|
| Últimos 7 dias | 23,2s | 0,05s | OK |
| Mês atual | 9,7s | 0,05s | OK |
| Mês anterior | 9,9s | 0,08s | OK |
| 01/06–17/06 | 16,6s | 0,05s | OK |
| Sem dados | 18,9s | 0,06s | OK |

---

*Gerado no fechamento CP1–CP8.1 — Funil da Reconecta.*
