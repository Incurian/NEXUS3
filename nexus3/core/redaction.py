"""Secrets redaction for NEXUS3.

This module provides functions to detect and redact sensitive information
from text before it's sent to external services (like summarization LLMs
during context compaction).

Patterns include:
- API keys (OpenAI, Anthropic, GitHub, AWS, etc.)
- Bearer tokens
- Passwords (in assignment/URL contexts)
- Private keys (RSA, ECDSA, etc.)
- Database connection strings with credentials
"""

import re
from typing import Any

# Redaction placeholder - clearly marks redacted content
REDACTED = "[REDACTED]"

# Secret patterns: name -> (regex_pattern, replacement)
# Patterns use capture groups to preserve context while redacting secrets
SECRET_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    # OpenAI API keys: sk-... (48+ chars)
    "openai_key": (
        re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"),
        REDACTED,
    ),
    # Anthropic API keys: sk-ant-... (starts with sk-ant-)
    "anthropic_key": (
        re.compile(r"\b(sk-ant-[A-Za-z0-9\-_]{20,})\b"),
        REDACTED,
    ),
    # GitHub tokens: ghp_, gho_, ghu_, ghs_, ghr_ (40 chars)
    "github_token": (
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b"),
        REDACTED,
    ),
    # AWS Access Key ID: AKIA... (20 chars)
    "aws_access_key": (
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        REDACTED,
    ),
    # AWS Secret Access Key: 40 char base64-like after known prefixes
    # This matches common patterns like "aws_secret_access_key = ..." or JSON
    # Preserves the key name and replaces just the value
    "aws_secret_key": (
        re.compile(
            r'((?:aws_)?secret_access_key[\s]*[=:][\s]*["\']?)'
            r'([A-Za-z0-9+/]{20,})',
            re.IGNORECASE,
        ),
        f"\\1{REDACTED}",
    ),
    # Bearer tokens in Authorization headers
    "bearer_token": (
        re.compile(
            r"(Authorization:\s*Bearer\s+)([A-Za-z0-9\-_\.]+)",
            re.IGNORECASE,
        ),
        f"\\1{REDACTED}",
    ),
    # Generic API key patterns: api_key=..., api-key: ..., etc.
    # Preserves the key name and replaces the value
    "generic_api_key": (
        re.compile(
            r'((?:api[_-]?key|apikey)[\s]*[=:][\s]*["\']?)'
            r'([A-Za-z0-9\-_]{20,})',
            re.IGNORECASE,
        ),
        f"\\1{REDACTED}",
    ),
    # Password assignments: password = "...", password: "...", "password": "...", etc.
    # Preserves the key name and surrounding quotes, replaces the value
    "password_assignment": (
        re.compile(
            r'(["\']?(?:password|passwd|pwd)["\']?[\s]*[=:][\s]*["\']?)'
            r'([^\s"\',;\}]+)',
            re.IGNORECASE,
        ),
        f"\\1{REDACTED}",
    ),
    # Passwords in URLs: user:password@host
    "password_in_url": (
        re.compile(
            r"(://[^:]+:)([^@]+)(@)",
        ),
        f"\\1{REDACTED}\\3",
    ),
    # Private key blocks (RSA, ECDSA, etc.)
    "private_key_block": (
        re.compile(
            r"(-----BEGIN\s+(?:RSA\s+)?(?:EC\s+)?(?:OPENSSH\s+)?PRIVATE\s+KEY-----)"
            r"([\s\S]*?)"
            r"(-----END\s+(?:RSA\s+)?(?:EC\s+)?(?:OPENSSH\s+)?PRIVATE\s+KEY-----)",
            re.MULTILINE,
        ),
        f"\\1\n{REDACTED}\n\\3",
    ),
    # Database connection strings with credentials
    # postgresql://user:password@host/db, mysql://user:pass@host/db, etc.
    "connection_string": (
        re.compile(
            r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://)"
            r"([^:]+):([^@]+)@",
            re.IGNORECASE,
        ),
        f"\\1\\2:{REDACTED}@",
    ),
    # JWT tokens (three base64url segments separated by dots)
    "jwt_token": (
        re.compile(
            r"\b(eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)\b",
        ),
        REDACTED,
    ),
}


def redact_secrets(text: str) -> str:
    """Redact secrets from a text string.

    Applies all patterns in SECRET_PATTERNS to find and replace
    sensitive information with [REDACTED].

    Args:
        text: The text to scan and redact.

    Returns:
        The text with secrets replaced by [REDACTED].

    Example:
        >>> redact_secrets("api_key = sk-abc123...")
        "api_key = [REDACTED]"
    """
    result = text

    for pattern_name, (pattern, replacement) in SECRET_PATTERNS.items():
        result = pattern.sub(replacement, result)

    return result


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact secrets from a dictionary.

    Processes all string values in the dict, including nested dicts
    and lists. Returns a new dict; the original is not modified.

    Args:
        data: The dictionary to process.

    Returns:
        A new dictionary with secrets redacted from string values.
    """
    return _redact_value(data)  # type: ignore[return-value]


def _redact_value(value: Any) -> Any:
    """Recursively redact secrets from a value of any type."""
    if isinstance(value, str):
        return redact_secrets(value)
    elif isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_redact_value(item) for item in value]
    elif isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    else:
        # Primitives (int, float, bool, None) pass through unchanged
        return value
