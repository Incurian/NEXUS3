"""Tests for provider HTTP client lifecycle management (G1).

These tests verify that:
1. BaseProvider lazily creates HTTP clients
2. Clients are reused across requests
3. aclose() properly closes clients
4. ProviderRegistry closes all providers on aclose()
5. Windows certifi fallback works (SSL cert bundle missing)
"""

import os
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.provider import OpenRouterProvider
from nexus3.provider.registry import ProviderRegistry


class TestProviderClientLifecycle:
    """Tests for BaseProvider HTTP client lifecycle."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_LIFECYCLE_KEY")
        os.environ["TEST_LIFECYCLE_KEY"] = "test-key"
        try:
            provider = OpenRouterProvider(config, "test-model")
        finally:
            os.environ.pop("TEST_LIFECYCLE_KEY", None)
        return provider

    def test_provider_creates_client_lazily(self, provider: OpenRouterProvider) -> None:
        """Client is None until first request."""
        # Initially, client should be None (lazy initialization)
        assert provider._client is None

    @pytest.mark.asyncio
    async def test_ensure_client_creates_client(self, provider: OpenRouterProvider) -> None:
        """_ensure_client() creates client on first call."""
        assert provider._client is None

        client = await provider._ensure_client()

        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        assert provider._client is client

        # Clean up
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_provider_reuses_client(self, provider: OpenRouterProvider) -> None:
        """Same client instance is reused across multiple calls."""
        # First call creates client
        client1 = await provider._ensure_client()

        # Second call returns same client
        client2 = await provider._ensure_client()

        assert client1 is client2
        assert provider._client is client1

        # Clean up
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_provider_aclose_closes_client(self, provider: OpenRouterProvider) -> None:
        """aclose() closes the httpx client."""
        # Create client
        client = await provider._ensure_client()
        assert provider._client is not None

        # Close should set _client to None
        await provider.aclose()

        assert provider._client is None

    @pytest.mark.asyncio
    async def test_provider_aclose_idempotent(self, provider: OpenRouterProvider) -> None:
        """Multiple aclose() calls are safe."""
        # Create client
        await provider._ensure_client()

        # First close
        await provider.aclose()
        assert provider._client is None

        # Second close should not raise
        await provider.aclose()
        assert provider._client is None

        # Third close with no client ever created
        provider2_config = ProviderConfig(api_key_env="TEST_LIFECYCLE_KEY2")
        os.environ["TEST_LIFECYCLE_KEY2"] = "test-key"
        try:
            provider2 = OpenRouterProvider(provider2_config, "test-model")
        finally:
            os.environ.pop("TEST_LIFECYCLE_KEY2", None)

        # Close without ever creating client
        await provider2.aclose()
        assert provider2._client is None

    @pytest.mark.asyncio
    async def test_aclose_actually_closes_httpx_client(self, provider: OpenRouterProvider) -> None:
        """Verify that aclose() actually calls client.aclose()."""
        # Create client
        client = await provider._ensure_client()

        # Mock the client's aclose method
        client.aclose = AsyncMock()

        # Close provider
        await provider.aclose()

        # Verify client.aclose() was called
        client.aclose.assert_called_once()


class TestProviderRegistryLifecycle:
    """Tests for ProviderRegistry cleanup."""

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """Create a mock config for registry testing."""
        config = MagicMock()

        # Mock get_provider_config to return valid config
        provider_config = ProviderConfig(api_key_env="TEST_REGISTRY_KEY")
        config.get_provider_config.return_value = provider_config

        return config

    @pytest.fixture
    def registry(self, mock_config: MagicMock) -> ProviderRegistry:
        """Create a registry for testing."""
        os.environ["TEST_REGISTRY_KEY"] = "test-key"
        return ProviderRegistry(mock_config)

    def teardown_method(self) -> None:
        """Clean up env vars after each test."""
        os.environ.pop("TEST_REGISTRY_KEY", None)

    @pytest.mark.asyncio
    async def test_registry_aclose_closes_all_providers(
        self, registry: ProviderRegistry
    ) -> None:
        """Registry cleanup closes all cached providers."""
        # Create two providers
        provider1 = registry.get("openrouter", "model-1")
        provider2 = registry.get("openrouter", "model-2")

        # Ensure clients are created
        await provider1._ensure_client()
        await provider2._ensure_client()

        # Mock aclose on both providers
        provider1.aclose = AsyncMock()
        provider2.aclose = AsyncMock()

        # Close registry
        await registry.aclose()

        # Both providers should have been closed
        provider1.aclose.assert_called_once()
        provider2.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_registry_aclose_clears_cache(self, registry: ProviderRegistry) -> None:
        """Registry cache is empty after aclose()."""
        # Create a provider
        registry.get("openrouter", "model-1")
        assert len(registry.cached_providers) == 1

        # Close registry
        await registry.aclose()

        # Cache should be empty
        assert len(registry.cached_providers) == 0

    @pytest.mark.asyncio
    async def test_registry_aclose_handles_provider_errors(
        self, registry: ProviderRegistry
    ) -> None:
        """Errors in one provider don't stop closing others."""
        # Create two providers
        provider1 = registry.get("openrouter", "model-1")
        provider2 = registry.get("openrouter", "model-2")

        # First provider raises error on close
        provider1.aclose = AsyncMock(side_effect=RuntimeError("Close failed"))
        # Second provider closes normally
        provider2.aclose = AsyncMock()

        # Close registry should not raise despite provider1 error
        await registry.aclose()

        # Both providers should have been attempted
        provider1.aclose.assert_called_once()
        provider2.aclose.assert_called_once()

        # Cache should still be cleared
        assert len(registry.cached_providers) == 0

    @pytest.mark.asyncio
    async def test_registry_aclose_idempotent(self, registry: ProviderRegistry) -> None:
        """Multiple aclose() calls are safe."""
        # Create a provider
        provider = registry.get("openrouter", "model-1")
        provider.aclose = AsyncMock()

        # First close
        await registry.aclose()
        assert len(registry.cached_providers) == 0

        # Second close should not raise
        await registry.aclose()
        assert len(registry.cached_providers) == 0

    @pytest.mark.asyncio
    async def test_registry_aclose_handles_provider_without_aclose(
        self, mock_config: MagicMock
    ) -> None:
        """Registry handles providers that don't have aclose method."""
        # Create a mock provider without aclose
        mock_provider = MagicMock()
        del mock_provider.aclose  # Remove the method

        registry = ProviderRegistry(mock_config)
        registry._providers["test:model"] = mock_provider

        # Close should not raise even though provider has no aclose
        await registry.aclose()

        # Cache should be cleared
        assert len(registry.cached_providers) == 0


class TestCertifiFallback:
    """Tests for Windows certifi fallback (SSL cert bundle missing)."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_CERTIFI_KEY")
        os.environ["TEST_CERTIFI_KEY"] = "test-key"
        try:
            provider = OpenRouterProvider(config, "test-model")
        finally:
            os.environ.pop("TEST_CERTIFI_KEY", None)
        return provider

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_certifi_fallback_on_file_not_found(
        self, provider: OpenRouterProvider
    ) -> None:
        """Provider falls back to system certs when certifi bundle is missing."""
        # Mock httpx.AsyncClient to raise FileNotFoundError on first call (simulating
        # missing certifi bundle), then succeed on second call with ssl.SSLContext
        call_count = 0
        original_init = httpx.AsyncClient.__init__

        def patched_init(self: httpx.AsyncClient, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1 and not isinstance(kwargs.get("verify"), ssl.SSLContext):
                raise FileNotFoundError("certifi bundle not found")
            return original_init(self, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            # Should not raise - should fall back to SSLContext
            client = await provider._ensure_client()

            assert client is not None
            assert isinstance(client, httpx.AsyncClient)
            # Two calls: first fails, second succeeds with SSLContext
            assert call_count == 2

        # Clean up
        await provider.aclose()

    @pytest.mark.asyncio
    @pytest.mark.windows_mock
    async def test_certifi_fallback_uses_ssl_context(
        self, provider: OpenRouterProvider
    ) -> None:
        """Fallback creates client with ssl.SSLContext for system certs."""
        created_with_ssl_context = False

        def patched_init(self: httpx.AsyncClient, **kwargs: object) -> None:
            nonlocal created_with_ssl_context
            if isinstance(kwargs.get("verify"), ssl.SSLContext):
                created_with_ssl_context = True
                raise FileNotFoundError("Stop here to verify SSLContext was used")
            raise FileNotFoundError("certifi bundle not found")

        with patch.object(httpx.AsyncClient, "__init__", patched_init):
            with pytest.raises(FileNotFoundError, match="Stop here"):
                await provider._ensure_client()

            # Verify that on fallback, SSLContext was passed
            assert created_with_ssl_context
