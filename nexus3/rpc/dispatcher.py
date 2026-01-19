"""JSON-RPC method dispatcher for NEXUS3 headless mode."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from nexus3.core.cancel import CancellationToken
from nexus3.core.text_safety import strip_terminal_escapes
from nexus3.rpc.dispatch_core import InvalidParamsError, dispatch_request
from nexus3.rpc.event_hub import EventHub
from nexus3.rpc.types import Request, Response
from nexus3.session import Session
from nexus3.session.events import (
    ContentChunk,
    IterationCompleted,
    ReasoningEnded,
    ReasoningStarted,
    SessionCancelled,
    SessionCompleted,
    SessionEvent,
    ToolBatchCompleted,
    ToolBatchHalted,
    ToolBatchStarted,
    ToolCompleted,
    ToolDetected,
    ToolStarted,
)

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
        event_hub: EventHub | None = None,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            session: The Session instance to use for LLM interactions.
            context: Optional ContextManager for token/context info.
            agent_id: The agent's ID for log routing (required if log_multiplexer provided).
            log_multiplexer: Optional multiplexer for routing raw logs to correct agent.
            event_hub: Optional EventHub for publishing SSE events for this agent.
        """
        self._session = session
        self._context = context
        self._agent_id = agent_id
        self._log_multiplexer = log_multiplexer
        self._event_hub = event_hub
        self._should_shutdown = False
        self._active_requests: dict[str, CancellationToken] = {}
        self._turn_lock = asyncio.Lock()
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

    async def _publish_event(self, event: dict[str, Any]) -> None:
        """Publish an SSE event for this agent (no-op if not configured)."""
        if self._event_hub is None:
            return
        if not self._agent_id:
            # Agent dispatchers should always have an agent_id, but fail closed
            return
        # Enforce canonical agent_id (overwrite any incorrect value)
        event["agent_id"] = self._agent_id
        await self._event_hub.publish(self._agent_id, event)

    @staticmethod
    def _format_tool_params(arguments: dict[str, Any], max_length: int = 70) -> str:
        """Format tool arguments as a short human-readable preview.

        NOTE: This intentionally does NOT import REPL-only formatting helpers.
        Output is used for remote UI tool lines (gumballs/spinner).
        """
        if not arguments:
            return ""

        # Drop private/meta args (e.g. _parallel) from preview
        filtered: dict[str, Any] = {}
        for k, v in arguments.items():
            if v is None:
                continue
            if str(k).startswith("_"):
                continue
            filtered[str(k)] = v

        if not filtered:
            return ""

        # Priority keys (paths/cwd/ids first)
        priority_keys = (
            "path",
            "file",
            "file_path",
            "directory",
            "dir",
            "cwd",
            "agent_id",
            "source",
            "destination",
            "src",
            "dst",
        )

        parts: list[str] = []

        def _safe_str(x: Any) -> str:
            # Remove ANSI/control chars and normalize whitespace for single-line UI rendering
            s = strip_terminal_escapes(str(x))
            # Normalize all whitespace (newlines, tabs, etc.) to single spaces
            return " ".join(s.split())

        # Priority args first (full value, but overall string may be truncated later)
        for key in priority_keys:
            if key in filtered and filtered[key] not in ("", None):
                parts.append(f"{key}={_safe_str(filtered[key])}")

        # Remaining args (truncate individual values)
        for key, value in filtered.items():
            if key in priority_keys:
                continue
            s = _safe_str(value)
            if len(s) > 30:
                s = s[:27] + "..."
            if isinstance(value, str) and " " in s:
                s = f'"{s}"'
            parts.append(f"{key}={s}")

        result = ", ".join(parts)
        if len(result) > max_length:
            result = result[: max_length - 3] + "..."
        return result

    def _map_session_event_to_sse(
        self,
        event: SessionEvent,
        *,
        request_id: str,
        turn_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Map SessionEvent instances to SSE event dicts (Phase 0 contract)."""
        if isinstance(event, ContentChunk):
            return {
                "type": "content_chunk",
                "request_id": request_id,
                "text": event.text,
            }

        if isinstance(event, ReasoningStarted):
            turn_state["thinking_started_at"] = time.monotonic()
            return {
                "type": "thinking_started",
                "request_id": request_id,
            }

        if isinstance(event, ReasoningEnded):
            started_at = turn_state.get("thinking_started_at")
            duration_ms = 0
            if isinstance(started_at, (int, float)):
                duration_ms = max(0, int((time.monotonic() - started_at) * 1000))
            turn_state["thinking_started_at"] = None
            return {
                "type": "thinking_ended",
                "request_id": request_id,
                "duration_ms": duration_ms,
            }

        if isinstance(event, ToolDetected):
            return {
                "type": "tool_detected",
                "request_id": request_id,
                "name": event.name,
                "tool_id": event.tool_id,
            }

        if isinstance(event, ToolBatchStarted):
            tools = []
            for tc in event.tool_calls:
                tools.append(
                    {
                        "name": tc.name,
                        "id": tc.id,
                        "params": self._format_tool_params(tc.arguments),
                    }
                )
            return {
                "type": "batch_started",
                "request_id": request_id,
                "tools": tools,
                # Extra fields (clients may ignore)
                "parallel": event.parallel,
                "timestamp": event.timestamp,
            }

        if isinstance(event, ToolStarted):
            return {
                "type": "tool_started",
                "request_id": request_id,
                "tool_id": event.tool_id,
                # Extra fields (clients may ignore)
                "name": event.name,
                "timestamp": event.timestamp,
            }

        if isinstance(event, ToolCompleted):
            return {
                "type": "tool_completed",
                "request_id": request_id,
                "tool_id": event.tool_id,
                "success": event.success,
                # Extra fields (clients may ignore)
                "name": event.name,
                "error": event.error,
                "timestamp": event.timestamp,
            }

        if isinstance(event, ToolBatchHalted):
            return {
                "type": "batch_halted",
                "request_id": request_id,
                # Extra fields (clients may ignore)
                "timestamp": event.timestamp,
            }

        if isinstance(event, ToolBatchCompleted):
            return {
                "type": "batch_completed",
                "request_id": request_id,
                # Extra fields (clients may ignore)
                "timestamp": event.timestamp,
            }

        # Not in Phase 0 SSE contract (drop for now)
        if isinstance(event, IterationCompleted):
            return None

        # Terminal events are handled at Dispatcher level to emit turn_completed/turn_cancelled
        if isinstance(event, (SessionCompleted, SessionCancelled)):
            return None

        return None

    async def _handle_send(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the 'send' method.

        Sends a message to the LLM and returns the full response.
        Non-streaming: accumulates all chunks before returning.
        Publishes SSE events for real-time UI sync.

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
            async with self._turn_lock:
                # Check cancellation BEFORE emitting turn_started
                # (avoids confusing turn_started -> immediate turn_cancelled sequence)
                if token.is_cancelled:
                    # Emit turn_cancelled so SSE consumers always get a terminal event
                    # (even if the turn never started - they need to know it's done)
                    await self._publish_event(
                        {"type": "turn_cancelled", "request_id": request_id}
                    )
                    return {"cancelled": True, "request_id": request_id}

                await self._publish_event(
                    {"type": "turn_started", "request_id": request_id}
                )

                chunks: list[str] = []
                halted_at_limit = False
                cancelled = False
                turn_state: dict[str, Any] = {"thinking_started_at": None}

                try:
                    # Wrap in agent context for correct raw log routing
                    if self._log_multiplexer and self._agent_id:
                        with self._log_multiplexer.agent_context(self._agent_id):
                            async for ev in self._session.run_turn(content, cancel_token=token):
                                sse = self._map_session_event_to_sse(
                                    ev, request_id=request_id, turn_state=turn_state
                                )
                                if sse:
                                    await self._publish_event(sse)

                                if isinstance(ev, ContentChunk):
                                    chunks.append(ev.text)
                                elif isinstance(ev, SessionCompleted):
                                    halted_at_limit = ev.halted_at_limit
                                elif isinstance(ev, SessionCancelled):
                                    cancelled = True
                    else:
                        async for ev in self._session.run_turn(content, cancel_token=token):
                            sse = self._map_session_event_to_sse(
                                ev, request_id=request_id, turn_state=turn_state
                            )
                            if sse:
                                await self._publish_event(sse)

                            if isinstance(ev, ContentChunk):
                                chunks.append(ev.text)
                            elif isinstance(ev, SessionCompleted):
                                halted_at_limit = ev.halted_at_limit
                            elif isinstance(ev, SessionCancelled):
                                cancelled = True

                except asyncio.CancelledError:
                    await self._publish_event(
                        {"type": "turn_cancelled", "request_id": request_id}
                    )
                    return {"cancelled": True, "request_id": request_id}
                except Exception:
                    # Unexpected error - emit turn_cancelled so SSE consumers get terminal event
                    await self._publish_event(
                        {"type": "turn_cancelled", "request_id": request_id}
                    )
                    raise  # Re-raise so JSON-RPC returns the error

                if cancelled:
                    # If we were mid-thinking, emit a best-effort thinking_ended
                    if turn_state.get("thinking_started_at") is not None:
                        started_at = float(turn_state["thinking_started_at"])
                        duration_ms = max(0, int((time.monotonic() - started_at) * 1000))
                        await self._publish_event(
                            {
                                "type": "thinking_ended",
                                "request_id": request_id,
                                "duration_ms": duration_ms,
                            }
                        )
                    await self._publish_event(
                        {"type": "turn_cancelled", "request_id": request_id}
                    )
                    return {"cancelled": True, "request_id": request_id}

                full_content = "".join(chunks)
                await self._publish_event(
                    {
                        "type": "turn_completed",
                        "request_id": request_id,
                        "content": full_content,
                        "halted": halted_at_limit,
                    }
                )

                return {
                    "content": full_content,
                    "request_id": request_id,
                    "halted_at_iteration_limit": halted_at_limit,
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
