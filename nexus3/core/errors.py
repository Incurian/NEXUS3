"""Typed exception hierarchy for NEXUS3."""

import re


class NexusError(Exception):
    """Base class for all NEXUS3 errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ConfigError(NexusError):
    """Raised for configuration issues (missing file, invalid JSON, validation failure)."""


class ProviderError(NexusError):
    """Raised for LLM provider issues (API errors, network issues, auth failure)."""


class PathSecurityError(NexusError):
    """Raised when a path violates security sandbox constraints."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Path security violation for '{path}': {reason}")


class LoadError(NexusError):
    """Base class for loading errors (config, context, files)."""

    pass


class ContextLoadError(LoadError):
    """Context loading issues (JSON, validation, merging)."""

    pass


class MCPConfigError(ContextLoadError):
    """MCP server configuration errors."""

    pass


# === Error Sanitization for Agent-Facing Messages ===

# Patterns that may leak sensitive info
_PATH_PATTERN = re.compile(r'(/[^\s:]+)+')
_HOME_PATTERN = re.compile(r'/home/[^/\s]+')


def sanitize_error_for_agent(error: str | None, tool_name: str = "") -> str | None:
    """Reduce sensitive details in errors shown to agents.

    Keeps errors informative but removes:
    - Full filesystem paths (replaced with [path])
    - Home directory usernames
    - Internal error codes

    Args:
        error: The original error message
        tool_name: Optional tool name for context

    Returns:
        Sanitized error message safe to show agents, or None if input was None
    """
    if not error:
        return error

    # Common error patterns - provide generic but helpful messages
    error_lower = error.lower()

    if "permission denied" in error_lower:
        return f"Permission denied for {tool_name or 'this operation'}"

    if "no such file" in error_lower or "not found" in error_lower:
        return "File or directory not found"

    if "is a directory" in error_lower:
        return "Expected a file but got a directory"

    if "not a directory" in error_lower:
        return "Expected a directory but got a file"

    if "file exists" in error_lower:
        return "File already exists"

    if "disk quota" in error_lower or "no space" in error_lower:
        return "Insufficient disk space"

    if "timed out" in error_lower or "timeout" in error_lower:
        return f"{tool_name or 'Operation'} timed out"

    # For other errors, sanitize paths but keep the message
    result = error
    result = _HOME_PATTERN.sub('/home/[user]', result)
    result = _PATH_PATTERN.sub('[path]', result)

    return result
