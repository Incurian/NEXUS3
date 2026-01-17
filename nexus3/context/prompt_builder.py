"""Structured prompt construction.

Replaces brittle string operations with typed sections and explicit boundaries.

This module provides:
- PromptSection: A typed section of the system prompt with metadata
- EnvironmentBlock: Typed environment information for dynamic datetime injection
- StructuredPrompt: Complete prompt with typed sections that can be rendered
- PromptBuilder: Fluent builder for constructing prompts programmatically

The key security improvement is replacing str.replace() based datetime injection
(which can fail if the marker appears elsewhere in the prompt) with explicit
structured sections that maintain clear boundaries.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class PromptSection:
    """A typed section of the system prompt.

    Attributes:
        title: Section header (e.g., "Project Configuration")
        content: Section content text
        source: Optional source file path for debugging
        section_type: Classification for the section
    """

    title: str
    content: str
    source: Path | None = None
    section_type: Literal["config", "environment", "documentation"] = "config"


@dataclass
class EnvironmentBlock:
    """Typed environment information - replaces brittle datetime injection.

    This class ensures datetime is injected at a known position rather than
    relying on str.replace() which could match unintended content.

    Attributes:
        cwd: Working directory to report
        os_info: Operating system description
        terminal: Optional terminal info (for REPL mode)
        datetime_str: Pre-formatted datetime string to inject
        kernel: Optional kernel version (for WSL)
        mode: Optional mode description ("Interactive REPL" or "HTTP JSON-RPC Server")
        extra_lines: Additional lines to include (for full get_system_info() compat)
    """

    cwd: Path
    os_info: str
    terminal: str | None = None
    datetime_str: str | None = None
    kernel: str | None = None
    mode: str | None = None
    extra_lines: list[str] | None = None

    def render(self) -> str:
        """Render environment block as text.

        Returns:
            Formatted environment section with all fields.
        """
        lines = ["# Environment"]
        if self.datetime_str:
            lines.append(self.datetime_str)
        lines.append(f"Working directory: {self.cwd}")
        lines.append(f"Operating system: {self.os_info}")
        if self.kernel:
            lines.append(f"Kernel: {self.kernel}")
        if self.terminal:
            lines.append(f"Terminal: {self.terminal}")
        if self.mode:
            lines.append(f"Mode: {self.mode}")
        if self.extra_lines:
            lines.extend(self.extra_lines)
        return "\n".join(lines)


@dataclass
class StructuredPrompt:
    """Complete structured prompt with typed sections.

    A StructuredPrompt maintains explicit structure so that datetime injection
    and other dynamic content can be inserted at known positions without
    relying on string matching.

    Attributes:
        sections: List of PromptSection objects
        environment: Optional EnvironmentBlock for system info
    """

    sections: list[PromptSection] = field(default_factory=list)
    environment: EnvironmentBlock | None = None

    def render(self) -> str:
        """Render complete prompt as string.

        Sections are joined with horizontal rule delimiters.
        Environment block (if present) is rendered last.

        Returns:
            Complete prompt text ready for use.
        """
        parts: list[str] = []

        for section in self.sections:
            header = f"## {section.title}"
            if section.source:
                header += f"\nSource: {section.source}"
            parts.append(f"{header}\n\n{section.content.strip()}")

        if self.environment:
            parts.append(self.environment.render())

        return "\n\n---\n\n".join(parts)

    def render_compat(self) -> str:
        """Render in compatibility format matching loader.py output.

        This produces output that exactly matches the current loader.py
        format, ensuring no behavior change when adopting StructuredPrompt.

        Format:
            # System Configuration

            ## Section Title
            Source: /path/to/source

            <content>

            ## Another Section
            ...

            # Environment
            ...

        Returns:
            Complete prompt matching loader.py format exactly.
        """
        parts: list[str] = []

        # Sections with "# System Configuration" header
        if self.sections:
            section_parts = []
            for section in self.sections:
                header = f"## {section.title}"
                if section.source:
                    header += f"\nSource: {section.source}"
                section_parts.append(f"{header}\n\n{section.content.strip()}")
            parts.append("# System Configuration\n\n" + "\n\n".join(section_parts))
        else:
            parts.append("You are a helpful AI assistant.")

        # Environment block
        if self.environment:
            parts.append(self.environment.render())

        return "\n\n".join(parts)


class PromptBuilder:
    """Fluent builder for constructing prompts.

    Example:
        >>> builder = PromptBuilder()
        >>> prompt = (builder
        ...     .add_section("Config", "Some config text")
        ...     .set_environment(EnvironmentBlock(
        ...         cwd=Path("/home/user"),
        ...         os_info="Linux",
        ...         datetime_str="Current date: 2026-01-16"
        ...     ))
        ...     .build())
        >>> print(prompt.render())
    """

    def __init__(self) -> None:
        """Initialize an empty builder."""
        self._sections: list[PromptSection] = []
        self._environment: EnvironmentBlock | None = None

    def add_section(
        self,
        title: str,
        content: str,
        source: Path | None = None,
        section_type: Literal["config", "environment", "documentation"] = "config",
    ) -> "PromptBuilder":
        """Add a section to the prompt.

        Args:
            title: Section header text
            content: Section content text
            source: Optional source file path
            section_type: Section classification

        Returns:
            Self for method chaining.
        """
        self._sections.append(
            PromptSection(
                title=title,
                content=content,
                source=source,
                section_type=section_type,
            )
        )
        return self

    def set_environment(self, env: EnvironmentBlock) -> "PromptBuilder":
        """Set the environment block.

        Args:
            env: Environment block with system info

        Returns:
            Self for method chaining.
        """
        self._environment = env
        return self

    def build(self) -> StructuredPrompt:
        """Build the final structured prompt.

        Returns:
            StructuredPrompt instance with all added sections and environment.
        """
        return StructuredPrompt(
            sections=self._sections.copy(),
            environment=self._environment,
        )
