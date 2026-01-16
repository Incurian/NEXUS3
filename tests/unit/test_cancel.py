"""Unit tests for cancellation support."""

from asyncio import CancelledError

import pytest

from nexus3.core.cancel import CancellationToken


class TestCancellationToken:
    """Tests for CancellationToken."""

    def test_not_cancelled_initially(self):
        """Token is not cancelled when created."""
        token = CancellationToken()
        assert token.is_cancelled is False

    def test_cancel_sets_is_cancelled(self):
        """cancel() sets is_cancelled to True."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancel_is_idempotent(self):
        """Calling cancel() multiple times is safe."""
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled is True

    def test_raise_if_cancelled_does_nothing_when_not_cancelled(self):
        """raise_if_cancelled() is no-op when not cancelled."""
        token = CancellationToken()
        token.raise_if_cancelled()  # Should not raise

    def test_raise_if_cancelled_raises_when_cancelled(self):
        """raise_if_cancelled() raises CancelledError when cancelled."""
        token = CancellationToken()
        token.cancel()
        with pytest.raises(CancelledError):
            token.raise_if_cancelled()

    def test_on_cancel_callback_called_when_cancelled(self):
        """on_cancel() callback is invoked when cancel() is called."""
        token = CancellationToken()
        called = []
        token.on_cancel(lambda: called.append(True))

        assert len(called) == 0
        token.cancel()
        assert len(called) == 1

    def test_on_cancel_callback_called_immediately_if_already_cancelled(self):
        """on_cancel() callback invoked immediately if token already cancelled."""
        token = CancellationToken()
        token.cancel()

        called = []
        token.on_cancel(lambda: called.append(True))
        assert len(called) == 1

    def test_multiple_callbacks(self):
        """Multiple callbacks are all invoked."""
        token = CancellationToken()
        results = []
        token.on_cancel(lambda: results.append(1))
        token.on_cancel(lambda: results.append(2))

        token.cancel()
        assert results == [1, 2]

    def test_reset_clears_cancelled_state(self):
        """reset() clears the cancelled state."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

        token.reset()
        assert token.is_cancelled is False

    def test_callback_error_does_not_prevent_cancellation(self):
        """Callback errors don't prevent other callbacks or cancellation."""
        token = CancellationToken()
        results = []

        def raise_error():
            raise ValueError("oops")

        token.on_cancel(lambda: results.append(1))
        token.on_cancel(raise_error)
        token.on_cancel(lambda: results.append(3))

        token.cancel()  # Should not raise
        assert token.is_cancelled is True
        # First and third callbacks should still run
        assert 1 in results
        assert 3 in results

    def test_reset_keeps_callbacks(self):
        """reset() clears cancelled state but keeps callbacks."""
        token = CancellationToken()
        results = []
        token.on_cancel(lambda: results.append("called"))

        token.cancel()
        assert results == ["called"]

        token.reset()
        assert token.is_cancelled is False

        # Callbacks should still be registered and fire again
        token.cancel()
        assert results == ["called", "called"]

    def test_callback_not_called_twice_on_duplicate_cancel(self):
        """Callbacks only called once even if cancel() called multiple times."""
        token = CancellationToken()
        call_count = []
        token.on_cancel(lambda: call_count.append(1))

        token.cancel()
        token.cancel()  # Second cancel should be no-op

        assert len(call_count) == 1

    def test_raise_if_cancelled_message(self):
        """raise_if_cancelled() includes descriptive message."""
        token = CancellationToken()
        token.cancel()

        with pytest.raises(CancelledError) as exc_info:
            token.raise_if_cancelled()

        assert "cancelled" in str(exc_info.value).lower()

    def test_callback_exception_logged_on_cancel(self, caplog):
        """Callback exception is logged at debug level during cancel()."""
        import logging

        token = CancellationToken()

        def raise_error():
            raise ValueError("test error")

        token.on_cancel(raise_error)

        with caplog.at_level(logging.DEBUG, logger="nexus3.core.cancel"):
            token.cancel()

        # Verify the exception was logged
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.DEBUG
        assert "ValueError" in record.message
        assert "test error" in record.message

    def test_callback_exception_logged_on_immediate_cancel(self, caplog):
        """Callback exception is logged when registered on already-cancelled token."""
        import logging

        token = CancellationToken()
        token.cancel()

        def raise_error():
            raise RuntimeError("immediate error")

        with caplog.at_level(logging.DEBUG, logger="nexus3.core.cancel"):
            token.on_cancel(raise_error)

        # Verify the exception was logged
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.DEBUG
        assert "RuntimeError" in record.message
        assert "immediate error" in record.message
