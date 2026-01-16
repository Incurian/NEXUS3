"""Typed exception hierarchy for NEXUS3."""


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
