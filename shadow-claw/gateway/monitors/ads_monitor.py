"""Ads monitor — checks Meta Ads performance anomalies."""

import logging

import bot_state
from attention_queue import AttentionItem, Urgency

LOGGER = logging.getLogger("shadow_claw_gateway.monitors.ads")

_ANOMALY_THRESHOLD = 0.15  # 15% deviation


async def check_ads_performance(context) -> list[AttentionItem]:
    """Query Meta Ads for performance anomalies."""
    items = []

    config = bot_state.config
    if config is None:
        return items

    account_id = config.extra.get("META_ADS_ACCOUNT_ID") if hasattr(config, "extra") else None
    if not account_id:
        return items

    try:
        from tools.marketing import analyze_meta_ads
        result = await analyze_meta_ads(account_id=account_id, period="yesterday")

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
