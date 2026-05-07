"""Gate de autenticação por senha compartilhada com persistência via cookie.

Lê a senha esperada de:
1. `st.secrets["auth"]["password"]`  (produção, Streamlit Cloud)
2. variável de ambiente `AUTH_PASSWORD`  (local via .env)

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

API pública: `require_auth()` — única função exposta. Chame uma vez no
topo do `app.py`, logo após `apply_dark_theme()`.
"""
from __future__ import annotations

import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import extra_streamlit_components as stx
import jwt
import streamlit as st

_AUTHED_KEY = "_reconecta_authed"
_COOKIE_NAME = "reconecta_auth"
_DEFAULT_EXPIRY_DAYS = 7
_JWT_ALGO = "HS256"


# ---------------------------------------------------------------------------
# Resolução de configuração — secrets.toml > env, sem hardcode
# ---------------------------------------------------------------------------
def _from_secrets_or_env(secret_path: tuple[str, str],
                         env_name: str) -> str | None:
    """Lê de st.secrets[section][key] (preferido) com fallback pra env var."""
    section, key = secret_path
    try:
        if section in st.secrets and key in st.secrets[section]:
            val = st.secrets[section][key]
            if val:
                return str(val)
    except Exception:
        pass
    return os.getenv(env_name) or None


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
    if st.session_state.get(_AUTHED_KEY):
        return

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

    # CookieManager — `key` fixa identifica o componente entre reruns.
    cm = stx.CookieManager(key="reconecta_auth_cm")
    # `get_all()` força hidratação do componente. Sem isso, `get()` pode
    # devolver None na 1ª passada de uma sessão nova.
    cookies = cm.get_all() or {}

    _dbg("cookies_visiveis", list(cookies.keys()))
    _dbg("tem_reconecta_auth", _COOKIE_NAME in cookies)

    # 2) Cookie válido?
    token = cookies.get(_COOKIE_NAME)
    if token:
        valid = _validate_token(str(token), cookie_key)
        _dbg("token_valido", valid)
        if valid:
            st.session_state[_AUTHED_KEY] = True
            return

    # 3) Form de login
    pwd, submitted = _login_form()
    if submitted:
        if hmac.compare_digest(str(pwd), str(expected)):
            days = _expiry_days()
            new_token = _issue_token(cookie_key, days)
            # IMPORTANTE: usar datetime NAIVE (sem tz). O CookieManager
            # serializa via `.isoformat()` e o frontend JS espera o
            # formato ISO sem offset de tz (como o default do pacote, que
            # usa `datetime.datetime.now()`). Datetime tz-aware vira
            # `2026-05-14T20:22+00:00` que alguns parsers JS rejeitam.
            expires_at = datetime.now() + timedelta(days=days)
            _dbg("expires_at", expires_at.isoformat())
            # Parâmetros explícitos:
            #   - same_site="lax" (default do pacote é "strict", que pode
            #     impedir cookies de voltar em refreshes vindos de iframe;
            #     "lax" é o equivalente prático para sessão).
            #   - path="/" (default já é "/", explícito por clareza).
            #   - secure=None (default) → não força Secure flag,
            #     compatível com http://localhost.
            cm.set(
                _COOKIE_NAME, new_token,
                expires_at=expires_at,
                path="/",
                same_site="lax",
                key="reconecta_auth_set",
            )
            st.session_state[_AUTHED_KEY] = True
            # CRÍTICO: dar tempo do JS escrever o cookie ANTES do rerun.
            # `st.rerun()` descarta o output do run atual; sem este sleep,
            # o componente JS do `cm.set` pode não chegar ao browser e o
            # cookie nunca é gravado. ~0.5s é suficiente em LAN local;
            # Streamlit Cloud pode precisar de um pouco mais.
            time.sleep(0.6)
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()  # nada mais é renderizado até logar
