#!/usr/bin/env python3
"""
Dexter Bot Core - Step 2: AI Integration

This is the ONLY module that talks to Telegram.
It handles Telegram input/output and passes text to other modules.
For Step 2, it routes text messages to the AI engine and handles /reload command.

Architecture constraints:
- Never imports Gemini, retriever, or logger internals
- Token must come from environment configuration
- Uses python-telegram-bot with long polling
- Communicates with ai/ module only through public interface
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

from .commands import (
    start_command,
    help_command,
    reload_command,
    handle_text_message,
    handle_non_text_message,
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
    application.add_handler(CommandHandler("reload", reload_command))
    
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