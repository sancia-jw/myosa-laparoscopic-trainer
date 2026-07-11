"""Phase 2B V2 shadow scorer tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scoring.v2.config import load_v2_config
from scoring.v2.metrics import extract_raw_metrics
from scoring.v2.scorer import clamp_score, piecewise_metric_score, score_trial_v2
from scoring.v2.shadow import SHADOW_CSV, append_shadow_result


SAMPLE_FINAL = {
    "trial": 99,
    "total": 84,
    "total_ms": 30500,
    "approach_ms": 21000,
    "hover_ms": 7200,
    "course_gyro_rms": 180.0,
    "course_jerk_rms": 1400.0,
    "course_spike_rate": 2.5,
    "tilt_rms": 8.0,
    "hover_stable_pct": 82.0,
    "hover_occluded_pct": 95.0,
    "hover_resets": 0,
    "hover_gyro_rms": 85.0,
    "course_pause_ms": 500,
}


def test_piecewise_lower_is_better_anchors() -> None:
    assert piecewise_metric_score(130.0, good=130, okay=195, bad=260, direction="lower_is_better") == 90.0
    assert piecewise_metric_score(195.0, good=130, okay=195, bad=260, direction="lower_is_better") == 65.0
    assert piecewise_metric_score(260.0, good=130, okay=195, bad=260, direction="lower_is_better") == 30.0
    assert piecewise_metric_score(0.0, good=130, okay=195, bad=260, direction="lower_is_better") == 100.0


def test_piecewise_higher_is_better_anchors() -> None:
    assert piecewise_metric_score(80.0, good=80, okay=65, bad=40, direction="higher_is_better") == 90.0
    assert piecewise_metric_score(65.0, good=80, okay=65, bad=40, direction="higher_is_better") == 65.0
    assert piecewise_metric_score(40.0, good=80, okay=65, bad=40, direction="higher_is_better") == 30.0


def test_piecewise_clamps_and_missing() -> None:
    assert piecewise_metric_score(None, good=1, okay=2, bad=3, direction="lower_is_better") is None
    assert 0.0 <= clamp_score(-5) <= 100.0
    assert clamp_score(150) == 100.0


def test_v2_overall_in_range() -> None:
    result = score_trial_v2(SAMPLE_FINAL)
    assert 0 <= result.overall_score <= 100
    assert 0 <= result.control_score <= 100
    assert 0 <= result.efficiency_score <= 100
    assert 0 <= result.target_stability_score <= 100


def test_category_weights_sum() -> None:
    cfg = load_v2_config()
    weights = cfg["category_weights"]
    assert math.isclose(sum(weights.values()), 1.0, rel_tol=1e-6)


def test_metric_weights_sum_per_category() -> None:
    cfg = load_v2_config()
    by_cat: dict[str, float] = {}
    for m in cfg["metrics"]:
        if m.get("enabled", True):
            by_cat[m["category"]] = by_cat.get(m["category"], 0.0) + float(m["weight"])
    for cat, total in by_cat.items():
        assert math.isclose(total, 1.0, rel_tol=1e-6), cat


def test_missing_optional_metric_handled() -> None:
    row = dict(SAMPLE_FINAL)
    row.pop("hover_gyro_rms", None)
    row.pop("course_pause_ms", None)
    result = score_trial_v2(row)
    assert 0 <= result.overall_score <= 100
    assert any("hover_motion_gyro_rms" in w for w in result.warnings)


def test_short_trial_zero_duration() -> None:
    row = dict(SAMPLE_FINAL)
    row["total_ms"] = 0
    row["approach_ms"] = 0
    result = score_trial_v2(row)
    assert 0 <= result.overall_score <= 100


def test_malformed_telemetry() -> None:
    row = {"trial": 1, "total": 50, "course_gyro_rms": "bad", "total_ms": "nan"}
    result = score_trial_v2(row)
    assert 0 <= result.overall_score <= 100
    assert result.warnings


def test_shadow_one_row_per_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scoring.v2.shadow as shadow_mod

    csv_path = tmp_path / "v2_shadow_results.csv"
    monkeypatch.setattr(shadow_mod, "SHADOW_CSV", csv_path)

    logged: set[int] = set()
    row = dict(SAMPLE_FINAL)
    r1 = append_shadow_result(row, logged_trials=logged, enabled=True)
    r2 = append_shadow_result(row, logged_trials=logged, enabled=True)
    assert r1 is not None
    assert r2 is None
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # header + one data row


def test_shadow_disabled_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scoring.v2.shadow as shadow_mod

    csv_path = tmp_path / "v2_shadow_results.csv"
    monkeypatch.setattr(shadow_mod, "SHADOW_CSV", csv_path)
    logged: set[int] = set()
    assert append_shadow_result(SAMPLE_FINAL, logged_trials=logged, enabled=False) is None
    assert not csv_path.exists()


def test_shadow_csv_failure_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scoring.v2.shadow as shadow_mod

    monkeypatch.setattr(shadow_mod, "SHADOW_CSV", tmp_path / "no" / "access.csv")
    logged: set[int] = set()
    result = append_shadow_result(SAMPLE_FINAL, logged_trials=logged, enabled=True)
    assert result is not None


def test_extract_raw_metrics_transform() -> None:
    cfg = load_v2_config()
    raw, warnings = extract_raw_metrics({"total_ms": 30000, "trial": 1}, cfg["metrics"])
    assert raw["completion_time_s"] == 30.0


def test_v2_result_has_feedback_fields() -> None:
    result = score_trial_v2(SAMPLE_FINAL)
    assert result.strongest_category
    assert result.weakest_category
    assert result.feedback
    assert result.config_version == "v2_initial"
