#!/usr/bin/env python3
"""
Dexter Bot Commands - Step 3 Implementation

This module contains the command handlers for the bot.
It maintains the separation between Telegram-specific code and AI logic.

Architecture constraints:
- Imports from ai/ module but only the public interface
- Never imports Gemini SDK internals
- Imports from logger/ module only the public interface
- Raw Telegram chat IDs are transformed at the boundary before any other module sees them
"""

import os
import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from ai.ai_engine import answer, reload_persona
from logger.logger import get_telegram_id_alias, Exchange, log_exchange

logger = logging.getLogger(__name__)


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
    
    Patron-only: reloads persona.md configuration without restarting the bot.
    """
    if not update.message or not update.message.chat:
        return
    
    chat_id = update.message.chat.id
    patron_ids = get_patron_chat_ids()
    
    if chat_id not in patron_ids:
        await update.message.reply_text("Sorry, this command is for patrons only.")
        return
    
    # Reload persona
    success, message = reload_persona()
    
    if success:
        await update.message.reply_text(f"✓ {message}")
    else:
        await update.message.reply_text(f"⚠️  {message}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages by passing to AI engine.
    
    For Step 3: transforms raw Telegram chat ID at the boundary before
    any other module sees it. AI engine still receives generic "Student" alias
    to preserve privacy in the AI prompt, while logger receives privacy-safe alias.
    """
    message = update.message
    if message and message.text and hasattr(message, 'chat') and message.chat:
        try:
            # PRIVACY BOUNDARY: Transform raw Telegram chat ID before it reaches any other module
            # If TELEGRAM_ID_HASH_SALT is not configured, we cannot safely hash the ID,
            # so we skip logging but still process the message with AI
            raw_chat_id = message.chat.id
            try:
                telegram_id_hash, db_alias = get_telegram_id_alias(raw_chat_id)
                logging_enabled = True
            except ValueError as salt_error:
                # Salt not configured - cannot safely hash Telegram ID
                # Log diagnostic to stderr only, do NOT expose the error to user
                logger.error(f"Hashing unavailable: {salt_error}")
                # Set flag to skip logging, but continue with AI processing
                logging_enabled = False
                db_alias = None
            
            # AI engine receives generic "Student" alias to preserve privacy in AI prompt
            # This is independent of logging configuration
            ai_alias = "Student"
            
            # Call AI engine
            result = answer(user_text=message.text, alias=ai_alias)
            
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
            await message.reply_text("I'm resting, try again in a few minutes")


async def handle_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle non-text messages (photos, voice, etc.).
    
    Per architecture: "Non-text messages (photos, voice): reply 'Text only for now'"
    """
    message = update.message
    if message:
        await message.reply_text("Text only for now — type your question.")