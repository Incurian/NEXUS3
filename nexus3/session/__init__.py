"""Chat session management and logging."""

from nexus3.session.confirmation import ConfirmationController
from nexus3.session.dispatcher import ToolDispatcher
from nexus3.session.enforcer import PermissionEnforcer
from nexus3.session.events import (
    ContentChunk,
    IterationCompleted,
    ReasoningEnded,
    ReasoningStarted,
    SessionCancelled,
    SessionCompleted,
    SessionEvent,
    ToolBatchCompleted,
    ToolBatchHalted,
    ToolBatchStarted,
    ToolCompleted,
    ToolDetected,
    ToolStarted,
)
from nexus3.session.http_logging import (
    clear_current_logger,
    configure_http_logging,
    set_current_logger,
    unconfigure_http_logging,
)
from nexus3.session.logging import RawLogCallbackAdapter, SessionLogger
from nexus3.session.persistence import (
    SavedSession,
    SessionSummary,
    deserialize_message,
    deserialize_messages,
    serialize_message,
    serialize_messages,
    serialize_session,
)
from nexus3.session.session import ConfirmationCallback, Session
from nexus3.session.session_manager import (
    SessionManager,
    SessionManagerError,
    SessionNotFoundError,
)
from nexus3.session.storage import SessionMarkers, SessionStorage
from nexus3.session.types import LogConfig, LogStream, SessionInfo

__all__ = [
    "Session",
    "ConfirmationCallback",
    "ConfirmationController",
    "ToolDispatcher",
    "PermissionEnforcer",
    "SessionLogger",
    "SessionStorage",
    "SessionMarkers",
    "LogConfig",
    "LogStream",
    "SessionInfo",
    "RawLogCallbackAdapter",
    # HTTP debug logging
    "configure_http_logging",
    "unconfigure_http_logging",
    "set_current_logger",
    "clear_current_logger",
    # Persistence
    "SavedSession",
    "SessionSummary",
    "serialize_message",
    "deserialize_message",
    "serialize_messages",
    "deserialize_messages",
    "serialize_session",
    # Session Manager
    "SessionManager",
    "SessionManagerError",
    "SessionNotFoundError",
    # Session Events
    "SessionEvent",
    "ContentChunk",
    "ReasoningStarted",
    "ReasoningEnded",
    "ToolDetected",
    "ToolBatchStarted",
    "ToolStarted",
    "ToolCompleted",
    "ToolBatchHalted",
    "ToolBatchCompleted",
    "IterationCompleted",
    "SessionCompleted",
    "SessionCancelled",
]
