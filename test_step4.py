#!/usr/bin/env python3
"""
Tests for Dexter Bot - BUILD STEP 4 (Rate Limiting)

Covers the Step 4 requirements of ARCHITECTURE.md section 5:
- Per-user cooldown (10-15 s, in-memory, resets on restart)
- Global daily API counter in SQLite, incremented per AI call
- Graceful, friendly rejection messages; nothing technical exposed
- CONCURRENCY: the global daily counter must be atomic — concurrent
  requests must never push the count past the configured limit (this
  regression test exists because a naive SELECT-then-UPDATE counter was
  verified to overshoot under concurrent threads)
- FAIL-CLOSED: a database error must not become a quota bypass
- Patron-only /status command (uptime, today's exchanges, daily counter,
  last error)
- Rate-limit rejection happens BEFORE the AI engine is invoked

All tests use temporary databases and mocks; no network, no real keys.
"""

import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch, AsyncMock, Mock
import asyncio

from bot.ratelimit import (
    check_cooldown,
    try_consume,
    release,
    get_today_count,
    get_daily_limit,
    get_cooldown_seconds,
    _connect,
    _try_consume_with_transaction,
    COOLDOWNS_KEY,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_DAILY_API_LIMIT,
)


class TestRateLimitModuleStructure(unittest.TestCase):
    """Test the rate limit module exists and follows isolation rules."""

    def test_ratelimit_file_exists(self):
        """Architecture section 3 requires bot/ratelimit.py."""
        self.assertTrue(os.path.exists('bot/ratelimit.py'))

    def test_ratelimit_imports_successfully(self):
        """Test the module exposes its public functions."""
        import bot.ratelimit as rl
        for name in ('check_cooldown', 'try_consume', 'release',
                     'get_today_count', 'get_daily_limit',
                     'get_cooldown_seconds'):
            self.assertTrue(hasattr(rl, name), f"missing {name}")

    def test_ratelimit_no_telegram_imports(self):
        """The module must not import Telegram modules."""
        with open('bot/ratelimit.py', 'r') as f:
            content = f.read()
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('telegram', stripped)

    def test_ratelimit_no_gemini_imports(self):
        """The module must not import the Gemini SDK."""
        with open('bot/ratelimit.py', 'r') as f:
            content = f.read()
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('gemini', stripped)
                self.assertNotIn('google-genai', stripped)

    def test_no_database_created_on_import(self):
        """Importing the module must not create any database."""
        import importlib
        import bot.ratelimit
        # data/ may legitimately exist from other tests; only assert that
        # importing did not CREATE it right now.
        before = os.path.exists('data')
        importlib.reload(bot.ratelimit)
        if not before:
            self.assertFalse(os.path.exists('data'),
                             "import must not create data/")


class TestPerUserCooldown(unittest.TestCase):
    """Test the in-memory per-user cooldown."""

    def test_first_message_allowed(self):
        bot_data = {}
        self.assertTrue(check_cooldown(bot_data, "user-1", cooldown_seconds=15))

    def test_second_message_within_window_rejected(self):
        bot_data = {}
        check_cooldown(bot_data, "user-1", cooldown_seconds=15, now=1000.0)
        self.assertFalse(check_cooldown(bot_data, "user-1",
                                        cooldown_seconds=15, now=1005.0))

    def test_message_after_window_allowed(self):
        bot_data = {}
        check_cooldown(bot_data, "user-1", cooldown_seconds=15, now=1000.0)
        self.assertTrue(check_cooldown(bot_data, "user-1",
                                       cooldown_seconds=15, now=1016.0))

    def test_different_users_independent(self):
        bot_data = {}
        self.assertTrue(check_cooldown(bot_data, "user-1", cooldown_seconds=15, now=1000.0))
        self.assertTrue(check_cooldown(bot_data, "user-2", cooldown_seconds=15, now=1000.5))

    def test_non_dict_bot_data_allows(self):
        """A missing/degraded context must never block a student."""
        self.assertTrue(check_cooldown(None, "user-1"))
        self.assertTrue(check_cooldown(object(), "user-1"))
        self.assertTrue(check_cooldown(Mock(), "user-1"))

    def test_zero_cooldown_disables_limit(self):
        bot_data = {}
        self.assertTrue(check_cooldown(bot_data, "user-1", cooldown_seconds=0, now=1.0))
        self.assertTrue(check_cooldown(bot_data, "user-1", cooldown_seconds=0, now=1.0))

    def test_cooldown_state_lives_in_bot_data(self):
        bot_data = {}
        check_cooldown(bot_data, "user-1", cooldown_seconds=15, now=1000.0)
        self.assertIn("user-1", bot_data[COOLDOWNS_KEY])

    def test_default_cooldown_seconds(self):
        with patch.dict('os.environ', {}, clear=False):
            os.environ.pop('COOLDOWN_SECONDS', None)
            self.assertEqual(get_cooldown_seconds(), DEFAULT_COOLDOWN_SECONDS)
            self.assertGreaterEqual(DEFAULT_COOLDOWN_SECONDS, 10)
            self.assertLessEqual(DEFAULT_COOLDOWN_SECONDS, 15)

    def test_cooldown_env_override(self):
        with patch.dict('os.environ', {'COOLDOWN_SECONDS': '12'}):
            self.assertEqual(get_cooldown_seconds(), 12.0)

    def test_cooldown_invalid_env_falls_back(self):
        with patch.dict('os.environ', {'COOLDOWN_SECONDS': 'banana'}):
            self.assertEqual(get_cooldown_seconds(), DEFAULT_COOLDOWN_SECONDS)
        with patch.dict('os.environ', {'COOLDOWN_SECONDS': '-5'}):
            self.assertEqual(get_cooldown_seconds(), DEFAULT_COOLDOWN_SECONDS)


class TestDailyCounter(unittest.TestCase):
    """Test the SQLite global daily counter (single-threaded behavior)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, 'shule.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_first_consume_creates_count(self):
        self.assertTrue(try_consume(limit=5, day='2099-01-01', db_path=self.db))
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), 1)

    def test_limit_enforced_exactly(self):
        limit = 5
        results = [try_consume(limit=limit, day='2099-01-01', db_path=self.db)
                   for _ in range(limit + 3)]
        self.assertEqual(results, [True] * limit + [False] * 3)
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), limit)

    def test_release_decrements_with_floor_zero(self):
        for _ in range(3):
            try_consume(limit=10, day='2099-01-01', db_path=self.db)
        release(day='2099-01-01', db_path=self.db)
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), 2)
        # Releasing more than consumed must never go below zero.
        for _ in range(5):
            release(day='2099-01-01', db_path=self.db)
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), 0)

    def test_days_are_independent(self):
        try_consume(limit=1, day='2099-01-01', db_path=self.db)
        self.assertTrue(try_consume(limit=1, day='2099-01-02', db_path=self.db))
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), 1)
        self.assertEqual(get_today_count(day='2099-01-02', db_path=self.db), 1)

    def test_default_daily_limit(self):
        os.environ.pop('DAILY_API_LIMIT', None)
        self.assertEqual(get_daily_limit(), DEFAULT_DAILY_API_LIMIT)

    def test_daily_limit_env_override(self):
        with patch.dict('os.environ', {'DAILY_API_LIMIT': '75'}):
            self.assertEqual(get_daily_limit(), 75)

    def test_daily_limit_invalid_env_falls_back(self):
        with patch.dict('os.environ', {'DAILY_API_LIMIT': 'many'}):
            self.assertEqual(get_daily_limit(), DEFAULT_DAILY_API_LIMIT)
        with patch.dict('os.environ', {'DAILY_API_LIMIT': '0'}):
            self.assertEqual(get_daily_limit(), DEFAULT_DAILY_API_LIMIT)

    def test_counter_database_unavailable_fails_closed(self):
        """A broken database must reject, never silently allow."""
        with patch('bot.ratelimit.get_database_path',
                   return_value='/nonexistent/dir/shule.db'):
            self.assertFalse(try_consume(limit=5, day='2099-01-01'))
            self.assertFalse(try_consume(limit=5, day='2099-01-01'))


class TestDailyCounterConcurrency(unittest.TestCase):
    """
    Regression tests for the flagged concurrency defect: the global daily
    counter's check-and-increment must be atomic, so concurrent requests
    can NEVER exceed the configured limit.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, 'shule.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _hammer(self, db_path, threads, per_thread, limit):
        allowed = []
        lock = threading.Lock()

        def worker():
            results = [try_consume(limit=limit, day='2099-01-01', db_path=db_path)
                       for _ in range(per_thread)]
            with lock:
                allowed.extend(results)

        workers = [threading.Thread(target=worker) for _ in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        return allowed

    def test_concurrent_requests_never_exceed_limit(self):
        for round_number in range(3):
            db = os.path.join(self.tmpdir, f'round{round_number}.db')
            allowed = self._hammer(db, threads=16, per_thread=25, limit=50)
            self.assertEqual(sum(allowed), 50,
                             f"round {round_number}: allowed {sum(allowed)} != 50")
            self.assertEqual(get_today_count(day='2099-01-01', db_path=db), 50)

    def test_concurrent_requests_limit_one(self):
        allowed = self._hammer(self.db, threads=8, per_thread=5, limit=1)
        self.assertEqual(sum(allowed), 1)
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), 1)

    def test_transaction_fallback_path_is_also_atomic(self):
        """The BEGIN IMMEDIATE fallback for old SQLite must be atomic too."""
        allowed = []
        lock = threading.Lock()

        def worker():
            results = []
            for _ in range(25):
                conn = _connect(self.db)
                try:
                    results.append(
                        _try_consume_with_transaction(conn, '2099-01-01', 50))
                finally:
                    conn.close()
            with lock:
                allowed.extend(results)

        workers = [threading.Thread(target=worker) for _ in range(16)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sum(allowed), 50)
        self.assertEqual(get_today_count(day='2099-01-01', db_path=self.db), 50)


class TestRateLimitingBotFlow(unittest.TestCase):
    """Rate limiting as wired into the Telegram text handler."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ratelimit_db = os.path.join(self.tmpdir, 'ratelimit.db')
        self.logger_db = os.path.join(self.tmpdir, 'logger.db')
        self.log_patcher = patch('logger.logger.get_database_path',
                                 return_value=self.logger_db)
        self.log_patcher.start()

    def tearDown(self):
        self.log_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _make_update(chat_id=12345678, text="What is a mixture?"):
        mock_message = Mock()
        mock_message.text = text
        mock_message.chat = Mock()
        mock_message.chat.id = chat_id
        mock_message.reply_text = AsyncMock()
        mock_update = Mock()
        mock_update.message = mock_message
        return mock_update, mock_message

    def _run(self, handler, update, bot_data=None):
        context = Mock()
        if bot_data is not None:
            context.bot_data = bot_data
        asyncio.run(handler(update, context))

    def test_cooldown_rejects_second_message_before_ai(self):
        """3 rapid messages: 1 answered, 2 cooldown notices, AI called once."""
        from bot.commands import handle_text_message
        from ai.ai_engine import EngineResult, STATUS_OK

        bot_data = {}
        with patch.dict('os.environ', {}, clear=False):
            os.environ.pop('TELEGRAM_ID_HASH_SALT', None)
            with patch('bot.commands.answer') as mock_answer:
                mock_answer.return_value = EngineResult(
                    reply_text="ok", status=STATUS_OK)
                for _ in range(3):
                    update, message = self._make_update(chat_id=42)
                    self._run(handle_text_message, update, bot_data)

                self.assertEqual(mock_answer.call_count, 1,
                                 "AI must be invoked exactly once")
                self.assertEqual(message.reply_text.call_count, 1)

    def test_cooldown_rejection_message_is_friendly(self):
        from bot.commands import handle_text_message, COOLDOWN_REPLY

        bot_data = {}
        os.environ.pop('TELEGRAM_ID_HASH_SALT', None)
        with patch('bot.commands.answer') as mock_answer:
            from ai.ai_engine import EngineResult, STATUS_OK
            mock_answer.return_value = EngineResult(reply_text="ok",
                                                    status=STATUS_OK)
            replies = []
            for _ in range(2):
                update, message = self._make_update(chat_id=99)
                self._run(handle_text_message, update, bot_data)
                replies.append(message.reply_text.call_args.args[0])
            self.assertEqual(replies[0], "ok")
            self.assertEqual(replies[1], COOLDOWN_REPLY)
            self.assertIn("seconds", replies[1].lower())

    def test_cooldown_allows_again_after_window(self):
        from bot.commands import handle_text_message

        bot_data = {}
        os.environ.pop('TELEGRAM_ID_HASH_SALT', None)
        with patch('bot.commands.answer') as mock_answer:
            from ai.ai_engine import EngineResult, STATUS_OK
            mock_answer.return_value = EngineResult(reply_text="ok",
                                                    status=STATUS_OK)
            self._run(handle_text_message, self._make_update(chat_id=7)[0], bot_data)
            self._run(handle_text_message, self._make_update(chat_id=7)[0], bot_data)
            self.assertEqual(mock_answer.call_count, 1)
            # Simulate the cooldown window having passed.
            bot_data[COOLDOWNS_KEY][7] -= 60
            self._run(handle_text_message, self._make_update(chat_id=7)[0], bot_data)
            self.assertEqual(mock_answer.call_count, 2)

    def test_daily_limit_rejects_before_ai_and_logs_rejection(self):
        """With DAILY_API_LIMIT=1: second message never reaches the AI."""
        from bot.commands import handle_text_message
        from ai.ai_engine import EngineResult, STATUS_OK
        from logger.logger import initialize_database

        env = {'TELEGRAM_ID_HASH_SALT': 'test_salt_step4',
               'DAILY_API_LIMIT': '1'}
        with patch.dict('os.environ', env):
            with patch('bot.ratelimit.get_database_path',
                       return_value=self.ratelimit_db):
                with patch('bot.commands.answer') as mock_answer:
                    mock_answer.side_effect = [
                        EngineResult(reply_text="first answer", status=STATUS_OK),
                        EngineResult(reply_text="second answer", status=STATUS_OK),
                    ]
                    update1, message1 = self._make_update(chat_id=11)
                    self._run(handle_text_message, update1, bot_data={})
                    update2, message2 = self._make_update(chat_id=12)
                    self._run(handle_text_message, update2, bot_data={})

                    # The second message must NOT have reached the AI.
                    self.assertEqual(mock_answer.call_count, 1)
                    self.assertEqual(message2.reply_text.call_args.args[0],
                                     "I've answered a lot of questions today and "
                                     "I need to rest. Please try again tomorrow!")
                    # ...and the rejection was logged for the weekly review.
                    initialize_database()
                    conn = sqlite3.connect(self.logger_db)
                    try:
                        row = conn.execute(
                            "SELECT status, error FROM exchanges ORDER BY id"
                        ).fetchall()[-1]
                    finally:
                        conn.close()
                    self.assertEqual(row[0], 'quota_exhausted')
                    self.assertIn('daily API limit reached', row[1])

    def test_engine_hard_error_releases_quota_reservation(self):
        """A failed AI call must not burn the day's quota."""
        from bot.commands import handle_text_message
        from ai.ai_engine import EngineResult, STATUS_OK, STATUS_ERROR

        env = {'TELEGRAM_ID_HASH_SALT': 'test_salt_step4',
               'DAILY_API_LIMIT': '1'}
        with patch.dict('os.environ', env):
            with patch('bot.ratelimit.get_database_path',
                       return_value=self.ratelimit_db):
                with patch('bot.commands.answer') as mock_answer:
                    mock_answer.side_effect = [
                        EngineResult(reply_text="I'm resting, try again in a few minutes",
                                     status=STATUS_ERROR, error="network down"),
                        EngineResult(reply_text="good answer", status=STATUS_OK),
                    ]
                    self._run(handle_text_message,
                              self._make_update(chat_id=21)[0], bot_data={})
                    self._run(handle_text_message,
                              self._make_update(chat_id=22)[0], bot_data={})
                    # The second call was allowed because the first
                    # reservation was released after the hard error.
                    self.assertEqual(mock_answer.call_count, 2)

    def test_counter_database_failure_fails_closed(self):
        """If the counter DB is broken, the AI call is rejected (fail-closed)."""
        from bot.commands import handle_text_message

        env = {'TELEGRAM_ID_HASH_SALT': 'test_salt_step4'}
        with patch.dict('os.environ', env):
            with patch('bot.ratelimit.get_database_path',
                       return_value='/nonexistent/dir/shule.db'):
                with patch('bot.commands.answer') as mock_answer:
                    from ai.ai_engine import EngineResult, STATUS_OK
                    mock_answer.return_value = EngineResult(
                        reply_text="should not happen", status=STATUS_OK)
                    update, message = self._make_update(chat_id=31)
                    self._run(handle_text_message, update, bot_data={})
                    mock_answer.assert_not_called()
                    self.assertIn("rest",
                                  message.reply_text.call_args.args[0].lower())

    def test_quota_exhausted_engine_result_keeps_reservation(self):
        """quota_exhausted from the engine keeps the slot (attempt was made)."""
        from bot.commands import handle_text_message
        from ai.ai_engine import EngineResult, STATUS_QUOTA_EXHAUSTED

        env = {'TELEGRAM_ID_HASH_SALT': 'test_salt_step4',
               'DAILY_API_LIMIT': '1'}
        with patch.dict('os.environ', env):
            with patch('bot.ratelimit.get_database_path',
                       return_value=self.ratelimit_db):
                with patch('bot.commands.answer') as mock_answer:
                    mock_answer.return_value = EngineResult(
                        reply_text="I'm resting, try again in a few minutes",
                        status=STATUS_QUOTA_EXHAUSTED, error="429")
                    self._run(handle_text_message,
                              self._make_update(chat_id=41)[0], bot_data={})
                    self.assertEqual(
                        get_today_count(db_path=self.ratelimit_db), 1,
                        "quota_exhausted must keep the reservation")


class TestStatusCommand(unittest.TestCase):
    """Patron-only /status command (architecture section 8)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, 'shule.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _make_update(chat_id):
        mock_message = Mock()
        mock_message.chat = Mock()
        mock_message.chat.id = chat_id
        mock_message.reply_text = AsyncMock()
        mock_update = Mock()
        mock_update.message = mock_message
        return mock_update, mock_message

    def _seed_database(self):
        from logger.logger import (initialize_database, nairobi_today,
                                   nairobi_day_bounds_utc)
        initialize_database()
        start, _ = nairobi_day_bounds_utc(nairobi_today())
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO exchanges (ts, chat_alias, user_text, snippet_ids, "
            "match_scores, model, latency_ms, status, error, reviewed, "
            "reviewer_note) VALUES (?, 'Student-07', 'q1', '[]', '[]', "
            "'gemini-2.5-flash', 100, 'ok', '', 0, NULL)", (start,))
        conn.execute(
            "INSERT INTO exchanges (ts, chat_alias, user_text, snippet_ids, "
            "match_scores, model, latency_ms, status, error, reviewed, "
            "reviewer_note) VALUES (?, 'Student-09', 'q2', '[]', '[]', "
            "'gemini-2.5-flash', 100, 'error', 'Gemini API call failed: boom', "
            "0, NULL)", (start,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS daily_counters ("
            "day TEXT PRIMARY KEY, count INTEGER NOT NULL)")
        from logger.logger import nairobi_today as today
        conn.execute("INSERT INTO daily_counters (day, count) VALUES (?, 2)",
                     (today(),))
        conn.commit()
        conn.close()

    def test_status_is_patron_only(self):
        from bot.commands import status_command
        with patch.dict('os.environ', {'PATRON_CHAT_IDS': '111'}):
            update, message = self._make_update(chat_id=999)
            asyncio.run(status_command(update, Mock()))
            text = message.reply_text.call_args.args[0]
            self.assertIn("patrons only", text.lower())

    def test_status_shows_patron_the_required_fields(self):
        from bot.commands import status_command
        env = {'PATRON_CHAT_IDS': '111'}
        with patch.dict('os.environ', env):
            with patch('logger.logger.get_database_path', return_value=self.db), \
                 patch('bot.ratelimit.get_database_path', return_value=self.db):
                self._seed_database()
                update, message = self._make_update(chat_id=111)
                asyncio.run(status_command(update, Mock()))
                text = message.reply_text.call_args.args[0]
                self.assertIn("Uptime:", text)
                self.assertIn("Today's exchanges (Nairobi): 2", text)
                self.assertIn("Daily API counter: 2/200", text)
                self.assertIn("Gemini API call failed: boom", text)
                # Only aliases — never a raw Telegram ID.
                self.assertNotIn("12345678", text)

    def test_status_works_on_fresh_database(self):
        from bot.commands import status_command
        fresh = os.path.join(self.tmpdir, 'fresh.db')
        env = {'PATRON_CHAT_IDS': '111'}
        with patch.dict('os.environ', env):
            with patch('logger.logger.get_database_path', return_value=fresh), \
                 patch('bot.ratelimit.get_database_path', return_value=fresh):
                update, message = self._make_update(chat_id=111)
                asyncio.run(status_command(update, Mock()))
                text = message.reply_text.call_args.args[0]
                self.assertIn("Today's exchanges (Nairobi): 0", text)
                self.assertIn("Last error: none", text)


class TestStatusRegisteredInBotCore(unittest.TestCase):
    """The /status handler must be registered in the application."""

    def test_status_command_imported_and_registered(self):
        """Runtime check: build the real application and inspect its
        handlers (a source grep missed a missing import once)."""
        from telegram.ext import CommandHandler
        from bot.bot_core import create_application
        env = {'TELEGRAM_BOT_TOKEN': '123456:test-token-format'}
        with patch.dict('os.environ', env):
            application = create_application()
        commands = sorted(
            command
            for handlers in application.handlers.values()
            for handler in handlers
            if isinstance(handler, CommandHandler)
            for command in handler.commands
        )
        self.assertEqual(commands, ['help', 'reload', 'start', 'status'])


class TestStep4EnvironmentDocumentation(unittest.TestCase):
    """Step 4 configuration must be documented in .env.example."""

    def test_env_example_documents_rate_limits(self):
        with open('.env.example', 'r') as f:
            content = f.read()
        self.assertIn('DAILY_API_LIMIT=', content)
        self.assertIn('COOLDOWN_SECONDS=', content)


def run_tests():
    """Run all Step 4 tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for test_class in (
        TestRateLimitModuleStructure,
        TestPerUserCooldown,
        TestDailyCounter,
        TestDailyCounterConcurrency,
        TestRateLimitingBotFlow,
        TestStatusCommand,
        TestStatusRegisteredInBotCore,
        TestStep4EnvironmentDocumentation,
    ):
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    run_tests()
