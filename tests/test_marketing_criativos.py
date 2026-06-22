"""Testes unitarios — Criativos Marketing (transforms e seletor).

Nao dependem do banco de producao."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from src.marketing_transforms import (
    criativo_funil_kpis,
    criativos_kpis,
    criativos_por_quality,
    criativos_ranking,
    criativos_top_por_nome_ranking,
    lista_criativos_funil,
)
from src.transforms import _safe_div
from src.ui.marketing_components import _normalize_funil_select_state

_TODOS = "__todos__"
_VINCULADOS = "__vinculados__"
_SEM_CRI = "__sem_criativo_identificado__"


def _cri_row(
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
    alc: int = 0,
) -> dict:
    return {
        "ad_name_norm": norm,
        "ad_name": name,
        "investimento": invest,
        "impressoes": imp,
        "cliques": clk,
        "link_clicks": clk,
        "alcance": alc,
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


def _criativos_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _resultados_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestCriativosKpis(unittest.TestCase):
    def test_performance_meta_from_view_and_mart(self):
        df = _criativos_df([
            {
                "ad_id": "1",
                "investimento": 1000.0,
                "impressoes": 10000,
                "cliques": 200,
                "alcance": 5000,
            },
            {
                "ad_id": "2",
                "investimento": 500.0,
                "impressoes": 5000,
                "cliques": 100,
                "alcance": 2500,
            },
        ])
        mart = _resultados_df([
            {
                "ad_id": "1",
                "leads_total": 10,
                "leads_mais_12": 5,
                "leads_menos_12": 3,
                "leads_nao_atua": 2,
                "agendamentos": 4,
                "comparecimentos": 2,
                "vendas": 1,
                "valor_receita": 5000.0,
                "no_shows": 0,
                "deals": 1,
                "deals_ganhos": 1,
                "valor_venda": 5000.0,
            },
            {
                "ad_id": "2",
                "leads_total": 8,
                "leads_mais_12": 4,
                "leads_menos_12": 2,
                "leads_nao_atua": 2,
                "agendamentos": 3,
                "comparecimentos": 1,
                "vendas": 2,
                "valor_receita": 8000.0,
                "no_shows": 0,
                "deals": 2,
                "deals_ganhos": 2,
                "valor_venda": 8000.0,
            },
        ])
        k = criativos_kpis(df, mart)
        self.assertEqual(k["anuncios_ativos"], 2)
        self.assertAlmostEqual(k["investimento"], 1500.0)
        self.assertEqual(k["impressoes"], 15000)
        self.assertEqual(k["alcance"], 7500)
        self.assertAlmostEqual(k["frequencia"], _safe_div(15000, 7500))
        self.assertAlmostEqual(k["ctr"], _safe_div(300, 15000) * 100)
        self.assertAlmostEqual(k["cpc"], _safe_div(1500.0, 300))
        self.assertEqual(k["leads_total"], 18)
        self.assertEqual(k["vendas"], 3)

    def test_empty_view_returns_zeros(self):
        k = criativos_kpis(pd.DataFrame(), pd.DataFrame())
        self.assertEqual(k["anuncios_ativos"], 0)
        self.assertEqual(k["investimento"], 0.0)


class TestListaCriativosFunil(unittest.TestCase):
    def _df(self) -> pd.DataFrame:
        return _funil_df([
            _cri_row("cri_a", "Criativo A", invest=100.0, leads=10, vendas=1),
            _cri_row("cri_b", "Criativo B", invest=200.0, leads=20, vendas=2),
            _cri_row(
                _SEM_CRI, "Sem criativo", invest=0.0, leads=3, vendas=1,
            ),
        ])

    def test_sinteticas_presentes(self):
        opts = lista_criativos_funil(self._df())
        norms = opts["ad_name_norm"].tolist()
        self.assertEqual(norms[0], _TODOS)
        self.assertEqual(norms[1], _VINCULADOS)
        self.assertIn(_SEM_CRI, norms)

    def test_todos_com_oficiais_no_label(self):
        opts = lista_criativos_funil(
            self._df(),
            leads_totais_oficial=854,
            vendas_novas_oficial=50,
            investimento_oficial=102_199.89,
        )
        todos = opts.loc[opts["ad_name_norm"] == _TODOS].iloc[0]
        self.assertIn("854", todos["label"])
        self.assertIn("50", todos["label"])


class TestCriativoFunilKpis(unittest.TestCase):
    def _df(self) -> pd.DataFrame:
        return _funil_df([
            _cri_row("cri_a", "Criativo A", invest=100.0, leads=10, vendas=1),
            _cri_row("cri_b", "Criativo B", invest=200.0, leads=20, vendas=2),
        ])

    def test_todos_usa_oficiais(self):
        k = criativo_funil_kpis(
            self._df(), _TODOS,
            leads_totais_oficial=854,
            vendas_novas_oficial=50,
            investimento_oficial=102_199.89,
        )
        self.assertTrue(k["tem_dados"])
        self.assertEqual(k["leads_totais"], 854)
        self.assertEqual(k["vendas_novas"], 50)
        self.assertAlmostEqual(k["investimento"], 102_199.89)

    def test_todos_fallback_sem_oficiais(self):
        k = criativo_funil_kpis(self._df(), _TODOS)
        self.assertEqual(k["leads_totais"], 30)
        self.assertEqual(k["vendas_novas"], 3)
        self.assertAlmostEqual(k["investimento"], 300.0)

    def test_vinculados_soma_df(self):
        k = criativo_funil_kpis(self._df(), _VINCULADOS)
        self.assertEqual(k["leads_totais"], 30)
        self.assertEqual(k["vendas_novas"], 3)

    def test_criativo_individual(self):
        k = criativo_funil_kpis(self._df(), "cri_a")
        self.assertTrue(k["tem_dados"])
        self.assertEqual(k["leads_totais"], 10)
        self.assertEqual(k["vendas_novas"], 1)
        self.assertAlmostEqual(k["investimento"], 100.0)

    def test_oficiais_nao_alteram_outras_metricas_individual(self):
        k_base = criativo_funil_kpis(self._df(), "cri_a")
        k_off = criativo_funil_kpis(
            self._df(), "cri_a",
            leads_totais_oficial=999,
            vendas_novas_oficial=99,
        )
        self.assertEqual(k_base["leads_totais"], k_off["leads_totais"])
        self.assertEqual(k_base["vendas_novas"], k_off["vendas_novas"])


class TestResolveVendasNovasOficial(unittest.TestCase):
    def _resolve(self, vendas_count, **kwargs):
        from views.marketing_creatives import _resolve_vendas_novas_oficial

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


class TestCriativosOficiaisIntegration(unittest.TestCase):
    def _ctx(self) -> MagicMock:
        ctx = MagicMock()
        ctx.data_ini = date(2026, 4, 1)
        ctx.data_fim = date(2026, 4, 30)
        return ctx

    @patch("views.marketing_creatives.st")
    @patch("views.marketing_creatives._fetch_df")
    def test_todos_usa_vendas_oficiais_slim(self, mock_fetch, _mock_st):
        from views.marketing_creatives import _load_oficiais_todos

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

    @patch("views.marketing_creatives.perf_timed_block")
    @patch("views.marketing_creatives.st")
    @patch("views.marketing_creatives._load_oficiais_todos")
    def test_vinculados_nao_carrega_oficiais(
        self, mock_load, _mock_st, mock_block,
    ):
        from views.marketing_creatives import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        loader = _oficiais_loader_factory(self._ctx())
        self.assertEqual(loader(_VINCULADOS), {})
        mock_load.assert_not_called()

    @patch("views.marketing_creatives.perf_timed_block")
    @patch("views.marketing_creatives.st")
    @patch("views.marketing_creatives._load_oficiais_todos")
    def test_sem_criativo_nao_carrega_oficiais(
        self, mock_load, _mock_st, mock_block,
    ):
        from views.marketing_creatives import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        loader = _oficiais_loader_factory(self._ctx())
        self.assertEqual(loader(_SEM_CRI), {})
        mock_load.assert_not_called()

    @patch("views.marketing_creatives.perf_timed_block")
    @patch("views.marketing_creatives.st")
    @patch("views.marketing_creatives._load_oficiais_todos")
    def test_criativo_individual_nao_carrega_oficiais(
        self, mock_load, _mock_st, mock_block,
    ):
        from views.marketing_creatives import _oficiais_loader_factory

        mock_block.return_value.__enter__ = MagicMock(return_value=None)
        mock_block.return_value.__exit__ = MagicMock(return_value=False)
        loader = _oficiais_loader_factory(self._ctx())
        self.assertEqual(loader("cri_a"), {})
        mock_load.assert_not_called()


class TestFunilSelectRevalidation(unittest.TestCase):
    def test_normaliza_label_legado_para_norm(self):
        state: dict = {
            "cri_funil_selecionado": "Todos os resultados · R$ 100 · 10 leads",
        }
        labels = {
            _TODOS: "Todos os resultados · R$ 100 · 10 leads · 1 apl. · 0 vendas",
            "cri_a": "Criativo A · R$ 50 · 5 leads · 0 apl. · 0 vendas",
        }
        with patch("src.ui.marketing_components.st") as mock_st:
            mock_st.session_state = state
            _normalize_funil_select_state(
                "cri_funil_selecionado",
                [_TODOS, "cri_a"],
                labels,
            )
        self.assertEqual(state["cri_funil_selecionado"], _TODOS)

    def test_selecao_invalida_cai_no_primeiro(self):
        state: dict = {"cri_funil_selecionado": "inexistente"}
        labels = {_TODOS: "Todos", "cri_a": "Criativo A"}
        with patch("src.ui.marketing_components.st") as mock_st:
            mock_st.session_state = state
            _normalize_funil_select_state(
                "cri_funil_selecionado",
                [_TODOS, "cri_a"],
                labels,
            )
        self.assertEqual(state["cri_funil_selecionado"], _TODOS)


def _criativos_view_row(
    ad_id: str = "1",
    ad_name: str = "Ad A",
    invest: float = 100.0,
    *,
    thumbnail_url=None,
    image_url=None,
    permalink_url=None,
    quality_ranking: str | None = "UNKNOWN",
    engagement_ranking: str | None = "UNKNOWN",
    conversion_ranking: str | None = "UNKNOWN",
) -> dict:
    row = {
        "ad_id": ad_id,
        "ad_name": ad_name,
        "campaign_name": "Camp",
        "effective_status": "ACTIVE",
        "investimento": invest,
        "impressoes": 1000,
        "cliques": 50,
        "alcance": 500,
        "quality_ranking": quality_ranking,
        "engagement_ranking": engagement_ranking,
        "conversion_ranking": conversion_ranking,
    }
    if thumbnail_url is not None:
        row["thumbnail_url"] = thumbnail_url
    if image_url is not None:
        row["image_url"] = image_url
    if permalink_url is not None:
        row["permalink_url"] = permalink_url
    return row


def _top_nome_row(ad_name: str = "ad a", invest: float = 100.0) -> dict:
    return {
        "ad_name_norm": ad_name,
        "ad_name": ad_name.upper(),
        "investimento": invest,
        "leads_reais": 10,
        "leads_mais_12": 5,
        "leads_menos_12": 2,
        "leads_nao_atua": 1,
        "aplicacoes": 3,
        "aplicacoes_mais_12": 1,
        "aplicacoes_menos_12": 1,
        "impressoes": 1000,
        "cliques": 50,
        "alcance": 500,
        "ctr": 5.0,
        "cpc": 2.0,
    }


class TestCriativosTop12MediaCols(unittest.TestCase):
    def test_ranking_com_tres_colunas_de_midia(self):
        df = pd.DataFrame([
            _criativos_view_row(
                thumbnail_url="http://t/1.jpg",
                image_url="http://i/1.jpg",
                permalink_url="http://p/1",
            ),
        ])
        top = criativos_ranking(df, top_n=12)
        self.assertEqual(len(top), 1)
        self.assertEqual(top.iloc[0]["thumbnail_url"], "http://t/1.jpg")
        self.assertEqual(top.iloc[0]["image_url"], "http://i/1.jpg")
        self.assertEqual(top.iloc[0]["permalink_url"], "http://p/1")

    def test_ranking_sem_colunas_de_midia(self):
        df = pd.DataFrame([_criativos_view_row()])
        top = criativos_ranking(df, top_n=12)
        self.assertEqual(len(top), 1)
        for col in ("thumbnail_url", "image_url", "permalink_url"):
            self.assertIn(col, top.columns)
            self.assertTrue(pd.isna(top.iloc[0][col]))

    def test_ranking_apenas_thumbnail(self):
        df = pd.DataFrame([
            _criativos_view_row(thumbnail_url="http://t/2.jpg"),
        ])
        top = criativos_ranking(df, top_n=12)
        self.assertEqual(top.iloc[0]["thumbnail_url"], "http://t/2.jpg")
        self.assertTrue(pd.isna(top.iloc[0]["image_url"]))
        self.assertTrue(pd.isna(top.iloc[0]["permalink_url"]))

    def test_ranking_urls_nulas(self):
        df = pd.DataFrame([
            _criativos_view_row(
                thumbnail_url=None,
                image_url=None,
                permalink_url=None,
            ),
        ])
        top = criativos_ranking(df, top_n=12)
        for col in ("thumbnail_url", "image_url", "permalink_url"):
            self.assertTrue(pd.isna(top.iloc[0][col]))

    def test_ranking_valores_e_ordem_inalterados_sem_midia(self):
        df = pd.DataFrame([
            _criativos_view_row("1", "A", 200.0),
            _criativos_view_row("2", "B", 100.0),
        ])
        top = criativos_ranking(df, sort_by="investimento", ascending=False, top_n=12)
        self.assertEqual(top["ad_name"].tolist(), ["A", "B"])
        self.assertAlmostEqual(top.iloc[0]["investimento"], 200.0)

    def test_top_por_nome_sem_colunas_midia_na_view(self):
        df_view = pd.DataFrame([_criativos_view_row()])
        df_top = pd.DataFrame([_top_nome_row("ad a", 100.0)])
        top = criativos_top_por_nome_ranking(
            df_view, df_top, pd.DataFrame(), top_n=12,
        )
        self.assertEqual(len(top), 1)
        for col in ("thumbnail_url", "image_url", "permalink_url"):
            self.assertIn(col, top.columns)

    def test_fallback_ranking_apos_top_nome_vazio(self):
        df_view = pd.DataFrame([
            _criativos_view_row("1", "Z", 300.0),
            _criativos_view_row("2", "Y", 100.0),
        ])
        top = criativos_top_por_nome_ranking(
            df_view, pd.DataFrame(), pd.DataFrame(), top_n=12,
        )
        self.assertTrue(top.empty)
        fallback = criativos_ranking(df_view, top_n=12)
        self.assertEqual(fallback.iloc[0]["ad_name"], "Z")

    def test_card_html_sem_imagem_nao_gera_img_vazio(self):
        from views.marketing_creatives import _creative_card_html

        html = _creative_card_html(pd.Series({
            "ad_name": "Teste",
            "status_label": "Ativo",
            "investimento": 100,
            "ctr": 1.5,
            "cpc": 2.0,
            "thumbnail_url": None,
            "image_url": None,
            "permalink_url": None,
            "leads_total": 5,
        }))
        self.assertNotIn('src=""', html)
        self.assertNotIn("<img ", html)
        self.assertIn("Sem preview", html)

    def test_card_html_com_thumbnail(self):
        from views.marketing_creatives import _creative_card_html

        html = _creative_card_html(pd.Series({
            "ad_name": "Teste",
            "status_label": "Ativo",
            "investimento": 100,
            "ctr": 1.5,
            "cpc": 2.0,
            "thumbnail_url": "http://example.com/t.jpg",
            "permalink_url": "http://example.com/p",
            "leads_total": 5,
        }))
        self.assertIn('src="http://example.com/t.jpg"', html)
        self.assertIn('href="http://example.com/p"', html)


class TestCriativosPorQuality(unittest.TestCase):
    def test_com_quality_ranking_agrupa_investimento(self):
        df = pd.DataFrame([
            _criativos_view_row("1", "A", 200.0, quality_ranking="ABOVE_AVERAGE"),
            _criativos_view_row("2", "B", 100.0, quality_ranking="ABOVE_AVERAGE"),
            _criativos_view_row("3", "C", 50.0, quality_ranking="BELOW_AVERAGE_10"),
        ])
        out = criativos_por_quality(df)
        self.assertEqual(
            set(out["quality_label"]), {"Acima da média", "Abaixo da média"},
        )
        above = out.loc[
            out["quality_label"] == "Acima da média", "investimento",
        ].iloc[0]
        self.assertAlmostEqual(above, 300.0)

    def test_periodo_vazio_retorna_schema_vazio(self):
        out = criativos_por_quality(pd.DataFrame())
        self.assertTrue(out.empty)
        self.assertEqual(list(out.columns), ["quality_label", "investimento"])

    def test_keyerror_quando_coluna_ausente(self):
        """Contrato vw_mkt_criativos: quality_ranking obrigatorio em df nao vazio."""
        df = pd.DataFrame([
            {
                "ad_id": "1",
                "investimento": 100.0,
                "effective_status": "ACTIVE",
            },
        ])
        with self.assertRaises(KeyError) as ctx:
            criativos_por_quality(df)
        self.assertEqual(ctx.exception.args[0], "quality_ranking")

    @patch("views.marketing_creatives.st")
    def test_render_distribuicoes_com_mock_completo(self, mock_st):
        from views.marketing_creatives import _render_distribuicoes

        col = MagicMock()
        mock_st.columns.return_value = (col, col)
        df = pd.DataFrame([_criativos_view_row(invest=100.0)])
        _render_distribuicoes(df)
        mock_st.plotly_chart.assert_called()

    @patch("views.marketing_creatives.st")
    def test_render_distribuicoes_keyerror_mock_incompleto(self, mock_st):
        from views.marketing_creatives import _render_distribuicoes

        col = MagicMock()
        mock_st.columns.return_value = (col, col)
        df = pd.DataFrame([
            {"ad_id": "1", "investimento": 100.0, "effective_status": "ACTIVE"},
        ])
        with self.assertRaises(KeyError):
            _render_distribuicoes(df)


class TestCreativesPageNavigation(unittest.TestCase):
    """Smoke da pagina com mocks — substitui validate_creatives_navigation.py."""

    def _mock_ctx(self) -> MagicMock:
        ctx = MagicMock()
        ctx.data_ini = date(2026, 4, 1)
        ctx.data_fim = date(2026, 4, 30)
        ctx.selections = {"campanha": [], "status": []}
        ctx.apply_filters = lambda df, _col_map: df
        ctx.refilter = lambda df, _col_map: df
        return ctx

    @patch("views.marketing_creatives.perf_render_panel")
    @patch("views.marketing_creatives.perf_finalize_page")
    @patch("views.marketing_creatives._render_auditorias")
    @patch("views.marketing_creatives._render_comparar_criativos")
    @patch("views.marketing_creatives._render_top12")
    @patch("views.marketing_creatives._render_funil_section")
    @patch("views.marketing_creatives._render_distribuicoes")
    @patch("views.marketing_creatives._render_performance_meta")
    @patch("views.marketing_creatives._load_p1_data")
    @patch("views.marketing_creatives.start_page")
    @patch("views.marketing_creatives.st")
    def test_main_nao_executa_distribuicoes_sem_dados(
        self,
        _mock_st,
        mock_start,
        mock_p1,
        mock_perf,
        mock_dist,
        mock_funil,
        _mock_top,
        _mock_cmp,
        _mock_aud,
        _mock_fin,
        _mock_panel,
    ):
        from views.marketing_creatives import main

        mock_start.return_value = self._mock_ctx()
        mock_p1.return_value = (
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            {}, {}, None,
        )
        main()
        mock_dist.assert_not_called()
        mock_funil.assert_called_once()
        mock_perf.assert_called_once()

    @patch("views.marketing_creatives.perf_render_panel")
    @patch("views.marketing_creatives.perf_finalize_page")
    @patch("views.marketing_creatives._render_auditorias")
    @patch("views.marketing_creatives._render_comparar_criativos")
    @patch("views.marketing_creatives._render_top12")
    @patch("views.marketing_creatives._render_funil_section")
    @patch("views.marketing_creatives._render_distribuicoes")
    @patch("views.marketing_creatives._render_performance_meta")
    @patch("views.marketing_creatives._load_p1_data")
    @patch("views.marketing_creatives.start_page")
    @patch("views.marketing_creatives.st")
    def test_main_chama_distribuicoes_com_view_completa(
        self,
        _mock_st,
        mock_start,
        mock_p1,
        mock_perf,
        mock_dist,
        mock_funil,
        _mock_top,
        _mock_cmp,
        _mock_aud,
        _mock_fin,
        _mock_panel,
    ):
        from views.marketing_creatives import main

        df_all = pd.DataFrame([_criativos_view_row()])
        mock_start.return_value = self._mock_ctx()
        mock_p1.return_value = (
            df_all, df_all, pd.DataFrame(), pd.DataFrame(),
            pd.DataFrame(), pd.DataFrame(), {}, {}, None,
        )
        main()
        mock_dist.assert_called_once()
        passed_df = mock_dist.call_args[0][0]
        self.assertIn("quality_ranking", passed_df.columns)

    def test_fallback_top12_com_quality_ranking_na_view(self):
        df = pd.DataFrame([
            _criativos_view_row("1", "Z", 300.0),
            _criativos_view_row("2", "Y", 100.0),
        ])
        top = criativos_top_por_nome_ranking(
            df, pd.DataFrame(), pd.DataFrame(), top_n=12,
        )
        self.assertTrue(top.empty)
        fallback = criativos_ranking(df, top_n=12)
        self.assertEqual(fallback.iloc[0]["ad_name"], "Z")
        self.assertAlmostEqual(fallback.iloc[0]["investimento"], 300.0)


class TestCreativesPageGuard(unittest.TestCase):
    def test_st_page_exec_usa_main_guard(self):
        import types
        from pathlib import Path

        code = Path(__file__).resolve().parents[1] / "views" / "marketing_creatives.py"
        text = code.read_text(encoding="utf-8")
        mod = types.ModuleType("__main__")
        mod.__dict__["__file__"] = str(code)
        exec("ok = (__name__ == '__main__')", mod.__dict__)
        self.assertTrue(mod.__dict__["ok"])
        self.assertIn('if __name__ == "__main__":', text)
        self.assertIn("main()", text)


if __name__ == "__main__":
    unittest.main()
