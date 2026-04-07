"""Focused keep-alive stale-connection recovery tests for provider base paths."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.core.errors import ProviderError
from nexus3.core.types import ContentDelta, Message, Role
from nexus3.provider import OpenRouterProvider


def _make_provider(max_retries: int) -> OpenRouterProvider:
    """Create a provider with explicit retry budget for recovery tests."""
    config = ProviderConfig(
        api_key_env="TEST_KEEPALIVE_RECOVERY_KEY",
        max_retries=max_retries,
    )
    os.environ["TEST_KEEPALIVE_RECOVERY_KEY"] = "test-key"
    try:
        provider = OpenRouterProvider(config, "test-model")
    finally:
        os.environ.pop("TEST_KEEPALIVE_RECOVERY_KEY", None)
    return provider


class TestKeepAliveRecovery:
    """Stale/reused connection recovery behavior in provider request paths."""

    @pytest.mark.asyncio
    async def test_non_streaming_retries_after_stale_connection_error(self) -> None:
        """Non-streaming retries once with fresh client after stale transport failure."""
        provider = _make_provider(max_retries=1)
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"ok": True}

        stale_error = httpx.RemoteProtocolError(
            "Server disconnected without sending a response."
        )
        mock_client = AsyncMock()
        mock_client.post.side_effect = [stale_error, success_response]

        with (
            patch.object(provider, "_ensure_client", new=AsyncMock(return_value=mock_client)),
            patch.object(provider, "aclose", new_callable=AsyncMock) as mock_aclose,
        ):
            result = await provider._make_request(
                "https://test.example.com/v1/chat/completions",
                {"model": "test-model"},
            )

        assert result == {"ok": True}
        assert mock_client.post.call_count == 2
        mock_aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_streaming_retries_after_stale_connection_error(self) -> None:
        """Streaming retries once with fresh client after stale transport failure."""
        provider = _make_provider(max_retries=1)
        stale_error = httpx.RemoteProtocolError(
            "Server disconnected without sending a response."
        )

        success_response = MagicMock()
        success_response.status_code = 200
        success_context_manager = AsyncMock()
        success_context_manager.__aenter__.return_value = success_response
        success_context_manager.__aexit__.return_value = None

        mock_client = MagicMock()
        mock_client.stream.side_effect = [stale_error, success_context_manager]

        with (
            patch.object(provider, "_ensure_client", new=AsyncMock(return_value=mock_client)),
            patch.object(provider, "aclose", new_callable=AsyncMock) as mock_aclose,
        ):
            responses = []
            async for response in provider._make_streaming_request(
                "https://test.example.com/v1/chat/completions",
                {"model": "test-model", "stream": True},
            ):
                responses.append(response)

        assert responses == [success_response]
        assert mock_client.stream.call_count == 2
        mock_aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_stale_http_error_is_fail_fast(self) -> None:
        """Non-classified HTTP errors remain fail-fast and do not trigger stale recovery."""
        provider = _make_provider(max_retries=3)
        non_stale_error = httpx.HTTPError("synthetic non-stale transport error")

        mock_client = AsyncMock()
        mock_client.post.side_effect = non_stale_error

        with (
            patch.object(provider, "_ensure_client", new=AsyncMock(return_value=mock_client)),
            patch.object(provider, "aclose", new_callable=AsyncMock) as mock_aclose,
        ):
            with pytest.raises(ProviderError, match="HTTP error occurred"):
                await provider._make_request(
                    "https://test.example.com/v1/chat/completions",
                    {"model": "test-model"},
                )

        assert mock_client.post.call_count == 1
        mock_aclose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_body_error_before_first_event_raises_provider_error(self) -> None:
        """Streaming body transport failures surface as typed provider errors."""
        provider = _make_provider(max_retries=1)
        response = MagicMock()

        async def make_streaming_request(
            url: str, body: dict[str, object]
        ) -> AsyncIterator[MagicMock]:
            yield response

        async def parse_stream(
            stream_response: object,
        ) -> AsyncIterator[object]:
            assert stream_response is response
            if stream_response is None:
                yield ContentDelta(text="")
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body "
                "(incomplete chunked read)"
            )

        with (
            patch.object(
                provider,
                "_build_endpoint",
                return_value="https://test.example.com/v1/chat/completions",
            ),
            patch.object(
                provider,
                "_build_request_body",
                return_value={"model": "test-model", "stream": True},
            ),
            patch.object(provider, "_make_streaming_request", side_effect=make_streaming_request),
            patch.object(provider, "_parse_stream", side_effect=parse_stream),
        ):
            with pytest.raises(
                ProviderError,
                match="Streaming response failed before any data was received",
            ):
                async for _ in provider.stream(
                    [Message(role=Role.USER, content="hello")],
                ):
                    pass

    @pytest.mark.asyncio
    async def test_stream_body_error_after_partial_output_raises_provider_error(self) -> None:
        """Mid-stream body transport failures mention partial streamed output."""
        provider = _make_provider(max_retries=1)
        response = MagicMock()

        async def make_streaming_request(
            url: str, body: dict[str, object]
        ) -> AsyncIterator[MagicMock]:
            yield response

        async def parse_stream(
            stream_response: object,
        ) -> AsyncIterator[object]:
            assert stream_response is response
            yield ContentDelta(text="partial")
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body "
                "(incomplete chunked read)"
            )

        with (
            patch.object(
                provider,
                "_build_endpoint",
                return_value="https://test.example.com/v1/chat/completions",
            ),
            patch.object(
                provider,
                "_build_request_body",
                return_value={"model": "test-model", "stream": True},
            ),
            patch.object(provider, "_make_streaming_request", side_effect=make_streaming_request),
            patch.object(provider, "_parse_stream", side_effect=parse_stream),
        ):
            stream = provider.stream([Message(role=Role.USER, content="hello")])
            first = await anext(stream)
            assert first == ContentDelta(text="partial")
            with pytest.raises(
                ProviderError,
                match="Partial output may have been displayed; retry the request",
            ):
                await anext(stream)

    @pytest.mark.asyncio
    async def test_max_retries_zero_keeps_stale_recovery_disabled(self) -> None:
        """With max_retries=0, stale errors do not perform a recovery retry."""
        provider = _make_provider(max_retries=0)
        stale_error = httpx.RemoteProtocolError(
            "Server disconnected without sending a response."
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = stale_error

        with (
            patch.object(provider, "_ensure_client", new=AsyncMock(return_value=mock_client)),
            patch.object(provider, "aclose", new_callable=AsyncMock) as mock_aclose,
        ):
            with pytest.raises(ProviderError, match="HTTP error occurred"):
                await provider._make_request(
                    "https://test.example.com/v1/chat/completions",
                    {"model": "test-model"},
                )

        assert mock_client.post.call_count == 1
        mock_aclose.assert_not_awaited()
