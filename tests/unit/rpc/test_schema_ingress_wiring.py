"""Focused tests for Plan H Phase 2 compat-safe schema ingress wiring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nexus3.rpc.dispatcher import Dispatcher
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.protocol import ParseError, parse_request
from nexus3.rpc.types import Request


class _StubSession:
    halted_at_iteration_limit = False
    last_iteration_count = 0
    max_tool_iterations = 10

    async def compact(self, force: bool = True) -> Any:
        return SimpleNamespace(original_token_count=10, new_token_count=6)


class _StreamingStubSession(_StubSession):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(
        self,
        content: str,
        cancel_token: Any = None,
        user_meta: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "content": content,
                "cancel_token": cancel_token,
                "user_meta": user_meta,
            }
        )
        yield "ok"


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


class _NoParentLookupPool(_StubPool):
    def get(self, agent_id: str) -> Any:
        raise AssertionError("get() should not be called in this test")


class _CreateCapableStubPool(_StubPool):
    def __init__(self) -> None:
        self.last_create: dict[str, Any] | None = None

    async def create(self, agent_id: str | None = None, config: Any = None) -> Any:
        effective_id = agent_id or "auto-1"
        self.last_create = {"agent_id": agent_id, "config": config, "effective_id": effective_id}
        return SimpleNamespace(agent_id=effective_id)


class _StubContext:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.system_prompt = None

    def get_token_usage(self) -> dict[str, int]:
        return {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}


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
@pytest.mark.parametrize(
    ("request_id", "expected_message"),
    [
        (True, "request_id must be string or integer"),
        ("", "request_id cannot be empty"),
        ({"bad": "shape"}, "request_id must be string or integer"),
    ],
)
async def test_dispatcher_send_schema_validation_rejects_malformed_request_id_shape(
    request_id: object,
    expected_message: str,
) -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="send",
        params={"content": "hello", "request_id": request_id},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected_message"),
    [
        (
            {"content": "hello", "source": 123},
            "source must be string, got: int",
        ),
        (
            {"content": "hello", "source_agent_id": {"bad": "shape"}},
            "source_agent_id must be string or integer, got: dict",
        ),
        (
            {"content": "hello", "source_agent_id": False},
            "source_agent_id must be string or integer, got: bool",
        ),
    ],
)
async def test_dispatcher_send_schema_validation_rejects_malformed_optional_attribution_params(
    params: dict[str, object],
    expected_message: str,
) -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="send",
        params=params,
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
async def test_dispatcher_send_missing_content_preserves_error_style() -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="send",
        params={},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "Missing required parameter: content"


@pytest.mark.asyncio
async def test_dispatcher_send_ingress_wiring_keeps_compat_with_benign_extra_params() -> None:
    session = _StreamingStubSession()
    dispatcher = Dispatcher(session, context=None, agent_id="agent-1")

    request = Request(
        jsonrpc="2.0",
        method="send",
        params={
            "content": "hello",
            "request_id": "req-1",
            "source": "rpc",
            "trace_id": "benign-extra",
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is None
    assert response.result == {
        "content": "ok",
        "request_id": "req-1",
        "halted_at_iteration_limit": False,
    }
    assert session.calls[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_global_create_agent_schema_validation_rejects_malformed_agent_id_shape() -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={"agent_id": ["bad"]},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "agent_id" in response.error["message"].lower()


@pytest.mark.asyncio
async def test_global_create_agent_rejects_blank_initial_message() -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={"initial_message": "   "},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "initial_message cannot be empty"


@pytest.mark.asyncio
async def test_global_create_agent_parent_id_wiring_blocks_lookup_for_malformed_id() -> None:
    dispatcher = GlobalDispatcher(_NoParentLookupPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "child-1",
            "parent_agent_id": "../../escape",
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "Parent agent not found: ../../escape"


@pytest.mark.asyncio
async def test_global_create_agent_wait_flag_wiring_rejects_invalid_type_pre_create() -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "initial_message": "hello",
            "wait_for_initial_response": {"bad": True},
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "wait_for_initial_response must be boolean"


@pytest.mark.asyncio
async def test_global_create_agent_ingress_wiring_keeps_compat_with_benign_extra_params() -> None:
    pool = _CreateCapableStubPool()
    dispatcher = GlobalDispatcher(pool)

    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "preset": "sandboxed",
            "allowed_write_paths": [],
            "benign_extra": "value",
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is None
    assert response.result == {
        "agent_id": "worker-1",
        "url": "/agent/worker-1",
    }


def test_parse_request_rejects_malformed_object_id_shape() -> None:
    with pytest.raises(ParseError, match="id must be string, number, or null"):
        parse_request(
            '{"jsonrpc":"2.0","method":"send","params":{"content":"hi"},"id":{"bad":1}}'
        )


def test_parse_request_rejects_boolean_id() -> None:
    with pytest.raises(ParseError, match="id must be string, number, or null, got: bool"):
        parse_request('{"jsonrpc":"2.0","method":"send","params":{"content":"hi"},"id":true}')


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


@pytest.mark.asyncio
async def test_dispatcher_noarg_ingress_wiring_keeps_compat_with_extra_params() -> None:
    dispatcher = Dispatcher(_StubSession(), context=_StubContext(), agent_id="agent-1")

    shutdown_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="shutdown",
            params={"unexpected": "value"},
            id=1,
        )
    )
    get_tokens_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="get_tokens",
            params={"unexpected": "value"},
            id=2,
        )
    )
    get_context_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="get_context",
            params={"unexpected": "value"},
            id=3,
        )
    )

    assert shutdown_response is not None
    assert shutdown_response.error is None
    assert shutdown_response.result == {"success": True}

    assert get_tokens_response is not None
    assert get_tokens_response.error is None
    assert get_tokens_response.result == {
        "input_tokens": 3,
        "output_tokens": 4,
        "total_tokens": 7,
    }

    assert get_context_response is not None
    assert get_context_response.error is None
    assert get_context_response.result == {
        "message_count": 0,
        "system_prompt": False,
        "halted_at_iteration_limit": False,
        "last_iteration_count": 0,
        "max_tool_iterations": 10,
    }


@pytest.mark.asyncio
async def test_global_noarg_ingress_wiring_keeps_compat_with_extra_params() -> None:
    dispatcher = GlobalDispatcher(_StubPool())

    list_agents_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="list_agents",
            params={"unexpected": "value"},
            id=1,
        )
    )
    shutdown_server_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="shutdown_server",
            params={"unexpected": "value"},
            id=2,
        )
    )

    assert list_agents_response is not None
    assert list_agents_response.error is None
    assert list_agents_response.result == {"agents": []}

    assert shutdown_server_response is not None
    assert shutdown_server_response.error is None
    assert shutdown_server_response.result == {
        "success": True,
        "message": "Server shutting down",
    }
