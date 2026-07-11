"""V2 shadow scorer — piecewise linear metric scoring."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from scoring.v2.config import load_active_v2_config
from scoring.v2.metrics import extract_raw_metrics


def clamp_score(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def piecewise_metric_score(
    value: float | None,
    *,
    good: float,
    okay: float,
    bad: float,
    direction: str,
    good_score: float = 90.0,
    okay_score: float = 65.0,
    bad_score: float = 30.0,
) -> float | None:
    """
    Continuous piecewise-linear score for one metric.

    Good → good_score (90), okay → okay_score (65), bad → bad_score (30).
    Better than good trends toward 100; worse than bad trends toward 0.
    """
    if value is None or math.isnan(value) or math.isinf(value):
        return None

    if direction == "lower_is_better":
        if good >= bad:
            return None
        if value <= good:
            if good <= 0:
                return clamp_score(100.0)
            ratio = max(0.0, 1.0 - value / good)
            return clamp_score(good_score + ratio * (100.0 - good_score))
        if value <= okay:
            t = (value - good) / (okay - good)
            return clamp_score(good_score - t * (good_score - okay_score))
        if value <= bad:
            t = (value - okay) / (bad - okay)
            return clamp_score(okay_score - t * (okay_score - bad_score))
        if bad <= 0:
            return clamp_score(0.0)
        excess = (value - bad) / bad
        return clamp_score(bad_score * max(0.0, 1.0 - excess))

    if direction == "higher_is_better":
        if good <= bad:
            return None
        if value >= good:
            if good <= 0:
                return clamp_score(good_score)
            ratio = min(2.0, value / good - 1.0)
            return clamp_score(good_score + ratio * (100.0 - good_score))
        if value >= okay:
            t = (good - value) / (good - okay)
            return clamp_score(good_score - t * (good_score - okay_score))
        if value >= bad:
            t = (okay - value) / (okay - bad)
            return clamp_score(okay_score - t * (okay_score - bad_score))
        if bad >= 0:
            deficit = (bad - value) / max(bad, 1e-6)
            return clamp_score(bad_score * max(0.0, 1.0 - deficit))
        return clamp_score(0.0)

    return None


@dataclass
class V2ScoreResult:
    overall_score: float
    control_score: float
    efficiency_score: float
    target_stability_score: float
    raw_metrics: dict[str, float | None]
    metric_scores: dict[str, float | None]
    config_version: str
    strongest_category: str
    weakest_category: str
    feedback: str
    warnings: list[str] = field(default_factory=list)


def _category_score(
    metric_defs: list[dict[str, Any]],
    raw: dict[str, float | None],
    piecewise: dict[str, float],
) -> tuple[float, dict[str, float | None], list[str]]:
    scores: dict[str, float | None] = {}
    warnings: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for spec in metric_defs:
        if not spec.get("enabled", True):
            continue
        name = str(spec["name"])
        value = raw.get(name)
        score = piecewise_metric_score(
            value,
            good=float(spec["good"]),
            okay=float(spec["okay"]),
            bad=float(spec["bad"]),
            direction=str(spec["direction"]),
            good_score=float(piecewise.get("good", 90)),
            okay_score=float(piecewise.get("okay", 65)),
            bad_score=float(piecewise.get("bad", 30)),
        )
        scores[name] = score
        weight = float(spec.get("weight", 1.0))
        if score is None:
            if spec.get("optional"):
                warnings.append(f"{name}: skipped (optional data missing)")
            else:
                warnings.append(f"{name}: skipped (missing data)")
            continue
        weighted_sum += score * weight
        weight_total += weight

    if weight_total <= 0:
        return 50.0, scores, warnings
    return clamp_score(weighted_sum / weight_total), scores, warnings


def score_trial_v2(
    final_row: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> V2ScoreResult:
    cfg = config or load_active_v2_config()
    metric_defs: list[dict[str, Any]] = list(cfg.get("metrics", []))
    piecewise = cfg.get("piecewise_scores", {})
    cat_weights = cfg.get("category_weights", {})

    raw, extract_warnings = extract_raw_metrics(final_row, metric_defs)

    by_cat: dict[str, list[dict[str, Any]]] = {}
    for spec in metric_defs:
        by_cat.setdefault(str(spec["category"]), []).append(spec)

    cat_scores: dict[str, float] = {}
    metric_scores: dict[str, float | None] = {}
    warnings = list(extract_warnings)

    for cat, specs in by_cat.items():
        score, m_scores, cat_warnings = _category_score(specs, raw, piecewise)
        cat_scores[cat] = score
        metric_scores.update(m_scores)
        warnings.extend(cat_warnings)

    cw = float(cat_weights.get("control", 0.4))
    ew = float(cat_weights.get("efficiency", 0.3))
    tw = float(cat_weights.get("target_stability", 0.3))
    overall = clamp_score(
        cat_scores.get("control", 50.0) * cw
        + cat_scores.get("efficiency", 50.0) * ew
        + cat_scores.get("target_stability", 50.0) * tw
    )

    labels = {
        "control": cat_scores.get("control", 0.0),
        "efficiency": cat_scores.get("efficiency", 0.0),
        "target_stability": cat_scores.get("target_stability", 0.0),
    }
    strongest = max(labels, key=labels.get)
    weakest = min(labels, key=labels.get)

    label_map = {
        "control": "Control",
        "efficiency": "Efficiency",
        "target_stability": "Target Stability",
    }
    feedback = f"Strongest: {label_map[strongest]}. Focus next: {label_map[weakest]}."

    low_conf = [str(m["name"]) for m in metric_defs if m.get("confidence") == "low"]
    if low_conf:
        warnings.append(f"Low-confidence anchors: {', '.join(low_conf)}")

    return V2ScoreResult(
        overall_score=overall,
        control_score=cat_scores.get("control", 50.0),
        efficiency_score=cat_scores.get("efficiency", 50.0),
        target_stability_score=cat_scores.get("target_stability", 50.0),
        raw_metrics=raw,
        metric_scores=metric_scores,
        config_version=str(cfg.get("version", "v2_initial")),
        strongest_category=label_map[strongest],
        weakest_category=label_map[weakest],
        feedback=feedback,
        warnings=warnings,
    )
