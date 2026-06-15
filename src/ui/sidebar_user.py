"""Menu de conta do usuário na sidebar (perfil local em session_state)."""
from __future__ import annotations

import base64
import html
from typing import NamedTuple

import streamlit as st

_PROFILE_NAME_KEY = "sidebar_user_display_name"
_PROFILE_PHOTO_KEY = "sidebar_user_profile_photo_bytes"
_PROFILE_PHOTO_MIME_KEY = "sidebar_user_profile_photo_mime"
_PANEL_KEY = "sidebar_account_panel"
_MENU_OPEN_KEY = "sidebar_account_menu_open"


class AccountInfo(NamedTuple):
    initials: str
    default_name: str
    badge_label: str
    is_editor: bool


def clear_user_profile_state() -> None:
    """Remove personalizações locais (chamar no logout completo)."""
    for key in (
        _PROFILE_NAME_KEY,
        _PROFILE_PHOTO_KEY,
        _PROFILE_PHOTO_MIME_KEY,
        _PANEL_KEY,
        _MENU_OPEN_KEY,
    ):
        st.session_state.pop(key, None)


def _account_info() -> AccountInfo:
    from src.metas_auth import is_metas_editor_authenticated

    is_editor = is_metas_editor_authenticated()
    if is_editor:
        return AccountInfo("EM", "Editor de Metas", "Editor", True)
    return AccountInfo("BI", "Reconecta BI", "Visualização", False)


def _custom_display_name() -> str | None:
    raw = st.session_state.get(_PROFILE_NAME_KEY)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def get_display_name() -> str:
    custom = _custom_display_name()
    if custom:
        return custom
    return _account_info().default_name


def _profile_photo() -> tuple[bytes, str] | None:
    data = st.session_state.get(_PROFILE_PHOTO_KEY)
    if not data:
        return None
    mime = str(st.session_state.get(_PROFILE_PHOTO_MIME_KEY) or "image/png")
    return bytes(data), mime


def _avatar_initials(display_name: str, fallback: str) -> str:
    custom = _custom_display_name()
    if not custom and not _profile_photo():
        return fallback
    parts = [p for p in display_name.split() if p]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    if parts:
        return parts[0][:2].upper()
    return fallback


def _avatar_html(display_name: str, info: AccountInfo) -> str:
    photo = _profile_photo()
    if photo:
        b64 = base64.b64encode(photo[0]).decode("ascii")
        return (
            f'<img class="sidebar-user-avatar-img" '
            f'src="data:{html.escape(photo[1])};base64,{b64}" '
            f'alt="Avatar" />'
        )
    initials = html.escape(_avatar_initials(display_name, info.initials))
    return f'<div class="sidebar-user-avatar">{initials}</div>'


def _render_back_button() -> None:
    if st.button("← Voltar", key="sidebar_account_back", use_container_width=True):
        st.session_state.pop(_PANEL_KEY, None)
        st.rerun()


def _render_photo_panel() -> None:
    st.markdown("**Trocar foto de perfil**")
    st.caption("PNG, JPG ou WebP · salvo só nesta sessão.")
    uploaded = st.file_uploader(
        "Enviar foto",
        type=["png", "jpg", "jpeg", "webp"],
        key="sidebar_profile_upload",
        label_visibility="collapsed",
    )
    if uploaded is not None:
        st.session_state[_PROFILE_PHOTO_KEY] = uploaded.getvalue()
        st.session_state[_PROFILE_PHOTO_MIME_KEY] = uploaded.type or "image/png"
        st.success("Foto atualizada.")
    photo = _profile_photo()
    if photo:
        st.image(photo[0], caption="Pré-visualização", width=88)
        if st.button("Remover foto", key="sidebar_profile_remove", use_container_width=True):
            st.session_state.pop(_PROFILE_PHOTO_KEY, None)
            st.session_state.pop(_PROFILE_PHOTO_MIME_KEY, None)
            st.rerun()
    _render_back_button()


def _render_name_panel() -> None:
    st.markdown("**Alterar nome exibido**")
    info = _account_info()
    current = _custom_display_name() or info.default_name
    new_name = st.text_input(
        "Nome na sidebar",
        value=current,
        max_chars=48,
        key="sidebar_profile_name_input",
        placeholder=info.default_name,
    )
    c_save, c_reset = st.columns(2, gap="small")
    with c_save:
        if st.button("Salvar", key="sidebar_profile_name_save", use_container_width=True):
            text = str(new_name).strip()
            if text:
                st.session_state[_PROFILE_NAME_KEY] = text
            else:
                st.session_state.pop(_PROFILE_NAME_KEY, None)
            st.session_state.pop(_PANEL_KEY, None)
            st.rerun()
    with c_reset:
        if st.button("Padrão", key="sidebar_profile_name_reset", use_container_width=True):
            st.session_state.pop(_PROFILE_NAME_KEY, None)
            st.session_state.pop(_PANEL_KEY, None)
            st.rerun()
    _render_back_button()


def _render_permissions_panel() -> None:
    st.markdown("**Permissões**")
    info = _account_info()
    if info.is_editor:
        st.caption(
            "Modo **Editor de Metas**. Pode editar, carregar e salvar metas "
            "no Funil da Reconecta."
        )
    else:
        st.caption(
            "Modo **Visualização**. Pode consultar o dashboard, mas não "
            "editar ou salvar metas."
        )
    _render_back_button()


def _render_account_menu() -> None:
    panel = st.session_state.get(_PANEL_KEY)
    if panel == "photo":
        _render_photo_panel()
        return
    if panel == "name":
        _render_name_panel()
        return
    if panel == "permissions":
        _render_permissions_panel()
        return

    st.markdown('<p class="sidebar-account-section">Perfil</p>', unsafe_allow_html=True)
    if st.button("Trocar foto de perfil", key="sidebar_menu_photo", use_container_width=True):
        st.session_state[_PANEL_KEY] = "photo"
        st.rerun()
    if st.button("Alterar nome exibido", key="sidebar_menu_name", use_container_width=True):
        st.session_state[_PANEL_KEY] = "name"
        st.rerun()

    st.markdown('<p class="sidebar-account-section">Conta</p>', unsafe_allow_html=True)
    if st.button("Ver permissões", key="sidebar_menu_permissions", use_container_width=True):
        st.session_state[_PANEL_KEY] = "permissions"
        st.rerun()

    info = _account_info()
    if info.is_editor:
        if st.button(
            "Sair do modo editor",
            key="sidebar_menu_leave_editor",
            use_container_width=True,
        ):
            from src.auth import logout_dashboard

            logout_dashboard()

    if st.button("Trocar acesso", key="sidebar_menu_logout", use_container_width=True):
        from src.auth import logout_dashboard

        logout_dashboard()


def render_sidebar_user_block() -> None:
    """Card compacto: avatar | conteúdo (nome → tag → trocar) | engrenagem."""
    info = _account_info()
    display_name = get_display_name()
    badge_cls = "editor" if info.is_editor else "viewer"
    avatar = _avatar_html(display_name, info)
    badge_text = html.escape(info.badge_label.upper())

    st.markdown(
        '<div class="sidebar-user-card-marker" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    col_avatar, col_content, col_gear = st.columns([0.15, 0.7, 0.15], gap="small")

    with col_avatar:
        st.markdown(
            f'<div class="sidebar-user-avatar-col">{avatar}</div>',
            unsafe_allow_html=True,
        )

    with col_content:
        st.markdown(
            f'<div class="sidebar-user-name">{html.escape(display_name)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="sidebar-user-role-wrap">'
            f'<span class="sidebar-user-badge sidebar-user-badge--{badge_cls}">'
            f"{badge_text}</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="sidebar-user-switch-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        if st.button("Trocar acesso", key="sidebar_card_swap_access"):
            from src.auth import logout_dashboard

            logout_dashboard()

    with col_gear:
        with st.popover(
            "⚙",
            help="Configurações da conta",
            use_container_width=False,
        ):
            _render_account_menu()
