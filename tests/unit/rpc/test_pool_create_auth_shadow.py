"""Tests for authoritative create authorization in AgentPool."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.authorization_kernel import AuthorizationDecision
from nexus3.core.permissions import PermissionDelta, ToolPermission, resolve_preset
from nexus3.rpc.pool import (
    MAX_AGENT_DEPTH,
    AgentConfig,
    AgentPool,
    SharedComponents,
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


class _DenyCreateStageKernel:
    def __init__(self, check_stage: str) -> None:
        self._check_stage = check_stage

    def authorize(self, request: Any) -> AuthorizationDecision:
        if request.context.get("check_stage") == self._check_stage:
            return AuthorizationDecision.deny(request, reason="forced_deny_for_test")
        return AuthorizationDecision.allow(request, reason="forced_allow_for_test")


@pytest.mark.asyncio
async def test_create_authoritative_max_depth_denial_preserves_wording(
    tmp_path: Path,
) -> None:
    """Max-depth deny remains kernel-authoritative with existing message wording."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = MAX_AGENT_DEPTH

    with pytest.raises(PermissionError, match="max nesting depth"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-max-depth-deny",
                preset="sandboxed",
                parent_permissions=parent_permissions,
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

    parent_permissions = resolve_preset("sandboxed")
    parent_permissions.depth = 0

    with pytest.raises(PermissionError, match="exceeds parent ceiling"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-base-ceiling-deny",
                preset="yolo",
                parent_permissions=parent_permissions,
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

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = 0
    parent_permissions.tool_permissions["bash_safe"] = ToolPermission(enabled=False)

    with pytest.raises(PermissionError, match="Permission delta would exceed parent ceiling"):
        await pool.create(
            config=AgentConfig(
                agent_id="child-delta-ceiling-deny",
                preset="sandboxed",
                delta=PermissionDelta(enable_tools=["bash_safe"]),
                parent_permissions=parent_permissions,
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
async def test_create_authoritative_requester_parent_binding_match_allows(
    tmp_path: Path,
) -> None:
    """Requester/parent binding allows create when requester matches parent."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = 0

    with patch("nexus3.skill.builtin.register_builtin_skills"):
        agent = await pool.create(
            config=AgentConfig(
                agent_id="child-requester-binding-match",
                preset="sandboxed",
                parent_permissions=parent_permissions,
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

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = 0

    with pytest.raises(
        PermissionError,
        match="requester does not match the parent agent",
    ):
        await pool.create(
            config=AgentConfig(
                agent_id="child-requester-binding-mismatch",
                preset="sandboxed",
                parent_permissions=parent_permissions,
                parent_agent_id="parent-agent",
            ),
            requester_id="requester-agent",
        )

    assert "child-requester-binding-mismatch" not in pool
