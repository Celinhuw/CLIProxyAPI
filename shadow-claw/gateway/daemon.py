"""Shadow-Claw Daemon — background monitor orchestration.

Registers periodic monitors on python-telegram-bot's JobQueue (APScheduler).
Each monitor runs independently with crash isolation — one failing monitor
does not affect others.
"""

from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import TYPE_CHECKING

import bot_state
from attention_queue import AttentionQueue, AttentionItem, Urgency, URGENCY_EMOJI

if TYPE_CHECKING:
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import CallbackContext, JobQueue

LOGGER = logging.getLogger("shadow_claw_gateway.daemon")

# ---------------------------------------------------------------------------
# Monitor intervals (seconds)
# ---------------------------------------------------------------------------

_LEGAL_INTERVAL = 3600       # 1h
_ADS_INTERVAL = 14400        # 4h
_SITES_INTERVAL = 1800       # 30min
_DISPATCH_INTERVAL = 900     # 15min — dispatch queued items
_MORNING_BRIEF_TIME = dt_time(8, 0)  # 8:00 AM local


# ---------------------------------------------------------------------------
# Monitor wrappers (crash-isolated)
# ---------------------------------------------------------------------------

async def _run_legal_monitor(context: "CallbackContext") -> None:
    """Check court deadlines and push to attention queue."""
    try:
        from monitors.legal_monitor import check_deadlines
        items = await check_deadlines(context)
        queue = bot_state.attention_queue
        if queue:
            for item in items:
                queue.push(item)
    except Exception as e:
        LOGGER.error("Legal monitor crashed (isolated): %s", e)


async def _run_ads_monitor(context: "CallbackContext") -> None:
    """Check Meta Ads anomalies and push to attention queue."""
    try:
        from monitors.ads_monitor import check_ads_performance
        items = await check_ads_performance(context)
        queue = bot_state.attention_queue
        if queue:
            for item in items:
                queue.push(item)
    except Exception as e:
        LOGGER.error("Ads monitor crashed (isolated): %s", e)


async def _run_site_monitor(context: "CallbackContext") -> None:
    """Check changedetection.io and push to attention queue."""
    try:
        from monitors.site_monitor import check_site_changes
        items = await check_site_changes(context)
        queue = bot_state.attention_queue
        if queue:
            for item in items:
                queue.push(item)
    except Exception as e:
        LOGGER.error("Site monitor crashed (isolated): %s", e)


async def _run_morning_brief(context: "CallbackContext") -> None:
    """Compile and send morning brief."""
    try:
        from briefing.morning_brief import compile_morning_brief
        brief = await compile_morning_brief()
        chat_id = context.job.data.get("chat_id") if context.job.data else None
        if chat_id and brief:
            await context.bot.send_message(chat_id=chat_id, text=brief, parse_mode="Markdown")
            LOGGER.info("Morning brief sent to %s", chat_id)
    except Exception as e:
        LOGGER.error("Morning brief crashed (isolated): %s", e)


# ---------------------------------------------------------------------------
# Attention queue dispatcher
# ---------------------------------------------------------------------------

async def _dispatch_attention(context: "CallbackContext") -> None:
    """Pop items from attention queue and send to Telegram."""
    queue = bot_state.attention_queue
    if not queue or queue.pending_count == 0:
        return

    chat_id = context.job.data.get("chat_id") if context.job.data else None
    if not chat_id:
        return

    batch = queue.pop_batch(max_items=5)
    if not batch:
        return

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        lines = [f"📢 **Shadow-Claw** — {len(batch)} {'item precisa' if len(batch) == 1 else 'itens precisam'} de atenção\n"]

        buttons_rows = []
        for item in batch:
            emoji = URGENCY_EMOJI[item.urgency]
            lines.append(f"{emoji} **{item.title}**")
            if item.body:
                lines.append(f"   {item.body[:200]}")
            lines.append("")

            # Build inline buttons for this item
            row = []
            for action in item.actions[:3]:
                callback = f"attn:{action.lower().replace(' ', '_')}:{item.content_hash}"
                row.append(InlineKeyboardButton(action, callback_data=callback[:64]))
            buttons_rows.append(row)

        markup = InlineKeyboardMarkup(buttons_rows) if buttons_rows else None
        text = "\n".join(lines)

        await context.bot.send_message(
            chat_id=chat_id,
            text=text[:4000],
            parse_mode="Markdown",
            reply_markup=markup,
        )
        LOGGER.info("Dispatched %d attention items to %s", len(batch), chat_id)

    except Exception as e:
        LOGGER.error("Attention dispatch failed: %s", e)


# ---------------------------------------------------------------------------
# Attention callback handler
# ---------------------------------------------------------------------------

async def attention_callback(update, context) -> None:
    """Handle inline button presses on attention items."""
    query = update.callback_query
    await query.answer()

    data = query.data  # "attn:snooze_4h:abc123"
    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    action = parts[1]
    content_hash = parts[2]
    queue = bot_state.attention_queue

    if not queue:
        return

    if "snooze" in action:
        hours = 4.0
        if "1h" in action:
            hours = 1.0
        elif "8h" in action:
            hours = 8.0
        queue.snooze(content_hash, hours=hours)
        await query.edit_message_text(f"⏸ Snoozed por {hours:.0f}h")

    elif "ignorar" in action or "dismiss" in action:
        queue.dismiss(content_hash)
        await query.edit_message_text("✅ Ignorado")

    else:
        # Other actions: just acknowledge
        await query.edit_message_text(f"👍 {action.replace('_', ' ').title()}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_monitors(job_queue: "JobQueue", chat_id: int) -> None:
    """Register all background monitors on the Telegram JobQueue."""
    job_data = {"chat_id": chat_id}

    # Initialize attention queue in shared state
    bot_state.attention_queue = AttentionQueue()

    # Register periodic monitors
    job_queue.run_repeating(
        _run_legal_monitor, interval=_LEGAL_INTERVAL, first=60, data=job_data, name="monitor_legal"
    )
    job_queue.run_repeating(
        _run_ads_monitor, interval=_ADS_INTERVAL, first=300, data=job_data, name="monitor_ads"
    )
    job_queue.run_repeating(
        _run_site_monitor, interval=_SITES_INTERVAL, first=120, data=job_data, name="monitor_sites"
    )

    # Dispatch queued items periodically
    job_queue.run_repeating(
        _dispatch_attention, interval=_DISPATCH_INTERVAL, first=180, data=job_data, name="dispatch_attention"
    )

    # Morning brief at 8:00 AM
    job_queue.run_daily(
        _run_morning_brief, time=_MORNING_BRIEF_TIME, data=job_data, name="morning_brief"
    )

    LOGGER.info(
        "Daemon registered: legal(%ds), ads(%ds), sites(%ds), dispatch(%ds), brief(08:00)",
        _LEGAL_INTERVAL, _ADS_INTERVAL, _SITES_INTERVAL, _DISPATCH_INTERVAL,
    )
