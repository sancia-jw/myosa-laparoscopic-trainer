"""Conference leaderboard ranking tests."""

from __future__ import annotations

import json

from conference_leaderboard import pick_best_per_participant, rank_leaderboard


def _trial(name: str, score: float, seconds: float, *, mode: str = "open") -> dict:
    return {
        "user_name": name,
        "v2_overall": score,
        "mode": mode,
        "raw_metrics_json": json.dumps({"completion_time_s": seconds}),
    }


def test_rank_by_score_then_time() -> None:
    rows = rank_leaderboard(
        [
            _trial("Alice", 80, 12.0),
            _trial("Bob", 90, 15.0),
            _trial("Cara", 90, 11.0),
        ]
    )
    assert [r["name"] for r in rows] == ["Cara", "Bob", "Alice"]
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_duplicate_participant_keeps_best_score() -> None:
    rows = rank_leaderboard(
        [
            _trial("Test1", 60, 20.0),
            _trial(" test1 ", 85, 18.0),
            _trial("TEST1", 75, 10.0),
        ]
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "test1"
    assert rows[0]["score"] == 85


def test_duplicate_participant_tie_breaks_on_time() -> None:
    rows = rank_leaderboard(
        [
            _trial("Sam", 88, 14.0),
            _trial("sam", 88, 9.5),
        ]
    )
    assert len(rows) == 1
    assert rows[0]["completion_s"] == 9.5


def test_pick_best_per_participant_preserves_display_name() -> None:
    best = pick_best_per_participant([_trial("Mary", 70, 12), _trial("Mary", 82, 11)])
    assert len(best) == 1
    assert best[0]["user_name"] == "Mary"
