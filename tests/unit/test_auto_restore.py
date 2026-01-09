"""Unit tests for cross-session auto-restore functionality.

Tests for Phase 6.6: Cross-Session Auto-Restore.

When external requests target an agent that:
- Is NOT in the active AgentPool
- BUT EXISTS in saved sessions (SessionManager)

Then:
1. Auto-restore the session from disk
2. Create agent in pool with restored state
3. Process the request normally
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.types import Message, Role
from nexus3.rpc.pool import AgentPool, SharedComponents
from nexus3.session.persistence import SavedSession, serialize_message

# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------


def create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create SharedComponents with mocks for testing."""
    mock_config = MagicMock()
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


def create_saved_session(
    agent_id: str,
    messages: list[Message] | None = None,
    system_prompt: str = "You are a helpful assistant.",
) -> SavedSession:
    """Create a SavedSession for testing."""
    if messages is None:
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi there!"),
        ]

    serialized_messages = [serialize_message(msg) for msg in messages]

    return SavedSession(
        agent_id=agent_id,
        created_at=datetime.now(),
        modified_at=datetime.now(),
        messages=serialized_messages,
        system_prompt=system_prompt,
        system_prompt_path=None,
        working_directory="/tmp",
        permission_level="trusted",
        token_usage={"total": 100, "system": 50, "messages": 50},
        provenance="user",
    )


# -----------------------------------------------------------------------------
# AgentPool.restore_from_saved Tests
# -----------------------------------------------------------------------------


class TestRestoreFromSaved:
    """Tests for AgentPool.restore_from_saved method."""

    @pytest.mark.asyncio
    async def test_restore_creates_agent_with_correct_id(self, tmp_path):
        """restore_from_saved creates agent with saved session's ID."""
        shared = create_mock_shared_components(tmp_path)
        saved = create_saved_session("restored-agent")

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.restore_from_saved(saved)

            assert agent.agent_id == "restored-agent"
            assert "restored-agent" in pool
            assert len(pool) == 1

    @pytest.mark.asyncio
    async def test_restore_preserves_conversation_history(self, tmp_path):
        """restore_from_saved restores all messages from saved session."""
        shared = create_mock_shared_components(tmp_path)
        messages = [
            Message(role=Role.USER, content="First message"),
            Message(role=Role.ASSISTANT, content="First response"),
            Message(role=Role.USER, content="Second message"),
            Message(role=Role.ASSISTANT, content="Second response"),
        ]
        saved = create_saved_session("history-agent", messages=messages)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.restore_from_saved(saved)

            # Check message count matches
            assert len(agent.context.messages) == 4

            # Check content matches
            context_messages = agent.context.messages
            assert context_messages[0].content == "First message"
            assert context_messages[0].role == Role.USER
            assert context_messages[1].content == "First response"
            assert context_messages[1].role == Role.ASSISTANT
            assert context_messages[2].content == "Second message"
            assert context_messages[3].content == "Second response"

    @pytest.mark.asyncio
    async def test_restore_preserves_system_prompt(self, tmp_path):
        """restore_from_saved uses system prompt from saved session."""
        shared = create_mock_shared_components(tmp_path)
        custom_prompt = "You are a specialized assistant for testing."
        saved = create_saved_session("prompt-agent", system_prompt=custom_prompt)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.restore_from_saved(saved)

            assert agent.context.system_prompt == custom_prompt

    @pytest.mark.asyncio
    async def test_restore_preserves_created_at(self, tmp_path):
        """restore_from_saved preserves original creation timestamp."""
        shared = create_mock_shared_components(tmp_path)
        original_time = datetime(2024, 1, 15, 10, 30, 0)
        saved = create_saved_session("time-agent")
        saved.created_at = original_time

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.restore_from_saved(saved)

            assert agent.created_at == original_time

    @pytest.mark.asyncio
    async def test_restore_raises_on_duplicate_id(self, tmp_path):
        """restore_from_saved raises ValueError if agent ID already exists."""
        shared = create_mock_shared_components(tmp_path)
        saved = create_saved_session("duplicate-agent")

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            # Create an agent with the same ID first
            await pool.create(agent_id="duplicate-agent")

            # Attempting to restore with same ID should raise
            with pytest.raises(ValueError) as exc_info:
                await pool.restore_from_saved(saved)

            assert "duplicate-agent" in str(exc_info.value)
            assert "already exists" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_restore_registers_skills(self, tmp_path):
        """restore_from_saved sets up skill registry."""
        shared = create_mock_shared_components(tmp_path)
        saved = create_saved_session("skills-agent")

        with patch("nexus3.skill.builtin.register_builtin_skills") as mock_register:
            pool = AgentPool(shared)
            agent = await pool.restore_from_saved(saved)

            # Verify skills were registered
            mock_register.assert_called_once_with(agent.registry)

    @pytest.mark.asyncio
    async def test_restore_creates_dispatcher(self, tmp_path):
        """restore_from_saved creates a working dispatcher."""
        shared = create_mock_shared_components(tmp_path)
        saved = create_saved_session("dispatcher-agent")

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.restore_from_saved(saved)

            # Dispatcher should exist and have expected methods
            assert agent.dispatcher is not None
            assert hasattr(agent.dispatcher, "dispatch")
            assert hasattr(agent.dispatcher, "should_shutdown")


# -----------------------------------------------------------------------------
# Mock Session Manager for HTTP Tests
# -----------------------------------------------------------------------------


class MockSessionManager:
    """Mock SessionManager for testing auto-restore in HTTP server."""

    def __init__(self, sessions: dict[str, SavedSession] | None = None):
        self._sessions = sessions or {}

    def session_exists(self, name: str) -> bool:
        """Check if a session exists."""
        return name in self._sessions

    def load_session(self, name: str) -> SavedSession:
        """Load a session by name."""
        if name not in self._sessions:
            from nexus3.session.session_manager import SessionNotFoundError
            raise SessionNotFoundError(name)
        return self._sessions[name]

    def add_session(self, saved: SavedSession) -> None:
        """Add a session to the mock store."""
        self._sessions[saved.agent_id] = saved


# -----------------------------------------------------------------------------
# HTTP Server Auto-Restore Tests
# -----------------------------------------------------------------------------


class TestHttpAutoRestore:
    """Tests for auto-restore behavior in HTTP request handling."""

    @pytest.mark.asyncio
    async def test_auto_restore_not_triggered_for_active_agent(self, tmp_path):
        """Auto-restore is not triggered if agent is already active."""
        shared = create_mock_shared_components(tmp_path)
        saved = create_saved_session("active-agent")
        # SessionManager has the session, but agent is already in pool
        mock_session_manager = MockSessionManager({"active-agent": saved})

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            # Create agent directly (already active)
            await pool.create(agent_id="active-agent")

            # Agent is in pool, no restore needed
            agent = pool.get("active-agent")
            assert agent is not None
            # Messages should be empty since we created fresh, not restored
            assert len(agent.context.messages) == 0
            # Session manager has the saved session, but we didn't need it
            assert mock_session_manager.session_exists("active-agent")

    @pytest.mark.asyncio
    async def test_auto_restore_not_triggered_without_session_manager(self, tmp_path):
        """Without SessionManager, missing agents return None."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # No agent, no session manager = just None
            agent = pool.get("nonexistent")
            assert agent is None

    @pytest.mark.asyncio
    async def test_session_manager_integration(self, tmp_path):
        """SessionManager can detect and load saved sessions."""
        saved = create_saved_session("saved-agent")
        session_manager = MockSessionManager({"saved-agent": saved})

        # Session exists
        assert session_manager.session_exists("saved-agent")
        assert not session_manager.session_exists("unknown-agent")

        # Can load session
        loaded = session_manager.load_session("saved-agent")
        assert loaded.agent_id == "saved-agent"


# -----------------------------------------------------------------------------
# Integration Test: Full Auto-Restore Flow
# -----------------------------------------------------------------------------


class TestAutoRestoreIntegration:
    """Integration tests for the full auto-restore flow."""

    @pytest.mark.asyncio
    async def test_full_restore_flow(self, tmp_path):
        """Test complete flow: saved session -> restore -> active agent."""
        shared = create_mock_shared_components(tmp_path)

        # Create a "saved" session with conversation history
        messages = [
            Message(role=Role.USER, content="Remember this: the password is 42"),
            Message(role=Role.ASSISTANT, content="I'll remember that the password is 42."),
            Message(role=Role.USER, content="What's the password?"),
            Message(role=Role.ASSISTANT, content="The password is 42."),
        ]
        saved = create_saved_session(
            "memory-agent",
            messages=messages,
            system_prompt="You are an assistant with good memory.",
        )

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Initially no agent in pool
            assert "memory-agent" not in pool
            assert pool.get("memory-agent") is None

            # Restore from saved session
            agent = await pool.restore_from_saved(saved)

            # Now agent is in pool
            assert "memory-agent" in pool
            assert pool.get("memory-agent") is agent

            # Has full conversation history
            assert len(agent.context.messages) == 4
            assert "password is 42" in agent.context.messages[1].content

            # Has custom system prompt
            assert "good memory" in agent.context.system_prompt

            # Agent is fully functional
            assert agent.dispatcher is not None
            assert agent.session is not None
