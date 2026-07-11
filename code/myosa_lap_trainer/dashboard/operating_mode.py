"""Open / Box operating mode — session helpers and UI."""

from __future__ import annotations

from typing import Any

import streamlit as st

MODES = ("open", "box")
DEFAULT_MODE = "open"
ALL_MODES = "all"

MODE_LABELS = {
    "open": "Open Mode",
    "box": "Box Mode",
}
MODE_SHORT = {
    "open": "OPEN",
    "box": "BOX",
}


def normalize_mode(mode: str | None) -> str:
    m = str(mode or DEFAULT_MODE).lower().strip()
    return m if m in MODES else DEFAULT_MODE


def get_active_mode(state: dict[str, Any] | None = None) -> str:
    if state is None:
        state = st.session_state
    return normalize_mode(state.get("operating_mode"))


def is_trial_running(state: dict[str, Any] | None = None) -> bool:
    if state is None:
        state = st.session_state
    return str(state.get("session", "READY")).upper() == "RUNNING"


def persist_thresholds_for_active_mode(state: dict[str, Any]) -> None:
    mode = get_active_mode(state)
    thresholds = state.get("thresholds")
    if thresholds:
        cache = state.setdefault("thresholds_by_mode", {})
        cache[mode] = dict(thresholds)


def apply_mode_thresholds(state: dict[str, Any], mode: str) -> None:
    cache = state.setdefault("thresholds_by_mode", {})
    state["thresholds"] = dict(cache.get(normalize_mode(mode), {}))


def request_mode_switch(state: dict[str, Any], new_mode: str) -> bool:
    target = normalize_mode(new_mode)
    if get_active_mode(state) == target:
        return False
    if is_trial_running(state):
        return False
    persist_thresholds_for_active_mode(state)
    state["operating_mode"] = target
    apply_mode_thresholds(state, target)
    state["trial_data_version"] = int(state.get("trial_data_version", 0)) + 1
    return True


def render_operating_mode_switch(*, key_prefix: str = "sidebar") -> None:
    """Two-position OPEN / BOX switch beside connection controls."""
    mode = get_active_mode()
    blocked = is_trial_running()
    st.markdown("**Operating mode**")
    if blocked:
        st.caption(f"Active: **{MODE_LABELS[mode]}** — locked during trial")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "OPEN",
            type="primary" if mode == "open" else "secondary",
            disabled=blocked or mode == "open",
            use_container_width=True,
            key=f"{key_prefix}_mode_open",
        ):
            if request_mode_switch(st.session_state, "open"):
                st.rerun()
    with c2:
        if st.button(
            "BOX",
            type="primary" if mode == "box" else "secondary",
            disabled=blocked or mode == "box",
            use_container_width=True,
            key=f"{key_prefix}_mode_box",
        ):
            if request_mode_switch(st.session_state, "box"):
                st.rerun()
    st.markdown(
        f'<p class="so-mode-badge so-mode-{mode}">{MODE_LABELS[mode]}</p>',
        unsafe_allow_html=True,
    )


def render_active_mode_caption() -> None:
    mode = get_active_mode()
    st.caption(f"Viewing **{MODE_LABELS[mode]}** data")


def render_mode_history_filter(*, key: str) -> str | None:
    """History filter: defaults to active mode; None means all modes."""
    active = get_active_mode()
    labels = [MODE_SHORT["open"], MODE_SHORT["box"], "All Modes"]
    default_idx = 0 if active == "open" else 1
    choice = st.radio("Mode", labels, horizontal=True, index=default_idx, key=key)
    if choice == "All Modes":
        return None
    return "open" if choice == "OPEN" else "box"
