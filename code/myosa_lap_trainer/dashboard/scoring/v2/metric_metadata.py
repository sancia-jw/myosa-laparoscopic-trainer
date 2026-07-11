"""Human-friendly metric labels and explanations for UI display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricMeta:
    key: str
    display_name: str
    explanation: str
    unit: str
    better: str  # "lower" | "higher"
    category: str
    interpretation_good: str = "Controlled and consistent."
    interpretation_okay: str = "Acceptable with room to improve."
    interpretation_bad: str = "Needs focused practice."


METRIC_METADATA: dict[str, MetricMeta] = {
    "course_smoothness_gyro_rms": MetricMeta(
        key="course_smoothness_gyro_rms",
        display_name="Rotational Smoothness",
        explanation=(
            "How consistently the instrument rotated during navigation. "
            "Lower rotational variability indicates more controlled handling."
        ),
        unit="deg/s",
        better="lower",
        category="control",
    ),
    "correction_spike_rate": MetricMeta(
        key="correction_spike_rate",
        display_name="Abrupt Motion Rate",
        explanation="How often sudden corrections or sharp movements were detected.",
        unit="events/s",
        better="lower",
        category="control",
    ),
    "course_jerk_rms": MetricMeta(
        key="course_jerk_rms",
        display_name="Linear Motion Control",
        explanation=(
            "How smoothly the instrument moved in a straight line after accounting for gravity. "
            "Lower values indicate fewer abrupt jolts."
        ),
        unit="mm/s³",
        better="lower",
        category="control",
    ),
    "completion_time_s": MetricMeta(
        key="completion_time_s",
        display_name="Completion Time",
        explanation="How long it took to complete the full task. Speed matters only after maintaining control.",
        unit="s",
        better="lower",
        category="efficiency",
    ),
    "hesitation_pause_ms": MetricMeta(
        key="hesitation_pause_ms",
        display_name="Hesitation Time",
        explanation="How much time the instrument remained inactive before the task was completed.",
        unit="ms",
        better="lower",
        category="efficiency",
    ),
    "hover_interruptions": MetricMeta(
        key="hover_interruptions",
        display_name="Hover Interruptions",
        explanation="How often stable target coverage was lost and had to be reacquired.",
        unit="count",
        better="lower",
        category="efficiency",
    ),
    "hover_stable_pct": MetricMeta(
        key="hover_stable_pct",
        display_name="Hover Stability",
        explanation="How steadily the instrument was held while covering the target.",
        unit="%",
        better="higher",
        category="target_stability",
    ),
    "hover_target_cover_pct": MetricMeta(
        key="hover_target_cover_pct",
        display_name="Target Coverage",
        explanation="How consistently the object remained positioned over the hover sensor.",
        unit="%",
        better="higher",
        category="target_stability",
    ),
    "hover_motion_gyro_rms": MetricMeta(
        key="hover_motion_gyro_rms",
        display_name="Hover Rotational Control",
        explanation="Rotational steadiness while maintaining hover over the target.",
        unit="deg/s",
        better="lower",
        category="target_stability",
    ),
    "hover_jerk_rms": MetricMeta(
        key="hover_jerk_rms",
        display_name="Hover Linear Stability",
        explanation="Linear motion smoothness while holding over the target.",
        unit="mm/s³",
        better="lower",
        category="target_stability",
    ),
    "target_acquisition_time_s": MetricMeta(
        key="target_acquisition_time_s",
        display_name="Target Acquisition Time",
        explanation="How long it took to reach and stabilize over the final target.",
        unit="s",
        better="lower",
        category="target_stability",
    ),
}

# Live telemetry keys mapped to display (may differ from scored metric keys)
LIVE_METRIC_ALIASES = {
    "gyro_rms": "course_smoothness_gyro_rms",
    "jerk_rms": "course_jerk_rms",
    "spike_rate": "correction_spike_rate",
}


def get_meta(key: str) -> MetricMeta | None:
    return METRIC_METADATA.get(key)


def display_name(key: str, fallback: str | None = None) -> str:
    meta = get_meta(key)
    if meta:
        return meta.display_name
    if fallback:
        return fallback
    return key.replace("_", " ").title()


def quality_badge(score: float | None) -> str:
    if score is None:
        return "—"
    if score >= 80:
        return "Good"
    if score >= 55:
        return "Okay"
    return "Needs Improvement"


def all_scored_keys(metric_defs: list[dict[str, Any]]) -> list[str]:
    keys = [str(m["name"]) for m in metric_defs]
    for extra in ("course_jerk_rms", "hover_jerk_rms"):
        if extra not in keys:
            keys.append(extra)
    return keys
