"""Last-known live metric values — preserved across phase changes."""

from __future__ import annotations

from typing import Any


def _f(val: Any) -> float | None:
    if val is None:
        return None
    try:
        x = float(val)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def clear_live_metrics(state: dict[str, Any]) -> None:
    state["live_metrics_last"] = {}
    state["live_chart_series"] = []


def update_live_metrics(state: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    """Merge new LIVE packet into last-known metrics; never erase with missing fields."""
    if not live:
        return state.get("live_metrics_last") or {}

    last: dict[str, Any] = dict(state.get("live_metrics_last") or {})

    for key in ("gyro_rms", "jerk_rms", "spike_rate"):
        v = _f(live.get(key))
        if v is not None:
            last[key] = v

    if live.get("elapsed_ms") is not None:
        try:
            last["elapsed_ms"] = int(live["elapsed_ms"])
        except (TypeError, ValueError):
            pass

    if live.get("stable") is not None:
        last["stable"] = int(live["stable"])
    if live.get("occ") is not None or live.get("occluded") is not None:
        occ = live.get("occ", live.get("occluded"))
        last["occ"] = int(occ) if occ is not None else last.get("occ")

    if live.get("hover_ms") is not None:
        try:
            last["hover_ms"] = int(live["hover_ms"])
        except (TypeError, ValueError):
            pass
    if live.get("hover_target_ms") is not None:
        try:
            last["hover_target_ms"] = int(live["hover_target_ms"])
        except (TypeError, ValueError):
            pass

    state["live_metrics_last"] = last
    return last


def append_chart_live(
    state: dict[str, Any],
    *,
    live_v2: dict[str, Any] | None = None,
) -> None:
    """Append one chart point per LIVE packet — responsive 0–100 quality traces."""
    from scoring.v2.config import load_active_v2_config
    from scoring.v2.scorer import piecewise_metric_score

    last = state.get("live_metrics_last") or {}
    series: list[dict[str, float]] = list(state.get("live_chart_series") or [])
    prev = series[-1] if series else {"rot": 50.0, "lin": 50.0}

    try:
        from operating_mode import get_active_mode
        from storage import get_store

        cfg = load_active_v2_config(get_store, mode=get_active_mode(state))
    except Exception:
        cfg = load_active_v2_config()
    piecewise = cfg.get("piecewise_scores", {})
    gyro_spec = next((m for m in cfg.get("metrics", []) if m["name"] == "course_smoothness_gyro_rms"), None)

    rot = prev["rot"]
    gyro = _f(last.get("gyro_rms"))
    if gyro_spec and gyro is not None:
        scored = piecewise_metric_score(
            gyro,
            good=float(gyro_spec["good"]),
            okay=float(gyro_spec["okay"]),
            bad=float(gyro_spec["bad"]),
            direction=str(gyro_spec.get("direction", "lower_is_better")),
            good_score=float(piecewise.get("good", 90)),
            okay_score=float(piecewise.get("okay", 65)),
            bad_score=float(piecewise.get("bad", 30)),
        )
        if scored is not None:
            rot = scored

    lin = prev["lin"]
    jerk = _f(last.get("jerk_rms"))
    if jerk is not None:
        scored = piecewise_metric_score(
            jerk,
            good=400.0,
            okay=1000.0,
            bad=2200.0,
            direction="lower_is_better",
            good_score=float(piecewise.get("good", 90)),
            okay_score=float(piecewise.get("okay", 65)),
            bad_score=float(piecewise.get("bad", 30)),
        )
        if scored is not None:
            lin = scored

    series.append({"rot": float(rot), "lin": float(lin)})
    if len(series) > 80:
        series = series[-80:]
    state["live_chart_series"] = series


def append_chart_quality(state: dict[str, Any], live_v2: dict[str, Any] | None) -> None:
    """Legacy alias — chart updates via append_chart_live on each LIVE packet."""
    append_chart_live(state, live_v2=live_v2)


def get_metric_display(last: dict[str, Any], key: str, *, fmt: str = "{}") -> str:
    if key not in last or last[key] is None:
        return "—"
    try:
        return fmt.format(last[key])
    except (TypeError, ValueError):
        return str(last[key])
