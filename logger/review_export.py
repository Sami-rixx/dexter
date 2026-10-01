#!/usr/bin/env python3
"""
Dexter Review Export (architecture sections 6.3 and 12)

Dumps one day's exchanges to Markdown (human-readable) and CSV
(spreadsheet-friendly), including snippet_ids/match_scores so the Testing
Team can distinguish "the AI answered badly" from "the retriever never
found the right file". This export IS the entire review infrastructure.

Usage:
    python logger/review_export.py --date 2026-09-08
    python logger/review_export.py                    # today (Nairobi)
    python logger/review_export.py --purge-old        # also purge >90-day-old
                                                      # exchanges (section 6.2)

Days are Africa/Nairobi days (the school day); timestamps are stored in
UTC (section 2) and displayed in Nairobi time in the Markdown export.

Never exposes raw Telegram IDs — only Student-NN aliases (section 6.2).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional

# Allow running both as a module (python -m logger.review_export) and as a
# script (python logger/review_export.py) from the repository root.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger.logger import (  # noqa: E402
    NAIROBI_UTC_OFFSET,
    TS_FORMAT,
    get_database_path,
    nairobi_day_bounds_utc,
    nairobi_today,
    parse_ts,
    purge_old_exchanges,
)

logger = logging.getLogger(__name__)

NAIROBI_SUFFIX = " EAT"  # Africa/Nairobi, UTC+3 (no DST in Kenya)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_rows(db_path: str, date_str: str) -> list:
    """
    All exchanges of the given Africa/Nairobi day, oldest first.
    """
    start_str, end_str = nairobi_day_bounds_utc(date_str)
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, ts, chat_alias, user_text, snippet_ids, match_scores, "
            "model, latency_ms, status, error, reviewed, reviewer_note "
            "FROM exchanges WHERE ts >= ? AND ts < ? ORDER BY ts, id",
            (start_str, end_str)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def fetch_daily_counter(db_path: str, date_str: str) -> Optional[int]:
    """
    The global daily API counter value for the day, if recorded.
    Reads the daily_counters table maintained by bot/ratelimit.py
    directly from the shared database (data-level sharing, no module
    dependency). Returns None when unavailable.
    """
    try:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT count FROM daily_counters WHERE day = ?", (date_str,)
            ).fetchone()
            return int(row["count"]) if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _nairobi_time(ts: str) -> str:
    """Convert a stored UTC timestamp to Nairobi display time."""
    parsed = parse_ts(ts)
    if parsed is None:
        return ts + " (unparsed)"
    return (parsed + NAIROBI_UTC_OFFSET).strftime("%H:%M") + NAIROBI_SUFFIX


def render_markdown(date_str: str, rows: list, counter: Optional[int]) -> str:
    """Human-readable Markdown export for the Testing Team."""
    generated_utc = datetime.now(timezone.utc).strftime(TS_FORMAT)
    lines = [
        f"# Dexter review export — {date_str} (Africa/Nairobi)",
        "",
        f"Generated: {generated_utc} (UTC)",
        f"Exchanges: {len(rows)}",
        f"Daily API counter: {counter if counter is not None else 'not recorded'}",
        "",
        "## How to review",
        "",
        "For each exchange, check the question, the knowledge snippets that",
        "were injected (snippet_ids with match_scores), the model, latency",
        "and status. Annotate this file (or the CSV) and send it to the",
        "patron:",
        "",
        "- Bad answer + low/empty match_scores or snippet_ids → the knowledge",
        "  file was not found (retriever gap).",
        "- Bad answer + good match_scores → the answer or the knowledge file",
        "  content needs fixing (Research Team, patron fact-checks).",
        "- quota_exhausted/error entries → quota or API issues to report.",
        "",
        "---",
        "",
    ]
    if not rows:
        lines.append("_No exchanges were logged on this day._\n")
        return "\n".join(lines)

    for row in rows:
        snippet_ids = json.loads(row.get("snippet_ids") or "[]")
        match_scores = json.loads(row.get("match_scores") or "[]")
        snippets = ", ".join(
            f"{sid} (score {score})"
            for sid, score in zip(snippet_ids, match_scores)
        ) or "none injected"
        error_line = row.get("error") or "—"
        reviewed = "yes" if row.get("reviewed") else "no"
        note = (row.get("reviewer_note") or "—")
        lines.extend([
            f"## {_nairobi_time(row['ts'])} — {row['chat_alias']} — "
            f"exchange #{row['id']} — {row['status']}",
            "",
            f"- **Question:** {row['user_text']}",
            f"- **Snippets:** {snippets}",
            f"- **Model:** {row.get('model') or '—'} — "
            f"{row.get('latency_ms') or 0} ms",
            f"- **Error:** {error_line}",
            f"- **Reviewed:** {reviewed} — note: {note}",
            "",
        ])
    return "\n".join(lines)


def render_csv(rows: list) -> str:
    """Spreadsheet-friendly CSV export."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "id", "ts_utc", "time_nairobi", "chat_alias", "user_text",
        "snippet_ids", "match_scores", "model", "latency_ms", "status",
        "error", "reviewed", "reviewer_note",
    ])
    for row in rows:
        writer.writerow([
            row["id"],
            row["ts"],
            _nairobi_time(row["ts"]),
            row["chat_alias"],
            row["user_text"],
            row.get("snippet_ids") or "[]",
            row.get("match_scores") or "[]",
            row.get("model") or "",
            row.get("latency_ms") or 0,
            row["status"],
            row.get("error") or "",
            row.get("reviewed") or 0,
            row.get("reviewer_note") or "",
        ])
    return buffer.getvalue()


def export_day(date_str: Optional[str] = None, db_path: Optional[str] = None,
               out_dir: Optional[str] = None) -> tuple:
    """
    Write the Markdown and CSV exports for one Nairobi day.

    Returns (markdown_path, csv_path). Raises on failure (the CLI reports
    it; this function is also usable as a library call).
    """
    if date_str is None:
        date_str = nairobi_today()
    if db_path is None:
        db_path = get_database_path()
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "exports")
    os.makedirs(out_dir, exist_ok=True)

    rows = fetch_rows(db_path, date_str)
    counter = fetch_daily_counter(db_path, date_str)

    base = f"review_{date_str}"
    md_path = os.path.join(out_dir, base + ".md")
    csv_path = os.path.join(out_dir, base + ".csv")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(date_str, rows, counter))
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write(render_csv(rows))

    return md_path, csv_path, len(rows)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export one day's Dexter exchanges for review "
                    "(architecture section 6.3).")
    parser.add_argument(
        "--date", default=None,
        help="Africa/Nairobi day to export as YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--db", default=None,
        help="Path to the SQLite database (default: data/shule.db)")
    parser.add_argument(
        "--out-dir", default=None,
        help="Directory for the export files (default: data/exports)")
    parser.add_argument(
        "--purge-old", action="store_true",
        help="After exporting, purge exchanges older than --keep-days "
             "(architecture section 6.2 retention)")
    parser.add_argument(
        "--keep-days", type=int, default=90,
        help="Retention window in days for --purge-old (default: 90)")
    args = parser.parse_args(argv)

    date_str = args.date or nairobi_today()
    if args.db is None:
        db_path = get_database_path()
    else:
        db_path = os.path.abspath(args.db)

    try:
        md_path, csv_path, count = export_day(date_str, db_path, args.out_dir)
    except Exception as e:
        print(f"Export failed: {e}", file=sys.stderr)
        return 1

    print(f"Exported {count} exchange(s) for {date_str}:")
    print(f"  Markdown: {md_path}")
    print(f"  CSV:      {csv_path}")

    if args.purge_old:
        purged = purge_old_exchanges(args.keep_days)
        print(f"Purged {purged} exchange(s) older than "
              f"{args.keep_days} day(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
