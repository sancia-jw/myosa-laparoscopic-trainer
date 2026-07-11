"""
MYOSA Lap Trainer — Legacy V1 scorer (conference-safe).

Faithful Python port of the scoring logic in firmware `src/main.cpp`.
This is the pre-calibration, pre-V2 scorer preserved for rollback.

Do NOT modify formulas here without running:
  python -m pytest tests/test_old_scorer_equivalence.py -v

The firmware remains the runtime authority during live trials; this module
enables offline replay, regression checks, and future scorer switching.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).with_name("old_scoring_config.json")


def _load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or _CONFIG_PATH
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def clamp_score(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def compute_rms(sumsq: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return math.sqrt(sumsq / float(count))


def penalty_ramp(val: float, good: float, bad: float, max_pen: float) -> float:
    if val <= good:
        return 0.0
    if val >= bad:
        return max_pen
    if bad == good:
        return max_pen
    return max_pen * (val - good) / (bad - good)


@dataclass
class CalibrationState:
    """Optional per-trial reference calibration (serial `c` on firmware)."""

    course_gyro_rms: float = 0.0
    course_jerk_rms: float = 0.0
    course_spike_rate: float = 0.0
    hover_gyro_rms: float = 0.0
    hover_jerk_rms: float = 0.0
    dock_jerk_peak: float = 0.0


@dataclass
class TrialMetrics:
    """Mirrors firmware TrialMetrics (src/main.cpp)."""

    trial_id: int = 0
    trial_start_ms: int = 0
    hover_enter_ms: int = 0
    hover_complete_ms: int = 0
    dock_complete_ms: int = 0
    approach_time_ms: int = 0
    hover_time_ms: int = 0
    dock_time_ms: int = 0
    total_trial_time_ms: int = 0
    got_trial_start: bool = False
    got_hover_enter: bool = False
    got_hover_complete: bool = False
    got_dock_complete: bool = False

    course_sample_count: int = 0
    course_gyro_sumsq: float = 0.0
    course_jerk_sumsq: float = 0.0
    course_gyro_spike_count: int = 0
    course_jerk_spike_count: int = 0
    course_pause_time_ms: int = 0
    course_tilt_sumsq: float = 0.0
    course_tilt_samples: int = 0

    hover_reset_count: int = 0
    occlusion_loss_count: int = 0
    hover_total_samples: int = 0
    hover_stable_samples: int = 0
    hover_unstable_sample_count: int = 0
    hover_occluded_samples: int = 0
    hover_gyro_sumsq: float = 0.0
    hover_jerk_sumsq: float = 0.0
    hover_tilt_sumsq: float = 0.0
    hover_tilt_samples: int = 0

    tilt_deg_max: float = 0.0
    tilt_over_limit_time_ms: int = 0
    tilt_deg_rms_course: float = 0.0
    tilt_deg_rms_hover: float = 0.0

    dock_jerk_peak_recent: float = 0.0
    dock_gyro_peak_recent: float = 0.0

    course_score: int = 0
    hover_score: int = 0
    axis_score: int = 0
    flow_score: int = 0
    target_score: int = 0
    dock_score: int = 0
    total_score: int = 0

    pen_course: int = 0
    pen_hover: int = 0
    pen_axis: int = 0
    pen_flow: int = 0
    pen_target: int = 0
    pen_dock: int = 0

    feedback: str = ""


class OldScorer:
    """
    Pre-calibration conference-safe scorer (V1 / legacy).

    Reproduces firmware scoring with default thresholds. Optional
    CalibrationState mirrors firmware `g_score_calibrated` behavior.
    """

    VERSION = "v1_legacy"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        calibration: CalibrationState | None = None,
        calibrated: bool = False,
    ) -> None:
        self.config = config or _load_config()
        self.calibration = calibration or CalibrationState()
        self.calibrated = calibrated

    # --- effective thresholds (eff* in firmware) ---

    def _eff_course_gyro_good(self) -> float:
        c = self.config["calibration"]
        d = self.config["course"]
        if self.calibrated:
            return max(
                self.calibration.course_gyro_rms * c["course_gyro_good_scale"],
                c["course_gyro_good_floor"],
            )
        return d["gyro_rms_good"]

    def _eff_course_gyro_bad(self) -> float:
        c = self.config["calibration"]
        d = self.config["course"]
        if self.calibrated:
            return max(
                self.calibration.course_gyro_rms * c["course_gyro_bad_scale"],
                self._eff_course_gyro_good() + c["course_gyro_bad_min_offset"],
            )
        return d["gyro_rms_bad"]

    def _eff_course_jerk_good(self) -> float:
        c = self.config["calibration"]
        d = self.config["course"]
        if self.calibrated:
            return max(
                self.calibration.course_jerk_rms * c["course_jerk_good_scale"],
                c["course_jerk_good_floor"],
            )
        return d["jerk_rms_good"]

    def _eff_course_jerk_bad(self) -> float:
        c = self.config["calibration"]
        d = self.config["course"]
        if self.calibrated:
            return max(
                self.calibration.course_jerk_rms * c["course_jerk_bad_scale"],
                self._eff_course_jerk_good() + c["course_jerk_bad_min_offset"],
            )
        return d["jerk_rms_bad"]

    def _eff_course_spike_good(self) -> float:
        c = self.config["calibration"]
        d = self.config["course"]
        if self.calibrated:
            return max(
                self.calibration.course_spike_rate * c["course_spike_good_scale"],
                c["course_spike_good_floor"],
            )
        return d["spike_rate_good"]

    def _eff_course_spike_bad(self) -> float:
        c = self.config["calibration"]
        d = self.config["course"]
        if self.calibrated:
            scaled = self.calibration.course_spike_rate * c["course_spike_bad_scale"]
            offset = self.calibration.course_spike_rate + c["course_spike_bad_offset"]
            return max(scaled, max(offset, self._eff_course_spike_good() + 2.0))
        return d["spike_rate_bad"]

    def _eff_hover_gyro_good(self) -> float:
        c = self.config["calibration"]
        h = self.config["hover"]
        if self.calibrated:
            return max(
                self.calibration.hover_gyro_rms * c["hover_gyro_good_scale"],
                c["hover_gyro_good_floor"],
            )
        return h["gyro_rms_good"]

    def _eff_hover_gyro_bad(self) -> float:
        c = self.config["calibration"]
        h = self.config["hover"]
        if self.calibrated:
            return max(
                self.calibration.hover_gyro_rms * c["hover_gyro_bad_scale"],
                self._eff_hover_gyro_good() + c["hover_gyro_bad_min_offset"],
            )
        return h["gyro_rms_bad"]

    def _eff_hover_jerk_good(self) -> float:
        c = self.config["calibration"]
        h = self.config["hover"]
        if self.calibrated:
            return max(
                self.calibration.hover_jerk_rms * c["hover_jerk_good_scale"],
                c["hover_jerk_good_floor"],
            )
        return h["jerk_rms_good"]

    def _eff_hover_jerk_bad(self) -> float:
        c = self.config["calibration"]
        h = self.config["hover"]
        if self.calibrated:
            return max(
                self.calibration.hover_jerk_rms * c["hover_jerk_bad_scale"],
                self._eff_hover_jerk_good() + c["hover_jerk_bad_min_offset"],
            )
        return h["jerk_rms_bad"]

    def _eff_dock_jerk_bad(self) -> float:
        c = self.config["calibration"]
        d = self.config["dock"]
        if self.calibrated and self.calibration.dock_jerk_peak > 0.0:
            return max(
                self.calibration.dock_jerk_peak * c["dock_jerk_bad_scale"],
                c["jerk_bad_floor"],
            )
        return d["jerk_bad_default"]

    # --- derived helpers ---

    def compute_derived_rms(self, m: TrialMetrics) -> None:
        m.tilt_deg_rms_course = compute_rms(m.course_tilt_sumsq, m.course_tilt_samples)
        m.tilt_deg_rms_hover = compute_rms(m.hover_tilt_sumsq, m.hover_tilt_samples)

    def compute_phase_times(self, m: TrialMetrics) -> None:
        """Recompute phase times from event timestamps when not already set."""
        if m.approach_time_ms > 0 and m.total_trial_time_ms > 0:
            return
        m.approach_time_ms = 0
        m.hover_time_ms = 0
        m.dock_time_ms = 0
        if m.got_hover_enter and m.trial_start_ms > 0:
            m.approach_time_ms = m.hover_enter_ms - m.trial_start_ms
        if m.got_hover_complete and m.got_hover_enter:
            m.hover_time_ms = m.hover_complete_ms - m.hover_enter_ms
        if m.got_dock_complete and m.got_hover_complete:
            m.dock_time_ms = m.dock_complete_ms - m.hover_complete_ms
        if m.got_dock_complete and m.trial_start_ms > 0:
            m.total_trial_time_ms = m.dock_complete_ms - m.trial_start_ms

    # --- component scorers ---

    def score_course_traversal(self, m: TrialMetrics) -> int:
        cfg = self.config["course"]
        pen_max = cfg["penalties"]
        s = 35
        pen = 0

        gyro_rms = compute_rms(m.course_gyro_sumsq, m.course_sample_count)
        jerk_rms = compute_rms(m.course_jerk_sumsq, m.course_sample_count)

        gyro_pen = int(penalty_ramp(gyro_rms, self._eff_course_gyro_good(), self._eff_course_gyro_bad(), pen_max["gyro_rms_max"]))
        jerk_pen = int(penalty_ramp(jerk_rms, self._eff_course_jerk_good(), self._eff_course_jerk_bad(), pen_max["jerk_rms_max"]))
        pen += gyro_pen + jerk_pen
        s -= gyro_pen + jerk_pen

        sample_ms = self.config["sampling"]["sample_period_ms"]
        if m.approach_time_ms > 0:
            course_sec = m.approach_time_ms / 1000.0
        elif m.course_sample_count > 0:
            course_sec = m.course_sample_count * sample_ms / 1000.0
        else:
            course_sec = 0.0

        if course_sec > 0.1:
            spike_rate = (m.course_gyro_spike_count + m.course_jerk_spike_count) / course_sec
            spike_pen = int(
                penalty_ramp(
                    spike_rate,
                    self._eff_course_spike_good(),
                    self._eff_course_spike_bad(),
                    pen_max["spike_rate_max"],
                )
            )
            pen += spike_pen
            s -= spike_pen

        pause_pen = int(
            penalty_ramp(
                float(m.course_pause_time_ms),
                float(cfg["pause_min_ms"]),
                float(cfg["pause_bad_ms"]),
                float(pen_max["pause_max"]),
            )
        )
        pen += pause_pen
        s -= pause_pen

        if m.approach_time_ms > cfg["approach_time_bad_ms"]:
            pen += pen_max["approach_time_max"]
            s -= pen_max["approach_time_max"]
        elif m.approach_time_ms > cfg["approach_time_good_ms"]:
            t = (m.approach_time_ms - cfg["approach_time_good_ms"]) / (
                cfg["approach_time_bad_ms"] - cfg["approach_time_good_ms"]
            )
            time_pen = int(t * pen_max["approach_time_max"])
            pen += time_pen
            s -= time_pen

        m.pen_course = pen
        m.course_score = clamp_score(s, 0, 35)
        return m.course_score

    def score_hover_precision(self, m: TrialMetrics) -> int:
        hcfg = self.config["hover"]
        dwell = self.config["sampling"]["hover_dwell_ms"]
        slack = self.config["sampling"]["hover_time_slack_ms"]
        s = 30
        pen = 0

        reset_pen = int(m.hover_reset_count) * hcfg["reset_penalty_each"]
        reset_cap = min(reset_pen, hcfg["reset_penalty_cap"])
        pen += reset_cap
        s -= reset_cap

        if m.hover_total_samples > 0:
            unstable_frac = m.hover_unstable_sample_count / float(m.hover_total_samples)
            unstable_max = hcfg["unstable_penalty_max_default"]
            unstable_bad = hcfg["unstable_frac_bad_default"]
            if m.got_hover_complete and m.hover_reset_count == 0:
                unstable_max = hcfg["unstable_penalty_max_clean_complete"]
                unstable_bad = hcfg["unstable_frac_bad_clean_complete"]
            unstable_pen = int(penalty_ramp(unstable_frac, hcfg["unstable_frac_good"], unstable_bad, unstable_max))
            pen += unstable_pen
            s -= unstable_pen

        hover_gyro_rms = compute_rms(m.hover_gyro_sumsq, m.hover_total_samples)
        hover_jerk_rms = compute_rms(m.hover_jerk_sumsq, m.hover_total_samples)
        gyro_pen = int(penalty_ramp(hover_gyro_rms, self._eff_hover_gyro_good(), self._eff_hover_gyro_bad(), 4.0))
        jerk_pen = int(penalty_ramp(hover_jerk_rms, self._eff_hover_jerk_good(), self._eff_hover_jerk_bad(), 4.0))
        pen += gyro_pen + jerk_pen
        s -= gyro_pen + jerk_pen

        if m.hover_time_ms > dwell + slack:
            extra = m.hover_time_ms - dwell - slack
            time_pen = int(penalty_ramp(float(extra), 0.0, float(hcfg["extra_hover_time_ramp_ms"]), float(hcfg["extra_hover_time_penalty_max"])))
            pen += time_pen
            s -= time_pen

        m.hover_score = clamp_score(s, 0, 30)

        if m.got_hover_complete and m.hover_reset_count == 0:
            occ_frac = 1.0
            if m.hover_total_samples > 0:
                occ_frac = m.hover_occluded_samples / float(m.hover_total_samples)
            if occ_frac >= hcfg["bonus_occluded_frac"]:
                m.hover_score = clamp_score(max(m.hover_score, hcfg["bonus_min_score_occluded"]), 0, 30)
            if 0 < m.hover_time_ms <= hcfg["bonus_fast_hover_ms"]:
                m.hover_score = clamp_score(max(m.hover_score, hcfg["bonus_min_score_fast_hover"]), 0, 30)

        m.pen_hover = 30 - m.hover_score
        return m.hover_score

    def score_axis_discipline(self, m: TrialMetrics) -> int:
        acfg = self.config["axis"]
        pen_cfg = acfg["penalties"]
        s = 15
        pen = 0

        if m.tilt_deg_rms_hover > 0.0:
            tilt_rms = m.tilt_deg_rms_hover * acfg["hover_tilt_weight"] + m.tilt_deg_rms_course * acfg["course_tilt_weight"]
        else:
            tilt_rms = m.tilt_deg_rms_course

        rms_pen = int(penalty_ramp(tilt_rms, acfg["tilt_good_deg"], acfg["tilt_bad_deg"], float(pen_cfg["rms_max"])))
        pen += rms_pen
        s -= rms_pen

        warn_pen = int(
            penalty_ramp(
                float(m.tilt_over_limit_time_ms),
                0.0,
                float(pen_cfg["warn_time_ramp_ms"]),
                float(pen_cfg["warn_time_max"]),
            )
        )
        pen += warn_pen
        s -= warn_pen

        max_pen = int(
            penalty_ramp(
                m.tilt_deg_max,
                acfg["tilt_warn_deg"],
                acfg["tilt_max_bad_deg"],
                float(pen_cfg["max_tilt_max"]),
            )
        )
        pen += max_pen
        s -= max_pen

        m.pen_axis = pen
        m.axis_score = clamp_score(s, 0, 15)
        return m.axis_score

    def score_flow_timing(self, total_ms: int) -> int:
        f = self.config["flow"]
        if f["plateau_lo_ms"] <= total_ms <= f["plateau_hi_ms"]:
            return 10
        if f["fast_lo_ms"] <= total_ms < f["plateau_lo_ms"]:
            t = (f["plateau_lo_ms"] - total_ms) / (f["plateau_lo_ms"] - f["fast_lo_ms"])
            return clamp_score(int(7.0 + t * 3.0), 0, 10)
        if f["plateau_hi_ms"] < total_ms <= f["slow_hi_ms"]:
            t = (total_ms - f["plateau_hi_ms"]) / (f["slow_hi_ms"] - f["plateau_hi_ms"])
            return clamp_score(int(10.0 - t * 2.0), 0, 10)
        if f["min_ms"] <= total_ms < f["fast_lo_ms"]:
            t = (f["fast_lo_ms"] - total_ms) / (f["fast_lo_ms"] - f["min_ms"])
            return clamp_score(int(5.0 + t * 2.0), 0, 10)
        if f["slow_hi_ms"] < total_ms <= f["max_ms"]:
            t = (total_ms - f["slow_hi_ms"]) / (f["max_ms"] - f["slow_hi_ms"])
            return clamp_score(int(8.0 - t * 4.0), 0, 10)
        if total_ms < f["min_ms"]:
            return 4
        if total_ms > f["max_ms"]:
            t = (total_ms - f["max_ms"]) / 30000.0
            return clamp_score(int(4.0 - t * 4.0), 0, 10)
        return 0

    def score_target_apds(self, m: TrialMetrics) -> int:
        tcfg = self.config["target"]
        s = 5
        pen = 0

        hover_occluded_fraction = 1.0
        if m.hover_total_samples > 0:
            hover_occluded_fraction = m.hover_occluded_samples / float(m.hover_total_samples)

        if (
            m.got_hover_complete
            and m.hover_reset_count == 0
            and hover_occluded_fraction >= tcfg["perfect_occluded_frac"]
            and m.occlusion_loss_count == 0
        ):
            m.target_score = 5
            m.pen_target = 0
            return 5

        if hover_occluded_fraction < tcfg["occluded_frac_threshold"]:
            pen += tcfg["penalty_occluded_low"]
            s -= tcfg["penalty_occluded_low"]
        if m.occlusion_loss_count > 0:
            pen += tcfg["penalty_occlusion_loss"]
            s -= tcfg["penalty_occlusion_loss"]

        m.pen_target = pen
        m.target_score = clamp_score(s, 0, 5)
        return m.target_score

    def score_dock_quality(self, m: TrialMetrics) -> int:
        dcfg = self.config["dock"]
        pen_cfg = dcfg["penalties"]
        s = 5
        pen = 0

        if m.dock_time_ms > dcfg["time_bad_ms"]:
            pen += pen_cfg["time_max"]
            s -= pen_cfg["time_max"]
        elif m.dock_time_ms > dcfg["time_good_ms"]:
            time_pen = int(
                penalty_ramp(
                    float(m.dock_time_ms),
                    float(dcfg["time_good_ms"]),
                    float(dcfg["time_bad_ms"]),
                    float(pen_cfg["time_max"]),
                )
            )
            pen += time_pen
            s -= time_pen

        jerk_pen = int(penalty_ramp(m.dock_jerk_peak_recent, dcfg["jerk_good"], self._eff_dock_jerk_bad(), float(pen_cfg["jerk_max"])))
        pen += jerk_pen
        s -= jerk_pen

        gyro_pen = int(penalty_ramp(m.dock_gyro_peak_recent, dcfg["gyro_good"], dcfg["gyro_bad"], float(pen_cfg["gyro_max"])))
        pen += gyro_pen
        s -= gyro_pen

        m.pen_dock = pen
        m.dock_score = clamp_score(s, 0, 5)
        return m.dock_score

    def choose_feedback_label(self, m: TrialMetrics) -> str:
        fb = self.config["feedback_thresholds"]
        flow = self.config["flow"]
        label = "Good control"

        if not m.got_dock_complete:
            label = "Incomplete"
        elif m.hover_reset_count > 0:
            label = "Hover unstable"
        elif m.target_score < fb["target_low"] or m.occlusion_loss_count > 0:
            label = "Lost target"
        elif m.axis_score < fb["axis_off_axis"]:
            label = "Handle off-axis"
        elif m.course_score < fb["course_jerky"]:
            jerk_rms = compute_rms(m.course_jerk_sumsq, m.course_sample_count)
            course_sec = m.approach_time_ms / 1000.0 if m.approach_time_ms > 0 else 0.0
            spike_rate = 0.0
            if course_sec > 0.1:
                spike_rate = (m.course_gyro_spike_count + m.course_jerk_spike_count) / course_sec
            if jerk_rms > self._eff_course_jerk_bad() * 0.9 or spike_rate > self._eff_course_spike_bad() * 0.9:
                label = "Course too jerky"
            else:
                label = "Too much rotation"
        elif m.flow_score < fb["flow_low"] and m.total_trial_time_ms < flow["plateau_lo_ms"]:
            label = "Fast but controlled" if m.course_score >= 25 else "Too fast"
        elif m.flow_score < fb["flow_low"] and m.total_trial_time_ms > flow["slow_hi_ms"]:
            label = "Too slow"
        elif m.dock_score <= fb["dock_harsh_score"] and m.total_score > fb["dock_harsh_total"]:
            label = "Dock too harsh"
        elif m.total_score > fb["great_control_total"]:
            label = "Great control"
        elif m.course_score >= fb["improve_hover_course"] and m.hover_score < fb["improve_hover_score"]:
            label = "Improve hover"

        m.feedback = label
        return label

    def compute_final_component_scores(self, m: TrialMetrics) -> TrialMetrics:
        if not m.got_dock_complete:
            return m
        self.compute_derived_rms(m)
        self.compute_phase_times(m)
        self.score_course_traversal(m)
        self.score_hover_precision(m)
        self.score_axis_discipline(m)
        m.flow_score = self.score_flow_timing(m.total_trial_time_ms)
        m.pen_flow = 10 - m.flow_score
        self.score_target_apds(m)
        self.score_dock_quality(m)
        m.total_score = clamp_score(
            m.course_score + m.hover_score + m.axis_score + m.flow_score + m.target_score + m.dock_score,
            0,
            100,
        )
        self.choose_feedback_label(m)
        return m

    def score(self, metrics: TrialMetrics) -> TrialMetrics:
        """Score a completed trial and return updated metrics."""
        m = deepcopy(metrics)
        return self.compute_final_component_scores(m)


def score_trial_v1(metrics: TrialMetrics, calibrated: bool = False, calibration: CalibrationState | None = None) -> TrialMetrics:
    """Convenience wrapper for legacy V1 scoring."""
    return OldScorer(calibrated=calibrated, calibration=calibration).score(metrics)


def metrics_from_final_score_row(row: dict[str, Any]) -> TrialMetrics:
    """
    Reconstruct TrialMetrics from a persisted FINAL_SCORE CSV/dict row.

    Used for regression replay against firmware-recorded trials.
    """
    def _f(key: str, default: float = 0.0) -> float:
        v = row.get(key)
        if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)

    def _i(key: str, default: int = 0) -> int:
        v = row.get(key)
        if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
            return default
        return int(float(v))

    approach_ms = _i("approach_ms")
    hover_ms = _i("hover_ms")
    dock_ms = _i("dock_ms")
    total_ms = _i("total_ms")
    course_gyro = _f("course_gyro_rms")
    course_jerk = _f("course_jerk_rms")
    spike_rate = _f("course_spike_rate")
    tilt_rms = _f("tilt_rms")
    hover_stable_pct = _f("hover_stable_pct")
    hover_occluded_pct = _f("hover_occluded_pct")

    # Use synthetic sample counts so compute_rms returns exported RMS values.
    n_course = 100 if course_gyro or course_jerk else 0
    n_hover = 100 if hover_ms > 0 else 0

    spike_total = int(round(spike_rate * (approach_ms / 1000.0))) if approach_ms > 0 else 0

    m = TrialMetrics(
        trial_id=_i("trial"),
        got_trial_start=True,
        got_hover_enter=approach_ms > 0,
        got_hover_complete=hover_ms >= 2000,
        got_dock_complete=True,
        trial_start_ms=max(0, approach_ms) if approach_ms > 0 else 0,
        hover_enter_ms=approach_ms if approach_ms > 0 else hover_ms,
        hover_complete_ms=(approach_ms + hover_ms) if approach_ms > 0 else hover_ms,
        dock_complete_ms=(approach_ms + hover_ms + dock_ms) if dock_ms else total_ms,
        approach_time_ms=approach_ms,
        hover_time_ms=hover_ms,
        dock_time_ms=dock_ms,
        total_trial_time_ms=total_ms,
        course_sample_count=n_course,
        course_gyro_sumsq=course_gyro * course_gyro * n_course,
        course_jerk_sumsq=course_jerk * course_jerk * n_course,
        course_gyro_spike_count=spike_total // 2,
        course_jerk_spike_count=spike_total - spike_total // 2,
        course_pause_time_ms=0,
        course_tilt_sumsq=tilt_rms * tilt_rms * max(n_course, 1),
        course_tilt_samples=max(n_course, 1),
        hover_reset_count=_i("hover_resets"),
        occlusion_loss_count=_i("occlusion_losses"),
        hover_total_samples=n_hover,
        hover_unstable_sample_count=int(round(n_hover * (1.0 - hover_stable_pct / 100.0))) if n_hover else 0,
        hover_occluded_samples=int(round(n_hover * hover_occluded_pct / 100.0)) if n_hover else 0,
        hover_gyro_sumsq=0.0,
        hover_jerk_sumsq=0.0,
        tilt_deg_max=_f("tilt_max"),
        tilt_over_limit_time_ms=_i("tilt_over_limit_ms"),
        tilt_deg_rms_course=tilt_rms,
        tilt_deg_rms_hover=0.0,
        dock_jerk_peak_recent=_f("dock_jerk_peak"),
        dock_gyro_peak_recent=0.0,
    )
    return m
