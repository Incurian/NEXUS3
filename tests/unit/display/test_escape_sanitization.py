"""Tests for terminal escape sequence sanitization in InlinePrinter.

P3.1: Verifies that print_streaming_chunk strips ANSI escape sequences
to prevent terminal injection from malicious/buggy LLM output.
"""

import io
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from nexus3.core.text_safety import ANSI_ESCAPE_PATTERN
from nexus3.display.printer import InlinePrinter
from nexus3.display.spinner import Spinner
from nexus3.display.streaming import StreamingDisplay, ToolState, ToolStatus
from nexus3.display.theme import Activity, Status, Theme


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


@pytest.fixture
def mock_stdout() -> MockStdout:
    """Create mock stdout for capturing output."""
    return MockStdout()


@pytest.fixture
def printer() -> InlinePrinter:
    """Create InlinePrinter with mock console."""
    console = MagicMock(spec=Console)
    theme = Theme()
    return InlinePrinter(console, theme)


@pytest.fixture
def print_chunk(printer: InlinePrinter, mock_stdout: MockStdout) -> Callable[[str], str]:
    """Return a function that prints a chunk and returns the captured output."""
    def _print_chunk(chunk: str) -> str:
        printer.safe_sink._stream = mock_stdout
        printer.print_streaming_chunk(chunk)
        return mock_stdout.getvalue()
    return _print_chunk


class TestRemovesColorCodes:
    """Test removal of color/style escape sequences."""

    def test_removes_foreground_color(self, print_chunk: Callable[[str], str]) -> None:
        """Red foreground color code is stripped."""
        result = print_chunk('\x1b[31mred\x1b[0m')
        assert result == 'red'

    def test_removes_background_color(self, print_chunk: Callable[[str], str]) -> None:
        """Background color code is stripped."""
        result = print_chunk('\x1b[44mblue bg\x1b[0m')
        assert result == 'blue bg'

    def test_removes_bold(self, print_chunk: Callable[[str], str]) -> None:
        """Bold style code is stripped."""
        result = print_chunk('\x1b[1mbold\x1b[0m')
        assert result == 'bold'

    def test_removes_256_color(self, print_chunk: Callable[[str], str]) -> None:
        """256-color code is stripped."""
        result = print_chunk('\x1b[38;5;196mred256\x1b[0m')
        assert result == 'red256'

    def test_removes_rgb_color(self, print_chunk: Callable[[str], str]) -> None:
        """RGB color code is stripped."""
        result = print_chunk('\x1b[38;2;255;0;0mrgb red\x1b[0m')
        assert result == 'rgb red'


class TestRemovesCursorMovement:
    """Test removal of cursor movement/screen control sequences."""

    def test_removes_clear_screen(self, print_chunk: Callable[[str], str]) -> None:
        """Clear screen sequence is stripped."""
        result = print_chunk('\x1b[2Jtext')
        assert result == 'text'

    def test_removes_cursor_up(self, print_chunk: Callable[[str], str]) -> None:
        """Cursor up sequence is stripped."""
        result = print_chunk('\x1b[5Hmoved')
        assert result == 'moved'

    def test_removes_cursor_save_restore(self, print_chunk: Callable[[str], str]) -> None:
        """Cursor save/restore sequences are stripped."""
        result = print_chunk('\x1b[stext\x1b[u')
        assert result == 'text'

    def test_removes_clear_line(self, print_chunk: Callable[[str], str]) -> None:
        """Clear line sequence is stripped."""
        result = print_chunk('\x1b[Kcleared')
        assert result == 'cleared'


class TestRemovesOSCSequences:
    """Test removal of OSC (Operating System Command) sequences."""

    def test_removes_title_set_bel(self, print_chunk: Callable[[str], str]) -> None:
        """Window title set sequence (BEL terminated) is stripped."""
        result = print_chunk('\x1b]0;malicious title\x07text')
        assert result == 'text'

    def test_removes_title_set_st(self, print_chunk: Callable[[str], str]) -> None:
        """Window title set sequence (ST terminated) is stripped."""
        result = print_chunk('\x1b]0;malicious title\x1b\\text')
        assert result == 'text'

    def test_removes_hyperlink(self, print_chunk: Callable[[str], str]) -> None:
        """Hyperlink OSC sequence is stripped."""
        result = print_chunk('\x1b]8;;http://evil.com\x07link\x1b]8;;\x07')
        assert result == 'link'


class TestRemovesModeSequences:
    """Test removal of terminal mode sequences."""

    def test_removes_alt_screen_enable(self, print_chunk: Callable[[str], str]) -> None:
        """Alternative screen buffer enable is stripped."""
        result = print_chunk('\x1b[?1049htext')
        assert result == 'text'

    def test_removes_alt_screen_disable(self, print_chunk: Callable[[str], str]) -> None:
        """Alternative screen buffer disable is stripped."""
        result = print_chunk('\x1b[?1049ltext')
        assert result == 'text'

    def test_removes_cursor_hide(self, print_chunk: Callable[[str], str]) -> None:
        """Cursor hide sequence is stripped."""
        result = print_chunk('\x1b[?25lhidden')
        assert result == 'hidden'


class TestPreservesNormalText:
    """Test that normal text is preserved unchanged."""

    def test_preserves_plain_text(self, print_chunk: Callable[[str], str]) -> None:
        """Plain text passes through unchanged."""
        result = print_chunk('Hello, World!')
        assert result == 'Hello, World!'

    def test_preserves_unicode(self, print_chunk: Callable[[str], str]) -> None:
        """Unicode characters pass through unchanged."""
        result = print_chunk('Hello \u2022 World \u2713 Done')
        assert result == 'Hello \u2022 World \u2713 Done'

    def test_preserves_code_samples(self, print_chunk: Callable[[str], str]) -> None:
        """Code samples with brackets pass through."""
        result = print_chunk('def foo[T](x: T) -> T:')
        assert result == 'def foo[T](x: T) -> T:'

    def test_preserves_json(self, print_chunk: Callable[[str], str]) -> None:
        """JSON content passes through unchanged."""
        result = print_chunk('{"key": "value", "count": [1, 2, 3]}')
        assert result == '{"key": "value", "count": [1, 2, 3]}'


class TestPreservesNewlines:
    """Test that newlines and whitespace are preserved."""

    def test_preserves_newline(self, print_chunk: Callable[[str], str]) -> None:
        """Newlines pass through unchanged."""
        result = print_chunk('line1\nline2\nline3')
        assert result == 'line1\nline2\nline3'

    def test_preserves_tabs(self, print_chunk: Callable[[str], str]) -> None:
        """Tab characters pass through unchanged."""
        result = print_chunk('col1\tcol2\tcol3')
        assert result == 'col1\tcol2\tcol3'

    def test_preserves_carriage_return(self, print_chunk: Callable[[str], str]) -> None:
        """Carriage returns pass through unchanged."""
        result = print_chunk('line1\r\nline2')
        assert result == 'line1\r\nline2'


class TestHandlesMixedContent:
    """Test handling of mixed normal text and escape sequences."""

    def test_mixed_text_and_colors(self, print_chunk: Callable[[str], str]) -> None:
        """Mixed text and color codes - only text preserved."""
        result = print_chunk('Hello \x1b[31mred\x1b[0m world')
        assert result == 'Hello red world'

    def test_multiple_escape_sequences(self, print_chunk: Callable[[str], str]) -> None:
        """Multiple escape sequences all stripped."""
        result = print_chunk('\x1b[2J\x1b[H\x1b[31mtext\x1b[0m\x1b]0;title\x07')
        assert result == 'text'

    def test_escape_at_boundaries(self, print_chunk: Callable[[str], str]) -> None:
        """Escape sequences at start/end are stripped."""
        result = print_chunk('\x1b[1mstart\x1b[0m middle \x1b[4mend\x1b[0m')
        assert result == 'start middle end'

    def test_nested_appearing_sequences(self, print_chunk: Callable[[str], str]) -> None:
        """Multiple adjacent sequences all stripped."""
        result = print_chunk('\x1b[1m\x1b[31m\x1b[44mbold red on blue\x1b[0m')
        assert result == 'bold red on blue'


class TestPatternDirectly:
    """Direct tests on the regex pattern."""

    def test_pattern_matches_csi_color(self) -> None:
        """Pattern matches CSI color sequences."""
        assert ANSI_ESCAPE_PATTERN.search('\x1b[31m')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[0m')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[38;5;196m')

    def test_pattern_matches_csi_cursor(self) -> None:
        """Pattern matches CSI cursor sequences."""
        assert ANSI_ESCAPE_PATTERN.search('\x1b[2J')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[H')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[s')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[u')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[K')

    def test_pattern_matches_csi_mode(self) -> None:
        """Pattern matches CSI ? mode sequences."""
        assert ANSI_ESCAPE_PATTERN.search('\x1b[?25h')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[?25l')
        assert ANSI_ESCAPE_PATTERN.search('\x1b[?1049h')

    def test_pattern_matches_osc(self) -> None:
        """Pattern matches OSC sequences."""
        assert ANSI_ESCAPE_PATTERN.search('\x1b]0;title\x07')
        assert ANSI_ESCAPE_PATTERN.search('\x1b]0;title\x1b\\')

    def test_pattern_does_not_match_normal_text(self) -> None:
        """Pattern does not match normal text."""
        assert not ANSI_ESCAPE_PATTERN.search('Hello World')
        assert not ANSI_ESCAPE_PATTERN.search('[1, 2, 3]')
        assert not ANSI_ESCAPE_PATTERN.search('func[T]()')


class TestEdgeCases:
    """Edge cases and potential attack vectors."""

    def test_empty_string(self, print_chunk: Callable[[str], str]) -> None:
        """Empty string handled correctly."""
        result = print_chunk('')
        assert result == ''

    def test_only_escape_sequence(self, print_chunk: Callable[[str], str]) -> None:
        """String containing only escape sequence becomes empty."""
        result = print_chunk('\x1b[31m\x1b[0m')
        assert result == ''

    def test_incomplete_escape_preserved(self, print_chunk: Callable[[str], str]) -> None:
        """Incomplete escape sequences pass through (safe - no terminal effect)."""
        # Incomplete sequence without valid terminator - not harmful
        # Pattern may or may not match depending on content after [
        result = print_chunk('\x1b[text')
        # The important thing is the text 'text' is preserved
        assert 'text' in result

    def test_bell_in_text_is_not_osc(self, print_chunk: Callable[[str], str]) -> None:
        """Standalone bell character is not an OSC sequence."""
        # Bell without preceding OSC starter is just a bell
        # OSC requires \x1b] prefix
        result = print_chunk('alerttext')
        # Without the \x1b] prefix, bell is not stripped
        assert result == 'alerttext'


class TestInlinePrinterRichOutputSanitization:
    """Focused sanitization tests for Rich-rendered printer output paths."""

    def test_print_task_start_sanitizes_untrusted_tool_and_label(
        self, printer: InlinePrinter
    ) -> None:
        printer.print_task_start(
            "[red]read_file[/red]\x1b[31m",
            "src/[bold]main.py[/bold]\x1b]8;;https://example.com\x07x\x1b]8;;\x07",
        )

        printer.console.print.assert_called_once()
        rendered = printer.console.print.call_args.args[0]

        assert rendered.startswith("  [cyan]●[/] ")
        assert r"\[red]read_file\[/red]" in rendered
        assert r"src/\[bold]main.py\[/bold]x" in rendered
        assert "\x1b" not in rendered

    def test_print_thinking_expanded_sanitizes_content(self, printer: InlinePrinter) -> None:
        printer.print_thinking("[red]trace[/red]\x1b[31m", collapsed=False)

        assert printer.console.print.call_count == 3
        first = printer.console.print.call_args_list[0]
        second = printer.console.print.call_args_list[1]
        third = printer.console.print.call_args_list[2]

        assert first.args[0].endswith(" <thinking>")
        assert first.kwargs["style"] == printer.theme.thinking
        assert second.args[0] == r"\[red]trace\[/red]"
        assert second.kwargs["style"] == printer.theme.thinking
        assert third.args[0] == "</thinking>"
        assert third.kwargs["style"] == printer.theme.thinking
        assert "\x1b" not in second.args[0]

    def test_print_gumball_sanitizes_dynamic_message(self, printer: InlinePrinter) -> None:
        printer.print_gumball(Status.ACTIVE, "[bold]unsafe[/bold]\x1b[31m")

        printer.console.print.assert_called_once()
        rendered = printer.console.print.call_args.args[0]

        assert rendered.startswith("[cyan]●[/] ")
        assert r"\[bold]unsafe\[/bold]" in rendered
        assert "\x1b" not in rendered

    def test_print_gumball_trusted_preserves_markup(self, printer: InlinePrinter) -> None:
        printer.print_gumball_trusted(Status.ACTIVE, "[bold]trusted[/bold]")

        printer.console.print.assert_called_once()
        rendered = printer.console.print.call_args.args[0]

        assert rendered.startswith("[cyan]●[/] ")
        assert "[bold]trusted[/bold]" in rendered


class TestSpinnerStreamingSanitization:
    """Focused sanitizer routing tests for Spinner streaming output."""

    def test_print_streaming_sanitizes_untrusted_chunk(self) -> None:
        console = MagicMock(spec=Console)
        spinner = Spinner(console=console, theme=Theme())

        spinner.print_streaming("safe \x1b[31m[bold]red[/bold]\x1b[0m\n")

        console.print.assert_called_once_with(
            r"safe \[bold]red\[/bold]",
            style="magenta",
            end="\n",
        )

    def test_flush_stream_sanitizes_partial_chunk_and_uses_response_style(self) -> None:
        console = MagicMock(spec=Console)
        spinner = Spinner(console=console, theme=Theme())

        spinner.print_streaming("partial \x1b[31m[bold]line[/bold]\x1b[0m")
        spinner.flush_stream()

        console.print.assert_called_once_with(
            r"partial \[bold]line\[/bold]",
            style="magenta",
            end="",
        )

    def test_rich_render_sanitizes_dynamic_status_text(self) -> None:
        spinner = Spinner(console=MagicMock(spec=Console), theme=Theme())
        spinner.update("[red]run[/red]\x1b[31m\nnext\rline", activity=Activity.TOOL_CALLING)

        rendered = spinner.__rich__().plain

        assert r"\[red]run\[/red] next line" in rendered
        assert "\x1b" not in rendered
        assert "\n" not in rendered
        assert "\r" not in rendered


class TestStreamingDisplaySanitization:
    """Focused sanitizer routing tests for StreamingDisplay."""

    def test_add_chunk_sanitizes_terminal_escapes(self) -> None:
        display = StreamingDisplay(Theme())
        display.add_chunk("safe \x1b[31mred\x1b[0m text")
        assert display.response == "safe red text"

    def test_render_tool_line_sanitizes_error_preview(self) -> None:
        display = StreamingDisplay(Theme())
        tool = ToolStatus(
            name="run",
            tool_id="t1",
            state=ToolState.ERROR,
            error="[red]bad[/red]\x1b[31m",
        )

        line = display._render_tool_line(tool)
        plain = line.plain

        assert r"\[red]bad\[/red]" in plain
        assert "\x1b" not in plain

    def test_render_tool_line_sanitizes_tool_name_and_params(self) -> None:
        display = StreamingDisplay(Theme())
        tool = ToolStatus(
            name="[red]run[/red]\x1b[31m",
            tool_id="t1",
            state=ToolState.ACTIVE,
            params="arg=\\[bold]x\\[/bold]\x1b]8;;https://evil\x07y\x1b]8;;\x07",
        )

        line = display._render_tool_line(tool)
        plain = line.plain

        assert r"\[red]run\[/red]" in plain
        assert r"arg=\\\[bold]x\\\[/bold]y" in plain
        assert "\x1b" not in plain

    def test_render_batch_status_sanitizes_active_tool_name(self) -> None:
        display = StreamingDisplay(Theme())
        display.start_batch(
            [
                (
                    "[red]active[/red]\x1b]8;;https://evil\x07x\x1b]8;;\x07",
                    "t1",
                    "",
                ),
                ("other", "t2", ""),
            ]
        )
        display.set_tool_active("t1")

        status = display._render_batch_status()

        assert status.startswith(r"Running: \[red]active\[/red]x")
        assert "\x1b" not in status
