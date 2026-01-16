"""Arch A2: Test PathDecisionEngine - authoritative path access decisions.

This tests the centralized path decision engine that provides explicit
decision results with detailed reasoning.

The PathDecisionEngine:
- Provides explicit decision results (PathDecision dataclass)
- Explains why paths are allowed or denied
- Handles all path validation in one place
- Supports both standalone and ServiceContainer modes
"""

from pathlib import Path

import pytest

from nexus3.core.errors import PathSecurityError
from nexus3.core.path_decision import (
    PathDecisionEngine,
    PathDecisionReason,
)
from nexus3.skill.services import ServiceContainer

# =============================================================================
# 1. Basic Access Decisions
# =============================================================================


class TestUnrestrictedMode:
    """Test unrestricted mode (allowed_paths=None)."""

    def test_unrestricted_allows_any_path(self, tmp_path: Path) -> None:
        """Unrestricted mode allows access to any path."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()
        assert decision.reason == PathDecisionReason.UNRESTRICTED
        assert "TRUSTED/YOLO" in decision.reason_detail

    def test_unrestricted_allows_paths_outside_cwd(self, tmp_path: Path) -> None:
        """Unrestricted mode allows paths outside cwd."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        test_file = outside / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=cwd)

        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()

    def test_is_unrestricted_returns_true(self, tmp_path: Path) -> None:
        """is_unrestricted() returns True when allowed_paths is None."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        assert engine.is_unrestricted() is True


class TestRestrictedModeAllowed:
    """Test restricted mode with paths within allowed directories."""

    def test_path_within_allowed_is_allowed(self, tmp_path: Path) -> None:
        """Path within an allowed directory is allowed."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        test_file = allowed_dir / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed_dir], cwd=tmp_path)

        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()
        assert decision.reason == PathDecisionReason.WITHIN_ALLOWED
        assert str(allowed_dir) in decision.reason_detail
        assert decision.matched_rule == allowed_dir

    def test_nested_path_within_allowed(self, tmp_path: Path) -> None:
        """Nested path within an allowed directory is allowed."""
        allowed_dir = tmp_path / "allowed"
        nested = allowed_dir / "deep" / "nested"
        nested.mkdir(parents=True)
        test_file = nested / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed_dir], cwd=tmp_path)

        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()

    def test_multiple_allowed_paths(self, tmp_path: Path) -> None:
        """Path within any of multiple allowed directories is allowed."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        test_file = dir_b / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[dir_a, dir_b], cwd=tmp_path)

        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.matched_rule == dir_b

    def test_is_unrestricted_returns_false(self, tmp_path: Path) -> None:
        """is_unrestricted() returns False when allowed_paths is set."""
        engine = PathDecisionEngine(allowed_paths=[tmp_path], cwd=tmp_path)

        assert engine.is_unrestricted() is False


class TestRestrictedModeDenied:
    """Test restricted mode with paths outside allowed directories."""

    def test_path_outside_allowed_is_denied(self, tmp_path: Path) -> None:
        """Path outside allowed directories is denied."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        test_file = outside_dir / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed_dir], cwd=tmp_path)

        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.resolved_path is None
        assert decision.reason == PathDecisionReason.OUTSIDE_ALLOWED
        assert "outside allowed" in decision.reason_detail.lower()
        assert str(allowed_dir) in decision.reason_detail

    def test_sibling_directory_denied(self, tmp_path: Path) -> None:
        """Sibling directory to allowed path is denied."""
        allowed = tmp_path / "allowed"
        sibling = tmp_path / "sibling"
        allowed.mkdir()
        sibling.mkdir()
        test_file = sibling / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)

        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.OUTSIDE_ALLOWED


class TestEmptyAllowedPaths:
    """Test behavior when allowed_paths is an empty list."""

    def test_empty_allowed_paths_denies_all(self, tmp_path: Path) -> None:
        """Empty allowed_paths list denies all paths."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[], cwd=tmp_path)

        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.resolved_path is None
        assert decision.reason == PathDecisionReason.NO_ALLOWED_PATHS
        assert "no allowed paths" in decision.reason_detail.lower()

    def test_empty_allowed_paths_denies_cwd(self, tmp_path: Path) -> None:
        """Empty allowed_paths list denies even the cwd."""
        engine = PathDecisionEngine(allowed_paths=[], cwd=tmp_path)

        decision = engine.check_access(tmp_path)

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.NO_ALLOWED_PATHS


# =============================================================================
# 2. Blocked Paths
# =============================================================================


class TestBlockedPaths:
    """Test blocked paths functionality."""

    def test_blocked_path_denied(self, tmp_path: Path) -> None:
        """Path in blocked_paths is denied."""
        blocked_dir = tmp_path / "blocked"
        blocked_dir.mkdir()
        test_file = blocked_dir / "secret.txt"
        test_file.write_text("secret")

        engine = PathDecisionEngine(
            allowed_paths=None,  # Unrestricted
            blocked_paths=[blocked_dir],
            cwd=tmp_path,
        )

        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.resolved_path is None
        assert decision.reason == PathDecisionReason.BLOCKED
        assert str(blocked_dir) in decision.reason_detail
        assert decision.matched_rule == blocked_dir

    def test_blocked_path_in_allowed_denied(self, tmp_path: Path) -> None:
        """Blocked path within an allowed directory is still denied."""
        allowed_dir = tmp_path / "allowed"
        blocked_subdir = allowed_dir / "blocked"
        allowed_dir.mkdir()
        blocked_subdir.mkdir()
        test_file = blocked_subdir / "secret.txt"
        test_file.write_text("secret")

        engine = PathDecisionEngine(
            allowed_paths=[allowed_dir],
            blocked_paths=[blocked_subdir],
            cwd=tmp_path,
        )

        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.BLOCKED

    def test_blocked_takes_precedence_over_allowed(self, tmp_path: Path) -> None:
        """Blocked paths take precedence over allowed paths."""
        sensitive = tmp_path / "sensitive"
        sensitive.mkdir()
        (sensitive / "data.txt").write_text("sensitive data")

        # Allow entire tmp_path but block sensitive subdir
        engine = PathDecisionEngine(
            allowed_paths=[tmp_path],
            blocked_paths=[sensitive],
            cwd=tmp_path,
        )

        # Non-blocked file should be allowed
        normal = tmp_path / "normal.txt"
        normal.write_text("normal")
        assert engine.check_access(normal).allowed is True

        # Blocked file should be denied
        assert engine.check_access(sensitive / "data.txt").allowed is False

    def test_multiple_blocked_paths(self, tmp_path: Path) -> None:
        """Multiple blocked paths are all enforced."""
        blocked_a = tmp_path / "blocked_a"
        blocked_b = tmp_path / "blocked_b"
        blocked_a.mkdir()
        blocked_b.mkdir()
        (blocked_a / "a.txt").write_text("a")
        (blocked_b / "b.txt").write_text("b")

        engine = PathDecisionEngine(
            allowed_paths=None,
            blocked_paths=[blocked_a, blocked_b],
            cwd=tmp_path,
        )

        assert engine.check_access(blocked_a / "a.txt").allowed is False
        assert engine.check_access(blocked_b / "b.txt").allowed is False

    def test_nested_blocked_path(self, tmp_path: Path) -> None:
        """File nested within blocked directory is denied."""
        blocked = tmp_path / "blocked"
        nested = blocked / "deep" / "nested"
        nested.mkdir(parents=True)
        test_file = nested / "secret.txt"
        test_file.write_text("secret")

        engine = PathDecisionEngine(
            allowed_paths=None,
            blocked_paths=[blocked],
            cwd=tmp_path,
        )

        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.BLOCKED


# =============================================================================
# 3. Path Resolution
# =============================================================================


class TestPathResolution:
    """Test path resolution behavior."""

    def test_relative_path_resolved_against_cwd(self, tmp_path: Path) -> None:
        """Relative paths are resolved against cwd."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[subdir], cwd=subdir)

        # Use relative path
        decision = engine.check_access("test.txt")

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()

    def test_relative_path_with_parent(self, tmp_path: Path) -> None:
        """Relative paths with parent references are resolved correctly."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        test_file = dir_b / "test.txt"
        test_file.write_text("test")

        # cwd is in 'a', allowed is 'b'
        engine = PathDecisionEngine(allowed_paths=[dir_b], cwd=dir_a)

        # Use relative path from 'a' to 'b'
        decision = engine.check_access("../b/test.txt")

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()

    def test_symlink_followed_correctly(self, tmp_path: Path) -> None:
        """Symlinks are resolved and followed."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        real_file = real_dir / "test.txt"
        real_file.write_text("test")

        symlink = tmp_path / "link"
        symlink.symlink_to(real_dir)

        # Allow the real directory
        engine = PathDecisionEngine(allowed_paths=[real_dir], cwd=tmp_path)

        # Access via symlink should work (resolves to real path)
        decision = engine.check_access(symlink / "test.txt")

        assert decision.allowed is True
        assert decision.resolved_path == real_file.resolve()

    def test_symlink_to_blocked_denied(self, tmp_path: Path) -> None:
        """Symlink pointing to blocked path is denied."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        secret = blocked / "secret.txt"
        secret.write_text("secret")

        symlink = tmp_path / "innocent_link"
        symlink.symlink_to(secret)

        engine = PathDecisionEngine(
            allowed_paths=None,
            blocked_paths=[blocked],
            cwd=tmp_path,
        )

        decision = engine.check_access(symlink)

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.BLOCKED

    def test_symlink_escape_blocked(self, tmp_path: Path) -> None:
        """Symlink escaping allowed directory is blocked."""
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        target = outside / "target.txt"
        target.write_text("target")

        # Create symlink inside allowed pointing outside
        escape_link = allowed / "escape"
        escape_link.symlink_to(target)

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)

        decision = engine.check_access(escape_link)

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.OUTSIDE_ALLOWED

    def test_invalid_path_resolution_fails(self, tmp_path: Path) -> None:
        """Invalid path that cannot be resolved fails gracefully."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        # Create a path with null character (invalid on most systems)
        # Note: Python's Path may handle this differently on different systems
        # Using a more portable approach: dangling symlink
        dangling = tmp_path / "dangling"
        dangling.symlink_to(tmp_path / "nonexistent_target")

        # The path can be resolved (to the dangling target)
        # But the real file doesn't exist
        decision = engine.check_access(dangling)

        # Should still resolve (symlinks can be resolved even if target is missing)
        assert decision.allowed is True


# =============================================================================
# 4. Existence Constraints
# =============================================================================


class TestExistenceConstraints:
    """Test must_exist and must_be_dir constraints."""

    def test_must_exist_with_existing_file(self, tmp_path: Path) -> None:
        """must_exist=True allows existing files."""
        test_file = tmp_path / "exists.txt"
        test_file.write_text("content")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_access(test_file, must_exist=True)

        assert decision.allowed is True
        assert decision.resolved_path == test_file.resolve()

    def test_must_exist_with_nonexistent_file(self, tmp_path: Path) -> None:
        """must_exist=True denies non-existent files."""
        nonexistent = tmp_path / "does_not_exist.txt"

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_access(nonexistent, must_exist=True)

        assert decision.allowed is False
        assert decision.resolved_path is None
        assert decision.reason == PathDecisionReason.PATH_NOT_FOUND
        assert "not found" in decision.reason_detail.lower()

    def test_must_be_dir_with_directory(self, tmp_path: Path) -> None:
        """must_be_dir=True allows directories."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_access(test_dir, must_be_dir=True)

        assert decision.allowed is True
        assert decision.resolved_path == test_dir.resolve()

    def test_must_be_dir_with_file(self, tmp_path: Path) -> None:
        """must_be_dir=True denies regular files."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_access(test_file, must_be_dir=True)

        assert decision.allowed is False
        assert decision.resolved_path is None
        assert decision.reason == PathDecisionReason.NOT_A_DIRECTORY
        assert "not a directory" in decision.reason_detail.lower()

    def test_must_be_dir_with_nonexistent(self, tmp_path: Path) -> None:
        """must_be_dir=True with non-existent path is allowed (unless must_exist)."""
        nonexistent = tmp_path / "nonexistent_dir"

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        # must_be_dir without must_exist - path doesn't exist, so not a dir check is skipped
        decision = engine.check_access(nonexistent, must_be_dir=True)

        assert decision.allowed is True

    def test_both_constraints_together(self, tmp_path: Path) -> None:
        """Both must_exist and must_be_dir work together."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("content")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        # Directory should pass both
        decision = engine.check_access(test_dir, must_exist=True, must_be_dir=True)
        assert decision.allowed is True

        # File should fail must_be_dir
        decision = engine.check_access(test_file, must_exist=True, must_be_dir=True)
        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.NOT_A_DIRECTORY

        # Non-existent should fail must_exist first
        decision = engine.check_access(
            tmp_path / "nope", must_exist=True, must_be_dir=True
        )
        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.PATH_NOT_FOUND


# =============================================================================
# 5. PathDecision Result
# =============================================================================


class TestPathDecisionResult:
    """Test PathDecision dataclass behavior."""

    def test_allowed_decision_has_resolved_path(self, tmp_path: Path) -> None:
        """Allowed decision has resolved_path set."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.resolved_path is not None
        assert decision.resolved_path == test_file.resolve()

    def test_denied_decision_has_no_resolved_path(self, tmp_path: Path) -> None:
        """Denied decision has resolved_path=None."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        test_file = outside / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)
        decision = engine.check_access(test_file)

        assert decision.allowed is False
        assert decision.resolved_path is None

    def test_reason_and_detail_set(self, tmp_path: Path) -> None:
        """Reason and reason_detail are always set."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        decision = engine.check_access(test_file)

        assert decision.reason is not None
        assert isinstance(decision.reason, PathDecisionReason)
        assert decision.reason_detail is not None
        assert len(decision.reason_detail) > 0

    def test_original_path_preserved(self, tmp_path: Path) -> None:
        """Original path string is preserved in decision."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        original = "./relative/path.txt"
        decision = engine.check_access(original)

        assert decision.original_path == original

    def test_matched_rule_for_allowed(self, tmp_path: Path) -> None:
        """matched_rule is set when path matches an allowed_path."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        test_file = allowed / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)
        decision = engine.check_access(test_file)

        assert decision.matched_rule == allowed

    def test_matched_rule_for_blocked(self, tmp_path: Path) -> None:
        """matched_rule is set when path matches a blocked_path."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        test_file = blocked / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(
            allowed_paths=None, blocked_paths=[blocked], cwd=tmp_path
        )
        decision = engine.check_access(test_file)

        assert decision.matched_rule == blocked

    def test_matched_rule_none_for_unrestricted(self, tmp_path: Path) -> None:
        """matched_rule is None in unrestricted mode."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        decision = engine.check_access(test_file)

        assert decision.matched_rule is None

    def test_str_representation(self, tmp_path: Path) -> None:
        """String representation is readable."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        decision = engine.check_access(test_file)

        str_repr = str(decision)
        assert "ALLOWED" in str_repr or "DENIED" in str_repr
        assert str(test_file) in str_repr

    def test_raise_if_denied_raises_on_denied(self, tmp_path: Path) -> None:
        """raise_if_denied() raises PathSecurityError when denied."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        test_file = outside / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)
        decision = engine.check_access(test_file)

        with pytest.raises(PathSecurityError) as exc_info:
            decision.raise_if_denied()

        assert exc_info.value.path == str(test_file)
        assert exc_info.value.reason == decision.reason_detail

    def test_raise_if_denied_returns_path_on_allowed(self, tmp_path: Path) -> None:
        """raise_if_denied() returns resolved path when allowed."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        decision = engine.check_access(test_file)

        result = decision.raise_if_denied()

        assert result == test_file.resolve()


# =============================================================================
# 6. check_cwd() Method
# =============================================================================


class TestCheckCwd:
    """Test check_cwd() convenience method."""

    def test_none_cwd_returns_agent_default(self, tmp_path: Path) -> None:
        """None cwd returns the agent's default cwd."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_cwd(None)

        assert decision.allowed is True
        assert decision.resolved_path == tmp_path
        assert decision.reason == PathDecisionReason.CWD_DEFAULT
        assert "default working directory" in decision.reason_detail.lower()

    def test_valid_cwd_allowed(self, tmp_path: Path) -> None:
        """Valid working directory is allowed."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_cwd(str(work_dir))

        assert decision.allowed is True
        assert decision.resolved_path == work_dir.resolve()

    def test_nonexistent_cwd_denied(self, tmp_path: Path) -> None:
        """Non-existent working directory is denied."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_cwd(str(tmp_path / "nonexistent"))

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.PATH_NOT_FOUND

    def test_file_as_cwd_denied(self, tmp_path: Path) -> None:
        """File (not directory) as cwd is denied."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        decision = engine.check_cwd(str(test_file))

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.NOT_A_DIRECTORY

    def test_cwd_outside_allowed_denied(self, tmp_path: Path) -> None:
        """Working directory outside allowed paths is denied."""
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)

        decision = engine.check_cwd(str(outside))

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.OUTSIDE_ALLOWED

    def test_cwd_within_allowed_allowed(self, tmp_path: Path) -> None:
        """Working directory within allowed paths is allowed."""
        allowed = tmp_path / "allowed"
        subdir = allowed / "subdir"
        allowed.mkdir()
        subdir.mkdir()

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)

        decision = engine.check_cwd(str(subdir))

        assert decision.allowed is True
        assert decision.resolved_path == subdir.resolve()

    def test_blocked_cwd_denied(self, tmp_path: Path) -> None:
        """Working directory in blocked paths is denied."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()

        engine = PathDecisionEngine(
            allowed_paths=None, blocked_paths=[blocked], cwd=tmp_path
        )

        decision = engine.check_cwd(str(blocked))

        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.BLOCKED


# =============================================================================
# 7. from_services() Factory
# =============================================================================


class TestFromServicesFactory:
    """Test from_services() class method."""

    def test_creates_engine_from_services(self, tmp_path: Path) -> None:
        """Creates engine from ServiceContainer."""
        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("allowed_paths", [tmp_path])
        services.register("blocked_paths", [tmp_path / "blocked"])

        engine = PathDecisionEngine.from_services(services)

        assert engine.allowed_paths == [tmp_path]
        assert engine.blocked_paths == [tmp_path / "blocked"]
        assert engine.cwd == tmp_path

    def test_uses_cwd_from_services(self, tmp_path: Path) -> None:
        """Engine uses cwd from ServiceContainer."""
        custom_cwd = tmp_path / "custom"
        custom_cwd.mkdir()

        services = ServiceContainer()
        services.register("cwd", custom_cwd)

        engine = PathDecisionEngine.from_services(services)

        assert engine.cwd == custom_cwd

    def test_respects_tool_specific_allowed_paths(self, tmp_path: Path) -> None:
        """Engine uses per-tool allowed_paths when tool_name provided."""
        # Create a mock permissions structure
        from nexus3.core.permissions import AgentPermissions
        from nexus3.core.policy import PermissionLevel, PermissionPolicy
        from nexus3.core.presets import ToolPermission

        tool_specific_path = tmp_path / "tool_specific"
        tool_specific_path.mkdir()
        general_path = tmp_path / "general"
        general_path.mkdir()

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[general_path],
        )
        tool_perms = {
            "special_tool": ToolPermission(allowed_paths=[tool_specific_path])
        }
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions=tool_perms,
        )

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("permissions", permissions)

        # Without tool_name, uses general path
        engine_general = PathDecisionEngine.from_services(services)
        assert engine_general.allowed_paths == [general_path]

        # With tool_name, uses tool-specific path
        engine_specific = PathDecisionEngine.from_services(
            services, tool_name="special_tool"
        )
        assert engine_specific.allowed_paths == [tool_specific_path]

    def test_inherits_blocked_paths_from_permissions(self, tmp_path: Path) -> None:
        """Engine inherits blocked_paths from agent permissions."""
        from nexus3.core.permissions import AgentPermissions
        from nexus3.core.policy import PermissionLevel, PermissionPolicy

        blocked = tmp_path / "blocked"
        blocked.mkdir()

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            blocked_paths=[blocked],
        )
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
        )

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("permissions", permissions)

        engine = PathDecisionEngine.from_services(services)

        assert blocked in engine.blocked_paths

    def test_unrestricted_when_no_allowed_paths(self, tmp_path: Path) -> None:
        """Engine is unrestricted when permissions have no allowed_paths."""
        from nexus3.core.permissions import AgentPermissions
        from nexus3.core.policy import PermissionLevel, PermissionPolicy

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=None,  # Unrestricted
        )
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
        )

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("permissions", permissions)

        engine = PathDecisionEngine.from_services(services)

        assert engine.is_unrestricted() is True
        assert engine.allowed_paths is None


# =============================================================================
# 8. Helper Methods
# =============================================================================


class TestHelperMethods:
    """Test helper methods and properties."""

    def test_allowed_paths_property(self, tmp_path: Path) -> None:
        """allowed_paths property returns configured paths."""
        allowed = [tmp_path / "a", tmp_path / "b"]

        engine = PathDecisionEngine(allowed_paths=allowed, cwd=tmp_path)

        assert engine.allowed_paths == allowed

    def test_allowed_paths_none_returns_none(self, tmp_path: Path) -> None:
        """allowed_paths property returns None for unrestricted."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        assert engine.allowed_paths is None

    def test_blocked_paths_property(self, tmp_path: Path) -> None:
        """blocked_paths property returns configured paths."""
        blocked = [tmp_path / "blocked"]

        engine = PathDecisionEngine(blocked_paths=blocked, cwd=tmp_path)

        assert engine.blocked_paths == blocked

    def test_blocked_paths_empty_by_default(self, tmp_path: Path) -> None:
        """blocked_paths defaults to empty list."""
        engine = PathDecisionEngine(cwd=tmp_path)

        assert engine.blocked_paths == []

    def test_cwd_property(self, tmp_path: Path) -> None:
        """cwd property returns configured cwd."""
        custom_cwd = tmp_path / "cwd"
        custom_cwd.mkdir()

        engine = PathDecisionEngine(cwd=custom_cwd)

        assert engine.cwd == custom_cwd

    def test_explain_config_unrestricted(self, tmp_path: Path) -> None:
        """explain_config() describes unrestricted mode."""
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        explanation = engine.explain_config()

        assert "UNRESTRICTED" in explanation
        assert "all paths permitted" in explanation.lower()
        assert str(tmp_path) in explanation  # Working directory shown

    def test_explain_config_restricted(self, tmp_path: Path) -> None:
        """explain_config() lists allowed paths."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        engine = PathDecisionEngine(allowed_paths=[allowed], cwd=tmp_path)

        explanation = engine.explain_config()

        assert "Allowed paths:" in explanation
        assert str(allowed) in explanation

    def test_explain_config_empty_allowed(self, tmp_path: Path) -> None:
        """explain_config() shows NONE for empty allowed_paths."""
        engine = PathDecisionEngine(allowed_paths=[], cwd=tmp_path)

        explanation = engine.explain_config()

        assert "NONE" in explanation
        assert "all access denied" in explanation.lower()

    def test_explain_config_blocked(self, tmp_path: Path) -> None:
        """explain_config() lists blocked paths."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()

        engine = PathDecisionEngine(blocked_paths=[blocked], cwd=tmp_path)

        explanation = engine.explain_config()

        assert "Blocked paths:" in explanation
        assert str(blocked) in explanation

    def test_explain_config_no_blocked(self, tmp_path: Path) -> None:
        """explain_config() shows 'none' when no blocked paths."""
        engine = PathDecisionEngine(cwd=tmp_path)

        explanation = engine.explain_config()

        assert "Blocked paths: none" in explanation


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_home_directory_expansion(self, tmp_path: Path) -> None:
        """Tilde is expanded in paths."""
        # We can't easily test actual ~ expansion, but we can verify
        # the expanduser() call happens
        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        # Create a path string with ~
        # This will expand to user's home directory
        decision = engine.check_access("~")

        # Should expand and be allowed (unrestricted mode)
        assert decision.allowed is True
        assert decision.resolved_path is not None
        # The path should be expanded (not contain ~)
        assert "~" not in str(decision.resolved_path)

    def test_very_deep_nesting(self, tmp_path: Path) -> None:
        """Very deeply nested paths work correctly."""
        deep_path = tmp_path
        for i in range(20):
            deep_path = deep_path / f"level{i}"
        deep_path.mkdir(parents=True)
        deep_file = deep_path / "deep.txt"
        deep_file.write_text("deep")

        engine = PathDecisionEngine(allowed_paths=[tmp_path], cwd=tmp_path)

        decision = engine.check_access(deep_file)

        assert decision.allowed is True
        assert decision.resolved_path == deep_file.resolve()

    def test_unicode_path_names(self, tmp_path: Path) -> None:
        """Unicode characters in path names work."""
        unicode_dir = tmp_path / "unicode_test"
        unicode_dir.mkdir()
        unicode_file = unicode_dir / "test.txt"
        unicode_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[unicode_dir], cwd=tmp_path)

        decision = engine.check_access(unicode_file)

        assert decision.allowed is True

    def test_path_with_spaces(self, tmp_path: Path) -> None:
        """Paths with spaces work correctly."""
        spaced_dir = tmp_path / "dir with spaces"
        spaced_dir.mkdir()
        spaced_file = spaced_dir / "file with spaces.txt"
        spaced_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=[spaced_dir], cwd=tmp_path)

        decision = engine.check_access(spaced_file)

        assert decision.allowed is True
        assert decision.resolved_path == spaced_file.resolve()

    def test_pathlib_path_input(self, tmp_path: Path) -> None:
        """Path objects are accepted as input."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)

        # Pass Path object directly
        decision = engine.check_access(test_file)

        assert decision.allowed is True
        assert decision.original_path == str(test_file)

    def test_cwd_defaults_to_process_cwd(self) -> None:
        """Engine defaults to process cwd if not specified."""
        engine = PathDecisionEngine(allowed_paths=None)

        assert engine.cwd == Path.cwd()

    def test_decision_is_frozen(self, tmp_path: Path) -> None:
        """PathDecision is immutable (frozen dataclass)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        engine = PathDecisionEngine(allowed_paths=None, cwd=tmp_path)
        decision = engine.check_access(test_file)

        with pytest.raises((TypeError, AttributeError)):
            decision.allowed = False  # type: ignore


# =============================================================================
# Integration with ServiceContainer
# =============================================================================


class TestServiceContainerIntegration:
    """Test integration with ServiceContainer without full permissions."""

    def test_fallback_to_simple_services(self, tmp_path: Path) -> None:
        """Works with simple services (no AgentPermissions)."""
        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("allowed_paths", [tmp_path])

        engine = PathDecisionEngine.from_services(services)

        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        decision = engine.check_access(test_file)
        assert decision.allowed is True

    def test_uses_blocked_paths_from_simple_services(self, tmp_path: Path) -> None:
        """Uses blocked_paths from simple services."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        (blocked / "secret.txt").write_text("secret")

        services = ServiceContainer()
        services.register("cwd", tmp_path)
        services.register("blocked_paths", [blocked])

        engine = PathDecisionEngine.from_services(services)

        decision = engine.check_access(blocked / "secret.txt")
        assert decision.allowed is False
        assert decision.reason == PathDecisionReason.BLOCKED
