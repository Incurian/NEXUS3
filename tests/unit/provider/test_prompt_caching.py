"""Tests for prompt caching support across providers."""

import pytest
from unittest.mock import MagicMock

from nexus3.config.schema import AuthMethod, ProviderConfig
from nexus3.core.types import Message, Role


class TestAnthropicCacheControl:
    """Test Anthropic cache_control injection."""

    def test_cache_control_injected_when_enabled(self):
        """P5.1: cache_control added to system prompt when prompt_caching=True."""
        from nexus3.provider.anthropic import AnthropicProvider

        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            prompt_caching=True,
        )
        provider = AnthropicProvider(config, model_id="claude-haiku-4-5")

        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)

        # System should be a list with cache_control
        assert isinstance(body["system"], list)
        assert len(body["system"]) == 1
        assert body["system"][0]["type"] == "text"
        assert body["system"][0]["text"] == "You are a helpful assistant."
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_control_not_injected_when_disabled(self):
        """P5.2: cache_control NOT added when prompt_caching=False."""
        from nexus3.provider.anthropic import AnthropicProvider

        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            prompt_caching=False,
        )
        provider = AnthropicProvider(config, model_id="claude-haiku-4-5")

        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)

        # System should be a plain string
        assert isinstance(body["system"], str)
        assert body["system"] == "You are a helpful assistant."

    def test_no_system_message_no_error(self):
        """No error when there's no system message."""
        from nexus3.provider.anthropic import AnthropicProvider

        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            prompt_caching=True,
        )
        provider = AnthropicProvider(config, model_id="claude-haiku-4-5")

        messages = [
            Message(role=Role.USER, content="Hello"),
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)

        # No system key should be present
        assert "system" not in body


class TestAnthropicCacheMetricsParsing:
    """Test Anthropic cache metrics parsing from responses."""

    def test_cache_metrics_parsed_from_response(self):
        """Cache creation and read tokens parsed from response."""
        from nexus3.provider.anthropic import AnthropicProvider

        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        )
        provider = AnthropicProvider(config, model_id="claude-haiku-4-5")

        # Simulate response with cache metrics
        response_data = {
            "content": [{"type": "text", "text": "Hello!"}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 25,
            },
        }

        # Should not raise - metrics are logged at DEBUG level
        message = provider._parse_response(response_data)
        assert message.content == "Hello!"

    def test_cache_metrics_missing_backwards_compat(self):
        """No error when cache metrics are missing (old API)."""
        from nexus3.provider.anthropic import AnthropicProvider

        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        )
        provider = AnthropicProvider(config, model_id="claude-haiku-4-5")

        # Simulate old API response without cache metrics
        response_data = {
            "content": [{"type": "text", "text": "Hello!"}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
            },
        }

        # Should not raise
        message = provider._parse_response(response_data)
        assert message.content == "Hello!"

    def test_usage_missing_backwards_compat(self):
        """No error when usage field is entirely missing."""
        from nexus3.provider.anthropic import AnthropicProvider

        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
        )
        provider = AnthropicProvider(config, model_id="claude-haiku-4-5")

        # Simulate response without usage at all
        response_data = {
            "content": [{"type": "text", "text": "Hello!"}],
        }

        # Should not raise
        message = provider._parse_response(response_data)
        assert message.content == "Hello!"


class TestOpenAICacheMetricsParsing:
    """Test OpenAI cached_tokens parsing."""

    def test_cached_tokens_parsed_when_present(self):
        """P5.3: cached_tokens parsed from response when present."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="gpt-4o")

        # Simulate response with cached_tokens
        response_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello!",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "prompt_tokens_details": {
                    "cached_tokens": 50,
                },
            },
        }

        # Should not raise - metrics are logged at DEBUG level
        message = provider._parse_response(response_data)
        assert message.content == "Hello!"

    def test_cached_tokens_missing_backwards_compat(self):
        """P5.4: No error when cached_tokens missing (old API)."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="gpt-4o")

        # Simulate old API response without cached_tokens
        response_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello!",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
            },
        }

        # Should not raise
        message = provider._parse_response(response_data)
        assert message.content == "Hello!"

    def test_prompt_tokens_details_missing_backwards_compat(self):
        """No error when prompt_tokens_details is missing."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="gpt-4o")

        # Simulate response without prompt_tokens_details
        response_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello!",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
            },
        }

        # Should not raise
        message = provider._parse_response(response_data)
        assert message.content == "Hello!"


class TestOpenRouterAnthropicDetection:
    """Test OpenRouter Anthropic model detection."""

    def test_openrouter_anthropic_detected(self):
        """P5.5: OpenRouter with Anthropic model detected correctly."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="anthropic/claude-sonnet-4")

        assert provider._is_openrouter_anthropic() is True

    def test_openrouter_anthropic_case_insensitive(self):
        """Detection is case-insensitive."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="ANTHROPIC/Claude-Sonnet-4")

        assert provider._is_openrouter_anthropic() is True

    def test_openrouter_openai_not_detected(self):
        """P5.6: OpenRouter with OpenAI model NOT detected as Anthropic."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="openai/gpt-4o")

        assert provider._is_openrouter_anthropic() is False

    def test_openrouter_other_model_not_detected(self):
        """OpenRouter with non-Anthropic model NOT detected."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="google/gemini-pro")

        assert provider._is_openrouter_anthropic() is False

    def test_direct_anthropic_not_detected_as_openrouter(self):
        """Direct Anthropic provider NOT detected as OpenRouter."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="anthropic",  # Not openrouter
            api_key_env="ANTHROPIC_API_KEY",
        )
        provider = OpenAICompatProvider(config, model_id="anthropic/claude-sonnet-4")

        assert provider._is_openrouter_anthropic() is False

    def test_direct_openai_not_detected(self):
        """Direct OpenAI provider NOT detected as OpenRouter Anthropic."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        )
        provider = OpenAICompatProvider(config, model_id="gpt-4o")

        assert provider._is_openrouter_anthropic() is False


class TestOpenRouterCacheControlInjection:
    """Test cache_control injection for OpenRouter Anthropic models."""

    def test_cache_control_injected_for_openrouter_anthropic(self):
        """cache_control added for OpenRouter + Anthropic model."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
            prompt_caching=True,
        )
        provider = OpenAICompatProvider(config, model_id="anthropic/claude-sonnet-4")

        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)

        # Find system message and verify cache_control
        system_msg = next(m for m in body["messages"] if m["role"] == "system")
        assert isinstance(system_msg["content"], list)
        assert len(system_msg["content"]) == 1
        assert system_msg["content"][0]["type"] == "text"
        assert system_msg["content"][0]["text"] == "You are a helpful assistant."
        assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_control_not_injected_for_openrouter_openai(self):
        """cache_control NOT added for OpenRouter + OpenAI model."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
            prompt_caching=True,
        )
        provider = OpenAICompatProvider(config, model_id="openai/gpt-4o")

        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)

        # System message should be plain string
        system_msg = next(m for m in body["messages"] if m["role"] == "system")
        assert isinstance(system_msg["content"], str)
        assert system_msg["content"] == "You are a helpful assistant."

    def test_cache_control_not_injected_when_disabled(self):
        """cache_control NOT added when prompt_caching=False."""
        from nexus3.provider.openai_compat import OpenAICompatProvider

        config = ProviderConfig(
            type="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            auth_method=AuthMethod.NONE,
            prompt_caching=False,
        )
        provider = OpenAICompatProvider(config, model_id="anthropic/claude-sonnet-4")

        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="Hello"),
        ]

        body = provider._build_request_body(messages, tools=None, stream=False)

        # System message should be plain string
        system_msg = next(m for m in body["messages"] if m["role"] == "system")
        assert isinstance(system_msg["content"], str)


class TestProviderConfigPromptCaching:
    """Test ProviderConfig prompt_caching field."""

    def test_prompt_caching_default_true(self):
        """prompt_caching defaults to True."""
        config = ProviderConfig(type="openai", api_key_env="TEST")
        assert config.prompt_caching is True

    def test_prompt_caching_explicit_false(self):
        """prompt_caching can be set to False."""
        config = ProviderConfig(type="openai", api_key_env="TEST", prompt_caching=False)
        assert config.prompt_caching is False

    def test_prompt_caching_explicit_true(self):
        """prompt_caching can be explicitly set to True."""
        config = ProviderConfig(type="openai", api_key_env="TEST", prompt_caching=True)
        assert config.prompt_caching is True
