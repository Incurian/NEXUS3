"""Unit tests for unified command infrastructure.

Tests for:
- CommandResult: Enum for command result statuses
- CommandOutput: Structured command output
- CommandContext: Context for command execution
- Core commands: list, create, destroy, send, status, cancel, save, clone, rename, delete, shutdown
"""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus3.commands import (
    CommandContext,
    CommandOutput,
    CommandResult,
    cmd_cancel,
    cmd_clone,
    cmd_create,
    cmd_delete,
    cmd_destroy,
    cmd_list,
    cmd_rename,
    cmd_save,
    cmd_send,
    cmd_shutdown,
    cmd_status,
)

# -----------------------------------------------------------------------------
# CommandResult Tests
# -----------------------------------------------------------------------------


class TestCommandResult:
    """Tests for CommandResult enum."""

    def test_has_success(self):
        """CommandResult has SUCCESS value."""
        assert CommandResult.SUCCESS is not None

    def test_has_error(self):
        """CommandResult has ERROR value."""
        assert CommandResult.ERROR is not None

    def test_has_quit(self):
        """CommandResult has QUIT value."""
        assert CommandResult.QUIT is not None

    def test_has_switch_agent(self):
        """CommandResult has SWITCH_AGENT value."""
        assert CommandResult.SWITCH_AGENT is not None

    def test_has_enter_whisper(self):
        """CommandResult has ENTER_WHISPER value."""
        assert CommandResult.ENTER_WHISPER is not None

    def test_all_values_unique(self):
        """All CommandResult values are unique."""
        values = [r.value for r in CommandResult]
        assert len(values) == len(set(values))


# -----------------------------------------------------------------------------
# CommandOutput Tests
# -----------------------------------------------------------------------------


class TestCommandOutput:
    """Tests for CommandOutput dataclass."""

    def test_basic_construction(self):
        """CommandOutput can be constructed with result only."""
        output = CommandOutput(result=CommandResult.SUCCESS)
        assert output.result == CommandResult.SUCCESS
        assert output.message is None
        assert output.data is None
        assert output.new_agent_id is None
        assert output.whisper_target is None

    def test_with_all_fields(self):
        """CommandOutput can be constructed with all fields."""
        output = CommandOutput(
            result=CommandResult.SWITCH_AGENT,
            message="Switching to agent",
            data={"key": "value"},
            new_agent_id="worker-1",
            whisper_target="helper",
        )
        assert output.result == CommandResult.SWITCH_AGENT
        assert output.message == "Switching to agent"
        assert output.data == {"key": "value"}
        assert output.new_agent_id == "worker-1"
        assert output.whisper_target == "helper"

    def test_success_factory(self):
        """CommandOutput.success() creates SUCCESS output."""
        output = CommandOutput.success(message="OK", data={"foo": "bar"})
        assert output.result == CommandResult.SUCCESS
        assert output.message == "OK"
        assert output.data == {"foo": "bar"}

    def test_success_factory_defaults(self):
        """CommandOutput.success() works with no args."""
        output = CommandOutput.success()
        assert output.result == CommandResult.SUCCESS
        assert output.message is None
        assert output.data is None

    def test_error_factory(self):
        """CommandOutput.error() creates ERROR output with message."""
        output = CommandOutput.error("Something went wrong")
        assert output.result == CommandResult.ERROR
        assert output.message == "Something went wrong"

    def test_quit_factory(self):
        """CommandOutput.quit() creates QUIT output."""
        output = CommandOutput.quit()
        assert output.result == CommandResult.QUIT

    def test_switch_agent_factory(self):
        """CommandOutput.switch_agent() creates SWITCH_AGENT output."""
        output = CommandOutput.switch_agent("new-agent")
        assert output.result == CommandResult.SWITCH_AGENT
        assert output.new_agent_id == "new-agent"

    def test_enter_whisper_factory(self):
        """CommandOutput.enter_whisper() creates ENTER_WHISPER output."""
        output = CommandOutput.enter_whisper("target-agent")
        assert output.result == CommandResult.ENTER_WHISPER
        assert output.whisper_target == "target-agent"


# -----------------------------------------------------------------------------
# Test Fixtures and Helpers
# -----------------------------------------------------------------------------


class MockAgent:
    """Mock Agent for testing commands."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.created_at = datetime.now()

        # Mock context
        self.context = MagicMock()
        self.context.messages = []
        self.context.system_prompt = "Test prompt"
        self.context.get_token_summary.return_value = {"total": 100}
        self.context.get_token_usage.return_value = {"total": 100}

        # Mock session
        self.session = MagicMock()
        self.session.cancel = MagicMock()
        # send() returns an async generator - use _send_chunks to configure
        self._send_chunks: list[str] = []
        self._send_error: Exception | None = None

        async def mock_send(*args, **kwargs):
            if self._send_error:
                raise self._send_error
            for chunk in self._send_chunks:
                yield chunk

        self.session.send = mock_send

        # Mock dispatcher
        self.dispatcher = MagicMock()
        self.dispatcher.should_shutdown = False
        self.dispatcher.request_shutdown = MagicMock()

        # Mock services (dict-like for .get())
        self.services = MagicMock()
        self.services.get = MagicMock(return_value=None)  # No permissions by default


class MockAgentPool:
    """Mock AgentPool for testing commands."""

    def __init__(self):
        self._agents: dict[str, MockAgent] = {}
        self._system_prompt_path: str | None = None

    @property
    def system_prompt_path(self) -> str | None:
        """Mock system_prompt_path property."""
        return self._system_prompt_path

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def get(self, agent_id: str) -> MockAgent | None:
        return self._agents.get(agent_id)

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "agent_id": agent.agent_id,
                "is_temp": agent.agent_id.startswith("."),
                "created_at": agent.created_at.isoformat(),
                "message_count": len(agent.context.messages),
                "should_shutdown": agent.dispatcher.should_shutdown,
            }
            for agent in self._agents.values()
        ]

    async def create(self, agent_id: str, config: Any = None) -> MockAgent:
        if agent_id in self._agents:
            raise ValueError(f"Agent already exists: {agent_id}")
        agent = MockAgent(agent_id)
        self._agents[agent_id] = agent
        return agent

    async def destroy(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def add_agent(self, agent_id: str) -> MockAgent:
        """Helper to add a pre-existing agent."""
        agent = MockAgent(agent_id)
        self._agents[agent_id] = agent
        return agent


class MockSessionManager:
    """Mock SessionManager for testing commands."""

    def __init__(self):
        self._sessions: dict[str, MagicMock] = {}
        self.save_calls: list[Any] = []
        self.delete_calls: list[str] = []
        self.rename_calls: list[tuple[str, str]] = []
        self.clone_calls: list[tuple[str, str]] = []

    def save_session(self, saved: Any) -> Path:
        self.save_calls.append(saved)
        return Path(f"/mock/sessions/{saved.agent_id}.json")

    def delete_session(self, name: str) -> bool:
        self.delete_calls.append(name)
        return name in self._sessions

    def rename_session(self, old: str, new: str) -> Path:
        self.rename_calls.append((old, new))
        if old not in self._sessions:
            from nexus3.session.session_manager import SessionNotFoundError
            raise SessionNotFoundError(old)
        self._sessions[new] = self._sessions.pop(old)
        return Path(f"/mock/sessions/{new}.json")

    def clone_session(self, src: str, dest: str) -> Path:
        self.clone_calls.append((src, dest))
        if src not in self._sessions:
            from nexus3.session.session_manager import SessionNotFoundError
            raise SessionNotFoundError(src)
        self._sessions[dest] = self._sessions[src]
        return Path(f"/mock/sessions/{dest}.json")

    def add_session(self, name: str):
        """Helper to add a pre-existing session."""
        self._sessions[name] = MagicMock()


@pytest.fixture
def mock_pool() -> MockAgentPool:
    """Create a mock agent pool."""
    return MockAgentPool()


@pytest.fixture
def mock_session_manager() -> MockSessionManager:
    """Create a mock session manager."""
    return MockSessionManager()


@pytest.fixture
def ctx(mock_pool: MockAgentPool, mock_session_manager: MockSessionManager) -> CommandContext:
    """Create a command context with mocks."""
    return CommandContext(
        pool=mock_pool,
        session_manager=mock_session_manager,
        current_agent_id=None,
        is_repl=False,
    )


# -----------------------------------------------------------------------------
# cmd_list Tests
# -----------------------------------------------------------------------------


class TestCmdList:
    """Tests for cmd_list command."""

    @pytest.mark.asyncio
    async def test_list_empty_pool(self, ctx: CommandContext):
        """cmd_list returns success with empty list when no agents."""
        output = await cmd_list(ctx)

        assert output.result == CommandResult.SUCCESS
        assert output.data == {"agents": []}
        assert "No active agents" in output.message

    @pytest.mark.asyncio
    async def test_list_with_agents(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_list returns info about all agents."""
        mock_pool.add_agent("agent-1")
        mock_pool.add_agent("agent-2")

        output = await cmd_list(ctx)

        assert output.result == CommandResult.SUCCESS
        assert len(output.data["agents"]) == 2
        agent_ids = {a["agent_id"] for a in output.data["agents"]}
        assert agent_ids == {"agent-1", "agent-2"}

    @pytest.mark.asyncio
    async def test_list_shows_temp_status(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_list shows temp vs named status for agents."""
        mock_pool.add_agent(".1")  # temp
        mock_pool.add_agent("named")  # named

        output = await cmd_list(ctx)

        agents = {a["agent_id"]: a for a in output.data["agents"]}
        assert agents[".1"]["is_temp"] is True
        assert agents["named"]["is_temp"] is False


# -----------------------------------------------------------------------------
# cmd_create Tests
# -----------------------------------------------------------------------------


class TestCmdCreate:
    """Tests for cmd_create command."""

    @pytest.mark.asyncio
    async def test_create_success(self, ctx: CommandContext):
        """cmd_create creates agent and returns success."""
        output = await cmd_create(ctx, name="new-agent")

        assert output.result == CommandResult.SUCCESS
        assert output.data["agent_id"] == "new-agent"
        assert "Created agent" in output.message

    @pytest.mark.asyncio
    async def test_create_with_permission(self, ctx: CommandContext):
        """cmd_create accepts permission parameter."""
        output = await cmd_create(ctx, name="sandbox-agent", permission="sandboxed")

        assert output.result == CommandResult.SUCCESS
        assert output.data["permission"] == "sandboxed"

    @pytest.mark.asyncio
    async def test_create_invalid_permission(self, ctx: CommandContext):
        """cmd_create rejects invalid permission level."""
        output = await cmd_create(ctx, name="agent", permission="invalid")

        assert output.result == CommandResult.ERROR
        assert "Invalid permission level" in output.message

    @pytest.mark.asyncio
    async def test_create_duplicate(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_create fails for existing agent."""
        mock_pool.add_agent("existing")

        output = await cmd_create(ctx, name="existing")

        assert output.result == CommandResult.ERROR
        assert "already exists" in output.message


# -----------------------------------------------------------------------------
# cmd_destroy Tests
# -----------------------------------------------------------------------------


class TestCmdDestroy:
    """Tests for cmd_destroy command."""

    @pytest.mark.asyncio
    async def test_destroy_success(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_destroy removes agent and returns success."""
        mock_pool.add_agent("to-destroy")

        output = await cmd_destroy(ctx, name="to-destroy")

        assert output.result == CommandResult.SUCCESS
        assert output.data["destroyed"] is True
        assert "to-destroy" not in mock_pool

    @pytest.mark.asyncio
    async def test_destroy_not_found(self, ctx: CommandContext):
        """cmd_destroy fails for non-existent agent."""
        output = await cmd_destroy(ctx, name="nonexistent")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message

    @pytest.mark.asyncio
    async def test_destroy_current_agent_repl(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """cmd_destroy fails when trying to destroy current agent in REPL mode."""
        mock_pool.add_agent("current")
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="current",
            is_repl=True,
        )

        output = await cmd_destroy(ctx, name="current")

        assert output.result == CommandResult.ERROR
        assert "current agent" in output.message.lower()


# -----------------------------------------------------------------------------
# cmd_send Tests
# -----------------------------------------------------------------------------


class TestCmdSend:
    """Tests for cmd_send command."""

    @pytest.mark.asyncio
    async def test_send_success(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_send sends message and returns response."""
        agent = mock_pool.add_agent("target")
        # Configure the mock send() to yield response chunks
        agent._send_chunks = ["Hello ", "back!"]

        output = await cmd_send(ctx, agent_id="target", message="Hello")

        assert output.result == CommandResult.SUCCESS
        assert output.data["content"] == "Hello back!"

    @pytest.mark.asyncio
    async def test_send_agent_not_found(self, ctx: CommandContext):
        """cmd_send fails for non-existent agent."""
        output = await cmd_send(ctx, agent_id="nonexistent", message="Hello")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message

    @pytest.mark.asyncio
    async def test_send_handles_error(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_send handles session errors gracefully."""
        agent = mock_pool.add_agent("target")
        # Configure the mock send() to raise an error
        agent._send_error = Exception("Test error")

        output = await cmd_send(ctx, agent_id="target", message="Hello")

        assert output.result == CommandResult.ERROR
        assert "Test error" in output.message


# -----------------------------------------------------------------------------
# cmd_status Tests
# -----------------------------------------------------------------------------


class TestCmdStatus:
    """Tests for cmd_status command."""

    @pytest.mark.asyncio
    async def test_status_with_agent_id(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_status returns agent info when agent_id provided."""
        mock_pool.add_agent("target")

        output = await cmd_status(ctx, agent_id="target")

        assert output.result == CommandResult.SUCCESS
        assert output.data["agent_id"] == "target"
        assert "tokens" in output.data

    @pytest.mark.asyncio
    async def test_status_current_agent(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """cmd_status uses current agent when no agent_id provided."""
        mock_pool.add_agent("current")
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="current",
            is_repl=True,
        )

        output = await cmd_status(ctx, agent_id=None)

        assert output.result == CommandResult.SUCCESS
        assert output.data["agent_id"] == "current"

    @pytest.mark.asyncio
    async def test_status_no_agent(self, ctx: CommandContext):
        """cmd_status fails when no agent specified and no current."""
        output = await cmd_status(ctx, agent_id=None)

        assert output.result == CommandResult.ERROR
        assert "No agent specified" in output.message

    @pytest.mark.asyncio
    async def test_status_agent_not_found(self, ctx: CommandContext):
        """cmd_status fails for non-existent agent."""
        output = await cmd_status(ctx, agent_id="nonexistent")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message


# -----------------------------------------------------------------------------
# cmd_cancel Tests
# -----------------------------------------------------------------------------


class TestCmdCancel:
    """Tests for cmd_cancel command."""

    @pytest.mark.asyncio
    async def test_cancel_success(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_cancel cancels request and returns success."""
        mock_pool.add_agent("target")

        output = await cmd_cancel(ctx, agent_id="target")

        assert output.result == CommandResult.SUCCESS
        assert output.data["cancelled"] is True

    @pytest.mark.asyncio
    async def test_cancel_with_request_id(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_cancel accepts request_id parameter."""
        mock_pool.add_agent("target")

        output = await cmd_cancel(ctx, agent_id="target", request_id="123")

        assert output.result == CommandResult.SUCCESS
        assert output.data["request_id"] == 123

    @pytest.mark.asyncio
    async def test_cancel_invalid_request_id(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_cancel fails with invalid request_id."""
        mock_pool.add_agent("target")

        output = await cmd_cancel(ctx, agent_id="target", request_id="not-a-number")

        assert output.result == CommandResult.ERROR
        assert "Invalid request_id" in output.message

    @pytest.mark.asyncio
    async def test_cancel_no_agent(self, ctx: CommandContext):
        """cmd_cancel fails when no agent specified and no current."""
        output = await cmd_cancel(ctx, agent_id=None)

        assert output.result == CommandResult.ERROR
        assert "No agent specified" in output.message


# -----------------------------------------------------------------------------
# cmd_save Tests
# -----------------------------------------------------------------------------


class TestCmdSave:
    """Tests for cmd_save command."""

    @pytest.mark.asyncio
    async def test_save_success(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """cmd_save saves session and returns success."""
        mock_pool.add_agent("my-agent")
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="my-agent",
            is_repl=True,
        )

        output = await cmd_save(ctx, name="my-save")

        assert output.result == CommandResult.SUCCESS
        assert "my-save" in output.data["path"]
        assert len(mock_session_manager.save_calls) == 1

    @pytest.mark.asyncio
    async def test_save_no_current_agent(self, ctx: CommandContext):
        """cmd_save fails when no current agent."""
        output = await cmd_save(ctx, name="save")

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message

    @pytest.mark.asyncio
    async def test_save_temp_name_rejected(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """cmd_save rejects temp names."""
        mock_pool.add_agent(".1")
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id=".1",
            is_repl=True,
        )

        output = await cmd_save(ctx, name=".temp")

        assert output.result == CommandResult.ERROR
        assert "temp name" in output.message.lower()


# -----------------------------------------------------------------------------
# cmd_clone Tests
# -----------------------------------------------------------------------------


class TestCmdClone:
    """Tests for cmd_clone command."""

    @pytest.mark.asyncio
    async def test_clone_active_agent(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_clone clones active agent to new active agent."""
        src = mock_pool.add_agent("src")
        src.context.messages = [MagicMock(), MagicMock()]

        output = await cmd_clone(ctx, src="src", dest="dest")

        assert output.result == CommandResult.SUCCESS
        assert output.data["type"] == "active"
        assert "dest" in mock_pool

    @pytest.mark.asyncio
    async def test_clone_saved_session(
        self, ctx: CommandContext, mock_session_manager: MockSessionManager
    ):
        """cmd_clone clones saved session to new saved session."""
        mock_session_manager.add_session("saved-src")

        output = await cmd_clone(ctx, src="saved-src", dest="saved-dest")

        assert output.result == CommandResult.SUCCESS
        assert output.data["type"] == "saved"

    @pytest.mark.asyncio
    async def test_clone_not_found(self, ctx: CommandContext):
        """cmd_clone fails when source not found."""
        output = await cmd_clone(ctx, src="nonexistent", dest="dest")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message

    @pytest.mark.asyncio
    async def test_clone_dest_exists(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_clone fails when destination already exists."""
        mock_pool.add_agent("src")
        mock_pool.add_agent("dest")

        output = await cmd_clone(ctx, src="src", dest="dest")

        assert output.result == CommandResult.ERROR
        assert "already exists" in output.message


# -----------------------------------------------------------------------------
# cmd_rename Tests
# -----------------------------------------------------------------------------


class TestCmdRename:
    """Tests for cmd_rename command."""

    @pytest.mark.asyncio
    async def test_rename_active_agent(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_rename renames active agent."""
        mock_pool.add_agent("old")

        output = await cmd_rename(ctx, old="old", new="new")

        assert output.result == CommandResult.SUCCESS
        assert output.data["type"] == "active"
        assert "old" not in mock_pool
        assert "new" in mock_pool

    @pytest.mark.asyncio
    async def test_rename_saved_session(
        self, ctx: CommandContext, mock_session_manager: MockSessionManager
    ):
        """cmd_rename renames saved session."""
        mock_session_manager.add_session("old-saved")

        output = await cmd_rename(ctx, old="old-saved", new="new-saved")

        assert output.result == CommandResult.SUCCESS
        assert output.data["type"] == "saved"

    @pytest.mark.asyncio
    async def test_rename_not_found(self, ctx: CommandContext):
        """cmd_rename fails when source not found."""
        output = await cmd_rename(ctx, old="nonexistent", new="new")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message

    @pytest.mark.asyncio
    async def test_rename_dest_exists(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_rename fails when destination already exists."""
        mock_pool.add_agent("old")
        mock_pool.add_agent("new")

        output = await cmd_rename(ctx, old="old", new="new")

        assert output.result == CommandResult.ERROR
        assert "already exists" in output.message


# -----------------------------------------------------------------------------
# cmd_delete Tests
# -----------------------------------------------------------------------------


class TestCmdDelete:
    """Tests for cmd_delete command."""

    @pytest.mark.asyncio
    async def test_delete_success(
        self, ctx: CommandContext, mock_session_manager: MockSessionManager
    ):
        """cmd_delete deletes saved session."""
        mock_session_manager.add_session("to-delete")

        output = await cmd_delete(ctx, name="to-delete")

        assert output.result == CommandResult.SUCCESS
        assert output.data["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, ctx: CommandContext):
        """cmd_delete fails when session not found."""
        output = await cmd_delete(ctx, name="nonexistent")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message

    @pytest.mark.asyncio
    async def test_delete_temp_name_rejected(self, ctx: CommandContext):
        """cmd_delete rejects temp names."""
        output = await cmd_delete(ctx, name=".1")

        assert output.result == CommandResult.ERROR
        assert "temp" in output.message.lower()


# -----------------------------------------------------------------------------
# cmd_shutdown Tests
# -----------------------------------------------------------------------------


class TestCmdShutdown:
    """Tests for cmd_shutdown command."""

    @pytest.mark.asyncio
    async def test_shutdown_requests_shutdown(self, ctx: CommandContext, mock_pool: MockAgentPool):
        """cmd_shutdown marks agents for shutdown."""
        agent = mock_pool.add_agent("agent")

        output = await cmd_shutdown(ctx)

        assert output.result == CommandResult.QUIT
        assert output.data["shutdown"] is True
        agent.dispatcher.request_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_empty_pool(self, ctx: CommandContext):
        """cmd_shutdown works with empty pool."""
        output = await cmd_shutdown(ctx)

        assert output.result == CommandResult.QUIT
        assert output.data["shutdown"] is True
