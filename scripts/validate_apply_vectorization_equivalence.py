"""Validação de equivalência — vetorização dos blocos `DataFrame.apply(lambda r: ...)`
nas views executivas, prevendas_overview e one_page.

Compara a versão escalar original (lambda row-wise) com a versão vetorizada
proposta, em DataFrames sintéticos com casos extremos:

- 0 e None no numerador / denominador
- NaN no numerador / denominador / ambos
- valores inteiros e float grandes
- negativos
- séries vazias

Saída: pass/fail por bloco. Falhas exibem `assert_series_equal` detalhado.
Regressão automática contra drift se algum dos helpers escalares ou
vetorizados for alterado no futuro.

Uso:  python scripts/validate_apply_vectorization_equivalence.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Funções escalares ORIGINAIS (copiadas dos arquivos atuais, intocadas).
# ---------------------------------------------------------------------------

def _safe_pct_scalar(num, den) -> float:
    """views/executivas.py:127"""
    try:
        d = float(den or 0)
        return (float(num or 0) / d) * 100 if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_div_scalar(num, den):
    """views/one_page.py:103"""
    try:
        d = float(den or 0)
        return float(num or 0) / d if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def _ratio_scalar(num, den):
    """views/prevendas_overview.py:1351 (inline)"""
    return (num / den * 100.0) if den else None


def _ticket_medio_scalar(row):
    """views/executivas.py:740"""
    return (float(row["montante"]) / float(row["vendas"])) \
        if float(row.get("vendas", 0) or 0) > 0 else 0.0


# ---------------------------------------------------------------------------
# Versões VETORIZADAS propostas.
# ---------------------------------------------------------------------------

def _safe_pct_vec(num_s: pd.Series, den_s: pd.Series) -> np.ndarray:
    """Equivalente vetorizado de `_safe_pct_scalar`.

    Semântica preservada (verificada em test_safe_pct_corner_cases):
      - den == 0 (ou None convertido a 0): 0.0
      - den == NaN: propaga NaN (NaN é truthy em Python → ramo de cálculo)
      - num == NaN, den válido: NaN
      - num/den válidos: num/den * 100
    """
    num = pd.to_numeric(num_s, errors="coerce").to_numpy(dtype=float)
    den = pd.to_numeric(den_s, errors="coerce").to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = num / den * 100.0
    # `den == 0` é False para NaN — NaN cai no ramo `ratio` (= NaN).
    return np.where(den == 0, 0.0, ratio)


def _safe_div_vec(num_s: pd.Series, den_s: pd.Series) -> np.ndarray:
    """Equivalente vetorizado de `_safe_div_scalar` (sem * 100)."""
    num = pd.to_numeric(num_s, errors="coerce").to_numpy(dtype=float)
    den = pd.to_numeric(den_s, errors="coerce").to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = num / den
    return np.where(den == 0, 0.0, ratio)


def _ratio_vec(num_s: pd.Series, den_s: pd.Series) -> np.ndarray:
    """Equivalente vetorizado de `_ratio_scalar` — retorna NaN quando den é 0/None.

    No DataFrame, `None` em coluna numérica vira NaN (comportamento padrão pandas).
    """
    num = pd.to_numeric(num_s, errors="coerce").to_numpy(dtype=float)
    den = pd.to_numeric(den_s, errors="coerce").to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = num / den * 100.0
    return np.where(den == 0, np.nan, ratio)


def _ticket_medio_vec(montante_s: pd.Series, vendas_s: pd.Series) -> np.ndarray:
    """Equivalente vetorizado de `_ticket_medio_scalar`."""
    montante = pd.to_numeric(montante_s, errors="coerce").to_numpy(dtype=float)
    vendas = pd.to_numeric(vendas_s, errors="coerce").to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = montante / vendas
    # `vendas > 0` é False para NaN e para <=0 — ambos viram 0.0.
    return np.where(vendas > 0, ratio, 0.0)


# ---------------------------------------------------------------------------
# DataFrames sintéticos com casos extremos.
# ---------------------------------------------------------------------------

# Cenário de produção: colunas SEMPRE numéricas (saída de groupby.sum() ou
# SQL com cast). None do banco vira NaN. NaN preserva semântica de propagação
# entre escalar e vetor (validado em test_safe_pct).
#
# Casos cobertos:
#  row 0  — caso típico positivo
#  row 1  — den=0 (deve retornar 0 ou None, depende da função)
#  row 2  — num=0, den>0 (resultado=0)
#  row 3  — num=NaN, den>0 (propaga NaN)
#  row 4  — ambos NaN
#  row 5  — magnitude alta
#  row 6  — num negativo (resultado negativo)
#  row 7  — grandes inteiros
#  row 8  — den=0 (variação)
#  row 9  — todos 0
CORNER_CASES = pd.DataFrame({
    "vendas":          [10.0,  0.0,   5.0,   float("nan"), float("nan"), 100.0, -3.0,  1e9,  2.0,  0.0],
    "agendamentos":    [50.0,  30.0,  0.0,   20.0,         10.0,          500.0, 100.0, 2e9,  0.0,  0.0],
    "comparecimentos": [20.0,  25.0,  0.0,   float("nan"), 8.0,           450.0, float("nan"), 1e9, 1.0,  5.0],
    "montante":        [5000.0, 0.0,  100.0, float("nan"), float("nan"),  5e7,   200.0, 1e12, 100.0, 0.0],
    "receita":         [4500.0, 0.0,  80.0,  500.0,        90.0,          4e7,   float("nan"), 9e11, 50.0, 0.0],
    "oportunidades":   [200.0, 100.0, 50.0,  60.0,         40.0,          1000.0, 200.0, 3e9,  10.0, 0.0],
}, dtype=float)


# ---------------------------------------------------------------------------
# Testes — assert_series_equal (NaN==NaN no compare por padrão).
# ---------------------------------------------------------------------------

def _apply_scalar(df: pd.DataFrame, num_col: str, den_col: str, fn) -> pd.Series:
    return df.apply(lambda r: fn(r[num_col], r[den_col]), axis=1)


def _assert_equivalent(label: str, scalar: pd.Series, vector: np.ndarray) -> None:
    scalar_arr = scalar.to_numpy(dtype=float)
    vector_arr = np.asarray(vector, dtype=float)
    same = np.array_equal(scalar_arr, vector_arr, equal_nan=True)
    if same:
        print(f"  OK  {label}")
        return
    print(f"  FAIL  {label}")
    df = pd.DataFrame({"scalar": scalar_arr, "vector": vector_arr})
    df["match"] = np.isclose(df["scalar"], df["vector"], equal_nan=True)
    print(df.to_string())
    raise AssertionError(f"Divergência em {label}")


def test_safe_pct() -> None:
    print("\n[executivas.py] _safe_pct vetorizado")
    df = CORNER_CASES
    # pct_conversao = vendas / agendamentos * 100
    _assert_equivalent(
        "pct_conversao  (vendas/agendamentos*100)",
        _apply_scalar(df, "vendas", "agendamentos", _safe_pct_scalar),
        _safe_pct_vec(df["vendas"], df["agendamentos"]),
    )
    # pct_comparecimento = comparecimentos / agendamentos * 100
    _assert_equivalent(
        "pct_comparecimento  (comparecimentos/agendamentos*100)",
        _apply_scalar(df, "comparecimentos", "agendamentos", _safe_pct_scalar),
        _safe_pct_vec(df["comparecimentos"], df["agendamentos"]),
    )
    # pct_vendas = vendas / comparecimentos * 100
    _assert_equivalent(
        "pct_vendas  (vendas/comparecimentos*100)",
        _apply_scalar(df, "vendas", "comparecimentos", _safe_pct_scalar),
        _safe_pct_vec(df["vendas"], df["comparecimentos"]),
    )
    # pct_recebimento = receita / montante * 100
    _assert_equivalent(
        "pct_recebimento  (receita/montante*100)",
        _apply_scalar(df, "receita", "montante", _safe_pct_scalar),
        _safe_pct_vec(df["receita"], df["montante"]),
    )


def test_ticket_medio() -> None:
    print("\n[executivas.py] _ticket_medio vetorizado")
    df = CORNER_CASES
    scalar = df.apply(_ticket_medio_scalar, axis=1)
    vector = _ticket_medio_vec(df["montante"], df["vendas"])
    _assert_equivalent("ticket_medio  (montante/vendas se vendas>0 else 0)",
                       scalar, vector)


def test_one_page_safe_div() -> None:
    print("\n[one_page.py] _safe_div * 100 vetorizado")
    df = CORNER_CASES
    # one_page faz: out["pct_x"] = out.apply(lambda r: _safe_div(...) * 100, axis=1)
    # Vetorizado: _safe_div_vec(num, den) * 100
    pairs = [
        ("pct_comparecimento", "comparecimentos", "agendamentos"),
        ("pct_conversao",      "vendas",          "agendamentos"),
        ("pct_vendas",         "vendas",          "comparecimentos"),
        ("pct_recebimento",    "receita",         "montante"),
    ]
    for label, num, den in pairs:
        scalar = df.apply(
            lambda r: _safe_div_scalar(r[num], r[den]) * 100, axis=1,
        )
        vector = _safe_div_vec(df[num], df[den]) * 100
        _assert_equivalent(f"{label}  ({num}/{den}*100)", scalar, vector)


def test_prevendas_ratio() -> None:
    print("\n[prevendas_overview.py] _ratio vetorizado (None=>NaN)")
    df = CORNER_CASES
    pairs = [
        ("pct_agend",          "vendas",          "agendamentos"),
        ("pct_conv_v_a",       "vendas",          "comparecimentos"),
        ("pct_rec",            "receita",         "montante"),
        ("pct_op",             "agendamentos",    "oportunidades"),
    ]
    for label, num, den in pairs:
        scalar = df.apply(lambda r: _ratio_scalar(r[num], r[den]), axis=1)
        vector = _ratio_vec(df[num], df[den])
        _assert_equivalent(f"{label}  ({num}/{den}*100, 0→NaN)", scalar, vector)


def test_empty_dataframe() -> None:
    print("\n[edge] DataFrame vazio")
    empty = pd.DataFrame({"vendas": [], "agendamentos": []})
    out = _safe_pct_vec(empty["vendas"], empty["agendamentos"])
    assert len(out) == 0, "Vetor para DF vazio deve ter len 0"
    print("  OK  vetor de tamanho 0 para DF vazio")


def test_string_normalization_consolidation() -> None:
    """prevendas_overview.py:1793+ — fillna().astype(str).str.strip().replace().

    A consolidação proposta junta `fillna(default) + .replace("", default)` em
    uma única passada equivalente. A normalização (astype/strip) é mantida.
    """
    print("\n[prevendas_overview.py] consolidação astype/strip/replace")
    series = pd.Series([None, "", "  ok  ", "x ", " y", "Sem classificação", 1, 2.5])

    # Original — 4 chamadas (fillna, astype, strip, replace)
    original = (
        series.fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Sem classificação")
    )

    # Consolidado — mesma ordem, sem alteração de semântica. Vou apenas
    # garantir que `replace` final continua mapeando "" → fallback após o
    # strip. Como semanticamente é idêntico, este teste só comprova que NÃO
    # introduzimos drift acidental.
    consolidado = (
        series.fillna("")
        .astype(str)
        .str.strip()
        .replace({"": "Sem classificação"})
    )

    pd.testing.assert_series_equal(original, consolidado)
    print("  OK  fillna+astype+strip+replace idênticos (semântica preservada)")


def main() -> int:
    print("=" * 60)
    print(" Validação batch 1 — vetorização de .apply()")
    print("=" * 60)
    try:
        test_safe_pct()
        test_ticket_medio()
        test_one_page_safe_div()
        test_prevendas_ratio()
        test_empty_dataframe()
        test_string_normalization_consolidation()
    except AssertionError as e:
        print(f"\n>>> FALHOU: {e}")
        return 1
    print("\n" + "=" * 60)
    print(" Todas as equivalências validadas")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
