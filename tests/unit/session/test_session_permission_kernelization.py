"""Focused tests for session-side authorization kernel gates."""

from pathlib import Path

import pytest

from nexus3.core.authorization_kernel import AuthorizationDecision
from nexus3.core.permissions import ConfirmationResult, resolve_preset
from nexus3.core.types import ToolCall
from nexus3.session.permission_runtime import (
    handle_gitlab_permissions as handle_gitlab_permissions_runtime,
)
from nexus3.session.permission_runtime import (
    handle_mcp_permissions as handle_mcp_permissions_runtime,
)
from nexus3.session.session import Session
from nexus3.skill.services import ServiceContainer
from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance


class DummyProvider:
    """Provider stub for Session construction in unit tests."""


def _make_gitlab_config() -> GitLabConfig:
    return GitLabConfig(
        instances={
            "default": GitLabInstance(url="http://localhost", token="test-token"),
        },
        default_instance="default",
    )


class TestSessionIntegrationLevelKernelization:
    """Tests for MCP/GitLab level gates routed through authorization kernels."""

    @pytest.mark.asyncio
    async def test_mcp_kernel_deny_preserves_legacy_wording(self) -> None:
        session = Session(provider=DummyProvider())
        permissions = resolve_preset("trusted")
        tool_call = ToolCall(id="tc-1", name="mcp_demo_list", arguments={})

        def deny_request(request):
            return AuthorizationDecision.deny(request, reason="forced_deny")

        session._mcp_authorization_kernel.authorize = deny_request  # type: ignore[method-assign]

        result = await handle_mcp_permissions_runtime(
            tool_call=tool_call,
            skill=object(),
            server_name="demo",
            permissions=permissions,
            authorization_kernel=session._mcp_authorization_kernel,
            confirmation=session._confirmation,
            services=session._services,
            on_confirm=session.on_confirm,
        )

        assert result is not None
        assert result.error == "MCP tools require TRUSTED or YOLO permission level"

    @pytest.mark.asyncio
    async def test_gitlab_kernel_deny_preserves_legacy_wording(self) -> None:
        services = ServiceContainer()
        services.register("gitlab_config", _make_gitlab_config())
        session = Session(provider=DummyProvider(), services=services)
        permissions = resolve_preset("trusted")
        tool_call = ToolCall(
            id="tc-1",
            name="gitlab_issue",
            arguments={"action": "create", "instance": "default"},
        )

        def deny_request(request):
            return AuthorizationDecision.deny(request, reason="forced_deny")

        session._gitlab_authorization_kernel.authorize = deny_request  # type: ignore[method-assign]

        result = await handle_gitlab_permissions_runtime(
            tool_call=tool_call,
            skill=object(),
            permissions=permissions,
            authorization_kernel=session._gitlab_authorization_kernel,
            confirmation=session._confirmation,
            services=session._services,
            on_confirm=session.on_confirm,
        )

        assert result is not None
        assert result.error == "GitLab tools require TRUSTED or YOLO permission level"

    @pytest.mark.asyncio
    async def test_mcp_confirmation_behavior_preserved_when_level_allows(self) -> None:
        services = ServiceContainer()
        services.register("cwd", Path("/tmp"))
        confirmations: list[tuple[ToolCall, Path | None, Path]] = []

        async def on_confirm(
            tool_call: ToolCall,
            target_path: Path | None,
            agent_cwd: Path,
        ) -> ConfirmationResult:
            confirmations.append((tool_call, target_path, agent_cwd))
            return ConfirmationResult.ALLOW_ONCE

        session = Session(provider=DummyProvider(), services=services, on_confirm=on_confirm)
        permissions = resolve_preset("trusted")
        tool_call = ToolCall(id="tc-1", name="mcp_demo_list", arguments={})

        result = await handle_mcp_permissions_runtime(
            tool_call=tool_call,
            skill=object(),
            server_name="demo",
            permissions=permissions,
            authorization_kernel=session._mcp_authorization_kernel,
            confirmation=session._confirmation,
            services=session._services,
            on_confirm=session.on_confirm,
        )

        assert result is None
        assert len(confirmations) == 1
        assert confirmations[0][0] == tool_call
        assert confirmations[0][1] is None
        assert confirmations[0][2] == Path("/tmp")

    @pytest.mark.asyncio
    async def test_gitlab_confirmation_behavior_preserved_when_level_allows(self) -> None:
        services = ServiceContainer()
        services.register("cwd", Path("/tmp"))
        services.register("gitlab_config", _make_gitlab_config())
        confirmations: list[tuple[ToolCall, Path | None, Path]] = []

        async def on_confirm(
            tool_call: ToolCall,
            target_path: Path | None,
            agent_cwd: Path,
        ) -> ConfirmationResult:
            confirmations.append((tool_call, target_path, agent_cwd))
            return ConfirmationResult.ALLOW_ONCE

        session = Session(provider=DummyProvider(), services=services, on_confirm=on_confirm)
        permissions = resolve_preset("trusted")
        tool_call = ToolCall(
            id="tc-1",
            name="gitlab_issue",
            arguments={"action": "create", "instance": "default"},
        )

        result = await handle_gitlab_permissions_runtime(
            tool_call=tool_call,
            skill=object(),
            permissions=permissions,
            authorization_kernel=session._gitlab_authorization_kernel,
            confirmation=session._confirmation,
            services=session._services,
            on_confirm=session.on_confirm,
        )

        assert result is None
        assert len(confirmations) == 1
        assert confirmations[0][0] == tool_call
        assert confirmations[0][1] is None
        assert confirmations[0][2] == Path("/tmp")
