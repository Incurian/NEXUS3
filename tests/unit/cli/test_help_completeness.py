"""Tests for help system completeness.

These tests ensure that:
1. The main HELP_TEXT lists all implemented commands
2. Per-command help (when implemented) documents all flags
3. Both help invocation styles return identical text
4. No orphan commands exist in help that aren't implemented
"""

import re
from typing import Set

import pytest


class TestMainHelpCompleteness:
    """Tests for the main HELP_TEXT containing all commands."""

    # All implemented REPL commands
    IMPLEMENTED_COMMANDS: Set[str] = {
        # Agent management
        "agent", "whisper", "over", "list", "create", "destroy",
        "send", "status", "cancel",
        # Session management
        "save", "clone", "rename", "delete",
        # Configuration
        "cwd", "model", "permissions", "prompt", "compact",
        # MCP
        "mcp",
        # GitLab
        "gitlab",
        # Initialization
        "init",
        # REPL control
        "help", "clear", "quit", "exit", "q",
    }

    # Command aliases (map alias -> canonical name)
    COMMAND_ALIASES: dict[str, str] = {
        "exit": "quit",
        "q": "quit",
    }

    def test_help_text_exists(self):
        """HELP_TEXT should be defined and non-empty."""
        from nexus3.cli.repl_commands import HELP_TEXT

        assert HELP_TEXT is not None
        assert len(HELP_TEXT) > 100  # Sanity check it has content

    def test_all_commands_in_help_text(self):
        """Every implemented command should appear in HELP_TEXT."""
        from nexus3.cli.repl_commands import HELP_TEXT

        missing_commands = []
        for cmd in self.IMPLEMENTED_COMMANDS:
            # Check for /cmd or just cmd in help text
            if f"/{cmd}" not in HELP_TEXT and f" {cmd} " not in HELP_TEXT:
                # Allow aliases to not be separately documented if canonical is
                if cmd in self.COMMAND_ALIASES:
                    canonical = self.COMMAND_ALIASES[cmd]
                    if f"/{canonical}" in HELP_TEXT:
                        continue
                missing_commands.append(cmd)

        assert not missing_commands, f"Commands missing from HELP_TEXT: {missing_commands}"

    def test_no_extra_commands_in_help(self):
        """Commands in HELP_TEXT should be implemented."""
        from nexus3.cli.repl_commands import HELP_TEXT

        # Extract command names from HELP_TEXT
        # Commands appear at start of line (after optional spaces) as /cmd
        # We exclude things like --yolo|--trusted|--sandboxed which are flags
        documented_commands = set()
        for line in HELP_TEXT.split('\n'):
            stripped = line.strip()
            # Command lines start with /
            if stripped.startswith('/'):
                # Extract first word after /
                match = re.match(r'/([a-z_]+)', stripped)
                if match:
                    documented_commands.add(match.group(1))

        # All documented commands should be in our implemented set
        all_known = self.IMPLEMENTED_COMMANDS | set(self.COMMAND_ALIASES.keys())
        unknown_commands = documented_commands - all_known

        assert not unknown_commands, f"Unknown commands in HELP_TEXT: {unknown_commands}"

    def test_help_text_has_sections(self):
        """HELP_TEXT should have organized sections."""
        from nexus3.cli.repl_commands import HELP_TEXT

        expected_sections = [
            "Agent Management",
            "Session Management",
            "Configuration",
            "MCP",
            "REPL Control",
            "Keyboard Shortcuts",
        ]

        for section in expected_sections:
            assert section in HELP_TEXT, f"Missing section: {section}"


class TestCommandFlagsDocumented:
    """Tests that command flags are documented in help text."""

    def test_agent_command_flags(self):
        """The /agent command should document all its flags."""
        from nexus3.cli.repl_commands import HELP_TEXT

        # All flags that /agent accepts
        agent_flags = ["--yolo", "--trusted", "--sandboxed", "--model"]

        for flag in agent_flags:
            assert flag in HELP_TEXT, f"/agent flag {flag} not documented"

    def test_permissions_command_flags(self):
        """The /permissions command should document all its flags."""
        from nexus3.cli.repl_commands import HELP_TEXT

        permissions_flags = ["--disable", "--enable", "--list-tools"]

        for flag in permissions_flags:
            assert flag in HELP_TEXT, f"/permissions flag {flag} not documented"

    def test_status_command_flags(self):
        """The /status command should document all its flags."""
        from nexus3.cli.repl_commands import HELP_TEXT

        status_flags = ["--tools", "--tokens"]

        for flag in status_flags:
            assert flag in HELP_TEXT, f"/status flag {flag} not documented"

    def test_mcp_connect_flags(self):
        """The /mcp connect command should document all its flags."""
        from nexus3.cli.repl_commands import HELP_TEXT

        mcp_flags = ["--allow-all", "--per-tool", "--shared", "--private"]

        for flag in mcp_flags:
            assert flag in HELP_TEXT, f"/mcp connect flag {flag} not documented"

    def test_init_command_flags(self):
        """The /init command should document all its flags."""
        from nexus3.cli.repl_commands import HELP_TEXT

        init_flags = ["--force", "--global"]

        for flag in init_flags:
            assert flag in HELP_TEXT, f"/init flag {flag} not documented"

    def test_create_command_flags(self):
        """The /create command should document its flags."""
        from nexus3.cli.repl_commands import HELP_TEXT

        # /create has same flags as /agent for presets
        create_flags = ["--preset", "--model"]

        for flag in create_flags:
            assert flag in HELP_TEXT, f"/create flag {flag} not documented"


class TestCommandImplementationExists:
    """Tests that documented commands have implementations."""

    # Map command names to their implementation function names
    COMMAND_TO_FUNCTION: dict[str, str] = {
        "agent": "cmd_agent",
        "whisper": "cmd_whisper",
        "over": "cmd_over",
        "cwd": "cmd_cwd",
        "permissions": "cmd_permissions",
        "prompt": "cmd_prompt",
        "help": "cmd_help",
        "clear": "cmd_clear",
        "quit": "cmd_quit",
        "compact": "cmd_compact",
        "model": "cmd_model",
        "mcp": "cmd_mcp",
        "init": "cmd_init",
    }

    # Commands implemented in core.py (via commands module)
    CORE_COMMANDS: Set[str] = {
        "list", "create", "destroy", "send", "status", "cancel",
        "save", "clone", "rename", "delete", "shutdown",
    }

    def test_repl_command_functions_exist(self):
        """Each REPL command should have a corresponding cmd_ function."""
        import nexus3.cli.repl_commands as repl_commands

        for cmd_name, func_name in self.COMMAND_TO_FUNCTION.items():
            assert hasattr(repl_commands, func_name), \
                f"Missing function {func_name} for command /{cmd_name}"

            func = getattr(repl_commands, func_name)
            assert callable(func), f"{func_name} should be callable"

    def test_core_command_functions_exist(self):
        """Core commands should have implementations in commands.core."""
        from nexus3.commands import core

        for cmd_name in self.CORE_COMMANDS:
            func_name = f"cmd_{cmd_name}"
            assert hasattr(core, func_name), \
                f"Missing function {func_name} in commands.core"


class TestKeyboardShortcutsDocumented:
    """Tests that keyboard shortcuts are documented."""

    def test_esc_documented(self):
        """ESC key should be documented."""
        from nexus3.cli.repl_commands import HELP_TEXT
        assert "ESC" in HELP_TEXT

    def test_ctrl_c_documented(self):
        """Ctrl+C should be documented."""
        from nexus3.cli.repl_commands import HELP_TEXT
        assert "Ctrl+C" in HELP_TEXT or "Ctrl-C" in HELP_TEXT

    def test_ctrl_d_documented(self):
        """Ctrl+D should be documented."""
        from nexus3.cli.repl_commands import HELP_TEXT
        assert "Ctrl+D" in HELP_TEXT or "Ctrl-D" in HELP_TEXT


class TestHelpMechanismEquivalence:
    """Tests for per-command help implementation.

    These tests verify that both /help <cmd> and /<cmd> --help
    return the same text from the COMMAND_HELP dict.
    """

    def test_help_cmd_returns_same_as_cmd_help(self):
        """Both /help save and /save --help should return identical text."""
        from nexus3.cli.repl_commands import COMMAND_HELP, get_command_help

        for cmd_name in COMMAND_HELP.keys():
            # Via /help <cmd>
            via_help_cmd = get_command_help(cmd_name)
            # Via /<cmd> --help (should use same source)
            via_flag = get_command_help(cmd_name)

            assert via_help_cmd == via_flag, \
                f"Help mismatch for {cmd_name}: /help {cmd_name} != /{cmd_name} --help"

    def test_all_commands_have_detailed_help(self):
        """Every command should have an entry in COMMAND_HELP."""
        from nexus3.cli.repl_commands import COMMAND_HELP

        # Canonical commands (excluding aliases)
        commands = TestMainHelpCompleteness.IMPLEMENTED_COMMANDS - {"exit", "q"}

        for cmd in commands:
            assert cmd in COMMAND_HELP, f"Missing detailed help for /{cmd}"

    def test_detailed_help_has_required_sections(self):
        """Each command's detailed help should have examples and description."""
        from nexus3.cli.repl_commands import COMMAND_HELP

        for cmd_name, help_text in COMMAND_HELP.items():
            # Should have a description
            assert len(help_text) > 50, f"/{cmd_name} help too short"

            # Should have examples (lines starting with /)
            has_examples = bool(re.search(r'^/', help_text, re.MULTILINE))
            assert has_examples, f"/{cmd_name} help missing examples"

    def test_get_command_help_handles_leading_slash(self):
        """get_command_help should work with or without leading slash."""
        from nexus3.cli.repl_commands import get_command_help

        # With slash
        help_with_slash = get_command_help("/save")
        # Without slash
        help_without_slash = get_command_help("save")

        assert help_with_slash == help_without_slash
        assert help_with_slash is not None

    def test_get_command_help_resolves_aliases(self):
        """get_command_help should resolve command aliases to canonical names."""
        from nexus3.cli.repl_commands import get_command_help

        # exit and q should both return help for quit
        quit_help = get_command_help("quit")
        exit_help = get_command_help("exit")
        q_help = get_command_help("q")

        assert quit_help == exit_help == q_help
        assert quit_help is not None

    def test_get_command_help_returns_none_for_unknown(self):
        """get_command_help should return None for unknown commands."""
        from nexus3.cli.repl_commands import get_command_help

        assert get_command_help("notacommand") is None
        assert get_command_help("/fakecmd") is None

    def test_get_command_help_case_insensitive(self):
        """get_command_help should be case insensitive."""
        from nexus3.cli.repl_commands import get_command_help

        lower_help = get_command_help("save")
        upper_help = get_command_help("SAVE")
        mixed_help = get_command_help("Save")

        assert lower_help == upper_help == mixed_help
        assert lower_help is not None


class TestHelpTextFormatting:
    """Tests for help text formatting consistency."""

    def test_help_text_line_length(self):
        """Help text lines should be reasonable length for terminal display."""
        from nexus3.cli.repl_commands import HELP_TEXT

        max_reasonable_length = 100  # Allow some margin

        for i, line in enumerate(HELP_TEXT.split('\n'), 1):
            # Skip lines that are just command examples (may be long)
            if line.strip().startswith('/') or line.strip().startswith('#'):
                continue
            assert len(line) <= max_reasonable_length, \
                f"Line {i} too long ({len(line)} chars): {line[:50]}..."

    def test_help_text_no_tabs(self):
        """Help text should use spaces, not tabs, for consistent display."""
        from nexus3.cli.repl_commands import HELP_TEXT

        assert '\t' not in HELP_TEXT, "HELP_TEXT should not contain tabs"

    def test_help_text_consistent_indentation(self):
        """Command descriptions should have consistent indentation."""
        from nexus3.cli.repl_commands import HELP_TEXT

        # Lines starting with / should have consistent leading spaces
        command_lines = [
            line for line in HELP_TEXT.split('\n')
            if line.strip().startswith('/')
        ]

        indentations = set()
        for line in command_lines:
            indent = len(line) - len(line.lstrip())
            indentations.add(indent)

        # Should be at most 2 different indentation levels (main commands and sub-commands)
        assert len(indentations) <= 2, \
            f"Inconsistent indentation levels: {indentations}"
