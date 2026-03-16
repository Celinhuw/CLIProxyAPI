"""Nudge Engine — learns WHEN to contact the user without being annoying.

Inspired by NousResearch/hermes-agent (#6). Tracks user response patterns
to determine optimal notification timing and frequency.

Learns:
- What times the user is most responsive (response latency)
- Which urgency levels get acted on vs dismissed
- Snooze patterns → "user doesn't want ads alerts before 10am"
- Action rates per source → reduce notifications from low-action sources
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger("shadow_claw_gateway.self_improvement.nudge")

_DB_PATH = str(Path(__file__).parent.parent / "data" / "self_improvement.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nudge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    urgency TEXT NOT NULL,
    action TEXT NOT NULL,
    hour_of_day INTEGER,
    response_seconds REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nudge_source ON nudge_events (source);
CREATE INDEX IF NOT EXISTS idx_nudge_hour ON nudge_events (hour_of_day);
"""


@dataclass
class NudgeProfile:
    """Learned user notification preferences."""
    quiet_hours: list[int]           # hours when user doesn't respond
    active_hours: list[int]          # hours when user responds fast
    preferred_sources: list[str]     # sources user acts on most
    suppressed_sources: list[str]    # sources user mostly dismisses
    avg_response_seconds: float


class NudgeEngine:
    """Learns optimal notification timing from user behavior."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_interaction(
        self,
        source: str,
        urgency: str,
        action: str,
        response_seconds: float | None = None,
    ) -> None:
        """Record a user interaction with a notification."""
        from datetime import datetime
        now = time.time()
        hour = datetime.fromtimestamp(now).hour

        self._conn.execute(
            "INSERT INTO nudge_events (source, urgency, action, hour_of_day, response_seconds, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source, urgency, action, hour, response_seconds, now),
        )
        self._conn.commit()

    def build_profile(self) -> NudgeProfile:
        """Analyze interaction history to build a nudge profile."""
        # Response time by hour
        hour_data = defaultdict(lambda: {"count": 0, "total_response": 0.0})
        rows = self._conn.execute(
            "SELECT hour_of_day, response_seconds FROM nudge_events "
            "WHERE response_seconds IS NOT NULL AND response_seconds > 0"
        ).fetchall()

        for hour, resp_s in rows:
            hour_data[hour]["count"] += 1
            hour_data[hour]["total_response"] += resp_s

        # Active hours: avg response < 5 min
        active_hours = []
        quiet_hours = []
        for h in range(24):
            d = hour_data.get(h)
            if d and d["count"] >= 3:
                avg = d["total_response"] / d["count"]
                if avg < 300:  # < 5 min
                    active_hours.append(h)
                elif avg > 3600:  # > 1h
                    quiet_hours.append(h)
            elif not d:
                quiet_hours.append(h)

        # Source action rates
        source_stats = defaultdict(lambda: {"acted": 0, "dismissed": 0})
        rows = self._conn.execute(
            "SELECT source, action FROM nudge_events"
        ).fetchall()
        for source, action in rows:
            if action in ("snooze", "ignorar", "dismiss"):
                source_stats[source]["dismissed"] += 1
            else:
                source_stats[source]["acted"] += 1

        preferred = []
        suppressed = []
        for source, stats in source_stats.items():
            total = stats["acted"] + stats["dismissed"]
            if total >= 5:
                rate = stats["acted"] / total
                if rate > 0.6:
                    preferred.append(source)
                elif rate < 0.3:
                    suppressed.append(source)

        # Overall avg response
        all_responses = self._conn.execute(
            "SELECT AVG(response_seconds) FROM nudge_events WHERE response_seconds > 0"
        ).fetchone()[0] or 0.0

        return NudgeProfile(
            quiet_hours=quiet_hours,
            active_hours=active_hours or list(range(8, 22)),  # default 8am-10pm
            preferred_sources=preferred,
            suppressed_sources=suppressed,
            avg_response_seconds=all_responses,
        )

    def should_nudge_now(self, source: str, urgency: str) -> bool:
        """Decide if now is a good time to nudge based on learned profile."""
        from datetime import datetime
        current_hour = datetime.now().hour

        profile = self.build_profile()

        # CRITICAL always goes through
        if urgency == "CRITICAL":
            return True

        # Check quiet hours
        if current_hour in profile.quiet_hours:
            LOGGER.debug("Suppressing %s nudge during quiet hour %d", source, current_hour)
            return False

        # Check suppressed sources
        if source in profile.suppressed_sources and urgency != "IMPORTANT":
            LOGGER.debug("Suppressing %s nudge (low action rate)", source)
            return False

        return True

    def get_stats(self) -> dict:
        """Get nudge engine statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM nudge_events").fetchone()[0]
        by_action = dict(self._conn.execute(
            "SELECT action, COUNT(*) FROM nudge_events GROUP BY action"
        ).fetchall())
        return {"total_events": total, "by_action": by_action}

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
