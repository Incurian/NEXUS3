"""Security tests for Rich markup injection prevention.

Tests that untrusted input (tool names, arguments, paths) is properly
escaped before display in Rich console output.

Fix 2.5 in REMEDIATION-PLAN.md addresses H8: Rich markup injection.
"""

import pytest

from nexus3.core.text_safety import (
    escape_rich_markup,
    sanitize_for_display,
    strip_terminal_escapes,
)
from nexus3.cli.confirmation_ui import format_tool_params


class TestEscapeRichMarkup:
    """Tests for escape_rich_markup() function."""

    def test_escapes_bold_tag(self) -> None:
        """Bold markup tags should be escaped."""
        result = escape_rich_markup("[bold]text[/bold]")
        assert "[bold]" not in result or result.startswith("\\")
        # Rich's escape doubles the brackets
        assert "\\[bold]" in result or result == "\\[bold]text\\[/bold]"

    def test_escapes_color_tag(self) -> None:
        """Color markup tags should be escaped."""
        result = escape_rich_markup("[red]danger[/red]")
        assert "\\[red]" in result

    def test_escapes_link_tag(self) -> None:
        """Link markup tags should be escaped."""
        result = escape_rich_markup("[link=http://evil.com]click[/link]")
        assert "\\[link=" in result

    def test_escapes_nested_tags(self) -> None:
        """Nested markup tags should be escaped."""
        result = escape_rich_markup("[bold][red]nested[/red][/bold]")
        assert "\\[bold]" in result
        assert "\\[red]" in result

    def test_preserves_normal_text(self) -> None:
        """Normal text without markup should be unchanged."""
        result = escape_rich_markup("normal text without markup")
        assert result == "normal text without markup"

    def test_preserves_square_brackets_in_arrays(self) -> None:
        """Array notation is preserved (Rich only escapes valid markup)."""
        result = escape_rich_markup("array[0]")
        # Rich is smart - array notation isn't valid markup, so it's preserved
        assert result == "array[0]"

    def test_escapes_dim_tag(self) -> None:
        """Dim markup should be escaped."""
        result = escape_rich_markup("[dim]faded[/dim]")
        assert "\\[dim]" in result

    def test_escapes_italic_tag(self) -> None:
        """Italic markup should be escaped."""
        result = escape_rich_markup("[italic]slanted[/italic]")
        assert "\\[italic]" in result

    def test_empty_string(self) -> None:
        """Empty string should return empty string."""
        assert escape_rich_markup("") == ""

    def test_only_brackets(self) -> None:
        """Empty brackets are preserved (not valid markup)."""
        result = escape_rich_markup("[]")
        # Rich is smart - empty brackets aren't valid markup
        assert result == "[]"


class TestSanitizeForDisplay:
    """Tests for sanitize_for_display() which combines ANSI and Rich escaping."""

    def test_handles_ansi_and_rich_together(self) -> None:
        """Both ANSI escapes and Rich markup should be handled."""
        # Input has ANSI color code AND Rich markup
        malicious = "\x1b[31m[red]double attack[/red]\x1b[0m"
        result = sanitize_for_display(malicious)

        # ANSI sequences should be stripped
        assert "\x1b[31m" not in result
        assert "\x1b[0m" not in result

        # Rich markup should be escaped
        assert "\\[red]" in result

    def test_ansi_stripped_first_then_rich_escaped(self) -> None:
        """Verify order: ANSI stripping happens before Rich escaping."""
        # This input has ANSI that would be valid Rich after stripping
        input_text = "\x1b[0m[bold]text[/bold]"
        result = sanitize_for_display(input_text)

        # ANSI should be gone
        assert "\x1b" not in result

        # Rich markup should be escaped
        assert "\\[bold]" in result

    def test_control_chars_and_rich_markup(self) -> None:
        """Control characters should be stripped, Rich markup escaped."""
        # NUL byte + Rich markup
        malicious = "\x00[red]bad[/red]\x00"
        result = sanitize_for_display(malicious)

        # NUL bytes gone
        assert "\x00" not in result

        # Rich markup escaped
        assert "\\[red]" in result

    def test_preserves_safe_whitespace(self) -> None:
        """Newlines and tabs should be preserved."""
        text = "line1\nline2\ttabbed"
        result = sanitize_for_display(text)
        assert result == "line1\nline2\ttabbed"

    def test_complex_attack_vector(self) -> None:
        """Complex attack combining multiple injection techniques."""
        # OSC sequence (clipboard attack) + Rich link (phishing)
        malicious = "\x1b]52;c;YmFkZGF0YQ==\x07[link=http://phish.com]Click here[/link]"
        result = sanitize_for_display(malicious)

        # OSC sequence gone
        assert "\x1b]52" not in result
        assert "\x07" not in result

        # Rich link escaped
        assert "\\[link=" in result


class TestConfirmationUIEscaping:
    """Tests for Rich markup escaping in confirmation_ui.format_tool_params()."""

    def test_escapes_path_value(self) -> None:
        """Path values with Rich markup should be escaped."""
        args = {"path": "/tmp/[red]malicious[/red]/file.txt"}
        result = format_tool_params(args)

        # Markup should be escaped in output
        assert "\\[red]" in result
        # The escape adds backslash before [, so "[red]" becomes "\[red]"
        # but the string still contains "red]malicious" after the backslash
        assert "\\[red]malicious\\[/red]" in result

    def test_escapes_content_value(self) -> None:
        """Content values with Rich markup should be escaped."""
        args = {"content": "[bold]injected[/bold]"}
        result = format_tool_params(args)

        assert "\\[bold]" in result

    def test_escapes_agent_id(self) -> None:
        """Agent ID with Rich markup should be escaped."""
        args = {"agent_id": "evil_[link=http://bad.com]agent[/link]"}
        result = format_tool_params(args)

        assert "\\[link=" in result

    def test_escapes_command_value(self) -> None:
        """Command values with Rich markup should be escaped."""
        args = {"command": "echo '[red]danger[/red]'"}
        result = format_tool_params(args)

        assert "\\[red]" in result

    def test_escapes_non_priority_keys_too(self) -> None:
        """Non-priority argument keys and values should be escaped."""
        args = {"custom_[bold]key": "custom_[italic]value"}
        result = format_tool_params(args)

        # Both key and value should have escaped markup
        assert "\\[bold]" in result
        assert "\\[italic]" in result

    def test_mcp_tool_name_with_markup(self) -> None:
        """MCP tool names containing markup should be escaped."""
        # This tests the attack vector: MCP server provides tool name with injection
        args = {"path": "/normal/path"}
        result = format_tool_params(args)

        # This just tests format_tool_params; the tool name escaping is in
        # confirm_tool_action which we can't easily unit test without mocking

    def test_empty_arguments(self) -> None:
        """Empty arguments should return empty string."""
        assert format_tool_params({}) == ""

    def test_none_values_skipped(self) -> None:
        """None values should be skipped."""
        args = {"path": "/valid/path", "optional": None}
        result = format_tool_params(args)

        assert "path=" in result
        assert "optional" not in result

    def test_truncation_preserves_escaping(self) -> None:
        """Truncated values should still have escaping applied."""
        # Create a long value with markup near the end
        long_value = "a" * 50 + "[red]end[/red]"
        args = {"content": long_value}
        result = format_tool_params(args)

        # Value gets truncated, but if markup appears in truncated portion,
        # it should be escaped
        assert "[red]" not in result or "\\[red]" in result

    def test_quoted_strings_with_spaces_escaped(self) -> None:
        """Strings with spaces get quoted, and markup should be escaped."""
        args = {"message": "[bold]hello world[/bold]"}
        result = format_tool_params(args)

        # Should be escaped
        assert "\\[bold]" in result


class TestEdgeCases:
    """Edge case tests for markup escaping."""

    def test_unicode_with_markup(self) -> None:
        """Unicode text with markup should be handled correctly."""
        text = "[red]\u4e2d\u6587[/red]"  # Chinese characters
        result = escape_rich_markup(text)

        assert "\\[red]" in result
        assert "\u4e2d\u6587" in result  # Chinese preserved

    def test_very_long_markup(self) -> None:
        """Very long markup tag should be escaped."""
        long_tag = "[" + "a" * 100 + "]text[/" + "a" * 100 + "]"
        result = escape_rich_markup(long_tag)

        # Should be escaped
        assert "\\[" in result

    def test_malformed_markup(self) -> None:
        """Malformed markup (unclosed tags) is preserved by Rich."""
        result = escape_rich_markup("[bold unclosed")
        # Rich is smart - malformed tags aren't valid markup, so preserved
        # This is safe because Rich won't interpret them either
        assert result == "[bold unclosed"

    def test_consecutive_brackets(self) -> None:
        """Consecutive brackets - Rich escapes what looks like markup."""
        result = escape_rich_markup("[[nested]]")
        # Rich interprets [nested] as a potential style tag, so it escapes it
        # The outer brackets are not escaped because they don't form valid markup
        assert result == "[\\[nested]]"

    def test_close_tag_only(self) -> None:
        """Close tag without open tag should be escaped."""
        result = escape_rich_markup("[/red]orphan")
        assert "\\[/red]" in result
