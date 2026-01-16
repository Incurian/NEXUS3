"""Tests for BL-1: max_retries=0 should make exactly one attempt.

When max_retries is set to 0, the retry loop should still make one initial attempt
rather than failing immediately with "Request failed unexpectedly".
"""

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.core.errors import ProviderError
from nexus3.provider import OpenRouterProvider


class TestMaxRetriesZero:
    """Tests for max_retries=0 behavior."""

    @pytest.fixture
    def provider_config(self) -> ProviderConfig:
        """Create a provider config with max_retries=0."""
        return ProviderConfig(
            api_key_env="TEST_RETRY_ZERO_KEY",
            max_retries=0,
        )

    @pytest.fixture
    def provider(self, provider_config: ProviderConfig) -> OpenRouterProvider:
        """Create a provider with max_retries=0."""
        os.environ["TEST_RETRY_ZERO_KEY"] = "test-key"
        try:
            provider = OpenRouterProvider(provider_config, "test-model")
        finally:
            os.environ.pop("TEST_RETRY_ZERO_KEY", None)
        return provider

    @pytest.mark.asyncio
    async def test_max_retries_zero_makes_one_attempt(
        self, provider: OpenRouterProvider
    ) -> None:
        """With max_retries=0, exactly one request attempt is made."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello", "role": "assistant"}}]
        }

        with patch.object(provider, "_ensure_client") as mock_ensure:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_ensure.return_value = mock_client

            # This should succeed with one attempt
            result = await provider._make_request("http://localhost/test", {"test": 1})

            # Verify exactly one request was made
            assert mock_client.post.call_count == 1
            assert result == mock_response.json.return_value

    @pytest.mark.asyncio
    async def test_max_retries_zero_no_retry_on_error(
        self, provider: OpenRouterProvider
    ) -> None:
        """With max_retries=0, no retry on 503 error."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.content = b"Service Unavailable"

        with patch.object(provider, "_ensure_client") as mock_ensure:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_ensure.return_value = mock_client

            # This should fail after one attempt (no retries)
            with pytest.raises(ProviderError) as exc_info:
                await provider._make_request("http://localhost/test", {"test": 1})

            # Verify exactly one request was made (no retries)
            assert mock_client.post.call_count == 1
            assert "503" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_max_retries_zero_success(
        self, provider: OpenRouterProvider
    ) -> None:
        """With max_retries=0, successful requests work normally."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "success"}

        with patch.object(provider, "_ensure_client") as mock_ensure:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_ensure.return_value = mock_client

            result = await provider._make_request("http://localhost/test", {"test": 1})

            assert result == {"data": "success"}
            assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_zero_streaming(
        self, provider: OpenRouterProvider
    ) -> None:
        """With max_retries=0, streaming requests also make one attempt."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        # Create a proper async context manager for stream
        async_context_manager = AsyncMock()
        async_context_manager.__aenter__.return_value = mock_response
        async_context_manager.__aexit__.return_value = None

        with patch.object(provider, "_ensure_client") as mock_ensure:
            mock_client = MagicMock()
            mock_client.stream.return_value = async_context_manager
            mock_ensure.return_value = mock_client

            # Consume the async generator
            responses = []
            async for response in provider._make_streaming_request(
                "http://localhost/test", {"test": 1}
            ):
                responses.append(response)

            # Verify exactly one request was made
            assert mock_client.stream.call_count == 1
            assert len(responses) == 1
            assert responses[0] is mock_response


class TestMaxRetriesComparison:
    """Compare behavior between max_retries=0 and max_retries=1."""

    @pytest.fixture
    def config_zero_retries(self) -> ProviderConfig:
        """Config with max_retries=0 (1 attempt total)."""
        return ProviderConfig(
            api_key_env="TEST_RETRY_CMP_KEY",
            max_retries=0,
        )

    @pytest.fixture
    def config_one_retry(self) -> ProviderConfig:
        """Config with max_retries=1 (2 attempts total)."""
        return ProviderConfig(
            api_key_env="TEST_RETRY_CMP_KEY",
            max_retries=1,
        )

    @pytest.mark.asyncio
    async def test_zero_vs_one_retry_on_503(
        self,
        config_zero_retries: ProviderConfig,
        config_one_retry: ProviderConfig,
    ) -> None:
        """max_retries=0 makes 1 attempt, max_retries=1 makes 2 attempts."""
        os.environ["TEST_RETRY_CMP_KEY"] = "test-key"
        try:
            provider_zero = OpenRouterProvider(config_zero_retries, "test-model")
            provider_one = OpenRouterProvider(config_one_retry, "test-model")
        finally:
            os.environ.pop("TEST_RETRY_CMP_KEY", None)

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.content = b"Service Unavailable"

        # Test provider with max_retries=0
        with patch.object(provider_zero, "_ensure_client") as mock_ensure:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_ensure.return_value = mock_client

            with pytest.raises(ProviderError):
                await provider_zero._make_request("http://localhost/test", {})

            # Should make exactly 1 attempt
            assert mock_client.post.call_count == 1

        # Test provider with max_retries=1
        with (
            patch.object(provider_one, "_ensure_client") as mock_ensure,
            patch("asyncio.sleep", new_callable=AsyncMock),  # Skip retry delay
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_ensure.return_value = mock_client

            with pytest.raises(ProviderError):
                await provider_one._make_request("http://localhost/test", {})

            # Should make exactly 2 attempts (1 initial + 1 retry)
            assert mock_client.post.call_count == 2
