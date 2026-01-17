"""Text sanitization utilities for safe terminal output.

This module provides functions to sanitize text before terminal output,
preventing injection attacks via ANSI escape sequences and control characters.

Usage:
    from nexus3.core.text_safety import strip_terminal_escapes, escape_rich_markup

    # Sanitize untrusted text before display
    safe_text = strip_terminal_escapes(untrusted_input)

    # Escape Rich markup tags
    safe_text = escape_rich_markup(untrusted_input)

    # Full sanitization (both ANSI and Rich markup)
    safe_text = sanitize_for_display(untrusted_input)
"""

import re

from rich.markup import escape as rich_escape

# ANSI escape sequence pattern - comprehensive terminal escape stripping
# Covers CSI (colors, cursor), mode changes, OSC (title, clipboard), and others
ANSI_ESCAPE_PATTERN = re.compile(
    r'\x1b\[[0-9;]*[ABCDEFGHJKSTfmnsu]|'  # CSI sequences (colors, cursor movement, clear)
    r'\x1b\[\?[0-9;]*[hl]|'               # CSI ? sequences (modes like cursor visibility)
    r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|'  # OSC sequences (title, clipboard, etc.)
    r'\x1b[PX^_][^\x1b]*\x1b\\'            # DCS, SOS, PM, APC sequences
)

# C0 control characters to strip (except \n, \t, \r which are safe)
# Includes NUL, BEL, BS, vertical tab, form feed, and other dangerous characters
# Also strips DEL (0x7f)
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def strip_terminal_escapes(text: str) -> str:
    """Remove ANSI escape sequences and dangerous control characters.

    Safe for use on any untrusted text before terminal output.
    Preserves newlines (\\n), tabs (\\t), and carriage returns (\\r).

    Args:
        text: Input text that may contain escape sequences or control chars.

    Returns:
        Sanitized text safe for terminal output.

    Examples:
        >>> strip_terminal_escapes("\\x1b[31mRed\\x1b[0m")
        'Red'
        >>> strip_terminal_escapes("Hello\\x00World")
        'HelloWorld'
        >>> strip_terminal_escapes("Line1\\nLine2\\tTabbed")
        'Line1\\nLine2\\tTabbed'
    """
    text = ANSI_ESCAPE_PATTERN.sub('', text)
    text = CONTROL_CHAR_PATTERN.sub('', text)
    return text


def escape_rich_markup(text: str) -> str:
    """Escape Rich markup tags in untrusted text.

    Prevents [tag]injection[/tag] attacks in Rich console output.
    Rich uses square brackets for markup like [bold], [red], [link], etc.
    This function escapes these so they display as literal text.

    Args:
        text: Input text that may contain Rich markup tags.

    Returns:
        Text with Rich markup tags escaped (brackets doubled).

    Examples:
        >>> escape_rich_markup("[red]alert[/red]")
        '\\[red]alert\\[/red]'
        >>> escape_rich_markup("normal text")
        'normal text'
    """
    return rich_escape(text)


def sanitize_for_display(text: str) -> str:
    """Full sanitization for terminal display.

    Applies both terminal escape stripping AND Rich markup escaping.
    Use this when displaying completely untrusted text in a Rich console.

    Order of operations:
    1. Strip ANSI escape sequences and control characters
    2. Escape Rich markup tags

    Args:
        text: Untrusted input text.

    Returns:
        Text safe for display in a Rich console.

    Examples:
        >>> sanitize_for_display("\\x1b[31m[red]attack[/red]\\x1b[0m")
        '\\[red]attack\\[/red]'
    """
    text = strip_terminal_escapes(text)
    text = escape_rich_markup(text)
    return text
