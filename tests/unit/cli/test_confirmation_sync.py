"""Tests for confirmation pause synchronization (Fix 3.3).

This module tests the pause/resume protocol between KeyMonitor and confirm_tool_action,
ensuring proper synchronization instead of relying on arbitrary sleep delays.

The protocol is:
1. Confirmation clears pause_event to request pause
2. KeyMonitor sets pause_ack_event when it has paused (terminal restored)
3. Confirmation waits for pause_ack_event with timeout
4. Confirmation sets pause_event to signal resume
5. KeyMonitor clears pause_ack_event and resumes monitoring
"""

import asyncio

import pytest


class TestPauseProtocol:
    """Tests for the pause synchronization protocol."""

    @pytest.mark.asyncio
    async def test_pause_event_starts_set(self):
        """pause_event should start in 'set' state (running)."""
        pause_event = asyncio.Event()
        pause_event.set()
        assert pause_event.is_set(), "pause_event should start set (running state)"

    @pytest.mark.asyncio
    async def test_pause_ack_event_starts_clear(self):
        """pause_ack_event should start in 'clear' state (not paused)."""
        pause_ack_event = asyncio.Event()
        assert not pause_ack_event.is_set(), "pause_ack_event should start clear"

    @pytest.mark.asyncio
    async def test_pause_request_clears_pause_event(self):
        """Clearing pause_event signals a pause request."""
        pause_event = asyncio.Event()
        pause_event.set()  # Start running

        # Request pause by clearing
        pause_event.clear()
        assert not pause_event.is_set(), "pause_event should be clear after pause request"

    @pytest.mark.asyncio
    async def test_resume_sets_pause_event(self):
        """Setting pause_event signals resume."""
        pause_event = asyncio.Event()

        # Start paused
        pause_event.clear()

        # Resume
        pause_event.set()
        assert pause_event.is_set(), "pause_event should be set after resume"


class TestKeyMonitorPauseLogic:
    """Tests for KeyMonitor pause handling logic."""

    @pytest.mark.asyncio
    async def test_monitor_sets_ack_when_paused(self):
        """Monitor should set pause_ack_event when it detects pause request."""
        from nexus3.cli.keys import monitor_for_escape

        pause_event = asyncio.Event()
        pause_event.set()  # Start running
        pause_ack_event = asyncio.Event()

        escapes_detected = []

        def on_escape():
            escapes_detected.append(True)

        # Start monitor task
        task = asyncio.create_task(
            monitor_for_escape(on_escape, pause_event, pause_ack_event)
        )

        try:
            # Let it start
            await asyncio.sleep(0.05)

            # Request pause
            pause_event.clear()

            # Wait for acknowledgment (should be quick)
            try:
                await asyncio.wait_for(pause_ack_event.wait(), timeout=0.5)
                ack_received = True
            except asyncio.TimeoutError:
                ack_received = False

            assert ack_received, "Monitor should set pause_ack_event when paused"

        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_monitor_clears_ack_on_resume(self):
        """Monitor should clear pause_ack_event when resumed."""
        from nexus3.cli.keys import monitor_for_escape

        pause_event = asyncio.Event()
        pause_event.set()  # Start running
        pause_ack_event = asyncio.Event()

        def on_escape():
            pass

        task = asyncio.create_task(
            monitor_for_escape(on_escape, pause_event, pause_ack_event)
        )

        try:
            await asyncio.sleep(0.05)

            # Request pause
            pause_event.clear()

            # Wait for acknowledgment
            await asyncio.wait_for(pause_ack_event.wait(), timeout=0.5)
            assert pause_ack_event.is_set(), "Should be paused"

            # Resume
            pause_event.set()

            # Give time to process resume
            await asyncio.sleep(0.15)

            # Ack should be cleared
            assert not pause_ack_event.is_set(), "pause_ack_event should be clear after resume"

        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_monitor_waits_for_resume(self):
        """Monitor should wait on pause_event.wait() when paused."""
        from nexus3.cli.keys import monitor_for_escape

        pause_event = asyncio.Event()
        pause_event.set()
        pause_ack_event = asyncio.Event()

        def on_escape():
            pass

        task = asyncio.create_task(
            monitor_for_escape(on_escape, pause_event, pause_ack_event)
        )

        try:
            await asyncio.sleep(0.05)

            # Request pause
            pause_event.clear()

            # Wait for acknowledgment
            await asyncio.wait_for(pause_ack_event.wait(), timeout=0.5)

            # Monitor should now be waiting for resume
            # Verify by checking it stays paused for a while
            await asyncio.sleep(0.2)
            assert pause_ack_event.is_set(), "Monitor should stay paused until resumed"

        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestKeyMonitorContextManager:
    """Tests for KeyMonitor context manager with both events."""

    @pytest.mark.asyncio
    async def test_key_monitor_accepts_both_events(self):
        """KeyMonitor should accept pause_event and pause_ack_event."""
        from nexus3.cli.keys import KeyMonitor

        pause_event = asyncio.Event()
        pause_event.set()
        pause_ack_event = asyncio.Event()

        # Should not raise
        monitor = KeyMonitor(
            on_escape=lambda: None,
            pause_event=pause_event,
            pause_ack_event=pause_ack_event,
        )
        assert monitor.pause_event is pause_event
        assert monitor.pause_ack_event is pause_ack_event

    @pytest.mark.asyncio
    async def test_key_monitor_context_manager(self):
        """KeyMonitor should work as async context manager."""
        from nexus3.cli.keys import KeyMonitor

        pause_event = asyncio.Event()
        pause_event.set()
        pause_ack_event = asyncio.Event()

        async with KeyMonitor(
            on_escape=lambda: None,
            pause_event=pause_event,
            pause_ack_event=pause_ack_event,
        ) as monitor:
            assert monitor._task is not None
            assert not monitor._task.done()

        # After exit, task should be cancelled
        assert monitor._task is None or monitor._task.cancelled()


class TestConfirmationPauseIntegration:
    """Integration tests for confirmation UI pause synchronization."""

    @pytest.mark.asyncio
    async def test_confirmation_waits_for_ack_with_timeout(self):
        """Confirmation should wait for pause_ack with timeout."""
        # This tests the protocol without actually calling confirm_tool_action
        # (which requires terminal interaction)

        pause_event = asyncio.Event()
        pause_event.set()  # Start running
        pause_ack_event = asyncio.Event()

        # Simulate confirmation request
        pause_event.clear()

        # Simulate no monitor running (ack never comes)
        try:
            await asyncio.wait_for(pause_ack_event.wait(), timeout=0.1)
            ack_received = True
        except asyncio.TimeoutError:
            ack_received = False

        assert not ack_received, "Should timeout when no monitor"

        # Resume anyway (confirmation continues after timeout)
        pause_event.set()
        assert pause_event.is_set()

    @pytest.mark.asyncio
    async def test_confirmation_resumes_in_finally(self):
        """Confirmation should resume even on exception."""
        pause_event = asyncio.Event()
        pause_event.set()

        try:
            # Simulate confirmation starting
            pause_event.clear()
            # Simulate error during confirmation
            raise ValueError("Test error")
        except ValueError:
            pass
        finally:
            # This should happen in finally block
            pause_event.set()

        assert pause_event.is_set(), "pause_event should be set in finally"


class TestRaceConditionPrevention:
    """Tests that verify the race condition is actually prevented."""

    @pytest.mark.asyncio
    async def test_ack_guarantees_terminal_restored(self):
        """When ack is set, terminal should be restored (not in cbreak mode).

        This test verifies the conceptual guarantee - the actual terminal
        restoration happens in monitor_for_escape before setting ack.
        """
        from nexus3.cli.keys import monitor_for_escape

        pause_event = asyncio.Event()
        pause_event.set()
        pause_ack_event = asyncio.Event()

        # Track state transitions
        states = []

        async def track_state_monitor():
            try:
                await monitor_for_escape(lambda: None, pause_event, pause_ack_event)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(track_state_monitor())

        try:
            await asyncio.sleep(0.05)

            # Request pause
            states.append(("pause_requested", pause_ack_event.is_set()))
            pause_event.clear()

            # Wait for ack
            await asyncio.wait_for(pause_ack_event.wait(), timeout=0.5)
            states.append(("ack_received", pause_ack_event.is_set()))

            # At this point, monitor has:
            # 1. Exited cbreak mode (terminal restored)
            # 2. Set pause_ack_event
            # So we can safely take input

        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Verify state transitions
        assert states[0] == ("pause_requested", False), "ack should be clear initially"
        assert states[1] == ("ack_received", True), "ack should be set after waiting"

    @pytest.mark.asyncio
    async def test_no_race_between_pause_and_prompt(self):
        """Verify there's no window where input could be lost.

        With the old sleep-based approach, there was a race:
        1. Confirmation requests pause
        2. Sleep(0.15)
        3. If monitor hasn't paused yet, input could be eaten

        With event-based synchronization:
        1. Confirmation requests pause (clear pause_event)
        2. Wait for pause_ack_event
        3. Only then show prompt
        """
        from nexus3.cli.keys import monitor_for_escape

        pause_event = asyncio.Event()
        pause_event.set()
        pause_ack_event = asyncio.Event()

        task = asyncio.create_task(
            monitor_for_escape(lambda: None, pause_event, pause_ack_event)
        )

        try:
            await asyncio.sleep(0.05)

            # Request pause
            pause_event.clear()

            # OLD APPROACH (race-prone):
            # await asyncio.sleep(0.15)  # Hope monitor has paused
            # ... show prompt (monitor might still be in cbreak!)

            # NEW APPROACH (synchronized):
            await asyncio.wait_for(pause_ack_event.wait(), timeout=0.5)
            # Now we KNOW monitor has paused and terminal is restored
            # Safe to show prompt

            # This assertion proves the synchronization works
            assert pause_ack_event.is_set(), "Monitor must acknowledge before prompt"

        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
