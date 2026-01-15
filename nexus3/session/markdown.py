"""Markdown file writers for human-readable session logs."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from nexus3.core.secure_io import SECURE_FILE_MODE, secure_mkdir, secure_write_new

# Backwards compatibility alias
_SECURE_FILE_MODE = SECURE_FILE_MODE


class MarkdownWriter:
    """Writes human-readable markdown logs for a session."""

    def __init__(self, session_dir: Path, verbose_enabled: bool = False) -> None:
        """Initialize markdown writer.

        Args:
            session_dir: Directory to write markdown files to.
            verbose_enabled: Whether to write verbose.md.
        """
        self.session_dir = session_dir
        self.context_path = session_dir / "context.md"
        self.verbose_path = session_dir / "verbose.md"
        self.verbose_enabled = verbose_enabled

        # Ensure directory exists with secure permissions (0o700)
        secure_mkdir(session_dir)

        # Initialize files with headers (atomically with secure permissions)
        self._init_context_file()
        if verbose_enabled:
            self._init_verbose_file()

    def _init_context_file(self) -> None:
        """Initialize context.md with header atomically with secure permissions."""
        if self.context_path.exists():
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"# Session Log\n\nStarted: {timestamp}\n\n---\n\n"
        try:
            # Atomic creation with 0o600 permissions - no TOCTOU race
            secure_write_new(self.context_path, header)
        except FileExistsError:
            # Race condition: another process created it - that's fine
            pass

    def _init_verbose_file(self) -> None:
        """Initialize verbose.md with header atomically with secure permissions."""
        if self.verbose_path.exists():
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"# Verbose Log\n\nStarted: {timestamp}\n\n---\n\n"
        try:
            # Atomic creation with 0o600 permissions - no TOCTOU race
            secure_write_new(self.verbose_path, header)
        except FileExistsError:
            # Race condition: another process created it - that's fine
            pass

    def _append(self, path: Path, content: str) -> None:
        """Append content to a file."""
        with path.open("a", encoding="utf-8") as f:
            f.write(content)

    def _format_timestamp(self, ts: float | None = None) -> str:
        """Format a timestamp for display."""
        if ts is None:
            return datetime.now().strftime("%H:%M:%S")
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")

    # === Context Log Methods ===

    def write_system(self, content: str) -> None:
        """Write system prompt to context.md."""
        md = f"## System\n\n{content}\n\n---\n\n"
        self._append(self.context_path, md)

    def write_user(self, content: str) -> None:
        """Write user message to context.md."""
        timestamp = self._format_timestamp()
        md = f"## User [{timestamp}]\n\n{content}\n\n"
        self._append(self.context_path, md)

    def write_assistant(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Write assistant response to context.md."""
        timestamp = self._format_timestamp()
        md = f"## Assistant [{timestamp}]\n\n{content}\n\n"

        if tool_calls:
            md += "### Tool Calls\n\n"
            for call in tool_calls:
                name = call.get("name", "unknown")
                args = call.get("arguments", {})
                args_str = json.dumps(args, indent=2)
                md += f"**{name}**\n```json\n{args_str}\n```\n\n"

        self._append(self.context_path, md)

    def write_tool_result(
        self,
        name: str,
        result: str,
        error: str | None = None,
    ) -> None:
        """Write tool result to context.md."""
        status = "error" if error else "success"
        content = error if error else result

        # Truncate very long outputs for readability
        if len(content) > 2000:
            content = content[:2000] + "\n... (truncated)"

        md = f"### Tool Result: {name} ({status})\n\n```\n{content}\n```\n\n"
        self._append(self.context_path, md)

    def write_separator(self) -> None:
        """Write a separator line."""
        self._append(self.context_path, "---\n\n")

    # === Verbose Log Methods ===

    def write_thinking(self, content: str, timestamp: float | None = None) -> None:
        """Write thinking trace to verbose.md."""
        if not self.verbose_enabled:
            return

        ts = self._format_timestamp(timestamp)
        md = f"### Thinking [{ts}]\n\n{content}\n\n"
        self._append(self.verbose_path, md)

    def write_timing(
        self,
        operation: str,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write timing info to verbose.md."""
        if not self.verbose_enabled:
            return

        ts = self._format_timestamp()
        md = f"**{operation}** [{ts}]: {duration_ms:.1f}ms"

        if metadata:
            details = ", ".join(f"{k}={v}" for k, v in metadata.items())
            md += f" ({details})"

        md += "\n\n"
        self._append(self.verbose_path, md)

    def write_token_count(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """Write token usage to verbose.md."""
        if not self.verbose_enabled:
            return

        ts = self._format_timestamp()
        md = (
            f"**Tokens** [{ts}]: "
            f"prompt={prompt_tokens}, completion={completion_tokens}, "
            f"total={total_tokens}\n\n"
        )
        self._append(self.verbose_path, md)

    def write_event(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Write generic event to verbose.md."""
        if not self.verbose_enabled:
            return

        ts = self._format_timestamp()
        md = f"**{event_type}** [{ts}]"

        if data:
            data_str = json.dumps(data, indent=2)
            md += f"\n```json\n{data_str}\n```"

        md += "\n\n"
        self._append(self.verbose_path, md)


class RawWriter:
    """Writes raw API JSON to a JSONL file."""

    def __init__(self, session_dir: Path) -> None:
        """Initialize raw writer.

        Args:
            session_dir: Directory to write raw.jsonl to.
        """
        self.raw_path = session_dir / "raw.jsonl"
        session_dir.mkdir(parents=True, exist_ok=True)

    def write_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        """Write API request to raw.jsonl."""
        from time import time

        entry = {
            "type": "request",
            "timestamp": timestamp or time(),
            "endpoint": endpoint,
            "payload": payload,
        }
        self._append_jsonl(entry)

    def write_response(
        self,
        status: int,
        body: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        """Write API response to raw.jsonl."""
        from time import time

        entry = {
            "type": "response",
            "timestamp": timestamp or time(),
            "status": status,
            "body": body,
        }
        self._append_jsonl(entry)

    def write_stream_chunk(
        self,
        chunk: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        """Write streaming chunk to raw.jsonl."""
        from time import time

        entry = {
            "type": "stream_chunk",
            "timestamp": timestamp or time(),
            "chunk": chunk,
        }
        self._append_jsonl(entry)

    def _append_jsonl(self, entry: dict[str, Any]) -> None:
        """Append a JSON line to the file."""
        is_new = not self.raw_path.exists()
        with self.raw_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        # Set secure permissions on first write
        if is_new:
            os.chmod(self.raw_path, _SECURE_FILE_MODE)
