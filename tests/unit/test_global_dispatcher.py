"""Unit tests for GlobalDispatcher direct in-process ingress validation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nexus3.core.authorization_kernel import AuthorizationDecision
from nexus3.core.capabilities import CapabilityClaims, CapabilitySignatureError
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


class _CapabilityPool(_GuardPool):
    def __init__(
        self,
        *,
        claims: CapabilityClaims | None = None,
        error: Exception | None = None,
    ) -> None:
        self._claims = claims
        self._error = error
        self.verify_calls: list[tuple[str, str]] = []

    def list(self):  # type: ignore[no-untyped-def]
        return []

    def verify_direct_capability(
        self,
        token: str,
        *,
        required_scope: str,
    ) -> CapabilityClaims:
        self.verify_calls.append((token, required_scope))
        if self._error is not None:
            raise self._error
        assert self._claims is not None
        return self._claims


class _CreateCapturingPool(_GuardPool):
    def __init__(self) -> None:
        self.last_create: dict[str, Any] | None = None

    async def create(
        self,
        agent_id: str | None = None,
        config: Any = None,
        requester_id: str | None = None,
    ) -> Any:
        effective_id = agent_id or "auto-1"
        self.last_create = {
            "agent_id": agent_id,
            "config": config,
            "requester_id": requester_id,
            "effective_id": effective_id,
        }
        return SimpleNamespace(agent_id=effective_id)


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
@pytest.mark.parametrize(
    ("params", "expected_message"),
    [
        ({}, "Field required"),
        ({"agent_id": 123}, "Input should be a valid string"),
    ],
)
async def test_global_dispatch_destroy_agent_uses_canonical_schema_validation_for_malformed_params(
    params: dict[str, object],
    expected_message: str,
) -> None:
    dispatcher = GlobalDispatcher(_GuardPool())
    request = Request(
        jsonrpc="2.0",
        method="destroy_agent",
        params=params,
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


@pytest.mark.asyncio
async def test_global_dispatch_rejects_invalid_capability_token() -> None:
    pool = _CapabilityPool(error=CapabilitySignatureError("bad signature"))
    dispatcher = GlobalDispatcher(pool)
    request = Request(
        jsonrpc="2.0",
        method="list_agents",
        params={},
        id=1,
    )

    response = await dispatcher.dispatch(request, capability_token="bad-token")

    assert response is not None
    assert response.error is not None
    assert response.error["code"] == -32602
    assert "Invalid capability token" in response.error["message"]


@pytest.mark.asyncio
async def test_global_dispatch_uses_capability_subject_identity() -> None:
    claims = CapabilityClaims(
        token_id="tok-1",
        issuer_id="issuer-1",
        subject_id="subject-7",
        scopes=("rpc:global:list_agents",),
        issued_at=1,
        expires_at=10,
    )
    pool = _CapabilityPool(claims=claims)
    dispatcher = GlobalDispatcher(pool)

    captured_principals: list[str] = []

    def _allow_and_capture(request):  # type: ignore[no-untyped-def]
        captured_principals.append(str(request.principal_id))
        return AuthorizationDecision.allow(request, reason="ok")

    dispatcher._list_agents_authorization_kernel.authorize = _allow_and_capture
    request = Request(
        jsonrpc="2.0",
        method="list_agents",
        params={},
        id=1,
    )

    response = await dispatcher.dispatch(request, capability_token="cap-token")

    assert response is not None
    assert response.error is None
    assert response.result == {"agents": []}
    assert pool.verify_calls == [("cap-token", "rpc:global:list_agents")]
    assert captured_principals == ["subject-7"]


@pytest.mark.asyncio
async def test_global_create_agent_sandboxed_without_allowed_write_paths_disables_all_write_tools(
) -> None:
    pool = _CreateCapturingPool()
    dispatcher = GlobalDispatcher(pool)
    request = Request(
        jsonrpc="2.0",
        method="create_agent",
        params={
            "agent_id": "worker-1",
            "preset": "sandboxed",
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

    assert pool.last_create is not None
    config = pool.last_create["config"]
    assert config is not None
    assert config.delta is not None

    tool_overrides = config.delta.tool_overrides
    for tool_name in (
        "write_file",
        "edit_file",
        "edit_lines",
        "append_file",
        "regex_replace",
        "patch",
        "mkdir",
        "copy_file",
        "rename",
    ):
        assert tool_name in tool_overrides
        assert tool_overrides[tool_name].enabled is False
