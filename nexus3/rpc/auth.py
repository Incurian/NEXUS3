"""RPC token authentication for NEXUS3 HTTP server.

This module provides token generation, validation, and management for
securing the JSON-RPC HTTP server.

Token Format: nxk_ + 32 bytes URL-safe Base64 (e.g., nxk_7Ks9XmN2pLqR4Tv8YbHc...)

Token Storage:
    ~/.nexus3/
    ├── rpc.token           # Default (port 8765)
    └── rpc-{port}.token    # Port-specific

Security properties:
    - File permissions: 0o600 (owner read/write only)
    - Local-only: Server binds to localhost by default
    - Ephemeral: Deleted on clean server shutdown
    - Rotated: Fresh token on each server start (when no server running)

P2.8 SECURITY: Token file permission checks
    - On read/discovery, verify file has secure permissions (0600)
    - Warn or refuse if permissions are too permissive
    - Configurable: strict_permissions parameter

Example usage:
    # Server-side: Generate and store token
    manager = ServerTokenManager(port=8765)
    token = manager.generate_fresh()
    print(f"Token: {token}")

    # Client-side: Discover token
    token = discover_rpc_token(port=8765)
    if token:
        # Use token in Authorization header
        headers = {"Authorization": f"Bearer {token}"}
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import stat
from pathlib import Path

from nexus3.core.constants import get_nexus_dir
from nexus3.core.secure_io import secure_mkdir

logger = logging.getLogger(__name__)

# API key prefix for identification
API_KEY_PREFIX = "nxk_"

# P2.8 SECURITY: Required permission mask for token files
# Token files must not be readable by group or others
SECURE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600


class InsecureTokenFileError(Exception):
    """Raised when token file has insecure permissions.

    P2.8 SECURITY: This exception is raised in strict mode when the token
    file is readable by group or others (permissions more open than 0600).
    """

    def __init__(self, path: Path, mode: int) -> None:
        self.path = path
        self.mode = mode
        mode_str = oct(mode)[-3:]  # e.g., "644"
        super().__init__(
            f"Token file {path} has insecure permissions ({mode_str}). "
            f"Expected 0600 (owner read/write only). "
            f"Fix with: chmod 600 {path}"
        )


def check_token_file_permissions(
    path: Path,
    strict: bool = False,
) -> bool:
    """Check if a token file has secure permissions.

    P2.8 SECURITY: Token files should only be readable by the owner.
    This function verifies the file is not readable by group or others.

    Args:
        path: Path to the token file.
        strict: If True, raise InsecureTokenFileError on insecure permissions.
                If False, log a warning and return False.

    Returns:
        True if permissions are secure (0600 or more restrictive).
        False if permissions are insecure (and strict=False).

    Raises:
        InsecureTokenFileError: If strict=True and permissions are insecure.
        OSError: If the file cannot be stat'd.
    """
    file_stat = path.stat()
    mode = file_stat.st_mode

    # Check if group or others have any access
    # S_IRWXG = group rwx, S_IRWXO = others rwx
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        # Permissions are too open
        if strict:
            raise InsecureTokenFileError(path, mode)
        else:
            mode_str = oct(mode)[-3:]
            logger.warning(
                "Token file %s has insecure permissions (%s). "
                "Should be 0600 (owner read/write only). "
                "Fix with: chmod 600 %s",
                path, mode_str, path
            )
            return False

    return True


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


class ServerTokenManager:
    """Manages server RPC token storage and lifecycle.

    This class handles generating, storing, loading, and deleting tokens
    for the NEXUS3 HTTP server. Tokens are stored in files with mode 0o600
    (readable only by owner) for security.

    Attributes:
        port: The port number for port-specific token files.
        nexus_dir: The NEXUS3 configuration directory.

    Example:
        # Create manager for default port
        manager = ServerTokenManager()

        # Generate fresh token (deletes any stale token first)
        token = manager.generate_fresh()
        print(f"Token saved to: {manager.token_path}")

        # Cleanup on shutdown
        manager.delete()
    """

    def __init__(
        self,
        port: int = 8765,
        nexus_dir: Path | None = None,
        strict_permissions: bool = True,
    ) -> None:
        """Initialize the token manager.

        Args:
            port: The server port. Used for port-specific token files.
                  Default port (8765) uses rpc.token, other ports use
                  rpc-{port}.token.
            nexus_dir: The NEXUS3 configuration directory. Defaults to
                       ~/.nexus3 if not specified.
            strict_permissions: P2.8 SECURITY - If True, refuse to load tokens
                  from files with insecure permissions. If False (default),
                  log a warning but still load the token.
        """
        self._port = port
        self._nexus_dir = nexus_dir or get_nexus_dir()
        self._strict_permissions = strict_permissions

    @property
    def port(self) -> int:
        """The port number this manager is configured for."""
        return self._port

    @property
    def nexus_dir(self) -> Path:
        """The NEXUS3 configuration directory."""
        return self._nexus_dir

    @property
    def token_path(self) -> Path:
        """Path to the token file for this port.

        Returns:
            Path to rpc.token for default port (8765), or
            rpc-{port}.token for other ports.
        """
        if self._port == 8765:
            return self._nexus_dir / "rpc.token"
        else:
            return self._nexus_dir / f"rpc-{self._port}.token"

    def _save(self, token: str) -> None:
        """Save a token to the token file with secure permissions.

        Creates the NEXUS3 directory if it doesn't exist. The token file
        is created with mode 0o600 (readable only by owner) atomically
        to avoid race conditions.

        Args:
            token: The token to save.

        Raises:
            OSError: If the token file cannot be written.
        """
        # Ensure directory exists with secure permissions (0o700)
        secure_mkdir(self._nexus_dir)

        # Write token with restrictive permissions atomically
        # Using os.open() to set permissions at creation time avoids the
        # race window between write and chmod
        fd = os.open(
            str(self.token_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token)
        except Exception:
            # fd is closed by fdopen, even on error
            raise

    def load(self) -> str | None:
        """Load the token from the token file.

        P2.8 SECURITY: Checks file permissions before loading. If the file
        has insecure permissions (readable by group or others), behavior
        depends on the strict_permissions setting:
        - strict=True: Raises InsecureTokenFileError
        - strict=False: Logs warning, returns token anyway

        Returns:
            The token if the file exists and is readable, None otherwise.

        Raises:
            InsecureTokenFileError: If strict_permissions=True and file
                has insecure permissions.
        """
        if not self.token_path.exists():
            return None

        try:
            # P2.8 SECURITY: Check permissions before reading
            check_token_file_permissions(
                self.token_path,
                strict=self._strict_permissions
            )
            return self.token_path.read_text(encoding="utf-8").strip()
        except InsecureTokenFileError:
            # Re-raise permission errors
            raise
        except OSError as e:
            logger.debug("Failed to read token file %s: %s", self.token_path, e)
            return None

    def generate_fresh(self) -> str:
        """Delete any stale token and generate a fresh one.

        Use this when starting a server after confirming no other server
        is running on this port. This provides token rotation while still
        preventing auth mismatches (since there's no existing server to
        mismatch with).

        The sequence is:
        1. Delete existing token file (if any) - it's stale
        2. Generate new random token
        3. Save with secure permissions (0o600)

        Returns:
            The newly generated token.
        """
        self.delete()
        token = generate_api_key()
        self._save(token)
        logger.debug("Generated fresh token at %s", self.token_path)
        return token

    def delete(self) -> None:
        """Delete the token file if it exists.

        This should be called during server shutdown to clean up
        the token file. Silently succeeds if the file doesn't exist.
        """
        try:
            self.token_path.unlink(missing_ok=True)
        except OSError as e:
            logger.debug("Failed to delete token file %s: %s", self.token_path, e)


def discover_rpc_token(
    port: int = 8765,
    nexus_dir: Path | None = None,
    strict_permissions: bool = True,
) -> str | None:
    """Discover an RPC token for connecting to a NEXUS3 server.

    This function checks multiple locations for a token, in order:
    1. NEXUS3_API_KEY environment variable (for backwards compatibility)
    2. ~/.nexus3/rpc-{port}.token (port-specific)
    3. ~/.nexus3/rpc.token (default)

    P2.8 SECURITY: Token files are checked for secure permissions (0600).
    If strict_permissions=True, insecure files are skipped. If False,
    a warning is logged but the token is still returned.

    Args:
        port: The server port to connect to. Used for port-specific
              token file lookup.
        nexus_dir: The NEXUS3 configuration directory. Defaults to
                   ~/.nexus3 if not specified.
        strict_permissions: If True, skip token files with insecure
                           permissions. If False (default), warn but
                           still use them.

    Returns:
        The discovered token, or None if no token was found.

    Example:
        # Try to discover token for default port
        token = discover_rpc_token()
        if token:
            client = NexusClient(url, api_key=token)
        else:
            print("No token found. Use --api-key flag.")
    """
    nexus_dir = nexus_dir or get_nexus_dir()

    # 1. Check environment variable (backwards compatible name)
    env_token = os.environ.get("NEXUS3_API_KEY")
    if env_token:
        return env_token.strip()

    def _try_load_token(token_path: Path) -> str | None:
        """Try to load token from a file, checking permissions."""
        if not token_path.exists():
            return None
        try:
            # P2.8 SECURITY: Check permissions before reading
            is_secure = check_token_file_permissions(
                token_path,
                strict=False  # Always check, but don't raise
            )
            if strict_permissions and not is_secure:
                logger.debug(
                    "Skipping insecure token file %s (strict mode)",
                    token_path
                )
                return None

            token = token_path.read_text(encoding="utf-8").strip()
            return token if token else None
        except OSError as e:
            logger.debug("Failed to read token file %s: %s", token_path, e)
            return None

    # 2. Check port-specific token file
    if port != 8765:
        port_token_path = nexus_dir / f"rpc-{port}.token"
        token = _try_load_token(port_token_path)
        if token:
            return token

    # 3. Check default token file
    default_token_path = nexus_dir / "rpc.token"
    token = _try_load_token(default_token_path)
    if token:
        return token

    return None


