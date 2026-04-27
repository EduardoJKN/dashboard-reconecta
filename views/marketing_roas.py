"""ROAS / CAC — placeholder (próxima iteração)."""
import streamlit as st

from src.ui.page import start_page

start_page(
    title="ROAS / CAC",
    subtitle="Eficiência de mídia paga · em desenvolvimento",
    filters=(),
    include_period=False,
)

st.info(
    "Página em construção. Vai consumir `bi.vw_mkt_roas` para mostrar "
    "investimento × receita atribuída por canal, ROAS e CAC diários, "
    "com janelas comparativas (período atual vs anterior)."
)
