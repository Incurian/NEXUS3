"""Unit tests for the RPC Dispatcher cancel method and send request_id tracking."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus3.core.authorization_kernel import AuthorizationDecision
from nexus3.core.permissions import PermissionLevel
from nexus3.rpc.dispatcher import Dispatcher
from nexus3.rpc.types import Request
from nexus3.session.events import ContentChunk, SessionCompleted, SessionEvent


class MockSession:
    """Mock Session that yields chunks slowly for testing cancellation."""

    def __init__(self, chunks: list[str] | None = None, delay: float = 0.0):
        """Initialize mock session.

        Args:
            chunks: List of chunks to yield. Defaults to ["Hello", " ", "World"].
            delay: Delay between chunks in seconds.
        """
        self._chunks = chunks if chunks is not None else ["Hello", " ", "World"]
        self._delay = delay
        self._halted_at_iteration_limit = False

    @property
    def halted_at_iteration_limit(self) -> bool:
        """Mock property for iteration limit state."""
        return self._halted_at_iteration_limit

    async def send(
        self,
        user_input: str,
        use_tools: bool = False,
        cancel_token: Any = None,
        user_meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield chunks with optional delay."""
        for chunk in self._chunks:
            if self._delay > 0:
                await asyncio.sleep(self._delay)
            if cancel_token and cancel_token.is_cancelled:
                return
            yield chunk

    async def run_turn(
        self,
        user_input: str,
        use_tools: bool = False,
        cancel_token: Any = None,
        user_meta: dict[str, str] | None = None,
    ) -> AsyncIterator[SessionEvent]:
        """Yield session events with optional delay (for dispatcher run_turn support)."""
        for chunk in self._chunks:
            if self._delay > 0:
                await asyncio.sleep(self._delay)
            if cancel_token and cancel_token.is_cancelled:
                return
            yield ContentChunk(text=chunk)
        yield SessionCompleted(halted_at_limit=self._halted_at_iteration_limit)


class TestCancelMethod:
    """Tests for the cancel RPC method."""

    @pytest.mark.asyncio
    async def test_cancel_missing_request_id(self):
        """Calling cancel without request_id raises InvalidParamsError."""
        session = MockSession()
        dispatcher = Dispatcher(session)

        request = Request(jsonrpc="2.0", method="cancel", params={}, id=1)
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "request_id" in response.error["message"].lower()

    @pytest.mark.asyncio
    async def test_cancel_unknown_request_id(self):
        """Cancel with unknown ID returns cancelled=False with reason."""
        session = MockSession()
        dispatcher = Dispatcher(session)

        request = Request(
            jsonrpc="2.0",
            method="cancel",
            params={"request_id": "nonexistent_id"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["cancelled"] is False
        assert response.result["reason"] == "not_found_or_completed"
        assert response.result["request_id"] == "nonexistent_id"


class TestSendRequestId:
    """Tests for request_id tracking in send method."""

    @pytest.mark.asyncio
    async def test_send_returns_request_id(self):
        """The send method returns a request_id in the response."""
        session = MockSession(chunks=["test response"])
        dispatcher = Dispatcher(session)

        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "hello"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert "request_id" in response.result
        assert isinstance(response.result["request_id"], str)
        assert len(response.result["request_id"]) > 0
        assert response.result["content"] == "test response"

    @pytest.mark.asyncio
    async def test_send_with_provided_request_id(self):
        """If client provides request_id, it's used instead of generating one."""
        session = MockSession(chunks=["test"])
        dispatcher = Dispatcher(session)

        custom_id = "my_custom_request_id_123"
        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "hello", "request_id": custom_id},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["request_id"] == custom_id

    @pytest.mark.asyncio
    async def test_cancel_active_request(self):
        """Cancel an active request successfully."""
        # Create a session that yields chunks slowly, giving time to cancel
        # The key is that the session keeps yielding after cancel is called,
        # so the dispatcher's raise_if_cancelled() check can trigger
        class SlowYieldingSession:
            """Session that keeps yielding slowly, allowing cancel to be tested."""

            @property
            def halted_at_iteration_limit(self) -> bool:
                return False

            async def send(
                self,
                user_input: str,
                use_tools: bool = False,
                cancel_token: Any = None,
                user_meta: dict[str, Any] | None = None,
            ) -> AsyncIterator[str]:
                for i in range(10):
                    await asyncio.sleep(0.05)  # Small delay between chunks
                    if cancel_token and cancel_token.is_cancelled:
                        return
                    yield f"chunk{i}"

            async def run_turn(
                self,
                user_input: str,
                use_tools: bool = False,
                cancel_token: Any = None,
                user_meta: dict[str, str] | None = None,
            ) -> AsyncIterator[SessionEvent]:
                from nexus3.session.events import SessionCancelled

                for i in range(10):
                    await asyncio.sleep(0.05)  # Small delay between chunks
                    if cancel_token and cancel_token.is_cancelled:
                        yield SessionCancelled()
                        return
                    yield ContentChunk(text=f"chunk{i}")
                yield SessionCompleted(halted_at_limit=False)

        session = SlowYieldingSession()
        dispatcher = Dispatcher(session)

        custom_id = "active_request_to_cancel"

        # Start the send request in a background task
        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "hello", "request_id": custom_id},
            id=1,
        )

        # Run send in background
        send_task = asyncio.create_task(dispatcher.dispatch(request))

        # Give it a moment to start and process first chunk
        await asyncio.sleep(0.1)

        # Now cancel it
        cancel_request = Request(
            jsonrpc="2.0",
            method="cancel",
            params={"request_id": custom_id},
            id=2,
        )
        cancel_response = await dispatcher.dispatch(cancel_request)

        # Verify cancel succeeded (token was marked as cancelled)
        assert cancel_response is not None
        assert cancel_response.error is None
        assert cancel_response.result is not None
        assert cancel_response.result["cancelled"] is True
        assert cancel_response.result["request_id"] == custom_id

        # Wait for send to complete
        send_response = await send_task

        # The send response should indicate cancellation
        # (raise_if_cancelled() was called and raised CancelledError)
        assert send_response is not None
        assert send_response.result is not None
        assert send_response.result.get("cancelled") is True
        assert send_response.result["request_id"] == custom_id


class TestDispatcherBasics:
    """Basic dispatcher tests related to request tracking."""

    @pytest.mark.asyncio
    async def test_request_id_cleaned_up_after_send_completes(self):
        """Request ID is removed from active requests after send completes."""
        session = MockSession(chunks=["done"])
        dispatcher = Dispatcher(session)

        custom_id = "will_be_cleaned_up"
        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "test", "request_id": custom_id},
            id=1,
        )

        # Send completes
        await dispatcher.dispatch(request)

        # Now cancel should fail because the request is no longer active
        cancel_request = Request(
            jsonrpc="2.0",
            method="cancel",
            params={"request_id": custom_id},
            id=2,
        )
        cancel_response = await dispatcher.dispatch(cancel_request)

        assert cancel_response.result["cancelled"] is False
        assert cancel_response.result["reason"] == "not_found_or_completed"

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests_have_different_ids(self):
        """Multiple concurrent requests get unique request IDs."""
        session = MockSession(chunks=["response"], delay=0.1)
        dispatcher = Dispatcher(session)

        # Start two requests without providing request_ids
        request1 = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "first"},
            id=1,
        )
        request2 = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "second"},
            id=2,
        )

        # Run both concurrently
        task1 = asyncio.create_task(dispatcher.dispatch(request1))
        task2 = asyncio.create_task(dispatcher.dispatch(request2))

        response1, response2 = await asyncio.gather(task1, task2)

        # Both should have request_ids and they should be different
        assert response1.result is not None
        assert response2.result is not None
        assert "request_id" in response1.result
        assert "request_id" in response2.result
        assert response1.result["request_id"] != response2.result["request_id"]


class TestSendAuthorizationKernelAuthoritative:
    """Tests for kernel-authoritative send authorization enforcement."""

    @pytest.mark.asyncio
    async def test_send_yolo_without_repl_denied_with_legacy_message(self) -> None:
        """YOLO target without REPL keeps the existing user-facing deny message."""
        session = MockSession(chunks=["unused"])
        permissions = MagicMock()
        permissions.effective_policy.level = PermissionLevel.YOLO
        services = MagicMock()
        services.get.side_effect = lambda key, default=None: (
            permissions if key == "permissions" else default
        )
        session._services = services  # Dispatcher reads permissions via session services
        pool = MagicMock()
        pool.is_repl_connected.return_value = False
        dispatcher = Dispatcher(session, agent_id="target-agent", pool=pool)

        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "hello"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602
        assert response.error["message"] == "Cannot send to YOLO agent - no REPL connected"

    @pytest.mark.asyncio
    async def test_send_kernel_allow_is_authoritative_over_legacy_yolo_gate(self) -> None:
        """Kernel allow remains authoritative even when the legacy path would deny."""
        session = MockSession(chunks=["allowed"])
        permissions = MagicMock()
        permissions.effective_policy.level = PermissionLevel.YOLO
        services = MagicMock()
        services.get.side_effect = lambda key, default=None: (
            permissions if key == "permissions" else default
        )
        session._services = services
        pool = MagicMock()
        pool.is_repl_connected.return_value = False
        dispatcher = Dispatcher(session, agent_id="target-agent", pool=pool)

        class _ForceAllowKernel:
            def authorize(self, request: Any) -> AuthorizationDecision:
                return AuthorizationDecision.allow(request, reason="forced_allow")

        dispatcher._send_authorization_kernel = _ForceAllowKernel()

        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "hello", "source_agent_id": "caller-1"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["content"] == "allowed"

    @pytest.mark.asyncio
    async def test_send_deny_maps_reason_and_uses_trusted_requester_precedence(self) -> None:
        """Kernel deny maps to generic send message and uses trusted requester_id precedence."""
        session = MockSession(chunks=["unused"])
        permissions = MagicMock()
        permissions.effective_policy.level = PermissionLevel.YOLO
        services = MagicMock()
        services.get.side_effect = lambda key, default=None: (
            permissions if key == "permissions" else default
        )
        session._services = services
        pool = MagicMock()
        pool.is_repl_connected.return_value = False
        dispatcher = Dispatcher(session, agent_id="target-agent", pool=pool)

        class _CaptureDenyKernel:
            def __init__(self) -> None:
                self.principals: list[str] = []

            def authorize(self, request: Any) -> AuthorizationDecision:
                self.principals.append(str(request.principal_id))
                return AuthorizationDecision.deny(request, reason="forced_deny")

        kernel = _CaptureDenyKernel()
        dispatcher._send_authorization_kernel = kernel

        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "hello", "source_agent_id": "spoofed-caller"},
            id=1,
        )
        response = await dispatcher.dispatch(request, requester_id="trusted-caller")

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602
        assert response.error["message"] == "send denied: forced_deny"
        assert kernel.principals == ["trusted-caller"]


class TestAgentLifecycleAuthorization:
    """Tests for kernel-authoritative shutdown/cancel/compact authorization."""

    @pytest.mark.asyncio
    async def test_shutdown_denied_by_kernel_fails_closed(self) -> None:
        """Kernel deny for shutdown returns invalid-params and does not toggle shutdown."""
        session = MockSession(chunks=["unused"])
        dispatcher = Dispatcher(session, agent_id="target-agent")

        class _ForceDenyKernel:
            def authorize(self, request: Any) -> AuthorizationDecision:
                return AuthorizationDecision.deny(request, reason="forced_deny")

        dispatcher._shutdown_authorization_kernel = _ForceDenyKernel()

        request = Request(jsonrpc="2.0", method="shutdown", params={}, id=1)
        response = await dispatcher.dispatch(request, requester_id="caller-1")

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602
        assert response.error["message"] == "shutdown denied: forced_deny"
        assert response.result is None
        assert dispatcher.should_shutdown is False

    @pytest.mark.asyncio
    async def test_cancel_denied_by_kernel_fails_closed(self) -> None:
        """Kernel deny for cancel returns invalid-params and does not execute cancel path."""
        session = MockSession(chunks=["unused"])
        dispatcher = Dispatcher(session, agent_id="target-agent")

        class _ForceDenyKernel:
            def authorize(self, request: Any) -> AuthorizationDecision:
                return AuthorizationDecision.deny(request, reason="forced_deny")

        dispatcher._cancel_authorization_kernel = _ForceDenyKernel()

        request = Request(
            jsonrpc="2.0",
            method="cancel",
            params={"request_id": "does-not-exist"},
            id=1,
        )
        response = await dispatcher.dispatch(request, requester_id="caller-2")

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602
        assert response.error["message"] == "cancel denied: forced_deny"
        assert response.result is None

    @pytest.mark.asyncio
    async def test_compact_denied_by_kernel_fails_closed(self) -> None:
        """Kernel deny for compact returns invalid-params and does not execute compaction."""

        class CompactSession(MockSession):
            async def compact(self, force: bool = True) -> Any:
                return type(
                    "CompactResult",
                    (),
                    {"original_token_count": 20, "new_token_count": 8},
                )()

        session = CompactSession(chunks=["unused"])
        dispatcher = Dispatcher(session, agent_id="target-agent")

        class _ForceDenyKernel:
            def authorize(self, request: Any) -> AuthorizationDecision:
                return AuthorizationDecision.deny(request, reason="forced_deny")

        dispatcher._compact_authorization_kernel = _ForceDenyKernel()

        request = Request(jsonrpc="2.0", method="compact", params={"force": True}, id=1)
        response = await dispatcher.dispatch(request, requester_id="caller-3")

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602
        assert response.error["message"] == "compact denied: forced_deny"
        assert response.result is None


class TestNoContextManagerErrors:
    """Tests for get_tokens/get_context without context manager."""

    @pytest.mark.asyncio
    async def test_get_tokens_no_context_returns_error_response(self):
        """get_tokens without context manager returns JSON-RPC error, not success-with-error."""
        session = MockSession()
        # Create dispatcher WITHOUT context manager
        dispatcher = Dispatcher(session, context=None)

        # Manually add the handler to simulate a misconfigured scenario
        # (normally these handlers aren't added without context, but we test the guard)
        dispatcher._handlers["get_tokens"] = dispatcher._handle_get_tokens

        request = Request(
            jsonrpc="2.0",
            method="get_tokens",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        # Should be a proper JSON-RPC error, not {"result": {"error": "..."}}
        assert response is not None
        assert response.error is not None, "Expected error field, not success-with-error"
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "context manager" in response.error["message"].lower()
        assert response.result is None

    @pytest.mark.asyncio
    async def test_get_context_no_context_returns_error_response(self):
        """get_context without context manager returns JSON-RPC error, not success-with-error."""
        session = MockSession()
        # Create dispatcher WITHOUT context manager
        dispatcher = Dispatcher(session, context=None)

        # Manually add the handler to simulate a misconfigured scenario
        dispatcher._handlers["get_context"] = dispatcher._handle_get_context

        request = Request(
            jsonrpc="2.0",
            method="get_context",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        # Should be a proper JSON-RPC error, not {"result": {"error": "..."}}
        assert response is not None
        assert response.error is not None, "Expected error field, not success-with-error"
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "context manager" in response.error["message"].lower()
        assert response.result is None


class TestInvalidParamsError:
    """Tests for InvalidParamsError handling."""

    @pytest.mark.asyncio
    async def test_cancel_with_empty_request_id(self):
        """Cancel with empty string request_id raises InvalidParamsError."""
        session = MockSession()
        dispatcher = Dispatcher(session)

        request = Request(
            jsonrpc="2.0",
            method="cancel",
            params={"request_id": ""},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_cancel_with_none_request_id(self):
        """Cancel with None request_id raises InvalidParamsError."""
        session = MockSession()
        dispatcher = Dispatcher(session)

        request = Request(
            jsonrpc="2.0",
            method="cancel",
            params={"request_id": None},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS
