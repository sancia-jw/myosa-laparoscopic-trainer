"""Conference leaderboard ranking from stored trials."""

from __future__ import annotations

import json
from typing import Any

from conference_mode import participant_display_name, participant_key
from scoring.v2.presentation import format_duration_seconds
from storage import get_store


def completion_seconds(row: dict[str, Any]) -> float | None:
    raw = row.get("raw_metrics_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    val = raw.get("completion_time_s")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _trial_score(row: dict[str, Any]) -> float:
    try:
        return float(row.get("v2_overall") or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_better_trial(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    c_score = _trial_score(candidate)
    cur_score = _trial_score(current)
    if c_score > cur_score:
        return True
    if c_score < cur_score:
        return False
    c_time = completion_seconds(candidate)
    cur_time = completion_seconds(current)
    if c_time is None:
        return False
    if cur_time is None:
        return True
    return c_time < cur_time


def pick_best_per_participant(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One best trial per participant using score then completion time."""
    best: dict[str, dict[str, Any]] = {}
    for trial in trials:
        name = participant_display_name(trial.get("user_name"))
        key = participant_key(name)
        if not key:
            continue
        if key not in best or _is_better_trial(trial, best[key]):
            best[key] = trial
    return list(best.values())


def rank_leaderboard(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank participants: higher score first, faster time breaks ties."""
    rows = pick_best_per_participant(trials)

    def sort_key(trial: dict[str, Any]) -> tuple[float, float]:
        comp = completion_seconds(trial)
        return (-_trial_score(trial), comp if comp is not None else 1e12)

    rows.sort(key=sort_key)
    ranked: list[dict[str, Any]] = []
    for idx, trial in enumerate(rows, start=1):
        comp = completion_seconds(trial)
        ranked.append(
            {
                "rank": idx,
                "name": participant_display_name(trial.get("user_name")) or "—",
                "score": _trial_score(trial),
                "completion_s": comp,
                "completion_display": format_duration_seconds(comp),
                "trial_id": trial.get("trial_id"),
                "created_at": trial.get("created_at"),
            }
        )
    return ranked


def fetch_leaderboard(*, mode: str) -> list[dict[str, Any]]:
    store = get_store()
    trials = store.list_conference_trials(mode=mode)
    return rank_leaderboard(trials)
