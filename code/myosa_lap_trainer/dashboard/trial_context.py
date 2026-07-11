"""Trial metadata snapshot — survives Streamlit reruns through completion."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from operating_mode import get_active_mode


def normalize_operator_name(name: str | None) -> str | None:
    if not name:
        return None
    trimmed = str(name).strip()
    return trimmed if trimmed else None


def snapshot_trial_context(state: dict[str, Any], *, firmware_trial_id: int | None = None) -> dict[str, Any]:
    """Capture operator and calibration metadata at trial start."""
    if state.get("calibration_pending"):
        op = normalize_operator_name(state.get("calibration_operator"))
        source_type = "manual_calibration"
        manual_label = state.get("calibration_label")
        notes = (state.get("calibration_note") or "").strip() or None
    else:
        op = normalize_operator_name(state.get("user_name_input"))
        source_type = "normal"
        manual_label = None
        notes = None

    ctx = {
        "operator_name": op,
        "display_name": op,
        "source_type": source_type,
        "manual_label": manual_label,
        "notes": notes,
        "mode": get_active_mode(state),
        "conference_mode": bool(state.get("conference_mode")),
        "firmware_trial_id": firmware_trial_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    state["active_trial_context"] = ctx
    return ctx


def context_for_save(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("active_trial_context") or {})


def clear_trial_context(state: dict[str, Any]) -> None:
    state.pop("active_trial_context", None)
