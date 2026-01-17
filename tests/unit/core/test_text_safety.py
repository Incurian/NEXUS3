"""Tests for nexus3.core.text_safety module.

Tests cover:
- ANSI color code stripping
- Cursor movement sequence stripping
- OSC sequences (title, clipboard)
- Preservation of safe whitespace (newlines, tabs)
- Stripping of dangerous C0 control characters
"""

import pytest

from nexus3.core.text_safety import (
    ANSI_ESCAPE_PATTERN,
    CONTROL_CHAR_PATTERN,
    strip_terminal_escapes,
)


class TestANSIColorCodeStripping:
    """Test stripping of ANSI color codes."""

    def test_strip_basic_color(self) -> None:
        """Strip basic ANSI color codes."""
        # Red text
        assert strip_terminal_escapes("\x1b[31mRed\x1b[0m") == "Red"
        # Green text
        assert strip_terminal_escapes("\x1b[32mGreen\x1b[0m") == "Green"
        # Bold
        assert strip_terminal_escapes("\x1b[1mBold\x1b[0m") == "Bold"

    def test_strip_256_color(self) -> None:
        """Strip 256-color ANSI codes."""
        # 256 color foreground
        assert strip_terminal_escapes("\x1b[38;5;196mRed\x1b[0m") == "Red"
        # 256 color background
        assert strip_terminal_escapes("\x1b[48;5;21mBlue BG\x1b[0m") == "Blue BG"

    def test_strip_rgb_color(self) -> None:
        """Strip RGB ANSI codes."""
        # RGB foreground
        assert strip_terminal_escapes("\x1b[38;2;255;0;0mRed\x1b[0m") == "Red"
        # RGB background
        assert strip_terminal_escapes("\x1b[48;2;0;0;255mBlue BG\x1b[0m") == "Blue BG"

    def test_strip_combined_styles(self) -> None:
        """Strip combined style codes."""
        # Bold + Red + Underline
        assert strip_terminal_escapes("\x1b[1;31;4mStyled\x1b[0m") == "Styled"

    def test_multiple_color_changes(self) -> None:
        """Handle multiple color changes in text."""
        text = "\x1b[31mRed\x1b[32m Green\x1b[33m Yellow\x1b[0m"
        assert strip_terminal_escapes(text) == "Red Green Yellow"


class TestCursorMovementStripping:
    """Test stripping of cursor movement sequences."""

    def test_strip_cursor_up(self) -> None:
        """Strip cursor up sequences."""
        assert strip_terminal_escapes("Text\x1b[AMore") == "TextMore"
        assert strip_terminal_escapes("Text\x1b[5AMore") == "TextMore"

    def test_strip_cursor_position(self) -> None:
        """Strip cursor position sequences."""
        # Move to position
        assert strip_terminal_escapes("\x1b[10;20HText") == "Text"
        # Home position
        assert strip_terminal_escapes("\x1b[HHome") == "Home"

    def test_strip_clear_screen(self) -> None:
        """Strip clear screen sequences."""
        # Clear screen
        assert strip_terminal_escapes("\x1b[2JClean") == "Clean"
        # Clear line
        assert strip_terminal_escapes("\x1b[2KClean") == "Clean"

    def test_strip_save_restore_cursor(self) -> None:
        """Strip cursor save/restore sequences."""
        # Save cursor
        assert strip_terminal_escapes("\x1b[sText\x1b[uMore") == "TextMore"


class TestOSCSequenceStripping:
    """Test stripping of OSC (Operating System Command) sequences."""

    def test_strip_window_title(self) -> None:
        """Strip window title change sequences."""
        # OSC with BEL terminator
        assert strip_terminal_escapes("\x1b]0;Evil Title\x07Normal") == "Normal"
        # OSC with ST terminator
        assert strip_terminal_escapes("\x1b]0;Evil Title\x1b\\Normal") == "Normal"

    def test_strip_clipboard_write(self) -> None:
        """Strip clipboard write sequences (OSC 52)."""
        # OSC 52 clipboard write attempt
        assert strip_terminal_escapes("\x1b]52;c;SGVsbG8=\x07Text") == "Text"
        assert strip_terminal_escapes("\x1b]52;c;SGVsbG8=\x1b\\Text") == "Text"

    def test_strip_hyperlink(self) -> None:
        """Strip hyperlink sequences (OSC 8)."""
        # OSC 8 hyperlink
        link = "\x1b]8;;http://evil.com\x07Click\x1b]8;;\x07"
        assert strip_terminal_escapes(link) == "Click"


class TestModeSequenceStripping:
    """Test stripping of terminal mode sequences."""

    def test_strip_cursor_visibility(self) -> None:
        """Strip cursor visibility changes."""
        # Hide cursor
        assert strip_terminal_escapes("\x1b[?25lHidden\x1b[?25h") == "Hidden"

    def test_strip_alternate_screen(self) -> None:
        """Strip alternate screen buffer sequences."""
        # Enter alternate screen
        assert strip_terminal_escapes("\x1b[?1049hAlt\x1b[?1049l") == "Alt"

    def test_strip_mouse_tracking(self) -> None:
        """Strip mouse tracking sequences."""
        # Enable mouse tracking
        assert strip_terminal_escapes("\x1b[?1000hMouse\x1b[?1000l") == "Mouse"


class TestDCSAndOtherSequences:
    """Test stripping of DCS, SOS, PM, APC sequences."""

    def test_strip_dcs_sequence(self) -> None:
        """Strip Device Control String sequences."""
        # DCS sequence
        dcs = "\x1bPsome data\x1b\\Normal"
        assert strip_terminal_escapes(dcs) == "Normal"

    def test_strip_apc_sequence(self) -> None:
        """Strip Application Program Command sequences."""
        apc = "\x1b_custom command\x1b\\Normal"
        assert strip_terminal_escapes(apc) == "Normal"


class TestWhitespacePreservation:
    """Test that safe whitespace is preserved."""

    def test_preserve_newlines(self) -> None:
        """Newlines should be preserved."""
        assert strip_terminal_escapes("Line1\nLine2\nLine3") == "Line1\nLine2\nLine3"

    def test_preserve_tabs(self) -> None:
        """Tabs should be preserved."""
        assert strip_terminal_escapes("Col1\tCol2\tCol3") == "Col1\tCol2\tCol3"

    def test_preserve_carriage_return(self) -> None:
        """Carriage returns should be preserved."""
        assert strip_terminal_escapes("Line\rOverwrite") == "Line\rOverwrite"

    def test_preserve_mixed_whitespace(self) -> None:
        """Mixed whitespace should be preserved."""
        text = "Line1\n\tIndented\r\nWindows line"
        assert strip_terminal_escapes(text) == text

    def test_preserve_whitespace_with_escapes(self) -> None:
        """Whitespace preserved even when surrounded by escape sequences."""
        text = "\x1b[31mRed\nLine\x1b[0m"
        assert strip_terminal_escapes(text) == "Red\nLine"


class TestControlCharacterStripping:
    """Test stripping of dangerous C0 control characters."""

    def test_strip_null(self) -> None:
        """Strip NUL character."""
        assert strip_terminal_escapes("Hello\x00World") == "HelloWorld"

    def test_strip_bell(self) -> None:
        """Strip BEL character (standalone, not in OSC)."""
        # Note: BEL inside OSC is handled by OSC pattern
        # This tests standalone BEL
        assert strip_terminal_escapes("Alert\x07Sound") == "AlertSound"

    def test_strip_backspace(self) -> None:
        """Strip backspace character."""
        assert strip_terminal_escapes("Delete\x08This") == "DeleteThis"

    def test_strip_vertical_tab(self) -> None:
        """Strip vertical tab."""
        assert strip_terminal_escapes("Line\x0bNext") == "LineNext"

    def test_strip_form_feed(self) -> None:
        """Strip form feed."""
        assert strip_terminal_escapes("Page\x0cBreak") == "PageBreak"

    def test_strip_delete(self) -> None:
        """Strip DEL character."""
        assert strip_terminal_escapes("Delete\x7fThis") == "DeleteThis"

    def test_strip_escape_character(self) -> None:
        """Strip escape character when not part of sequence."""
        # Lone ESC followed by non-sequence char
        assert strip_terminal_escapes("Text\x1bxMore") == "TextxMore"

    def test_strip_multiple_control_chars(self) -> None:
        """Strip multiple control characters."""
        text = "A\x00B\x07C\x08D\x7fE"
        assert strip_terminal_escapes(text) == "ABCDE"


class TestEdgeCases:
    """Test edge cases and complex scenarios."""

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert strip_terminal_escapes("") == ""

    def test_only_escapes(self) -> None:
        """String with only escape sequences returns empty."""
        assert strip_terminal_escapes("\x1b[31m\x1b[0m") == ""

    def test_only_control_chars(self) -> None:
        """String with only control chars returns empty."""
        assert strip_terminal_escapes("\x00\x07\x08") == ""

    def test_unicode_preserved(self) -> None:
        """Unicode characters are preserved."""
        assert strip_terminal_escapes("Hello World") == "Hello World"
        assert strip_terminal_escapes("\x1b[31mCafe\x1b[0m") == "Cafe"

    def test_nested_escapes(self) -> None:
        """Handle nested/malformed escape sequences."""
        # Overlapping sequences
        text = "\x1b[31m\x1b[1mNested\x1b[0m"
        assert strip_terminal_escapes(text) == "Nested"

    def test_incomplete_escape_sequence(self) -> None:
        """Incomplete sequences may leave partial data."""
        # Incomplete CSI (no terminator)
        # This is expected - we strip what we can match
        text = "\x1b[31Text"  # Missing 'm'
        result = strip_terminal_escapes(text)
        # The \x1b should be stripped as control char, [ and 31 remain
        assert "\x1b" not in result

    def test_real_world_llm_output(self) -> None:
        """Test realistic LLM output with various injections."""
        malicious = (
            "Here is the code:\n"
            "\x1b[31m# Highlighted comment\x1b[0m\n"
            "def foo():\n"
            "    \x1b]0;Pwned!\x07"  # Title injection
            "    return 42\n"
            "\x1b[?25l"  # Hide cursor
            "Done!"
        )
        expected = (
            "Here is the code:\n"
            "# Highlighted comment\n"
            "def foo():\n"
            "    "
            "    return 42\n"
            "Done!"
        )
        assert strip_terminal_escapes(malicious) == expected


class TestPatternCompilation:
    """Test that patterns are correctly compiled."""

    def test_ansi_pattern_is_compiled(self) -> None:
        """ANSI pattern should be a compiled regex."""
        import re
        assert isinstance(ANSI_ESCAPE_PATTERN, re.Pattern)

    def test_control_pattern_is_compiled(self) -> None:
        """Control char pattern should be a compiled regex."""
        import re
        assert isinstance(CONTROL_CHAR_PATTERN, re.Pattern)

    def test_patterns_match_expected(self) -> None:
        """Patterns should match expected sequences."""
        # CSI color
        assert ANSI_ESCAPE_PATTERN.search("\x1b[31m")
        # OSC title
        assert ANSI_ESCAPE_PATTERN.search("\x1b]0;title\x07")
        # Control char
        assert CONTROL_CHAR_PATTERN.search("\x00")
        # Safe chars should not match control pattern
        assert not CONTROL_CHAR_PATTERN.search("abc\n\t\r")
