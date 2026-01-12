"""Unit tests for nexus3.core.permissions module."""

from pathlib import Path

import pytest

from nexus3.core.permissions import (
    DESTRUCTIVE_ACTIONS,
    NETWORK_ACTIONS,
    SAFE_ACTIONS,
    SANDBOXED_DISABLED_TOOLS,
    PermissionLevel,
    PermissionPolicy,
)


class TestPermissionLevel:
    """Tests for PermissionLevel enum."""

    def test_yolo_value(self):
        """YOLO level has value 'yolo'."""
        assert PermissionLevel.YOLO.value == "yolo"

    def test_trusted_value(self):
        """TRUSTED level has value 'trusted'."""
        assert PermissionLevel.TRUSTED.value == "trusted"

    def test_sandboxed_value(self):
        """SANDBOXED level has value 'sandboxed'."""
        assert PermissionLevel.SANDBOXED.value == "sandboxed"

    def test_from_string_yolo(self):
        """PermissionLevel can be created from 'yolo' string."""
        level = PermissionLevel("yolo")
        assert level == PermissionLevel.YOLO

    def test_from_string_trusted(self):
        """PermissionLevel can be created from 'trusted' string."""
        level = PermissionLevel("trusted")
        assert level == PermissionLevel.TRUSTED

    def test_from_string_sandboxed(self):
        """PermissionLevel can be created from 'sandboxed' string."""
        level = PermissionLevel("sandboxed")
        assert level == PermissionLevel.SANDBOXED

    def test_invalid_string_raises_error(self):
        """Invalid permission level string raises ValueError."""
        with pytest.raises(ValueError):
            PermissionLevel("invalid")

    def test_three_levels_exist(self):
        """Exactly three permission levels exist."""
        assert len(PermissionLevel) == 3


class TestPermissionPolicyFromLevel:
    """Tests for PermissionPolicy.from_level class method."""

    def test_from_level_string_yolo(self):
        """from_level accepts 'yolo' string."""
        policy = PermissionPolicy.from_level("yolo")
        assert policy.level == PermissionLevel.YOLO

    def test_from_level_string_trusted(self):
        """from_level accepts 'trusted' string."""
        policy = PermissionPolicy.from_level("trusted")
        assert policy.level == PermissionLevel.TRUSTED

    def test_from_level_string_sandboxed(self):
        """from_level accepts 'sandboxed' string."""
        policy = PermissionPolicy.from_level("sandboxed")
        assert policy.level == PermissionLevel.SANDBOXED

    def test_from_level_enum_yolo(self):
        """from_level accepts PermissionLevel enum."""
        policy = PermissionPolicy.from_level(PermissionLevel.YOLO)
        assert policy.level == PermissionLevel.YOLO

    def test_from_level_enum_trusted(self):
        """from_level accepts PermissionLevel enum."""
        policy = PermissionPolicy.from_level(PermissionLevel.TRUSTED)
        assert policy.level == PermissionLevel.TRUSTED

    def test_from_level_enum_sandboxed(self):
        """from_level accepts PermissionLevel enum."""
        policy = PermissionPolicy.from_level(PermissionLevel.SANDBOXED)
        assert policy.level == PermissionLevel.SANDBOXED

    def test_from_level_case_insensitive(self):
        """from_level is case-insensitive for strings."""
        policy1 = PermissionPolicy.from_level("YOLO")
        policy2 = PermissionPolicy.from_level("Trusted")
        policy3 = PermissionPolicy.from_level("SANDBOXED")

        assert policy1.level == PermissionLevel.YOLO
        assert policy2.level == PermissionLevel.TRUSTED
        assert policy3.level == PermissionLevel.SANDBOXED

    def test_from_level_invalid_string_raises_error(self):
        """from_level raises ValueError for invalid string."""
        with pytest.raises(ValueError) as exc_info:
            PermissionPolicy.from_level("invalid")

        assert "Invalid permission level" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_from_level_yolo_no_path_restrictions(self):
        """YOLO level has no path restrictions by default."""
        policy = PermissionPolicy.from_level("yolo")
        assert policy.allowed_paths is None

    def test_from_level_trusted_no_path_restrictions(self):
        """TRUSTED level has no path restrictions by default."""
        policy = PermissionPolicy.from_level("trusted")
        assert policy.allowed_paths is None

    def test_from_level_sandboxed_has_cwd_only(self):
        """SANDBOXED level defaults to CWD only."""
        policy = PermissionPolicy.from_level("sandboxed")
        assert policy.allowed_paths is not None
        assert len(policy.allowed_paths) == 1
        assert Path.cwd() in policy.allowed_paths

    def test_from_level_empty_blocked_paths(self):
        """All levels default to empty blocked_paths."""
        for level in ["yolo", "trusted", "sandboxed"]:
            policy = PermissionPolicy.from_level(level)
            assert policy.blocked_paths == []


class TestPermissionPolicyPathAccess:
    """Tests for can_read_path and can_write_path methods."""

    def test_yolo_can_read_any_path(self, tmp_path):
        """YOLO level can read any path."""
        policy = PermissionPolicy.from_level("yolo")
        assert policy.can_read_path(tmp_path / "any" / "file.txt")
        assert policy.can_read_path("/etc/passwd")
        assert policy.can_read_path("relative/path.txt")

    def test_yolo_can_write_any_path(self, tmp_path):
        """YOLO level can write to any path."""
        policy = PermissionPolicy.from_level("yolo")
        assert policy.can_write_path(tmp_path / "any" / "file.txt")
        assert policy.can_write_path("/etc/sensitive")
        assert policy.can_write_path("relative/path.txt")

    def test_trusted_can_read_any_path(self, tmp_path):
        """TRUSTED level can read any path."""
        policy = PermissionPolicy.from_level("trusted")
        assert policy.can_read_path(tmp_path / "any" / "file.txt")
        assert policy.can_read_path("/etc/passwd")

    def test_trusted_can_write_any_path(self, tmp_path):
        """TRUSTED level can write to any path."""
        policy = PermissionPolicy.from_level("trusted")
        assert policy.can_write_path(tmp_path / "any" / "file.txt")

    def test_sandboxed_can_read_cwd(self, tmp_path, monkeypatch):
        """SANDBOXED level can read files in CWD."""
        monkeypatch.chdir(tmp_path)
        policy = PermissionPolicy.from_level("sandboxed")
        assert policy.can_read_path(tmp_path / "file.txt")

    def test_sandboxed_can_write_cwd(self, tmp_path, monkeypatch):
        """SANDBOXED level can write files in CWD."""
        monkeypatch.chdir(tmp_path)
        policy = PermissionPolicy.from_level("sandboxed")
        assert policy.can_write_path(tmp_path / "file.txt")

    def test_sandboxed_cannot_read_outside_cwd(self, tmp_path, monkeypatch):
        """SANDBOXED level cannot read files outside CWD."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.chdir(sandbox)
        policy = PermissionPolicy.from_level("sandboxed")
        assert not policy.can_read_path(tmp_path / "outside.txt")

    def test_sandboxed_cannot_write_outside_cwd(self, tmp_path, monkeypatch):
        """SANDBOXED level cannot write files outside CWD."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.chdir(sandbox)
        policy = PermissionPolicy.from_level("sandboxed")
        assert not policy.can_write_path(tmp_path / "outside.txt")

    def test_blocked_paths_override_allowed(self, tmp_path):
        """Blocked paths override allowed paths."""
        blocked = tmp_path / "secret"
        blocked.mkdir()

        policy = PermissionPolicy(
            level=PermissionLevel.YOLO,
            allowed_paths=None,  # Unrestricted
            blocked_paths=[blocked],
        )

        assert policy.can_read_path(tmp_path / "other.txt")
        assert not policy.can_read_path(blocked / "sensitive.txt")
        assert not policy.can_write_path(blocked / "sensitive.txt")

    def test_custom_allowed_paths(self, tmp_path):
        """Custom allowed_paths restricts access."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        restricted = tmp_path / "restricted"
        restricted.mkdir()

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[allowed],
        )

        assert policy.can_read_path(allowed / "file.txt")
        assert not policy.can_read_path(restricted / "file.txt")

    def test_multiple_allowed_paths(self, tmp_path):
        """Multiple allowed paths all work."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[dir1, dir2],
        )

        assert policy.can_read_path(dir1 / "file.txt")
        assert policy.can_read_path(dir2 / "file.txt")
        assert not policy.can_read_path(tmp_path / "file.txt")

    def test_empty_allowed_paths_blocks_read_but_not_write_for_trusted(self, tmp_path):
        """Empty allowed_paths blocks read but not write for TRUSTED (uses confirmation instead)."""
        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[],
        )

        # TRUSTED with empty allowed_paths blocks read
        assert not policy.can_read_path(tmp_path / "file.txt")
        # But allows write (confirmation handles write restrictions for TRUSTED)
        assert policy.can_write_path(tmp_path / "file.txt")

    def test_empty_allowed_paths_blocks_all_for_sandboxed(self, tmp_path):
        """Empty allowed_paths list blocks all paths for SANDBOXED."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[],
        )

        assert not policy.can_read_path(tmp_path / "file.txt")
        assert not policy.can_write_path(tmp_path / "file.txt")

    def test_path_accepts_string(self, tmp_path, monkeypatch):
        """Path methods accept string arguments."""
        monkeypatch.chdir(tmp_path)
        policy = PermissionPolicy.from_level("sandboxed")

        assert policy.can_read_path(str(tmp_path / "file.txt"))
        assert policy.can_write_path(str(tmp_path / "file.txt"))


class TestPermissionPolicyNetwork:
    """Tests for network access control."""

    def test_yolo_can_network(self):
        """YOLO level allows network access."""
        policy = PermissionPolicy.from_level("yolo")
        assert policy.can_network() is True

    def test_trusted_can_network(self):
        """TRUSTED level allows network access."""
        policy = PermissionPolicy.from_level("trusted")
        assert policy.can_network() is True

    def test_sandboxed_cannot_network(self):
        """SANDBOXED level blocks network access."""
        policy = PermissionPolicy.from_level("sandboxed")
        assert policy.can_network() is False


class TestPermissionPolicyConfirmation:
    """Tests for requires_confirmation method."""

    def test_yolo_never_requires_confirmation(self):
        """YOLO level never requires confirmation."""
        policy = PermissionPolicy.from_level("yolo")

        for action in DESTRUCTIVE_ACTIONS:
            assert policy.requires_confirmation(action) is False

        for action in SAFE_ACTIONS:
            assert policy.requires_confirmation(action) is False

    def test_trusted_requires_confirmation_for_destructive(self):
        """TRUSTED level requires confirmation for destructive actions."""
        policy = PermissionPolicy.from_level("trusted")

        for action in DESTRUCTIVE_ACTIONS:
            assert policy.requires_confirmation(action) is True

    def test_trusted_no_confirmation_for_safe_actions(self):
        """TRUSTED level doesn't require confirmation for safe actions."""
        policy = PermissionPolicy.from_level("trusted")

        for action in SAFE_ACTIONS:
            assert policy.requires_confirmation(action) is False

    def test_sandboxed_no_confirmation_for_safe_actions(self):
        """SANDBOXED level doesn't require confirmation for safe actions."""
        policy = PermissionPolicy.from_level("sandboxed")

        for action in SAFE_ACTIONS:
            assert policy.requires_confirmation(action) is False

    def test_sandboxed_never_requires_confirmation(self):
        """SANDBOXED level never requires confirmation (enforces sandbox instead)."""
        policy = PermissionPolicy.from_level("sandboxed")

        # SANDBOXED mode doesn't use confirmation - it just enforces the sandbox
        for action in DESTRUCTIVE_ACTIONS:
            assert policy.requires_confirmation(action) is False

    def test_requires_confirmation_case_insensitive(self):
        """requires_confirmation is case-insensitive."""
        policy = PermissionPolicy.from_level("trusted")

        assert policy.requires_confirmation("DELETE") is True
        assert policy.requires_confirmation("Delete") is True
        assert policy.requires_confirmation("delete") is True


class TestPermissionPolicyAllowsAction:
    """Tests for allows_action method."""

    def test_yolo_allows_all_actions(self):
        """YOLO level allows all actions."""
        policy = PermissionPolicy.from_level("yolo")

        assert policy.allows_action("delete") is True
        assert policy.allows_action("http_request") is True
        assert policy.allows_action("anything") is True

    def test_trusted_allows_all_actions(self):
        """TRUSTED level allows all actions."""
        policy = PermissionPolicy.from_level("trusted")

        assert policy.allows_action("delete") is True
        assert policy.allows_action("http_request") is True
        assert policy.allows_action("anything") is True

    def test_sandboxed_blocks_disabled_tools(self):
        """SANDBOXED level blocks execution and agent management tools."""
        policy = PermissionPolicy.from_level("sandboxed")

        for action in SANDBOXED_DISABLED_TOOLS:
            assert policy.allows_action(action) is False

    def test_sandboxed_allows_non_disabled_actions(self):
        """SANDBOXED level allows actions not in SANDBOXED_DISABLED_TOOLS."""
        policy = PermissionPolicy.from_level("sandboxed")

        for action in SAFE_ACTIONS:
            assert policy.allows_action(action) is True

        # Write/delete actions are allowed in sandbox (but limited to sandbox paths)
        assert policy.allows_action("delete") is True
        assert policy.allows_action("write") is True

    def test_allows_action_case_insensitive(self):
        """allows_action is case-insensitive."""
        policy = PermissionPolicy.from_level("sandboxed")

        # bash is in SANDBOXED_DISABLED_TOOLS
        assert policy.allows_action("BASH") is False
        assert policy.allows_action("Bash") is False
        assert policy.allows_action("bash") is False


class TestPermissionPolicyStr:
    """Tests for string representation."""

    def test_str_includes_level(self):
        """String representation includes level."""
        policy = PermissionPolicy.from_level("trusted")
        assert "trusted" in str(policy)

    def test_str_includes_allowed_paths(self, tmp_path):
        """String representation includes allowed_paths when set."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[tmp_path],
        )
        assert str(tmp_path) in str(policy)

    def test_str_includes_blocked_paths(self, tmp_path):
        """String representation includes blocked_paths when set."""
        policy = PermissionPolicy(
            level=PermissionLevel.YOLO,
            blocked_paths=[tmp_path],
        )
        assert str(tmp_path) in str(policy)
        assert "blocked_paths" in str(policy)

    def test_str_no_paths_when_unrestricted(self):
        """String representation omits path info when unrestricted."""
        policy = PermissionPolicy.from_level("yolo")
        result = str(policy)
        assert "allowed_paths" not in result


class TestActionSets:
    """Tests for action category sets."""

    def test_destructive_actions_not_empty(self):
        """DESTRUCTIVE_ACTIONS is not empty."""
        assert len(DESTRUCTIVE_ACTIONS) > 0

    def test_safe_actions_not_empty(self):
        """SAFE_ACTIONS is not empty."""
        assert len(SAFE_ACTIONS) > 0

    def test_network_actions_not_empty(self):
        """NETWORK_ACTIONS is not empty."""
        assert len(NETWORK_ACTIONS) > 0

    def test_destructive_and_safe_disjoint(self):
        """DESTRUCTIVE_ACTIONS and SAFE_ACTIONS don't overlap."""
        assert DESTRUCTIVE_ACTIONS.isdisjoint(SAFE_ACTIONS)

    def test_action_sets_are_frozen(self):
        """Action sets are frozensets (immutable)."""
        assert isinstance(DESTRUCTIVE_ACTIONS, frozenset)
        assert isinstance(SAFE_ACTIONS, frozenset)
        assert isinstance(NETWORK_ACTIONS, frozenset)


class TestPermissionPolicyDataclass:
    """Tests for PermissionPolicy as a dataclass."""

    def test_can_create_with_all_params(self, tmp_path):
        """PermissionPolicy can be created with all parameters."""
        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
            blocked_paths=[tmp_path / "secret"],
        )

        assert policy.level == PermissionLevel.TRUSTED
        assert policy.allowed_paths == [tmp_path]
        assert policy.blocked_paths == [tmp_path / "secret"]

    def test_blocked_paths_defaults_to_empty_list(self):
        """blocked_paths defaults to empty list."""
        policy = PermissionPolicy(
            level=PermissionLevel.YOLO,
        )
        assert policy.blocked_paths == []

    def test_allowed_paths_defaults_to_none(self):
        """allowed_paths defaults to None."""
        policy = PermissionPolicy(
            level=PermissionLevel.YOLO,
        )
        assert policy.allowed_paths is None


class TestCoreModuleExports:
    """Tests for exports from nexus3.core module."""

    def test_permission_level_exported(self):
        """PermissionLevel is exported from nexus3.core."""
        from nexus3.core import PermissionLevel as CorePermissionLevel
        assert CorePermissionLevel is PermissionLevel

    def test_permission_policy_exported(self):
        """PermissionPolicy is exported from nexus3.core."""
        from nexus3.core import PermissionPolicy as CorePermissionPolicy
        assert CorePermissionPolicy is PermissionPolicy
