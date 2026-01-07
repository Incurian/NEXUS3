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
