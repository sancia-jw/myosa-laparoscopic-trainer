"""Pure session-sync helpers for dashboard state (testable without Streamlit UI)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

DIAG_LOG_MAX = 80


def append_diag(state: dict[str, Any], msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log: list[str] = state.setdefault("diag_log", [])
    log.append(f"[{ts}] {msg}")
    if len(log) > DIAG_LOG_MAX:
        state["diag_log"] = log[-DIAG_LOG_MAX:]


def clear_live_trial_state(
    state: dict[str, Any],
    *,
    feedback: str = "Position the instrument and press Start.",
    preserve_final: bool = False,
) -> None:
    state["live_score"] = 0
    state["elapsed_ms"] = 0
    state["latest_live"] = None
    state["live_rows"] = []
    if not preserve_final:
        state["latest_final"] = None
    state["metric_labels"] = {}
    state["coach_display"] = feedback
    state["coach_pending"] = ""
    state["current_feedback"] = feedback


def should_record_final_score(state: dict[str, Any], trial_id: int | None) -> bool:
    if trial_id is None:
        return True
    finalized: set[int] = state.setdefault("finalized_trial_ids", set())
    return trial_id not in finalized


def mark_final_recorded(state: dict[str, Any], trial_id: int | None) -> None:
    if trial_id is None:
        return
    finalized: set[int] = state.setdefault("finalized_trial_ids", set())
    finalized.add(trial_id)


def control_flags(session: str) -> dict[str, bool]:
    """Enable/disable dashboard trial controls by user-facing session state."""
    s = (session or "IDLE").upper()
    return {
        "start": s == "READY",
        "stop": s == "RUNNING",
        "reset": s in ("IDLE", "READY", "RUNNING", "COMPLETE", "ERROR"),
    }


def firmware_start_allowed(session: str) -> bool:
    return (session or "").upper() == "READY"


def firmware_start_ignored_reason(session: str) -> str | None:
    s = (session or "").upper()
    if s == "READY":
        return None
    if s == "RUNNING":
        return "running"
    if s == "COMPLETE":
        return "complete"
    if s == "ERROR":
        return "error"
    return "not_ready"


def reset_clears_completed_result(prev_session: str) -> bool:
    return (prev_session or "").upper() == "COMPLETE"
