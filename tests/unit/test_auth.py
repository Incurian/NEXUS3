"""Unit tests for nexus3.rpc.auth module."""

import os
import stat
import string

import pytest

from nexus3.rpc.auth import (
    API_KEY_PREFIX,
    ServerKeyManager,
    discover_api_key,
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


# === ServerKeyManager tests ===


class TestServerKeyManager:
    """Tests for ServerKeyManager class."""

    def test_default_port_uses_server_key(self, tmp_path):
        """Default port (8765) uses server.key filename."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        assert manager.key_path == tmp_path / "server.key"

    def test_non_default_port_uses_port_specific_key(self, tmp_path):
        """Non-default ports use server-{port}.key filename."""
        manager = ServerKeyManager(port=9000, nexus_dir=tmp_path)
        assert manager.key_path == tmp_path / "server-9000.key"

    def test_various_ports(self, tmp_path):
        """Test various port numbers for correct key path."""
        test_cases = [
            (8765, "server.key"),
            (8000, "server-8000.key"),
            (9999, "server-9999.key"),
            (1, "server-1.key"),
        ]
        for port, expected_filename in test_cases:
            manager = ServerKeyManager(port=port, nexus_dir=tmp_path)
            assert manager.key_path.name == expected_filename

    def test_generate_and_save_creates_file(self, tmp_path):
        """generate_and_save creates key file."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        key = manager.generate_and_save()

        assert manager.key_path.exists()
        assert manager.key_path.read_text(encoding="utf-8") == key

    def test_generate_and_save_returns_valid_key(self, tmp_path):
        """generate_and_save returns a valid API key."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        key = manager.generate_and_save()

        assert key.startswith(API_KEY_PREFIX)
        assert len(key) == 47

    def test_generate_and_save_creates_directory(self, tmp_path):
        """generate_and_save creates nexus_dir if it doesn't exist."""
        nested_dir = tmp_path / "nested" / "dir" / ".nexus3"
        manager = ServerKeyManager(port=8765, nexus_dir=nested_dir)

        assert not nested_dir.exists()
        manager.generate_and_save()
        assert nested_dir.exists()

    def test_generate_and_save_sets_permissions(self, tmp_path):
        """generate_and_save sets file permissions to 0o600."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        manager.generate_and_save()

        file_stat = manager.key_path.stat()
        # Extract permission bits (last 9 bits of mode)
        permissions = stat.S_IMODE(file_stat.st_mode)
        assert permissions == 0o600

    def test_load_returns_saved_key(self, tmp_path):
        """load returns the key that was saved."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        saved_key = manager.generate_and_save()

        loaded_key = manager.load()
        assert loaded_key == saved_key

    def test_load_returns_none_when_file_missing(self, tmp_path):
        """load returns None when key file doesn't exist."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)

        assert manager.load() is None

    def test_load_strips_whitespace(self, tmp_path):
        """load strips whitespace from key file contents."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)

        # Manually write key with extra whitespace
        manager.key_path.parent.mkdir(parents=True, exist_ok=True)
        manager.key_path.write_text("  nxk_testkey123  \n", encoding="utf-8")

        loaded = manager.load()
        assert loaded == "nxk_testkey123"

    def test_delete_removes_key_file(self, tmp_path):
        """delete removes the key file."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        manager.generate_and_save()

        assert manager.key_path.exists()
        manager.delete()
        assert not manager.key_path.exists()

    def test_delete_succeeds_when_file_missing(self, tmp_path):
        """delete silently succeeds when file doesn't exist."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)

        # Should not raise
        manager.delete()

    def test_port_property(self, tmp_path):
        """port property returns configured port."""
        manager = ServerKeyManager(port=9001, nexus_dir=tmp_path)
        assert manager.port == 9001

    def test_nexus_dir_property(self, tmp_path):
        """nexus_dir property returns configured directory."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)
        assert manager.nexus_dir == tmp_path

    def test_regenerate_overwrites_existing_key(self, tmp_path):
        """Calling generate_and_save twice overwrites the key."""
        manager = ServerKeyManager(port=8765, nexus_dir=tmp_path)

        first_key = manager.generate_and_save()
        second_key = manager.generate_and_save()

        # Keys should be different
        assert first_key != second_key
        # File should contain the second key
        assert manager.load() == second_key


# === discover_api_key() tests ===


class TestDiscoverApiKey:
    """Tests for discover_api_key function."""

    def test_returns_env_var_if_set(self, tmp_path, monkeypatch):
        """discover_api_key returns NEXUS3_API_KEY env var if set."""
        env_key = "nxk_from_environment"
        monkeypatch.setenv("NEXUS3_API_KEY", env_key)

        result = discover_api_key(port=8765, nexus_dir=tmp_path)
        assert result == env_key

    def test_env_var_strips_whitespace(self, tmp_path, monkeypatch):
        """discover_api_key strips whitespace from env var."""
        monkeypatch.setenv("NEXUS3_API_KEY", "  nxk_with_spaces  ")

        result = discover_api_key(port=8765, nexus_dir=tmp_path)
        assert result == "nxk_with_spaces"

    def test_returns_port_specific_file_if_exists(self, tmp_path, monkeypatch):
        """discover_api_key returns port-specific key file for non-default port."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create port-specific key file
        port_key = "nxk_port_specific"
        port_file = tmp_path / "server-9000.key"
        port_file.write_text(port_key, encoding="utf-8")

        result = discover_api_key(port=9000, nexus_dir=tmp_path)
        assert result == port_key

    def test_returns_default_file_if_exists(self, tmp_path, monkeypatch):
        """discover_api_key returns default key file."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create default key file
        default_key = "nxk_default_key"
        default_file = tmp_path / "server.key"
        default_file.write_text(default_key, encoding="utf-8")

        result = discover_api_key(port=8765, nexus_dir=tmp_path)
        assert result == default_key

    def test_returns_none_if_nothing_found(self, tmp_path, monkeypatch):
        """discover_api_key returns None when no key source exists."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        result = discover_api_key(port=8765, nexus_dir=tmp_path)
        assert result is None

    def test_priority_env_var_over_files(self, tmp_path, monkeypatch):
        """discover_api_key prefers env var over file-based keys."""
        env_key = "nxk_from_env"
        file_key = "nxk_from_file"

        monkeypatch.setenv("NEXUS3_API_KEY", env_key)
        (tmp_path / "server.key").write_text(file_key, encoding="utf-8")

        result = discover_api_key(port=8765, nexus_dir=tmp_path)
        assert result == env_key

    def test_priority_port_specific_over_default(self, tmp_path, monkeypatch):
        """discover_api_key prefers port-specific over default for non-default ports."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        port_key = "nxk_port_specific"
        default_key = "nxk_default"

        (tmp_path / "server-9000.key").write_text(port_key, encoding="utf-8")
        (tmp_path / "server.key").write_text(default_key, encoding="utf-8")

        result = discover_api_key(port=9000, nexus_dir=tmp_path)
        assert result == port_key

    def test_default_port_only_checks_default_file(self, tmp_path, monkeypatch):
        """For default port (8765), only server.key is checked, not server-8765.key."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # This file should NOT be found for default port
        (tmp_path / "server-8765.key").write_text("nxk_wrong", encoding="utf-8")

        result = discover_api_key(port=8765, nexus_dir=tmp_path)
        assert result is None  # server.key doesn't exist

    def test_falls_back_to_default_when_port_specific_missing(self, tmp_path, monkeypatch):
        """discover_api_key falls back to default file for non-default ports."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        default_key = "nxk_default_fallback"
        (tmp_path / "server.key").write_text(default_key, encoding="utf-8")

        # Port-specific file doesn't exist
        result = discover_api_key(port=9000, nexus_dir=tmp_path)
        assert result == default_key

    def test_ignores_empty_key_files(self, tmp_path, monkeypatch):
        """discover_api_key ignores key files that are empty or whitespace-only."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create empty port-specific file
        (tmp_path / "server-9000.key").write_text("", encoding="utf-8")

        # Create valid default file
        default_key = "nxk_valid"
        (tmp_path / "server.key").write_text(default_key, encoding="utf-8")

        result = discover_api_key(port=9000, nexus_dir=tmp_path)
        assert result == default_key

    def test_ignores_whitespace_only_key_files(self, tmp_path, monkeypatch):
        """discover_api_key ignores whitespace-only key files."""
        monkeypatch.delenv("NEXUS3_API_KEY", raising=False)

        # Create whitespace-only port-specific file
        (tmp_path / "server-9000.key").write_text("   \n  ", encoding="utf-8")

        # Create valid default file
        default_key = "nxk_valid"
        (tmp_path / "server.key").write_text(default_key, encoding="utf-8")

        result = discover_api_key(port=9000, nexus_dir=tmp_path)
        assert result == default_key
