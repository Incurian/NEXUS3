"""Unit tests for multi-agent pool management components.

Tests for:
- SharedComponents: Dataclass for shared resources
- AgentConfig: Per-agent configuration
- AgentPool: Agent lifecycle management
- GlobalDispatcher: Agent management RPC methods
- HTTP path routing: _extract_agent_id helper
"""

from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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
        """SharedComponents has config, provider, prompt_loader, base_log_dir, log_streams fields."""
        field_names = {f.name for f in fields(SharedComponents)}
        expected = {"config", "provider", "prompt_loader", "base_log_dir", "log_streams"}
        assert field_names == expected

    def test_shared_components_is_frozen(self):
        """SharedComponents is immutable (frozen=True)."""
        # Create with mocks
        mock_config = MagicMock()
        mock_provider = MagicMock()
        mock_prompt_loader = MagicMock()

        shared = SharedComponents(
            config=mock_config,
            provider=mock_provider,
            prompt_loader=mock_prompt_loader,
            base_log_dir=Path("/tmp/logs"),
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            shared.config = MagicMock()

    def test_shared_components_stores_values(self):
        """SharedComponents correctly stores provided values."""
        mock_config = MagicMock()
        mock_provider = MagicMock()
        mock_prompt_loader = MagicMock()
        log_dir = Path("/tmp/test_logs")

        shared = SharedComponents(
            config=mock_config,
            provider=mock_provider,
            prompt_loader=mock_prompt_loader,
            base_log_dir=log_dir,
        )

        assert shared.config is mock_config
        assert shared.provider is mock_provider
        assert shared.prompt_loader is mock_prompt_loader
        assert shared.base_log_dir == log_dir


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
    mock_provider = MagicMock()

    # Mock prompt_loader.load() to return a LoadedPrompt-like object
    mock_prompt_loader = MagicMock()
    mock_loaded_prompt = MagicMock()
    mock_loaded_prompt.content = "You are a test assistant."
    mock_prompt_loader.load.return_value = mock_loaded_prompt

    return SharedComponents(
        config=mock_config,
        provider=mock_provider,
        prompt_loader=mock_prompt_loader,
        base_log_dir=tmp_path / "logs",
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

    async def destroy(self, agent_id: str) -> bool:
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

    def test_extract_agent_id_with_subpath(self):
        """Extracts agent_id including subpaths after the ID."""
        # The function returns everything after /agent/
        # This includes any subpath as part of the "agent_id"
        result = _extract_agent_id("/agent/foo/bar")
        assert result == "foo/bar"

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
