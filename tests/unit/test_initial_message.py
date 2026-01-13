"""Tests for initial_message feature in agent creation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.dispatcher import InvalidParamsError


class TestInitialMessageValidation:
    """Tests for initial_message parameter validation."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock pool."""
        pool = MagicMock()
        pool.get.return_value = None  # No parent agent
        return pool

    @pytest.fixture
    def dispatcher(self, mock_pool):
        """Create a dispatcher with mock pool."""
        return GlobalDispatcher(mock_pool)

    @pytest.mark.asyncio
    async def test_initial_message_must_be_string(self, dispatcher, mock_pool):
        """initial_message must be a string if provided."""
        # Set up mock pool to return a mock agent
        mock_agent = MagicMock()
        mock_agent.agent_id = "test-agent"
        mock_pool.create = AsyncMock(return_value=mock_agent)

        # Test with invalid type
        with pytest.raises(InvalidParamsError) as exc_info:
            await dispatcher._handle_create_agent({
                "agent_id": "test",
                "initial_message": 123,  # Not a string
            })
        assert "initial_message must be string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_initial_message_string_accepted(self, dispatcher, mock_pool):
        """Valid string initial_message is accepted."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "test-agent"
        mock_agent.dispatcher = MagicMock()
        mock_agent.dispatcher.dispatch = AsyncMock(return_value=MagicMock(
            result={"content": "Hello!", "request_id": "123"},
            error=None
        ))
        mock_pool.create = AsyncMock(return_value=mock_agent)

        result = await dispatcher._handle_create_agent({
            "agent_id": "test",
            "initial_message": "Hello, agent!",
        })

        assert result["agent_id"] == "test-agent"
        assert "response" in result
        assert result["response"]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_no_initial_message_no_response(self, dispatcher, mock_pool):
        """Without initial_message, no response field in result."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "test-agent"
        mock_pool.create = AsyncMock(return_value=mock_agent)

        result = await dispatcher._handle_create_agent({
            "agent_id": "test",
        })

        assert result["agent_id"] == "test-agent"
        assert "response" not in result


class TestInitialMessageDispatch:
    """Tests for initial_message being dispatched to agent."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock pool."""
        pool = MagicMock()
        pool.get.return_value = None
        return pool

    @pytest.fixture
    def dispatcher(self, mock_pool):
        """Create a dispatcher with mock pool."""
        return GlobalDispatcher(mock_pool)

    @pytest.mark.asyncio
    async def test_initial_message_dispatched_after_create(self, dispatcher, mock_pool):
        """initial_message is dispatched to agent after creation."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "worker-1"
        mock_agent.dispatcher = MagicMock()
        mock_dispatch = AsyncMock(return_value=MagicMock(
            result={"content": "Done!", "request_id": "abc"},
            error=None
        ))
        mock_agent.dispatcher.dispatch = mock_dispatch
        mock_pool.create = AsyncMock(return_value=mock_agent)

        await dispatcher._handle_create_agent({
            "agent_id": "worker-1",
            "initial_message": "Please do something",
        })

        # Verify dispatch was called with a Request object
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args[0][0]
        assert call_args.method == "send"
        assert call_args.params == {"content": "Please do something"}

    @pytest.mark.asyncio
    async def test_initial_message_error_included(self, dispatcher, mock_pool):
        """Error from initial_message dispatch is included in result."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "worker-1"
        mock_agent.dispatcher = MagicMock()
        mock_agent.dispatcher.dispatch = AsyncMock(return_value=MagicMock(
            result=None,
            error={"code": -32000, "message": "Something went wrong"}
        ))
        mock_pool.create = AsyncMock(return_value=mock_agent)

        result = await dispatcher._handle_create_agent({
            "agent_id": "worker-1",
            "initial_message": "Fail please",
        })

        assert "response" in result
        assert "error" in result["response"]


class TestClientCreateAgent:
    """Tests for NexusClient.create_agent with initial_message."""

    def test_initial_message_in_params(self):
        """initial_message is added to params when provided."""
        from nexus3.client import NexusClient

        client = NexusClient()
        client._client = MagicMock()  # Bypass context manager check

        # Check that initial_message parameter exists
        import inspect
        sig = inspect.signature(client.create_agent)
        params = list(sig.parameters.keys())
        assert "initial_message" in params


class TestNexusCreateSkill:
    """Tests for nexus_create skill with initial_message."""

    def test_initial_message_in_parameters(self):
        """initial_message is in skill parameters schema."""
        from nexus3.skill.builtin.nexus_create import NexusCreateSkill
        from nexus3.skill.services import ServiceContainer

        skill = NexusCreateSkill(ServiceContainer())
        params = skill.parameters

        assert "initial_message" in params["properties"]
        assert params["properties"]["initial_message"]["type"] == "string"

    def test_initial_message_in_execute_signature(self):
        """initial_message is in execute method signature."""
        from nexus3.skill.builtin.nexus_create import NexusCreateSkill

        import inspect
        sig = inspect.signature(NexusCreateSkill.execute)
        params = list(sig.parameters.keys())
        assert "initial_message" in params
