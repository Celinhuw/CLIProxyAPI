"""Email triage tools: AI-powered inbox management via inbox-zero.

Wraps inbox-zero (elie222/inbox-zero) API for email categorization,
auto-archiving, and summary delivery via Telegram.

Requires inbox-zero running as a Docker service on the VPS.
"""

import json
import logging

import requests

import bot_state
from agent import tool

LOGGER = logging.getLogger("shadow_claw_gateway.tools.email_triage")

_INBOX_ZERO_URL = "http://localhost:3000"


def _get_inbox_zero_url() -> str:
    from config import get_config_value
    return get_config_value("INBOX_ZERO_URL", _INBOX_ZERO_URL)


def _inbox_request(endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
    """Make a request to inbox-zero API."""
    url = f"{_get_inbox_zero_url()}/api/{endpoint}"
    try:
        if method == "POST":
            resp = requests.post(url, json=data, timeout=30)
        else:
            resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        return {"error": "inbox-zero not running. Deploy with: docker-compose up inbox-zero"}
    except requests.RequestException as e:
        return {"error": f"inbox-zero API error: {e}"}


@tool(
    "email_summary",
    "Get a summary of unread emails categorized by urgency. "
    "Uses inbox-zero AI to categorize: client emails, court notifications, "
    "newsletters, and spam.",
    {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max emails to summarize (default: 20)",
            },
        },
    },
)
async def email_summary(limit: int = 20) -> str:
    result = _inbox_request("emails/unread")
    if "error" in result:
        return result["error"]

    emails = result.get("emails", result.get("data", []))
    if not emails:
        return "Inbox zero! Nenhum email pendente. ✅"

    # Categorize
    categories = {"client": [], "court": [], "important": [], "newsletter": [], "other": []}

    court_keywords = {"intimação", "citação", "prazo", "tribunal", "pje", "despacho", "sentença"}
    client_keywords = {"reunião", "contrato", "consulta", "honorário", "processo"}

    for email in emails[:limit]:
        subject = (email.get("subject", "") or "").lower()
        sender = (email.get("from", "") or "").lower()
        category = email.get("category", "")

        if any(kw in subject for kw in court_keywords) or "jus.br" in sender:
            categories["court"].append(email)
        elif any(kw in subject for kw in client_keywords) or category == "client":
            categories["client"].append(email)
        elif category == "newsletter" or "unsubscribe" in (email.get("body", "") or "").lower()[:500]:
            categories["newsletter"].append(email)
        elif category == "important":
            categories["important"].append(email)
        else:
            categories["other"].append(email)

    lines = [f"📧 **Inbox Summary** ({len(emails)} unread)\n"]

    if categories["court"]:
        lines.append(f"⚖️ **Tribunal** ({len(categories['court'])}):")
        for e in categories["court"][:5]:
            lines.append(f"  - {e.get('from', '?')}: {e.get('subject', '?')[:60]}")

    if categories["client"]:
        lines.append(f"\n👤 **Clientes** ({len(categories['client'])}):")
        for e in categories["client"][:5]:
            lines.append(f"  - {e.get('from', '?')}: {e.get('subject', '?')[:60]}")

    if categories["important"]:
        lines.append(f"\n⭐ **Importantes** ({len(categories['important'])}):")
        for e in categories["important"][:3]:
            lines.append(f"  - {e.get('from', '?')}: {e.get('subject', '?')[:60]}")

    newsletter_count = len(categories["newsletter"])
    other_count = len(categories["other"])
    if newsletter_count or other_count:
        lines.append(f"\n📰 Newsletters: {newsletter_count} | Outros: {other_count}")

    return "\n".join(lines)


@tool(
    "email_archive_newsletters",
    "Auto-archive all newsletter and promotional emails. "
    "Keeps inbox clean with one command.",
    {
        "type": "object",
        "properties": {},
    },
)
async def email_archive_newsletters() -> str:
    result = _inbox_request("emails/archive-newsletters", method="POST")
    if "error" in result:
        return result["error"]

    count = result.get("archived", result.get("count", 0))
    return f"Arquivados {count} newsletters/promos. ✅"
