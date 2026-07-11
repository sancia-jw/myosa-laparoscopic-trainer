"""Map firmware states to visible task phases."""

from __future__ import annotations

PHASES = [
    ("approach", "Approach", "Tube entry, poles, pickup and transport"),
    ("stable_hover", "Stable Hover", "Acquire and maintain target coverage"),
    ("finish", "Finish", "Hover complete — press the red button"),
]

PHASE_ORDER = [p[0] for p in PHASES]


def firmware_state_to_phase(state: str) -> str:
    s = (state or "IDLE").upper()
    if s == "APPROACH":
        return "approach"
    if s == "HOVER":
        return "stable_hover"
    if s in ("DOCK", "COMPLETE"):
        return "finish"
    return "approach"


def phase_index(phase_key: str) -> int:
    try:
        return PHASE_ORDER.index(phase_key)
    except ValueError:
        return 0


def phase_label(phase_key: str) -> str:
    for key, label, _ in PHASES:
        if key == phase_key:
            return label
    return "Approach"
