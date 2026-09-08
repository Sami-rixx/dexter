# Shule AI Helper — Architecture (v1)

> **Single source of truth.** Any coding agent working on this repo MUST read this
> file before making changes. If code and this document disagree, the document is
> wrong — fix the document first (in the same PR), then the code.

## 1. Context & Purpose

A STEM club at a Kenyan private school (junior secondary boys, CBC curriculum) is
building an AI chatbot as a hands-on learning project. Club members contribute
ideas, research, and testing feedback; the patron (a teacher, not a professional
developer) does all the coding with the help of an AI coding agent inside Termux
on a phone. GitHub is the code/config repo. No dedicated server — cost must stay
at or near zero (free-tier APIs and hosting only).

The bot helps students with:
- CBC topic explanations, kept simple
- Step-by-step math problem walkthroughs
- Timetable and career-pathway information
- Quick study tips

## 2. Tech Stack (v1)

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Telegram | `python-telegram-bot`, long polling (no public server / open ports — works from Termux) |
| AI model | Gemini API (free tier), via the official `google-genai` SDK |
| Storage | SQLite local file, no external DB |
| Config/knowledge | Plain Markdown files versioned in this repo |
| Dev environment | Termux on Android + AI coding agent |
| Time | Store all timestamps as UTC; display in Africa/Nairobi (UTC+3) in exports |

## 3. Repo Layout

```
shule-ai-helper/
├── ARCHITECTURE.md        # this file — single source of truth
├── README.md              # what the project is, how to run it
├── requirements.txt
├── .env.example           # template only — copy to .env locally, never commit
├── .gitignore             # MUST include: .env, data/, __pycache__/
├── bot/
│   ├── bot_core.py        # the ONLY module that talks to Telegram
│   ├── commands.py        # /start /help /reload /status handlers
│   └── ratelimit.py       # cooldowns + daily counter
├── ai/
│   ├── ai_engine.py       # prompt assembly + calling the model
│   ├── retriever.py       # keyword matching BEHIND the retrieve() interface
│   └── gemini_client.py   # thin wrapper around the Gemini SDK
├── logger/
│   ├── logger.py          # SQLite writes, best-effort
│   └── review_export.py   # dump a day's exchanges to Markdown/CSV
├── config/
│   ├── persona.md         # system prompt — edited by Ideation & Design Team
│   └── topics/            # CBC topic snippets — edited by Research Team
│       └── _template.md   # template showing the expected file format
├── data/                  # RUNTIME ONLY — gitignored, never pushed
│   └── shule.db
└── docs/
    └── testing_feedback.md # how the Testing Team reviews exports
```

## 4. Module Architecture — Three Isolated Modules

```
[Telegram] <--> [bot core] <--> [ai_engine] <--> [gemini_client] --> [Gemini API]
                     |              |
                     |         [retriever] --> config/topics/*.md
                     v              |
                 [logger] <--------'
                     |
                     v
                  data/shule.db
```

**Hard rules:**
- `bot/` never imports Gemini, the retriever, or logging internals. It passes
  text in, gets text out.
- `ai/` never imports anything Telegram-related. It does not know messages
  exist — it answers text questions.
- `logger/` never raises. A logging failure must never crash the bot or delay
  a student's reply.

### 4.1 Module Contracts

These signatures are the interface between modules. Changing one requires
updating this document in the same commit.

```python
# bot/bot_core.py
def handle_text_message(text: str, telegram_chat_id: int) -> str
    # Returns the reply text to send. Handles commands, rate limiting,
    # and non-text fallbacks. Knows nothing about prompts or models.

# ai/ai_engine.py
def answer(user_text: str, alias: str) -> EngineResult
    # Builds prompt = persona.md + retrieved snippets + user_text,
    # calls the model, returns the reply plus metadata for logging.

# ai/retriever.py
@dataclass
class Snippet:
    source_file: str
    content: str
    match_score: float

def retrieve(query: str, max_snippets: int = 2) -> list[Snippet]
    # v1: keyword matching against filenames and ## headers in topics/.
    # MUST stay behind this interface; the matching method is an
    # implementation detail and may be swapped (e.g. TF-IDF) later.

# logger/logger.py
def log_exchange(entry: Exchange) -> None
    # Best-effort SQLite insert. Swallows all exceptions after logging
    # a warning to stderr.
```

`EngineResult` carries: `reply_text`, `snippet_ids`, `match_scores`, `model`,
`latency_ms`, `status` (`ok | quota_exhausted | error`), `error` — so the bot
core never has to ask the engine anything else, and the logger gets everything
it needs in one object.

## 5. Rate Limiting & Quota Policy (required before first classroom use)

Free-tier Gemini quota is per-minute and per-day, shared by ALL students. A
classroom of excited boys will exhaust it in one session without protection.

- **Per-user cooldown:** 10–15 seconds between messages. In-memory dict is
  sufficient at this scale; if the bot restarts, cooldowns reset (acceptable).
- **Global daily counter:** SQLite, incremented per successful API call, so
  quota burn is visible and the export can show it.
- **Graceful degradation:** on `quota_exhausted` or any API error, reply with a
  friendly "I'm resting, try again in a few minutes" message and log the event.
  Never fail silently, never crash.

Deferred (do NOT build): queues, retries with backoff, per-user token budgets.

## 6. Logging & Privacy

### 6.1 Schema

```sql
CREATE TABLE users (
  telegram_id_hash TEXT PRIMARY KEY,   -- SHA-256 of the telegram chat_id, salted
  alias            TEXT NOT NULL,      -- e.g. "Student-07", the only handle ever shown
  first_seen       TEXT NOT NULL
);

CREATE TABLE exchanges (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           TEXT NOT NULL,          -- UTC ISO-8601
  chat_alias   TEXT NOT NULL,          -- from users table — never a name, never a raw ID
  user_text    TEXT NOT NULL,
  snippet_ids  TEXT,                   -- JSON list of source files injected
  match_scores TEXT,                   -- JSON list of floats, parallel to snippet_ids
  model        TEXT NOT NULL,
  latency_ms   INTEGER,
  status       TEXT NOT NULL,          -- ok | quota_exhausted | error
  error        TEXT,
  reviewed     INTEGER DEFAULT 0,
  reviewer_note TEXT
);
```

### 6.2 Privacy requirements — non-negotiable

Club members are **minors**.
- Never log real names or raw Telegram IDs anywhere — hash (salted SHA-256)
  the chat_id at the boundary, before anything else sees it.
- Aliases (`Student-NN`) are the only handle used in logs, exports, and anything
  shown to the Testing Team.
- `data/` is gitignored. The database never leaves the device it runs on.
- **Retention:** after the weekly review, keep exchanges at most 90 days, then
  purge. The review export (the annotated artifact) is the permanent record.

### 6.3 Review tooling

`python logger/review_export.py --date 2026-09-08` dumps one day's exchanges to
Markdown (human-readable) and CSV (spreadsheet-friendly), including
`snippet_ids`/`match_scores` so reviewers can distinguish "the AI answered
badly" from "the retriever never found the right file." This export IS the
entire review infrastructure — no dashboard, no web UI.

## 7. Config-as-Source-of-Truth

Persona and knowledge live as versioned Markdown in this repo, not in code:
- `config/persona.md` — tone, behavior, what the bot should and shouldn't do.
  Owned by the Ideation & Design Team; the patron merges their edits.
- `config/topics/*.md` — CBC topic explanations and math walkthroughs. Owned by
  the Research Team; **fact-checked by the patron before every merge**.
- Every topic file follows `config/topics/_template.md` (title, grade, keywords,
  body) so the retriever has a consistent structure to match against.

A patron-only `/reload` command re-reads `persona.md` and `topics/` from disk
after a `git pull`, so config edits go live without restarting the Termux
session. If a file is malformed, keep the previous config and warn the patron —
never crash.

## 8. Commands

| Command | Audience | Behavior |
|---|---|---|
| `/start`, `/help` | students | Intro + what the bot can do |
| `/reload` | patron only (chat_id allowlist in `.env`) | Re-read persona.md + topics/ |
| `/status` | patron only | Uptime, today's exchange count, daily counter, last error |

Non-text messages (photos, voice): reply "Text only for now — type your
question." (Photo homework help is a deliberate v2 decision.)

## 9. Secrets & Security

- `GEMINI_API_KEY` and `PATRON_CHAT_IDS` live in `.env` (gitignored).
  `.env.example` documents the keys with placeholder values.
- **Never commit a real key.** GitHub scans pushes and blocks/handles Google API
  keys; if a key is ever committed, rotate it immediately at Google AI Studio
  and treat it as compromised.
- The bot is text-in/text-out to students; there is no admin surface beyond the
  two patron commands above.

## 10. Error Handling Policy

| Failure | Behavior |
|---|---|
| Gemini quota exhausted | Friendly "resting" reply + `quota_exhausted` log event |
| Gemini/network error | Same friendly reply + `error` log event; never expose traceback to students |
| persona.md / topics file malformed on `/reload` | Keep previous config, warn patron in chat |
| Logger fails | Swallow, warn to stderr, reply unaffected |
| Non-text message | "Text only for now" |

## 11. Build Order — skeleton-first, each step validated before the next

1. **Bot core alone** — echo bot.
   *Done when:* every Telegram message gets a "got it" reply within ~5 s.
2. **Wire in AI engine** with a minimal `persona.md`.
   *Done when:* replies come from Gemini and follow persona tone; `/reload`
   changes behavior without restart.
3. **Add Logger** — with alias hashing from the very first write.
   *Done when:* every exchange appears in SQLite with alias, timestamps, and
   model; no raw Telegram ID anywhere in the DB.
4. **Add rate limiting** — before ANY real classroom use.
   *Done when:* 3 rapid messages from one user → 1 answered, 2 get the cooldown
   notice; daily counter increments.
5. **Layer in knowledge files** — retriever injects snippets via `retrieve()`.
   *Done when:* a question matching a topic file shows that file in
   `snippet_ids` of the log, and the answer reflects its content.

## 12. Testing & Feedback Loop

1. Testing Team uses `review_export.py` to get the day's exchanges.
2. They annotate: wrong answer? wrong/missing snippet (`match_scores` low or
   `snippet_ids` empty)? quota issues? Tone problems?
3. Annotated export goes to the patron → converted into GitHub issues or
   direct fixes. Fact errors in `topics/` get fixed by the Research Team via PR,
   patron fact-checks, `/reload` ships it.
4. This loop, weekly, is the entire QA process for v1.

## 13. Upgrade Triggers (so nobody re-litigates these prematurely)

- **Retrieval upgrade:** swap keyword matching for TF-IDF (still in-process,
  no infra) when EITHER `topics/` exceeds ~40 files OR weekly review shows
  >20% of flagged bad answers had wrong/empty `snippet_ids`. Only ever behind
  `retrieve()` — nothing else changes.
- **Always-on hosting:** decide only when the school needs the bot live outside
  club sessions. Evaluate free-tier options against *current* terms at that
  time (they change often). Bot core is the only module a hosting change
  touches — polling loop vs. webhook front — which is exactly why the isolation
  above matters. Stopgaps: the school's Windows 7 lab machine via Task
  Scheduler; Termux:Boot + wake-lock on the phone.

## 14. Deliberately Deferred — do not build yet

- Intent classification / routing
- Vector/semantic search (keyword matching is fine for v1, behind `retrieve()`)
- Multi-turn conversation memory / sessions
- Always-on hosting (see §13)
- Queues, retries with backoff, per-user token budgets
- Photo/voice input

## 15. Open Questions

- Final free-tier hosting choice, when §13 trigger fires (verify current terms).
- Exact retrieval-swap timing (§13 gives the measurable triggers).
