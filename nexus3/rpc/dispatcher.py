"""JSON-RPC method dispatcher for NEXUS3 headless mode."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from nexus3.core.cancel import CancellationToken

logger = logging.getLogger(__name__)
from nexus3.rpc.dispatch_core import InvalidParamsError, dispatch_request
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
            "compact": self._handle_compact,
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
        return await dispatch_request(request, self._handlers, "method")

    async def _handle_send(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'send' method.

        Sends a message to the LLM and returns the full response.
        Non-streaming: accumulates all chunks before returning.

        Args:
            params: Must contain 'content' key with message text.
                   Optional 'request_id' for cancellation support.

        Returns:
            Dict with keys:
            - content: The assistant's response text
            - request_id: Request identifier for cancellation
            - halted_at_iteration_limit: True if max tool iterations was reached

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

            return {
                "content": "".join(chunks),
                "request_id": request_id,
                "halted_at_iteration_limit": self._session.halted_at_iteration_limit,
            }
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

        Raises:
            InvalidParamsError: If no context manager is configured.
        """
        if not self._context:
            raise InvalidParamsError("No context manager configured")
        return self._context.get_token_usage()

    async def _handle_get_context(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'get_context' method.

        Returns context information (message count, system prompt status, iteration state).

        Args:
            params: Ignored.

        Returns:
            Dict with context information including:
            - message_count: Number of messages in context
            - system_prompt: Whether system prompt is set
            - halted_at_iteration_limit: Whether last send() hit max iterations
            - last_iteration_count: Number of iterations in last send()
            - max_tool_iterations: Configured max iterations limit

        Raises:
            InvalidParamsError: If no context manager is configured.
        """
        if not self._context:
            raise InvalidParamsError("No context manager configured")
        messages = self._context.messages
        return {
            "message_count": len(messages),
            "system_prompt": bool(self._context.system_prompt),
            "halted_at_iteration_limit": self._session.halted_at_iteration_limit,
            "last_iteration_count": self._session.last_iteration_count,
            "max_tool_iterations": self._session.max_tool_iterations,
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
        # D4: Use 'is None' not truthiness - request_id=0 is valid JSON-RPC id
        # But reject empty string explicitly (almost certainly a user error)
        if request_id is None or request_id == "":
            raise InvalidParamsError("Missing required parameter: request_id")

        token = self._active_requests.get(request_id)
        if token:
            token.cancel()
            return {"cancelled": True, "request_id": request_id}
        return {"cancelled": False, "request_id": request_id, "reason": "not_found_or_completed"}

    async def _handle_compact(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'compact' method.

        Forces context compaction/summarization to reclaim token space.
        This is useful for recovering stuck agents that have exceeded
        their context window.

        Args:
            params: Optional 'force' key (default: True for RPC).

        Returns:
            Dict with compaction result:
            - compacted: True, tokens_before, tokens_after, tokens_saved
            OR
            - compacted: False, reason: why compaction didn't occur
        """
        force = params.get("force", True)  # Default to force for RPC

        result = await self._session.compact(force=force)

        if result is None:
            return {
                "compacted": False,
                "reason": "nothing_to_compact",
            }

        return {
            "compacted": True,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "tokens_saved": result.tokens_before - result.tokens_after,
        }

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
