import unittest

import pandas as pd

from src.prevendas_transforms import (
    classificacao_final_com_prioridade_crm,
    email_final_com_prioridade_crm,
    prevendas_normalizar_detalhe,
)


class TestClassificacaoFinalDetalhe(unittest.TestCase):
    def test_crm_valido_prevalece_sobre_lead(self):
        self.assertEqual(
            classificacao_final_com_prioridade_crm("Atua +12", "Sem classificação"),
            "Atua +12",
        )

    def test_crm_vazio_usa_lead_valido(self):
        self.assertEqual(
            classificacao_final_com_prioridade_crm("", "Atua -12"),
            "Atua -12",
        )

    def test_ambos_vazios_sem_classificacao(self):
        self.assertEqual(
            classificacao_final_com_prioridade_crm(None, "Sem classificação"),
            "Sem classificação",
        )

    def test_mariana_tecchio_caso_real(self):
        df = prevendas_normalizar_detalhe(pd.DataFrame([{
            "classificacao": None,
            "classificacao_crm": "Atua +12",
            "email_lead": None,
            "email_crm": "esteticamarianatecchio@hotmail.com",
            "tipo_registro_base": "Atividade",
        }]))
        self.assertEqual(df.loc[0, "classificacao_final_filtro"], "Atua +12")
        self.assertEqual(df.loc[0, "classificacao_filtro"], "Sem classificação")
        self.assertEqual(df.loc[0, "classificacao_crm_filtro"], "Atua +12")
        self.assertEqual(
            df.loc[0, "email_final_filtro"],
            "esteticamarianatecchio@hotmail.com",
        )
        self.assertEqual(df.loc[0, "email_lead_filtro"], "")
        self.assertEqual(
            df.loc[0, "email_crm_filtro"],
            "esteticamarianatecchio@hotmail.com",
        )


class TestEmailFinalDetalhe(unittest.TestCase):
    def test_crm_valido_prevalece_sobre_lead(self):
        self.assertEqual(
            email_final_com_prioridade_crm(
                "crm@exemplo.com",
                "lead@exemplo.com",
            ),
            "crm@exemplo.com",
        )

    def test_none_texto_tratado_como_vazio(self):
        self.assertEqual(
            email_final_com_prioridade_crm("None", "lead@exemplo.com"),
            "lead@exemplo.com",
        )
        self.assertEqual(email_final_com_prioridade_crm("nan", None), "")

    def test_crm_vazio_usa_lead(self):
        self.assertEqual(
            email_final_com_prioridade_crm("", "lead@exemplo.com"),
            "lead@exemplo.com",
        )


if __name__ == "__main__":
    unittest.main()
