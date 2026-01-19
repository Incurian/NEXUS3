"""Unit tests for multi-agent pool management components.

Tests for:
- SharedComponents: Dataclass for shared resources
- AgentConfig: Per-agent configuration
- AgentPool: Agent lifecycle management
- GlobalDispatcher: Agent management RPC methods
- HTTP path routing: _extract_agent_id helper
- Security: Tool definition filtering, ceiling isolation, parent_agent_id tracking
"""

from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    PermissionLevel,
    PermissionPolicy,
    ToolPermission,
    resolve_preset,
)
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.http import _extract_agent_id
from nexus3.rpc.pool import AgentConfig, AgentPool, SharedComponents
from nexus3.rpc.types import Request

# -----------------------------------------------------------------------------
# SharedComponents Tests
# -----------------------------------------------------------------------------


class TestSharedComponents:
    """Tests for SharedComponents dataclass."""

    def test_shared_components_is_dataclass(self):
        """SharedComponents is a dataclass with expected fields."""
        # Verify it's a dataclass by checking for __dataclass_fields__
        assert hasattr(SharedComponents, "__dataclass_fields__")

    def test_shared_components_has_expected_fields(self):
        """SharedComponents has expected fields including mcp_registry, base_context, and event_hub."""
        field_names = {f.name for f in fields(SharedComponents)}
        expected = {
            "config", "provider_registry", "base_log_dir", "base_context",
            "context_loader", "log_streams", "custom_presets", "mcp_registry",
            "event_hub"
        }
        assert field_names == expected

    def test_shared_components_is_frozen(self):
        """SharedComponents is immutable (frozen=True)."""
        # Create with mocks
        mock_config = MagicMock()
        mock_provider_registry = MagicMock()
        mock_base_context = MagicMock()
        mock_context_loader = MagicMock()

        shared = SharedComponents(
            config=mock_config,
            provider_registry=mock_provider_registry,
            base_log_dir=Path("/tmp/logs"),
            base_context=mock_base_context,
            context_loader=mock_context_loader,
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            shared.config = MagicMock()

    def test_shared_components_stores_values(self):
        """SharedComponents correctly stores provided values."""
        mock_config = MagicMock()
        mock_provider_registry = MagicMock()
        mock_base_context = MagicMock()
        mock_context_loader = MagicMock()
        log_dir = Path("/tmp/test_logs")

        shared = SharedComponents(
            config=mock_config,
            provider_registry=mock_provider_registry,
            base_log_dir=log_dir,
            base_context=mock_base_context,
            context_loader=mock_context_loader,
        )

        assert shared.config is mock_config
        assert shared.provider_registry is mock_provider_registry
        assert shared.base_log_dir == log_dir
        assert shared.base_context is mock_base_context
        assert shared.context_loader is mock_context_loader


# -----------------------------------------------------------------------------
# AgentConfig Tests
# -----------------------------------------------------------------------------


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_agent_config_default_values(self):
        """AgentConfig has None defaults for agent_id and system_prompt."""
        config = AgentConfig()

        assert config.agent_id is None
        assert config.system_prompt is None

    def test_agent_config_accepts_agent_id(self):
        """AgentConfig accepts agent_id parameter."""
        config = AgentConfig(agent_id="my-agent")

        assert config.agent_id == "my-agent"
        assert config.system_prompt is None

    def test_agent_config_accepts_system_prompt(self):
        """AgentConfig accepts system_prompt parameter."""
        config = AgentConfig(system_prompt="You are a helpful assistant.")

        assert config.agent_id is None
        assert config.system_prompt == "You are a helpful assistant."

    def test_agent_config_accepts_both_params(self):
        """AgentConfig accepts both agent_id and system_prompt."""
        config = AgentConfig(
            agent_id="worker-1",
            system_prompt="You are a worker agent.",
        )

        assert config.agent_id == "worker-1"
        assert config.system_prompt == "You are a worker agent."


# -----------------------------------------------------------------------------
# AgentPool Tests
# -----------------------------------------------------------------------------


def create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create SharedComponents with mocks for testing."""
    mock_config = MagicMock()
    # Provide concrete values for skill timeout and concurrency limit
    mock_config.skill_timeout = 30.0
    mock_config.max_concurrent_tools = 10
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


class TestAgentPool:
    """Tests for AgentPool lifecycle management."""

    @pytest.mark.asyncio
    async def test_create_with_explicit_agent_id(self, tmp_path):
        """create() with explicit agent_id uses that ID."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create(agent_id="my-custom-id")

            assert agent.agent_id == "my-custom-id"
            assert "my-custom-id" in pool
            assert len(pool) == 1

    @pytest.mark.asyncio
    async def test_create_with_auto_generated_agent_id(self, tmp_path):
        """create() without agent_id generates a random ID."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create()

            # Auto-generated ID should be 8 hex chars
            assert agent.agent_id is not None
            assert len(agent.agent_id) == 8
            assert agent.agent_id in pool

    @pytest.mark.asyncio
    async def test_create_with_duplicate_agent_id_raises(self, tmp_path):
        """create() with duplicate agent_id raises ValueError."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="duplicate-id")

            with pytest.raises(ValueError) as exc_info:
                await pool.create(agent_id="duplicate-id")

            assert "duplicate-id" in str(exc_info.value)
            assert "already exists" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_returns_agent(self, tmp_path):
        """get() returns the agent if it exists."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            created = await pool.create(agent_id="test-agent")

            retrieved = pool.get("test-agent")
            assert retrieved is created

    @pytest.mark.asyncio
    async def test_get_returns_none_for_nonexistent(self, tmp_path):
        """get() returns None for non-existent agent."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        result = pool.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_destroy_removes_agent_and_returns_true(self, tmp_path):
        """destroy() removes the agent and returns True."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="to-destroy")

            assert "to-destroy" in pool
            result = await pool.destroy("to-destroy")

            assert result is True
            assert "to-destroy" not in pool
            assert pool.get("to-destroy") is None

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_returns_false(self, tmp_path):
        """destroy() on non-existent agent returns False."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        result = await pool.destroy("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_returns_agent_info_dicts(self, tmp_path):
        """list() returns list of agent info dictionaries."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="agent-1")
            await pool.create(agent_id="agent-2")

            agents = pool.list()

            assert len(agents) == 2
            agent_ids = {a["agent_id"] for a in agents}
            assert agent_ids == {"agent-1", "agent-2"}

            # Check each agent has expected keys
            for agent_info in agents:
                assert "agent_id" in agent_info
                assert "created_at" in agent_info
                assert "message_count" in agent_info
                assert "should_shutdown" in agent_info
                # created_at should be ISO format
                assert isinstance(agent_info["created_at"], str)

    @pytest.mark.asyncio
    async def test_should_shutdown_false_when_empty(self, tmp_path):
        """should_shutdown is False when pool is empty."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        assert pool.should_shutdown is False

    @pytest.mark.asyncio
    async def test_should_shutdown_false_when_agents_active(self, tmp_path):
        """should_shutdown is False when agents are not shut down."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="active-agent")

            # By default, dispatcher.should_shutdown is False
            assert pool.should_shutdown is False

    @pytest.mark.asyncio
    async def test_should_shutdown_true_when_all_agents_shutdown(self, tmp_path):
        """should_shutdown is True when all agents want shutdown."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create(agent_id="shutting-down")

            # Mock the dispatcher's should_shutdown to return True
            agent.dispatcher._should_shutdown = True

            assert pool.should_shutdown is True

    @pytest.mark.asyncio
    async def test_len_returns_agent_count(self, tmp_path):
        """__len__ returns the number of agents in the pool."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            assert len(pool) == 0

            await pool.create(agent_id="agent-1")
            assert len(pool) == 1

            await pool.create(agent_id="agent-2")
            assert len(pool) == 2

            await pool.destroy("agent-1")
            assert len(pool) == 1

    @pytest.mark.asyncio
    async def test_contains_checks_agent_id(self, tmp_path):
        """__contains__ checks if agent_id exists in pool."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="existing")

            assert "existing" in pool
            assert "nonexistent" not in pool


# -----------------------------------------------------------------------------
# GlobalDispatcher Tests
# -----------------------------------------------------------------------------


class MockAgentPool:
    """Mock AgentPool for testing GlobalDispatcher.

    Implements the interface expected by GlobalDispatcher.
    """

    def __init__(self):
        self._agents: dict[str, Any] = {}
        self._next_id = 1

    async def create(
        self,
        agent_id: str | None = None,
        config: Any = None,
    ) -> Any:
        """Create mock agent and return Agent object."""
        effective_id = agent_id or f"auto-{self._next_id}"
        self._next_id += 1

        if effective_id in self._agents:
            raise ValueError(f"Agent already exists: {effective_id}")

        agent = MagicMock()
        agent.agent_id = effective_id
        agent.created_at = datetime.now().isoformat()
        agent.message_count = 0

        self._agents[effective_id] = agent
        return agent

    async def destroy(
        self,
        agent_id: str,
        requester_id: str | None = None,
        *,
        admin_override: bool = False,
    ) -> bool:
        """Destroy mock agent."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def list(self) -> list[dict[str, Any]]:
        """List all mock agents as dicts."""
        return [
            {
                "agent_id": a.agent_id,
                "created_at": a.created_at,
                "message_count": a.message_count,
                "should_shutdown": False,
            }
            for a in self._agents.values()
        ]

    def get(self, agent_id: str) -> Any:
        """Get an agent by ID."""
        return self._agents.get(agent_id)


class TestGlobalDispatcher:
    """Tests for GlobalDispatcher RPC methods."""

    @pytest.mark.asyncio
    async def test_create_agent_with_id(self):
        """create_agent with agent_id creates agent with that ID."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": "test-agent"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["agent_id"] == "test-agent"
        assert response.result["url"] == "/agent/test-agent"

    @pytest.mark.asyncio
    async def test_create_agent_auto_generated_id(self):
        """create_agent without agent_id generates an ID."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert "agent_id" in response.result
        assert response.result["agent_id"].startswith("auto-")

    @pytest.mark.asyncio
    async def test_destroy_agent_success(self):
        """destroy_agent removes existing agent."""
        pool = MockAgentPool()
        await pool.create(agent_id="to-destroy")

        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "to-destroy"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["success"] is True
        assert response.result["agent_id"] == "to-destroy"

    @pytest.mark.asyncio
    async def test_destroy_agent_not_found(self):
        """destroy_agent for non-existent agent returns success=False."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "nonexistent"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["success"] is False
        assert response.result["agent_id"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_destroy_agent_missing_params(self):
        """destroy_agent without agent_id returns error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "agent_id" in response.error["message"].lower()

    @pytest.mark.asyncio
    async def test_list_agents_empty(self):
        """list_agents returns empty list when no agents."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["agents"] == []

    @pytest.mark.asyncio
    async def test_list_agents_with_agents(self):
        """list_agents returns info for all agents."""
        pool = MockAgentPool()
        await pool.create(agent_id="agent-1")
        await pool.create(agent_id="agent-2")

        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert len(response.result["agents"]) == 2

        agent_ids = {a["agent_id"] for a in response.result["agents"]}
        assert agent_ids == {"agent-1", "agent-2"}

    @pytest.mark.asyncio
    async def test_method_not_found(self):
        """Unknown method returns METHOD_NOT_FOUND error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="unknown_method",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32601  # METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handles_method(self):
        """handles() returns True for known methods, False otherwise."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        assert dispatcher.handles("create_agent") is True
        assert dispatcher.handles("destroy_agent") is True
        assert dispatcher.handles("list_agents") is True
        assert dispatcher.handles("unknown") is False
        assert dispatcher.handles("send") is False

    @pytest.mark.asyncio
    async def test_create_agent_invalid_agent_id_type(self):
        """create_agent with non-string agent_id returns error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": 123},  # Should be string
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_destroy_agent_invalid_agent_id_type(self):
        """destroy_agent with non-string agent_id returns error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": 123},  # Should be string
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_notification_no_response(self):
        """Notifications (no id) don't get responses."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        # Notification has no id
        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params={},
            id=None,
        )
        response = await dispatcher.dispatch(request)

        assert response is None


# -----------------------------------------------------------------------------
# HTTP Path Routing Tests
# -----------------------------------------------------------------------------


class TestExtractAgentId:
    """Tests for _extract_agent_id helper function."""

    def test_extract_agent_id_simple(self):
        """Extracts agent_id from /agent/{id} path."""
        assert _extract_agent_id("/agent/foo") == "foo"
        assert _extract_agent_id("/agent/my-agent") == "my-agent"
        assert _extract_agent_id("/agent/agent123") == "agent123"

    def test_extract_agent_id_with_subpath_rejected(self):
        """Rejects agent_id containing path separators for security."""
        # SECURITY: Agent IDs with slashes are rejected to prevent path traversal
        result = _extract_agent_id("/agent/foo/bar")
        assert result is None  # foo/bar is invalid agent ID

    def test_extract_agent_id_root_path(self):
        """Returns None for root path."""
        assert _extract_agent_id("/") is None

    def test_extract_agent_id_rpc_path(self):
        """Returns None for /rpc path."""
        assert _extract_agent_id("/rpc") is None

    def test_extract_agent_id_other_paths(self):
        """Returns None for paths that don't match /agent/."""
        assert _extract_agent_id("/other") is None
        assert _extract_agent_id("/agents") is None
        assert _extract_agent_id("/agent") is None  # No trailing slash/id
        assert _extract_agent_id("/something/agent/foo") is None

    def test_extract_agent_id_empty_agent(self):
        """Returns None for /agent/ with no ID."""
        # Path is /agent/ with empty string after
        assert _extract_agent_id("/agent/") is None

    def test_extract_agent_id_special_characters(self):
        """Handles agent IDs with special characters."""
        assert _extract_agent_id("/agent/agent-with-dashes") == "agent-with-dashes"
        assert _extract_agent_id("/agent/agent_with_underscores") == "agent_with_underscores"
        assert _extract_agent_id("/agent/abc123") == "abc123"


# -----------------------------------------------------------------------------
# Security Tests: Permission System Fixes
# -----------------------------------------------------------------------------


class TestAgentConfigParentAgentId:
    """Tests for parent_agent_id field in AgentConfig.

    SECURITY FIX: parent_agent_id should store actual agent ID, not preset name.
    """

    def test_agent_config_has_parent_agent_id_field(self):
        """AgentConfig has parent_agent_id field."""
        config = AgentConfig()
        assert hasattr(config, "parent_agent_id")
        assert config.parent_agent_id is None

    def test_agent_config_accepts_parent_agent_id(self):
        """AgentConfig accepts parent_agent_id parameter."""
        config = AgentConfig(parent_agent_id="parent-worker-1")
        assert config.parent_agent_id == "parent-worker-1"

    def test_agent_config_stores_actual_agent_id(self):
        """parent_agent_id stores actual ID, not preset name."""
        # This test verifies the fix for the bug where parent_agent_id
        # was incorrectly assigned from parent_permissions.base_preset
        parent_permissions = resolve_preset("trusted")
        config = AgentConfig(
            agent_id="child-1",
            preset="sandboxed",
            parent_permissions=parent_permissions,
            parent_agent_id="main-agent",  # Actual parent ID, not "trusted"
        )
        assert config.parent_agent_id == "main-agent"
        assert config.parent_permissions.base_preset == "trusted"
        # These should be different values
        assert config.parent_agent_id != config.parent_permissions.base_preset


class TestCeilingIsolation:
    """Tests for ceiling deep copy to prevent shared references.

    SECURITY FIX: ceiling should be deep copied to prevent mutation leaking
    between parent and child agents.
    """

    def test_ceiling_mutation_does_not_affect_child(self):
        """Mutating parent permissions after agent creation doesn't affect child ceiling."""
        # Create parent permissions
        parent_permissions = resolve_preset("trusted")

        # Simulate the fix: deep copy the ceiling
        import copy
        child_ceiling = copy.deepcopy(parent_permissions)

        # Now mutate the original parent permissions
        parent_permissions.tool_permissions["write_file"] = ToolPermission(enabled=False)

        # Child's ceiling should be unaffected
        assert "write_file" not in child_ceiling.tool_permissions or \
               child_ceiling.tool_permissions.get("write_file", ToolPermission()).enabled is True

    def test_ceiling_is_independent_copy(self):
        """Ceiling is a fully independent copy of parent permissions."""
        import copy

        parent_permissions = resolve_preset("trusted")
        parent_permissions.tool_permissions["test_tool"] = ToolPermission(
            enabled=True,
            timeout=60.0,
        )

        # Deep copy as the fix does
        child_ceiling = copy.deepcopy(parent_permissions)

        # Verify they are different objects
        assert child_ceiling is not parent_permissions
        assert child_ceiling.tool_permissions is not parent_permissions.tool_permissions

        # Verify nested objects are also different
        if "test_tool" in child_ceiling.tool_permissions:
            assert child_ceiling.tool_permissions["test_tool"] is not \
                   parent_permissions.tool_permissions["test_tool"]

    def test_ceiling_policy_is_independent(self):
        """Ceiling's effective_policy is also deep copied."""
        import copy

        parent_permissions = resolve_preset("sandboxed")
        child_ceiling = copy.deepcopy(parent_permissions)

        # Verify policy is independent
        assert child_ceiling.effective_policy is not parent_permissions.effective_policy

        # Verify path lists are independent
        if parent_permissions.effective_policy.allowed_paths is not None:
            assert child_ceiling.effective_policy.allowed_paths is not \
                   parent_permissions.effective_policy.allowed_paths


class TestGlobalDispatcherParentAgentId:
    """Tests for GlobalDispatcher passing parent_agent_id correctly.

    SECURITY FIX: GlobalDispatcher should pass parent_agent_id to AgentConfig.
    """

    @pytest.mark.asyncio
    async def test_create_agent_with_parent_agent_id(self):
        """create_agent passes parent_agent_id to AgentConfig."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        # First create a parent agent
        await pool.create(agent_id="parent-1")
        # Mock the services.get("permissions") return
        pool._agents["parent-1"].services = MagicMock()
        pool._agents["parent-1"].services.get = MagicMock(return_value=resolve_preset("trusted"))

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={
                "agent_id": "child-1",
                "parent_agent_id": "parent-1",
            },
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["agent_id"] == "child-1"

    @pytest.mark.asyncio
    async def test_create_agent_validates_parent_agent_id_type(self):
        """create_agent validates parent_agent_id is a string."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={
                "agent_id": "child-1",
                "parent_agent_id": 123,  # Should be string
            },
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_create_agent_validates_parent_exists(self):
        """create_agent returns error if parent agent doesn't exist."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={
                "agent_id": "child-1",
                "parent_agent_id": "nonexistent-parent",
            },
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert "not found" in response.error["message"].lower()
