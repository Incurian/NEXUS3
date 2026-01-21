"""HTTP debug logging handler for verbose.md.

This module provides a logging handler that routes httpx/httpcore debug
output to the current session's verbose.md file.

Usage:
    from nexus3.session.http_logging import set_current_logger, clear_current_logger

    # In session processing code:
    set_current_logger(session_logger)
    try:
        # ... make HTTP calls ...
    finally:
        clear_current_logger()

The handler is automatically configured when this module is imported with
LogStream.VERBOSE enabled.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.session.logging import SessionLogger

# Context variable to track the current session's logger
_current_logger: ContextVar[SessionLogger | None] = ContextVar(
    "current_session_logger", default=None
)


def set_current_logger(logger: SessionLogger) -> None:
    """Set the current session logger for HTTP debug routing."""
    _current_logger.set(logger)


def clear_current_logger() -> None:
    """Clear the current session logger."""
    _current_logger.set(None)


class VerboseMdHandler(logging.Handler):
    """Logging handler that writes to the current session's verbose.md.

    This handler is attached to httpx/httpcore loggers to capture HTTP
    debug output and route it to the appropriate session's verbose.md.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Write log record to current session's verbose.md."""
        logger = _current_logger.get()
        if logger is None:
            return

        try:
            message = self.format(record)
            logger.log_http_debug(record.name, message)
        except Exception:
            # Don't let logging errors crash the application
            self.handleError(record)


# Global handler instance
_handler: VerboseMdHandler | None = None


def configure_http_logging() -> None:
    """Configure httpx/httpcore loggers to write to verbose.md.

    Call this once at startup when -V/--log-verbose is enabled.
    """
    global _handler

    if _handler is not None:
        return  # Already configured

    _handler = VerboseMdHandler()
    _handler.setLevel(logging.DEBUG)
    _handler.setFormatter(logging.Formatter("%(message)s"))

    # Attach to parent loggers only to avoid duplication from child propagation
    for logger_name in ("httpx", "httpcore"):
        logger = logging.getLogger(logger_name)
        logger.addHandler(_handler)
        logger.setLevel(logging.DEBUG)


def unconfigure_http_logging() -> None:
    """Remove HTTP logging handler.

    Call this to clean up when shutting down.
    """
    global _handler

    if _handler is None:
        return

    for logger_name in ("httpx", "httpcore"):
        logger = logging.getLogger(logger_name)
        logger.removeHandler(_handler)

    _handler = None
