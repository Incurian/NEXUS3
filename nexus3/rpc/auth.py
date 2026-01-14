"""API key authentication for NEXUS3 HTTP server.

This module provides API key generation, validation, and management for
securing the JSON-RPC HTTP server.

Key Format: nxk_ + 32 bytes URL-safe Base64 (e.g., nxk_7Ks9XmN2pLqR4Tv8YbHc...)

Key Storage:
    ~/.nexus3/
    ├── server.key          # Default (port 8765)
    └── server-{port}.key   # Port-specific

Example usage:
    # Server-side: Generate and store key
    manager = ServerKeyManager(port=8765)
    api_key = manager.generate_and_save()
    print(f"API key: {api_key}")

    # Client-side: Discover key
    key = discover_api_key(port=8765)
    if key:
        # Use key in Authorization header
        headers = {"Authorization": f"Bearer {key}"}
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

# API key prefix for identification
API_KEY_PREFIX = "nxk_"

# Default NEXUS3 directory
DEFAULT_NEXUS_DIR = Path.home() / ".nexus3"


def generate_api_key() -> str:
    """Generate a new API key with nxk_ prefix.

    Returns:
        A new API key in format: nxk_ + 32 bytes URL-safe Base64.
        Total length is approximately 47 characters.

    Example:
        >>> key = generate_api_key()
        >>> key.startswith("nxk_")
        True
        >>> len(key) > 40
        True
    """
    # Generate 32 bytes of random data, URL-safe Base64 encoded
    token = secrets.token_urlsafe(32)
    return f"{API_KEY_PREFIX}{token}"


def validate_api_key(provided: str, expected: str) -> bool:
    """Validate an API key using constant-time comparison.

    This function uses hmac.compare_digest to prevent timing attacks
    that could leak information about the expected key.

    Args:
        provided: The API key provided by the client.
        expected: The expected API key stored on the server.

    Returns:
        True if the keys match, False otherwise.

    Note:
        Both arguments should be non-empty strings. If either is empty
        or None-like, returns False without attempting comparison.
    """
    if not provided or not expected:
        return False

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided, expected)


class ServerKeyManager:
    """Manages server API key storage and lifecycle.

    This class handles generating, storing, loading, and deleting API keys
    for the NEXUS3 HTTP server. Keys are stored in files with mode 0o600
    (readable only by owner) for security.

    Attributes:
        port: The port number for port-specific key files.
        nexus_dir: The NEXUS3 configuration directory.

    Example:
        # Create manager for default port
        manager = ServerKeyManager()

        # Generate and save a new key
        key = manager.generate_and_save()
        print(f"Key saved to: {manager.key_path}")

        # Later, load the key
        loaded_key = manager.load()

        # Cleanup on shutdown
        manager.delete()
    """

    def __init__(
        self,
        port: int = 8765,
        nexus_dir: Path | None = None,
    ) -> None:
        """Initialize the key manager.

        Args:
            port: The server port. Used for port-specific key files.
                  Default port (8765) uses server.key, other ports use
                  server-{port}.key.
            nexus_dir: The NEXUS3 configuration directory. Defaults to
                       ~/.nexus3 if not specified.
        """
        self._port = port
        self._nexus_dir = nexus_dir or DEFAULT_NEXUS_DIR

    @property
    def port(self) -> int:
        """The port number this manager is configured for."""
        return self._port

    @property
    def nexus_dir(self) -> Path:
        """The NEXUS3 configuration directory."""
        return self._nexus_dir

    @property
    def key_path(self) -> Path:
        """Path to the key file for this port.

        Returns:
            Path to server.key for default port (8765), or
            server-{port}.key for other ports.
        """
        if self._port == 8765:
            return self._nexus_dir / "server.key"
        else:
            return self._nexus_dir / f"server-{self._port}.key"

    def generate_and_save(self) -> str:
        """Generate a new API key and save it to the key file.

        Creates the NEXUS3 directory if it doesn't exist. The key file
        is created with mode 0o600 (readable only by owner).

        Returns:
            The generated API key.

        Raises:
            OSError: If the key file cannot be written.
        """
        # Ensure directory exists
        self._nexus_dir.mkdir(parents=True, exist_ok=True)

        # Generate key
        api_key = generate_api_key()

        # Write key with restrictive permissions
        # First write, then chmod to ensure file exists
        self.key_path.write_text(api_key, encoding="utf-8")

        # Set file permissions to 0o600 (owner read/write only)
        # This prevents other users from reading the key
        os.chmod(self.key_path, stat.S_IRUSR | stat.S_IWUSR)

        return api_key

    def load(self) -> str | None:
        """Load the API key from the key file.

        Returns:
            The API key if the file exists and is readable, None otherwise.
        """
        if not self.key_path.exists():
            return None

        try:
            return self.key_path.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.debug("Failed to read key file %s: %s", self.key_path, e)
            return None

    def delete(self) -> None:
        """Delete the key file if it exists.

        This should be called during server shutdown to clean up
        the key file. Silently succeeds if the file doesn't exist.
        """
        try:
            self.key_path.unlink(missing_ok=True)
        except OSError as e:
            logger.debug("Failed to delete key file %s: %s", self.key_path, e)


def discover_api_key(
    port: int = 8765,
    nexus_dir: Path | None = None,
) -> str | None:
    """Discover an API key for connecting to a NEXUS3 server.

    This function checks multiple locations for an API key, in order:
    1. NEXUS3_API_KEY environment variable
    2. ~/.nexus3/server-{port}.key (port-specific)
    3. ~/.nexus3/server.key (default)

    Args:
        port: The server port to connect to. Used for port-specific
              key file lookup.
        nexus_dir: The NEXUS3 configuration directory. Defaults to
                   ~/.nexus3 if not specified.

    Returns:
        The discovered API key, or None if no key was found.

    Example:
        # Try to discover key for default port
        key = discover_api_key()
        if key:
            client = NexusClient(url, api_key=key)
        else:
            print("No API key found. Use --api-key flag.")
    """
    nexus_dir = nexus_dir or DEFAULT_NEXUS_DIR

    # 1. Check environment variable
    env_key = os.environ.get("NEXUS3_API_KEY")
    if env_key:
        return env_key.strip()

    # 2. Check port-specific key file
    if port != 8765:
        port_key_path = nexus_dir / f"server-{port}.key"
        if port_key_path.exists():
            try:
                key = port_key_path.read_text(encoding="utf-8").strip()
                if key:
                    return key
            except OSError as e:
                logger.debug("Failed to read port-specific key file %s: %s", port_key_path, e)

    # 3. Check default key file
    default_key_path = nexus_dir / "server.key"
    if default_key_path.exists():
        try:
            key = default_key_path.read_text(encoding="utf-8").strip()
            if key:
                return key
        except OSError as e:
            logger.debug("Failed to read default key file %s: %s", default_key_path, e)

    return None
