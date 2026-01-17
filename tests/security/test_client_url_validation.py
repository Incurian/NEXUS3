"""Fix 2.1: Test URL validation in NexusClient.

This tests the security fix where NexusClient validates URLs on initialization
to prevent SSRF attacks via --connect.

The fix:
- NexusClient.__init__() validates URLs with allow_localhost=True, allow_private=True
- skip_url_validation=True bypasses checks for edge cases
- Dangerous URLs (cloud metadata, etc.) are rejected
- validate_url() gains allow_private parameter for RFC1918 addresses
"""

import pytest

from nexus3.client import NexusClient
from nexus3.core.url_validator import UrlSecurityError, validate_url


class TestValidateUrlAllowPrivate:
    """Test the new allow_private parameter in validate_url()."""

    def test_private_10_blocked_by_default(self) -> None:
        """Private 10.x.x.x is blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://10.0.0.1:8765", allow_localhost=True)
        assert "private network" in str(exc_info.value).lower()

    def test_private_172_16_blocked_by_default(self) -> None:
        """Private 172.16.x.x is blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://172.16.0.1:8765", allow_localhost=True)
        assert "private network" in str(exc_info.value).lower()

    def test_private_192_168_blocked_by_default(self) -> None:
        """Private 192.168.x.x is blocked by default."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://192.168.1.1:8765", allow_localhost=True)
        assert "private network" in str(exc_info.value).lower()

    def test_private_10_allowed_with_flag(self) -> None:
        """Private 10.x.x.x is allowed with allow_private=True."""
        result = validate_url("http://10.0.0.1:8765", allow_localhost=True, allow_private=True)
        assert result == "http://10.0.0.1:8765"

    def test_private_172_16_allowed_with_flag(self) -> None:
        """Private 172.16.x.x is allowed with allow_private=True."""
        result = validate_url("http://172.16.0.1:8765", allow_localhost=True, allow_private=True)
        assert result == "http://172.16.0.1:8765"

    def test_private_192_168_allowed_with_flag(self) -> None:
        """Private 192.168.x.x is allowed with allow_private=True."""
        result = validate_url("http://192.168.1.1:8765", allow_localhost=True, allow_private=True)
        assert result == "http://192.168.1.1:8765"

    def test_cloud_metadata_still_blocked_with_allow_private(self) -> None:
        """Cloud metadata is ALWAYS blocked, even with allow_private=True."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url(
                "http://169.254.169.254/latest/meta-data/",
                allow_localhost=True,
                allow_private=True,
            )
        assert "cloud metadata" in str(exc_info.value).lower()

    def test_localhost_still_needs_explicit_flag(self) -> None:
        """allow_private=True does not implicitly allow localhost."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://localhost:8765", allow_private=True)
        assert "localhost" in str(exc_info.value).lower()


class TestNexusClientUrlValidation:
    """Test NexusClient validates URLs on initialization."""

    def test_localhost_url_accepted(self) -> None:
        """Localhost URLs are accepted."""
        # Should not raise
        client = NexusClient(url="http://localhost:8765")
        assert client._url == "http://localhost:8765"

    def test_127_0_0_1_url_accepted(self) -> None:
        """127.0.0.1 URLs are accepted."""
        client = NexusClient(url="http://127.0.0.1:8765")
        assert client._url == "http://127.0.0.1:8765"

    def test_private_10_url_accepted(self) -> None:
        """Private 10.x.x.x URLs are accepted (for internal deployments)."""
        client = NexusClient(url="http://10.0.0.1:8765")
        assert client._url == "http://10.0.0.1:8765"

    def test_private_172_16_url_accepted(self) -> None:
        """Private 172.16.x.x URLs are accepted."""
        client = NexusClient(url="http://172.16.0.1:8765")
        assert client._url == "http://172.16.0.1:8765"

    def test_private_192_168_url_accepted(self) -> None:
        """Private 192.168.x.x URLs are accepted."""
        client = NexusClient(url="http://192.168.1.1:8765")
        assert client._url == "http://192.168.1.1:8765"

    def test_cloud_metadata_url_rejected(self) -> None:
        """Cloud metadata URLs are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NexusClient(url="http://169.254.169.254/")
        assert "Invalid server URL" in str(exc_info.value)
        assert "cloud metadata" in str(exc_info.value).lower()

    def test_link_local_url_rejected(self) -> None:
        """Link-local URLs (non-metadata 169.254.x.x) are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NexusClient(url="http://169.254.1.1:8765")
        # Link-local addresses are in blocked range
        assert "Invalid server URL" in str(exc_info.value)

    def test_none_url_uses_default(self) -> None:
        """None URL uses default localhost without validation."""
        client = NexusClient(url=None)
        assert "127.0.0.1" in client._url


class TestNexusClientSkipValidation:
    """Test the skip_url_validation escape hatch."""

    def test_skip_validation_allows_any_url(self) -> None:
        """skip_url_validation=True allows any URL."""
        # This would normally be blocked
        client = NexusClient(
            url="http://169.254.169.254/",
            skip_url_validation=True,
        )
        assert client._url == "http://169.254.169.254/"

    def test_skip_validation_default_false(self) -> None:
        """skip_url_validation defaults to False (validates by default)."""
        with pytest.raises(ValueError):
            NexusClient(url="http://169.254.169.254/")


class TestNexusClientUrlValidationEdgeCases:
    """Test edge cases in URL validation."""

    def test_https_urls_work(self) -> None:
        """HTTPS URLs are validated the same as HTTP."""
        # Localhost HTTPS should work
        client = NexusClient(url="https://localhost:8765")
        assert client._url == "https://localhost:8765"

    def test_url_with_path_validated(self) -> None:
        """URLs with paths are validated."""
        client = NexusClient(url="http://localhost:8765/agent/test")
        assert client._url == "http://localhost:8765/agent/test"

    def test_invalid_scheme_rejected(self) -> None:
        """Non-HTTP(S) schemes are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NexusClient(url="ftp://localhost:8765")
        assert "Invalid server URL" in str(exc_info.value)

    def test_empty_url_rejected(self) -> None:
        """Empty string URL is rejected."""
        with pytest.raises(ValueError) as exc_info:
            NexusClient(url="")
        assert "Invalid server URL" in str(exc_info.value)


class TestExternalUrlsAccepted:
    """Test that external (public) URLs are accepted."""

    def test_public_https_url_accepted(self) -> None:
        """Public HTTPS URLs are accepted.

        Note: This test may fail if DNS resolution fails. The key thing
        is that the URL is NOT blocked for being private/localhost.
        """
        try:
            client = NexusClient(url="https://example.com:8765")
            assert client._url == "https://example.com:8765"
        except ValueError as e:
            # If it fails, make sure it's NOT because of security validation
            # DNS failure is OK for this test
            if "resolve" not in str(e).lower():
                raise

    def test_public_ip_accepted(self) -> None:
        """Public IP addresses are accepted.

        Using 8.8.8.8 (Google DNS) as an example public IP.
        """
        # This should not raise - public IPs are allowed
        client = NexusClient(url="http://8.8.8.8:8765")
        assert client._url == "http://8.8.8.8:8765"
