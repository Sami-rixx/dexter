#!/usr/bin/env python3
"""
Dexter Rate Limiting - Step 4 Implementation

Implements the two quota protections required by ARCHITECTURE.md section 5
before any real classroom use:

1. Per-user cooldown (10-15 seconds between messages)
   - In-memory only, kept in the Telegram application's bot_data dict.
     Raw chat IDs live in process RAM for the lifetime of the cooldown
     window only: they are never written to disk, never passed to other
     modules and never logged.
   - If bot_data is missing or is not a dict (degraded runtime), the
     cooldown is skipped rather than blocking a student.
   - If the bot restarts, cooldowns reset (acceptable per the architecture).

2. Global daily API counter (SQLite)
   - Lives in the shared runtime database data/shule.db, table
     daily_counters(day TEXT PRIMARY KEY, count INTEGER NOT NULL).
   - The day key is the Africa/Nairobi local date (Kenya is UTC+3 all
     year, no DST) so the quota matches the school day it caps.
   - CONCURRENCY SAFETY: the check-and-increment is ONE atomic SQL
     statement (INSERT ... ON CONFLICT DO UPDATE ... WHERE count < limit)
     verified with SELECT changes() on the same connection. SQLite
     serializes writes, so concurrent requests can never push the count
     past the limit. A naive SELECT-then-UPDATE implementation was
     verified during development to overshoot the limit under concurrent
     threads and is deliberately NOT used. On SQLite builds older than
     3.24 (no upsert support) an equivalent BEGIN IMMEDIATE transaction
     is used instead — it is atomic for the same reason.
   - The counter is a reservation taken BEFORE the Gemini call. If the
     engine then fails with a hard error (status "error"), the caller
     releases the reservation so genuine failures do not burn the day's
     quota. Google-side quota exhaustion ("quota_exhausted") keeps the
     reservation: the attempt was still made against Google's limits.
   - FAIL-CLOSED: if the counter database cannot be read or written, the
     AI call is rejected. A database error must not become a way to
     bypass the daily limit.
   - Quota enforcement is active only when TELEGRAM_ID_HASH_SALT is
     configured (the required production configuration). Without the
     salt the bot keeps the established Step 3 degraded behavior: the
     student still gets an answer, with logging and quota tracking
     skipped.

Configuration (environment variables):
- COOLDOWN_SECONDS: per-user cooldown in seconds (default 15; the
  architecture allows 10-15).
- DAILY_API_LIMIT:   global daily Gemini call limit (default 200).

Architecture constraints:
- Lives in bot/ because it protects the Telegram entry point.
- Never imports the Gemini SDK, the knowledge retriever, or logger
  internals; it only uses the logger module's public date helpers.
- Never raises to its callers.
"""

import os
import sqlite3
import logging
import time
from typing import Optional

from logger.logger import nairobi_today

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 15.0
DEFAULT_DAILY_API_LIMIT = 200

# Key under which the per-user cooldown table is stored in bot_data.
COOLDOWNS_KEY = "dexter_cooldowns"

# Table shared with the logger module inside data/shule.db.
_COUNTER_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS daily_counters ("
    "day TEXT PRIMARY KEY, "
    "count INTEGER NOT NULL"
    ")"
)


def get_cooldown_seconds() -> float:
    """
    Per-user cooldown in seconds, from COOLDOWN_SECONDS (default 15).

    Invalid or negative values fall back to the default with a warning.
    A value of 0 disables the cooldown.
    """
    raw = os.getenv("COOLDOWN_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_COOLDOWN_SECONDS
    try:
        value = float(raw.strip())
    except ValueError:
        logger.warning(f"Invalid COOLDOWN_SECONDS value {raw!r}; "
                       f"using default {DEFAULT_COOLDOWN_SECONDS}")
        return DEFAULT_COOLDOWN_SECONDS
    if value < 0:
        logger.warning(f"Negative COOLDOWN_SECONDS value {raw!r}; "
                       f"using default {DEFAULT_COOLDOWN_SECONDS}")
        return DEFAULT_COOLDOWN_SECONDS
    return value


def get_daily_limit() -> int:
    """
    Global daily Gemini call limit, from DAILY_API_LIMIT (default 200).

    Invalid or non-positive values fall back to the default with a warning.
    """
    raw = os.getenv("DAILY_API_LIMIT")
    if raw is None or not raw.strip():
        return DEFAULT_DAILY_API_LIMIT
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(f"Invalid DAILY_API_LIMIT value {raw!r}; "
                       f"using default {DEFAULT_DAILY_API_LIMIT}")
        return DEFAULT_DAILY_API_LIMIT
    if value < 1:
        logger.warning(f"Non-positive DAILY_API_LIMIT value {raw!r}; "
                       f"using default {DEFAULT_DAILY_API_LIMIT}")
        return DEFAULT_DAILY_API_LIMIT
    return value


def get_database_path() -> str:
    """Path of the shared runtime database (data/shule.db)."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "shule.db")


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Open an autocommit connection with a busy timeout.

    Every call gets its own connection, which makes the helpers in this
    module safe to call from multiple threads. WAL journaling is enabled
    opportunistically so readers do not block the writer; failure to
    enable it (e.g. exotic filesystems) is harmless.
    """
    if db_path is None:
        db_path = get_database_path()
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    conn.execute(_COUNTER_TABLE_SQL)
    return conn


def _try_consume_with_transaction(conn: sqlite3.Connection, day: str, limit: int) -> bool:
    """
    Atomic check-and-increment for SQLite builds without upsert support
    (older than 3.24). BEGIN IMMEDIATE acquires the database write lock
    for the whole read-decide-write sequence, so it cannot interleave.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT count FROM daily_counters WHERE day = ?", (day,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO daily_counters (day, count) VALUES (?, 1)", (day,)
            )
            allowed = True
        elif row[0] < limit:
            conn.execute(
                "UPDATE daily_counters SET count = count + 1 WHERE day = ?", (day,)
            )
            allowed = True
        else:
            allowed = False
        conn.execute("COMMIT")
        return allowed
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def try_consume(limit: Optional[int] = None, day: Optional[str] = None,
                db_path: Optional[str] = None) -> bool:
    """
    Atomically reserve one slot of the global daily API quota.

    Returns True if a slot was reserved (the caller may proceed with the
    Gemini call), False if the day's limit is reached or the counter
    database is unavailable (fail-closed). Never raises.
    """
    if limit is None:
        limit = get_daily_limit()
    if day is None:
        day = nairobi_today()
    try:
        conn = _connect(db_path)
        try:
            try:
                # Single atomic statement: SQLite serializes writes, so the
                # conditional increment can never overshoot the limit even
                # when many threads race on the same day.
                conn.execute(
                    "INSERT INTO daily_counters (day, count) VALUES (?, 1) "
                    "ON CONFLICT(day) DO UPDATE SET count = count + 1 "
                    "WHERE count < ?",
                    (day, limit)
                )
                changed = conn.execute("SELECT changes()").fetchone()[0]
                return changed == 1
            except sqlite3.OperationalError as e:
                # Ancient SQLite without upsert support: use the
                # transaction-based atomic path instead.
                if "ON CONFLICT" in str(e) or "syntax error" in str(e).lower():
                    return _try_consume_with_transaction(conn, day, limit)
                raise
        finally:
            conn.close()
    except Exception as e:
        # Fail-closed: a database error must not become a quota bypass.
        logger.error(f"Daily counter unavailable (fail-closed): {e}")
        return False


def release(day: Optional[str] = None, db_path: Optional[str] = None) -> None:
    """
    Give back one reserved daily-quota slot (best-effort, never raises).

    Called when the AI engine failed outright (status "error") so genuine
    failures do not burn the shared daily quota. The count never goes
    below zero.
    """
    if day is None:
        day = nairobi_today()
    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                "UPDATE daily_counters SET count = count - 1 "
                "WHERE day = ? AND count > 0",
                (day,)
            )
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to release daily quota slot: {e}")


def get_today_count(day: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """
    Number of daily-quota slots consumed so far today (Africa/Nairobi day).

    Returns 0 when nothing has been consumed or the database is
    unavailable. Never raises.
    """
    if day is None:
        day = nairobi_today()
    try:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT count FROM daily_counters WHERE day = ?", (day,)
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to read daily counter: {e}")
        return 0


def check_cooldown(bot_data: Optional[object], user_key: object,
                   cooldown_seconds: Optional[float] = None,
                   now: Optional[float] = None) -> bool:
    """
    Per-user cooldown check (and timestamp update).

    The cooldown table lives inside `bot_data` — the plain dict that
    python-telegram-bot shares across handlers. If bot_data is missing or
    is not a dict the check is skipped (allow) rather than failing.

    Args:
        bot_data: the shared dict from the Telegram context (or None).
        user_key: key identifying the user for this process only.
        cooldown_seconds: window in seconds; None reads COOLDOWN_SECONDS.
        now: current time override for testing; None uses time.time().

    Returns:
        True if the message may proceed, False if the user is cooling down.
    """
    if not isinstance(bot_data, dict):
        # No usable shared state (e.g. degraded context). Allow the message
        # instead of blocking a student.
        return True
    if cooldown_seconds is None:
        cooldown_seconds = get_cooldown_seconds()
    if cooldown_seconds <= 0:
        return True
    if now is None:
        now = time.time()

    cooldowns = bot_data.get(COOLDOWNS_KEY)
    if not isinstance(cooldowns, dict):
        cooldowns = {}
        bot_data[COOLDOWNS_KEY] = cooldowns

    last = cooldowns.get(user_key)
    if last is not None and (now - last) < cooldown_seconds:
        return False
    cooldowns[user_key] = now
    return True
