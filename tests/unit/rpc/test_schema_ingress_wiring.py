"""Focused tests for Plan H strict schema ingress wiring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nexus3.core.cancel import CancellationToken
from nexus3.rpc.dispatcher import Dispatcher
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.protocol import ParseError, parse_request, parse_response
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

    async def create(
        self,
        agent_id: str | None = None,
        config: Any = None,
        requester_id: str | None = None,
    ) -> Any:
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

    async def create(
        self,
        agent_id: str | None = None,
        config: Any = None,
        requester_id: str | None = None,
    ) -> Any:
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
@pytest.mark.parametrize(
    ("params", "expected_message"),
    [
        ({"offset": "1"}, "offset must be a non-negative integer"),
        ({"offset": -1}, "offset must be a non-negative integer"),
        ({"limit": 0}, "limit must be an integer between 1 and 2000"),
        ({"limit": 2001}, "limit must be an integer between 1 and 2000"),
        ({"limit": "10"}, "limit must be an integer between 1 and 2000"),
    ],
)
async def test_dispatcher_get_messages_schema_validation_preserves_error_style(
    params: dict[str, object],
    expected_message: str,
) -> None:
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
        params=params,
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
async def test_dispatcher_get_messages_schema_validation_rejects_unknown_extra_params() -> None:
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
        params={"offset": 0, "limit": 10, "unexpected": "value"},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "Invalid get_messages parameters"


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
async def test_global_destroy_agent_schema_validation_rejects_unknown_extra_params() -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="destroy_agent",
        params={"agent_id": "agent-1", "unexpected": "value"},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "extra inputs are not permitted" in response.error["message"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_id", "expected_message"),
    [
        (True, "request_id must be string or integer"),
        (1.0, "request_id must be string or integer"),
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
            {"content": "hello", "source": b"rpc"},
            "source must be string, got: bytes",
        ),
        (
            {"content": "hello", "source_agent_id": {"bad": "shape"}},
            "source_agent_id must be string or integer, got: dict",
        ),
        (
            {"content": "hello", "source_agent_id": 1.0},
            "source_agent_id must be string or integer, got: float",
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
@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        (None, "Missing required parameter: content"),
        (123, "content must be string, got: int"),
        (False, "content must be string, got: bool"),
    ],
)
async def test_dispatcher_send_content_validation_preserves_error_wording(
    content: object,
    expected_message: str,
) -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="send",
        params={"content": content},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
async def test_dispatcher_send_ingress_wiring_rejects_unknown_extra_params() -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")

    request = Request(
        jsonrpc="2.0",
        method="send",
        params={
            "content": "hello",
            "request_id": "req-1",
            "source": "rpc",
            "trace_id": "unexpected-extra",
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "extra inputs are not permitted" in response.error["message"].lower()


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
@pytest.mark.parametrize("wait_for_initial_response", ["true", 1])
async def test_global_create_agent_wait_flag_wiring_rejects_coercible_values_pre_create(
    wait_for_initial_response: object,
) -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "initial_message": "hello",
            "wait_for_initial_response": wait_for_initial_response,
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "wait_for_initial_response must be boolean"


@pytest.mark.asyncio
async def test_global_create_agent_parent_id_wiring_rejects_invalid_type_pre_lookup() -> None:
    dispatcher = GlobalDispatcher(_NoParentLookupPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "parent_agent_id": 7,
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "parent_agent_id must be string, got: int"


@pytest.mark.asyncio
async def test_global_create_agent_wait_flag_rejected_without_initial_message() -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
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
async def test_global_create_agent_wait_flag_accepts_valid_bool_without_initial_message() -> None:
    pool = _CreateCapableStubPool()
    dispatcher = GlobalDispatcher(pool)
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "wait_for_initial_response": True,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("allowed_write_paths", "expected_message"),
    [
        ("not-a-list", "allowed_write_paths must be array, got: str"),
        ([1], "allowed_write_paths[0] must be string, got: int"),
    ],
)
async def test_global_create_agent_allowed_write_paths_wiring_rejects_malformed_type_shape(
    allowed_write_paths: object,
    expected_message: str,
) -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "allowed_write_paths": allowed_write_paths,
        },
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
async def test_global_create_agent_allowed_write_paths_wiring_accepts_valid_list() -> None:
    pool = _CreateCapableStubPool()
    dispatcher = GlobalDispatcher(pool)
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "preset": "sandboxed",
            "allowed_write_paths": ["tmp-out"],
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


@pytest.mark.asyncio
async def test_global_create_agent_ingress_wiring_rejects_unknown_extra_params() -> None:
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
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "extra inputs are not permitted" in response.error["message"].lower()


def test_parse_request_rejects_malformed_object_id_shape() -> None:
    with pytest.raises(ParseError, match="id must be string, number, or null"):
        parse_request(
            '{"jsonrpc":"2.0","method":"send","params":{"content":"hi"},"id":{"bad":1}}'
        )


def test_parse_request_rejects_non_object_payload_with_legacy_wording() -> None:
    with pytest.raises(ParseError, match="Request must be a JSON object"):
        parse_request('["not","an","object"]')


def test_parse_request_schema_ingress_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ParseError, match="Invalid JSON-RPC request"):
        parse_request(
            '{"jsonrpc":"2.0","method":"send","params":{"content":"hi"},"id":1,"extra":"ignored"}'
        )


def test_parse_request_rejects_empty_method_with_clear_wording() -> None:
    with pytest.raises(ParseError, match="method must be a non-empty string"):
        parse_request('{"jsonrpc":"2.0","method":"","params":{"content":"hi"},"id":1}')


def test_parse_request_rejects_boolean_id() -> None:
    with pytest.raises(ParseError, match="id must be string, number, or null, got: bool"):
        parse_request('{"jsonrpc":"2.0","method":"send","params":{"content":"hi"},"id":true}')


def test_parse_request_rejects_non_string_method_with_legacy_wording() -> None:
    with pytest.raises(ParseError, match="method must be a string, got: int"):
        parse_request('{"jsonrpc":"2.0","method":123,"params":{"content":"hi"}}')


def test_parse_request_rejects_scalar_params_with_legacy_wording() -> None:
    with pytest.raises(ParseError, match="params must be object or array, got: int"):
        parse_request('{"jsonrpc":"2.0","method":"send","params":7}')


def test_parse_request_rejects_array_params_with_legacy_wording() -> None:
    expected = "Positional params \\(array\\) not supported, use named params \\(object\\)"
    with pytest.raises(
        ParseError,
        match=expected,
    ):
        parse_request('{"jsonrpc":"2.0","method":"send","params":["hi"]}')


def test_parse_request_rejects_invalid_jsonrpc_with_legacy_wording() -> None:
    with pytest.raises(ParseError, match=r"jsonrpc must be '2.0', got: '1.0'"):
        parse_request('{"jsonrpc":"1.0","method":"send","params":{"content":"hi"}}')


def test_parse_response_rejects_malformed_error_shape() -> None:
    with pytest.raises(ParseError, match="error must have 'code' and 'message' fields"):
        parse_response('{"jsonrpc":"2.0","id":1,"error":{"message":"missing-code"}}')


def test_parse_response_rejects_non_object_error_shape() -> None:
    with pytest.raises(ParseError, match="error must be an object, got: str"):
        parse_response('{"jsonrpc":"2.0","id":1,"error":"boom"}')


def test_parse_response_rejects_malformed_error_code_type() -> None:
    with pytest.raises(ParseError, match="Invalid JSON-RPC response"):
        parse_response('{"jsonrpc":"2.0","id":1,"error":{"code":"bad","message":"boom"}}')


def test_parse_response_rejects_malformed_error_message_type() -> None:
    with pytest.raises(ParseError, match="Invalid JSON-RPC response"):
        parse_response('{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":7}}')


def test_parse_response_rejects_error_extra_fields() -> None:
    with pytest.raises(ParseError, match="Invalid JSON-RPC response"):
        parse_response(
            '{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"boom","extra":"x"}}'
        )


def test_parse_response_returns_error_payload_as_plain_dict_without_default_fields() -> None:
    response = parse_response('{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"boom"}}')

    assert response.error == {"code": -32000, "message": "boom"}
    assert isinstance(response.error, dict)


def test_parse_response_schema_ingress_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ParseError, match="Invalid JSON-RPC response"):
        parse_response('{"jsonrpc":"2.0","id":1,"result":null,"extra":"ignored"}')


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{}, {"request_id": ""}])
async def test_dispatcher_cancel_schema_validation_preserves_missing_error_style(
    params: dict[str, object],
) -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="cancel",
        params=params,
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "Missing required parameter: request_id"


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [True, 1.0, {"bad": "shape"}])
async def test_dispatcher_cancel_schema_validation_rejects_malformed_request_id_type(
    request_id: object,
) -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="cancel",
        params={"request_id": request_id},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "request_id must be string or integer"


@pytest.mark.asyncio
async def test_dispatcher_cancel_schema_validation_accepts_integer_request_id_happy_path() -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    token = CancellationToken()
    dispatcher._active_requests[7] = token

    request = Request(
        jsonrpc="2.0",
        method="cancel",
        params={"request_id": 7},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is None
    assert response.result == {"cancelled": True, "request_id": 7}
    assert token.is_cancelled is True


@pytest.mark.asyncio
async def test_dispatcher_cancel_schema_validation_rejects_unknown_extra_params() -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="cancel",
        params={"request_id": "req-1", "unexpected": "value"},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "extra inputs are not permitted" in response.error["message"].lower()


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
@pytest.mark.parametrize("force_value", ["true", 1])
async def test_dispatcher_compact_schema_validation_rejects_coercible_force_values(
    force_value: object,
) -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="compact",
        params={"force": force_value},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "boolean" in response.error["message"].lower()


@pytest.mark.asyncio
async def test_dispatcher_compact_schema_validation_rejects_unknown_extra_params() -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request = Request(
        jsonrpc="2.0",
        method="compact",
        params={"force": True, "unexpected": "value"},
        id=1,
    )
    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert "extra inputs are not permitted" in response.error["message"].lower()


@pytest.mark.asyncio
async def test_dispatcher_cancel_all_noarg_ingress_wiring_rejects_extra_params() -> None:
    dispatcher = Dispatcher(_StubSession(), context=None, agent_id="agent-1")
    request_a = CancellationToken()
    request_b = CancellationToken()
    dispatcher._active_requests["req-a"] = request_a
    dispatcher._active_requests[7] = request_b
    dispatcher._handlers["cancel_all"] = dispatcher._handle_cancel_all

    response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="cancel_all",
            params={"unexpected": "value"},
            id=1,
        )
    )

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "Invalid cancel_all parameters"
    assert request_a.is_cancelled is False
    assert request_b.is_cancelled is False


@pytest.mark.asyncio
async def test_dispatcher_noarg_ingress_wiring_rejects_extra_params() -> None:
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
    assert shutdown_response.error is not None
    assert shutdown_response.error["code"] == -32602  # INVALID_PARAMS
    assert shutdown_response.error["message"] == "Invalid shutdown parameters"

    assert get_tokens_response is not None
    assert get_tokens_response.error is not None
    assert get_tokens_response.error["code"] == -32602  # INVALID_PARAMS
    assert get_tokens_response.error["message"] == "Invalid get_tokens parameters"

    assert get_context_response is not None
    assert get_context_response.error is not None
    assert get_context_response.error["code"] == -32602  # INVALID_PARAMS
    assert get_context_response.error["message"] == "Invalid get_context parameters"


@pytest.mark.asyncio
async def test_global_noarg_ingress_wiring_rejects_extra_params() -> None:
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
    assert list_agents_response.error is not None
    assert list_agents_response.error["code"] == -32602  # INVALID_PARAMS
    assert list_agents_response.error["message"] == "Invalid list_agents parameters"

    assert shutdown_server_response is not None
    assert shutdown_server_response.error is not None
    assert shutdown_server_response.error["code"] == -32602  # INVALID_PARAMS
    assert shutdown_server_response.error["message"] == "Invalid shutdown_server parameters"


@pytest.mark.asyncio
async def test_global_shutdown_server_ingress_wiring_rejects_extra_params() -> None:
    dispatcher = GlobalDispatcher(_StubPool())

    shutdown_server_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="shutdown_server",
            params={"unexpected": "value"},
            id=1,
        )
    )

    assert shutdown_server_response is not None
    assert shutdown_server_response.error is not None
    assert shutdown_server_response.error["code"] == -32602  # INVALID_PARAMS
    assert shutdown_server_response.error["message"] == "Invalid shutdown_server parameters"


@pytest.mark.asyncio
async def test_global_list_agents_ingress_wiring_rejects_extra_params() -> None:
    dispatcher = GlobalDispatcher(_StubPool())

    list_agents_response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="list_agents",
            params={"unexpected": "value"},
            id=1,
        )
    )

    assert list_agents_response is not None
    assert list_agents_response.error is not None
    assert list_agents_response.error["code"] == -32602  # INVALID_PARAMS
    assert list_agents_response.error["message"] == "Invalid list_agents parameters"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_obj", "expected_message"),
    [
        (
            Request(
                jsonrpc="2.0",
                method="send",
                params=["hello"],  # type: ignore[arg-type]
                id=1,
            ),
            "Positional params (array) not supported, use named params (object)",
        ),
        (
            Request(
                jsonrpc="2.0",
                method="send",
                params={"content": "hello"},
                id=True,  # type: ignore[arg-type]
            ),
            "id must be string, number, or null, got: bool",
        ),
    ],
)
async def test_dispatcher_direct_ingress_wiring_rejects_malformed_request_envelope_or_shape(
    request_obj: Request,
    expected_message: str,
) -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    response = await dispatcher.dispatch(request_obj)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_obj", "expected_message"),
    [
        (
            Request(
                jsonrpc="2.0",
                method="list_agents",
                params=7,  # type: ignore[arg-type]
                id=1,
            ),
            "params must be object or array, got: int",
        ),
        (
            Request(
                jsonrpc="2.0",
                method=123,  # type: ignore[arg-type]
                params={},
                id=1,
            ),
            "method must be a string, got: int",
        ),
    ],
)
async def test_global_direct_ingress_wiring_rejects_malformed_request_envelope_or_shape(
    request_obj: Request,
    expected_message: str,
) -> None:
    dispatcher = GlobalDispatcher(_StubPool())
    response = await dispatcher.dispatch(request_obj)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["send", "list_agents"])
async def test_direct_dispatch_rejects_non_string_params_keys(method: str) -> None:
    request_obj = Request(
        jsonrpc="2.0",
        method=method,
        params={1: "bad"},  # type: ignore[arg-type]
        id=1,
    )

    if method == "send":
        dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    else:
        dispatcher = GlobalDispatcher(_StubPool())

    response = await dispatcher.dispatch(request_obj)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602  # INVALID_PARAMS
    assert response.error["message"] == "params keys must be strings, got: int"


@pytest.mark.asyncio
async def test_direct_dispatch_drops_malformed_notification_response() -> None:
    dispatcher = Dispatcher(_StreamingStubSession(), context=None, agent_id="agent-1")
    response = await dispatcher.dispatch(
        Request(
            jsonrpc="2.0",
            method="send",
            params={1: "bad"},  # type: ignore[arg-type]
            id=None,
        )
    )

    assert response is None
