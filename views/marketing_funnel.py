"""Funil Marketing — placeholder (próxima iteração)."""
import streamlit as st

from src.ui.page import start_page

start_page(
    title="Funil Marketing",
    subtitle="Impressão → clique → lead → SQL → venda · em desenvolvimento",
    filters=(),
    include_period=False,
)

st.info(
    "Página em construção. Vai consumir `bi.vw_mkt_funil` (paid + "
    "`odam.v_attribution_lead_to_deal`) para visualizar o funil completo "
    "por canal com taxas de conversão entre etapas."
)
