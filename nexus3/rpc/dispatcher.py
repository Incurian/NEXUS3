"""JSON-RPC method dispatcher for NEXUS3 headless mode."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from nexus3.core.cancel import CancellationToken
from nexus3.core.errors import NexusError

logger = logging.getLogger(__name__)
from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    make_error_response,
    make_success_response,
)
from nexus3.rpc.types import Request, Response
from nexus3.session import Session

if TYPE_CHECKING:
    from nexus3.context.manager import ContextManager
    from nexus3.rpc.log_multiplexer import LogMultiplexer

# Type alias for handler functions
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class Dispatcher:
    """Routes JSON-RPC requests to handler methods.

    The dispatcher manages method routing and maintains session state.
    It handles the standard methods 'send' and 'shutdown'.

    Attributes:
        should_shutdown: True when shutdown has been requested.
    """

    def __init__(
        self,
        session: Session,
        context: ContextManager | None = None,
        agent_id: str | None = None,
        log_multiplexer: LogMultiplexer | None = None,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            session: The Session instance to use for LLM interactions.
            context: Optional ContextManager for token/context info.
            agent_id: The agent's ID for log routing (required if log_multiplexer provided).
            log_multiplexer: Optional multiplexer for routing raw logs to correct agent.
        """
        self._session = session
        self._context = context
        self._agent_id = agent_id
        self._log_multiplexer = log_multiplexer
        self._should_shutdown = False
        self._active_requests: dict[str, CancellationToken] = {}
        self._handlers: dict[str, Handler] = {
            "send": self._handle_send,
            "shutdown": self._handle_shutdown,
            "cancel": self._handle_cancel,
        }

        # Add context-dependent handlers if context is available
        if context:
            self._handlers["get_tokens"] = self._handle_get_tokens
            self._handlers["get_context"] = self._handle_get_context

    @property
    def should_shutdown(self) -> bool:
        """Return True if shutdown has been requested."""
        return self._should_shutdown

    def request_shutdown(self) -> None:
        """Request shutdown of the dispatcher.

        Sets the should_shutdown flag to True, which signals the server
        to gracefully shut down.
        """
        self._should_shutdown = True

    async def dispatch(self, request: Request) -> Response | None:
        """Dispatch a request to the appropriate handler.

        Args:
            request: The parsed JSON-RPC request.

        Returns:
            A Response object, or None for notifications (requests without id).
        """
        # Look up handler
        handler = self._handlers.get(request.method)
        if handler is None:
            # Method not found
            if request.id is None:
                return None  # Notifications don't get error responses
            return make_error_response(
                request.id,
                METHOD_NOT_FOUND,
                f"Method not found: {request.method}",
            )

        # Execute handler
        try:
            params = request.params or {}
            result = await handler(params)

            # Return response (None for notifications)
            if request.id is None:
                return None
            return make_success_response(request.id, result)

        except InvalidParamsError as e:
            if request.id is None:
                return None
            return make_error_response(request.id, INVALID_PARAMS, str(e))

        except NexusError as e:
            if request.id is None:
                return None
            return make_error_response(request.id, INTERNAL_ERROR, e.message)

        except Exception as e:
            logger.error("Unexpected error dispatching method '%s': %s", method, e, exc_info=True)
            if request.id is None:
                return None
            return make_error_response(
                request.id,
                INTERNAL_ERROR,
                f"Internal error: {type(e).__name__}: {e}",
            )

    async def _handle_send(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'send' method.

        Sends a message to the LLM and returns the full response.
        Non-streaming: accumulates all chunks before returning.

        Args:
            params: Must contain 'content' key with message text.
                   Optional 'request_id' for cancellation support.

        Returns:
            Dict with 'content' and 'request_id' keys.

        Raises:
            InvalidParamsError: If 'content' is missing.
        """
        content = params.get("content")
        if content is None:
            raise InvalidParamsError("Missing required parameter: content")
        if not isinstance(content, str):
            raise InvalidParamsError(f"content must be string, got: {type(content).__name__}")

        # Generate or use provided request_id
        request_id = params.get("request_id") or secrets.token_hex(8)

        # Create cancellation token and track it
        token = CancellationToken()
        self._active_requests[request_id] = token

        try:
            # Accumulate all chunks (non-streaming)
            # Wrap in agent context for correct log routing
            chunks: list[str] = []
            if self._log_multiplexer and self._agent_id:
                with self._log_multiplexer.agent_context(self._agent_id):
                    async for chunk in self._session.send(content, cancel_token=token):
                        token.raise_if_cancelled()
                        chunks.append(chunk)
            else:
                async for chunk in self._session.send(content, cancel_token=token):
                    token.raise_if_cancelled()
                    chunks.append(chunk)

            return {"content": "".join(chunks), "request_id": request_id}
        except asyncio.CancelledError:
            return {"cancelled": True, "request_id": request_id}
        finally:
            self._active_requests.pop(request_id, None)

    async def _handle_shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'shutdown' method.

        Sets the shutdown flag to signal the main loop to exit.

        Args:
            params: Ignored.

        Returns:
            Dict with 'success' key set to True.
        """
        self._should_shutdown = True
        return {"success": True}

    async def _handle_get_tokens(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'get_tokens' method.

        Returns token usage information from the context manager.

        Args:
            params: Ignored.

        Returns:
            Dict with token usage breakdown.
        """
        if not self._context:
            return {"error": "No context manager"}
        return self._context.get_token_usage()

    async def _handle_get_context(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'get_context' method.

        Returns context information (message count, system prompt status).

        Args:
            params: Ignored.

        Returns:
            Dict with context information.
        """
        if not self._context:
            return {"error": "No context manager"}
        messages = self._context.messages
        return {
            "message_count": len(messages),
            "system_prompt": bool(self._context.system_prompt),
        }

    async def _handle_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'cancel' method.

        Cancels an in-progress request by its request_id.

        Args:
            params: Must contain 'request_id' key.

        Returns:
            Dict with 'cancelled' boolean and 'request_id'.
            If not found, includes 'reason': 'not_found_or_completed'.

        Raises:
            InvalidParamsError: If 'request_id' is missing.
        """
        request_id = params.get("request_id")
        if not request_id:
            raise InvalidParamsError("Missing required parameter: request_id")

        token = self._active_requests.get(request_id)
        if token:
            token.cancel()
            return {"cancelled": True, "request_id": request_id}
        return {"cancelled": False, "request_id": request_id, "reason": "not_found_or_completed"}

    async def cancel_all_requests(self) -> dict[str, bool]:
        """Cancel all in-progress requests.

        This is called during agent destruction to gracefully cancel
        any in-flight operations. Uses cooperative cancellation via tokens.

        Returns:
            Dict mapping request_id -> True for all cancelled requests.
        """
        cancelled = {}
        for request_id, token in list(self._active_requests.items()):
            token.cancel()
            cancelled[request_id] = True
        return cancelled


class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""
