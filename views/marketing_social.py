"""Social — placeholder (próxima iteração)."""
import streamlit as st

from src.ui.page import start_page

start_page(
    title="Social",
    subtitle="Instagram orgânico · em desenvolvimento",
    filters=(),
    include_period=False,
)

st.info(
    "Página em construção. Vai consumir `bi.vw_mkt_social` para mostrar "
    "alcance, engajamento e taxa de engajamento dos posts do Instagram, "
    "com top posts por reach e por engajamento."
)
