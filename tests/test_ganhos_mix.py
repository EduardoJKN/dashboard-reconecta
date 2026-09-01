"""Mix canônico de ganhos — predicado compartilhado Marketing / Pré-vendas."""
from __future__ import annotations

import unittest

import pandas as pd

from src.ganhos_mix import is_tipo_venda_ganho, sql_tipo_venda_ganho
from src.marketing_transforms import funil_estagios_oficial, visao_geral_kpis


class TestGanhosMix(unittest.TestCase):
    def test_predicado_sql_inclui_renovacao_antecipada_e_ingresso(self):
        sql = sql_tipo_venda_ganho("d")
        self.assertIn("'Novo cliente'", sql)
        self.assertIn("'Renovação antecipada'", sql)
        self.assertIn("'Novo cliente EVENTO'", sql)
        self.assertIn("LIKE 'Ingresso%'", sql)
        self.assertIn("d.tipo_venda", sql)

    def test_pandas_nao_trata_total_como_novo_cliente(self):
        s = pd.Series([
            "Novo cliente",
            "Ascensão",
            "Renovação",
            "Renovação antecipada",
            "Upgrade",
            "Novo cliente EVENTO",
            "Ingresso VIP",
            "Outro",
        ])
        mask = is_tipo_venda_ganho(s)
        self.assertEqual(int(mask.sum()), 7)
        self.assertFalse(bool(mask.iloc[-1]))

    def test_funil_marketing_fecha_com_vendas_totais_nao_so_novas(self):
        labels, values = funil_estagios_oficial({
            "investimento": 100,
            "leads": 10,
            "leads_qualificados": 8,
            "agendamentos": 6,
            "comparecimentos": 4,
            "vendas": 90,
            "vendas_novas": 37,
        })
        self.assertEqual(labels[-1], "Vendas")
        self.assertEqual(values[-1], 90)
        self.assertNotEqual(values[-1], 37)

    def test_ticket_marketing_usa_vendas_total(self):
        df = pd.DataFrame([{
            "investimento_total_geral": 100.0,
            "leads_totais": 10,
            "leads_qualificados": 8,
            "leads_mais_12": 3,
            "leads_menos_12": 5,
            "leads_nao_atua": 1,
            "vendas_total_geral": 90,
            "vendas_novas_total_geral": 37,
            "montante_total_geral": 900.0,
            "receita_total_geral": 450.0,
        }])
        k = visao_geral_kpis(df)
        self.assertAlmostEqual(k["ticket_medio"], 10.0)
        self.assertNotEqual(k["vendas_total_geral"], k["vendas_novas_total_geral"])


if __name__ == "__main__":
    unittest.main()
