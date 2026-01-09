"""SSRF protection module for validating URLs before HTTP requests."""

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


def _is_blocked(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_localhost: bool
) -> tuple[bool, str]:
    """Check if IP is in blocked ranges.

    Args:
        ip: IP address to check
        allow_localhost: Whether localhost is permitted

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

    # Check against blocked ranges
    for network in BLOCKED_IP_RANGES:
        # Skip loopback check if localhost is allowed
        if allow_localhost and network == ipaddress.ip_network("127.0.0.0/8"):
            continue
        if allow_localhost and network == ipaddress.ip_network("::1/128"):
            continue

        try:
            if ip in network:
                return True, f"IP in blocked range {network}"
        except TypeError:
            # IPv4/IPv6 mismatch, skip
            continue

    return False, ""


def validate_url(url: str, allow_localhost: bool = True) -> str:
    """Validate URL is safe for HTTP requests.

    Prevents Server-Side Request Forgery (SSRF) attacks by validating
    that URLs don't point to internal services, cloud metadata endpoints,
    or other blocked destinations.

    Args:
        url: URL to validate
        allow_localhost: Whether to allow localhost URLs (default True)

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

    # Resolve hostname to IP
    try:
        # Try IPv4 first
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
    except socket.gaierror as e:
        # If localhost hostname and allowed, don't fail on resolution
        if is_localhost_hostname and allow_localhost:
            return url
        raise UrlSecurityError(url, f"failed to resolve hostname: {e}") from e
    except ValueError as e:
        raise UrlSecurityError(url, f"invalid IP address: {e}") from e

    # Check if blocked
    blocked, reason = _is_blocked(ip, allow_localhost)
    if blocked:
        raise UrlSecurityError(url, reason)

    return url
