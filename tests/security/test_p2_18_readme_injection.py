"""P2.18: README Injection Hardening Tests.

Tests that:
1. Default readme_as_fallback is False (safe default)
2. When readme_as_fallback=True, README is wrapped with boundaries
3. Boundary markers include "DOCUMENTATION" and "not agent instructions"
4. README content is preserved within boundaries
5. Source path is included in boundary
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nexus3.config.schema import ContextConfig
from nexus3.context.loader import ContextLoader


class TestReadmeDefaultDisabled:
    """Test that readme_as_fallback defaults to False."""

    def test_context_config_default_readme_as_fallback_is_false(self) -> None:
        """ContextConfig.readme_as_fallback defaults to False for security."""
        config = ContextConfig()
        assert config.readme_as_fallback is False

    def test_readme_not_loaded_by_default(self, tmp_path: Path) -> None:
        """With default config, README.md is NOT used as fallback."""
        # Create a directory with only README.md (no NEXUS.md)
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        # Create README.md in project root (parent of .nexus3)
        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Project\n\nThis is the README content.", encoding="utf-8")

        # Load context with default config (readme_as_fallback=False)
        loader = ContextLoader(cwd=tmp_path, context_config=ContextConfig())
        context = loader.load()

        # README content should NOT be in the prompt
        assert "This is the README content" not in context.system_prompt

    def test_readme_loaded_when_explicitly_enabled(self, tmp_path: Path) -> None:
        """With readme_as_fallback=True, README.md is used as fallback."""
        # Create a directory with only README.md (no NEXUS.md)
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        # Create README.md in project root
        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Project\n\nThis is the README content.", encoding="utf-8")

        # Load context with readme_as_fallback enabled
        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # README content SHOULD be in the prompt
        assert "This is the README content" in context.system_prompt


class TestReadmeBoundaryMarkers:
    """Test that README content is wrapped with explicit boundaries."""

    def test_readme_fallback_has_documentation_boundary(self, tmp_path: Path) -> None:
        """README as fallback is wrapped with DOCUMENTATION boundary."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        readme_path = tmp_path / "README.md"
        readme_path.write_text("# My Project\n\nProject description here.", encoding="utf-8")

        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # Check for boundary markers
        assert "DOCUMENTATION (README.md - not agent instructions)" in context.system_prompt
        assert "END DOCUMENTATION" in context.system_prompt

    def test_readme_fallback_has_not_agent_instructions_text(self, tmp_path: Path) -> None:
        """README boundary explicitly says 'not agent instructions'."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        readme_path = tmp_path / "README.md"
        readme_path.write_text("Project documentation", encoding="utf-8")

        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        assert "not agent instructions" in context.system_prompt

    def test_readme_fallback_includes_source_path(self, tmp_path: Path) -> None:
        """README boundary includes the source path."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        readme_path = tmp_path / "README.md"
        readme_path.write_text("Project documentation", encoding="utf-8")

        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # Source path should be in the prompt
        assert str(readme_path) in context.system_prompt

    def test_readme_content_preserved_within_boundaries(self, tmp_path: Path) -> None:
        """README content is preserved (not modified) within boundaries."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        readme_content = """# My Special Project

This has **markdown** formatting.

- Bullet point 1
- Bullet point 2

```python
def hello():
    print("world")
```"""
        readme_path = tmp_path / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")

        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # All content should be preserved (stripped)
        assert "# My Special Project" in context.system_prompt
        assert "**markdown** formatting" in context.system_prompt
        assert "Bullet point 1" in context.system_prompt
        assert 'print("world")' in context.system_prompt


class TestReadmeIncludeWithNexusMd:
    """Test README inclusion when include_readme=True alongside NEXUS.md."""

    def test_include_readme_wraps_with_boundaries(self, tmp_path: Path) -> None:
        """When include_readme=True, README is wrapped with boundaries."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        # Create both NEXUS.md and README.md
        nexus_md = nexus_dir / "NEXUS.md"
        nexus_md.write_text("# Agent Instructions\n\nDo this task.", encoding="utf-8")

        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Documentation\n\nProject docs here.", encoding="utf-8")

        config = ContextConfig(include_readme=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # NEXUS.md content should NOT be wrapped
        assert "# Agent Instructions" in context.system_prompt
        assert "Do this task" in context.system_prompt

        # README content should be wrapped with boundaries
        assert "DOCUMENTATION (README.md - not agent instructions)" in context.system_prompt
        assert "Project docs here" in context.system_prompt
        assert "END DOCUMENTATION" in context.system_prompt

    def test_include_readme_has_source_path_for_readme(self, tmp_path: Path) -> None:
        """When include_readme=True, README boundary has correct source path."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        nexus_md = nexus_dir / "NEXUS.md"
        nexus_md.write_text("Agent instructions", encoding="utf-8")

        readme_path = tmp_path / "README.md"
        readme_path.write_text("Documentation", encoding="utf-8")

        config = ContextConfig(include_readme=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # The boundary should include the README path
        assert str(readme_path) in context.system_prompt


class TestBoundaryFormat:
    """Test the exact format of boundary markers."""

    def test_boundary_uses_equals_separator(self, tmp_path: Path) -> None:
        """Boundaries use '=' characters as visual separators."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        readme_path = tmp_path / "README.md"
        readme_path.write_text("Content", encoding="utf-8")

        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # Should have lines of equals signs
        assert "=" * 80 in context.system_prompt

    def test_boundary_structure_is_consistent(self, tmp_path: Path) -> None:
        """Boundary structure matches expected format."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        readme_path = tmp_path / "README.md"
        readme_path.write_text("Test content", encoding="utf-8")

        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        # Check structure
        lines = context.system_prompt.split("\n")

        # Find the DOCUMENTATION line
        doc_line_idx = None
        for i, line in enumerate(lines):
            if "DOCUMENTATION (README.md - not agent instructions)" in line:
                doc_line_idx = i
                break

        assert doc_line_idx is not None, "DOCUMENTATION line not found"

        # Line before should be separator
        assert "=" * 80 in lines[doc_line_idx - 1]

        # Find END DOCUMENTATION
        end_doc_idx = None
        for i, line in enumerate(lines):
            if "END DOCUMENTATION" in line:
                end_doc_idx = i
                break

        assert end_doc_idx is not None, "END DOCUMENTATION line not found"

        # Line before END DOCUMENTATION should be separator
        assert "=" * 80 in lines[end_doc_idx - 1] or "=" * 80 in lines[end_doc_idx]


class TestNoReadmeNoInjection:
    """Test that missing README doesn't cause issues."""

    def test_no_readme_no_boundaries(self, tmp_path: Path) -> None:
        """When no README exists, no boundary markers appear."""
        nexus_dir = tmp_path / ".nexus3"
        nexus_dir.mkdir()

        nexus_md = nexus_dir / "NEXUS.md"
        nexus_md.write_text("Agent instructions only", encoding="utf-8")

        # Even with readme_as_fallback=True, if no README exists, no boundaries
        config = ContextConfig(readme_as_fallback=True)
        loader = ContextLoader(cwd=tmp_path, context_config=config)
        context = loader.load()

        assert "DOCUMENTATION (README.md" not in context.system_prompt
        assert "END DOCUMENTATION" not in context.system_prompt


class TestFormatReadmeSectionMethod:
    """Test the _format_readme_section method directly."""

    def test_format_readme_section_basic(self, tmp_path: Path) -> None:
        """Test _format_readme_section formats content correctly."""
        loader = ContextLoader(cwd=tmp_path)
        source_path = tmp_path / "README.md"

        result = loader._format_readme_section("Hello world", source_path)

        assert "DOCUMENTATION (README.md - not agent instructions)" in result
        assert str(source_path) in result
        assert "Hello world" in result
        assert "END DOCUMENTATION" in result

    def test_format_readme_section_strips_whitespace(self, tmp_path: Path) -> None:
        """Test _format_readme_section strips leading/trailing whitespace."""
        loader = ContextLoader(cwd=tmp_path)
        source_path = tmp_path / "README.md"

        result = loader._format_readme_section("\n\n  Content with whitespace  \n\n", source_path)

        # Content should be stripped but present
        assert "Content with whitespace" in result
        # Should not have the extra newlines at content boundaries
        lines = result.split("\n")
        content_idx = None
        for i, line in enumerate(lines):
            if "Content with whitespace" in line:
                content_idx = i
                break
        assert content_idx is not None
        # Line should be clean
        assert lines[content_idx] == "Content with whitespace"

    def test_format_readme_section_preserves_internal_formatting(self, tmp_path: Path) -> None:
        """Test _format_readme_section preserves internal line breaks."""
        loader = ContextLoader(cwd=tmp_path)
        source_path = tmp_path / "README.md"

        multi_line = """Line 1

Line 3 after blank

Line 5"""
        result = loader._format_readme_section(multi_line, source_path)

        assert "Line 1" in result
        assert "Line 3 after blank" in result
        assert "Line 5" in result
