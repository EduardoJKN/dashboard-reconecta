"""Classificação canônica de SDRs e Closers — listas fornecidas pela operação.

Match é case + accent-insensitive:
- Entradas de uma palavra (ex.: "Hawinne") batem se o **primeiro nome** do
  alvo for exatamente igual.
- Entradas com múltiplas palavras (ex.: "Leonardo Melo Patriota") batem se
  a sequência aparecer como **substring contígua** no nome alvo.

Qualquer nome que não bate em nenhuma lista vira `Sem Time Definido`.
"""
from __future__ import annotations

import unicodedata

UNKNOWN_LABEL = "Sem Time Definido"

# ---------------------------------------------------------------------------
# Listas canônicas
# ---------------------------------------------------------------------------
TIMES_CLOSER: dict[str, list[str]] = {
    "Time Leidianne": ["Hawinne", "Thaís", "Andrezza", "Nathally"],
    "Time Marcelo":   ["Nathan", "Leonardo Melo Patriota", "Leandro Alves",
                       "Camile Silveira"],
}

TIPOS_SDR: dict[str, list[str]] = {
    "Pré-vendas":     ["Laura", "Isabela", "Maria Fernanda"],
    "Social Sellers": ["Geovanna", "Estefany"],
}

CLOSER_TIME_LABELS: list[str] = list(TIMES_CLOSER.keys()) + [UNKNOWN_LABEL]
SDR_TIPO_LABELS:    list[str] = list(TIPOS_SDR.keys())   + [UNKNOWN_LABEL]


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------
def _normalize(s) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _matches(entry: str, target: str) -> bool:
    e, t = _normalize(entry), _normalize(target)
    if not e or not t:
        return False
    if " " in e:
        # multi-word: exige substring contígua (ex.: "leonardo melo patriota")
        return e in t
    # single-word: primeiro nome do alvo precisa bater
    primeiro = t.split()[0] if t else ""
    return primeiro == e


def _classify(name, mapping: dict[str, list[str]]) -> str:
    for label, members in mapping.items():
        for m in members:
            if _matches(m, name):
                return label
    return UNKNOWN_LABEL


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def classify_closer(name) -> str:
    """Retorna o time do closer (`Time Leidianne` / `Time Marcelo`) ou
    `Sem Time Definido`."""
    return _classify(name, TIMES_CLOSER)


def classify_sdr(name) -> str:
    """Retorna o tipo do SDR (`Pré-vendas` / `Social Sellers`) ou
    `Sem Time Definido`."""
    return _classify(name, TIPOS_SDR)


def is_known_closer(name) -> bool:
    return classify_closer(name) != UNKNOWN_LABEL


def is_known_sdr(name) -> bool:
    return classify_sdr(name) != UNKNOWN_LABEL
