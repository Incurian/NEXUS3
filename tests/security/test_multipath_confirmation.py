"""Fix 1.2: Tests for multi-path confirmation (C2 vulnerability fix).

This tests the security fix for multi-path tools like copy_file and rename
where confirmation must trigger on the DESTINATION path, not the source.

The vulnerability:
- Before fix: copy_file("/safe/source", "/sensitive/dest") would only check
  confirmation on "/safe/source" (allowed), not "/sensitive/dest" (needs confirm)
- After fix: Confirmation triggers based on write paths (destination)
- Allowances are applied to write paths, not source paths

Key behaviors tested:
1. copy_file destination triggers confirmation
2. rename destination triggers confirmation
3. Allowance is applied to destination, not source
4. Single-path tools (edit_file, write_file) still work correctly
5. Read-only tools (read_file, grep) don't trigger confirmation
"""

from pathlib import Path

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionLevel,
    PermissionPolicy,
    SessionAllowances,
)
from nexus3.core.types import ToolCall
from nexus3.session.enforcer import PermissionEnforcer
from nexus3.session.path_semantics import (
    TOOL_PATH_SEMANTICS,
    ToolPathSemantics,
    extract_display_path,
    extract_tool_paths,
    extract_write_paths,
    get_semantics,
)


class TestToolPathSemantics:
    """Test the ToolPathSemantics data structure and registry."""

    def test_copy_file_semantics(self) -> None:
        """copy_file has source as read, destination as write."""
        semantics = get_semantics("copy_file")
        assert semantics.read_keys == ("source",)
        assert semantics.write_keys == ("destination",)
        assert semantics.display_key == "destination"

    def test_rename_semantics(self) -> None:
        """rename has source as read, destination as write."""
        semantics = get_semantics("rename")
        assert semantics.read_keys == ("source",)
        assert semantics.write_keys == ("destination",)
        assert semantics.display_key == "destination"

    def test_write_file_semantics(self) -> None:
        """write_file has path as write only."""
        semantics = get_semantics("write_file")
        assert semantics.read_keys == ()
        assert semantics.write_keys == ("path",)
        assert semantics.display_key == "path"

    def test_edit_file_semantics(self) -> None:
        """edit_file has path as both read and write."""
        semantics = get_semantics("edit_file")
        assert semantics.read_keys == ("path",)
        assert semantics.write_keys == ("path",)
        assert semantics.display_key == "path"

    def test_edit_lines_semantics_registered(self) -> None:
        """edit_lines has explicit path semantics for confirmation handling."""
        assert TOOL_PATH_SEMANTICS["edit_lines"] == ToolPathSemantics(
            read_keys=("path",),
            write_keys=("path",),
            display_key="path",
        )
        assert get_semantics("edit_lines") == TOOL_PATH_SEMANTICS["edit_lines"]

    def test_patch_semantics_registered(self) -> None:
        """patch prefers path while accepting target as a compatibility alias."""
        assert TOOL_PATH_SEMANTICS["patch"] == ToolPathSemantics(
            read_keys=("path", "target", "diff_file"),
            write_keys=("path", "target"),
            display_key="path",
        )
        assert get_semantics("patch") == TOOL_PATH_SEMANTICS["patch"]

    def test_read_file_semantics(self) -> None:
        """read_file has path as read only."""
        semantics = get_semantics("read_file")
        assert semantics.read_keys == ("path",)
        assert semantics.write_keys == ()
        assert semantics.display_key is None

    def test_unknown_tool_defaults(self) -> None:
        """Unknown tools get safe defaults (path as read+write)."""
        semantics = get_semantics("unknown_tool_xyz")
        assert semantics.read_keys == ("path",)
        assert semantics.write_keys == ("path",)
        assert semantics.display_key == "path"


class TestExtractWritePaths:
    """Test the extract_write_paths function."""

    def test_copy_file_returns_destination(self) -> None:
        """copy_file returns only the destination path."""
        args = {"source": "/safe/file.txt", "destination": "/sensitive/copy.txt"}
        paths = extract_write_paths("copy_file", args)
        assert len(paths) == 1
        assert paths[0] == Path("/sensitive/copy.txt")

    def test_rename_returns_destination(self) -> None:
        """rename returns only the destination path."""
        args = {"source": "/old/name.txt", "destination": "/new/name.txt"}
        paths = extract_write_paths("rename", args)
        assert len(paths) == 1
        assert paths[0] == Path("/new/name.txt")

    def test_write_file_returns_path(self) -> None:
        """write_file returns the path."""
        args = {"path": "/some/file.txt", "content": "data"}
        paths = extract_write_paths("write_file", args)
        assert len(paths) == 1
        assert paths[0] == Path("/some/file.txt")

    def test_edit_lines_returns_path(self) -> None:
        """edit_lines returns the path it will modify."""
        args = {
            "path": "/some/file.txt",
            "start_line": 2,
            "end_line": 2,
            "new_text": "updated",
        }
        paths = extract_write_paths("edit_lines", args)
        assert paths == [Path("/some/file.txt")]

    def test_patch_returns_target(self) -> None:
        """patch returns the preferred path argument, not diff_file."""
        args = {
            "path": "/repo/src/file.py",
            "diff_file": "/repo/changes.diff",
        }
        paths = extract_write_paths("patch", args)
        assert paths == [Path("/repo/src/file.py")]

    def test_patch_returns_target_alias(self) -> None:
        """patch still supports the legacy target alias."""
        args = {
            "target": "/repo/src/file.py",
            "diff_file": "/repo/changes.diff",
        }
        paths = extract_write_paths("patch", args)
        assert paths == [Path("/repo/src/file.py")]

    def test_read_file_returns_empty(self) -> None:
        """read_file has no write paths."""
        args = {"path": "/some/file.txt"}
        paths = extract_write_paths("read_file", args)
        assert paths == []

    def test_missing_keys_returns_empty(self) -> None:
        """Missing keys in args returns empty list."""
        args = {"unrelated": "value"}
        paths = extract_write_paths("copy_file", args)
        assert paths == []

    def test_empty_values_skipped(self) -> None:
        """Empty string values are skipped."""
        args = {"source": "/source.txt", "destination": ""}
        paths = extract_write_paths("copy_file", args)
        assert paths == []


class TestExtractDisplayPath:
    """Test the extract_display_path function."""

    def test_copy_file_shows_destination(self) -> None:
        """copy_file displays the destination path."""
        args = {"source": "/safe/file.txt", "destination": "/sensitive/copy.txt"}
        path = extract_display_path("copy_file", args)
        assert path == Path("/sensitive/copy.txt")

    def test_write_file_shows_path(self) -> None:
        """write_file displays the path."""
        args = {"path": "/some/file.txt", "content": "data"}
        path = extract_display_path("write_file", args)
        assert path == Path("/some/file.txt")

    def test_edit_lines_shows_path(self) -> None:
        """edit_lines displays the file path being modified."""
        args = {
            "path": "/some/file.txt",
            "start_line": 3,
            "end_line": 4,
            "new_text": "replacement",
        }
        path = extract_display_path("edit_lines", args)
        assert path == Path("/some/file.txt")

    def test_patch_shows_path(self) -> None:
        """patch displays the preferred path argument."""
        args = {
            "path": "/repo/src/file.py",
            "diff": "--- a/src/file.py\n+++ b/src/file.py\n",
        }
        path = extract_display_path("patch", args)
        assert path == Path("/repo/src/file.py")

    def test_patch_shows_target_alias(self) -> None:
        """patch falls back to the target alias when path is absent."""
        args = {
            "target": "/repo/src/file.py",
            "diff": "--- a/src/file.py\n+++ b/src/file.py\n",
        }
        path = extract_display_path("patch", args)
        assert path == Path("/repo/src/file.py")


class TestExtractToolPaths:
    """Test the extract_tool_paths helper used by permission checks."""

    def test_patch_paths_include_diff_file_and_write_target(self) -> None:
        """patch permission checks should see both the diff input and target file."""
        args = {
            "path": "/repo/src/file.py",
            "diff_file": "/repo/changes.diff",
        }
        paths = extract_tool_paths("patch", args)
        assert paths == [Path("/repo/src/file.py"), Path("/repo/changes.diff")]

    def test_patch_paths_support_legacy_target_alias(self) -> None:
        """patch permission checks still support the target alias."""
        args = {
            "target": "/repo/src/file.py",
            "diff_file": "/repo/changes.diff",
        }
        paths = extract_tool_paths("patch", args)
        assert paths == [Path("/repo/src/file.py"), Path("/repo/changes.diff")]

    def test_read_file_returns_none(self) -> None:
        """read_file has no display path (no confirmation needed)."""
        args = {"path": "/some/file.txt"}
        path = extract_display_path("read_file", args)
        assert path is None


class TestEnforcerRequiresConfirmation:
    """Test that requires_confirmation checks write paths correctly."""

    def _make_trusted_permissions(self, cwd: Path) -> AgentPermissions:
        """Create TRUSTED permissions with given cwd."""
        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            cwd=cwd,
            allowed_paths=None,  # Trusted can read anywhere
        )
        return AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            session_allowances=SessionAllowances(),
        )

    def test_copy_file_checks_destination(self, tmp_path: Path) -> None:
        """copy_file triggers confirmation based on destination, not source."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        # Source is in cwd (no confirm), destination is outside (should confirm)
        source = cwd / "source.txt"
        dest = outside / "dest.txt"

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="copy_file",
            arguments={"source": str(source), "destination": str(dest)}
        )

        # Should require confirmation because DESTINATION is outside cwd
        assert enforcer.requires_confirmation(tool_call, permissions) is True

    def test_copy_file_no_confirm_dest_in_cwd(self, tmp_path: Path) -> None:
        """copy_file doesn't need confirmation if destination is in cwd."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        # Source is outside, destination is in cwd
        source = outside / "source.txt"
        dest = cwd / "dest.txt"

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="copy_file",
            arguments={"source": str(source), "destination": str(dest)}
        )

        # Should NOT require confirmation because destination is in cwd
        assert enforcer.requires_confirmation(tool_call, permissions) is False

    def test_rename_checks_destination(self, tmp_path: Path) -> None:
        """rename triggers confirmation based on destination."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        source = cwd / "old.txt"
        dest = outside / "new.txt"

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="rename",
            arguments={"source": str(source), "destination": str(dest)}
        )

        # Should require confirmation because destination is outside cwd
        assert enforcer.requires_confirmation(tool_call, permissions) is True

    def test_write_file_unchanged_behavior(self, tmp_path: Path) -> None:
        """write_file confirmation behavior unchanged (single path)."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        # File in cwd - no confirmation
        tool_call_in = ToolCall(
            id="1",
            name="write_file",
            arguments={"path": str(cwd / "file.txt"), "content": "data"}
        )
        assert enforcer.requires_confirmation(tool_call_in, permissions) is False

        # File outside cwd - needs confirmation
        tool_call_out = ToolCall(
            id="2",
            name="write_file",
            arguments={"path": str(outside / "file.txt"), "content": "data"}
        )
        assert enforcer.requires_confirmation(tool_call_out, permissions) is True

    def test_edit_lines_no_confirm_path_in_cwd(self, tmp_path: Path) -> None:
        """edit_lines stays auto-approved for TRUSTED writes inside cwd."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="edit_lines",
            arguments={
                "path": str(cwd / "notes.txt"),
                "start_line": 1,
                "end_line": 1,
                "new_text": "updated",
            },
        )

        assert enforcer.requires_confirmation(tool_call, permissions) is False

    def test_edit_lines_checks_path_outside_cwd(self, tmp_path: Path) -> None:
        """edit_lines requires confirmation for TRUSTED writes outside cwd."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="edit_lines",
            arguments={
                "path": str(outside / "notes.txt"),
                "start_line": 1,
                "end_line": 1,
                "new_text": "updated",
            },
        )

        assert enforcer.requires_confirmation(tool_call, permissions) is True

    def test_patch_no_confirm_target_in_cwd(self, tmp_path: Path) -> None:
        """patch stays auto-approved for TRUSTED targets inside cwd."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="patch",
            arguments={
                "target": str(cwd / "notes.txt"),
                "diff": "--- a/notes.txt\n+++ b/notes.txt\n",
            },
        )

        assert enforcer.requires_confirmation(tool_call, permissions) is False

    def test_patch_checks_target_outside_cwd(self, tmp_path: Path) -> None:
        """patch requires confirmation for TRUSTED targets outside cwd."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        permissions = self._make_trusted_permissions(cwd)
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="patch",
            arguments={
                "target": str(outside / "notes.txt"),
                "diff": "--- a/notes.txt\n+++ b/notes.txt\n",
            },
        )

        assert enforcer.requires_confirmation(tool_call, permissions) is True


class TestEnforcerGetConfirmationContext:
    """Test the get_confirmation_context method."""

    def test_copy_file_context(self) -> None:
        """copy_file context returns destination for display and writes."""
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="copy_file",
            arguments={"source": "/src/file.txt", "destination": "/dst/file.txt"}
        )

        display_path, write_paths = enforcer.get_confirmation_context(tool_call)

        assert display_path == Path("/dst/file.txt")
        assert write_paths == [Path("/dst/file.txt")]

    def test_rename_context(self) -> None:
        """rename context returns destination for display and writes."""
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="rename",
            arguments={"source": "/old/name.txt", "destination": "/new/name.txt"}
        )

        display_path, write_paths = enforcer.get_confirmation_context(tool_call)

        assert display_path == Path("/new/name.txt")
        assert write_paths == [Path("/new/name.txt")]

    def test_write_file_context(self) -> None:
        """write_file context returns path for both display and writes."""
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="write_file",
            arguments={"path": "/some/file.txt", "content": "data"}
        )

        display_path, write_paths = enforcer.get_confirmation_context(tool_call)

        assert display_path == Path("/some/file.txt")
        assert write_paths == [Path("/some/file.txt")]

    def test_edit_lines_context(self) -> None:
        """edit_lines context returns path for both display and writes."""
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="edit_lines",
            arguments={
                "path": "/some/file.txt",
                "start_line": 10,
                "end_line": 12,
                "new_text": "replacement",
            },
        )

        display_path, write_paths = enforcer.get_confirmation_context(tool_call)

        assert display_path == Path("/some/file.txt")
        assert write_paths == [Path("/some/file.txt")]

    def test_patch_context(self) -> None:
        """patch context returns target for both display and writes."""
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="patch",
            arguments={
                "target": "/repo/src/file.py",
                "diff": "--- a/src/file.py\n+++ b/src/file.py\n",
            },
        )

        display_path, write_paths = enforcer.get_confirmation_context(tool_call)

        assert display_path == Path("/repo/src/file.py")
        assert write_paths == [Path("/repo/src/file.py")]


class TestAllowanceAppliedToWritePaths:
    """Test that allowances are applied to write paths, not source paths."""

    def test_copy_file_allowance_on_destination(self, tmp_path: Path) -> None:
        """Allowance for copy_file should be on destination, not source."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        source = cwd / "source.txt"
        dest = outside / "dest.txt"

        # Create permissions and add file allowance for destination
        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            cwd=cwd,
            allowed_paths=None,
        )
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            session_allowances=SessionAllowances(),
        )

        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="copy_file",
            arguments={"source": str(source), "destination": str(dest)}
        )

        # Initially requires confirmation
        assert enforcer.requires_confirmation(tool_call, permissions) is True

        # Add allowance for DESTINATION (not source)
        permissions.add_file_allowance(dest)

        # Now should NOT require confirmation
        assert enforcer.requires_confirmation(tool_call, permissions) is False

    def test_rename_allowance_on_destination(self, tmp_path: Path) -> None:
        """Allowance for rename should be on destination, not source."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        source = cwd / "old.txt"
        dest = outside / "new.txt"

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            cwd=cwd,
            allowed_paths=None,
        )
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            session_allowances=SessionAllowances(),
        )

        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="rename",
            arguments={"source": str(source), "destination": str(dest)}
        )

        # Initially requires confirmation
        assert enforcer.requires_confirmation(tool_call, permissions) is True

        # Add allowance for DESTINATION
        permissions.add_file_allowance(dest)

        # Now should NOT require confirmation
        assert enforcer.requires_confirmation(tool_call, permissions) is False

    def test_source_allowance_does_not_bypass(self, tmp_path: Path) -> None:
        """Adding allowance to SOURCE should NOT bypass confirmation."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        source = outside / "source.txt"  # Source outside cwd
        dest = tmp_path / "dest.txt"  # Dest also outside cwd

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            cwd=cwd,
            allowed_paths=None,
        )
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            session_allowances=SessionAllowances(),
        )

        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="copy_file",
            arguments={"source": str(source), "destination": str(dest)}
        )

        # Initially requires confirmation
        assert enforcer.requires_confirmation(tool_call, permissions) is True

        # Add allowance for SOURCE (wrong path!)
        permissions.add_file_allowance(source)

        # Should STILL require confirmation (allowance is on wrong path)
        assert enforcer.requires_confirmation(tool_call, permissions) is True


class TestReadOnlyToolsUnaffected:
    """Test that read-only tools are unaffected by the fix."""

    def test_read_file_no_confirmation(self) -> None:
        """read_file never requires confirmation (it's read-only)."""
        enforcer = PermissionEnforcer()

        tool_call = ToolCall(
            id="1",
            name="read_file",
            arguments={"path": "/some/sensitive/file.txt"}
        )

        # Read-only tools shouldn't trigger confirmation for write paths
        # (they have no write paths)
        _, write_paths = enforcer.get_confirmation_context(tool_call)
        assert write_paths == []

    def test_grep_no_write_paths(self) -> None:
        """grep has no write paths."""
        args = {"pattern": "test", "path": "/search/dir"}
        paths = extract_write_paths("grep", args)
        assert paths == []

    def test_list_directory_no_write_paths(self) -> None:
        """list_directory has no write paths."""
        args = {"path": "/some/dir"}
        paths = extract_write_paths("list_directory", args)
        assert paths == []
