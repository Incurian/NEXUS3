"""System prompt loading with layered configuration.

This module provides the PromptLoader class for loading system prompts from
multiple sources and combining them. This allows prompts to be customized at
multiple levels: personal defaults and project-specific overrides.

Loading strategy:
1. First load personal prompt: ~/.nexus3/NEXUS.md OR package default
2. Then load project prompt: ./NEXUS.md (cwd) if it exists
3. Combine them with explanatory headers
4. Append system environment info (working directory, OS, terminal)
"""

import os
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


def get_system_info(is_repl: bool = True) -> str:
    """Generate system environment information for context injection.

    Args:
        is_repl: Whether running in interactive REPL mode.

    Returns:
        Formatted string with system information.
    """
    parts = ["# Environment"]

    # Note: Current date/time is injected dynamically per-request in ContextManager
    # to ensure accuracy throughout the session

    # Working directory
    cwd = Path.cwd()
    parts.append(f"Working directory: {cwd}")

    # Operating system detection with WSL handling
    system = platform.system()
    release = platform.release()

    if system == "Linux" and "microsoft" in release.lower():
        # Running in WSL
        parts.append("Operating system: Linux (WSL2 on Windows)")
        parts.append(f"Kernel: {release}")
    elif system == "Linux":
        # Native Linux
        try:
            # Try to get distro info
            if Path("/etc/os-release").exists():
                os_release = Path("/etc/os-release").read_text(encoding="utf-8")
                for line in os_release.splitlines():
                    if line.startswith("PRETTY_NAME="):
                        distro = line.split("=", 1)[1].strip('"')
                        parts.append(f"Operating system: {distro}")
                        break
                else:
                    parts.append(f"Operating system: Linux {release}")
            else:
                parts.append(f"Operating system: Linux {release}")
        except Exception:
            parts.append(f"Operating system: Linux {release}")
    elif system == "Darwin":
        # macOS
        mac_ver = platform.mac_ver()[0]
        parts.append(f"Operating system: macOS {mac_ver}")
    elif system == "Windows":
        parts.append(f"Operating system: Windows {release}")
    else:
        parts.append(f"Operating system: {system} {release}")

    # Terminal/mode info
    if is_repl:
        term = os.environ.get("TERM", "unknown")
        term_program = os.environ.get("TERM_PROGRAM", "")
        if term_program:
            parts.append(f"Terminal: {term_program} ({term})")
        else:
            parts.append(f"Terminal: {term}")
        parts.append("Mode: Interactive REPL")
    else:
        parts.append("Mode: HTTP JSON-RPC Server")

    return "\n".join(parts)


@dataclass
class LoadedPrompt:
    """Result of loading prompts from all sources.

    Attributes:
        content: The combined prompt content with headers.
        personal_path: Path to the personal/default prompt that was loaded.
        project_path: Path to the project prompt, if one was loaded.
    """

    content: str
    personal_path: Path | None
    project_path: Path | None


class PromptSource(Protocol):
    """Protocol for prompt sources.

    A PromptSource can attempt to load prompt content from some location
    (file, environment variable, hardcoded, etc.).
    """

    def load(self) -> str | None:
        """Load prompt content.

        Returns:
            The prompt content as a string if successfully loaded, None otherwise.
        """
        ...

    @property
    def path(self) -> Path | None:
        """Return the path if this source loaded successfully.

        Returns:
            The Path that was loaded from, or None if this source didn't load
            or doesn't have a path (e.g., hardcoded prompts).
        """
        ...


class FilePromptSource:
    """Load prompt from a file path.

    Simple source that reads a prompt from the filesystem if the file exists.

    Attributes:
        path: The file path to attempt to load from.
    """

    def __init__(self, path: Path) -> None:
        """Initialize with a file path.

        Args:
            path: Path to the prompt file.
        """
        self._path = path
        self._loaded = False

    def load(self) -> str | None:
        """Load prompt from file if it exists.

        Returns:
            File contents as a string if the file exists, None otherwise.
        """
        if self._path.exists():
            self._loaded = True
            return self._path.read_text(encoding="utf-8")
        return None

    @property
    def path(self) -> Path | None:
        """Return the path if loaded, None otherwise.

        Returns:
            The path that was successfully loaded from, or None.
        """
        return self._path if self._loaded else None


class PromptLoader:
    """Load and combine system prompts from multiple layers.

    Loads prompts from two layers and combines them:
    1. Personal layer: ~/.nexus3/NEXUS.md OR package default (fallback)
    2. Project layer: ./NEXUS.md (cwd) - optional, adds project-specific config

    Both layers are combined with explanatory headers when present.

    Example:
        >>> loader = PromptLoader()
        >>> result = loader.load()
        >>> print(f"Personal from: {result.personal_path}")
        >>> print(f"Project from: {result.project_path}")

    Attributes:
        personal_sources: Sources for personal/default prompts (first match wins).
        project_source: Source for project-specific prompt (cwd/NEXUS.md).
    """

    # Header templates for combining prompts
    PERSONAL_HEADER = "# Personal Configuration"
    PROJECT_HEADER = "# Project Configuration"

    def __init__(
        self,
        personal_sources: list[PromptSource] | None = None,
        project_source: PromptSource | None = None,
    ) -> None:
        """Initialize with custom sources or use defaults.

        Args:
            personal_sources: Sources for personal/default prompt (first match wins).
                If None, uses ~/.nexus3/NEXUS.md then package default.
            project_source: Source for project prompt. If None, uses cwd/NEXUS.md.
        """
        if personal_sources is not None:
            self._personal_sources = personal_sources
        else:
            self._personal_sources = self._default_personal_sources()

        if project_source is not None:
            self._project_source = project_source
        else:
            self._project_source = FilePromptSource(Path.cwd() / "NEXUS.md")

        self._personal_path: Path | None = None
        self._project_path: Path | None = None

    @staticmethod
    def _default_personal_sources() -> list[PromptSource]:
        """Create the default personal sources fallback chain.

        Returns:
            List of PromptSource instances in order of precedence:
            [~/.nexus3/NEXUS.md, package/defaults/NEXUS.md]
        """
        import nexus3

        package_dir = Path(nexus3.__file__).parent
        return [
            FilePromptSource(Path.home() / ".nexus3" / "NEXUS.md"),
            FilePromptSource(package_dir / "defaults" / "NEXUS.md"),
        ]

    def _load_personal(self) -> tuple[str | None, Path | None]:
        """Load personal/default prompt from first available source.

        Returns:
            Tuple of (content, path). Both None if no source succeeded.
        """
        for source in self._personal_sources:
            content = source.load()
            if content is not None:
                return content, source.path
        return None, None

    def _load_project(self) -> tuple[str | None, Path | None]:
        """Load project prompt if it exists.

        Returns:
            Tuple of (content, path). Both None if project prompt doesn't exist.
        """
        content = self._project_source.load()
        if content is not None:
            return content, self._project_source.path
        return None, None

    def _combine_prompts(
        self,
        personal_content: str | None,
        project_content: str | None,
        is_repl: bool = True,
    ) -> str:
        """Combine personal and project prompts with headers and system info.

        Args:
            personal_content: Content from personal/default source.
            project_content: Content from project source.
            is_repl: Whether running in REPL mode (affects system info).

        Returns:
            Combined prompt with appropriate headers and system info.
        """
        parts: list[str] = []

        if personal_content:
            parts.append(self.PERSONAL_HEADER)
            parts.append(personal_content.strip())

        if project_content:
            parts.append(self.PROJECT_HEADER)
            parts.append(project_content.strip())

        if not parts:
            # Ultimate fallback - hardcoded minimal prompt
            parts.append("You are a helpful AI assistant.")

        # Always append system environment info
        parts.append(get_system_info(is_repl=is_repl))

        return "\n\n".join(parts)

    def load(self, is_repl: bool = True) -> LoadedPrompt:
        """Load and combine prompts from all layers.

        Loads personal/default prompt first, then project prompt if it exists,
        and combines them with explanatory headers and system info.

        Args:
            is_repl: Whether running in REPL mode (affects system info).

        Returns:
            LoadedPrompt with combined content and source paths.

        Example:
            >>> loader = PromptLoader()
            >>> result = loader.load()
            >>> print(result.content)
            # Personal Configuration
            [personal prompt content]

            # Project Configuration
            [project prompt content]

            # Environment
            Working directory: /path/to/project
            Operating system: Linux (WSL2 on Windows)
            ...
        """
        personal_content, personal_path = self._load_personal()
        project_content, project_path = self._load_project()

        self._personal_path = personal_path
        self._project_path = project_path

        combined = self._combine_prompts(personal_content, project_content, is_repl=is_repl)

        return LoadedPrompt(
            content=combined,
            personal_path=personal_path,
            project_path=project_path,
        )

    @property
    def personal_path(self) -> Path | None:
        """Return the personal/default path that was loaded from.

        This is only set after calling load(). Returns None if the hardcoded
        fallback was used or if load() hasn't been called yet.

        Returns:
            The Path that was successfully loaded from, or None.
        """
        return self._personal_path

    @property
    def project_path(self) -> Path | None:
        """Return the project path that was loaded from, if any.

        This is only set after calling load(). Returns None if no project
        prompt was found or if load() hasn't been called yet.

        Returns:
            The Path that was successfully loaded from, or None.
        """
        return self._project_path

    # Legacy compatibility - deprecated, use load() instead
    @property
    def loaded_from(self) -> Path | None:
        """Return the primary path that was loaded from.

        Deprecated: Use personal_path and project_path instead.

        Returns:
            The personal_path if set, otherwise None.
        """
        return self._personal_path
