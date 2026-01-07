"""Pydantic models for NEXUS3 configuration validation."""

from pydantic import BaseModel


class ProviderConfig(BaseModel):
    """Configuration for LLM provider."""

    type: str = "openrouter"
    api_key_env: str = "OPENROUTER_API_KEY"  # env var name containing API key
    model: str = "x-ai/grok-code-fast-1"
    base_url: str = "https://openrouter.ai/api/v1"


class Config(BaseModel):
    """Root configuration model."""

    provider: ProviderConfig = ProviderConfig()
    stream_output: bool = True
