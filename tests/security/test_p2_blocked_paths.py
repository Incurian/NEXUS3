"""P2.3: Test that blocked_paths are enforced in PathResolver.

This tests the security feature where certain paths can be blocked regardless
of what allowed_paths are configured. This provides a deny-list that takes
precedence over any allow-list.

The fix:
- PathResolver.resolve() now passes blocked_paths to validate_path()
- ServiceContainer.get_blocked_paths() retrieves from permissions
- Blocked paths are checked BEFORE allowed paths
"""

from pathlib import Path

import pytest

from nexus3.core.errors import PathSecurityError
from nexus3.core.resolver import PathResolver
from nexus3.skill.services import ServiceContainer


class TestBlockedPathsEnforcement:
    """Test that blocked_paths are always enforced."""

    def test_blocked_path_rejected(self, tmp_path: Path) -> None:
        """Path within blocked_paths is rejected."""
        blocked_dir = tmp_path / "blocked"
        blocked_dir.mkdir()
        (blocked_dir / "secret.txt").write_text("secret")

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [blocked_dir])

        resolver = PathResolver(services)

        with pytest.raises(PathSecurityError) as exc_info:
            resolver.resolve(blocked_dir / "secret.txt")

        assert "blocked" in str(exc_info.value).lower()

    def test_blocked_path_takes_precedence(self, tmp_path: Path) -> None:
        """Blocked paths take precedence over allowed paths."""
        # Create a directory that is both in allowed and blocked
        sensitive = tmp_path / "sensitive"
        sensitive.mkdir()
        (sensitive / "data.txt").write_text("sensitive data")

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("allowed_paths", [tmp_path])  # Allow entire tmp_path
        services.register("blocked_paths", [sensitive])  # But block sensitive dir

        resolver = PathResolver(services)

        # Should be able to access files outside sensitive
        normal = tmp_path / "normal.txt"
        normal.write_text("normal")
        resolved = resolver.resolve(normal)
        assert resolved == normal.resolve()

        # But should NOT be able to access files in sensitive
        with pytest.raises(PathSecurityError):
            resolver.resolve(sensitive / "data.txt")

    def test_blocked_path_with_symlink(self, tmp_path: Path) -> None:
        """Symlink pointing to blocked path is rejected."""
        blocked_dir = tmp_path / "blocked"
        blocked_dir.mkdir()
        (blocked_dir / "secret.txt").write_text("secret")

        # Create symlink outside blocked dir pointing into it
        symlink = tmp_path / "innocent_link"
        symlink.symlink_to(blocked_dir / "secret.txt")

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [blocked_dir])

        resolver = PathResolver(services)

        # Even via symlink, should be blocked
        with pytest.raises(PathSecurityError) as exc_info:
            resolver.resolve(symlink)

        assert "blocked" in str(exc_info.value).lower()

    def test_empty_blocked_paths(self, tmp_path: Path) -> None:
        """Empty blocked_paths list allows all paths."""
        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [])

        resolver = PathResolver(services)

        # Create and access a file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        resolved = resolver.resolve(test_file)
        assert resolved == test_file.resolve()

    def test_no_blocked_paths_set(self, tmp_path: Path) -> None:
        """When blocked_paths not set, all paths allowed (by blocked_paths)."""
        services = ServiceContainer()
        services.register("cwd", tmp_path)
        # Don't register blocked_paths at all

        resolver = PathResolver(services)

        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        resolved = resolver.resolve(test_file)
        assert resolved == test_file.resolve()


class TestBlockedPathsWithToolPermissions:
    """Test blocked_paths integration with per-tool permissions."""

    def test_blocked_paths_apply_to_all_tools(self, tmp_path: Path) -> None:
        """Blocked paths apply regardless of tool-specific allowed_paths."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        (blocked / "file.txt").write_text("blocked")

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [blocked])
        # Even with very permissive per-tool paths
        services.register("allowed_paths", None)  # Unrestricted

        resolver = PathResolver(services)

        with pytest.raises(PathSecurityError):
            resolver.resolve(blocked / "file.txt", tool_name="read_file")


class TestBlockedPathsErrorMessages:
    """Test that error messages are appropriate."""

    def test_error_message_contains_blocked(self, tmp_path: Path) -> None:
        """Error message indicates path is blocked."""
        blocked = tmp_path / "forbidden"
        blocked.mkdir()

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [blocked])

        resolver = PathResolver(services)

        with pytest.raises(PathSecurityError) as exc_info:
            resolver.resolve(blocked)

        # Error should mention it's blocked
        assert "blocked" in str(exc_info.value).lower()


class TestResolveCwdWithBlockedPaths:
    """Test that resolve_cwd respects blocked_paths."""

    def test_resolve_cwd_rejects_blocked(self, tmp_path: Path) -> None:
        """resolve_cwd rejects working directory if in blocked_paths."""
        blocked = tmp_path / "blocked_dir"
        blocked.mkdir()

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [blocked])

        resolver = PathResolver(services)

        resolved, error = resolver.resolve_cwd(str(blocked))
        assert resolved is None
        assert error is not None
        assert "blocked" in error.lower()

    def test_resolve_cwd_allows_non_blocked(self, tmp_path: Path) -> None:
        """resolve_cwd allows working directory not in blocked_paths."""
        allowed = tmp_path / "allowed_dir"
        allowed.mkdir()

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [tmp_path / "other_blocked"])

        resolver = PathResolver(services)

        resolved, error = resolver.resolve_cwd(str(allowed))
        assert error is None
        assert resolved == str(allowed.resolve())
