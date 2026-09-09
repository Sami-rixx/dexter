#!/usr/bin/env python3
"""
Tests for Dexter Bot - BUILD STEP 3

Comprehensive test suite for privacy-safe SQLite logging with security-focused tests.
All tests use mocks/temporary data - no real credentials required.

Security audit tests specifically cover:
- Missing TELEGRAM_ID_HASH_SALT raises ValueError (no fallback)
- Empty/invalid salt handling
- Privacy boundary: raw Telegram IDs never cross module boundaries
- AI response works without salt (logging skipped safely)
- No raw IDs in database, aliases, diagnostics, or exceptions
"""

import os
import json
import sqlite3
import unittest
import shutil
import tempfile
import hashlib
from unittest.mock import patch, AsyncMock, MagicMock, Mock
import asyncio
import importlib
import sys


class TestLoggerModuleStructure(unittest.TestCase):
    """Test logger module structure and imports."""
    
    def test_logger_module_imports(self):
        """Test that logger module imports successfully."""
        try:
            import logger.logger
            self.assertTrue(hasattr(logger.logger, 'Exchange'))
            self.assertTrue(hasattr(logger.logger, 'log_exchange'))
            self.assertTrue(hasattr(logger.logger, 'hash_telegram_id'))
            self.assertTrue(hasattr(logger.logger, 'generate_alias'))
            self.assertTrue(hasattr(logger.logger, 'get_telegram_id_alias'))
            self.assertTrue(hasattr(logger.logger, 'get_hash_salt'))
        except ImportError as e:
            self.fail(f"Failed to import logger.logger: {e}")
    
    def test_logger_no_telegram_imports(self):
        """Test that logger does not import Telegram modules."""
        with open('logger/logger.py', 'r') as f:
            content = f.read()
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('telegram', stripped)
                self.assertNotIn('python-telegram-bot', stripped)
    
    def test_logger_no_gemini_imports(self):
        """Test that logger does not import Gemini modules."""
        with open('logger/logger.py', 'r') as f:
            content = f.read()
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('gemini', stripped)
                self.assertNotIn('google-genai', stripped)
    
    def test_no_database_on_import(self):
        """Test that no database is created on module import."""
        # Clean up first
        if os.path.exists('data'):
            shutil.rmtree('data')
        
        # Import modules
        import logger.logger
        import bot.commands
        
        # data/ should not exist after import
        self.assertFalse(os.path.exists('data'), "data/ should not be created on import")


class TestSaltConfiguration(unittest.TestCase):
    """Test salt configuration security."""
    
    def setUp(self):
        """Set up test environment."""
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        # Reload logger module to ensure clean state
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
    
    def tearDown(self):
        """Restore original environment."""
        if self.original_salt is not None:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
    
    def test_missing_salt_raises_valueerror(self):
        """Test that missing TELEGRAM_ID_HASH_SALT raises ValueError with NO fallback."""
        from logger.logger import get_hash_salt
        
        # Ensure environment variable is not set
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        with self.assertRaises(ValueError) as context:
            get_hash_salt()
        
        error_msg = str(context.exception)
        self.assertIn('TELEGRAM_ID_HASH_SALT not configured', error_msg)
        # Confirm this is NOT a fallback value
        self.assertNotIn('development', error_msg.lower())
        self.assertNotIn('default', error_msg.lower())
        self.assertNotIn('fallback', error_msg.lower())
    
    def test_empty_salt_raises_valueerror(self):
        """Test that empty TELEGRAM_ID_HASH_SALT raises ValueError."""
        os.environ['TELEGRAM_ID_HASH_SALT'] = ''
        
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        
        from logger.logger import get_hash_salt
        
        with self.assertRaises(ValueError) as context:
            get_hash_salt()
        
        self.assertIn('TELEGRAM_ID_HASH_SALT not configured', str(context.exception))
    
    def test_whitespace_only_salt_raises_valueerror(self):
        """Test that whitespace-only TELEGRAM_ID_HASH_SALT raises ValueError."""
        os.environ['TELEGRAM_ID_HASH_SALT'] = '   '
        
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        
        from logger.logger import get_hash_salt
        
        with self.assertRaises(ValueError) as context:
            get_hash_salt()
        
        self.assertIn('TELEGRAM_ID_HASH_SALT not configured', str(context.exception))
    
    def test_valid_salt_returns_correctly(self):
        """Test that valid salt returns the configured value."""
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_secret_salt_123'
        
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        
        from logger.logger import get_hash_salt
        
        salt = get_hash_salt()
        self.assertEqual(salt, 'test_secret_salt_123')


class TestNoFallbackSalt(unittest.TestCase):
    """Test that NO fallback salt is ever used."""
    
    def setUp(self):
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
    
    def tearDown(self):
        if self.original_salt is not None:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
    
    def test_no_hardcoded_salt_in_logger(self):
        """Test that no hardcoded/default salt exists in logger code."""
        with open('logger/logger.py', 'r') as f:
            content = f.read()
        
        # Check for any hardcoded salt values
        self.assertNotIn('development_salt', content.lower())
        self.assertNotIn('default_salt', content.lower())
        self.assertNotIn('fallback_salt', content.lower())
        self.assertNotIn('dev_salt', content.lower())
        
        # Check that get_hash_salt only reads from environment
        self.assertIn('os.getenv("TELEGRAM_ID_HASH_SALT")', content)
        
        # Check that it raises ValueError when not configured
        self.assertIn('raise ValueError', content)
    
    def test_get_telegram_id_alias_requires_salt(self):
        """Test that get_telegram_id_alias requires configured salt."""
        from logger.logger import get_telegram_id_alias
        
        # Ensure no salt is configured
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        with self.assertRaises(ValueError):
            get_telegram_id_alias(12345678)


class TestSaltedHashing(unittest.TestCase):
    """Test salted SHA-256 hashing functionality."""
    
    def setUp(self):
        """Set up test environment with salt."""
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_salt_12345'
        
        import importlib
        import logger.logger
        importlib.reload(logger.logger)
    
    def tearDown(self):
        """Restore original environment."""
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        import importlib
        import logger.logger
        importlib.reload(logger.logger)
    
    def test_hash_deterministic(self):
        """Test that same chat ID produces same hash."""
        from logger.logger import hash_telegram_id
        chat_id = 12345678
        hash1 = hash_telegram_id(chat_id)
        hash2 = hash_telegram_id(chat_id)
        self.assertEqual(hash1, hash2)
    
    def test_hash_different_ids_different_hashes(self):
        """Test that different chat IDs produce different hashes."""
        from logger.logger import hash_telegram_id
        hash1 = hash_telegram_id(12345678)
        hash2 = hash_telegram_id(87654321)
        self.assertNotEqual(hash1, hash2)
    
    def test_hash_sha256_format(self):
        """Test that hash is valid SHA-256."""
        from logger.logger import hash_telegram_id
        hash_result = hash_telegram_id(12345678)
        self.assertEqual(len(hash_result), 64)
        try:
            int(hash_result, 16)
        except ValueError:
            self.fail("Hash is not valid hex")
    
    def test_raw_id_not_in_hash(self):
        """Test that raw chat ID does not appear in hash."""
        from logger.logger import hash_telegram_id
        chat_id = 12345678
        hash_result = hash_telegram_id(chat_id)
        self.assertNotIn(str(chat_id), hash_result)
    
    def test_salt_changes_hash(self):
        """Test that changing salt changes the hash for same chat ID."""
        from logger.logger import hash_telegram_id
        import importlib
        import logger.logger
        
        chat_id = 12345678
        
        # Hash with first salt
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'salt_1'
        importlib.reload(logger.logger)
        from logger.logger import hash_telegram_id as hash_func_1
        hash1 = hash_func_1(chat_id)
        
        # Hash with different salt
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'salt_2'
        importlib.reload(logger.logger)
        from logger.logger import hash_telegram_id as hash_func_2
        hash2 = hash_func_2(chat_id)
        
        # Hashes should be different
        self.assertNotEqual(hash1, hash2)
        
        # Restore
        importlib.reload(logger.logger)
    
    def test_manual_hash_verification(self):
        """Test that hash matches manual SHA-256 computation."""
        from logger.logger import hash_telegram_id
        
        chat_id = 12345678
        salt = 'test_salt_12345'
        
        # Manual computation
        salted_input = f"{chat_id}{salt}"
        expected_hash = hashlib.sha256(salted_input.encode('utf-8')).hexdigest()
        
        # Function computation
        actual_hash = hash_telegram_id(chat_id)
        
        self.assertEqual(actual_hash, expected_hash)


class TestAliasGeneration(unittest.TestCase):
    """Test alias generation."""
    
    def setUp(self):
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_salt_12345'
        import importlib, logger.logger
        importlib.reload(logger.logger)
    
    def tearDown(self):
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        import importlib, logger.logger
        importlib.reload(logger.logger)
    
    def test_alias_format(self):
        """Test alias format is Student-NN."""
        from logger.logger import hash_telegram_id, generate_alias
        chat_id_hash = hash_telegram_id(12345678)
        alias = generate_alias(chat_id_hash)
        self.assertTrue(alias.startswith('Student-'))
        suffix = alias[8:]
        self.assertTrue(suffix.isdigit())
        self.assertTrue(0 <= int(suffix) <= 99)
    
    def test_alias_deterministic(self):
        """Test same hash produces same alias."""
        from logger.logger import generate_alias
        alias1 = generate_alias('a' * 64)
        alias2 = generate_alias('a' * 64)
        self.assertEqual(alias1, alias2)
    
    def test_alias_contains_no_raw_id(self):
        """Test alias contains no raw Telegram ID."""
        from logger.logger import get_telegram_id_alias
        raw_chat_id = 12345678
        _, alias = get_telegram_id_alias(raw_chat_id)
        self.assertNotIn(str(raw_chat_id), alias)


class TestBoundaryPrivacy(unittest.TestCase):
    """Test privacy boundary - raw Telegram IDs never cross into logger/ai/ modules."""
    
    def setUp(self):
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_salt_12345'
        import importlib, logger.logger
        importlib.reload(logger.logger)
    
    def tearDown(self):
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        import importlib, logger.logger
        importlib.reload(logger.logger)
    
    def test_get_telegram_id_alias_no_raw_id(self):
        """Test get_telegram_id_alias doesn't return raw ID."""
        from logger.logger import get_telegram_id_alias
        raw_chat_id = 12345678
        result_hash, result_alias = get_telegram_id_alias(raw_chat_id)
        self.assertNotEqual(result_hash, str(raw_chat_id))
        self.assertNotEqual(result_alias, str(raw_chat_id))
    
    def test_hash_is_salted_sha256(self):
        """Test that hash uses salted SHA-256 as specified in architecture."""
        from logger.logger import hash_telegram_id
        
        chat_id = 12345678
        hash_result = hash_telegram_id(chat_id)
        
        # Should be SHA-256 hex string
        self.assertEqual(len(hash_result), 64)
        
        # Verify it's actually SHA-256 with salt
        salt = os.environ['TELEGRAM_ID_HASH_SALT']
        expected = hashlib.sha256(f"{chat_id}{salt}".encode()).hexdigest()
        self.assertEqual(hash_result, expected)


class TestMissingSaltBehavior(unittest.TestCase):
    """Test behavior when salt is missing/unavailable."""
    
    def setUp(self):
        """Ensure no salt is configured."""
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        # Clean up any existing data directory
        if os.path.exists('data'):
            shutil.rmtree('data')
        
        # Reload modules
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
    
    def tearDown(self):
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        # Clean up data directory
        if os.path.exists('data'):
            shutil.rmtree('data')
        
        # Reload modules
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
    
    def test_get_telegram_id_alias_fails_without_salt(self):
        """Test get_telegram_id_alias raises ValueError without salt."""
        from logger.logger import get_telegram_id_alias
        
        with self.assertRaises(ValueError) as context:
            get_telegram_id_alias(12345678)
        
        self.assertIn('TELEGRAM_ID_HASH_SALT not configured', str(context.exception))
    
    def test_bot_continues_without_salt(self):
        """Test that bot continues processing AI responses when salt is missing."""
        from ai.ai_engine import EngineResult, STATUS_OK
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio
        
        # Ensure no salt is configured
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        # Reload bot.commands to pick up the missing salt
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
        
        # Create mock update
        mock_message = Mock()
        mock_message.text = "What is the capital of Kenya?"
        mock_message.chat.id = 12345678
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        # Mock the AI answer to avoid real API calls
        mock_result = EngineResult(
            reply_text="Nairobi is the capital of Kenya",
            status=STATUS_OK
        )
        
        with patch('bot.commands.answer') as mock_answer:
            mock_answer.return_value = mock_result
            
            from bot.commands import handle_text_message
            
            # This should NOT raise an exception - bot should continue
            asyncio.run(handle_text_message(mock_update, Mock()))
            
            # Verify AI was called
            mock_answer.assert_called_once()
            
            # Verify reply was sent to user
            mock_message.reply_text.assert_called_once_with("Nairobi is the capital of Kenya")
    
    def test_no_database_created_without_salt(self):
        """Test that no database is created when salt is missing and logging is skipped."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio
        
        # Ensure no salt
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        # Clean data directory
        if os.path.exists('data'):
            shutil.rmtree('data')
        
        # Reload modules
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        
        # Mock update
        mock_message = Mock()
        mock_message.text = "Test message"
        mock_message.chat.id = 12345678
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        from ai.ai_engine import EngineResult, STATUS_OK
        mock_result = EngineResult(reply_text="Test reply", status=STATUS_OK)
        
        with patch('bot.commands.answer') as mock_answer:
            mock_answer.return_value = mock_result
            
            from bot.commands import handle_text_message
            
            asyncio.run(handle_text_message(mock_update, Mock()))
            
            # Verify no database was created
            self.assertFalse(os.path.exists('data'), "No data directory should be created without salt")
            self.assertFalse(os.path.exists('data/shule.db'), "No database should be created without salt")
    
    def test_raw_id_not_exposed_in_missing_salt_path(self):
        """Test that raw Telegram ID is not exposed when salt is missing."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio
        import io
        import sys
        
        # Ensure no salt
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        # Capture stderr
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        
        # Reload modules
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        
        test_chat_id = 12345678
        
        try:
            # Mock update
            mock_message = Mock()
            mock_message.text = "Test message"
            mock_message.chat.id = test_chat_id
            mock_message.reply_text = AsyncMock()
            
            mock_update = Mock()
            mock_update.message = mock_message
            
            from ai.ai_engine import EngineResult, STATUS_OK
            mock_result = EngineResult(reply_text="Test reply", status=STATUS_OK)
            
            with patch('bot.commands.answer') as mock_answer:
                mock_answer.return_value = mock_result
                
                from bot.commands import handle_text_message
                
                asyncio.run(handle_text_message(mock_update, Mock()))
                
                # Get stderr output
                stderr_output = sys.stderr.getvalue()
                
                # Verify raw chat ID is NOT in stderr
                self.assertNotIn(str(test_chat_id), stderr_output)
                
        finally:
            sys.stderr = old_stderr


class TestAIReceivesGenericAlias(unittest.TestCase):
    """Test that AI engine receives generic 'Student' alias regardless of logging config."""
    
    def setUp(self):
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
    
    def tearDown(self):
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        if 'logger.logger' in sys.modules:
            importlib.reload(sys.modules['logger.logger'])
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
    
    def test_ai_always_receives_student_alias_with_salt(self):
        """Test AI receives 'Student' alias when salt is configured."""
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_salt_12345'
        
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
        
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio
        
        mock_message = Mock()
        mock_message.text = "Test question"
        mock_message.chat.id = 12345678
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        from ai.ai_engine import EngineResult, STATUS_OK
        mock_result = EngineResult(reply_text="Test reply", status=STATUS_OK)
        
        with patch('bot.commands.answer') as mock_answer:
            mock_answer.return_value = mock_result
            
            from bot.commands import handle_text_message
            
            asyncio.run(handle_text_message(mock_update, Mock()))
            
            # Check that answer was called with ai_alias="Student"
            mock_answer.assert_called_once()
            call_kwargs = mock_answer.call_args[1]
            self.assertEqual(call_kwargs['alias'], 'Student')
    
    def test_ai_always_receives_student_alias_without_salt(self):
        """Test AI receives 'Student' alias even when salt is NOT configured."""
        # Ensure no salt
        if 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        if 'bot.commands' in sys.modules:
            importlib.reload(sys.modules['bot.commands'])
        
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio
        
        mock_message = Mock()
        mock_message.text = "Test question"
        mock_message.chat.id = 12345678
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        from ai.ai_engine import EngineResult, STATUS_OK
        mock_result = EngineResult(reply_text="Test reply", status=STATUS_OK)
        
        with patch('bot.commands.answer') as mock_answer:
            mock_answer.return_value = mock_result
            
            from bot.commands import handle_text_message
            
            asyncio.run(handle_text_message(mock_update, Mock()))
            
            # Check that answer was called with ai_alias="Student"
            mock_answer.assert_called_once()
            call_kwargs = mock_answer.call_args[1]
            self.assertEqual(call_kwargs['alias'], 'Student')
            
            # Importantly, it should NOT be the chat ID
            self.assertNotEqual(call_kwargs['alias'], '12345678')
            self.assertNotEqual(call_kwargs['alias'], 12345678)


class TestExchangeDataclass(unittest.TestCase):
    """Test Exchange dataclass."""
    
    def test_exchange_fields(self):
        """Test Exchange has all required fields."""
        from logger.logger import Exchange
        exchange = Exchange(chat_alias='Student-01', user_text='Test')
        for field in ['chat_alias', 'user_text', 'snippet_ids', 'match_scores', 
                     'model', 'latency_ms', 'status', 'error', 'reviewed', 'reviewer_note']:
            self.assertTrue(hasattr(exchange, field), f"Missing field: {field}")
    
    def test_exchange_defaults(self):
        """Test Exchange defaults."""
        from logger.logger import Exchange
        exchange = Exchange(chat_alias='Student-01', user_text='Test')
        self.assertEqual(exchange.snippet_ids, [])
        self.assertEqual(exchange.match_scores, [])
        self.assertEqual(exchange.model, "")
        self.assertEqual(exchange.latency_ms, 0)
        self.assertEqual(exchange.status, "")
        self.assertEqual(exchange.error, "")
        self.assertEqual(exchange.reviewed, 0)
        self.assertIsNone(exchange.reviewer_note)


class TestDatabasePrivacy(unittest.TestCase):
    """Test that no raw Telegram IDs appear in database."""
    
    def setUp(self):
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_db_salt_xyz'
        
        import importlib, logger.logger
        importlib.reload(logger.logger)
        
        # Create a temporary database for testing
        self.temp_db_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.temp_db_dir, 'test_shule.db')
        
        # Patch database path
        self.db_patcher = patch('logger.logger.get_database_path')
        self.mock_db_path = self.db_patcher.start()
        self.mock_db_path.return_value = self.temp_db_path
        
        # Initialize database
        from logger.logger import initialize_database
        initialize_database()
    
    def tearDown(self):
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        
        # Clean up temporary database
        if os.path.exists(self.temp_db_dir):
            shutil.rmtree(self.temp_db_dir)
        
        self.db_patcher.stop()
        
        import importlib, logger.logger
        importlib.reload(logger.logger)
    
    def test_database_schema_created(self):
        """Test that database schema is created correctly."""
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()
        
        # Check users table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        self.assertIsNotNone(cursor.fetchone())
        
        # Check exchanges table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exchanges'")
        self.assertIsNotNone(cursor.fetchone())
        
        # Check users table has telegram_id_hash column (not raw chat_id)
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        self.assertIn('telegram_id_hash', columns)
        self.assertNotIn('telegram_chat_id', columns)
        self.assertNotIn('chat_id', columns)
        
        # Check exchanges table has chat_alias column
        cursor.execute("PRAGMA table_info(exchanges)")
        columns = [row[1] for row in cursor.fetchall()]
        self.assertIn('chat_alias', columns)
        self.assertNotIn('telegram_chat_id', columns)
        self.assertNotIn('chat_id', columns)
        
        conn.close()
    
    def test_user_insertion_stores_hash_not_raw_id(self):
        """Test that user insertion stores hash, not raw ID."""
        from logger.logger import hash_telegram_id, get_or_create_user
        
        raw_chat_id = 999888777
        
        # Hash the ID
        chat_id_hash = hash_telegram_id(raw_chat_id)
        
        # Insert user
        hash_result, alias = get_or_create_user(chat_id_hash)
        
        # Verify in database
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT telegram_id_hash, alias FROM users WHERE telegram_id_hash = ?",
                      (chat_id_hash,))
        row = cursor.fetchone()
        
        self.assertIsNotNone(row)
        db_hash, db_alias = row
        
        # Verify hash is stored
        self.assertEqual(db_hash, chat_id_hash)
        
        # Verify raw ID is NOT stored
        self.assertNotEqual(db_hash, str(raw_chat_id))
        self.assertNotEqual(db_alias, str(raw_chat_id))
        
        # Verify alias format
        self.assertTrue(db_alias.startswith('Student-'))
        
        conn.close()
    
    def test_exchange_insertion_no_raw_id(self):
        """Test that exchange insertion contains no raw Telegram ID."""
        from logger.logger import Exchange, log_exchange
        
        raw_chat_id = 555666777
        
        # Create exchange with alias (not raw ID)
        exchange = Exchange(
            chat_alias='Student-01',
            user_text='Test question',
            snippet_ids=[],
            match_scores=[],
            model='gemini-2.5-flash',
            latency_ms=100,
            status='ok',
            error='',
            reviewed=0,
            reviewer_note=None
        )
        
        # Log exchange
        log_exchange(exchange)
        
        # Verify in database
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT chat_alias, user_text FROM exchanges WHERE user_text = ?",
                      ('Test question',))
        row = cursor.fetchone()
        
        self.assertIsNotNone(row)
        db_alias, db_text = row
        
        # Verify no raw ID in any field
        self.assertNotEqual(db_alias, str(raw_chat_id))
        self.assertNotIn(str(raw_chat_id), db_alias)
        self.assertNotIn(str(raw_chat_id), db_text)
        
        # Verify alias format
        self.assertTrue(db_alias.startswith('Student-'))
        
        conn.close()
    
    def test_parameterized_queries_prevent_injection(self):
        """Test that parameterized queries are used to prevent SQL injection."""
        from logger.logger import Exchange, log_exchange
        
        # Try to inject SQL via user text
        malicious_text = "'; DROP TABLE users; --"
        
        exchange = Exchange(
            chat_alias='Student-01',
            user_text=malicious_text,
            snippet_ids=[],
            match_scores=[],
            model='test',
            latency_ms=1,
            status='ok',
            error='',
            reviewed=0,
            reviewer_note=None
        )
        
        # This should not raise an exception or cause injection
        try:
            log_exchange(exchange)
            
            # Verify database is still intact
            conn = sqlite3.connect(self.temp_db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            self.assertIn('users', tables)
            self.assertIn('exchanges', tables)
            
            conn.close()
        except Exception as e:
            self.fail(f"SQL injection test failed: {e}")


class TestLoggerReliability(unittest.TestCase):
    """Test logger reliability - never crashes bot."""
    
    def setUp(self):
        self.original_salt = os.environ.get('TELEGRAM_ID_HASH_SALT')
        os.environ['TELEGRAM_ID_HASH_SALT'] = 'test_salt_12345'
        import importlib, logger.logger
        importlib.reload(logger.logger)
        
        # Clean up data directory
        if os.path.exists('data'):
            shutil.rmtree('data')
    
    def tearDown(self):
        if self.original_salt:
            os.environ['TELEGRAM_ID_HASH_SALT'] = self.original_salt
        elif 'TELEGRAM_ID_HASH_SALT' in os.environ:
            del os.environ['TELEGRAM_ID_HASH_SALT']
        import importlib, logger.logger
        importlib.reload(logger.logger)
        
        if os.path.exists('data'):
            shutil.rmtree('data')
    
    def test_log_exchange_never_raises(self):
        """Test that log_exchange never raises exceptions."""
        from logger.logger import Exchange, log_exchange
        
        exchange = Exchange(
            chat_alias='Student-01',
            user_text='Test'
        )
        
        try:
            log_exchange(exchange)
            self.assertTrue(True)  # If we get here, no exception was raised
        except Exception as e:
            self.fail(f"log_exchange raised exception: {e}")
    
    def test_database_failure_swallowed(self):
        """Test that database failures are swallowed and logged to stderr."""
        from logger.logger import Exchange, log_exchange
        import logging
        import io
        import sys
        
        # Create a temporary bad database path
        bad_db_path = '/nonexistent/path/shule.db'
        
        # Configure logger to write to a string buffer
        log_buffer = io.StringIO()
        handler = logging.StreamHandler(log_buffer)
        handler.setLevel(logging.ERROR)
        logger_logger = logging.getLogger('logger.logger')
        logger_logger.addHandler(handler)
        logger_logger.setLevel(logging.ERROR)
        
        # Patch to use bad path
        with patch('logger.logger.get_database_path') as mock_path:
            mock_path.return_value = bad_db_path
            
            try:
                exchange = Exchange(chat_alias='Student-01', user_text='Test')
                log_exchange(exchange)  # Should not raise
                
                # Should have logged error to the buffer
                log_output = log_buffer.getvalue()
                self.assertIn('Logger failed to write exchange', log_output)
                
            finally:
                logger_logger.removeHandler(handler)
    
    def test_ai_response_independent_of_logging(self):
        """Test that AI response is sent even if logging fails."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import asyncio
        
        # Patch logger to always fail
        with patch('bot.commands.log_exchange') as mock_log:
            mock_log.side_effect = Exception("Database error")
            
            mock_message = Mock()
            mock_message.text = "Test question"
            mock_message.chat.id = 12345678
            mock_message.reply_text = AsyncMock()
            
            mock_update = Mock()
            mock_update.message = mock_message
            
            from ai.ai_engine import EngineResult, STATUS_OK
            mock_result = EngineResult(reply_text="Test reply", status=STATUS_OK)
            
            with patch('bot.commands.answer') as mock_answer:
                mock_answer.return_value = mock_result
                
                from bot.commands import handle_text_message
                
                # Should not raise
                asyncio.run(handle_text_message(mock_update, Mock()))
                
                # AI should have been called
                mock_answer.assert_called_once()
                
                # Reply should have been sent
                mock_message.reply_text.assert_called_once_with("Test reply")
                
                # Logging should have been attempted
                mock_log.assert_called_once()


class TestBotIntegration(unittest.TestCase):
    """Test bot integration."""
    
    def test_bot_uses_get_telegram_id_alias(self):
        """Test bot uses get_telegram_id_alias."""
        import inspect
        from bot.commands import handle_text_message
        source = inspect.getsource(handle_text_message)
        self.assertIn('get_telegram_id_alias', source)
    
    def test_ai_receives_generic_alias(self):
        """Test AI receives generic 'Student' alias."""
        import inspect
        from bot.commands import handle_text_message
        source = inspect.getsource(handle_text_message)
        self.assertIn('ai_alias = "Student"', source)
    
    def test_logging_uses_db_alias(self):
        """Test logging uses db_alias."""
        import inspect
        from bot.commands import handle_text_message
        source = inspect.getsource(handle_text_message)
        self.assertIn('db_alias', source)
    
    def test_response_before_logging(self):
        """Test response sent before logging."""
        import inspect
        from bot.commands import handle_text_message
        source = inspect.getsource(handle_text_message)
        reply_pos = source.find('await message.reply_text(result.reply_text)')
        log_pos = source.find('log_exchange')
        self.assertLess(reply_pos, log_pos, "Reply should come before logging")


class TestEnvironmentVariables(unittest.TestCase):
    """Test environment variables."""
    
    def test_env_example_has_salt(self):
        """Test .env.example has hash salt."""
        with open('.env.example', 'r') as f:
            content = f.read()
        self.assertIn('TELEGRAM_ID_HASH_SALT=', content)
    
    def test_env_example_has_salt_instruction(self):
        """Test .env.example has instruction for generating salt."""
        with open('.env.example', 'r') as f:
            content = f.read()
        self.assertIn('secrets.token_hex', content)


class TestFileStructure(unittest.TestCase):
    """Test file structure."""
    
    def test_logger_files_exist(self):
        """Test logger files exist."""
        self.assertTrue(os.path.exists('logger/__init__.py'))
        self.assertTrue(os.path.exists('logger/logger.py'))
    
    def test_data_gitignored(self):
        """Test data/ is gitignored."""
        with open('.gitignore', 'r') as f:
            content = f.read()
        self.assertIn('data/', content)
    
    def test_env_gitignored(self):
        """Test .env is gitignored."""
        with open('.gitignore', 'r') as f:
            content = f.read()
        self.assertIn('.env', content)


class TestNonTextBehaviorPreserved(unittest.TestCase):
    """Test that non-text behavior from Step 1 is preserved."""
    
    def test_non_text_message_response(self):
        """Test non-text message handling."""
        from unittest.mock import AsyncMock, MagicMock
        import asyncio
        
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        from bot.commands import handle_non_text_message
        
        asyncio.run(handle_non_text_message(mock_update, Mock()))
        
        mock_message.reply_text.assert_called_once_with("Text only for now — type your question.")


class TestCommandsModuleIsolation(unittest.TestCase):
    """Test commands module isolation."""
    
    def test_commands_no_gemini_imports(self):
        """Test that commands.py doesn't import Gemini SDK."""
        with open('bot/commands.py', 'r') as f:
            content = f.read()
        
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('gemini', stripped)
                self.assertNotIn('google-genai', stripped)
    
    def test_commands_only_public_interfaces(self):
        """Test that commands.py only imports public interfaces."""
        import inspect
        from bot import commands
        
        # Check imports
        source = inspect.getsource(commands)
        
        # Should import from ai.ai_engine
        self.assertIn('from ai.ai_engine import answer, reload_persona', source)
        
        # Should import from logger.logger
        self.assertIn('from logger.logger import get_telegram_id_alias, Exchange, log_exchange', source)
        
        # Should NOT import gemini_client
        self.assertNotIn('gemini_client', source)
        
        # Should NOT import retriever
        self.assertNotIn('retriever', source)


def run_tests():
    """Run all Step 3 tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestLoggerModuleStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestSaltConfiguration))
    suite.addTests(loader.loadTestsFromTestCase(TestNoFallbackSalt))
    suite.addTests(loader.loadTestsFromTestCase(TestSaltedHashing))
    suite.addTests(loader.loadTestsFromTestCase(TestAliasGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestBoundaryPrivacy))
    suite.addTests(loader.loadTestsFromTestCase(TestMissingSaltBehavior))
    suite.addTests(loader.loadTestsFromTestCase(TestAIReceivesGenericAlias))
    suite.addTests(loader.loadTestsFromTestCase(TestExchangeDataclass))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabasePrivacy))
    suite.addTests(loader.loadTestsFromTestCase(TestLoggerReliability))
    suite.addTests(loader.loadTestsFromTestCase(TestBotIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestEnvironmentVariables))
    suite.addTests(loader.loadTestsFromTestCase(TestFileStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestNonTextBehaviorPreserved))
    suite.addTests(loader.loadTestsFromTestCase(TestCommandsModuleIsolation))
    
    runner = unittest.TextTestRunner(verbosity=2)
    results = runner.run(suite)
    return results


if __name__ == '__main__':
    run_tests()