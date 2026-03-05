"""Unit tests for nexus3.patch.parser module."""

from nexus3.patch import (
    parse_unified_diff,
    parse_unified_diff_v2,
    project_patch_files_v2_to_v1,
)
from nexus3.patch.types import Hunk, PatchFile


class TestParseUnifiedDiff:
    """Tests for parse_unified_diff function."""

    def test_parse_simple_hunk(self) -> None:
        """Test parsing a single hunk with add/remove."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1,4 +1,4 @@
 line1
-old line
+new line
 line3
 line4
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        assert pf.old_path == "file.py"
        assert pf.new_path == "file.py"
        assert len(pf.hunks) == 1

        hunk = pf.hunks[0]
        assert hunk.old_start == 1
        assert hunk.old_count == 4
        assert hunk.new_start == 1
        assert hunk.new_count == 4

        # Check line parsing
        assert len(hunk.lines) == 5
        assert hunk.lines[0] == (" ", "line1")
        assert hunk.lines[1] == ("-", "old line")
        assert hunk.lines[2] == ("+", "new line")
        assert hunk.lines[3] == (" ", "line3")
        assert hunk.lines[4] == (" ", "line4")

    def test_parse_multiple_hunks(self) -> None:
        """Test parsing multiple hunks in the same file."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 line1
+added at top
 line2
 line3
@@ -10,3 +11,2 @@
 line10
-removed
 line11
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        assert len(pf.hunks) == 2

        # First hunk - addition
        hunk1 = pf.hunks[0]
        assert hunk1.old_start == 1
        assert hunk1.old_count == 3
        assert hunk1.new_start == 1
        assert hunk1.new_count == 4
        assert hunk1.count_additions() == 1
        assert hunk1.count_removals() == 0
        assert hunk1.count_context() == 3

        # Second hunk - removal
        hunk2 = pf.hunks[1]
        assert hunk2.old_start == 10
        assert hunk2.old_count == 3
        assert hunk2.new_start == 11
        assert hunk2.new_count == 2
        assert hunk2.count_additions() == 0
        assert hunk2.count_removals() == 1
        assert hunk2.count_context() == 2

    def test_parse_git_format(self) -> None:
        """Test parsing git extended format with 'diff --git a/...' header."""
        diff_text = """\
diff --git a/src/module.py b/src/module.py
index abc1234..def5678 100644
--- a/src/module.py
+++ b/src/module.py
@@ -5,3 +5,4 @@ def function():
     pass
+    # new comment
     return None
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        assert pf.old_path == "src/module.py"
        assert pf.new_path == "src/module.py"
        assert len(pf.hunks) == 1

        hunk = pf.hunks[0]
        assert hunk.old_start == 5
        assert hunk.old_count == 3
        assert hunk.new_start == 5
        assert hunk.new_count == 4
        assert hunk.context == "def function():"

    def test_parse_context_only(self) -> None:
        """Test parsing a hunk with only context lines (no changes)."""
        # This is unusual but technically valid diff format
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line1
 line2
 line3
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        # A hunk with only context and no changes is unusual but parseable
        assert len(pf.hunks) == 1
        hunk = pf.hunks[0]
        assert hunk.count_context() == 3
        assert hunk.count_additions() == 0
        assert hunk.count_removals() == 0

    def test_malformed_header(self) -> None:
        """Test graceful handling of malformed @@ header line."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ invalid header @@
 some content
"""
        # Should not crash, may return empty or skip the malformed hunk
        files = parse_unified_diff(diff_text)
        # Either no files (couldn't parse) or file with no hunks
        if files:
            assert len(files[0].hunks) == 0

    def test_no_newline_at_eof(self) -> None:
        """Test handling of '\\ No newline at end of file' marker."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1,2 +1,2 @@
 line1
-old last line
\\ No newline at end of file
+new last line
\\ No newline at end of file
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        assert len(pf.hunks) == 1

        hunk = pf.hunks[0]
        # The marker should be skipped, only actual diff lines counted
        assert len(hunk.lines) == 3
        assert hunk.lines[0] == (" ", "line1")
        assert hunk.lines[1] == ("-", "old last line")
        assert hunk.lines[2] == ("+", "new last line")

    def test_bare_empty_line_treated_as_context(self) -> None:
        """Test that bare empty lines in hunk are treated as blank context lines.

        LLMs often forget the space prefix for blank context lines.
        A bare empty line should be auto-fixed to context, not skipped.
        """
        # Note: The empty line between +new and "next" has no space prefix
        # (LLM mistake). Parser should treat it as blank context.
        diff_text = "--- a/file.py\n+++ b/file.py\n@@ -1,4 +1,4 @@\n line1\n-old\n+new\n\n next\n"
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        hunk = files[0].hunks[0]
        # Should have 5 lines: context, removal, addition, blank context, context
        assert len(hunk.lines) == 5
        assert hunk.lines[0] == (" ", "line1")
        assert hunk.lines[1] == ("-", "old")
        assert hunk.lines[2] == ("+", "new")
        assert hunk.lines[3] == (" ", "")  # Bare empty line -> blank context
        assert hunk.lines[4] == (" ", "next")

    def test_parse_multiple_files(self) -> None:
        """Test parsing diff with multiple files."""
        diff_text = """\
--- a/file1.py
+++ b/file1.py
@@ -1,2 +1,2 @@
 line1
-old
+new
--- a/file2.py
+++ b/file2.py
@@ -1 +1,2 @@
 existing
+added
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 2
        assert files[0].path == "file1.py"
        assert files[1].path == "file2.py"
        assert len(files[0].hunks) == 1
        assert len(files[1].hunks) == 1

    def test_parse_new_file(self) -> None:
        """Test parsing diff for a new file (old_path is /dev/null)."""
        diff_text = """\
--- /dev/null
+++ b/newfile.py
@@ -0,0 +1,3 @@
+line1
+line2
+line3
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        assert pf.is_new_file is True
        assert pf.is_deleted is False
        assert pf.path == "newfile.py"
        assert len(pf.hunks) == 1

        hunk = pf.hunks[0]
        assert hunk.old_start == 0
        assert hunk.old_count == 0
        assert hunk.new_start == 1
        assert hunk.new_count == 3
        assert hunk.count_additions() == 3

    def test_parse_deleted_file(self) -> None:
        """Test parsing diff for a deleted file (new_path is /dev/null)."""
        diff_text = """\
--- a/oldfile.py
+++ /dev/null
@@ -1,3 +0,0 @@
-line1
-line2
-line3
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        pf = files[0]
        assert pf.is_new_file is False
        assert pf.is_deleted is True
        assert pf.path == "oldfile.py"
        assert len(pf.hunks) == 1

        hunk = pf.hunks[0]
        assert hunk.count_removals() == 3
        assert hunk.count_additions() == 0

    def test_parse_empty_input(self) -> None:
        """Test parsing empty or whitespace-only input."""
        assert parse_unified_diff("") == []
        assert parse_unified_diff("   ") == []
        assert parse_unified_diff("\n\n\n") == []

    def test_parse_count_defaults_to_one(self) -> None:
        """Test that omitted count defaults to 1 in hunk header."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -5 +5 @@
-old
+new
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 1
        hunk = files[0].hunks[0]
        # When count is omitted, it defaults to 1
        assert hunk.old_count == 1
        assert hunk.new_count == 1

    def test_parse_git_multiple_files(self) -> None:
        """Test parsing git format diff with multiple files."""
        diff_text = """\
diff --git a/src/a.py b/src/a.py
index 123..456 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,3 @@
 line1
+added
 line2
diff --git a/src/b.py b/src/b.py
index 789..012 100644
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-old
+new
"""
        files = parse_unified_diff(diff_text)

        assert len(files) == 2
        assert files[0].path == "src/a.py"
        assert files[1].path == "src/b.py"


class TestParseUnifiedDiffV2:
    """Tests for parse_unified_diff_v2 function."""

    def test_v2_projects_to_legacy_parity(self) -> None:
        """Projected AST-v2 output should match legacy parser output."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1,4 +1,4 @@
 line1
-old line
+new line
 line3
 line4
"""
        legacy_files = parse_unified_diff(diff_text)
        v2_files = parse_unified_diff_v2(diff_text)

        assert project_patch_files_v2_to_v1(v2_files) == legacy_files

    def test_v2_preserves_raw_bytes_and_newline_metadata(self) -> None:
        """AST-v2 should keep per-line raw bytes and newline token details."""
        diff_text = (
            "--- a/file.py\r\n"
            "+++ b/file.py\r\n"
            "@@ -1 +1 @@\r\n"
            "-old\r\n"
            "+new"
        )
        files = parse_unified_diff_v2(diff_text)

        assert len(files) == 1
        patch_file = files[0]
        assert patch_file.old_header_line is not None
        assert patch_file.new_header_line is not None
        assert patch_file.old_header_line.raw_bytes == b"--- a/file.py"
        assert patch_file.old_header_line.newline == "\r\n"
        assert patch_file.new_header_line.newline == "\r\n"

        hunk = patch_file.hunks[0]
        assert hunk.header_line is not None
        assert hunk.header_line.newline == "\r\n"
        assert hunk.lines[0].raw_line.raw_bytes == b"-old"
        assert hunk.lines[0].raw_content_bytes == b"old"
        assert hunk.lines[0].raw_line.newline == "\r\n"
        assert hunk.lines[1].raw_line.raw_bytes == b"+new"
        assert hunk.lines[1].raw_content_bytes == b"new"
        assert hunk.lines[1].raw_line.newline == ""
        assert hunk.lines[1].raw_line.has_newline is False

    def test_v2_tracks_no_newline_markers(self) -> None:
        """AST-v2 should track the no-newline marker on the preceding hunk line."""
        diff_text = """\
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
-old
\\ No newline at end of file
+new
\\ No newline at end of file
"""
        files = parse_unified_diff_v2(diff_text)

        assert len(files) == 1
        hunk = files[0].hunks[0]
        assert hunk.lines[0].no_newline_at_eof is True
        assert hunk.lines[1].no_newline_at_eof is True


class TestHunkMethods:
    """Tests for Hunk helper methods."""

    def test_compute_counts(self) -> None:
        """Test compute_counts returns correct values from lines."""
        hunk = Hunk(
            old_start=1,
            old_count=0,  # Intentionally wrong
            new_start=1,
            new_count=0,  # Intentionally wrong
            lines=[
                (" ", "context1"),
                ("-", "removed"),
                ("+", "added1"),
                ("+", "added2"),
                (" ", "context2"),
            ],
        )

        old_count, new_count = hunk.compute_counts()
        # old_count = context (2) + removals (1) = 3
        assert old_count == 3
        # new_count = context (2) + additions (2) = 4
        assert new_count == 4

    def test_count_methods(self) -> None:
        """Test individual count methods."""
        hunk = Hunk(
            old_start=1,
            old_count=5,
            new_start=1,
            new_count=6,
            lines=[
                (" ", "ctx1"),
                (" ", "ctx2"),
                ("-", "rm1"),
                ("-", "rm2"),
                ("+", "add1"),
                ("+", "add2"),
                ("+", "add3"),
            ],
        )

        assert hunk.count_context() == 2
        assert hunk.count_removals() == 2
        assert hunk.count_additions() == 3


class TestPatchFileMethods:
    """Tests for PatchFile helper methods."""

    def test_path_property_normal(self) -> None:
        """Test path property returns new_path for normal edits."""
        pf = PatchFile(old_path="old.py", new_path="new.py")
        assert pf.path == "new.py"

    def test_path_property_deleted(self) -> None:
        """Test path property returns old_path for deletions."""
        pf = PatchFile(old_path="deleted.py", new_path="deleted.py", is_deleted=True)
        assert pf.path == "deleted.py"


class TestPatchSetMethods:
    """Tests for PatchSet helper methods."""

    def test_get_file(self) -> None:
        """Test getting a specific file from patch set."""
        from nexus3.patch.types import PatchSet

        ps = PatchSet(
            files=[
                PatchFile(old_path="a.py", new_path="a.py"),
                PatchFile(old_path="b.py", new_path="b.py"),
            ]
        )

        patch_file = ps.get_file("a.py")
        assert patch_file is not None
        assert patch_file.path == "a.py"
        assert ps.get_file("nonexistent.py") is None

    def test_file_paths(self) -> None:
        """Test getting all file paths from patch set."""
        from nexus3.patch.types import PatchSet

        ps = PatchSet(
            files=[
                PatchFile(old_path="a.py", new_path="a.py"),
                PatchFile(old_path="b.py", new_path="b.py"),
            ]
        )

        paths = ps.file_paths()
        assert paths == ["a.py", "b.py"]
