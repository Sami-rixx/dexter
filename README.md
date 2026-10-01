# Dexter - STEM Study Helper Bot

A Telegram bot built by a Kenyan STEM club to help students with CBC topics, math problems, and study tips.

## Current Status: BUILD STEP 5 Complete (v1 feature-complete)

All five build steps from the architecture are implemented:

1. **BUILD STEP 1** — Telegram core with command handlers
2. **BUILD STEP 2** — Gemini AI engine with persona and graceful degradation
3. **BUILD STEP 3** — Privacy-safe SQLite exchange logger with alias hashing
4. **BUILD STEP 4** — Rate limiting (per-user cooldown + global daily API counter)
5. **BUILD STEP 5** — Knowledge retrieval over the CBC topic files (`config/topics/`)

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

Edit `.env` and set your values:

```bash
# Required for Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Required for AI engine
GEMINI_API_KEY=your_gemini_api_key_here

# Required for /reload and /status (comma-separated Telegram chat IDs)
PATRON_CHAT_IDS=12345678,87654321

# Required for privacy-safe logging - must be a strong random secret
# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
TELEGRAM_ID_HASH_SALT=your_strong_random_salt_here

# Optional rate limiting (defaults shown)
COOLDOWN_SECONDS=15      # per-user cooldown in seconds
DAILY_API_LIMIT=200      # shared daily Gemini call budget
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

## Bot Behavior

- **/start** - Welcome message
- **/help** - Help message with capabilities
- **/reload** - Patron-only: reload persona **and** knowledge files without restarting
- **/status** - Patron-only: uptime, today's exchange count, daily API counter, last error
- **Any text message** - Checked against rate limits, grounded with knowledge snippets, answered via Gemini using the persona, and logged with a privacy-safe alias
- **Photos/voice messages** - Replies "Text only for now — type your question."

## Rate Limiting (Step 4)

Protects the shared free-tier Gemini quota:

- **Per-user cooldown** (default 15s): rapid repeat messages get a friendly
  "taking a short rest" notice instead of an API call
- **Global daily counter** (default 200 calls, adjustable via `DAILY_API_LIMIT`):
  when exhausted, everyone gets the daily-limit message and the bot logs
  rejections as `quota_exhausted`
- The counter is a single atomic SQLite upsert, so concurrent messages can
  never overshoot the limit (verified by a 16-thread regression test)
- On a database error the limiter **fails closed** — no AI call without a
  reservation
- Nairobi (UTC+3) days, matching the students' school day

## Knowledge Retrieval (Step 5)

- 26 Grade 7 Integrated Science knowledge files in `config/topics/`, written
  from the club's CBC notes PDF
- The retriever matches a question against each file's name, title, `##`
  section headings, and metadata (Grade/Learning area/Strand/Topic/Keywords)
- The best-matching snippets are injected into the Gemini prompt with
  instructions to answer from that material and to say when it doesn't
  cover the question (no invented curriculum facts)
- `snippet_ids` and `match_scores` are stored with every exchange, so
  reviewers can tell "wrong answer" from "right file never found"
- New grades/subjects: drop more Markdown files into `config/topics/`
  following `config/topics/_template.md`, then `/reload` — no code changes
- Missing, empty, or malformed knowledge files are skipped (never crash);
  a failed reload keeps the previous index

## Review Exports (Testing Team)

```bash
# Dump one day's exchanges (Nairobi day) to Markdown + CSV:
python logger/review_export.py --date 2026-09-08

# Purge exchanges older than 90 days:
python logger/review_export.py --purge-old
```

Exports land in `data/exports/review_YYYY-MM-DD.{md,csv}` with aliases only.
See `docs/testing_feedback.md` for the weekly review loop.

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
- ✅ Knowledge loaded from external config/topics/*.md files
- ✅ /reload preserves previous valid persona and topics on malformed config
- ✅ /reload and /status restricted to PATRON_CHAT_IDS allowlist
- ✅ Privacy: raw Telegram chat IDs never stored, only salted SHA-256 hashes
- ✅ Privacy: aliases (Student-NN) are the only handles used in logs
- ✅ Privacy: no raw chat IDs in prompts, exports, or error messages
- ✅ Logging: best-effort, never blocks student responses
- ✅ Rate limits checked before any Gemini call
- ✅ Follows ARCHITECTURE.md specifications

## Repository Structure

```
dexter/
├── ARCHITECTURE.md        # Single source of truth
├── README.md              # This file
├── requirements.txt       # Dependencies
├── .env.example           # Environment template
├── .gitignore             # Git ignore rules
├── docs/
│   └── testing_feedback.md  # Testing Team review guide
├── bot/
│   ├── __init__.py        # Module init
│   ├── bot_core.py        # Telegram bot core
│   ├── commands.py        # Handlers (/start /help /reload /status, text)
│   └── ratelimit.py       # Cooldown + atomic daily API counter
├── ai/
│   ├── __init__.py        # Module init
│   ├── ai_engine.py       # Prompt assembly + EngineResult contract
│   ├── gemini_client.py   # Thin wrapper around google-genai SDK
│   ├── retriever.py       # Keyword retriever over config/topics/
│   └── exceptions.py      # Custom exceptions
├── logger/
│   ├── __init__.py        # Module init
│   ├── logger.py          # SQLite exchange logger with privacy hashing
│   └── review_export.py   # Day exports to Markdown/CSV + retention purge
├── config/
│   ├── persona.md         # System prompt for AI
│   └── topics/            # 26 CBC knowledge files + _template.md
├── test_bot_core.py       # Step 1 tests
├── test_step2.py          # Step 2 tests (AI engine)
├── test_step3.py          # Step 3 tests (logger/privacy)
├── test_step4.py          # Step 4 tests (rate limiting, /status)
└── test_step5.py          # Step 5 tests (retrieval, review export)
```

## Testing

All suites run offline — Telegram and Gemini are mocked; no live API
verification is claimed by the tests:

```bash
# Everything:
python -m unittest discover -p "test_*.py"

# Or individually:
python -m unittest test_bot_core test_step2 test_step3 test_step4 test_step5
```

Highlights: rate-limit concurrency (16 threads cannot overshoot the daily
limit), privacy boundary (no raw chat IDs anywhere), retrieval relevance
against the real knowledge files, malformed knowledge handling, persona and
topic reload, Gemini error classification, and the end-to-end message flow.

## Live Testing

To test with real AI responses:
- Set valid `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` in environment
- Run the bot and send messages to your Telegram bot
- The bot will respond with AI-generated answers based on persona.md and the
  matching knowledge files

## Configuration

### Model Selection
- Default: `gemini-2.5-flash` (free tier compatible)
- Can be changed in `ai/ai_engine.py` if needed

### Persona Customization
- Edit `config/persona.md` to change the bot's personality and behavior
- Use `/reload` command (patron only) to apply changes without restart
- Malformed persona files preserve the last valid configuration

### Knowledge Base
- Edit or add files in `config/topics/` (see `_template.md` for the format)
- `/reload` (patron only) re-indexes them without a restart
- Malformed files are skipped; the previous index is kept on failure

### Rate Limits
- `COOLDOWN_SECONDS` — per-user cooldown (default 15)
- `DAILY_API_LIMIT` — shared daily Gemini budget (default 200, roughly the
  free-tier daily cap; adjust to current terms)

## Privacy & Logging

### Privacy Guarantees
- **Raw Telegram chat IDs are NEVER stored** in the database
- Only **salted SHA-256 hashes** are stored as identifiers
- **Aliases** like "Student-07" are the only handles used in logs, exports,
  prompts, and error messages
- The hash salt is secret and configured via environment variable (mandatory;
  logging is disabled without it)

### Database Location
- SQLite database: `data/shule.db` (created at runtime, **gitignored**)
- Tables: `users`, `exchanges`, `daily_counters`
- Timestamps stored in UTC ISO-8601; days counted in Africa/Nairobi (UTC+3)
- Logging is best-effort: never blocks student responses

### Retention Policy
- **90-day retention** for exchanges as specified in architecture
- The permanent record is the annotated review export
- Purge with `python logger/review_export.py --purge-old`

## License

MIT License - See LICENSE file for details.
