"""Smooth Operator V2 dashboard: live scoring, storage, calibration, and UI helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scoring.v2.calibration import check_ordering, operator_balanced_anchor, propose_calibration
from scoring.v2.config import (
    INITIAL_CONFIG_PATH,
    load_active_v2_config,
    revert_to_initial_v2,
    revert_to_v1_legacy,
    set_active_config_path,
)
from scoring.v2.feedback import MESSAGES, rate_limited_feedback, select_feedback
from scoring.v2.live_scorer import LiveV2State, compute_live_v2, final_v2_from_trial
from scoring.v2.calibration import apply_proposal_to_config, save_versioned_config
from session_sync import should_record_final_score
from storage.database import TrialStore
from ui.theme import logo_path

SAMPLE_FINAL = {
    "trial": 501,
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


def _manual_trial(op: str, label: str, metric: str, value: float, trial_id: int) -> dict:
    return {
        "trial_id": trial_id,
        "user_name": op,
        "manual_label": label,
        "source_type": "manual_calibration",
        "raw_metrics_json": json.dumps({metric: value}),
    }


@pytest.fixture
def temp_store(tmp_path: Path) -> TrialStore:
    return TrialStore(tmp_path / "test.db")


def test_live_v2_score_in_range() -> None:
    live = {"state": "APPROACH", "gyro_rms": 150, "spike_rate": 3, "elapsed_ms": 5000}
    state = compute_live_v2(live, 5000)
    assert 0 <= state.displayed_score <= 100
    assert 0 <= state.raw_overall <= 100


def test_phase_aware_renormalization_approach() -> None:
    live = {"state": "APPROACH", "gyro_rms": 130, "spike_rate": 2, "elapsed_ms": 8000}
    state = compute_live_v2(live, 8000)
    assert state.phase == "approach"
    assert state.target_stability_score is None


def test_phase_aware_all_categories_hover() -> None:
    live = {
        "state": "HOVER",
        "gyro_rms": 90,
        "spike_rate": 1,
        "elapsed_ms": 15000,
        "stable": 1,
        "occ": 1,
        "hover_ms": 2000,
    }
    state = compute_live_v2(live, 15000)
    assert state.phase == "stable_hover"
    assert state.target_stability_score is not None


def test_finish_retains_live_score() -> None:
    prev = LiveV2State(displayed_score=72.0, raw_overall=70.0, phase="stable_hover")
    live = {"state": "DOCK", "gyro_rms": 200, "spike_rate": 10, "elapsed_ms": 25000}
    state = compute_live_v2(live, 25000, prev)
    assert state.phase == "finish"
    assert state.displayed_score == 72.0


def test_final_v2_recomputation() -> None:
    result = final_v2_from_trial(SAMPLE_FINAL)
    assert 0 <= result.overall_score <= 100
    assert result.config_version


def test_feedback_priority_finish() -> None:
    assert select_feedback(
        phase="finish", live={}, gyro=0, jerk=0, spike=0, stable=None, occ=None
    ) == MESSAGES["press_red"]


def test_feedback_rate_limiting() -> None:
    msg, ts = rate_limited_feedback(
        "Slow down",
        last_msg="Smooth and controlled",
        last_change_ts=time.time(),
        phase="approach",
        prev_phase="approach",
        min_interval=5.0,
    )
    assert msg == "Smooth and controlled"
    msg2, _ = rate_limited_feedback(
        "Target lost — reacquire",
        last_msg="Stable hover",
        last_change_ts=time.time(),
        phase="stable_hover",
        prev_phase="stable_hover",
        min_interval=5.0,
    )
    assert msg2 == "Target lost — reacquire"


def test_named_trial_history(temp_store: TrialStore) -> None:
    v2 = {"overall_score": 80, "control_score": 85, "efficiency_score": 75, "target_stability_score": 78}
    row_id, _ = temp_store.save_completed_trial(
        trial_id=1,
        user_name="Alex",
        source_type="normal",
        manual_label=None,
        v1_score=70,
        v2_result=v2,
    )
    assert row_id is not None
    users = temp_store.list_user_names()
    assert "Alex" in users
    trials = temp_store.list_trials(user_name="Alex", named_only=True)
    assert len(trials) == 1


def test_anonymous_excluded_from_named_progress(temp_store: TrialStore) -> None:
    v2 = {"overall_score": 70, "control_score": 70, "efficiency_score": 70, "target_stability_score": 70}
    temp_store.save_completed_trial(
        trial_id=2,
        user_name=None,
        source_type="normal",
        manual_label=None,
        v1_score=65,
        v2_result=v2,
    )
    assert temp_store.list_user_names() == []
    assert temp_store.list_trials(named_only=True) == []


def test_one_row_per_completion(temp_store: TrialStore) -> None:
    v2 = {"overall_score": 75, "control_score": 75, "efficiency_score": 75, "target_stability_score": 75}
    row_id, _ = temp_store.save_completed_trial(
        trial_id=10,
        user_name="Sam",
        source_type="normal",
        manual_label=None,
        v1_score=70,
        v2_result=v2,
    )
    assert row_id is not None
    dup_id, dup_err = temp_store.save_completed_trial(
        trial_id=10,
        user_name="Sam",
        source_type="normal",
        manual_label=None,
        v1_score=70,
        v2_result=v2,
    )
    assert dup_id is None
    assert dup_err
    assert len(temp_store.list_trials()) == 1


def test_duplicate_final_score_guard() -> None:
    state: dict = {"finalized_trial_ids": set()}
    assert should_record_final_score(state, 42)
    state["finalized_trial_ids"].add(42)
    assert not should_record_final_score(state, 42)


def test_manual_calibration_storage(temp_store: TrialStore) -> None:
    v2 = {
        "overall_score": 88,
        "control_score": 90,
        "efficiency_score": 85,
        "target_stability_score": 87,
        "raw_metrics": {"course_smoothness_gyro_rms": 120},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    row_id, _ = temp_store.save_completed_trial(
        trial_id=20,
        user_name="CalOp",
        source_type="manual_calibration",
        manual_label="good",
        v1_score=80,
        v2_result=v2,
        notes="reference run",
    )
    assert row_id is not None
    rows = temp_store.list_trials(source_type="manual_calibration")
    assert rows[0]["manual_label"] == "good"


def test_delete_trial(temp_store: TrialStore) -> None:
    v2 = {"overall_score": 60, "control_score": 60, "efficiency_score": 60, "target_stability_score": 60}
    temp_store.save_completed_trial(
        trial_id=30,
        user_name=None,
        source_type="normal",
        manual_label=None,
        v1_score=55,
        v2_result=v2,
    )
    row = temp_store.list_trials()[0]
    assert temp_store.delete_trial(row["id"])
    assert temp_store.list_trials() == []


def test_clear_all_trials(temp_store: TrialStore) -> None:
    v2 = {"overall_score": 60, "control_score": 60, "efficiency_score": 60, "target_stability_score": 60}
    for tid in (40, 41):
        temp_store.save_completed_trial(
            trial_id=tid,
            user_name=None,
            source_type="normal",
            manual_label=None,
            v1_score=55,
            v2_result=v2,
        )
    assert temp_store.clear_all_trials()
    assert temp_store.list_trials() == []


def test_csv_export(temp_store: TrialStore) -> None:
    v2 = {"overall_score": 77, "control_score": 77, "efficiency_score": 77, "target_stability_score": 77}
    temp_store.save_completed_trial(
        trial_id=50,
        user_name="Pat",
        source_type="normal",
        manual_label=None,
        v1_score=70,
        v2_result=v2,
    )
    csv_text = temp_store.export_csv()
    assert "trial_id" in csv_text
    assert "Pat" in csv_text


def test_operator_balanced_anchor() -> None:
    trials = [
        _manual_trial("A", "good", "course_smoothness_gyro_rms", 120, 1),
        _manual_trial("A", "good", "course_smoothness_gyro_rms", 130, 2),
        _manual_trial("B", "good", "course_smoothness_gyro_rms", 140, 3),
        _manual_trial("B", "good", "course_smoothness_gyro_rms", 150, 4),
    ]
    val, mad, cnt, n_ops = operator_balanced_anchor(trials, "course_smoothness_gyro_rms", "good")
    assert val == 135.0
    assert n_ops == 2
    assert cnt == 2


def test_inconsistent_anchor_ordering_warning() -> None:
    trials = [
        _manual_trial("A", "good", "course_smoothness_gyro_rms", 300, 1),
        _manual_trial("A", "okay", "course_smoothness_gyro_rms", 200, 2),
        _manual_trial("A", "bad", "course_smoothness_gyro_rms", 100, 3),
    ]
    proposal = propose_calibration(trials, [])
    entry = next(p for p in proposal["proposals"] if p["metric"] == "course_smoothness_gyro_rms")
    assert not entry["consistent"]


def test_versioned_config_application(tmp_path: Path) -> None:
    trials = [
        _manual_trial("A", "good", "course_smoothness_gyro_rms", 120, 1),
        _manual_trial("A", "okay", "course_smoothness_gyro_rms", 195, 2),
        _manual_trial("A", "bad", "course_smoothness_gyro_rms", 260, 3),
    ]
    proposal = propose_calibration(trials, [])
    new_cfg = apply_proposal_to_config(proposal, version_suffix="test")
    path = save_versioned_config(new_cfg, directory=tmp_path)
    assert path.exists()
    assert path.name.startswith("scoring_config_v2_calibrated_")


def test_revert_to_initial_v2(temp_store: TrialStore) -> None:
    temp_store.set_setting("active_v2_config_path", "/tmp/custom.json")
    temp_store.set_setting("scorer_mode", "v1_legacy")
    revert_to_initial_v2(temp_store, mode="open")
    assert temp_store.get_setting("active_v2_config_path_open") == str(INITIAL_CONFIG_PATH)
    assert temp_store.get_setting("scorer_mode_open") == "v2"


def test_revert_to_v1_legacy(temp_store: TrialStore) -> None:
    revert_to_v1_legacy(temp_store, mode="open")
    assert temp_store.get_setting("scorer_mode_open") == "v1_legacy"


def test_database_failure_fallback(monkeypatch: pytest.MonkeyPatch, temp_store: TrialStore) -> None:
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(temp_store, "_connect", boom)
    rows = temp_store.list_trials()
    assert rows == []


def test_missing_logo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from ui import theme

    monkeypatch.setattr(theme, "LOGO_CANDIDATES", [Path("/nonexistent/logo.jpg")])
    assert logo_path() is None


def test_check_ordering_lower_is_better() -> None:
    assert check_ordering(100, 200, 300, "lower_is_better")
    assert not check_ordering(300, 200, 100, "lower_is_better")
