"""Unit tests for nexus3.core.paths sandbox functionality."""

import os
from pathlib import Path

import pytest

from nexus3.core.errors import NexusError, PathSecurityError
from nexus3.core.paths import get_default_sandbox, validate_sandbox


class TestPathSecurityError:
    """Tests for PathSecurityError exception."""

    def test_path_security_error_has_path_attribute(self):
        """PathSecurityError stores the path attribute."""
        err = PathSecurityError("/etc/passwd", "Path outside sandbox")
        assert err.path == "/etc/passwd"

    def test_path_security_error_has_reason_attribute(self):
        """PathSecurityError stores the reason attribute."""
        err = PathSecurityError("/etc/passwd", "Path outside sandbox")
        assert err.reason == "Path outside sandbox"

    def test_path_security_error_message_includes_path(self):
        """PathSecurityError message includes the path."""
        err = PathSecurityError("/etc/passwd", "Path outside sandbox")
        assert "/etc/passwd" in str(err)

    def test_path_security_error_message_includes_reason(self):
        """PathSecurityError message includes the reason."""
        err = PathSecurityError("/some/path", "Symlinks not allowed")
        assert "Symlinks not allowed" in str(err)

    def test_path_security_error_inherits_from_nexus_error(self):
        """PathSecurityError inherits from NexusError."""
        assert issubclass(PathSecurityError, NexusError)

    def test_path_security_error_can_be_caught_as_nexus_error(self):
        """PathSecurityError can be caught as NexusError."""
        try:
            raise PathSecurityError("/etc/passwd", "Path outside sandbox")
        except NexusError as e:
            assert "Path security violation" in e.message

    def test_path_security_error_has_message_attribute(self):
        """PathSecurityError has message attribute from NexusError."""
        err = PathSecurityError("/test/path", "Test reason")
        assert hasattr(err, "message")
        assert "Path security violation" in err.message
        assert "/test/path" in err.message
        assert "Test reason" in err.message


class TestGetDefaultSandbox:
    """Tests for get_default_sandbox function."""

    def test_returns_list_containing_cwd(self):
        """get_default_sandbox returns list containing current working directory."""
        sandbox = get_default_sandbox()
        cwd = Path.cwd()
        assert cwd in sandbox

    def test_returns_exactly_one_path(self):
        """get_default_sandbox returns exactly one path."""
        sandbox = get_default_sandbox()
        assert len(sandbox) == 1

    def test_returns_list_type(self):
        """get_default_sandbox returns a list."""
        sandbox = get_default_sandbox()
        assert isinstance(sandbox, list)

    def test_returns_path_objects(self):
        """get_default_sandbox returns Path objects, not strings."""
        sandbox = get_default_sandbox()
        for p in sandbox:
            assert isinstance(p, Path)


class TestValidateSandbox:
    """Tests for validate_sandbox function."""

    def test_valid_path_within_sandbox_returns_resolved_path(self, tmp_path):
        """Valid path within sandbox returns resolved absolute path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        result = validate_sandbox(str(test_file), [tmp_path])

        assert result == test_file.resolve()
        assert result.is_absolute()

    def test_relative_path_within_sandbox_works(self, tmp_path, monkeypatch):
        """Relative path within sandbox works correctly."""
        # Create file in tmp_path
        test_file = tmp_path / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        # Change to tmp_path so relative paths resolve there
        monkeypatch.chdir(tmp_path)

        result = validate_sandbox("test.txt", [tmp_path])

        assert result == test_file.resolve()

    def test_absolute_path_within_sandbox_works(self, tmp_path):
        """Absolute path within sandbox works correctly."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        result = validate_sandbox(test_file.resolve(), [tmp_path])

        assert result == test_file.resolve()

    def test_path_outside_sandbox_raises_error(self, tmp_path):
        """Path outside sandbox raises PathSecurityError."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("test", encoding="utf-8")

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(outside_file), [sandbox])

        assert "outside allowed directories" in exc_info.value.reason.lower()

    def test_path_traversal_outside_sandbox_raises_error(self, tmp_path):
        """Path traversal attempt outside sandbox raises PathSecurityError."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        # Try to access parent directory via ../
        traversal_path = sandbox / ".." / "outside.txt"

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(traversal_path), [sandbox])

        assert "outside allowed directories" in exc_info.value.reason.lower()

    def test_nested_path_traversal_outside_sandbox_raises_error(self, tmp_path):
        """Deeply nested path traversal outside sandbox raises PathSecurityError."""
        sandbox = tmp_path / "sandbox" / "nested"
        sandbox.mkdir(parents=True)

        # Try to escape via multiple ../
        traversal_path = sandbox / ".." / ".." / "outside.txt"

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(traversal_path), [sandbox])

        assert "outside allowed directories" in exc_info.value.reason.lower()

    def test_symlink_file_within_sandbox_resolves_to_target(self, tmp_path):
        """Symlink to file within sandbox resolves to target path.

        Note: The current implementation follows symlinks via resolve().
        Symlinks within the sandbox are allowed as long as their target
        is also within the sandbox. The security check catches symlinks
        pointing OUTSIDE the sandbox.
        """
        # Create real file
        real_file = tmp_path / "real.txt"
        real_file.write_text("test", encoding="utf-8")

        # Create symlink to the file
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        # Symlink within sandbox resolves to the real file
        result = validate_sandbox(str(symlink), [tmp_path])

        # Returns the resolved path (the real file, not the symlink)
        assert result == real_file.resolve()

    def test_symlink_directory_within_sandbox_resolves_to_target(self, tmp_path):
        """Symlink directory within sandbox resolves to target path.

        Note: The current implementation follows symlinks via resolve().
        Directory symlinks within the sandbox are allowed as long as their
        target is also within the sandbox.
        """
        # Create real directory structure
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        test_file = real_dir / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        # Create symlink to directory
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)

        # Try to access file through symlinked directory
        path_through_symlink = link_dir / "test.txt"

        # Symlink within sandbox resolves to the real file
        result = validate_sandbox(str(path_through_symlink), [tmp_path])

        # Returns the resolved path (real_dir/test.txt, not link_dir/test.txt)
        assert result == test_file.resolve()

    def test_symlink_pointing_outside_sandbox_raises_error(self, tmp_path):
        """Symlink pointing outside sandbox raises PathSecurityError.

        This is the key security test: even if a symlink exists inside the
        sandbox, if it points to a file outside the sandbox, access is denied.
        The implementation catches this because resolve() follows the symlink,
        resulting in a path outside the sandbox.
        """
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "secret.txt"
        outside_file.write_text("secret", encoding="utf-8")

        # Create symlink inside sandbox pointing outside
        symlink_escape = sandbox / "escape.txt"
        symlink_escape.symlink_to(outside_file)

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(symlink_escape), [sandbox])

        # The error message mentions "outside sandbox" since the resolved path
        # is outside the sandbox
        assert "outside allowed directories" in exc_info.value.reason.lower()

    def test_multiple_allowed_paths_any_valid(self, tmp_path):
        """Multiple allowed paths work - path valid if under ANY allowed path."""
        sandbox1 = tmp_path / "sandbox1"
        sandbox2 = tmp_path / "sandbox2"
        sandbox1.mkdir()
        sandbox2.mkdir()

        # File in sandbox2
        test_file = sandbox2 / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        # Should succeed with path in sandbox2
        result = validate_sandbox(str(test_file), [sandbox1, sandbox2])

        assert result == test_file.resolve()

    def test_multiple_allowed_paths_file_in_first(self, tmp_path):
        """File in first of multiple allowed paths works."""
        sandbox1 = tmp_path / "sandbox1"
        sandbox2 = tmp_path / "sandbox2"
        sandbox1.mkdir()
        sandbox2.mkdir()

        # File in sandbox1
        test_file = sandbox1 / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        result = validate_sandbox(str(test_file), [sandbox1, sandbox2])

        assert result == test_file.resolve()

    def test_multiple_allowed_paths_rejects_outside(self, tmp_path):
        """Multiple allowed paths still reject paths outside all sandboxes."""
        sandbox1 = tmp_path / "sandbox1"
        sandbox2 = tmp_path / "sandbox2"
        sandbox1.mkdir()
        sandbox2.mkdir()

        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("test", encoding="utf-8")

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(outside_file), [sandbox1, sandbox2])

        assert "outside allowed directories" in exc_info.value.reason.lower()

    def test_empty_allowed_paths_rejects_all(self, tmp_path):
        """Empty allowed_paths list rejects all paths."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(test_file), [])

        assert "no allowed paths" in exc_info.value.reason.lower()

    def test_path_object_input_works(self, tmp_path):
        """Path object (not just string) input works."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        result = validate_sandbox(test_file, [tmp_path])

        assert result == test_file.resolve()

    def test_nonexistent_file_in_sandbox_returns_resolved(self, tmp_path):
        """Non-existent file path within sandbox returns resolved path."""
        nonexistent = tmp_path / "does_not_exist.txt"

        result = validate_sandbox(str(nonexistent), [tmp_path])

        assert result == nonexistent.resolve()

    def test_nested_directory_within_sandbox_works(self, tmp_path):
        """Nested directory path within sandbox works."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        test_file = nested / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        result = validate_sandbox(str(test_file), [tmp_path])

        assert result == test_file.resolve()

    def test_path_to_sandbox_root_itself_works(self, tmp_path):
        """Path to sandbox root directory itself works."""
        result = validate_sandbox(str(tmp_path), [tmp_path])

        assert result == tmp_path.resolve()

    def test_dot_path_within_sandbox_works(self, tmp_path, monkeypatch):
        """Path with . component within sandbox works."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        dot_path = "./test.txt"

        result = validate_sandbox(dot_path, [tmp_path])

        assert result == test_file.resolve()

    def test_sandbox_path_is_resolved(self, tmp_path):
        """Sandbox paths are resolved before comparison."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"
        test_file.write_text("test", encoding="utf-8")

        # Use non-resolved sandbox path with ..
        non_resolved_sandbox = tmp_path / "other" / ".." / "subdir"

        result = validate_sandbox(str(test_file), [non_resolved_sandbox])

        assert result == test_file.resolve()

    def test_error_message_includes_allowed_paths(self, tmp_path):
        """PathSecurityError message includes allowed paths for debugging."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        outside = tmp_path / "outside.txt"

        with pytest.raises(PathSecurityError) as exc_info:
            validate_sandbox(str(outside), [sandbox])

        assert str(sandbox) in exc_info.value.reason

    def test_relative_path_escape_blocked(self, tmp_path, monkeypatch):
        """Relative path that escapes sandbox via .. is blocked."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        secret = tmp_path / "secret.txt"
        secret.write_text("secret", encoding="utf-8")

        monkeypatch.chdir(sandbox)

        with pytest.raises(PathSecurityError):
            validate_sandbox("../secret.txt", [sandbox])
