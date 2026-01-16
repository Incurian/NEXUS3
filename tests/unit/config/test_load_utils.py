"""Tests for nexus3.config.load_utils module.

F2: Error Type Unification - tests for load_json_file utility.
"""

from pathlib import Path

import pytest

from nexus3.config.load_utils import load_json_file
from nexus3.core.errors import LoadError


class TestLoadJsonFile:
    """Tests for load_json_file function."""

    def test_load_valid_json_file(self, tmp_path: Path) -> None:
        """Should successfully load a valid JSON file."""
        json_file = tmp_path / "valid.json"
        json_file.write_text('{"key": "value", "number": 42}', encoding="utf-8")

        result = load_json_file(json_file)

        assert result == {"key": "value", "number": 42}

    def test_load_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Empty files should return an empty dict."""
        json_file = tmp_path / "empty.json"
        json_file.write_text("", encoding="utf-8")

        result = load_json_file(json_file)

        assert result == {}

    def test_load_whitespace_only_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Files with only whitespace should return an empty dict."""
        json_file = tmp_path / "whitespace.json"
        json_file.write_text("   \n\t  \n  ", encoding="utf-8")

        result = load_json_file(json_file)

        assert result == {}

    def test_load_nonexistent_file_raises_load_error(self, tmp_path: Path) -> None:
        """Non-existent files should raise LoadError."""
        nonexistent = tmp_path / "does_not_exist.json"

        with pytest.raises(LoadError) as exc_info:
            load_json_file(nonexistent)

        assert "File not found" in str(exc_info.value)
        assert str(nonexistent) in str(exc_info.value)

    def test_load_invalid_json_raises_load_error(self, tmp_path: Path) -> None:
        """Invalid JSON should raise LoadError."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text('{"key": "unclosed', encoding="utf-8")

        with pytest.raises(LoadError) as exc_info:
            load_json_file(invalid_file)

        assert "Invalid JSON" in str(exc_info.value)
        assert str(invalid_file) in str(exc_info.value)

    def test_load_non_dict_json_raises_load_error(self, tmp_path: Path) -> None:
        """JSON that parses to non-dict (e.g., array) should raise LoadError."""
        array_file = tmp_path / "array.json"
        array_file.write_text('["item1", "item2"]', encoding="utf-8")

        with pytest.raises(LoadError) as exc_info:
            load_json_file(array_file)

        assert "Expected object" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_load_scalar_json_raises_load_error(self, tmp_path: Path) -> None:
        """JSON that parses to a scalar should raise LoadError."""
        scalar_file = tmp_path / "scalar.json"
        scalar_file.write_text('"just a string"', encoding="utf-8")

        with pytest.raises(LoadError) as exc_info:
            load_json_file(scalar_file)

        assert "Expected object" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    def test_load_with_error_context(self, tmp_path: Path) -> None:
        """Error context should be included in error messages."""
        nonexistent = tmp_path / "missing.json"

        with pytest.raises(LoadError) as exc_info:
            load_json_file(nonexistent, error_context="config")

        assert "config: File not found" in str(exc_info.value)

    def test_load_nested_json(self, tmp_path: Path) -> None:
        """Should correctly load nested JSON structures."""
        nested_file = tmp_path / "nested.json"
        nested_file.write_text(
            '{"outer": {"inner": {"deep": [1, 2, 3]}}, "simple": true}',
            encoding="utf-8",
        )

        result = load_json_file(nested_file)

        assert result == {
            "outer": {"inner": {"deep": [1, 2, 3]}},
            "simple": True,
        }

    def test_load_error_is_nexus_error_subclass(self, tmp_path: Path) -> None:
        """LoadError should be a subclass of NexusError for consistent handling."""
        from nexus3.core.errors import NexusError

        nonexistent = tmp_path / "missing.json"

        with pytest.raises(NexusError):
            load_json_file(nonexistent)
