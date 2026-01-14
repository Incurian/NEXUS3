"""Unit tests for nexus3.config module."""

import os
import warnings

import pytest
from pydantic import ValidationError

from nexus3.config.loader import load_config
from nexus3.config.schema import (
    Config,
    PermissionPresetConfig,
    ProviderConfig,
    ServerConfig,
    ToolPermissionConfig,
)
from nexus3.core.errors import ConfigError


class TestProviderConfig:
    """Tests for ProviderConfig schema."""

    def test_provider_config_defaults(self):
        """ProviderConfig has expected default values."""
        pc = ProviderConfig()
        assert pc.type == "openrouter"
        assert pc.api_key_env == "OPENROUTER_API_KEY"
        assert pc.model == "x-ai/grok-code-fast-1"
        assert pc.base_url == "https://openrouter.ai/api/v1"

    def test_provider_config_custom_values(self):
        """ProviderConfig accepts custom values for valid provider types."""
        pc = ProviderConfig(
            type="openai",
            api_key_env="CUSTOM_API_KEY",
            model="custom/model",
            base_url="https://custom.api.com/v1",
        )
        assert pc.type == "openai"
        assert pc.api_key_env == "CUSTOM_API_KEY"
        assert pc.model == "custom/model"
        assert pc.base_url == "https://custom.api.com/v1"

    def test_provider_config_rejects_invalid_type(self):
        """ProviderConfig rejects invalid provider types."""
        with pytest.raises(ValidationError, match="Input should be"):
            ProviderConfig(type="invalid_provider")

    def test_provider_config_timeout_defaults(self):
        """ProviderConfig has timeout/retry defaults."""
        pc = ProviderConfig()
        assert pc.request_timeout == 120.0
        assert pc.max_retries == 3
        assert pc.retry_backoff == 1.5

    def test_provider_config_timeout_custom(self):
        """ProviderConfig accepts custom timeout/retry values."""
        pc = ProviderConfig(request_timeout=60.0, max_retries=5, retry_backoff=2.0)
        assert pc.request_timeout == 60.0
        assert pc.max_retries == 5
        assert pc.retry_backoff == 2.0

    def test_provider_config_timeout_validation(self):
        """ProviderConfig validates timeout/retry constraints."""
        with pytest.raises(ValidationError):
            ProviderConfig(request_timeout=0)  # Must be > 0
        with pytest.raises(ValidationError):
            ProviderConfig(max_retries=-1)  # Must be >= 0
        with pytest.raises(ValidationError):
            ProviderConfig(retry_backoff=0.5)  # Must be >= 1.0


class TestServerConfig:
    """Tests for ServerConfig schema."""

    def test_server_config_defaults(self):
        """ServerConfig has expected default values."""
        sc = ServerConfig()
        assert sc.host == "127.0.0.1"
        assert sc.port == 8765
        assert sc.log_level == "INFO"

    def test_server_config_custom_values(self):
        """ServerConfig accepts custom values."""
        sc = ServerConfig(host="0.0.0.0", port=9000, log_level="DEBUG")
        assert sc.host == "0.0.0.0"
        assert sc.port == 9000
        assert sc.log_level == "DEBUG"

    def test_server_config_port_validation(self):
        """ServerConfig validates port range."""
        with pytest.raises(ValidationError):
            ServerConfig(port=0)  # Must be >= 1
        with pytest.raises(ValidationError):
            ServerConfig(port=70000)  # Must be <= 65535

    def test_server_config_log_level_validation(self):
        """ServerConfig validates log_level enum."""
        with pytest.raises(ValidationError):
            ServerConfig(log_level="INVALID")


class TestPathValidation:
    """Tests for path normalization in permission configs."""

    def test_tool_permission_normalizes_relative_path(self, tmp_path):
        """ToolPermissionConfig normalizes relative paths to absolute."""
        # Create actual directory
        test_dir = tmp_path / "testdir"
        test_dir.mkdir()

        # Use cwd-relative path by changing to tmp_path
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            tpc = ToolPermissionConfig(allowed_paths=["testdir"])
            assert tpc.allowed_paths is not None
            assert len(tpc.allowed_paths) == 1
            assert os.path.isabs(tpc.allowed_paths[0])
            assert tpc.allowed_paths[0] == str(test_dir)
        finally:
            os.chdir(old_cwd)

    def test_tool_permission_expands_tilde(self, tmp_path, monkeypatch):
        """ToolPermissionConfig expands ~ to home directory."""
        # Mock home directory
        monkeypatch.setenv("HOME", str(tmp_path))
        test_dir = tmp_path / "mydir"
        test_dir.mkdir()

        tpc = ToolPermissionConfig(allowed_paths=["~/mydir"])
        assert tpc.allowed_paths is not None
        assert tpc.allowed_paths[0] == str(test_dir)

    def test_tool_permission_warns_nonexistent_path(self):
        """ToolPermissionConfig warns when path doesn't exist."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ToolPermissionConfig(allowed_paths=["/nonexistent/path/12345"])
            assert len(w) == 1
            assert "does not exist" in str(w[0].message)

    def test_tool_permission_warns_file_not_directory(self, tmp_path):
        """ToolPermissionConfig warns when path is a file, not directory."""
        test_file = tmp_path / "testfile.txt"
        test_file.write_text("content")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ToolPermissionConfig(allowed_paths=[str(test_file)])
            assert len(w) == 1
            assert "not a directory" in str(w[0].message)

    def test_tool_permission_none_allowed_paths_unchanged(self):
        """ToolPermissionConfig leaves None as None (inherit from preset)."""
        tpc = ToolPermissionConfig(allowed_paths=None)
        assert tpc.allowed_paths is None

    def test_tool_permission_empty_list_unchanged(self):
        """ToolPermissionConfig preserves empty list (deny all)."""
        tpc = ToolPermissionConfig(allowed_paths=[])
        assert tpc.allowed_paths == []

    def test_preset_normalizes_allowed_paths(self, tmp_path):
        """PermissionPresetConfig normalizes allowed_paths."""
        test_dir = tmp_path / "allowed"
        test_dir.mkdir()

        ppc = PermissionPresetConfig(allowed_paths=[str(test_dir)])
        assert ppc.allowed_paths is not None
        assert ppc.allowed_paths[0] == str(test_dir)

    def test_preset_normalizes_blocked_paths(self, tmp_path):
        """PermissionPresetConfig normalizes blocked_paths."""
        test_dir = tmp_path / "blocked"
        test_dir.mkdir()

        ppc = PermissionPresetConfig(blocked_paths=[str(test_dir)])
        assert ppc.blocked_paths[0] == str(test_dir)

    def test_preset_blocked_paths_default_empty(self):
        """PermissionPresetConfig defaults blocked_paths to empty list."""
        ppc = PermissionPresetConfig()
        assert ppc.blocked_paths == []


class TestConfig:
    """Tests for Config schema."""

    def test_config_defaults(self):
        """Config() has expected default values."""
        cfg = Config()
        assert cfg.stream_output is True
        assert isinstance(cfg.provider, ProviderConfig)
        assert cfg.config_version == 1
        assert isinstance(cfg.server, ServerConfig)

    def test_config_provider_defaults(self):
        """Default Config has default ProviderConfig."""
        cfg = Config()
        assert cfg.provider.type == "openrouter"
        assert cfg.provider.model == "x-ai/grok-code-fast-1"

    def test_config_custom_stream_output(self):
        """Config accepts custom stream_output value."""
        cfg = Config(stream_output=False)
        assert cfg.stream_output is False


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        """load_config() returns default Config when no config file exists."""
        # Change to a directory with no config files
        monkeypatch.chdir(tmp_path)
        # Also ensure home directory check doesn't find a config
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        # Force Path.home() to return fake_home
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        cfg = load_config()
        assert isinstance(cfg, Config)
        assert cfg.stream_output is True
        assert cfg.provider.type == "openrouter"

    def test_load_config_raises_on_invalid_json(self, tmp_path):
        """load_config() raises ConfigError on invalid JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{ invalid json }", encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            load_config(path=config_file)

        assert "Invalid JSON" in str(exc_info.value)

    def test_load_config_raises_on_missing_explicit_path(self, tmp_path):
        """load_config() raises ConfigError when explicit path doesn't exist."""
        nonexistent = tmp_path / "nonexistent.json"

        with pytest.raises(ConfigError) as exc_info:
            load_config(path=nonexistent)

        assert "Config file not found" in str(exc_info.value)

    def test_load_config_loads_valid_json(self, tmp_path):
        """load_config() successfully loads valid JSON config."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"stream_output": false, "provider": {"model": "test/model"}}',
            encoding="utf-8",
        )

        cfg = load_config(path=config_file)
        assert cfg.stream_output is False
        assert cfg.provider.model == "test/model"
        # Other provider fields should have defaults
        assert cfg.provider.type == "openrouter"

    def test_load_config_raises_on_validation_error(self, tmp_path):
        """load_config() raises ConfigError on validation failure."""
        config_file = tmp_path / "config.json"
        # stream_output should be bool, not string
        config_file.write_text('{"stream_output": "not_a_bool"}', encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            load_config(path=config_file)

        assert "validation failed" in str(exc_info.value)
