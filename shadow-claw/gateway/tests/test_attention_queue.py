"""Tests for attention_queue.py — TDAH-optimized notification queue."""

import time
import unittest

from attention_queue import AttentionItem, AttentionQueue, Urgency


class TestAttentionItem(unittest.TestCase):
    """Test AttentionItem creation and hashing."""

    def test_auto_hash(self):
        item = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Test", body="Body")
        self.assertTrue(len(item.content_hash) == 16)

    def test_same_content_same_hash(self):
        a = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Test", body="Body")
        b = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Test", body="Body")
        self.assertEqual(a.content_hash, b.content_hash)

    def test_different_content_different_hash(self):
        a = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Test A", body="Body")
        b = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Test B", body="Body")
        self.assertNotEqual(a.content_hash, b.content_hash)


class TestAttentionQueue(unittest.TestCase):
    """Test AttentionQueue push/pop/dedup/snooze."""

    def setUp(self):
        self.queue = AttentionQueue()

    def test_push_and_pop(self):
        item = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="2 dias")
        self.assertTrue(self.queue.push(item))
        self.assertEqual(self.queue.pending_count, 1)

        batch = self.queue.pop_batch()
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0].title, "Prazo")
        self.assertEqual(self.queue.pending_count, 0)

    def test_dedup_rejects_same_hash(self):
        item1 = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="2 dias")
        item2 = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="2 dias")
        self.assertTrue(self.queue.push(item1))
        self.assertFalse(self.queue.push(item2))
        self.assertEqual(self.queue.pending_count, 1)

    def test_dedup_after_delivery(self):
        item = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="2 dias")
        self.queue.push(item)
        self.queue.pop_batch()  # delivers it

        # Same item again — should be deduped
        item2 = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="2 dias")
        self.assertFalse(self.queue.push(item2))

    def test_urgency_ordering(self):
        self.queue.push(AttentionItem(source="sites", urgency=Urgency.INFO, title="Info", body=""))
        self.queue.push(AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Critical", body=""))
        self.queue.push(AttentionItem(source="ads", urgency=Urgency.IMPORTANT, title="Important", body=""))

        batch = self.queue.pop_batch(max_items=5, include_info=True)
        self.assertEqual(batch[0].urgency, Urgency.CRITICAL)
        self.assertEqual(batch[1].urgency, Urgency.IMPORTANT)
        self.assertEqual(batch[2].urgency, Urgency.INFO)

    def test_max_5_items_per_batch(self):
        for i in range(10):
            self.queue.push(AttentionItem(
                source="legal", urgency=Urgency.CRITICAL,
                title=f"Item {i}", body=f"Body {i}"
            ))
        batch = self.queue.pop_batch(max_items=5)
        self.assertEqual(len(batch), 5)

    def test_important_capped_at_2(self):
        for i in range(5):
            self.queue.push(AttentionItem(
                source="ads", urgency=Urgency.IMPORTANT,
                title=f"Important {i}", body=""
            ))
        batch = self.queue.pop_batch(max_items=5)
        self.assertEqual(len(batch), 2)

    def test_info_excluded_by_default(self):
        self.queue.push(AttentionItem(source="sites", urgency=Urgency.INFO, title="Info", body=""))
        batch = self.queue.pop_batch()
        self.assertEqual(len(batch), 0)

    def test_info_included_for_morning_brief(self):
        self.queue.push(AttentionItem(source="sites", urgency=Urgency.INFO, title="Info", body=""))
        batch = self.queue.pop_batch(include_info=True)
        self.assertEqual(len(batch), 1)

    def test_snooze(self):
        item = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="")
        self.queue.push(item)
        self.queue.snooze(item.content_hash, hours=1)

        # Should not appear in batch (snoozed)
        batch = self.queue.pop_batch()
        self.assertEqual(len(batch), 0)

    def test_dismiss(self):
        item = AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="Prazo", body="")
        self.queue.push(item)
        self.assertTrue(self.queue.dismiss(item.content_hash))
        self.assertEqual(self.queue.pending_count, 0)

    def test_pending_summary(self):
        self.queue.push(AttentionItem(source="legal", urgency=Urgency.CRITICAL, title="A", body=""))
        self.queue.push(AttentionItem(source="ads", urgency=Urgency.IMPORTANT, title="B", body=""))
        self.queue.push(AttentionItem(source="sites", urgency=Urgency.INFO, title="C", body=""))
        summary = self.queue.pending_summary()
        self.assertEqual(summary["CRITICAL"], 1)
        self.assertEqual(summary["IMPORTANT"], 1)
        self.assertEqual(summary["INFO"], 1)

    def test_queue_bounded_at_max(self):
        for i in range(55):
            self.queue.push(AttentionItem(
                source="sites", urgency=Urgency.INFO,
                title=f"Item {i}", body=""
            ))
        # Should evict oldest INFO items to stay under 50
        self.assertLessEqual(self.queue.pending_count, 50)


class TestDaemonRegistration(unittest.TestCase):
    """Test daemon monitor registration."""

    def test_register_monitors_creates_queue(self):
        """Verify register_monitors initializes attention_queue in bot_state."""
        import bot_state
        from unittest.mock import MagicMock

        mock_job_queue = MagicMock()
        from daemon import register_monitors
        register_monitors(mock_job_queue, chat_id=12345)

        self.assertIsNotNone(bot_state.attention_queue)
        # Should have registered 5 jobs
        self.assertEqual(mock_job_queue.run_repeating.call_count, 4)
        self.assertEqual(mock_job_queue.run_daily.call_count, 1)

        # Cleanup
        bot_state.attention_queue = None


if __name__ == "__main__":
    unittest.main()
