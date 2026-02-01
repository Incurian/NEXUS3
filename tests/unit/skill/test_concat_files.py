"""Tests for concat_files skill."""

import pytest
from pathlib import Path

from nexus3.skill.builtin.concat_files import (
    concat_files_factory,
    DEFAULT_EXCLUDES,
    EXT_TO_LANG,
)
from nexus3.skill.services import ServiceContainer


class TestConcatFilesSkill:
    """Base test class for ConcatFilesSkill."""

    @pytest.fixture
    def services(self, tmp_path):
        """Create ServiceContainer with tmp_path as cwd."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        return services

    @pytest.fixture
    def skill(self, services):
        """Create concat_files skill instance."""
        return concat_files_factory(services)


class TestBasicFunctionality(TestConcatFilesSkill):
    """Tests for basic skill functionality."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_stats(self, skill, tmp_path):
        """Test that dry_run returns file statistics."""
        # Create test files
        (tmp_path / "file1.py").write_text("line1\nline2\nline3\n")
        (tmp_path / "file2.py").write_text("a = 1\nb = 2\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "Dry Run Results" in result.output
        assert "Files found:" in result.output
        assert "2" in result.output  # 2 files
        assert "file1.py" in result.output
        assert "file2.py" in result.output
        assert "Estimated output:" in result.output
        assert "Tokens (est):" in result.output

    @pytest.mark.asyncio
    async def test_no_matching_files(self, skill, tmp_path):
        """Test behavior when no files match extensions."""
        # Create a file with different extension
        (tmp_path / "file.txt").write_text("content\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "No files with extensions" in result.output

    @pytest.mark.asyncio
    async def test_binary_files_skipped(self, skill, tmp_path):
        """Test that binary files are detected and skipped."""
        # Create a text file
        (tmp_path / "text.py").write_text("print('hello')\n")
        # Create a binary file with null bytes
        (tmp_path / "binary.py").write_bytes(b"import os\n\x00\x01\x02binary data")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "Binary (skipped): 1" in result.output
        assert "text.py" in result.output
        # binary.py should not be in the files list

    @pytest.mark.asyncio
    async def test_multiple_extensions(self, skill, tmp_path):
        """Test searching for multiple file extensions."""
        (tmp_path / "code.py").write_text("def foo(): pass\n")
        (tmp_path / "script.ts").write_text("const x = 1;\n")
        (tmp_path / "readme.md").write_text("# Title\n")

        result = await skill.execute(
            extensions=["py", "ts"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "code.py" in result.output
        assert "script.ts" in result.output
        assert "readme.md" not in result.output

    @pytest.mark.asyncio
    async def test_actual_concatenation(self, skill, tmp_path):
        """Test actual file concatenation (not dry run)."""
        (tmp_path / "a.py").write_text("def a(): pass\n")
        (tmp_path / "b.py").write_text("def b(): pass\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=False,
        )

        assert result.success
        assert "Concatenation Complete" in result.output
        assert "Files written:" in result.output

        # Find the output file
        output_files = list(tmp_path.glob("*-concat.txt"))
        assert len(output_files) == 1

        content = output_files[0].read_text()
        assert "def a():" in content
        assert "def b():" in content


class TestParameterValidation(TestConcatFilesSkill):
    """Tests for parameter validation."""

    @pytest.mark.asyncio
    async def test_empty_extensions_list_error(self, skill, tmp_path):
        """Test error when extensions list is empty."""
        result = await skill.execute(
            extensions=[],
            path=str(tmp_path),
        )

        assert not result.success
        assert "No extensions provided" in result.error

    @pytest.mark.asyncio
    async def test_no_extensions_provided_error(self, skill, tmp_path):
        """Test error when extensions parameter is None."""
        result = await skill.execute(
            extensions=None,
            path=str(tmp_path),
        )

        assert not result.success
        # Could be either validation error or explicit check
        assert "extensions" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_path_error(self, skill, tmp_path):
        """Test error when path doesn't exist."""
        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path / "nonexistent"),
        )

        assert not result.success
        assert "not found" in result.error.lower() or "Directory not found" in result.error

    @pytest.mark.asyncio
    async def test_path_is_file_not_directory(self, skill, tmp_path):
        """Test error when path is a file, not a directory."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(test_file),
        )

        assert not result.success
        assert "Not a directory" in result.error


class TestSorting(TestConcatFilesSkill):
    """Tests for file sorting."""

    @pytest.mark.asyncio
    async def test_alpha_sorting(self, skill, tmp_path):
        """Test alphabetical sorting."""
        (tmp_path / "zebra.py").write_text("z = 1\n")
        (tmp_path / "apple.py").write_text("a = 1\n")
        (tmp_path / "mango.py").write_text("m = 1\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            sort="alpha",
            dry_run=True,
        )

        assert result.success
        # Files should appear in alphabetical order in output
        apple_pos = result.output.find("apple.py")
        mango_pos = result.output.find("mango.py")
        zebra_pos = result.output.find("zebra.py")

        assert apple_pos < mango_pos < zebra_pos

    @pytest.mark.asyncio
    async def test_mtime_sorting(self, skill, tmp_path):
        """Test modification time sorting (most recent first)."""
        import time

        # Create files with different mtimes
        (tmp_path / "old.py").write_text("old = 1\n")
        time.sleep(0.1)
        (tmp_path / "mid.py").write_text("mid = 1\n")
        time.sleep(0.1)
        (tmp_path / "new.py").write_text("new = 1\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            sort="mtime",
            dry_run=True,
        )

        assert result.success
        # Most recent first
        new_pos = result.output.find("new.py")
        mid_pos = result.output.find("mid.py")
        old_pos = result.output.find("old.py")

        assert new_pos < mid_pos < old_pos

    @pytest.mark.asyncio
    async def test_size_sorting(self, skill, tmp_path):
        """Test size sorting (largest first)."""
        (tmp_path / "small.py").write_text("x = 1\n")
        (tmp_path / "medium.py").write_text("x = 1\n" * 10)
        (tmp_path / "large.py").write_text("x = 1\n" * 100)

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            sort="size",
            dry_run=True,
        )

        assert result.success
        # Largest first
        large_pos = result.output.find("large.py")
        medium_pos = result.output.find("medium.py")
        small_pos = result.output.find("small.py")

        assert large_pos < medium_pos < small_pos


class TestOutputFormats(TestConcatFilesSkill):
    """Tests for output format generation."""

    @pytest.mark.asyncio
    async def test_plain_format(self, skill, tmp_path):
        """Test plain text format output structure."""
        (tmp_path / "test.py").write_text("def hello(): pass\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="plain",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.txt"))[0]
        content = output_file.read_text()

        # Plain format has comment headers
        assert "# Concatenated files" in content
        assert "# File:" in content
        assert "# Lines:" in content
        assert "====" in content

    @pytest.mark.asyncio
    async def test_markdown_format(self, skill, tmp_path):
        """Test markdown format has code fences."""
        (tmp_path / "test.py").write_text("def hello(): pass\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="markdown",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.md"))[0]
        content = output_file.read_text()

        # Markdown format has code fences with language
        assert "# Concatenated Files" in content
        assert "```python" in content
        assert "```" in content
        assert "def hello():" in content

    @pytest.mark.asyncio
    async def test_xml_format(self, skill, tmp_path):
        """Test XML format has proper structure."""
        (tmp_path / "test.py").write_text("def hello(): pass\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="xml",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.xml"))[0]
        content = output_file.read_text()

        # XML format has proper elements
        assert '<?xml version="1.0"' in content
        assert "<concatenated_files>" in content
        assert "</concatenated_files>" in content
        assert "<file " in content
        assert 'path="' in content
        assert "<![CDATA[" in content

    @pytest.mark.asyncio
    async def test_markdown_language_detection(self, skill, tmp_path):
        """Test markdown format detects correct language for various extensions."""
        (tmp_path / "code.ts").write_text("const x: number = 1;\n")

        result = await skill.execute(
            extensions=["ts"],
            path=str(tmp_path),
            format="markdown",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.md"))[0]
        content = output_file.read_text()

        # TypeScript should be detected
        assert "```typescript" in content


class TestLineLimits(TestConcatFilesSkill):
    """Tests for line limiting functionality."""

    @pytest.mark.asyncio
    async def test_per_file_line_limit(self, skill, tmp_path):
        """Test per-file line limit truncates long files."""
        # Create a file with many lines
        lines = "\n".join([f"line{i}" for i in range(100)])
        (tmp_path / "long.py").write_text(lines + "\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            lines=10,  # Limit to 10 lines per file
            dry_run=True,
        )

        assert result.success
        # Should show truncation info
        assert "truncated to 10" in result.output

    @pytest.mark.asyncio
    async def test_max_total_line_limit(self, skill, tmp_path):
        """Test max_total limits total lines across all files."""
        # Create multiple files
        for i in range(5):
            content = "\n".join([f"file{i}_line{j}" for j in range(20)])
            (tmp_path / f"file{i}.py").write_text(content + "\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            max_total=30,  # Only 30 total lines
            sort="alpha",  # Ensure consistent order
            dry_run=True,
        )

        assert result.success
        # Total lines should be limited
        assert "30" in result.output

    @pytest.mark.asyncio
    async def test_line_limit_in_actual_output(self, skill, tmp_path):
        """Test that line limit is applied in actual concatenation."""
        lines = "\n".join([f"line{i}" for i in range(50)])
        (tmp_path / "test.py").write_text(lines + "\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            lines=5,
            format="plain",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.txt"))[0]
        content = output_file.read_text()

        # Should only have first 5 lines of the file
        assert "line0" in content
        assert "line4" in content
        # And a truncation indicator
        assert "more lines" in content


class TestExclusions(TestConcatFilesSkill):
    """Tests for file exclusion patterns."""

    @pytest.mark.asyncio
    async def test_default_excludes_node_modules(self, skill, tmp_path):
        """Test that node_modules is excluded by default."""
        # Create files in node_modules
        node_dir = tmp_path / "node_modules" / "pkg"
        node_dir.mkdir(parents=True)
        (node_dir / "index.js").write_text("module.exports = {};\n")

        # Create a file outside node_modules
        (tmp_path / "app.js").write_text("const x = 1;\n")

        result = await skill.execute(
            extensions=["js"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "app.js" in result.output
        assert "node_modules" not in result.output or "index.js" not in result.output.split("node_modules")[-1]

    @pytest.mark.asyncio
    async def test_default_excludes_git(self, skill, tmp_path):
        """Test that .git directory is excluded by default."""
        git_dir = tmp_path / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (git_dir / "pack.py").write_text("# git internal\n")

        (tmp_path / "main.py").write_text("print('hello')\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "main.py" in result.output
        # .git files should not appear
        assert "pack.py" not in result.output

    @pytest.mark.asyncio
    async def test_default_excludes_pycache(self, skill, tmp_path):
        """Test that __pycache__ is excluded by default."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "module.cpython-310.pyc").write_text("# bytecode\n")

        (tmp_path / "module.py").write_text("def func(): pass\n")

        result = await skill.execute(
            extensions=["py", "pyc"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "module.py" in result.output
        assert "__pycache__" not in result.output

    @pytest.mark.asyncio
    async def test_custom_exclude_patterns(self, skill, tmp_path):
        """Test custom exclude patterns work."""
        # Create test structure
        (tmp_path / "keep.py").write_text("keep = 1\n")
        (tmp_path / "skip_me.py").write_text("skip = 1\n")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_thing.py").write_text("test = 1\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            exclude=["skip_*", "tests"],  # Custom patterns
            dry_run=True,
        )

        assert result.success
        assert "keep.py" in result.output
        assert "skip_me.py" not in result.output
        assert "test_thing.py" not in result.output

    @pytest.mark.asyncio
    async def test_default_excludes_constant(self):
        """Test DEFAULT_EXCLUDES constant contains expected directories."""
        assert "node_modules" in DEFAULT_EXCLUDES
        assert ".git" in DEFAULT_EXCLUDES
        assert "__pycache__" in DEFAULT_EXCLUDES
        assert ".venv" in DEFAULT_EXCLUDES
        assert "venv" in DEFAULT_EXCLUDES
        assert ".pytest_cache" in DEFAULT_EXCLUDES


class TestExtensionMapping(TestConcatFilesSkill):
    """Tests for extension to language mapping."""

    def test_ext_to_lang_mapping(self):
        """Test EXT_TO_LANG has expected mappings."""
        assert EXT_TO_LANG["py"] == "python"
        assert EXT_TO_LANG["ts"] == "typescript"
        assert EXT_TO_LANG["js"] == "javascript"
        assert EXT_TO_LANG["rs"] == "rust"
        assert EXT_TO_LANG["go"] == "go"
        assert EXT_TO_LANG["java"] == "java"
        assert EXT_TO_LANG["rb"] == "ruby"
        assert EXT_TO_LANG["sh"] == "bash"
        assert EXT_TO_LANG["json"] == "json"
        assert EXT_TO_LANG["yaml"] == "yaml"
        assert EXT_TO_LANG["md"] == "markdown"


class TestOutputPathGeneration(TestConcatFilesSkill):
    """Tests for output file path generation."""

    @pytest.mark.asyncio
    async def test_output_path_includes_extensions(self, skill, tmp_path):
        """Test output filename includes searched extensions."""
        (tmp_path / "test.py").write_text("x = 1\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "-py-concat" in result.output

    @pytest.mark.asyncio
    async def test_output_path_handles_multiple_extensions(self, skill, tmp_path):
        """Test output filename handles multiple extensions."""
        (tmp_path / "a.py").write_text("a = 1\n")
        (tmp_path / "b.ts").write_text("const b = 1;\n")

        result = await skill.execute(
            extensions=["py", "ts"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        # Should have both extensions in name
        assert "-py-ts-concat" in result.output

    @pytest.mark.asyncio
    async def test_output_path_unique_suffix(self, skill, tmp_path):
        """Test output path adds numeric suffix if file exists."""
        (tmp_path / "test.py").write_text("x = 1\n")

        # Create first output file
        result1 = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="plain",
            dry_run=False,
        )
        assert result1.success

        # Create second output (should have -1 suffix)
        result2 = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="plain",
            dry_run=False,
        )
        assert result2.success

        # Should have two different output files
        output_files = list(tmp_path.glob("*-concat*.txt"))
        assert len(output_files) == 2


class TestSubdirectorySearch(TestConcatFilesSkill):
    """Tests for recursive subdirectory searching."""

    @pytest.mark.asyncio
    async def test_recursive_search(self, skill, tmp_path):
        """Test files in subdirectories are found."""
        # Create nested structure
        sub1 = tmp_path / "src" / "module1"
        sub1.mkdir(parents=True)
        (sub1 / "a.py").write_text("a = 1\n")

        sub2 = tmp_path / "src" / "module2"
        sub2.mkdir(parents=True)
        (sub2 / "b.py").write_text("b = 1\n")

        (tmp_path / "main.py").write_text("main = 1\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "main.py" in result.output
        assert "a.py" in result.output
        assert "b.py" in result.output


class TestLineEndings(TestConcatFilesSkill):
    """Tests for line ending handling."""

    @pytest.mark.asyncio
    async def test_handles_unix_line_endings(self, skill, tmp_path):
        """Test files with LF line endings are handled."""
        (tmp_path / "unix.py").write_text("line1\nline2\nline3\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "3 lines" in result.output

    @pytest.mark.asyncio
    async def test_handles_windows_line_endings(self, skill, tmp_path):
        """Test files with CRLF line endings are handled."""
        (tmp_path / "windows.py").write_bytes(b"line1\r\nline2\r\nline3\r\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "3 lines" in result.output

    @pytest.mark.asyncio
    async def test_handles_old_mac_line_endings(self, skill, tmp_path):
        """Test files with CR line endings are handled."""
        (tmp_path / "oldmac.py").write_bytes(b"line1\rline2\rline3\r")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "3 lines" in result.output


class TestXMLEscaping(TestConcatFilesSkill):
    """Tests for XML format special character escaping."""

    @pytest.mark.asyncio
    async def test_xml_escapes_special_chars_in_content(self, skill, tmp_path):
        """Test that XML special characters in content are properly escaped."""
        # Content with XML special characters
        (tmp_path / "special.py").write_text('x = "<tag>&value</tag>"\n')

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="xml",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.xml"))[0]
        content = output_file.read_text()

        # CDATA should contain the content (doesn't need escaping inside CDATA)
        assert "<![CDATA[" in content

    @pytest.mark.asyncio
    async def test_xml_handles_cdata_end_sequence(self, skill, tmp_path):
        """Test that ]]> in content is escaped in XML output."""
        # Content that contains CDATA end sequence
        (tmp_path / "cdata.py").write_text('x = "]]>"\n')

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            format="xml",
            dry_run=False,
        )

        assert result.success

        output_file = list(tmp_path.glob("*.xml"))[0]
        content = output_file.read_text()

        # The ]]> should be escaped
        assert "]]]]><![CDATA[>" in content


class TestTokenEstimation(TestConcatFilesSkill):
    """Tests for token estimation in dry run."""

    @pytest.mark.asyncio
    async def test_token_estimate_reasonable(self, skill, tmp_path):
        """Test that token estimate is reasonable (roughly 4 chars per token)."""
        # Create a file with known content
        content = "x" * 400  # 400 characters
        (tmp_path / "test.py").write_text(content + "\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        # Should estimate roughly 100+ tokens for 400+ chars (plus overhead)
        # The output should contain a token estimate
        assert "Tokens (est):" in result.output


class TestEmptyFiles(TestConcatFilesSkill):
    """Tests for handling empty files."""

    @pytest.mark.asyncio
    async def test_empty_file_included(self, skill, tmp_path):
        """Test that empty files are included with 0 lines."""
        (tmp_path / "empty.py").write_text("")
        (tmp_path / "nonempty.py").write_text("x = 1\n")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "empty.py" in result.output
        assert "nonempty.py" in result.output


class TestAllBinaryFilesCase(TestConcatFilesSkill):
    """Tests for edge case when all files are binary."""

    @pytest.mark.asyncio
    async def test_all_files_binary(self, skill, tmp_path):
        """Test message when all matched files are binary."""
        # Create only binary files
        (tmp_path / "bin1.py").write_bytes(b"\x00\x01\x02\x03")
        (tmp_path / "bin2.py").write_bytes(b"\xff\xfe\x00\x00")

        result = await skill.execute(
            extensions=["py"],
            path=str(tmp_path),
            dry_run=True,
        )

        assert result.success
        assert "binary" in result.output.lower()
