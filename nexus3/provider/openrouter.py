"""OpenRouter provider implementation for NEXUS3.

This module implements the AsyncProvider protocol for OpenRouter's API,
which is compatible with the OpenAI chat completions format.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from nexus3.config.schema import ProviderConfig
from nexus3.core.errors import ProviderError
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

if TYPE_CHECKING:
    from nexus3.core.interfaces import RawLogCallback

# Default timeout for API requests (30 seconds)
DEFAULT_TIMEOUT = 30.0

# Retry configuration
MAX_RETRIES = 3
MAX_RETRY_DELAY = 10.0  # Maximum delay between retries in seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class OpenRouterProvider:
    """Async LLM provider for OpenRouter API.

    Implements the AsyncProvider protocol with support for both streaming
    and non-streaming completions. Uses httpx for async HTTP requests.

    Example:
        config = ProviderConfig(
            api_key_env="OPENROUTER_API_KEY",
            model="anthropic/claude-sonnet-4",
        )
        provider = OpenRouterProvider(config)

        # Non-streaming
        response = await provider.complete([Message(Role.USER, "Hello")])

        # Streaming
        async for chunk in provider.stream([Message(Role.USER, "Hello")]):
            print(chunk, end="")
    """

    def __init__(
        self,
        config: ProviderConfig,
        raw_log: RawLogCallback | None = None,
    ) -> None:
        """Initialize the OpenRouter provider.

        Args:
            config: Provider configuration including API key env var and model.
            raw_log: Optional callback for raw API logging.

        Raises:
            ProviderError: If the API key environment variable is not set.
        """
        self._config = config
        self._api_key = self._get_api_key()
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model
        self._raw_log = raw_log

    def set_raw_log_callback(self, callback: RawLogCallback | None) -> None:
        """Set or clear the raw logging callback.

        This allows setting the callback after construction, which is useful
        when the logger isn't available at provider creation time.

        Args:
            callback: The callback to set, or None to disable raw logging.
        """
        self._raw_log = callback

    def _get_api_key(self) -> str:
        """Get the API key from the environment variable.

        Returns:
            The API key string.

        Raises:
            ProviderError: If the environment variable is not set or empty.
        """
        api_key = os.environ.get(self._config.api_key_env)
        if not api_key:
            raise ProviderError(
                f"API key not found. Set the {self._config.api_key_env} environment variable."
            )
        return api_key

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for API requests."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/nexus3",  # Required by OpenRouter
        }

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate delay for retry with exponential backoff and jitter.

        Args:
            attempt: The current attempt number (0-indexed).

        Returns:
            Delay in seconds before next retry.
        """
        # Exponential backoff: 2^attempt + random jitter (0-1s)
        delay = 2**attempt + random.uniform(0, 1)
        return min(delay, MAX_RETRY_DELAY)

    def _is_retryable_error(self, status_code: int) -> bool:
        """Check if an HTTP status code indicates a retryable error.

        Args:
            status_code: The HTTP status code from the response.

        Returns:
            True if the request should be retried, False otherwise.
        """
        return status_code in RETRYABLE_STATUS_CODES

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

    def _parse_tool_calls(self, tool_calls_data: list[dict[str, Any]]) -> tuple[ToolCall, ...]:
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
                arguments = {}

            result.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            )
        return tuple(result)

    def _build_request_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        model_override: str | None = None,
        reasoning_override: bool | None = None,
    ) -> dict[str, Any]:
        """Build the request body for the API.

        Args:
            messages: List of Messages in the conversation.
            tools: Optional list of tool definitions.
            stream: Whether to enable streaming.
            model_override: Optional model ID to use instead of config default.
            reasoning_override: Optional reasoning setting to use instead of config default.

        Returns:
            Request body dict.
        """
        effective_model = model_override or self._model
        effective_reasoning = reasoning_override if reasoning_override is not None else self._config.reasoning

        body: dict[str, Any] = {
            "model": effective_model,
            "messages": [self._message_to_dict(m) for m in messages],
            "stream": stream,
        }

        if tools:
            body["tools"] = tools

        # Enable extended thinking/reasoning if configured
        if effective_reasoning:
            body["reasoning"] = {"effort": "high"}

        return body

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Perform a non-streaming completion.

        Args:
            messages: The conversation history as a list of Messages.
            tools: Optional list of tool definitions in OpenAI function format.

        Returns:
            The assistant's response as a Message, potentially including tool_calls.

        Raises:
            ProviderError: If the API request fails after all retries.
        """
        url = f"{self._base_url}/chat/completions"
        body = self._build_request_body(messages, tools, stream=False)

        # Log raw request if callback is set
        if self._raw_log:
            self._raw_log.on_request(url, body)

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    response = await client.post(
                        url,
                        headers=self._build_headers(),
                        json=body,
                    )

                    # Non-retryable client errors - fail immediately
                    if response.status_code == 401:
                        raise ProviderError("Authentication failed. Check your API key.")

                    if response.status_code == 403:
                        raise ProviderError("Access forbidden. Check your API permissions.")

                    if response.status_code == 404:
                        raise ProviderError("API endpoint not found. Check your configuration.")

                    # Retryable server errors - retry with backoff
                    if self._is_retryable_error(response.status_code):
                        error_detail = response.text
                        last_error = ProviderError(
                            f"API request failed with status {response.status_code}: {error_detail}"
                        )
                        if attempt < MAX_RETRIES - 1:
                            delay = self._calculate_retry_delay(attempt)
                            await asyncio.sleep(delay)
                            continue
                        raise last_error

                    # Other client errors (400, etc.) - fail immediately
                    if response.status_code >= 400:
                        error_detail = response.text
                        raise ProviderError(
                            f"API request failed with status {response.status_code}: {error_detail}"
                        )

                    data = response.json()

                    # Log raw response if callback is set
                    if self._raw_log:
                        self._raw_log.on_response(response.status_code, data)

                    # Success - break out of retry loop
                    break

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Network errors are retryable
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = self._calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                # Final attempt failed
                if isinstance(e, httpx.ConnectError):
                    raise ProviderError(
                        f"Failed to connect to API after {MAX_RETRIES} attempts: {e}"
                    ) from e
                raise ProviderError(
                    f"API request timed out after {MAX_RETRIES} attempts: {e}"
                ) from e
            except httpx.HTTPError as e:
                # Other HTTP errors - don't retry
                raise ProviderError(f"HTTP error occurred: {e}") from e
        else:
            # This shouldn't be reached, but handle it just in case
            if last_error:
                raise ProviderError(f"Request failed after {MAX_RETRIES} attempts") from last_error

        # Parse the response
        try:
            choice = data["choices"][0]
            msg = choice["message"]
            content = msg.get("content") or ""

            # Parse tool calls if present
            tool_calls: tuple[ToolCall, ...] = ()
            if "tool_calls" in msg and msg["tool_calls"]:
                tool_calls = self._parse_tool_calls(msg["tool_calls"])

            return Message(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=tool_calls,
            )

        except (KeyError, IndexError) as e:
            raise ProviderError(f"Failed to parse API response: {e}") from e

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response with content and tool call detection.

        Args:
            messages: The conversation history as a list of Messages.
            tools: Optional list of tool definitions in OpenAI function format.

        Yields:
            StreamEvent subclasses:
            - ContentDelta: text content chunks (display immediately)
            - ToolCallStarted: notification when a tool call is detected
            - StreamComplete: final event with complete Message (content + tool_calls)

        Raises:
            ProviderError: If the API request fails after all retries.
        """
        url = f"{self._base_url}/chat/completions"
        body = self._build_request_body(messages, tools, stream=True)

        # Log raw request if callback is set
        if self._raw_log:
            self._raw_log.on_request(url, body)

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers=self._build_headers(),
                        json=body,
                    ) as response:
                        # Non-retryable client errors - fail immediately
                        if response.status_code == 401:
                            raise ProviderError("Authentication failed. Check your API key.")

                        if response.status_code == 403:
                            raise ProviderError("Access forbidden. Check your API permissions.")

                        if response.status_code == 404:
                            raise ProviderError("API endpoint not found. Check your configuration.")

                        # Retryable server errors - retry with backoff
                        if self._is_retryable_error(response.status_code):
                            error_body = await response.aread()
                            error_msg = error_body.decode()
                            last_error = ProviderError(
                                f"API request failed ({response.status_code}): {error_msg}"
                            )
                            if attempt < MAX_RETRIES - 1:
                                delay = self._calculate_retry_delay(attempt)
                                await asyncio.sleep(delay)
                                continue
                            raise last_error

                        # Other client errors (400, etc.) - fail immediately
                        if response.status_code >= 400:
                            error_body = await response.aread()
                            error_msg = error_body.decode()
                            raise ProviderError(
                                f"API request failed ({response.status_code}): {error_msg}"
                            )

                        # Success - process SSE stream with tool call accumulation
                        # Note: Once we start yielding, we cannot retry
                        async for event in self._parse_sse_stream_with_tools(response):
                            yield event
                        return  # Successful completion

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Network errors are retryable
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = self._calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                # Final attempt failed
                if isinstance(e, httpx.ConnectError):
                    raise ProviderError(
                        f"Failed to connect to API after {MAX_RETRIES} attempts: {e}"
                    ) from e
                raise ProviderError(
                    f"API request timed out after {MAX_RETRIES} attempts: {e}"
                ) from e
            except httpx.HTTPError as e:
                # Other HTTP errors - don't retry
                raise ProviderError(f"HTTP error occurred: {e}") from e

        # This shouldn't be reached, but handle it just in case
        if last_error:
            raise ProviderError(f"Request failed after {MAX_RETRIES} attempts") from last_error

    async def _parse_sse_stream_with_tools(
        self, response: httpx.Response
    ) -> AsyncIterator[StreamEvent]:
        """Parse SSE stream, yielding events and accumulating tool calls.

        Args:
            response: The httpx Response object with streaming content.

        Yields:
            StreamEvent subclasses for content, tool calls, and completion.
        """
        # Accumulators
        accumulated_content = ""
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        seen_tool_indices: set[int] = set()

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

                # Handle data lines
                if line.startswith("data: "):
                    data = line[6:]  # Remove "data: " prefix

                    # Check for stream end marker
                    if data == "[DONE]":
                        # Build final message and yield StreamComplete
                        yield self._build_stream_complete(
                            accumulated_content, tool_calls_by_index
                        )
                        return

                    # Parse JSON data
                    try:
                        event_data = json.loads(data)

                        # Log raw chunk if callback is set
                        if self._raw_log:
                            self._raw_log.on_chunk(event_data)

                        # Process the event
                        async for event in self._process_stream_event(
                            event_data,
                            accumulated_content,
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
            if line.startswith("data: ") and line[6:] != "[DONE]":
                try:
                    event_data = json.loads(line[6:])

                    # Log raw chunk if callback is set
                    if self._raw_log:
                        self._raw_log.on_chunk(event_data)

                    async for event in self._process_stream_event(
                        event_data,
                        accumulated_content,
                        tool_calls_by_index,
                        seen_tool_indices,
                    ):
                        if isinstance(event, ContentDelta):
                            accumulated_content += event.text
                        yield event

                except json.JSONDecodeError:
                    pass

        # If we get here without [DONE], still yield StreamComplete
        yield self._build_stream_complete(accumulated_content, tool_calls_by_index)

    async def _process_stream_event(
        self,
        event_data: dict[str, Any],
        accumulated_content: str,
        tool_calls_by_index: dict[int, dict[str, str]],
        seen_tool_indices: set[int],
    ) -> AsyncIterator[StreamEvent]:
        """Process a single SSE event, yielding appropriate StreamEvents.

        Args:
            event_data: Parsed JSON from SSE event.
            accumulated_content: Running content accumulator (for reference).
            tool_calls_by_index: Tool call accumulator dict.
            seen_tool_indices: Set of tool indices we've already notified about.

        Yields:
            ContentDelta for content, ToolCallStarted for new tool calls.
        """
        choices = event_data.get("choices", [])
        if not choices:
            return

        delta = choices[0].get("delta", {})

        # Handle reasoning delta (Grok/xAI models)
        reasoning = delta.get("reasoning")
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

            # Accumulate fields (they come incrementally)
            if tc_delta.get("id"):
                acc["id"] += tc_delta["id"]

            func = tc_delta.get("function", {})
            if func.get("name"):
                acc["name"] += func["name"]
            if func.get("arguments"):
                acc["arguments"] += func["arguments"]

            # Yield ToolCallStarted once per tool call (when we first have id and name)
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
                arguments = {}

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
