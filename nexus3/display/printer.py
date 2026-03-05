"""Inline printing with gumball status indicators."""

from rich.console import Console

from nexus3.display.safe_sink import SafeSink
from nexus3.display.theme import Status, Theme


class InlinePrinter:
    """Handles all scrolling content output with gumball indicators.

    All output from this class scrolls normally in the terminal.
    Uses Rich Console for styled output, except streaming which
    uses raw stdout to avoid conflicts with Rich.Live.
    """

    def __init__(self, console: Console, theme: Theme) -> None:
        self.console = console
        self.theme = theme
        self.safe_sink = SafeSink(console)

    def print(self, content: str, style: str | None = None, end: str = "\n") -> None:
        """Print content (scrolls normally).

        Args:
            content: Text to print
            style: Optional Rich style string
            end: String to append (default newline)
        """
        self.safe_sink.print_trusted(content, style=style, end=end)

    def print_gumball(self, status: Status, message: str, indent: int = 0) -> None:
        """Print a gumball indicator with message.

        Args:
            status: Status for gumball color
            message: Text after the gumball
            indent: Number of spaces to indent
        """
        prefix = " " * indent
        gumball = self.theme.gumball(status)
        self.safe_sink.print_trusted(f"{prefix}{gumball} {message}")

    def print_thinking(self, content: str, collapsed: bool = True) -> None:
        """Print thinking trace inline.

        Args:
            content: The thinking content
            collapsed: If True, show "Thinking..." instead of full content
        """
        if collapsed:
            self.print_gumball(Status.ACTIVE, "Thinking...")
        else:
            gumball = self.theme.gumball(Status.ACTIVE)
            self.safe_sink.print_trusted(f"{gumball} <thinking>", style=self.theme.thinking)
            self.safe_sink.print_untrusted(content, style=self.theme.thinking)
            self.safe_sink.print_trusted("</thinking>", style=self.theme.thinking)

    def print_task_start(self, task_type: str, label: str, indent: int = 2) -> None:
        """Print task starting (e.g., '  [cyan]●[/] read_file: src/main.py').

        Args:
            task_type: Type of task (read_file, grep, etc.)
            label: Task details
            indent: Indentation level
        """
        safe_task_type = self.safe_sink.sanitize_print_content(task_type)
        safe_label = self.safe_sink.sanitize_print_content(label)
        self.print_gumball(Status.ACTIVE, f"{safe_task_type}: {safe_label}", indent=indent)

    def print_task_end(self, task_type: str, success: bool, indent: int = 2) -> None:
        """Print task completion.

        Args:
            task_type: Type of task
            success: Whether task succeeded
            indent: Indentation level
        """
        status = Status.COMPLETE if success else Status.ERROR
        result = "complete" if success else "failed"
        safe_task_type = self.safe_sink.sanitize_print_content(task_type)
        self.print_gumball(status, f"{safe_task_type}: {result}", indent=indent)

    def print_error(self, message: str) -> None:
        """Print error message."""
        safe_message = self.safe_sink.sanitize_print_content(message)
        self.print_gumball(Status.ERROR, safe_message)

    def print_cancelled(self, message: str = "Cancelled") -> None:
        """Print cancellation message."""
        safe_message = self.safe_sink.sanitize_print_content(message)
        self.print_gumball(Status.CANCELLED, safe_message)

    def print_streaming_chunk(self, chunk: str) -> None:
        """Print a streaming chunk without newline.

        Uses raw stdout to avoid conflicts with Rich.Live.
        Strips ANSI escape sequences and control chars to prevent terminal injection.
        """
        self.safe_sink.write_untrusted(chunk)

    def finish_streaming(self) -> None:
        """Finish streaming output (print newline)."""
        self.safe_sink.write_trusted("\n")
