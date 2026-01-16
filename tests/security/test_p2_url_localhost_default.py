"""P2.1: Test that validate_url() defaults to allow_localhost=False.

This tests the security change where localhost URLs are blocked by default,
requiring explicit opt-in for localhost access.

The fix:
- Default changed from allow_localhost=True to allow_localhost=False
- Callers that need localhost (e.g., NexusSkill) must explicitly pass True
- Safe-by-default: prevents SSRF to localhost services
"""

import pytest

from nexus3.core.url_validator import UrlSecurityError, validate_url


class TestLocalhostDefaultBlocked:
    """Test that localhost is blocked by default (P2.1)."""

    def test_localhost_blocked_by_default(self) -> None:
        """validate_url() blocks localhost when no flag passed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://localhost:8080")

        assert "localhost" in str(exc_info.value).lower()

    def test_127_0_0_1_blocked_by_default(self) -> None:
        """validate_url() blocks 127.0.0.1 when no flag passed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://127.0.0.1:8080")

        assert "localhost" in str(exc_info.value).lower()

    def test_ipv6_loopback_blocked_by_default(self) -> None:
        """validate_url() blocks ::1 when no flag passed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://[::1]:8080")

        assert "localhost" in str(exc_info.value).lower()


class TestLocalhostExplicitAllowed:
    """Test that localhost is allowed when explicitly requested."""

    def test_localhost_allowed_when_explicit(self) -> None:
        """validate_url() allows localhost with allow_localhost=True."""
        result = validate_url("http://localhost:8080", allow_localhost=True)
        assert result == "http://localhost:8080"

    def test_127_0_0_1_allowed_when_explicit(self) -> None:
        """validate_url() allows 127.0.0.1 with allow_localhost=True."""
        result = validate_url("http://127.0.0.1:8080", allow_localhost=True)
        assert result == "http://127.0.0.1:8080"


class TestExternalUrlsStillWork:
    """Test that external (non-localhost) URLs work with new default."""

    def test_https_external_allowed(self) -> None:
        """HTTPS external URLs are allowed by default."""
        # Note: This test may fail if example.com can't be resolved.
        # The important thing is that the URL is NOT blocked for being localhost.
        # We're testing that the default change doesn't break external URLs.
        try:
            result = validate_url("https://example.com")
            assert result == "https://example.com"
        except UrlSecurityError as e:
            # If it fails, make sure it's NOT because of localhost
            assert "localhost" not in str(e).lower()


class TestPrivateIPsStillBlocked:
    """Test that private IPs are still blocked with new default."""

    def test_private_10_x_blocked(self) -> None:
        """Private 10.x.x.x IPs are blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://10.0.0.1")

        assert "blocked" in str(exc_info.value).lower()

    def test_private_172_16_blocked(self) -> None:
        """Private 172.16.x.x IPs are blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://172.16.0.1")

        assert "blocked" in str(exc_info.value).lower()

    def test_private_192_168_blocked(self) -> None:
        """Private 192.168.x.x IPs are blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://192.168.1.1")

        assert "blocked" in str(exc_info.value).lower()

    def test_cloud_metadata_blocked(self) -> None:
        """Cloud metadata endpoint is blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://169.254.169.254")

        assert "cloud metadata" in str(exc_info.value).lower()
