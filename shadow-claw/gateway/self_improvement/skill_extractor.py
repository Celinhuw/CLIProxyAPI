"""Skill Extractor — learns reusable patterns from successful interactions.

Inspired by aiming-lab/MetaClaw (#4). Analyzes positive feedback entries
to extract tool usage patterns, prompt templates, and workflows that
worked well. These become "skills" the agent can reuse.

Flow:
1. FeedbackCollector records action + 👍 rating
2. SkillExtractor periodically scans positive feedback
3. Extracts patterns: tool → input pattern → success rate
4. Stores as reusable skills for the agent loop to reference
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

LOGGER = logging.getLogger("shadow_claw_gateway.self_improvement.skills")

_DB_PATH = str(Path(__file__).parent.parent / "data" / "self_improvement.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    tool_chain TEXT NOT NULL,
    input_pattern TEXT,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    last_used REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_name ON skills (name);
"""


@dataclass
class ExtractedSkill:
    name: str
    tool_chain: list[str]
    input_pattern: str
    success_count: int = 0
    fail_count: int = 0


class SkillExtractor:
    """Extracts and manages reusable skills from feedback data."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def extract_from_feedback(self, feedback_entries: list[dict]) -> list[ExtractedSkill]:
        """Analyze feedback entries and extract tool usage patterns."""
        tool_patterns = defaultdict(lambda: {"success": 0, "fail": 0, "inputs": []})

        for entry in feedback_entries:
            tool = entry.get("tool", "unknown")
            rating = entry.get("rating", 0)
            input_text = entry.get("input", "")

            if rating == 1:
                tool_patterns[tool]["success"] += 1
                tool_patterns[tool]["inputs"].append(input_text[:200])
            elif rating == -1:
                tool_patterns[tool]["fail"] += 1

        skills = []
        for tool, data in tool_patterns.items():
            if data["success"] >= 3:  # need at least 3 positive uses
                # Find common input patterns
                input_words = Counter()
                for inp in data["inputs"]:
                    for word in inp.lower().split():
                        if len(word) > 3:
                            input_words[word] += 1

                common_words = [w for w, c in input_words.most_common(5) if c >= 2]
                pattern = " ".join(common_words) if common_words else "*"

                skill = ExtractedSkill(
                    name=f"auto_{tool}_{len(skills)}",
                    tool_chain=[tool],
                    input_pattern=pattern,
                    success_count=data["success"],
                    fail_count=data["fail"],
                )
                skills.append(skill)

        return skills

    def store_skill(self, skill: ExtractedSkill) -> bool:
        """Store or update an extracted skill."""
        now = time.time()
        try:
            self._conn.execute(
                "INSERT INTO skills (name, tool_chain, input_pattern, success_count, fail_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (skill.name, json.dumps(skill.tool_chain), skill.input_pattern,
                 skill.success_count, skill.fail_count, now),
            )
        except sqlite3.IntegrityError:
            self._conn.execute(
                "UPDATE skills SET success_count = ?, fail_count = ?, last_used = ? WHERE name = ?",
                (skill.success_count, skill.fail_count, now, skill.name),
            )
        self._conn.commit()
        return True

    def suggest_tool(self, user_input: str) -> str | None:
        """Suggest the best tool based on learned skills."""
        words = set(user_input.lower().split())
        rows = self._conn.execute(
            "SELECT name, tool_chain, input_pattern, success_count, fail_count FROM skills "
            "ORDER BY success_count DESC"
        ).fetchall()

        best_match = None
        best_score = 0

        for name, tool_chain_json, pattern, success, fail in rows:
            if fail > success:
                continue
            pattern_words = set(pattern.split())
            overlap = len(words & pattern_words)
            score = overlap * (success / max(success + fail, 1))
            if score > best_score:
                best_score = score
                tools = json.loads(tool_chain_json)
                best_match = tools[0] if tools else None

        return best_match

    def list_skills(self) -> list[dict]:
        """List all extracted skills with performance metrics."""
        rows = self._conn.execute(
            "SELECT name, tool_chain, input_pattern, success_count, fail_count, created_at "
            "FROM skills ORDER BY success_count DESC"
        ).fetchall()
        return [
            {"name": r[0], "tools": json.loads(r[1]), "pattern": r[2],
             "success": r[3], "fail": r[4], "created": r[5]}
            for r in rows
        ]

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
