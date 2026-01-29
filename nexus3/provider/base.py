"""Base provider with shared HTTP, retry, and logging logic.

This module provides the abstract base class for all LLM providers.
It handles common functionality like authentication, retries, and logging.

SECURITY: Includes SSRF validation on base_url (P1.6).
SECURITY: P2.13 - Error body size caps prevent memory exhaustion from large error responses.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import ssl
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

from nexus3.config.schema import AuthMethod, ProviderConfig
from nexus3.core.errors import ProviderError
from nexus3.core.types import Message, StreamEvent

# Hosts that are considered safe for HTTP (non-HTTPS) connections
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

# P2.13 SECURITY: Maximum size for error response bodies
# Prevents memory exhaustion from malicious/buggy providers returning huge error responses
MAX_ERROR_BODY_SIZE: int = 10 * 1024  # 10 KB

if TYPE_CHECKING:
    from nexus3.core.interfaces import RawLogCallback

# Default timeout for API requests (seconds) - can be overridden via config
DEFAULT_TIMEOUT = 120.0

# Retry configuration defaults - can be overridden via config
MAX_RETRIES = 3
MAX_RETRY_DELAY = 10.0  # Maximum delay between retries in seconds
DEFAULT_RETRY_BACKOFF = 1.5  # Exponential backoff multiplier
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def validate_base_url(url: str, allow_insecure: bool = False) -> None:
    """Validate provider base_url for SSRF protection.

    P1.6 SECURITY FIX: Prevents SSRF attacks where a malicious base_url
    could make the server send requests to internal services.

    Rules:
    - HTTPS URLs are always allowed
    - HTTP URLs are only allowed for loopback addresses (localhost, 127.0.0.1, ::1)
    - Empty scheme defaults to HTTPS
    - Other schemes (file://, ftp://, etc.) are rejected

    Args:
        url: The base URL to validate.
        allow_insecure: If True, allow HTTP for any host (for development only).

    Raises:
        ProviderError: If the URL fails validation.
    """
    if not url:
        raise ProviderError("Provider base_url cannot be empty")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""

    # HTTPS is always safe
    if scheme == "https":
        return

    # HTTP needs special handling
    if scheme == "http":
        if allow_insecure:
            return  # Developer explicitly opted in

        # Only loopback addresses are safe for HTTP
        if host.lower() in _LOOPBACK_HOSTS:
            return

        raise ProviderError(
            f"HTTP base_url '{url}' is not allowed for security reasons. "
            f"Use HTTPS, or http://localhost for local development. "
            f"Set allow_insecure_http=true in provider config to override (not recommended)."
        )

    # No scheme - could be relative, reject
    if not scheme:
        raise ProviderError(
            f"Provider base_url '{url}' must include a scheme (https:// or http://)"
        )

    # Unknown scheme (file://, ftp://, gopher://, etc.)
    raise ProviderError(
        f"Provider base_url scheme '{scheme}' is not allowed. Use https:// or http://localhost."
    )


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
        model_id: str,
        raw_log: RawLogCallback | None = None,
        reasoning: bool = False,
    ) -> None:
        """Initialize the provider.

        Args:
            config: Provider configuration.
            model_id: The model ID to use for API requests.
            raw_log: Optional callback for raw API logging.
            reasoning: Whether to enable extended thinking/reasoning.

        Raises:
            ProviderError: If auth is required but API key is not set,
                          or if base_url fails SSRF validation.
        """
        self._config = config

        # P1.6 SECURITY: Validate base_url before use (SSRF protection)
        validate_base_url(config.base_url, allow_insecure=config.allow_insecure_http)

        self._api_key = self._get_api_key()
        self._base_url = config.base_url.rstrip("/")
        self._model = model_id
        self._raw_log = raw_log
        self._reasoning = reasoning

        # Timeout/retry settings from config (with fallbacks to module defaults)
        self._timeout = config.request_timeout
        self._max_retries = config.max_retries
        self._retry_backoff = config.retry_backoff

        # SSL settings for on-prem/corporate deployments
        self._verify_ssl = config.verify_ssl
        self._ssl_ca_cert = config.ssl_ca_cert

        # G1: HTTP client lifecycle - lazily created, instance-owned
        self._client: httpx.AsyncClient | None = None

    def set_raw_log_callback(self, callback: RawLogCallback | None) -> None:
        """Set or clear the raw logging callback.

        Args:
            callback: The callback to set, or None to disable raw logging.
        """
        self._raw_log = callback

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        The client is lazily created on first request and reused for subsequent
        requests. This improves connection reuse and reduces overhead.

        On Windows, if certifi's certificate bundle is missing/corrupted, falls
        back to using the Windows certificate store via ssl.create_default_context().

        Returns:
            The httpx.AsyncClient instance for making HTTP requests.
        """
        if self._client is None:
            # SSL verification settings for on-prem/corporate deployments
            # Priority: ssl_ca_cert (custom CA) > verify_ssl (bool)
            if self._ssl_ca_cert:
                verify: bool | str | ssl.SSLContext = self._ssl_ca_cert
            else:
                verify = self._verify_ssl

            try:
                self._client = httpx.AsyncClient(timeout=self._timeout, verify=verify)
            except FileNotFoundError:
                # Windows: certifi installed but cert bundle missing/corrupted
                # Fall back to system certificate store
                logger.warning(
                    "SSL certificate bundle not found (certifi issue?), "
                    "falling back to system certificates"
                )
                # Use system certificates via ssl.create_default_context()
                ssl_context = ssl.create_default_context()
                self._client = httpx.AsyncClient(timeout=self._timeout, verify=ssl_context)
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client and release resources.

        This method should be called when the provider is no longer needed.
        It is safe to call multiple times (idempotent).
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

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
            from nexus3.core.constants import get_nexus_dir

            global_config = get_nexus_dir() / "config.json"
            msg = f"API key not found. Set the {self._config.api_key_env} environment variable."

            # Help diagnose config loading issues
            if not global_config.resolve().is_file():
                msg += f"\n\nNote: No config found at {global_config}"
                msg += "\nExpected location: ~/.nexus3/config.json"
            else:
                msg += f"\n\nConfig exists at: {global_config}"
                msg += "\nCheck your provider's api_key_env setting."

            raise ProviderError(msg)
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

        for attempt in range(self._max_retries + 1):
            try:
                # G1: Use shared client instance for connection reuse
                client = await self._ensure_client()
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
                    # P2.13 SECURITY: Limit error body size to prevent memory exhaustion
                    error_body = response.content[:MAX_ERROR_BODY_SIZE]
                    error_detail = error_body.decode(errors="replace")
                    last_error = ProviderError(
                        f"API request failed with status {response.status_code}: {error_detail}"
                    )
                    if attempt < self._max_retries:
                        delay = self._calculate_retry_delay(attempt)
                        await asyncio.sleep(delay)
                        continue
                    raise last_error

                # Other client errors (400, etc.) - fail immediately
                if response.status_code >= 400:
                    # P2.13 SECURITY: Limit error body size to prevent memory exhaustion
                    error_body = response.content[:MAX_ERROR_BODY_SIZE]
                    error_detail = error_body.decode(errors="replace")
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
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                # Final attempt failed
                if isinstance(e, httpx.ConnectError):
                    raise ProviderError(
                        f"Failed to connect to API after {self._max_retries + 1} attempts: {e}"
                    ) from e
                raise ProviderError(
                    f"API request timed out after {self._max_retries + 1} attempts: {e}"
                ) from e
            except httpx.HTTPError as e:
                # Other HTTP errors - don't retry
                raise ProviderError(f"HTTP error occurred: {e}") from e

        # Shouldn't reach here, but handle it
        if last_error:
            msg = f"Request failed after {self._max_retries + 1} attempts"
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

        for attempt in range(self._max_retries + 1):
            try:
                # G1: Use shared client instance for connection reuse
                client = await self._ensure_client()
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
                        # P2.13 SECURITY: Limit error body size to prevent memory exhaustion
                        error_body = error_body[:MAX_ERROR_BODY_SIZE]
                        error_msg = error_body.decode(errors="replace")
                        last_error = ProviderError(
                            f"API request failed ({response.status_code}): {error_msg}"
                        )
                        if attempt < self._max_retries:
                            delay = self._calculate_retry_delay(attempt)
                            await asyncio.sleep(delay)
                            continue
                        raise last_error

                    # Other client errors (400, etc.) - fail immediately
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        # P2.13 SECURITY: Limit error body size to prevent memory exhaustion
                        error_body = error_body[:MAX_ERROR_BODY_SIZE]
                        error_msg = error_body.decode(errors="replace")
                        raise ProviderError(
                            f"API request failed ({response.status_code}): {error_msg}"
                        )

                    # Success - yield the response for streaming
                    yield response
                    return

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Network errors are retryable
                last_error = e
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                # Final attempt failed
                if isinstance(e, httpx.ConnectError):
                    raise ProviderError(
                        f"Failed to connect to API after {self._max_retries + 1} attempts: {e}"
                    ) from e
                raise ProviderError(
                    f"API request timed out after {self._max_retries + 1} attempts: {e}"
                ) from e
            except httpx.HTTPError as e:
                # Other HTTP errors - don't retry
                raise ProviderError(f"HTTP error occurred: {e}") from e

        # Shouldn't reach here
        if last_error:
            msg = f"Request failed after {self._max_retries + 1} attempts"
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
