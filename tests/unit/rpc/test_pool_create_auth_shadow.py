"""Tests for authoritative create authorization in AgentPool."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.authorization_kernel import (
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
    CreateAuthorizationContext,
    CreateAuthorizationStage,
)
from nexus3.core.permissions import PermissionDelta, ToolPermission, resolve_preset
from nexus3.rpc.pool import (
    MAX_AGENT_DEPTH,
    AgentConfig,
    AgentPool,
    SharedComponents,
    _CreateAuthorizationAdapter,
)


def _create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create minimal shared components required by AgentPool.create."""
    config = MagicMock()
    config.permissions.default_preset = "sandboxed"
    config.skill_timeout = 30.0
    config.max_tool_iterations = 10
    config.max_concurrent_tools = 10
    config.default_provider = None
    config.resolve_model.return_value = MagicMock(
        provider_name="default",
        model_id="test-model",
        reasoning=None,
        context_window=100000,
    )

    provider_registry = MagicMock()
    provider_registry.get.return_value = MagicMock()

    base_context = MagicMock()
    base_context.system_prompt = "test prompt"
    base_context.sources.prompt_sources = []

    context_loader = MagicMock()

    return SharedComponents(
        config=config,
        provider_registry=provider_registry,
        base_log_dir=tmp_path / "logs",
        base_context=base_context,
        context_loader=context_loader,
    )


async def _create_parent_agent(
    pool: AgentPool,
    *,
    parent_agent_id: str = "parent-agent",
    preset: str = "trusted",
) -> Any:
    with patch("nexus3.skill.builtin.register_builtin_skills"):
        return await pool.create(
            config=AgentConfig(
                agent_id=parent_agent_id,
                preset=preset,
            )
        )


class _DenyCreateStageKernel:
    def __init__(self, check_stage: str) -> None:
        self._check_stage = check_stage

    def authorize(self, request: Any) -> AuthorizationDecision:
        if request.context.get("check_stage") == self._check_stage:
            return AuthorizationDecision.deny(request, reason="forced_deny_for_test")
        return AuthorizationDecision.allow(request, reason="forced_allow_for_test")


def _build_create_request(create_context: CreateAuthorizationContext) -> AuthorizationRequest:
    return AuthorizationRequest(
        action=AuthorizationAction.AGENT_CREATE,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.AGENT,
            identifier="child-test-agent",
        ),
        principal_id="requester-agent",
        context=create_context.to_context_map(),
    )


def test_create_adapter_base_ceiling_allow_uses_typed_context_permissions() -> None:
    adapter = _CreateAuthorizationAdapter()
    parent_permissions = resolve_preset("trusted")
    requested_permissions = resolve_preset("sandboxed")
    create_context = CreateAuthorizationContext(
        check_stage=CreateAuthorizationStage.BASE_CEILING,
        parent_depth=0,
        max_depth=MAX_AGENT_DEPTH,
        parent_permissions_json=json.dumps(parent_permissions.to_dict(), sort_keys=True),
        requested_permissions_json=json.dumps(requested_permissions.to_dict(), sort_keys=True),
    )

    decision = adapter.authorize(_build_create_request(create_context))
    assert decision is not None
    assert decision.allowed is True
    assert decision.reason == "base_preset_within_parent_ceiling"


def test_create_adapter_delta_ceiling_deny_uses_typed_context_permissions() -> None:
    adapter = _CreateAuthorizationAdapter()
    parent_permissions = resolve_preset("sandboxed")
    requested_permissions = resolve_preset("trusted")
    create_context = CreateAuthorizationContext(
        check_stage=CreateAuthorizationStage.DELTA_CEILING,
        parent_depth=0,
        max_depth=MAX_AGENT_DEPTH,
        parent_permissions_json=json.dumps(parent_permissions.to_dict(), sort_keys=True),
        requested_permissions_json=json.dumps(requested_permissions.to_dict(), sort_keys=True),
    )

    decision = adapter.authorize(_build_create_request(create_context))
    assert decision is not None
    assert decision.allowed is False
    assert decision.reason == "delta_exceeds_parent_ceiling"


def test_create_adapter_base_ceiling_missing_permissions_payload_denies() -> None:
    adapter = _CreateAuthorizationAdapter()
    create_context = CreateAuthorizationContext(
        check_stage=CreateAuthorizationStage.BASE_CEILING,
        parent_depth=0,
        max_depth=MAX_AGENT_DEPTH,
    )

    decision = adapter.authorize(_build_create_request(create_context))
    assert decision is not None
    assert decision.allowed is False
    assert decision.reason == "invalid_create_context"


def test_create_adapter_base_ceiling_malformed_permissions_payload_denies() -> None:
    adapter = _CreateAuthorizationAdapter()
    parent_permissions = resolve_preset("trusted")
    create_context = CreateAuthorizationContext(
        check_stage=CreateAuthorizationStage.BASE_CEILING,
        parent_depth=0,
        max_depth=MAX_AGENT_DEPTH,
        parent_permissions_json=json.dumps(parent_permissions.to_dict(), sort_keys=True),
        requested_permissions_json="not-json",
    )

    decision = adapter.authorize(_build_create_request(create_context))
    assert decision is not None
    assert decision.allowed is False
    assert decision.reason == "invalid_create_context"


@pytest.mark.asyncio
async def test_create_authoritative_max_depth_denial_preserves_wording(
    tmp_path: Path,
) -> None:
    """Max-depth deny remains kernel-authoritative with existing message wording."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    parent = await _create_parent_agent(pool, preset="trusted")
    parent_permissions = parent.services.get("permissions")
    assert parent_permissions is not None
    parent_permissions.depth = MAX_AGENT_DEPTH

    with pytest.raises(PermissionError, match="max nesting depth"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-max-depth-deny",
                preset="sandboxed",
                parent_agent_id="parent-agent",
            )
        )


@pytest.mark.asyncio
async def test_create_authoritative_base_ceiling_denial_preserves_wording(
    tmp_path: Path,
) -> None:
    """Base-ceiling deny remains kernel-authoritative with existing message wording."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    await _create_parent_agent(pool, preset="sandboxed")

    with pytest.raises(PermissionError, match="exceeds parent ceiling"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-base-ceiling-deny",
                preset="yolo",
                parent_agent_id="parent-agent",
            )
        )


@pytest.mark.asyncio
async def test_create_authoritative_delta_ceiling_denial_preserves_wording(
    tmp_path: Path,
) -> None:
    """Delta-ceiling deny remains kernel-authoritative with existing message wording."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    parent = await _create_parent_agent(pool, preset="trusted")
    parent_permissions = parent.services.get("permissions")
    assert parent_permissions is not None
    parent_permissions.depth = 0
    parent_permissions.tool_permissions["exec"] = ToolPermission(enabled=False)

    with pytest.raises(PermissionError, match="Permission delta would exceed parent ceiling"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-delta-ceiling-deny",
                preset="sandboxed",
                delta=PermissionDelta(enable_tools=["exec"]),
                parent_agent_id="parent-agent",
            )
        )


@pytest.mark.asyncio
async def test_create_authoritative_fail_closed_on_kernel_deny(
    tmp_path: Path,
) -> None:
    """Kernel deny is authoritative even when legacy base ceiling would allow."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)
    pool._create_authorization_kernel = _DenyCreateStageKernel("base_ceiling")

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = 0

    with pytest.raises(PermissionError, match="exceeds parent ceiling"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-base-ceiling-forced-deny",
                preset="sandboxed",
                parent_permissions=parent_permissions,
            )
        )

    assert "child-base-ceiling-forced-deny" not in pool


@pytest.mark.asyncio
async def test_create_authoritative_lifecycle_entry_forced_deny(
    tmp_path: Path,
) -> None:
    """Lifecycle-entry deny is authoritative with stable create deny wording."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)
    pool._create_authorization_kernel = _DenyCreateStageKernel("lifecycle_entry")

    with pytest.raises(
        PermissionError,
        match="requester is not authorized to create this agent",
    ):
        await pool.create(
            config=AgentConfig(
                agent_id="root-lifecycle-entry-forced-deny",
                preset="sandboxed",
            )
        )

    assert "root-lifecycle-entry-forced-deny" not in pool


@pytest.mark.asyncio
async def test_create_authoritative_requester_parent_binding_match_allows(
    tmp_path: Path,
) -> None:
    """Requester/parent binding allows create when requester matches parent."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    await _create_parent_agent(pool, preset="trusted")

    with patch("nexus3.skill.builtin.register_builtin_skills"):
        agent = await pool.create(
            config=AgentConfig(
                agent_id="child-requester-binding-match",
                preset="sandboxed",
                parent_agent_id="parent-agent",
            ),
            requester_id="parent-agent",
        )

    assert agent.agent_id == "child-requester-binding-match"
    assert "child-requester-binding-match" in pool


@pytest.mark.asyncio
async def test_create_authoritative_requester_parent_binding_mismatch_denied(
    tmp_path: Path,
) -> None:
    """Requester/parent binding mismatch is denied authoritatively."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    await _create_parent_agent(pool, preset="trusted")

    with pytest.raises(
        PermissionError,
        match="requester does not match the parent agent",
    ):
        await pool.create(
            config=AgentConfig(
                agent_id="child-requester-binding-mismatch",
                preset="sandboxed",
                parent_agent_id="parent-agent",
            ),
            requester_id="requester-agent",
        )

    assert "child-requester-binding-mismatch" not in pool


@pytest.mark.asyncio
async def test_parented_create_enforces_live_parent_permissions_over_forged_config(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Create uses live parent permissions when config passes a forged object."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    await _create_parent_agent(pool, preset="sandboxed")
    forged_parent_permissions = resolve_preset("trusted")

    with caplog.at_level("WARNING"):
        with pytest.raises(PermissionError, match="exceeds parent ceiling"):
            await pool.create(
                config=AgentConfig(
                    agent_id="child-forged-parent-perms",
                    preset="trusted",
                    parent_permissions=forged_parent_permissions,
                    parent_agent_id="parent-agent",
                )
            )

    assert "child-forged-parent-perms" not in pool
    assert "Parent permissions mismatch for create(child-forged-parent-perms)" in caplog.text


@pytest.mark.asyncio
async def test_parented_create_uses_live_parent_ceiling_when_parent_permissions_omitted(
    tmp_path: Path,
) -> None:
    """Create enforces live parent ceiling even if parent_permissions is omitted."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    await _create_parent_agent(pool, preset="sandboxed")

    with pytest.raises(PermissionError, match="exceeds parent ceiling"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-omitted-parent-perms",
                preset="trusted",
                parent_agent_id="parent-agent",
            )
        )

    assert "child-omitted-parent-perms" not in pool


@pytest.mark.asyncio
async def test_parented_create_fails_closed_when_parent_agent_missing(
    tmp_path: Path,
) -> None:
    """Create fails closed when parent_agent_id does not resolve to a live parent."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    with pytest.raises(PermissionError, match="parent agent not found"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-missing-parent",
                preset="sandboxed",
                parent_agent_id="missing-parent",
            )
        )

    assert "child-missing-parent" not in pool
