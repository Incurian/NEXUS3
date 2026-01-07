"""Unit tests for the NEXUS3 display system."""

from asyncio import CancelledError
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from rich.text import Text

from nexus3.core.cancel import CancellationToken
from nexus3.display.manager import DisplayManager
from nexus3.display.segments import ActivitySegment, CancelHintSegment, TaskCountSegment
from nexus3.display.summary import SummaryBar
from nexus3.display.theme import Activity, Status, Theme, load_theme

# =============================================================================
# Theme Tests
# =============================================================================


class TestStatusEnum:
    """Tests for the Status enum."""

    def test_status_has_active(self) -> None:
        """Status enum should have ACTIVE value."""
        assert Status.ACTIVE.value == "active"

    def test_status_has_pending(self) -> None:
        """Status enum should have PENDING value."""
        assert Status.PENDING.value == "pending"

    def test_status_has_complete(self) -> None:
        """Status enum should have COMPLETE value."""
        assert Status.COMPLETE.value == "complete"

    def test_status_has_error(self) -> None:
        """Status enum should have ERROR value."""
        assert Status.ERROR.value == "error"

    def test_status_has_cancelled(self) -> None:
        """Status enum should have CANCELLED value."""
        assert Status.CANCELLED.value == "cancelled"

    def test_status_has_expected_count(self) -> None:
        """Status enum should have exactly 5 values."""
        assert len(Status) == 5


class TestActivityEnum:
    """Tests for the Activity enum."""

    def test_activity_has_idle(self) -> None:
        """Activity enum should have IDLE value."""
        assert Activity.IDLE.value == "idle"

    def test_activity_has_thinking(self) -> None:
        """Activity enum should have THINKING value."""
        assert Activity.THINKING.value == "thinking"

    def test_activity_has_responding(self) -> None:
        """Activity enum should have RESPONDING value."""
        assert Activity.RESPONDING.value == "responding"

    def test_activity_has_tool_calling(self) -> None:
        """Activity enum should have TOOL_CALLING value."""
        assert Activity.TOOL_CALLING.value == "tool_calling"

    def test_activity_has_expected_count(self) -> None:
        """Activity enum should have exactly 4 values."""
        assert len(Activity) == 4


class TestTheme:
    """Tests for the Theme class."""

    def test_theme_has_default_gumballs_for_all_status(self) -> None:
        """Theme should have gumballs for all Status values."""
        theme = Theme()
        for status in Status:
            assert status in theme.gumballs

    def test_gumball_returns_correct_value_for_active(self) -> None:
        """Theme.gumball() should return correct value for ACTIVE."""
        theme = Theme()
        assert theme.gumball(Status.ACTIVE) == "[cyan]●[/]"

    def test_gumball_returns_correct_value_for_pending(self) -> None:
        """Theme.gumball() should return correct value for PENDING."""
        theme = Theme()
        assert theme.gumball(Status.PENDING) == "[dim]○[/]"

    def test_gumball_returns_correct_value_for_complete(self) -> None:
        """Theme.gumball() should return correct value for COMPLETE."""
        theme = Theme()
        assert theme.gumball(Status.COMPLETE) == "[green]●[/]"

    def test_gumball_returns_correct_value_for_error(self) -> None:
        """Theme.gumball() should return correct value for ERROR."""
        theme = Theme()
        assert theme.gumball(Status.ERROR) == "[red]●[/]"

    def test_gumball_returns_correct_value_for_cancelled(self) -> None:
        """Theme.gumball() should return correct value for CANCELLED."""
        theme = Theme()
        assert theme.gumball(Status.CANCELLED) == "[yellow]●[/]"

    def test_theme_has_spinner_frames(self) -> None:
        """Theme should have spinner frames defined."""
        theme = Theme()
        assert len(theme.spinner_frames) > 0

    def test_theme_has_summary_separator(self) -> None:
        """Theme should have summary separator defined."""
        theme = Theme()
        assert theme.summary_separator == " | "


class TestLoadTheme:
    """Tests for the load_theme function."""

    def test_load_theme_returns_theme_instance(self) -> None:
        """load_theme() should return a Theme instance."""
        theme = load_theme()
        assert isinstance(theme, Theme)

    def test_load_theme_with_none_overrides(self) -> None:
        """load_theme() with None overrides returns default Theme."""
        theme = load_theme(None)
        assert isinstance(theme, Theme)

    def test_load_theme_with_empty_overrides(self) -> None:
        """load_theme() with empty dict returns Theme."""
        theme = load_theme({})
        assert isinstance(theme, Theme)


# =============================================================================
# Segment Tests
# =============================================================================


class TestActivitySegment:
    """Tests for the ActivitySegment class."""

    def test_visible_is_false_when_idle(self) -> None:
        """ActivitySegment.visible should be False when IDLE."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.IDLE
        assert segment.visible is False

    def test_visible_is_true_when_thinking(self) -> None:
        """ActivitySegment.visible should be True when THINKING."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.THINKING
        assert segment.visible is True

    def test_visible_is_true_when_responding(self) -> None:
        """ActivitySegment.visible should be True when RESPONDING."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.RESPONDING
        assert segment.visible is True

    def test_visible_is_true_when_tool_calling(self) -> None:
        """ActivitySegment.visible should be True when TOOL_CALLING."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.TOOL_CALLING
        assert segment.visible is True

    def test_render_returns_text_with_spinner(self) -> None:
        """ActivitySegment.render() should return Text with spinner."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.THINKING
        result = segment.render()
        assert isinstance(result, Text)
        text_str = str(result)
        # Should contain a spinner character from SPINNER_FRAMES
        assert any(c in text_str for c in ActivitySegment.SPINNER_FRAMES)

    def test_render_includes_activity_name(self) -> None:
        """ActivitySegment.render() should include activity name."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.RESPONDING
        result = segment.render()
        assert "responding" in str(result)

    def test_set_activity_changes_activity(self) -> None:
        """ActivitySegment.set_activity() should change the activity."""
        theme = Theme()
        segment = ActivitySegment(theme)
        assert segment.activity == Activity.IDLE
        segment.set_activity(Activity.THINKING)
        assert segment.activity == Activity.THINKING

    def test_set_activity_to_idle_resets_frame(self) -> None:
        """ActivitySegment.set_activity(IDLE) should reset spinner frame."""
        theme = Theme()
        segment = ActivitySegment(theme)
        segment.activity = Activity.THINKING
        segment.render()  # Increment frame
        segment.render()  # Increment frame again
        assert segment._frame > 0
        segment.set_activity(Activity.IDLE)
        assert segment._frame == 0


class TestTaskCountSegment:
    """Tests for the TaskCountSegment class."""

    def test_visible_is_false_when_all_counts_zero(self) -> None:
        """TaskCountSegment.visible should be False when all counts are 0."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        assert segment.visible is False

    def test_visible_is_true_when_active_nonzero(self) -> None:
        """TaskCountSegment.visible should be True when active > 0."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.active = 1
        assert segment.visible is True

    def test_visible_is_true_when_pending_nonzero(self) -> None:
        """TaskCountSegment.visible should be True when pending > 0."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.pending = 1
        assert segment.visible is True

    def test_visible_is_true_when_done_nonzero(self) -> None:
        """TaskCountSegment.visible should be True when done > 0."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.done = 1
        assert segment.visible is True

    def test_visible_is_true_when_failed_nonzero(self) -> None:
        """TaskCountSegment.visible should be True when failed > 0."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.failed = 1
        assert segment.visible is True

    def test_add_task_increments_pending(self) -> None:
        """TaskCountSegment.add_task() should increment pending."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        assert segment.pending == 0
        segment.add_task()
        assert segment.pending == 1
        segment.add_task()
        assert segment.pending == 2

    def test_start_task_moves_pending_to_active(self) -> None:
        """TaskCountSegment.start_task() should move pending to active."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.add_task()
        segment.add_task()
        assert segment.pending == 2
        assert segment.active == 0
        segment.start_task()
        assert segment.pending == 1
        assert segment.active == 1

    def test_start_task_increments_active_even_without_pending(self) -> None:
        """TaskCountSegment.start_task() should increment active even if no pending."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        assert segment.pending == 0
        segment.start_task()
        assert segment.active == 1
        assert segment.pending == 0  # Should not go negative

    def test_complete_task_success_increments_done(self) -> None:
        """TaskCountSegment.complete_task(success=True) increments done."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.start_task()
        segment.complete_task(success=True)
        assert segment.active == 0
        assert segment.done == 1
        assert segment.failed == 0

    def test_complete_task_failure_increments_failed(self) -> None:
        """TaskCountSegment.complete_task(success=False) increments failed."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.start_task()
        segment.complete_task(success=False)
        assert segment.active == 0
        assert segment.done == 0
        assert segment.failed == 1

    def test_render_shows_correct_counts(self) -> None:
        """TaskCountSegment.render() should show correct counts."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.active = 2
        segment.pending = 3
        segment.done = 5
        segment.failed = 1
        result = segment.render()
        text_str = str(result)
        assert "2 active" in text_str
        assert "3 pending" in text_str
        assert "5 done" in text_str
        assert "1 failed" in text_str

    def test_render_omits_zero_counts(self) -> None:
        """TaskCountSegment.render() should omit zero counts."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.active = 1
        # pending, done, failed all 0
        result = segment.render()
        text_str = str(result)
        assert "active" in text_str
        assert "pending" not in text_str
        assert "done" not in text_str
        assert "failed" not in text_str

    def test_reset_clears_all_counts(self) -> None:
        """TaskCountSegment.reset() should clear all counts."""
        theme = Theme()
        segment = TaskCountSegment(theme)
        segment.active = 1
        segment.pending = 2
        segment.done = 3
        segment.failed = 4
        segment.reset()
        assert segment.active == 0
        assert segment.pending == 0
        assert segment.done == 0
        assert segment.failed == 0


class TestCancelHintSegment:
    """Tests for the CancelHintSegment class."""

    def test_visible_is_false_by_default(self) -> None:
        """CancelHintSegment.visible should be False by default."""
        segment = CancelHintSegment()
        assert segment.visible is False

    def test_visible_controlled_by_show_attribute(self) -> None:
        """CancelHintSegment.visible should be controlled by show attribute."""
        segment = CancelHintSegment()
        assert segment.visible is False
        segment.show = True
        assert segment.visible is True
        segment.show = False
        assert segment.visible is False

    def test_render_returns_esc_cancel_text(self) -> None:
        """CancelHintSegment.render() should return 'ESC cancel' text."""
        segment = CancelHintSegment()
        result = segment.render()
        assert isinstance(result, Text)
        assert "ESC cancel" in str(result)


# =============================================================================
# CancellationToken Tests
# =============================================================================


class TestCancellationToken:
    """Tests for the CancellationToken class."""

    def test_is_cancelled_false_initially(self) -> None:
        """CancellationToken.is_cancelled should be False initially."""
        token = CancellationToken()
        assert token.is_cancelled is False

    def test_cancel_sets_is_cancelled_true(self) -> None:
        """CancellationToken.cancel() should set is_cancelled to True."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancel_is_idempotent(self) -> None:
        """CancellationToken.cancel() should be idempotent."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True
        token.cancel()  # Should not raise
        assert token.is_cancelled is True

    def test_raise_if_cancelled_does_nothing_when_not_cancelled(self) -> None:
        """raise_if_cancelled() should do nothing when not cancelled."""
        token = CancellationToken()
        # Should not raise
        token.raise_if_cancelled()

    def test_raise_if_cancelled_raises_when_cancelled(self) -> None:
        """raise_if_cancelled() should raise CancelledError when cancelled."""
        token = CancellationToken()
        token.cancel()
        with pytest.raises(CancelledError):
            token.raise_if_cancelled()

    def test_on_cancel_callback_called_when_cancelled(self) -> None:
        """on_cancel() callback should be called when cancelled."""
        token = CancellationToken()
        callback = MagicMock()
        token.on_cancel(callback)
        callback.assert_not_called()
        token.cancel()
        callback.assert_called_once()

    def test_on_cancel_callback_called_immediately_if_already_cancelled(self) -> None:
        """on_cancel() callback should be called immediately if already cancelled."""
        token = CancellationToken()
        token.cancel()
        callback = MagicMock()
        token.on_cancel(callback)
        callback.assert_called_once()

    def test_multiple_callbacks_all_called(self) -> None:
        """Multiple on_cancel() callbacks should all be called."""
        token = CancellationToken()
        callback1 = MagicMock()
        callback2 = MagicMock()
        token.on_cancel(callback1)
        token.on_cancel(callback2)
        token.cancel()
        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_callback_exception_does_not_prevent_cancellation(self) -> None:
        """Callback exception should not prevent cancellation."""
        token = CancellationToken()

        def raising_callback() -> None:
            raise RuntimeError("callback error")

        good_callback = MagicMock()
        token.on_cancel(raising_callback)
        token.on_cancel(good_callback)
        token.cancel()  # Should not raise
        assert token.is_cancelled is True
        good_callback.assert_called_once()

    def test_reset_clears_cancelled_state(self) -> None:
        """CancellationToken.reset() should clear cancelled state."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True
        token.reset()
        assert token.is_cancelled is False

    def test_reset_preserves_callbacks(self) -> None:
        """CancellationToken.reset() should keep callbacks."""
        token = CancellationToken()
        callback = MagicMock()
        token.on_cancel(callback)
        token.reset()
        # Callback should still be registered
        token.cancel()
        callback.assert_called_once()


# =============================================================================
# SummaryBar Tests
# =============================================================================


class TestSummaryBar:
    """Tests for the SummaryBar class."""

    def test_register_segment_adds_segment(self) -> None:
        """register_segment() should add segment to the bar."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        segment = CancelHintSegment()
        assert len(bar.segments) == 0
        bar.register_segment(segment)
        assert len(bar.segments) == 1
        assert segment in bar.segments

    def test_register_segment_at_position(self) -> None:
        """register_segment() should insert at specified position."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        seg1 = CancelHintSegment()
        seg2 = CancelHintSegment()
        seg3 = CancelHintSegment()
        bar.register_segment(seg1)
        bar.register_segment(seg2)
        bar.register_segment(seg3, position=1)
        assert bar.segments[0] is seg1
        assert bar.segments[1] is seg3
        assert bar.segments[2] is seg2

    def test_unregister_segment_removes_segment(self) -> None:
        """unregister_segment() should remove segment from the bar."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        segment = CancelHintSegment()
        bar.register_segment(segment)
        assert segment in bar.segments
        bar.unregister_segment(segment)
        assert segment not in bar.segments

    def test_unregister_segment_does_nothing_if_not_found(self) -> None:
        """unregister_segment() should do nothing if segment not in bar."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        segment = CancelHintSegment()
        # Should not raise
        bar.unregister_segment(segment)
        assert len(bar.segments) == 0

    def test_render_returns_empty_text_when_no_visible_segments(self) -> None:
        """_render() should return empty Text when no visible segments."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        # Add invisible segment
        segment = CancelHintSegment()
        segment.show = False
        bar.register_segment(segment)
        result = bar._render()
        assert isinstance(result, Text)
        assert str(result) == ""

    def test_render_returns_empty_text_when_no_segments(self) -> None:
        """_render() should return empty Text when no segments registered."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        result = bar._render()
        assert isinstance(result, Text)
        assert str(result) == ""

    def test_render_joins_visible_segments_with_separator(self) -> None:
        """_render() should join visible segments with separator."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)

        # Create two visible segments
        seg1 = CancelHintSegment()
        seg1.show = True
        seg2 = CancelHintSegment()
        seg2.show = True

        bar.register_segment(seg1)
        bar.register_segment(seg2)

        result = bar._render()
        text_str = str(result)
        # Both should be present with separator
        assert "ESC cancel" in text_str
        # The separator " | " should be used
        assert " | " in text_str or text_str.count("ESC cancel") == 2

    def test_render_skips_invisible_segments(self) -> None:
        """_render() should skip invisible segments."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)

        visible_seg = CancelHintSegment()
        visible_seg.show = True
        invisible_seg = ActivitySegment(theme)
        invisible_seg.activity = Activity.IDLE  # Makes it invisible

        bar.register_segment(visible_seg)
        bar.register_segment(invisible_seg)

        result = bar._render()
        text_str = str(result)
        # Only the cancel hint should be present
        assert "ESC cancel" in text_str
        # Activity segment should not contribute (no separator expected)
        assert " | " not in text_str

    def test_is_live_false_by_default(self) -> None:
        """SummaryBar.is_live should be False by default."""
        console = Console(force_terminal=False)
        theme = Theme()
        bar = SummaryBar(console, theme)
        assert bar.is_live is False


# =============================================================================
# DisplayManager Tests
# =============================================================================


class TestDisplayManager:
    """Tests for the DisplayManager class."""

    def test_creates_with_default_console_and_theme(self) -> None:
        """DisplayManager should create with default console and theme."""
        manager = DisplayManager()
        assert manager.console is not None
        assert isinstance(manager.theme, Theme)

    def test_creates_with_custom_console(self) -> None:
        """DisplayManager should accept custom console."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager.console is console

    def test_creates_with_custom_theme(self) -> None:
        """DisplayManager should accept custom theme."""
        theme = Theme()
        manager = DisplayManager(theme=theme)
        assert manager.theme is theme

    def test_is_cancelled_false_initially(self) -> None:
        """DisplayManager.is_cancelled should be False initially."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager.is_cancelled is False

    def test_cancel_sets_is_cancelled_true_when_token_exists(self) -> None:
        """DisplayManager.cancel() should set is_cancelled when token exists."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        # Manually set a cancel token (simulating live_session)
        manager._cancel_token = CancellationToken()
        assert manager.is_cancelled is False
        manager.cancel()
        assert manager.is_cancelled is True

    def test_cancel_does_nothing_when_no_token(self) -> None:
        """DisplayManager.cancel() should do nothing when no token."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        # Should not raise
        manager.cancel()
        assert manager.is_cancelled is False

    def test_set_activity_updates_activity_segment(self) -> None:
        """DisplayManager.set_activity() should update activity segment."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager._activity_segment.activity == Activity.IDLE
        manager.set_activity(Activity.THINKING)
        assert manager._activity_segment.activity == Activity.THINKING

    def test_set_activity_shows_cancel_hint_when_not_idle(self) -> None:
        """set_activity() should show cancel hint when activity is not IDLE."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager._cancel_hint.show is False
        manager.set_activity(Activity.THINKING)
        assert manager._cancel_hint.show is True

    def test_set_activity_hides_cancel_hint_when_idle(self) -> None:
        """set_activity() should hide cancel hint when activity is IDLE."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        manager.set_activity(Activity.THINKING)
        assert manager._cancel_hint.show is True
        manager.set_activity(Activity.IDLE)
        assert manager._cancel_hint.show is False

    def test_has_printer_component(self) -> None:
        """DisplayManager should have printer component."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager.printer is not None

    def test_has_summary_component(self) -> None:
        """DisplayManager should have summary component."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager.summary is not None

    def test_default_segments_registered(self) -> None:
        """DisplayManager should register default segments."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        # Should have activity, task, and cancel hint segments
        assert len(manager.summary.segments) == 3

    def test_cancel_token_none_initially(self) -> None:
        """DisplayManager.cancel_token should be None initially."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager.cancel_token is None

    def test_add_task_increments_task_count(self) -> None:
        """DisplayManager.add_task() should increment task count."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        assert manager._task_segment.pending == 0
        manager.add_task()
        assert manager._task_segment.pending == 1

    def test_start_task_updates_task_segment(self) -> None:
        """DisplayManager.start_task() should update task segment."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        manager.add_task()
        manager.start_task()
        assert manager._task_segment.active == 1
        assert manager._task_segment.pending == 0

    def test_complete_task_updates_task_segment(self) -> None:
        """DisplayManager.complete_task() should update task segment."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        manager.start_task()
        manager.complete_task(success=True)
        assert manager._task_segment.active == 0
        assert manager._task_segment.done == 1

    def test_reset_tasks_clears_task_segment(self) -> None:
        """DisplayManager.reset_tasks() should clear task segment."""
        console = Console(force_terminal=False)
        manager = DisplayManager(console=console)
        manager.add_task()
        manager.start_task()
        manager.complete_task()
        manager.reset_tasks()
        assert manager._task_segment.active == 0
        assert manager._task_segment.pending == 0
        assert manager._task_segment.done == 0
        assert manager._task_segment.failed == 0
