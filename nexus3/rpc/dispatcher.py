"""JSON-RPC method dispatcher for NEXUS3 headless mode."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
)
from nexus3.core.cancel import CancellationToken
from nexus3.core.permissions import PermissionLevel
from nexus3.core.request_context import RequestContext
from nexus3.rpc.dispatch_core import InvalidParamsError, dispatch_request
from nexus3.rpc.schemas import (
    CancelParamsSchema,
    CompactParamsSchema,
    EmptyParamsSchema,
    GetMessagesParamsSchema,
    SendParamsSchema,
)
from nexus3.rpc.types import Request, Response
from nexus3.session import Session

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nexus3.context.manager import ContextManager
    from nexus3.rpc.log_multiplexer import LogMultiplexer
    from nexus3.rpc.pool import AgentPool

# Type alias for handler functions
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class _SendAuthorizationAdapter:
    """Kernel adapter mirroring legacy YOLO/REPL send authorization checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.AGENT_SEND:
            return None
        if request.resource.resource_type != AuthorizationResourceType.AGENT:
            return None

        is_yolo_agent = bool(request.context.get("is_yolo_agent"))
        repl_connected = bool(request.context.get("repl_connected"))

        if not is_yolo_agent:
            return AuthorizationDecision.allow(request, reason="not_yolo_agent")
        if repl_connected:
            return AuthorizationDecision.allow(request, reason="repl_connected")
        return AuthorizationDecision.deny(request, reason="no_repl_for_yolo")


class _ShutdownAuthorizationAdapter:
    """Kernel adapter mirroring legacy dispatcher shutdown policy."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.SESSION_WRITE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.RPC:
            return None
        if request.resource.identifier != "shutdown":
            return None
        return AuthorizationDecision.allow(request, reason="shutdown_allowed")


class _CancelAuthorizationAdapter:
    """Kernel adapter mirroring legacy dispatcher cancel policy."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.SESSION_WRITE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.RPC:
            return None
        if request.resource.identifier != "cancel":
            return None
        return AuthorizationDecision.allow(request, reason="cancel_allowed")


class _CompactAuthorizationAdapter:
    """Kernel adapter mirroring legacy dispatcher compact policy."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.SESSION_WRITE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.RPC:
            return None
        if request.resource.identifier != "compact":
            return None
        return AuthorizationDecision.allow(request, reason="compact_allowed")


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
        pool: AgentPool | None = None,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            session: The Session instance to use for LLM interactions.
            context: Optional ContextManager for token/context info.
            agent_id: The agent's ID for log routing (required if log_multiplexer provided).
            log_multiplexer: Optional multiplexer for routing raw logs to correct agent.
            pool: Optional AgentPool for REPL connection state checks.
        """
        self._session = session
        self._context = context
        self._agent_id = agent_id
        self._log_multiplexer = log_multiplexer
        self._pool = pool
        self._should_shutdown = False
        self._active_requests: dict[str | int, CancellationToken] = {}
        self._turn_lock = asyncio.Lock()
        self._send_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_SendAuthorizationAdapter(),),
            default_allow=False,
        )
        self._shutdown_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_ShutdownAuthorizationAdapter(),),
            default_allow=False,
        )
        self._cancel_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_CancelAuthorizationAdapter(),),
            default_allow=False,
        )
        self._compact_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_CompactAuthorizationAdapter(),),
            default_allow=False,
        )

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

    async def dispatch(
        self,
        request: Request,
        requester_id: str | None = None,
    ) -> Response | None:
        """Dispatch a request to the appropriate handler.

        Args:
            request: The parsed JSON-RPC request.
            requester_id: Requesting agent identity when available.

        Returns:
            A Response object, or None for notifications (requests without id).
        """
        request_context = RequestContext(
            requester_id=requester_id,
            request_id=str(request.id) if request.id is not None else None,
        )
        handlers = dict(self._handlers)

        async def handle_send_with_context(params: dict[str, Any]) -> dict[str, Any]:
            return await self._handle_send(params, request_context)

        async def handle_shutdown_with_context(params: dict[str, Any]) -> dict[str, Any]:
            return await self._handle_shutdown(params, request_context)

        async def handle_cancel_with_context(params: dict[str, Any]) -> dict[str, Any]:
            return await self._handle_cancel(params, request_context)

        async def handle_compact_with_context(params: dict[str, Any]) -> dict[str, Any]:
            return await self._handle_compact(params, request_context)

        handlers["send"] = handle_send_with_context
        handlers["shutdown"] = handle_shutdown_with_context
        handlers["cancel"] = handle_cancel_with_context
        handlers["compact"] = handle_compact_with_context

        return await dispatch_request(request, handlers, "method")

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

    async def _handle_send(
        self,
        params: dict[str, Any],
        request_context: RequestContext | None = None,
    ) -> dict[str, Any]:
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
        try:
            validated = SendParamsSchema.model_validate(params, strict=False)
        except PydanticValidationError as exc:
            errors = exc.errors()
            if errors:
                error = errors[0]
                loc = error.get("loc", ())
                field = str(loc[0]) if loc else None
                raw_value = params.get(field) if field else None
                if field == "content":
                    if error.get("type") == "missing" or raw_value is None:
                        raise InvalidParamsError("Missing required parameter: content") from exc
                    raise InvalidParamsError(
                        f"content must be string, got: {type(raw_value).__name__}"
                    ) from exc
                if field == "request_id":
                    if raw_value == "":
                        raise InvalidParamsError("request_id cannot be empty") from exc
                    raise InvalidParamsError("request_id must be string or integer") from exc
                if field == "source":
                    raise InvalidParamsError(
                        f"source must be string, got: {type(raw_value).__name__}"
                    ) from exc
                if field == "source_agent_id":
                    raise InvalidParamsError(
                        "source_agent_id must be string or integer, "
                        f"got: {type(raw_value).__name__}"
                    ) from exc
                if error.get("type") == "extra_forbidden":
                    raise InvalidParamsError(
                        str(error.get("msg", "Invalid send parameters"))
                    ) from exc
            raise InvalidParamsError("Invalid send parameters") from exc

        # Block RPC sends to YOLO agents when no REPL connected
        if self._pool and self._agent_id:
            permissions = (
                self._session._services.get("permissions")
                if self._session._services else None
            )
            is_yolo_agent = bool(
                permissions and permissions.effective_policy.level == PermissionLevel.YOLO
            )
            repl_connected = bool(self._pool.is_repl_connected(self._agent_id))
            principal_id = (
                request_context.requester_id
                if request_context is not None and request_context.requester_id is not None
                else (
                    str(validated.source_agent_id)
                    if validated.source_agent_id is not None
                    else (validated.source or "rpc")
                )
            )
            kernel_request = AuthorizationRequest(
                action=AuthorizationAction.AGENT_SEND,
                resource=AuthorizationResource(
                    resource_type=AuthorizationResourceType.AGENT,
                    identifier=self._agent_id,
                ),
                principal_id=principal_id,
                context={
                    "is_yolo_agent": is_yolo_agent,
                    "repl_connected": repl_connected,
                },
            )
            kernel_decision = self._send_authorization_kernel.authorize(kernel_request)
            if not kernel_decision.allowed:
                reason = kernel_decision.reason or "authorization policy denied request"
                if reason == "no_repl_for_yolo":
                    raise InvalidParamsError(
                        "Cannot send to YOLO agent - no REPL connected"
                    )
                raise InvalidParamsError(f"send denied: {reason}")

        content = validated.content

        # Source attribution (stored in Message.meta)
        # Default missing source to "rpc" to ensure external sends have attribution
        source = validated.source or "rpc"
        source_agent_id = validated.source_agent_id

        # Build user_meta for non-repl sends (REPL-originated messages don't need attribution)
        user_meta: dict[str, str] | None = None
        if source != "repl":
            user_meta = {"source": source}
            if source_agent_id:
                user_meta["source_agent_id"] = str(source_agent_id)

        # Generate or use provided request_id
        request_id = (
            validated.request_id
            if validated.request_id is not None
            else secrets.token_hex(8)
        )

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

    async def _handle_shutdown(
        self,
        params: dict[str, Any],
        request_context: RequestContext | None = None,
    ) -> dict[str, Any]:
        """Handle the 'shutdown' method.

        Sets the shutdown flag to signal the main loop to exit.

        Args:
            params: Ignored.

        Returns:
            Dict with 'success' key set to True.
        """
        try:
            EmptyParamsSchema.model_validate(params, strict=True)
        except PydanticValidationError as exc:
            raise InvalidParamsError("Invalid shutdown parameters") from exc

        self._enforce_lifecycle_authorization("shutdown", request_context)

        self._should_shutdown = True
        return {"success": True}

    def _enforce_lifecycle_authorization(
        self,
        method: str,
        request_context: RequestContext | None,
    ) -> None:
        principal_id = (
            request_context.requester_id
            if request_context is not None and request_context.requester_id is not None
            else "rpc"
        )
        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.SESSION_WRITE,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.RPC,
                identifier=method,
            ),
            principal_id=principal_id,
        )
        kernel = {
            "shutdown": self._shutdown_authorization_kernel,
            "cancel": self._cancel_authorization_kernel,
            "compact": self._compact_authorization_kernel,
        }[method]
        kernel_decision = kernel.authorize(kernel_request)
        if not kernel_decision.allowed:
            reason = kernel_decision.reason or "authorization policy denied request"
            raise InvalidParamsError(f"{method} denied: {reason}")

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
        try:
            EmptyParamsSchema.model_validate(params, strict=True)
        except PydanticValidationError as exc:
            raise InvalidParamsError("Invalid get_tokens parameters") from exc

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
        try:
            EmptyParamsSchema.model_validate(params, strict=True)
        except PydanticValidationError as exc:
            raise InvalidParamsError("Invalid get_context parameters") from exc

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
        candidate: dict[str, Any] = {}
        if "offset" in params:
            candidate["offset"] = params["offset"]
        if "limit" in params:
            candidate["limit"] = params["limit"]

        try:
            validated = GetMessagesParamsSchema.model_validate(candidate, strict=True)
        except PydanticValidationError as exc:
            for error in exc.errors():
                loc = error.get("loc", ())
                field = loc[0] if loc else None
                if field == "offset":
                    raise InvalidParamsError(
                        "offset must be a non-negative integer"
                    ) from exc
                if field == "limit":
                    raise InvalidParamsError(
                        "limit must be an integer between 1 and 2000"
                    ) from exc
            raise InvalidParamsError("Invalid get_messages parameters") from exc

        offset = validated.offset
        limit = validated.limit

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

    async def _handle_cancel(
        self,
        params: dict[str, Any],
        request_context: RequestContext | None = None,
    ) -> dict[str, Any]:
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
        try:
            validated = CancelParamsSchema.model_validate(
                params,
                strict=False,
            )
        except PydanticValidationError as exc:
            errors = exc.errors()
            if errors:
                error = errors[0]
                loc = error.get("loc", ())
                field = str(loc[0]) if loc else None
                raw_value = params.get(field) if field else None
                if field == "request_id":
                    if error.get("type") == "missing" or raw_value == "":
                        raise InvalidParamsError("Missing required parameter: request_id") from exc
                    raise InvalidParamsError("request_id must be string or integer") from exc
                if error.get("type") == "extra_forbidden":
                    raise InvalidParamsError(
                        str(error.get("msg", "Invalid request_id"))
                    ) from exc
            raise InvalidParamsError("Invalid request_id") from exc

        self._enforce_lifecycle_authorization("cancel", request_context)

        request_id = validated.request_id
        token = self._active_requests.get(request_id)
        if token:
            token.cancel()
            return {"cancelled": True, "request_id": request_id}
        return {"cancelled": False, "request_id": request_id, "reason": "not_found_or_completed"}

    async def _handle_compact(
        self,
        params: dict[str, Any],
        request_context: RequestContext | None = None,
    ) -> dict[str, Any]:
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
        try:
            validated = CompactParamsSchema.model_validate(params, strict=False)
        except PydanticValidationError as exc:
            errors = exc.errors()
            if errors:
                raise InvalidParamsError(str(errors[0].get("msg", "Invalid force value"))) from exc
            raise InvalidParamsError("Invalid compact parameters") from exc

        self._enforce_lifecycle_authorization("compact", request_context)

        force = validated.force

        result = await self._session.compact(force=force)

        if result is None:
            return {
                "compacted": False,
                "reason": "nothing_to_compact",
            }

        return {
            "compacted": True,
            "tokens_before": result.original_token_count,
            "tokens_after": result.new_token_count,
            "tokens_saved": result.original_token_count - result.new_token_count,
        }

    async def _handle_cancel_all(self, params: dict[str, Any]) -> dict[str | int, bool]:
        """Handle cooperative cancellation for all active requests.

        Args:
            params: Ignored.

        Returns:
            Dict mapping request_id -> True for all cancelled requests.
        """
        try:
            EmptyParamsSchema.model_validate(params, strict=True)
        except PydanticValidationError as exc:
            raise InvalidParamsError("Invalid cancel_all parameters") from exc

        cancelled: dict[str | int, bool] = {}
        for request_id, token in list(self._active_requests.items()):
            token.cancel()
            cancelled[request_id] = True
        return cancelled

    async def cancel_all_requests(self) -> dict[str | int, bool]:
        """Cancel all in-progress requests.

        This is called during agent destruction to gracefully cancel
        any in-flight operations. Uses cooperative cancellation via tokens.

        Returns:
            Dict mapping request_id -> True for all cancelled requests.
        """
        return await self._handle_cancel_all({})
