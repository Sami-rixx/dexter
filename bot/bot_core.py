#!/usr/bin/env python3
"""
Dexter Bot Core - Step 1: Echo Bot Implementation

This is the ONLY module that talks to Telegram.
It handles Telegram input/output and passes text to other modules.
For Step 1, it simply replies "got it" to every text message.

Architecture constraints:
- Never imports Gemini, retriever, or logger internals
- Token must come from environment configuration
- Uses python-telegram-bot with long polling
"""

import os
import logging
from typing import Optional

from telegram import Update, Message
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Set up basic logging for the bot
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_bot_token() -> str:
    """Get Telegram bot token from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not found in environment. "
            "Set it in .env file or export it before running the bot."
        )
    return token


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text("Hi! I'm Dexter, your STEM study helper. Send me a message and I'll reply 'got it' for now.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text("I'm Dexter, a study helper bot. For now, I'll reply 'got it' to any message you send.")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages.
    
    For Step 1, simply reply "got it" to acknowledge receipt.
    This satisfies the requirement: "every Telegram message gets a 'got it' reply within ~5 s"
    
    Args:
        update: Telegram update object containing the message
        context: Context for the conversation
    """
    message: Optional[Message] = getattr(update, 'message', None)
    if message and message.text:
        # For Step 1: simply reply "got it"
        await message.reply_text("got it")


async def handle_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle non-text messages (photos, voice, etc.).
    
    Per architecture: "Non-text messages (photos, voice): reply 'Text only for now'"
    """
    message: Optional[Message] = getattr(update, 'message', None)
    if message:
        await message.reply_text("Text only for now — type your question.")


def create_application() -> Application:
    """
    Create and configure the Telegram bot application.
    
    Returns:
        Application: Configured telegram.ext.Application instance
    """
    token = get_bot_token()
    
    application = Application.builder().token(token).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Register message handlers
    # Text messages (excluding commands, which are handled above)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_text_message
    ))
    
    # Non-text messages
    application.add_handler(MessageHandler(
        ~filters.TEXT, 
        handle_non_text_message
    ))
    
    return application


def run_bot() -> None:
    """
    Run the Dexter bot using long polling.
    
    This is the main entry point for the bot.
    Uses long polling as specified in the architecture.
    """
    application = create_application()
    
    logger.info("Starting Dexter bot with long polling...")
    application.run_polling(
        poll_interval=1.0,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    run_bot()