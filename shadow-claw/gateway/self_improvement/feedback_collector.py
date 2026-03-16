"""Feedback Collector — captures 👍/👎 signals after agent actions.

Every significant agent action gets inline buttons for feedback.
Feedback is stored in SQLite and used later for skill extraction
and behavior tuning (OpenPipe ART integration in Fase 6).

Inspired by OpenPipe/ART (#308) — collect data now, train later.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger("shadow_claw_gateway.self_improvement.feedback")

_DB_PATH = str(Path(__file__).parent.parent / "data" / "feedback.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    action_input TEXT,
    action_output TEXT,
    tool_name TEXT,
    rating INTEGER,
    comment TEXT,
    chat_id INTEGER,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fb_tool ON feedback (tool_name);
CREATE INDEX IF NOT EXISTS idx_fb_rating ON feedback (rating);
CREATE INDEX IF NOT EXISTS idx_fb_ts ON feedback (created_at);
"""


@dataclass
class FeedbackEntry:
    action_type: str      # "tool_call", "research", "alert", "suggestion"
    action_input: str     # what was asked
    action_output: str    # what was returned (truncated)
    tool_name: str        # which tool was used
    rating: int | None    # 1 = 👍, -1 = 👎, None = no rating yet
    comment: str = ""
    chat_id: int = 0
    created_at: float = 0.0


class FeedbackCollector:
    """Collects and stores user feedback on agent actions."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_action(self, entry: FeedbackEntry) -> int:
        """Record an action that may receive feedback later. Returns row ID."""
        now = entry.created_at or time.time()
        cursor = self._conn.execute(
            "INSERT INTO feedback (action_type, action_input, action_output, tool_name, rating, comment, chat_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.action_type, entry.action_input[:1000], entry.action_output[:2000],
             entry.tool_name, entry.rating, entry.comment, entry.chat_id, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def set_rating(self, row_id: int, rating: int, comment: str = "") -> bool:
        """Set feedback rating for a recorded action. 1=👍, -1=👎."""
        cursor = self._conn.execute(
            "UPDATE feedback SET rating = ?, comment = ? WHERE id = ?",
            (rating, comment, row_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_stats(self) -> dict:
        """Get feedback statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        positive = self._conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 1").fetchone()[0]
        negative = self._conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = -1").fetchone()[0]
        unrated = self._conn.execute("SELECT COUNT(*) FROM feedback WHERE rating IS NULL").fetchone()[0]
        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "unrated": unrated,
            "satisfaction_rate": positive / max(positive + negative, 1),
        }

    def get_negative_patterns(self, limit: int = 20) -> list[dict]:
        """Get recent negative feedback for analysis."""
        rows = self._conn.execute(
            "SELECT tool_name, action_input, action_output, comment, created_at "
            "FROM feedback WHERE rating = -1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"tool": r[0], "input": r[1], "output": r[2], "comment": r[3], "at": r[4]}
            for r in rows
        ]

    def get_tool_performance(self) -> list[dict]:
        """Get per-tool satisfaction rates."""
        rows = self._conn.execute(
            "SELECT tool_name, "
            "COUNT(*) as total, "
            "SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as positive, "
            "SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) as negative "
            "FROM feedback WHERE rating IS NOT NULL "
            "GROUP BY tool_name ORDER BY total DESC"
        ).fetchall()
        return [
            {"tool": r[0], "total": r[1], "positive": r[2], "negative": r[3],
             "rate": r[2] / max(r[1], 1)}
            for r in rows
        ]

    def export_training_data(self, min_rating: int | None = None) -> list[dict]:
        """Export feedback as training data for future ART fine-tuning."""
        sql = "SELECT action_type, action_input, action_output, tool_name, rating, comment FROM feedback WHERE rating IS NOT NULL"
        params = []
        if min_rating is not None:
            sql += " AND rating >= ?"
            params.append(min_rating)
        sql += " ORDER BY created_at"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {"type": r[0], "input": r[1], "output": r[2], "tool": r[3], "rating": r[4], "comment": r[5]}
            for r in rows
        ]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
