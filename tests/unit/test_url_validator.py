"""Unit tests for nexus3.core.url_validator module (SSRF protection)."""

import socket
from unittest.mock import patch

import pytest

from nexus3.core.errors import NexusError
from nexus3.core.url_validator import UrlSecurityError, validate_url


class TestUrlSecurityError:
    """Tests for UrlSecurityError exception class."""

    def test_exception_has_url_attribute(self):
        """UrlSecurityError stores the url attribute."""
        err = UrlSecurityError("http://example.com", "test reason")
        assert err.url == "http://example.com"

    def test_exception_has_reason_attribute(self):
        """UrlSecurityError stores the reason attribute."""
        err = UrlSecurityError("http://example.com", "blocked by policy")
        assert err.reason == "blocked by policy"

    def test_exception_message_includes_url(self):
        """UrlSecurityError message includes the URL."""
        err = UrlSecurityError("http://test.local", "not allowed")
        assert "http://test.local" in str(err)

    def test_exception_message_includes_reason(self):
        """UrlSecurityError message includes the reason."""
        err = UrlSecurityError("http://test.local", "cloud metadata endpoint")
        assert "cloud metadata endpoint" in str(err)

    def test_inherits_from_nexus_error(self):
        """UrlSecurityError inherits from NexusError."""
        assert issubclass(UrlSecurityError, NexusError)

    def test_can_be_caught_as_nexus_error(self):
        """UrlSecurityError can be caught as NexusError."""
        try:
            raise UrlSecurityError("http://bad.url", "blocked")
        except NexusError as e:
            assert hasattr(e, "url")
            assert hasattr(e, "reason")


class TestValidateUrlWithLocalhostAllowed:
    """Tests for validate_url() with allow_localhost=True (explicit).

    Note: P2.1 changed the default to allow_localhost=False, so these tests
    must explicitly pass allow_localhost=True.
    """

    def test_allows_127_0_0_1(self):
        """http://127.0.0.1:8080 is allowed with localhost enabled."""
        result = validate_url("http://127.0.0.1:8080", allow_localhost=True)
        assert result == "http://127.0.0.1:8080"

    def test_allows_localhost_hostname(self):
        """http://localhost:8080 is allowed with localhost enabled."""
        result = validate_url("http://localhost:8080", allow_localhost=True)
        assert result == "http://localhost:8080"

    def test_allows_https_localhost(self):
        """https://localhost:8080 is allowed with localhost enabled."""
        result = validate_url("https://localhost:8080", allow_localhost=True)
        assert result == "https://localhost:8080"

    def test_blocks_cloud_metadata_ip(self):
        """Cloud metadata IP 169.254.169.254 is ALWAYS blocked, even with localhost allowed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://169.254.169.254", allow_localhost=True)

        assert exc_info.value.url == "http://169.254.169.254"
        assert "cloud metadata" in exc_info.value.reason.lower()

    def test_blocks_cloud_metadata_with_path(self):
        """Cloud metadata with path is blocked, even with localhost allowed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://169.254.169.254/latest/meta-data/", allow_localhost=True)

        assert "cloud metadata" in exc_info.value.reason.lower()

    def test_blocks_private_network_10_x(self):
        """Private network 10.0.0.0/8 is blocked, even with localhost allowed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://10.0.0.1", allow_localhost=True)

        assert exc_info.value.url == "http://10.0.0.1"
        assert "private network" in exc_info.value.reason.lower()

    def test_blocks_private_network_172_16_x(self):
        """Private network 172.16.0.0/12 is blocked, even with localhost allowed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://172.16.0.1", allow_localhost=True)

        assert exc_info.value.url == "http://172.16.0.1"
        assert "private network" in exc_info.value.reason.lower()

    def test_blocks_private_network_192_168_x(self):
        """Private network 192.168.0.0/16 is blocked, even with localhost allowed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://192.168.1.1", allow_localhost=True)

        assert exc_info.value.url == "http://192.168.1.1"
        assert "private network" in exc_info.value.reason.lower()

    def test_rejects_invalid_scheme_ftp(self):
        """FTP scheme is rejected."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("ftp://localhost", allow_localhost=True)

        assert "invalid scheme" in exc_info.value.reason.lower()
        assert "ftp" in exc_info.value.reason.lower()

    def test_rejects_invalid_scheme_file(self):
        """File scheme is rejected."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("file:///etc/passwd", allow_localhost=True)

        assert "invalid scheme" in exc_info.value.reason.lower()

    def test_rejects_empty_url(self):
        """Empty URL raises error."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("")

        assert exc_info.value.url == ""
        assert "empty" in exc_info.value.reason.lower()

    def test_rejects_url_without_host(self):
        """URL without hostname raises error."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://")

        assert "no hostname" in exc_info.value.reason.lower()


class TestValidateUrlWithLocalhostDisallowed:
    """Tests for validate_url() with allow_localhost=False."""

    def test_blocks_127_0_0_1(self):
        """http://127.0.0.1:8080 is blocked when localhost disabled."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://127.0.0.1:8080", allow_localhost=False)

        assert exc_info.value.url == "http://127.0.0.1:8080"
        assert "localhost not allowed" in exc_info.value.reason.lower()

    def test_blocks_localhost_hostname(self):
        """http://localhost:8080 is blocked when localhost disabled."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://localhost:8080", allow_localhost=False)

        assert "localhost" in exc_info.value.reason.lower()

    def test_still_blocks_cloud_metadata(self):
        """Cloud metadata is blocked regardless of localhost setting."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://169.254.169.254", allow_localhost=False)

        assert "cloud metadata" in exc_info.value.reason.lower()

    def test_still_blocks_private_networks(self):
        """Private networks are blocked regardless of localhost setting."""
        with pytest.raises(UrlSecurityError):
            validate_url("http://10.0.0.1", allow_localhost=False)

        with pytest.raises(UrlSecurityError):
            validate_url("http://192.168.1.1", allow_localhost=False)


class TestValidateUrlEdgeCases:
    """Tests for edge cases in validate_url()."""

    def test_url_with_port_number(self):
        """URL with port number works correctly."""
        result = validate_url("http://127.0.0.1:9999", allow_localhost=True)
        assert result == "http://127.0.0.1:9999"

    def test_url_with_path(self):
        """URL with path is validated and returned."""
        result = validate_url("http://localhost:8080/api/v1/status", allow_localhost=True)
        assert result == "http://localhost:8080/api/v1/status"

    def test_url_with_query_string(self):
        """URL with query string is validated and returned."""
        result = validate_url("http://localhost:8080/search?q=test&page=1", allow_localhost=True)
        assert result == "http://localhost:8080/search?q=test&page=1"

    def test_dns_resolution_failure(self):
        """DNS resolution failure raises UrlSecurityError."""
        with patch("socket.gethostbyname") as mock_dns:
            mock_dns.side_effect = socket.gaierror(8, "Name or service not known")

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://nonexistent.invalid.domain.test")

            assert "failed to resolve hostname" in exc_info.value.reason.lower()

    def test_dns_resolution_failure_for_localhost_still_works(self):
        """DNS failure for 'localhost' hostname still works when allowed.

        The validator allows localhost hostnames even if DNS resolution fails,
        since localhost resolution can be flaky on some systems.
        """
        with patch("socket.gethostbyname") as mock_dns:
            mock_dns.side_effect = socket.gaierror(8, "Name or service not known")

            # Should NOT raise because 'localhost' is a known localhost hostname
            result = validate_url("http://localhost:8080", allow_localhost=True)
            assert result == "http://localhost:8080"

    def test_localhost_blocked_when_disallowed(self):
        """'localhost' is blocked when allow_localhost=False even if it resolves."""
        # With getaddrinfo, localhost resolves to 127.0.0.1, which gets blocked
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://localhost:8080", allow_localhost=False)

        assert "localhost not allowed" in exc_info.value.reason.lower()

    def test_blocks_link_local_range(self):
        """Link-local addresses (169.254.x.x) are blocked, even with localhost allowed."""
        with pytest.raises(UrlSecurityError) as exc_info:
            validate_url("http://169.254.1.1", allow_localhost=True)

        assert "blocked range" in exc_info.value.reason.lower()

    def test_allows_external_url_mocked(self):
        """External URLs are allowed when DNS resolves to public IP."""
        # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
        # sockaddr is (ip, port) for IPv4
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80))]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            result = validate_url("http://example.com")
            assert result == "http://example.com"

    def test_blocks_internal_hostname_resolving_to_private(self):
        """Hostname resolving to private IP is blocked."""
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.50", 80))]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://internal-service.corp")

            assert "private network" in exc_info.value.reason.lower()

    def test_blocks_hostname_resolving_to_metadata(self):
        """Hostname resolving to cloud metadata IP is blocked."""
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 80))]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://metadata.google.internal")

            assert "cloud metadata" in exc_info.value.reason.lower()

    def test_handles_uppercase_scheme(self):
        """URL with uppercase scheme is handled."""
        # Note: urlparse lowercases the scheme
        result = validate_url("HTTP://localhost:8080", allow_localhost=True)
        assert result == "HTTP://localhost:8080"

    def test_handles_mixed_case_localhost(self):
        """Mixed case 'LocalHost' is recognized."""
        result = validate_url("http://LocalHost:8080", allow_localhost=True)
        assert result == "http://LocalHost:8080"


class TestValidateUrlIpv6:
    """Tests for IPv6 address handling."""

    def test_blocks_ipv6_loopback_when_localhost_disabled(self):
        """IPv6 loopback ::1 is blocked when localhost disabled."""
        with patch("socket.gethostbyname") as mock_dns:
            mock_dns.return_value = "::1"  # This won't happen but test the logic

            with pytest.raises(UrlSecurityError):
                validate_url("http://[::1]:8080", allow_localhost=False)


class TestDnsRebindingProtection:
    """Tests for DNS rebinding attack prevention."""

    def test_blocks_if_any_address_is_private(self):
        """If DNS returns multiple addresses and ANY is private, block."""
        # Simulate DNS returning public IP first, then private IP
        mock_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80)),  # Public
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.50", 80)),      # Private
        ]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://rebinding-attack.example.com")

            assert "private network" in exc_info.value.reason.lower()

    def test_blocks_if_any_address_is_cloud_metadata(self):
        """If DNS returns cloud metadata IP as any address, block."""
        mock_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 80)),         # Public
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 80)), # Metadata
        ]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://sneaky.example.com")

            assert "cloud metadata" in exc_info.value.reason.lower()

    def test_blocks_if_any_ipv6_address_is_private(self):
        """If DNS returns IPv6 private address among others, block."""
        mock_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80)),  # Public IPv4
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fc00::1", 80, 0, 0)), # Private IPv6
        ]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://dual-stack.example.com")

            assert "private network" in exc_info.value.reason.lower()

    def test_allows_when_all_addresses_public(self):
        """If all DNS addresses are public, allow."""
        mock_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80)),  # Public
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.35", 80)),  # Public
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2606:2800:220:1:248:1893:25c8:1946", 80, 0, 0)),  # Public IPv6
        ]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            result = validate_url("http://example.com")
            assert result == "http://example.com"

    def test_blocks_localhost_in_multi_address_when_disallowed(self):
        """If DNS returns localhost among others and localhost not allowed, block."""
        mock_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80)),  # Public
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 80)),      # Localhost
        ]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://tricky.example.com", allow_localhost=False)

            assert "localhost" in exc_info.value.reason.lower()


class TestMulticastBlocking:
    """Tests for multicast address blocking."""

    def test_blocks_ipv4_multicast_224_x(self):
        """IPv4 multicast address 224.x.x.x is blocked."""
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("224.0.0.1", 80))]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://multicast.example.com")

            assert "blocked range" in exc_info.value.reason.lower()

    def test_blocks_ipv4_multicast_239_x(self):
        """IPv4 multicast address 239.x.x.x is blocked."""
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("239.255.255.250", 80))]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://ssdp.example.com")

            assert "blocked range" in exc_info.value.reason.lower()

    def test_blocks_ipv6_multicast(self):
        """IPv6 multicast address ff00::/8 is blocked."""
        mock_result = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("ff02::1", 80, 0, 0))]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://multicast6.example.com")

            assert "blocked range" in exc_info.value.reason.lower()

    def test_blocks_multicast_among_other_addresses(self):
        """If DNS returns multicast among other addresses, block."""
        mock_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80)),  # Public
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("224.0.0.251", 80)),    # mDNS multicast
        ]
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = mock_result

            with pytest.raises(UrlSecurityError) as exc_info:
                validate_url("http://mdns.example.com")

            assert "blocked range" in exc_info.value.reason.lower()
