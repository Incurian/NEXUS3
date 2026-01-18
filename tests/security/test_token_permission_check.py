"""Tests for Fix 2.4: Token Permission Check in client_commands.

This tests verifies that the CLI's _get_api_key() function uses discover_rpc_token()
for token discovery, ensuring permission checks are not bypassed.

The key security property: All token discovery should go through discover_rpc_token()
which performs file permission checks (P2.8). No direct file reads should bypass this.
"""

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus3.cli.client_commands import _get_api_key
from nexus3.rpc.auth import discover_rpc_token, generate_api_key


class TestGetApiKeyUsesDiscoverRpcToken:
    """Verify _get_api_key() delegates to discover_rpc_token()."""

    def test_explicit_api_key_returned_directly(self) -> None:
        """Explicit api_key parameter is returned without discovery."""
        explicit_key = "explicit_test_key_12345"
        result = _get_api_key(port=8765, api_key=explicit_key)
        assert result == explicit_key

    def test_none_api_key_triggers_discovery(self, tmp_path: Path) -> None:
        """When api_key=None, discover_rpc_token() is called."""
        expected_token = generate_api_key()

        # Create a secure token file
        token_file = tmp_path / "rpc.token"
        fd = os.open(str(token_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(expected_token)

        # Patch discover_rpc_token to use our tmp_path
        with patch("nexus3.cli.client_commands.discover_rpc_token") as mock_discover:
            mock_discover.return_value = expected_token
            result = _get_api_key(port=8765, api_key=None)

        mock_discover.assert_called_once_with(port=8765)
        assert result == expected_token

    def test_correct_port_passed_to_discovery(self) -> None:
        """The port parameter is correctly passed to discover_rpc_token()."""
        with patch("nexus3.cli.client_commands.discover_rpc_token") as mock_discover:
            mock_discover.return_value = None

            _get_api_key(port=9999, api_key=None)
            mock_discover.assert_called_once_with(port=9999)

            mock_discover.reset_mock()

            _get_api_key(port=8765, api_key=None)
            mock_discover.assert_called_once_with(port=8765)

            mock_discover.reset_mock()

            _get_api_key(port=12345, api_key=None)
            mock_discover.assert_called_once_with(port=12345)

    def test_discovery_result_returned(self) -> None:
        """The result from discover_rpc_token() is returned."""
        test_token = "nxk_discovered_token_abc123"

        with patch("nexus3.cli.client_commands.discover_rpc_token") as mock_discover:
            mock_discover.return_value = test_token
            result = _get_api_key(port=8765, api_key=None)

        assert result == test_token

    def test_discovery_returns_none_when_no_token(self) -> None:
        """When discover_rpc_token() returns None, _get_api_key() returns None."""
        with patch("nexus3.cli.client_commands.discover_rpc_token") as mock_discover:
            mock_discover.return_value = None
            result = _get_api_key(port=8765, api_key=None)

        assert result is None


class TestClientCommandsPermissionCheckIntegration:
    """Integration tests verifying permission checks are performed."""

    def test_insecure_token_file_skipped_in_strict_mode(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An insecure token file is skipped in strict mode (default) with warning."""
        # Clear any existing env var
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        expected_token = generate_api_key()

        # Create token file with insecure permissions (0644)
        token_file = tmp_path / "rpc.token"
        token_file.write_text(expected_token)
        os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

        # Patch get_nexus_dir to use our tmp_path
        with patch("nexus3.rpc.auth.get_nexus_dir", return_value=tmp_path):
            import logging
            with caplog.at_level(logging.WARNING):
                result = _get_api_key(port=8765, api_key=None)

        # Token is NOT returned in strict mode (file is skipped)
        assert result is None
        # Warning was logged about insecure permissions
        assert "insecure permissions" in caplog.text

    def test_secure_token_file_no_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A secure token file does not trigger any warning."""
        # Clear any existing env var
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        expected_token = generate_api_key()

        # Create token file with secure permissions (0600)
        token_file = tmp_path / "rpc.token"
        fd = os.open(str(token_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(expected_token)

        # Patch get_nexus_dir to use our tmp_path
        with patch("nexus3.rpc.auth.get_nexus_dir", return_value=tmp_path):
            import logging
            with caplog.at_level(logging.WARNING):
                result = _get_api_key(port=8765, api_key=None)

        assert result == expected_token
        assert "insecure permissions" not in caplog.text

    def test_port_specific_token_file_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Port-specific token file is found when correct port is passed."""
        # Clear any existing env var
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        port_token = generate_api_key()
        default_token = generate_api_key()

        # Create port-specific token file (0600)
        port_file = tmp_path / "rpc-9999.token"
        fd = os.open(str(port_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(port_token)

        # Create default token file (0600)
        default_file = tmp_path / "rpc.token"
        fd = os.open(str(default_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(default_token)

        # Patch get_nexus_dir to use our tmp_path
        with patch("nexus3.rpc.auth.get_nexus_dir", return_value=tmp_path):
            result = _get_api_key(port=9999, api_key=None)

        # Should get port-specific token
        assert result == port_token

    def test_default_token_file_used_for_default_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default token file (rpc.token) is used for port 8765."""
        # Clear any existing env var
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        default_token = generate_api_key()

        # Create default token file (0600)
        default_file = tmp_path / "rpc.token"
        fd = os.open(str(default_file), os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(default_token)

        # Patch get_nexus_dir to use our tmp_path
        with patch("nexus3.rpc.auth.get_nexus_dir", return_value=tmp_path):
            result = _get_api_key(port=8765, api_key=None)

        assert result == default_token
