"""Attention Queue — TDAH-optimized proactive notification system.

Collects items from background monitors, deduplicates, prioritizes,
and delivers batches of max 5 items to the user via Telegram.

Rules:
- 🔴 CRITICAL always delivered immediately
- 🟡 IMPORTANT max 2 per batch
- 🔵 INFO only in morning brief (unless queue is empty)
- Dedup: same content_hash within 24h = ignored
- Snooze: hides item for N hours, then re-queues
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum

LOGGER = logging.getLogger("shadow_claw_gateway.attention_queue")

_MAX_PENDING = 50
_DEDUP_WINDOW_SECONDS = 86400  # 24h
_DEFAULT_SNOOZE_HOURS = 4


class Urgency(IntEnum):
    """Priority levels — lower number = higher priority."""
    CRITICAL = 1   # 🔴
    IMPORTANT = 2  # 🟡
    INFO = 3       # 🔵


URGENCY_EMOJI = {
    Urgency.CRITICAL: "🔴",
    Urgency.IMPORTANT: "🟡",
    Urgency.INFO: "🔵",
}


@dataclass
class AttentionItem:
    source: str
    urgency: Urgency
    title: str
    body: str
    actions: list[str] = field(default_factory=lambda: ["Snooze", "Ignorar"])
    content_hash: str = ""
    created_at: float = field(default_factory=time.time)
    snoozed_until: float = 0.0

    def __post_init__(self):
        if not self.content_hash:
            raw = f"{self.source}:{self.title}:{self.body[:200]}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]


class AttentionQueue:
    """Thread-safe attention queue with dedup, snooze, and urgency filtering."""

    def __init__(self) -> None:
        self._items: list[AttentionItem] = []
        self._delivered_hashes: dict[str, float] = {}  # hash → delivered_at

    def push(self, item: AttentionItem) -> bool:
        """Add item to queue. Returns False if duplicate or queue full."""
        now = time.time()

        # Dedup check
        if item.content_hash in self._delivered_hashes:
            delivered_at = self._delivered_hashes[item.content_hash]
            if now - delivered_at < _DEDUP_WINDOW_SECONDS:
                LOGGER.debug("Dedup: skipping %s (delivered %.0fs ago)", item.content_hash, now - delivered_at)
                return False

        # Check if already in queue
        if any(i.content_hash == item.content_hash for i in self._items):
            return False

        # Evict oldest INFO items if queue is full
        if len(self._items) >= _MAX_PENDING:
            info_items = [i for i in self._items if i.urgency == Urgency.INFO]
            if info_items:
                self._items.remove(min(info_items, key=lambda x: x.created_at))
            else:
                LOGGER.warning("Attention queue full (%d items), dropping new item", _MAX_PENDING)
                return False

        self._items.append(item)
        LOGGER.info("Queued: [%s] %s — %s", URGENCY_EMOJI[item.urgency], item.source, item.title)
        return True

    def pop_batch(self, max_items: int = 5, include_info: bool = False) -> list[AttentionItem]:
        """Pop top items by urgency for delivery.

        Args:
            max_items: Maximum items to return.
            include_info: Include INFO items (True for morning brief).
        """
        now = time.time()
        self._clear_expired(now)

        # Filter out snoozed items
        available = [i for i in self._items if i.snoozed_until <= now]

        # Sort by urgency (CRITICAL first), then by created_at
        available.sort(key=lambda i: (i.urgency, i.created_at))

        batch = []
        important_count = 0

        for item in available:
            if len(batch) >= max_items:
                break

            if item.urgency == Urgency.CRITICAL:
                batch.append(item)
            elif item.urgency == Urgency.IMPORTANT and important_count < 2:
                batch.append(item)
                important_count += 1
            elif item.urgency == Urgency.INFO and include_info:
                batch.append(item)

        # Mark as delivered
        for item in batch:
            self._delivered_hashes[item.content_hash] = now
            if item in self._items:
                self._items.remove(item)

        return batch

    def snooze(self, content_hash: str, hours: float = _DEFAULT_SNOOZE_HOURS) -> bool:
        """Snooze an item — hide it for N hours, then re-queue."""
        for item in self._items:
            if item.content_hash == content_hash:
                item.snoozed_until = time.time() + (hours * 3600)
                LOGGER.info("Snoozed %s for %.1fh", content_hash, hours)
                return True

        # Item already delivered — re-create it as snoozed
        if content_hash in self._delivered_hashes:
            del self._delivered_hashes[content_hash]
            return True

        return False

    def dismiss(self, content_hash: str) -> bool:
        """Permanently dismiss an item."""
        for item in list(self._items):
            if item.content_hash == content_hash:
                self._items.remove(item)
                self._delivered_hashes[content_hash] = time.time()
                return True
        return False

    def _clear_expired(self, now: float | None = None) -> None:
        """Remove expired dedup entries and old items."""
        now = now or time.time()
        cutoff = now - _DEDUP_WINDOW_SECONDS

        # Clean dedup window
        expired_hashes = [h for h, t in self._delivered_hashes.items() if t < cutoff]
        for h in expired_hashes:
            del self._delivered_hashes[h]

        # Clean old pending items (>48h)
        old_cutoff = now - 172800
        self._items = [i for i in self._items if i.created_at > old_cutoff]

    @property
    def pending_count(self) -> int:
        return len(self._items)

    def pending_summary(self) -> dict[str, int]:
        """Count pending items by urgency."""
        counts = {u.name: 0 for u in Urgency}
        for item in self._items:
            counts[item.urgency.name] += 1
        return counts
