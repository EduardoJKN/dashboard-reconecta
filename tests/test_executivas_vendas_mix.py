"""Alinhamento novos × vendas da view (Ganho sem data_hora_compra)."""
from __future__ import annotations

import pandas as pd

from src.transforms import (
    executivas_alinhar_novos_com_vendas,
    executivas_ranking,
    executivas_recalcular_vendas_mix,
)


def test_alinhar_novos_usa_vendas_quando_maior():
    df = pd.DataFrame(
        {
            "executiva": ["Leandro Alves"],
            "novos": [13],
            "vendas": [14],
            "ascensoes": [0],
            "renovacoes": [0],
            "indicacoes": [0],
        }
    )
    out = executivas_alinhar_novos_com_vendas(df)
    assert int(out.loc[0, "novos"]) == 14
    assert int(out.loc[0, "vendas"]) == 14  # coluna view ainda intacta


def test_alinhar_novos_nao_reduz_quando_novos_ja_maior():
    df = pd.DataFrame({"novos": [5], "vendas": [3]})
    out = executivas_alinhar_novos_com_vendas(df)
    assert int(out.loc[0, "novos"]) == 5


def test_mix_recalculado_conta_venda_sem_data_compra():
    """Caso Leandro: view vendas=14, trat novos=13 → mix deve ser 14."""
    df = pd.DataFrame(
        {
            "novos": [13],
            "vendas": [14],
            "ascensoes": [0],
            "renovacoes": [0],
            "indicacoes": [0],
        }
    )
    out = executivas_recalcular_vendas_mix(df)
    assert int(out.loc[0, "novos"]) == 14
    assert int(out.loc[0, "vendas"]) == 14


def test_mix_preserva_renovacoes_e_demais():
    df = pd.DataFrame(
        {
            "novos": [6],
            "vendas": [6],
            "ascensoes": [0],
            "renovacoes": [2],
            "indicacoes": [0],
        }
    )
    out = executivas_recalcular_vendas_mix(df)
    assert int(out.loc[0, "vendas"]) == 8
    assert int(out.loc[0, "novos"]) == 6


def test_ranking_top_closers_leandro_14():
    df = pd.DataFrame(
        {
            "executiva": ["Leandro Alves"] * 2,
            "data_ref": pd.to_datetime(["2026-07-02", "2026-07-08"]),
            "oportunidades": [4, 5],
            "agendamentos": [4, 6],
            "comparecimentos": [2, 5],
            "vendas": [2, 2],  # 02/07: 2 na view (1 sem data_hora_compra)
            "novos": [1, 2],
            "ascensoes": [0, 0],
            "renovacoes": [0, 0],
            "indicacoes": [0, 0],
            "montante": [0, 0],
            "receita": [0, 0],
            "perdidos": [0, 0],
            "cancelados": [0, 0],
        }
    )
    ranking = executivas_ranking(df)
    row = ranking.loc[ranking["executiva"] == "Leandro Alves"].iloc[0]
    assert int(row["novos"]) == 4  # max por linha: 2+2
    assert int(row["vendas"]) == 4
