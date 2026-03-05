"""Unit tests for GlobalDispatcher direct in-process ingress validation."""

from __future__ import annotations

import pytest

from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.types import Request


class _GuardPool:
    """Pool stub that should not be called by malformed envelope requests."""

    async def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("create() should not be called")

    async def destroy(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("destroy() should not be called")

    def list(self):  # type: ignore[no-untyped-def]
        raise AssertionError("list() should not be called")

    def get(self, agent_id: str):
        raise AssertionError("get() should not be called")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected_message"),
    [
        (
            ["bad"],
            "Positional params (array) not supported, use named params (object)",
        ),
        (3.14, "params must be object or array, got: float"),
    ],
)
async def test_global_dispatch_rejects_malformed_params_shape_before_handlers(
    params: object,
    expected_message: str,
) -> None:
    dispatcher = GlobalDispatcher(_GuardPool())
    request = Request(
        jsonrpc="2.0",
        method="list_agents",
        params=params,  # type: ignore[arg-type]
        id=1,
    )

    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602
    assert response.error["message"] == expected_message


@pytest.mark.asyncio
async def test_global_dispatch_rejects_boolean_id_before_handlers() -> None:
    dispatcher = GlobalDispatcher(_GuardPool())
    request = Request(
        jsonrpc="2.0",
        method="list_agents",
        params={},
        id=True,  # type: ignore[arg-type]
    )

    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602
    assert response.error["message"] == "id must be string, number, or null, got: bool"


@pytest.mark.asyncio
async def test_global_dispatch_rejects_invalid_jsonrpc_before_handlers() -> None:
    dispatcher = GlobalDispatcher(_GuardPool())
    request = Request(
        jsonrpc="1.0",
        method="list_agents",
        params={},
        id=1,
    )

    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602
    assert response.error["message"] == "jsonrpc must be '2.0', got: '1.0'"


@pytest.mark.asyncio
async def test_global_dispatch_rejects_non_string_method_before_handlers() -> None:
    dispatcher = GlobalDispatcher(_GuardPool())
    request = Request(
        jsonrpc="2.0",
        method=123,  # type: ignore[arg-type]
        params={},
        id=1,
    )

    response = await dispatcher.dispatch(request)

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602
    assert response.error["message"] == "method must be a string, got: int"
