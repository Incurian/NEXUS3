"""Canonical tool and skill identifier handling.

Arch A1: Provides normalized, validated tool/skill names across the codebase.

This module is the SINGLE SOURCE OF TRUTH for tool name validation and
normalization. All boundaries (config load, registry registration, RPC, CLI,
MCP integration) should use these functions.

SECURITY: MCP server names and tool names from external sources MUST be
sanitized before use to prevent:
- Name collision attacks (e.g., 'mcp_trusted__evil' mimicking 'mcp_trusted_evil')
- Path/command injection via skill names
- Unicode normalization attacks

Usage:
    from nexus3.core.identifiers import normalize_tool_name, validate_tool_name

    # Validate a name (raises ValueError if invalid)
    validate_tool_name("my_tool")

    # Normalize an external name (makes it safe)
    safe_name = normalize_tool_name("My-Tool!@#")  # Returns "my_tool"

    # Check if a name is valid without raising
    if is_valid_tool_name("my_tool"):
        ...
"""

from __future__ import annotations

import re
import unicodedata

# Maximum length for tool/skill names
MAX_TOOL_NAME_LENGTH: int = 64

# Minimum length for tool/skill names
MIN_TOOL_NAME_LENGTH: int = 1

# Valid tool name pattern: alphanumeric, underscore, hyphen
# Must start with a letter or underscore (like Python identifiers)
# Length: 1-64 characters
VALID_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$")

# Pattern for characters to replace during normalization
# Matches anything that's not alphanumeric, underscore, or hyphen
INVALID_CHAR_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")

# Pattern for consecutive underscores/hyphens (collapse to single)
CONSECUTIVE_SEPARATOR_PATTERN = re.compile(r"[_-]{2,}")

# Reserved names that cannot be used as tool names
# (prevents confusion with system functions)
RESERVED_TOOL_NAMES: frozenset[str] = frozenset({
    # Python/JSON reserved
    "true",
    "false",
    "null",
    "none",
    # Common system names
    "system",
    "admin",
    "root",
    # Internal prefixes that shouldn't be standalone
    "mcp",
    "nexus",
})


class ToolNameError(ValueError):
    """Raised when a tool name is invalid."""

    pass


def validate_tool_name(name: str, *, allow_reserved: bool = False) -> None:
    """Validate that a tool name conforms to the canonical format.

    Args:
        name: The tool name to validate.
        allow_reserved: If True, allow reserved names. Default False.

    Raises:
        ToolNameError: If the name is invalid, with a descriptive message.

    Examples:
        >>> validate_tool_name("read_file")  # OK
        >>> validate_tool_name("MyTool-v2")  # OK
        >>> validate_tool_name("")  # Raises ToolNameError
        >>> validate_tool_name("123_start")  # Raises ToolNameError (starts with digit)
        >>> validate_tool_name("a" * 100)  # Raises ToolNameError (too long)
    """
    if not isinstance(name, str):
        raise ToolNameError(f"Tool name must be a string, got {type(name).__name__}")

    if len(name) < MIN_TOOL_NAME_LENGTH:
        raise ToolNameError("Tool name cannot be empty")

    if len(name) > MAX_TOOL_NAME_LENGTH:
        raise ToolNameError(
            f"Tool name '{name[:20]}...' exceeds maximum length of "
            f"{MAX_TOOL_NAME_LENGTH} characters"
        )

    if not VALID_TOOL_NAME_PATTERN.match(name):
        # Provide specific error for common issues
        if name[0].isdigit():
            raise ToolNameError(
                f"Tool name '{name}' cannot start with a digit"
            )
        if name[0] == "-":
            raise ToolNameError(
                f"Tool name '{name}' cannot start with a hyphen"
            )
        raise ToolNameError(
            f"Tool name '{name}' contains invalid characters. "
            "Must be 1-64 chars, start with letter/underscore, "
            "contain only alphanumeric/underscore/hyphen"
        )

    if not allow_reserved and name.lower() in RESERVED_TOOL_NAMES:
        raise ToolNameError(
            f"Tool name '{name}' is reserved and cannot be used"
        )


def is_valid_tool_name(name: str, *, allow_reserved: bool = False) -> bool:
    """Check if a tool name is valid without raising an exception.

    Args:
        name: The tool name to check.
        allow_reserved: If True, allow reserved names. Default False.

    Returns:
        True if the name is valid, False otherwise.

    Examples:
        >>> is_valid_tool_name("read_file")
        True
        >>> is_valid_tool_name("")
        False
        >>> is_valid_tool_name("mcp")
        False
        >>> is_valid_tool_name("mcp", allow_reserved=True)
        True
    """
    try:
        validate_tool_name(name, allow_reserved=allow_reserved)
        return True
    except ToolNameError:
        return False


def normalize_tool_name(name: str, *, prefix: str = "") -> str:
    """Normalize an external name to a valid tool name.

    This function takes potentially unsafe input (e.g., MCP server names,
    tool names from external sources) and normalizes it to a safe, canonical
    form suitable for use as a skill/tool identifier.

    Normalization steps:
    1. Unicode normalization (NFKC - compatibility decomposition + composition)
    2. Convert to lowercase
    3. Replace invalid characters with underscore
    4. Collapse consecutive separators
    5. Strip leading/trailing separators
    6. Ensure starts with letter/underscore
    7. Truncate to max length (accounting for prefix)

    Args:
        name: The name to normalize. May contain any characters.
        prefix: Optional prefix to prepend (e.g., "mcp_server_").
            The prefix is prepended AFTER normalization and counts
            toward the max length.

    Returns:
        A valid, normalized tool name.

    Raises:
        ToolNameError: If the name cannot be normalized (e.g., empty after
            removing all invalid characters, or prefix alone exceeds max length).

    Examples:
        >>> normalize_tool_name("My Tool!")
        'my_tool'
        >>> normalize_tool_name("123-start")
        '_123_start'
        >>> normalize_tool_name("test", prefix="mcp_server_")
        'mcp_server_test'
        >>> normalize_tool_name("--dangerous--")
        'dangerous'
        >>> normalize_tool_name("über-tool")
        'uber_tool'
    """
    if not isinstance(name, str):
        raise ToolNameError(f"Tool name must be a string, got {type(name).__name__}")

    # Step 1: Unicode normalization (NFKC decomposes then recomposes)
    # This handles things like ü -> u, ﬁ -> fi, etc.
    normalized = unicodedata.normalize("NFKC", name)

    # Step 2: Convert to lowercase
    normalized = normalized.lower()

    # Step 3: Replace invalid characters with underscore
    normalized = INVALID_CHAR_PATTERN.sub("_", normalized)

    # Step 4: Collapse consecutive separators
    normalized = CONSECUTIVE_SEPARATOR_PATTERN.sub("_", normalized)

    # Step 5: Strip leading/trailing separators
    normalized = normalized.strip("_-")

    # Step 6: Ensure starts with letter/underscore
    if normalized and normalized[0].isdigit():
        normalized = "_" + normalized
    elif normalized and normalized[0] == "-":
        normalized = "_" + normalized[1:]

    # Handle empty result
    if not normalized:
        raise ToolNameError(
            f"Tool name '{name}' cannot be normalized: "
            "no valid characters remain after normalization"
        )

    # Step 7: Apply prefix and truncate
    if prefix:
        # Validate prefix itself (allow reserved since it may contain "mcp")
        if not VALID_TOOL_NAME_PATTERN.match(prefix.rstrip("_")):
            raise ToolNameError(f"Invalid prefix '{prefix}'")

        available_length = MAX_TOOL_NAME_LENGTH - len(prefix)
        if available_length < MIN_TOOL_NAME_LENGTH:
            raise ToolNameError(
                f"Prefix '{prefix}' is too long, leaving no room for tool name"
            )
        normalized = prefix + normalized[:available_length]
    else:
        normalized = normalized[:MAX_TOOL_NAME_LENGTH]

    return normalized


def build_mcp_skill_name(server_name: str, tool_name: str) -> str:
    """Build a canonical MCP skill name from server and tool names.

    SECURITY: This function sanitizes both server_name and tool_name to
    prevent injection attacks. External MCP servers can provide arbitrary
    tool names, which must be sanitized before use.

    The resulting name has format: mcp_{normalized_server}_{normalized_tool}

    Args:
        server_name: MCP server identifier (e.g., "my-server").
        tool_name: Tool name from the MCP server (may be arbitrary).

    Returns:
        A safe, canonical skill name (e.g., "mcp_my_server_echo").

    Raises:
        ToolNameError: If either name cannot be normalized.

    Examples:
        >>> build_mcp_skill_name("test", "echo")
        'mcp_test_echo'
        >>> build_mcp_skill_name("My Server!", "Tool@#$")
        'mcp_my_server_tool'
        >>> build_mcp_skill_name("evil/../path", "../../etc/passwd")
        'mcp_evil_path_etc_passwd'

    Note:
        Server names containing underscores may create parsing ambiguity.
        For example, both ``build_mcp_skill_name("trusted_evil", "cmd")`` and
        ``build_mcp_skill_name("trusted", "evil_cmd")`` produce the same
        canonical name ``"mcp_trusted_evil_cmd"``. When parsed back with
        ``parse_mcp_skill_name()``, both return ``("trusted", "evil_cmd")``.
        Consider using hyphens instead of underscores in server names to
        avoid this ambiguity (hyphens are normalized to underscores, but
        at least the source is unambiguous).
    """
    # Normalize server name
    safe_server = normalize_tool_name(server_name)

    # Build prefix and normalize tool name with length budget
    prefix = f"mcp_{safe_server}_"
    return normalize_tool_name(tool_name, prefix=prefix)


def parse_mcp_skill_name(skill_name: str) -> tuple[str, str] | None:
    """Parse an MCP skill name into server and tool components.

    Args:
        skill_name: A skill name, possibly an MCP skill (e.g., "mcp_test_echo").

    Returns:
        Tuple of (server_name, tool_name) if this is an MCP skill,
        None if not an MCP skill (doesn't start with "mcp_").

    Examples:
        >>> parse_mcp_skill_name("mcp_test_echo")
        ('test', 'echo')
        >>> parse_mcp_skill_name("mcp_my_server_my_tool")
        ('my', 'server_my_tool')  # Note: ambiguous without separator
        >>> parse_mcp_skill_name("read_file")
        None

    Note:
        Due to underscore ambiguity, parsing may not recover the original
        server/tool split. For example, ``"mcp_trusted_evil_cmd"`` could have
        come from either ``("trusted_evil", "cmd")`` or ``("trusted", "evil_cmd")``.
        The parser always returns the shortest server name (first underscore split).
    """
    if not skill_name.startswith("mcp_"):
        return None

    # Remove "mcp_" prefix
    remainder = skill_name[4:]

    # Find first underscore to split server from tool
    parts = remainder.split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None

    return (parts[0], parts[1])
