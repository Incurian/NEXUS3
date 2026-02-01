"""Anthropic Claude API provider for NEXUS3.

This module implements the native Anthropic Messages API, which differs
significantly from the OpenAI format:

- Endpoint: /v1/messages (not /v1/chat/completions)
- Auth: x-api-key header + anthropic-version header
- Messages: Content blocks instead of plain strings
- Tool calls: tool_use blocks in response content
- Tool results: tool_result blocks in user message content
- Streaming: Different event types (content_block_delta, etc.)
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

logger = logging.getLogger(__name__)

from nexus3.core.types import (
    ContentDelta,
    Message,
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


# Anthropic API version header
ANTHROPIC_VERSION = "2023-06-01"

# Default max tokens for Anthropic (required parameter)
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(BaseProvider):
    """Provider for native Anthropic Claude API.

    Uses the Messages API with Anthropic-specific format for messages,
    tools, and streaming. Not OpenAI-compatible.

    Configuration:
        - type: "anthropic"
        - base_url: https://api.anthropic.com (default)
        - api_key_env: ANTHROPIC_API_KEY
        - model: claude-sonnet-4-20250514 or other Claude model
        - auth_method: x-api-key (auto-set by factory)

    Example config.json:
        {
            "provider": {
                "type": "anthropic",
                "api_key_env": "ANTHROPIC_API_KEY",
                "model": "claude-sonnet-4-20250514"
            }
        }

    Example:
        config = ProviderConfig(
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            model="claude-sonnet-4-20250514",
        )
        provider = AnthropicProvider(config)
    """

    def __init__(
        self,
        config: ProviderConfig,
        model_id: str,
        raw_log: RawLogCallback | None = None,
        reasoning: bool = False,
    ) -> None:
        """Initialize the Anthropic provider.

        Args:
            config: Provider configuration.
            model_id: The model ID to use for API requests.
            raw_log: Optional callback for raw API logging.
            reasoning: Whether to enable extended thinking/reasoning.
        """
        super().__init__(config, model_id, raw_log, reasoning)

    def _build_headers(self) -> dict[str, str]:
        """Build Anthropic-specific headers.

        Adds the required anthropic-version header.

        Returns:
            Dict of HTTP headers.
        """
        headers = super()._build_headers()
        headers["anthropic-version"] = ANTHROPIC_VERSION
        return headers

    def _build_endpoint(self, stream: bool = False) -> str:
        """Build the Anthropic messages endpoint URL.

        Args:
            stream: Whether this is a streaming request (unused).

        Returns:
            Full URL for /v1/messages.
        """
        return f"{self._base_url}/v1/messages"

    def _build_request_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> dict[str, Any]:
        """Build Anthropic-format request body.

        Args:
            messages: List of Messages in the conversation.
            tools: Optional list of tool definitions (OpenAI format, converted).
            stream: Whether streaming is enabled.

        Returns:
            Request body dict in Anthropic format.
        """
        # Extract system message if present (first message with SYSTEM role)
        system: str | None = None
        conversation = messages
        if messages and messages[0].role == Role.SYSTEM:
            system = messages[0].content
            conversation = messages[1:]

        # Convert messages to Anthropic format
        anthropic_messages = self._convert_messages(conversation)

        body: dict[str, Any] = {
            "model": self._model,
            "messages": anthropic_messages,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "stream": stream,
        }

        if system:
            body["system"] = system

        if tools:
            body["tools"] = self._convert_tools(tools)

        return body

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert NEXUS3 messages to Anthropic format.

        Anthropic uses content blocks instead of plain strings.
        Tool results must be in user messages with tool_result blocks.
        Assistant tool calls become tool_use blocks.

        Ensures every tool_use block has a matching tool_result by synthesizing
        missing results for orphaned tool calls (e.g., from cancellation or crash).

        Args:
            messages: List of NEXUS3 Messages.

        Returns:
            List of Anthropic-format message dicts.
        """
        result: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        # Phase 1: Collect all tool_call IDs and tool_result IDs
        tool_call_ids: set[str] = set()
        tool_result_ids: set[str] = set()

        for msg in messages:
            if msg.role == Role.ASSISTANT:
                for tc in msg.tool_calls:
                    tool_call_ids.add(tc.id)
            elif msg.role == Role.TOOL and msg.tool_call_id:
                tool_result_ids.add(msg.tool_call_id)

        # Phase 2: Detect orphaned tool_use blocks and prepare synthetic results
        orphaned_ids = tool_call_ids - tool_result_ids
        synthetic_results: list[dict[str, Any]] = []
        if orphaned_ids:
            logger.warning(
                "Synthesizing %d missing tool_result(s) for orphaned tool_use "
                "blocks: %s",
                len(orphaned_ids),
                list(orphaned_ids),
            )
            for tid in orphaned_ids:
                synthetic_results.append({
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": "[Tool execution was interrupted]",
                })

        # Phase 3: Convert messages
        for msg in messages:
            if msg.role == Role.TOOL:
                # Collect tool results to add to next user message
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                })
            elif msg.role == Role.USER:
                # User message with any pending tool results
                content: list[dict[str, Any]] = []
                content.extend(pending_tool_results)
                pending_tool_results = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                result.append({"role": "user", "content": content})
            elif msg.role == Role.ASSISTANT:
                # Assistant message with content and/or tool_use blocks
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                result.append({"role": "assistant", "content": content})

        # Remaining tool results + synthetic results for orphaned tool_use blocks
        all_pending = pending_tool_results + synthetic_results
        if all_pending:
            result.append({"role": "user", "content": all_pending})

        return result

    def _convert_tools(
        self, openai_tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert OpenAI tool format to Anthropic format.

        OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}

        Args:
            openai_tools: Tools in OpenAI function format.

        Returns:
            Tools in Anthropic format.
        """
        result: list[dict[str, Any]] = []
        for tool in openai_tools:
            func = tool.get("function", {})
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            })
        return result

    def _parse_response(self, data: dict[str, Any]) -> Message:
        """Parse Anthropic response to Message.

        Anthropic response has content array with text and tool_use blocks.

        Args:
            data: Parsed JSON response from API.

        Returns:
            Message with content and tool_calls.

        Raises:
            ProviderError: If response format is invalid.
        """
        from nexus3.core.errors import ProviderError

        try:
            content_blocks = data.get("content", [])
            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []

            for block in content_blocks:
                block_type = block.get("type")
                if block_type == "text":
                    text_parts.append(block.get("text", ""))
                elif block_type == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=block.get("id", ""),
                            name=block.get("name", ""),
                            arguments=block.get("input", {}),
                        )
                    )

            return Message(
                role=Role.ASSISTANT,
                content="".join(text_parts),
                tool_calls=tuple(tool_calls),
            )

        except (KeyError, TypeError) as e:
            raise ProviderError(f"Failed to parse Anthropic response: {e}") from e

    async def _parse_stream(
        self, response: httpx.Response
    ) -> AsyncIterator[StreamEvent]:
        """Parse Anthropic SSE stream to StreamEvents.

        Anthropic streaming events:
        - message_start: Initial message metadata
        - content_block_start: Start of text or tool_use block
        - content_block_delta: Incremental content (text_delta or input_json_delta)
        - content_block_stop: End of content block
        - message_delta: Message-level updates (stop_reason)
        - message_stop: End of message

        Args:
            response: httpx Response object with streaming content.

        Yields:
            StreamEvent subclasses.
        """
        # Accumulators
        accumulated_content = ""
        current_tool: dict[str, Any] | None = None
        tool_calls: list[ToolCall] = []
        seen_tool_ids: set[str] = set()

        buffer = ""

        async for chunk in response.aiter_text():
            buffer += chunk

            # Process complete lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                # Skip empty lines
                if not line:
                    continue

                # Handle event type lines
                if line.startswith("event: "):
                    event_type = line[7:]
                    continue

                # Handle data lines
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)

                        # Log raw chunk if callback is set
                        if self._raw_log:
                            self._raw_log.on_chunk(data)

                        event_type = data.get("type", "")

                        if event_type == "content_block_start":
                            # New content block starting
                            block = data.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "input": "",
                                }
                                # Yield ToolCallStarted
                                if current_tool["id"] not in seen_tool_ids:
                                    seen_tool_ids.add(current_tool["id"])
                                    yield ToolCallStarted(
                                        index=len(tool_calls),
                                        id=current_tool["id"],
                                        name=current_tool["name"],
                                    )

                        elif event_type == "content_block_delta":
                            delta = data.get("delta", {})
                            delta_type = delta.get("type")

                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    accumulated_content += text
                                    yield ContentDelta(text=text)

                            elif delta_type == "input_json_delta":
                                # Accumulate tool input JSON
                                if current_tool is not None:
                                    current_tool["input"] += delta.get(
                                        "partial_json", ""
                                    )

                        elif event_type == "content_block_stop":
                            # Content block finished
                            if current_tool is not None:
                                # Parse accumulated JSON input
                                try:
                                    input_data = (
                                        json.loads(current_tool["input"])
                                        if current_tool["input"]
                                        else {}
                                    )
                                except json.JSONDecodeError:
                                    input_data = {}

                                tool_calls.append(
                                    ToolCall(
                                        id=current_tool["id"],
                                        name=current_tool["name"],
                                        arguments=input_data,
                                    )
                                )
                                current_tool = None

                        elif event_type == "message_stop":
                            # Message complete
                            yield StreamComplete(
                                message=Message(
                                    role=Role.ASSISTANT,
                                    content=accumulated_content,
                                    tool_calls=tuple(tool_calls),
                                )
                            )
                            return

                    except json.JSONDecodeError:
                        continue

        # If we exit without message_stop, yield what we have
        yield StreamComplete(
            message=Message(
                role=Role.ASSISTANT,
                content=accumulated_content,
                tool_calls=tuple(tool_calls),
            )
        )
