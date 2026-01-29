"""Tests for layered config loading."""

import json
from pathlib import Path

import pytest

from nexus3.config.load_utils import load_json_file, load_json_file_optional
from nexus3.config.loader import load_config
from nexus3.config.schema import Config
from nexus3.core.errors import ConfigError, LoadError
from nexus3.core.utils import deep_merge, find_ancestor_config_dirs


class TestLoadJsonFileOptional:
    """Tests for load_json_file_optional function."""

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Returns None when file doesn't exist."""
        result = load_json_file_optional(tmp_path / "missing.json")
        assert result is None

    def test_loads_existing_file(self, tmp_path: Path) -> None:
        """Loads and parses existing JSON file."""
        config = tmp_path / "config.json"
        config.write_text('{"key": "value"}')
        result = load_json_file_optional(config)
        assert result == {"key": "value"}

    def test_returns_empty_dict_for_empty_file(self, tmp_path: Path) -> None:
        """Returns empty dict for empty file."""
        config = tmp_path / "config.json"
        config.write_text("")
        result = load_json_file_optional(config)
        assert result == {}

    def test_raises_for_invalid_json(self, tmp_path: Path) -> None:
        """Raises LoadError for invalid JSON."""
        config = tmp_path / "config.json"
        config.write_text("not json")
        with pytest.raises(LoadError):
            load_json_file_optional(config)

    def test_uses_path_resolve(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Path.resolve() is called for Windows compatibility.

        On Windows/Git Bash, Path.home() may return Unix-style paths like
        /c/Users/... that fail exists() checks. Using resolve() fixes this.
        """
        config = tmp_path / "config.json"
        config.write_text("{}")

        # Track resolve() calls
        original_resolve = Path.resolve
        resolve_called = []

        def tracking_resolve(self: Path) -> Path:
            resolve_called.append(self)
            return original_resolve(self)

        monkeypatch.setattr(Path, "resolve", tracking_resolve)
        load_json_file_optional(config)
        assert len(resolve_called) > 0


class TestDeepMerge:
    """Tests for deep_merge function."""

    def test_simple_merge(self) -> None:
        """Test basic key merging."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Test nested dict merging preserves base keys."""
        base = {"provider": {"model": "a", "type": "openrouter"}}
        override = {"provider": {"model": "b"}}
        result = deep_merge(base, override)
        assert result == {"provider": {"model": "b", "type": "openrouter"}}

    def test_list_replacement(self) -> None:
        """Test lists are REPLACED (not concatenated).

        P2.14 SECURITY: Lists must be replaced to allow local config to
        override global security settings like blocked_paths.
        """
        base = {"items": [1, 2]}
        override = {"items": [3, 4]}
        result = deep_merge(base, override)
        assert result == {"items": [3, 4]}


class TestAncestorDiscovery:
    """Tests for ancestor config directory discovery."""

    def test_finds_ancestors(self, tmp_path: Path) -> None:
        """Test finding ancestor .nexus3 directories."""
        # Create structure: a/b/c/project
        project = tmp_path / "a" / "b" / "c" / "project"
        project.mkdir(parents=True)

        # Create .nexus3 in a and b
        (tmp_path / "a" / ".nexus3").mkdir()
        (tmp_path / "a" / "b" / ".nexus3").mkdir()

        ancestors = find_ancestor_config_dirs(project, max_depth=4)

        assert len(ancestors) == 2
        # Should be ordered: furthest first (a before b)
        assert ancestors[0] == tmp_path / "a" / ".nexus3"
        assert ancestors[1] == tmp_path / "a" / "b" / ".nexus3"

    def test_respects_depth_limit(self, tmp_path: Path) -> None:
        """Test depth limit is respected."""
        project = tmp_path / "a" / "b" / "c" / "project"
        project.mkdir(parents=True)

        (tmp_path / "a" / ".nexus3").mkdir()
        (tmp_path / "a" / "b" / ".nexus3").mkdir()
        (tmp_path / "a" / "b" / "c" / ".nexus3").mkdir()

        ancestors = find_ancestor_config_dirs(project, max_depth=1)

        assert len(ancestors) == 1
        assert ancestors[0] == tmp_path / "a" / "b" / "c" / ".nexus3"

    def test_stops_at_root(self, tmp_path: Path) -> None:
        """Test doesn't go beyond filesystem root."""
        ancestors = find_ancestor_config_dirs(tmp_path, max_depth=100)
        # Shouldn't crash, just return whatever it finds
        assert isinstance(ancestors, list)

    def test_excludes_specified_paths(self, tmp_path: Path) -> None:
        """Test exclude_paths prevents matching directories from being included.

        This fixes a bug where global ~/.nexus3 was loaded twice when CWD
        was inside the home directory (once as global, once as ancestor).
        """
        # Create structure: home/.nexus3 and home/projects/app
        home = tmp_path / "home"
        global_dir = home / ".nexus3"
        global_dir.mkdir(parents=True)
        project = home / "projects" / "app"
        project.mkdir(parents=True)

        # Without exclusion - global_dir is found as ancestor
        ancestors = find_ancestor_config_dirs(project, max_depth=3)
        assert global_dir in ancestors

        # With exclusion - global_dir is excluded
        ancestors = find_ancestor_config_dirs(
            project, max_depth=3, exclude_paths=[global_dir]
        )
        assert global_dir not in ancestors

    def test_exclusion_uses_resolved_paths(self, tmp_path: Path) -> None:
        """Test exclusion comparison works with different path representations.

        On Windows/Git Bash, paths may have different formats. Using resolve()
        ensures consistent comparison.
        """
        global_dir = tmp_path / ".nexus3"
        global_dir.mkdir()
        project = tmp_path / "projects" / "app"
        project.mkdir(parents=True)

        # Exclude using non-resolved path representation
        ancestors = find_ancestor_config_dirs(
            project, max_depth=3, exclude_paths=[tmp_path / ".nexus3"]
        )
        assert global_dir not in ancestors


class TestLayeredConfigLoading:
    """Tests for layered config loading."""

    def test_local_overrides_global(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test local config overrides global."""
        # Mock home
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        # Create global config
        global_nexus = home / ".nexus3"
        global_nexus.mkdir()
        (global_nexus / "config.json").write_text(json.dumps({
            "stream_output": True,
            "max_tool_iterations": 5,
        }))

        # Create local config
        project = tmp_path / "project"
        local_nexus = project / ".nexus3"
        local_nexus.mkdir(parents=True)
        (local_nexus / "config.json").write_text(json.dumps({
            "max_tool_iterations": 10,
        }))

        config = load_config(cwd=project)

        # Local should override global
        assert config.max_tool_iterations == 10
        # Global should be preserved where not overridden
        assert config.stream_output is True

    def test_nested_config_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test nested objects are deep merged."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        # Global with provider config
        global_nexus = home / ".nexus3"
        global_nexus.mkdir()
        (global_nexus / "config.json").write_text(json.dumps({
            "default_model": "test",
            "providers": {
                "openrouter": {
                    "type": "openrouter",
                    "models": {
                        "test": {"id": "global-model", "context_window": 100000}
                    }
                }
            }
        }))

        # Local overrides the model id
        project = tmp_path / "project"
        local_nexus = project / ".nexus3"
        local_nexus.mkdir(parents=True)
        (local_nexus / "config.json").write_text(json.dumps({
            "providers": {
                "openrouter": {
                    "models": {
                        "test": {"id": "local-model"}
                    }
                }
            }
        }))

        config = load_config(cwd=project)

        # Should have local model id but preserve provider type
        resolved = config.resolve_model("test")
        assert resolved.model_id == "local-model"
        assert config.providers["openrouter"].type == "openrouter"

    def test_ancestor_configs_merged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ancestor directory configs are merged."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        # No global config

        # Company level
        company = tmp_path / "company"
        company_nexus = company / ".nexus3"
        company_nexus.mkdir(parents=True)
        (company_nexus / "config.json").write_text(json.dumps({
            "max_tool_iterations": 8,
            "stream_output": False,
        }))

        # Project level
        project = company / "project"
        project_nexus = project / ".nexus3"
        project_nexus.mkdir(parents=True)
        (project_nexus / "config.json").write_text(json.dumps({
            "skill_timeout": 45.0,
        }))

        config = load_config(cwd=project)

        # Should have both company and project settings
        assert config.max_tool_iterations == 8
        assert config.stream_output is False
        assert config.skill_timeout == 45.0

    def test_invalid_json_fails_fast(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test invalid JSON causes error."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        project = tmp_path / "project"
        local_nexus = project / ".nexus3"
        local_nexus.mkdir(parents=True)
        (local_nexus / "config.json").write_text("not valid json")

        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(cwd=project)

    def test_empty_file_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test empty config file is treated as empty dict."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        project = tmp_path / "project"
        local_nexus = project / ".nexus3"
        local_nexus.mkdir(parents=True)
        (local_nexus / "config.json").write_text("")

        # Should not raise, just use defaults
        config = load_config(cwd=project)
        assert isinstance(config, Config)

    def test_explicit_path_skips_layering(self, tmp_path: Path) -> None:
        """Test explicit path bypasses layered loading."""
        config_file = tmp_path / "explicit.json"
        config_file.write_text(json.dumps({
            "max_tool_iterations": 99,
            "default_model": "test",
            "providers": {
                "test": {
                    "type": "openrouter",
                    "models": {
                        "test": {"id": "test/model"}
                    }
                }
            }
        }))

        config = load_config(path=config_file)
        assert config.max_tool_iterations == 99

    def test_no_user_configs_uses_package_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing user configs uses package defaults."""
        # Point to empty home (no ~/.nexus3/)
        home = tmp_path / "empty_home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        project = tmp_path / "empty_project"
        project.mkdir()

        # No local .nexus3/ either - should use package defaults
        config = load_config(cwd=project)

        # Should get package defaults (from nexus3/defaults/config.json)
        assert config.max_tool_iterations == 100
        assert config.stream_output is True
        # Should have providers from defaults
        assert "openrouter" in config.providers
