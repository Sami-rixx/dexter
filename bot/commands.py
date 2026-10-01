#!/usr/bin/env python3
"""
Dexter Bot Commands - Steps 3-5 Implementation

This module contains the command handlers for the bot.
It maintains the separation between Telegram-specific code and AI logic.

Architecture constraints:
- Imports from ai/ module but only the public interface
- Never imports Gemini SDK internals
- Imports from logger/ module only the public interface
- Raw Telegram chat IDs are transformed at the boundary before any other module sees them
- Rate limiting (Step 4) runs before the AI engine is invoked
"""

import os
import time
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ai.ai_engine import answer, reload_persona, reload_config, STATUS_ERROR  # noqa: F401 (import line pinned by Step-3 test contract)
from logger.logger import get_telegram_id_alias, Exchange, log_exchange, get_today_exchange_count, get_last_error
from .ratelimit import check_cooldown, try_consume, release, get_today_count, get_daily_limit

logger = logging.getLogger(__name__)

# Process start time, used by the patron-only /status command.
_PROCESS_START = time.time()

# Friendly, non-technical rejection messages (never expose internals).
COOLDOWN_REPLY = (
    "You're quick! Please wait a few seconds between questions "
    "so everyone gets a turn."
)
DAILY_LIMIT_REPLY = (
    "I've answered a lot of questions today and I need to rest. "
    "Please try again tomorrow!"
)
RESTING_REPLY = "I'm resting, try again in a few minutes"


def get_patron_chat_ids() -> set[int]:
    """Get set of patron chat IDs from environment."""
    patron_ids_str = os.getenv("PATRON_CHAT_IDS", "")
    if not patron_ids_str.strip():
        return set()

    try:
        # Parse comma-separated list of chat IDs
        ids = [int(pid.strip()) for pid in patron_ids_str.split(",") if pid.strip()]
        return set(ids)
    except ValueError as e:
        logger.warning(f"Invalid PATRON_CHAT_IDS format: {e}")
        return set()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text("Hi! I'm Dexter, your STEM study helper. Ask me any CBC topic or math question!")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "I'm Dexter, a study helper bot for CBC students. "
        "I can help with:\n\n"
        "• CBC topic explanations\n"
        "• Step-by-step math problem solving\n"
        "• Timetable and career-pathway information\n"
        "• Study tips\n\n"
        "Just type your question and I'll help you understand it!"
    )


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /reload command.

    Patron-only: reloads persona.md and the config/topics knowledge files
    from disk (after a git pull) without restarting the bot.
    """
    if not update.message or not update.message.chat:
        return

    chat_id = update.message.chat.id
    patron_ids = get_patron_chat_ids()

    if chat_id not in patron_ids:
        await update.message.reply_text("Sorry, this command is for patrons only.")
        return

    # Reload persona and knowledge configuration
    success, message = reload_config()

    if success:
        await update.message.reply_text(f"✓ {message}")
    else:
        await update.message.reply_text(f"⚠️  {message}")


def _format_uptime(seconds: float) -> str:
    """Human-friendly uptime like '2d 3h', '4h 12m' or '45s'."""
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{seconds}s" if seconds < 60 else f"{minutes}m {seconds % 60}s"


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /status command.

    Patron-only (architecture section 8): uptime, today's exchange count,
    the global daily API counter, and the last error on record. Never
    exposes raw Telegram IDs or internal tracebacks.
    """
    if not update.message or not update.message.chat:
        return

    chat_id = update.message.chat.id
    patron_ids = get_patron_chat_ids()

    if chat_id not in patron_ids:
        await update.message.reply_text("Sorry, this command is for patrons only.")
        return

    uptime = _format_uptime(time.time() - _PROCESS_START)

    try:
        today_exchanges = get_today_exchange_count()
    except Exception as e:
        logger.error(f"Status: exchange count unavailable: {e}")
        today_exchanges = None

    try:
        counter = get_today_count()
    except Exception as e:
        logger.error(f"Status: daily counter unavailable: {e}")
        counter = None

    try:
        last_error = get_last_error()
    except Exception as e:
        logger.error(f"Status: last error unavailable: {e}")
        last_error = None

    exchanges_text = str(today_exchanges) if today_exchanges is not None else "unavailable"
    counter_text = str(counter) if counter is not None else "unavailable"

    if last_error:
        error_text = (f"{last_error['ts']} | {last_error['chat_alias']} | "
                      f"{last_error['status']} | {last_error['error'][:120]}")
    else:
        error_text = "none"

    await update.message.reply_text(
        "Dexter status\n"
        f"Uptime: {uptime}\n"
        f"Today's exchanges (Nairobi): {exchanges_text}\n"
        f"Daily API counter: {counter_text}/{get_daily_limit()}\n"
        f"Last error: {error_text}"
    )


def _log_rejection(db_alias: str, user_text: str, error: str) -> None:
    """
    Best-effort logging of a rate-limit rejection (never raises).

    Rejections are recorded with status 'quota_exhausted' so the weekly
    review can see when the shared quota blocked students.
    """
    try:
        exchange = Exchange(
            chat_alias=db_alias,
            user_text=user_text,
            snippet_ids=[],
            match_scores=[],
            model="",
            latency_ms=0,
            status="quota_exhausted",
            error=error,
            reviewed=0,
            reviewer_note=None
        )
        log_exchange(exchange)
    except Exception as log_error:
        logger.error(f"Logging failed: {log_error}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages by passing to the AI engine.

    Privacy boundary: the raw Telegram chat ID is transformed at this
    boundary before any other module sees it. The AI engine receives the
    generic "Student" alias to preserve privacy in the AI prompt, while
    the logger receives the privacy-safe Student-NN alias.

    Rate limiting (Step 4), in order:
    1. Per-user cooldown (in-memory, via context.bot_data).
    2. Global daily API counter: one atomic SQLite reservation taken
       BEFORE the AI engine is invoked; released again if the engine
       fails outright. Enforced only when the hash salt is configured
       (the required production configuration) — without it the bot
       keeps the Step 3 degraded behavior: answer without logging or
       quota tracking.
    """
    message = update.message
    if message and message.text and hasattr(message, 'chat') and message.chat:
        try:
            # PRIVACY BOUNDARY anchor: raw chat ID exists only in this
            # module, in process memory, never stored or passed onwards.
            raw_chat_id = message.chat.id

            # Step 4: per-user cooldown. context.bot_data is a plain dict
            # in production; if it is missing or not a dict we allow the
            # message rather than block a student.
            bot_data = context.bot_data if context is not None else None
            if not check_cooldown(bot_data, raw_chat_id):
                await message.reply_text(COOLDOWN_REPLY)
                return

            # PRIVACY BOUNDARY: transform raw Telegram chat ID before it
            # reaches any other module. If TELEGRAM_ID_HASH_SALT is not
            # configured, we cannot safely hash the ID, so we skip logging
            # but still process the message with AI.
            try:
                telegram_id_hash, db_alias = get_telegram_id_alias(raw_chat_id)
                logging_enabled = True
            except ValueError as salt_error:
                # Salt not configured - cannot safely hash Telegram ID.
                # Log diagnostic to stderr only, do NOT expose to the user.
                logger.error(f"Hashing unavailable: {salt_error}")
                logging_enabled = False
                db_alias = None

            # AI engine receives generic "Student" alias to preserve privacy
            # in the AI prompt. This is independent of logging configuration.
            ai_alias = "Student"

            # Step 4: global daily API limit. One atomic SQLite reservation
            # per AI call; fail-closed if the counter database is
            # unavailable so a database error can never bypass the limit.
            if logging_enabled and not try_consume():
                if db_alias is not None:
                    _log_rejection(db_alias, message.text, "daily API limit reached")
                await message.reply_text(DAILY_LIMIT_REPLY)
                return

            # Call AI engine
            result = answer(user_text=message.text, alias=ai_alias)

            # If the engine failed outright, give the daily-quota
            # reservation back so real failures do not burn the quota.
            if logging_enabled and result.status == STATUS_ERROR:
                release()

            # Send the reply text back to user (this must happen regardless of logging)
            await message.reply_text(result.reply_text)

            # Log the exchange only if hashing was successful (salt configured)
            if logging_enabled and db_alias is not None:
                try:
                    exchange = Exchange(
                        chat_alias=db_alias,
                        user_text=message.text,
                        snippet_ids=result.snippet_ids,
                        match_scores=result.match_scores,
                        model=result.model,
                        latency_ms=result.latency_ms,
                        status=result.status,
                        error=result.error,
                        reviewed=0,
                        reviewer_note=None
                    )
                    log_exchange(exchange)
                except Exception as log_error:
                    # Logging failure must never affect the user's response
                    logger.error(f"Logging failed: {log_error}")
                    # User already received their reply above, so no action needed

        except Exception as e:
            # Fallback to safe message if AI engine fails
            logger.error(f"AI engine error: {e}")
            await message.reply_text(RESTING_REPLY)


async def handle_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle non-text messages (photos, voice, etc.).

    Per architecture: "Non-text messages (photos, voice): reply 'Text only for now'"
    """
    message = update.message
    if message:
        await message.reply_text("Text only for now — type your question.")
