"""JSON-RPC method dispatcher for NEXUS3 headless mode."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from nexus3.core.cancel import CancellationToken
from nexus3.rpc.dispatch_core import InvalidParamsError, dispatch_request
from nexus3.rpc.types import Request, Response
from nexus3.session import Session

logger = logging.getLogger(__name__)

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
        self._turn_lock = asyncio.Lock()

        # REPL hook: called when a non-REPL send triggers a turn
        self.on_incoming_turn: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None
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
            self._handlers["get_messages"] = self._handle_get_messages

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

    async def _notify_incoming(self, payload: dict[str, Any]) -> None:
        """Notify the REPL about an incoming turn (non-REPL source).

        This is called when a subagent or external client sends a message,
        allowing the REPL to show tool-like progress indicators.
        """
        cb = self.on_incoming_turn
        if cb is None:
            return
        try:
            await cb(payload)
        except Exception:
            logger.debug("incoming-turn hook failed", exc_info=True)

    async def _handle_send(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'send' method.

        Sends a message to the LLM and returns the full response.
        Uses Session.send() for streaming; accumulates chunks before returning.

        Args:
            params: Must contain 'content' key with message text.
                   Optional 'request_id' for cancellation support.
                   Optional 'source' and 'source_agent_id' for attribution.

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
            raise InvalidParamsError(
                f"content must be string, got: {type(content).__name__}"
            )

        # Source attribution (stored in Message.meta)
        # Default missing source to "rpc" to ensure external sends have attribution
        source = params.get("source") or "rpc"
        source_agent_id = params.get("source_agent_id")

        # Build user_meta for non-repl sends (REPL-originated messages don't need attribution)
        user_meta: dict[str, str] | None = None
        if source != "repl":
            user_meta = {"source": source}
            if source_agent_id:
                user_meta["source_agent_id"] = str(source_agent_id)

        # Generate or use provided request_id
        request_id = params.get("request_id") or secrets.token_hex(8)

        # Create cancellation token and track it
        token = CancellationToken()
        self._active_requests[request_id] = token

        try:
            async with self._turn_lock:
                # Check cancellation before starting
                if token.is_cancelled:
                    return {"cancelled": True, "request_id": request_id}

                # Notify REPL when this is an incoming (non-repl) message
                if source != "repl":
                    preview = (content[:80] + "...") if len(content) > 80 else content
                    await self._notify_incoming(
                        {
                            "phase": "started",
                            "request_id": request_id,
                            "source": source,
                            "source_agent_id": source_agent_id,
                            "preview": preview,
                        }
                    )

                chunks: list[str] = []
                try:
                    # Wrap in agent context for correct raw log routing
                    if self._log_multiplexer and self._agent_id:
                        with self._log_multiplexer.agent_context(self._agent_id):
                            async for chunk in self._session.send(
                                content,
                                cancel_token=token,
                                user_meta=user_meta,
                            ):
                                token.raise_if_cancelled()
                                chunks.append(chunk)
                    else:
                        async for chunk in self._session.send(
                            content,
                            cancel_token=token,
                            user_meta=user_meta,
                        ):
                            token.raise_if_cancelled()
                            chunks.append(chunk)

                    # Final check after loop ends (session may have stopped early)
                    token.raise_if_cancelled()

                    full = "".join(chunks)

                    # Notify REPL of completion
                    if source != "repl":
                        preview = (full[:80] + "...") if len(full) > 80 else full
                        await self._notify_incoming(
                            {
                                "phase": "ended",
                                "request_id": request_id,
                                "ok": True,
                                "content_preview": preview,
                            }
                        )

                    return {
                        "content": full,
                        "request_id": request_id,
                        "halted_at_iteration_limit": self._session.halted_at_iteration_limit,
                    }

                except asyncio.CancelledError:
                    if source != "repl":
                        await self._notify_incoming(
                            {
                                "phase": "ended",
                                "request_id": request_id,
                                "ok": False,
                                "cancelled": True,
                            }
                        )
                    return {"cancelled": True, "request_id": request_id}

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

    async def _handle_get_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get recent message history for transcript sync.

        Args:
            params: Must contain:
                - offset: int (default 0) - Start index
                - limit: int (default 200, max 2000) - Number of messages

        Returns:
            Dict with agent_id, total, offset, limit, and messages array.

        Raises:
            InvalidParamsError: If offset/limit are invalid.
        """
        offset = params.get("offset", 0)
        limit = params.get("limit", 200)

        if not isinstance(offset, int) or offset < 0:
            raise InvalidParamsError("offset must be a non-negative integer")
        if not isinstance(limit, int) or limit <= 0 or limit > 2000:
            raise InvalidParamsError("limit must be an integer between 1 and 2000")

        if not self._context:
            raise InvalidParamsError("No context manager configured")

        msgs = self._context.messages
        total = len(msgs)
        slice_ = msgs[offset : offset + limit]

        def serialize_message(msg: Any, idx: int) -> dict[str, Any]:
            out: dict[str, Any] = {
                "index": idx,
                "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                "content": msg.content,
                "tool_call_id": msg.tool_call_id,
            }
            # Phase 5b: include meta if present
            meta = getattr(msg, "meta", None)
            if meta:
                out["meta"] = meta
            return out

        serialized = [serialize_message(m, offset + i) for i, m in enumerate(slice_)]

        return {
            "agent_id": self._agent_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "messages": serialized,
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
