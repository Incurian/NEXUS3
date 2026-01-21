"""Unit tests for MCP transport module."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.mcp.transport import SAFE_ENV_KEYS, StdioTransport, build_safe_env


class TestSafeEnvKeys:
    """Test the SAFE_ENV_KEYS constant."""

    def test_includes_path(self):
        """PATH is essential for finding executables."""
        assert "PATH" in SAFE_ENV_KEYS

    def test_includes_home(self):
        """HOME is needed for config file lookup."""
        assert "HOME" in SAFE_ENV_KEYS

    def test_includes_user(self):
        """USER identifies current user."""
        assert "USER" in SAFE_ENV_KEYS

    def test_includes_locale_vars(self):
        """Locale vars needed for character encoding."""
        assert "LANG" in SAFE_ENV_KEYS
        assert "LC_ALL" in SAFE_ENV_KEYS

    def test_does_not_include_api_keys(self):
        """API key vars should NOT be in safe keys."""
        assert "OPENROUTER_API_KEY" not in SAFE_ENV_KEYS
        assert "ANTHROPIC_API_KEY" not in SAFE_ENV_KEYS
        assert "OPENAI_API_KEY" not in SAFE_ENV_KEYS
        assert "AWS_SECRET_ACCESS_KEY" not in SAFE_ENV_KEYS
        assert "GITHUB_TOKEN" not in SAFE_ENV_KEYS

    def test_is_frozenset(self):
        """Should be immutable."""
        assert isinstance(SAFE_ENV_KEYS, frozenset)


class TestBuildSafeEnv:
    """Test the build_safe_env function."""

    def test_includes_only_safe_keys_by_default(self):
        """Without passthrough or explicit, only safe keys are included."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "OPENROUTER_API_KEY": "secret-key",
            "GITHUB_TOKEN": "ghp_xxx",
        }, clear=True):
            env = build_safe_env()

            assert env.get("PATH") == "/usr/bin"
            assert env.get("HOME") == "/home/user"
            assert "OPENROUTER_API_KEY" not in env
            assert "GITHUB_TOKEN" not in env

    def test_explicit_env_included(self):
        """Explicit env vars are included."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(explicit_env={"DATABASE_URL": "postgres://localhost/db"})

            assert env.get("DATABASE_URL") == "postgres://localhost/db"

    def test_passthrough_copies_from_host(self):
        """Passthrough vars are copied from host environment."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "GITHUB_TOKEN": "ghp_xxx",
            "AWS_KEY": "aws_secret",
        }, clear=True):
            env = build_safe_env(passthrough=["GITHUB_TOKEN"])

            assert env.get("GITHUB_TOKEN") == "ghp_xxx"
            assert "AWS_KEY" not in env  # Not in passthrough list

    def test_passthrough_ignores_missing_vars(self):
        """Passthrough vars that don't exist in host are ignored."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(passthrough=["NONEXISTENT_VAR"])

            assert "NONEXISTENT_VAR" not in env

    def test_explicit_overrides_passthrough(self):
        """Explicit env has priority over passthrough."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "MY_VAR": "from_host",
        }, clear=True):
            env = build_safe_env(
                explicit_env={"MY_VAR": "explicit_value"},
                passthrough=["MY_VAR"],
            )

            assert env.get("MY_VAR") == "explicit_value"

    def test_explicit_overrides_safe_keys(self):
        """Explicit env has priority over safe keys."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(explicit_env={"PATH": "/custom/path"})

            assert env.get("PATH") == "/custom/path"

    def test_empty_inputs(self):
        """Handles None and empty inputs gracefully."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            env = build_safe_env(explicit_env=None, passthrough=None)

            assert env.get("PATH") == "/usr/bin"

    def test_combined_usage(self):
        """Test realistic combined usage."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "LANG": "en_US.UTF-8",
            "GITHUB_TOKEN": "ghp_real_token",
            "AWS_SECRET_ACCESS_KEY": "aws_secret",
            "OPENROUTER_API_KEY": "openrouter_key",
        }, clear=True):
            env = build_safe_env(
                explicit_env={"DATABASE_URL": "postgres://localhost/mydb"},
                passthrough=["GITHUB_TOKEN"],
            )

            # Safe keys
            assert env.get("PATH") == "/usr/bin"
            assert env.get("HOME") == "/home/user"
            assert env.get("LANG") == "en_US.UTF-8"

            # Passthrough
            assert env.get("GITHUB_TOKEN") == "ghp_real_token"

            # Explicit
            assert env.get("DATABASE_URL") == "postgres://localhost/mydb"

            # Should NOT be present
            assert "AWS_SECRET_ACCESS_KEY" not in env
            assert "OPENROUTER_API_KEY" not in env


class TestStdioTransportBuffering:
    """Test stdio transport read buffering.

    These tests verify that _read_bounded_line properly buffers data
    when multiple responses arrive in a single read() call - common
    with buffered I/O (especially WSL→Windows subprocess).
    """

    @pytest.mark.asyncio
    async def test_multi_response_in_single_read(self):
        """When read() returns multiple lines, each call gets one line."""
        transport = StdioTransport(["dummy"])
        transport._process = MagicMock()

        # Simulate reading two complete JSON-RPC responses in one chunk
        response1 = b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
        response2 = b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
        combined = response1 + response2

        # First read() returns both responses, subsequent reads return empty
        read_calls = [combined, b""]
        call_idx = 0

        async def mock_read(n):
            nonlocal call_idx
            if call_idx < len(read_calls):
                result = read_calls[call_idx]
                call_idx += 1
                return result
            return b""

        transport._process.stdout = MagicMock()
        transport._process.stdout.read = mock_read

        # First call should return first response
        line1 = await transport._read_bounded_line()
        assert line1 == response1

        # Second call should return buffered second response (no new read needed)
        line2 = await transport._read_bounded_line()
        assert line2 == response2

    @pytest.mark.asyncio
    async def test_partial_line_in_buffer(self):
        """Buffer handles partial lines that span multiple reads."""
        transport = StdioTransport(["dummy"])
        transport._process = MagicMock()

        # First read: incomplete line, Second read: rest of line + next line
        chunk1 = b'{"jsonrpc":"2.0",'
        chunk2 = b'"id":1,"result":{}}\n{"jsonrpc":"2.0","id":2}\n'

        read_calls = [chunk1, chunk2, b""]
        call_idx = 0

        async def mock_read(n):
            nonlocal call_idx
            if call_idx < len(read_calls):
                result = read_calls[call_idx]
                call_idx += 1
                return result
            return b""

        transport._process.stdout = MagicMock()
        transport._process.stdout.read = mock_read

        # First call should return complete first response
        line1 = await transport._read_bounded_line()
        assert line1 == b'{"jsonrpc":"2.0","id":1,"result":{}}\n'

        # Second call should return buffered second response
        line2 = await transport._read_bounded_line()
        assert line2 == b'{"jsonrpc":"2.0","id":2}\n'

    @pytest.mark.asyncio
    async def test_buffer_cleared_on_close(self):
        """Close clears any buffered data."""
        transport = StdioTransport(["dummy"])
        transport._read_buffer = b"leftover data"
        transport._process = None  # Already closed
        transport._stderr_task = None

        await transport.close()

        assert transport._read_buffer == b""

    @pytest.mark.asyncio
    async def test_complete_line_in_buffer_no_read_needed(self):
        """If buffer has complete line, no read() is called."""
        transport = StdioTransport(["dummy"])
        transport._process = MagicMock()

        # Pre-fill buffer with a complete line
        transport._read_buffer = b'{"id":1}\n{"id":2}\n'

        # read() should NOT be called
        read_called = False

        async def mock_read(n):
            nonlocal read_called
            read_called = True
            return b""

        transport._process.stdout = MagicMock()
        transport._process.stdout.read = mock_read

        line = await transport._read_bounded_line()

        assert line == b'{"id":1}\n'
        assert not read_called  # Buffer had complete line
        assert transport._read_buffer == b'{"id":2}\n'  # Rest still buffered
