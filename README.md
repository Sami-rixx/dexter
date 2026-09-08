# Dexter - STEM Study Helper Bot

A Telegram bot built by a Kenyan STEM club to help students with CBC topics, math problems, and study tips.

## Current Status: BUILD STEP 1 Complete

This implementation completes **BUILD STEP 1** from the architecture: bot core alone.

## Prerequisites

- Python 3.11+ (developed with Python 3.14.6)
- Termux on Android or any Unix-like environment
- Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example environment file and set your token:

```bash
cp .env.example .env
```

Edit `.env` and set your Telegram bot token:

```bash
TELEGRAM_BOT_TOKEN=your_actual_token_here
```

### 3. Run the Bot

```bash
# Source the environment variables and run
export TELEGRAM_BOT_TOKEN=your_actual_token_here
python bot/bot_core.py
```

Or in Termux:

```bash
# Install dependencies first
pip install -r requirements.txt

# Set token and run
export TELEGRAM_BOT_TOKEN="your_actual_token_here"
python bot/bot_core.py
```

## Step 1 Behavior

- **/start** - Welcome message
- **/help** - Help message
- **Any text message** - Replies "got it"
- **Photos/voice messages** - Replies "Text only for now — type your question."

## Architecture Compliance

- ✅ Token from environment (never hardcoded)
- ✅ Uses python-telegram-bot with long polling
- ✅ Telegram-specific code isolated in `bot/` directory
- ✅ No imports of Gemini, retriever, or logger modules
- ✅ Simple text-in/text-out behavior
- ✅ Follows ARCHITECTURE.md specifications

## Next Steps

After Step 1 is validated:
- Step 2: Wire in AI engine with minimal persona.md
- Step 3: Add Logger with alias hashing
- Step 4: Add rate limiting
- Step 5: Layer in knowledge files with retriever

## Repository Structure

```
dexter/
├── ARCHITECTURE.md        # Single source of truth
├── README.md              # This file
├── requirements.txt       # Dependencies
├── .env.example           # Environment template
├── .gitignore             # Git ignore rules
└── bot/
    ├── __init__.py        # Module init
    └── bot_core.py        # Telegram bot core (Step 1)
```

## License

MIT License - See LICENSE file for details.