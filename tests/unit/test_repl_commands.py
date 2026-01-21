"""Unit tests for nexus3.cli.repl_commands module.

Tests for REPL-specific command handlers:
- cmd_agent: Agent status, switching, creation
- cmd_whisper/cmd_over: Whisper mode management
- cmd_cwd: Working directory management
- cmd_permissions: Permission level management
- cmd_prompt: System prompt management
- cmd_help: Help display
- cmd_clear: Display clearing
- cmd_quit: REPL exit
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus3.cli.repl_commands import (
    HELP_TEXT,
    cmd_agent,
    cmd_clear,
    cmd_compact,
    cmd_cwd,
    cmd_help,
    cmd_over,
    cmd_permissions,
    cmd_prompt,
    cmd_quit,
    cmd_whisper,
)
from nexus3.cli.whisper import WhisperMode
from nexus3.commands.protocol import CommandContext, CommandResult


# -----------------------------------------------------------------------------
# Test Fixtures and Helpers
# -----------------------------------------------------------------------------


class MockServices:
    """Mock ServiceContainer for testing REPL commands."""

    def __init__(self):
        self._services: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        return self._services.get(name)

    def register(self, name: str, value: Any) -> None:
        self._services[name] = value

    def get_cwd(self) -> Path:
        """Get agent's working directory."""
        cwd = self._services.get("cwd")
        if cwd is not None:
            return Path(cwd)
        return Path.cwd()


class MockResolvedModel:
    """Mock ResolvedModel for testing."""

    def __init__(self):
        self.alias = "default"
        self.model_id = "test/model"
        self.context_window = 8000
        self.reasoning = False
        self.provider_name = "test-provider"


class MockAgent:
    """Mock Agent for testing REPL commands."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.created_at = datetime.now()

        # Mock context
        self.context = MagicMock()
        self.context.messages = []
        self.context.system_prompt = "Test system prompt content"
        self.context.get_token_summary.return_value = {"total": 500, "budget": 8000}
        self.context.get_token_usage.return_value = {
            "total": 500,
            "budget": 8000,
            "available": 6000,
            "remaining": 5500,
        }

        # Mock session
        self.session = MagicMock()

        # Mock dispatcher
        self.dispatcher = MagicMock()
        self.dispatcher.should_shutdown = False

        # Mock services (with model)
        self.services = MockServices()
        self.services.register("model", MockResolvedModel())

        # Mock registry for permission-based tool filtering
        self.registry = MagicMock()
        self.registry.get_definitions_for_permissions.return_value = []


class MockAgentPool:
    """Mock AgentPool for testing REPL commands."""

    def __init__(self):
        self._agents: dict[str, MockAgent] = {}

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
            }
            for agent in self._agents.values()
        ]

    async def create(self, agent_id: str) -> MockAgent:
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
    """Mock SessionManager for testing REPL commands."""
    pass


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
        is_repl=True,
    )


@pytest.fixture
def ctx_with_agent(mock_pool: MockAgentPool, mock_session_manager: MockSessionManager) -> CommandContext:
    """Create a command context with a current agent."""
    mock_pool.add_agent("main")
    return CommandContext(
        pool=mock_pool,
        session_manager=mock_session_manager,
        current_agent_id="main",
        is_repl=True,
    )


@pytest.fixture
def whisper() -> WhisperMode:
    """Create a fresh WhisperMode instance."""
    return WhisperMode()


# -----------------------------------------------------------------------------
# cmd_agent Tests
# -----------------------------------------------------------------------------


class TestCmdAgentNoArgs:
    """Tests for /agent (no arguments) - show current agent status."""

    @pytest.mark.asyncio
    async def test_shows_status_for_current_agent(self, ctx_with_agent: CommandContext):
        """Shows detailed status when current agent exists."""
        output = await cmd_agent(ctx_with_agent, args=None)

        assert output.result == CommandResult.SUCCESS
        assert "main" in output.message
        assert output.data["agent_id"] == "main"
        assert "tokens" in output.data

    @pytest.mark.asyncio
    async def test_empty_args_shows_status(self, ctx_with_agent: CommandContext):
        """Empty string args also shows status."""
        output = await cmd_agent(ctx_with_agent, args="")

        assert output.result == CommandResult.SUCCESS
        assert output.data["agent_id"] == "main"

    @pytest.mark.asyncio
    async def test_whitespace_args_shows_status(self, ctx_with_agent: CommandContext):
        """Whitespace-only args shows status."""
        output = await cmd_agent(ctx_with_agent, args="   ")

        assert output.result == CommandResult.SUCCESS
        assert output.data["agent_id"] == "main"

    @pytest.mark.asyncio
    async def test_error_when_no_current_agent(self, ctx: CommandContext):
        """Returns error when no current agent."""
        output = await cmd_agent(ctx, args=None)

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message


class TestCmdAgentSwitch:
    """Tests for /agent <name> - switch to existing agent."""

    @pytest.mark.asyncio
    async def test_switch_to_existing_agent(
        self, ctx: CommandContext, mock_pool: MockAgentPool
    ):
        """Returns SWITCH_AGENT for existing agent."""
        mock_pool.add_agent("worker-1")

        output = await cmd_agent(ctx, args="worker-1")

        assert output.result == CommandResult.SWITCH_AGENT
        assert output.new_agent_id == "worker-1"

    @pytest.mark.asyncio
    async def test_prompt_create_for_nonexistent_agent(self, ctx: CommandContext):
        """Returns prompt to create when agent doesn't exist."""
        output = await cmd_agent(ctx, args="nonexistent")

        assert output.result == CommandResult.ERROR
        assert "doesn't exist" in output.message
        assert "Create it" in output.message
        assert output.data["action"] == "prompt_create"
        assert output.data["agent_name"] == "nonexistent"


class TestCmdAgentCreate:
    """Tests for /agent <name> --permission - create with permission."""

    @pytest.mark.asyncio
    async def test_prompt_create_with_yolo(self, ctx: CommandContext):
        """Parses --yolo flag for creation prompt."""
        output = await cmd_agent(ctx, args="new-agent --yolo")

        assert output.result == CommandResult.ERROR
        assert output.data["action"] == "prompt_create"
        assert output.data["permission"] == "yolo"

    @pytest.mark.asyncio
    async def test_prompt_create_with_trusted(self, ctx: CommandContext):
        """Parses --trusted flag for creation prompt."""
        output = await cmd_agent(ctx, args="new-agent --trusted")

        assert output.data["permission"] == "trusted"

    @pytest.mark.asyncio
    async def test_prompt_create_with_sandboxed(self, ctx: CommandContext):
        """Parses --sandboxed flag for creation prompt."""
        output = await cmd_agent(ctx, args="new-agent --sandboxed")

        assert output.data["permission"] == "sandboxed"

    @pytest.mark.asyncio
    async def test_prompt_create_with_short_flags(self, ctx: CommandContext):
        """Parses short permission flags (-y, -t, -s)."""
        output_y = await cmd_agent(ctx, args="new -y")
        output_t = await cmd_agent(ctx, args="new -t")
        output_s = await cmd_agent(ctx, args="new -s")

        # Short flags -y, -t, -s are recognized
        assert output_y.data["permission"] == "yolo"
        assert output_t.data["permission"] == "trusted"
        assert output_s.data["permission"] == "sandboxed"

    @pytest.mark.asyncio
    async def test_rejects_unknown_flags(self, ctx: CommandContext):
        """Unknown flags produce helpful error message."""
        output = await cmd_agent(ctx, args="new --unknown")

        assert output.result == CommandResult.ERROR
        assert "Unknown flag" in output.message
        assert "--unknown" in output.message

    @pytest.mark.asyncio
    async def test_rejects_unexpected_positional(self, ctx: CommandContext):
        """Unexpected positional arguments produce helpful error."""
        output = await cmd_agent(ctx, args="new extraarg")

        assert output.result == CommandResult.ERROR
        assert "Unexpected argument" in output.message

    @pytest.mark.asyncio
    async def test_model_flag_requires_value(self, ctx: CommandContext):
        """--model flag without value produces error."""
        output = await cmd_agent(ctx, args="new --model")

        assert output.result == CommandResult.ERROR
        assert "requires a value" in output.message

    @pytest.mark.asyncio
    async def test_default_permission_is_trusted(self, ctx: CommandContext):
        """Default permission level is trusted."""
        output = await cmd_agent(ctx, args="new-agent")

        assert output.data["permission"] == "trusted"


# -----------------------------------------------------------------------------
# cmd_whisper Tests
# -----------------------------------------------------------------------------


class TestCmdWhisper:
    """Tests for /whisper <target> - enter whisper mode."""

    @pytest.mark.asyncio
    async def test_enter_whisper_mode(
        self, ctx_with_agent: CommandContext, mock_pool: MockAgentPool, whisper: WhisperMode
    ):
        """Successfully enters whisper mode for existing agent."""
        mock_pool.add_agent("worker-1")

        output = await cmd_whisper(ctx_with_agent, whisper, "worker-1")

        assert output.result == CommandResult.ENTER_WHISPER
        assert output.whisper_target == "worker-1"
        assert whisper.is_active() is True
        assert whisper.get_target() == "worker-1"

    @pytest.mark.asyncio
    async def test_whisper_stores_original_agent(
        self, ctx_with_agent: CommandContext, mock_pool: MockAgentPool, whisper: WhisperMode
    ):
        """Whisper mode stores original agent for return."""
        mock_pool.add_agent("worker-1")

        await cmd_whisper(ctx_with_agent, whisper, "worker-1")

        assert whisper.original_agent_id == "main"

    @pytest.mark.asyncio
    async def test_whisper_nonexistent_prompts_create(
        self, ctx_with_agent: CommandContext, whisper: WhisperMode
    ):
        """Prompts to create when target doesn't exist."""
        output = await cmd_whisper(ctx_with_agent, whisper, "nonexistent")

        assert output.result == CommandResult.ERROR
        assert "doesn't exist" in output.message
        assert output.data["action"] == "prompt_create_whisper"

    @pytest.mark.asyncio
    async def test_whisper_already_whispering_to_same(
        self, ctx_with_agent: CommandContext, mock_pool: MockAgentPool, whisper: WhisperMode
    ):
        """Error when already whispering to same target."""
        mock_pool.add_agent("worker-1")
        whisper.enter("worker-1", "main")

        output = await cmd_whisper(ctx_with_agent, whisper, "worker-1")

        assert output.result == CommandResult.ERROR
        assert "Already whispering" in output.message

    @pytest.mark.asyncio
    async def test_whisper_no_current_agent(
        self, ctx: CommandContext, mock_pool: MockAgentPool, whisper: WhisperMode
    ):
        """Error when no current agent to return to."""
        mock_pool.add_agent("worker-1")

        output = await cmd_whisper(ctx, whisper, "worker-1")

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message


# -----------------------------------------------------------------------------
# cmd_over Tests
# -----------------------------------------------------------------------------


class TestCmdOver:
    """Tests for /over - exit whisper mode."""

    @pytest.mark.asyncio
    async def test_exit_whisper_mode(self, ctx: CommandContext, whisper: WhisperMode):
        """Successfully exits whisper mode."""
        whisper.enter("worker-1", "main")

        output = await cmd_over(ctx, whisper)

        assert output.result == CommandResult.SWITCH_AGENT
        assert output.new_agent_id == "main"
        assert whisper.is_active() is False

    @pytest.mark.asyncio
    async def test_over_clears_whisper_state(self, ctx: CommandContext, whisper: WhisperMode):
        """Over command clears all whisper state."""
        whisper.enter("worker-1", "main")

        await cmd_over(ctx, whisper)

        assert whisper.target_agent_id is None
        assert whisper.original_agent_id is None

    @pytest.mark.asyncio
    async def test_over_when_not_whispering(self, ctx: CommandContext, whisper: WhisperMode):
        """Error when not in whisper mode."""
        output = await cmd_over(ctx, whisper)

        assert output.result == CommandResult.ERROR
        assert "Not in whisper mode" in output.message


# -----------------------------------------------------------------------------
# cmd_cwd Tests
# -----------------------------------------------------------------------------


class TestCmdCwd:
    """Tests for /cwd [path] - working directory management.

    Note: cmd_cwd now uses per-agent cwd stored in ServiceContainer,
    not the global os.chdir(). This ensures agent isolation.
    """

    @pytest.mark.asyncio
    async def test_show_current_directory(
        self, ctx_with_agent: CommandContext, mock_pool: MockAgentPool
    ):
        """Shows current working directory with no args."""
        output = await cmd_cwd(ctx_with_agent, path=None)

        assert output.result == CommandResult.SUCCESS
        # Returns agent's cwd (defaults to Path.cwd() if not set)
        assert "Working directory" in output.message

    @pytest.mark.asyncio
    async def test_change_directory(
        self, ctx_with_agent: CommandContext, mock_pool: MockAgentPool, tmp_path: Path
    ):
        """Changes to valid directory (per-agent, not global)."""
        output = await cmd_cwd(ctx_with_agent, path=str(tmp_path))

        assert output.result == CommandResult.SUCCESS
        assert "Changed" in output.message
        # Verify agent's cwd was updated
        agent = mock_pool.get("main")
        assert agent.services.get("cwd") == tmp_path

    @pytest.mark.asyncio
    async def test_change_directory_nonexistent(self, ctx_with_agent: CommandContext):
        """Error for nonexistent directory."""
        output = await cmd_cwd(ctx_with_agent, path="/nonexistent/path/xyz")

        assert output.result == CommandResult.ERROR
        assert "does not exist" in output.message

    @pytest.mark.asyncio
    async def test_change_directory_to_file(
        self, ctx_with_agent: CommandContext, tmp_path: Path
    ):
        """Error when path is a file, not directory."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("test")

        output = await cmd_cwd(ctx_with_agent, path=str(file_path))

        assert output.result == CommandResult.ERROR
        assert "Not a directory" in output.message

    @pytest.mark.asyncio
    async def test_change_directory_expands_home(
        self, ctx_with_agent: CommandContext, tmp_path: Path, monkeypatch
    ):
        """Expands ~ to home directory."""
        # Create a dir in tmp and pretend it's home
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setenv("HOME", str(home_dir))

        output = await cmd_cwd(ctx_with_agent, path="~")

        assert output.result == CommandResult.SUCCESS

    @pytest.mark.asyncio
    async def test_no_current_agent(self, ctx: CommandContext):
        """Error when no current agent."""
        output = await cmd_cwd(ctx, path=None)

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message


# -----------------------------------------------------------------------------
# cmd_permissions Tests
# -----------------------------------------------------------------------------


class TestCmdPermissions:
    """Tests for /permissions command - permission management."""

    @pytest.mark.asyncio
    async def test_show_current_no_permissions_set(self, ctx_with_agent: CommandContext):
        """Shows 'unrestricted' when no permissions are set."""
        output = await cmd_permissions(ctx_with_agent, args=None)

        assert output.result == CommandResult.SUCCESS
        assert "unrestricted" in output.message.lower()
        assert output.data["preset"] is None

    @pytest.mark.asyncio
    async def test_show_current_with_permissions(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Shows current permission preset when permissions are set."""
        from nexus3.core.permissions import resolve_preset

        agent = mock_pool.add_agent("main")
        perms = resolve_preset("trusted")
        agent.services.register("permissions", perms)

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_permissions(ctx, args=None)

        assert output.result == CommandResult.SUCCESS
        assert "trusted" in output.message.lower()
        assert output.data["preset"] == "trusted"

    @pytest.mark.asyncio
    async def test_change_to_yolo_preset(self, ctx_with_agent: CommandContext):
        """Changes permission preset to yolo."""
        output = await cmd_permissions(ctx_with_agent, args="yolo")

        assert output.result == CommandResult.SUCCESS
        assert output.data["preset"] == "yolo"

    @pytest.mark.asyncio
    async def test_change_to_trusted_preset(self, ctx_with_agent: CommandContext):
        """Changes permission preset to trusted."""
        output = await cmd_permissions(ctx_with_agent, args="trusted")

        assert output.result == CommandResult.SUCCESS
        assert output.data["preset"] == "trusted"

    @pytest.mark.asyncio
    async def test_change_to_sandboxed_preset(self, ctx_with_agent: CommandContext):
        """Changes permission preset to sandboxed."""
        output = await cmd_permissions(ctx_with_agent, args="sandboxed")

        assert output.result == CommandResult.SUCCESS
        assert output.data["preset"] == "sandboxed"

    @pytest.mark.asyncio
    async def test_change_to_worker_preset_backwards_compat(self, ctx_with_agent: CommandContext):
        """Worker preset maps to sandboxed for backwards compatibility."""
        output = await cmd_permissions(ctx_with_agent, args="worker")

        assert output.result == CommandResult.SUCCESS
        # Worker is mapped to sandboxed for backwards compatibility
        assert output.data["preset"] == "sandboxed"

    @pytest.mark.asyncio
    async def test_invalid_preset_name(self, ctx_with_agent: CommandContext):
        """Error for invalid preset name."""
        output = await cmd_permissions(ctx_with_agent, args="invalid")

        assert output.result == CommandResult.ERROR
        assert "Unknown preset" in output.message

    @pytest.mark.asyncio
    async def test_preset_case_insensitive(self, ctx_with_agent: CommandContext):
        """Preset name is case-insensitive."""
        output = await cmd_permissions(ctx_with_agent, args="YOLO")

        assert output.result == CommandResult.SUCCESS
        assert output.data["preset"] == "yolo"

    @pytest.mark.asyncio
    async def test_no_current_agent(self, ctx: CommandContext):
        """Error when no current agent."""
        output = await cmd_permissions(ctx, args=None)

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message

    @pytest.mark.asyncio
    async def test_disable_tool(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Can disable a tool."""
        from nexus3.core.permissions import resolve_preset

        agent = mock_pool.add_agent("main")
        perms = resolve_preset("trusted")
        agent.services.register("permissions", perms)

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_permissions(ctx, args="--disable write_file")

        assert output.result == CommandResult.SUCCESS
        assert "Disabled" in output.message
        assert output.data["tool"] == "write_file"
        assert output.data["enabled"] is False

    @pytest.mark.asyncio
    async def test_enable_tool(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Can enable a tool."""
        from nexus3.core.permissions import ToolPermission, resolve_preset

        agent = mock_pool.add_agent("main")
        perms = resolve_preset("trusted")
        perms.tool_permissions["write_file"] = ToolPermission(enabled=False)
        agent.services.register("permissions", perms)

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_permissions(ctx, args="--enable write_file")

        assert output.result == CommandResult.SUCCESS
        assert "Enabled" in output.message
        assert output.data["tool"] == "write_file"
        assert output.data["enabled"] is True

    @pytest.mark.asyncio
    async def test_list_tools(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Can list tool permissions."""
        from nexus3.core.permissions import ToolPermission, resolve_preset

        agent = mock_pool.add_agent("main")
        perms = resolve_preset("sandboxed")  # Has some disabled tools by default
        agent.services.register("permissions", perms)

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_permissions(ctx, args="--list-tools")

        assert output.result == CommandResult.SUCCESS
        assert "Tool permissions:" in output.message

    @pytest.mark.asyncio
    async def test_list_tools_no_permissions(self, ctx_with_agent: CommandContext):
        """List tools shows 'no restrictions' when permissions not set."""
        output = await cmd_permissions(ctx_with_agent, args="--list-tools")

        assert output.result == CommandResult.SUCCESS
        assert "no restrictions" in output.message.lower()

    @pytest.mark.asyncio
    async def test_disable_tool_no_permissions(self, ctx_with_agent: CommandContext):
        """Error when trying to disable tool without permissions set."""
        output = await cmd_permissions(ctx_with_agent, args="--disable write_file")

        assert output.result == CommandResult.ERROR
        assert "no policy set" in output.message.lower()

    @pytest.mark.asyncio
    async def test_unknown_flag(self, ctx_with_agent: CommandContext):
        """Error for unknown flag."""
        output = await cmd_permissions(ctx_with_agent, args="--unknown")

        assert output.result == CommandResult.ERROR
        assert "Unknown flag" in output.message


# -----------------------------------------------------------------------------
# cmd_prompt Tests
# -----------------------------------------------------------------------------


class TestCmdPrompt:
    """Tests for /prompt [file] - system prompt management."""

    @pytest.mark.asyncio
    async def test_show_current_prompt(self, ctx_with_agent: CommandContext):
        """Shows current system prompt info with no args."""
        output = await cmd_prompt(ctx_with_agent, file=None)

        assert output.result == CommandResult.SUCCESS
        assert "System prompt" in output.message
        assert output.data["length"] > 0

    @pytest.mark.asyncio
    async def test_show_prompt_preview(self, ctx_with_agent: CommandContext):
        """Shows preview of system prompt."""
        output = await cmd_prompt(ctx_with_agent, file=None)

        # Should have preview in output
        assert "preview" in output.data

    @pytest.mark.asyncio
    async def test_load_prompt_from_file(
        self, ctx_with_agent: CommandContext, mock_pool: MockAgentPool, tmp_path: Path
    ):
        """Loads system prompt from file."""
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("New system prompt content")

        output = await cmd_prompt(ctx_with_agent, file=str(prompt_file))

        assert output.result == CommandResult.SUCCESS
        assert "loaded from" in output.message.lower()
        # Verify context was updated
        agent = mock_pool.get("main")
        agent.context.set_system_prompt.assert_called_once_with("New system prompt content")

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self, ctx_with_agent: CommandContext):
        """Error for nonexistent file."""
        output = await cmd_prompt(ctx_with_agent, file="/nonexistent/file.md")

        assert output.result == CommandResult.ERROR
        assert "not found" in output.message.lower()

    @pytest.mark.asyncio
    async def test_load_directory_as_file(self, ctx_with_agent: CommandContext, tmp_path: Path):
        """Error when path is directory, not file."""
        output = await cmd_prompt(ctx_with_agent, file=str(tmp_path))

        assert output.result == CommandResult.ERROR
        assert "Not a file" in output.message

    @pytest.mark.asyncio
    async def test_no_current_agent(self, ctx: CommandContext):
        """Error when no current agent."""
        output = await cmd_prompt(ctx, file=None)

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message


# -----------------------------------------------------------------------------
# cmd_help Tests
# -----------------------------------------------------------------------------


class TestCmdHelp:
    """Tests for /help - display help text."""

    @pytest.mark.asyncio
    async def test_returns_help_text(self, ctx: CommandContext):
        """Returns help text message."""
        output = await cmd_help(ctx)

        assert output.result == CommandResult.SUCCESS
        assert output.message == HELP_TEXT

    @pytest.mark.asyncio
    async def test_help_contains_command_sections(self, ctx: CommandContext):
        """Help text contains expected sections."""
        output = await cmd_help(ctx)

        assert "Agent Management" in output.message
        assert "Session Management" in output.message
        assert "REPL Control" in output.message

    @pytest.mark.asyncio
    async def test_help_contains_key_commands(self, ctx: CommandContext):
        """Help text documents key commands."""
        output = await cmd_help(ctx)

        assert "/agent" in output.message
        assert "/whisper" in output.message
        assert "/over" in output.message
        assert "/quit" in output.message


# -----------------------------------------------------------------------------
# cmd_clear Tests
# -----------------------------------------------------------------------------


class TestCmdClear:
    """Tests for /clear - clear display."""

    @pytest.mark.asyncio
    async def test_returns_clear_action(self, ctx: CommandContext):
        """Returns success with clear action."""
        output = await cmd_clear(ctx)

        assert output.result == CommandResult.SUCCESS
        assert output.data["action"] == "clear"

    @pytest.mark.asyncio
    async def test_no_message(self, ctx: CommandContext):
        """Clear command has no message to display."""
        output = await cmd_clear(ctx)

        assert output.message is None


# -----------------------------------------------------------------------------
# cmd_quit Tests
# -----------------------------------------------------------------------------


class TestCmdQuit:
    """Tests for /quit - exit REPL."""

    @pytest.mark.asyncio
    async def test_returns_quit_result(self, ctx: CommandContext):
        """Returns QUIT result."""
        output = await cmd_quit(ctx)

        assert output.result == CommandResult.QUIT


# -----------------------------------------------------------------------------
# cmd_compact Tests
# -----------------------------------------------------------------------------


class TestCmdCompact:
    """Tests for /compact - force context compaction."""

    @pytest.mark.asyncio
    async def test_no_current_agent(self, ctx: CommandContext):
        """Error when no current agent."""
        ctx_no_agent = CommandContext(
            pool=ctx.pool,
            session_manager=ctx.session_manager,
            current_agent_id=None,
            is_repl=True,
        )
        output = await cmd_compact(ctx_no_agent)

        assert output.result == CommandResult.ERROR
        assert "No current agent" in output.message

    @pytest.mark.asyncio
    async def test_agent_not_found(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Error when agent not found in pool."""
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="nonexistent",
            is_repl=True,
        )
        output = await cmd_compact(ctx)

        assert output.result == CommandResult.ERROR
        assert "Agent not found" in output.message

    @pytest.mark.asyncio
    async def test_no_context(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Error when session has no context."""
        agent = mock_pool.add_agent("main")
        agent.session.context = None

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_compact(ctx)

        assert output.result == CommandResult.ERROR
        assert "No context available" in output.message

    @pytest.mark.asyncio
    async def test_insufficient_messages(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Returns not enough messages when context has fewer than 2 messages."""
        agent = mock_pool.add_agent("main")
        agent.session.context = MagicMock()
        agent.session.context.messages = [MagicMock()]  # Only 1 message

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_compact(ctx)

        assert output.result == CommandResult.SUCCESS
        assert "Not enough context" in output.message
        assert output.data["compacted"] is False
        assert output.data["reason"] == "insufficient_messages"

    @pytest.mark.asyncio
    async def test_nothing_to_compact(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Returns nothing to compact when compact returns None."""
        agent = mock_pool.add_agent("main")
        agent.session.context = MagicMock()
        agent.session.context.messages = [MagicMock(), MagicMock()]
        agent.session.compact = MagicMock(return_value=None)

        # Make compact an async mock
        async def mock_compact(force: bool = False):
            return None
        agent.session.compact = mock_compact

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_compact(ctx)

        assert output.result == CommandResult.SUCCESS
        assert "Nothing to compact" in output.message
        assert output.data["compacted"] is False

    @pytest.mark.asyncio
    async def test_successful_compaction(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Returns success with token counts when compaction succeeds."""
        agent = mock_pool.add_agent("main")
        agent.session.context = MagicMock()
        agent.session.context.messages = [MagicMock(), MagicMock(), MagicMock()]

        # Mock CompactionResult
        mock_result = MagicMock()
        mock_result.original_token_count = 5000
        mock_result.new_token_count = 1000

        async def mock_compact(force: bool = False):
            return mock_result
        agent.session.compact = mock_compact

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_compact(ctx)

        assert output.result == CommandResult.SUCCESS
        assert "5000" in output.message
        assert "1000" in output.message
        assert output.data["compacted"] is True
        assert output.data["original_tokens"] == 5000
        assert output.data["new_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_compaction_error(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Returns error when compaction raises exception."""
        agent = mock_pool.add_agent("main")
        agent.session.context = MagicMock()
        agent.session.context.messages = [MagicMock(), MagicMock()]

        async def mock_compact(force: bool = False):
            raise RuntimeError("Test error")
        agent.session.compact = mock_compact

        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        output = await cmd_compact(ctx)

        assert output.result == CommandResult.ERROR
        assert "Compaction failed" in output.message
        assert "Test error" in output.message


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


class TestWhisperWorkflow:
    """Tests for complete whisper mode workflows."""

    @pytest.mark.asyncio
    async def test_complete_whisper_workflow(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Complete workflow: enter whisper, exit with /over."""
        mock_pool.add_agent("main")
        mock_pool.add_agent("worker")
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="main",
            is_repl=True,
        )
        whisper = WhisperMode()

        # Enter whisper
        output1 = await cmd_whisper(ctx, whisper, "worker")
        assert output1.result == CommandResult.ENTER_WHISPER
        assert whisper.get_prompt_prefix() == "worker> "

        # Exit whisper
        output2 = await cmd_over(ctx, whisper)
        assert output2.result == CommandResult.SWITCH_AGENT
        assert output2.new_agent_id == "main"
        assert whisper.get_prompt_prefix() == ""


class TestAgentSwitchWorkflow:
    """Tests for agent switching workflows."""

    @pytest.mark.asyncio
    async def test_switch_between_agents(
        self, mock_pool: MockAgentPool, mock_session_manager: MockSessionManager
    ):
        """Can switch between multiple agents."""
        mock_pool.add_agent("agent-1")
        mock_pool.add_agent("agent-2")
        ctx = CommandContext(
            pool=mock_pool,
            session_manager=mock_session_manager,
            current_agent_id="agent-1",
            is_repl=True,
        )

        # Switch to agent-2
        output = await cmd_agent(ctx, args="agent-2")
        assert output.result == CommandResult.SWITCH_AGENT
        assert output.new_agent_id == "agent-2"
