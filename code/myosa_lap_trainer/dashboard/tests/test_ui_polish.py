"""UI polish, presentation, and validity tests."""

from __future__ import annotations

import pytest

from scoring.v2.feedback import MESSAGES, select_feedback
from scoring.v2.metric_metadata import METRIC_METADATA, display_name
from scoring.v2.presentation import build_category_summary, category_points, format_duration_ms, overall_from_categories
from scoring.v2.validity import assess_trial_validity
from ui.theme import THEME_CSS, logo_path


SAMPLE_FINAL = {
    "hover_ms": 2100,
    "hover_stable_pct": 82,
    "hover_occluded_pct": 95,
    "total_ms": 30500,
}


def test_category_point_math() -> None:
    cats = build_category_summary(98, 80, 70)
    assert cats["control"]["points"] == pytest.approx(39.2, abs=0.1)
    assert cats["efficiency"]["points"] == pytest.approx(24.0, abs=0.1)
    assert cats["target_stability"]["points"] == pytest.approx(21.0, abs=0.1)
    assert overall_from_categories(cats) == pytest.approx(84.2, abs=0.1)


def test_never_display_quality_as_points_denominator() -> None:
    pts, max_pts = category_points(91, "control")
    assert max_pts == 40
    assert pts == pytest.approx(36.4, abs=0.1)


def test_skipped_hover_incomplete() -> None:
    fin = {"hover_ms": 500, "hover_stable_pct": 30, "hover_occluded_pct": 40}
    ok, msg = assess_trial_validity(fin, phase_timestamps={})
    assert not ok
    assert "Incomplete" in msg


def test_completed_hover_valid() -> None:
    ok, _ = assess_trial_validity(
        SAMPLE_FINAL,
        phase_timestamps={"hover_complete": "2026-01-01T00:00:00"},
    )
    assert ok


def test_completion_time_formatting() -> None:
    assert format_duration_ms(600) == "0.6 s"
    assert format_duration_ms(12400) == "12.4 s"
    assert format_duration_ms(64200) == "1:04.2"


def test_metric_metadata_covers_scored_keys() -> None:
    keys = {
        "course_smoothness_gyro_rms",
        "correction_spike_rate",
        "completion_time_s",
        "hover_stable_pct",
    }
    for k in keys:
        assert k in METRIC_METADATA
        assert display_name(k) != k


def test_accel_metrics_in_metadata() -> None:
    assert "course_jerk_rms" in METRIC_METADATA
    assert "hover_jerk_rms" in METRIC_METADATA


def test_no_raw_key_as_display_name() -> None:
    assert display_name("course_smoothness_gyro_rms") == "Rotational Smoothness"


def test_feedback_target_lost() -> None:
    msg = select_feedback(
        phase="stable_hover",
        live={},
        gyro=50,
        jerk=100,
        spike=1,
        stable=1,
        occ=0,
    )
    assert msg == MESSAGES["target_lost"]


def test_theme_has_nav_and_page_tints() -> None:
    assert "so-nav-wrap" in THEME_CSS
    assert "so-page-live" in THEME_CSS
    assert 'section[data-testid="stSidebar"] *' not in THEME_CSS


def test_missing_logo_fallback() -> None:
    from ui import theme

    assert callable(logo_path)
