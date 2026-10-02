#!/usr/bin/env python3
"""
Dexter Gemini Client - Thin wrapper around the official Google GenAI SDK

This is the boundary layer between the AI engine and the Gemini API.
The ai_engine does not contain SDK-specific request mechanics.

Uses the Google GenAI Interactions API (client.interactions.create)
with response.output_text extraction.

Architecture constraints:
- Never imports anything Telegram-related
- Never imports logging internals (Step 3)
- Handles API key configuration from environment securely
- Configurable model via GEMINI_MODEL env var (default: gemini-3.8-flash)
"""

import os
from typing import Any, Optional
import google.genai as genai

# Import our custom exception
from .exceptions import QuotaExhaustedError

DEFAULT_MODEL = "gemini-3.8-flash"


def get_api_key() -> str:
    """
    Get Gemini API key from environment.

    Raises:
        ValueError: When GEMINI_API_KEY is not set or empty.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key or not key.strip():
        raise ValueError(
            "GEMINI_API_KEY not found in environment. "
            "Set it in .env file or export it before running the bot."
        )
    return key.strip()


def get_model_name() -> str:
    """
    Get Gemini model name from environment or return default.

    Returns:
        Configured model name (from GEMINI_MODEL) or 'gemini-3.8-flash'.
    """
    model = os.getenv("GEMINI_MODEL")
    if model and model.strip():
        return model.strip()
    return DEFAULT_MODEL


def _is_quota_error(exception: Exception) -> bool:
    """
    Classify an exception as a quota/rate-limit error (testable helper).

    Checks the HTTP status code when the SDK exposes one (429) and falls
    back to matching the error message keywords.
    """
    code = getattr(exception, "code", None)
    if code is not None:
        try:
            if int(code) == 429:
                return True
        except (TypeError, ValueError):
            pass

    status_code = getattr(exception, "status_code", None)
    if status_code is not None:
        try:
            if int(status_code) == 429:
                return True
        except (TypeError, ValueError):
            pass

    error_str = str(exception).lower()
    return any(keyword in error_str for keyword in [
        'quota', 'rate limit', 'limit exceeded', '429', 'too many requests', 'resource_exhausted'
    ])


def _extract_response_text(response: Any) -> str:
    """
    Extract text output from an Interactions API response.

    Handles valid output_text, dict responses, fallback structured steps,
    empty/whitespace responses, and malformed objects.
    """
    fallback_message = "I'm sorry, I couldn't generate a response."

    if response is None:
        return fallback_message

    # 1. Primary: output_text attribute from Interactions API
    if hasattr(response, "output_text"):
        text = response.output_text
        if text is not None and isinstance(text, str) and text.strip():
            return text

    # 2. Dictionary output_text support
    if isinstance(response, dict):
        text = response.get("output_text")
        if text is not None and isinstance(text, str) and text.strip():
            return text

    # 3. Fallback: extract text from steps if present
    steps = getattr(response, "steps", None)
    if isinstance(steps, (list, tuple)) and steps:
        parts: list[str] = []
        for step in steps:
            content = getattr(step, "content", None)
            if isinstance(content, list):
                for item in content:
                    if getattr(item, "type", None) == "text" or (isinstance(item, dict) and item.get("type") == "text"):
                        text_val = getattr(item, "text", None) if hasattr(item, "text") else (item.get("text") if isinstance(item, dict) else None)
                        if text_val and isinstance(text_val, str):
                            parts.append(text_val)
            elif isinstance(content, str) and content.strip():
                parts.append(content)
        if parts:
            joined = "".join(parts)
            if joined.strip():
                return joined

    return fallback_message


def _extract_model_name(response: Any, fallback_model: str) -> str:
    """Extract model name from response if available, or fall back to requested model."""
    if response is not None:
        model_val = getattr(response, "model", None)
        if isinstance(model_val, str) and model_val.strip():
            return model_val.strip()
        if isinstance(response, dict):
            dict_model = response.get("model")
            if isinstance(dict_model, str) and dict_model.strip():
                return dict_model.strip()
    return fallback_model


def call_gemini_api(prompt: str, model_name: Optional[str] = None) -> tuple[str, str]:
    """
    Call the Gemini API with the given prompt using the Interactions API.

    Args:
        prompt: The text prompt to send to the model
        model_name: The model to use (default: GEMINI_MODEL env var or gemini-3.8-flash)

    Returns:
        tuple: (response_text: str, actual_model: str)

    Raises:
        QuotaExhaustedError: When API quota is exhausted
        ValueError: When API key is missing
        Exception: For other API errors, timeouts, or failures
    """
    if not model_name:
        model_name = get_model_name()

    api_key = get_api_key()

    # Create client with API key securely passed
    client = genai.Client(api_key=api_key)

    try:
        response = client.interactions.create(
            model=model_name,
            input=prompt
        )

        response_text = _extract_response_text(response)
        actual_model = _extract_model_name(response, model_name)
        return response_text, actual_model

    except QuotaExhaustedError:
        # Never swallow an already-classified quota error
        raise

    except getattr(genai.errors, "APIError", Exception) as e:
        if _is_quota_error(e):
            raise QuotaExhaustedError(f"Gemini API quota exhausted: {e}")
        if isinstance(e, getattr(genai.errors, "APIError", ())):
            raise Exception(f"Gemini API error: {e}")
        raise Exception(f"Gemini API call failed: {e}")

    except Exception as e:
        if _is_quota_error(e):
            raise QuotaExhaustedError(f"Gemini API quota exhausted: {e}")
        raise Exception(f"Gemini API call failed: {e}")
