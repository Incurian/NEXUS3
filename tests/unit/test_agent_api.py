"""Tests for DirectAgentAPI, AgentScopedAPI, and ClientAdapter."""

import pytest

from nexus3.client import ClientError
from nexus3.rpc.agent_api import AgentScopedAPI, ClientAdapter, DirectAgentAPI
from nexus3.rpc.types import Request, Response


# === Mock Classes ===


class MockAgent:
    """Mock agent with a mock dispatcher."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.dispatcher = MockDispatcher()


class MockDispatcher:
    """Mock dispatcher that records calls and returns configurable responses."""

    def __init__(self):
        self.calls: list[Request] = []
        self.response: Response | None = None

    async def dispatch(self, request: Request) -> Response | None:
        """Record the request and return the configured response."""
        self.calls.append(request)
        return self.response


class MockPool:
    """Mock agent pool."""

    def __init__(self):
        self.agents: dict[str, MockAgent] = {}

    def get(self, agent_id: str) -> MockAgent | None:
        return self.agents.get(agent_id)


class MockGlobalDispatcher:
    """Mock global dispatcher."""

    def __init__(self):
        self.calls: list[Request] = []
        self.response: Response | None = None
        self.requester_ids: list[str | None] = []  # Track requester_ids

    async def dispatch(
        self, request: Request, requester_id: str | None = None
    ) -> Response | None:
        self.calls.append(request)
        self.requester_ids.append(requester_id)
        return self.response


# === AgentScopedAPI Tests ===


class TestAgentScopedAPI:
    """Tests for AgentScopedAPI."""

    @pytest.fixture
    def pool(self):
        """Create a mock pool with an agent."""
        pool = MockPool()
        pool.agents["test-agent"] = MockAgent("test-agent")
        return pool

    @pytest.fixture
    def scoped_api(self, pool):
        """Create an AgentScopedAPI for test-agent."""
        return AgentScopedAPI(pool, "test-agent")

    async def test_send_calls_dispatcher(self, scoped_api, pool):
        """Test that send() calls the dispatcher with correct method."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"content": "Hello back", "request_id": "abc123"},
        )

        result = await scoped_api.send("Hello")

        assert result == {"content": "Hello back", "request_id": "abc123"}
        assert len(pool.agents["test-agent"].dispatcher.calls) == 1
        call = pool.agents["test-agent"].dispatcher.calls[0]
        assert call.method == "send"
        assert call.params == {"content": "Hello"}

    async def test_get_tokens_calls_dispatcher(self, scoped_api, pool):
        """Test that get_tokens() calls the dispatcher."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"used": 100, "available": 1000},
        )

        result = await scoped_api.get_tokens()

        assert result == {"used": 100, "available": 1000}
        call = pool.agents["test-agent"].dispatcher.calls[0]
        assert call.method == "get_tokens"

    async def test_agent_not_found_raises_client_error(self, pool):
        """Test that accessing a non-existent agent raises ClientError."""
        api = AgentScopedAPI(pool, "nonexistent")

        with pytest.raises(ClientError, match="Agent not found: nonexistent"):
            await api.send("Hello")

    async def test_error_response_raises_client_error(self, scoped_api, pool):
        """Test that error responses are converted to ClientError."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            error={"code": -32602, "message": "Invalid params"},
        )

        with pytest.raises(ClientError, match="RPC error -32602: Invalid params"):
            await scoped_api.send("Hello")

    async def test_send_includes_request_id_when_provided(self, scoped_api, pool):
        """Test that send() includes request_id in params when provided."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"content": "Response", "request_id": 42},
        )

        await scoped_api.send("Hello", request_id=42)

        call = pool.agents["test-agent"].dispatcher.calls[0]
        assert call.method == "send"
        assert call.params == {"content": "Hello", "request_id": 42}

    async def test_send_omits_request_id_when_none(self, scoped_api, pool):
        """Test that send() omits request_id from params when not provided."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"content": "Response"},
        )

        await scoped_api.send("Hello")

        call = pool.agents["test-agent"].dispatcher.calls[0]
        assert call.method == "send"
        assert call.params == {"content": "Hello"}
        assert "request_id" not in call.params

    async def test_send_with_request_id_zero(self, scoped_api, pool):
        """Test that send() correctly handles request_id=0 (BL-5 fix)."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"content": "Response", "request_id": 0},
        )

        await scoped_api.send("Hello", request_id=0)

        call = pool.agents["test-agent"].dispatcher.calls[0]
        assert call.params == {"content": "Hello", "request_id": 0}

    async def test_cancel_with_request_id_zero(self, scoped_api, pool):
        """Test that cancel() correctly handles request_id=0 (BL-6 fix)."""
        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"cancelled": True},
        )

        await scoped_api.cancel(request_id=0)

        call = pool.agents["test-agent"].dispatcher.calls[0]
        assert call.method == "cancel"
        assert call.params == {"request_id": 0}


# === DirectAgentAPI Tests ===


class TestDirectAgentAPI:
    """Tests for DirectAgentAPI."""

    @pytest.fixture
    def pool(self):
        """Create a mock pool."""
        return MockPool()

    @pytest.fixture
    def global_dispatcher(self):
        """Create a mock global dispatcher."""
        return MockGlobalDispatcher()

    @pytest.fixture
    def api(self, pool, global_dispatcher):
        """Create a DirectAgentAPI."""
        return DirectAgentAPI(pool, global_dispatcher)

    async def test_create_agent_calls_global_dispatcher(self, api, global_dispatcher):
        """Test that create_agent() calls the global dispatcher."""
        global_dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"agent_id": "new-agent", "url": "/agent/new-agent"},
        )

        result = await api.create_agent("new-agent", preset="sandboxed")

        assert result == {"agent_id": "new-agent", "url": "/agent/new-agent"}
        assert len(global_dispatcher.calls) == 1
        call = global_dispatcher.calls[0]
        assert call.method == "create_agent"
        assert call.params["agent_id"] == "new-agent"
        assert call.params["preset"] == "sandboxed"

    async def test_destroy_agent_calls_global_dispatcher(self, api, global_dispatcher):
        """Test that destroy_agent() calls the global dispatcher."""
        global_dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"success": True, "agent_id": "old-agent"},
        )

        result = await api.destroy_agent("old-agent")

        assert result == {"success": True, "agent_id": "old-agent"}
        call = global_dispatcher.calls[0]
        assert call.method == "destroy_agent"
        assert call.params == {"agent_id": "old-agent"}

    async def test_list_agents_returns_list(self, api, global_dispatcher):
        """Test that list_agents() returns the agent list."""
        global_dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"agents": [{"agent_id": "a"}, {"agent_id": "b"}]},
        )

        result = await api.list_agents()

        assert result == [{"agent_id": "a"}, {"agent_id": "b"}]

    async def test_for_agent_returns_scoped_api(self, api, pool):
        """Test that for_agent() returns an AgentScopedAPI."""
        scoped = api.for_agent("test-agent")

        assert isinstance(scoped, AgentScopedAPI)
        assert scoped._agent_id == "test-agent"


# === ClientAdapter Tests ===


class TestClientAdapter:
    """Tests for ClientAdapter."""

    @pytest.fixture
    def pool(self):
        """Create a mock pool with an agent."""
        pool = MockPool()
        pool.agents["test-agent"] = MockAgent("test-agent")
        return pool

    @pytest.fixture
    def global_dispatcher(self):
        """Create a mock global dispatcher."""
        return MockGlobalDispatcher()

    @pytest.fixture
    def api(self, pool, global_dispatcher):
        """Create a DirectAgentAPI."""
        return DirectAgentAPI(pool, global_dispatcher)

    def test_adapter_with_agent_scoped(self, api, pool):
        """Test creating adapter with agent-scoped API."""
        scoped = api.for_agent("test-agent")
        adapter = ClientAdapter(api, scoped)

        assert adapter._global is api
        assert adapter._agent is scoped

    def test_adapter_without_agent_scoped(self, api):
        """Test creating adapter without agent-scoped API."""
        adapter = ClientAdapter(api, None)

        assert adapter._global is api
        assert adapter._agent is None

    async def test_send_requires_agent_context(self, api):
        """Test that send() requires an agent-scoped API."""
        adapter = ClientAdapter(api, None)

        with pytest.raises(ClientError, match="No agent context for send"):
            await adapter.send("Hello")

    async def test_global_methods_work_without_agent_context(
        self, api, global_dispatcher
    ):
        """Test that global methods work without agent-scoped API."""
        adapter = ClientAdapter(api, None)
        global_dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"agents": []},
        )

        result = await adapter.list_agents()

        assert result == []

    async def test_adapter_send_delegates_to_scoped(self, api, pool):
        """Test that adapter.send() delegates to AgentScopedAPI."""
        scoped = api.for_agent("test-agent")
        adapter = ClientAdapter(api, scoped)

        pool.agents["test-agent"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"content": "Response", "request_id": "123"},
        )

        result = await adapter.send("Hello")

        assert result == {"content": "Response", "request_id": "123"}


# === Integration-style Tests ===


class TestAgentAPIIntegration:
    """Integration-style tests for the full AgentAPI flow."""

    async def test_full_flow_create_send_destroy(self):
        """Test a complete flow: create agent, send message, destroy agent."""
        pool = MockPool()
        global_dispatcher = MockGlobalDispatcher()
        api = DirectAgentAPI(pool, global_dispatcher)

        # Create agent
        global_dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"agent_id": "worker", "url": "/agent/worker"},
        )
        create_result = await api.create_agent("worker", preset="sandboxed")
        assert create_result["agent_id"] == "worker"

        # Simulate agent being added to pool
        pool.agents["worker"] = MockAgent("worker")

        # Send message
        pool.agents["worker"].dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"content": "Done!", "request_id": "abc"},
        )
        scoped = api.for_agent("worker")
        send_result = await scoped.send("Do something")
        assert send_result["content"] == "Done!"

        # Destroy agent
        global_dispatcher.response = Response(
            jsonrpc="2.0",
            id=1,
            result={"success": True, "agent_id": "worker"},
        )
        destroy_result = await api.destroy_agent("worker")
        assert destroy_result["success"] is True
