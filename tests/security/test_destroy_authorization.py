"""Security tests for destroy-agent authorization (H5 fix).

Tests that only authorized agents can destroy other agents:
- Self-destruction is allowed (agent destroys itself)
- Parent can destroy children
- Sibling destroying sibling is denied
- External clients (requester_id=None) are treated as admin
- admin_override=True bypasses all checks
"""

import pytest

from nexus3.core.permissions import AgentPermissions, PermissionLevel
from nexus3.core.policy import PermissionPolicy
from nexus3.rpc.pool import AgentPool, AuthorizationError


class MockLogger:
    """Minimal mock for SessionLogger."""

    def close(self) -> None:
        pass

    def get_raw_log_callback(self):
        return None


class MockDispatcher:
    """Minimal mock for Dispatcher."""

    def __init__(self):
        self.should_shutdown = False
        self._cancelled = False

    async def cancel_all_requests(self) -> None:
        self._cancelled = True


class MockServices:
    """Minimal mock for ServiceContainer."""

    def __init__(self, permissions: AgentPermissions | None = None, child_ids: set | None = None):
        self._data = {}
        if permissions:
            self._data["permissions"] = permissions
        if child_ids:
            self._data["child_agent_ids"] = child_ids

    def get(self, key: str):
        return self._data.get(key)

    def register(self, key: str, value):
        self._data[key] = value


class MockAgent:
    """Minimal mock for Agent."""

    def __init__(
        self,
        agent_id: str,
        parent_agent_id: str | None = None,
        child_ids: set | None = None,
    ):
        self.agent_id = agent_id
        self.logger = MockLogger()
        self.dispatcher = MockDispatcher()

        # Create permissions with parent_agent_id
        policy = PermissionPolicy.from_level(PermissionLevel.TRUSTED)
        permissions = AgentPermissions(base_preset="trusted", effective_policy=policy)
        permissions.parent_agent_id = parent_agent_id

        self.services = MockServices(permissions=permissions, child_ids=child_ids)


class MockLogMultiplexer:
    """Minimal mock for LogMultiplexer."""

    def register(self, agent_id: str, callback):
        pass

    def unregister(self, agent_id: str):
        pass


@pytest.fixture
def mock_pool():
    """Create a pool with mock components for testing destroy authorization."""
    # Create a minimal pool with direct access to _agents dict
    class TestPool(AgentPool):
        def __init__(self):
            # Skip normal init, just set up what we need
            self._agents = {}
            self._lock = None  # Will create in test
            self._log_multiplexer = MockLogMultiplexer()

    pool = TestPool()
    # Create lock in async context
    return pool


@pytest.mark.asyncio
async def test_self_destruction_allowed(mock_pool):
    """Test that an agent can destroy itself."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create agent
    agent = MockAgent("worker-1")
    mock_pool._agents["worker-1"] = agent

    # Agent destroys itself - should succeed
    result = await mock_pool.destroy("worker-1", requester_id="worker-1")
    assert result is True
    assert "worker-1" not in mock_pool._agents


@pytest.mark.asyncio
async def test_parent_destroying_child_allowed(mock_pool):
    """Test that a parent agent can destroy its child."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create parent and child
    parent = MockAgent("parent", child_ids={"child"})
    child = MockAgent("child", parent_agent_id="parent")
    mock_pool._agents["parent"] = parent
    mock_pool._agents["child"] = child

    # Parent destroys child - should succeed
    result = await mock_pool.destroy("child", requester_id="parent")
    assert result is True
    assert "child" not in mock_pool._agents


@pytest.mark.asyncio
async def test_sibling_destroying_sibling_denied(mock_pool):
    """Test that a sibling agent cannot destroy another sibling."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create two siblings with same parent
    sibling1 = MockAgent("sibling1", parent_agent_id="parent")
    sibling2 = MockAgent("sibling2", parent_agent_id="parent")
    mock_pool._agents["sibling1"] = sibling1
    mock_pool._agents["sibling2"] = sibling2

    # Sibling1 tries to destroy sibling2 - should fail
    with pytest.raises(AuthorizationError) as exc_info:
        await mock_pool.destroy("sibling2", requester_id="sibling1")

    assert "not authorized" in str(exc_info.value)
    assert "sibling2" in mock_pool._agents  # Agent still exists


@pytest.mark.asyncio
async def test_unrelated_agent_destroying_denied(mock_pool):
    """Test that an unrelated agent cannot destroy another agent."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create two unrelated agents (no parent relationship)
    agent1 = MockAgent("agent1")
    agent2 = MockAgent("agent2")
    mock_pool._agents["agent1"] = agent1
    mock_pool._agents["agent2"] = agent2

    # Agent1 tries to destroy agent2 - should fail
    with pytest.raises(AuthorizationError) as exc_info:
        await mock_pool.destroy("agent2", requester_id="agent1")

    assert "not authorized" in str(exc_info.value)
    assert "agent2" in mock_pool._agents


@pytest.mark.asyncio
async def test_external_client_allowed(mock_pool):
    """Test that external clients (requester_id=None) can destroy any agent."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create agent
    agent = MockAgent("worker-1")
    mock_pool._agents["worker-1"] = agent

    # External client (CLI, script) destroys agent - should succeed
    result = await mock_pool.destroy("worker-1", requester_id=None)
    assert result is True
    assert "worker-1" not in mock_pool._agents


@pytest.mark.asyncio
async def test_admin_override_bypasses_checks(mock_pool):
    """Test that admin_override=True bypasses authorization checks."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create two unrelated agents
    agent1 = MockAgent("agent1")
    agent2 = MockAgent("agent2")
    mock_pool._agents["agent1"] = agent1
    mock_pool._agents["agent2"] = agent2

    # Agent1 tries to destroy agent2 with admin_override - should succeed
    result = await mock_pool.destroy("agent2", requester_id="agent1", admin_override=True)
    assert result is True
    assert "agent2" not in mock_pool._agents


@pytest.mark.asyncio
async def test_destroy_nonexistent_agent_returns_false(mock_pool):
    """Test that destroying a nonexistent agent returns False."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Try to destroy nonexistent agent
    result = await mock_pool.destroy("nonexistent", requester_id="anyone")
    assert result is False


@pytest.mark.asyncio
async def test_child_cannot_destroy_parent(mock_pool):
    """Test that a child agent cannot destroy its parent."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create parent and child
    parent = MockAgent("parent", child_ids={"child"})
    child = MockAgent("child", parent_agent_id="parent")
    mock_pool._agents["parent"] = parent
    mock_pool._agents["child"] = child

    # Child tries to destroy parent - should fail
    with pytest.raises(AuthorizationError) as exc_info:
        await mock_pool.destroy("parent", requester_id="child")

    assert "not authorized" in str(exc_info.value)
    assert "parent" in mock_pool._agents


@pytest.mark.asyncio
async def test_grandparent_cannot_destroy_grandchild(mock_pool):
    """Test that a grandparent cannot destroy a grandchild (only direct parent)."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    # Create grandparent -> parent -> grandchild chain
    grandparent = MockAgent("grandparent", child_ids={"parent"})
    parent = MockAgent("parent", parent_agent_id="grandparent", child_ids={"grandchild"})
    grandchild = MockAgent("grandchild", parent_agent_id="parent")
    mock_pool._agents["grandparent"] = grandparent
    mock_pool._agents["parent"] = parent
    mock_pool._agents["grandchild"] = grandchild

    # Grandparent tries to destroy grandchild - should fail (not direct parent)
    with pytest.raises(AuthorizationError) as exc_info:
        await mock_pool.destroy("grandchild", requester_id="grandparent")

    assert "not authorized" in str(exc_info.value)
    assert "grandchild" in mock_pool._agents

    # But parent can destroy grandchild
    result = await mock_pool.destroy("grandchild", requester_id="parent")
    assert result is True
