"""Calibration anchor proposal from labeled trials."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from scoring.v2.config import INITIAL_CONFIG_PATH, load_v2_config

LABELS = ("good", "okay", "bad")
LABELED_WEIGHT = 0.85
NORMAL_WEIGHT = 0.15


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _mad(values: list[float], med: float) -> float:
    if not values:
        return 0.0
    devs = [abs(v - med) for v in values]
    return float(statistics.median(devs))


def operator_balanced_anchor(
    trials: list[dict[str, Any]],
    metric_name: str,
    label: str,
) -> tuple[float | None, float, int, int]:
    """Median of operator-level medians for a metric and label."""
    by_op: dict[str, list[float]] = {}
    for t in trials:
        if str(t.get("manual_label", "")).lower() != label:
            continue
        op = str(t.get("user_name") or "anonymous")
        raw = t.get("raw_metrics_json")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                continue
        if not isinstance(raw, dict):
            continue
        val = raw.get(metric_name)
        if val is None:
            continue
        try:
            by_op.setdefault(op, []).append(float(val))
        except (TypeError, ValueError):
            continue
    op_medians = [_median(v) for v in by_op.values()]
    op_medians = [m for m in op_medians if m is not None]
    if not op_medians:
        return None, 0.0, 0, len(by_op)
    final = _median(op_medians)
    assert final is not None
    return final, _mad(op_medians, final), len(op_medians), len(by_op)


def check_ordering(good: float, okay: float, bad: float, direction: str) -> bool:
    if direction == "lower_is_better":
        return good < okay < bad
    return good > okay > bad


def propose_calibration(
    manual_trials: list[dict[str, Any]],
    normal_trials: list[dict[str, Any]] | None = None,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = json.loads(json.dumps(base_config or load_v2_config()))
    proposals: list[dict[str, Any]] = []

    for spec in cfg.get("metrics", []):
        name = str(spec["name"])
        direction = str(spec["direction"])
        anchors: dict[str, float | None] = {}
        mads: dict[str, float] = {}
        counts: dict[str, int] = {}
        ops: dict[str, int] = {}

        for label in LABELS:
            val, mad, cnt, n_ops = operator_balanced_anchor(manual_trials, name, label)
            anchors[label] = val
            mads[label] = mad
            counts[label] = cnt
            ops[label] = n_ops

        proposed = dict(spec)
        consistent = True
        g, o, b = anchors.get("good"), anchors.get("okay"), anchors.get("bad")
        if g is not None and o is not None and b is not None:
            consistent = check_ordering(g, o, b, direction)
            if consistent:
                proposed["good"] = g
                proposed["okay"] = o
                proposed["bad"] = b
        else:
            consistent = False

        # Optional light regularization from normal trial distribution (max 15%)
        if normal_trials and g is not None:
            normals: list[float] = []
            for t in normal_trials:
                raw = t.get("raw_metrics_json")
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                if isinstance(raw, dict) and raw.get(name) is not None:
                    try:
                        normals.append(float(raw[name]))
                    except (TypeError, ValueError):
                        pass
            if normals and consistent:
                nmed = _median(normals)
                if nmed is not None:
                    for key in ("good", "okay", "bad"):
                        if proposed.get(key) is not None:
                            cur = float(proposed[key])
                            proposed[key] = cur * LABELED_WEIGHT + nmed * NORMAL_WEIGHT

        proposals.append(
            {
                "metric": name,
                "current": {"good": spec["good"], "okay": spec["okay"], "bad": spec["bad"]},
                "proposed": {
                    "good": proposed.get("good", spec["good"]),
                    "okay": proposed.get("okay", spec["okay"]),
                    "bad": proposed.get("bad", spec["bad"]),
                },
                "medians": anchors,
                "mad": mads,
                "trial_counts": counts,
                "operators": ops,
                "consistent": consistent,
                "safe_to_apply": consistent and all(counts.get(l, 0) > 0 for l in LABELS),
                "spec": proposed,
            }
        )

    return {
        "base_version": cfg.get("version"),
        "proposals": proposals,
        "labeled_weight": LABELED_WEIGHT,
        "normal_weight": NORMAL_WEIGHT,
    }


def apply_proposal_to_config(
    proposal: dict[str, Any],
    *,
    version_suffix: str | None = None,
) -> dict[str, Any]:
    cfg = load_v2_config()
    prop_map = {p["metric"]: p["spec"] for p in proposal.get("proposals", []) if p.get("consistent")}
    new_metrics = []
    for spec in cfg.get("metrics", []):
        name = str(spec["name"])
        if name in prop_map:
            new_metrics.append(prop_map[name])
        else:
            new_metrics.append(spec)
    new_cfg = dict(cfg)
    new_cfg["metrics"] = new_metrics
    ts = version_suffix or __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    new_cfg["version"] = f"v2_calibrated_{ts}"
    new_cfg["description"] = "Calibrated V2 config (applied from Tune Scoring)"
    return new_cfg


def save_versioned_config(cfg: dict[str, Any], directory: Path | None = None) -> Path:
    d = directory or INITIAL_CONFIG_PATH.parent / "calibrated"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"scoring_config_{cfg['version']}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path
