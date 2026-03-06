"""Tests for nexus3.core.authorization_kernel."""

from dataclasses import FrozenInstanceError

import pytest

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
    CreateAuthorizationContext,
    CreateAuthorizationStage,
)


def _build_request() -> AuthorizationRequest:
    return AuthorizationRequest(
        action=AuthorizationAction.AGENT_SEND,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.AGENT,
            identifier="agent-2",
            attributes={"depth": 1},
        ),
        principal_id="agent-1",
        context={"source": "rpc"},
    )


class _AllowAdapter:
    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        return AuthorizationDecision.allow(request, reason="adapter_allow")


class _SkipAdapter:
    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        return None


class TestAuthorizationDecision:
    def test_allow_helper_sets_fields(self) -> None:
        request = _build_request()

        decision = AuthorizationDecision.allow(
            request,
            reason="ok",
            metadata={"policy": "legacy"},
        )

        assert decision.allowed is True
        assert decision.reason == "ok"
        assert decision.request == request
        assert decision.metadata == {"policy": "legacy"}

    def test_deny_helper_and_raise_if_denied(self) -> None:
        request = _build_request()
        decision = AuthorizationDecision.deny(request, reason="blocked")

        assert decision.allowed is False
        with pytest.raises(PermissionError, match="blocked"):
            decision.raise_if_denied()


class TestAuthorizationSchemas:
    def test_request_and_resource_are_frozen(self) -> None:
        request = _build_request()

        with pytest.raises(FrozenInstanceError):
            request.principal_id = "other"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            request.resource.identifier = "agent-3"  # type: ignore[misc]


class TestCreateAuthorizationContext:
    def test_round_trip_scalar_context_map(self) -> None:
        context = CreateAuthorizationContext(
            check_stage=CreateAuthorizationStage.BASE_CEILING,
            parent_depth=1,
            max_depth=5,
            parent_permissions_json='{"base_preset":"trusted"}',
            requested_permissions_json='{"base_preset":"sandboxed"}',
            parent_agent_id="parent-1",
        )

        serialized = context.to_context_map()
        parsed = CreateAuthorizationContext.from_context_map(serialized)

        assert parsed == context
        assert serialized["check_stage"] == "base_ceiling"

    def test_from_context_map_rejects_invalid_shapes(self) -> None:
        invalid_context = {
            "check_stage": "base_ceiling",
            "parent_depth": True,  # bool should not be accepted as int
            "max_depth": 5,
            "parent_permissions_json": 1,
        }

        parsed = CreateAuthorizationContext.from_context_map(invalid_context)
        assert parsed is None


class TestAdapterAuthorizationKernel:
    def test_adapter_decision_takes_precedence(self) -> None:
        request = _build_request()
        kernel = AdapterAuthorizationKernel(adapters=(_SkipAdapter(), _AllowAdapter()))

        decision = kernel.authorize(request)

        assert decision.allowed is True
        assert decision.reason == "adapter_allow"

    def test_default_deny_when_no_adapter_handles_request(self) -> None:
        request = _build_request()
        kernel = AdapterAuthorizationKernel(adapters=(_SkipAdapter(),))

        decision = kernel.authorize(request)

        assert decision.allowed is False
        assert decision.reason == "default_deny"

    def test_default_allow_mode(self) -> None:
        request = _build_request()
        kernel = AdapterAuthorizationKernel(default_allow=True)

        decision = kernel.authorize(request)

        assert decision.allowed is True
        assert decision.reason == "default_allow"

