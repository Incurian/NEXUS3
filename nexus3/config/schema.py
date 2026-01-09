"""Pydantic models for NEXUS3 configuration validation."""

from pydantic import BaseModel, ConfigDict


class ProviderConfig(BaseModel):
    """Configuration for LLM provider."""

    model_config = ConfigDict(extra="forbid")

    type: str = "openrouter"
    api_key_env: str = "OPENROUTER_API_KEY"  # env var name containing API key
    model: str = "x-ai/grok-code-fast-1"
    base_url: str = "https://openrouter.ai/api/v1"


class ToolPermissionConfig(BaseModel):
    """Per-tool permission configuration in config.json."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allowed_paths: list[str] | None = None
    timeout: float | None = None
    requires_confirmation: bool | None = None


class PermissionPresetConfig(BaseModel):
    """Custom permission preset in config.json."""

    model_config = ConfigDict(extra="forbid")

    extends: str | None = None  # Base preset to extend
    description: str = ""
    allowed_paths: list[str] | None = None
    blocked_paths: list[str] = []
    network_access: bool | None = None
    tool_permissions: dict[str, ToolPermissionConfig] = {}
    default_tool_timeout: float | None = None


class PermissionsConfig(BaseModel):
    """Top-level permissions configuration."""

    model_config = ConfigDict(extra="forbid")

    default_preset: str = "trusted"
    presets: dict[str, PermissionPresetConfig] = {}
    destructive_tools: list[str] = ["write_file", "nexus_destroy", "nexus_shutdown"]


class Config(BaseModel):
    """Root configuration model."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderConfig = ProviderConfig()
    stream_output: bool = True
    max_tool_iterations: int = 10  # Maximum iterations of the tool execution loop
    default_permission_level: str = "trusted"  # yolo, trusted, or sandboxed
    skill_timeout: float = 30.0  # Seconds, 0 = no timeout
    max_concurrent_tools: int = 10  # Max parallel tool executions
    permissions: PermissionsConfig = PermissionsConfig()  # Permission system config
