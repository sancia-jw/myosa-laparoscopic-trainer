"""Experimental V2 shadow scorer (not conference-active)."""

from scoring.v2.scorer import V2ScoreResult, piecewise_metric_score, score_trial_v2
from scoring.v2.shadow import SHADOW_CSV, append_shadow_result

__all__ = [
    "V2ScoreResult",
    "piecewise_metric_score",
    "score_trial_v2",
    "append_shadow_result",
    "SHADOW_CSV",
]
