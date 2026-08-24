"""Mix canônico de ganhos — categorias mutuamente exclusivas.

A coluna `vendas` da view BI é o total de ganhos (todas as naturezas de
`tipo_venda`). `novos` é só Novo cliente. Copiar `vendas` para `novos`
e depois somar o mix provoca dupla contagem (ex.: 90 + 53 = 143).
"""
from __future__ import annotations

import unittest

import pandas as pd

from src.transforms import (
    executivas_kpis,
    executivas_ranking,
    executivas_recalcular_vendas_mix,
    format_vendas_mix_hint_from_kpis,
    vendas_mix_from_kpis,
    visao_geral_kpis,
)

# Fixture equivalente à conferência em zoho_deals (01–24/08/2026):
#   37 Novo cliente
#   14 Ascensão
#    3 Renovação + 2 Renovação antecipada  → coluna `renovacoes` = 5
#   25 Upgrade
#    9 Novo cliente EVENTO
# A view já agrega Renovação + Renovação antecipada em `renovacoes`.
# `vendas` da view = total de ganhos (90), NÃO "só novos".
_GANHOS_AGO2026 = {
    "novos": 37,
    "ascensoes": 14,
    "renovacoes": 5,
    "indicacoes": 0,
    "upgrades": 25,
    "eventos": 9,
    "ingressos": 0,
}


def _df_ganhos_view(*, vendas_view: int = 90) -> pd.DataFrame:
    """Uma linha no formato da view: mix correto + `vendas` = total ganhos."""
    return pd.DataFrame(
        {
            "data_ref": pd.to_datetime(["2026-08-01"]),
            "executiva": ["Closer A"],
            "receita": [0],
            "montante": [0],
            "vendas": [vendas_view],
            "perdidos": [0],
            "cancelados": [0],
            "oportunidades": [0],
            "agendamentos": [0],
            "comparecimentos": [0],
            **{col: [val] for col, val in _GANHOS_AGO2026.items()},
        }
    )


class TestExecutivasVendasMix(unittest.TestCase):
    def test_novos_nao_recebe_total_de_ganhos_da_view(self):
        """Regressão: novos = vendas_view (90) inflava o card para 143."""
        out = executivas_recalcular_vendas_mix(_df_ganhos_view(vendas_view=90))
        self.assertEqual(int(out.loc[0, "novos"]), 37)
        self.assertNotEqual(int(out.loc[0, "novos"]), 90)
        self.assertEqual(int(out.loc[0, "vendas"]), 90)

    def test_mix_recalculado_fecha_com_total_sem_dupla_contagem(self):
        out = executivas_recalcular_vendas_mix(_df_ganhos_view())
        self.assertEqual(int(out.loc[0, "novos"]), 37)
        self.assertEqual(int(out.loc[0, "ascensoes"]), 14)
        self.assertEqual(int(out.loc[0, "renovacoes"]), 5)
        self.assertEqual(int(out.loc[0, "indicacoes"]), 0)
        self.assertEqual(int(out.loc[0, "upgrades"]), 25)
        self.assertEqual(int(out.loc[0, "eventos"]), 9)
        self.assertEqual(int(out.loc[0, "ingressos"]), 0)
        self.assertEqual(int(out.loc[0, "vendas"]), 90)
        self.assertNotEqual(int(out.loc[0, "vendas"]), 143)

    def test_visao_geral_kpis_nao_usa_novos_igual_total_ganhos(self):
        k = visao_geral_kpis(_df_ganhos_view(), pd.DataFrame())
        self.assertEqual(int(k["novos"]), 37)
        self.assertEqual(int(k["ascensoes"]), 14)
        self.assertEqual(int(k["renovacoes"]), 5)
        self.assertEqual(int(k["indicacoes"]), 0)
        self.assertEqual(int(k["upgrades"]), 25)
        self.assertEqual(int(k["eventos"]), 9)
        self.assertEqual(int(k["ingressos"]), 0)
        self.assertEqual(int(k["ganhos"]), 90)
        self.assertEqual(int(k["vendas"]), 90)
        self.assertNotEqual(int(k["novos"]), int(k["ganhos"]))
        self.assertNotEqual(int(k["ganhos"]), 143)
        self.assertEqual(int(vendas_mix_from_kpis(k)), 90)

    def test_executivas_kpis_mesmo_mix_do_card_ganhos(self):
        k = executivas_kpis(_df_ganhos_view())
        self.assertEqual(int(k["novos"]), 37)
        self.assertEqual(int(k["ganhos"]), 90)
        self.assertEqual(int(k["vendas"]), 90)
        self.assertNotEqual(int(k["novos"]), int(k["ganhos"]))

    def test_hint_do_card_ganhos_usa_novos_nao_o_total(self):
        k = visao_geral_kpis(_df_ganhos_view(), pd.DataFrame())
        hint = format_vendas_mix_hint_from_kpis(k)
        self.assertEqual(
            hint,
            "Nov. 37 · Asc. 14 · Ren. 5 · Ind. 0 · Upg. 25 · Evt. 9 · Ing. 0",
        )
        self.assertNotIn("Nov. 90", hint)

    def test_mix_preserva_categorias_quando_vendas_view_igual_novos(self):
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
        self.assertEqual(int(out.loc[0, "vendas"]), 8)
        self.assertEqual(int(out.loc[0, "novos"]), 6)

    def test_ranking_nao_infla_novos_com_total_da_view(self):
        """Closer com mix misto: vendas da view = total do dia, não 'só novos'."""
        df = pd.DataFrame(
            {
                "executiva": ["Closer A", "Closer A"],
                "data_ref": pd.to_datetime(["2026-08-02", "2026-08-08"]),
                "oportunidades": [4, 5],
                "agendamentos": [4, 6],
                "comparecimentos": [2, 5],
                "vendas": [3, 4],
                "novos": [1, 2],
                "ascensoes": [1, 0],
                "renovacoes": [0, 1],
                "indicacoes": [0, 0],
                "upgrades": [1, 1],
                "eventos": [0, 0],
                "ingressos": [0, 0],
                "montante": [0, 0],
                "receita": [0, 0],
                "perdidos": [0, 0],
                "cancelados": [0, 0],
            }
        )
        ranking = executivas_ranking(df)
        row = ranking.loc[ranking["executiva"] == "Closer A"].iloc[0]
        self.assertEqual(int(row["novos"]), 3)
        self.assertEqual(int(row["ascensoes"]), 1)
        self.assertEqual(int(row["renovacoes"]), 1)
        self.assertEqual(int(row["upgrades"]), 2)
        self.assertEqual(int(row["vendas"]), 7)
        self.assertNotEqual(int(row["novos"]), int(row["vendas"]))


if __name__ == "__main__":
    unittest.main()
