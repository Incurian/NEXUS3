"""Safe sink abstraction for terminal output boundaries."""

from __future__ import annotations

import sys
from typing import TextIO

from rich.console import Console

from nexus3.core.text_safety import sanitize_for_display, strip_terminal_escapes


class SafeSink:
    """Terminal output sink with explicit trusted/untrusted entrypoints."""

    def __init__(self, console: Console, stream: TextIO | None = None) -> None:
        self.console = console
        self._stream = stream

    def print_trusted(self, content: str, style: str | None = None, end: str = "\n") -> None:
        """Print trusted text through Rich without sanitization."""
        self.console.print(content, style=style, end=end)

    def print_untrusted(self, content: str, style: str | None = None, end: str = "\n") -> None:
        """Print untrusted text through Rich after full display sanitization."""
        safe_content = self.sanitize_print_content(content)
        self.console.print(safe_content, style=style, end=end)

    def write_trusted(self, chunk: str) -> None:
        """Write trusted text directly to the stream without sanitization."""
        if not chunk:
            return
        stream = self._stream or sys.stdout
        stream.write(chunk)
        stream.flush()

    def write_untrusted(self, chunk: str) -> None:
        """Write untrusted text directly to stream after terminal sanitization."""
        safe_chunk = self.sanitize_stream_content(chunk)
        if not safe_chunk:
            return
        stream = self._stream or sys.stdout
        stream.write(safe_chunk)
        stream.flush()

    @staticmethod
    def sanitize_print_content(content: str) -> str:
        """Sanitize untrusted text for Rich-rendered output."""
        return sanitize_for_display(content)

    @staticmethod
    def sanitize_print_value(value: object) -> str:
        """Sanitize an arbitrary value for Rich-rendered output."""
        return sanitize_for_display(str(value))

    @staticmethod
    def sanitize_stream_content(chunk: str) -> str:
        """Sanitize untrusted text for raw stream writes."""
        return strip_terminal_escapes(chunk)
