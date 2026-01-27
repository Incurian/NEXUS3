"""Security tests for MCP security fixes.

Tests for:
- S5: SSRF redirect bypass prevention (HTTPTransport follow_redirects=False)
- S6: MCP output injection prevention (sanitize_for_display on MCP results)
- S7: Oversized MCP response truncation (MAX_MCP_OUTPUT_SIZE limit)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.text_safety import sanitize_for_display
from nexus3.core.types import ToolResult
from nexus3.mcp.protocol import MAX_MCP_OUTPUT_SIZE, MCPToolResult
from nexus3.mcp.skill_adapter import MCPSkillAdapter
from nexus3.mcp.transport import HTTPTransport, MCPTransportError

# =============================================================================
# S5: SSRF Redirect Bypass Prevention
# =============================================================================


class TestSSRFRedirectBypass:
    """Tests for S5: SSRF redirect bypass prevention.

    HTTPTransport must have follow_redirects=False to prevent SSRF bypass attacks
    where an attacker-controlled server returns a redirect to an internal URL.
    """

    @pytest.mark.asyncio
    async def test_http_transport_follow_redirects_false(self) -> None:
        """HTTPTransport must have follow_redirects=False set."""
        # httpx is imported inside connect(), so we patch at the import location
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            import sys

            mock_httpx = sys.modules["httpx"]
            mock_client = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client

            transport = HTTPTransport("http://localhost:8080")
            await transport.connect()

            # Verify AsyncClient was called with follow_redirects=False
            mock_httpx.AsyncClient.assert_called_once()
            call_kwargs = mock_httpx.AsyncClient.call_args[1]
            assert call_kwargs.get("follow_redirects") is False, (
                "HTTPTransport must have follow_redirects=False to prevent SSRF bypass"
            )

    @pytest.mark.asyncio
    async def test_redirect_response_not_followed(self) -> None:
        """Verify that redirect responses are not automatically followed.

        When a redirect (3xx) response is received, it should raise an error
        rather than following the redirect to a potentially dangerous URL.
        """
        # httpx is imported inside connect(), so we patch at the import location
        with patch.dict("sys.modules", {"httpx": MagicMock()}):
            import sys

            mock_httpx = sys.modules["httpx"]
            mock_client = AsyncMock()
            mock_httpx.AsyncClient.return_value = mock_client

            # Simulate a redirect response (302)
            mock_response = MagicMock()
            mock_response.status_code = 302
            mock_response.headers = {"Location": "http://internal-server/admin"}
            mock_response.raise_for_status.side_effect = Exception(
                "Client error '302 Found'"
            )

            mock_client.post = AsyncMock(return_value=mock_response)

            transport = HTTPTransport("http://attacker-server.com/mcp")
            await transport.connect()

            # Sending a message should fail because redirects aren't followed
            # and the 302 response will raise an error
            with pytest.raises(MCPTransportError) as exc_info:
                await transport.send({"jsonrpc": "2.0", "method": "test"})

            assert "HTTP request failed" in str(exc_info.value)

    def test_http_transport_validates_url_on_init(self) -> None:
        """HTTPTransport should validate URL on initialization."""
        # Valid localhost URL should work
        transport = HTTPTransport("http://localhost:8080")
        assert transport._url == "http://localhost:8080"

        # Internal IP ranges should be blocked (SSRF protection)
        with pytest.raises(MCPTransportError) as exc_info:
            HTTPTransport("http://169.254.169.254/latest/meta-data")

        assert "Invalid MCP server URL" in str(exc_info.value)


# =============================================================================
# S6: MCP Output Injection Prevention
# =============================================================================


class TestMCPOutputInjection:
    """Tests for S6: MCP output injection prevention.

    MCP tool output must be sanitized before being returned to prevent:
    - ANSI escape sequence injection (terminal attacks)
    - Rich markup injection (UI manipulation)
    """

    @pytest.mark.asyncio
    async def test_mcp_skill_adapter_sanitizes_output(self) -> None:
        """MCPSkillAdapter must sanitize MCP tool output."""
        from nexus3.mcp.client import MCPClient
        from nexus3.mcp.protocol import MCPTool

        # Create mock MCP client and tool
        mock_client = MagicMock(spec=MCPClient)

        # MCP result with malicious content
        malicious_output = "\x1b[31m[red]ATTACK[/red]\x1b[0m"
        mock_mcp_result = MCPToolResult(
            content=[{"type": "text", "text": malicious_output}],
            is_error=False,
        )
        mock_client.call_tool = AsyncMock(return_value=mock_mcp_result)

        tool = MCPTool(
            name="malicious_tool",
            description="A tool that returns malicious content",
            input_schema={},
        )

        adapter = MCPSkillAdapter(mock_client, tool, "test_server")

        # Execute the adapter
        result = await adapter.execute()

        # Verify the output is sanitized
        assert isinstance(result, ToolResult)
        assert result.output is not None

        # ANSI escape sequences should be stripped
        assert "\x1b[31m" not in result.output
        assert "\x1b[0m" not in result.output

        # Rich markup should be escaped
        assert "\\[red]" in result.output

    @pytest.mark.asyncio
    async def test_mcp_skill_adapter_sanitizes_error_output(self) -> None:
        """MCPSkillAdapter must sanitize error output too."""
        from nexus3.mcp.client import MCPClient
        from nexus3.mcp.protocol import MCPTool

        mock_client = MagicMock(spec=MCPClient)

        # MCP error result with malicious content
        malicious_error = "[bold]Error:[/bold] \x1b[5mBLINKING\x1b[0m attack"
        mock_mcp_result = MCPToolResult(
            content=[{"type": "text", "text": malicious_error}],
            is_error=True,
        )
        mock_client.call_tool = AsyncMock(return_value=mock_mcp_result)

        tool = MCPTool(
            name="error_tool",
            description="A tool that returns malicious errors",
            input_schema={},
        )

        adapter = MCPSkillAdapter(mock_client, tool, "test_server")
        result = await adapter.execute()

        # Verify error output is also sanitized
        assert result.error is not None

        # ANSI escape sequences stripped
        assert "\x1b[5m" not in result.error
        assert "\x1b[0m" not in result.error

        # Rich markup escaped
        assert "\\[bold]" in result.error

    def test_sanitize_ansi_escape_sequences(self) -> None:
        """Test that ANSI escape sequences are properly stripped."""
        test_cases = [
            # Color codes
            ("\x1b[31mred text\x1b[0m", "red text"),
            # Cursor movement
            ("\x1b[2Amove up\x1b[2B", "move up"),
            # Clear screen
            ("\x1b[2Jcleared\x1b[H", "cleared"),
            # Title change (OSC)
            ("\x1b]0;Evil Title\x07normal text", "normal text"),
            # Clipboard attack (OSC 52)
            ("\x1b]52;c;YmFkZGF0YQ==\x07safe", "safe"),
        ]

        for malicious, expected in test_cases:
            result = sanitize_for_display(malicious)
            # ANSI sequences should be stripped, safe text preserved
            assert "\x1b" not in result
            assert expected in result

    def test_sanitize_rich_markup(self) -> None:
        """Test that Rich markup is properly escaped."""
        test_cases = [
            # Bold tag
            ("[bold]text[/bold]", "\\[bold]text\\[/bold]"),
            # Color tag
            ("[red]danger[/red]", "\\[red]danger\\[/red]"),
            # Link tag (phishing risk)
            (
                "[link=http://evil.com]Click me[/link]",
                "\\[link=http://evil.com]Click me\\[/link]",
            ),
            # Nested tags
            (
                "[bold][red]nested[/red][/bold]",
                "\\[bold]\\[red]nested\\[/red]\\[/bold]",
            ),
        ]

        for malicious, expected in test_cases:
            result = sanitize_for_display(malicious)
            assert result == expected

    def test_sanitize_combined_attacks(self) -> None:
        """Test sanitization of combined ANSI and Rich markup attacks."""
        # Combined attack: ANSI color + Rich markup + control chars
        malicious = "\x00\x1b[31m[red]ATTACK[/red]\x1b[0m\x07"
        result = sanitize_for_display(malicious)

        # NUL byte stripped
        assert "\x00" not in result
        # BEL stripped
        assert "\x07" not in result
        # ANSI stripped
        assert "\x1b" not in result
        # Rich markup escaped
        assert "\\[red]" in result
        # Actual text preserved
        assert "ATTACK" in result

    def test_sanitize_preserves_safe_content(self) -> None:
        """Test that sanitization preserves safe content."""
        safe_text = "Normal text with newlines\nand\ttabs"
        result = sanitize_for_display(safe_text)
        assert result == safe_text


# =============================================================================
# S7: Oversized MCP Response Truncation
# =============================================================================


class TestOversizedMCPResponse:
    """Tests for S7: Oversized MCP response truncation.

    MCPToolResult.to_text() must truncate content exceeding MAX_MCP_OUTPUT_SIZE
    to prevent memory exhaustion from malicious MCP servers.
    """

    def test_max_mcp_output_size_constant(self) -> None:
        """MAX_MCP_OUTPUT_SIZE constant is defined and reasonable."""
        assert MAX_MCP_OUTPUT_SIZE > 0
        assert MAX_MCP_OUTPUT_SIZE == 10 * 1024 * 1024  # 10 MB

    def test_content_under_limit_not_truncated(self) -> None:
        """Content under MAX_MCP_OUTPUT_SIZE is returned unchanged."""
        small_content = "Small response"
        result = MCPToolResult(
            content=[{"type": "text", "text": small_content}],
            is_error=False,
        )

        text = result.to_text()
        assert text == small_content
        assert "truncated" not in text.lower()

    def test_content_exactly_at_limit_not_truncated(self) -> None:
        """Content exactly at MAX_MCP_OUTPUT_SIZE is returned unchanged."""
        exact_content = "x" * MAX_MCP_OUTPUT_SIZE
        result = MCPToolResult(
            content=[{"type": "text", "text": exact_content}],
            is_error=False,
        )

        text = result.to_text()
        assert len(text) == MAX_MCP_OUTPUT_SIZE
        assert "truncated" not in text.lower()

    def test_content_over_limit_truncated(self) -> None:
        """Content exceeding MAX_MCP_OUTPUT_SIZE is truncated."""
        # Create content that exceeds the limit
        oversized_content = "x" * (MAX_MCP_OUTPUT_SIZE + 1000)
        result = MCPToolResult(
            content=[{"type": "text", "text": oversized_content}],
            is_error=False,
        )

        text = result.to_text()

        # Should be truncated
        assert len(text) < len(oversized_content)
        # Should have truncation message
        assert "truncated" in text.lower()
        assert "10MB" in text or "10" in text  # Size limit mentioned

    def test_multiple_items_total_exceeds_limit(self) -> None:
        """Multiple content items whose total exceeds limit are truncated."""
        # Create multiple items that together exceed the limit
        item_size = MAX_MCP_OUTPUT_SIZE // 2 + 1000
        result = MCPToolResult(
            content=[
                {"type": "text", "text": "x" * item_size},
                {"type": "text", "text": "y" * item_size},
            ],
            is_error=False,
        )

        text = result.to_text()

        # Should be truncated before reaching total size of both items
        assert len(text) < item_size * 2
        # Should have truncation message
        assert "truncated" in text.lower()

    def test_truncation_message_format(self) -> None:
        """Verify truncation message format is informative."""
        oversized_content = "x" * (MAX_MCP_OUTPUT_SIZE + 100)
        result = MCPToolResult(
            content=[{"type": "text", "text": oversized_content}],
            is_error=False,
        )

        text = result.to_text()

        # Truncation message should include:
        # 1. The word "truncated"
        # 2. The size limit
        assert "truncated" in text.lower()
        # Check for size limit in MB
        limit_mb = MAX_MCP_OUTPUT_SIZE // 1024 // 1024
        assert str(limit_mb) in text or "10MB" in text.replace(" ", "")

    def test_non_text_content_ignored(self) -> None:
        """Non-text content items are ignored in size calculation."""
        result = MCPToolResult(
            content=[
                {"type": "image", "data": "x" * 1000000},  # Should be ignored
                {"type": "text", "text": "Hello"},
            ],
            is_error=False,
        )

        text = result.to_text()
        assert text == "Hello"
        assert "truncated" not in text.lower()

    def test_empty_content(self) -> None:
        """Empty content returns empty string."""
        result = MCPToolResult(content=[], is_error=False)
        text = result.to_text()
        assert text == ""

    def test_no_text_items(self) -> None:
        """Content with no text items returns empty string."""
        result = MCPToolResult(
            content=[
                {"type": "image", "data": "base64..."},
                {"type": "binary", "data": "..."},
            ],
            is_error=False,
        )

        text = result.to_text()
        assert text == ""


class TestMCPSecurityIntegration:
    """Integration tests combining multiple security features."""

    @pytest.mark.asyncio
    async def test_oversized_malicious_output_sanitized_and_truncated(self) -> None:
        """Oversized malicious output should be both truncated and sanitized."""
        from nexus3.mcp.client import MCPClient
        from nexus3.mcp.protocol import MCPTool

        mock_client = MagicMock(spec=MCPClient)

        # Create oversized content with injection attempts
        # (though in practice this would be truncated before sanitization matters)
        malicious_prefix = "\x1b[31m[red]"
        malicious_suffix = "[/red]\x1b[0m"
        payload = "x" * (MAX_MCP_OUTPUT_SIZE + 1000)
        full_malicious = malicious_prefix + payload + malicious_suffix

        mock_mcp_result = MCPToolResult(
            content=[{"type": "text", "text": full_malicious}],
            is_error=False,
        )
        mock_client.call_tool = AsyncMock(return_value=mock_mcp_result)

        tool = MCPTool(name="attack_tool", description="", input_schema={})
        adapter = MCPSkillAdapter(mock_client, tool, "test_server")

        result = await adapter.execute()

        # Output should be truncated (not full length)
        assert result.output is not None
        assert len(result.output) < len(full_malicious)

        # Output should also be sanitized
        assert "\x1b" not in result.output

    def test_mcp_tool_result_text_extraction(self) -> None:
        """MCPToolResult.to_text() properly extracts text content."""
        result = MCPToolResult(
            content=[
                {"type": "text", "text": "First line"},
                {"type": "image", "data": "ignored"},
                {"type": "text", "text": "Second line"},
            ],
            is_error=False,
        )

        text = result.to_text()
        assert "First line" in text
        assert "Second line" in text
        assert "ignored" not in text
        # Text items should be joined with newlines
        assert text == "First line\nSecond line"
