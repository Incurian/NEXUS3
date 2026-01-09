"""Unit tests for nexus3.cli.whisper module.

Tests for WhisperMode state management class.
"""

import pytest

from nexus3.cli.whisper import WhisperMode


class TestWhisperModeInitialization:
    """Tests for WhisperMode initialization."""

    def test_default_state_inactive(self):
        """WhisperMode starts inactive by default."""
        whisper = WhisperMode()
        assert whisper.active is False
        assert whisper.target_agent_id is None
        assert whisper.original_agent_id is None

    def test_is_active_returns_false_initially(self):
        """is_active() returns False initially."""
        whisper = WhisperMode()
        assert whisper.is_active() is False

    def test_get_target_returns_none_initially(self):
        """get_target() returns None when not active."""
        whisper = WhisperMode()
        assert whisper.get_target() is None

    def test_get_prompt_prefix_returns_empty_initially(self):
        """get_prompt_prefix() returns empty string when not active."""
        whisper = WhisperMode()
        assert whisper.get_prompt_prefix() == ""


class TestWhisperModeEnter:
    """Tests for entering whisper mode."""

    def test_enter_sets_active(self):
        """enter() sets active to True."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        assert whisper.active is True

    def test_enter_sets_target_agent_id(self):
        """enter() sets target_agent_id."""
        whisper = WhisperMode()
        whisper.enter("worker-1", "main")
        assert whisper.target_agent_id == "worker-1"

    def test_enter_sets_original_agent_id(self):
        """enter() sets original_agent_id."""
        whisper = WhisperMode()
        whisper.enter("worker-1", "main")
        assert whisper.original_agent_id == "main"

    def test_is_active_returns_true_after_enter(self):
        """is_active() returns True after enter()."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        assert whisper.is_active() is True

    def test_get_target_returns_target_after_enter(self):
        """get_target() returns target agent ID after enter()."""
        whisper = WhisperMode()
        whisper.enter("worker-1", "main")
        assert whisper.get_target() == "worker-1"

    def test_get_prompt_prefix_returns_formatted_after_enter(self):
        """get_prompt_prefix() returns 'target> ' after enter()."""
        whisper = WhisperMode()
        whisper.enter("worker-1", "main")
        assert whisper.get_prompt_prefix() == "worker-1> "

    def test_enter_overwrites_previous_state(self):
        """enter() overwrites previous whisper state."""
        whisper = WhisperMode()
        whisper.enter("first", "original")
        whisper.enter("second", "first")
        assert whisper.target_agent_id == "second"
        assert whisper.original_agent_id == "first"


class TestWhisperModeExit:
    """Tests for exiting whisper mode."""

    def test_exit_sets_inactive(self):
        """exit() sets active to False."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        whisper.exit()
        assert whisper.active is False

    def test_exit_clears_target_agent_id(self):
        """exit() clears target_agent_id to None."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        whisper.exit()
        assert whisper.target_agent_id is None

    def test_exit_clears_original_agent_id(self):
        """exit() clears original_agent_id to None."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        whisper.exit()
        assert whisper.original_agent_id is None

    def test_exit_returns_original_agent_id(self):
        """exit() returns the original agent ID."""
        whisper = WhisperMode()
        whisper.enter("target", "main")
        result = whisper.exit()
        assert result == "main"

    def test_exit_when_not_active_returns_none(self):
        """exit() returns None when not in whisper mode."""
        whisper = WhisperMode()
        result = whisper.exit()
        assert result is None

    def test_is_active_returns_false_after_exit(self):
        """is_active() returns False after exit()."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        whisper.exit()
        assert whisper.is_active() is False

    def test_get_target_returns_none_after_exit(self):
        """get_target() returns None after exit()."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        whisper.exit()
        assert whisper.get_target() is None

    def test_get_prompt_prefix_returns_empty_after_exit(self):
        """get_prompt_prefix() returns empty string after exit()."""
        whisper = WhisperMode()
        whisper.enter("target", "current")
        whisper.exit()
        assert whisper.get_prompt_prefix() == ""


class TestWhisperModeMultipleTransitions:
    """Tests for multiple enter/exit transitions."""

    def test_enter_exit_enter_works(self):
        """Can enter whisper mode again after exiting."""
        whisper = WhisperMode()

        # First whisper
        whisper.enter("agent-1", "main")
        assert whisper.is_active() is True
        assert whisper.get_target() == "agent-1"

        # Exit
        original = whisper.exit()
        assert original == "main"
        assert whisper.is_active() is False

        # Second whisper to different target
        whisper.enter("agent-2", "main")
        assert whisper.is_active() is True
        assert whisper.get_target() == "agent-2"

    def test_double_exit_is_safe(self):
        """Calling exit() twice is safe."""
        whisper = WhisperMode()
        whisper.enter("target", "current")

        result1 = whisper.exit()
        result2 = whisper.exit()

        assert result1 == "current"
        assert result2 is None  # Second exit returns None


class TestWhisperModeRepr:
    """Tests for WhisperMode string representation."""

    def test_repr_inactive(self):
        """repr shows inactive state."""
        whisper = WhisperMode()
        assert repr(whisper) == "WhisperMode(active=False)"

    def test_repr_active(self):
        """repr shows active state with target and original."""
        whisper = WhisperMode()
        whisper.enter("worker-1", "main")
        result = repr(whisper)

        assert "active=True" in result
        assert "target='worker-1'" in result
        assert "original='main'" in result


class TestWhisperModeEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_enter_with_same_target_and_current(self):
        """Can enter whisper mode with same target and current."""
        whisper = WhisperMode()
        whisper.enter("agent", "agent")
        assert whisper.target_agent_id == "agent"
        assert whisper.original_agent_id == "agent"

    def test_enter_with_temp_agent_names(self):
        """Works with temp agent names (starting with .)."""
        whisper = WhisperMode()
        whisper.enter(".1", ".2")
        assert whisper.get_target() == ".1"
        assert whisper.get_prompt_prefix() == ".1> "

    def test_enter_with_empty_string_target(self):
        """Works with empty string target (edge case)."""
        whisper = WhisperMode()
        whisper.enter("", "main")
        assert whisper.target_agent_id == ""
        # Empty target is falsy, so produces empty prefix
        # (this is an edge case that shouldn't happen in practice)
        assert whisper.get_prompt_prefix() == ""

    def test_prompt_prefix_with_special_characters(self):
        """Prompt prefix handles special characters in agent names."""
        whisper = WhisperMode()
        whisper.enter("agent-1_test", "main")
        assert whisper.get_prompt_prefix() == "agent-1_test> "


class TestWhisperModeDataclass:
    """Tests for WhisperMode as a dataclass."""

    def test_can_create_with_explicit_values(self):
        """WhisperMode can be created with explicit values."""
        whisper = WhisperMode(
            active=True,
            target_agent_id="target",
            original_agent_id="original",
        )
        assert whisper.active is True
        assert whisper.target_agent_id == "target"
        assert whisper.original_agent_id == "original"

    def test_equality(self):
        """Two WhisperMode instances with same values are equal."""
        w1 = WhisperMode(active=True, target_agent_id="t", original_agent_id="o")
        w2 = WhisperMode(active=True, target_agent_id="t", original_agent_id="o")
        assert w1 == w2

    def test_inequality(self):
        """WhisperMode instances with different values are not equal."""
        w1 = WhisperMode(active=True, target_agent_id="t1", original_agent_id="o")
        w2 = WhisperMode(active=True, target_agent_id="t2", original_agent_id="o")
        assert w1 != w2
