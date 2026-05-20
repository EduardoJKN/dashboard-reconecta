"""Classificação canônica de SDRs e Closers — listas fornecidas pela operação.

Match é case + accent-insensitive:
- Entradas com múltiplas palavras (default agora) batem como **substring
  contígua** no nome alvo. Permite ser preciso quando há nomes parecidos
  no banco — ex.: `"Laura Garcia"` casa `"Laura Garcia de Freitas"` mas
  NÃO casa `"Laura Silva"`.
- Entradas de uma palavra batem se o **primeiro nome** do alvo for
  exatamente igual.

Categorias especiais reservadas:
- `"Sem SDR"` e `"Sem Closer"` são placeholders devolvidos pelo SQL para
  deals sem `sdr_ss` / `executiva_vendas`. Preservadas como categoria
  própria — NÃO classificadas como Pré-vendas, Social Seller nem time
  de closer.
- Nomes que não batem em nenhuma lista canônica viram
  `"SDR não classificado"` ou `"Closer não classificado"`.
"""
from __future__ import annotations

import unicodedata

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
# Placeholders devolvidos pelo SQL (compatibilidade_sdr_closer.sql) quando
# o deal não tem SDR / Closer atribuído. Não classificar.
SEM_SDR_LABEL = "Sem SDR"
SEM_CLOSER_LABEL = "Sem Closer"

# Labels para nomes que não batem em nenhuma lista canônica.
SDR_UNKNOWN_LABEL = "SDR não classificado"
CLOSER_UNKNOWN_LABEL = "Closer não classificado"

# ---------------------------------------------------------------------------
# Listas canônicas (composição validada com a operação · maio/2026)
# ---------------------------------------------------------------------------
# Notas de matching:
#   - Pré-vendas: nomes em duas palavras (substring contígua) pra evitar
#     falsos positivos. "Laura Garcia" não casa "Laura Silva"; "Isabela
#     Lopes" não casa "Isabela Lobato" nem "Isabella Lopes Ribeiro";
#     "Camilla Lyra" não casa "Camila Lyra" (1 vs 2 'l').
#   - Ingrid: no banco aparece como "Ingrid Lorrayne" (nome curto).
#     "Ingrid Lorrayne" também casa "Ingrid Lorrayne Carvalho de Morais"
#     (substring) caso a versão estendida apareça depois.
#   - Social Seller (singular, alinhado com a operação): "Estefany
#     Nascimento" não casa "Estefany Bastos" (versão antiga, fora da
#     composição); "Isabella Esbell" não casa "Isabella Lopes Ribeiro".
#   - Letícia Garcia de Freitas (1 venda em maio/2026) NÃO está na
#     composição → vira "SDR não classificado". "Laura Garcia" não casa
#     "Letícia Garcia de Freitas".
TIMES_CLOSER: dict[str, list[str]] = {
    "Time Leidianne": ["Hawinne", "Thaís", "Andrezza", "Nathally"],
    "Time Marcelo":   ["Nathan", "Leonardo Melo Patriota", "Leandro Alves",
                       "Camile Silveira", "Henrique Gonçalves"],
}

TIPOS_SDR: dict[str, list[str]] = {
    "Pré-vendas":    ["Laura Garcia", "Isabela Lopes", "Mayana Silva",
                      "Camilla Lyra", "Ingrid Lorrayne"],
    "Social Seller": ["Geovanna Souza", "Estefany Nascimento",
                      "Isabella Esbell"],
}

CLOSER_TIME_LABELS: list[str] = list(TIMES_CLOSER.keys()) + [CLOSER_UNKNOWN_LABEL]
SDR_TIPO_LABELS:    list[str] = list(TIPOS_SDR.keys())   + [SDR_UNKNOWN_LABEL]


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


def _classify(name, mapping: dict[str, list[str]], unknown_label: str) -> str:
    for label, members in mapping.items():
        for m in members:
            if _matches(m, name):
                return label
    return unknown_label


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def classify_closer(name) -> str:
    """Retorna o time do closer (`Time Leidianne` / `Time Marcelo`),
    `Sem Closer` quando o input é o placeholder do SQL, ou
    `Closer não classificado` quando o nome não bate em nenhuma lista."""
    if isinstance(name, str) and name.strip() == SEM_CLOSER_LABEL:
        return SEM_CLOSER_LABEL
    return _classify(name, TIMES_CLOSER, CLOSER_UNKNOWN_LABEL)


def classify_sdr(name) -> str:
    """Retorna o tipo do SDR (`Pré-vendas` / `Social Seller`),
    `Sem SDR` quando o input é o placeholder do SQL, ou
    `SDR não classificado` quando o nome não bate em nenhuma lista."""
    if isinstance(name, str) and name.strip() == SEM_SDR_LABEL:
        return SEM_SDR_LABEL
    return _classify(name, TIPOS_SDR, SDR_UNKNOWN_LABEL)


def is_known_closer(name) -> bool:
    """True quando o nome é um closer mapeado em TIMES_CLOSER. Não conta
    `Sem Closer` (placeholder) nem `Closer não classificado`."""
    result = classify_closer(name)
    return result not in (CLOSER_UNKNOWN_LABEL, SEM_CLOSER_LABEL)


def is_known_sdr(name) -> bool:
    """True quando o nome é um SDR mapeado em TIPOS_SDR. Não conta
    `Sem SDR` (placeholder) nem `SDR não classificado`."""
    result = classify_sdr(name)
    return result not in (SDR_UNKNOWN_LABEL, SEM_SDR_LABEL)
