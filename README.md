# Dexter - STEM Study Helper Bot

A Telegram bot built by a Kenyan STEM club to help students with CBC topics, math problems, and study tips.

## Current Status: BUILD STEP 3 Complete

This implementation completes **BUILD STEP 3** from the architecture: add privacy-safe SQLite exchange logger with alias hashing.

## Prerequisites

- Python 3.11+ (developed with Python 3.14.6)
- Termux on Android or any Unix-like environment
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Gemini API key from [Google AI Studio](https://aistudio.google.com)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example environment file and set your tokens:

```bash
cp .env.example .env
```

Edit `.env` and set your tokens:

```bash
# Required for Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Required for AI engine
GEMINI_API_KEY=your_gemini_api_key_here

# Required for /reload command (comma-separated Telegram chat IDs)
PATRON_CHAT_IDS=12345678,87654321

# Required for privacy-safe logging - must be a strong random secret
# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
TELEGRAM_ID_HASH_SALT=your_strong_random_salt_here
```

### 3. Run the Bot

```bash
# Install dependencies and run
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"
export GEMINI_API_KEY="your_gemini_api_key_here"
export PATRON_CHAT_IDS="12345678,87654321"
export TELEGRAM_ID_HASH_SALT="your_strong_random_salt_here"
python bot/bot_core.py
```

Or in Termux with .env file:

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
nano .env

# Run the bot
python -m dotenv run python bot/bot_core.py
```

## Step 2 Behavior

- **/start** - Welcome message
- **/help** - Help message with capabilities
- **/reload** - Patron-only command to reload persona.md without restarting bot
- **Any text message** - Processed by AI engine using persona.md, returns generated answer, and logs exchange with privacy-safe alias
- **Photos/voice messages** - Replies "Text only for now — type your question."

## Step 3 Features

- **AI Engine**: Uses Gemini API via official `google-genai` SDK
- **Persona**: Loads system prompt from `config/persona.md` (editable without code changes)
- **Contract**: Implements `answer(user_text: str, alias: str) -> EngineResult` per architecture
- **EngineResult**: Carries `reply_text`, `snippet_ids`, `match_scores`, `model`, `latency_ms`, `status`, `error`
- **Error Handling**: Graceful degradation with friendly "resting" messages for API failures
- **/reload**: Patron-only command to reload persona configuration live
- **Privacy-Safe Logging**: SQLite database with salted SHA-256 hashed chat IDs and Student-NN aliases
- **Exchange Tracking**: All AI exchanges logged with metadata, never blocks bot responses

## Architecture Compliance

- ✅ Token from environment (never hardcoded)
- ✅ Uses python-telegram-bot with long polling
- ✅ Uses official google-genai SDK
- ✅ Telegram-specific code isolated in `bot/` directory
- ✅ AI code isolated in `ai/` directory
- ✅ Logger code isolated in `logger/` directory
- ✅ bot/ imports only public ai/ and logger/ interfaces
- ✅ ai/ never imports Telegram modules
- ✅ logger/ never imports Telegram, Gemini, or retriever modules
- ✅ Persona loaded from external config/persona.md file
- ✅ /reload preserves previous valid persona on malformed config
- ✅ /reload restricted to PATRON_CHAT_IDS allowlist
- ✅ Privacy: raw Telegram chat IDs never stored, only salted SHA-256 hashes
- ✅ Privacy: aliases (Student-NN) are the only handles used in logs
- ✅ Logging: best-effort, never blocks student responses
- ✅ Follows ARCHITECTURE.md specifications

## Next Steps

After Step 3 is validated:
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
├── bot/
│   ├── __init__.py        # Module init
│   ├── bot_core.py        # Telegram bot core
│   └── commands.py        # Command handlers (/start, /help, /reload)
├── ai/
│   ├── __init__.py        # Module init
│   ├── ai_engine.py       # Prompt assembly + EngineResult contract
│   ├── gemini_client.py   # Thin wrapper around google-genai SDK
│   └── exceptions.py      # Custom exceptions
├── logger/
│   ├── __init__.py        # Module init
│   └── logger.py          # SQLite exchange logger with privacy hashing
└── config/
    └── persona.md          # System prompt for AI
```

## Live Testing

To test with real AI responses:
- Set valid `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` in environment
- Run the bot and send messages to your Telegram bot
- The bot will respond with AI-generated answers based on persona.md

## Configuration

### Model Selection
- Default: `gemini-2.5-flash` (free tier compatible)
- Can be changed in `ai/ai_engine.py` if needed

### Persona Customization
- Edit `config/persona.md` to change the bot's personality and behavior
- Use `/reload` command (patron only) to apply changes without restart
- Malformed persona files preserve the last valid configuration

## Privacy & Logging

### Privacy Guarantees
- **Raw Telegram chat IDs are NEVER stored** in the database
- Only **salted SHA-256 hashes** are stored as identifiers
- **Aliases** like "Student-07" are the only handles used in logs and exports
- The hash salt is secret and configured via environment variable

### Database Location
- SQLite database: `data/shule.db` (created at runtime, **gitignored**)
- Contains two tables: `users` and `exchanges` per architecture
- Timestamp stored in UTC ISO-8601 format
- Logging is best-effort: never blocks student responses

### Retention Policy
- **90-day retention** for exchanges as specified in architecture
- Permanent review export is the official record
- Actual cleanup implementation is deferred to later steps

## License

MIT License - See LICENSE file for details.