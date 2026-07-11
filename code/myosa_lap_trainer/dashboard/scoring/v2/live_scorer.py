"""Provisional live V2 scoring from LIVE telemetry."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from scoring.v2.config import load_active_v2_config
from scoring.v2.phases import firmware_state_to_phase
from scoring.v2.scorer import V2ScoreResult, _category_score, clamp_score, score_trial_v2


@dataclass
class LiveV2State:
    displayed_score: float = 0.0
    raw_overall: float = 0.0
    control_score: float = 0.0
    efficiency_score: float = 0.0
    target_stability_score: float | None = None
    phase: str = "approach"
    is_provisional: bool = True
    warnings: list[str] = field(default_factory=list)


def _live_to_partial_raw(live: dict[str, Any], elapsed_ms: int) -> dict[str, float | None]:
    gyro = _f(live.get("gyro_rms"))
    spike = _f(live.get("spike_rate"))
    elapsed_s = max(0.0, elapsed_ms / 1000.0)
    stable = live.get("stable")
    occ = live.get("occ", live.get("occluded"))
    hover_ms = _f(live.get("hover_ms"))

    raw: dict[str, float | None] = {
        "course_smoothness_gyro_rms": gyro,
        "correction_spike_rate": spike,
        "completion_time_s": elapsed_s if elapsed_s > 0 else None,
        "hesitation_pause_ms": None,
        "hover_interruptions": None,
        "hover_stable_pct": 100.0 if stable == 1 or stable == "1" else (0.0 if stable == 0 else None),
        "hover_target_cover_pct": 100.0 if occ == 1 or occ == "1" else (0.0 if occ == 0 else None),
        "hover_motion_gyro_rms": gyro if hover_ms else None,
        "target_acquisition_time_s": None,
    }
    return raw


def _f(val: Any) -> float | None:
    if val is None:
        return None
    try:
        x = float(val)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def compute_live_v2(
    live: dict[str, Any] | None,
    elapsed_ms: int,
    prev: LiveV2State | None = None,
    *,
    smooth_alpha: float = 0.35,
    config: dict[str, Any] | None = None,
) -> LiveV2State:
    cfg = config or load_active_v2_config()
    metric_defs = list(cfg.get("metrics", []))
    piecewise = cfg.get("piecewise_scores", {})
    cat_weights = cfg.get("category_weights", {})
    fw_state = str((live or {}).get("state", "APPROACH")).upper()
    phase = firmware_state_to_phase(fw_state)

    raw = _live_to_partial_raw(live or {}, elapsed_ms)
    by_cat: dict[str, list] = {}
    for spec in metric_defs:
        by_cat.setdefault(str(spec["category"]), []).append(spec)

    cat_scores: dict[str, float] = {}
    warnings: list[str] = []

    for cat, specs in by_cat.items():
        if cat == "target_stability" and phase == "approach":
            continue
        if cat == "target_stability" and phase == "finish":
            if prev and prev.target_stability_score is not None:
                cat_scores[cat] = prev.target_stability_score
            continue
        score, _, cat_warn = _category_score(specs, raw, piecewise)
        cat_scores[cat] = score
        warnings.extend(cat_warn)

    available = list(cat_scores.keys())
    if not available:
        overall = prev.raw_overall if prev else 50.0
    else:
        num = sum(cat_scores[c] * float(cat_weights.get(c, 0.33)) for c in available)
        den = sum(float(cat_weights.get(c, 0.33)) for c in available)
        overall = clamp_score(num / den) if den > 0 else 50.0

    state = LiveV2State(
        raw_overall=overall,
        control_score=cat_scores.get("control", prev.control_score if prev else 50.0),
        efficiency_score=cat_scores.get("efficiency", prev.efficiency_score if prev else 50.0),
        target_stability_score=cat_scores.get("target_stability"),
        phase=phase,
        is_provisional=True,
        warnings=warnings,
    )

    if prev:
        state.displayed_score = clamp_score(
            smooth_alpha * overall + (1.0 - smooth_alpha) * prev.displayed_score
        )
    else:
        state.displayed_score = overall

    if phase == "finish" and prev:
        state.displayed_score = prev.displayed_score

    return state


def final_v2_from_trial(
    final_row: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> V2ScoreResult:
    return score_trial_v2(final_row, config=config or load_active_v2_config())
