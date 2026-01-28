"""Typed exception hierarchy for NEXUS3."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.mcp.errors import MCPErrorContext


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

    def __init__(
        self, message: str, context: MCPErrorContext | None = None
    ) -> None:
        super().__init__(message)
        self.context = context


# === Error Sanitization for Agent-Facing Messages ===

# Patterns that may leak sensitive info

# Unix path patterns
_PATH_PATTERN = re.compile(r'(/[^\s:]+)+')
_HOME_PATTERN = re.compile(r'/home/[^/\s]+')

# Windows path patterns (order matters - most specific first)
# Handle BOTH backslashes AND forward slashes - Windows accepts either
_UNC_PATTERN = re.compile(r'(?:\\\\|//)[^\\/]+[/\\][^\\/]+')  # \\server\share or //server/share
_APPDATA_PATTERN = re.compile(
    r'[A-Za-z]:[/\\]Users[/\\][^\\/]+[/\\]AppData[/\\][^\\/]+',
    re.IGNORECASE
)
_WINDOWS_USER_PATTERN = re.compile(
    r'[A-Za-z]:[/\\]Users[/\\][^\\/]+',
    re.IGNORECASE
)
# Relative paths without drive letter (e.g., ..\Users\alice\secrets.txt)
_RELATIVE_USER_PATTERN = re.compile(r'(^|\s|\\|/)Users[/\\][^\\/\"]+', re.IGNORECASE)
# Domain\username format (e.g., DOMAIN\alice, BUILTIN\Administrators)
# Must not match drive letters (C: pattern) - requires at least 2 chars before backslash
_DOMAIN_USER_PATTERN = re.compile(r'(?<!\])\b([A-Z][A-Z0-9_-]{1,})(\\)[^\\/\"\s]+', re.IGNORECASE)


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

    # Windows paths (apply in order: most specific first)
    # Handle both backslash and forward slash variants
    result = _UNC_PATTERN.sub('[server]\\\\[share]', result)
    result = _APPDATA_PATTERN.sub('C:\\\\Users\\\\[user]\\\\AppData\\\\[...]', result)
    result = _WINDOWS_USER_PATTERN.sub('C:\\\\Users\\\\[user]', result)
    # Relative paths and domain\user patterns
    result = _RELATIVE_USER_PATTERN.sub(r'\1Users\\[user]', result)
    result = _DOMAIN_USER_PATTERN.sub('[domain]\\\\[user]', result)

    # Unix paths
    result = _HOME_PATTERN.sub('/home/[user]', result)
    result = _PATH_PATTERN.sub('[path]', result)

    return result
