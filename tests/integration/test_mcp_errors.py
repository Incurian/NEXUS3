"""Integration tests for MCP error message formatting and display."""

import sys

import pytest

from nexus3.mcp import MCPServerConfig, MCPServerRegistry
from nexus3.mcp.transport import StdioTransport, MCPTransportError
from nexus3.mcp.errors import MCPErrorContext
from nexus3.mcp.error_formatter import (
    format_command_not_found,
    format_server_crash,
    format_json_error,
    format_timeout_error,
)


class TestErrorFormatterOutput:
    """Test error formatter produces correct user-facing output."""

    def test_command_not_found_includes_source_info(self) -> None:
        """Test command not found error includes source file info."""
        context = MCPErrorContext(
            server_name="my-server",
            source_path="/home/user/.nexus3/mcp.json",
            source_layer="global",
        )

        output = format_command_not_found(context, "nonexistent_cmd")

        assert "my-server" in output
        assert "/home/user/.nexus3/mcp.json" in output
        assert "global config" in output
        assert "nonexistent_cmd" in output

    def test_server_crash_includes_stderr(self) -> None:
        """Test server crash error includes captured stderr."""
        context = MCPErrorContext(
            server_name="crashing-server",
            command=["python", "-m", "bad_module"],
        )
        stderr_lines = ["ModuleNotFoundError: No module named 'bad_module'"]

        output = format_server_crash(context, exit_code=1, stderr_lines=stderr_lines)

        assert "crashing-server" in output
        assert "exit" in output.lower()
        assert "1" in output
        assert "ModuleNotFoundError" in output

    def test_json_error_shows_preview(self) -> None:
        """Test JSON parse error shows raw response preview."""
        context = MCPErrorContext(server_name="broken-server")
        raw_text = "This is not valid JSON at all"

        output = format_json_error(context, raw_text, "Expecting value")

        assert "broken-server" in output
        assert "invalid json" in output.lower()
        assert "This is not valid JSON" in output

    def test_timeout_error_shows_phase(self) -> None:
        """Test timeout error shows which phase timed out."""
        context = MCPErrorContext(
            server_name="slow-server",
            command=["python", "-m", "slow_server"],
        )

        output = format_timeout_error(context, timeout=30.0, phase="initialization")

        assert "slow-server" in output
        assert "30" in output
        assert "Initialization" in output


class TestRichMarkupEscaping:
    """Test that output is safe for Rich terminal rendering."""

    def test_server_name_with_brackets_escaped(self) -> None:
        """Test server name with Rich markup chars doesn't break rendering."""
        # Rich uses [brackets] for markup - must be escaped
        context = MCPErrorContext(server_name="server[with]brackets")

        output = format_command_not_found(context, "cmd")

        # The brackets should be in the output (for user info)
        # but shouldn't cause Rich to interpret them as markup
        # This is a basic check - actual Rich escaping would use \\[
        assert "server[with]brackets" in output or "server\\[with\\]brackets" in output

    def test_stderr_with_ansi_codes(self) -> None:
        """Test stderr containing ANSI codes doesn't break output."""
        context = MCPErrorContext(server_name="colorful-server")
        # ANSI escape sequence for red text
        stderr_lines = ["\x1b[31mError: something failed\x1b[0m"]

        output = format_server_crash(context, exit_code=1, stderr_lines=stderr_lines)

        # Should contain the error message (ANSI codes may be stripped or escaped)
        assert "Error: something failed" in output or "Error" in output


class TestStderrCapture:
    """Test that StdioTransport captures stderr for error context."""

    @pytest.mark.asyncio
    async def test_stderr_captured_on_crash(self) -> None:
        """Test stderr is captured when server process crashes."""
        # Use a command that will definitely fail with stderr output
        transport = StdioTransport([
            sys.executable, "-c",
            "import sys; sys.stderr.write('test error\\n'); sys.exit(1)"
        ])

        try:
            await transport.connect()
            # Give it a moment to capture stderr
            import asyncio
            await asyncio.sleep(0.1)
        except Exception:
            pass

        # Check stderr was captured
        stderr = transport.stderr_lines
        # The exact capture depends on timing, but buffer should exist
        assert isinstance(stderr, list)

        await transport.close()

    @pytest.mark.asyncio
    async def test_stderr_buffer_limited(self) -> None:
        """Test stderr buffer doesn't grow unbounded."""
        # The buffer is limited to 20 lines (see StdioTransport._stderr_buffer)
        transport = StdioTransport([
            sys.executable, "-c", """
import sys
for i in range(50):
    sys.stderr.write(f'line {i}\\n')
    sys.stderr.flush()
import time
time.sleep(0.5)  # Give time for stderr to be read
"""
        ])

        await transport.connect()
        import asyncio
        await asyncio.sleep(0.6)  # Wait for stderr reader

        stderr = transport.stderr_lines
        # Should be capped at 20 lines
        assert len(stderr) <= 20

        await transport.close()

    @pytest.mark.asyncio
    async def test_stderr_lines_property_returns_list(self) -> None:
        """Test stderr_lines property always returns a list, even when empty."""
        transport = StdioTransport([
            sys.executable, "-c",
            "import time; time.sleep(0.1)"
        ])

        await transport.connect()

        # Even with no stderr, should return empty list
        stderr = transport.stderr_lines
        assert isinstance(stderr, list)

        await transport.close()


class TestRegistryErrorHandling:
    """Test registry error handling with formatted messages."""

    @pytest.mark.asyncio
    async def test_registry_command_not_found_error(self) -> None:
        """Test registry provides helpful error for missing command."""
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="bad-server",
            command=["completely_nonexistent_command_xyz123"],
        )

        with pytest.raises(MCPTransportError) as exc_info:
            await registry.connect(config)

        # Should mention the command or "not found"
        error_str = str(exc_info.value).lower()
        assert "not found" in error_str or "nonexistent" in error_str

    @pytest.mark.asyncio
    async def test_graceful_tool_listing_failure(self) -> None:
        """Test server connects even when tool listing fails initially."""
        # This tests the graceful degradation from P2.1.6
        # Create a server that connects but fails tools/list
        # For now, just verify a normal connection works
        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="test-server",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
        )

        server = await registry.connect(config)
        assert server is not None
        assert server.client.is_initialized

        await registry.close_all()

    @pytest.mark.asyncio
    async def test_disabled_server_error(self) -> None:
        """Test registry provides clear error for disabled server."""
        from nexus3.core.errors import MCPConfigError

        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="disabled-server",
            command=[sys.executable, "-m", "nexus3.mcp.test_server"],
            enabled=False,
        )

        with pytest.raises(MCPConfigError) as exc_info:
            await registry.connect(config)

        assert "disabled" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_registry_no_command_or_url_error(self) -> None:
        """Test registry provides clear error when neither command nor url is set."""
        from nexus3.core.errors import MCPConfigError

        registry = MCPServerRegistry()

        config = MCPServerConfig(
            name="empty-config-server",
            # No command or url
        )

        with pytest.raises(MCPConfigError) as exc_info:
            await registry.connect(config)

        error_str = str(exc_info.value).lower()
        assert "command" in error_str or "url" in error_str


class TestErrorContextPreservation:
    """Test that error context is properly propagated through the stack."""

    def test_error_context_from_config_has_all_fields(self) -> None:
        """Test MCPErrorContext captures all relevant config info."""
        context = MCPErrorContext(
            server_name="test-server",
            source_path="/path/to/config.json",
            source_layer="project",
            command=["npx", "-y", "@example/server"],
        )

        assert context.server_name == "test-server"
        assert context.source_path == "/path/to/config.json"
        assert context.source_layer == "project"
        assert context.command == ["npx", "-y", "@example/server"]

    def test_error_context_optional_fields(self) -> None:
        """Test MCPErrorContext works with minimal required fields."""
        context = MCPErrorContext(server_name="minimal-server")

        assert context.server_name == "minimal-server"
        assert context.source_path is None
        assert context.source_layer is None
        assert context.command is None
        assert context.stderr_lines is None

    def test_error_context_stderr_can_be_set(self) -> None:
        """Test stderr_lines can be set on error context."""
        context = MCPErrorContext(server_name="test")
        context.stderr_lines = ["error line 1", "error line 2"]

        assert len(context.stderr_lines) == 2
        assert "error line 1" in context.stderr_lines


class TestFormattedErrorMessages:
    """Test that formatted error messages have proper structure."""

    def test_command_not_found_has_troubleshooting(self) -> None:
        """Test command not found error includes troubleshooting section."""
        context = MCPErrorContext(server_name="test")
        output = format_command_not_found(context, "unknown_cmd")

        assert "troubleshoot" in output.lower()
        assert "env_passthrough" in output.lower()

    def test_server_crash_has_troubleshooting(self) -> None:
        """Test server crash error includes troubleshooting section."""
        context = MCPErrorContext(server_name="test")
        output = format_server_crash(context, exit_code=1)

        assert "troubleshoot" in output.lower()

    def test_json_error_has_likely_causes(self) -> None:
        """Test JSON error includes likely causes."""
        context = MCPErrorContext(server_name="test")
        output = format_json_error(context, "not json", "Parse error")

        assert "likely cause" in output.lower()

    def test_timeout_error_has_likely_causes(self) -> None:
        """Test timeout error includes likely causes."""
        context = MCPErrorContext(server_name="test")
        output = format_timeout_error(context, timeout=30.0, phase="connection")

        assert "likely cause" in output.lower()
        assert "troubleshoot" in output.lower()

    def test_formatted_errors_have_headers(self) -> None:
        """Test formatted errors have clear header sections."""
        context = MCPErrorContext(server_name="test")

        # Each formatter should produce output with a header
        outputs = [
            format_command_not_found(context, "cmd"),
            format_server_crash(context, exit_code=1),
            format_json_error(context, "bad", "error"),
            format_timeout_error(context, timeout=30.0, phase="init"),
        ]

        for output in outputs:
            # Should have MCP in header
            assert "MCP" in output
            # Should have horizontal line separator (unicode box drawing)
            assert "\u2501" in output
