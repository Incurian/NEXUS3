"""Session logging interface."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any

from nexus3.core.secure_io import secure_mkdir
from nexus3.core.types import Message, Role, ToolCall, ToolResult
from nexus3.session.events import SessionEvent
from nexus3.session.markdown import MarkdownWriter, RawWriter
from nexus3.session.storage import SessionStorage
from nexus3.session.types import LogConfig, LogStream, SessionInfo

if TYPE_CHECKING:
    from nexus3.core.interfaces import RawLogCallback


def _json_safe_dict(obj: Any) -> Any:
    """Recursively convert to JSON-safe (str non-primitives)."""
    if isinstance(obj, dict):
        return {k: _json_safe_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe_dict(i) for i in obj]
    if hasattr(obj, '__dataclass_fields__'):
        return _json_safe_dict(asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    if not isinstance(obj, (str, int, float, bool, type(None), dict, list)):
        return str(obj)
    return obj


class SessionLogger:
    """Central logging interface for a session.

    Coordinates SQLite storage, markdown generation, and raw logging
    based on configured log streams.
    """

    def __init__(self, config: LogConfig) -> None:
        """Initialize logger with configuration.

        Creates session directory and initializes storage/writers.
        """
        self.config = config
        self.info = SessionInfo.create(
            base_dir=config.base_dir,
            parent_id=config.parent_session,
            mode=config.mode,
        )

        # Ensure session directory exists with secure permissions (0o700)
        secure_mkdir(self.info.session_dir)

        # Initialize storage (always on for context)
        self.storage = SessionStorage(self.info.session_dir / "session.db")

        # Store session metadata
        self.storage.set_metadata("session_id", self.info.session_id)
        self.storage.set_metadata("created_at", str(self.info.created_at))
        if self.info.parent_id:
            self.storage.set_metadata("parent_id", self.info.parent_id)

        # Initialize session markers for cleanup tracking
        # Determine session type: subagent if parent_id set, else from config
        session_type = "subagent" if config.parent_session else config.session_type
        self.storage.init_session_markers(
            session_type=session_type,
            parent_agent_id=config.parent_session,
        )

        # Initialize markdown writer
        verbose_enabled = LogStream.VERBOSE in config.streams
        self._md_writer = MarkdownWriter(
            self.info.session_dir,
            verbose_enabled=verbose_enabled,
        )

        # Initialize raw writer if enabled
        self._raw_writer: RawWriter | None = None
        if LogStream.RAW in config.streams:
            self._raw_writer = RawWriter(self.info.session_dir)

    @property
    def session_dir(self) -> Path:
        """Get the session directory path."""
        return self.info.session_dir

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self.info.session_id

    def _has_stream(self, stream: LogStream) -> bool:
        """Check if a log stream is enabled."""
        return stream in self.config.streams

    # === Message Logging ===

    def log_system(self, content: str) -> int:
        """Log system prompt. Returns message ID."""
        msg_id = self.storage.insert_message(
            role="system",
            content=content,
            timestamp=time(),
        )
        self._md_writer.write_system(content)
        return msg_id

    def log_user(self, content: str, meta: dict[str, Any] | None = None) -> int:
        """Log user message. Returns message ID.

        Args:
            content: The user message content.
            meta: Optional metadata dict (e.g., source attribution).
        """
        msg_id = self.storage.insert_message(
            role="user",
            content=content,
            meta=meta,
            timestamp=time(),
        )
        self._md_writer.write_user(content, meta=meta)
        return msg_id

    def log_assistant(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
        thinking: str | None = None,
        tokens: int | None = None,
    ) -> int:
        """Log assistant response. Returns message ID."""
        # Convert tool calls to dict format for storage
        tool_calls_data: list[dict[str, Any]] | None = None
        if tool_calls:
            tool_calls_data = [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
                for tc in tool_calls
            ]

        msg_id = self.storage.insert_message(
            role="assistant",
            content=content,
            tool_calls=tool_calls_data,
            tokens=tokens,
            timestamp=time(),
        )

        self._md_writer.write_assistant(content, tool_calls_data)

        # Log thinking to verbose stream
        if thinking and self._has_stream(LogStream.VERBOSE):
            self.storage.insert_event(
                event_type="thinking",
                data={"content": thinking},
                message_id=msg_id,
            )
            self._md_writer.write_thinking(thinking)

        return msg_id

    def log_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: ToolResult,
    ) -> int:
        """Log tool execution result. Returns message ID."""
        content = result.error if result.error else result.output

        msg_id = self.storage.insert_message(
            role="tool",
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            timestamp=time(),
        )

        self._md_writer.write_tool_result(
            name=name,
            result=result.output,
            error=result.error if result.error else None,
        )

        return msg_id

    # === Verbose Stream ===

    def log_thinking(self, content: str, message_id: int | None = None) -> None:
        """Log thinking trace (verbose only)."""
        if not self._has_stream(LogStream.VERBOSE):
            return

        ts = time()
        self.storage.insert_event(
            event_type="thinking",
            data={"content": content},
            message_id=message_id,
            timestamp=ts,
        )
        self._md_writer.write_thinking(content, ts)

    def log_timing(
        self,
        operation: str,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log timing info (verbose only)."""
        if not self._has_stream(LogStream.VERBOSE):
            return

        self.storage.insert_event(
            event_type="timing",
            data={
                "operation": operation,
                "duration_ms": duration_ms,
                **(metadata or {}),
            },
        )
        self._md_writer.write_timing(operation, duration_ms, metadata)

    def log_token_count(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """Log token usage (verbose only)."""
        if not self._has_stream(LogStream.VERBOSE):
            return

        self.storage.insert_event(
            event_type="token_usage",
            data={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )
        self._md_writer.write_token_count(
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )

    def log_http_debug(self, logger_name: str, message: str) -> None:
        """Log HTTP debug info (verbose only).

        Args:
            logger_name: Name of the logger (e.g., 'httpx', 'httpcore').
            message: The debug message.
        """
        if not self._has_stream(LogStream.VERBOSE):
            return

        self._md_writer.write_http_debug(logger_name, message)

    def log_session_event(self, event: SessionEvent) -> None:
        """Persist SessionEvent to SQLite (always). verbose.md if VERBOSE."""
        # Use event timestamp if available, otherwise current time
        ts: float = getattr(event, "timestamp", None) or time.time()
        event_name: str = type(event).__name__.lower()

        data = asdict(event)
        if 'tool_calls' in data:
            data['tool_calls'] = [
                {'id': tc['id'], 'name': tc['name'], 'arguments': _json_safe_dict(tc['arguments'])}
                for tc in data['tool_calls']
            ]
        safe_data = _json_safe_dict(data)

        # ALWAYS: SQLite
        self.storage.insert_event(event_type=event_name, data=safe_data, timestamp=ts)

        # CONDITIONAL: verbose.md
        if self._has_stream(LogStream.VERBOSE):
            self._md_writer.write_event(event_type=event_name, data=safe_data)

    # === Raw Stream ===

    def log_raw_request(self, endpoint: str, payload: dict[str, Any]) -> None:
        """Log raw API request (raw only)."""
        if self._raw_writer:
            self._raw_writer.write_request(endpoint, payload)

    def log_raw_response(self, status: int, body: dict[str, Any]) -> None:
        """Log raw API response (raw only)."""
        if self._raw_writer:
            self._raw_writer.write_response(status, body)

    def log_raw_chunk(self, chunk: dict[str, Any]) -> None:
        """Log raw streaming chunk (raw only)."""
        if self._raw_writer:
            self._raw_writer.write_stream_chunk(chunk)

    # === Context Management ===

    def get_context_messages(self) -> list[Message]:
        """Get all messages currently in context window."""
        rows = self.storage.get_messages(in_context_only=True)

        messages: list[Message] = []
        for row in rows:
            # Convert tool_calls back to ToolCall objects
            tool_calls: tuple[ToolCall, ...] = ()
            if row.tool_calls:
                tool_calls = tuple(
                    ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        arguments=tc["arguments"],
                    )
                    for tc in row.tool_calls
                )

            messages.append(
                Message(
                    role=Role(row.role),
                    content=row.content,
                    tool_calls=tool_calls,
                    tool_call_id=row.tool_call_id,
                )
            )

        return messages

    def get_token_count(self) -> int:
        """Get total tokens in current context."""
        return self.storage.get_token_count()

    def mark_compacted(self, message_ids: list[int], summary_id: int) -> None:
        """Mark messages as compacted, replaced by summary."""
        self.storage.mark_as_summary(summary_id, message_ids)

    # === Subagent Support ===

    def create_child_logger(self, name: str | None = None) -> SessionLogger:
        """Create a nested logger for a subagent."""
        child_config = LogConfig(
            base_dir=self.info.session_dir,
            streams=self.config.streams,
            parent_session=self.info.session_id,
        )
        return SessionLogger(child_config)

    # === Raw Log Callback ===

    def get_raw_log_callback(self) -> RawLogCallback | None:
        """Get a callback for raw API logging, if RAW stream is enabled.

        Returns:
            A RawLogCallback adapter if RAW logging is enabled, None otherwise.
        """
        if not self._has_stream(LogStream.RAW):
            return None
        return RawLogCallbackAdapter(self)

    # === Session Markers ===

    def update_session_status(self, status: str) -> None:
        """Update session status for cleanup tracking.

        Args:
            status: 'active' | 'destroyed' | 'orphaned'
        """
        self.storage.update_session_metadata(session_status=status)

    def mark_session_destroyed(self) -> None:
        """Mark session as destroyed for cleanup tracking."""
        self.storage.mark_session_destroyed()

    def mark_session_saved(self) -> None:
        """Mark session as saved (will not be auto-cleaned)."""
        self.storage.update_session_metadata(session_type="saved")

    # === Lifecycle ===

    def close(self) -> None:
        """Close the logger and release resources."""
        self.storage.close()


class RawLogCallbackAdapter:
    """Adapter that bridges SessionLogger to the RawLogCallback protocol.

    This class implements the RawLogCallback protocol by delegating to
    SessionLogger methods. It allows the provider to log raw API data
    without knowing about the logging implementation.
    """

    def __init__(self, logger: SessionLogger) -> None:
        """Initialize the adapter.

        Args:
            logger: The SessionLogger to delegate to.
        """
        self._logger = logger

    def on_request(self, endpoint: str, payload: dict[str, Any]) -> None:
        """Log a raw API request.

        Args:
            endpoint: The API endpoint URL.
            payload: The request body.
        """
        self._logger.log_raw_request(endpoint, payload)

    def on_response(self, status: int, body: dict[str, Any]) -> None:
        """Log a raw API response.

        Args:
            status: The HTTP status code.
            body: The response body.
        """
        self._logger.log_raw_response(status, body)

    def on_chunk(self, chunk: dict[str, Any]) -> None:
        """Log a raw streaming chunk.

        Args:
            chunk: The parsed SSE chunk.
        """
        self._logger.log_raw_chunk(chunk)
