"""Provider registry for multi-provider support.

This module provides the ProviderRegistry class that manages multiple
provider instances with lazy initialization.

Example:
    from nexus3.provider.registry import ProviderRegistry
    from nexus3.config.schema import Config

    config = Config(...)
    registry = ProviderRegistry(config)

    # Get provider for a model (lazy-created on first access)
    resolved = config.resolve_model("haiku")
    provider = registry.get(resolved.provider_name, resolved.model_id)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexus3.provider import create_provider

if TYPE_CHECKING:
    from nexus3.config.schema import Config
    from nexus3.core.interfaces import AsyncProvider, RawLogCallback


class ProviderRegistry:
    """Manages multiple provider instances with lazy initialization.

    Providers are created on first access to avoid connecting to unused
    APIs at startup. The registry maintains a cache of created providers
    keyed by provider_name:model_id.

    Attributes:
        _config: The global NEXUS3 configuration.
        _raw_log: Optional callback for raw API logging.
        _providers: Cache of created provider instances.

    Example:
        registry = ProviderRegistry(config)

        # Get provider for a model (lazy-created)
        resolved = config.resolve_model("haiku")
        provider = registry.get(resolved.provider_name, resolved.model_id)

        # Send request
        response = await provider.complete(messages, tools)
    """

    def __init__(
        self,
        config: "Config",
        raw_log: "RawLogCallback | None" = None,
    ) -> None:
        """Initialize the provider registry.

        Args:
            config: The global NEXUS3 configuration.
            raw_log: Optional callback for raw API request/response logging.
        """
        self._config = config
        self._raw_log = raw_log
        self._providers: dict[str, AsyncProvider] = {}

    def get(
        self,
        provider_name: str,
        model_id: str,
        reasoning: bool = False,
    ) -> "AsyncProvider":
        """Get or create a provider for a specific model.

        Providers are lazily created on first access and cached by
        provider_name:model_id.

        Args:
            provider_name: Provider name from config.providers.
            model_id: The model ID to use for API requests.
            reasoning: Whether to enable extended thinking/reasoning.

        Returns:
            AsyncProvider instance for the provider/model combination.

        Raises:
            KeyError: If provider name not found in config.

        Example:
            provider = registry.get("openrouter", "anthropic/claude-haiku-4.5")
        """
        cache_key = f"{provider_name}:{model_id}"

        if cache_key not in self._providers:
            provider_config = self._config.get_provider_config(provider_name)
            self._providers[cache_key] = create_provider(
                provider_config, model_id, self._raw_log, reasoning
            )
        return self._providers[cache_key]

    def get_for_model(self, alias: str | None = None) -> "AsyncProvider":
        """Get the appropriate provider for a model alias.

        Resolves the model alias to determine which provider and model_id
        to use, then returns (or creates) that provider.

        Args:
            alias: Model alias. If None, uses default_model from config.

        Returns:
            AsyncProvider instance for the model's provider.

        Example:
            # Get provider for default model
            provider = registry.get_for_model()

            # Get provider for specific model alias
            provider = registry.get_for_model("haiku-native")
        """
        resolved = self._config.resolve_model(alias)
        return self.get(resolved.provider_name, resolved.model_id, resolved.reasoning)

    def set_raw_log_callback(self, callback: "RawLogCallback | None") -> None:
        """Set or clear the raw logging callback on all providers.

        Updates the callback on all existing provider instances. New providers
        created after this call will also use this callback.

        Args:
            callback: The callback to set, or None to disable raw logging.
        """
        self._raw_log = callback
        for provider in self._providers.values():
            if hasattr(provider, "set_raw_log_callback"):
                provider.set_raw_log_callback(callback)

    def clear_cache(self) -> None:
        """Clear the provider cache.

        Forces all providers to be recreated on next access. Useful for
        testing or when configuration changes.
        """
        self._providers.clear()

    @property
    def cached_providers(self) -> list[str]:
        """List cache keys of currently cached (instantiated) providers.

        Returns:
            List of provider:model_id keys that have been accessed and cached.
        """
        return list(self._providers.keys())
