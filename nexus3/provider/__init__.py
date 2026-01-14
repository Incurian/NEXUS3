"""LLM provider implementations for NEXUS3.

This module provides the factory function for creating providers based on
configuration, plus provider defaults for each supported provider type.

Supported providers:
- openrouter: OpenRouter.ai (default)
- openai: Direct OpenAI API
- azure: Azure OpenAI Service
- anthropic: Anthropic Claude API
- ollama: Local Ollama server
- vllm: vLLM OpenAI-compatible server

Example:
    from nexus3.provider import create_provider
    from nexus3.config.schema import ProviderConfig

    config = ProviderConfig(type="anthropic", model="claude-sonnet-4-20250514")
    provider = create_provider(config)
"""

from typing import TYPE_CHECKING

from nexus3.config.schema import AuthMethod
from nexus3.core.errors import ConfigError

if TYPE_CHECKING:
    from nexus3.config.schema import ProviderConfig
    from nexus3.core.interfaces import AsyncProvider, RawLogCallback


# Provider type defaults - used by factory and for documentation
PROVIDER_DEFAULTS: dict[str, dict[str, str | AuthMethod]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "auth_method": AuthMethod.BEARER,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "auth_method": AuthMethod.BEARER,
    },
    "azure": {
        "api_key_env": "AZURE_OPENAI_KEY",
        "auth_method": AuthMethod.API_KEY,
        "api_version": "2024-02-01",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY",
        "auth_method": AuthMethod.X_API_KEY,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "auth_method": AuthMethod.NONE,
        "api_key_env": "",
    },
    "vllm": {
        "base_url": "http://localhost:8000/v1",
        "auth_method": AuthMethod.NONE,
        "api_key_env": "",
    },
}


def create_provider(
    config: "ProviderConfig",
    model_id: str,
    raw_log: "RawLogCallback | None" = None,
    reasoning: bool = False,
) -> "AsyncProvider":
    """Create a provider instance based on config.provider.type.

    The factory creates the appropriate provider class based on the type
    field in the configuration. Each provider type has default settings
    that can be overridden in config.

    Args:
        config: Provider configuration. The 'type' field determines which
            provider class is instantiated.
        model_id: The model ID to use for API requests.
        raw_log: Optional callback for raw API logging.
        reasoning: Whether to enable extended thinking/reasoning.

    Returns:
        Provider instance implementing the AsyncProvider protocol.

    Raises:
        ConfigError: If provider type is unknown.

    Example:
        # OpenRouter
        config = ProviderConfig(type="openrouter")
        provider = create_provider(config, "anthropic/claude-haiku-4.5")

        # Anthropic
        config = ProviderConfig(type="anthropic", api_key_env="ANTHROPIC_API_KEY")
        provider = create_provider(config, "claude-sonnet-4-20250514")

        # Local Ollama
        config = ProviderConfig(type="ollama")
        provider = create_provider(config, "llama3.2")
    """
    provider_type = config.type.lower()

    # OpenAI-compatible providers
    if provider_type in ("openrouter", "openai", "ollama", "vllm"):
        from nexus3.provider.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(config, model_id, raw_log, reasoning)

    # Azure OpenAI
    if provider_type == "azure":
        from nexus3.provider.azure import AzureOpenAIProvider

        return AzureOpenAIProvider(config, model_id, raw_log, reasoning)

    # Anthropic
    if provider_type == "anthropic":
        from nexus3.provider.anthropic import AnthropicProvider

        return AnthropicProvider(config, model_id, raw_log, reasoning)

    # Unknown provider type
    supported = ", ".join(PROVIDER_DEFAULTS.keys())
    raise ConfigError(
        f"Unknown provider type: '{provider_type}'. Supported: {supported}"
    )


# Backwards compatibility: alias OpenRouterProvider to OpenAICompatProvider
from nexus3.provider.openai_compat import OpenAICompatProvider as OpenRouterProvider
from nexus3.provider.registry import ProviderRegistry

__all__ = [
    "create_provider",
    "OpenRouterProvider",
    "ProviderRegistry",
    "PROVIDER_DEFAULTS",
]
