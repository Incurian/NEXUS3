"""Unit tests for MCP error formatting."""

from unittest.mock import patch

import pytest
from nexus3.mcp.errors import MCPErrorContext
from nexus3.mcp.error_formatter import (
    format_config_validation_error,
    format_command_not_found,
    format_server_crash,
    format_json_error,
    format_timeout_error,
)


class TestFormatConfigValidationError:
    def test_basic_error(self):
        context = MCPErrorContext(server_name="test-server")
        result = format_config_validation_error(context, "command", "Invalid type")
        assert "test-server" in result
        assert "Invalid type" in result

    def test_with_source_path(self):
        context = MCPErrorContext(
            server_name="test",
            source_path="/home/user/.nexus3/mcp.json",
            source_layer="global",
        )
        result = format_config_validation_error(context, "url", "Missing field")
        assert "global config" in result
        assert "mcp.json" in result

    def test_no_context(self):
        result = format_config_validation_error(None, "field", "Error message")
        assert "Error message" in result

    def test_with_provided_value(self):
        context = MCPErrorContext(server_name="test")
        result = format_config_validation_error(
            context, "timeout", "Must be positive", provided_value="-5"
        )
        assert "test" in result
        assert "Must be positive" in result
        assert "You provided: -5" in result

    def test_with_expected_format(self):
        context = MCPErrorContext(server_name="test")
        result = format_config_validation_error(
            context, "url", "Invalid URL", expected_format="http(s)://host:port"
        )
        assert "Invalid URL" in result
        assert "Expected:" in result
        assert "http(s)://host:port" in result


class TestFormatCommandNotFound:
    def test_npx_command(self):
        context = MCPErrorContext(server_name="github")
        result = format_command_not_found(context, "npx")
        assert "npx" in result
        assert "Node.js" in result
        assert "nodejs.org" in result

    def test_npm_command(self):
        context = MCPErrorContext(server_name="github")
        result = format_command_not_found(context, "npm")
        assert "npm" in result
        assert "Node.js" in result

    def test_node_command(self):
        context = MCPErrorContext(server_name="github")
        result = format_command_not_found(context, "node")
        assert "node" in result
        assert "Node.js" in result

    def test_python_command(self):
        context = MCPErrorContext(server_name="python-server")
        result = format_command_not_found(context, "python3")
        assert "python3" in result
        assert "Python" in result

    def test_python_pip_command(self):
        context = MCPErrorContext(server_name="python-server")
        result = format_command_not_found(context, "pip")
        assert "pip" in result
        assert "Python" in result

    def test_uvx_command(self):
        context = MCPErrorContext(server_name="uv-server")
        result = format_command_not_found(context, "uvx")
        assert "uvx" in result
        assert "uv" in result
        assert "astral.sh" in result

    def test_docker_command(self):
        context = MCPErrorContext(server_name="docker-server")
        result = format_command_not_found(context, "docker")
        assert "docker" in result
        assert "daemon" in result

    def test_podman_command(self):
        context = MCPErrorContext(server_name="podman-server")
        result = format_command_not_found(context, "podman")
        assert "podman" in result
        assert "daemon" in result

    def test_generic_command(self):
        context = MCPErrorContext(server_name="custom")
        result = format_command_not_found(context, "custom-binary")
        assert "custom-binary" in result
        assert "env_passthrough" in result

    def test_with_source_path(self):
        context = MCPErrorContext(
            server_name="test",
            source_path="/path/to/mcp.json",
            source_layer="project",
        )
        result = format_command_not_found(context, "some-cmd")
        assert "test" in result
        assert "project config" in result
        assert "mcp.json" in result


class TestFormatServerCrash:
    def test_with_exit_code(self):
        context = MCPErrorContext(server_name="test")
        result = format_server_crash(context, exit_code=1, stderr_lines=["Error: failed"])
        assert "exit" in result.lower() or "code 1" in result
        assert "Error: failed" in result

    def test_with_stderr_lines(self):
        context = MCPErrorContext(server_name="test", command=["npx", "server"])
        stderr = ["line1", "line2", "Error: connection refused"]
        result = format_server_crash(context, exit_code=1, stderr_lines=stderr)
        assert "connection refused" in result

    def test_exit_code_1_hint(self):
        context = MCPErrorContext(server_name="test")
        result = format_server_crash(context, exit_code=1)
        assert "configuration" in result.lower() or "startup error" in result.lower()

    def test_exit_code_127_hint(self):
        context = MCPErrorContext(server_name="test")
        result = format_server_crash(context, exit_code=127)
        assert "not found" in result.lower()

    def test_exit_code_126_hint(self):
        context = MCPErrorContext(server_name="test")
        result = format_server_crash(context, exit_code=126)
        assert "permission" in result.lower()

    def test_signal_exit_code(self):
        context = MCPErrorContext(server_name="test")
        result = format_server_crash(context, exit_code=137)  # 128 + SIGKILL(9)
        assert "signal" in result.lower()
        assert "9" in result  # signal number

    def test_no_exit_code(self):
        context = MCPErrorContext(server_name="test")
        result = format_server_crash(context, exit_code=None)
        assert "terminated unexpectedly" in result.lower()

    def test_with_command(self):
        context = MCPErrorContext(server_name="test", command=["npx", "-y", "server"])
        result = format_server_crash(context, exit_code=1)
        assert "npx" in result or "Command:" in result

    def test_stderr_truncation(self):
        """Test that only the last 10 lines of stderr are shown."""
        context = MCPErrorContext(server_name="test")
        stderr = [f"line{i}" for i in range(20)]
        result = format_server_crash(context, exit_code=1, stderr_lines=stderr)
        # Last 10 lines should be shown
        assert "line10" in result
        assert "line19" in result
        # First lines should be truncated
        assert "line0" not in result


class TestFormatJsonError:
    def test_basic_json_error(self):
        context = MCPErrorContext(server_name="test")
        result = format_json_error(context, raw_text="not json", error_msg="Expecting value")
        assert "test" in result
        assert "invalid json" in result.lower()  # "Server sent invalid JSON"
        assert "not json" in result

    def test_with_line_column(self):
        context = MCPErrorContext(server_name="test")
        result = format_json_error(
            context, raw_text="{bad}", error_msg="Expecting property name", line=1, column=2
        )
        assert "line 1" in result
        assert "column 2" in result

    def test_long_raw_text_truncation(self):
        context = MCPErrorContext(server_name="test")
        long_text = "x" * 300
        result = format_json_error(context, raw_text=long_text, error_msg="Parse error")
        assert "..." in result  # Should be truncated
        # Only the preview is truncated, but the full message includes other text
        # Just verify the raw text itself is truncated (200 chars + "...")
        assert long_text not in result  # Full text should not appear

    def test_troubleshooting_hints(self):
        context = MCPErrorContext(server_name="test")
        result = format_json_error(context, raw_text="debug output", error_msg="Error")
        assert "debug" in result.lower() or "stdout" in result.lower()
        assert "protocol" in result.lower() or "JSON-RPC" in result

    def test_no_context(self):
        result = format_json_error(None, raw_text="bad", error_msg="Parse error")
        assert "invalid json" in result.lower()  # "Server sent invalid JSON"
        assert "Parse error" in result


class TestFormatTimeoutError:
    def test_connection_timeout(self):
        context = MCPErrorContext(server_name="slow-server")
        result = format_timeout_error(context, timeout=30.0, phase="connection")
        assert "30" in result
        assert "slow-server" in result
        assert "connection" in result.lower() or "Connection" in result

    def test_tool_call_timeout(self):
        context = MCPErrorContext(server_name="test")
        result = format_timeout_error(context, timeout=60.0, phase="tool_call")
        assert "tool" in result.lower() or "60" in result

    def test_request_timeout(self):
        context = MCPErrorContext(server_name="test")
        result = format_timeout_error(context, timeout=45.0, phase="request")
        assert "45" in result

    def test_initialization_timeout(self):
        context = MCPErrorContext(server_name="test")
        result = format_timeout_error(context, timeout=30.0, phase="initialization")
        assert "initialization" in result.lower() or "start" in result.lower()
        # Should have stdout hint for init timeouts
        assert "stdout" in result.lower()

    def test_generic_phase_timeout(self):
        context = MCPErrorContext(server_name="test")
        result = format_timeout_error(context, timeout=10.0, phase="custom_operation")
        assert "10" in result
        assert "custom_operation" in result.lower() or "operation" in result.lower()

    def test_with_source_info(self):
        context = MCPErrorContext(
            server_name="test",
            source_path="/home/user/.nexus3/mcp.json",
            source_layer="global",
        )
        result = format_timeout_error(context, timeout=30.0, phase="connection")
        assert "global config" in result
        assert "mcp.json" in result

    def test_with_command(self):
        context = MCPErrorContext(
            server_name="test",
            command=["npx", "-y", "@modelcontextprotocol/server-github"],
        )
        result = format_timeout_error(context, timeout=30.0, phase="connection")
        assert "npx" in result or "Command:" in result

    def test_troubleshooting_hints(self):
        context = MCPErrorContext(server_name="test")
        result = format_timeout_error(context, timeout=30.0, phase="connection")
        # Should have troubleshooting section
        assert "troubleshoot" in result.lower()
        # Should suggest running command manually
        assert "manually" in result.lower()


class TestFormatCommandNotFoundWindowsHints:
    """Tests for Windows-specific hints in command not found errors."""

    def test_windows_uses_where_command(self):
        """On Windows, should suggest 'where' instead of 'which'."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "win32"):
            result = format_command_not_found(context, "npx")
        assert "where npx" in result
        assert "which npx" not in result

    def test_unix_uses_which_command(self):
        """On Unix, should suggest 'which' command."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "linux"):
            result = format_command_not_found(context, "npx")
        assert "which npx" in result
        assert "where npx" not in result

    def test_windows_pathext_hint(self):
        """On Windows, should mention PATHEXT for extension resolution."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "win32"):
            result = format_command_not_found(context, "npx")
        assert "PATHEXT" in result
        assert ".exe" in result
        assert ".cmd" in result
        assert ".bat" in result

    def test_windows_cmd_files_hint(self):
        """On Windows, should mention that Node.js tools install as .cmd files."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "win32"):
            result = format_command_not_found(context, "npx")
        assert ".cmd files on Windows" in result

    def test_windows_hints_for_generic_command(self):
        """Windows hints should also appear for generic commands."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "win32"):
            result = format_command_not_found(context, "custom-binary")
        assert "where custom-binary" in result
        assert "PATHEXT" in result
        assert ".cmd files on Windows" in result

    def test_unix_no_windows_hints(self):
        """On Unix, Windows-specific hints should not appear."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "linux"):
            result = format_command_not_found(context, "npx")
        assert "PATHEXT" not in result
        assert ".cmd files on Windows" not in result

    def test_windows_hints_for_python_command(self):
        """Windows hints should appear for Python commands too."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "win32"):
            result = format_command_not_found(context, "python")
        assert "where python" in result
        assert "PATHEXT" in result

    def test_windows_hints_for_docker_command(self):
        """Windows hints should appear for Docker commands too."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "win32"):
            result = format_command_not_found(context, "docker")
        assert "where docker" in result
        assert "PATHEXT" in result

    def test_darwin_uses_which_command(self):
        """On macOS (darwin), should suggest 'which' command."""
        context = MCPErrorContext(server_name="test")
        with patch("nexus3.mcp.error_formatter.sys.platform", "darwin"):
            result = format_command_not_found(context, "npx")
        assert "which npx" in result
        assert "where npx" not in result
        assert "PATHEXT" not in result
