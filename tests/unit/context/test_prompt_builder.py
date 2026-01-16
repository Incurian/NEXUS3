"""Tests for structured prompt builder.

Tests cover:
- PromptSection creation and attributes
- EnvironmentBlock rendering
- StructuredPrompt rendering with sections and environment
- PromptBuilder fluent API
- inject_datetime_into_prompt security fix
"""

from pathlib import Path

import pytest

from nexus3.context.manager import inject_datetime_into_prompt
from nexus3.context.prompt_builder import (
    EnvironmentBlock,
    PromptBuilder,
    PromptSection,
    StructuredPrompt,
)


class TestPromptSection:
    """Tests for PromptSection dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Section can be created with just title and content."""
        section = PromptSection(title="Test", content="Some content")
        assert section.title == "Test"
        assert section.content == "Some content"
        assert section.source is None
        assert section.section_type == "config"

    def test_create_with_all_fields(self) -> None:
        """Section can be created with all fields specified."""
        source = Path("/path/to/file.md")
        section = PromptSection(
            title="Documentation",
            content="Doc content here",
            source=source,
            section_type="documentation",
        )
        assert section.title == "Documentation"
        assert section.content == "Doc content here"
        assert section.source == source
        assert section.section_type == "documentation"

    def test_section_types(self) -> None:
        """All valid section types can be used."""
        for section_type in ["config", "environment", "documentation"]:
            section = PromptSection(
                title="Test",
                content="Content",
                section_type=section_type,  # type: ignore[arg-type]
            )
            assert section.section_type == section_type


class TestEnvironmentBlock:
    """Tests for EnvironmentBlock dataclass and rendering."""

    def test_create_minimal(self) -> None:
        """Block can be created with required fields only."""
        block = EnvironmentBlock(
            cwd=Path("/home/user"),
            os_info="Linux",
        )
        assert block.cwd == Path("/home/user")
        assert block.os_info == "Linux"
        assert block.terminal is None
        assert block.datetime_str is None

    def test_create_full(self) -> None:
        """Block can be created with all fields."""
        block = EnvironmentBlock(
            cwd=Path("/home/user/project"),
            os_info="macOS 14.0",
            terminal="iTerm2",
            datetime_str="Current date: 2026-01-16",
        )
        assert block.cwd == Path("/home/user/project")
        assert block.os_info == "macOS 14.0"
        assert block.terminal == "iTerm2"
        assert block.datetime_str == "Current date: 2026-01-16"

    def test_render_minimal(self) -> None:
        """Render with only required fields."""
        block = EnvironmentBlock(
            cwd=Path("/home/user"),
            os_info="Linux",
        )
        result = block.render()
        lines = result.split("\n")
        assert lines[0] == "# Environment"
        assert "Working directory: /home/user" in result
        assert "Operating system: Linux" in result
        # No datetime or terminal
        assert "Current date" not in result
        assert "Terminal" not in result

    def test_render_with_datetime(self) -> None:
        """Render includes datetime when provided."""
        block = EnvironmentBlock(
            cwd=Path("/tmp"),
            os_info="Windows 11",
            datetime_str="Current date: 2026-01-16, Current time: 14:30 (local)",
        )
        result = block.render()
        lines = result.split("\n")
        # Datetime should be right after header
        assert lines[0] == "# Environment"
        assert lines[1] == "Current date: 2026-01-16, Current time: 14:30 (local)"
        assert "Working directory: /tmp" in result

    def test_render_with_terminal(self) -> None:
        """Render includes terminal when provided."""
        block = EnvironmentBlock(
            cwd=Path("/home/user"),
            os_info="Linux",
            terminal="xterm-256color",
        )
        result = block.render()
        assert "Terminal: xterm-256color" in result

    def test_render_full(self) -> None:
        """Render with all fields shows correct order."""
        block = EnvironmentBlock(
            cwd=Path("/project"),
            os_info="Linux (WSL2)",
            terminal="Windows Terminal",
            datetime_str="Current date: 2026-01-16",
        )
        result = block.render()
        lines = result.split("\n")
        assert lines[0] == "# Environment"
        assert lines[1] == "Current date: 2026-01-16"
        assert lines[2] == "Working directory: /project"
        assert lines[3] == "Operating system: Linux (WSL2)"
        assert lines[4] == "Terminal: Windows Terminal"


class TestStructuredPrompt:
    """Tests for StructuredPrompt rendering."""

    def test_empty_prompt(self) -> None:
        """Empty prompt renders as empty string."""
        prompt = StructuredPrompt()
        assert prompt.render() == ""

    def test_single_section(self) -> None:
        """Single section renders with header."""
        prompt = StructuredPrompt(
            sections=[PromptSection(title="Config", content="Config content")]
        )
        result = prompt.render()
        assert "## Config" in result
        assert "Config content" in result

    def test_section_with_source(self) -> None:
        """Section with source includes source path."""
        prompt = StructuredPrompt(
            sections=[
                PromptSection(
                    title="Project",
                    content="Project instructions",
                    source=Path("/home/user/NEXUS.md"),
                )
            ]
        )
        result = prompt.render()
        assert "## Project" in result
        assert "Source: /home/user/NEXUS.md" in result
        assert "Project instructions" in result

    def test_multiple_sections(self) -> None:
        """Multiple sections are joined with delimiters."""
        prompt = StructuredPrompt(
            sections=[
                PromptSection(title="First", content="First content"),
                PromptSection(title="Second", content="Second content"),
            ]
        )
        result = prompt.render()
        assert "## First" in result
        assert "First content" in result
        assert "---" in result  # Delimiter between sections
        assert "## Second" in result
        assert "Second content" in result

    def test_environment_only(self) -> None:
        """Prompt with only environment block."""
        prompt = StructuredPrompt(
            environment=EnvironmentBlock(
                cwd=Path("/home"),
                os_info="Linux",
            )
        )
        result = prompt.render()
        assert "# Environment" in result
        assert "Working directory: /home" in result

    def test_sections_and_environment(self) -> None:
        """Full prompt with sections and environment."""
        prompt = StructuredPrompt(
            sections=[
                PromptSection(title="Config", content="Config here"),
            ],
            environment=EnvironmentBlock(
                cwd=Path("/project"),
                os_info="macOS",
                datetime_str="Current date: 2026-01-16",
            ),
        )
        result = prompt.render()
        # Section comes first
        assert result.index("## Config") < result.index("# Environment")
        # Environment comes after delimiter
        assert "---" in result
        assert "Current date: 2026-01-16" in result

    def test_content_trimmed(self) -> None:
        """Section content is stripped of whitespace."""
        prompt = StructuredPrompt(
            sections=[
                PromptSection(title="Test", content="  \n  Content with spaces  \n  ")
            ]
        )
        result = prompt.render()
        assert "Content with spaces" in result
        # Should not have trailing/leading whitespace in content area
        assert "  \n  Content" not in result


class TestPromptBuilder:
    """Tests for PromptBuilder fluent API."""

    def test_empty_builder(self) -> None:
        """Empty builder produces empty prompt."""
        builder = PromptBuilder()
        prompt = builder.build()
        assert prompt.sections == []
        assert prompt.environment is None

    def test_add_single_section(self) -> None:
        """Add section returns self for chaining."""
        builder = PromptBuilder()
        result = builder.add_section("Title", "Content")
        assert result is builder
        prompt = builder.build()
        assert len(prompt.sections) == 1
        assert prompt.sections[0].title == "Title"
        assert prompt.sections[0].content == "Content"

    def test_add_section_with_all_params(self) -> None:
        """Add section accepts all parameters."""
        builder = PromptBuilder()
        source = Path("/test/path.md")
        builder.add_section(
            title="Docs",
            content="Documentation",
            source=source,
            section_type="documentation",
        )
        prompt = builder.build()
        section = prompt.sections[0]
        assert section.title == "Docs"
        assert section.content == "Documentation"
        assert section.source == source
        assert section.section_type == "documentation"

    def test_add_multiple_sections(self) -> None:
        """Multiple sections can be added."""
        builder = PromptBuilder()
        builder.add_section("First", "Content 1")
        builder.add_section("Second", "Content 2")
        builder.add_section("Third", "Content 3")
        prompt = builder.build()
        assert len(prompt.sections) == 3
        assert prompt.sections[0].title == "First"
        assert prompt.sections[1].title == "Second"
        assert prompt.sections[2].title == "Third"

    def test_set_environment(self) -> None:
        """Set environment returns self for chaining."""
        builder = PromptBuilder()
        env = EnvironmentBlock(cwd=Path("/home"), os_info="Linux")
        result = builder.set_environment(env)
        assert result is builder
        prompt = builder.build()
        assert prompt.environment is env

    def test_fluent_chaining(self) -> None:
        """Builder supports full fluent chaining."""
        env = EnvironmentBlock(
            cwd=Path("/project"),
            os_info="Linux",
            datetime_str="Current date: 2026-01-16",
        )
        prompt = (
            PromptBuilder()
            .add_section("Global", "Global config")
            .add_section("Project", "Project config", source=Path("/project/NEXUS.md"))
            .set_environment(env)
            .build()
        )
        assert len(prompt.sections) == 2
        assert prompt.sections[0].title == "Global"
        assert prompt.sections[1].title == "Project"
        assert prompt.environment is env

    def test_build_creates_copy(self) -> None:
        """Build creates independent copy of sections."""
        builder = PromptBuilder()
        builder.add_section("Test", "Content")
        prompt1 = builder.build()
        builder.add_section("Another", "More content")
        prompt2 = builder.build()
        # prompt1 should not have the new section
        assert len(prompt1.sections) == 1
        assert len(prompt2.sections) == 2

    def test_full_render(self) -> None:
        """Built prompt renders correctly."""
        prompt = (
            PromptBuilder()
            .add_section("Config", "Configuration content")
            .set_environment(
                EnvironmentBlock(
                    cwd=Path("/home/user"),
                    os_info="Ubuntu 22.04",
                    datetime_str="Current date: 2026-01-16, Current time: 10:00 (local)",
                )
            )
            .build()
        )
        result = prompt.render()
        assert "## Config" in result
        assert "Configuration content" in result
        assert "# Environment" in result
        assert "Current date: 2026-01-16, Current time: 10:00 (local)" in result
        assert "Working directory: /home/user" in result
        assert "Operating system: Ubuntu 22.04" in result


class TestInjectDatetimeIntoPrompt:
    """Tests for inject_datetime_into_prompt security fix.

    This function replaces the brittle str.replace() approach that could
    match "# Environment" anywhere in the prompt text.
    """

    def test_inject_at_environment_header(self) -> None:
        """Datetime is injected after Environment header."""
        prompt = "Some intro\n\n# Environment\nWorking directory: /home"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        # Should be inserted after the header line
        expected = "Some intro\n\n# Environment\nCurrent date: 2026-01-16\nWorking directory: /home"
        assert result == expected

    def test_inject_at_start_of_file(self) -> None:
        """Works when Environment section is at file start."""
        prompt = "# Environment\nWorking directory: /home"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        expected = "# Environment\nCurrent date: 2026-01-16\nWorking directory: /home"
        assert result == expected

    def test_no_environment_section(self) -> None:
        """Appends to end when no Environment section exists."""
        prompt = "# Configuration\nSome config"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        assert result == "# Configuration\nSome config\n\nCurrent date: 2026-01-16"

    def test_environment_at_eof_no_newline(self) -> None:
        """Handles Environment header at EOF with no trailing newline."""
        prompt = "Some content\n\n# Environment"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        assert result == "Some content\n\n# Environment\nCurrent date: 2026-01-16"

    def test_ignores_inline_environment_mention(self) -> None:
        """Does not match '# Environment' in middle of line."""
        # This is the key security fix - the old str.replace would match this
        prompt = "Text mentioning # Environment in the middle\n\n# Environment\nActual section"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        # Should only inject after the actual header (at line start)
        assert "Text mentioning # Environment in the middle" in result
        lines = result.split("\n")
        # Find the actual Environment header line
        env_idx = None
        for i, line in enumerate(lines):
            if line == "# Environment":
                env_idx = i
                break
        assert env_idx is not None
        # Datetime should be right after it
        assert lines[env_idx + 1] == "Current date: 2026-01-16"

    def test_multiple_environment_headers(self) -> None:
        """Uses first valid Environment header at line start."""
        prompt = "# Environment\nFirst\n\nSome text\n\n# Environment\nSecond"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        # Should inject after the FIRST header
        assert result.startswith("# Environment\nCurrent date: 2026-01-16\nFirst")

    def test_preserves_content_after_header(self) -> None:
        """All content after header is preserved."""
        prompt = """# System Configuration

## Global Config
Config content

# Environment
Working directory: /home/user
Operating system: Linux

## Other Section
More content"""
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        # Should have datetime after Environment header
        assert "# Environment\nCurrent date: 2026-01-16\nWorking directory:" in result
        # All other content should be preserved
        assert "# System Configuration" in result
        assert "## Global Config" in result
        assert "Config content" in result
        assert "## Other Section" in result
        assert "More content" in result

    def test_empty_prompt(self) -> None:
        """Empty prompt gets datetime appended."""
        result = inject_datetime_into_prompt("", "Current date: 2026-01-16")
        assert result == "\n\nCurrent date: 2026-01-16"

    def test_whitespace_only_prompt(self) -> None:
        """Whitespace-only prompt gets datetime appended."""
        result = inject_datetime_into_prompt("   \n\n   ", "Current date: 2026-01-16")
        assert "Current date: 2026-01-16" in result

    def test_environment_with_extra_text_on_line(self) -> None:
        """Environment header with extra text on same line is not matched."""
        prompt = "# Environment Variables\nVAR=value\n\n# Environment\nActual section"
        result = inject_datetime_into_prompt(prompt, "Current date: 2026-01-16")
        # Should not match "# Environment Variables", only "# Environment"
        assert "# Environment Variables\nVAR=value" in result
        # Datetime should be after the standalone "# Environment"
        assert "# Environment\nCurrent date: 2026-01-16\nActual section" in result

    def test_works_with_real_system_prompt_format(self) -> None:
        """Works with actual system prompt format from loader."""
        prompt = """# System Configuration

## Global Configuration
Source: /home/user/.nexus3/NEXUS.md

You are a helpful assistant.

# Environment
Working directory: /home/user/project
Operating system: Linux (WSL2 on Windows)
Terminal: Windows Terminal
Mode: Interactive REPL"""
        datetime_str = "Current date: 2026-01-16, Current time: 14:30 (local)"
        result = inject_datetime_into_prompt(prompt, datetime_str)

        # Verify structure is preserved
        assert "# System Configuration" in result
        assert "## Global Configuration" in result
        assert "You are a helpful assistant." in result

        # Verify datetime is in the right place
        env_line_idx = result.find("# Environment\n")
        datetime_idx = result.find(datetime_str)
        working_dir_idx = result.find("Working directory:")

        # Datetime should be after header and before working directory
        assert env_line_idx < datetime_idx < working_dir_idx
