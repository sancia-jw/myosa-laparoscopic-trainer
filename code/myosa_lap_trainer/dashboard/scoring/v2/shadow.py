"""V2 shadow-mode comparison logging (CSV only, no SQLite)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scoring.v2.scorer import V2ScoreResult, score_trial_v2

ROOT = Path(__file__).resolve().parents[2]
SHADOW_CSV = ROOT / "data" / "v2_shadow_results.csv"
SHADOW_CSV.parent.mkdir(parents=True, exist_ok=True)

SHADOW_COLUMNS = [
    "timestamp",
    "trial",
    "v1_total",
    "v2_overall",
    "control_score",
    "efficiency_score",
    "target_stability_score",
    "v2_config_version",
    "raw_metrics_json",
    "metric_scores_json",
    "warnings",
]


def _result_to_row(final_row: dict[str, Any], result: V2ScoreResult) -> dict[str, Any]:
    trial = final_row.get("trial")
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "trial": trial,
        "v1_total": final_row.get("total"),
        "v2_overall": round(result.overall_score, 1),
        "control_score": round(result.control_score, 1),
        "efficiency_score": round(result.efficiency_score, 1),
        "target_stability_score": round(result.target_stability_score, 1),
        "v2_config_version": result.config_version,
        "raw_metrics_json": json.dumps(result.raw_metrics, sort_keys=True),
        "metric_scores_json": json.dumps(
            {k: (round(v, 1) if v is not None else None) for k, v in result.metric_scores.items()},
            sort_keys=True,
        ),
        "warnings": "; ".join(result.warnings) if result.warnings else "",
    }


def append_shadow_result(
    final_row: dict[str, Any],
    *,
    logged_trials: set[int],
    enabled: bool = True,
) -> V2ScoreResult | None:
    """
    Compute and append one V2 shadow row for a completed trial.

    Returns None when disabled, duplicate, or invalid trial id.
    CSV failures are swallowed so live demos continue.
    """
    if not enabled:
        return None

    trial_raw = final_row.get("trial")
    try:
        trial_id = int(trial_raw)
    except (TypeError, ValueError):
        return None

    if trial_id in logged_trials:
        return None

    result = score_trial_v2(final_row)
    row = _result_to_row(final_row, result)

    try:
        if SHADOW_CSV.exists():
            df = pd.read_csv(SHADOW_CSV)
            if "trial" in df.columns and trial_id in df["trial"].astype(int).values:
                logged_trials.add(trial_id)
                return result
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row], columns=SHADOW_COLUMNS)
        df.to_csv(SHADOW_CSV, index=False)
    except Exception:
        return result

    logged_trials.add(trial_id)
    return result
