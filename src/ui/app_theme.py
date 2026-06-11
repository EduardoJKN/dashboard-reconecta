"""Tema global do dashboard (Dark / Light / System).

O padrão inicial vem de `.streamlit/config.toml` (`base = "dark"`).
A escolha do usuário fica em `st.session_state` e persiste durante a
navegação na mesma sessão.

Streamlit 1.56 ainda não expõe `st.set_theme()`; sincronizamos o tema
nativo via `st._config.set_option("theme.base", …)` quando o modo
efetivo muda. Os componentes customizados (cards, headers) seguem as CSS
variables `--color-*` injetadas a partir da paleta ativa.
"""
from __future__ import annotations

from typing import Literal

import streamlit as st
import streamlit.components.v1 as components

from .theme import GLOBAL_CSS_STATIC, PALETTE_DARK, PALETTE_LIGHT

ThemeMode = Literal["dark", "light", "system"]
ThemeBase = Literal["dark", "light"]

SESSION_KEY = "dashboard_theme_mode"
SYSTEM_RESOLVED_KEY = "_dashboard_theme_system_base"

THEME_CHOICES: dict[ThemeMode, str] = {
    "dark": "Dark",
    "light": "Light",
    "system": "System",
}

DEFAULT_THEME_MODE: ThemeMode = "dark"


def get_theme_mode() -> ThemeMode:
    """Modo escolhido pelo usuário (dark / light / system)."""
    if SESSION_KEY not in st.session_state:
        st.session_state[SESSION_KEY] = DEFAULT_THEME_MODE
    mode = st.session_state[SESSION_KEY]
    if mode not in THEME_CHOICES:
        st.session_state[SESSION_KEY] = DEFAULT_THEME_MODE
        return DEFAULT_THEME_MODE
    return mode  # type: ignore[return-value]


def _detect_system_prefers_dark() -> bool:
    """Melhor esforço para preferência do SO antes do probe em JS."""
    try:
        hints = st.context.headers.get_all("Sec-CH-Prefers-Color-Scheme")
        if hints:
            return hints[0].lower() == "dark"
    except Exception:
        pass
    return True


def get_active_palette_base() -> ThemeBase:
    """Base efetiva (dark/light) usada por Streamlit e pela paleta CSS."""
    mode = get_theme_mode()
    if mode == "dark":
        return "dark"
    if mode == "light":
        return "light"
    resolved = st.session_state.get(SYSTEM_RESOLVED_KEY)
    if resolved in ("dark", "light"):
        return resolved  # type: ignore[return-value]
    return "dark" if _detect_system_prefers_dark() else "light"


def get_active_palette() -> dict[str, str]:
    return PALETTE_DARK if get_active_palette_base() == "dark" else PALETTE_LIGHT


def _css_vars_block() -> str:
    palette = get_active_palette()
    lines = "\n".join(
        f"  --color-{k.replace('_', '-')}: {v};" for k, v in palette.items()
    )
    mode = get_theme_mode()
    return (
        f":root {{\n{lines}\n}}\n"
        f'html[data-dashboard-theme="{mode}"] {{ color-scheme: {get_active_palette_base()}; }}'
    )


def _sync_streamlit_base() -> None:
    """Alinha `theme.base` do Streamlit ao modo efetivo (melhor esforço)."""
    base = get_active_palette_base()
    try:
        if st._config.get_option("theme.base") != base:
            st._config.set_option("theme.base", base)
    except Exception:
        pass


def _run_system_theme_probe() -> None:
    """Detecta `prefers-color-scheme` no navegador quando modo = System."""
    if get_theme_mode() != "system":
        return

    detected = components.html(
        """
        <div id="rc-theme-probe"></div>
        <script>
        const send = () => {
            const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
            Streamlit.setComponentValue(dark ? "dark" : "light");
        };
        send();
        window.matchMedia("(prefers-color-scheme: dark)")
            .addEventListener("change", send);
        </script>
        """,
        height=0,
        key="rc_system_theme_probe",
    )

    if detected not in ("dark", "light"):
        return

    prev = st.session_state.get(SYSTEM_RESOLVED_KEY)
    if prev != detected:
        st.session_state[SYSTEM_RESOLVED_KEY] = detected
        _sync_streamlit_base()
        st.rerun()


def _theme_stylesheet() -> str:
    """Folha de estilos completa (variáveis + regras), sem tags HTML."""
    return f"{_css_vars_block()}\n{GLOBAL_CSS_STATIC}"


def apply_theme_css(theme_name: str | None = None) -> None:
    """Injeta fontes e CSS customizado sem exibir regras como texto na página."""
    if theme_name is not None and theme_name in THEME_CHOICES:
        st.session_state[SESSION_KEY] = theme_name

    st.markdown(
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">',
        unsafe_allow_html=True,
    )
    st.html(f"<style>\n{_theme_stylesheet()}\n</style>")


def apply_app_theme() -> None:
    """Injeta paleta + CSS global e sincroniza tema nativo do Streamlit."""
    _sync_streamlit_base()
    apply_theme_css()
    _run_system_theme_probe()


def _on_theme_mode_change() -> None:
    if st.session_state.get(SESSION_KEY) != "system":
        st.session_state.pop(SYSTEM_RESOLVED_KEY, None)


def render_theme_selector() -> None:
    """Seletor na sidebar — persiste em `st.session_state`."""
    st.divider()
    st.selectbox(
        "Tema do dashboard",
        options=list(THEME_CHOICES.keys()),
        format_func=lambda k: THEME_CHOICES[k],  # type: ignore[index]
        key=SESSION_KEY,
        on_change=_on_theme_mode_change,
        help="Dark é o padrão. System segue o tema do sistema operacional.",
    )
