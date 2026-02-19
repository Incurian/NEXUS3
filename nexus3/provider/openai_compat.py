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
from typing import TYPE_CHECKING, Any

import httpx

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

if TYPE_CHECKING:
    from nexus3.config.schema import ProviderConfig
    from nexus3.core.interfaces import RawLogCallback

logger = logging.getLogger(__name__)


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
    ) -> dict[str, Any]:
        """Build OpenAI-format request body.

        Args:
            messages: List of Messages in the conversation.
            tools: Optional list of tool definitions.
            stream: Whether streaming is enabled.

        Returns:
            Request body dict in OpenAI format.
        """
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [self._message_to_dict(m) for m in messages],
            "stream": stream,
        }

        if tools:
            body["tools"] = tools

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

        return body

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
        result: list[ToolCall] = []
        for tc in tool_calls_data:
            func = tc.get("function", {})
            arguments_str = func.get("arguments", "{}")
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool arguments JSON: %.100s", arguments_str)
                arguments = {"_raw_arguments": arguments_str}

            result.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            )
        return tuple(result)

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
            choice = data["choices"][0]
            msg = choice["message"]
            content = msg.get("content") or ""

            # Log reasoning content if present (not stored in Message, but useful for debugging)
            reasoning = msg.get("reasoning_content") or msg.get("reasoning")
            if reasoning:
                logger.debug(
                    "Non-streaming response includes reasoning (%d chars, content=%d chars)",
                    len(reasoning), len(content),
                )

            # Parse tool calls if present
            tool_calls: tuple[ToolCall, ...] = ()
            if "tool_calls" in msg and msg["tool_calls"]:
                tool_calls = self._parse_tool_calls(msg["tool_calls"])

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

        except (KeyError, IndexError) as e:
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
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        seen_tool_indices: set[int] = set()

        # Diagnostic tracking
        event_count = 0
        received_done = False
        finish_reason: str | None = None
        stream_start = time.monotonic()

        buffer = ""

        async for chunk in response.aiter_text():
            buffer += chunk

            # Process complete lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith(":"):
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
                            tool_calls_by_index,
                            seen_tool_indices,
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
                            tool_calls_by_index,
                            seen_tool_indices,
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
        tool_calls_by_index: dict[int, dict[str, str]],
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
            logger.warning(
                "Empty stream response: status=%d, events=%d, "
                "received_done=%s, finish_reason=%s, duration=%dms",
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
        tool_calls_by_index: dict[int, dict[str, str]],
        seen_tool_indices: set[int],
    ) -> AsyncIterator[StreamEvent]:
        """Process a single SSE event, yielding appropriate StreamEvents.

        Args:
            event_data: Parsed JSON from SSE event.
            tool_calls_by_index: Tool call accumulator dict.
            seen_tool_indices: Set of tool indices we've already notified about.

        Yields:
            ContentDelta for content, ReasoningDelta for thinking,
            ToolCallStarted for new tool calls.
        """
        choices = event_data.get("choices", [])
        if not choices:
            return

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

            # Initialize accumulator for new tool call
            if index not in tool_calls_by_index:
                tool_calls_by_index[index] = {"id": "", "name": "", "arguments": ""}

            acc = tool_calls_by_index[index]

            # Set id/name once (they should not be concatenated across deltas)
            if tc_delta.get("id") and not acc["id"]:
                acc["id"] = tc_delta["id"]

            func = tc_delta.get("function", {})
            if func.get("name") and not acc["name"]:
                acc["name"] = func["name"]
            # Arguments ARE accumulated incrementally (correct for streaming)
            if func.get("arguments"):
                acc["arguments"] += func["arguments"]

            # Yield ToolCallStarted once per tool call (when we have id and name)
            if index not in seen_tool_indices and acc["id"] and acc["name"]:
                seen_tool_indices.add(index)
                yield ToolCallStarted(
                    index=index,
                    id=acc["id"],
                    name=acc["name"],
                )

    def _build_stream_complete(
        self,
        content: str,
        tool_calls_by_index: dict[int, dict[str, str]],
    ) -> StreamComplete:
        """Build the final StreamComplete event.

        Args:
            content: Accumulated content string.
            tool_calls_by_index: Accumulated tool calls.

        Returns:
            StreamComplete with the final Message.
        """
        # Parse accumulated tool calls
        tool_calls: list[ToolCall] = []
        for index in sorted(tool_calls_by_index.keys()):
            tc = tool_calls_by_index[index]
            try:
                arguments = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool arguments JSON: %.100s", tc["arguments"])
                arguments = {"_raw_arguments": tc["arguments"]}

            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=arguments,
                )
            )

        message = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tuple(tool_calls),
        )

        return StreamComplete(message=message)
