#!/usr/bin/env python3
"""
Dexter AI Engine - Steps 2-5 Implementation

This module handles prompt assembly and calling the model through the Gemini client.
It does not know about Telegram messages - it simply answers text questions.

Architecture constraints:
- Never imports anything Telegram-related
- Never imports logging internals (Step 3)
- Preserves EngineResult contract for the logger
- Prompt assembly (architecture section 4.1): persona.md + retrieved
  knowledge snippets + user_text
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from .gemini_client import call_gemini_api
from .exceptions import QuotaExhaustedError, PersonaLoadError
from .retriever import Snippet, get_retriever, reload_topics

logger = logging.getLogger(__name__)


# Status constants as per architecture
STATUS_OK = "ok"
STATUS_QUOTA_EXHAUSTED = "quota_exhausted"
STATUS_ERROR = "error"


# Instructions that frame the injected knowledge snippets. The goal
# (architecture sections 1, 7 and 12): answers grounded in the vetted CBC
# knowledge files stay faithful to them, and questions the files do not
# cover are answered honestly instead of with invented curriculum facts.
REFERENCE_INSTRUCTIONS = (
    "--- Reference material from Dexter's CBC knowledge base ---\n"
    "The material below comes from the school's vetted CBC knowledge files "
    "and may include page references to its source book. Treat it as your "
    "primary, trusted source when it covers the student's question. If it "
    "does not cover the question, say plainly that you are not sure about "
    "this topic rather than inventing curriculum facts. Keep your friendly "
    "tutor tone and explain simply."
)


@dataclass
class EngineResult:
    """
    Result of AI engine processing.
    
    Carries all metadata needed by the bot and future logger.
    Per architecture §4.1:
    - reply_text: The text to return to the user
    - snippet_ids: JSON list of source files injected (from retrieval)
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
    AI Engine that builds prompts from persona.md, retrieved knowledge
    snippets and user text.

    This is the public interface for the bot to call the AI.
    Uses gemini_client for actual API calls, maintaining separation.
    """
    
    def __init__(self, model_name: str = "gemini-2.5-flash",
                 retriever: Optional[object] = None):
        """
        Initialize AI Engine.
        
        Args:
            model_name: The Gemini model to use (default: gemini-2.5-flash for free tier)
            retriever: Optional knowledge retriever (anything exposing
                retrieve(query, max_snippets) -> list[Snippet]). Defaults
                to the shared config/topics/ retriever.
        """
        self.model_name = model_name
        self._retriever = retriever
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

    def reload_config(self) -> tuple[bool, str]:
        """
        Reload persona.md AND the config/topics knowledge files from disk.

        This backs the patron-only /reload command (architecture section 7:
        after a git pull, config edits go live without restarting the bot).
        Each part fails independently and keeps its previous valid state.
        """
        persona_ok, persona_message = self.reload_persona()
        topics_ok, topics_message = reload_topics()
        success = persona_ok and topics_ok
        return success, f"{persona_message}; topics: {topics_message}"

    def _retrieve_snippets(self, user_text: str) -> list[Snippet]:
        """
        Fetch knowledge snippets for the question.

        Retrieval must never break answering: any failure yields an
        empty list and a stderr warning.
        """
        try:
            retriever = self._retriever if self._retriever is not None else get_retriever()
            return retriever.retrieve(user_text)
        except Exception as e:
            logger.error(f"Knowledge retrieval failed: {e}")
            return []
    
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
        
        # Build prompt: persona.md + retrieved knowledge snippets + user_text
        # (architecture section 4.1). Snippets are retrieved even when the
        # API call later fails, so reviews can see whether the right
        # knowledge file was found.
        snippets = self._retrieve_snippets(user_text)
        snippet_ids = [s.source_file for s in snippets]
        match_scores = [s.match_score for s in snippets]
        
        prompt = self._build_prompt(user_text, alias, snippets)
        
        try:
            # Call Gemini API through our client wrapper
            result_text, actual_model = call_gemini_api(
                prompt=prompt,
                model_name=self.model_name
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            return EngineResult(
                reply_text=result_text,
                snippet_ids=snippet_ids,
                match_scores=match_scores,
                model=actual_model,
                latency_ms=latency_ms,
                status=STATUS_OK,
                error=""
            )
            
        except QuotaExhaustedError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return EngineResult(
                reply_text="I'm resting, try again in a few minutes",
                snippet_ids=snippet_ids,
                match_scores=match_scores,
                model=self.model_name,
                latency_ms=latency_ms,
                status=STATUS_QUOTA_EXHAUSTED,
                error=str(e)
            )
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return EngineResult(
                reply_text="I'm resting, try again in a few minutes",
                snippet_ids=snippet_ids,
                match_scores=match_scores,
                model=self.model_name,
                latency_ms=latency_ms,
                status=STATUS_ERROR,
                error=str(e)
            )
    
    def _build_prompt(self, user_text: str, alias: str,
                      snippets: Optional[list[Snippet]] = None) -> str:
        """
        Build the prompt from persona + (optional) knowledge snippets + user text.
        
        With no snippets the prompt is exactly the persona + user text
        form of the earlier build steps. With snippets, a reference block
        with grounding instructions is inserted between persona and user
        text (architecture section 4.1).
        """
        # Use persona content as system prompt
        prompt_parts = [self._persona_content]

        if snippets:
            prompt_parts.append(REFERENCE_INSTRUCTIONS)
            for index, snippet in enumerate(snippets, start=1):
                prompt_parts.append(
                    f"[Reference {index} — {snippet.source_file}]\n"
                    f"{snippet.content}"
                )
        
        prompt_parts.append(f"\n\nUser ({alias}): {user_text}")
        prompt_parts.append("\n\nAssistant:")
        
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


def reload_config() -> tuple[bool, str]:
    """
    Reload persona.md and the config/topics knowledge files.

    Public interface used by the patron-only /reload command.
    """
    return get_engine().reload_config()
