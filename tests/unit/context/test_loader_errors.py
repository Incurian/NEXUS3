"""Tests for context loader error handling.

F2: Error Type Unification - tests for ContextLoadError in context loader.
"""

from pathlib import Path

import pytest

from nexus3.context.loader import ContextLoader
from nexus3.core.errors import ContextLoadError, LoadError


class TestContextLoaderErrors:
    """Tests for error handling in ContextLoader."""

    def test_invalid_json_in_config_raises_context_load_error(
        self, tmp_path: Path
    ) -> None:
        """Invalid JSON in config.json should raise ContextLoadError."""
        # Create a .nexus3 directory with invalid config.json
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        config_file = nexus_dir / "config.json"
        config_file.write_text('{"invalid": json syntax', encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        with pytest.raises(ContextLoadError) as exc_info:
            loader.load()

        assert "Invalid JSON" in str(exc_info.value)

    def test_invalid_json_in_mcp_raises_context_load_error(
        self, tmp_path: Path
    ) -> None:
        """Invalid JSON in mcp.json should raise ContextLoadError."""
        # Create a .nexus3 directory with valid config but invalid mcp.json
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        config_file = nexus_dir / "config.json"
        config_file.write_text("{}", encoding="utf-8")
        mcp_file = nexus_dir / "mcp.json"
        mcp_file.write_text("[broken mcp json", encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        with pytest.raises(ContextLoadError) as exc_info:
            loader.load()

        assert "Invalid JSON" in str(exc_info.value)

    def test_non_dict_config_raises_context_load_error(self, tmp_path: Path) -> None:
        """Config file with non-dict JSON should raise ContextLoadError."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        config_file = nexus_dir / "config.json"
        config_file.write_text('["this", "is", "an", "array"]', encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        with pytest.raises(ContextLoadError) as exc_info:
            loader.load()

        assert "Expected object" in str(exc_info.value)

    def test_context_load_error_is_load_error_subclass(
        self, tmp_path: Path
    ) -> None:
        """ContextLoadError should be a subclass of LoadError."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        config_file = nexus_dir / "config.json"
        config_file.write_text("not json at all", encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        with pytest.raises(LoadError):
            loader.load()

    def test_empty_config_file_is_valid(self, tmp_path: Path) -> None:
        """Empty config.json should be treated as valid (empty dict)."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        config_file = nexus_dir / "config.json"
        config_file.write_text("", encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        # Should not raise - empty file is valid
        context = loader.load()
        assert context is not None

    def test_whitespace_only_config_file_is_valid(self, tmp_path: Path) -> None:
        """Config file with only whitespace should be treated as valid."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()
        config_file = nexus_dir / "config.json"
        config_file.write_text("   \n\t  \n  ", encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        # Should not raise - whitespace-only is valid
        context = loader.load()
        assert context is not None

    def test_valid_config_and_mcp_load_successfully(self, tmp_path: Path) -> None:
        """Valid config and mcp files should load without errors."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        config_file = nexus_dir / "config.json"
        config_file.write_text('{"server": {"port": 9999}}', encoding="utf-8")

        mcp_file = nexus_dir / "mcp.json"
        mcp_file.write_text('{"servers": []}', encoding="utf-8")

        loader = ContextLoader(cwd=tmp_path)

        context = loader.load()

        assert context is not None
        assert context.merged_config.get("server", {}).get("port") == 9999

    def test_missing_nexus_dir_loads_defaults(self, tmp_path: Path) -> None:
        """Directory without .nexus3 should still load (using defaults)."""
        loader = ContextLoader(cwd=tmp_path)

        # Should not raise - falls back to defaults or empty
        context = loader.load()
        assert context is not None
        assert context.system_prompt  # Should have at least default prompt
