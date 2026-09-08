#!/usr/bin/env python3
"""
Dexter AI Engine - Step 2 Implementation

This module handles prompt assembly and calling the model through the Gemini client.
It does not know about Telegram messages - it simply answers text questions.

Architecture constraints:
- Never imports anything Telegram-related
- Never imports logging internals (Step 3)
- Preserves EngineResult contract for future logger integration
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any

from .gemini_client import call_gemini_api
from .exceptions import QuotaExhaustedError, PersonaLoadError


# Status constants as per architecture
STATUS_OK = "ok"
STATUS_QUOTA_EXHAUSTED = "quota_exhausted"
STATUS_ERROR = "error"


@dataclass
class EngineResult:
    """
    Result of AI engine processing.
    
    Carries all metadata needed by the bot and future logger.
    Per architecture §4.1:
    - reply_text: The text to return to the user
    - snippet_ids: JSON list of source files injected (for future retrieval)
    - match_scores: JSON list of floats, parallel to snippet_ids
    - model: The model name/version used
    - latency_ms: Time taken in milliseconds
    - status: One of "ok | quota_exhausted | error"
    - error: Error description if status is error or quota_exhausted
    """
    reply_text: str
    snippet_ids: list[str] = field(default_factory=list)
    match_scores: list[float] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    status: str = STATUS_ERROR
    error: str = ""


class AIEngine:
    """
    AI Engine that builds prompts from persona.md and user text.
    
    This is the public interface for the bot to call the AI.
    Uses gemini_client for actual API calls, maintaining separation.
    """
    
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        """
        Initialize AI Engine.
        
        Args:
            model_name: The Gemini model to use (default: gemini-2.5-flash for free tier)
        """
        self.model_name = model_name
        self._persona_content = ""  # Loaded from persona.md
        self._last_valid_persona = ""  # Backup of last valid persona
        self._load_persona()
    
    def _load_persona(self) -> None:
        """Load persona from config/persona.md file."""
        persona_path = os.path.join(os.path.dirname(__file__), "..", "config", "persona.md")
        
        try:
            with open(persona_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate that we got some content
            if content.strip():
                # If this is the first load or different content, update
                if not self._persona_content or content != self._persona_content:
                    self._last_valid_persona = content
                self._persona_content = content
            else:
                # Empty file - this is an error
                raise PersonaLoadError("persona.md is empty")
                    
        except (FileNotFoundError, IOError) as e:
            # If first load, this is an error
            if not self._last_valid_persona:
                raise PersonaLoadError(f"Cannot load persona.md: {e}")
            # Otherwise, keep using last valid persona
            # Do not update _last_valid_persona since current file is invalid
            self._persona_content = self._last_valid_persona
    
    def reload_persona(self) -> tuple[bool, str]:
        """
        Reload persona from config/persona.md.
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            old_content = self._persona_content
            self._load_persona()
            
            if self._persona_content != old_content:
                return True, "Persona reloaded successfully"
            else:
                return True, "Persona unchanged"
                
        except PersonaLoadError as e:
            # Keep previous persona, warn about failure
            return False, f"Failed to reload persona: {e}"
    
    def answer(self, user_text: str, alias: str) -> EngineResult:
        """
        Generate an answer using the AI engine.
        
        Args:
            user_text: The user's input text
            alias: A privacy-safe alias (never raw Telegram ID)
            
        Returns:
            EngineResult with reply_text and metadata
            
        Architecture contract per §4.1:
        answer(user_text: str, alias: str) -> EngineResult
        """
        start_time = time.time()
        
        # Build prompt: persona.md + user_text
        # For Step 2, no retrieval yet (retrieval is Step 5)
        # So snippet_ids and match_scores remain empty lists
        prompt = self._build_prompt(user_text, alias)
        
        try:
            # Call Gemini API through our client wrapper
            result_text, actual_model = call_gemini_api(
                prompt=prompt,
                model_name=self.model_name
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            return EngineResult(
                reply_text=result_text,
                snippet_ids=[],  # No retrieval in Step 2
                match_scores=[],  # No retrieval in Step 2
                model=actual_model,
                latency_ms=latency_ms,
                status=STATUS_OK,
                error=""
            )
            
        except QuotaExhaustedError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return EngineResult(
                reply_text="I'm resting, try again in a few minutes",
                snippet_ids=[],
                match_scores=[],
                model=self.model_name,
                latency_ms=latency_ms,
                status=STATUS_QUOTA_EXHAUSTED,
                error=str(e)
            )
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return EngineResult(
                reply_text="I'm resting, try again in a few minutes",
                snippet_ids=[],
                match_scores=[],
                model=self.model_name,
                latency_ms=latency_ms,
                status=STATUS_ERROR,
                error=str(e)
            )
    
    def _build_prompt(self, user_text: str, alias: str) -> str:
        """
        Build the prompt from persona + user text.
        
        This design is extensible for future retrieval integration.
        When retrieval is added (Step 5), snippets can be inserted
        between persona and user text without changing this interface.
        """
        # Use persona content as system prompt
        prompt_parts = [
            self._persona_content,
            f"\n\nUser ({alias}): {user_text}",
            "\n\nAssistant:"
        ]
        
        return "\n".join(prompt_parts)


# Global engine instance (for convenience, but could be dependency injected)
_engine: AIEngine | None = None


def get_engine() -> AIEngine:
    """Get or create the global AI engine instance."""
    global _engine
    if _engine is None:
        _engine = AIEngine()
    return _engine


def answer(user_text: str, alias: str) -> EngineResult:
    """
    Public interface: answer a user text question with alias.
    
    This is the contract specified in ARCHITECTURE.md §4.1:
    def answer(user_text: str, alias: str) -> EngineResult
    """
    return get_engine().answer(user_text, alias)


def reload_persona() -> tuple[bool, str]:
    """Reload persona configuration."""
    return get_engine().reload_persona()