"""Session logging interface."""

from pathlib import Path
from time import time
from typing import Any

from nexus3.core.types import Message, Role, ToolCall, ToolResult
from nexus3.session.markdown import MarkdownWriter, RawWriter
from nexus3.session.storage import SessionStorage
from nexus3.session.types import LogConfig, LogStream, SessionInfo


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
        )

        # Ensure session directory exists
        self.info.session_dir.mkdir(parents=True, exist_ok=True)

        # Initialize storage (always on for context)
        self.storage = SessionStorage(self.info.session_dir / "session.db")

        # Store session metadata
        self.storage.set_metadata("session_id", self.info.session_id)
        self.storage.set_metadata("created_at", str(self.info.created_at))
        if self.info.parent_id:
            self.storage.set_metadata("parent_id", self.info.parent_id)

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

    def log_user(self, content: str) -> int:
        """Log user message. Returns message ID."""
        msg_id = self.storage.insert_message(
            role="user",
            content=content,
            timestamp=time(),
        )
        self._md_writer.write_user(content)
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

    def create_child_logger(self, name: str | None = None) -> "SessionLogger":
        """Create a nested logger for a subagent."""
        child_config = LogConfig(
            base_dir=self.info.session_dir,
            streams=self.config.streams,
            parent_session=self.info.session_id,
        )
        return SessionLogger(child_config)

    # === Lifecycle ===

    def close(self) -> None:
        """Close the logger and release resources."""
        self.storage.close()
