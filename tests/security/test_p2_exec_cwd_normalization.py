"""P2.4: Test that exec cwd is normalized before permission checks.

This tests the security requirement that working directory paths are
normalized (symlinks followed, .. resolved) BEFORE permission checks.

Without normalization first, paths like:
- "/allowed/../../../etc" might bypass checks
- Symlinks pointing outside sandbox might be followed

The fix ensures PathResolver.resolve_cwd() normalizes via resolve()
before checking against allowed_paths.
"""

from pathlib import Path

import pytest

from nexus3.core.errors import PathSecurityError
from nexus3.core.resolver import PathResolver
from nexus3.skill.services import ServiceContainer


class TestCwdNormalizationBeforeCheck:
    """Test that cwd is normalized before permission validation."""

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Path traversal attempts are caught after normalization."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        forbidden = tmp_path / "forbidden"
        forbidden.mkdir()

        services = ServiceContainer()
        services.register("cwd", allowed)
        services.register("allowed_paths", [allowed])

        resolver = PathResolver(services)

        # Try to escape via path traversal
        traversal_path = str(allowed / ".." / "forbidden")
        resolved, error = resolver.resolve_cwd(traversal_path)

        # Should be blocked because after normalization it's outside allowed
        assert resolved is None
        assert error is not None
        assert "outside" in error.lower() or "allowed" in error.lower()

    def test_symlink_to_forbidden_blocked(self, tmp_path: Path) -> None:
        """Symlink pointing to forbidden directory is blocked."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        forbidden = tmp_path / "forbidden"
        forbidden.mkdir()

        # Create symlink inside allowed pointing to forbidden
        symlink = allowed / "escape"
        symlink.symlink_to(forbidden)

        services = ServiceContainer()
        services.register("cwd", allowed)
        services.register("allowed_paths", [allowed])

        resolver = PathResolver(services)

        # Try to use symlink as cwd
        resolved, error = resolver.resolve_cwd(str(symlink))

        # Should be blocked because after following symlink, it's outside allowed
        assert resolved is None
        assert error is not None

    def test_valid_cwd_works(self, tmp_path: Path) -> None:
        """Valid cwd within allowed paths works correctly."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        subdir = allowed / "subdir"
        subdir.mkdir()

        services = ServiceContainer()
        services.register("cwd", allowed)
        services.register("allowed_paths", [allowed])

        resolver = PathResolver(services)

        resolved, error = resolver.resolve_cwd(str(subdir))

        assert error is None
        assert resolved == str(subdir.resolve())

    def test_double_dot_normalization(self, tmp_path: Path) -> None:
        """Multiple .. segments are properly normalized."""
        allowed = tmp_path / "a" / "b" / "c"
        allowed.mkdir(parents=True)

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("allowed_paths", [allowed])

        resolver = PathResolver(services)

        # Try to navigate up and back down - should end up at allowed
        complex_path = str(allowed / ".." / ".." / ".." / "a" / "b" / "c")
        resolved, error = resolver.resolve_cwd(complex_path)

        assert error is None
        assert resolved == str(allowed.resolve())

    def test_normalization_before_blocked_check(self, tmp_path: Path) -> None:
        """Normalization happens before blocked_paths check too."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        blocked = tmp_path / "blocked"
        blocked.mkdir()

        services = ServiceContainer()
        services.register("cwd", allowed)
        services.register("allowed_paths", [tmp_path])  # Allow parent
        services.register("blocked_paths", [blocked])

        resolver = PathResolver(services)

        # Try to access blocked via path traversal
        traversal_path = str(allowed / ".." / "blocked")
        resolved, error = resolver.resolve_cwd(traversal_path)

        # Should be blocked after normalization reveals it's in blocked_paths
        assert resolved is None
        assert error is not None
        assert "blocked" in error.lower()


class TestExecSkillCwdValidation:
    """Test cwd validation for execution skills specifically."""

    def test_relative_cwd_resolved_against_agent_cwd(self, tmp_path: Path) -> None:
        """Relative cwd is resolved against agent's cwd, not process cwd."""
        agent_cwd = tmp_path / "agent_home"
        agent_cwd.mkdir()
        target = agent_cwd / "target"
        target.mkdir()

        services = ServiceContainer()
        services.register("cwd", agent_cwd)  # Agent's cwd
        services.register("allowed_paths", [agent_cwd])

        resolver = PathResolver(services)

        # Relative path should be resolved against agent_cwd
        resolved, error = resolver.resolve_cwd("target")

        assert error is None
        assert resolved == str(target.resolve())

    def test_absolute_cwd_still_validated(self, tmp_path: Path) -> None:
        """Absolute cwd path is still validated against permissions."""
        agent_cwd = tmp_path / "agent_home"
        agent_cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        services = ServiceContainer()
        services.register("cwd", agent_cwd)
        services.register("allowed_paths", [agent_cwd])

        resolver = PathResolver(services)

        # Absolute path outside allowed should be blocked
        resolved, error = resolver.resolve_cwd(str(outside))

        assert resolved is None
        assert error is not None

    def test_none_cwd_uses_agent_default(self, tmp_path: Path) -> None:
        """None cwd uses agent's default working directory."""
        agent_cwd = tmp_path / "agent_home"
        agent_cwd.mkdir()

        services = ServiceContainer()
        services.register("cwd", agent_cwd)

        resolver = PathResolver(services)

        resolved, error = resolver.resolve_cwd(None)

        assert error is None
        assert resolved == str(agent_cwd.resolve())

    def test_empty_cwd_uses_agent_default(self, tmp_path: Path) -> None:
        """Empty string cwd uses agent's default working directory."""
        agent_cwd = tmp_path / "agent_home"
        agent_cwd.mkdir()

        services = ServiceContainer()
        services.register("cwd", agent_cwd)

        resolver = PathResolver(services)

        resolved, error = resolver.resolve_cwd("")

        assert error is None
        assert resolved == str(agent_cwd.resolve())
