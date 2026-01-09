"""Unit tests for nexus3.cli.lobby module."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from nexus3.cli.lobby import (
    LobbyChoice,
    LobbyResult,
    format_time_ago,
    show_lobby,
    show_session_list,
)
from nexus3.session.persistence import SavedSession
from nexus3.session.session_manager import SessionManager


class TestLobbyChoice:
    """Tests for LobbyChoice enum."""

    def test_choice_values(self):
        """Enum has expected values."""
        assert LobbyChoice.RESUME.value == 1
        assert LobbyChoice.FRESH.value == 2
        assert LobbyChoice.SELECT.value == 3
        assert LobbyChoice.QUIT.value == 4


class TestLobbyResult:
    """Tests for LobbyResult dataclass."""

    def test_result_with_defaults(self):
        """Create result with default values."""
        result = LobbyResult(choice=LobbyChoice.FRESH)
        assert result.choice == LobbyChoice.FRESH
        assert result.session_name is None
        assert result.template_path is None

    def test_result_with_session_name(self):
        """Create result with session name."""
        result = LobbyResult(choice=LobbyChoice.RESUME, session_name="my-project")
        assert result.choice == LobbyChoice.RESUME
        assert result.session_name == "my-project"

    def test_result_with_template_path(self):
        """Create result with template path."""
        result = LobbyResult(
            choice=LobbyChoice.FRESH,
            template_path=Path("/path/to/prompt.md"),
        )
        assert result.template_path == Path("/path/to/prompt.md")


class TestFormatTimeAgo:
    """Tests for format_time_ago function."""

    def test_just_now(self):
        """Recent times show 'just now'."""
        now = datetime.now()
        assert format_time_ago(now) == "just now"

        # 30 seconds ago
        thirty_sec_ago = now - timedelta(seconds=30)
        assert format_time_ago(thirty_sec_ago) == "just now"

    def test_minutes_ago(self):
        """Times within an hour show minutes."""
        now = datetime.now()

        one_min = now - timedelta(minutes=1)
        assert format_time_ago(one_min) == "1m ago"

        five_min = now - timedelta(minutes=5)
        assert format_time_ago(five_min) == "5m ago"

        fifty_nine_min = now - timedelta(minutes=59)
        assert format_time_ago(fifty_nine_min) == "59m ago"

    def test_hours_ago(self):
        """Times within a day show hours."""
        now = datetime.now()

        one_hour = now - timedelta(hours=1)
        assert format_time_ago(one_hour) == "1h ago"

        two_hours = now - timedelta(hours=2)
        assert format_time_ago(two_hours) == "2h ago"

        twenty_three_hours = now - timedelta(hours=23)
        assert format_time_ago(twenty_three_hours) == "23h ago"

    def test_days_ago(self):
        """Times within a month show days."""
        now = datetime.now()

        one_day = now - timedelta(days=1)
        assert format_time_ago(one_day) == "1d ago"

        seven_days = now - timedelta(days=7)
        assert format_time_ago(seven_days) == "7d ago"

        twenty_nine_days = now - timedelta(days=29)
        assert format_time_ago(twenty_nine_days) == "29d ago"

    def test_months_ago(self):
        """Times within a year show months."""
        now = datetime.now()

        thirty_days = now - timedelta(days=30)
        assert format_time_ago(thirty_days) == "1mo ago"

        sixty_days = now - timedelta(days=60)
        assert format_time_ago(sixty_days) == "2mo ago"

        eleven_months = now - timedelta(days=330)
        assert format_time_ago(eleven_months) == "11mo ago"

    def test_years_ago(self):
        """Times over a year show years."""
        now = datetime.now()

        one_year = now - timedelta(days=365)
        assert format_time_ago(one_year) == "1y ago"

        two_years = now - timedelta(days=730)
        assert format_time_ago(two_years) == "2y ago"

    def test_future_time(self):
        """Future times show 'just now'."""
        future = datetime.now() + timedelta(hours=1)
        assert format_time_ago(future) == "just now"


class TestShowLobby:
    """Tests for show_lobby function."""

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
            created_at=datetime.now() - timedelta(hours=2),
            modified_at=datetime.now() - timedelta(hours=1),
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            system_prompt="Test prompt",
            system_prompt_path=None,
            working_directory="/tmp",
            permission_level="trusted",
            token_usage={"total": 50},
            provenance="user",
        )

    @pytest.fixture
    def mock_console(self):
        """Create a mock console for testing."""
        console = MagicMock(spec=Console)
        return console

    @pytest.mark.asyncio
    async def test_empty_state_fresh_only(self, manager, mock_console):
        """With no sessions, only 'Fresh session' is shown."""
        mock_console.input.return_value = "1"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.FRESH
        assert result.session_name is None

    @pytest.mark.asyncio
    async def test_quit_from_lobby(self, manager, mock_console):
        """User can quit from lobby."""
        mock_console.input.return_value = "q"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.QUIT

    @pytest.mark.asyncio
    async def test_quit_with_exit(self, manager, mock_console):
        """User can quit with 'exit'."""
        mock_console.input.return_value = "exit"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.QUIT

    @pytest.mark.asyncio
    async def test_resume_last_session(self, manager, mock_console, sample_session):
        """User can resume last session."""
        manager.save_last_session(sample_session, "my-project")
        mock_console.input.return_value = "1"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.RESUME
        assert result.session_name == "my-project"

    @pytest.mark.asyncio
    async def test_resume_temp_session(self, manager, mock_console, sample_session):
        """Resume option shows temp session correctly."""
        manager.save_last_session(sample_session, ".1")
        mock_console.input.return_value = "1"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.RESUME
        assert result.session_name == ".1"
        # Verify temp session is displayed with "temp" prefix
        # (check that print was called with appropriate content)
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("temp" in call for call in calls)

    @pytest.mark.asyncio
    async def test_fresh_with_last_session(self, manager, mock_console, sample_session):
        """User can choose fresh session when last session exists."""
        manager.save_last_session(sample_session, "my-project")
        mock_console.input.return_value = "2"  # Fresh is option 2 when resume exists

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.FRESH

    @pytest.mark.asyncio
    async def test_invalid_input_retry(self, manager, mock_console):
        """Invalid input prompts for retry."""
        mock_console.input.side_effect = ["invalid", "abc", "1"]

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.FRESH
        # Should have printed invalid input message
        assert mock_console.print.call_count >= 1

    @pytest.mark.asyncio
    async def test_out_of_range_input(self, manager, mock_console):
        """Out of range input prompts for retry."""
        mock_console.input.side_effect = ["5", "99", "1"]

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.FRESH

    @pytest.mark.asyncio
    async def test_eof_quits(self, manager, mock_console):
        """EOFError exits gracefully."""
        mock_console.input.side_effect = EOFError()

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.QUIT

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_quits(self, manager, mock_console):
        """KeyboardInterrupt exits gracefully."""
        mock_console.input.side_effect = KeyboardInterrupt()

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.QUIT

    @pytest.mark.asyncio
    async def test_choose_from_saved_option(self, manager, mock_console, sample_session):
        """'Choose from saved' option appears when sessions exist."""
        manager.save_session(sample_session)
        manager.save_last_session(sample_session, "my-project")

        # First choose "3" (Choose from saved), then select session "1"
        mock_console.input.side_effect = ["3", "1"]

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.SELECT
        assert result.session_name == "test-session"

    @pytest.mark.asyncio
    async def test_all_options_displayed(self, manager, mock_console, sample_session):
        """All three options displayed when conditions met."""
        manager.save_session(sample_session)
        manager.save_last_session(sample_session, "my-project")

        mock_console.input.return_value = "1"

        await show_lobby(manager, mock_console)

        # Check that all options were printed
        calls = [str(call) for call in mock_console.print.call_args_list]
        output = " ".join(calls)
        assert "Resume" in output
        assert "Fresh" in output
        assert "saved" in output.lower()


class TestShowSessionList:
    """Tests for show_session_list function."""

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
    def mock_console(self):
        """Create a mock console for testing."""
        console = MagicMock(spec=Console)
        return console

    @pytest.mark.asyncio
    async def test_empty_session_list(self, manager, mock_console):
        """Empty session list returns None."""
        result = await show_session_list(manager, mock_console)

        assert result is None
        # Should print "No saved sessions" message
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("No saved sessions" in call for call in calls)

    @pytest.mark.asyncio
    async def test_select_session(self, manager, mock_console):
        """User can select a session from list."""
        session = SavedSession(
            agent_id="my-session",
            created_at=datetime.now() - timedelta(days=1),
            modified_at=datetime.now() - timedelta(hours=2),
            messages=[{"role": "user", "content": "Test"}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        manager.save_session(session)

        mock_console.input.return_value = "1"

        result = await show_session_list(manager, mock_console)

        assert result == "my-session"

    @pytest.mark.asyncio
    async def test_back_returns_none(self, manager, mock_console):
        """User can go back with 'b'."""
        session = SavedSession(
            agent_id="test",
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
        manager.save_session(session)

        mock_console.input.return_value = "b"

        result = await show_session_list(manager, mock_console)

        assert result is None

    @pytest.mark.asyncio
    async def test_back_with_full_word(self, manager, mock_console):
        """User can go back with 'back'."""
        session = SavedSession(
            agent_id="test",
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
        manager.save_session(session)

        mock_console.input.return_value = "back"

        result = await show_session_list(manager, mock_console)

        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_sessions_sorted(self, manager, mock_console):
        """Sessions are sorted by modified time (newest first)."""
        session1 = SavedSession(
            agent_id="older",
            created_at=datetime.now() - timedelta(days=5),
            modified_at=datetime.now() - timedelta(days=3),
            messages=[],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        session2 = SavedSession(
            agent_id="newer",
            created_at=datetime.now() - timedelta(days=1),
            modified_at=datetime.now() - timedelta(hours=1),
            messages=[{"role": "user", "content": "Recent"}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        manager.save_session(session1)
        manager.save_session(session2)

        mock_console.input.return_value = "1"

        result = await show_session_list(manager, mock_console)

        # First in list should be "newer" (more recently modified)
        assert result == "newer"

    @pytest.mark.asyncio
    async def test_invalid_input_retry(self, manager, mock_console):
        """Invalid input prompts for retry."""
        session = SavedSession(
            agent_id="test",
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
        manager.save_session(session)

        mock_console.input.side_effect = ["invalid", "99", "1"]

        result = await show_session_list(manager, mock_console)

        assert result == "test"

    @pytest.mark.asyncio
    async def test_eof_returns_none(self, manager, mock_console):
        """EOFError returns None."""
        session = SavedSession(
            agent_id="test",
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
        manager.save_session(session)

        mock_console.input.side_effect = EOFError()

        result = await show_session_list(manager, mock_console)

        assert result is None

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_returns_none(self, manager, mock_console):
        """KeyboardInterrupt returns None."""
        session = SavedSession(
            agent_id="test",
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
        manager.save_session(session)

        mock_console.input.side_effect = KeyboardInterrupt()

        result = await show_session_list(manager, mock_console)

        assert result is None

    @pytest.mark.asyncio
    async def test_session_details_displayed(self, manager, mock_console):
        """Session details are displayed correctly."""
        session = SavedSession(
            agent_id="detailed-session",
            created_at=datetime.now() - timedelta(hours=5),
            modified_at=datetime.now() - timedelta(hours=2),
            messages=[
                {"role": "user", "content": "1"},
                {"role": "assistant", "content": "2"},
                {"role": "user", "content": "3"},
            ],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        manager.save_session(session)

        mock_console.input.return_value = "1"

        await show_session_list(manager, mock_console)

        # Check that session name and details were printed
        calls = [str(call) for call in mock_console.print.call_args_list]
        output = " ".join(calls)
        assert "detailed-session" in output
        assert "3 messages" in output
        assert "2h ago" in output


class TestLobbyIntegration:
    """Integration tests for lobby flow."""

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
    def mock_console(self):
        """Create a mock console for testing."""
        console = MagicMock(spec=Console)
        return console

    @pytest.mark.asyncio
    async def test_full_flow_resume(self, manager, mock_console):
        """Complete flow: resume last session."""
        session = SavedSession(
            agent_id="project-x",
            created_at=datetime.now() - timedelta(days=1),
            modified_at=datetime.now() - timedelta(hours=1),
            messages=[{"role": "user", "content": "Working on X"}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/projects/x",
            permission_level="trusted",
            token_usage={"total": 100},
            provenance="user",
        )
        manager.save_last_session(session, "project-x")

        mock_console.input.return_value = "1"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.RESUME
        assert result.session_name == "project-x"

    @pytest.mark.asyncio
    async def test_full_flow_fresh(self, manager, mock_console):
        """Complete flow: start fresh session."""
        # No saved sessions, so fresh is option 1
        mock_console.input.return_value = "1"

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.FRESH
        assert result.session_name is None

    @pytest.mark.asyncio
    async def test_full_flow_select_from_saved(self, manager, mock_console):
        """Complete flow: select from saved sessions."""
        session1 = SavedSession(
            agent_id="analysis",
            created_at=datetime.now() - timedelta(days=2),
            modified_at=datetime.now() - timedelta(days=1),
            messages=[{"role": "user", "content": "Analyzing..."}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        session2 = SavedSession(
            agent_id="debugging",
            created_at=datetime.now() - timedelta(hours=5),
            modified_at=datetime.now() - timedelta(hours=2),
            messages=[{"role": "user", "content": "Debug this..."}],
            system_prompt="",
            system_prompt_path=None,
            working_directory="/",
            permission_level="yolo",
            token_usage={},
            provenance="user",
        )
        manager.save_session(session1)
        manager.save_session(session2)

        # No last session, so:
        # 1 = Fresh
        # 2 = Choose from saved
        # Then select session 2 (analysis, older)
        mock_console.input.side_effect = ["2", "2"]

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.SELECT
        assert result.session_name == "analysis"

    @pytest.mark.asyncio
    async def test_cancel_from_session_list_returns_to_lobby(
        self, manager, mock_console
    ):
        """Cancelling from session list shows lobby again."""
        session = SavedSession(
            agent_id="test",
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
        manager.save_session(session)

        # Choose "Choose from saved" (2), then back (b), then Fresh (1)
        mock_console.input.side_effect = ["2", "b", "1"]

        result = await show_lobby(manager, mock_console)

        assert result.choice == LobbyChoice.FRESH
