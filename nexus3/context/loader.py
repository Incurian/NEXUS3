"""Unified context loader for layered configuration.

This module provides the ContextLoader class for loading and merging context
from multiple directory layers (global, ancestor, local).
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nexus3.config.load_utils import load_json_file_optional
from nexus3.config.schema import ContextConfig, MCPServerConfig
from nexus3.core.constants import get_defaults_dir, get_nexus_dir
from nexus3.core.errors import ContextLoadError, LoadError, MCPConfigError
from nexus3.core.utils import deep_merge, find_ancestor_config_dirs
from nexus3.mcp.errors import MCPErrorContext


def get_system_info(is_repl: bool = True, cwd: Path | None = None) -> str:
    """Generate system environment information for context injection.

    Args:
        is_repl: Whether running in interactive REPL mode.
        cwd: Working directory to report. Defaults to Path.cwd() if not provided.

    Returns:
        Formatted string with system information.
    """
    parts = ["# Environment"]

    # Note: Current date/time is injected dynamically per-request in ContextManager
    # to ensure accuracy throughout the session

    # Working directory (use agent's cwd if provided, not process cwd)
    effective_cwd = cwd if cwd is not None else Path.cwd()
    parts.append(f"Working directory: {effective_cwd}")

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
                os_release = Path("/etc/os-release").read_text(encoding="utf-8-sig")
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
class PromptSource:
    """A single prompt source with its path and layer name."""

    path: Path
    layer_name: str


@dataclass
class MCPServerWithOrigin:
    """MCP server config with its origin layer."""

    config: MCPServerConfig
    origin: str  # "global", "ancestor:dirname", "local"
    source_path: Path


@dataclass
class ContextSources:
    """Tracks where each piece of context came from."""

    global_dir: Path | None = None
    ancestor_dirs: list[Path] = field(default_factory=list)
    local_dir: Path | None = None

    prompt_sources: list[PromptSource] = field(default_factory=list)
    config_sources: list[Path] = field(default_factory=list)
    mcp_sources: list[Path] = field(default_factory=list)


# Search directories for instruction filenames, relative to project root.
# Each filename maps to an ordered list of subdirectories to check.
INSTRUCTION_FILE_SEARCH_DIRS: dict[str, list[str]] = {
    "NEXUS.md": [".nexus3", "."],
    "AGENTS.md": [".nexus3", ".agents", "."],
    "CLAUDE.md": [".nexus3", ".claude", ".agents", "."],
    "README.md": ["."],
}

# Default search pattern for filenames not in the map above
DEFAULT_SEARCH_DIRS = [".nexus3", "."]


@dataclass
class InstructionFileResult:
    """Result of searching for an instruction file."""

    content: str
    source_path: Path
    filename: str  # e.g., "NEXUS.md", "AGENTS.md"
    is_readme: bool  # True if this is a README.md (needs wrapping)


@dataclass
class ContextLayer:
    """A single layer of context (global, ancestor, or local)."""

    name: str  # "global", "ancestor:dirname", "local"
    path: Path  # Directory path

    prompt: str | None = None  # Instruction file content
    readme: str | None = None  # README.md content (for wrapping)
    config: dict[str, Any] | None = None  # config.json content (pre-validation)
    mcp: dict[str, Any] | None = None  # mcp.json content

    # Track which instruction file was found (for accurate source labels)
    prompt_source_path: Path | None = None
    prompt_filename: str | None = None  # e.g., "NEXUS.md", "AGENTS.md"


@dataclass
class LoadedContext:
    """Result of loading all context layers."""

    # Prompt content (already merged and labeled)
    system_prompt: str

    # Merged configuration (as dict, for further validation)
    merged_config: dict[str, Any]

    # Merged MCP servers (with origin tracking)
    mcp_servers: list[MCPServerWithOrigin]

    # Source tracking for debugging
    sources: ContextSources


class ContextLoader:
    """Unified loader for all context types with layered merging.

    Loads context from multiple layers:
    1. Global (~/.nexus3/)
    2. Ancestors (up to N levels above CWD)
    3. Local (CWD/.nexus3/)

    Each layer can provide:
    - NEXUS.md: System prompt
    - README.md: Fallback prompt (if configured)
    - config.json: Configuration overrides
    - mcp.json: MCP server definitions

    Example:
        >>> loader = ContextLoader(Path.cwd())
        >>> context = loader.load()
        >>> print(context.system_prompt)
    """

    def __init__(
        self,
        cwd: Path | None = None,
        context_config: ContextConfig | None = None,
    ) -> None:
        """Initialize the context loader.

        Args:
            cwd: Working directory to load context for. Defaults to Path.cwd().
            context_config: Context loading configuration. Defaults to ContextConfig().
        """
        self._cwd = cwd or Path.cwd()
        self._config = context_config or ContextConfig()

    def _get_global_dir(self) -> Path:
        """Get the global config directory."""
        return get_nexus_dir()

    def _get_defaults_dir(self) -> Path:
        """Get the install defaults directory."""
        return get_defaults_dir()

    def _load_file(self, path: Path) -> str | None:
        """Load a text file if it exists.

        Args:
            path: Path to the file.

        Returns:
            File contents or None if file doesn't exist.
        """
        if path.is_file():
            return path.read_text(encoding="utf-8-sig")
        return None

    def _get_search_locations(self, filename: str, project_root: Path) -> list[Path]:
        """Get ordered search locations for an instruction filename.

        Args:
            filename: The instruction filename (e.g., "NEXUS.md", "CLAUDE.md").
            project_root: The project root directory.

        Returns:
            List of absolute file paths to check, in priority order.
        """
        search_dirs = INSTRUCTION_FILE_SEARCH_DIRS.get(filename, DEFAULT_SEARCH_DIRS)
        locations = []
        for dir_name in search_dirs:
            if dir_name == ".":
                locations.append(project_root / filename)
            else:
                locations.append(project_root / dir_name / filename)
        return locations

    def _find_instruction_file(
        self, project_root: Path
    ) -> InstructionFileResult | None:
        """Search for the first matching instruction file using priority list.

        Iterates through configured instruction_files list, checking each
        filename's search locations. Returns the first file found.

        Args:
            project_root: The project root directory to search in.

        Returns:
            InstructionFileResult if found, None if no instruction file exists.
        """
        for filename in self._config.instruction_files:
            locations = self._get_search_locations(filename, project_root)
            for location in locations:
                content = self._load_file(location)
                if content is not None:
                    return InstructionFileResult(
                        content=content,
                        source_path=location,
                        filename=filename,
                        is_readme=(filename.upper() == "README.MD"),
                    )
        return None

    def _load_layer(self, directory: Path, layer_name: str) -> ContextLayer:
        """Load all context files from a directory.

        Args:
            directory: Directory to load from (the .nexus3 dir, or project root for legacy).
            layer_name: Name for this layer (e.g., "global", "ancestor:company").

        Returns:
            ContextLayer with loaded content.
        """
        layer = ContextLayer(name=layer_name, path=directory)

        # Find instruction file using priority search
        project_root = directory.parent if directory.name == ".nexus3" else directory
        result = self._find_instruction_file(project_root)
        if result is not None:
            if result.is_readme:
                layer.readme = result.content
            else:
                layer.prompt = result.content
            layer.prompt_source_path = result.source_path
            layer.prompt_filename = result.filename

        # Load config.json - ContextLoadError propagates for fail-fast behavior
        config_path = directory / "config.json"
        try:
            layer.config = load_json_file_optional(config_path)
        except LoadError as e:
            raise ContextLoadError(e.message) from e

        # Load mcp.json - ContextLoadError propagates for fail-fast behavior
        mcp_path = directory / "mcp.json"
        try:
            layer.mcp = load_json_file_optional(mcp_path)
        except LoadError as e:
            raise ContextLoadError(e.message) from e

        return layer

    def _load_global_layer(self) -> list[ContextLayer]:
        """Load the global layer with both system defaults and user customization.

        System defaults (NEXUS-DEFAULT.md) always come from the package.
        User customization (NEXUS.md) comes from ~/.nexus3/ if it exists,
        otherwise falls back to package template.

        Returns:
            List of layers: [system-defaults layer, user/global layer]
        """
        layers: list[ContextLayer] = []
        global_dir = self._get_global_dir()
        defaults_dir = self._get_defaults_dir()

        # 1. Always load NEXUS-DEFAULT.md from package (system docs/tools)
        pkg_default = defaults_dir / "NEXUS-DEFAULT.md"
        if pkg_default.is_file():
            layer = ContextLayer(name="system-defaults", path=defaults_dir)
            layer.prompt = pkg_default.read_text(encoding="utf-8-sig")
            layers.append(layer)

        # 2. Load user's global config (config.json, mcp.json always from global dir)
        global_config = load_json_file_optional(global_dir / "config.json")
        global_mcp = load_json_file_optional(global_dir / "mcp.json")

        # 3. Load user's NEXUS.md from global dir, or fall back to package template
        user_nexus = global_dir / "NEXUS.md"
        if user_nexus.is_file():
            layer = ContextLayer(name="global", path=global_dir)
            layer.prompt = user_nexus.read_text(encoding="utf-8-sig")
            layer.config = global_config
            layer.mcp = global_mcp
            layers.append(layer)
        else:
            # Fall back to package NEXUS.md template for prompt,
            # but still use global config/mcp if they exist
            pkg_nexus = defaults_dir / "NEXUS.md"
            if pkg_nexus.is_file() or global_config or global_mcp:
                # Use global_dir as path if we have config/mcp there, otherwise defaults_dir
                layer_path = global_dir if (global_config or global_mcp) else defaults_dir
                layer = ContextLayer(name="global", path=layer_path)
                if pkg_nexus.is_file():
                    layer.prompt = pkg_nexus.read_text(encoding="utf-8-sig")
                layer.config = global_config
                layer.mcp = global_mcp
                layers.append(layer)

        return layers

    def _format_readme_section(self, content: str, source_path: Path) -> str:
        """Format README with explicit documentation boundaries.

        Marks README content as documentation, not agent instructions,
        to reduce prompt injection risk.

        Args:
            content: The README content.
            source_path: Path to the README file.

        Returns:
            README content wrapped with explicit boundary markers.
        """
        return f"""================================================================================
DOCUMENTATION (README.md - not agent instructions)
Source: {source_path}
================================================================================

{content.strip()}

================================================================================
END DOCUMENTATION
================================================================================"""

    def _format_prompt_section(
        self,
        layer: ContextLayer,
        sources: ContextSources,
    ) -> str | None:
        """Format a prompt section from a layer.

        Args:
            layer: The context layer.
            sources: ContextSources to record what was loaded.

        Returns:
            Formatted prompt section or None if no content.
        """
        content = layer.prompt
        readme_content: str | None = None

        # If the instruction file found was README.md, wrap it with boundaries
        if content is None and layer.readme and layer.prompt_filename == "README.md":
            readme_source_path = layer.prompt_source_path or layer.path / "README.md"
            readme_content = self._format_readme_section(layer.readme, readme_source_path)
        elif not content:
            return None

        # Determine source path for labeling
        if layer.name == "system-defaults":
            source_path = self._get_defaults_dir() / "NEXUS-DEFAULT.md"
            header = "## System Defaults"
        elif layer.name == "defaults":
            source_path = self._get_defaults_dir() / "NEXUS.md"
            header = "## Default Configuration"
        elif layer.name == "global":
            source_path = self._get_global_dir() / "NEXUS.md"
            header = "## Global Configuration"
        elif layer.name.startswith("ancestor:"):
            dirname = layer.name.split(":", 1)[1]
            source_path = layer.prompt_source_path or (layer.path / "NEXUS.md")
            header = f"## Ancestor Configuration ({dirname})"
        else:  # local
            source_path = layer.prompt_source_path or (layer.path / "NEXUS.md")
            header = "## Project Configuration"

        # Record source
        sources.prompt_sources.append(PromptSource(path=source_path, layer_name=layer.name))

        # Build final content
        if readme_content:
            # README as fallback - wrapped with documentation boundaries
            readme_source_path = layer.prompt_source_path or layer.path / "README.md"
            return f"""{header}
Source: {readme_source_path}

{readme_content}"""
        else:
            return f"""{header}
Source: {source_path}

{content.strip()}"""

    def _merge_mcp_servers(
        self,
        layers: list[ContextLayer],
        sources: ContextSources,
    ) -> list[MCPServerWithOrigin]:
        """Merge MCP servers from all layers.

        Later layers override earlier layers with same name.

        Supports two MCP config formats:
        - Official (Claude Desktop): {"mcpServers": {"name": {...config...}}}
        - NEXUS3: {"servers": [{"name": "...", ...config...}]}

        Args:
            layers: All context layers in order.
            sources: ContextSources to record what was loaded.

        Returns:
            List of MCP servers with origin tracking.
        """
        servers_by_name: dict[str, MCPServerWithOrigin] = {}

        for layer in layers:
            if not layer.mcp:
                continue

            mcp_path = layer.path / "mcp.json"
            sources.mcp_sources.append(mcp_path)

            # Support both official ("mcpServers" with dict) and NEXUS3 ("servers" with array) keys
            servers_data = layer.mcp.get("mcpServers") or layer.mcp.get("servers")
            if not servers_data:
                continue

            # Normalize to list of (name, server_dict) tuples
            if isinstance(servers_data, dict):
                # Official format: {"mcpServers": {"test": {...}}}
                server_items = list(servers_data.items())
            elif isinstance(servers_data, list):
                # NEXUS3 format: {"servers": [{"name": "test", ...}]}
                server_items = [
                    (s.get("name", f"unnamed-{i}"), s) for i, s in enumerate(servers_data)
                ]
            else:
                continue

            for server_name, server_data in server_items:
                # Ensure name is in the dict for MCPServerConfig validation
                if isinstance(server_data, dict):
                    server_data = {**server_data, "name": server_name}

                try:
                    server_config = MCPServerConfig.model_validate(server_data)
                    servers_by_name[server_config.name] = MCPServerWithOrigin(
                        config=server_config,
                        origin=layer.name,
                        source_path=mcp_path,
                    )
                except ValidationError as e:
                    # Sanitize: Don't include full config dict which may contain secrets
                    # Extract field locations from errors (loc can be empty for root validators)
                    error_fields = []
                    for err in e.errors():
                        loc = err.get("loc", ())
                        if loc:
                            error_fields.append(str(loc[-1]))
                        else:
                            # Root-level validation error (e.g., model_validator)
                            error_fields.append(err.get("type", "validation_error"))

                    # Create error context for detailed error reporting
                    context = MCPErrorContext(
                        server_name=server_name,
                        source_path=mcp_path,
                        source_layer=layer.name,
                    )
                    raise MCPConfigError(
                        f"Invalid MCP server config '{server_name}' in {mcp_path}: "
                        f"validation failed for fields: {error_fields}",
                        context=context,
                    ) from e
                except Exception as e:
                    # Create error context for detailed error reporting
                    context = MCPErrorContext(
                        server_name=server_name,
                        source_path=mcp_path,
                        source_layer=layer.name,
                    )
                    raise MCPConfigError(
                        f"Invalid MCP server config '{server_name}' in {mcp_path}: "
                        f"{type(e).__name__}",
                        context=context,
                    ) from e

        return list(servers_by_name.values())

    def load(self, is_repl: bool = True) -> LoadedContext:
        """Load and merge all context layers.

        Args:
            is_repl: Whether running in REPL mode (affects system info).

        Returns:
            LoadedContext with merged prompt, config, and MCP servers.
        """
        sources = ContextSources()
        layers: list[ContextLayer] = []
        prompt_sections: list[str] = []
        merged_config: dict[str, Any] = {}

        # 1. Load global layers (system-defaults from package + user's global)
        global_layers = self._load_global_layer()
        for global_layer in global_layers:
            layers.append(global_layer)
            if global_layer.name == "global":
                sources.global_dir = self._get_global_dir()

            section = self._format_prompt_section(global_layer, sources)
            if section:
                prompt_sections.append(section)

            if global_layer.config:
                merged_config = deep_merge(merged_config, global_layer.config)
                sources.config_sources.append(global_layer.path / "config.json")

        # 2. Load ancestors (exclude global dir to avoid loading it twice)
        global_dir = self._get_global_dir()
        ancestor_dirs = find_ancestor_config_dirs(
            self._cwd, self._config.ancestor_depth, exclude_paths=[global_dir]
        )
        sources.ancestor_dirs = [d.parent for d in ancestor_dirs]

        for ancestor_dir in ancestor_dirs:
            # Get the project directory name for labeling
            project_name = ancestor_dir.parent.name
            layer = self._load_layer(ancestor_dir, f"ancestor:{project_name}")
            layers.append(layer)

            section = self._format_prompt_section(layer, sources)
            if section:
                prompt_sections.append(section)

            if layer.config:
                merged_config = deep_merge(merged_config, layer.config)
                sources.config_sources.append(layer.path / "config.json")

        # 3. Load local
        local_dir = self._cwd / ".nexus3"
        if local_dir.is_dir():
            sources.local_dir = local_dir
            local_layer = self._load_layer(local_dir, "local")
            layers.append(local_layer)

            section = self._format_prompt_section(local_layer, sources)
            if section:
                prompt_sections.append(section)

            if local_layer.config:
                merged_config = deep_merge(merged_config, local_layer.config)
                sources.config_sources.append(local_layer.path / "config.json")

        # 4. Merge MCP servers
        mcp_servers = self._merge_mcp_servers(layers, sources)

        # 5. Build final prompt
        if prompt_sections:
            combined_prompt = "# System Configuration\n\n" + "\n\n".join(prompt_sections)
        else:
            combined_prompt = "You are a helpful AI assistant."

        # Add system info (pass cwd so agent sees its own working directory)
        combined_prompt += "\n\n" + get_system_info(is_repl=is_repl, cwd=self._cwd)

        return LoadedContext(
            system_prompt=combined_prompt,
            merged_config=merged_config,
            mcp_servers=mcp_servers,
            sources=sources,
        )

    def load_for_subagent(
        self,
        parent_context: LoadedContext | None = None,
    ) -> str:
        """Load context for a subagent, avoiding duplication with parent.

        Subagents get their cwd's NEXUS.md + parent's context (non-redundantly).

        Args:
            parent_context: The parent agent's loaded context.

        Returns:
            System prompt for the subagent.
        """
        # Find instruction file using priority search
        result = self._find_instruction_file(self._cwd)
        local_instruction = result.source_path if result else self._cwd / ".nexus3" / "NEXUS.md"

        if not parent_context:
            # No parent - just load normally
            ctx = self.load(is_repl=False)
            return ctx.system_prompt

        # Check if agent's instruction file is already in parent's context
        parent_paths = {s.path for s in parent_context.sources.prompt_sources}
        if local_instruction in parent_paths:
            # Already loaded by parent - use parent context as-is
            return parent_context.system_prompt

        # Build subagent prompt with its own environment info
        # (parent's environment shows parent's cwd, not subagent's)
        env_info = get_system_info(is_repl=False, cwd=self._cwd)

        # Strip parent's environment section to avoid duplication
        parent_prompt = parent_context.system_prompt
        if "# Environment" in parent_prompt:
            # Remove parent's environment section (we'll add subagent's)
            env_start = parent_prompt.find("# Environment")
            parent_prompt = parent_prompt[:env_start].rstrip()

        # Prepend subagent's instruction file
        if result and not result.is_readme:
            return f"""## Subagent Configuration
Source: {result.source_path}

{result.content.strip()}

{parent_prompt}

{env_info}"""

        # No local instruction file - use parent context with subagent's environment
        return f"""{parent_prompt}

{env_info}"""
