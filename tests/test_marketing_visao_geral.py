"""Testes unitários — Visão Geral Marketing (transforms e regras de filtro).

Não dependem do banco de produção. Valores de referência abr/2026 documentados
em `mkt_visao_geral_periodo.sql`."""
from __future__ import annotations

import unittest

import pandas as pd

from src.marketing_transforms import (
    CANAIS_VISIVEIS_OVERVIEW,
    filtro_canal_ativo,
    visao_geral_diario,
    visao_geral_kpis,
    visao_geral_kpis_canal,
)

# Referência abr/2026 — mkt_visao_geral_periodo.sql (1 linha agregada)
REF_PERIODO = {
    "investimento_total_geral": 102_199.89,
    "leads_totais": 854,
    "leads_qualificados": 701,
    "leads_mais_12": 259,
    "leads_menos_12": 443,
    "leads_nao_atua": 118,
    "vendas_total_geral": 57,
    "vendas_novas_total_geral": 50,
    "montante_total_geral": 1_216_572.0,
    "receita_total_geral": 774_182.0,
}

# Referência por canal — mkt_visao_geral_kpis_canal.sql (trecho Meta)
REF_CANAL_META = {
    "canal": "Meta",
    "investimento_total_geral": 102_185.30,
    "leads_totais": 690,
    "leads_qualificados": 578,
    "leads_mais_12": 259,
    "leads_menos_12": 442,
    "leads_nao_atua": 0,
    "vendas_total_geral": 27,
    "vendas_novas_total_geral": 25,
    "montante_total_geral": 534_000.0,
    "receita_total_geral": 385_500.0,
}


def _periodo_df(row: dict | None = None) -> pd.DataFrame:
    data = dict(REF_PERIODO)
    if row:
        data.update(row)
    return pd.DataFrame([data])


def _canal_df(rows: list[dict] | None = None) -> pd.DataFrame:
    if rows is None:
        rows = [REF_CANAL_META, {
            "canal": "Organico",
            "investimento_total_geral": 0.0,
            "leads_totais": 133,
            "leads_qualificados": 101,
            "leads_mais_12": 0,
            "leads_menos_12": 0,
            "leads_nao_atua": 0,
            "vendas_total_geral": 9,
            "vendas_novas_total_geral": 9,
            "montante_total_geral": 241_000.0,
            "receita_total_geral": 132_300.0,
        }]
    return pd.DataFrame(rows)


class TestFiltroCanalAtivo(unittest.TestCase):
    def test_vazio_e_todos_representam_total_geral(self):
        self.assertFalse(filtro_canal_ativo([]))
        self.assertFalse(filtro_canal_ativo(list(CANAIS_VISIVEIS_OVERVIEW)))

    def test_um_canal_ativa_filtro(self):
        self.assertTrue(filtro_canal_ativo(["Meta"]))

    def test_multiplos_canais_ativa_filtro(self):
        self.assertTrue(filtro_canal_ativo(["Meta", "Google"]))

    def test_canal_sem_dados_continua_restritivo(self):
        self.assertTrue(filtro_canal_ativo(["TikTok"]))


class TestVisaoGeralKpisPeriodo(unittest.TestCase):
    def test_referencia_abril_2026(self):
        k = visao_geral_kpis(_periodo_df())
        self.assertEqual(k["leads_totais"], 854)
        self.assertEqual(k["leads_qualificados"], 701)
        self.assertEqual(k["leads_mais_12"], 259)
        self.assertEqual(k["leads_menos_12"], 443)
        self.assertEqual(k["leads_nao_atua"], 118)
        self.assertAlmostEqual(k["investimento_total_geral"], 102_199.89, places=2)

    def test_roas_cpl_taxa_recalculados_sobre_agregado(self):
        k = visao_geral_kpis(_periodo_df())
        self.assertAlmostEqual(
            k["roas_total_geral"],
            REF_PERIODO["montante_total_geral"] / REF_PERIODO["investimento_total_geral"],
            places=4,
        )
        self.assertAlmostEqual(
            k["cpl"],
            REF_PERIODO["investimento_total_geral"] / REF_PERIODO["leads_totais"],
            places=4,
        )
        self.assertAlmostEqual(
            k["cpl_qualificado"],
            REF_PERIODO["investimento_total_geral"] / REF_PERIODO["leads_qualificados"],
            places=4,
        )
        self.assertAlmostEqual(
            k["taxa_qualificacao"],
            REF_PERIODO["leads_qualificados"] / REF_PERIODO["leads_totais"] * 100,
            places=4,
        )

    def test_sobreposicao_mais_12_menos_12_permitida(self):
        """Buckets +12 e -12 podem coexistir — soma dos buckets pode exceder qualificados."""
        k = visao_geral_kpis(_periodo_df())
        self.assertGreater(
            k["leads_mais_12"] + k["leads_menos_12"],
            k["leads_qualificados"],
        )

    def test_dataframe_vazio_retorna_zeros(self):
        k = visao_geral_kpis(pd.DataFrame())
        self.assertEqual(k["leads_totais"], 0)
        self.assertEqual(k["roas_total_geral"], 0.0)


class TestVisaoGeralKpisCanal(unittest.TestCase):
    def test_um_canal_meta(self):
        k = visao_geral_kpis_canal(_canal_df(), ["Meta"])
        self.assertEqual(k["leads_totais"], 690)
        self.assertEqual(k["vendas_novas_total_geral"], 25)
        self.assertAlmostEqual(k["investimento_total_geral"], 102_185.30, places=2)

    def test_multiplos_canais_soma_absolutos_e_recalcula_ratios(self):
        k = visao_geral_kpis_canal(_canal_df(), ["Meta", "Organico"])
        self.assertEqual(k["leads_totais"], 690 + 133)
        invest = 102_185.30
        leads = 823
        self.assertAlmostEqual(k["cpl"], invest / leads, places=4)

    def test_canal_inexistente_retorna_zeros(self):
        k = visao_geral_kpis_canal(_canal_df(), ["TikTok"])
        self.assertEqual(k["leads_totais"], 0)
        self.assertEqual(k["investimento_total_geral"], 0.0)


class TestVisaoGeralDiario(unittest.TestCase):
    def test_projecao_colunas_tendencia(self):
        df = pd.DataFrame([
            {
                "data_ref": "2026-04-01",
                "investimento_total_geral": 100.0,
                "leads_totais": 10,
                "leads_qualificados": 8,
                "leads_mais_12": 3,
                "leads_menos_12": 5,
            },
            {
                "data_ref": "2026-04-02",
                "investimento_total_geral": 200.0,
                "leads_totais": 12,
                "leads_qualificados": 9,
                "leads_mais_12": 4,
                "leads_menos_12": 4,
            },
        ])
        out = visao_geral_diario(df)
        self.assertEqual(len(out), 2)
        self.assertEqual(list(out.columns), [
            "data_ref", "investimento_total_geral",
            "leads_totais", "leads_qualificados",
            "leads_mais_12", "leads_menos_12",
        ])
        # Soma diária NÃO deve ser usada como proxy de dedupe no período
        self.assertNotEqual(
            int(out["leads_totais"].sum()),
            REF_PERIODO["leads_totais"],
        )


if __name__ == "__main__":
    unittest.main()
