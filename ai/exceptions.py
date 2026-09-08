#!/usr/bin/env python3
"""
Dexter AI Exceptions

Contains custom exceptions for the AI module to avoid circular imports.
"""


class QuotaExhaustedError(Exception):
    """Raised when Gemini API quota is exhausted."""
    pass


class PersonaLoadError(Exception):
    """Raised when persona.md cannot be loaded."""
    pass