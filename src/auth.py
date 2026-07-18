"""Gate de autenticação por senha compartilhada com persistência via cookie.

Senhas aceitas na tela inicial:
1. `AUTH_PASSWORD` — acesso ao dashboard em modo visualização.
2. `METAS_EDITOR_PASSWORD` — acesso ao dashboard já como editor de metas.

`AUTH_PASSWORD` vem de `st.secrets["auth"]["password"]` ou env `AUTH_PASSWORD`.
`METAS_EDITOR_PASSWORD` é resolvida em `src.metas_auth`.

Persistência via cookie `reconecta_auth` que carrega um JWT assinado com
HMAC-SHA256. A chave de assinatura vem de:
1. `st.secrets["auth"]["cookie_key"]`
2. variável de ambiente `AUTH_COOKIE_KEY`

A validade do cookie (default 7 dias) vem de:
1. `st.secrets["auth"]["cookie_expiry_days"]`
2. variável de ambiente `AUTH_COOKIE_EXPIRY_DAYS`

Trocar `cookie_key` invalida instantaneamente todos os cookies existentes
(mecanismo de logout global). A senha NUNCA trafega para o cliente — só
o JWT, que carrega apenas `iat` (issued at) e `exp` (expiry).

Comparação da senha usa `hmac.compare_digest` (timing-safe). Se nenhuma
fonte tiver senha definida, o app é bloqueado em modo failsafe (evita
publicar acidentalmente sem proteção).

API pública:
  - `require_auth()` — gate de login geral (chamar no topo do `app.py`).
  - `get_cookie` / `set_cookie` / `delete_cookie` — único CookieManager do app.
  - `logout_dashboard()` — encerra login geral e editor de metas.
  - `render_sidebar_user_block()` — usuário logado + «Trocar acesso» na sidebar.
"""
from __future__ import annotations

import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import extra_streamlit_components as stx
import jwt
import streamlit as st
from dotenv import load_dotenv

_dotenv_loaded = False

_AUTHED_KEY = "_reconecta_authed"
_LOGOUT_PENDING_KEY = "_reconecta_logout_pending"
_COOKIE_NAME = "reconecta_auth"
_COOKIE_MANAGER_KEY = "auth_cookie_manager_init"
_GET_ALL_KEY = "auth_cookie_get_all"
_AUTH_CM_INSTANCE_KEY = "_reconecta_auth_cm_instance"
_AUTH_COOKIES_KEY = "_auth_cookies"
_AUTH_COOKIES_LOADED_KEY = "_auth_cookies_loaded"
_COOKIES_READY_KEY = "_reconecta_cookies_component_ready"
_DEFAULT_EXPIRY_DAYS = 7
_JWT_ALGO = "HS256"


# ---------------------------------------------------------------------------
# Resolução de configuração — secrets.toml > env, sem hardcode
# ---------------------------------------------------------------------------
def _ensure_dotenv_loaded() -> None:
    """Carrega `.env` local uma vez antes de ler variáveis de ambiente."""
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


def _from_secrets_or_env(secret_path: tuple[str, str],
                         env_name: str) -> str | None:
    """Lê de st.secrets[section][key] (preferido) com fallback pra env var."""
    _ensure_dotenv_loaded()
    section, key = secret_path
    try:
        if section in st.secrets and key in st.secrets[section]:
            val = st.secrets[section][key]
            if val not in (None, ""):
                return str(val).strip()
    except Exception:
        pass
    raw = (os.getenv(env_name) or "").strip()
    return raw or None


def resolve_env_or_secret(
    env_name: str,
    secrets_path: tuple[str, str] | None = None,
    *,
    top_level_secret_key: str | None = None,
) -> str | None:
    """Resolve credencial: `[section].key` → top-level secret → `os.getenv`."""
    _ensure_dotenv_loaded()
    if secrets_path:
        val = _from_secrets_or_env(secrets_path, env_name)
        if val:
            return val
    if top_level_secret_key:
        try:
            val = st.secrets.get(top_level_secret_key)
            if val not in (None, ""):
                return str(val).strip()
        except Exception:
            pass
    raw = (os.getenv(env_name) or "").strip()
    return raw or None


def _expected_password() -> str | None:
    return _from_secrets_or_env(("auth", "password"), "AUTH_PASSWORD")


def _cookie_key() -> str | None:
    return _from_secrets_or_env(("auth", "cookie_key"), "AUTH_COOKIE_KEY")


def _expiry_days() -> float:
    raw = _from_secrets_or_env(
        ("auth", "cookie_expiry_days"), "AUTH_COOKIE_EXPIRY_DAYS"
    )
    if raw is None:
        return float(_DEFAULT_EXPIRY_DAYS)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(_DEFAULT_EXPIRY_DAYS)


# ---------------------------------------------------------------------------
# JWT helpers — token só carrega iat/exp; sem PII, sem senha
# ---------------------------------------------------------------------------
def _issue_token(key: str, expiry_days: float) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expiry_days)).timestamp()),
    }
    return jwt.encode(payload, key, algorithm=_JWT_ALGO)


def _validate_token(token: str, key: str) -> bool:
    """True quando o token tem assinatura válida e `exp` no futuro.
    PyJWT valida `exp` automaticamente em jwt.decode."""
    try:
        jwt.decode(token, key, algorithms=[_JWT_ALGO])
        return True
    except jwt.PyJWTError:
        return False


# ---------------------------------------------------------------------------
# Login form — visual idêntico ao anterior
# ---------------------------------------------------------------------------
def _login_form() -> tuple[str, bool]:
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


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def _debug_enabled() -> bool:
    """Toggle de logs de auth por env var AUTH_DEBUG=1.
    Usar SOMENTE em dev local — em prod deixar desligado."""
    return os.getenv("AUTH_DEBUG", "").strip() in ("1", "true", "True")


def _dbg(label: str, value) -> None:
    if _debug_enabled():
        st.caption(f"🔧 [auth-debug] {label}: `{value}`")


def auth_cookie_key() -> str | None:
    """Chave HMAC compartilhada para cookies JWT (login geral e editor de metas)."""
    return _cookie_key()


def auth_cookie_expiry_days() -> float:
    """Validade padrão dos cookies de sessão (dias)."""
    return _expiry_days()


def _auth_cookie_manager() -> stx.CookieManager:
    """Uma instância do CookieManager por sessão (widget não pode ir em cache)."""
    if _AUTH_CM_INSTANCE_KEY not in st.session_state:
        st.session_state[_AUTH_CM_INSTANCE_KEY] = stx.CookieManager(
            key=_COOKIE_MANAGER_KEY
        )
    return st.session_state[_AUTH_CM_INSTANCE_KEY]


def bootstrap_auth_cookies() -> None:
    """Força a leitura fresca dos cookies do navegador.

    Deve ser a PRIMEIRA coisa chamada em cada execução do script (ver
    `app.py`), antes de `require_auth()` / `sync_metas_editor_session()` —
    são elas que reaproveitam esse cache em vez de ler os cookies de novo."""
    _ensure_cookies_loaded(force_refresh=True)


def _ensure_cookies_loaded(*, force_refresh: bool = False) -> dict:
    """Lê cookies do navegador — no máximo uma chamada real a `cm.get_all()`
    por execução do script.

    `bootstrap_auth_cookies()` força essa leitura uma única vez, no topo do
    app; toda chamada seguinte na mesma execução (via `require_auth()`,
    `get_cookie()`, `sync_metas_editor_session()`, ...) reaproveita o valor
    já cacheado em `st.session_state`. Isso importa porque o CookieManager
    levanta `StreamlitDuplicateElementKey` se `get_all(key=...)` for chamado
    mais de uma vez com a mesma key na mesma execução — e detectar "essa
    chamada é da mesma execução?" via atributos internos do
    `ScriptRunContext` é frágil entre versões do Streamlit (foi o que
    quebrou no deploy). Por isso o cache aqui depende só da ordem fixa de
    chamadas em `app.py`, não de heurística de identidade de run.

    O componente do CookieManager costuma devolver `{}` no primeiro paint após
    F5 ou nova aba; nesse caso paramos uma vez para o iframe sincronizar.
    """
    if not force_refresh and st.session_state.get(_AUTH_COOKIES_LOADED_KEY):
        _dbg("cookies_load", "cache_hit")
        return st.session_state.get(_AUTH_COOKIES_KEY, {})

    cm = _auth_cookie_manager()
    _dbg("cookies_load", "get_all_called")
    cookies = cm.get_all(key=_GET_ALL_KEY) or {}

    if not st.session_state.get(_COOKIES_READY_KEY):
        st.session_state[_COOKIES_READY_KEY] = True
        if not cookies and not st.session_state.get(_AUTHED_KEY):
            st.stop()

    st.session_state[_AUTH_COOKIES_KEY] = cookies
    st.session_state[_AUTH_COOKIES_LOADED_KEY] = True
    return cookies


def get_cookie(name: str) -> str | None:
    """Lê um cookie pelo nome (snapshot da execução atual)."""
    val = _ensure_cookies_loaded().get(name)
    return str(val) if val is not None else None


def set_cookie(
    name: str,
    value: str,
    *,
    expires_at: datetime,
    widget_key: str | None = None,
) -> None:
    """Grava cookie via o CookieManager único do app."""
    cm = _auth_cookie_manager()
    max_age = max(0, int((expires_at - datetime.now()).total_seconds()))
    cm.set(
        name,
        value,
        expires_at=expires_at,
        max_age=max_age,
        path="/",
        same_site="lax",
        key=widget_key or f"auth_cookie_set_{name}",
    )
    if _AUTH_COOKIES_KEY in st.session_state:
        st.session_state[_AUTH_COOKIES_KEY][name] = value


def delete_cookie(name: str, *, widget_key: str | None = None) -> None:
    """Remove cookie via o CookieManager único do app."""
    cm = _auth_cookie_manager()
    wkey = widget_key or f"auth_cookie_delete_{name}"
    try:
        cm.delete(name, key=wkey)
    except Exception:
        pass
    try:
        expired = datetime.now() - timedelta(days=1)
        cm.set(
            name,
            "",
            expires_at=expired,
            max_age=0,
            path="/",
            same_site="lax",
            key=f"{wkey}_expire",
        )
    except Exception:
        pass
    if _AUTH_COOKIES_KEY in st.session_state:
        st.session_state[_AUTH_COOKIES_KEY].pop(name, None)


def is_logout_pending() -> bool:
    """True após logout — bloqueia reidratação automática via cookie."""
    return bool(st.session_state.get(_LOGOUT_PENDING_KEY))


def clear_logout_pending() -> None:
    st.session_state.pop(_LOGOUT_PENDING_KEY, None)


def is_dashboard_authenticated() -> bool:
    return bool(st.session_state.get(_AUTHED_KEY))


def _persist_dashboard_login(cookie_key: str, days: float) -> None:
    """Grava cookie do dashboard e marca sessão autenticada."""
    new_token = _issue_token(cookie_key, days)
    expires_at = datetime.now() + timedelta(days=days)
    _dbg("expires_at", expires_at.isoformat())
    set_cookie(
        _COOKIE_NAME,
        new_token,
        expires_at=expires_at,
        widget_key="reconecta_auth_set",
    )
    st.session_state[_AUTHED_KEY] = True


def logout_dashboard() -> None:
    """Encerra login geral e editor de metas; volta para a tela de login."""
    st.session_state[_LOGOUT_PENDING_KEY] = True
    st.session_state.pop(_AUTHED_KEY, None)
    st.session_state.pop(_COOKIES_READY_KEY, None)
    st.session_state.pop(_AUTH_COOKIES_KEY, None)
    st.session_state.pop(_AUTH_COOKIES_LOADED_KEY, None)
    delete_cookie(_COOKIE_NAME, widget_key="reconecta_auth_logout")

    from src.metas_auth import logout_metas_editor
    from src.ui.sidebar_user import clear_user_profile_state

    logout_metas_editor()
    clear_user_profile_state()
    time.sleep(0.6)
    st.rerun()


def render_sidebar_user_block() -> None:
    """Bloco de usuário logado no topo da sidebar (delegado a `sidebar_user`)."""
    from src.ui.sidebar_user import render_sidebar_user_block as _render

    _render()


def render_sidebar_logout_button() -> None:
    """Compatibilidade — preferir `render_sidebar_user_block`."""
    render_sidebar_user_block()


def require_auth() -> None:
    """Bloqueia a renderização da página até a autenticação ser válida.

    Ordem de resolução:
      1. Já autenticado nesta sessão (`st.session_state`) → retorna direto.
      2. Cookie `reconecta_auth` válido (assinatura OK + exp no futuro)
         → marca autenticado nesta sessão e retorna.
      3. Senão → exibe form de login. Em login bem-sucedido, grava cookie
         + marca autenticado + rerun (na próxima execução, cai no caso 1).

    Chame UMA VEZ no topo do `app.py`."""
    # 1) Sessão atual já autenticada — caminho rápido pós-login no mesmo run.
    if st.session_state.get(_AUTHED_KEY) and not is_logout_pending():
        return

    if is_logout_pending():
        st.session_state.pop(_AUTHED_KEY, None)

    expected = _expected_password()
    if not expected:
        st.error(
            "⚠️ Configuração de autenticação ausente. "
            "Defina `auth.password` em `.streamlit/secrets.toml` (local) "
            "ou no painel **Secrets** do Streamlit Cloud (produção)."
        )
        st.stop()

    cookie_key = _cookie_key()
    if not cookie_key:
        st.error(
            "⚠️ `auth.cookie_key` ausente. Defina em "
            "`.streamlit/secrets.toml` (local) ou no painel Secrets do "
            "Streamlit Cloud (produção). Use 32+ chars aleatórios — pode "
            "gerar via `python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\"`."
        )
        st.stop()

    cookies = _ensure_cookies_loaded()
    _dbg("cookies_visiveis", list(cookies.keys()))
    _dbg("tem_reconecta_auth", _COOKIE_NAME in cookies)

    # 2) Cookie válido? (ignorado enquanto logout pendente — evita relogin automático)
    token = cookies.get(_COOKIE_NAME)
    if token and not is_logout_pending():
        valid = _validate_token(str(token), cookie_key)
        _dbg("token_valido", valid)
        if valid:
            st.session_state[_AUTHED_KEY] = True
            clear_logout_pending()
            return

    # 3) Form de login — AUTH_PASSWORD (visualização) ou METAS_EDITOR_PASSWORD
    from src.metas_auth import (
        activate_metas_editor,
        expected_metas_editor_password,
        logout_metas_editor,
    )

    metas_password = expected_metas_editor_password()
    _dbg("auth_password_configured", bool(expected))
    _dbg("metas_editor_password_configured", bool(metas_password))
    pwd, submitted = _login_form()
    if submitted:
        days = _expiry_days()
        pwd_cmp = str(pwd).strip()
        if hmac.compare_digest(pwd_cmp, str(expected).strip()):
            logout_metas_editor()
            clear_logout_pending()
            _persist_dashboard_login(cookie_key, days)
            time.sleep(0.6)
            st.rerun()
        elif metas_password and hmac.compare_digest(
            pwd_cmp, str(metas_password).strip()
        ):
            clear_logout_pending()
            _persist_dashboard_login(cookie_key, days)
            activate_metas_editor(persist_cookie=True)
            st.session_state["_metas_editor_just_activated"] = True
            time.sleep(0.6)
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()  # nada mais é renderizado até logar
