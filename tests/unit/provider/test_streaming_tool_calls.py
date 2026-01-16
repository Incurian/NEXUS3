"""Tests for streaming tool call handling in OpenAI-compatible providers.

These tests verify:
1. BL-2: Tool call id/name are set once, not accumulated across deltas
2. BL-3: Invalid JSON arguments are logged and preserved, not silently replaced with {}
"""

import json
import logging
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.core.types import Message, Role, ToolCall
from nexus3.provider import OpenRouterProvider


class TestToolCallIdNameSetOnce:
    """BL-2: Test that tool call id/name are set once, not accumulated."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_STREAMING_KEY")
        os.environ["TEST_STREAMING_KEY"] = "test-key"
        try:
            provider = OpenRouterProvider(config, "test-model")
        finally:
            os.environ.pop("TEST_STREAMING_KEY", None)
        return provider

    @pytest.mark.asyncio
    async def test_tool_call_id_set_once(self, provider: OpenRouterProvider) -> None:
        """Tool call id is not duplicated if sent twice in deltas."""
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        seen_tool_indices: set[int] = set()

        # First delta with id
        event1 = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc123",
                        "function": {"name": "test_tool", "arguments": ""}
                    }]
                }
            }]
        }

        # Second delta repeating the same id (some providers do this)
        event2 = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc123",  # Duplicate!
                        "function": {"arguments": '{"foo": '}
                    }]
                }
            }]
        }

        # Process both events
        async for _ in provider._process_stream_event(event1, tool_calls_by_index, seen_tool_indices):
            pass
        async for _ in provider._process_stream_event(event2, tool_calls_by_index, seen_tool_indices):
            pass

        # ID should be set once, not "call_abc123call_abc123"
        assert tool_calls_by_index[0]["id"] == "call_abc123"

    @pytest.mark.asyncio
    async def test_tool_call_name_set_once(self, provider: OpenRouterProvider) -> None:
        """Tool call name is not duplicated if sent twice in deltas."""
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        seen_tool_indices: set[int] = set()

        # First delta with name
        event1 = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_xyz",
                        "function": {"name": "read_file", "arguments": ""}
                    }]
                }
            }]
        }

        # Second delta repeating the same name (some providers do this)
        event2 = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"name": "read_file", "arguments": '{"path": '}
                    }]
                }
            }]
        }

        # Process both events
        async for _ in provider._process_stream_event(event1, tool_calls_by_index, seen_tool_indices):
            pass
        async for _ in provider._process_stream_event(event2, tool_calls_by_index, seen_tool_indices):
            pass

        # Name should be set once, not "read_fileread_file"
        assert tool_calls_by_index[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_tool_call_arguments_accumulated(self, provider: OpenRouterProvider) -> None:
        """Tool call arguments ARE accumulated incrementally (this is correct)."""
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        seen_tool_indices: set[int] = set()

        # Arguments come in chunks during streaming
        events = [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "bash", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"com'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'mand": '}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"ls -la"}'}}]}}]},
        ]

        for event in events:
            async for _ in provider._process_stream_event(event, tool_calls_by_index, seen_tool_indices):
                pass

        # Arguments should be concatenated
        assert tool_calls_by_index[0]["arguments"] == '{"command": "ls -la"}'

    @pytest.mark.asyncio
    async def test_tool_call_id_name_args_independent(self, provider: OpenRouterProvider) -> None:
        """Verify that id/name set-once doesn't affect argument accumulation."""
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        seen_tool_indices: set[int] = set()

        # Real-world pattern: first chunk has id+name, subsequent have arguments
        events = [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_abc", "function": {"name": "write_file", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_abc", "function": {"name": "write_file", "arguments": '{"path'}}]}}]},  # Duplicates!
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '": "/tmp/test",'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "content": "hello"}'}}]}}]},
        ]

        for event in events:
            async for _ in provider._process_stream_event(event, tool_calls_by_index, seen_tool_indices):
                pass

        # ID and name set once (not duplicated)
        assert tool_calls_by_index[0]["id"] == "call_abc"
        assert tool_calls_by_index[0]["name"] == "write_file"
        # Arguments accumulated
        assert tool_calls_by_index[0]["arguments"] == '{"path": "/tmp/test", "content": "hello"}'


class TestInvalidJsonArgumentsPreserved:
    """BL-3: Test that invalid JSON arguments are logged and preserved."""

    @pytest.fixture
    def provider(self) -> OpenRouterProvider:
        """Create a provider for testing."""
        config = ProviderConfig(api_key_env="TEST_STREAMING_KEY2")
        os.environ["TEST_STREAMING_KEY2"] = "test-key"
        try:
            provider = OpenRouterProvider(config, "test-model")
        finally:
            os.environ.pop("TEST_STREAMING_KEY2", None)
        return provider

    def test_invalid_json_arguments_preserved_non_streaming(
        self, provider: OpenRouterProvider
    ) -> None:
        """Invalid JSON in non-streaming response preserves raw arguments."""
        tool_calls_data = [
            {
                "id": "call_123",
                "function": {
                    "name": "test_tool",
                    "arguments": "this is not { valid json"
                }
            }
        ]

        result = provider._parse_tool_calls(tool_calls_data)

        assert len(result) == 1
        # Should have _raw_arguments with the original invalid JSON
        assert "_raw_arguments" in result[0].arguments
        assert result[0].arguments["_raw_arguments"] == "this is not { valid json"

    def test_invalid_json_arguments_preserved_streaming(
        self, provider: OpenRouterProvider
    ) -> None:
        """Invalid JSON in streaming response preserves raw arguments."""
        tool_calls_by_index = {
            0: {
                "id": "call_456",
                "name": "bash",
                "arguments": '{"command": unquoted}'  # Invalid JSON
            }
        }

        result = provider._build_stream_complete("", tool_calls_by_index)

        assert len(result.message.tool_calls) == 1
        tc = result.message.tool_calls[0]
        # Should have _raw_arguments with the original invalid JSON
        assert "_raw_arguments" in tc.arguments
        assert tc.arguments["_raw_arguments"] == '{"command": unquoted}'

    def test_valid_json_arguments_parsed_normally(
        self, provider: OpenRouterProvider
    ) -> None:
        """Valid JSON arguments are parsed normally (sanity check)."""
        tool_calls_data = [
            {
                "id": "call_789",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "/etc/passwd", "limit": 100}'
                }
            }
        ]

        result = provider._parse_tool_calls(tool_calls_data)

        assert len(result) == 1
        assert result[0].arguments == {"path": "/etc/passwd", "limit": 100}
        assert "_raw_arguments" not in result[0].arguments

    def test_empty_arguments_default_to_empty_dict(
        self, provider: OpenRouterProvider
    ) -> None:
        """Empty arguments string results in empty dict (not error)."""
        tool_calls_by_index = {
            0: {
                "id": "call_empty",
                "name": "no_args_tool",
                "arguments": ""  # Empty
            }
        }

        result = provider._build_stream_complete("", tool_calls_by_index)

        assert len(result.message.tool_calls) == 1
        assert result.message.tool_calls[0].arguments == {}

    def test_invalid_json_logs_warning_non_streaming(
        self, provider: OpenRouterProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid JSON in non-streaming logs a warning."""
        tool_calls_data = [
            {
                "id": "call_log_test",
                "function": {
                    "name": "test",
                    "arguments": "broken json {"
                }
            }
        ]

        with caplog.at_level(logging.WARNING, logger="nexus3.provider.openai_compat"):
            provider._parse_tool_calls(tool_calls_data)

        # Should have logged a warning about the invalid JSON
        assert any("Failed to parse tool arguments JSON" in record.message for record in caplog.records)
        # Warning should contain truncated JSON (%.100s format)
        assert any("broken json" in record.message for record in caplog.records)

    def test_invalid_json_logs_warning_streaming(
        self, provider: OpenRouterProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid JSON in streaming logs a warning."""
        tool_calls_by_index = {
            0: {
                "id": "call_stream_log",
                "name": "test",
                "arguments": "not valid { json"
            }
        }

        with caplog.at_level(logging.WARNING, logger="nexus3.provider.openai_compat"):
            provider._build_stream_complete("", tool_calls_by_index)

        # Should have logged a warning
        assert any("Failed to parse tool arguments JSON" in record.message for record in caplog.records)

    def test_truncated_json_preserved_in_raw(
        self, provider: OpenRouterProvider
    ) -> None:
        """Truncated JSON (incomplete streaming) is preserved."""
        # Simulate truncated stream - JSON was cut off
        tool_calls_by_index = {
            0: {
                "id": "call_truncated",
                "name": "write_file",
                "arguments": '{"path": "/tmp/test", "content": "hello'  # Missing closing
            }
        }

        result = provider._build_stream_complete("", tool_calls_by_index)

        tc = result.message.tool_calls[0]
        assert "_raw_arguments" in tc.arguments
        assert tc.arguments["_raw_arguments"] == '{"path": "/tmp/test", "content": "hello'

    def test_very_long_invalid_json_truncated_in_log(
        self, provider: OpenRouterProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Very long invalid JSON is truncated in log message (%.100s)."""
        long_invalid_json = "x" * 500  # 500 chars of invalid JSON (use x to avoid counting in msg)

        tool_calls_data = [
            {
                "id": "call_long",
                "function": {
                    "name": "test",
                    "arguments": long_invalid_json
                }
            }
        ]

        with caplog.at_level(logging.WARNING, logger="nexus3.provider.openai_compat"):
            result = provider._parse_tool_calls(tool_calls_data)

        # Full raw should be preserved in result
        assert result[0].arguments["_raw_arguments"] == long_invalid_json

        # But log message should be truncated (%.100s means max 100 chars)
        for record in caplog.records:
            if "Failed to parse" in record.message:
                # The "x"s in the log should be at most 100
                assert record.message.count("x") <= 100
