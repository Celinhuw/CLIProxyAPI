"""Site monitor — checks changedetection.io for watched site changes."""

import logging

try:
    import httpx
    _HTTP_AVAILABLE = True
except ImportError:
    _HTTP_AVAILABLE = False

from attention_queue import AttentionItem, Urgency

LOGGER = logging.getLogger("shadow_claw_gateway.monitors.site")

_CHANGEDETECTION_URL = "http://localhost:5000"


async def check_site_changes(context) -> list[AttentionItem]:
    """Query changedetection.io API for recent changes."""
    items = []

    if not _HTTP_AVAILABLE:
        LOGGER.debug("httpx not installed — site monitor disabled")
        return items

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_CHANGEDETECTION_URL}/api/v1/watch",
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            return items

        watches = resp.json()
        for watch_id, watch in watches.items():
            last_changed = watch.get("last_changed", 0)
            last_checked = watch.get("last_checked", 0)
            title = watch.get("title", watch.get("url", "Unknown site"))

            # If changed since last check
            if last_changed and last_changed > last_checked - 3600:
                url = watch.get("url", "")
                items.append(AttentionItem(
                    source="sites",
                    urgency=Urgency.INFO,
                    title=f"SITE: {title[:60]} mudou",
                    body=f"URL: {url}",
                    actions=["Ver diff", "Ignorar"],
                ))

    except httpx.ConnectError:
        LOGGER.debug("changedetection.io not running at %s", _CHANGEDETECTION_URL)
    except Exception as e:
        LOGGER.error("Site monitor failed: %s", e)

    return items
