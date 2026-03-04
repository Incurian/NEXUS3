"""Focused tests for Plan H Phase 2 compat-safe schema ingress wiring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nexus3.rpc.dispatcher import Dispatcher
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.types import Request


class _StubSession:
    halted_at_iteration_limit = False
    last_iteration_count = 0
    max_tool_iterations = 10

    async def compact(self, force: bool = True) -> Any:
        return SimpleNamespace(original_token_count=10, new_token_count=6)


class _StubPool:
    async def destroy(
        self,
        agent_id: str,
        requester_id: str | None = None,
        *,
        admin_override: bool = False,
    ) -> bool:
        return False

    async def create(self, agent_id: str | None = None, config: Any = None) -> Any:
        raise AssertionError("create() should not be called in this test")

    def list(self) -> list[dict[str, Any]]:
        return []

    def get(self, agent_id: str) -> Any:
        return None


@pytest.mark.asyncio
async def test_dispatcher_get_messages_schema_validation_preserves_error_style() -> None:
    message = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="hello",
        tool_call_id=None,
    )
    context = SimpleNamespace(messages=[message], system_prompt=None)
    dispatcher = Dispatcher(_StubSession(), context=context, agent_id="agent-1")

    request = Request(
        jsonrpc="2.0",
        method="get_messages",
        params={"offset": "1"},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "offset must be a non-negative integer"


@pytest.mark.asyncio
async def test_global_destroy_agent_schema_validation_rejects_malformed_id() -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="destroy_agent",
        params={"agent_id": "../../escape"},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "invalid agent id" in response.error["message"].lower()


@pytest.mark.asyncio
async def test_dispatcher_cancel_schema_validation_preserves_missing_error_style() -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
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
    assert response.error["message"] == "Missing required parameter: request_id"


@pytest.mark.asyncio
async def test_dispatcher_compact_schema_validation_rejects_invalid_force() -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="compact",
        params={"force": {"invalid": True}},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "boolean" in response.error["message"].lower()
