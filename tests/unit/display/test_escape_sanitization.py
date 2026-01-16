"""Tests for terminal escape sequence sanitization in InlinePrinter.

P3.1: Verifies that print_streaming_chunk strips ANSI escape sequences
to prevent terminal injection from malicious/buggy LLM output.
"""

import io
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from nexus3.display.printer import InlinePrinter, _ANSI_ESCAPE_PATTERN
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
        with patch('nexus3.display.printer.sys.stdout', mock_stdout):
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
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[31m')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[0m')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[38;5;196m')

    def test_pattern_matches_csi_cursor(self) -> None:
        """Pattern matches CSI cursor sequences."""
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[2J')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[H')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[s')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[u')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[K')

    def test_pattern_matches_csi_mode(self) -> None:
        """Pattern matches CSI ? mode sequences."""
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[?25h')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[?25l')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b[?1049h')

    def test_pattern_matches_osc(self) -> None:
        """Pattern matches OSC sequences."""
        assert _ANSI_ESCAPE_PATTERN.search('\x1b]0;title\x07')
        assert _ANSI_ESCAPE_PATTERN.search('\x1b]0;title\x1b\\')

    def test_pattern_does_not_match_normal_text(self) -> None:
        """Pattern does not match normal text."""
        assert not _ANSI_ESCAPE_PATTERN.search('Hello World')
        assert not _ANSI_ESCAPE_PATTERN.search('[1, 2, 3]')
        assert not _ANSI_ESCAPE_PATTERN.search('func[T]()')


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
