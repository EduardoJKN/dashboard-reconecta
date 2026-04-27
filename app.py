"""Entrypoint do Reconecta BI.

Este arquivo é apenas o roteador de navegação — cada página real vive em
`views/`. A sidebar mostra só a navegação (os filtros vão no topo de cada
página, compartilhando o período via `st.session_state`)."""
import streamlit as st

from src.auth import require_auth
from src.ui.components import apply_dark_theme

# -----------------------------------------------------------------------------
# Config global
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Reconecta BI",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_dark_theme()

# -----------------------------------------------------------------------------
# Gate de autenticação — bloqueia tudo abaixo até inserir a senha correta
# -----------------------------------------------------------------------------
require_auth()

# -----------------------------------------------------------------------------
# Marca na sidebar (acima da lista de páginas)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '<div class="brand">'
        '<div class="brand-title">RECONECTA BI</div>'
        '<div class="brand-sub">Inteligência Comercial</div>'
        '</div>',
        unsafe_allow_html=True,
    )

# -----------------------------------------------------------------------------
# Navegação
# -----------------------------------------------------------------------------
pages = [
    st.Page("views/home.py",         title="Visão Geral",         default=True),
    st.Page("views/executivas.py",   title="Executivas & Times"),
    st.Page("views/sdr_closer.py",   title="SDR × Closer"),
    st.Page("views/investimento.py", title="Investimento & ROAS"),
    st.Page("views/inspecao.py",     title="Inspeção de Views"),
]

pg = st.navigation(pages, position="sidebar")
pg.run()
