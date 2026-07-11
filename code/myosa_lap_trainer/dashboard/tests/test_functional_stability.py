"""Functional stability regression tests."""

from __future__ import annotations

from pathlib import Path

import sqlite3

from live_metrics import append_chart_live, append_chart_quality, clear_live_metrics, get_metric_display, update_live_metrics
from scoring.v2.presentation import format_trial_label
from storage.database import TrialStore
from trial_context import clear_trial_context, context_for_save, normalize_operator_name, snapshot_trial_context
from ui.navigation import NAV_PAGES


def test_normalize_operator_name() -> None:
    assert normalize_operator_name("  test1  ") == "test1"
    assert normalize_operator_name("") is None
    assert normalize_operator_name(None) is None


def test_snapshot_trial_context_preserves_operator() -> None:
    state = {"user_name_input": "Test1", "calibration_pending": False}
    ctx = snapshot_trial_context(state, firmware_trial_id=42)
    assert ctx["operator_name"] == "Test1"
    state["user_name_input"] = ""
    assert context_for_save(state)["operator_name"] == "Test1"


def test_calibration_snapshot_uses_calibration_fields() -> None:
    state = {
        "calibration_pending": True,
        "calibration_operator": " cal_op ",
        "calibration_label": "good",
        "calibration_note": "note",
        "user_name_input": "",
    }
    ctx = snapshot_trial_context(state)
    assert ctx["operator_name"] == "cal_op"
    assert ctx["source_type"] == "manual_calibration"
    assert ctx["manual_label"] == "good"
    assert ctx["notes"] == "note"


def test_clear_trial_context() -> None:
    state = {"active_trial_context": {"operator_name": "x"}}
    clear_trial_context(state)
    assert "active_trial_context" not in state


def test_hover_packet_preserves_motion_metrics() -> None:
    state: dict = {}
    update_live_metrics(state, {"gyro_rms": 12.5, "jerk_rms": 88.0, "spike_rate": 0.4, "elapsed_ms": 5000})
    update_live_metrics(state, {"hover_ms": 800, "hover_target_ms": 2000, "stable": 1, "occ": 1, "elapsed_ms": 6000})
    last = state["live_metrics_last"]
    assert last["gyro_rms"] == 12.5
    assert last["jerk_rms"] == 88.0
    assert last["spike_rate"] == 0.4
    assert last["hover_ms"] == 800


def test_incomplete_packet_does_not_erase_values() -> None:
    state: dict = {}
    update_live_metrics(state, {"gyro_rms": 10.0, "jerk_rms": 50.0})
    update_live_metrics(state, {"elapsed_ms": 7000})
    assert state["live_metrics_last"]["gyro_rms"] == 10.0
    assert state["live_metrics_last"]["jerk_rms"] == 50.0


def test_clear_live_metrics_on_reset() -> None:
    state = {"live_metrics_last": {"gyro_rms": 1}, "live_chart_series": [{"rot": 1, "lin": 2}]}
    clear_live_metrics(state)
    assert state["live_metrics_last"] == {}
    assert state["live_chart_series"] == []


def test_append_chart_live_appends_per_packet() -> None:
    state: dict = {"live_metrics_last": {"gyro_rms": 120.0, "jerk_rms": 800.0}, "live_chart_series": []}
    append_chart_live(state)
    append_chart_live(state)
    assert len(state["live_chart_series"]) == 2
    assert state["live_chart_series"][-1]["rot"] > 0


def test_append_chart_live_carries_forward_on_hover() -> None:
    state: dict = {"live_metrics_last": {"gyro_rms": 100.0, "jerk_rms": 900.0}, "live_chart_series": []}
    append_chart_live(state)
    state["live_metrics_last"] = {"hover_ms": 500}
    append_chart_live(state)
    assert len(state["live_chart_series"]) == 2
    assert state["live_chart_series"][-1]["rot"] == state["live_chart_series"][0]["rot"]


def test_chart_quality_fills_missing_from_previous() -> None:
    state = {"live_metrics_last": {"gyro_rms": 90.0}, "live_chart_series": []}
    append_chart_live(state)
    state["live_metrics_last"] = {}
    append_chart_live(state)
    assert state["live_chart_series"][-1]["rot"] == state["live_chart_series"][0]["rot"]


def test_get_metric_display_em_dash_when_missing() -> None:
    assert get_metric_display({}, "gyro_rms") == "—"
    assert get_metric_display({"gyro_rms": 3.2}, "gyro_rms", fmt="{:.1f}") == "3.2"


def test_format_trial_label() -> None:
    row = {"user_name": "Test1", "created_at": "2026-07-11T23:42:00", "v2_overall": 81.2}
    label = format_trial_label(row)
    assert "Test1" in label
    assert "Score 81" in label
    assert "Jul" in label


def test_display_overall_score_rounds() -> None:
    from scoring.v2.presentation import display_overall_score

    assert display_overall_score(67.4) == 67
    assert display_overall_score(67.6) == 68
    assert display_overall_score(81.2) == 81


def test_format_trial_label_anonymous() -> None:
    row = {"user_name": None, "created_at": "2026-07-11T23:42:00", "v2_overall": 70}
    assert format_trial_label(row).startswith("Anonymous")


def test_database_save_returns_row_id(tmp_path: Path) -> None:
    store = TrialStore(path=tmp_path / "t.db")
    v2 = {
        "overall_score": 80,
        "control_score": 82,
        "efficiency_score": 76,
        "target_stability_score": 69,
        "raw_metrics": {"completion_time_s": 30},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    row_id, err = store.save_completed_trial(
        trial_id=101,
        user_name="test1",
        source_type="normal",
        manual_label=None,
        v1_score=75.0,
        v2_result=v2,
    )
    assert row_id is not None
    assert err is None
    dup_id, dup_err = store.save_completed_trial(
        trial_id=101,
        user_name="test1",
        source_type="normal",
        manual_label=None,
        v1_score=75.0,
        v2_result=v2,
    )
    assert dup_id is None
    assert dup_err is not None


def test_named_user_case_insensitive_lookup(tmp_path: Path) -> None:
    store = TrialStore(path=tmp_path / "t2.db")
    v2 = {
        "overall_score": 80,
        "control_score": 82,
        "efficiency_score": 76,
        "target_stability_score": 69,
        "raw_metrics": {},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    store.save_completed_trial(
        trial_id=1, user_name="Test1", source_type="normal", manual_label=None, v1_score=None, v2_result=v2
    )[0]
    users = store.list_user_names()
    assert len(users) == 1
    trials = store.list_trials(user_name="test1", named_only=True)
    assert len(trials) == 1
    assert trials[0]["user_name"] == "Test1"


def test_anonymous_trials_appear_in_breakdown_list(tmp_path: Path) -> None:
    store = TrialStore(path=tmp_path / "anon.db")
    v2 = {
        "overall_score": 72,
        "control_score": 72,
        "efficiency_score": 72,
        "target_stability_score": 72,
        "raw_metrics": {"completion_time_s": 25},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    row_id, err = store.save_completed_trial(
        trial_id=501,
        user_name=None,
        source_type="normal",
        manual_label=None,
        v1_score=70,
        v2_result=v2,
        mode="box",
    )
    assert err is None and row_id is not None
    listed = store.list_trials(mode="box")
    assert len(listed) == 1
    assert listed[0]["user_name"] is None
    assert store.list_trials(named_only=True, mode="box") == []


def test_trial_save_key_per_mode() -> None:
    from app import _trial_save_key

    assert _trial_save_key(5, "open") != _trial_save_key(5, "box")


def test_navigation_pending_page_pattern() -> None:
    """Regression: redirect via pending_page, not widget key mutation."""
    state: dict = {"active_page": "Track Progress", "pending_page": "Live Trial"}
    pending = state.pop("pending_page", None)
    if pending in NAV_PAGES:
        state["active_page"] = pending
    assert state["active_page"] == "Live Trial"
    assert "pending_page" not in state


def test_request_page_only_sets_pending() -> None:
    state: dict = {"active_page": "Live Trial"}
    page = "Trial Breakdown"
    if page in NAV_PAGES:
        state["pending_page"] = page
    assert state["pending_page"] == "Trial Breakdown"
    assert state["active_page"] == "Live Trial"


def test_invalid_trial_still_persisted_with_valid_zero(tmp_path: Path) -> None:
    store = TrialStore(path=tmp_path / "inv.db")
    v2 = {
        "overall_score": 40,
        "control_score": 40,
        "efficiency_score": 40,
        "target_stability_score": 40,
        "raw_metrics": {},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    row_id, err = store.save_completed_trial(
        trial_id=55,
        user_name="test1",
        source_type="normal",
        manual_label=None,
        v1_score=40.0,
        v2_result=v2,
        valid=False,
    )
    assert row_id is not None
    assert err is None
    assert store.count_trials() == 1
    assert store.count_trials(valid_only=True) == 0
    assert store.list_trials() == []
    rows_all = store.list_trials(limit=10)  # valid only
    assert len(rows_all) == 0
    from ui.components import _benchmark_scale

    g, o, _, marker = _benchmark_scale(5.0, 10.0, 20.0, 40.0, lower_is_better=True)
    assert marker < g


def test_calibration_snapshot_includes_mode() -> None:
    state = {
        "calibration_pending": True,
        "calibration_operator": " op ",
        "calibration_label": "good",
        "calibration_note": "note",
        "operating_mode": "box",
    }
    ctx = snapshot_trial_context(state)
    assert ctx["mode"] == "box"
    assert ctx["conference_mode"] is False


def test_conference_snapshot_flag() -> None:
    state = {"user_name_input": "Pat", "conference_mode": True, "operating_mode": "open"}
    ctx = snapshot_trial_context(state)
    assert ctx["conference_mode"] is True
    assert ctx["operator_name"] == "Pat"


def test_trial_mode_storage_separation(tmp_path: Path) -> None:
    store = TrialStore(path=tmp_path / "mode.db")
    v2 = {
        "overall_score": 70,
        "control_score": 70,
        "efficiency_score": 70,
        "target_stability_score": 70,
        "raw_metrics": {},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    store.save_completed_trial(
        trial_id=1,
        user_name="A",
        source_type="normal",
        manual_label=None,
        v1_score=70,
        v2_result=v2,
        mode="open",
    )
    store.save_completed_trial(
        trial_id=1,
        user_name="A",
        source_type="normal",
        manual_label=None,
        v1_score=72,
        v2_result=v2,
        mode="box",
    )
    open_rows = store.list_trials(mode="open")
    box_rows = store.list_trials(mode="box")
    assert len(open_rows) == 1
    assert len(box_rows) == 1
    assert open_rows[0]["v1_score"] == 70
    assert box_rows[0]["v1_score"] == 72


def test_legacy_db_migration_adds_mode_column(tmp_path: Path) -> None:
    """Existing DBs without mode must migrate without error."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trial_id INTEGER NOT NULL,
            user_name TEXT,
            source_type TEXT NOT NULL DEFAULT 'normal',
            manual_label TEXT,
            created_at TEXT NOT NULL,
            phase_timestamps_json TEXT,
            v1_score REAL,
            v2_overall REAL,
            control_score REAL,
            efficiency_score REAL,
            target_stability_score REAL,
            raw_metrics_json TEXT,
            metric_scores_json TEXT,
            config_version TEXT,
            valid INTEGER NOT NULL DEFAULT 1,
            notes TEXT
        );
        CREATE UNIQUE INDEX idx_trials_trial_id ON trials(trial_id) WHERE valid = 1;
        """
    )
    conn.close()

    store = TrialStore(db_path)
    cols = {row[1] for row in store._connect().execute("PRAGMA table_info(trials)")}
    assert "mode" in cols
    v2 = {
        "overall_score": 80,
        "control_score": 80,
        "efficiency_score": 80,
        "target_stability_score": 80,
        "raw_metrics": {},
        "metric_scores": {},
        "config_version": "v2_initial",
    }
    row_id, err = store.save_completed_trial(
        trial_id=99,
        user_name="test",
        source_type="normal",
        manual_label=None,
        v1_score=80,
        v2_result=v2,
        mode="box",
    )
    assert err is None
    assert row_id is not None
    assert store.list_trials(mode="box")[0]["mode"] == "box"


def test_mode_settings_migration(tmp_path: Path) -> None:
    from scoring.v2.config import active_config_key, migrate_legacy_settings, scorer_mode_key

    store = TrialStore(path=tmp_path / "migrate.db")
    store.set_setting("active_v2_config_path", "/legacy/path.json")
    store.set_setting("scorer_mode", "v1_legacy")
    migrate_legacy_settings(store)
    assert store.get_setting(active_config_key("open")) == "/legacy/path.json"
    assert store.get_setting(scorer_mode_key("open")) == "v1_legacy"
    assert store.get_setting(active_config_key("box")) != ""
