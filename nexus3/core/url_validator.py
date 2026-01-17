"""SSRF protection module for validating URLs before HTTP requests.

SECURITY: This module validates URLs against SSRF attacks by checking resolved
IP addresses against blocked ranges (private networks, cloud metadata, etc.).

KNOWN LIMITATION (P2.2): DNS rebinding / TOCTOU
    This validation is subject to Time-of-Check-to-Time-of-Use (TOCTOU) issues.
    A malicious DNS server could return a safe IP during validation, then a
    dangerous IP (e.g., 169.254.169.254) during the actual HTTP request.

    Mitigations in place:
    1. ALL returned DNS addresses are validated (not just the first one)
    2. DNS results with ANY private IP are blocked
    3. Short-lived DNS cache entries are assumed (typical TTL < 5 minutes)

    For higher security requirements, consider:
    - Using IP pinning (connect to resolved IP directly)
    - Network-level egress filtering
    - Running in isolated network namespace
"""

import ipaddress
import socket
from urllib.parse import urlparse

from nexus3.core.errors import NexusError


class UrlSecurityError(NexusError):
    """Raised when a URL fails security validation."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"URL security error for '{url}': {reason}")


# IP ranges that are always blocked (cloud metadata, private networks, etc.)
BLOCKED_IP_RANGES = [
    # Cloud metadata endpoints - ALWAYS blocked
    ipaddress.ip_network("169.254.169.254/32"),  # AWS/GCP/Azure metadata
    # Link-local (includes metadata range)
    ipaddress.ip_network("169.254.0.0/16"),
    # Private networks
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # Loopback (allowed conditionally)
    ipaddress.ip_network("127.0.0.0/8"),
    # IPv6 private/link-local
    ipaddress.ip_network("::1/128"),  # Loopback
    ipaddress.ip_network("fc00::/7"),  # Unique local
    ipaddress.ip_network("fe80::/10"),  # Link-local
    # Multicast addresses - should never be used for HTTP requests
    ipaddress.ip_network("224.0.0.0/4"),  # IPv4 multicast
    ipaddress.ip_network("ff00::/8"),  # IPv6 multicast
]

# Cloud metadata IPs that are NEVER allowed regardless of allow_localhost
CLOUD_METADATA_IPS = [
    ipaddress.ip_address("169.254.169.254"),
]

# Localhost addresses that can be explicitly allowed
ALLOWED_LOCALHOST = ["127.0.0.1", "localhost", "::1"]


def _is_cloud_metadata(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is a cloud metadata endpoint."""
    return any(ip == metadata_ip for metadata_ip in CLOUD_METADATA_IPS)


def _is_localhost(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is a localhost address."""
    if isinstance(ip, ipaddress.IPv4Address):
        return ip in ipaddress.ip_network("127.0.0.0/8")
    # IPv6 loopback
    return ip == ipaddress.ip_address("::1")


def _is_private_network(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is in RFC1918 private network ranges.

    RFC1918 ranges:
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    """
    if isinstance(ip, ipaddress.IPv4Address):
        return (
            ip in ipaddress.ip_network("10.0.0.0/8")
            or ip in ipaddress.ip_network("172.16.0.0/12")
            or ip in ipaddress.ip_network("192.168.0.0/16")
        )
    # IPv6 unique local addresses (fc00::/7)
    return ip in ipaddress.ip_network("fc00::/7")


def _is_blocked(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allow_localhost: bool,
    allow_private: bool = False,
) -> tuple[bool, str]:
    """Check if IP is in blocked ranges.

    Args:
        ip: IP address to check
        allow_localhost: Whether localhost is permitted
        allow_private: Whether RFC1918 private networks are permitted

    Returns:
        Tuple of (is_blocked, reason)
    """
    # Cloud metadata is ALWAYS blocked
    if _is_cloud_metadata(ip):
        return True, "cloud metadata endpoint"

    # Check if it's localhost
    if _is_localhost(ip):
        if allow_localhost:
            return False, ""
        return True, "localhost not allowed"

    # Check if it's a private network address
    if _is_private_network(ip):
        if allow_private:
            return False, ""
        return True, "private network address not allowed"

    # Check against blocked ranges
    for network in BLOCKED_IP_RANGES:
        # Skip loopback check if localhost is allowed
        if allow_localhost and network == ipaddress.ip_network("127.0.0.0/8"):
            continue
        if allow_localhost and network == ipaddress.ip_network("::1/128"):
            continue

        # Skip private network ranges if allowed
        if allow_private:
            if network == ipaddress.ip_network("10.0.0.0/8"):
                continue
            if network == ipaddress.ip_network("172.16.0.0/12"):
                continue
            if network == ipaddress.ip_network("192.168.0.0/16"):
                continue
            if network == ipaddress.ip_network("fc00::/7"):
                continue

        try:
            if ip in network:
                return True, f"IP in blocked range {network}"
        except TypeError:
            # IPv4/IPv6 mismatch, skip
            continue

    return False, ""


def validate_url(
    url: str, allow_localhost: bool = False, allow_private: bool = False
) -> str:
    """Validate URL is safe for HTTP requests.

    Prevents Server-Side Request Forgery (SSRF) attacks by validating
    that URLs don't point to internal services, cloud metadata endpoints,
    or other blocked destinations.

    P2.1 SECURITY: Default changed to allow_localhost=False for safe-by-default.
    Callers that need localhost access (e.g., NexusSkill connecting to local
    server) must explicitly pass allow_localhost=True.

    Args:
        url: URL to validate
        allow_localhost: Whether to allow localhost URLs (default False)
        allow_private: Whether to allow RFC1918 private network addresses
            (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) (default False).
            Useful for internal deployments where servers run on private networks.

    Returns:
        The validated URL (may be normalized)

    Raises:
        UrlSecurityError: If URL points to blocked destination
    """
    if not url:
        raise UrlSecurityError(url, "empty URL")

    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise UrlSecurityError(url, f"failed to parse URL: {e}") from e

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise UrlSecurityError(
            url, f"invalid scheme '{parsed.scheme}', must be http or https"
        )

    # Validate hostname exists
    hostname = parsed.hostname
    if not hostname:
        raise UrlSecurityError(url, "no hostname in URL")

    # Check for special localhost hostnames
    is_localhost_hostname = hostname.lower() in [h.lower() for h in ALLOWED_LOCALHOST]

    # Resolve hostname to IP using getaddrinfo (handles both IPv4 and IPv6)
    try:
        # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
        # sockaddr is (ip, port) for IPv4 or (ip, port, flow, scope) for IPv6
        addr_info = socket.getaddrinfo(
            hostname,
            parsed.port or 80,
            type=socket.SOCK_STREAM,
        )
        if not addr_info:
            if is_localhost_hostname and allow_localhost:
                return url
            raise UrlSecurityError(url, "no address info found for hostname")

        # SECURITY: Validate ALL returned addresses, not just the first.
        # This prevents DNS rebinding attacks where one address is public
        # but another is private (e.g., first lookup returns safe IP,
        # subsequent lookups return internal IPs).
        for addr in addr_info:
            ip_str = addr[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                # Skip invalid IP representations (shouldn't happen, but be defensive)
                continue

            blocked, reason = _is_blocked(ip, allow_localhost, allow_private)
            if blocked:
                raise UrlSecurityError(url, reason)

    except socket.gaierror as e:
        # If localhost hostname and allowed, don't fail on resolution
        if is_localhost_hostname and allow_localhost:
            return url
        raise UrlSecurityError(url, f"failed to resolve hostname: {e}") from e

    return url
