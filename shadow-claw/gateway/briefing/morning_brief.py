"""Morning brief — daily 8am compiled summary of everything that needs attention."""

import logging
from datetime import datetime

import bot_state
from attention_queue import AttentionItem, Urgency, URGENCY_EMOJI

LOGGER = logging.getLogger("shadow_claw_gateway.briefing")


async def compile_morning_brief() -> str:
    """Compile a morning brief from all sources."""
    sections = []
    now = datetime.now()
    sections.append(f"☀️ **Bom dia!** Briefing de {now.strftime('%d/%m/%Y')}\n")

    # 1. Court deadlines
    try:
        from tools.legal import list_deadlines
        deadlines = await list_deadlines(status="active")
        if "No active deadlines" not in deadlines:
            sections.append("⚖️ **Prazos Jurídicos:**")
            sections.append(deadlines[:500])
            sections.append("")
    except Exception as e:
        LOGGER.debug("Morning brief: legal section failed: %s", e)

    # 2. Ads performance
    try:
        config = bot_state.config
        account_id = None
        if config and hasattr(config, "extra"):
            account_id = config.extra.get("META_ADS_ACCOUNT_ID")
        if account_id:
            from tools.marketing import analyze_meta_ads
            ads = await analyze_meta_ads(account_id=account_id, period="yesterday")
            if "error" not in ads.lower() and "not configured" not in ads.lower():
                sections.append("📊 **Meta Ads (ontem):**")
                sections.append(ads[:400])
                sections.append("")
    except Exception as e:
        LOGGER.debug("Morning brief: ads section failed: %s", e)

    # 3. Attention queue pending items
    queue = bot_state.attention_queue
    if queue and queue.pending_count > 0:
        summary = queue.pending_summary()
        sections.append("📋 **Itens pendentes:**")
        for urgency_name, count in summary.items():
            if count > 0:
                sections.append(f"  {urgency_name}: {count}")
        sections.append("")

    # 4. Footer
    sections.append("_[Só críticos] [Ver tudo] [Snooze tudo]_")

    return "\n".join(sections)


async def build_brief_attention_items() -> list[AttentionItem]:
    """Build attention items from morning brief data."""
    brief_text = await compile_morning_brief()

    return [AttentionItem(
        source="briefing",
        urgency=Urgency.INFO,
        title="☀️ Morning Brief",
        body=brief_text[:500],
        actions=["Ver completo", "Só críticos"],
    )]
