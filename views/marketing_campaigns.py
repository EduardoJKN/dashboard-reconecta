"""Campanhas — placeholder (próxima iteração)."""
import streamlit as st

from src.ui.page import start_page

start_page(
    title="Campanhas",
    subtitle="Performance diária por campanha · em desenvolvimento",
    filters=(),
    include_period=False,
)

st.info(
    "Página em construção. Vai consumir `bi.vw_mkt_campanhas` (UNION de Meta + "
    "Google + Pinterest no grão `data × campanha`) para listar invest, "
    "impressões, cliques, CPC e status com filtro por canal."
)
