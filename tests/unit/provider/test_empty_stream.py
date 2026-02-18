"""Tests for empty stream response handling in both providers.

Verifies:
- Event counting and diagnostic logging
- Empty stream detection and warning
- finish_reason extraction
- on_stream_complete() called with correct summary
"""

import json
import os
import time
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.provider import OpenRouterProvider
from nexus3.provider.anthropic import AnthropicProvider


def _make_sse_response(lines: list[str], status_code: int = 200) -> httpx.Response:
    """Create a mock httpx.Response that yields SSE lines."""
    body = "\n".join(lines) + "\n"
    response = httpx.Response(
        status_code=status_code,
        content=body.encode(),
        headers={"content-type": "text/event-stream"},
        request=httpx.Request("POST", "https://test.example.com/v1/chat/completions"),
    )
    return response


@pytest.fixture
def openai_provider() -> OpenRouterProvider:
    config = ProviderConfig(api_key_env="TEST_EMPTY_STREAM_KEY")
    os.environ["TEST_EMPTY_STREAM_KEY"] = "test-key"
    try:
        provider = OpenRouterProvider(config, "test-model")
    finally:
        os.environ.pop("TEST_EMPTY_STREAM_KEY", None)
    return provider


@pytest.fixture
def anthropic_provider() -> AnthropicProvider:
    config = ProviderConfig(
        type="anthropic",
        api_key_env="TEST_EMPTY_STREAM_ANTH_KEY",
    )
    os.environ["TEST_EMPTY_STREAM_ANTH_KEY"] = "test-key"
    try:
        provider = AnthropicProvider(config, "test-model")
    finally:
        os.environ.pop("TEST_EMPTY_STREAM_ANTH_KEY", None)
    return provider


class TestOpenAIEmptyStream:
    """Empty stream handling for OpenAI-compatible providers."""

    @pytest.mark.asyncio
    async def test_empty_stream_yields_stream_complete(
        self, openai_provider: OpenRouterProvider
    ) -> None:
        """Empty SSE body (only [DONE]) still yields StreamComplete."""
        response = _make_sse_response(["data: [DONE]"])
        events = []
        async for event in openai_provider._parse_stream(response):
            events.append(event)

        assert len(events) == 1
        from nexus3.core.types import StreamComplete
        assert isinstance(events[0], StreamComplete)
        assert events[0].message.content == ""
        assert events[0].message.tool_calls == ()

    @pytest.mark.asyncio
    async def test_completely_empty_stream(
        self, openai_provider: OpenRouterProvider
    ) -> None:
        """Completely empty body (no [DONE]) still yields StreamComplete."""
        response = _make_sse_response([])
        events = []
        async for event in openai_provider._parse_stream(response):
            events.append(event)

        assert len(events) == 1
        from nexus3.core.types import StreamComplete
        assert isinstance(events[0], StreamComplete)
        assert events[0].message.content == ""

    @pytest.mark.asyncio
    async def test_event_count_tracked(
        self, openai_provider: OpenRouterProvider
    ) -> None:
        """Events are counted correctly."""
        raw_log = MagicMock()
        openai_provider._raw_log = raw_log

        chunk1 = json.dumps({
            "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]
        })
        chunk2 = json.dumps({
            "choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]
        })
        response = _make_sse_response([
            f"data: {chunk1}",
            f"data: {chunk2}",
            "data: [DONE]",
        ])

        events = []
        async for event in openai_provider._parse_stream(response):
            events.append(event)

        # on_stream_complete should have been called
        raw_log.on_stream_complete.assert_called_once()
        summary = raw_log.on_stream_complete.call_args[0][0]
        assert summary["event_count"] == 2
        assert summary["content_length"] == 11  # "Hello world"
        assert summary["received_done"] is True
        assert summary["finish_reason"] == "stop"
        assert summary["http_status"] == 200
        assert summary["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_finish_reason_extracted(
        self, openai_provider: OpenRouterProvider
    ) -> None:
        """finish_reason is extracted from the final chunk."""
        raw_log = MagicMock()
        openai_provider._raw_log = raw_log

        chunk = json.dumps({
            "choices": [{"delta": {"content": "done"}, "finish_reason": "length"}]
        })
        response = _make_sse_response([f"data: {chunk}", "data: [DONE]"])

        async for _ in openai_provider._parse_stream(response):
            pass

        summary = raw_log.on_stream_complete.call_args[0][0]
        assert summary["finish_reason"] == "length"

    @pytest.mark.asyncio
    async def test_empty_stream_logs_warning(
        self, openai_provider: OpenRouterProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty stream triggers a warning log."""
        response = _make_sse_response(["data: [DONE]"])
        with caplog.at_level("WARNING", logger="nexus3.provider.openai_compat"):
            async for _ in openai_provider._parse_stream(response):
                pass

        assert any("Empty stream response" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_done_marker_still_logs(
        self, openai_provider: OpenRouterProvider
    ) -> None:
        """Stream ending without [DONE] still gets logged."""
        raw_log = MagicMock()
        openai_provider._raw_log = raw_log

        chunk = json.dumps({
            "choices": [{"delta": {"content": "hi"}, "finish_reason": None}]
        })
        response = _make_sse_response([f"data: {chunk}"])

        async for _ in openai_provider._parse_stream(response):
            pass

        summary = raw_log.on_stream_complete.call_args[0][0]
        assert summary["received_done"] is False
        assert summary["event_count"] == 1


class TestAnthropicEmptyStream:
    """Empty stream handling for Anthropic provider."""

    @pytest.mark.asyncio
    async def test_empty_stream_yields_stream_complete(
        self, anthropic_provider: AnthropicProvider
    ) -> None:
        """Empty body (no message_stop) still yields StreamComplete."""
        response = _make_sse_response([])
        events = []
        async for event in anthropic_provider._parse_stream(response):
            events.append(event)

        assert len(events) == 1
        from nexus3.core.types import StreamComplete
        assert isinstance(events[0], StreamComplete)
        assert events[0].message.content == ""

    @pytest.mark.asyncio
    async def test_message_delta_stop_reason_extracted(
        self, anthropic_provider: AnthropicProvider
    ) -> None:
        """stop_reason from message_delta event is extracted."""
        raw_log = MagicMock()
        anthropic_provider._raw_log = raw_log

        lines = [
            'event: message_start',
            'data: {"type": "message_start", "message": {"usage": {}}}',
            '',
            'event: content_block_start',
            'data: {"type": "content_block_start", "content_block": {"type": "text", "text": ""}}',
            '',
            'event: content_block_delta',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}',
            '',
            'event: content_block_stop',
            'data: {"type": "content_block_stop"}',
            '',
            'event: message_delta',
            'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}',
            '',
            'event: message_stop',
            'data: {"type": "message_stop"}',
        ]
        response = _make_sse_response(lines)

        events = []
        async for event in anthropic_provider._parse_stream(response):
            events.append(event)

        summary = raw_log.on_stream_complete.call_args[0][0]
        assert summary["finish_reason"] == "end_turn"
        assert summary["received_done"] is True
        assert summary["content_length"] == 5  # "Hello"

    @pytest.mark.asyncio
    async def test_empty_stream_logs_warning(
        self, anthropic_provider: AnthropicProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty Anthropic stream triggers a warning log."""
        response = _make_sse_response([])
        with caplog.at_level("WARNING", logger="nexus3.provider.anthropic"):
            async for _ in anthropic_provider._parse_stream(response):
                pass

        assert any("Empty stream response" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_event_count_tracked(
        self, anthropic_provider: AnthropicProvider
    ) -> None:
        """Events are counted correctly for Anthropic."""
        raw_log = MagicMock()
        anthropic_provider._raw_log = raw_log

        lines = [
            'event: message_start',
            'data: {"type": "message_start", "message": {"usage": {}}}',
            '',
            'event: message_stop',
            'data: {"type": "message_stop"}',
        ]
        response = _make_sse_response(lines)

        async for _ in anthropic_provider._parse_stream(response):
            pass

        summary = raw_log.on_stream_complete.call_args[0][0]
        assert summary["event_count"] == 2  # message_start + message_stop
