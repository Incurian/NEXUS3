"""OpenRouter provider implementation for NEXUS3.

This module implements the AsyncProvider protocol for OpenRouter's API,
which is compatible with the OpenAI chat completions format.
"""

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexus3.config.schema import ProviderConfig
from nexus3.core.errors import ProviderError
from nexus3.core.types import Message, Role, ToolCall

# Default timeout for API requests (30 seconds)
DEFAULT_TIMEOUT = 30.0


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

    def __init__(self, config: ProviderConfig) -> None:
        """Initialize the OpenRouter provider.

        Args:
            config: Provider configuration including API key env var and model.

        Raises:
            ProviderError: If the API key environment variable is not set.
        """
        self._config = config
        self._api_key = self._get_api_key()
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model

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
    ) -> dict[str, Any]:
        """Build the request body for the API.

        Args:
            messages: List of Messages in the conversation.
            tools: Optional list of tool definitions.
            stream: Whether to enable streaming.

        Returns:
            Request body dict.
        """
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [self._message_to_dict(m) for m in messages],
            "stream": stream,
        }

        if tools:
            body["tools"] = tools

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
            ProviderError: If the API request fails.
        """
        url = f"{self._base_url}/chat/completions"
        body = self._build_request_body(messages, tools, stream=False)

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    url,
                    headers=self._build_headers(),
                    json=body,
                )

                if response.status_code == 401:
                    raise ProviderError("Authentication failed. Check your API key.")

                if response.status_code == 429:
                    raise ProviderError("Rate limit exceeded. Please wait and try again.")

                if response.status_code >= 400:
                    error_detail = response.text
                    raise ProviderError(
                        f"API request failed with status {response.status_code}: {error_detail}"
                    )

                data = response.json()

        except httpx.ConnectError as e:
            raise ProviderError(f"Failed to connect to API: {e}") from e
        except httpx.TimeoutException as e:
            raise ProviderError(f"API request timed out: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"HTTP error occurred: {e}") from e

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
    ) -> AsyncIterator[str]:
        """Stream response tokens from a completion.

        Args:
            messages: The conversation history as a list of Messages.
            tools: Optional list of tool definitions in OpenAI function format.

        Yields:
            String chunks of the response as they arrive.

        Raises:
            ProviderError: If the API request fails.

        Note:
            When tools are provided and the model decides to call a tool,
            the stream may end early and the caller should use complete()
            to get the full tool call information.
        """
        url = f"{self._base_url}/chat/completions"
        body = self._build_request_body(messages, tools, stream=True)

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=self._build_headers(),
                    json=body,
                ) as response:
                    if response.status_code == 401:
                        raise ProviderError("Authentication failed. Check your API key.")

                    if response.status_code == 429:
                        raise ProviderError("Rate limit exceeded. Please wait and try again.")

                    if response.status_code >= 400:
                        # Read the error body
                        error_body = await response.aread()
                        error_msg = error_body.decode()
                        raise ProviderError(
                            f"API request failed with status {response.status_code}: {error_msg}"
                        )

                    # Process SSE stream
                    async for chunk in self._parse_sse_stream(response):
                        yield chunk

        except httpx.ConnectError as e:
            raise ProviderError(f"Failed to connect to API: {e}") from e
        except httpx.TimeoutException as e:
            raise ProviderError(f"API request timed out: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"HTTP error occurred: {e}") from e

    async def _parse_sse_stream(self, response: httpx.Response) -> AsyncIterator[str]:
        """Parse Server-Sent Events stream from the response.

        Args:
            response: The httpx Response object with streaming content.

        Yields:
            Content delta strings from each SSE event.
        """
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
                        return

                    # Parse JSON data
                    try:
                        event_data = json.loads(data)
                        choices = event_data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        # Skip malformed JSON in stream
                        continue

        # Process any remaining data in buffer
        if buffer.strip():
            line = buffer.strip()
            if line.startswith("data: ") and line[6:] != "[DONE]":
                try:
                    event_data = json.loads(line[6:])
                    choices = event_data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    pass
