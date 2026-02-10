"""Tests for GitLab tools default-off and /gitlab on|off toggle.

Tests:
- GitLab tools disabled by default after agent creation
- /gitlab on enables all gitlab tools
- /gitlab off disables all gitlab tools
- Session restore preserves enabled state (tool_permissions guard)
- /gitlab status shows correct state
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus3.cli.repl_commands import cmd_gitlab
from nexus3.commands.protocol import CommandContext, CommandResult
from nexus3.core.permissions import (
    AgentPermissions,
    PermissionLevel,
    PermissionPolicy,
    ToolPermission,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockServices:
    """Minimal ServiceContainer mock."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        return self._services.get(name)

    def register(self, name: str, value: Any) -> None:
        self._services[name] = value


class MockSkillSpec:
    """Minimal SkillSpec stand-in (only name matters for _specs dict)."""
    pass


def _make_registry_with_gitlab() -> MagicMock:
    """Create a mock registry with gitlab_* entries in _specs."""
    registry = MagicMock()
    # Simulate 21 gitlab tools + some non-gitlab tools
    gitlab_names = [
        "gitlab_repo", "gitlab_issue", "gitlab_mr", "gitlab_label",
        "gitlab_branch", "gitlab_tag", "gitlab_epic", "gitlab_iteration",
        "gitlab_milestone", "gitlab_board", "gitlab_time", "gitlab_approval",
        "gitlab_draft", "gitlab_discussion", "gitlab_pipeline", "gitlab_job",
        "gitlab_artifact", "gitlab_variable", "gitlab_deploy_key",
        "gitlab_deploy_token", "gitlab_feature_flag",
    ]
    specs = {name: MockSkillSpec() for name in gitlab_names}
    specs["read_file"] = MockSkillSpec()
    specs["write_file"] = MockSkillSpec()
    specs["bash_safe"] = MockSkillSpec()
    registry._specs = specs
    registry.get_definitions_for_permissions.return_value = []
    return registry


def _make_agent(
    agent_id: str = "main",
    gitlab_enabled: bool = False,
) -> MagicMock:
    """Create a mock Agent with gitlab tools in registry."""
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.registry = _make_registry_with_gitlab()

    perms = AgentPermissions(
        base_preset="trusted",
        effective_policy=PermissionPolicy(level=PermissionLevel.TRUSTED),
    )
    # Set gitlab tools enabled/disabled
    for name in agent.registry._specs:
        if name.startswith("gitlab_"):
            perms.tool_permissions[name] = ToolPermission(enabled=gitlab_enabled)
    agent.services = MockServices()
    agent.services.register("permissions", perms)

    agent.context = MagicMock()
    return agent


def _make_pool(agent: MagicMock) -> MagicMock:
    """Create a mock pool with _shared and config."""
    pool = MagicMock()
    pool.get.return_value = agent

    # Mock shared config with gitlab instances
    shared = MagicMock()
    shared.config.gitlab.instances = {
        "default": MagicMock(
            url="https://gitlab.com",
            token="fake",
            token_env="GITLAB_TOKEN",
            username="testuser",
        ),
    }
    shared.config.gitlab.default_instance = "default"
    pool._shared = shared
    return pool


def _make_ctx(
    agent: MagicMock,
    pool: MagicMock | None = None,
) -> CommandContext:
    """Create a CommandContext."""
    if pool is None:
        pool = _make_pool(agent)
    return CommandContext(
        pool=pool,
        session_manager=MagicMock(),
        current_agent_id=agent.agent_id,
        is_repl=True,
    )


# ---------------------------------------------------------------------------
# Tests: Default Off (pool.py logic)
# ---------------------------------------------------------------------------


class TestGitlabDefaultOff:
    """Test that gitlab tools are disabled by default in pool.py."""

    def test_new_agent_gitlab_disabled(self) -> None:
        """Simulate pool.py default-disable logic: new agent, no tool_permissions."""
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(level=PermissionLevel.TRUSTED),
        )
        registry_specs = {
            "read_file": MockSkillSpec(),
            "gitlab_repo": MockSkillSpec(),
            "gitlab_issue": MockSkillSpec(),
            "gitlab_mr": MockSkillSpec(),
        }

        # This is the exact loop from pool.py
        for name in list(registry_specs):
            if name.startswith("gitlab_") and name not in perms.tool_permissions:
                perms.tool_permissions[name] = ToolPermission(enabled=False)

        # gitlab tools should be disabled
        assert not perms.tool_permissions["gitlab_repo"].enabled
        assert not perms.tool_permissions["gitlab_issue"].enabled
        assert not perms.tool_permissions["gitlab_mr"].enabled
        # non-gitlab tools should not be affected
        assert "read_file" not in perms.tool_permissions

    def test_restored_session_preserves_enabled(self) -> None:
        """Restored session with gitlab enabled should NOT be overwritten."""
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(level=PermissionLevel.TRUSTED),
        )
        # Simulate a restored session where user had /gitlab on
        perms.tool_permissions["gitlab_repo"] = ToolPermission(enabled=True)
        perms.tool_permissions["gitlab_issue"] = ToolPermission(enabled=True)
        # gitlab_mr not in tool_permissions (not explicitly set)

        registry_specs = {
            "gitlab_repo": MockSkillSpec(),
            "gitlab_issue": MockSkillSpec(),
            "gitlab_mr": MockSkillSpec(),
        }

        # Run the pool.py loop
        for name in list(registry_specs):
            if name.startswith("gitlab_") and name not in perms.tool_permissions:
                perms.tool_permissions[name] = ToolPermission(enabled=False)

        # Explicitly enabled tools should stay enabled
        assert perms.tool_permissions["gitlab_repo"].enabled
        assert perms.tool_permissions["gitlab_issue"].enabled
        # Tool not in tool_permissions gets disabled
        assert not perms.tool_permissions["gitlab_mr"].enabled


# ---------------------------------------------------------------------------
# Tests: /gitlab command
# ---------------------------------------------------------------------------


class TestGitlabStatus:
    """Test /gitlab (no args) status display."""

    @pytest.mark.asyncio
    async def test_status_when_off(self) -> None:
        agent = _make_agent(gitlab_enabled=False)
        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx)
        assert result.result == CommandResult.SUCCESS
        assert "OFF" in (result.message or "")
        assert result.data["enabled"] is False
        assert result.data["disabled_count"] == 21

    @pytest.mark.asyncio
    async def test_status_when_on(self) -> None:
        agent = _make_agent(gitlab_enabled=True)
        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx)
        assert result.result == CommandResult.SUCCESS
        assert "ON" in (result.message or "")
        assert result.data["enabled"] is True
        assert result.data["enabled_count"] == 21

    @pytest.mark.asyncio
    async def test_status_shows_instances(self) -> None:
        agent = _make_agent(gitlab_enabled=False)
        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx)
        assert "gitlab.com" in (result.message or "")
        assert "@testuser" in (result.message or "")


class TestGitlabToggle:
    """Test /gitlab on and /gitlab off."""

    @pytest.mark.asyncio
    async def test_toggle_on(self) -> None:
        agent = _make_agent(gitlab_enabled=False)
        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx, "on")
        assert result.result == CommandResult.SUCCESS
        assert "ON" in (result.message or "")
        assert result.data["enabled"] is True
        assert result.data["count"] == 21

        # Verify permissions were actually changed
        perms: AgentPermissions = agent.services.get("permissions")
        for name in agent.registry._specs:
            if name.startswith("gitlab_"):
                assert perms.tool_permissions[name].enabled is True

        # Verify resync was called
        agent.context.set_tool_definitions.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_off(self) -> None:
        agent = _make_agent(gitlab_enabled=True)
        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx, "off")
        assert result.result == CommandResult.SUCCESS
        assert "OFF" in (result.message or "")
        assert result.data["enabled"] is False

        # Verify permissions were actually changed
        perms: AgentPermissions = agent.services.get("permissions")
        for name in agent.registry._specs:
            if name.startswith("gitlab_"):
                assert perms.tool_permissions[name].enabled is False

    @pytest.mark.asyncio
    async def test_toggle_on_then_off(self) -> None:
        agent = _make_agent(gitlab_enabled=False)
        ctx = _make_ctx(agent)

        # Turn on
        result = await cmd_gitlab(ctx, "on")
        assert result.data["enabled"] is True

        # Turn off
        result = await cmd_gitlab(ctx, "off")
        assert result.data["enabled"] is False

        # Verify tools are disabled
        perms: AgentPermissions = agent.services.get("permissions")
        for name in agent.registry._specs:
            if name.startswith("gitlab_"):
                assert perms.tool_permissions[name].enabled is False

    @pytest.mark.asyncio
    async def test_toggle_no_agent(self) -> None:
        agent = _make_agent()
        pool = _make_pool(agent)
        ctx = CommandContext(
            pool=pool,
            session_manager=MagicMock(),
            current_agent_id=None,
            is_repl=True,
        )
        result = await cmd_gitlab(ctx, "on")
        assert result.result == CommandResult.ERROR

    @pytest.mark.asyncio
    async def test_toggle_no_gitlab_tools(self) -> None:
        """Toggle when no gitlab tools are registered."""
        agent = MagicMock()
        agent.agent_id = "main"
        registry = MagicMock()
        registry._specs = {"read_file": MockSkillSpec(), "bash_safe": MockSkillSpec()}
        agent.registry = registry
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(level=PermissionLevel.TRUSTED),
        )
        agent.services = MockServices()
        agent.services.register("permissions", perms)

        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx, "on")
        assert result.result == CommandResult.ERROR
        assert "No GitLab tools" in (result.message or "")

    @pytest.mark.asyncio
    async def test_unknown_subcommand(self) -> None:
        agent = _make_agent()
        ctx = _make_ctx(agent)
        result = await cmd_gitlab(ctx, "banana")
        assert result.result == CommandResult.ERROR
        assert "Unknown" in (result.message or "")
