"""Gate de autenticação simples por senha compartilhada.

Lê a senha esperada de:
1. `st.secrets["auth"]["password"]`  (produção, Streamlit Cloud)
2. variável de ambiente `AUTH_PASSWORD`  (local via .env)

Se nenhuma das duas estiver definida, o app é bloqueado em modo failsafe
(evita publicar acidentalmente sem proteção).

A comparação usa `hmac.compare_digest` (tempo-constante) para mitigar
timing attacks. A senha NUNCA aparece nem em logs nem na URL.

A sessão é mantida em `st.session_state` — fechar o navegador desloga.
Para revogar acesso global, basta trocar a senha e reiniciar o app.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

_AUTHED_KEY = "_reconecta_authed"


def _expected_password() -> str | None:
    """Retorna a senha configurada (st.secrets > env). None se ausente."""
    try:
        if "auth" in st.secrets and "password" in st.secrets["auth"]:
            val = st.secrets["auth"]["password"]
            if val:
                return str(val)
    except Exception:
        pass
    return os.getenv("AUTH_PASSWORD") or None


def _login_form() -> None:
    """Renderiza o formulário de login centralizado."""
    st.markdown(
        """
        <div style="max-width: 380px; margin: 80px auto 0;
                    padding: 32px 28px;
                    background: #161311;
                    border: 1px solid #3a2e20;
                    border-radius: 12px;">
          <div style="color:#e8c96e; font-weight:800; letter-spacing:2px;
                      font-size:0.95rem; margin-bottom:6px;">RECONECTA BI</div>
          <div style="color:#a89a8a; font-size:0.82rem; margin-bottom:20px;">
            Acesso restrito · informe a senha para continuar
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 2, 1])
    with cols[1]:
        with st.form("login_form", clear_on_submit=False):
            pwd = st.text_input("Senha", type="password",
                                label_visibility="collapsed",
                                placeholder="Senha")
            submitted = st.form_submit_button("Entrar", use_container_width=True)
        return pwd, submitted


def require_auth() -> None:
    """Bloqueia a renderização da página até o usuário inserir a senha correta.
    Chame UMA VEZ no topo do `app.py`, logo após `apply_dark_theme()`."""
    if st.session_state.get(_AUTHED_KEY):
        return  # já autenticado nessa sessão

    expected = _expected_password()
    if not expected:
        st.error(
            "⚠️ Configuração de autenticação ausente. "
            "Defina `auth.password` em `.streamlit/secrets.toml` (local) "
            "ou no painel **Secrets** do Streamlit Cloud (produção)."
        )
        st.stop()

    pwd, submitted = _login_form()
    if submitted:
        # Comparação de tempo constante (resiste a timing attacks).
        if hmac.compare_digest(str(pwd), str(expected)):
            st.session_state[_AUTHED_KEY] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()  # ← nada mais é renderizado até logar
