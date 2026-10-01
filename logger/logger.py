#!/usr/bin/env python3
"""
Dexter Logger - Step 3 Implementation

This module implements best-effort SQLite exchange logging.
It never raises exceptions that can crash the bot or delay student responses.

Architecture constraints:
- Never imports Telegram modules
- Never imports Gemini SDK internals  
- Never imports retriever internals
- Never raises exceptions to callers
- Never blocks student responses
- Logs to stderr on failure only

Privacy requirements:
- Raw Telegram chat IDs are never stored
- Only salted SHA-256 hashes are stored as identifiers
- Aliases (Student-NN) are the only handles used in logs
"""

import os
import json
import sqlite3
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

# Set up module-level logger for stderr diagnostics
logger = logging.getLogger(__name__)


@dataclass
class Exchange:
    """
    Exchange data structure for logging.
    
    Per architecture §4.1 and §6.1, this carries the data needed
    for the logger to persist an exchange record.
    """
    chat_alias: str  # Privacy-safe alias like "Student-07"
    user_text: str   # The user's input text
    snippet_ids: list[str] = field(default_factory=list)  # JSON list of source files
    match_scores: list[float] = field(default_factory=list)  # JSON list of floats
    model: str = ""  # Model name used
    latency_ms: int = 0  # Processing time in milliseconds
    status: str = ""  # ok | quota_exhausted | error
    error: str = ""  # Error description if applicable
    reviewed: int = 0  # Review status (0 = not reviewed)
    reviewer_note: Optional[str] = None  # Reviewer annotation


def get_hash_salt() -> str:
    """
    Get the salt for SHA-256 hashing from environment.
    
    The salt must be secret and never committed.
    If not configured, raises ValueError - hashing cannot proceed.
    """
    salt = os.getenv("TELEGRAM_ID_HASH_SALT")
    if not salt or not salt.strip():
        raise ValueError("TELEGRAM_ID_HASH_SALT not configured")
    return salt


def hash_telegram_id(chat_id: int) -> str:
    """
    Create a salted SHA-256 hash of a Telegram chat ID.
    
    This is the privacy boundary: raw Telegram IDs must never be stored.
    The same chat_id with the same salt always produces the same hash.
    
    Args:
        chat_id: Raw Telegram chat ID (integer)
        
    Returns:
        Salted SHA-256 hash as hex string
    """
    salt = get_hash_salt()
    # Combine chat_id string with salt
    salted_input = f"{chat_id}{salt}"
    # Create SHA-256 hash
    hash_obj = hashlib.sha256(salted_input.encode('utf-8'))
    return hash_obj.hexdigest()


def generate_alias(chat_id_hash: str) -> str:
    """
    Generate a privacy-safe alias from a chat ID hash.
    
    Uses format like "Student-07" as mentioned in architecture.
    The alias is deterministic based on the hash, so the same user
    always gets the same alias.
    
    Args:
        chat_id_hash: Salted SHA-256 hash of the Telegram chat ID
        
    Returns:
        Privacy-safe alias string
    """
    # Use last 4 characters of hash to create a numeric identifier
    # This gives us a deterministic but non-identifying alias
    hash_hex_suffix = chat_id_hash[-4:]  # Last 4 hex characters
    numeric_suffix = int(hash_hex_suffix, 16) % 100  # 0-99
    return f"Student-{numeric_suffix:02d}"


def get_database_path() -> str:
    """Get the path to the SQLite database file."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "shule.db")


def initialize_database() -> None:
    """
    Initialize the SQLite database with the required schema.
    
    This is safe to call multiple times - it will not destroy existing records.
    """
    db_path = get_database_path()
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create users table per architecture §6.1
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id_hash TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                first_seen TEXT NOT NULL
            )
        """)
        
        # Create exchanges table per architecture §6.1
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                chat_alias TEXT NOT NULL,
                user_text TEXT NOT NULL,
                snippet_ids TEXT,
                match_scores TEXT,
                model TEXT NOT NULL,
                latency_ms INTEGER,
                status TEXT NOT NULL,
                error TEXT,
                reviewed INTEGER DEFAULT 0,
                reviewer_note TEXT
            )
        """)
        
        # Create index for faster queries by timestamp
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_exchanges_ts ON exchanges(ts)
        """)
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


def get_or_create_user(telegram_id_hash: str) -> tuple[str, str]:
    """
    Get existing user or create new user entry.
    
    Args:
        telegram_id_hash: Salted SHA-256 hash of Telegram chat ID
        
    Returns:
        tuple: (telegram_id_hash, alias)
    """
    # Ensure database is initialized
    initialize_database()
    
    db_path = get_database_path()
    alias = generate_alias(telegram_id_hash)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Try to get existing user
        cursor.execute(
            "SELECT alias FROM users WHERE telegram_id_hash = ?",
            (telegram_id_hash,)
        )
        result = cursor.fetchone()
        
        if result:
            # User exists, return existing alias
            existing_alias = result[0]
            conn.close()
            return telegram_id_hash, existing_alias
        else:
            # Create new user
            cursor.execute(
                "INSERT INTO users (telegram_id_hash, alias, first_seen) VALUES (?, ?, ?)",
                (telegram_id_hash, alias, now_utc)
            )
            conn.commit()
            conn.close()
            return telegram_id_hash, alias
            
    except Exception as e:
        logger.error(f"Failed to get/create user: {e}")
        # Return hash and generated alias even if DB write failed
        # This ensures logging can continue and the user gets a response
        return telegram_id_hash, alias


def log_exchange(entry: Exchange) -> None:
    """
    Log an exchange to the SQLite database.
    
    This is the public interface for logging.
    Per architecture §4.1: log_exchange(entry: Exchange) -> None
    
    Best-effort: never raises, never blocks student response.
    
    Args:
        entry: Exchange dataclass containing all logging data
    """
    # Ensure database is initialized
    initialize_database()
    
    db_path = get_database_path()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    
    try:
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Insert exchange record
        cursor.execute(
            """INSERT INTO exchanges (
                ts, chat_alias, user_text, snippet_ids, match_scores, 
                model, latency_ms, status, error, reviewed, reviewer_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_utc,
                entry.chat_alias,
                entry.user_text,
                json.dumps(entry.snippet_ids),
                json.dumps(entry.match_scores),
                entry.model,
                entry.latency_ms,
                entry.status,
                entry.error,
                entry.reviewed,
                entry.reviewer_note
            )
        )
        conn.commit()
        conn.close()
        
    except Exception as e:
        # Best-effort: swallow the exception, log to stderr only
        logger.error(f"Logger failed to write exchange: {e}")


def get_telegram_id_alias(chat_id: int) -> tuple[str, str]:
    """
    Transform a raw Telegram chat ID into a privacy-safe hash and alias.
    
    This is the boundary function that ensures raw Telegram IDs never
    leave the Telegram boundary. Requires TELEGRAM_ID_HASH_SALT to be configured.
    
    Args:
        chat_id: Raw Telegram chat ID
        
    Returns:
        tuple: (telegram_id_hash, alias) - privacy-safe identifiers
        
    Raises:
        ValueError: If TELEGRAM_ID_HASH_SALT is not configured
    """
    chat_id_hash = hash_telegram_id(chat_id)
    return get_or_create_user(chat_id_hash)


# ---------------------------------------------------------------------------
# Timezone helpers (architecture section 2: store timestamps as UTC,
# display Africa/Nairobi). Kenya does not observe daylight saving time,
# so a fixed UTC+3 offset is exact all year.
# ---------------------------------------------------------------------------

# Timestamp format used for the `ts` column of the exchanges table.
TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

NAIROBI_UTC_OFFSET = timedelta(hours=3)


def nairobi_now() -> datetime:
    """Current Africa/Nairobi time as an aware datetime (UTC+3, no DST)."""
    return datetime.now(timezone.utc) + NAIROBI_UTC_OFFSET


def nairobi_today() -> str:
    """Current Africa/Nairobi local date as 'YYYY-MM-DD'."""
    return nairobi_now().strftime("%Y-%m-%d")


def nairobi_day_bounds_utc(date_str: str) -> tuple[str, str]:
    """
    UTC timestamp bounds [start, end) of an Africa/Nairobi local date.

    The returned strings use TS_FORMAT so they can be compared directly
    (lexicographically) against the `ts` column of the exchanges table.

    Args:
        date_str: Nairobi local date as 'YYYY-MM-DD'

    Returns:
        tuple: (start_ts_utc, end_ts_utc) in TS_FORMAT

    Raises:
        ValueError: If date_str is not a valid 'YYYY-MM-DD' date.
    """
    day_start_nairobi = datetime.strptime(date_str, "%Y-%m-%d")
    start_utc = day_start_nairobi - NAIROBI_UTC_OFFSET
    end_utc = day_start_nairobi + timedelta(days=1) - NAIROBI_UTC_OFFSET
    return start_utc.strftime(TS_FORMAT), end_utc.strftime(TS_FORMAT)


def parse_ts(ts: str) -> Optional[datetime]:
    """
    Parse a stored UTC timestamp string into an aware UTC datetime.

    Returns None if the string cannot be parsed (best-effort, never raises).
    """
    try:
        return datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Review/status support (architecture sections 6.2, 6.3 and 8).
# All functions here are best-effort: they never raise to callers.
# ---------------------------------------------------------------------------

def get_today_exchange_count() -> Optional[int]:
    """
    Number of exchanges logged so far in the current Africa/Nairobi day.

    Returns None if the database is unavailable (best-effort, never raises).
    """
    try:
        initialize_database()
        start_str, end_str = nairobi_day_bounds_utc(nairobi_today())
        conn = sqlite3.connect(get_database_path())
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM exchanges WHERE ts >= ? AND ts < ?",
                (start_str, end_str)
            )
            return int(cursor.fetchone()[0])
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to count today's exchanges: {e}")
        return None


def get_last_error() -> Optional[dict]:
    """
    Most recent non-ok exchange (status 'error' or 'quota_exhausted').

    Returns a dict with keys ts, chat_alias, status, error — or None when
    there is no error on record or the database is unavailable.
    Never raises; never returns a raw Telegram ID.
    """
    try:
        initialize_database()
        conn = sqlite3.connect(get_database_path())
        try:
            cursor = conn.execute(
                "SELECT ts, chat_alias, status, error FROM exchanges "
                "WHERE status != 'ok' ORDER BY ts DESC, id DESC LIMIT 1"
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "ts": row[0],
            "chat_alias": row[1],
            "status": row[2],
            "error": row[3] or "",
        }
    except Exception as e:
        logger.error(f"Failed to read last error: {e}")
        return None


def purge_old_exchanges(keep_days: int = 90) -> int:
    """
    Delete exchanges older than `keep_days` days (architecture section 6.2:
    keep exchanges at most 90 days after the weekly review, then purge).

    Returns the number of rows deleted, or 0 on failure. Never raises.
    """
    try:
        initialize_database()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime(TS_FORMAT)
        conn = sqlite3.connect(get_database_path())
        try:
            cursor = conn.execute(
                "DELETE FROM exchanges WHERE ts < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to purge old exchanges: {e}")
        return 0