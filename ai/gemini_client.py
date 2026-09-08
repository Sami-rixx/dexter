#!/usr/bin/env python3
"""
Dexter Gemini Client - Thin wrapper around the official Google GenAI SDK

This is the boundary layer between the AI engine and the Gemini API.
The ai_engine does not contain SDK-specific request mechanics.

Architecture constraints:
- Never imports anything Telegram-related
- Never imports logging internals (Step 3)
- Handles API key configuration from environment
"""

import os
import google.genai as genai
from typing import Optional

# Import our custom exception
from .exceptions import QuotaExhaustedError


def get_api_key() -> str:
    """Get Gemini API key from environment."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "GEMINI_API_KEY not found in environment. "
            "Set it in .env file or export it before running the bot."
        )
    return key


def call_gemini_api(prompt: str, model_name: str = "gemini-2.5-flash") -> tuple[str, str]:
    """
    Call the Gemini API with the given prompt.
    
    Args:
        prompt: The text prompt to send to the model
        model_name: The model to use (default: gemini-2.5-flash)
        
    Returns:
        tuple: (response_text: str, actual_model: str)
        
    Raises:
        QuotaExhaustedError: When API quota is exhausted
        Exception: For other API errors
    """
    api_key = get_api_key()
    
    # Create client with API key
    client = genai.Client(api_key=api_key)
    
    # Use the models client to generate content
    models = client.models
    
    try:
        response = models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        # Extract text from response
        # The response has a candidates field with content parts
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                content = candidate.content
                if hasattr(content, 'parts') and content.parts:
                    # Extract text from parts
                    text_parts = []
                    for part in content.parts:
                        if hasattr(part, 'text'):
                            text_parts.append(part.text)
                    response_text = "".join(text_parts)
                else:
                    # Fallback: try to get text directly
                    response_text = str(content)
            else:
                response_text = "I'm sorry, I couldn't generate a response."
        else:
            response_text = "I'm sorry, I couldn't generate a response."
        
        # Return the response and actual model used
        # If the response has model info, use it, otherwise use the requested model
        actual_model = model_name
        return response_text, actual_model
        
    except genai.errors.GeminiError as e:
        # Check for quota-related errors
        error_str = str(e).lower()
        if any(keyword in error_str for keyword in [
            'quota', 'rate limit', 'limit exceeded', '429', 'too many requests'
        ]):
            raise QuotaExhaustedError(f"Gemini API quota exhausted: {e}")
        else:
            # For other Gemini errors, wrap the error message
            raise Exception(f"Gemini API error: {e}")
    
    except Exception as e:
        # For any other exceptions, wrap them
        raise Exception(f"Gemini API call failed: {e}")