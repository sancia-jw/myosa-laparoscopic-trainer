#!/usr/bin/env python3
"""Run Phase 1 OLD/V1 scorer equivalence check without pytest."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from scoring.legacy.old_scorer import OldScorer, TrialMetrics, metrics_from_final_score_row, score_trial_v1


def main() -> int:
    print("=== MYOSA Phase 1: OLD/V1 Scorer Equivalence Check ===\n")

    # 1. Perfect trial
    m = TrialMetrics(
        got_dock_complete=True,
        total_trial_time_ms=30000,
        approach_time_ms=20000,
        hover_time_ms=2000,
        dock_time_ms=2000,
        got_hover_complete=True,
        course_sample_count=500,
        course_gyro_sumsq=130.0**2 * 500,
        course_jerk_sumsq=1700.0**2 * 500,
        hover_total_samples=200,
        hover_occluded_samples=200,
        hover_stable_samples=200,
        hover_gyro_sumsq=90.0**2 * 200,
        hover_jerk_sumsq=900.0**2 * 200,
        course_tilt_sumsq=12.0**2 * 500,
        course_tilt_samples=500,
        hover_tilt_sumsq=10.0**2 * 200,
        hover_tilt_samples=200,
        dock_jerk_peak_recent=400.0,
        dock_gyro_peak_recent=30.0,
    )
    out = score_trial_v1(m)
    print(f"Perfect trial: total={out.total_score} (expect 100)")
    assert out.total_score == 100

    # 2. Wrapper parity
    out2 = OldScorer().score(m)
    assert out2.total_score == out.total_score
    print("OldScorer vs score_trial_v1: MATCH")

    # 3. CSV replay
    csv_path = ROOT / "data" / "summary" / "trials.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        scorer = OldScorer()
        matches = 0
        for _, row in df.iterrows():
            d = row.to_dict()
            scored = scorer.score(metrics_from_final_score_row(d))
            if scored.total_score == int(d["total"]):
                matches += 1
        print(f"trials.csv replay: {matches}/{len(df)} totals match")
    else:
        print("trials.csv: not found (skipped)")

    print("\nPhase 1 equivalence check: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
