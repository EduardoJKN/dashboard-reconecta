# -*- coding: utf-8 -*-
"""Período efetivo da página Funil da Reconecta.

Quando o preset global é "Mês atual" e a opção "Mês atual até hoje" está
marcada, o período efetivo da página passa a ser do dia 1 do mês até hoje
(inclusivo), alinhado a um recorte manual equivalente.
"""
from __future__ import annotations

from datetime import date

from src.funil_meta_store import first_day_of_month

FUNIL_MES_ATUAL_ATE_HOJE_KEY = "funil_mes_atual_ate_hoje"
MES_ATUAL_PRESET_LABEL = "Mês atual"


def is_mes_atual_preset(preset: str | None) -> bool:
    return (preset or "").strip() == MES_ATUAL_PRESET_LABEL


def resolve_effective_funil_period(
    preset: str | None,
    data_ini: date,
    data_fim: date,
    usar_mes_atual_ate_hoje: bool,
    *,
    hoje: date | None = None,
) -> tuple[date, date, bool]:
    """Resolve o período efetivo usado por Atual, meta, benchmark e export.

    Retorna ``(data_ini_efetiva, data_fim_efetiva, ajuste_aplicado)``.
    O ajuste só vale para o preset ``Mês atual`` com a checkbox ligada.
    """
    hoje = hoje or date.today()
    if is_mes_atual_preset(preset) and usar_mes_atual_ate_hoje:
        return first_day_of_month(hoje), hoje, True
    return data_ini, data_fim, False
