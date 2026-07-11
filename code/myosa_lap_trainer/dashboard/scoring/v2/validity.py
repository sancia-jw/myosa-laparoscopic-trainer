"""Trial completion validity — hover dwell is mandatory for scored results."""

from __future__ import annotations

from typing import Any


DEFAULT_HOVER_DWELL_MS = 2000


def required_hover_dwell_ms(thresholds: dict[str, Any] | None = None) -> int:
    if thresholds and thresholds.get("hover_dwell_ms"):
        try:
            return int(thresholds["hover_dwell_ms"])
        except (TypeError, ValueError):
            pass
    return DEFAULT_HOVER_DWELL_MS


def assess_trial_validity(
    final_row: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
    phase_timestamps: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Return (is_valid, user_message).
    Successful hover is mandatory for a normal final V2 result.
    """
    required_ms = required_hover_dwell_ms(thresholds)
    hover_ms = final_row.get("hover_ms")
    try:
        hover_ms_i = int(float(hover_ms)) if hover_ms is not None else 0
    except (TypeError, ValueError):
        hover_ms_i = 0

    hover_complete = bool(phase_timestamps and phase_timestamps.get("hover_complete"))
    if not hover_complete and hover_ms_i < required_ms:
        return False, "Incomplete — stable hover not completed."

    if hover_ms_i < int(required_ms * 0.95):
        return False, "Incomplete — stable hover not completed."

    stable_pct = final_row.get("hover_stable_pct")
    if stable_pct is not None:
        try:
            if float(stable_pct) < 40.0:
                return False, "Incomplete — stable hover not completed."
        except (TypeError, ValueError):
            pass

    cover_pct = final_row.get("hover_occluded_pct")
    if cover_pct is not None:
        try:
            if float(cover_pct) < 50.0:
                return False, "Incomplete — stable hover not completed."
        except (TypeError, ValueError):
            pass

    return True, "Trial complete."
