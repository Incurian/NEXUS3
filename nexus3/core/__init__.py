"""Core types and interfaces."""

from nexus3.core.cancel import CancellationToken
from nexus3.core.encoding import ENCODING, ENCODING_ERRORS, configure_stdio
from nexus3.core.errors import ConfigError, NexusError, PathSecurityError, ProviderError
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.paths import get_default_sandbox, validate_sandbox
from nexus3.core.permissions import PermissionLevel, PermissionPolicy
from nexus3.core.types import (
    ContentDelta,
    Message,
    ReasoningDelta,
    Role,
    StreamComplete,
    StreamEvent,
    ToolCall,
    ToolCallStarted,
    ToolResult,
)
from nexus3.core.url_validator import UrlSecurityError, validate_url

__all__ = [
    "CancellationToken",
    "ENCODING",
    "ENCODING_ERRORS",
    "configure_stdio",
    "NexusError",
    "ConfigError",
    "ProviderError",
    "PathSecurityError",
    "UrlSecurityError",
    "AsyncProvider",
    "Message",
    "Role",
    "ToolCall",
    "ToolResult",
    # Streaming types
    "StreamEvent",
    "ContentDelta",
    "ReasoningDelta",
    "ToolCallStarted",
    "StreamComplete",
    # Path sandbox
    "validate_sandbox",
    "get_default_sandbox",
    # URL validation
    "validate_url",
    # Permissions
    "PermissionLevel",
    "PermissionPolicy",
]
