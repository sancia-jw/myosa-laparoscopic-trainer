"""SQLite storage for Smooth Operator trials and calibration data."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "smooth_operator.db"


class TrialStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS trials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trial_id INTEGER NOT NULL,
                        user_name TEXT,
                        source_type TEXT NOT NULL DEFAULT 'normal',
                        manual_label TEXT,
                        created_at TEXT NOT NULL,
                        phase_timestamps_json TEXT,
                        v1_score REAL,
                        v2_overall REAL,
                        control_score REAL,
                        efficiency_score REAL,
                        target_stability_score REAL,
                        raw_metrics_json TEXT,
                        metric_scores_json TEXT,
                        config_version TEXT,
                        valid INTEGER NOT NULL DEFAULT 1,
                        notes TEXT
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )
                self._migrate_schema(conn)
                conn.commit()
            finally:
                conn.close()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trials)")}
        if "mode" not in cols:
            conn.execute("ALTER TABLE trials ADD COLUMN mode TEXT NOT NULL DEFAULT 'open'")
        if "conference_mode" not in cols:
            conn.execute("ALTER TABLE trials ADD COLUMN conference_mode INTEGER NOT NULL DEFAULT 0")
        conn.execute("DROP INDEX IF EXISTS idx_trials_trial_id")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trials_trial_id_mode
                ON trials(trial_id, mode) WHERE valid = 1
            """
        )

    def get_setting(self, key: str, default: str = "") -> str:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    row = conn.execute(
                        "SELECT value FROM settings WHERE key = ?", (key,)
                    ).fetchone()
                    return row["value"] if row else default
                finally:
                    conn.close()
        except Exception:
            return default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
                conn.commit()
            finally:
                conn.close()

    def save_completed_trial(
        self,
        *,
        trial_id: int,
        user_name: str | None,
        source_type: str,
        manual_label: str | None,
        v1_score: float | None,
        v2_result: dict[str, Any],
        phase_timestamps: dict[str, Any] | None = None,
        notes: str | None = None,
        valid: bool = True,
        mode: str = "open",
        conference_mode: bool = False,
    ) -> tuple[int | None, str | None]:
        """Insert one completed trial. Returns (row_id, error_reason)."""
        mode = str(mode or "open").lower().strip()
        if mode not in ("open", "box"):
            mode = "open"
        try:
            with self._lock:
                conn = self._connect()
                try:
                    if valid:
                        exists = conn.execute(
                            "SELECT id FROM trials WHERE trial_id=? AND mode=? AND valid=1",
                            (trial_id, mode),
                        ).fetchone()
                        if exists:
                            return None, f"duplicate firmware trial_id={trial_id} mode={mode} (db id={exists['id']})"
                    cur = conn.execute(
                        """
                        INSERT INTO trials (
                            trial_id, user_name, source_type, manual_label, created_at,
                            phase_timestamps_json, v1_score, v2_overall, control_score,
                            efficiency_score, target_stability_score, raw_metrics_json,
                            metric_scores_json, config_version, valid, notes, mode,
                            conference_mode
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            trial_id,
                            user_name or None,
                            source_type,
                            manual_label,
                            datetime.now().isoformat(timespec="seconds"),
                            json.dumps(phase_timestamps or {}),
                            v1_score,
                            v2_result.get("overall_score"),
                            v2_result.get("control_score"),
                            v2_result.get("efficiency_score"),
                            v2_result.get("target_stability_score"),
                            json.dumps(v2_result.get("raw_metrics", {})),
                            json.dumps(v2_result.get("metric_scores", {})),
                            v2_result.get("config_version"),
                            1 if valid else 0,
                            notes,
                            mode,
                            1 if conference_mode else 0,
                        ),
                    )
                    conn.commit()
                    return int(cur.lastrowid), None
                finally:
                    conn.close()
        except Exception as exc:
            return None, str(exc)

    def count_trials(self, *, valid_only: bool = False) -> int:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    if valid_only:
                        row = conn.execute("SELECT COUNT(*) AS n FROM trials WHERE valid=1").fetchone()
                    else:
                        row = conn.execute("SELECT COUNT(*) AS n FROM trials").fetchone()
                    return int(row["n"]) if row else 0
                finally:
                    conn.close()
        except Exception:
            return 0

    def list_conference_trials(self, *, mode: str, limit: int = 5000) -> list[dict[str, Any]]:
        return self.list_trials(
            source_type="normal",
            named_only=True,
            mode=mode,
            limit=limit,
            conference_only=True,
        )

    def clear_conference_trials(self) -> int:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    cur = conn.execute("DELETE FROM trials WHERE conference_mode=1")
                    conn.commit()
                    return int(cur.rowcount)
                finally:
                    conn.close()
        except Exception:
            return 0

    def list_trials(
        self,
        *,
        user_name: str | None = None,
        source_type: str | None = None,
        manual_label: str | None = None,
        named_only: bool = False,
        mode: str | None = None,
        conference_only: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        try:
            clauses = ["valid=1"]
            params: list[Any] = []
            if conference_only:
                clauses.append("conference_mode=1")
            if named_only:
                clauses.append("user_name IS NOT NULL AND TRIM(user_name) != ''")
            if user_name:
                clauses.append("LOWER(TRIM(user_name)) = LOWER(TRIM(?))")
                params.append(user_name)
            if source_type:
                clauses.append("source_type = ?")
                params.append(source_type)
            if manual_label:
                clauses.append("manual_label = ?")
                params.append(manual_label)
            if mode and mode != "all":
                clauses.append("mode = ?")
                params.append(mode)
            sql = f"SELECT * FROM trials WHERE {' AND '.join(clauses)} ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
            params.append(limit)
            with self._lock:
                conn = self._connect()
                try:
                    rows = conn.execute(sql, params).fetchall()
                    return [dict(r) for r in rows]
                finally:
                    conn.close()
        except Exception:
            return []

    def get_trial(self, db_id: int) -> dict[str, Any] | None:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    row = conn.execute("SELECT * FROM trials WHERE id=?", (db_id,)).fetchone()
                    return dict(row) if row else None
                finally:
                    conn.close()
        except Exception:
            return None

    def delete_trial(self, db_id: int) -> bool:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    conn.execute("DELETE FROM trials WHERE id=?", (db_id,))
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def clear_all_trials(self) -> bool:
        return self.clear_trials(mode=None)

    def clear_trials(self, *, mode: str | None = None) -> bool:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    if mode:
                        conn.execute("DELETE FROM trials WHERE mode=?", (mode,))
                    else:
                        conn.execute("DELETE FROM trials")
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def export_csv(self, *, mode: str | None = None) -> str:
        import pandas as pd

        rows = self.list_trials(limit=10000, mode=mode)
        if not rows:
            return "trial_id,user_name,source_type,manual_label,mode,created_at,v2_overall,v1_score\n"
        return pd.DataFrame(rows).to_csv(index=False)

    def list_user_names(self, *, mode: str | None = None) -> list[str]:
        try:
            clauses = ["valid=1", "user_name IS NOT NULL", "TRIM(user_name)!=''"]
            params: list[Any] = []
            if mode and mode != "all":
                clauses.append("mode = ?")
                params.append(mode)
            where = " AND ".join(clauses)
            with self._lock:
                conn = self._connect()
                try:
                    rows = conn.execute(
                        f"""
                        SELECT MIN(user_name) AS user_name FROM trials
                        WHERE {where}
                        GROUP BY LOWER(TRIM(user_name))
                        ORDER BY MIN(user_name) COLLATE NOCASE
                        """,
                        params,
                    ).fetchall()
                    return [str(r["user_name"]) for r in rows]
                finally:
                    conn.close()
        except Exception:
            return []


_store: TrialStore | None = None


def get_store() -> TrialStore:
    global _store
    if _store is None:
        _store = TrialStore()
        from scoring.v2.config import migrate_legacy_settings

        migrate_legacy_settings(_store)
    return _store
