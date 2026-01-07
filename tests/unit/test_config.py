"""Unit tests for nexus3.config module."""

import pytest

from nexus3.config.loader import load_config
from nexus3.config.schema import Config, ProviderConfig
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
        """ProviderConfig accepts custom values."""
        pc = ProviderConfig(
            type="custom",
            api_key_env="CUSTOM_API_KEY",
            model="custom/model",
            base_url="https://custom.api.com/v1",
        )
        assert pc.type == "custom"
        assert pc.api_key_env == "CUSTOM_API_KEY"
        assert pc.model == "custom/model"
        assert pc.base_url == "https://custom.api.com/v1"


class TestConfig:
    """Tests for Config schema."""

    def test_config_defaults(self):
        """Config() has expected default values."""
        cfg = Config()
        assert cfg.stream_output is True
        assert isinstance(cfg.provider, ProviderConfig)

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
