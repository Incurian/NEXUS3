"""Focused tests for the nexus_create skill."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nexus3.client import ClientError
from nexus3.core.permissions import resolve_preset
from nexus3.skill.builtin.nexus_create import NexusCreateSkill
from nexus3.skill.services import ServiceContainer


def _build_skill(*, create_agent: AsyncMock) -> NexusCreateSkill:
    services = ServiceContainer()
    services.register("agent_api", SimpleNamespace(create_agent=create_agent))
    services.register("agent_id", "parent-agent")
    services.register("cwd", Path("/workspace/parent"))
    services.register(
        "permissions",
        resolve_preset("sandboxed", cwd=Path("/workspace/parent")),
    )
    return NexusCreateSkill(services)


@pytest.mark.asyncio
async def test_execute_defers_parent_ceiling_decision_to_rpc_create() -> None:
    parent_permissions = resolve_preset("sandboxed", cwd=Path("/workspace/parent"))
    requested_permissions = resolve_preset("trusted", cwd=Path("/workspace/parent"))
    assert parent_permissions.can_grant(requested_permissions) is False

    create_agent = AsyncMock(
        return_value={"agent_id": "child-agent", "url": "/agent/child-agent"}
    )
    skill = _build_skill(create_agent=create_agent)

    result = await skill.execute(agent_id="child-agent", preset="trusted")

    assert result.error == ""
    assert json.loads(result.output) == {
        "agent_id": "child-agent",
        "url": "/agent/child-agent",
    }
    create_agent.assert_awaited_once_with(
        agent_id="child-agent",
        preset="trusted",
        disable_tools=None,
        parent_agent_id="parent-agent",
        cwd=None,
        allowed_write_paths=None,
        model=None,
        initial_message=None,
        wait_for_initial_response=False,
    )


@pytest.mark.asyncio
async def test_execute_preserves_downstream_create_error_text() -> None:
    create_agent = AsyncMock(
        side_effect=ClientError(
            "RPC error -32000: Requested preset 'trusted' exceeds parent ceiling"
        )
    )
    skill = _build_skill(create_agent=create_agent)

    result = await skill.execute(agent_id="child-agent", preset="trusted")

    assert (
        result.error
        == "RPC error -32000: Requested preset 'trusted' exceeds parent ceiling"
    )
    create_agent.assert_awaited_once_with(
        agent_id="child-agent",
        preset="trusted",
        disable_tools=None,
        parent_agent_id="parent-agent",
        cwd=None,
        allowed_write_paths=None,
        model=None,
        initial_message=None,
        wait_for_initial_response=False,
    )
