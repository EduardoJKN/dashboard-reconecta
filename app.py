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
# Navegação — agrupada por área seguindo a lógica do funil:
# Marketing → Pré-vendas → Vendas
# -----------------------------------------------------------------------------
pages = {
    # Item independente, sem cabeçalho de seção (chave vazia). Fica acima
    # dos blocos de Marketing/Pré-vendas/Vendas — visão executiva pro CEO.
    "": [
        st.Page("views/one_page.py", title="One Page"),
    ],
    "Time de Marketing": [
        st.Page("views/marketing_overview.py",  title="Visão Geral Marketing"),
        st.Page("views/marketing_campaigns.py", title="Campanhas"),
        st.Page("views/marketing_creatives.py", title="Criativos"),
        st.Page("views/marketing_funnel.py",    title="Funil Marketing"),
        st.Page("views/marketing_social.py",    title="Social"),
        st.Page("views/marketing_roas.py",      title="ROAS / CAC"),
        st.Page("views/marketing_growth.py",    title="Growth"),
    ],
    "Time de Pré-vendas": [
        st.Page("views/prevendas_overview.py",        title="Visão Geral Pré-vendas"),
        st.Page("views/prevendas_sdrs_times.py",      title="SDRs & Times"),
        st.Page("views/prevendas_sdr_closer.py",      title="SDR × Closer"),
        st.Page("views/prevendas_comparecimentos.py", title="Comparecimentos & Oportunidades"),
        st.Page("views/prevendas_sla.py",             title="SLA & Tempo de Resposta"),
    ],
    "Time de Vendas": [
        st.Page("views/home.py",         title="Visão Geral", default=True),
        st.Page("views/executivas.py",   title="Executivas & Times"),
        st.Page("views/sdr_closer.py",   title="SDR × Closer"),
        st.Page("views/investimento.py", title="Investimento & ROAS"),
        st.Page("views/inspecao.py",     title="Inspeção de Views"),
    ],
    # Ferramentas — vão abaixo dos blocos por time. Por enquanto só o
    # simulador de funil; quando crescer, vira um bloco próprio.
    "Ferramentas": [
        st.Page("views/funil_reconecta.py", title="Funil da Reconecta"),
    ],
}

pg = st.navigation(pages, position="sidebar")
pg.run()
