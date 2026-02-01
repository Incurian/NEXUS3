"""Tests for P2.8: Token file permission checks on read/discovery.

These tests verify that token files with insecure permissions (readable by
group or others) are handled appropriately:
- In strict mode: refused/skipped
- In non-strict mode: warned but accepted

This is defense-in-depth against token files that are accidentally or
maliciously made world-readable.
"""

import os
import stat
from pathlib import Path

import pytest

from nexus3.rpc.auth import (
    InsecureTokenFileError,
    ServerTokenManager,
    check_token_file_permissions,
    discover_rpc_token,
    generate_api_key,
)


class TestCheckTokenFilePermissions:
    """Tests for check_token_file_permissions()."""

    def test_secure_permissions_returns_true(self, tmp_path: Path) -> None:
        """0600 permissions return True."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600

        result = check_token_file_permissions(token_file)
        assert result is True

    def test_read_only_owner_returns_true(self, tmp_path: Path) -> None:
        """0400 (read-only owner) returns True."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR)  # 0400

        result = check_token_file_permissions(token_file)
        assert result is True

    def test_group_readable_returns_false_nonstrict(self, tmp_path: Path) -> None:
        """0640 (group readable) returns False in non-strict mode."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)  # 0640

        result = check_token_file_permissions(token_file, strict=False)
        assert result is False

    def test_world_readable_returns_false_nonstrict(self, tmp_path: Path) -> None:
        """0644 (world readable) returns False in non-strict mode."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        result = check_token_file_permissions(token_file, strict=False)
        assert result is False

    def test_group_readable_raises_in_strict_mode(self, tmp_path: Path) -> None:
        """0640 (group readable) raises InsecureTokenFileError in strict mode."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)  # 0640

        with pytest.raises(InsecureTokenFileError) as exc_info:
            check_token_file_permissions(token_file, strict=True)

        assert exc_info.value.path == token_file
        assert "640" in str(exc_info.value)
        assert "chmod 600" in str(exc_info.value)

    def test_world_readable_raises_in_strict_mode(self, tmp_path: Path) -> None:
        """0644 (world readable) raises InsecureTokenFileError in strict mode."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        with pytest.raises(InsecureTokenFileError) as exc_info:
            check_token_file_permissions(token_file, strict=True)

        assert exc_info.value.path == token_file
        assert "644" in str(exc_info.value)

    def test_group_writable_raises_in_strict_mode(self, tmp_path: Path) -> None:
        """0660 (group writable) raises InsecureTokenFileError in strict mode."""
        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)  # 0660

        with pytest.raises(InsecureTokenFileError) as exc_info:
            check_token_file_permissions(token_file, strict=True)

        assert exc_info.value.path == token_file


class TestServerTokenManagerLoad:
    """Tests for ServerTokenManager.load() permission checks."""

    def test_load_secure_file_succeeds(self, tmp_path: Path) -> None:
        """Loading a 0600 token file succeeds."""
        manager = ServerTokenManager(port=9999, nexus_dir=tmp_path)
        expected_token = generate_api_key()

        # Create token file with secure permissions
        token_file = tmp_path / "rpc-9999.token"
        fd = os.open(str(token_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(expected_token)

        token = manager.load()
        assert token == expected_token

    def test_load_insecure_file_warns_nonstrict(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Loading a 0644 file in non-strict mode warns but succeeds."""
        manager = ServerTokenManager(port=9999, nexus_dir=tmp_path, strict_permissions=False)
        expected_token = generate_api_key()

        # Create token file with insecure permissions
        token_file = tmp_path / "rpc-9999.token"
        token_file.write_text(expected_token)
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        import logging
        with caplog.at_level(logging.WARNING):
            token = manager.load()

        assert token == expected_token
        assert "insecure permissions" in caplog.text
        assert "644" in caplog.text

    def test_load_insecure_file_raises_strict(self, tmp_path: Path) -> None:
        """Loading a 0644 file in strict mode raises InsecureTokenFileError."""
        manager = ServerTokenManager(port=9999, nexus_dir=tmp_path, strict_permissions=True)
        expected_token = generate_api_key()

        # Create token file with insecure permissions
        token_file = tmp_path / "rpc-9999.token"
        token_file.write_text(expected_token)
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        with pytest.raises(InsecureTokenFileError):
            manager.load()

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Loading from nonexistent file returns None."""
        manager = ServerTokenManager(port=9999, nexus_dir=tmp_path)
        token = manager.load()
        assert token is None


class TestDiscoverRpcToken:
    """Tests for discover_rpc_token() permission checks."""

    def test_discover_secure_file_succeeds(self, tmp_path: Path) -> None:
        """Discovering a 0600 token file succeeds."""
        expected_token = generate_api_key()

        # Create token file with secure permissions
        token_file = tmp_path / "rpc.token"
        fd = os.open(str(token_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(expected_token)

        token = discover_rpc_token(nexus_dir=tmp_path)
        assert token == expected_token

    def test_discover_insecure_file_warns_nonstrict(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Discovering a 0644 file in non-strict mode warns but succeeds."""
        expected_token = generate_api_key()

        # Create token file with insecure permissions
        token_file = tmp_path / "rpc.token"
        token_file.write_text(expected_token)
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        import logging
        with caplog.at_level(logging.WARNING):
            token = discover_rpc_token(nexus_dir=tmp_path, strict_permissions=False)

        assert token == expected_token
        assert "insecure permissions" in caplog.text

    def test_discover_insecure_file_skips_strict(self, tmp_path: Path) -> None:
        """Discovering a 0644 file in strict mode returns None."""
        expected_token = generate_api_key()

        # Create token file with insecure permissions
        token_file = tmp_path / "rpc.token"
        token_file.write_text(expected_token)
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        token = discover_rpc_token(nexus_dir=tmp_path, strict_permissions=True)
        assert token is None

    def test_discover_falls_through_to_secure_file_strict(self, tmp_path: Path) -> None:
        """In strict mode, skips insecure port-specific and uses secure default."""
        expected_token = generate_api_key()
        insecure_token = generate_api_key()

        # Create insecure port-specific token
        port_file = tmp_path / "rpc-9999.token"
        port_file.write_text(insecure_token)
        os.chmod(port_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)  # 0640

        # Create secure default token
        default_file = tmp_path / "rpc.token"
        fd = os.open(str(default_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(expected_token)

        token = discover_rpc_token(port=9999, nexus_dir=tmp_path, strict_permissions=True)
        assert token == expected_token  # Should get the secure default, not the insecure port-specific

    def test_discover_env_var_bypasses_file_check(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable token bypasses file permission checks."""
        expected_token = generate_api_key()
        monkeypatch.setenv("NEXUS3_API_KEY", expected_token)

        # Create insecure file (shouldn't matter)
        token_file = tmp_path / "rpc.token"
        token_file.write_text("different_token")
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

        token = discover_rpc_token(nexus_dir=tmp_path, strict_permissions=True)
        assert token == expected_token


class TestInsecureTokenFileError:
    """Tests for InsecureTokenFileError exception."""

    def test_error_message_includes_path(self, tmp_path: Path) -> None:
        """Error message includes the token file path."""
        token_file = tmp_path / "my_token"
        error = InsecureTokenFileError(token_file, 0o644)
        assert str(token_file) in str(error)

    def test_error_message_includes_current_mode(self, tmp_path: Path) -> None:
        """Error message includes the current permission mode."""
        token_file = tmp_path / "my_token"
        error = InsecureTokenFileError(token_file, 0o644)
        assert "644" in str(error)

    def test_error_message_includes_fix_command(self, tmp_path: Path) -> None:
        """Error message includes the chmod fix command."""
        token_file = tmp_path / "my_token"
        error = InsecureTokenFileError(token_file, 0o644)
        assert "chmod 600" in str(error)

    def test_error_stores_path_and_mode(self, tmp_path: Path) -> None:
        """Error stores path and mode as attributes."""
        token_file = tmp_path / "my_token"
        error = InsecureTokenFileError(token_file, 0o755)
        assert error.path == token_file
        assert error.mode == 0o755


class TestWindowsPermissionSkip:
    """Tests for Windows permission check bypass.

    On Windows, POSIX permission bits (st_mode) are meaningless since Windows
    uses ACLs. The permission check is skipped on Windows and always returns True.
    """

    @pytest.mark.windows_mock
    def test_permission_check_skipped_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows, permission check always returns True."""
        # Mock sys.platform to simulate Windows
        import sys
        monkeypatch.setattr(sys, "platform", "win32")

        # Create token file - permissions don't matter on Windows
        token_file = tmp_path / "token"
        token_file.write_text("test_token")

        # Even without setting any specific permissions, should return True
        result = check_token_file_permissions(token_file, strict=True)
        assert result is True

    @pytest.mark.windows_mock
    def test_permission_check_skipped_even_if_insecure_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows, 'insecure' permissions don't trigger warnings."""
        import sys
        monkeypatch.setattr(sys, "platform", "win32")

        token_file = tmp_path / "token"
        token_file.write_text("test_token")
        # Set permissions that would be insecure on Unix
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0644

        # On Windows, this should still return True (permissions ignored)
        result = check_token_file_permissions(token_file, strict=True)
        assert result is True
