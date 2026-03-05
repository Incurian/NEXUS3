"""Focused tests for requester propagation through NexusSkill HTTP fallback."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from nexus3.core.types import ToolResult
from nexus3.skill.base import NexusSkill
from nexus3.skill.services import ServiceContainer


class _ProbeNexusSkill(NexusSkill):
    @property
    def name(self) -> str:
        return "probe_nexus"

    @property
    def description(self) -> str:
        return "Probe Nexus client wiring."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        async def op(client: Any) -> dict[str, Any]:
            return await client.get_tokens()

        return await self._execute_with_client(
            port=None,
            operation=op,
            agent_id="worker-1",
        )


class _RecordingClient:
    instances: list[_RecordingClient] = []

    def __init__(
        self,
        url: str,
        timeout: float = 60.0,
        api_key: str | None = None,
        skip_url_validation: bool = False,
        requester_id: str | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.api_key = api_key
        self.skip_url_validation = skip_url_validation
        self.requester_id = requester_id
        self.__class__.instances.append(self)

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None

    async def get_tokens(self) -> dict[str, Any]:
        return {"ok": True}


@pytest.mark.asyncio
async def test_nexus_skill_http_fallback_forwards_requester_id() -> None:
    services = ServiceContainer()
    services.register("agent_id", "caller-agent")
    services.register("api_key", "test-token")

    skill = _ProbeNexusSkill(services)
    _RecordingClient.instances.clear()

    with patch("nexus3.client.NexusClient", _RecordingClient):
        result = await skill.execute()

    assert result.error == ""
    assert json.loads(result.output or "") == {"ok": True}
    assert _RecordingClient.instances[0].requester_id == "caller-agent"
    assert _RecordingClient.instances[0].url == "http://127.0.0.1:8765/agent/worker-1"
