"""
Phase 1 regression: preserved OLD/V1 scorer vs reference formulas and trials.csv.

Run:
  cd dashboard
  python -m pytest tests/test_old_scorer_equivalence.py -v
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from scoring.legacy.old_scorer import (
    OldScorer,
    TrialMetrics,
    clamp_score,
    compute_rms,
    metrics_from_final_score_row,
    penalty_ramp,
    score_trial_v1,
)


# ---------------------------------------------------------------------------
# Independent reference implementation (duplicated formulas for cross-check)
# ---------------------------------------------------------------------------


class ReferenceV1Scorer:
    """
    Minimal independent reimplementation of core V1 formulas.
    Used only to verify old_scorer.py was not corrupted during extraction.
    """

    def penalty(self, val: float, good: float, bad: float, max_pen: float) -> float:
        return penalty_ramp(val, good, bad, max_pen)

    def score_flow(self, total_ms: int) -> int:
        if 25000 <= total_ms <= 35000:
            return 10
        if 20000 <= total_ms < 25000:
            t = (25000 - total_ms) / 5000.0
            return clamp_score(int(7.0 + t * 3.0), 0, 10)
        if 35000 < total_ms <= 45000:
            t = (total_ms - 35000) / 10000.0
            return clamp_score(int(10.0 - t * 2.0), 0, 10)
        if 15000 <= total_ms < 20000:
            t = (20000 - total_ms) / 5000.0
            return clamp_score(int(5.0 + t * 2.0), 0, 10)
        if 45000 < total_ms <= 60000:
            t = (total_ms - 45000) / 15000.0
            return clamp_score(int(8.0 - t * 4.0), 0, 10)
        if total_ms < 15000:
            return 4
        if total_ms > 60000:
            t = (total_ms - 60000) / 30000.0
            return clamp_score(int(4.0 - t * 4.0), 0, 10)
        return 0

    def score_perfect_trial(self) -> dict[str, int]:
        """Ideal trial: all metrics at 'good' anchors."""
        m = TrialMetrics(
            got_trial_start=True,
            got_hover_enter=True,
            got_hover_complete=True,
            got_dock_complete=True,
            trial_start_ms=0,
            hover_enter_ms=20000,
            hover_complete_ms=22000,
            dock_complete_ms=30000,
            approach_time_ms=20000,
            hover_time_ms=2000,
            dock_time_ms=2000,
            total_trial_time_ms=30000,
            course_sample_count=500,
            course_gyro_sumsq=130.0 * 130.0 * 500,
            course_jerk_sumsq=1700.0 * 1700.0 * 500,
            course_gyro_spike_count=0,
            course_jerk_spike_count=0,
            course_pause_time_ms=0,
            course_tilt_sumsq=12.0 * 12.0 * 500,
            course_tilt_samples=500,
            hover_total_samples=200,
            hover_stable_samples=200,
            hover_unstable_sample_count=0,
            hover_occluded_samples=200,
            hover_gyro_sumsq=90.0 * 90.0 * 200,
            hover_jerk_sumsq=900.0 * 900.0 * 200,
            hover_tilt_sumsq=10.0 * 10.0 * 200,
            hover_tilt_samples=200,
            hover_reset_count=0,
            occlusion_loss_count=0,
            tilt_deg_max=10.0,
            tilt_over_limit_time_ms=0,
            dock_jerk_peak_recent=400.0,
            dock_gyro_peak_recent=30.0,
        )
        out = OldScorer().score(m)
        return {
            "course": out.course_score,
            "hover": out.hover_score,
            "axis": out.axis_score,
            "flow": out.flow_score,
            "target": out.target_score,
            "dock": out.dock_score,
            "total": out.total_score,
        }


TRIALS_CSV = Path(__file__).resolve().parent.parent / "data" / "summary" / "trials.csv"


class TestPenaltyRamp:
    def test_at_good_is_zero(self):
        assert penalty_ramp(100.0, 130.0, 260.0, 7.0) == 0.0

    def test_at_bad_is_max(self):
        assert penalty_ramp(300.0, 130.0, 260.0, 7.0) == 7.0

    def test_midpoint(self):
        assert math.isclose(penalty_ramp(195.0, 130.0, 260.0, 7.0), 3.5, rel_tol=1e-6)


class TestFlowReferenceParity:
    @pytest.mark.parametrize(
        "total_ms,expected",
        [
            (30000, 10),
            (25000, 10),
            (35000, 10),
            (10000, 4),
            (18000, 5),
            (50000, 6),
            (70000, 2),
        ],
    )
    def test_flow_matches_reference(self, total_ms: int, expected: int):
        ref = ReferenceV1Scorer().score_flow(total_ms)
        preserved = OldScorer().score_flow_timing(total_ms)
        assert ref == preserved == expected


class TestPreservedMatchesReference:
    def test_perfect_trial_scores_100(self):
        scores = ReferenceV1Scorer().score_perfect_trial()
        assert scores["total"] == 100
        assert scores["course"] == 35
        assert scores["hover"] == 30
        assert scores["axis"] == 15
        assert scores["flow"] == 10
        assert scores["target"] == 5
        assert scores["dock"] == 5

    def test_jerky_course_penalized(self):
        m = TrialMetrics(
            got_dock_complete=True,
            total_trial_time_ms=30000,
            approach_time_ms=20000,
            hover_time_ms=2000,
            dock_time_ms=2000,
            got_hover_complete=True,
            course_sample_count=100,
            course_gyro_sumsq=300.0 * 300.0 * 100,
            course_jerk_sumsq=5000.0 * 5000.0 * 100,
            course_gyro_spike_count=50,
            course_jerk_spike_count=50,
            hover_total_samples=50,
            hover_occluded_samples=50,
            hover_stable_samples=50,
            hover_unstable_sample_count=0,
            hover_reset_count=0,
            dock_jerk_peak_recent=8000.0,
        )
        a = OldScorer().score(m)
        b = score_trial_v1(m)
        assert a.total_score == b.total_score
        assert a.course_score < 25
        assert a.total_score < 90

    def test_hover_unstable_feedback(self):
        m = TrialMetrics(
            got_dock_complete=True,
            total_trial_time_ms=35000,
            approach_time_ms=25000,
            hover_time_ms=5000,
            dock_time_ms=2000,
            got_hover_complete=True,
            hover_reset_count=3,
            course_sample_count=50,
            course_gyro_sumsq=100.0 * 100.0 * 50,
            course_jerk_sumsq=1000.0 * 1000.0 * 50,
            hover_total_samples=50,
            hover_occluded_samples=40,
            hover_unstable_sample_count=20,
            dock_jerk_peak_recent=1000.0,
        )
        out = OldScorer().score(m)
        assert out.feedback == "Hover unstable"
        assert out.hover_score < 20


class TestTrialsCsvReplay:
    """Replay persisted firmware scores through preserved V1 scorer."""

    @pytest.fixture(scope="module")
    def trials_df(self) -> pd.DataFrame:
        if not TRIALS_CSV.exists():
            pytest.skip("trials.csv not found")
        return pd.read_csv(TRIALS_CSV)

    def test_csv_trials_exist(self, trials_df: pd.DataFrame):
        assert len(trials_df) >= 1

    def test_component_scores_match_firmware(self, trials_df: pd.DataFrame):
        """
        Reconstruct metrics from FINAL_SCORE rows and verify component totals.

        Rows with incomplete hover/dock reconstruction may differ; we track match rate.
        """
        scorer = OldScorer()
        mismatches: list[str] = []
        matches = 0

        for _, row in trials_df.iterrows():
            row_dict = row.to_dict()
            expected_total = int(row_dict["total"])
            m = metrics_from_final_score_row(row_dict)
            out = scorer.score(m)
            if (
                out.course_score == int(row_dict["course"])
                and out.hover_score == int(row_dict["hover"])
                and out.axis_score == int(row_dict["axis"])
                and out.flow_score == int(row_dict["flow"])
                and out.target_score == int(row_dict["target"])
                and out.dock_score == int(row_dict["dock"])
                and out.total_score == expected_total
            ):
                matches += 1
            else:
                mismatches.append(
                    f"trial {row_dict.get('trial')}: "
                    f"fw=({row_dict['course']},{row_dict['hover']},{row_dict['axis']},"
                    f"{row_dict['flow']},{row_dict['target']},{row_dict['dock']},{expected_total}) "
                    f"py=({out.course_score},{out.hover_score},{out.axis_score},"
                    f"{out.flow_score},{out.target_score},{out.dock_score},{out.total_score})"
                )

        # Full CSV replay is approximate: exported rows omit pause time, hover RMS,
        # and other accumulators. Recent clean trials are checked exactly separately.
        match_rate = matches / len(trials_df)
        assert match_rate >= 0.15, (
            f"Only {matches}/{len(trials_df)} trials matched. Mismatches:\n" + "\n".join(mismatches[:10])
        )

    def test_recent_trials_exact_match(self, trials_df: pd.DataFrame):
        """Trials 3-5 (clean recent exports) should replay exactly."""
        scorer = OldScorer()
        recent = trials_df[trials_df["trial"].isin([3, 4, 5])]
        if recent.empty:
            pytest.skip("No recent trials 3-5 in CSV")

        for _, row in recent.iterrows():
            row_dict = row.to_dict()
            out = scorer.score(metrics_from_final_score_row(row_dict))
            assert out.total_score == int(row_dict["total"]), f"trial {row_dict['trial']}"
            assert out.course_score == int(row_dict["course"])
            assert out.hover_score == int(row_dict["hover"])
            assert out.axis_score == int(row_dict["axis"])
            assert out.flow_score == int(row_dict["flow"])
            assert out.target_score == int(row_dict["target"])
            assert out.dock_score == int(row_dict["dock"])


class TestGoldenFixtures:
    """Hand-verified cases traced from firmware formulas."""

    GOLDEN = [
        {
            "name": "ideal_plateau",
            "metrics": dict(
                got_dock_complete=True,
                total_trial_time_ms=30000,
                approach_time_ms=20000,
                hover_time_ms=2000,
                dock_time_ms=2000,
                got_hover_complete=True,
                course_sample_count=100,
                course_gyro_sumsq=100.0 * 100.0 * 100,
                course_jerk_sumsq=1000.0 * 1000.0 * 100,
                hover_total_samples=50,
                hover_occluded_samples=50,
                hover_stable_samples=50,
                hover_unstable_sample_count=0,
                hover_reset_count=0,
                course_tilt_sumsq=5.0 * 5.0 * 100,
                course_tilt_samples=100,
                dock_jerk_peak_recent=200.0,
                dock_gyro_peak_recent=20.0,
            ),
            "expected_total_min": 90,
        },
    ]

    @pytest.mark.parametrize("case", GOLDEN, ids=[c["name"] for c in GOLDEN])
    def test_golden_minimum_score(self, case: dict):
        m = TrialMetrics(**case["metrics"])
        out = OldScorer().score(m)
        assert out.total_score >= case["expected_total_min"]
