"""Integration tests for file editing skills (edit_lines, edit_file, patch).

These tests verify:
1. edit_lines uses atomic writes (temp file + rename)
2. batch edit_file rolls back completely on failure
3. patch skill applies inline diffs correctly
4. patch skill loads patches from .diff files
5. patch skill respects allowed_paths permissions

These tests use real files in a temp directory and execute skills directly.
"""

import tempfile
from pathlib import Path

import pytest

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionLevel,
    PermissionPolicy,
)
from nexus3.skill.builtin.edit_file import edit_file_factory
from nexus3.skill.builtin.edit_lines import edit_lines_factory
from nexus3.skill.builtin.patch import patch_factory
from nexus3.skill.services import ServiceContainer


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def services(temp_dir: Path) -> ServiceContainer:
    """Create ServiceContainer with permissions for the temp directory."""
    permissions = AgentPermissions(
        base_preset="trusted",
        effective_policy=PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[temp_dir],
            cwd=temp_dir,
        ),
    )
    container = ServiceContainer()
    container.register("permissions", permissions)
    container.register("cwd", temp_dir)
    return container


@pytest.fixture
def restricted_services(temp_dir: Path) -> ServiceContainer:
    """Create ServiceContainer with SANDBOXED permissions for restricted path testing."""
    # Create a subdirectory that will be allowed
    allowed_subdir = temp_dir / "allowed"
    allowed_subdir.mkdir()

    permissions = AgentPermissions(
        base_preset="sandboxed",
        effective_policy=PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[allowed_subdir],
            cwd=allowed_subdir,
        ),
    )
    container = ServiceContainer()
    container.register("permissions", permissions)
    container.register("cwd", allowed_subdir)
    return container


class TestEditLinesAtomicWrite:
    """P5.1: Tests for edit_lines atomic write behavior."""

    @pytest.mark.asyncio
    async def test_edit_lines_atomic_write(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Verify edit_lines writes atomically (no partial file states).

        The atomic behavior is ensured by atomic_write_bytes (temp file + rename).
        This test confirms the skill uses it correctly by verifying the file
        is modified correctly and completely.
        """
        # Create a test file
        test_file = temp_dir / "test.py"
        original_content = """line 1
line 2
line 3
line 4
line 5
"""
        test_file.write_text(original_content)

        # Create the skill
        skill = edit_lines_factory(services)

        # Use edit_lines to modify line 3
        result = await skill.execute(
            path=str(test_file),
            start_line=3,
            new_content="REPLACED LINE 3"
        )

        # Verify success
        assert result.success, f"Expected success, got error: {result.error}"
        assert "Replaced line 3" in result.output

        # Verify the file was modified correctly
        new_content = test_file.read_text()
        assert "REPLACED LINE 3" in new_content
        assert "line 1" in new_content
        assert "line 2" in new_content
        assert "line 4" in new_content
        assert "line 5" in new_content
        # Original line 3 should be gone
        assert "line 3\n" not in new_content

    @pytest.mark.asyncio
    async def test_edit_lines_multi_line_replacement(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Verify edit_lines can replace multiple lines atomically."""
        test_file = temp_dir / "multi.py"
        original_content = """line 1
line 2
line 3
line 4
line 5
"""
        test_file.write_text(original_content)

        skill = edit_lines_factory(services)

        # Replace lines 2-4 with a single line
        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            end_line=4,
            new_content="REPLACED LINES 2-4"
        )

        assert result.success, f"Expected success, got error: {result.error}"
        assert "Replaced lines 2-4" in result.output

        new_content = test_file.read_text()
        assert "line 1" in new_content
        assert "REPLACED LINES 2-4" in new_content
        assert "line 5" in new_content
        # Original lines 2, 3, 4 should be gone
        assert "line 2\n" not in new_content
        assert "line 3\n" not in new_content
        assert "line 4\n" not in new_content

    @pytest.mark.asyncio
    async def test_edit_lines_preserves_line_endings(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Verify edit_lines preserves original line endings (CRLF)."""
        test_file = temp_dir / "crlf.txt"
        # Windows-style line endings
        original_content = "line 1\r\nline 2\r\nline 3\r\n"
        test_file.write_bytes(original_content.encode())

        skill = edit_lines_factory(services)

        result = await skill.execute(
            path=str(test_file),
            start_line=2,
            new_content="REPLACED"
        )

        assert result.success

        # Check line endings are preserved
        new_bytes = test_file.read_bytes()
        new_content = new_bytes.decode()
        # Should still have CRLF
        assert "\r\n" in new_content


class TestBatchEditAtomicRollback:
    """P5.2: Tests for batch edit_file atomic rollback on failure."""

    @pytest.mark.asyncio
    async def test_batch_edit_atomic_rollback(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Verify batch edits leave file unchanged on any failure.

        Creates a file with multiple targets and attempts a batch edit where
        the second edit would fail (string not found). The file should be
        completely unchanged after the failed batch.
        """
        test_file = temp_dir / "batch.py"
        original_content = """def foo():
    return "hello"

def bar():
    return "world"
"""
        test_file.write_text(original_content)

        skill = edit_file_factory(services)

        # Attempt batch edit where second edit will fail (string doesn't exist)
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": 'return "hello"', "new_string": 'return "goodbye"'},
                {"old_string": 'THIS_DOES_NOT_EXIST', "new_string": 'replacement'},
            ]
        )

        # Should fail
        assert not result.success
        assert "Batch edit failed" in result.error
        assert "not found" in result.error.lower()

        # File should be UNCHANGED - atomic rollback
        current_content = test_file.read_text()
        assert current_content == original_content
        # Specifically, the first edit should NOT have been applied
        assert 'return "hello"' in current_content
        assert 'return "goodbye"' not in current_content

    @pytest.mark.asyncio
    async def test_batch_edit_success(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Verify batch edits apply all changes when all edits succeed."""
        test_file = temp_dir / "batch_success.py"
        original_content = """def foo():
    return "hello"

def bar():
    return "world"
"""
        test_file.write_text(original_content)

        skill = edit_file_factory(services)

        # Batch edit with two valid edits
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": 'return "hello"', "new_string": 'return "goodbye"'},
                {"old_string": 'return "world"', "new_string": 'return "universe"'},
            ]
        )

        assert result.success, f"Expected success, got error: {result.error}"
        assert "Applied 2 edits" in result.output

        # Both changes should be applied
        new_content = test_file.read_text()
        assert 'return "goodbye"' in new_content
        assert 'return "universe"' in new_content
        # Original strings should be gone
        assert 'return "hello"' not in new_content
        assert 'return "world"' not in new_content

    @pytest.mark.asyncio
    async def test_batch_edit_ambiguous_string_fails(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Verify batch edit fails when a string appears multiple times without replace_all."""
        test_file = temp_dir / "ambiguous.py"
        original_content = """def foo():
    return "hello"

def bar():
    return "hello"
"""
        test_file.write_text(original_content)

        skill = edit_file_factory(services)

        # This should fail - "hello" appears twice
        result = await skill.execute(
            path=str(test_file),
            edits=[
                {"old_string": '"hello"', "new_string": '"goodbye"'},
            ]
        )

        assert not result.success
        assert "Batch edit failed" in result.error
        assert "2 times" in result.error

        # File should be unchanged
        assert test_file.read_text() == original_content


class TestPatchInlineDiffIntegration:
    """P5.3: Tests for patch skill with inline diff content."""

    @pytest.mark.asyncio
    async def test_patch_inline_diff_integration(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test full patch skill with inline diff content - adding imports."""
        # Create a Python file (note: exact whitespace matters for diff context)
        test_file = temp_dir / "module.py"
        original_content = "import os\n\ndef main():\n    print(\"Hello\")\n"
        test_file.write_text(original_content)

        skill = patch_factory(services)

        # Create a unified diff that adds an import
        # NOTE: In unified diff format, context lines have a leading space.
        # Blank context lines ALSO need a leading space (line 6 below).
        diff_content = (
            "--- a/module.py\n"
            "+++ b/module.py\n"
            "@@ -1,4 +1,5 @@\n"
            " import os\n"
            "+import sys\n"
            " \n"  # blank line in file needs leading space as context
            " def main():\n"
            "     print(\"Hello\")\n"
        )

        result = await skill.execute(
            target=str(test_file),
            diff=diff_content,
        )

        assert result.success, f"Expected success, got error: {result.error}"
        assert "Applied patch" in result.output

        # Verify imports added correctly
        new_content = test_file.read_text()
        assert "import os" in new_content
        assert "import sys" in new_content
        # Verify order
        os_pos = new_content.index("import os")
        sys_pos = new_content.index("import sys")
        assert sys_pos > os_pos, "import sys should come after import os"

    @pytest.mark.asyncio
    async def test_patch_inline_diff_removes_lines(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test patch skill can remove lines."""
        test_file = temp_dir / "remove.py"
        original_content = """def foo():
    # TODO: remove this comment
    return 42
"""
        test_file.write_text(original_content)

        skill = patch_factory(services)

        diff_content = """--- a/remove.py
+++ b/remove.py
@@ -1,4 +1,3 @@
 def foo():
-    # TODO: remove this comment
     return 42
"""

        result = await skill.execute(
            target=str(test_file),
            diff=diff_content,
        )

        assert result.success, f"Expected success, got error: {result.error}"

        new_content = test_file.read_text()
        assert "TODO" not in new_content
        assert "return 42" in new_content

    @pytest.mark.asyncio
    async def test_patch_dry_run(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test patch dry_run validates without applying changes."""
        test_file = temp_dir / "dryrun.py"
        original_content = """line 1
line 2
"""
        test_file.write_text(original_content)

        skill = patch_factory(services)

        diff_content = """--- a/dryrun.py
+++ b/dryrun.py
@@ -1,2 +1,3 @@
 line 1
+new line
 line 2
"""

        result = await skill.execute(
            target=str(test_file),
            diff=diff_content,
            dry_run=True,
        )

        assert result.success
        assert "Dry run" in result.output
        assert "no changes made" in result.output.lower()

        # File should be UNCHANGED
        assert test_file.read_text() == original_content


class TestPatchFromDiffFile:
    """P5.4: Tests for patch skill loading from .diff files."""

    @pytest.mark.asyncio
    async def test_patch_from_diff_file(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test patch skill loading from .diff file."""
        # Create target file
        target_file = temp_dir / "target.py"
        original_content = """def greet():
    return "Hello"
"""
        target_file.write_text(original_content)

        # Create .diff file
        diff_file = temp_dir / "changes.diff"
        diff_content = """--- a/target.py
+++ b/target.py
@@ -1,2 +1,3 @@
 def greet():
-    return "Hello"
+    name = "World"
+    return f"Hello, {name}!"
"""
        diff_file.write_text(diff_content)

        skill = patch_factory(services)

        # Apply patch using diff_file parameter
        result = await skill.execute(
            target=str(target_file),
            diff_file=str(diff_file),
        )

        assert result.success, f"Expected success, got error: {result.error}"

        # Verify changes
        new_content = target_file.read_text()
        assert 'name = "World"' in new_content
        assert 'return f"Hello, {name}!"' in new_content
        assert 'return "Hello"' not in new_content

    @pytest.mark.asyncio
    async def test_patch_diff_file_not_found(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test patch skill error when diff_file doesn't exist."""
        target_file = temp_dir / "target.py"
        target_file.write_text("content")

        skill = patch_factory(services)

        result = await skill.execute(
            target=str(target_file),
            diff_file=str(temp_dir / "nonexistent.diff"),
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_patch_cannot_use_both_diff_and_diff_file(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test patch skill rejects both diff and diff_file parameters."""
        target_file = temp_dir / "target.py"
        target_file.write_text("content")

        diff_file = temp_dir / "changes.diff"
        diff_file.write_text("--- a/target.py\n+++ b/target.py\n")

        skill = patch_factory(services)

        result = await skill.execute(
            target=str(target_file),
            diff="some inline diff",
            diff_file=str(diff_file),
        )

        assert not result.success
        assert "Cannot provide both" in result.error


class TestPatchPermissionEnforcement:
    """P5.5: Tests for patch skill respecting allowed_paths permissions."""

    @pytest.mark.asyncio
    async def test_patch_permission_enforcement(
        self, temp_dir: Path, restricted_services: ServiceContainer
    ) -> None:
        """Verify patch skill respects file permission boundaries.

        Uses a ServiceContainer with restricted paths (only 'allowed' subdir).
        Attempts to patch a file outside allowed_paths should fail.
        """
        # Get the allowed directory from services
        allowed_dir = restricted_services.get_cwd()

        # Create a file INSIDE allowed directory
        allowed_file = allowed_dir / "allowed.py"
        allowed_file.write_text("allowed content\n")

        # Create a file OUTSIDE allowed directory (in parent temp_dir)
        outside_file = temp_dir / "outside.py"
        outside_file.write_text("outside content\n")

        skill = patch_factory(restricted_services)

        diff_content = """--- a/outside.py
+++ b/outside.py
@@ -1 +1 @@
-outside content
+modified content
"""

        # Attempt to patch file outside allowed_paths
        result = await skill.execute(
            target=str(outside_file),
            diff=diff_content,
        )

        # Should fail with permission error
        assert not result.success
        # The error should indicate path restriction
        assert "outside" in result.error.lower() or "allowed" in result.error.lower()

        # File should be unchanged
        assert outside_file.read_text() == "outside content\n"

    @pytest.mark.asyncio
    async def test_patch_allowed_path_succeeds(
        self, temp_dir: Path, restricted_services: ServiceContainer
    ) -> None:
        """Verify patch skill allows operations within allowed_paths."""
        allowed_dir = restricted_services.get_cwd()

        # Create a file inside allowed directory
        allowed_file = allowed_dir / "allowed.py"
        allowed_file.write_text("original content\n")

        skill = patch_factory(restricted_services)

        diff_content = """--- a/allowed.py
+++ b/allowed.py
@@ -1 +1 @@
-original content
+modified content
"""

        result = await skill.execute(
            target=str(allowed_file),
            diff=diff_content,
        )

        assert result.success, f"Expected success, got error: {result.error}"
        assert allowed_file.read_text() == "modified content\n"

    @pytest.mark.asyncio
    async def test_patch_diff_file_also_restricted(
        self, temp_dir: Path, restricted_services: ServiceContainer
    ) -> None:
        """Verify patch skill also restricts reading diff files outside allowed_paths."""
        allowed_dir = restricted_services.get_cwd()

        # Target file inside allowed directory
        target_file = allowed_dir / "target.py"
        target_file.write_text("content\n")

        # Diff file OUTSIDE allowed directory
        outside_diff = temp_dir / "outside.diff"
        outside_diff.write_text("""--- a/target.py
+++ b/target.py
@@ -1 +1 @@
-content
+modified
""")

        skill = patch_factory(restricted_services)

        result = await skill.execute(
            target=str(target_file),
            diff_file=str(outside_diff),
        )

        # Should fail because diff_file is outside allowed paths
        assert not result.success
        # Target file should be unchanged
        assert target_file.read_text() == "content\n"


class TestEditFileSingleMode:
    """Additional tests for edit_file single-edit mode."""

    @pytest.mark.asyncio
    async def test_edit_file_single_replacement(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test basic single string replacement."""
        test_file = temp_dir / "single.py"
        test_file.write_text('greeting = "Hello"\n')

        skill = edit_file_factory(services)

        result = await skill.execute(
            path=str(test_file),
            old_string='"Hello"',
            new_string='"Goodbye"',
        )

        assert result.success
        assert "Replaced text" in result.output
        assert test_file.read_text() == 'greeting = "Goodbye"\n'

    @pytest.mark.asyncio
    async def test_edit_file_replace_all(
        self, temp_dir: Path, services: ServiceContainer
    ) -> None:
        """Test replace_all mode."""
        test_file = temp_dir / "replaceall.py"
        test_file.write_text('a = "x"\nb = "x"\nc = "x"\n')

        skill = edit_file_factory(services)

        result = await skill.execute(
            path=str(test_file),
            old_string='"x"',
            new_string='"y"',
            replace_all=True,
        )

        assert result.success
        assert "3 occurrence" in result.output
        assert test_file.read_text() == 'a = "y"\nb = "y"\nc = "y"\n'
