"""Mix canônico de ganhos — mesma regra do card Ganhos (Time de Vendas).

Universo:
  stage IN ('Ganho', 'Fechado Ganho')
  data_hora_compra no período
  tipo_venda nas naturezas abaixo (mutuamente exclusivas)

Use `sql_tipo_venda_ganho(alias)` nas queries e `is_tipo_venda_ganho`
em pandas. Não crie um segundo mapeamento paralelo.
"""
from __future__ import annotations

import pandas as pd

TIPO_VENDA_GANHO_EXACT: tuple[str, ...] = (
    "Novo cliente",
    "Ascensão",
    "Renovação",
    "Renovação antecipada",
    "Indicação",
    "Upgrade",
    "Novo cliente EVENTO",
)

SQL_STAGE_GANHO = "stage IN ('Ganho', 'Fechado Ganho')"


def sql_tipo_venda_ganho(alias: str = "") -> str:
    """Predicado SQL do mix. `alias` vazio, `d` ou `d.`."""
    if not alias:
        col = "tipo_venda"
    elif alias.endswith("."):
        col = f"{alias}tipo_venda"
    else:
        col = f"{alias}.tipo_venda"
    exact = ", ".join(f"'{v}'" for v in TIPO_VENDA_GANHO_EXACT)
    return f"({col} IN ({exact}) OR {col} LIKE 'Ingresso%')"


def is_tipo_venda_ganho(serie: pd.Series) -> pd.Series:
    """Máscara pandas equivalente ao predicado SQL do mix."""
    txt = serie.fillna("").astype(str)
    return txt.isin(TIPO_VENDA_GANHO_EXACT) | txt.str.startswith("Ingresso")
