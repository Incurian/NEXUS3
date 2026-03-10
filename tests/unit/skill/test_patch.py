"""Tests for patch skill."""

from pathlib import Path

import pytest

from nexus3.skill.builtin.patch import patch_factory
from nexus3.skill.services import ServiceContainer

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "arch_baseline"


class TestPatchSkill:
    """Tests for PatchSkill."""

    @pytest.fixture
    def services(self, tmp_path):
        """Create ServiceContainer with tmp_path as cwd."""
        services = ServiceContainer()
        services.set_cwd(str(tmp_path))
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
    async def test_patch_inline_diff_accepts_path_alias(self, skill, tmp_path):
        """patch accepts path= for consistency with other file tools."""
        test_file = tmp_path / "alias.py"
        test_file.write_text("old content\n")

        diff = """--- a/alias.py
+++ b/alias.py
@@ -1 +1 @@
-old content
+new content
"""
        result = await skill.execute(path=str(test_file), diff=diff)

        assert result.success
        assert test_file.read_text() == "new content\n"

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
    async def test_patch_missing_diff_with_path_alias(self, skill, test_file):
        """Missing diff validation should work with path= too."""
        result = await skill.execute(path=str(test_file))

        assert not result.success
        assert "Must provide either" in result.error or "diff" in result.error

    @pytest.mark.asyncio
    async def test_patch_target_not_found(self, skill, tmp_path):
        """Test error when target file doesn't exist."""
        result = await skill.execute(
            target=str(tmp_path / "nonexistent.py"),
            diff="""--- a/nonexistent.py
+++ b/nonexistent.py
@@ -1 +1 @@
-old
+new
""",
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_patch_new_file_diff_creates_missing_target(self, skill, tmp_path):
        """New-file diffs can create a missing target file."""
        target_file = tmp_path / "created.py"

        diff = """--- /dev/null
+++ b/created.py
@@ -0,0 +1,2 @@
+def created():
+    return 1
"""
        result = await skill.execute(target=str(target_file), diff=diff)

        assert result.success
        assert target_file.read_text() == "def created():\n    return 1\n"

    @pytest.mark.asyncio
    async def test_patch_empty_target(self, skill):
        """Test error when target is empty."""
        result = await skill.execute(target="", diff="some diff")

        assert not result.success
        assert "No path provided" in result.error

    @pytest.mark.asyncio
    async def test_patch_path_and_target_mismatch_fails(self, skill, tmp_path):
        """path and target must agree when both are provided."""
        first = tmp_path / "first.py"
        second = tmp_path / "second.py"
        first.write_text("old\n")
        second.write_text("old\n")

        diff = """--- a/first.py
+++ b/first.py
@@ -1 +1 @@
-old
+new
"""
        result = await skill.execute(
            path=str(first),
            target=str(second),
            diff=diff,
        )

        assert not result.success
        assert "Cannot provide both 'path' and 'target' with different values." == result.error


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
    async def test_multi_file_diff_prefers_exact_path_match(self, skill, tmp_path):
        """Test exact-path match wins when basename matches multiple diff entries."""
        target = tmp_path / "pkg" / "nested" / "shared.py"
        target.parent.mkdir(parents=True)
        target.write_text("shared old\n")

        diff = f"""--- a/other/shared.py
+++ b/other/shared.py
@@ -1 +1 @@
-shared old
+wrong match
--- {target}
+++ {target}
@@ -1 +1 @@
-shared old
+exact match
"""
        result = await skill.execute(target=str(target), diff=diff)

        assert result.success
        assert target.read_text() == "exact match\n"

    @pytest.mark.asyncio
    async def test_multi_file_diff_ambiguous_basename_fails_closed(self, skill, tmp_path):
        """Test ambiguity fails closed when basename matches multiple entries."""
        target = tmp_path / "workspace" / "shared.py"
        target.parent.mkdir(parents=True)
        target.write_text("shared old\n")

        diff = """--- a/pkg_a/shared.py
+++ b/pkg_a/shared.py
@@ -1 +1 @@
-shared old
+pkg a update
--- a/pkg_b/shared.py
+++ b/pkg_b/shared.py
@@ -1 +1 @@
-shared old
+pkg b update
"""
        result = await skill.execute(target=str(target), diff=diff)

        assert not result.success
        assert "ambig" in result.error.lower()
        assert "shared.py" in result.error
        assert target.read_text() == "shared old\n"

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


class TestFidelityModeMigration(TestPatchSkill):
    """Migration tests for fidelity_mode wiring."""

    @pytest.mark.asyncio
    async def test_fidelity_mode_byte_strict_preserves_missing_trailing_newline(
        self, skill, tmp_path
    ):
        """byte_strict mode must honor explicit no-final-newline marker semantics."""
        target_file = tmp_path / "target.txt"
        target_file.write_bytes(b"alpha\nbeta")
        diff_content = (_FIXTURE_DIR / "patch_noeol_marker_update.diff").read_text(
            encoding="utf-8"
        )

        result = await skill.execute(
            target=str(target_file),
            diff=diff_content,
            fidelity_mode="byte_strict",
        )

        assert result.success
        assert target_file.read_bytes() == b"alpha\nBETA"
        assert not target_file.read_bytes().endswith(b"\n")

    @pytest.mark.asyncio
    async def test_fidelity_mode_invalid_value_returns_clear_error(self, skill, tmp_path):
        """Invalid fidelity mode should fail with actionable parameter guidance."""
        target_file = tmp_path / "target.txt"
        target_file.write_bytes(b"alpha\nbeta")
        diff_content = (_FIXTURE_DIR / "patch_noeol_marker_update.diff").read_text(
            encoding="utf-8"
        )

        result = await skill.execute(
            target=str(target_file),
            diff=diff_content,
            fidelity_mode="not_a_mode",
        )

        assert not result.success
        assert "fidelity_mode" in result.error
        assert "byte_strict" in result.error

    @pytest.mark.asyncio
    async def test_fidelity_mode_default_is_byte_strict(self, skill, tmp_path):
        """Default path should use byte_strict fidelity semantics."""
        target_file = tmp_path / "target.txt"
        target_file.write_bytes(b"alpha\r\nbeta\ngamma\r\n")
        diff_content = (_FIXTURE_DIR / "patch_mixed_newline_update.diff").read_text(
            encoding="utf-8"
        )

        await skill.execute(target=str(target_file), diff=diff_content)

        assert target_file.read_bytes() == b"alpha\r\nBETA\ngamma\r\n"

    @pytest.mark.asyncio
    async def test_fidelity_mode_explicit_legacy_is_rejected(self, skill, tmp_path):
        """Legacy mode is retired and must fail fast with clear guidance."""
        target_file = tmp_path / "target.txt"
        target_file.write_bytes(b"alpha\r\nbeta\ngamma\r\n")
        diff_content = (_FIXTURE_DIR / "patch_mixed_newline_update.diff").read_text(
            encoding="utf-8"
        )

        result = await skill.execute(
            target=str(target_file),
            diff=diff_content,
            fidelity_mode="legacy",
        )

        assert not result.success
        assert "no longer supported" in result.error
        assert "byte_strict" in result.error
        assert target_file.read_bytes() == b"alpha\r\nbeta\ngamma\r\n"


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
