"""Unit tests for nexus3.rpc.auth module."""

import os
import stat
import string

import pytest

from nexus3.rpc.auth import (
    API_KEY_PREFIX,
    ServerTokenManager,
    discover_rpc_token,
    generate_api_key,
    validate_api_key,
)


# === generate_api_key() tests ===


class TestGenerateApiKey:
    """Tests for generate_api_key function."""

    def test_key_starts_with_prefix(self):
        """Generated key starts with nxk_ prefix."""
        key = generate_api_key()
        assert key.startswith(API_KEY_PREFIX)
        assert key.startswith("nxk_")

    def test_key_has_correct_length(self):
        """Generated key has correct length (prefix + 43 chars base64)."""
        key = generate_api_key()
        # secrets.token_urlsafe(32) produces 43 characters
        # Total: 4 (prefix) + 43 (base64) = 47
        assert len(key) == 47

    def test_multiple_calls_generate_different_keys(self):
        """Multiple calls to generate_api_key produce different keys."""
        keys = [generate_api_key() for _ in range(100)]
        # All keys should be unique
        assert len(set(keys)) == 100

    def test_key_is_url_safe(self):
        """Generated key only contains URL-safe characters."""
        # URL-safe base64 uses: A-Z, a-z, 0-9, -, _
        url_safe_chars = set(string.ascii_letters + string.digits + "-_")

        for _ in range(100):
            key = generate_api_key()
            # Remove prefix before checking
            token_part = key[len(API_KEY_PREFIX):]
            for char in token_part:
                assert char in url_safe_chars, f"Non-URL-safe char: {char!r}"


# === validate_api_key() tests ===


class TestValidateApiKey:
    """Tests for validate_api_key function."""

    def test_returns_true_for_matching_keys(self):
        """validate_api_key returns True for identical keys."""
        key = generate_api_key()
        assert validate_api_key(key, key) is True

    def test_returns_false_for_non_matching_keys(self):
        """validate_api_key returns False for different keys."""
        key1 = generate_api_key()
        key2 = generate_api_key()
        assert validate_api_key(key1, key2) is False

    def test_returns_false_for_empty_provided(self):
        """validate_api_key returns False when provided key is empty."""
        expected = generate_api_key()
        assert validate_api_key("", expected) is False

    def test_returns_false_for_empty_expected(self):
        """validate_api_key returns False when expected key is empty."""
        provided = generate_api_key()
        assert validate_api_key(provided, "") is False

    def test_returns_false_for_both_empty(self):
        """validate_api_key returns False when both keys are empty."""
        assert validate_api_key("", "") is False

    def test_returns_false_for_none_like_values(self):
        """validate_api_key returns False for None-like falsy values."""
        key = generate_api_key()
        # Empty string is falsy
        assert validate_api_key("", key) is False
        assert validate_api_key(key, "") is False

    def test_partial_match_returns_false(self):
        """validate_api_key returns False for partial matches."""
        key = generate_api_key()
        partial = key[:-1]  # Remove last character
        assert validate_api_key(partial, key) is False
        assert validate_api_key(key, partial) is False

    def test_case_sensitive(self):
        """validate_api_key is case-sensitive."""
        key = "nxk_ABCdef123"
        assert validate_api_key(key.lower(), key) is False
        assert validate_api_key(key.upper(), key) is False


# === ServerTokenManager tests ===


class TestServerTokenManager:
    """Tests for ServerTokenManager class."""

    def test_default_port_uses_rpc_token(self, tmp_path):
        """Default port (8765) uses rpc.token filename."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        assert manager.token_path == tmp_path / "rpc.token"

    def test_non_default_port_uses_port_specific_token(self, tmp_path):
        """Non-default ports use rpc-{port}.token filename."""
        manager = ServerTokenManager(port=9000, nexus_dir=tmp_path)
        assert manager.token_path == tmp_path / "rpc-9000.token"

    def test_various_ports(self, tmp_path):
        """Test various port numbers for correct token path."""
        test_cases = [
            (8765, "rpc.token"),
            (8000, "rpc-8000.token"),
            (9999, "rpc-9999.token"),
            (1, "rpc-1.token"),
        ]
        for port, expected_filename in test_cases:
            manager = ServerTokenManager(port=port, nexus_dir=tmp_path)
            assert manager.token_path.name == expected_filename

    def test_generate_fresh_creates_file(self, tmp_path):
        """generate_fresh creates token file."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        token = manager.generate_fresh()

        assert manager.token_path.exists()
        assert manager.token_path.read_text(encoding="utf-8") == token

    def test_generate_fresh_returns_valid_token(self, tmp_path):
        """generate_fresh returns a valid token."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        token = manager.generate_fresh()

        assert token.startswith(API_KEY_PREFIX)
        assert len(token) == 47

    def test_generate_fresh_creates_directory(self, tmp_path):
        """generate_fresh creates nexus_dir if it doesn't exist."""
        nested_dir = tmp_path / "nested" / "dir" / ".nexus3"
        manager = ServerTokenManager(port=8765, nexus_dir=nested_dir)

        assert not nested_dir.exists()
        manager.generate_fresh()
        assert nested_dir.exists()

    def test_generate_fresh_sets_permissions(self, tmp_path):
        """generate_fresh sets file permissions to 0o600."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        manager.generate_fresh()

        file_stat = manager.token_path.stat()
        # Extract permission bits (last 9 bits of mode)
        permissions = stat.S_IMODE(file_stat.st_mode)
        assert permissions == 0o600

    def test_generate_fresh_deletes_existing_first(self, tmp_path):
        """generate_fresh deletes existing token before generating new one."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)

        # Create initial token
        first_token = manager.generate_fresh()

        # Generate fresh should create different token
        second_token = manager.generate_fresh()

        # Tokens should be different (key rotation)
        assert first_token != second_token
        # File should contain the second token
        assert manager.load() == second_token

    def test_load_returns_saved_token(self, tmp_path):
        """load returns the token that was saved."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        saved_token = manager.generate_fresh()

        loaded_token = manager.load()
        assert loaded_token == saved_token

    def test_load_returns_none_when_file_missing(self, tmp_path):
        """load returns None when token file doesn't exist."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)

        assert manager.load() is None

    def test_load_strips_whitespace(self, tmp_path):
        """load strips whitespace from token file contents."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)

        # Manually write token with extra whitespace
        manager.token_path.parent.mkdir(parents=True, exist_ok=True)
        manager.token_path.write_text("  nxk_testtoken123  \n", encoding="utf-8")

        loaded = manager.load()
        assert loaded == "nxk_testtoken123"

    def test_delete_removes_token_file(self, tmp_path):
        """delete removes the token file."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        manager.generate_fresh()

        assert manager.token_path.exists()
        manager.delete()
        assert not manager.token_path.exists()

    def test_delete_succeeds_when_file_missing(self, tmp_path):
        """delete silently succeeds when file doesn't exist."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)

        # Should not raise
        manager.delete()

    def test_port_property(self, tmp_path):
        """port property returns configured port."""
        manager = ServerTokenManager(port=9001, nexus_dir=tmp_path)
        assert manager.port == 9001

    def test_nexus_dir_property(self, tmp_path):
        """nexus_dir property returns configured directory."""
        manager = ServerTokenManager(port=8765, nexus_dir=tmp_path)
        assert manager.nexus_dir == tmp_path


# === discover_rpc_token() tests ===


class TestDiscoverRpcToken:
    """Tests for discover_rpc_token function."""

    def test_returns_env_var_if_set(self, tmp_path, monkeypatch):
        """discover_rpc_token returns NEXUS3_API_KEY env var if set."""
        env_key = "nxk_from_environment"
        monkeypatch.setenv("NEXUS3_API_KEY", env_key)

        result = discover_rpc_token(port=8765, nexus_dir=tmp_path)
        assert result == env_key

    def test_env_var_strips_whitespace(self, tmp_path, monkeypatch):
        """discover_rpc_token strips whitespace from env var."""
        monkeypatch.setenv("NEXUS3_API_KEY", "  nxk_with_spaces  ")

        result = discover_rpc_token(port=8765, nexus_dir=tmp_path)
        assert result == "nxk_with_spaces"

    def test_returns_port_specific_file_if_exists(self, tmp_path, monkeypatch):
        """discover_rpc_token returns port-specific token file for non-default port."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create port-specific token file
        port_token = "nxk_port_specific"
        port_file = tmp_path / "rpc-9000.token"
        port_file.write_text(port_token, encoding="utf-8")

        result = discover_rpc_token(port=9000, nexus_dir=tmp_path)
        assert result == port_token

    def test_returns_default_file_if_exists(self, tmp_path, monkeypatch):
        """discover_rpc_token returns default token file."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create default token file
        default_token = "nxk_default_token"
        default_file = tmp_path / "rpc.token"
        default_file.write_text(default_token, encoding="utf-8")

        result = discover_rpc_token(port=8765, nexus_dir=tmp_path)
        assert result == default_token

    def test_returns_none_if_nothing_found(self, tmp_path, monkeypatch):
        """discover_rpc_token returns None when no token source exists."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        result = discover_rpc_token(port=8765, nexus_dir=tmp_path)
        assert result is None

    def test_priority_env_var_over_files(self, tmp_path, monkeypatch):
        """discover_rpc_token prefers env var over file-based tokens."""
        env_token = "nxk_from_env"
        file_token = "nxk_from_file"

        monkeypatch.setenv("NEXUS3_API_KEY", env_token)
        (tmp_path / "rpc.token").write_text(file_token, encoding="utf-8")

        result = discover_rpc_token(port=8765, nexus_dir=tmp_path)
        assert result == env_token

    def test_priority_port_specific_over_default(self, tmp_path, monkeypatch):
        """discover_rpc_token prefers port-specific over default for non-default ports."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        port_token = "nxk_port_specific"
        default_token = "nxk_default"

        (tmp_path / "rpc-9000.token").write_text(port_token, encoding="utf-8")
        (tmp_path / "rpc.token").write_text(default_token, encoding="utf-8")

        result = discover_rpc_token(port=9000, nexus_dir=tmp_path)
        assert result == port_token

    def test_default_port_only_checks_default_file(self, tmp_path, monkeypatch):
        """For default port (8765), only rpc.token is checked, not rpc-8765.token."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # This file should NOT be found for default port
        (tmp_path / "rpc-8765.token").write_text("nxk_wrong", encoding="utf-8")

        result = discover_rpc_token(port=8765, nexus_dir=tmp_path)
        assert result is None  # rpc.token doesn't exist

    def test_falls_back_to_default_when_port_specific_missing(self, tmp_path, monkeypatch):
        """discover_rpc_token falls back to default file for non-default ports."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        default_token = "nxk_default_fallback"
        (tmp_path / "rpc.token").write_text(default_token, encoding="utf-8")

        # Port-specific file doesn't exist
        result = discover_rpc_token(port=9000, nexus_dir=tmp_path)
        assert result == default_token

    def test_ignores_empty_token_files(self, tmp_path, monkeypatch):
        """discover_rpc_token ignores token files that are empty or whitespace-only."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create empty port-specific file
        (tmp_path / "rpc-9000.token").write_text("", encoding="utf-8")

        # Create valid default file
        default_token = "nxk_valid"
        (tmp_path / "rpc.token").write_text(default_token, encoding="utf-8")

        result = discover_rpc_token(port=9000, nexus_dir=tmp_path)
        assert result == default_token

    def test_ignores_whitespace_only_token_files(self, tmp_path, monkeypatch):
        """discover_rpc_token ignores whitespace-only token files."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create whitespace-only port-specific file
        (tmp_path / "rpc-9000.token").write_text("   \n  ", encoding="utf-8")

        # Create valid default file
        default_token = "nxk_valid"
        (tmp_path / "rpc.token").write_text(default_token, encoding="utf-8")

        result = discover_rpc_token(port=9000, nexus_dir=tmp_path)
        assert result == default_token
