"""Testes unitarios — Campanhas Marketing (transforms e seletor).

Nao dependem do banco de producao."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from src.marketing_transforms import (
    campanha_funil_kpis,
    campanhas_kpis,
    campanhas_leads_canal_kpis,
    campanhas_tabela_ativas,
    campanhas_tabela_total_row,
    lista_campanhas_funil,
)
from src.transforms import _safe_div

_TODOS = "__todos__"
_VINCULADOS = "__vinculados__"
_SEM_CAMP = "__sem_campanha_identificada__"


def _camp_row(
    norm: str,
    name: str,
    *,
    invest: float = 0.0,
    leads: int = 0,
    apl: int = 0,
    apl12: int = 0,
    apl_menos: int = 0,
    apl_nao: int = 0,
    vendas: int = 0,
    imp: int = 0,
    clk: int = 0,
) -> dict:
    return {
        "campaign_name_norm": norm,
        "campaign_name": name,
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "link_clicks": clk,
        "alcance": 0,
        "leads_totais": leads,
        "leads_qualificados": max(0, leads - 1),
        "leads_mais_12": max(0, leads // 2),
        "leads_menos_12": max(0, leads // 3),
        "leads_nao_atua": 0,
        "agendamentos": 0,
        "comparecimentos": 0,
        "vendas_novas": vendas,
        "aplicacoes": apl,
        "aplicacoes_mais_12": apl12,
        "aplicacoes_menos_12": apl_menos,
        "aplicacoes_nao_atua": apl_nao,
        "aplicacoes_globais": apl,
        "aplicacoes_vinculados": apl,
        "qtd_adids": 1,
        "ctr": _safe_div(clk, imp) * 100 if imp else 0.0,
        "cpc": _safe_div(invest, clk) if clk else 0.0,
    }


def _funil_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _camp_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _leads_canal_diario_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "data_ref": pd.Timestamp("2026-04-01"),
            "canal": "Meta",
            "leads_totais": 60,
            "leads_qualificados": 50,
            "leads_mais_12": 20,
            "leads_menos_12": 30,
            "leads_nao_atua": 0,
        },
        {
            "data_ref": pd.Timestamp("2026-04-02"),
            "canal": "Meta",
            "leads_totais": 40,
            "leads_qualificados": 30,
            "leads_mais_12": 10,
            "leads_menos_12": 20,
            "leads_nao_atua": 0,
        },
    ])


class TestCampanhasKpis(unittest.TestCase):
    def test_media_metrics_from_campanhas_only(self):
        df_camp = _camp_df([
            {
                "data_ref": pd.Timestamp("2026-04-01"),
                "canal": "Meta",
                "campaign_id": "1",
                "campaign_name": "Camp A",
                "objetivo": "Leads",
                "investimento": 1000.0,
                "impressoes": 10000,
                "cliques": 200,
                "alcance": 5000,
            },
            {
                "data_ref": pd.Timestamp("2026-04-02"),
                "canal": "Meta",
                "campaign_id": "1",
                "campaign_name": "Camp A",
                "objetivo": "Leads",
                "investimento": 500.0,
                "impressoes": 5000,
                "cliques": 100,
                "alcance": 2500,
            },
        ])
        k = campanhas_kpis(df_camp, pd.DataFrame(), None)
        self.assertAlmostEqual(k["investimento"], 1500.0)
        self.assertEqual(k["impressoes"], 15000)
        self.assertEqual(k["cliques"], 300)
        self.assertAlmostEqual(k["ctr"], _safe_div(300, 15000) * 100)
        self.assertAlmostEqual(k["cpc"], _safe_div(1500.0, 300))

    def test_leads_override_canal_aware(self):
        df_camp = _camp_df([
            {
                "data_ref": pd.Timestamp("2026-04-01"),
                "canal": "Meta",
                "campaign_id": "1",
                "campaign_name": "Camp A",
                "objetivo": "Leads",
                "investimento": 1000.0,
                "impressoes": 1000,
                "cliques": 100,
                "alcance": 500,
            },
        ])
        k = campanhas_kpis(df_camp, pd.DataFrame(), None)
        kc = campanhas_leads_canal_kpis(_leads_canal_diario_df(), ["Meta"])
        k["leads"] = kc["leads_totais"]
        k["leads_qualificados"] = kc["leads_qualificados"]
        k["cpl"] = _safe_div(k["investimento"], k["leads"])
        k["cpl_qualificado"] = _safe_div(k["investimento"], k["leads_qualificados"])
        total_dias = 30
        k["investimento_dia"] = _safe_div(k["investimento"], total_dias)

        self.assertEqual(k["leads"], 100)
        self.assertEqual(k["leads_qualificados"], 80)
        self.assertAlmostEqual(k["cpl"], 10.0)
        self.assertAlmostEqual(k["cpl_qualificado"], 12.5)
        self.assertAlmostEqual(k["investimento_dia"], 1000.0 / 30)


class TestCampanhasLeadsCanalKpis(unittest.TestCase):
    def test_soma_por_canais_selecionados(self):
        df = pd.concat([
            _leads_canal_diario_df(),
            pd.DataFrame([{
                "data_ref": pd.Timestamp("2026-04-01"),
                "canal": "Google",
                "leads_totais": 5,
                "leads_qualificados": 4,
                "leads_mais_12": 2,
                "leads_menos_12": 2,
                "leads_nao_atua": 0,
            }]),
        ], ignore_index=True)
        k_meta = campanhas_leads_canal_kpis(df, ["Meta"])
        self.assertEqual(k_meta["leads_totais"], 100)
        k_all = campanhas_leads_canal_kpis(df, None)
        self.assertEqual(k_all["leads_totais"], 105)


class TestListaCampanhasFunil(unittest.TestCase):
    def test_opcoes_sinteticas_prepend(self):
        df = _funil_df([
            _camp_row("camp_a", "Camp A", invest=100.0, leads=10, apl=5, vendas=1),
            _camp_row(_SEM_CAMP, "Sem campanha identificada", leads=3, vendas=1),
        ])
        opts = lista_campanhas_funil(df)
        norms = opts["campaign_name_norm"].tolist()
        self.assertEqual(norms[0], _TODOS)
        self.assertEqual(norms[1], _VINCULADOS)
        self.assertIn(_SEM_CAMP, norms)
        self.assertIn("camp_a", norms)

    def test_consolidacao_por_norm(self):
        df = _funil_df([
            _camp_row("camp_a", "Camp A", invest=50.0, leads=5),
            _camp_row("camp_b", "Camp B", invest=150.0, leads=15),
        ])
        opts = lista_campanhas_funil(df, sort_by="investimento")
        indiv = opts[~opts["campaign_name_norm"].isin([_TODOS, _VINCULADOS])]
        self.assertEqual(indiv.iloc[0]["campaign_name_norm"], "camp_b")


class TestCampanhaFunilKpis(unittest.TestCase):
    def test_campanha_individual(self):
        df = _funil_df([
            _camp_row(
                "camp_x", "Camp X",
                invest=200.0, leads=20, apl=10,
                apl12=4, apl_menos=3, apl_nao=1,
                imp=1000, clk=50, vendas=2,
            ),
        ])
        k = campanha_funil_kpis(df, "camp_x")
        self.assertTrue(k["tem_dados"])
        self.assertAlmostEqual(k["investimento"], 200.0)
        self.assertEqual(k["leads_totais"], 20)
        self.assertEqual(k["aplicacoes"], 10)
        self.assertEqual(k["aplicacoes_mais_12"], 4)
        self.assertEqual(k["aplicacoes_menos_12"], 3)
        self.assertEqual(k["aplicacoes_nao_atua"], 1)
        self.assertEqual(k["vendas_novas"], 2)
        cpa = _safe_div(k["investimento"], k["aplicacoes"])
        cpa12 = _safe_div(k["investimento"], k["aplicacoes_mais_12"])
        self.assertAlmostEqual(cpa, 20.0)
        self.assertAlmostEqual(cpa12, 50.0)

    def test_todos_usa_oficiais_quando_disponiveis(self):
        df = _funil_df([
            _camp_row("camp_a", "Camp A", invest=100.0, leads=10, vendas=1),
            _camp_row("camp_b", "Camp B", invest=200.0, leads=20, vendas=2),
        ])
        k = campanha_funil_kpis(
            df, _TODOS,
            leads_totais_oficial=854,
            vendas_novas_oficial=50,
            investimento_oficial=102_199.89,
        )
        self.assertEqual(k["leads_totais"], 854)
        self.assertEqual(k["vendas_novas"], 50)
        self.assertAlmostEqual(k["investimento"], 102_199.89)

    def test_todos_fallback_sem_oficiais(self):
        df = _funil_df([
            _camp_row("camp_a", "Camp A", invest=100.0, leads=10, vendas=1),
            _camp_row("camp_b", "Camp B", invest=200.0, leads=20, vendas=2),
        ])
        k = campanha_funil_kpis(df, _TODOS)
        self.assertEqual(k["leads_totais"], 30)
        self.assertEqual(k["vendas_novas"], 3)
        self.assertAlmostEqual(k["investimento"], 300.0)

    def test_vinculados_exclui_sem_campanha(self):
        df = _funil_df([
            _camp_row("camp_a", "Camp A", invest=100.0, leads=10, vendas=1),
            _camp_row(_SEM_CAMP, "Sem campanha", invest=0.0, leads=5, vendas=1),
        ])
        k_todos = campanha_funil_kpis(df, _TODOS)
        k_vinc = campanha_funil_kpis(df, _VINCULADOS)
        self.assertEqual(k_todos["leads_totais"], 15)
        self.assertEqual(k_vinc["leads_totais"], 10)

    def test_sobreposicao_apl12_apl_menos(self):
        df = _funil_df([
            _camp_row(
                "camp_overlap", "Overlap",
                invest=100.0, leads=10, apl=8,
                apl12=5, apl_menos=4, apl_nao=1,
            ),
        ])
        k = campanha_funil_kpis(df, "camp_overlap")
        self.assertEqual(k["aplicacoes_mais_12"], 5)
        self.assertEqual(k["aplicacoes_menos_12"], 4)
        self.assertGreaterEqual(
            k["aplicacoes_mais_12"] + k["aplicacoes_menos_12"],
            k["aplicacoes"],
        )


class TestCampanhasTabela(unittest.TestCase):
    def _camp_ativas_df(self) -> pd.DataFrame:
        return _camp_df([
            {
                "data_ref": pd.Timestamp("2026-04-01"),
                "canal": "Meta",
                "campaign_id": "id1",
                "campaign_name": "Camp Alpha",
                "objetivo": "Leads",
                "investimento": 500.0,
                "impressoes": 5000,
                "cliques": 100,
                "alcance": 2000,
            },
            {
                "data_ref": pd.Timestamp("2026-04-01"),
                "canal": "Meta",
                "campaign_id": "id2",
                "campaign_name": "Camp Alpha",
                "objetivo": "Leads",
                "investimento": 300.0,
                "impressoes": 3000,
                "cliques": 60,
                "alcance": 1500,
            },
        ])

    def _leads_utm_df(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "campaign_norm": "camp alpha",
            "leads_totais": 25,
            "leads_qualificados": 20,
            "leads_mais_12": 10,
            "leads_menos_12": 10,
        }])

    def test_match_por_campaign_name_norm(self):
        ativas = campanhas_tabela_ativas(
            self._camp_ativas_df(), self._leads_utm_df(),
        )
        self.assertEqual(len(ativas), 2)
        self.assertTrue(all(ativas["leads"] == 25))

    def test_total_row_recalcula_ratios(self):
        ativas = campanhas_tabela_ativas(
            self._camp_ativas_df(), self._leads_utm_df(),
        )
        total = campanhas_tabela_total_row(ativas)
        self.assertEqual(len(total), 1)
        row = total.iloc[0]
        self.assertAlmostEqual(row["investimento"], 800.0)
        self.assertEqual(row["leads"], 25)
        self.assertAlmostEqual(row["ctr"], _safe_div(160, 8000) * 100)
        self.assertAlmostEqual(row["cpc"], _safe_div(800.0, 160))
        self.assertAlmostEqual(row["cpl"], _safe_div(800.0, 25))


class TestResolveVendasNovasOficial(unittest.TestCase):
    def _resolve(self, vendas_count, **kwargs):
        from views.marketing_campaigns import _resolve_vendas_novas_oficial

        defaults = {
            "leads_totais": None,
            "investimento": None,
            "agendamentos": None,
            "comparecimentos": None,
        }
        defaults.update(kwargs)
        return _resolve_vendas_novas_oficial(vendas_count, **defaults)

    def test_falha_consulta_retorna_none(self):
        self.assertIsNone(self._resolve(None))

    def test_periodo_sem_dados_retorna_none(self):
        self.assertIsNone(self._resolve(0))

    def test_zero_com_outras_fontes_retorna_zero(self):
        self.assertEqual(self._resolve(0, leads_totais=10), 0)

    def test_valor_positivo(self):
        self.assertEqual(self._resolve(49, leads_totais=100), 49)


class TestCampanhasOficiaisVendasIntegration(unittest.TestCase):
    def _ctx(self) -> MagicMock:
        ctx = MagicMock()
        ctx.data_ini = date(2026, 4, 1)
        ctx.data_fim = date(2026, 4, 30)
        return ctx

    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._fetch_df")
    def test_todos_usa_nova_fonte_vendas(self, mock_fetch, _mock_st):
        from views.marketing_campaigns import _load_oficiais_todos

        mock_fetch.side_effect = [
            (pd.DataFrame({"x": [1, 2]}), None),
            (pd.DataFrame({"vendas": [49]}), None),
            (pd.DataFrame({"investimento_total": [1000.0]}), None),
            (pd.DataFrame(), None),
        ]
        out = _load_oficiais_todos(self._ctx())
        names = [c.args[0] for c in mock_fetch.call_args_list]
        self.assertIn("mkt_campanhas_vendas_oficiais", names)
        self.assertNotIn("dashboard_executivas", names)
        self.assertEqual(out["vendas_novas_oficial"], 49)
        self.assertEqual(out["leads_totais_oficial"], 2)

    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._fetch_df")
    def test_erro_consulta_mantem_fallback(self, mock_fetch, _mock_st):
        from views.marketing_campaigns import _load_oficiais_todos

        mock_fetch.side_effect = [
            (pd.DataFrame({"x": [1]}), None),
            (pd.DataFrame(), "erro sql"),
            (pd.DataFrame({"investimento_total": [100.0]}), None),
            (pd.DataFrame(), None),
        ]
        out = _load_oficiais_todos(self._ctx())
        self.assertIsNone(out["vendas_novas_oficial"])

    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._fetch_df")
    def test_dataframe_vazio_periodo_sem_dados(self, mock_fetch, _mock_st):
        from views.marketing_campaigns import _load_oficiais_todos

        mock_fetch.side_effect = [
            (pd.DataFrame(), None),
            (pd.DataFrame({"vendas": [0]}), None),
            (pd.DataFrame(), None),
            (pd.DataFrame(), None),
        ]
        out = _load_oficiais_todos(self._ctx())
        self.assertIsNone(out["vendas_novas_oficial"])

    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._fetch_df")
    def test_oficial_substitui_funil_sem_alterar_leads(self, mock_fetch, _mock_st):
        from views.marketing_campaigns import _load_oficiais_todos

        mock_fetch.side_effect = [
            (pd.DataFrame({"x": range(854)}), None),
            (pd.DataFrame({"vendas": [50]}), None),
            (pd.DataFrame({"investimento_total": [102_199.89]}), None),
            (pd.DataFrame(), None),
        ]
        out = _load_oficiais_todos(self._ctx())
        self.assertEqual(out["vendas_novas_oficial"], 50)
        self.assertEqual(out["leads_totais_oficial"], 854)
        self.assertAlmostEqual(out["investimento_oficial"], 102_199.89)

    def test_funil_kpis_outras_metricas_inalteradas_pelo_override_vendas(self):
        df = _funil_df([
            _camp_row("camp_a", "Camp A", invest=100.0, leads=10, vendas=1),
            _camp_row("camp_b", "Camp B", invest=200.0, leads=20, vendas=2),
        ])
        k_base = campanha_funil_kpis(df, _TODOS)
        k_off = campanha_funil_kpis(
            df, _TODOS,
            leads_totais_oficial=854,
            vendas_novas_oficial=50,
            investimento_oficial=102_199.89,
        )
        for key in (
            "aplicacoes", "aplicacoes_mais_12", "aplicacoes_menos_12",
            "impressoes", "cliques", "leads_mais_12", "leads_menos_12",
        ):
            self.assertEqual(k_base[key], k_off[key], key)
        self.assertEqual(k_off["vendas_novas"], 50)
        self.assertNotEqual(k_base["vendas_novas"], k_off["vendas_novas"])

    @patch("views.marketing_campaigns.perf_timed_block")
    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._load_oficiais_todos")
    def test_vinculados_nao_carrega_oficiais(
        self, mock_load, _mock_st, mock_block,
    ):
        from views.marketing_campaigns import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        loader = _oficiais_loader_factory(self._ctx())
        self.assertEqual(loader("__vinculados__"), {})
        mock_load.assert_not_called()

    @patch("views.marketing_campaigns.perf_timed_block")
    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._load_oficiais_todos")
    def test_sem_campanha_nao_carrega_oficiais(
        self, mock_load, _mock_st, mock_block,
    ):
        from views.marketing_campaigns import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        loader = _oficiais_loader_factory(self._ctx())
        self.assertEqual(loader("__sem_campanha_identificada__"), {})
        mock_load.assert_not_called()

    @patch("views.marketing_campaigns.perf_timed_block")
    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._load_oficiais_todos")
    def test_campanha_individual_nao_carrega_oficiais(
        self, mock_load, _mock_st, mock_block,
    ):
        from views.marketing_campaigns import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        loader = _oficiais_loader_factory(self._ctx())
        self.assertEqual(loader("camp_alpha"), {})
        mock_load.assert_not_called()

    @patch("src.repositories.get_executivas")
    @patch("views.marketing_campaigns.get_prevendas_overview_diario")
    @patch("views.marketing_campaigns.get_investimento_diario")
    @patch("views.marketing_campaigns.get_leads_visao_geral")
    @patch("views.marketing_campaigns.get_mkt_campanhas_vendas_oficiais")
    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns.safe_run")
    def test_get_executivas_nao_chamado_pelo_loader(
        self,
        mock_safe,
        _mock_st,
        mock_vendas,
        mock_leads,
        mock_inv,
        mock_prev,
        mock_exec,
    ):
        from views.marketing_campaigns import _load_oficiais_todos

        mock_leads.return_value = pd.DataFrame({"x": [1]})
        mock_vendas.return_value = pd.DataFrame({"vendas": [49]})
        mock_inv.return_value = pd.DataFrame({"investimento_total": [100.0]})
        mock_prev.return_value = pd.DataFrame()
        mock_exec.return_value = pd.DataFrame({"vendas": [999]})

        def _safe(fn, **_kw):
            return fn()

        mock_safe.side_effect = _safe
        _load_oficiais_todos(self._ctx())
        mock_vendas.assert_called_once()
        mock_exec.assert_not_called()

    @patch("views.marketing_campaigns.perf_timed_block")
    @patch("views.marketing_campaigns.st")
    @patch("views.marketing_campaigns._load_oficiais_todos")
    def test_todos_dispara_loader(self, mock_load, _mock_st, mock_block):
        from views.marketing_campaigns import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        mock_load.return_value = {"vendas_novas_oficial": 49}
        loader = _oficiais_loader_factory(self._ctx())
        out = loader("__todos__")
        mock_load.assert_called_once()
        self.assertEqual(out["vendas_novas_oficial"], 49)


class TestGetMktCampanhasVendasOficiaisCache(unittest.TestCase):
    @patch("src.repositories.run_sql_file")
    def test_sql_executada_no_maximo_uma_vez_por_periodo(self, mock_sql):
        from src.repositories import get_mkt_campanhas_vendas_oficiais

        mock_sql.return_value = pd.DataFrame([{"vendas": 49}])
        get_mkt_campanhas_vendas_oficiais.clear()
        di, df = date(2026, 4, 1), date(2026, 4, 30)
        get_mkt_campanhas_vendas_oficiais(di, df)
        get_mkt_campanhas_vendas_oficiais(di, df)
        self.assertEqual(mock_sql.call_count, 1)
        mock_sql.assert_called_with(
            "mkt_campanhas_vendas_oficiais.sql",
            {"data_ini": di, "data_fim": df},
        )


if __name__ == "__main__":
    unittest.main()
