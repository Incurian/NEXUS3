"""OpenAI-compatible provider for NEXUS3.

This module implements providers for OpenAI-compatible APIs including:
- OpenRouter (openrouter.ai)
- OpenAI (api.openai.com)
- Ollama (local)
- vLLM (local/remote)
- Any other OpenAI-compatible server

The provider uses the standard /v1/chat/completions endpoint with
OpenAI message format and function calling.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from nexus3.context.compiler import compile_context_messages
from nexus3.core.types import (
    ContentDelta,
    Message,
    ReasoningDelta,
    Role,
    StreamComplete,
    StreamEvent,
    ToolCall,
    ToolCallStarted,
)
from nexus3.provider.base import BaseProvider
from nexus3.provider.tool_call_formats import (
    StreamingToolCallAccumulator,
    parse_anthropic_content_blocks,
    parse_openai_chat_tool_calls,
    parse_responses_output_items,
)
from nexus3.provider.tool_schema import normalize_tool_parameters_for_provider

if TYPE_CHECKING:
    from nexus3.config.schema import ProviderConfig
    from nexus3.core.interfaces import RawLogCallback

logger = logging.getLogger(__name__)


@dataclass
class _ResponsesStreamState:
    """Streaming state for Responses API text-deduplication."""

    seen_text_deltas: set[tuple[str, int | str | None, int | str | None, int | str | None]] = (
        field(default_factory=set)
    )
    emitted_text_blocks: set[
        tuple[str, int | str | None, int | str | None, int | str | None]
    ] = field(default_factory=set)
    seen_message_content: set[tuple[str, int | str | None, int | str | None]] = field(
        default_factory=set
    )


def _normalize_tools_for_openai(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return provider-safe tool definitions for OpenAI-compatible APIs."""
    normalized_tools: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function")
        if not isinstance(function, dict):
            normalized_tools.append(tool)
            continue

        normalized_function = dict(function)
        normalized_function["parameters"] = normalize_tool_parameters_for_provider(
            function.get("parameters")
            if isinstance(function.get("parameters"), dict)
            else None
        )
        normalized_tool = dict(tool)
        normalized_tool["function"] = normalized_function
        normalized_tools.append(normalized_tool)

    return normalized_tools


class OpenAICompatProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs.

    Supports standard OpenAI chat completions API with:
    - Message format: role/content/tool_calls/tool_call_id
    - Tool format: OpenAI function calling
    - Streaming: SSE with delta objects
    - Extended thinking: reasoning field (OpenRouter/Grok)

    Works with:
    - openrouter: OpenRouter.ai
    - openai: Direct OpenAI API
    - ollama: Local Ollama server (http://localhost:11434/v1)
    - vllm: vLLM OpenAI-compatible server

    Example:
        config = ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            model="gpt-4o",
        )
        provider = OpenAICompatProvider(config)

        response = await provider.complete([Message(Role.USER, "Hello")])
    """

    def __init__(
        self,
        config: ProviderConfig,
        model_id: str,
        raw_log: RawLogCallback | None = None,
        reasoning: bool = False,
    ) -> None:
        """Initialize the OpenAI-compatible provider.

        Args:
            config: Provider configuration.
            model_id: The model ID to use for API requests.
            raw_log: Optional callback for raw API logging.
            reasoning: Whether to enable extended thinking/reasoning.
        """
        super().__init__(config, model_id, raw_log, reasoning)

    def _build_endpoint(self, stream: bool = False) -> str:
        """Build the chat completions endpoint URL.

        Args:
            stream: Whether this is a streaming request (unused, same endpoint).

        Returns:
            Full URL for /v1/chat/completions.
        """
        return f"{self._base_url}/chat/completions"

    def _build_request_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        dynamic_context: str | None = None,
    ) -> dict[str, Any]:
        """Build OpenAI-format request body.

        Args:
            messages: List of Messages in the conversation.
            tools: Optional list of tool definitions.
            stream: Whether streaming is enabled.
            dynamic_context: Optional volatile context to inject into the
                last user message for cache-optimal placement.

        Returns:
            Request body dict in OpenAI format.
        """
        compiled = compile_context_messages(
            messages,
            ensure_assistant_after_tool_results=False,
        )

        body: dict[str, Any] = {
            "model": self._model,
            "messages": [self._message_to_dict(m) for m in compiled.messages],
            "stream": stream,
        }

        if tools:
            body["tools"] = _normalize_tools_for_openai(tools)

        # Enable extended thinking/reasoning if configured
        if self._reasoning:
            body["reasoning"] = {"effort": "high"}

        # OpenRouter + Anthropic model = need cache_control on system message
        if self._is_openrouter_anthropic() and self._config.prompt_caching:
            for msg in body.get("messages", []):
                if msg.get("role") == "system":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        msg["content"] = [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ]
                    break

        # Inject dynamic context into last user message (after cache_control
        # conversion so the system message format is already finalized)
        if dynamic_context:
            self._inject_dynamic_context(body["messages"], dynamic_context)

        return body

    def _inject_dynamic_context(
        self,
        messages: list[dict[str, Any]],
        dynamic_context: str,
    ) -> None:
        """Inject dynamic context into the last user message.

        For standard OpenAI format (string content), appends with double newline.
        For OpenRouter Anthropic passthrough (list content), appends a text block.

        Args:
            messages: OpenAI-format message dicts (mutated in place).
            dynamic_context: The context string to inject.
        """
        # Find last user message (search backwards)
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                content = messages[i]["content"]
                if isinstance(content, str):
                    messages[i]["content"] = content + "\n\n" + dynamic_context
                elif isinstance(content, list):
                    # OpenRouter Anthropic passthrough uses list content
                    content.append({"type": "text", "text": dynamic_context})
                return

        # No user message found — add one
        messages.append({"role": "user", "content": dynamic_context})

    def _message_to_dict(self, message: Message) -> dict[str, Any]:
        """Convert a Message to OpenAI-format dict.

        Args:
            message: The Message to convert.

        Returns:
            Dict in OpenAI chat completion format.
        """
        result: dict[str, Any] = {
            "role": message.role.value,
            "content": message.content,
        }

        # Add tool_call_id for tool response messages
        if message.tool_call_id is not None:
            result["tool_call_id"] = message.tool_call_id

        # Add tool_calls for assistant messages with tool calls
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in message.tool_calls
            ]

        return result

    def _is_openrouter_anthropic(self) -> bool:
        """Check if we're on OpenRouter routing to an Anthropic model.

        Uses config.type instead of URL parsing for robustness against
        URL changes, staging environments, and corporate proxies.

        Returns:
            True if provider is openrouter and model is from Anthropic.
        """
        return (
            self._config.type == "openrouter"
            and "anthropic" in self._model.lower()
        )

    def _parse_tool_calls(
        self, tool_calls_data: list[dict[str, Any]]
    ) -> tuple[ToolCall, ...]:
        """Parse tool calls from API response.

        Args:
            tool_calls_data: List of tool call dicts from the API.

        Returns:
            Tuple of ToolCall objects.
        """
        return parse_openai_chat_tool_calls(tool_calls_data)

    def _new_responses_stream_state(self) -> _ResponsesStreamState:
        """Create per-stream state for Responses API SSE parsing."""
        return _ResponsesStreamState()

    def _stream_key_part(self, value: Any) -> int | str | None:
        """Normalize a stream key fragment into a hashable identifier."""
        if value is None:
            return None
        if isinstance(value, (int, str)):
            return value
        return str(value)

    def _responses_message_key(
        self,
        event_data: dict[str, Any],
        item: dict[str, Any] | None = None,
    ) -> tuple[str, int | str | None, int | str | None]:
        """Build a stable key for one Responses API message item."""
        item_id = event_data.get("item_id")
        if item_id is None and isinstance(item, dict):
            item_id = item.get("id")
        return (
            "message",
            self._stream_key_part(event_data.get("output_index")),
            self._stream_key_part(item_id),
        )

    def _responses_text_block_key(
        self,
        event_data: dict[str, Any],
    ) -> tuple[str, int | str | None, int | str | None, int | str | None]:
        """Build a stable key for one Responses API output_text block."""
        return (
            "text",
            self._stream_key_part(event_data.get("output_index")),
            self._stream_key_part(event_data.get("item_id")),
            self._stream_key_part(event_data.get("content_index")),
        )

    def _parse_response(self, data: dict[str, Any]) -> Message:
        """Parse OpenAI-format response to Message.

        Args:
            data: Parsed JSON response from API.

        Returns:
            Message with content and tool_calls.

        Raises:
            ProviderError: If response format is invalid.
        """
        from nexus3.core.errors import ProviderError

        try:
            content = ""
            tool_calls: tuple[ToolCall, ...] = ()

            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                msg = choice["message"]
                content_field = msg.get("content")
                if isinstance(content_field, list):
                    content, content_tool_calls = parse_anthropic_content_blocks(
                        content_field,
                        source_format="openai_chat_content_blocks",
                    )
                    if content_tool_calls:
                        tool_calls = content_tool_calls
                else:
                    content = content_field or ""

                # Log reasoning content if present (not stored in Message, but useful for debugging)
                reasoning = msg.get("reasoning_content") or msg.get("reasoning")
                if reasoning:
                    logger.debug(
                        "Non-streaming response includes reasoning (%d chars, content=%d chars)",
                        len(reasoning), len(content),
                    )

                if "tool_calls" in msg and msg["tool_calls"]:
                    tool_calls = self._parse_tool_calls(msg["tool_calls"])

            elif isinstance(data.get("output"), list):
                content, tool_calls = parse_responses_output_items(data["output"])

            elif isinstance(data.get("content"), list):
                content, tool_calls = parse_anthropic_content_blocks(
                    data["content"],
                    source_format="openai_compat_content_blocks",
                )

            else:
                raise KeyError("choices/output/content")

            # Log cache metrics if present (backwards compatible)
            usage = data.get("usage", {})
            prompt_details = usage.get("prompt_tokens_details", {})
            cached_tokens = prompt_details.get("cached_tokens", 0)
            if cached_tokens:
                logger.debug("Cache: read=%d tokens", cached_tokens)

            return Message(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=tool_calls,
            )

        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"Failed to parse API response: {e}") from e

    async def _parse_stream(
        self, response: httpx.Response
    ) -> AsyncIterator[StreamEvent]:
        """Parse OpenAI SSE stream to StreamEvents.

        Args:
            response: httpx Response object with streaming content.

        Yields:
            StreamEvent subclasses (ContentDelta, ReasoningDelta,
            ToolCallStarted, StreamComplete).
        """
        # Accumulators
        accumulated_content = ""
        tool_calls_by_index: dict[int, StreamingToolCallAccumulator] = {}
        seen_tool_indices: set[int] = set()
        stream_key_to_index: dict[int | str, int] = {}

        # Diagnostic tracking
        event_count = 0
        received_done = False
        finish_reason: str | None = None
        stream_start = time.monotonic()

        buffer = ""
        current_event_type: str | None = None
        responses_state = self._new_responses_stream_state()

        async for chunk in response.aiter_text():
            buffer += chunk

            # Process complete lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                if not line:
                    current_event_type = None
                    continue

                if line.startswith(":"):
                    continue

                if line.startswith("event:"):
                    current_event_type = line[6:].removeprefix(" ")
                    continue

                # Handle data lines (SSE spec: space after colon is optional)
                if line.startswith("data:"):
                    data = line[5:].removeprefix(" ")

                    # Check for stream end marker
                    if data == "[DONE]":
                        received_done = True
                        self._log_stream_summary(
                            response, event_count, accumulated_content,
                            tool_calls_by_index, received_done, finish_reason,
                            stream_start,
                        )
                        yield self._build_stream_complete(
                            accumulated_content, tool_calls_by_index
                        )
                        return

                    # Parse JSON data
                    try:
                        event_data = json.loads(data)
                        event_count += 1

                        # Extract finish_reason from final chunk
                        choices = event_data.get("choices", [])
                        if choices:
                            fr = choices[0].get("finish_reason")
                            if fr:
                                finish_reason = fr

                        # Log raw chunk if callback is set
                        if self._raw_log:
                            self._raw_log.on_chunk(event_data)

                        # Process the event
                        async for event in self._process_stream_event(
                            event_data,
                            current_event_type,
                            tool_calls_by_index,
                            seen_tool_indices,
                            stream_key_to_index,
                            responses_state,
                        ):
                            if isinstance(event, ContentDelta):
                                accumulated_content += event.text
                            yield event

                    except json.JSONDecodeError:
                        # Skip malformed JSON in stream
                        continue

        # Process any remaining data in buffer
        if buffer.strip():
            line = buffer.strip()
            if line.startswith("data:"):
                data = line[5:].removeprefix(" ")
                if data != "[DONE]":
                    try:
                        event_data = json.loads(data)
                        event_count += 1

                        choices = event_data.get("choices", [])
                        if choices:
                            fr = choices[0].get("finish_reason")
                            if fr:
                                finish_reason = fr

                        # Log raw chunk if callback is set
                        if self._raw_log:
                            self._raw_log.on_chunk(event_data)

                        async for event in self._process_stream_event(
                            event_data,
                            current_event_type,
                            tool_calls_by_index,
                            seen_tool_indices,
                            stream_key_to_index,
                            responses_state,
                        ):
                            if isinstance(event, ContentDelta):
                                accumulated_content += event.text
                            yield event

                    except json.JSONDecodeError:
                        pass

        # If we get here without [DONE], still yield StreamComplete
        self._log_stream_summary(
            response, event_count, accumulated_content,
            tool_calls_by_index, received_done, finish_reason,
            stream_start,
        )
        yield self._build_stream_complete(accumulated_content, tool_calls_by_index)

    def _log_stream_summary(
        self,
        response: httpx.Response,
        event_count: int,
        content: str,
        tool_calls_by_index: dict[int, StreamingToolCallAccumulator],
        received_done: bool,
        finish_reason: str | None,
        stream_start: float,
    ) -> None:
        """Log stream completion summary and write to raw log."""
        duration_ms = round((time.monotonic() - stream_start) * 1000)
        tool_call_count = len(tool_calls_by_index)
        content_length = len(content)

        summary = {
            "http_status": response.status_code,
            "event_count": event_count,
            "content_length": content_length,
            "tool_call_count": tool_call_count,
            "received_done": received_done,
            "finish_reason": finish_reason,
            "duration_ms": duration_ms,
        }

        if not content and not tool_calls_by_index:
            if received_done:
                logger.warning(
                    "Empty stream response: status=%d, events=%d, "
                    "received_done=%s, finish_reason=%s, duration=%dms",
                    response.status_code, event_count,
                    received_done, finish_reason, duration_ms,
                )
            else:
                logger.debug(
                    "Incomplete empty stream (likely interrupted/cancelled): "
                    "status=%d, events=%d, received_done=%s, finish_reason=%s, duration=%dms",
                    response.status_code, event_count,
                    received_done, finish_reason, duration_ms,
                )
        else:
            logger.debug(
                "Stream complete: events=%d, content_len=%d, tools=%d, "
                "done=%s, finish=%s, duration=%dms",
                event_count, content_length, tool_call_count,
                received_done, finish_reason, duration_ms,
            )

        if self._raw_log:
            self._raw_log.on_stream_complete(summary)

    async def _process_stream_event(
        self,
        event_data: dict[str, Any],
        event_type: str | None,
        tool_calls_by_index: dict[int, StreamingToolCallAccumulator],
        seen_tool_indices: set[int],
        stream_key_to_index: dict[int | str, int],
        responses_state: _ResponsesStreamState | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Process a single SSE event, yielding appropriate StreamEvents.

        Args:
            event_data: Parsed JSON from SSE event.
            event_type: Optional event name from the SSE envelope.
            tool_calls_by_index: Tool call accumulator dict.
            seen_tool_indices: Set of tool indices we've already notified about.
            stream_key_to_index: Stable output-item/tool-call key mapping.

        Yields:
            ContentDelta for content, ReasoningDelta for thinking,
            ToolCallStarted for new tool calls.
        """
        choices = event_data.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})

            # Handle reasoning delta (multiple field names across providers)
            # - "reasoning_content": DeepSeek, vLLM, Azure AI Factory
            # - "reasoning": Grok/xAI, OpenRouter
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                yield ReasoningDelta(text=reasoning)

            # Handle content delta
            content = delta.get("content")
            if content:
                yield ContentDelta(text=content)

            # Handle tool call deltas
            tc_deltas = delta.get("tool_calls", [])
            for tc_delta in tc_deltas:
                index = tc_delta.get("index", 0)

                if index not in tool_calls_by_index:
                    tool_calls_by_index[index] = StreamingToolCallAccumulator(
                        source_format="openai_chat_stream",
                    )

                acc = tool_calls_by_index[index]

                if tc_delta.get("id") and not acc.id:
                    acc.id = tc_delta["id"]

                func = tc_delta.get("function", {})
                if func.get("name") and not acc.name:
                    acc.name = func["name"]
                if "arguments" in func:
                    acc.add_payload(func["arguments"])

                if index not in seen_tool_indices and acc.id and acc.name:
                    seen_tool_indices.add(index)
                    yield ToolCallStarted(
                        index=index,
                        id=acc.id,
                        name=acc.name,
                    )
            return

        detected_type = str(event_data.get("type") or event_type or "")
        if not detected_type:
            return

        if responses_state is None:
            responses_state = self._new_responses_stream_state()

        async for event in self._process_responses_stream_event(
            event_data,
            detected_type,
            tool_calls_by_index,
            seen_tool_indices,
            stream_key_to_index,
            responses_state,
        ):
            yield event

    def _ensure_stream_accumulator(
        self,
        *keys: int | str | None,
        source_format: str,
        tool_calls_by_index: dict[int, StreamingToolCallAccumulator],
        stream_key_to_index: dict[int | str, int],
    ) -> tuple[int, StreamingToolCallAccumulator]:
        """Return the stable stream index and accumulator for tool-call aliases."""
        normalized_keys = [
            normalized
            for key in keys
            if (normalized := self._stream_key_part(key)) is not None
        ]
        for key in normalized_keys:
            if key in stream_key_to_index:
                index = stream_key_to_index[key]
                for alias in normalized_keys:
                    stream_key_to_index[alias] = index
                return index, tool_calls_by_index[index]

        index = len(tool_calls_by_index)
        tool_calls_by_index[index] = StreamingToolCallAccumulator(
            source_format=source_format,
        )
        for alias in normalized_keys:
            stream_key_to_index[alias] = index
        return index, tool_calls_by_index[index]

    async def _process_responses_stream_event(
        self,
        event_data: dict[str, Any],
        detected_type: str,
        tool_calls_by_index: dict[int, StreamingToolCallAccumulator],
        seen_tool_indices: set[int],
        stream_key_to_index: dict[int | str, int],
        responses_state: _ResponsesStreamState,
    ) -> AsyncIterator[StreamEvent]:
        """Process Responses API-style SSE events."""
        if detected_type.endswith("output_text.delta"):
            text = event_data.get("delta")
            if isinstance(text, str) and text:
                responses_state.seen_text_deltas.add(
                    self._responses_text_block_key(event_data)
                )
                responses_state.seen_message_content.add(
                    self._responses_message_key(event_data)
                )
                yield ContentDelta(text=text)
            return

        if detected_type.endswith("output_text.done"):
            text_key = self._responses_text_block_key(event_data)
            if (
                text_key in responses_state.seen_text_deltas
                or text_key in responses_state.emitted_text_blocks
            ):
                return
            text = event_data.get("text")
            if isinstance(text, str) and text:
                responses_state.emitted_text_blocks.add(text_key)
                responses_state.seen_message_content.add(
                    self._responses_message_key(event_data)
                )
                yield ContentDelta(text=text)
            return

        if (
            detected_type.endswith("output_item.added")
            or detected_type.endswith("output_item.done")
        ):
            item = event_data.get("item") or event_data.get("output_item")
            if not isinstance(item, dict):
                return

            item_type = str(item.get("type", ""))
            if item_type == "message":
                message_key = self._responses_message_key(event_data, item)
                if message_key in responses_state.seen_message_content:
                    return
                content, _ = parse_responses_output_items([item])
                if content:
                    responses_state.seen_message_content.add(message_key)
                    yield ContentDelta(text=content)
                return

            if item_type not in {"function_call", "custom_tool_call", "tool_call"}:
                return

            index, acc = self._ensure_stream_accumulator(
                event_data.get("output_index"),
                event_data.get("item_id"),
                item.get("call_id"),
                item.get("id"),
                source_format="openai_responses_stream",
                tool_calls_by_index=tool_calls_by_index,
                stream_key_to_index=stream_key_to_index,
            )

            if item.get("call_id") and not acc.id:
                acc.id = str(item["call_id"])
            elif item.get("id") and not acc.id:
                acc.id = str(item["id"])

            if item.get("name") and not acc.name:
                acc.name = str(item["name"])

            for payload_key in ("arguments", "input", "args"):
                if payload_key in item:
                    acc.replace_payload(item[payload_key])
                    break

            if index not in seen_tool_indices and acc.id and acc.name:
                seen_tool_indices.add(index)
                yield ToolCallStarted(index=index, id=acc.id, name=acc.name)
            return

        if detected_type.endswith("function_call_arguments.delta") or detected_type.endswith(
            "function_call_arguments.done"
        ):
            index, acc = self._ensure_stream_accumulator(
                event_data.get("output_index"),
                event_data.get("item_id"),
                event_data.get("call_id"),
                event_data.get("id"),
                source_format="openai_responses_stream",
                tool_calls_by_index=tool_calls_by_index,
                stream_key_to_index=stream_key_to_index,
            )

            if event_data.get("call_id") and not acc.id:
                acc.id = str(event_data["call_id"])
            if event_data.get("name") and not acc.name:
                acc.name = str(event_data["name"])

            if detected_type.endswith("function_call_arguments.done"):
                full_payload_key = next(
                    (
                        payload_key
                        for payload_key in ("arguments", "input", "args")
                        if payload_key in event_data
                    ),
                    None,
                )
                if full_payload_key is not None:
                    acc.replace_payload(event_data[full_payload_key])
                else:
                    for payload_key in ("delta", "arguments_delta", "partial_json"):
                        if payload_key in event_data:
                            acc.add_payload(event_data[payload_key])
                            break
            else:
                for payload_key in ("delta", "arguments_delta", "partial_json"):
                    if payload_key in event_data:
                        acc.add_payload(event_data[payload_key])
                        break

            if index not in seen_tool_indices and acc.id and acc.name:
                seen_tool_indices.add(index)
                yield ToolCallStarted(index=index, id=acc.id, name=acc.name)

    def _build_stream_complete(
        self,
        content: str,
        tool_calls_by_index: dict[int, StreamingToolCallAccumulator],
    ) -> StreamComplete:
        """Build the final StreamComplete event.

        Args:
            content: Accumulated content string.
            tool_calls_by_index: Accumulated tool calls.

        Returns:
            StreamComplete with the final Message.
        """
        tool_calls = [
            tool_calls_by_index[index].build_tool_call()
            for index in sorted(tool_calls_by_index.keys())
        ]

        message = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tuple(tool_calls),
        )

        return StreamComplete(message=message)
