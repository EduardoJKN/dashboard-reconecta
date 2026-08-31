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
# Listas canônicas (composição Slack · agosto/2026)
# ---------------------------------------------------------------------------
# Notas de matching:
#   - Pré-vendas: nomes em duas palavras (substring contígua) pra evitar
#     falsos positivos. "Laura Garcia" casa "Laura Garcia de Freitas"
#     (Slack: Laura Freitas) e NÃO casa "Laura Silva". "Isabela Lopes"
#     não casa "Isabela Lobato" nem "Isabella Lopes Ribeiro".
#   - Ingrid: no banco/Slack aparece como "Ingrid Lorrayne Carvalho de
#     Morais"; o token "Ingrid Lorrayne" casa a forma curta e a estendida.
#   - Social Seller: Geovanna Souza e Gabriela Matos (Slack).
#   - Letícia Freitas (Letícia Garcia de Freitas) é gestora do setor —
#     NÃO entra na composição. "Laura Garcia" não casa o nome dela.
TIMES_CLOSER: dict[str, list[str]] = {
    "Time Leidianne": ["Hawinne", "Thaís", "Andrezza", "Nathally"],
    "Time Marcelo":   ["Nathan", "Leonardo Melo Patriota", "Leandro Alves",
                       "Camile Silveira", "Henrique Gonçalves"],
    "Time Marcelo Executivas": ["Dayana Moura", "Karine Pacífico"],
}

# Times visuais do pedido operacional (Indicações / controle por time).
# Não substitui TIMES_CLOSER no ranking global — só a aba Indicações.
TIMES_VENDAS_VISUAL: dict[str, list[str]] = {
    "Time da Leidi": ["Hawinne", "Andrezza"],
    "Time do Marcelo": ["Nathan", "Leandro", "Leonardo Melo Patriota"],
    "Time do Marcelo Executivas": ["Karine Pacífico", "Dayana Moura"],
}

TIME_VENDAS_VISUAL_LABELS: list[str] = list(TIMES_VENDAS_VISUAL.keys())
TIME_VENDAS_VISUAL_OUTROS = "Outros / sem time visual"

TIPOS_SDR: dict[str, list[str]] = {
    "Pré-vendas":    ["Laura Garcia", "Isabela Lopes", "Mayana Silva",
                      "Ingrid Lorrayne"],
    "Social Seller": ["Geovanna Souza", "Gabriela Matos"],
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
    """Retorna o time do closer (`Time Leidianne` / `Time Marcelo` /
    `Time Marcelo Executivas`), `Sem Closer` quando o input é o
    placeholder do SQL, ou `Closer não classificado` quando o nome não
    bate em nenhuma lista."""
    if isinstance(name, str) and name.strip() == SEM_CLOSER_LABEL:
        return SEM_CLOSER_LABEL
    return _classify(name, TIMES_CLOSER, CLOSER_UNKNOWN_LABEL)


def classify_time_visual(name) -> str:
    """Time visual da aba Indicações (3 times do pedido operacional)."""
    if isinstance(name, str) and name.strip() in (SEM_CLOSER_LABEL, ""):
        return TIME_VENDAS_VISUAL_OUTROS
    return _classify(name, TIMES_VENDAS_VISUAL, TIME_VENDAS_VISUAL_OUTROS)


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
