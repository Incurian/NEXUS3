"""Cancellation support for async operations."""

from asyncio import CancelledError
from collections.abc import Callable


class CancellationToken:
    """Token for cooperative cancellation of async operations.

    When the user presses ESC, the token is cancelled. Async operations
    should periodically check is_cancelled or call raise_if_cancelled().

    Example:
        token = CancellationToken()

        async def long_operation():
            for chunk in stream:
                token.raise_if_cancelled()
                yield chunk

        # When ESC pressed:
        token.cancel()
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._callbacks: list[Callable[[], None]] = []

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    def cancel(self) -> None:
        """Request cancellation and notify callbacks."""
        if self._cancelled:
            return  # Already cancelled
        self._cancelled = True
        for callback in self._callbacks:
            try:
                callback()
            except Exception:
                pass  # Don't let callback errors prevent cancellation

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """Register a callback to be called when cancelled.

        If already cancelled, callback is invoked immediately.
        """
        self._callbacks.append(callback)
        if self._cancelled:
            try:
                callback()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        """Raise CancelledError if cancellation was requested.

        Raises:
            asyncio.CancelledError: If cancel() was called.
        """
        if self._cancelled:
            raise CancelledError("Operation cancelled by user")

    def reset(self) -> None:
        """Reset the token for reuse.

        Clears cancelled state but keeps callbacks.
        """
        self._cancelled = False
