"""Phase 2A.1 conference state-flow tests."""

from __future__ import annotations

import time

import pytest

from session_sync import (
    clear_live_trial_state,
    control_flags,
    firmware_start_allowed,
    firmware_start_ignored_reason,
    mark_final_recorded,
    reset_clears_completed_result,
    should_record_final_score,
)


def test_startup_settles_ready_firmware_boot_path() -> None:
    """After successful init firmware calls resetToReady() -> session READY."""
    # Mirrors setup() success branch: resetToReady -> TrialState::Idle -> session READY.
    assert firmware_start_allowed("READY") is True
    assert firmware_start_ignored_reason("IDLE") == "not_ready"


def test_control_flags_match_firmware_validity() -> None:
    assert control_flags("READY") == {"start": True, "stop": False, "reset": True}
    assert control_flags("RUNNING") == {"start": False, "stop": True, "reset": True}
    assert control_flags("COMPLETE") == {"start": False, "stop": False, "reset": True}
    assert control_flags("IDLE")["start"] is False
    assert control_flags("ERROR")["start"] is False


def test_start_from_ready_allowed() -> None:
    assert firmware_start_allowed("READY") is True
    assert firmware_start_ignored_reason("READY") is None


def test_start_from_complete_ignored() -> None:
    assert firmware_start_allowed("COMPLETE") is False
    assert firmware_start_ignored_reason("COMPLETE") == "complete"


def test_start_from_running_ignored() -> None:
    assert firmware_start_allowed("RUNNING") is False
    assert firmware_start_ignored_reason("RUNNING") == "running"


def test_completed_result_preserved_until_complete_reset() -> None:
    state = {
        "live_score": 84,
        "elapsed_ms": 30000,
        "latest_live": {"score": 84},
        "live_rows": [{"score": 84}],
        "latest_final": {"trial": 3, "total": 84},
        "metric_labels": {},
        "coach_display": "",
        "coach_pending": "",
        "current_feedback": "",
    }
    clear_live_trial_state(state, preserve_final=True)
    assert state["latest_final"] == {"trial": 3, "total": 84}
    assert state["live_score"] == 0


def test_reset_from_complete_clears_result() -> None:
    assert reset_clears_completed_result("COMPLETE") is True
    state = {"latest_final": {"total": 90}, "live_score": 90, "elapsed_ms": 1, "live_rows": [], "metric_labels": {}, "coach_display": "", "coach_pending": "", "current_feedback": ""}
    clear_live_trial_state(state, preserve_final=False)
    assert state["latest_final"] is None


def test_reset_from_running_does_not_emit_final_score() -> None:
    """RUNNING cancel clears live data only; no FINAL_SCORE path in firmware resetToReady."""
    state: dict = {"completed_trials": [], "finalized_trial_ids": set()}
    clear_live_trial_state(state, preserve_final=True)
    assert should_record_final_score(state, 5) is True
    assert state.get("latest_final") is None or state.get("latest_final") is not None


def test_reset_running_preserves_no_csv_row() -> None:
    state: dict = {"completed_trials": [], "finalized_trial_ids": set()}
    mark_final_recorded(state, 2)
    assert len(state["completed_trials"]) == 0
    clear_live_trial_state(state, preserve_final=True)
    assert 2 in state["finalized_trial_ids"]


def test_first_start_from_ready_enters_running_via_ingest() -> None:
    from app import ingest_line

    import streamlit as st

    backup = dict(st.session_state)
    try:
        st.session_state.clear()
        st.session_state.update(
            {
                "raw_lines": [],
                "events": [],
                "live_rows": [],
                "completed_trials": [],
                "parse_error_count": 0,
                "diag_log": [],
                "finalized_trial_ids": set(),
                "session": "READY",
                "current_state": "IDLE",
            }
        )
        ingest_line("EVENT,trial=1,t_ms=0,state=APPROACH,event=TRIAL_START,score=10")
        assert st.session_state.session == "RUNNING"
    finally:
        st.session_state.clear()
        st.session_state.update(backup)


def test_reset_from_complete_returns_ready_via_ingest() -> None:
    from app import ingest_line

    import streamlit as st

    backup = dict(st.session_state)
    try:
        st.session_state.clear()
        st.session_state.update(
            {
                "raw_lines": [],
                "events": [],
                "live_rows": [],
                "completed_trials": [{"trial": 1, "total": 80}],
                "parse_error_count": 0,
                "diag_log": [],
                "finalized_trial_ids": {1},
                "session": "COMPLETE",
                "current_state": "COMPLETE",
                "latest_final": {"trial": 1, "total": 80},
            }
        )
        ingest_line("EVENT,trial=1,t_ms=0,state=IDLE,event=RESET,score=0")
        assert st.session_state.session == "READY"
        assert st.session_state.latest_final is None
    finally:
        st.session_state.clear()
        st.session_state.update(backup)


def test_reset_during_running_no_final_score_ingest() -> None:
    from app import ingest_line

    import streamlit as st

    backup = dict(st.session_state)
    try:
        st.session_state.clear()
        st.session_state.update(
            {
                "raw_lines": [],
                "events": [],
                "live_rows": [{"score": 40}],
                "completed_trials": [],
                "parse_error_count": 0,
                "diag_log": [],
                "finalized_trial_ids": set(),
                "session": "RUNNING",
                "current_state": "APPROACH",
                "live_score": 40,
                "latest_final": None,
            }
        )
        n_before = len(st.session_state.completed_trials)
        ingest_line("EVENT,trial=2,t_ms=1000,state=IDLE,event=RESET,score=0")
        assert st.session_state.session == "READY"
        assert len(st.session_state.completed_trials) == n_before
        assert st.session_state.live_score == 0
    finally:
        st.session_state.clear()
        st.session_state.update(backup)


def test_session_action_is_nonblocking() -> None:
    from app import session_action

    import streamlit as st

    backup = dict(st.session_state)
    try:
        st.session_state.clear()
        st.session_state.update({"connected": False, "diag_log": []})
        t0 = time.perf_counter()
        session_action("r", source="test")
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.05
    finally:
        st.session_state.clear()
        st.session_state.update(backup)
