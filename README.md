# Dexter - STEM Study Helper Bot

A Telegram bot built by a Kenyan STEM club to help students with CBC topics, math problems, and study tips.

## Current Status: BUILD STEP 2 Complete

This implementation completes **BUILD STEP 2** from the architecture: wire the bot to a Gemini-backed AI engine with minimal persona.md.

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
```

### 3. Run the Bot

```bash
# Install dependencies and run
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"
export GEMINI_API_KEY="your_gemini_api_key_here"
export PATRON_CHAT_IDS="12345678,87654321"
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
- **Any text message** - Processed by AI engine using persona.md and returns generated answer
- **Photos/voice messages** - Replies "Text only for now — type your question."

## Step 2 Features

- **AI Engine**: Uses Gemini API via official `google-genai` SDK
- **Persona**: Loads system prompt from `config/persona.md` (editable without code changes)
- **Contract**: Implements `answer(user_text: str, alias: str) -> EngineResult` per architecture
- **EngineResult**: Carries `reply_text`, `snippet_ids`, `match_scores`, `model`, `latency_ms`, `status`, `error`
- **Error Handling**: Graceful degradation with friendly "resting" messages for API failures
- **/reload**: Patron-only command to reload persona configuration live

## Architecture Compliance

- ✅ Token from environment (never hardcoded)
- ✅ Uses python-telegram-bot with long polling
- ✅ Uses official google-genai SDK
- ✅ Telegram-specific code isolated in `bot/` directory
- ✅ AI code isolated in `ai/` directory
- ✅ bot/ imports only public ai/ interface (not Gemini SDK internals)
- ✅ ai/ never imports Telegram modules
- ✅ Persona loaded from external config/persona.md file
- ✅ /reload preserves previous valid persona on malformed config
- ✅ /reload restricted to PATRON_CHAT_IDS allowlist
- ✅ Follows ARCHITECTURE.md specifications

## Next Steps

After Step 2 is validated:
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
├── bot/
│   ├── __init__.py        # Module init
│   ├── bot_core.py        # Telegram bot core
│   └── commands.py        # Command handlers (/start, /help, /reload)
├── ai/
│   ├── __init__.py        # Module init
│   ├── ai_engine.py       # Prompt assembly + EngineResult contract
│   ├── gemini_client.py   # Thin wrapper around google-genai SDK
│   └── exceptions.py      # Custom exceptions
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

## License

MIT License - See LICENSE file for details.