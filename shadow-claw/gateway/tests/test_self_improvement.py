"""Tests for self_improvement subsystem — feedback, skills, nudge."""

import os
import tempfile
import time
import unittest

from self_improvement.feedback_collector import FeedbackCollector, FeedbackEntry
from self_improvement.skill_extractor import SkillExtractor, ExtractedSkill
from self_improvement.nudge_engine import NudgeEngine


class TestFeedbackCollector(unittest.TestCase):
    """Test feedback recording and querying."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "test_feedback.db")
        self.collector = FeedbackCollector(db_path=self.db_path)

    def tearDown(self):
        self.collector.close()

    def test_record_and_rate(self):
        row_id = self.collector.record_action(FeedbackEntry(
            action_type="tool_call",
            action_input="pesquisar fulano",
            action_output="Encontrou 5 perfis",
            tool_name="osint_username",
            rating=None,
        ))
        self.assertGreater(row_id, 0)

        self.assertTrue(self.collector.set_rating(row_id, 1))
        stats = self.collector.get_stats()
        self.assertEqual(stats["positive"], 1)

    def test_negative_patterns(self):
        for i in range(3):
            row_id = self.collector.record_action(FeedbackEntry(
                action_type="tool_call",
                action_input=f"input {i}",
                action_output="bad result",
                tool_name="browse_url",
                rating=-1,
            ))
        patterns = self.collector.get_negative_patterns()
        self.assertEqual(len(patterns), 3)
        self.assertEqual(patterns[0]["tool"], "browse_url")

    def test_tool_performance(self):
        for rating in [1, 1, 1, -1]:
            self.collector.record_action(FeedbackEntry(
                action_type="tool_call",
                action_input="test",
                action_output="result",
                tool_name="research_topic",
                rating=rating,
            ))
        perf = self.collector.get_tool_performance()
        self.assertEqual(len(perf), 1)
        self.assertEqual(perf[0]["tool"], "research_topic")
        self.assertEqual(perf[0]["positive"], 3)
        self.assertEqual(perf[0]["negative"], 1)

    def test_export_training_data(self):
        self.collector.record_action(FeedbackEntry(
            action_type="tool_call", action_input="q", action_output="r",
            tool_name="t", rating=1,
        ))
        data = self.collector.export_training_data()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["rating"], 1)


class TestSkillExtractor(unittest.TestCase):
    """Test skill extraction from feedback."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "test_skills.db")
        self.extractor = SkillExtractor(db_path=self.db_path)

    def tearDown(self):
        self.extractor.close()

    def test_extract_requires_min_3_positive(self):
        entries = [
            {"tool": "osint_username", "rating": 1, "input": "pesquisar usuario twitter"},
            {"tool": "osint_username", "rating": 1, "input": "pesquisar usuario instagram"},
        ]
        skills = self.extractor.extract_from_feedback(entries)
        self.assertEqual(len(skills), 0)  # only 2, need 3

    def test_extract_with_enough_feedback(self):
        entries = [
            {"tool": "osint_username", "rating": 1, "input": "pesquisar fulano twitter"},
            {"tool": "osint_username", "rating": 1, "input": "pesquisar ciclano twitter"},
            {"tool": "osint_username", "rating": 1, "input": "pesquisar beltrano twitter"},
        ]
        skills = self.extractor.extract_from_feedback(entries)
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].tool_chain, ["osint_username"])
        self.assertEqual(skills[0].success_count, 3)

    def test_store_and_list(self):
        skill = ExtractedSkill(
            name="test_skill", tool_chain=["osint_username"],
            input_pattern="pesquisar twitter", success_count=5,
        )
        self.extractor.store_skill(skill)
        skills = self.extractor.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["name"], "test_skill")

    def test_suggest_tool(self):
        skill = ExtractedSkill(
            name="osint_search", tool_chain=["osint_username"],
            input_pattern="pesquisar usuario twitter", success_count=10,
        )
        self.extractor.store_skill(skill)
        suggestion = self.extractor.suggest_tool("pesquisar usuario no twitter")
        self.assertEqual(suggestion, "osint_username")


class TestNudgeEngine(unittest.TestCase):
    """Test nudge timing learning."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "test_nudge.db")
        self.engine = NudgeEngine(db_path=self.db_path)

    def tearDown(self):
        self.engine.close()

    def test_record_interaction(self):
        self.engine.record_interaction("legal", "CRITICAL", "responder", response_seconds=30)
        stats = self.engine.get_stats()
        self.assertEqual(stats["total_events"], 1)

    def test_critical_always_nudges(self):
        self.assertTrue(self.engine.should_nudge_now("legal", "CRITICAL"))

    def test_build_profile_defaults(self):
        profile = self.engine.build_profile()
        # Default active hours: 8-22
        self.assertIn(10, profile.active_hours)
        self.assertNotIn(3, profile.active_hours)

    def test_suppressed_source_detection(self):
        # Record many dismissals for "sites" source
        for _ in range(10):
            self.engine.record_interaction("sites", "INFO", "dismiss", response_seconds=1)
        for _ in range(2):
            self.engine.record_interaction("sites", "INFO", "ver_diff", response_seconds=60)

        profile = self.engine.build_profile()
        # sites should be suppressed (dismiss rate > 70%)
        self.assertIn("sites", profile.suppressed_sources)


if __name__ == "__main__":
    unittest.main()
