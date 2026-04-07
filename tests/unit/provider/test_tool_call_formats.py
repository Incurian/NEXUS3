"""Focused tests for multi-format tool-call normalization."""

from __future__ import annotations

import os

import pytest

from nexus3.config.schema import ProviderConfig
from nexus3.core.types import ContentDelta, StreamComplete
from nexus3.provider import OpenRouterProvider
from nexus3.provider.tool_call_formats import StreamingToolCallAccumulator


@pytest.fixture
def provider() -> OpenRouterProvider:
    """Create a provider for parser-focused tests."""
    config = ProviderConfig(api_key_env="TEST_TOOL_FORMATS_KEY")
    os.environ["TEST_TOOL_FORMATS_KEY"] = "test-key"
    try:
        instance = OpenRouterProvider(config, "test-model")
    finally:
        os.environ.pop("TEST_TOOL_FORMATS_KEY", None)
    return instance


def test_openai_tool_call_accepts_object_arguments(provider: OpenRouterProvider) -> None:
    """OpenAI-compatible tool parsing should accept object-shaped arguments."""
    tool_calls = provider._parse_tool_calls(
        [
            {
                "id": "call_obj",
                "function": {
                    "name": "read_file",
                    "arguments": {"path": "/tmp/test.txt", "limit": 5},
                },
            }
        ]
    )

    assert tool_calls[0].arguments == {"path": "/tmp/test.txt", "limit": 5}
    assert tool_calls[0].argument_format == "object"


@pytest.mark.parametrize(
    ("raw_arguments", "expected_format", "expected_arguments"),
    [
        ("{'path': '/tmp/a.txt', 'limit': 5}", "python_dict", {"path": "/tmp/a.txt", "limit": 5}),
        ("path='/tmp/a.txt', limit=5", "python_kwargs", {"path": "/tmp/a.txt", "limit": 5}),
        (
            "read_file(path='/tmp/a.txt', limit=5)",
            "python_call",
            {"path": "/tmp/a.txt", "limit": 5},
        ),
    ],
)
def test_openai_tool_call_accepts_pythonic_arguments(
    provider: OpenRouterProvider,
    raw_arguments: str,
    expected_format: str,
    expected_arguments: dict[str, object],
) -> None:
    """Pythonic argument forms should normalize losslessly."""
    tool_calls = provider._parse_tool_calls(
        [
            {
                "id": "call_pythonic",
                "function": {
                    "name": "read_file",
                    "arguments": raw_arguments,
                },
            }
        ]
    )

    assert tool_calls[0].arguments == expected_arguments
    assert tool_calls[0].argument_format == expected_format


def test_openai_tool_call_python_call_mismatch_fails_closed(
    provider: OpenRouterProvider,
) -> None:
    """A mismatched Python call expression should stay unresolved."""
    tool_calls = provider._parse_tool_calls(
        [
            {
                "id": "call_mismatch",
                "function": {
                    "name": "read_file",
                    "arguments": "write_file(path='/tmp/a.txt')",
                },
            }
        ]
    )

    assert tool_calls[0].has_unresolved_arguments is True
    assert tool_calls[0].raw_arguments == "write_file(path='/tmp/a.txt')"


def test_responses_api_non_streaming_is_detected(provider: OpenRouterProvider) -> None:
    """Responses-style output arrays should normalize without a dedicated provider."""
    message = provider._parse_response(
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Checking now."}],
                },
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": '{"path": "/tmp/demo.txt"}',
                },
            ]
        }
    )

    assert message.content == "Checking now."
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].id == "call_1"
    assert message.tool_calls[0].arguments == {"path": "/tmp/demo.txt"}
    assert message.tool_calls[0].source_format == "openai_responses"


def test_responses_api_custom_tool_call_raw_input_fails_closed(
    provider: OpenRouterProvider,
) -> None:
    """Responses-style custom/raw tool input should preserve raw text."""
    message = provider._parse_response(
        {
            "output": [
                {
                    "type": "custom_tool_call",
                    "id": "ctc_1",
                    "call_id": "call_1",
                    "name": "read_file",
                    "input": "path=/tmp/demo.txt",
                }
            ]
        }
    )

    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].has_unresolved_arguments is True
    assert message.tool_calls[0].raw_arguments == "path=/tmp/demo.txt"


@pytest.mark.asyncio
async def test_streaming_openai_chat_object_arguments_supported(
    provider: OpenRouterProvider,
) -> None:
    """Chat-completions deltas may provide whole object arguments."""
    tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
    seen_tool_indices: set[int] = set()
    stream_key_to_index: dict[int | str, int] = {}

    event = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_obj_stream",
                            "function": {
                                "name": "read_file",
                                "arguments": {"path": "/tmp/demo.txt"},
                            },
                        }
                    ]
                }
            }
        ]
    }

    events = []
    async for stream_event in provider._process_stream_event(
        event,
        None,
        tool_calls_by_index,
        seen_tool_indices,
        stream_key_to_index,
    ):
        events.append(stream_event)

    complete = provider._build_stream_complete("", tool_calls_by_index)

    assert len(events) == 1
    assert complete.message.tool_calls[0].arguments == {"path": "/tmp/demo.txt"}


@pytest.mark.asyncio
async def test_streaming_responses_api_detected(provider: OpenRouterProvider) -> None:
    """Responses-style streaming events should accumulate text and tool args."""
    tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
    seen_tool_indices: set[int] = set()
    stream_key_to_index: dict[int | str, int] = {}

    added = {
        "type": "response.output_item.added",
        "output_index": 0,
        "item": {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "read_file",
        },
    }
    delta = {
        "type": "response.function_call_arguments.delta",
        "output_index": 0,
        "call_id": "call_1",
        "delta": '{"path": "/tmp/demo.txt"}',
    }
    text = {
        "type": "response.output_text.delta",
        "delta": "Checking now.",
    }

    streamed_content = ""
    for event in (added, delta, text):
        async for stream_event in provider._process_stream_event(
            event,
            event["type"],
            tool_calls_by_index,
            seen_tool_indices,
            stream_key_to_index,
        ):
            if isinstance(stream_event, ContentDelta):
                streamed_content += stream_event.text

    complete = provider._build_stream_complete(streamed_content, tool_calls_by_index)

    assert complete.message.content == "Checking now."
    assert len(complete.message.tool_calls) == 1
    assert complete.message.tool_calls[0].id == "call_1"
    assert complete.message.tool_calls[0].arguments == {"path": "/tmp/demo.txt"}


@pytest.mark.asyncio
async def test_streaming_responses_raw_arguments_preserved(
    provider: OpenRouterProvider,
) -> None:
    """Responses-style raw/freeform argument deltas should fail closed."""
    tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
    seen_tool_indices: set[int] = set()
    stream_key_to_index: dict[int | str, int] = {}

    added = {
        "type": "response.output_item.added",
        "output_index": 0,
        "item": {
            "type": "function_call",
            "id": "fc_2",
            "call_id": "call_2",
            "name": "read_file",
        },
    }
    delta = {
        "type": "response.function_call_arguments.delta",
        "output_index": 0,
        "call_id": "call_2",
        "delta": "path=/tmp/demo.txt",
    }

    for event in (added, delta):
        async for _ in provider._process_stream_event(
            event,
            event["type"],
            tool_calls_by_index,
            seen_tool_indices,
            stream_key_to_index,
        ):
            pass

    complete = provider._build_stream_complete("", tool_calls_by_index)
    tool_call = complete.message.tool_calls[0]

    assert tool_call.has_unresolved_arguments is True
    assert tool_call.raw_arguments == "path=/tmp/demo.txt"
    assert isinstance(complete, StreamComplete)


@pytest.mark.asyncio
async def test_streaming_responses_terminal_text_events_do_not_duplicate(
    provider: OpenRouterProvider,
) -> None:
    """Terminal Responses text snapshots should not re-emit prior content."""
    tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
    seen_tool_indices: set[int] = set()
    stream_key_to_index: dict[int | str, int] = {}
    responses_state = provider._new_responses_stream_state()

    events = (
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "item_id": "msg_1",
            "content_index": 0,
            "delta": "Hello",
        },
        {
            "type": "response.output_text.done",
            "output_index": 0,
            "item_id": "msg_1",
            "content_index": 0,
            "text": "Hello",
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "message",
                "id": "msg_1",
                "content": [{"type": "output_text", "text": "Hello"}],
            },
        },
    )

    streamed_content = ""
    for event in events:
        async for stream_event in provider._process_stream_event(
            event,
            event["type"],
            tool_calls_by_index,
            seen_tool_indices,
            stream_key_to_index,
            responses_state,
        ):
            if isinstance(stream_event, ContentDelta):
                streamed_content += stream_event.text

    assert streamed_content == "Hello"


@pytest.mark.asyncio
async def test_streaming_responses_terminal_tool_snapshot_replaces_delta_payload(
    provider: OpenRouterProvider,
) -> None:
    """Terminal tool snapshots should replace prior deltas, not append them."""
    tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
    seen_tool_indices: set[int] = set()
    stream_key_to_index: dict[int | str, int] = {}
    responses_state = provider._new_responses_stream_state()

    events = (
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "call_1",
                "name": "read_file",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "call_id": "call_1",
            "delta": '{"path": "/tmp/demo.txt"}',
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": '{"path": "/tmp/demo.txt"}',
            },
        },
    )

    for event in events:
        async for _ in provider._process_stream_event(
            event,
            event["type"],
            tool_calls_by_index,
            seen_tool_indices,
            stream_key_to_index,
            responses_state,
        ):
            pass

    complete = provider._build_stream_complete("", tool_calls_by_index)

    assert len(complete.message.tool_calls) == 1
    assert complete.message.tool_calls[0].id == "call_1"
    assert complete.message.tool_calls[0].arguments == {"path": "/tmp/demo.txt"}


@pytest.mark.asyncio
async def test_streaming_responses_output_index_zero_is_stable(
    provider: OpenRouterProvider,
) -> None:
    """`output_index=0` should not split a single tool call into two accumulators."""
    tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
    seen_tool_indices: set[int] = set()
    stream_key_to_index: dict[int | str, int] = {}
    responses_state = provider._new_responses_stream_state()

    events = (
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "name": "read_file",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "name": "read_file",
            "delta": '{"path": "/tmp/demo.txt"}',
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": '{"path": "/tmp/demo.txt"}',
            },
        },
    )

    for event in events:
        async for _ in provider._process_stream_event(
            event,
            event["type"],
            tool_calls_by_index,
            seen_tool_indices,
            stream_key_to_index,
            responses_state,
        ):
            pass

    complete = provider._build_stream_complete("", tool_calls_by_index)

    assert len(complete.message.tool_calls) == 1
    assert complete.message.tool_calls[0].id == "call_1"
    assert complete.message.tool_calls[0].arguments == {"path": "/tmp/demo.txt"}
