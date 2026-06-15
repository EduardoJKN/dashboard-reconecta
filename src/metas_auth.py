"""Autenticação de editor de metas (Funil da Reconecta).

Independente do login geral (`require_auth`). Libera edição/salvamento de
metas na página do funil. Persistência via cookie JWT separado
(`reconecta_metas_editor`), usando o CookieManager centralizado em `src.auth`.
"""
from __future__ import annotations

import hmac
import time
from datetime import datetime, timedelta, timezone

import jwt
import streamlit as st

from src.auth import (
    auth_cookie_expiry_days,
    auth_cookie_key,
    clear_logout_pending,
    delete_cookie,
    get_cookie,
    is_logout_pending,
    logout_dashboard,
    resolve_env_or_secret,
    set_cookie,
)

_SESSION_KEY = "metas_editor_authenticated"
_COOKIE_NAME = "reconecta_metas_editor"
_JWT_ALGO = "HS256"
_JWT_SCOPE = "metas_editor"

METAS_VIEW_ONLY_MESSAGE = (
    "Você está em modo visualização. Para editar ou salvar metas, "
    "faça login como editor de metas."
)


def expected_metas_editor_password() -> str | None:
    """Senha do editor — mesma ordem de resolução do login geral."""
    return resolve_env_or_secret(
        "METAS_EDITOR_PASSWORD",
        ("auth", "metas_editor_password"),
        top_level_secret_key="METAS_EDITOR_PASSWORD",
    )


def activate_metas_editor(*, persist_cookie: bool = True) -> None:
    """Marca editor de metas autenticado; opcionalmente grava cookie JWT."""
    st.session_state[_SESSION_KEY] = True
    if not persist_cookie:
        return

    cookie_key = auth_cookie_key()
    if not cookie_key:
        return

    days = auth_cookie_expiry_days()
    token = _issue_token(cookie_key, days)
    expires_at = datetime.now() + timedelta(days=days)
    set_cookie(
        _COOKIE_NAME,
        token,
        expires_at=expires_at,
        widget_key="metas_editor_login_set",
    )


def _issue_token(key: str, expiry_days: float) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "scope": _JWT_SCOPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expiry_days)).timestamp()),
    }
    return jwt.encode(payload, key, algorithm=_JWT_ALGO)


def _validate_token(token: str, key: str) -> bool:
    try:
        payload = jwt.decode(token, key, algorithms=[_JWT_ALGO])
        return payload.get("scope") == _JWT_SCOPE
    except jwt.PyJWTError:
        return False


def is_metas_editor_authenticated() -> bool:
    return bool(st.session_state.get(_SESSION_KEY))


def sync_metas_editor_session() -> bool:
    """Hidrata `session_state` a partir do cookie do editor (sem renderizar UI)."""
    if is_logout_pending():
        st.session_state.pop(_SESSION_KEY, None)
        return False

    if st.session_state.get(_SESSION_KEY):
        return True

    cookie_key = auth_cookie_key()
    if not cookie_key:
        return False

    token = get_cookie(_COOKIE_NAME)
    if token and _validate_token(token, cookie_key):
        st.session_state[_SESSION_KEY] = True
        return True
    return False


def logout_metas_editor(*, rerun: bool = False) -> None:
    """Remove sessão/cookie do editor de metas."""
    st.session_state.pop(_SESSION_KEY, None)
    st.session_state.pop("_metas_editor_just_activated", None)
    delete_cookie(_COOKIE_NAME, widget_key="metas_editor_logout")
    if rerun:
        time.sleep(0.4)
        st.rerun()


def render_metas_editor_gate() -> bool:
    """Bloco de login do editor de metas. Retorna True se edição está liberada."""
    sync_metas_editor_session()

    section_title = "Modo de edição de metas"
    st.markdown(f"### {section_title}")

    if is_metas_editor_authenticated():
        if st.session_state.pop("_metas_editor_just_activated", False):
            st.success("Modo editor de metas ativado.")
        else:
            st.success("Modo editor de metas ativo.")
        if st.button("Sair do modo editor", key="metas_editor_logout_btn"):
            logout_dashboard()
        return True

    expected = expected_metas_editor_password()
    if not expected:
        st.warning(
            "Edição de metas indisponível: configure `METAS_EDITOR_PASSWORD` "
            "no `.env` ou nos Secrets do Streamlit."
        )
        st.caption(METAS_VIEW_ONLY_MESSAGE)
        return False

    st.caption("Para editar e salvar metas, informe a senha de editor de metas.")
    with st.form("metas_editor_login_form", clear_on_submit=False):
        pwd = st.text_input(
            "Senha de editor",
            type="password",
            placeholder="Senha de editor",
        )
        submitted = st.form_submit_button(
            "Entrar como editor de metas",
            use_container_width=True,
        )

    if submitted:
        cookie_key = auth_cookie_key()
        if not cookie_key:
            st.error(
                "`AUTH_COOKIE_KEY` ausente — necessária para assinar o cookie "
                "do editor de metas."
            )
            return False
        if hmac.compare_digest(str(pwd), str(expected)):
            clear_logout_pending()
            activate_metas_editor(persist_cookie=True)
            st.session_state["_metas_editor_just_activated"] = True
            time.sleep(0.6)
            st.rerun()
        else:
            st.error("Senha de editor inválida.")

    st.caption(METAS_VIEW_ONLY_MESSAGE)
    return False
