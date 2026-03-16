"""Ads monitor — checks Meta Ads performance anomalies.

Routes through ToolRegistry.invoke() for audit logging, timeout,
and rate limiting consistency with the agent loop.
"""

import logging

import bot_state
from agent import ToolRegistry
from attention_queue import AttentionItem, Urgency
from config import get_config_value

LOGGER = logging.getLogger("shadow_claw_gateway.monitors.ads")

_ANOMALY_THRESHOLD = 0.15  # 15% deviation


async def check_ads_performance(context) -> list[AttentionItem]:
    """Query Meta Ads for performance anomalies."""
    items = []

    account_id = get_config_value("META_ADS_ACCOUNT_ID")
    if not account_id:
        return items

    try:
        result = await ToolRegistry.invoke(
            "analyze_meta_ads",
            {"account_id": account_id, "period": "yesterday"},
            log_event=bot_state.log_event,
        )

        if "error" in result.lower() or "not configured" in result.lower():
            return items

        # Look for anomaly indicators in the result
        # The analyze_meta_ads tool returns formatted text
        if "anomal" in result.lower() or "+2" in result or "+3" in result:
            items.append(AttentionItem(
                source="ads",
                urgency=Urgency.IMPORTANT,
                title="ADS: Anomalia detectada nas campanhas",
                body=result[:400],
                actions=["Ver detalhes", "Snooze 4h"],
            ))

    except Exception as e:
        LOGGER.error("Ads monitor failed: %s", e)

    return items
