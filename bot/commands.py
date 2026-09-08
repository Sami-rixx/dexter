#!/usr/bin/env python3
"""
Dexter Bot Commands - Step 2 Implementation

This module contains the command handlers for the bot.
It maintains the separation between Telegram-specific code and AI logic.

Architecture constraints:
- Imports from ai/ module but only the public interface
- Never imports Gemini SDK internals
- Never imports logger internals (Step 3)
"""

import os
import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from ai.ai_engine import answer, reload_persona

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
    
    For Step 2: gets answer from AI engine instead of replying "got it".
    Uses a generic "Student" alias for now (Step 3 will implement real aliases).
    """
    message = update.message
    if message and message.text:
        try:
            # Use generic alias for now (Step 3 will implement privacy-safe aliases)
            alias = "Student"
            
            # Call AI engine
            result = answer(user_text=message.text, alias=alias)
            
            # Send the reply text back to user
            await message.reply_text(result.reply_text)
            
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