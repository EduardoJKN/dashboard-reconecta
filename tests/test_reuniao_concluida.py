"""Testes unitários da regra oficial de reunião concluída / comparecimento."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.reuniao_concluida import (
    count_reunioes_concluidas,
    hoje_brasil,
    is_status_reuniao_concluida,
    mask_reuniao_concluida,
    sql_status_reuniao_concluida,
)
from src.transforms import comparecimento_ajustado_aplicar_flags


def test_status_aceita_variantes_normais_e_encoding():
    assert is_status_reuniao_concluida("Concluída")
    assert is_status_reuniao_concluida("Concluído")
    assert is_status_reuniao_concluida("concluida")
    assert is_status_reuniao_concluida("  CONCLUIDO  ")
    # Encoding corrompido — começa com conclu
    assert is_status_reuniao_concluida("Conclu" + chr(0xFFFD) + "da")
    assert is_status_reuniao_concluida("Conclu\xda")  # starts with conclu
    assert not is_status_reuniao_concluida("Agendada")
    assert not is_status_reuniao_concluida("Cancelada")
    assert not is_status_reuniao_concluida("Vencida")
    assert not is_status_reuniao_concluida("Realizada")
    assert not is_status_reuniao_concluida(None)
    assert not is_status_reuniao_concluida("")


def test_sql_fragment_usa_like_conclu():
    frag = sql_status_reuniao_concluida("a.")
    assert frag == "TRIM(LOWER(COALESCE(a.status_reuniao, ''))) LIKE 'conclu%'"
    assert "IN (" not in frag


def test_bloqueia_reuniao_futura_mesmo_com_status_concluida():
    hoje = date(2026, 8, 10)
    df = pd.DataFrame(
        {
            "activity_id": ["1", "2", "3", "4"],
            "activity_type": ["Consulta", "Consulta", "Indicação", "Consulta"],
            "status_reuniao": [
                "Concluída",
                "concluido",
                "Concluído",
                "Conclu" + chr(0xFFFD) + "da",
            ],
            "start_datetime": [
                datetime(2026, 8, 10, 9, 0),
                datetime(2026, 8, 11, 9, 0),  # futuro
                datetime(2026, 8, 7, 14, 0),
                datetime(2026, 8, 9, 10, 0),
            ],
        }
    )
    mask = mask_reuniao_concluida(
        df, data_ini=date(2026, 8, 1), data_fim=date(2026, 8, 31), hoje=hoje,
    )
    assert mask.tolist() == [True, False, True, True]
    assert count_reunioes_concluidas(
        df, data_ini=date(2026, 8, 1), data_fim=date(2026, 8, 31), hoje=hoje,
    ) == 3


def test_fim_futuro_nao_aumenta_comparecimentos_do_dia():
    hoje = date(2026, 8, 10)
    df = pd.DataFrame(
        {
            "activity_id": ["a", "b", "c"],
            "activity_type": ["Consulta", "Consulta", "Consulta"],
            "status_reuniao": ["Concluída", "Concluída", "Concluída"],
            "start_datetime": [
                datetime(2026, 8, 10, 10, 0),
                datetime(2026, 8, 15, 10, 0),
                datetime(2026, 8, 10, 16, 0),
            ],
        }
    )
    n_dia = count_reunioes_concluidas(df, data_ini=hoje, data_fim=hoje, hoje=hoje)
    n_mes = count_reunioes_concluidas(
        df, data_ini=hoje, data_fim=date(2026, 8, 31), hoje=hoje,
    )
    assert n_dia == 2
    assert n_mes == 2


def test_flag_zoho_oficial_em_comparecimento_ajustado():
    agora = pd.Timestamp(datetime(2026, 8, 10, 12, 0))
    df = pd.DataFrame(
        {
            "activity_id": ["1", "2", "3", "4"],
            "activity_type": ["Consulta", "Consulta", "Consulta", "Consulta"],
            "status_reuniao": [
                "Concluída",
                "Agendada",
                "concluida",
                "Conclu" + chr(0xFFFD) + "da",
            ],
            "start_datetime": [
                datetime(2026, 8, 10, 9, 0),
                datetime(2026, 8, 9, 9, 0),
                datetime(2026, 8, 20, 9, 0),  # futuro
                datetime(2026, 8, 8, 9, 0),
            ],
            "end_datetime": [
                datetime(2026, 8, 10, 10, 0),
                datetime(2026, 8, 9, 10, 0),
                datetime(2026, 8, 20, 10, 0),
                datetime(2026, 8, 8, 10, 0),
            ],
            "deal_stage": ["", "", "", ""],
        }
    )
    out = comparecimento_ajustado_aplicar_flags(df, agora_brt=agora)
    assert out["flag_comparecimento_zoho"].tolist() == [True, False, False, True]


def test_hoje_brasil_timezone():
    ts = datetime(2026, 8, 10, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert hoje_brasil(ts) == date(2026, 8, 9)
