"""Tests for patch skill."""

import pytest

from nexus3.skill.builtin.patch import patch_factory
from nexus3.skill.services import ServiceContainer


class TestPatchSkill:
    """Tests for PatchSkill."""

    @pytest.fixture
    def services(self, tmp_path):
        """Create ServiceContainer with tmp_path as cwd."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        return services

    @pytest.fixture
    def skill(self, services):
        """Create patch skill instance."""
        return patch_factory(services)

    @pytest.fixture
    def test_file(self, tmp_path):
        """Create a test file with multiple lines."""
        content = """import os

def main():
    print("hello")
    return 0
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)
        return test_file


class TestInlineDiff(TestPatchSkill):
    """Tests for inline diff application."""

    @pytest.mark.asyncio
    async def test_patch_inline_diff(self, skill, test_file):
        """Test applying inline diff string.

        The test file contains:
        import os
        <blank line>
        def main():
            print("hello")
            return 0
        """
        # NOTE: In unified diff format, blank context lines must have a space prefix
        # That's why we use ' \n' for blank lines, not just '\n'
        diff = (
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,3 +1,4 @@\n"
            " import os\n"
            "+import sys\n"
            " \n"  # blank line needs space prefix
            " def main():\n"
        )
        result = await skill.execute(
            target=str(test_file),
            diff=diff,
        )

        assert result.success
        assert "1 hunk(s) applied" in result.output

        content = test_file.read_text()
        assert "import os\nimport sys" in content

    @pytest.mark.asyncio
    async def test_patch_inline_diff_remove_line(self, skill, tmp_path):
        """Test removing a line with inline diff."""
        test_file = tmp_path / "remove.py"
        test_file.write_text("line1\nline2\nline3\n")

        diff = """--- a/remove.py
+++ b/remove.py
@@ -1,3 +1,2 @@
 line1
-line2
 line3
"""
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        content = test_file.read_text()
        assert "line1\nline3\n" == content

    @pytest.mark.asyncio
    async def test_patch_multiple_hunks(self, skill, tmp_path):
        """Test applying multiple hunks in one diff.

        File content:
        # header
        <blank>
        def foo():
            pass
        <blank>
        def bar():
            pass
        """
        test_file = tmp_path / "multi.py"
        test_file.write_text("# header\n\ndef foo():\n    pass\n\ndef bar():\n    pass\n")

        # NOTE: blank context lines need space prefix in unified diff format
        diff = (
            "--- a/multi.py\n"
            "+++ b/multi.py\n"
            "@@ -1,2 +1,3 @@\n"
            " # header\n"
            "+# new comment\n"
            " \n"  # blank line needs space prefix
            "@@ -5,3 +6,4 @@\n"
            " \n"  # blank line needs space prefix
            " def bar():\n"
            "     pass\n"
            "+    return None\n"
        )
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        assert "2 hunk(s) applied" in result.output

        content = test_file.read_text()
        assert "# new comment" in content
        assert "return None" in content


class TestDiffFile(TestPatchSkill):
    """Tests for loading and applying .diff file."""

    @pytest.mark.asyncio
    async def test_patch_from_file(self, skill, tmp_path):
        """Test loading and applying .diff file."""
        test_file = tmp_path / "target.py"
        test_file.write_text("old content\n")

        diff_file = tmp_path / "changes.diff"
        diff_file.write_text("""--- a/target.py
+++ b/target.py
@@ -1 +1 @@
-old content
+new content
""")

        result = await skill.execute(
            target=str(test_file),
            diff_file=str(diff_file),
        )

        assert result.success
        assert test_file.read_text() == "new content\n"

    @pytest.mark.asyncio
    async def test_diff_file_not_found(self, skill, test_file, tmp_path):
        """Test error when diff file doesn't exist."""
        result = await skill.execute(
            target=str(test_file),
            diff_file=str(tmp_path / "nonexistent.diff"),
        )

        assert not result.success
        assert "not found" in result.error.lower()


class TestDryRun(TestPatchSkill):
    """Tests for dry_run mode."""

    @pytest.mark.asyncio
    async def test_patch_dry_run(self, skill, test_file):
        """Test validate without applying changes."""
        original_content = test_file.read_text()

        # Match actual file content (blank line between import and def main)
        # NOTE: blank context lines need space prefix in unified diff format
        diff = (
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,3 +1,4 @@\n"
            " import os\n"
            "+import sys\n"
            " \n"  # blank line needs space prefix
            " def main():\n"
        )
        result = await skill.execute(
            target=str(test_file),
            diff=diff,
            dry_run=True,
        )

        assert result.success
        assert "Dry run" in result.output
        assert "would apply" in result.output

        # File should be unchanged
        assert test_file.read_text() == original_content

    @pytest.mark.asyncio
    async def test_dry_run_with_invalid_patch(self, skill, test_file):
        """Test dry run reports errors for invalid patches."""
        diff = """--- a/test.py
+++ b/test.py
@@ -1,4 +1,5 @@
 import nonexistent
+import sys

 def main():
     print("hello")
"""
        result = await skill.execute(
            target=str(test_file),
            diff=diff,
            dry_run=True,
        )

        assert not result.success
        assert "Dry run" in result.error
        assert "would fail" in result.error


class TestParameterValidation(TestPatchSkill):
    """Tests for parameter validation."""

    @pytest.mark.asyncio
    async def test_patch_mutual_exclusion(self, skill, test_file):
        """Test error when both diff and diff_file provided."""
        result = await skill.execute(
            target=str(test_file),
            diff="some diff",
            diff_file="some/path.diff",
        )

        assert not result.success
        assert "Cannot provide both" in result.error

    @pytest.mark.asyncio
    async def test_patch_missing_diff(self, skill, test_file):
        """Test error when neither diff nor diff_file provided."""
        result = await skill.execute(target=str(test_file))

        assert not result.success
        assert "Must provide either" in result.error or "diff" in result.error

    @pytest.mark.asyncio
    async def test_patch_target_not_found(self, skill, tmp_path):
        """Test error when target file doesn't exist."""
        result = await skill.execute(
            target=str(tmp_path / "nonexistent.py"),
            diff="some diff",
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_patch_empty_target(self, skill):
        """Test error when target is empty."""
        result = await skill.execute(target="", diff="some diff")

        assert not result.success
        assert "No path provided" in result.error


class TestFuzzyMode(TestPatchSkill):
    """Tests for fuzzy matching mode."""

    @pytest.mark.asyncio
    async def test_patch_fuzzy_mode(self, skill, tmp_path):
        """Test applying with fuzzy matching."""
        # Create file with slightly different whitespace than diff expects
        test_file = tmp_path / "fuzzy.py"
        test_file.write_text("line1\nline2 \nline3\n")  # extra space on line2

        diff = """--- a/fuzzy.py
+++ b/fuzzy.py
@@ -1,3 +1,4 @@
 line1
 line2
+new line
 line3
"""
        result = await skill.execute(
            target=str(test_file),
            diff=diff,
            mode="fuzzy",
            fuzzy_threshold=0.8,
        )

        assert result.success
        content = test_file.read_text()
        assert "new line" in content

    @pytest.mark.asyncio
    async def test_patch_tolerant_mode(self, skill, tmp_path):
        """Test tolerant mode ignores trailing whitespace."""
        test_file = tmp_path / "tolerant.py"
        test_file.write_text("line1\nline2  \nline3\n")  # trailing spaces

        diff = """--- a/tolerant.py
+++ b/tolerant.py
@@ -1,3 +1,4 @@
 line1
 line2
+new line
 line3
"""
        result = await skill.execute(
            target=str(test_file),
            diff=diff,
            mode="tolerant",
        )

        assert result.success
        content = test_file.read_text()
        assert "new line" in content


class TestMultiFileDiff(TestPatchSkill):
    """Tests for multi-file diff handling."""

    @pytest.mark.asyncio
    async def test_multi_file_diff_applies_only_target(self, skill, tmp_path):
        """Test that multi-file diff only applies hunks for target file."""
        target = tmp_path / "target.py"
        target.write_text("old content\n")

        # Diff contains changes for multiple files
        diff = """--- a/other.py
+++ b/other.py
@@ -1 +1 @@
-other old
+other new
--- a/target.py
+++ b/target.py
@@ -1 +1 @@
-old content
+new content
"""
        result = await skill.execute(target=str(target), diff=diff)

        assert result.success
        assert "2 files" in result.output
        assert "only hunks for target.py" in result.output
        assert target.read_text() == "new content\n"

    @pytest.mark.asyncio
    async def test_multi_file_diff_target_not_in_diff(self, skill, tmp_path):
        """Test error when target file is not in multi-file diff."""
        target = tmp_path / "notfound.py"
        target.write_text("content\n")

        diff = """--- a/other.py
+++ b/other.py
@@ -1 +1 @@
-old
+new
"""
        result = await skill.execute(target=str(target), diff=diff)

        assert not result.success
        assert "No hunks found for target file" in result.error
        assert "notfound.py" in result.error


class TestLineEndingPreservation(TestPatchSkill):
    """Tests for line ending preservation."""

    @pytest.mark.asyncio
    async def test_preserves_crlf(self, skill, tmp_path):
        """Test that CRLF line endings are preserved."""
        test_file = tmp_path / "crlf.py"
        test_file.write_bytes(b"line1\r\nline2\r\n")

        diff = """--- a/crlf.py
+++ b/crlf.py
@@ -1,2 +1,3 @@
 line1
+new line
 line2
"""
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        content = test_file.read_bytes()
        assert b"\r\n" in content
        # Should have CRLF line endings
        assert content.count(b"\r\n") == 3

    @pytest.mark.asyncio
    async def test_preserves_lf(self, skill, tmp_path):
        """Test that LF line endings are preserved."""
        test_file = tmp_path / "lf.py"
        test_file.write_text("line1\nline2\n")

        diff = """--- a/lf.py
+++ b/lf.py
@@ -1,2 +1,3 @@
 line1
+new line
 line2
"""
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        content = test_file.read_bytes()
        # Should have only LF, no CRLF
        assert b"\r\n" not in content
        assert content.count(b"\n") == 3


class TestPatchValidation(TestPatchSkill):
    """Tests for patch validation and auto-fix."""

    @pytest.mark.asyncio
    async def test_context_mismatch_strict_mode(self, skill, tmp_path):
        """Test that strict mode fails on context mismatch."""
        test_file = tmp_path / "mismatch.py"
        test_file.write_text("actual line\n")

        diff = """--- a/mismatch.py
+++ b/mismatch.py
@@ -1 +1,2 @@
 expected line
+new line
"""
        result = await skill.execute(
            target=str(test_file),
            diff=diff,
            mode="strict",
        )

        assert not result.success
        assert "mismatch" in result.error.lower() or "failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_diff_content(self, skill, test_file):
        """Test error when diff content has no hunks."""
        result = await skill.execute(
            target=str(test_file),
            diff="not a valid diff",
        )

        assert not result.success
        assert "No patch hunks found" in result.error or "No hunks found" in result.error


class TestEdgeCases(TestPatchSkill):
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_single_line_file(self, skill, tmp_path):
        """Test patching a single-line file."""
        test_file = tmp_path / "single.txt"
        test_file.write_text("old\n")

        diff = """--- a/single.txt
+++ b/single.txt
@@ -1 +1 @@
-old
+new
"""
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        assert test_file.read_text() == "new\n"

    @pytest.mark.asyncio
    async def test_add_to_end_of_file(self, skill, tmp_path):
        """Test adding lines at the end of file."""
        test_file = tmp_path / "append.txt"
        test_file.write_text("line1\nline2\n")

        diff = """--- a/append.txt
+++ b/append.txt
@@ -1,2 +1,4 @@
 line1
 line2
+line3
+line4
"""
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        content = test_file.read_text()
        assert "line3" in content
        assert "line4" in content

    @pytest.mark.asyncio
    async def test_git_diff_format(self, skill, tmp_path):
        """Test parsing git diff --git format."""
        test_file = tmp_path / "gitformat.py"
        test_file.write_text("old\n")

        diff = """diff --git a/gitformat.py b/gitformat.py
index abc123..def456 100644
--- a/gitformat.py
+++ b/gitformat.py
@@ -1 +1 @@
-old
+new
"""
        result = await skill.execute(target=str(test_file), diff=diff)

        assert result.success
        assert test_file.read_text() == "new\n"
