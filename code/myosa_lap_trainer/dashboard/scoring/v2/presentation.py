"""Score and category presentation helpers for UI."""

from __future__ import annotations

from datetime import datetime
from typing import Any


CATEGORY_LABELS = {
    "control": "Control",
    "efficiency": "Efficiency",
    "target_stability": "Target Stability",
}

CATEGORY_MAX_POINTS = {
    "control": 40.0,
    "efficiency": 30.0,
    "target_stability": 30.0,
}


def format_duration_ms(ms: int | float | None) -> str:
    if ms is None:
        return "—"
    sec = max(0.0, float(ms) / 1000.0)
    if sec < 60.0:
        return f"{sec:.1f} s"
    minutes = int(sec // 60)
    remainder = sec % 60
    return f"{minutes}:{remainder:04.1f}"


def format_duration_seconds(sec: float | None) -> str:
    if sec is None:
        return "—"
    return format_duration_ms(sec * 1000.0)


def format_trial_timestamp(created_at: str | None) -> str:
    if not created_at:
        return "—"
    try:
        dt = datetime.fromisoformat(str(created_at))
        return dt.strftime("%b %d, %I:%M %p").replace(" 0", " ")
    except (TypeError, ValueError):
        return str(created_at)[:16]


def format_trial_label(row: dict[str, Any]) -> str:
    name = (str(row.get("user_name") or "")).strip() or "Anonymous"
    ts = format_trial_timestamp(row.get("created_at"))
    score = display_overall_score(row.get("v2_overall"))
    return f"{name} · {ts} · Score {score}"


def display_overall_score(score: float | int | None) -> int:
    """Consistent rounded overall score for all UI surfaces."""
    if score is None:
        return 0
    return int(round(float(score)))


def category_points(quality_score: float, category: str) -> tuple[float, float]:
    max_pts = CATEGORY_MAX_POINTS.get(category, 0.0)
    pts = (float(quality_score) / 100.0) * max_pts
    return pts, max_pts


def build_category_summary(
    control_q: float,
    efficiency_q: float,
    target_q: float,
) -> dict[str, dict[str, float]]:
    return {
        "control": {
            "quality": control_q,
            "max_quality": 100.0,
            "points": category_points(control_q, "control")[0],
            "max_points": 40.0,
        },
        "efficiency": {
            "quality": efficiency_q,
            "max_quality": 100.0,
            "points": category_points(efficiency_q, "efficiency")[0],
            "max_points": 30.0,
        },
        "target_stability": {
            "quality": target_q,
            "max_quality": 100.0,
            "points": category_points(target_q, "target_stability")[0],
            "max_points": 30.0,
        },
    }


def overall_from_categories(cats: dict[str, dict[str, float]]) -> float:
    return sum(c["points"] for c in cats.values())


def metric_point_contribution(
    metric_score: float | None,
    spec: dict[str, Any],
    cat_weights: dict[str, float],
) -> tuple[float, float]:
    if metric_score is None:
        return 0.0, 0.0
    cat = str(spec.get("category", "control"))
    cat_w = float(cat_weights.get(cat, 0.33))
    weight = float(spec.get("weight", 0.0))
    max_pts = weight * cat_w * 100.0
    earned = float(metric_score) * weight * cat_w
    return earned, max_pts


def plotly_chart_defaults() -> dict[str, Any]:
    return {
        "paper_bgcolor": "#FFF7EF",
        "plot_bgcolor": "#FFF7EF",
        "font": {"color": "#1B1E3F", "size": 12},
        "xaxis": {
            "gridcolor": "rgba(27,30,63,0.08)",
            "linecolor": "rgba(27,30,63,0.15)",
            "tickfont": {"color": "#1B1E3F"},
        },
        "yaxis": {
            "gridcolor": "rgba(27,30,63,0.08)",
            "linecolor": "rgba(27,30,63,0.15)",
            "tickfont": {"color": "#1B1E3F"},
        },
        "margin": {"l": 40, "r": 20, "t": 40, "b": 40},
    }
