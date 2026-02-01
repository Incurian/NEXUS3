"""Integration tests for sandboxed agent parent-only send capability.

Tests that sandboxed agents can send messages to their parent agent but not
to siblings or arbitrary agents. This validates the allowed_targets="parent"
restriction on the sandboxed preset's nexus_send tool.

Test Coverage:
- P4.1: Sandboxed child can send to parent (should succeed)
- P4.2: Sandboxed child cannot send to sibling (should fail)
- P4.3: Root sandboxed agent cannot send to anyone (should fail)
- P4.4: Trusted parent creates sandboxed child, child reports back

These tests verify the integration between:
- AgentPool.create() with parent_agent_id
- PermissionEnforcer._check_target_allowed()
- ToolPermission.allowed_targets
- Sandboxed preset configuration
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionLevel,
    ToolPermission,
    resolve_preset,
)
from nexus3.core.types import ToolCall, ToolResult
from nexus3.rpc.pool import AgentConfig, AgentPool, SharedComponents
from nexus3.session.enforcer import PermissionEnforcer
from nexus3.skill.services import ServiceContainer


def create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create SharedComponents with mocks for testing."""
    mock_config = MagicMock()
    mock_config.skill_timeout = 30.0
    mock_config.max_concurrent_tools = 10
    mock_config.permissions = MagicMock()
    mock_config.permissions.default_preset = "trusted"
    mock_config.default_provider = None  # Use "default" provider

    # Mock provider registry
    mock_provider_registry = MagicMock()
    mock_provider = MagicMock()
    mock_provider_registry.get.return_value = mock_provider

    # Mock base_context with system_prompt
    mock_base_context = MagicMock()
    mock_base_context.system_prompt = "You are a test assistant."
    mock_base_context.sources.prompt_sources = []

    # Mock context_loader for compaction
    mock_context_loader = MagicMock()
    mock_loaded_context = MagicMock()
    mock_loaded_context.system_prompt = "You are a test assistant."
    mock_context_loader.load.return_value = mock_loaded_context

    return SharedComponents(
        config=mock_config,
        provider_registry=mock_provider_registry,
        base_log_dir=tmp_path / "logs",
        base_context=mock_base_context,
        context_loader=mock_context_loader,
    )


class TestSandboxedChildCanSendToParent:
    """P4.1: Sandboxed child agent can send message to parent."""

    @pytest.mark.asyncio
    async def test_sandboxed_child_send_to_parent_allowed_by_enforcer(self) -> None:
        """PermissionEnforcer allows nexus_send targeting parent agent."""
        # Create sandboxed permissions with parent_agent_id set
        permissions = resolve_preset("sandboxed")
        permissions.parent_agent_id = "parent-agent"

        # Create a tool call for nexus_send targeting parent
        tool_call = ToolCall(
            id="call_1",
            name="nexus_send",
            arguments={"agent_id": "parent-agent", "content": "Hello from child"},
        )

        # Check with enforcer
        enforcer = PermissionEnforcer()
        result = enforcer.check_all(tool_call, permissions)

        # Should pass (no error returned)
        assert result is None

    @pytest.mark.asyncio
    async def test_sandboxed_child_can_send_to_parent_in_pool(
        self, tmp_path: Path
    ) -> None:
        """Sandboxed child agent in pool can dispatch nexus_send to parent."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent (trusted)
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create sandboxed child with parent_agent_id
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                    parent_agent_id="parent",
                )
            )

            # Verify child has correct parent_agent_id
            child_permissions = child.services.get("permissions")
            assert child_permissions.parent_agent_id == "parent"

            # Verify nexus_send is enabled with parent restriction
            nexus_send_perm = child_permissions.tool_permissions.get("nexus_send")
            assert nexus_send_perm is not None
            assert nexus_send_perm.enabled is True
            assert nexus_send_perm.allowed_targets == "parent"

            # Create tool call targeting parent
            tool_call = ToolCall(
                id="call_1",
                name="nexus_send",
                arguments={"agent_id": "parent", "content": "Test message"},
            )

            # Create enforcer with child's services
            enforcer = PermissionEnforcer(services=child.services)

            # Check should pass
            result = enforcer.check_all(tool_call, child_permissions)
            assert result is None


class TestSandboxedChildCannotSendToSibling:
    """P4.2: Sandboxed child agent cannot send to sibling agent."""

    @pytest.mark.asyncio
    async def test_sandboxed_child_send_to_sibling_blocked_by_enforcer(self) -> None:
        """PermissionEnforcer blocks nexus_send targeting sibling agent."""
        # Create sandboxed permissions with parent_agent_id set
        permissions = resolve_preset("sandboxed")
        permissions.parent_agent_id = "parent-agent"

        # Create a tool call for nexus_send targeting sibling (not parent)
        tool_call = ToolCall(
            id="call_1",
            name="nexus_send",
            arguments={"agent_id": "sibling-agent", "content": "Hello sibling"},
        )

        # Check with enforcer
        enforcer = PermissionEnforcer()
        result = enforcer.check_all(tool_call, permissions)

        # Should fail with error
        assert result is not None
        assert result.error is not None
        assert "can only target parent agent" in result.error
        assert "parent-agent" in result.error

    @pytest.mark.asyncio
    async def test_sandboxed_child_cannot_send_to_sibling_in_pool(
        self, tmp_path: Path
    ) -> None:
        """Two sandboxed siblings in pool cannot send to each other."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent (trusted)
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create two sandboxed children
            child1 = await pool.create(
                config=AgentConfig(
                    agent_id="child1",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                    parent_agent_id="parent",
                )
            )

            child2 = await pool.create(
                config=AgentConfig(
                    agent_id="child2",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                    parent_agent_id="parent",
                )
            )

            # Child1 tries to send to Child2
            tool_call = ToolCall(
                id="call_1",
                name="nexus_send",
                arguments={"agent_id": "child2", "content": "Hello sibling"},
            )

            child1_permissions = child1.services.get("permissions")
            enforcer = PermissionEnforcer(services=child1.services)

            # Check should fail
            result = enforcer.check_all(tool_call, child1_permissions)
            assert result is not None
            assert "can only target parent agent" in result.error


class TestRootSandboxedCannotSend:
    """P4.3: Root sandboxed agent (no parent) cannot send to anyone."""

    @pytest.mark.asyncio
    async def test_root_sandboxed_send_blocked_by_enforcer(self) -> None:
        """PermissionEnforcer blocks nexus_send from root sandboxed agent."""
        # Create sandboxed permissions with no parent
        permissions = resolve_preset("sandboxed")
        # parent_agent_id defaults to None for root agents

        # Create a tool call for nexus_send to any agent
        tool_call = ToolCall(
            id="call_1",
            name="nexus_send",
            arguments={"agent_id": "some-agent", "content": "Hello?"},
        )

        # Check with enforcer
        enforcer = PermissionEnforcer()
        result = enforcer.check_all(tool_call, permissions)

        # Should fail with error mentioning "none" as the parent
        assert result is not None
        assert result.error is not None
        assert "can only target parent agent" in result.error
        assert "'none'" in result.error

    @pytest.mark.asyncio
    async def test_root_sandboxed_cannot_send_in_pool(self, tmp_path: Path) -> None:
        """Root sandboxed agent in pool cannot send to any agent."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create sandboxed agent with no parent (root)
            lonely = await pool.create(
                config=AgentConfig(agent_id="lonely", preset="sandboxed")
            )

            # Verify no parent
            lonely_permissions = lonely.services.get("permissions")
            assert lonely_permissions.parent_agent_id is None

            # Try to send to any agent
            tool_call = ToolCall(
                id="call_1",
                name="nexus_send",
                arguments={"agent_id": "anyone", "content": "Hello?"},
            )

            enforcer = PermissionEnforcer(services=lonely.services)

            # Check should fail
            result = enforcer.check_all(tool_call, lonely_permissions)
            assert result is not None
            assert "can only target parent agent ('none')" in result.error


class TestTrustedCreatesChildReportsBack:
    """P4.4: Trusted parent creates sandboxed child, child can report back."""

    @pytest.mark.asyncio
    async def test_child_created_by_parent_can_report_back(
        self, tmp_path: Path
    ) -> None:
        """Child created via nexus_create inherits parent_agent_id and can send back."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create trusted parent
            parent = await pool.create(
                config=AgentConfig(agent_id="coordinator", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Simulate what nexus_create does: create child with parent info
            child = await pool.create(
                config=AgentConfig(
                    agent_id="worker",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                    parent_agent_id="coordinator",
                )
            )

            # Verify the child's setup
            child_permissions = child.services.get("permissions")
            assert child_permissions.parent_agent_id == "coordinator"
            assert child_permissions.base_preset == "sandboxed"

            # Child sends to parent (coordinator)
            tool_call = ToolCall(
                id="call_1",
                name="nexus_send",
                arguments={
                    "agent_id": "coordinator",
                    "content": "Task completed successfully",
                },
            )

            enforcer = PermissionEnforcer(services=child.services)

            # Check should pass
            result = enforcer.check_all(tool_call, child_permissions)
            assert result is None

    @pytest.mark.asyncio
    async def test_child_cannot_send_to_other_trusted_agent(
        self, tmp_path: Path
    ) -> None:
        """Child created by one trusted agent cannot send to another trusted agent."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create two trusted agents (potential coordinators)
            coordinator1 = await pool.create(
                config=AgentConfig(agent_id="coord1", preset="trusted")
            )
            coordinator1_permissions = coordinator1.services.get("permissions")

            await pool.create(
                config=AgentConfig(agent_id="coord2", preset="trusted")
            )

            # Create child under coordinator1
            child = await pool.create(
                config=AgentConfig(
                    agent_id="worker",
                    preset="sandboxed",
                    parent_permissions=coordinator1_permissions,
                    parent_agent_id="coord1",
                )
            )

            # Child tries to send to coord2 (not its parent)
            tool_call = ToolCall(
                id="call_1",
                name="nexus_send",
                arguments={"agent_id": "coord2", "content": "Sneaky message"},
            )

            child_permissions = child.services.get("permissions")
            enforcer = PermissionEnforcer(services=child.services)

            # Check should fail
            result = enforcer.check_all(tool_call, child_permissions)
            assert result is not None
            assert "can only target parent agent" in result.error
            assert "coord1" in result.error  # Shows correct parent


class TestOtherAgentTargetToolsBlocked:
    """Verify other agent-targeting tools are disabled for sandboxed agents."""

    @pytest.mark.asyncio
    async def test_nexus_status_disabled(self) -> None:
        """nexus_status is disabled for sandboxed agents."""
        permissions = resolve_preset("sandboxed")

        tool_call = ToolCall(
            id="call_1",
            name="nexus_status",
            arguments={"agent_id": "parent"},
        )

        enforcer = PermissionEnforcer()
        result = enforcer.check_all(tool_call, permissions)

        # Should fail because nexus_status is disabled (not because of target)
        assert result is not None
        assert "disabled by permission policy" in result.error

    @pytest.mark.asyncio
    async def test_nexus_destroy_disabled(self) -> None:
        """nexus_destroy is disabled for sandboxed agents."""
        permissions = resolve_preset("sandboxed")

        tool_call = ToolCall(
            id="call_1",
            name="nexus_destroy",
            arguments={"agent_id": "some-agent"},
        )

        enforcer = PermissionEnforcer()
        result = enforcer.check_all(tool_call, permissions)

        assert result is not None
        assert "disabled by permission policy" in result.error

    @pytest.mark.asyncio
    async def test_nexus_create_disabled(self) -> None:
        """nexus_create is disabled for sandboxed agents."""
        permissions = resolve_preset("sandboxed")

        tool_call = ToolCall(
            id="call_1",
            name="nexus_create",
            arguments={"agent_id": "new-agent"},
        )

        enforcer = PermissionEnforcer()
        result = enforcer.check_all(tool_call, permissions)

        assert result is not None
        assert "disabled by permission policy" in result.error


class TestTargetRestrictionSerialization:
    """Test that allowed_targets survives serialization for RPC transport."""

    def test_allowed_targets_serialization_roundtrip(self) -> None:
        """ToolPermission with allowed_targets survives to_dict/from_dict."""
        original = ToolPermission(enabled=True, allowed_targets="parent")

        # Serialize
        data = original.to_dict()
        assert "allowed_targets" in data
        assert data["allowed_targets"] == "parent"

        # Deserialize
        restored = ToolPermission.from_dict(data)
        assert restored.enabled is True
        assert restored.allowed_targets == "parent"

    def test_allowed_targets_list_serialization(self) -> None:
        """ToolPermission with explicit agent list survives serialization."""
        original = ToolPermission(enabled=True, allowed_targets=["agent1", "agent2"])

        data = original.to_dict()
        assert data["allowed_targets"] == ["agent1", "agent2"]

        restored = ToolPermission.from_dict(data)
        assert restored.allowed_targets == ["agent1", "agent2"]

    def test_no_allowed_targets_serialization(self) -> None:
        """ToolPermission without allowed_targets doesn't include it in dict."""
        original = ToolPermission(enabled=True)

        data = original.to_dict()
        # allowed_targets should not be in dict if None
        assert "allowed_targets" not in data

        restored = ToolPermission.from_dict(data)
        assert restored.allowed_targets is None


class TestSandboxedPresetConfiguration:
    """Verify the sandboxed preset is configured correctly for parent-send."""

    def test_sandboxed_preset_has_nexus_send_enabled(self) -> None:
        """Sandboxed preset has nexus_send enabled with parent-only target."""
        permissions = resolve_preset("sandboxed")

        nexus_send = permissions.tool_permissions.get("nexus_send")
        assert nexus_send is not None
        assert nexus_send.enabled is True
        assert nexus_send.allowed_targets == "parent"

    def test_sandboxed_preset_has_other_nexus_tools_disabled(self) -> None:
        """Sandboxed preset has other nexus_* tools disabled."""
        permissions = resolve_preset("sandboxed")

        for tool_name in ["nexus_create", "nexus_destroy", "nexus_shutdown", "nexus_cancel", "nexus_status"]:
            tool_perm = permissions.tool_permissions.get(tool_name)
            assert tool_perm is not None, f"{tool_name} should be in tool_permissions"
            assert tool_perm.enabled is False, f"{tool_name} should be disabled"

    def test_trusted_preset_has_unrestricted_nexus_send(self) -> None:
        """Trusted preset has nexus_send without target restrictions."""
        permissions = resolve_preset("trusted")

        # nexus_send not in tool_permissions means unrestricted
        nexus_send = permissions.tool_permissions.get("nexus_send")
        # Either not present (default enabled, no restrictions) or explicitly enabled without restrictions
        if nexus_send is not None:
            assert nexus_send.allowed_targets is None
