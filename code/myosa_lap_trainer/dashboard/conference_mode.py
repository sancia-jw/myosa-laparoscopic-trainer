"""Conference mode — session helpers and participant handling."""

from __future__ import annotations

from typing import Any

import streamlit as st

from operating_mode import is_trial_running


def is_conference_mode(state: dict[str, Any] | None = None) -> bool:
    if state is None:
        state = st.session_state
    return bool(state.get("conference_mode"))


def participant_display_name(name: str | None) -> str | None:
    if not name:
        return None
    trimmed = str(name).strip()
    return trimmed if trimmed else None


def participant_key(name: str | None) -> str:
    trimmed = participant_display_name(name)
    return trimmed.lower() if trimmed else ""


def render_conference_mode_controls(*, key_prefix: str = "sidebar") -> None:
    """Conference toggle and leaderboard utilities in the sidebar."""
    blocked = is_trial_running()
    st.markdown("**Conference mode**")
    enabled = is_conference_mode()
    if blocked:
        st.caption("Locked during active trial")
    new_val = st.toggle(
        "Enable conference mode",
        value=enabled,
        disabled=blocked,
        key=f"{key_prefix}_conference_toggle",
    )
    if new_val != enabled and not blocked:
        st.session_state.conference_mode = new_val
        st.rerun()
    if is_conference_mode():
        st.caption("Participant name required before each trial.")
        st.link_button(
            "Open leaderboard display",
            "http://localhost:8502",
            use_container_width=True,
        )
        with st.expander("Clear conference leaderboard", expanded=False):
            st.caption("Removes conference trials only. Regular history and calibration are kept.")
            if st.checkbox("I understand this clears all conference leaderboard entries", key=f"{key_prefix}_conf_clear_ack"):
                if st.button("Clear conference data", type="secondary", key=f"{key_prefix}_conf_clear_btn"):
                    from storage import get_store

                    removed = get_store().clear_conference_trials()
                    st.session_state.trial_data_version = int(st.session_state.get("trial_data_version", 0)) + 1
                    st.success(f"Cleared {removed} conference trial(s).")
                    st.rerun()
