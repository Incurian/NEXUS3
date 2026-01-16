"""Tests for P2.17a: MCP Transport/Client Logging Improvements.

These tests verify that silent exception handlers in MCP transport/client code
now log appropriately instead of silently swallowing errors.

Covered locations:
1. client.py: Timeout cleanup handler logs warning when transport close fails
2. transport.py: Stderr reader logs debug when exception occurs
3. transport.py: Stdin close logs debug when exception occurs during shutdown
"""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.mcp.client import MCPClient, MCPError
from nexus3.mcp.transport import MCPTransport, StdioTransport


class MockTransport(MCPTransport):
    """Mock transport for testing MCPClient."""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        close_error: Exception | None = None,
        connect_delay: float = 0,
    ):
        self.responses = responses or []
        self.response_index = 0
        self.sent_messages: list[dict[str, Any]] = []
        self.connected = False
        self.close_error = close_error
        self.connect_delay = connect_delay

    async def connect(self) -> None:
        if self.connect_delay > 0:
            await asyncio.sleep(self.connect_delay)
        self.connected = True

    async def send(self, message: dict[str, Any]) -> None:
        self.sent_messages.append(message)

    async def receive(self) -> dict[str, Any]:
        if self.response_index >= len(self.responses):
            # Block forever to trigger timeout
            await asyncio.sleep(1000)
        response = self.responses[self.response_index]
        self.response_index += 1
        return response

    async def close(self) -> None:
        if self.close_error:
            raise self.close_error
        self.connected = False


class TestClientTimeoutCleanupLogging:
    """Tests for P2.17a: client.py timeout cleanup logging."""

    @pytest.mark.asyncio
    async def test_cleanup_failure_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Transport close failure during timeout cleanup is logged as warning."""
        cleanup_error = RuntimeError("Failed to close transport")
        transport = MockTransport(
            responses=[],  # No responses - will timeout
            close_error=cleanup_error,
            connect_delay=10,  # Longer than timeout
        )

        client = MCPClient(transport)

        with caplog.at_level(logging.WARNING, logger="nexus3.mcp.client"):
            with pytest.raises(MCPError) as exc_info:
                await client.connect(timeout=0.01)  # Very short timeout

        assert "timed out" in str(exc_info.value)

        # Check that warning was logged
        assert len(caplog.records) >= 1
        warning_logged = any(
            "Failed to close transport during timeout cleanup" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        )
        assert warning_logged, f"Expected warning not found in logs: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_cleanup_failure_includes_error_details(self, caplog: pytest.LogCaptureFixture) -> None:
        """Cleanup failure log includes the error details."""
        cleanup_error = ValueError("Connection already closed")
        transport = MockTransport(
            responses=[],
            close_error=cleanup_error,
            connect_delay=10,
        )

        client = MCPClient(transport)

        with caplog.at_level(logging.WARNING, logger="nexus3.mcp.client"):
            with pytest.raises(MCPError):
                await client.connect(timeout=0.01)

        # Check error details are in the log
        assert any(
            "Connection already closed" in record.message
            for record in caplog.records
        ), f"Error details not found in logs: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_successful_cleanup_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Successful cleanup does not log warning."""
        transport = MockTransport(
            responses=[],
            close_error=None,  # Close succeeds
            connect_delay=10,
        )

        client = MCPClient(transport)

        with caplog.at_level(logging.WARNING, logger="nexus3.mcp.client"):
            with pytest.raises(MCPError):
                await client.connect(timeout=0.01)

        # No warning should be logged when close succeeds
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0, f"Unexpected warnings: {[r.message for r in warnings]}"


class TestStderrReaderLogging:
    """Tests for P2.17a: transport.py stderr reader logging."""

    @pytest.mark.asyncio
    async def test_stderr_reader_logs_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stderr reader logs debug message when exception occurs."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stderr = AsyncMock()

        # Simulate exception during readline
        mock_stderr.readline = AsyncMock(side_effect=OSError("Pipe broken"))
        mock_process.stderr = mock_stderr
        transport._process = mock_process

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport._read_stderr()

        # Check that debug message was logged
        assert any(
            "Stderr reader stopped" in record.message
            and record.levelno == logging.DEBUG
            for record in caplog.records
        ), f"Expected debug log not found: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_stderr_reader_includes_error_details(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stderr reader log includes the error details."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stderr = AsyncMock()

        mock_stderr.readline = AsyncMock(side_effect=ConnectionResetError("Connection reset by peer"))
        mock_process.stderr = mock_stderr
        transport._process = mock_process

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport._read_stderr()

        assert any(
            "Connection reset by peer" in record.message
            for record in caplog.records
        ), f"Error details not found in logs: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_stderr_reader_normal_eof_no_error_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Normal EOF (empty line) does not log an error."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stderr = AsyncMock()

        # Return empty bytes to signal EOF
        mock_stderr.readline = AsyncMock(return_value=b"")
        mock_process.stderr = mock_stderr
        transport._process = mock_process

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport._read_stderr()

        # EOF should not trigger the exception handler
        assert not any(
            "Stderr reader stopped" in record.message
            for record in caplog.records
        ), f"Unexpected error log on normal EOF: {[r.message for r in caplog.records]}"


class TestStdinCloseLogging:
    """Tests for P2.17a: transport.py stdin close logging."""

    @pytest.mark.asyncio
    async def test_stdin_close_logs_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stdin close failure logs debug message."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdin = MagicMock()

        # Mock stdin.close() to succeed but wait_closed() to fail
        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock(side_effect=BrokenPipeError("Pipe is broken"))

        mock_process.stdin = mock_stdin
        mock_process.returncode = 0  # Process already exited
        mock_process.wait = AsyncMock(return_value=0)

        transport._process = mock_process
        transport._stderr_task = None

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport.close()

        assert any(
            "Stdin close error" in record.message
            and record.levelno == logging.DEBUG
            for record in caplog.records
        ), f"Expected debug log not found: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_stdin_close_includes_error_details(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stdin close log includes error details."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdin = MagicMock()

        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock(side_effect=OSError("Stream is closed"))

        mock_process.stdin = mock_stdin
        mock_process.returncode = 0
        mock_process.wait = AsyncMock(return_value=0)

        transport._process = mock_process
        transport._stderr_task = None

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport.close()

        assert any(
            "Stream is closed" in record.message
            for record in caplog.records
        ), f"Error details not found in logs: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_stdin_close_indicates_expected_during_shutdown(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stdin close log message indicates this is expected during shutdown."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdin = MagicMock()

        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock(side_effect=ConnectionResetError("Reset"))

        mock_process.stdin = mock_stdin
        mock_process.returncode = 0
        mock_process.wait = AsyncMock(return_value=0)

        transport._process = mock_process
        transport._stderr_task = None

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport.close()

        assert any(
            "expected during shutdown" in record.message
            for record in caplog.records
        ), f"Expected 'expected during shutdown' not found: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_successful_stdin_close_no_error_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Successful stdin close does not log error."""
        transport = StdioTransport(["echo", "test"])

        mock_process = MagicMock()
        mock_stdin = MagicMock()

        mock_stdin.close = MagicMock()
        mock_stdin.wait_closed = AsyncMock()  # Succeeds

        mock_process.stdin = mock_stdin
        mock_process.returncode = 0
        mock_process.wait = AsyncMock(return_value=0)

        transport._process = mock_process
        transport._stderr_task = None

        with caplog.at_level(logging.DEBUG, logger="nexus3.mcp.transport"):
            await transport.close()

        # No stdin close error should be logged when it succeeds
        assert not any(
            "Stdin close error" in record.message
            for record in caplog.records
        ), f"Unexpected error log on successful close: {[r.message for r in caplog.records]}"
