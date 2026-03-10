"""Focused tests for nexus_* skill behaviors outside nexus_create."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nexus3.skill.builtin.nexus_cancel import NexusCancelSkill
from nexus3.skill.builtin.nexus_send import NexusSendSkill
from nexus3.skill.services import ServiceContainer


@pytest.mark.asyncio
async def test_nexus_cancel_accepts_integer_request_id() -> None:
    cancel = AsyncMock(return_value={"cancelled": True, "request_id": 7})

    services = ServiceContainer()
    services.register(
        "agent_api",
        SimpleNamespace(for_agent=lambda agent_id: SimpleNamespace(cancel=cancel)),
    )
    services.set_cwd("/workspace")
    skill = NexusCancelSkill(services)

    result = await skill.execute(agent_id="worker-1", request_id=7)

    assert result.error == ""
    cancel.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_nexus_send_rejects_whitespace_only_content() -> None:
    send = AsyncMock(return_value={"content": "ok"})

    services = ServiceContainer()
    services.register("agent_api", SimpleNamespace(send=send))
    services.set_cwd("/workspace")
    skill = NexusSendSkill(services)

    result = await skill.execute(agent_id="worker-1", content="   ")

    assert not result.success
    assert result.error == "No content provided"
    send.assert_not_called()
