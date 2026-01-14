"""Tests for the OpenRouter provider."""

import os
from unittest.mock import MagicMock

import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.core.errors import ProviderError
from nexus3.core.types import Message, Role
from nexus3.provider import OpenRouterProvider
from nexus3.provider.base import (
    MAX_RETRY_DELAY,
    MAX_RETRIES,
    RETRYABLE_STATUS_CODES,
)


class TestProviderInit:
    """Tests for provider initialization."""

    def test_init_missing_api_key(self) -> None:
        """Test that init raises ProviderError when API key env var not set."""
        config = ProviderConfig(api_key_env="NONEXISTENT_KEY_12345")
        # Ensure the env var doesn't exist
        os.environ.pop("NONEXISTENT_KEY_12345", None)

        with pytest.raises(ProviderError, match="API key not found"):
            OpenRouterProvider(config, "test-model")

    def test_init_with_api_key(self) -> None:
        """Test successful init when API key is set."""
        config = ProviderConfig(api_key_env="TEST_PROVIDER_KEY")
        os.environ["TEST_PROVIDER_KEY"] = "test-api-key-123"
        try:
            provider = OpenRouterProvider(config, "test-model")
            assert provider._api_key == "test-api-key-123"
            assert provider._model == "test-model"
        finally:
            del os.environ["TEST_PROVIDER_KEY"]

    def test_init_empty_api_key(self) -> None:
        """Test that init raises ProviderError when API key is empty."""
        config = ProviderConfig(api_key_env="EMPTY_KEY_VAR")
        os.environ["EMPTY_KEY_VAR"] = ""
        try:
            with pytest.raises(ProviderError, match="API key not found"):
                OpenRouterProvider(config, "test-model")
        finally:
            del os.environ["EMPTY_KEY_VAR"]


class TestRetryLogic:
    """Tests for retry logic."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_RETRY_KEY")
        os.environ["TEST_RETRY_KEY"] = "test-key"
        provider = OpenRouterProvider(config, "test-model")
        os.environ.pop("TEST_RETRY_KEY", None)
        return provider

    def test_calculate_retry_delay_first_attempt(self, provider: OpenRouterProvider) -> None:
        """Test retry delay for first attempt (attempt=0)."""
        delay = provider._calculate_retry_delay(0)
        # backoff^0 + jitter(0-1) = 1.0 + 0-1 = 1-2
        assert 1.0 <= delay <= 2.0

    def test_calculate_retry_delay_second_attempt(self, provider: OpenRouterProvider) -> None:
        """Test retry delay for second attempt (attempt=1)."""
        delay = provider._calculate_retry_delay(1)
        # backoff^1 + jitter(0-1) = 1.5 + 0-1 = 1.5-2.5
        assert 1.5 <= delay <= 2.5

    def test_calculate_retry_delay_third_attempt(self, provider: OpenRouterProvider) -> None:
        """Test retry delay for third attempt (attempt=2)."""
        delay = provider._calculate_retry_delay(2)
        # backoff^2 + jitter(0-1) = 2.25 + 0-1 = 2.25-3.25
        assert 2.25 <= delay <= 3.25

    def test_calculate_retry_delay_capped(self, provider: OpenRouterProvider) -> None:
        """Test that retry delay is capped at MAX_RETRY_DELAY."""
        delay = provider._calculate_retry_delay(10)  # 2^10 = 1024, way over max
        assert delay <= MAX_RETRY_DELAY + 1  # +1 for jitter

    def test_is_retryable_error_429(self, provider: OpenRouterProvider) -> None:
        """Test that 429 (rate limit) is retryable."""
        assert provider._is_retryable_error(429) is True

    def test_is_retryable_error_500(self, provider: OpenRouterProvider) -> None:
        """Test that 500 (server error) is retryable."""
        assert provider._is_retryable_error(500) is True

    def test_is_retryable_error_502(self, provider: OpenRouterProvider) -> None:
        """Test that 502 (bad gateway) is retryable."""
        assert provider._is_retryable_error(502) is True

    def test_is_retryable_error_503(self, provider: OpenRouterProvider) -> None:
        """Test that 503 (service unavailable) is retryable."""
        assert provider._is_retryable_error(503) is True

    def test_is_retryable_error_504(self, provider: OpenRouterProvider) -> None:
        """Test that 504 (gateway timeout) is retryable."""
        assert provider._is_retryable_error(504) is True

    def test_is_retryable_error_400(self, provider: OpenRouterProvider) -> None:
        """Test that 400 (bad request) is NOT retryable."""
        assert provider._is_retryable_error(400) is False

    def test_is_retryable_error_401(self, provider: OpenRouterProvider) -> None:
        """Test that 401 (unauthorized) is NOT retryable."""
        assert provider._is_retryable_error(401) is False

    def test_is_retryable_error_403(self, provider: OpenRouterProvider) -> None:
        """Test that 403 (forbidden) is NOT retryable."""
        assert provider._is_retryable_error(403) is False

    def test_is_retryable_error_404(self, provider: OpenRouterProvider) -> None:
        """Test that 404 (not found) is NOT retryable."""
        assert provider._is_retryable_error(404) is False

    def test_retryable_status_codes_constant(self) -> None:
        """Test that RETRYABLE_STATUS_CODES matches expected values."""
        assert RETRYABLE_STATUS_CODES == {429, 500, 502, 503, 504}


class TestMessageConversion:
    """Tests for message conversion."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_MSG_KEY")
        os.environ["TEST_MSG_KEY"] = "test-key"
        provider = OpenRouterProvider(config, "test-model")
        os.environ.pop("TEST_MSG_KEY", None)
        return provider

    def test_message_to_dict_user(self, provider: OpenRouterProvider) -> None:
        """Test converting a user message."""
        msg = Message(role=Role.USER, content="Hello")
        result = provider._message_to_dict(msg)
        assert result == {"role": "user", "content": "Hello"}

    def test_message_to_dict_assistant(self, provider: OpenRouterProvider) -> None:
        """Test converting an assistant message."""
        msg = Message(role=Role.ASSISTANT, content="Hi there")
        result = provider._message_to_dict(msg)
        assert result == {"role": "assistant", "content": "Hi there"}

    def test_message_to_dict_system(self, provider: OpenRouterProvider) -> None:
        """Test converting a system message."""
        msg = Message(role=Role.SYSTEM, content="You are helpful")
        result = provider._message_to_dict(msg)
        assert result == {"role": "system", "content": "You are helpful"}

    def test_message_to_dict_tool_response(self, provider: OpenRouterProvider) -> None:
        """Test converting a tool response message."""
        msg = Message(role=Role.TOOL, content="result data", tool_call_id="call_123")
        result = provider._message_to_dict(msg)
        assert result == {
            "role": "tool",
            "content": "result data",
            "tool_call_id": "call_123",
        }


class TestHeaders:
    """Tests for header building."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_HDR_KEY")
        os.environ["TEST_HDR_KEY"] = "my-api-key"
        provider = OpenRouterProvider(config, "test-model")
        os.environ.pop("TEST_HDR_KEY", None)
        return provider

    def test_build_headers(self, provider: OpenRouterProvider) -> None:
        """Test that headers are built correctly."""
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer my-api-key"
        assert headers["Content-Type"] == "application/json"
        # Note: HTTP-Referer is now added via extra_headers in config for OpenRouter,
        # not hardcoded in the base provider class


class TestRawLogCallback:
    """Tests for raw log callback."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_LOG_KEY")
        os.environ["TEST_LOG_KEY"] = "test-key"
        provider = OpenRouterProvider(config, "test-model")
        os.environ.pop("TEST_LOG_KEY", None)
        return provider

    def test_set_raw_log_callback(self, provider: OpenRouterProvider) -> None:
        """Test setting raw log callback."""
        callback = MagicMock()
        provider.set_raw_log_callback(callback)
        assert provider._raw_log is callback

    def test_clear_raw_log_callback(self, provider: OpenRouterProvider) -> None:
        """Test clearing raw log callback."""
        callback = MagicMock()
        provider.set_raw_log_callback(callback)
        provider.set_raw_log_callback(None)
        assert provider._raw_log is None


class TestConstants:
    """Tests for provider constants."""

    def test_max_retries(self) -> None:
        """Test MAX_RETRIES constant."""
        assert MAX_RETRIES == 3

    def test_max_retry_delay(self) -> None:
        """Test MAX_RETRY_DELAY constant."""
        assert MAX_RETRY_DELAY == 10.0
