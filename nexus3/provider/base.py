"""Base provider with shared HTTP, retry, and logging logic.

This module provides the abstract base class for all LLM providers.
It handles common functionality like authentication, retries, and logging.
"""

from __future__ import annotations

import asyncio
import os
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from nexus3.config.schema import AuthMethod, ProviderConfig
from nexus3.core.errors import ProviderError
from nexus3.core.types import Message, StreamEvent

if TYPE_CHECKING:
    from nexus3.core.interfaces import RawLogCallback

# Default timeout for API requests (seconds) - can be overridden via config
DEFAULT_TIMEOUT = 120.0

# Retry configuration defaults - can be overridden via config
MAX_RETRIES = 3
MAX_RETRY_DELAY = 10.0  # Maximum delay between retries in seconds
DEFAULT_RETRY_BACKOFF = 1.5  # Exponential backoff multiplier
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class BaseProvider(ABC):
    """Abstract base class for LLM providers.

    Provides shared functionality:
    - API key resolution from environment
    - HTTP header building based on auth_method
    - Request retry logic with exponential backoff
    - Raw logging callbacks

    Subclasses implement:
    - _build_endpoint(): API endpoint URL
    - _build_request_body(): Convert messages to provider format
    - _parse_response(): Convert response to Message
    - _parse_stream(): Convert SSE to StreamEvents
    """

    def __init__(
        self,
        config: ProviderConfig,
        raw_log: RawLogCallback | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            config: Provider configuration.
            raw_log: Optional callback for raw API logging.

        Raises:
            ProviderError: If auth is required but API key is not set.
        """
        self._config = config
        self._api_key = self._get_api_key()
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model
        self._raw_log = raw_log

        # Timeout/retry settings from config (with fallbacks to module defaults)
        self._timeout = config.request_timeout
        self._max_retries = config.max_retries
        self._retry_backoff = config.retry_backoff

    def set_raw_log_callback(self, callback: RawLogCallback | None) -> None:
        """Set or clear the raw logging callback.

        Args:
            callback: The callback to set, or None to disable raw logging.
        """
        self._raw_log = callback

    def _get_api_key(self) -> str | None:
        """Get the API key from environment, or None if auth not required.

        Returns:
            API key string, or None if auth_method is NONE.

        Raises:
            ProviderError: If auth is required but env var is not set.
        """
        if self._config.auth_method == AuthMethod.NONE:
            return None

        api_key = os.environ.get(self._config.api_key_env)
        if not api_key:
            raise ProviderError(
                f"API key not found. Set the {self._config.api_key_env} environment variable."
            )
        return api_key

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers based on auth_method and config.

        Returns:
            Dict of HTTP headers.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}

        # Add configured extra headers
        headers.update(self._config.extra_headers)

        # Add authentication header based on method
        if self._api_key:
            match self._config.auth_method:
                case AuthMethod.BEARER:
                    headers["Authorization"] = f"Bearer {self._api_key}"
                case AuthMethod.API_KEY:
                    headers["api-key"] = self._api_key
                case AuthMethod.X_API_KEY:
                    headers["x-api-key"] = self._api_key
                case AuthMethod.NONE:
                    pass  # No auth header

        return headers

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate delay for retry with exponential backoff and jitter.

        Args:
            attempt: The current attempt number (0-indexed).

        Returns:
            Delay in seconds before next retry.
        """
        # Exponential backoff using config multiplier + random jitter (0-1s)
        delay = (self._retry_backoff ** attempt) + random.uniform(0, 1)
        return min(delay, MAX_RETRY_DELAY)

    def _is_retryable_error(self, status_code: int) -> bool:
        """Check if an HTTP status code indicates a retryable error.

        Args:
            status_code: The HTTP status code from the response.

        Returns:
            True if the request should be retried, False otherwise.
        """
        return status_code in RETRYABLE_STATUS_CODES

    async def _make_request(
        self,
        url: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a non-streaming HTTP request with retries.

        Args:
            url: Full API endpoint URL.
            body: Request body dict.

        Returns:
            Parsed JSON response.

        Raises:
            ProviderError: On failure after all retries.
        """
        # Log raw request if callback is set
        if self._raw_log:
            self._raw_log.on_request(url, body)

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
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
                        if attempt < self._max_retries - 1:
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

                    return data

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Network errors are retryable
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                # Final attempt failed
                if isinstance(e, httpx.ConnectError):
                    raise ProviderError(
                        f"Failed to connect to API after {self._max_retries} attempts: {e}"
                    ) from e
                raise ProviderError(
                    f"API request timed out after {self._max_retries} attempts: {e}"
                ) from e
            except httpx.HTTPError as e:
                # Other HTTP errors - don't retry
                raise ProviderError(f"HTTP error occurred: {e}") from e

        # Shouldn't reach here, but handle it
        if last_error:
            msg = f"Request failed after {self._max_retries} attempts"
            raise ProviderError(msg) from last_error
        raise ProviderError("Request failed unexpectedly")

    async def _make_streaming_request(
        self,
        url: str,
        body: dict[str, Any],
    ) -> AsyncIterator[httpx.Response]:
        """Make a streaming HTTP request with retries.

        Args:
            url: Full API endpoint URL.
            body: Request body dict.

        Yields:
            The httpx Response object for streaming.

        Raises:
            ProviderError: On failure after all retries.
        """
        # Log raw request if callback is set
        if self._raw_log:
            self._raw_log.on_request(url, body)

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
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
                            if attempt < self._max_retries - 1:
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

                        # Success - yield the response for streaming
                        yield response
                        return

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Network errors are retryable
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                # Final attempt failed
                if isinstance(e, httpx.ConnectError):
                    raise ProviderError(
                        f"Failed to connect to API after {self._max_retries} attempts: {e}"
                    ) from e
                raise ProviderError(
                    f"API request timed out after {self._max_retries} attempts: {e}"
                ) from e
            except httpx.HTTPError as e:
                # Other HTTP errors - don't retry
                raise ProviderError(f"HTTP error occurred: {e}") from e

        # Shouldn't reach here
        if last_error:
            msg = f"Request failed after {self._max_retries} attempts"
            raise ProviderError(msg) from last_error

    # Abstract methods for subclasses to implement

    @abstractmethod
    def _build_endpoint(self, stream: bool = False) -> str:
        """Build the API endpoint URL.

        Args:
            stream: Whether this is a streaming request.

        Returns:
            Full URL for the API endpoint.
        """
        ...

    @abstractmethod
    def _build_request_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> dict[str, Any]:
        """Build the request body in provider-specific format.

        Args:
            messages: List of Messages in the conversation.
            tools: Optional list of tool definitions.
            stream: Whether streaming is enabled.

        Returns:
            Request body dict.
        """
        ...

    @abstractmethod
    def _parse_response(self, data: dict[str, Any]) -> Message:
        """Parse non-streaming response to Message.

        Args:
            data: Parsed JSON response from API.

        Returns:
            Message with content and tool_calls.
        """
        ...

    @abstractmethod
    async def _parse_stream(
        self, response: httpx.Response
    ) -> AsyncIterator[StreamEvent]:
        """Parse streaming response to StreamEvents.

        Args:
            response: httpx Response object with streaming content.

        Yields:
            StreamEvent subclasses (ContentDelta, ToolCallStarted, StreamComplete).
        """
        ...

    # Concrete implementations using abstract methods

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
            The assistant's response as a Message.

        Raises:
            ProviderError: If the API request fails.
        """
        url = self._build_endpoint(stream=False)
        body = self._build_request_body(messages, tools, stream=False)

        data = await self._make_request(url, body)
        return self._parse_response(data)

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
            StreamEvent subclasses (ContentDelta, ToolCallStarted, StreamComplete).

        Raises:
            ProviderError: If the API request fails.
        """
        url = self._build_endpoint(stream=True)
        body = self._build_request_body(messages, tools, stream=True)

        async for response in self._make_streaming_request(url, body):
            async for event in self._parse_stream(response):
                yield event
