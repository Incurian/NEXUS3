"""Tests for create authorization kernel shadow parity in AgentPool."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus3.core.authorization_kernel import AuthorizationDecision
from nexus3.core.permissions import resolve_preset
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
    config.resolve_model.return_value = MagicMock()

    provider_registry = MagicMock()

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


class _ForceAllowCreateKernel:
    def authorize(self, request: Any) -> AuthorizationDecision:
        return AuthorizationDecision.allow(request, reason="forced_allow")


@pytest.mark.asyncio
async def test_create_shadow_parity_max_depth_denial_no_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Default adapter parity emits no mismatch warning for max-depth deny."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = MAX_AGENT_DEPTH

    with caplog.at_level(logging.WARNING, logger="nexus3.rpc.pool"):
        with pytest.raises(PermissionError, match="max nesting depth"):
            await pool.create(
                config=AgentConfig(
                    agent_id="child-max-depth-parity",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                    parent_agent_id="parent-agent",
                )
            )

    mismatch_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "create_auth_shadow_mismatch"
    ]
    assert mismatch_records == []


@pytest.mark.asyncio
async def test_create_shadow_mismatch_max_depth_warns_but_legacy_deny_remains(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kernel mismatch at max-depth emits warning while legacy deny remains authoritative."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)
    pool._create_authorization_kernel = _ForceAllowCreateKernel()

    parent_permissions = resolve_preset("trusted")
    parent_permissions.depth = MAX_AGENT_DEPTH

    with caplog.at_level(logging.WARNING, logger="nexus3.rpc.pool"):
        with pytest.raises(PermissionError, match="max nesting depth"):
            await pool.create(
                config=AgentConfig(
                    agent_id="child-max-depth-mismatch",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                    parent_agent_id="parent-agent",
                )
            )

    mismatch_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "create_auth_shadow_mismatch"
    ]
    assert len(mismatch_records) == 1
    mismatch = mismatch_records[0]
    assert mismatch.target_agent_id == "child-max-depth-mismatch"
    assert mismatch.requester_id == "parent-agent"
    assert mismatch.check_stage == "max_depth"
    assert mismatch.legacy_allowed is False
    assert mismatch.kernel_allowed is True


@pytest.mark.asyncio
async def test_create_shadow_mismatch_base_ceiling_warns_but_legacy_deny_remains(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kernel mismatch at base can_grant emits warning while legacy deny remains authoritative."""
    shared = _create_mock_shared_components(tmp_path)
    pool = AgentPool(shared)
    pool._create_authorization_kernel = _ForceAllowCreateKernel()

    parent_permissions = resolve_preset("sandboxed")
    parent_permissions.depth = 0

    with caplog.at_level(logging.WARNING, logger="nexus3.rpc.pool"):
        with pytest.raises(PermissionError, match="exceeds parent ceiling"):
            await pool.create(
                config=AgentConfig(
                    agent_id="child-base-ceiling-mismatch",
                    preset="yolo",
                    parent_permissions=parent_permissions,
                    parent_agent_id="parent-agent",
                )
            )

    mismatch_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "create_auth_shadow_mismatch"
    ]
    assert len(mismatch_records) == 1
    mismatch = mismatch_records[0]
    assert mismatch.target_agent_id == "child-base-ceiling-mismatch"
    assert mismatch.requester_id == "parent-agent"
    assert mismatch.check_stage == "base_ceiling"
    assert mismatch.legacy_allowed is False
    assert mismatch.kernel_allowed is True
