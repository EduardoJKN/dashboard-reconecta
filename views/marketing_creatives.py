"""Criativos — placeholder (próxima iteração)."""
import streamlit as st

from src.ui.page import start_page

start_page(
    title="Criativos",
    subtitle="Ranking de anúncios Meta · em desenvolvimento",
    filters=(),
    include_period=False,
)

st.info(
    "Página em construção. Vai consumir `bi.vw_mkt_criativos` (Meta + cache "
    "de criativos via `odam.meta_ads_creatives`) para mostrar ranking de "
    "anúncios por CTR / frequência / quality_ranking, com thumbnails e "
    "permalink direto para o Meta Ads Manager."
)
