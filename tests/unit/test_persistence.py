"""Unit tests for nexus3.session.persistence and session_manager modules."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from nexus3.core.types import Message, Role, ToolCall
from nexus3.session.persistence import (
    SavedSession,
    SessionSummary,
    deserialize_message,
    deserialize_messages,
    deserialize_tool_call,
    serialize_message,
    serialize_messages,
    serialize_session,
    serialize_tool_call,
)
from nexus3.session.session_manager import (
    SessionManager,
    SessionManagerError,
    SessionNotFoundError,
)


class TestToolCallSerialization:
    """Tests for ToolCall serialization."""

    def test_serialize_tool_call(self):
        """Serialize ToolCall to dict."""
        tc = ToolCall(
            id="call_123",
            name="read_file",
            arguments={"path": "/tmp/test.txt"},
        )
        data = serialize_tool_call(tc)

        assert data == {
            "id": "call_123",
            "name": "read_file",
            "arguments": {"path": "/tmp/test.txt"},
        }

    def test_deserialize_tool_call(self):
        """Deserialize dict to ToolCall."""
        data = {
            "id": "call_456",
            "name": "write_file",
            "arguments": {"path": "/tmp/out.txt", "content": "hello"},
        }
        tc = deserialize_tool_call(data)

        assert tc.id == "call_456"
        assert tc.name == "write_file"
        assert tc.arguments == {"path": "/tmp/out.txt", "content": "hello"}

    def test_roundtrip_tool_call(self):
        """ToolCall survives serialize/deserialize roundtrip."""
        original = ToolCall(
            id="tc_001",
            name="complex_tool",
            arguments={"nested": {"key": "value"}, "list": [1, 2, 3]},
        )
        data = serialize_tool_call(original)
        restored = deserialize_tool_call(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.arguments == original.arguments

    def test_deserialize_tool_call_empty_arguments(self):
        """Handle missing arguments field."""
        data = {"id": "tc_002", "name": "no_args"}
        tc = deserialize_tool_call(data)

        assert tc.arguments == {}


class TestMessageSerialization:
    """Tests for Message serialization."""

    def test_serialize_user_message(self):
        """Serialize simple user message."""
        msg = Message(role=Role.USER, content="Hello, world!")
        data = serialize_message(msg)

        assert data == {
            "role": "user",
            "content": "Hello, world!",
        }

    def test_serialize_assistant_message(self):
        """Serialize assistant message without tool calls."""
        msg = Message(role=Role.ASSISTANT, content="How can I help?")
        data = serialize_message(msg)

        assert data == {
            "role": "assistant",
            "content": "How can I help?",
        }

    def test_serialize_message_with_tool_calls(self):
        """Serialize assistant message with tool calls."""
        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/x"})
        msg = Message(role=Role.ASSISTANT, content="Reading file...", tool_calls=(tc,))
        data = serialize_message(msg)

        assert data["role"] == "assistant"
        assert data["content"] == "Reading file..."
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["name"] == "read_file"

    def test_serialize_tool_result_message(self):
        """Serialize tool result message."""
        msg = Message(
            role=Role.TOOL,
            content="File contents here",
            tool_call_id="call_123",
        )
        data = serialize_message(msg)

        assert data["role"] == "tool"
        assert data["content"] == "File contents here"
        assert data["tool_call_id"] == "call_123"

    def test_serialize_system_message(self):
        """Serialize system message."""
        msg = Message(role=Role.SYSTEM, content="You are a helpful assistant.")
        data = serialize_message(msg)

        assert data == {
            "role": "system",
            "content": "You are a helpful assistant.",
        }

    def test_deserialize_user_message(self):
        """Deserialize simple user message."""
        data = {"role": "user", "content": "Hello!"}
        msg = deserialize_message(data)

        assert msg.role == Role.USER
        assert msg.content == "Hello!"
        assert msg.tool_calls == ()
        assert msg.tool_call_id is None

    def test_deserialize_message_with_tool_calls(self):
        """Deserialize message with tool calls."""
        data = {
            "role": "assistant",
            "content": "Let me check that.",
            "tool_calls": [
                {"id": "tc_1", "name": "read_file", "arguments": {"path": "/x"}},
                {"id": "tc_2", "name": "write_file", "arguments": {"path": "/y"}},
            ],
        }
        msg = deserialize_message(data)

        assert msg.role == Role.ASSISTANT
        assert len(msg.tool_calls) == 2
        assert msg.tool_calls[0].name == "read_file"
        assert msg.tool_calls[1].name == "write_file"

    def test_deserialize_tool_result(self):
        """Deserialize tool result message."""
        data = {
            "role": "tool",
            "content": "Success!",
            "tool_call_id": "tc_abc",
        }
        msg = deserialize_message(data)

        assert msg.role == Role.TOOL
        assert msg.content == "Success!"
        assert msg.tool_call_id == "tc_abc"

    def test_roundtrip_complex_message(self):
        """Complex message survives roundtrip."""
        tc1 = ToolCall(id="tc_1", name="tool_a", arguments={"a": 1})
        tc2 = ToolCall(id="tc_2", name="tool_b", arguments={"b": [2, 3]})
        original = Message(
            role=Role.ASSISTANT,
            content="Processing...",
            tool_calls=(tc1, tc2),
        )
        data = serialize_message(original)
        restored = deserialize_message(data)

        assert restored.role == original.role
        assert restored.content == original.content
        assert len(restored.tool_calls) == 2
        assert restored.tool_calls[0].id == tc1.id
        assert restored.tool_calls[1].arguments == tc2.arguments


class TestSerializeMessages:
    """Tests for batch message serialization."""

    def test_serialize_messages_list(self):
        """Serialize list of messages."""
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi there!"),
            Message(role=Role.USER, content="How are you?"),
        ]
        data = serialize_messages(messages)

        assert len(data) == 3
        assert data[0]["content"] == "Hello"
        assert data[1]["content"] == "Hi there!"
        assert data[2]["content"] == "How are you?"

    def test_deserialize_messages_list(self):
        """Deserialize list of messages."""
        data = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        messages = deserialize_messages(data)

        assert len(messages) == 3
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER
        assert messages[2].content == "4"

    def test_empty_list(self):
        """Handle empty message lists."""
        assert serialize_messages([]) == []
        assert deserialize_messages([]) == []


class TestSavedSession:
    """Tests for SavedSession dataclass."""

    def test_saved_session_creation(self):
        """Create SavedSession with all fields."""
        now = datetime.now()
        session = SavedSession(
            agent_id="test-agent",
            created_at=now,
            modified_at=now,
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="Be helpful.",
            system_prompt_path="/path/to/prompt.md",
            working_directory="/home/user/project",
            permission_level="trusted",
            token_usage={"total": 100, "messages": 50},
            provenance="user",
        )

        assert session.agent_id == "test-agent"
        assert session.permission_level == "trusted"
        assert session.schema_version == 1

    def test_to_json(self):
        """SavedSession serializes to JSON."""
        now = datetime(2025, 1, 15, 12, 0, 0)
        session = SavedSession(
            agent_id="json-test",
            created_at=now,
            modified_at=now,
            messages=[],
            system_prompt="Test prompt",
            system_prompt_path=None,
            working_directory="/tmp",
            permission_level="sandboxed",
            token_usage={},
            provenance="parent-agent",
        )
        json_str = session.to_json()
        data = json.loads(json_str)

        assert data["agent_id"] == "json-test"
        assert data["permission_level"] == "sandboxed"
        assert data["provenance"] == "parent-agent"
        assert "2025-01-15" in data["created_at"]

    def test_from_json(self):
        """SavedSession deserializes from JSON."""
        json_str = """{
            "agent_id": "from-json",
            "created_at": "2025-01-10T10:00:00",
            "modified_at": "2025-01-10T11:00:00",
            "messages": [{"role": "user", "content": "Test"}],
            "system_prompt": "Prompt here",
            "system_prompt_path": null,
            "working_directory": "/work",
            "permission_level": "yolo",
            "token_usage": {"total": 50},
            "provenance": "user",
            "schema_version": 1
        }"""
        session = SavedSession.from_json(json_str)

        assert session.agent_id == "from-json"
        assert session.permission_level == "yolo"
        assert len(session.messages) == 1
        assert session.created_at.year == 2025

    def test_roundtrip(self):
        """SavedSession survives JSON roundtrip."""
        original = SavedSession(
            agent_id="roundtrip-test",
            created_at=datetime(2025, 6, 1),
            modified_at=datetime(2025, 6, 2),
            messages=[
                {"role": "user", "content": "Question?"},
                {"role": "assistant", "content": "Answer!"},
            ],
            system_prompt="Detailed prompt...",
            system_prompt_path="/prompts/test.md",
            working_directory="/projects/nexus",
            permission_level="trusted",
            token_usage={"system": 20, "messages": 80, "total": 100},
            provenance="spawner-agent",
        )
        json_str = original.to_json()
        restored = SavedSession.from_json(json_str)

        assert restored.agent_id == original.agent_id
        assert restored.created_at == original.created_at
        assert restored.messages == original.messages
        assert restored.token_usage == original.token_usage


class TestSerializeSession:
    """Tests for serialize_session helper."""

    def test_serialize_session(self):
        """Create SavedSession from runtime state."""
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi!"),
        ]
        saved = serialize_session(
            agent_id="my-agent",
            messages=messages,
            system_prompt="Be helpful",
            system_prompt_path="/NEXUS.md",
            working_directory="/home/user",
            permission_level="yolo",
            token_usage={"total": 100},
            provenance="user",
        )

        assert saved.agent_id == "my-agent"
        assert len(saved.messages) == 2
        assert saved.messages[0]["content"] == "Hello"
        assert saved.permission_level == "yolo"

    def test_serialize_session_with_tool_calls(self):
        """Serialize session with tool call messages."""
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "/x"})
        messages = [
            Message(role=Role.USER, content="Read the file"),
            Message(role=Role.ASSISTANT, content="", tool_calls=(tc,)),
            Message(role=Role.TOOL, content="File contents", tool_call_id="tc_1"),
            Message(role=Role.ASSISTANT, content="Here's the content."),
        ]
        saved = serialize_session(
            agent_id="tool-agent",
            messages=messages,
            system_prompt="",
            system_prompt_path=None,
            working_directory=".",
            permission_level="sandboxed",
            token_usage={},
        )

        assert len(saved.messages) == 4
        assert saved.messages[1]["tool_calls"][0]["name"] == "read_file"
        assert saved.messages[2]["tool_call_id"] == "tc_1"


class TestSessionManager:
    """Tests for SessionManager class."""

    @pytest.fixture
    def temp_nexus_dir(self):
        """Create a temporary nexus directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_nexus_dir):
        """Create SessionManager with temp directory."""
        return SessionManager(nexus_dir=temp_nexus_dir)

    @pytest.fixture
    def sample_session(self):
        """Create a sample SavedSession."""
        return SavedSession(
            agent_id="test-session",
            created_at=datetime(2025, 1, 1),
            modified_at=datetime(2025, 1, 2),
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="Test prompt",
            system_prompt_path=None,
            working_directory="/tmp",
            permission_level="trusted",
            token_usage={"total": 50},
            provenance="user",
        )

    def test_save_and_load_session(self, manager, sample_session):
        """Save and load a session."""
        path = manager.save_session(sample_session)
        assert path.exists()

        loaded = manager.load_session("test-session")
        assert loaded.agent_id == sample_session.agent_id
        assert loaded.messages == sample_session.messages

    def test_session_exists(self, manager, sample_session):
        """Check session existence."""
        assert not manager.session_exists("test-session")
        manager.save_session(sample_session)
        assert manager.session_exists("test-session")

    def test_delete_session(self, manager, sample_session):
        """Delete a session."""
        manager.save_session(sample_session)
        assert manager.session_exists("test-session")

        result = manager.delete_session("test-session")
        assert result is True
        assert not manager.session_exists("test-session")

    def test_delete_nonexistent_session(self, manager):
        """Delete returns False for missing session."""
        result = manager.delete_session("nonexistent")
        assert result is False

    def test_load_nonexistent_session(self, manager):
        """Load raises error for missing session."""
        with pytest.raises(SessionNotFoundError) as exc_info:
            manager.load_session("does-not-exist")
        assert exc_info.value.name == "does-not-exist"

    def test_list_sessions(self, manager):
        """List all saved sessions."""
        # Initially empty
        sessions = manager.list_sessions()
        assert sessions == []

        # Add sessions
        session1 = SavedSession(
            agent_id="alpha",
            created_at=datetime(2025, 1, 1),
            modified_at=datetime(2025, 1, 1),
            messages=[{"role": "user", "content": "A"}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        session2 = SavedSession(
            agent_id="beta",
            created_at=datetime(2025, 1, 2),
            modified_at=datetime(2025, 1, 3),  # Newer
            messages=[{"role": "user", "content": "B"}, {"role": "assistant", "content": "C"}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )

        manager.save_session(session1)
        manager.save_session(session2)

        sessions = manager.list_sessions()
        assert len(sessions) == 2
        # Sorted by modified_at descending
        assert sessions[0].name == "beta"
        assert sessions[0].message_count == 2
        assert sessions[1].name == "alpha"
        assert sessions[1].message_count == 1

    def test_save_and_load_last_session(self, manager, sample_session):
        """Save and load last session."""
        # No last session initially
        result = manager.load_last_session()
        assert result is None

        # Save last session
        manager.save_last_session(sample_session, ".1")

        # Load it back
        result = manager.load_last_session()
        assert result is not None
        loaded, name = result
        assert name == ".1"
        assert loaded.agent_id == sample_session.agent_id

    def test_get_last_session_name(self, manager, sample_session):
        """Get last session name without loading data."""
        assert manager.get_last_session_name() is None

        manager.save_last_session(sample_session, "my-project")
        assert manager.get_last_session_name() == "my-project"

    def test_clear_last_session(self, manager, sample_session):
        """Clear last session data."""
        manager.save_last_session(sample_session, "temp")
        assert manager.load_last_session() is not None

        manager.clear_last_session()
        assert manager.load_last_session() is None
        assert manager.get_last_session_name() is None

    def test_rename_session(self, manager, sample_session):
        """Rename a session."""
        manager.save_session(sample_session)

        new_path = manager.rename_session("test-session", "renamed-session")
        assert new_path.exists()
        assert not manager.session_exists("test-session")
        assert manager.session_exists("renamed-session")

        loaded = manager.load_session("renamed-session")
        assert loaded.agent_id == "renamed-session"

    def test_rename_nonexistent_session(self, manager):
        """Rename raises error for missing session."""
        with pytest.raises(SessionNotFoundError):
            manager.rename_session("missing", "new-name")

    def test_rename_to_existing_name(self, manager, sample_session):
        """Rename raises error if destination exists."""
        manager.save_session(sample_session)

        other_session = SavedSession(
            agent_id="other",
            created_at=datetime.now(),
            modified_at=datetime.now(),
            messages=[],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        manager.save_session(other_session)

        with pytest.raises(SessionManagerError) as exc_info:
            manager.rename_session("test-session", "other")
        assert "already exists" in str(exc_info.value)

    def test_clone_session(self, manager, sample_session):
        """Clone a session."""
        manager.save_session(sample_session)

        clone_path = manager.clone_session("test-session", "test-clone")
        assert clone_path.exists()
        assert manager.session_exists("test-session")  # Original still exists
        assert manager.session_exists("test-clone")

        original = manager.load_session("test-session")
        cloned = manager.load_session("test-clone")
        assert cloned.agent_id == "test-clone"
        assert cloned.messages == original.messages
        assert cloned.system_prompt == original.system_prompt

    def test_clone_nonexistent_session(self, manager):
        """Clone raises error for missing source."""
        with pytest.raises(SessionNotFoundError):
            manager.clone_session("missing", "clone")

    def test_clone_to_existing_name(self, manager, sample_session):
        """Clone raises error if destination exists."""
        manager.save_session(sample_session)

        with pytest.raises(SessionManagerError) as exc_info:
            manager.clone_session("test-session", "test-session")
        assert "already exists" in str(exc_info.value)

    def test_directories_created_on_demand(self, temp_nexus_dir):
        """Directories are created when needed."""
        # Don't pre-create directories
        manager = SessionManager(nexus_dir=temp_nexus_dir / "subdir")
        assert not manager.sessions_dir.exists()

        # Listing creates directories
        manager.list_sessions()
        assert manager.sessions_dir.exists()


class TestSessionSummary:
    """Tests for SessionSummary dataclass."""

    def test_session_summary_fields(self):
        """SessionSummary has expected fields."""
        summary = SessionSummary(
            name="my-session",
            modified_at=datetime(2025, 1, 15),
            message_count=42,
            agent_id="my-session",
        )

        assert summary.name == "my-session"
        assert summary.message_count == 42
        assert summary.modified_at.day == 15
