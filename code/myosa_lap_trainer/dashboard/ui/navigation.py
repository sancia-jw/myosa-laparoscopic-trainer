"""Page navigation without mutating widget-bound session state."""

from __future__ import annotations

import streamlit as st

NAV_PAGES = ["Live Trial", "Trial Breakdown", "Track Progress", "Tune Scoring"]

PAGE_STYLES = {
    "Live Trial": ("so-tab-live", "so-page-live"),
    "Trial Breakdown": ("so-tab-breakdown", "so-page-breakdown"),
    "Track Progress": ("so-tab-progress", "so-page-progress"),
    "Tune Scoring": ("so-tab-tune", "so-page-tune"),
}


def apply_pending_page() -> None:
    pending = st.session_state.pop("pending_page", None)
    if pending in NAV_PAGES:
        st.session_state.active_page = pending


def request_page(page: str) -> None:
    if page in NAV_PAGES:
        st.session_state.pending_page = page


def _set_page(page: str) -> None:
    st.session_state.active_page = page


def render_page_tabs() -> str:
    apply_pending_page()
    active = st.session_state.get("active_page", NAV_PAGES[0])
    if active not in NAV_PAGES:
        active = NAV_PAGES[0]
        st.session_state.active_page = active

    _, page_shell = PAGE_STYLES.get(active, ("", "so-page-live"))

    st.markdown('<div class="so-nav-wrap">', unsafe_allow_html=True)
    cols = st.columns(len(NAV_PAGES))
    for col, page in zip(cols, NAV_PAGES):
        tab_cls, _ = PAGE_STYLES[page]
        is_active = page == active
        btn_type = "primary" if is_active else "secondary"
        with col:
            st.markdown(
                f'<div class="so-nav-btn-wrap {tab_cls} {"so-nav-active" if is_active else "so-nav-inactive"}">',
                unsafe_allow_html=True,
            )
            st.button(
                page,
                key=f"page_tab_{page}",
                type=btn_type,
                use_container_width=True,
                on_click=_set_page,
                args=(page,),
            )
            st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(f'<div class="so-page-shell {page_shell}">', unsafe_allow_html=True)
    return active


def close_page_shell() -> None:
    st.markdown("</div>", unsafe_allow_html=True)
