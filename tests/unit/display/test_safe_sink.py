"""Unit tests for display safe sink trusted/untrusted contracts."""

import io
from unittest.mock import MagicMock

from rich.console import Console

from nexus3.display.safe_sink import SafeSink
from nexus3.display.spinner import Spinner
from nexus3.display.theme import Theme


class MockStdout:
    """Mock stdout that captures writes."""

    def __init__(self) -> None:
        self.buffer = io.StringIO()

    def write(self, data: str) -> int:
        return self.buffer.write(data)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self.buffer.getvalue()


def test_print_untrusted_sanitizes_terminal_and_rich_markup() -> None:
    console = MagicMock(spec=Console)
    sink = SafeSink(console)

    sink.print_untrusted("\x1b[31m[bold]unsafe[/bold]\x1b[0m")

    console.print.assert_called_once_with(r"\[bold]unsafe\[/bold]", style=None, end="\n")


def test_print_trusted_preserves_markup() -> None:
    console = MagicMock(spec=Console)
    sink = SafeSink(console)

    sink.print_trusted("[bold]trusted[/bold]", style="cyan", end="")

    console.print.assert_called_once_with("[bold]trusted[/bold]", style="cyan", end="")


def test_write_untrusted_strips_terminal_sequences() -> None:
    console = MagicMock(spec=Console)
    stdout = MockStdout()
    sink = SafeSink(console, stream=stdout)

    sink.write_untrusted("\x1b[2Jhello\x07")

    assert stdout.getvalue() == "hello"


def test_write_untrusted_drops_empty_after_sanitization() -> None:
    console = MagicMock(spec=Console)
    stdout = MockStdout()
    sink = SafeSink(console, stream=stdout)

    sink.write_untrusted("\x1b[31m\x1b[0m")

    assert stdout.getvalue() == ""


def test_write_trusted_preserves_terminal_sequences() -> None:
    console = MagicMock(spec=Console)
    stdout = MockStdout()
    sink = SafeSink(console, stream=stdout)

    sink.write_trusted("\x1b[31mtrusted\x1b[0m")

    assert stdout.getvalue() == "\x1b[31mtrusted\x1b[0m"


def test_sanitize_print_value_sanitizes_arbitrary_object() -> None:
    class UnsafeValue:
        def __str__(self) -> str:
            return "\x1b[31m[bold]unsafe[/bold]\x1b[0m"

    safe_value = SafeSink.sanitize_print_value(UnsafeValue())

    assert safe_value == r"\[bold]unsafe\[/bold]"


def test_spinner_print_untrusted_sanitizes_by_default() -> None:
    console = MagicMock(spec=Console)
    spinner = Spinner(console=console, theme=Theme())

    spinner.print_untrusted("\x1b[31m[bold]unsafe[/bold]\x1b[0m")

    console.print.assert_called_once_with(r"\[bold]unsafe\[/bold]", style=None, end="\n")


def test_spinner_print_trusted_preserves_markup() -> None:
    console = MagicMock(spec=Console)
    spinner = Spinner(console=console, theme=Theme())

    spinner.print_trusted("[bold]trusted[/bold]", style="cyan", end="")

    console.print.assert_called_once_with("[bold]trusted[/bold]", style="cyan", end="")
