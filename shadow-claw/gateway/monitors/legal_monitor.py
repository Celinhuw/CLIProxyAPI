"""Legal monitor — checks court deadlines via INTIMA.AI.

Routes through ToolRegistry.invoke() for audit logging, timeout,
and rate limiting consistency with the agent loop.
"""

import logging

import bot_state
from agent import ToolRegistry
from attention_queue import AttentionItem, Urgency

LOGGER = logging.getLogger("shadow_claw_gateway.monitors.legal")


async def check_deadlines(context) -> list[AttentionItem]:
    """Query INTIMA.AI for active deadlines and return attention items."""
    items = []

    try:
        result = await ToolRegistry.invoke(
            "list_deadlines", {"status": "active"}, log_event=bot_state.log_event
        )

        if "No active deadlines" in result:
            return items

        # Parse the formatted output for deadline info
        lines = result.split("\n")
        for i, line in enumerate(lines):
            if "🔴" in line or "🟡" in line or "🔵" in line:
                title = line.strip().lstrip("🔴🟡🔵 ").strip("*").strip()
                body = lines[i + 1].strip() if i + 1 < len(lines) else ""

                if "🔴" in line:
                    urgency = Urgency.CRITICAL
                elif "🟡" in line:
                    urgency = Urgency.IMPORTANT
                else:
                    urgency = Urgency.INFO

                items.append(AttentionItem(
                    source="legal",
                    urgency=urgency,
                    title=f"PRAZO: {title}",
                    body=body,
                    actions=["Ver processo", "Snooze 4h", "Delegar"],
                ))

    except Exception as e:
        LOGGER.error("Legal monitor failed: %s", e)

    return items
