"""P0.2: Test that auto-auth does not send local tokens to remote servers.

This tests the security bug where with_auto_auth() would discover and send
local RPC tokens to any URL, including remote servers controlled by attackers.

The fix gates token discovery to loopback addresses only:
- 127.0.0.1, localhost, ::1 -> auto-discovery enabled
- Any other host -> auto-discovery disabled (use explicit api_key)
"""

import pytest

from nexus3.client import NexusClient


class TestLoopbackDetection:
    """Test that loopback detection correctly classifies hosts."""

    @pytest.mark.parametrize(
        "host,expected",
        [
            # Loopback addresses (safe for auto-auth)
            ("127.0.0.1", True),
            ("localhost", True),
            ("LOCALHOST", True),  # Case insensitive
            ("::1", True),
            (None, True),  # Default URL is localhost

            # Non-loopback addresses (must NOT auto-auth)
            ("192.168.1.1", False),
            ("10.0.0.1", False),
            ("172.16.0.1", False),
            ("evil.com", False),
            ("example.com", False),
            ("127.0.0.1.evil.com", False),  # Subdomain trick
            ("localhost.evil.com", False),  # Subdomain trick
            ("0.0.0.0", False),  # Binds all interfaces, not loopback
        ],
    )
    def test_is_loopback(self, host: str | None, expected: bool) -> None:
        """Verify _is_loopback correctly classifies hosts."""
        result = NexusClient._is_loopback(host)
        assert result == expected, (
            f"Host '{host}' should be {'loopback' if expected else 'non-loopback'}"
        )


class TestAutoAuthTokenDiscovery:
    """Test that with_auto_auth only discovers tokens for loopback."""

    def test_loopback_enables_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Token discovery enabled for localhost."""
        # Mock discover_rpc_token to track calls
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "test_token"

        monkeypatch.setattr("nexus3.client.discover_rpc_token", mock_discover)

        client = NexusClient.with_auto_auth(url="http://localhost:8765")

        assert len(discovery_calls) == 1, "Token discovery should be called"
        assert discovery_calls[0] == 8765
        assert client._api_key == "test_token"

    def test_loopback_127_enables_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Token discovery enabled for 127.0.0.1."""
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "test_token"

        monkeypatch.setattr("nexus3.client.discover_rpc_token", mock_discover)

        client = NexusClient.with_auto_auth(url="http://127.0.0.1:9999")

        assert len(discovery_calls) == 1
        assert client._api_key == "test_token"

    def test_non_loopback_disables_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CRITICAL: Token discovery disabled for remote hosts.

        This is the P0.2 security fix - auto-auth must NOT discover tokens
        when connecting to non-loopback addresses.
        """
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "leaked_token"  # Would be leaked if called

        monkeypatch.setattr("nexus3.client.discover_rpc_token", mock_discover)

        # Connect to "remote" server
        client = NexusClient.with_auto_auth(url="http://evil.com:8765")

        assert len(discovery_calls) == 0, (
            "SECURITY BUG: Token discovery should NOT be called for remote hosts"
        )
        assert client._api_key is None, (
            "SECURITY BUG: No token should be set for remote hosts"
        )

    def test_subdomain_trick_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subdomain tricks like 'localhost.evil.com' must not bypass check."""
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "leaked_token"

        monkeypatch.setattr("nexus3.client.discover_rpc_token", mock_discover)

        # Attacker-controlled subdomain that looks like localhost
        client = NexusClient.with_auto_auth(url="http://localhost.evil.com:8765")

        assert len(discovery_calls) == 0, (
            "SECURITY BUG: Subdomain trick bypassed loopback check"
        )
        assert client._api_key is None

    def test_default_url_enables_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default URL (None -> localhost) should enable discovery."""
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "test_token"

        monkeypatch.setattr("nexus3.client.discover_rpc_token", mock_discover)

        client = NexusClient.with_auto_auth(url=None)

        assert len(discovery_calls) == 1, "Token discovery should be called for default URL"
        assert client._api_key == "test_token"


class TestReplClientSseDetectionTokenProtection:
    """Test that run_repl_client_with_sse_detection doesn't leak tokens to remote hosts.

    This tests the fix for the vulnerability where run_repl_client_with_sse_detection()
    would auto-discover local tokens and send them to ANY server URL, including remote
    attacker-controlled servers.

    We test this by mocking discover_rpc_token and verifying it's only called for
    loopback addresses.
    """

    @pytest.mark.asyncio
    async def test_loopback_enables_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Token discovery enabled for localhost."""
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "test_token"

        # Patch before importing the function to ensure our mock is used
        monkeypatch.setattr("nexus3.rpc.auth.discover_rpc_token", mock_discover)

        # Force reimport to pick up the mock
        import importlib

        import nexus3.cli.repl as repl_module
        importlib.reload(repl_module)

        try:
            await repl_module.run_repl_client_with_sse_detection(
                "http://localhost:8765", "main"
            )
        except Exception:
            pass  # Connection will fail, that's OK - we just check discovery

        assert len(discovery_calls) == 1, "Token discovery should be called for localhost"

    @pytest.mark.asyncio
    async def test_remote_host_disables_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CRITICAL: Token discovery disabled for remote hosts.

        This is the security fix for run_repl_client_with_sse_detection() -
        auto-discover must NOT discover tokens when connecting to non-loopback addresses.
        """
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "leaked_token"  # Would be leaked if called

        monkeypatch.setattr("nexus3.rpc.auth.discover_rpc_token", mock_discover)

        import importlib

        import nexus3.cli.repl as repl_module
        importlib.reload(repl_module)

        try:
            await repl_module.run_repl_client_with_sse_detection(
                "http://evil.com:8765", "main"
            )
        except Exception:
            pass

        assert len(discovery_calls) == 0, (
            "SECURITY BUG: Token discovery should NOT be called for remote hosts"
        )

    @pytest.mark.asyncio
    async def test_explicit_api_key_skips_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit API key should skip token discovery entirely."""
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "should_not_be_used"

        monkeypatch.setattr("nexus3.rpc.auth.discover_rpc_token", mock_discover)

        import importlib

        import nexus3.cli.repl as repl_module
        importlib.reload(repl_module)

        try:
            await repl_module.run_repl_client_with_sse_detection(
                "http://evil.com:8765", "main", api_key="explicit_key"
            )
        except Exception:
            pass

        # Discovery should not be called when explicit key is provided
        assert len(discovery_calls) == 0

    @pytest.mark.asyncio
    async def test_subdomain_trick_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subdomain tricks like 'localhost.evil.com' must not bypass check."""
        discovery_calls: list[int] = []

        def mock_discover(port: int) -> str | None:
            discovery_calls.append(port)
            return "leaked_token"

        monkeypatch.setattr("nexus3.rpc.auth.discover_rpc_token", mock_discover)

        import importlib

        import nexus3.cli.repl as repl_module
        importlib.reload(repl_module)

        try:
            await repl_module.run_repl_client_with_sse_detection(
                "http://localhost.evil.com:8765", "main"
            )
        except Exception:
            pass

        assert len(discovery_calls) == 0, (
            "SECURITY BUG: Subdomain trick bypassed loopback check"
        )
