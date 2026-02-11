"""Unit tests for nexus3.config module."""

import os
import warnings

import pytest
from pydantic import ValidationError

from nexus3.config.loader import load_config
from nexus3.config.schema import (
    Config,
    ModelConfig,
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
        assert pc.base_url == "https://openrouter.ai/api/v1"
        assert pc.models == {}

    def test_provider_config_custom_values(self):
        """ProviderConfig accepts custom values for valid provider types."""
        pc = ProviderConfig(
            type="openai",
            api_key_env="CUSTOM_API_KEY",
            base_url="https://custom.api.com/v1",
            models={
                "test": ModelConfig(id="custom/model", context_window=100000)
            },
        )
        assert pc.type == "openai"
        assert pc.api_key_env == "CUSTOM_API_KEY"
        assert pc.base_url == "https://custom.api.com/v1"
        assert "test" in pc.models
        assert pc.models["test"].id == "custom/model"

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


class TestModelConfig:
    """Tests for ModelConfig schema."""

    def test_model_config_required_id(self):
        """ModelConfig requires id field."""
        with pytest.raises(ValidationError):
            ModelConfig()  # id is required

    def test_model_config_defaults(self):
        """ModelConfig has expected default values."""
        mc = ModelConfig(id="test/model")
        assert mc.id == "test/model"
        assert mc.context_window == 131072
        assert mc.reasoning is False

    def test_model_config_custom(self):
        """ModelConfig accepts custom values."""
        mc = ModelConfig(id="test/model", context_window=200000, reasoning=True)
        assert mc.context_window == 200000
        assert mc.reasoning is True


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
        """Config() with minimal valid config has expected defaults."""
        cfg = Config(
            default_model="test/haiku",
            providers={
                "test": ProviderConfig(
                    models={"haiku": ModelConfig(id="test/model")}
                )
            },
        )
        assert cfg.stream_output is True
        assert cfg.default_model == "test/haiku"
        assert isinstance(cfg.server, ServerConfig)

    def test_config_validates_default_model_exists(self):
        """Config validates default_model references existing alias."""
        with pytest.raises(ValidationError, match="Unknown model alias"):
            Config(default_model="nonexistent")

    def test_config_validates_default_model_provider_exists(self):
        """Config validates explicit provider/alias format."""
        with pytest.raises(ValidationError, match="Unknown provider"):
            Config(default_model="nonexistent/model")

    def test_config_validates_unique_aliases(self):
        """Config validates model aliases are globally unique."""
        with pytest.raises(ValidationError, match="Duplicate model alias"):
            Config(
                default_model="p1/haiku",
                providers={
                    "p1": ProviderConfig(
                        models={"haiku": ModelConfig(id="m1")}
                    ),
                    "p2": ProviderConfig(
                        models={"haiku": ModelConfig(id="m2")}  # Duplicate!
                    ),
                },
            )

    def test_config_resolve_model(self):
        """Config.resolve_model resolves aliases correctly."""
        cfg = Config(
            default_model="haiku",  # Just alias, no provider prefix
            providers={
                "openrouter": ProviderConfig(
                    models={
                        "haiku": ModelConfig(id="anthropic/claude-haiku-4.5", context_window=200000)
                    }
                ),
                "anthropic": ProviderConfig(
                    type="anthropic",
                    models={
                        "native": ModelConfig(id="claude-haiku-4-5", context_window=200000)
                    }
                ),
            },
        )

        # Default model (just alias)
        resolved = cfg.resolve_model()
        assert resolved.model_id == "anthropic/claude-haiku-4.5"
        assert resolved.provider_name == "openrouter"
        assert resolved.alias == "haiku"

        # By alias
        resolved = cfg.resolve_model("native")
        assert resolved.model_id == "claude-haiku-4-5"
        assert resolved.provider_name == "anthropic"

        # By explicit provider/alias (still works)
        resolved = cfg.resolve_model("anthropic/native")
        assert resolved.model_id == "claude-haiku-4-5"
        assert resolved.provider_name == "anthropic"


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
        # Default config should have providers
        assert len(cfg.providers) > 0

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

        assert "File not found" in str(exc_info.value)

    def test_load_config_loads_valid_json(self, tmp_path):
        """load_config() successfully loads valid JSON config."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            """{
                "default_model": "test/model",
                "stream_output": false,
                "providers": {
                    "test": {
                        "type": "openrouter",
                        "models": {
                            "model": {"id": "actual/model-id"}
                        }
                    }
                }
            }""",
            encoding="utf-8",
        )

        cfg = load_config(path=config_file)
        assert cfg.stream_output is False
        assert cfg.default_model == "test/model"
        assert "test" in cfg.providers
        resolved = cfg.resolve_model()
        assert resolved.model_id == "actual/model-id"

    def test_load_config_raises_on_validation_error(self, tmp_path):
        """load_config() raises ConfigError on validation failure."""
        config_file = tmp_path / "config.json"
        # stream_output should be bool, not string
        config_file.write_text('{"stream_output": "not_a_bool"}', encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            load_config(path=config_file)

        assert "validation failed" in str(exc_info.value)


class TestContextConfigInstructionFiles:
    """Tests for instruction_files config field and deprecated field migration."""

    def test_default_instruction_files(self) -> None:
        """Default instruction_files has correct priority."""
        from nexus3.config.schema import ContextConfig

        config = ContextConfig()
        assert config.instruction_files == ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]

    def test_rejects_path_in_instruction_files(self) -> None:
        """Paths in instruction_files are rejected."""
        from nexus3.config.schema import ContextConfig

        with pytest.raises(Exception):
            ContextConfig(instruction_files=["../NEXUS.md"])

    def test_rejects_non_md_instruction_files(self) -> None:
        """Non-.md files in instruction_files are rejected."""
        from nexus3.config.schema import ContextConfig

        with pytest.raises(Exception):
            ContextConfig(instruction_files=["NEXUS.txt"])

    def test_deprecated_include_readme_migration(self) -> None:
        """Old include_readme field is migrated to instruction_files."""
        from nexus3.config.schema import Config

        data = {
            "context": {
                "include_readme": True,
                "readme_as_fallback": False,
            },
            "providers": {
                "test": {
                    "type": "openrouter",
                    "models": {"m": {"id": "test/model", "context_window": 1000}},
                }
            },
            "default_model": "m",
        }
        config = Config.model_validate(data)
        assert "README.md" in config.context.instruction_files

    def test_deprecated_fields_removed_when_instruction_files_present(self) -> None:
        """Old fields are silently removed when instruction_files is set."""
        from nexus3.config.schema import Config

        data = {
            "context": {
                "instruction_files": ["NEXUS.md"],
                "include_readme": True,
            },
            "providers": {
                "test": {
                    "type": "openrouter",
                    "models": {"m": {"id": "test/model", "context_window": 1000}},
                }
            },
            "default_model": "m",
        }
        config = Config.model_validate(data)
        assert config.context.instruction_files == ["NEXUS.md"]

    def test_deprecated_fields_without_readme(self) -> None:
        """When both old fields are false, README.md is not added."""
        from nexus3.config.schema import Config

        data = {
            "context": {
                "include_readme": False,
                "readme_as_fallback": False,
            },
            "providers": {
                "test": {
                    "type": "openrouter",
                    "models": {"m": {"id": "test/model", "context_window": 1000}},
                }
            },
            "default_model": "m",
        }
        config = Config.model_validate(data)
        assert "README.md" not in config.context.instruction_files
