"""Tune Scoring — calibration and configuration."""

from __future__ import annotations

import json

import streamlit as st

from scoring.v2.calibration import apply_proposal_to_config, propose_calibration, save_versioned_config
from scoring.v2.config import (
    get_scorer_mode,
    load_active_v2_config,
    load_v2_config,
    revert_to_initial_v2,
    revert_to_v1_legacy,
    set_active_config_path,
)
from scoring.v2.metric_metadata import display_name
from storage import get_store
from ui.components import render_empty_state
from ui.navigation import request_page
from operating_mode import get_active_mode, MODE_LABELS, render_active_mode_caption


CAL_LABELS = ("good", "okay", "bad")
CAL_HELP = {
    "good": "Controlled, smooth, and deliberate.",
    "okay": "Natural performance with minor corrections.",
    "bad": "Deliberately abrupt, hesitant, or inefficient.",
}


def _cal_button(label: str, key: str, css: str) -> bool:
    st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
    clicked = st.button(label.title(), key=key, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked


def render_tune_scoring(*, session_action) -> None:
    st.markdown("## Tune Scoring")
    mode = get_active_mode()
    render_active_mode_caption()
    store = get_store()
    scorer_mode = get_scorer_mode(get_store, mode=mode)
    cfg = load_active_v2_config(get_store, mode=mode)
    st.caption(
        f"Active scorer: **{scorer_mode}** · configuration version **{cfg.get('version')}** · "
        f"**{MODE_LABELS[mode]}**"
    )

    sec1, sec2, sec3 = st.tabs(
        ["Collect Calibration Data", "Stored Trials", "Thresholds & Configuration"]
    )

    with sec1:
        st.markdown("### Collect Calibration Data")
        op = st.text_input("Operator name", key="cal_operator")
        note = st.text_input("Note (optional)", key="cal_note_input")
        st.caption("Select a performance label, then start a calibration trial.")
        choice = st.session_state.get("calibration_label_choice")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                f'<div class="so-cal-btn-good {"so-cal-selected" if choice == "good" else ""}">',
                unsafe_allow_html=True,
            )
            if st.button("Good", use_container_width=True):
                st.session_state.calibration_label_choice = "good"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown(
                f'<div class="so-cal-btn-okay {"so-cal-selected" if choice == "okay" else ""}">',
                unsafe_allow_html=True,
            )
            if st.button("Okay", use_container_width=True):
                st.session_state.calibration_label_choice = "okay"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown(
                f'<div class="so-cal-btn-bad {"so-cal-selected" if choice == "bad" else ""}">',
                unsafe_allow_html=True,
            )
            if st.button("Bad", use_container_width=True):
                st.session_state.calibration_label_choice = "bad"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        if choice:
            st.info(f"**{choice.title()}** — {CAL_HELP[choice]}")
        if st.button(
            "Start Calibration Trial",
            type="primary",
            disabled=not choice or not op.strip(),
            use_container_width=True,
        ):
            from serial_manager import is_connected as sm_is_connected

            if not op.strip():
                st.error("Enter an operator name for calibration trials.")
            elif not sm_is_connected():
                st.error("Connect the device in the sidebar before starting a calibration trial.")
            else:
                st.session_state.calibration_pending = True
                st.session_state.calibration_label = choice
                st.session_state.calibration_operator = op
                st.session_state.calibration_note = note
                st.session_state.user_name_input = op
                from trial_context import snapshot_trial_context

                snapshot_trial_context(st.session_state)
                st.session_state.pending_calibration_start = True
                request_page("Live Trial")
                st.rerun()

    with sec2:
        st.markdown("### Stored Trials")
        source = st.selectbox("Filter", ["all", "manual_calibration", "normal"])
        src_f = None if source == "all" else source
        trials = store.list_trials(source_type=src_f, mode=mode, limit=200)
        if not trials:
            render_empty_state("No stored trials", "Completed and calibration trials appear here.")
        else:
            st.dataframe(
                [
                    {
                        "id": t["id"],
                        "trial": t["trial_id"],
                        "user": t.get("user_name"),
                        "source": t.get("source_type"),
                        "mode": t.get("mode", "open"),
                        "label": t.get("manual_label"),
                        "score": t.get("v2_overall"),
                        "at": t.get("created_at"),
                    }
                    for t in trials
                ],
                use_container_width=True,
                hide_index=True,
            )
        del_id = st.number_input("Delete trial by ID", min_value=0, step=1, value=0)
        if del_id > 0 and st.button("Delete selected trial"):
            if store.delete_trial(int(del_id)):
                st.session_state.trial_data_version = int(st.session_state.get("trial_data_version", 0)) + 1
            st.success("Trial deleted.")
            st.rerun()
        if st.checkbox("I understand this removes all trial records for this mode"):
            if st.button("Clear all trial data", type="secondary"):
                store.clear_trials(mode=mode)
                st.session_state.trial_data_version = int(st.session_state.get("trial_data_version", 0)) + 1
                st.warning(f"All {MODE_LABELS[mode]} trial data cleared. Scoring configuration preserved.")
                st.rerun()
        export_all = st.checkbox("Export all modes", value=False, key="export_all_modes")
        st.download_button(
            "Export trials CSV",
            store.export_csv(mode=None if export_all else mode),
            "smooth_operator_trials.csv",
            "text/csv",
        )

    with sec3:
        st.markdown("### Thresholds & Configuration")
        manual = store.list_trials(source_type="manual_calibration", mode=mode, limit=500)
        normal = store.list_trials(source_type="normal", mode=mode, limit=500)
        proposal = propose_calibration(manual, normal, base_config=load_v2_config())
        for p in proposal.get("proposals", []):
            dname = display_name(str(p["metric"]))
            status = "Consistent" if p.get("consistent") else "Needs review"
            st.markdown(f"**{dname}** — {status}")
            st.caption(
                f"Current Good/Okay/Needs work: {p['current']['good']} / {p['current']['okay']} / {p['current']['bad']}"
            )
            if p.get("consistent"):
                st.caption(
                    f"Proposed: {p['proposed']['good']} / {p['proposed']['okay']} / {p['proposed']['bad']} "
                    f"· samples {p.get('trial_counts')}"
                )
        c1, c2 = st.columns(2)
        if c1.button("Apply Proposed Calibration"):
            prev = st.session_state.get("calibration_preview") or proposal
            if not any(p.get("safe_to_apply") for p in prev.get("proposals", [])):
                st.error("Insufficient labeled data or inconsistent ordering.")
            else:
                new_cfg = apply_proposal_to_config(prev, version_suffix=mode)
                path = save_versioned_config(new_cfg)
                set_active_config_path(store, path, mode=mode)
                store.set_setting(f"scorer_mode_{mode}", "v2")
                st.success(f"Applied configuration {new_cfg['version']}")
        if c2.button("Preview details"):
            st.session_state.calibration_preview = proposal
        if st.session_state.get("calibration_preview"):
            with st.expander("Calibration preview (technical)"):
                st.json(st.session_state.calibration_preview)
        c3, c4 = st.columns(2)
        if c3.button("Revert to Initial V2"):
            revert_to_initial_v2(store, mode=mode)
            st.success(f"Reverted {MODE_LABELS[mode]} to initial V2 configuration.")
        if c4.button("Revert to Legacy V1 display"):
            revert_to_v1_legacy(store, mode=mode)
            st.warning(f"Live Trial will show V1 scores for {MODE_LABELS[mode]} until V2 is restored.")
        st.download_button(
            "Export calibration summary",
            json.dumps(proposal, indent=2),
            "calibration_summary.json",
            "application/json",
        )
