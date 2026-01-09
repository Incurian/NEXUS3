"""Pydantic models for NEXUS3 configuration validation."""

from pydantic import BaseModel, ConfigDict


class ProviderConfig(BaseModel):
    """Configuration for LLM provider."""

    model_config = ConfigDict(extra="forbid")

    type: str = "openrouter"
    api_key_env: str = "OPENROUTER_API_KEY"  # env var name containing API key
    model: str = "x-ai/grok-code-fast-1"
    base_url: str = "https://openrouter.ai/api/v1"


class Config(BaseModel):
    """Root configuration model."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderConfig = ProviderConfig()
    stream_output: bool = True
    max_tool_iterations: int = 10  # Maximum iterations of the tool execution loop
    default_permission_level: str = "trusted"  # yolo, trusted, or sandboxed
    skill_timeout: float = 30.0  # Seconds, 0 = no timeout
    max_concurrent_tools: int = 10  # Max parallel tool executions
