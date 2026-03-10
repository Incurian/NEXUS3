"""Security tests for destroy-agent authorization.

Tests that only authorized agents can destroy other agents:
- Self-destruction is allowed (agent destroys itself)
- Parent can destroy children
- Sibling destroying sibling is denied
- External clients (requester_id=None) are treated as admin
- admin_override=True bypasses all checks
- Destroy remains kernel-authoritative when the kernel denies
"""

import pytest

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResourceType,
)
from nexus3.core.capabilities import (
    CapabilitySigner,
    InMemoryCapabilityRevocationStore,
    generate_capability_secret,
)
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

    def has(self, key: str) -> bool:
        return key in self._data

    def get_permissions(self) -> AgentPermissions | None:
        permissions = self._data.get("permissions")
        return permissions if isinstance(permissions, AgentPermissions) else None

    def get_child_agent_ids(self) -> set[str] | None:
        child_ids = self._data.get("child_agent_ids")
        return set(child_ids) if isinstance(child_ids, set) else None

    def set_child_agent_ids(self, child_ids: set[str] | None) -> None:
        if child_ids is None:
            self._data.pop("child_agent_ids", None)
            return
        self._data["child_agent_ids"] = set(child_ids)

    def get_model(self):
        return self._data.get("model")

    def get_cwd(self):
        return self._data.get("cwd")


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


class TestDestroyAuthorizationAdapter:
    """Mirror current legacy destroy authorization logic for test parity."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.AGENT_DESTROY:
            return None
        if request.resource.resource_type != AuthorizationResourceType.AGENT:
            return None

        requester_id = request.principal_id
        target_agent_id = request.resource.identifier
        target_parent_agent_id = request.context.get("target_parent_agent_id")
        admin_override = request.context.get("admin_override")

        if admin_override is True:
            return AuthorizationDecision.allow(request, reason="admin_override")
        if requester_id == "external":
            return AuthorizationDecision.allow(request, reason="external_requester")

        if requester_id == target_agent_id:
            return AuthorizationDecision.allow(request, reason="self_destroy")
        if isinstance(target_parent_agent_id, str) and target_parent_agent_id == requester_id:
            return AuthorizationDecision.allow(request, reason="parent_destroy")
        return AuthorizationDecision.deny(request, reason="not_parent_or_self")


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
            self._destroy_authorization_kernel = AdapterAuthorizationKernel(
                adapters=(TestDestroyAuthorizationAdapter(),),
                default_allow=False,
            )
            self._capability_signer = CapabilitySigner(generate_capability_secret())
            self._capability_revocation_store = InMemoryCapabilityRevocationStore()
            self._issued_capability_token_ids_by_subject: dict[str, set[str]] = {}
            self._issued_capability_token_ids_by_issuer: dict[str, set[str]] = {}
            self._direct_capability_ttl_seconds = 300

    pool = TestPool()
    # Create lock in async context
    return pool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "target_id", "requester_id", "admin_override", "expect_success"),
    [
        ("self", "self-agent", "self-agent", False, True),
        ("parent", "child-agent", "parent-agent", False, True),
        ("sibling", "sibling-b", "sibling-a", False, False),
        ("external", "external-target", None, False, True),
        ("admin_override", "override-target", "unrelated-agent", True, True),
    ],
)
async def test_destroy_authorization_parity_matrix(
    mock_pool,
    case: str,
    target_id: str,
    requester_id: str | None,
    admin_override: bool,
    expect_success: bool,
):
    """Verify destroy authorization parity matrix stays stable across key relationships."""
    import asyncio

    mock_pool._lock = asyncio.Lock()

    if case == "self":
        mock_pool._agents[target_id] = MockAgent(target_id)
    elif case == "parent":
        mock_pool._agents["parent-agent"] = MockAgent("parent-agent", child_ids={"child-agent"})
        mock_pool._agents[target_id] = MockAgent(target_id, parent_agent_id="parent-agent")
    elif case == "sibling":
        mock_pool._agents["sibling-a"] = MockAgent("sibling-a", parent_agent_id="parent-root")
        mock_pool._agents[target_id] = MockAgent(target_id, parent_agent_id="parent-root")
    else:
        mock_pool._agents[target_id] = MockAgent(target_id)
        if case == "admin_override":
            mock_pool._agents["unrelated-agent"] = MockAgent("unrelated-agent")

    if expect_success:
        result = await mock_pool.destroy(
            target_id,
            requester_id=requester_id,
            admin_override=admin_override,
        )
        assert result is True
        assert target_id not in mock_pool._agents
    else:
        with pytest.raises(AuthorizationError):
            await mock_pool.destroy(
                target_id,
                requester_id=requester_id,
                admin_override=admin_override,
            )
        assert target_id in mock_pool._agents


@pytest.mark.asyncio
async def test_destroy_denied_when_kernel_denies(mock_pool):
    """Destroy is kernel-authoritative: explicit kernel denies block destroy."""
    import asyncio

    class DenyAllDestroyKernel:
        def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
            return AuthorizationDecision.deny(request, reason="forced_mismatch")

    mock_pool._lock = asyncio.Lock()
    mock_pool._agents["worker-1"] = MockAgent("worker-1")
    mock_pool._destroy_authorization_kernel = DenyAllDestroyKernel()

    with pytest.raises(AuthorizationError) as exc_info:
        await mock_pool.destroy("worker-1", requester_id="worker-1")
    assert "not authorized" in str(exc_info.value)
    assert "worker-1" in mock_pool._agents


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
