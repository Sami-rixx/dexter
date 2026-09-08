#!/usr/bin/env python3
"""
Tests for Dexter Bot Core - Step 1

These tests verify the bot core logic without requiring:
- Real Telegram bot token
- Live Telegram network access
- Any external dependencies beyond the bot module itself
"""

import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio

# Test the bot core module functions
class TestBotCoreFunctions(unittest.TestCase):
    """Test bot core functions that don't require Telegram connectivity."""
    
    def test_get_bot_token_from_environment(self):
        """Test that get_bot_token reads from environment."""
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'test_token_123'}):
            from bot.bot_core import get_bot_token
            token = get_bot_token()
            self.assertEqual(token, 'test_token_123')
    
    def test_get_bot_token_missing_raises_error(self):
        """Test that get_bot_token raises ValueError when token is missing."""
        with patch.dict('os.environ', {}, clear=True):
            from bot.bot_core import get_bot_token
            with self.assertRaises(ValueError) as context:
                get_bot_token()
            self.assertIn('TELEGRAM_BOT_TOKEN not found', str(context.exception))
    
    def test_get_bot_token_empty_string_raises_error(self):
        """Test that get_bot_token raises ValueError when token is empty."""
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': ''}):
            from bot.bot_core import get_bot_token
            with self.assertRaises(ValueError):
                get_bot_token()


class TestBotCoreImports(unittest.TestCase):
    """Test that bot core imports correctly and follows isolation rules."""
    
    def test_bot_core_imports_successfully(self):
        """Test that bot_core.py can be imported without errors."""
        try:
            import bot.bot_core
            self.assertTrue(hasattr(bot.bot_core, 'run_bot'))
            self.assertTrue(hasattr(bot.bot_core, 'create_application'))
            self.assertTrue(hasattr(bot.bot_core, 'handle_text_message'))
        except ImportError as e:
            self.fail(f"Failed to import bot.bot_core: {e}")
    
    def test_bot_module_structure(self):
        """Test that bot module has expected structure."""
        import bot
        import bot.bot_core
        # Should have __init__.py and bot_core.py
        self.assertTrue(hasattr(bot, '__file__'))
        self.assertTrue(hasattr(bot.bot_core, '__file__'))


class TestEnvironmentFile(unittest.TestCase):
    """Test environment configuration files."""
    
    def test_env_example_exists(self):
        """Test that .env.example file exists."""
        self.assertTrue(os.path.exists('.env.example'))
    
    def test_env_example_content(self):
        """Test that .env.example contains required placeholder."""
        with open('.env.example', 'r') as f:
            content = f.read()
        self.assertIn('TELEGRAM_BOT_TOKEN=', content)
        self.assertIn('your_telegram_bot_token_here', content)
    
    def test_requirements_txt_exists(self):
        """Test that requirements.txt exists."""
        self.assertTrue(os.path.exists('requirements.txt'))
    
    def test_requirements_txt_content(self):
        """Test that requirements.txt contains python-telegram-bot."""
        with open('requirements.txt', 'r') as f:
            content = f.read()
        self.assertIn('python-telegram-bot', content)


class TestGitIgnore(unittest.TestCase):
    """Test .gitignore configuration."""
    
    def test_gitignore_exists(self):
        """Test that .gitignore exists."""
        self.assertTrue(os.path.exists('.gitignore'))
    
    def test_gitignore_blocks_env(self):
        """Test that .gitignore blocks .env files."""
        with open('.gitignore', 'r') as f:
            content = f.read()
        self.assertIn('.env', content)
    
    def test_gitignore_blocks_data(self):
        """Test that .gitignore blocks data directory."""
        with open('.gitignore', 'r') as f:
            content = f.read()
        self.assertIn('data/', content)
    
    def test_gitignore_blocks_pycache(self):
        """Test that .gitignore blocks __pycache__."""
        with open('.gitignore', 'r') as f:
            content = f.read()
        self.assertIn('__pycache__/', content)


class TestBotCoreIsolation(unittest.TestCase):
    """Test that bot core maintains proper module isolation."""
    
    def test_bot_core_no_gemini_imports(self):
        """Test that bot_core.py doesn't import Gemini modules."""
        with open('bot/bot_core.py', 'r') as f:
            content = f.read()
        
        # Check for explicit import statements only
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('gemini', stripped)
                self.assertNotIn('google.genai', stripped)
                self.assertNotIn('google-genai', stripped)
    
    def test_bot_core_no_ai_imports(self):
        """Test that bot_core.py doesn't import ai/ modules."""
        with open('bot/bot_core.py', 'r') as f:
            content = f.read()
        
        # Check for ai module import statements only
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('ai.', stripped)
                self.assertNotIn(' from ai', stripped)
    
    def test_bot_core_no_logger_imports(self):
        """Test that bot_core.py doesn't import logger/ modules."""
        with open('bot/bot_core.py', 'r') as f:
            content = f.read()
        
        # Check for logger module import statements only
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('logger.', stripped)
                self.assertNotIn(' from logger', stripped)
    
    def test_bot_core_no_retriever_imports(self):
        """Test that bot_core.py doesn't import retriever modules."""
        with open('bot/bot_core.py', 'r') as f:
            content = f.read()
        
        # Check for retriever module imports (look for import statements, not comments)
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('retriever', stripped)
        # Also check that no line imports from retriever
        self.assertNotIn('from retriever', content.lower())
        self.assertNotIn('import retriever', content.lower())


class TestReadmeCompleteness(unittest.TestCase):
    """Test that README.md contains required information."""
    
    def test_readme_exists(self):
        """Test that README.md exists."""
        self.assertTrue(os.path.exists('README.md'))
    
    def test_readme_has_step_1_info(self):
        """Test that README.md mentions Step 1."""
        with open('README.md', 'r') as f:
            content = f.read()
        self.assertIn('BUILD STEP 1', content)
    
    def test_readme_has_usage_instructions(self):
        """Test that README.md has usage instructions."""
        with open('README.md', 'r') as f:
            content = f.read()
        self.assertIn('python bot/bot_core.py', content)
        self.assertIn('TELEGRAM_BOT_TOKEN', content)


def run_tests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBotCoreFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestBotCoreImports))
    suite.addTests(loader.loadTestsFromTestCase(TestEnvironmentFile))
    suite.addTests(loader.loadTestsFromTestCase(TestGitIgnore))
    suite.addTests(loader.loadTestsFromTestCase(TestBotCoreIsolation))
    suite.addTests(loader.loadTestsFromTestCase(TestReadmeCompleteness))
    
    runner = unittest.TextTestRunner(verbosity=2)
    results = runner.run(suite)
    return results


if __name__ == '__main__':
    run_tests()