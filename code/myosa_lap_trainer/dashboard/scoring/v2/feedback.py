"""Live immediate feedback with priority rules and rate limiting."""

from __future__ import annotations

import time
from typing import Any


MESSAGES = {
    "smooth": "Smooth and controlled",
    "slow_down": "Slow down",
    "reduce_rotation": "Reduce wrist rotation",
    "reduce_linear": "Reduce abrupt linear motion",
    "fewer_corrections": "Fewer corrections",
    "keep_moving": "Keep moving steadily",
    "hold_steadier": "Hold steadier",
    "target_lost": "Target lost — reacquire",
    "stable_hover": "Stable hover",
    "press_red": "Press the red button",
}


def select_feedback(
    *,
    phase: str,
    live: dict[str, Any] | None,
    gyro: float,
    jerk: float,
    spike: float,
    stable: int | None,
    occ: int | None,
) -> str:
    phase = phase or "approach"
    if phase == "finish":
        return MESSAGES["press_red"]
    if phase == "stable_hover":
        if occ == 0:
            return MESSAGES["target_lost"]
        if stable == 0:
            return MESSAGES["hold_steadier"]
        if jerk > 1800:
            return MESSAGES["reduce_linear"]
        if gyro > 150:
            return MESSAGES["reduce_rotation"]
        return MESSAGES["stable_hover"]
    if spike > 8:
        return MESSAGES["fewer_corrections"]
    if jerk > 2200:
        return MESSAGES["reduce_linear"]
    if gyro > 200:
        return MESSAGES["reduce_rotation"]
    if gyro > 140:
        return MESSAGES["slow_down"]
    if spike > 5:
        return MESSAGES["fewer_corrections"]
    return MESSAGES["smooth"]


def rate_limited_feedback(
    new_msg: str,
    *,
    last_msg: str,
    last_change_ts: float,
    phase: str,
    prev_phase: str,
    min_interval: float = 1.0,
) -> tuple[str, float]:
    now = time.time()
    if new_msg == last_msg:
        return last_msg, last_change_ts
    if phase != prev_phase:
        return new_msg, now
    urgent = new_msg in (MESSAGES["target_lost"], MESSAGES["press_red"])
    if urgent or (now - last_change_ts) >= min_interval:
        return new_msg, now
    return last_msg, last_change_ts
