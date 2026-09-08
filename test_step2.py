#!/usr/bin/env python3
"""
Tests for Dexter Bot - BUILD STEP 2

These tests verify Step 2 functionality:
- AI engine integration
- EngineResult contract
- Persona loading and reload
- Bot to AI integration
- /reload command behavior
- Module isolation

All tests use mocking to avoid requiring real API keys or network access.
"""

import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, Mock
import asyncio


class TestAIEngineResultContract(unittest.TestCase):
    """Test EngineResult dataclass contract per architecture."""
    
    def test_engine_result_contract_fields(self):
        """Test that EngineResult has all required fields."""
        from ai.ai_engine import EngineResult, STATUS_OK, STATUS_ERROR, STATUS_QUOTA_EXHAUSTED
        
        # Create an EngineResult instance
        result = EngineResult(
            reply_text="test reply",
            snippet_ids=[],
            match_scores=[],
            model="test-model",
            latency_ms=100,
            status=STATUS_OK,
            error=""
        )
        
        # Verify all required fields exist
        self.assertTrue(hasattr(result, 'reply_text'))
        self.assertTrue(hasattr(result, 'snippet_ids'))
        self.assertTrue(hasattr(result, 'match_scores'))
        self.assertTrue(hasattr(result, 'model'))
        self.assertTrue(hasattr(result, 'latency_ms'))
        self.assertTrue(hasattr(result, 'status'))
        self.assertTrue(hasattr(result, 'error'))
    
    def test_status_constants(self):
        """Test that status constants are defined."""
        from ai.ai_engine import STATUS_OK, STATUS_ERROR, STATUS_QUOTA_EXHAUSTED
        
        self.assertEqual(STATUS_OK, "ok")
        self.assertEqual(STATUS_ERROR, "error")
        self.assertEqual(STATUS_QUOTA_EXHAUSTED, "quota_exhausted")
    
    def test_engine_result_values(self):
        """Test EngineResult field values."""
        from ai.ai_engine import EngineResult, STATUS_OK
        
        result = EngineResult(
            reply_text="Hello, I am Dexter",
            snippet_ids=["test1.md"],
            match_scores=[0.95],
            model="gemini-2.5-flash",
            latency_ms=250,
            status=STATUS_OK,
            error=""
        )
        
        self.assertEqual(result.reply_text, "Hello, I am Dexter")
        self.assertEqual(result.snippet_ids, ["test1.md"])
        self.assertEqual(result.match_scores, [0.95])
        self.assertEqual(result.model, "gemini-2.5-flash")
        self.assertEqual(result.latency_ms, 250)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.error, "")


class TestAIModuleIsolation(unittest.TestCase):
    """Test AI module isolation constraints."""
    
    def test_ai_engine_no_telegram_imports(self):
        """Test that ai_engine.py doesn't import Telegram modules."""
        with open('ai/ai_engine.py', 'r') as f:
            content = f.read()
        
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('telegram', stripped)
                self.assertNotIn('python-telegram-bot', stripped)
    
    def test_gemini_client_no_telegram_imports(self):
        """Test that gemini_client.py doesn't import Telegram modules."""
        with open('ai/gemini_client.py', 'r') as f:
            content = f.read()
        
        lines = content.lower().split('\n')
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('telegram', stripped)
                self.assertNotIn('python-telegram-bot', stripped)
    
    def test_ai_modules_import_successfully(self):
        """Test that all ai/ modules import without errors."""
        try:
            import ai.ai_engine
            import ai.gemini_client
            import ai.exceptions
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import ai modules: {e}")


class TestPersonaLoading(unittest.TestCase):
    """Test persona.md loading and reload functionality."""
    
    def test_persona_file_exists(self):
        """Test that config/persona.md exists."""
        self.assertTrue(os.path.exists('config/persona.md'))
    
    def test_persona_content_valid(self):
        """Test that persona.md has valid content."""
        with open('config/persona.md', 'r') as f:
            content = f.read()
        self.assertTrue(len(content.strip()) > 100, "Persona should have substantial content")
        self.assertIn('Dexter', content)
    
    def test_ai_engine_loads_persona(self):
        """Test that AIEngine loads persona from file."""
        from ai.ai_engine import AIEngine
        
        engine = AIEngine()
        self.assertTrue(len(engine._persona_content) > 0, "Persona content should be loaded")
        self.assertIn('Dexter', engine._persona_content)
    
    def test_persona_reload_success(self):
        """Test that persona reload works correctly."""
        from ai.ai_engine import reload_persona
        
        # This should succeed with existing persona.md
        success, message = reload_persona()
        self.assertTrue(success)
        self.assertIn('Persona', message)
    
    def test_persona_in_prompt(self):
        """Test that persona content is included in generated prompt."""
        from ai.ai_engine import AIEngine
        
        engine = AIEngine()
        prompt = engine._build_prompt("What is the capital of Kenya?", "Student")
        
        # Prompt should contain persona content
        self.assertIn(engine._persona_content, prompt)
        # Prompt should contain user text
        self.assertIn("What is the capital of Kenya?", prompt)
        # Prompt should contain alias
        self.assertIn("Student", prompt)


class TestMockGeminiClient(unittest.TestCase):
    """Test AI engine with mocked Gemini client to avoid real API calls."""
    
    def test_answer_contract_with_mock(self):
        """Test answer() returns proper EngineResult contract."""
        from ai.ai_engine import EngineResult, STATUS_OK
        
        # Mock the gemini_client module
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.return_value = ("This is a test response", "gemini-2.5-flash")
            
            from ai.ai_engine import answer
            
            result = answer("What is 2+2?", "Student")
            
            # Verify contract
            self.assertIsInstance(result, EngineResult)
            self.assertEqual(result.reply_text, "This is a test response")
            self.assertEqual(result.model, "gemini-2.5-flash")
            self.assertEqual(result.status, STATUS_OK)
            self.assertEqual(result.snippet_ids, [])  # No retrieval in Step 2
            self.assertEqual(result.match_scores, [])  # No retrieval in Step 2
            self.assertIsInstance(result.latency_ms, int)  # Should be an integer
            self.assertGreaterEqual(result.latency_ms, 0)  # latency >= 0ms
            self.assertEqual(result.error, "")
    
    def test_answer_with_quota_error(self):
        """Test answer() handles quota exhausted error."""
        from ai.ai_engine import EngineResult, STATUS_QUOTA_EXHAUSTED
        from ai.exceptions import QuotaExhaustedError
        
        # Mock the gemini_client to raise QuotaExhaustedError
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.side_effect = QuotaExhaustedError("Rate limit exceeded")
            
            from ai.ai_engine import answer
            
            result = answer("What is 2+2?", "Student")
            
            # Verify quota exhausted handling
            self.assertIsInstance(result, EngineResult)
            self.assertEqual(result.status, STATUS_QUOTA_EXHAUSTED)
            self.assertIn("resting", result.reply_text.lower())
            self.assertEqual(result.error, "Rate limit exceeded")
    
    def test_answer_with_generic_error(self):
        """Test answer() handles generic API errors."""
        from ai.ai_engine import EngineResult, STATUS_ERROR
        
        # Mock the gemini_client to raise generic Exception
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.side_effect = Exception("Network error")
            
            from ai.ai_engine import answer
            
            result = answer("What is 2+2?", "Student")
            
            # Verify error handling
            self.assertIsInstance(result, EngineResult)
            self.assertEqual(result.status, STATUS_ERROR)
            self.assertIn("resting", result.reply_text.lower())
            self.assertEqual(result.error, "Network error")
    
    def test_user_text_reaches_model(self):
        """Test that user text is passed to the model."""
        from ai.ai_engine import answer
        
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.return_value = ("Response", "model")
            
            test_text = "What is the formula for water?"
            answer(test_text, "Student")
            
            # Check that call_gemini_api was called
            self.assertTrue(mock_call.called)
            
            # Get the prompt that was passed
            call_args = mock_call.call_args
            prompt_arg = call_args[1]['prompt'] if 'prompt' in call_args[1] else call_args[0][0]
            
            # Verify user text is in the prompt
            self.assertIn(test_text, str(prompt_arg))


class TestBotCommands(unittest.TestCase):
    """Test bot command handlers."""
    
    def test_commands_module_imports(self):
        """Test that commands module imports successfully."""
        try:
            import bot.commands
            self.assertTrue(hasattr(bot.commands, 'start_command'))
            self.assertTrue(hasattr(bot.commands, 'help_command'))
            self.assertTrue(hasattr(bot.commands, 'reload_command'))
            self.assertTrue(hasattr(bot.commands, 'handle_text_message'))
            self.assertTrue(hasattr(bot.commands, 'handle_non_text_message'))
        except ImportError as e:
            self.fail(f"Failed to import bot.commands: {e}")
    
    def test_patron_chat_ids_parsing(self):
        """Test patron chat IDs parsing from environment."""
        from bot.commands import get_patron_chat_ids
        
        # Test with comma-separated IDs
        with patch.dict('os.environ', {'PATRON_CHAT_IDS': '12345678,87654321'}):
            patron_ids = get_patron_chat_ids()
            self.assertEqual(patron_ids, {12345678, 87654321})
        
        # Test with empty string
        with patch.dict('os.environ', {'PATRON_CHAT_IDS': ''}):
            patron_ids = get_patron_chat_ids()
            self.assertEqual(patron_ids, set())
        
        # Test with spaces
        with patch.dict('os.environ', {'PATRON_CHAT_IDS': '12345678, 87654321, 11111111 '}):
            patron_ids = get_patron_chat_ids()
            self.assertEqual(patron_ids, {12345678, 87654321, 11111111})


class TestBotToAIIntegration(unittest.TestCase):
    """Test bot to AI engine integration."""
    
    def test_handle_text_message_calls_ai(self):
        """Test that handle_text_message calls AI engine."""
        from ai.ai_engine import EngineResult, STATUS_OK
        
        # Create a mock update object
        mock_message = Mock()
        mock_message.text = "What is the capital of Kenya?"
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        # Mock the answer function to return a test result
        with patch('bot.commands.answer') as mock_answer:
            mock_answer.return_value = EngineResult(
                reply_text="Nairobi is the capital of Kenya",
                status=STATUS_OK
            )
            
            from bot.commands import handle_text_message
            
            # Call the handler
            asyncio.run(handle_text_message(mock_update, Mock()))
            
            # Verify AI was called
            mock_answer.assert_called_once()
            
            # Verify reply was sent
            mock_message.reply_text.assert_called_once_with("Nairobi is the capital of Kenya")
    
    def test_non_text_message_behavior(self):
        """Test non-text message handling preserves Step 1 behavior."""
        # Create a mock update object with a photo
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        from bot.commands import handle_non_text_message
        
        # Call the handler
        asyncio.run(handle_non_text_message(mock_update, Mock()))
        
        # Verify correct response
        mock_message.reply_text.assert_called_once_with("Text only for now — type your question.")
    
    def test_reload_command_patron_only(self):
        """Test /reload command is restricted to patrons."""
        # Mock non-patron user
        mock_chat = Mock()
        mock_chat.id = 99999999  # Not in patron list
        
        mock_message = Mock()
        mock_message.chat = mock_chat
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        with patch.dict('os.environ', {'PATRON_CHAT_IDS': '12345678,87654321'}):
            from bot.commands import reload_command
            
            # Call the handler
            asyncio.run(reload_command(mock_update, Mock()))
            
            # Should get access denied message
            mock_message.reply_text.assert_called_once()
            call_text = mock_message.reply_text.call_args[0][0]
            self.assertIn("patrons only", call_text.lower())
    
    def test_reload_command_patron_allowed(self):
        """Test /reload command works for patrons."""
        # Mock patron user
        mock_chat = Mock()
        mock_chat.id = 12345678  # In patron list
        
        mock_message = Mock()
        mock_message.chat = mock_chat
        mock_message.reply_text = AsyncMock()
        
        mock_update = Mock()
        mock_update.message = mock_message
        
        with patch.dict('os.environ', {'PATRON_CHAT_IDS': '12345678,87654321'}):
            from bot.commands import reload_command
            
            # Call the handler
            asyncio.run(reload_command(mock_update, Mock()))
            
            # Should get success message (reload will succeed with valid persona.md)
            mock_message.reply_text.assert_called_once()
            call_text = mock_message.reply_text.call_args[0][0]
            self.assertIn("✓", call_text)


class TestPersonaReloadMalformedHandling(unittest.TestCase):
    """Test persona reload with malformed files."""
    
    def test_malformed_persona_preserves_previous(self):
        """Test that malformed persona reload preserves previous valid persona."""
        from ai.ai_engine import AIEngine
        
        # Create engine with current persona
        engine = AIEngine()
        original_content = engine._persona_content
        
        # Temporarily replace persona.md with empty file
        persona_path = os.path.join('config', 'persona.md')
        
        # Save original content
        with open(persona_path, 'r') as f:
            original_file_content = f.read()
        
        try:
            # Replace with empty content
            with open(persona_path, 'w') as f:
                f.write('')
            
            # Reload should fail but preserve previous persona
            success, message = engine.reload_persona()
            self.assertFalse(success)
            
            # Content should still be the original (preserved)
            self.assertEqual(engine._persona_content, original_content)
            
        finally:
            # Restore original content
            with open(persona_path, 'w') as f:
                f.write(original_file_content)


class TestStep2FileStructure(unittest.TestCase):
    """Test Step 2 file structure exists."""
    
    def test_ai_module_structure(self):
        """Test that ai/ module has required files."""
        self.assertTrue(os.path.exists('ai/__init__.py'))
        self.assertTrue(os.path.exists('ai/ai_engine.py'))
        self.assertTrue(os.path.exists('ai/gemini_client.py'))
        self.assertTrue(os.path.exists('ai/exceptions.py'))
    
    def test_config_directory_structure(self):
        """Test that config/ directory has required files."""
        self.assertTrue(os.path.exists('config/persona.md'))
    
    def test_bot_directory_structure(self):
        """Test that bot/ directory has required files."""
        self.assertTrue(os.path.exists('bot/__init__.py'))
        self.assertTrue(os.path.exists('bot/bot_core.py'))
        self.assertTrue(os.path.exists('bot/commands.py'))


def run_step2_tests():
    """Run all Step 2 tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add Step 2 test classes
    suite.addTests(loader.loadTestsFromTestCase(TestAIEngineResultContract))
    suite.addTests(loader.loadTestsFromTestCase(TestAIModuleIsolation))
    suite.addTests(loader.loadTestsFromTestCase(TestPersonaLoading))
    suite.addTests(loader.loadTestsFromTestCase(TestMockGeminiClient))
    suite.addTests(loader.loadTestsFromTestCase(TestBotCommands))
    suite.addTests(loader.loadTestsFromTestCase(TestBotToAIIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestPersonaReloadMalformedHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestStep2FileStructure))
    
    runner = unittest.TextTestRunner(verbosity=2)
    results = runner.run(suite)
    return results


if __name__ == '__main__':
    run_step2_tests()