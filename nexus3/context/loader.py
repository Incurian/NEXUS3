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

from nexus3.config.load_utils import load_json_file
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


@dataclass
class ContextLayer:
    """A single layer of context (global, ancestor, or local)."""

    name: str  # "global", "ancestor:dirname", "local"
    path: Path  # Directory path

    prompt: str | None = None  # NEXUS.md content
    readme: str | None = None  # README.md content
    config: dict[str, Any] | None = None  # config.json content (pre-validation)
    mcp: dict[str, Any] | None = None  # mcp.json content


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
            return path.read_text(encoding="utf-8")
        return None

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        """Load a JSON file if it exists.

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed JSON as dict, empty dict for empty files, or None if missing.

        Raises:
            ContextLoadError: If file contains invalid JSON or non-dict content.
        """
        if not path.is_file():
            return None

        try:
            return load_json_file(path)
        except LoadError as e:
            raise ContextLoadError(e.message) from e

    def _load_layer(self, directory: Path, layer_name: str) -> ContextLayer:
        """Load all context files from a directory.

        Args:
            directory: Directory to load from (the .nexus3 dir, or project root for legacy).
            layer_name: Name for this layer (e.g., "global", "ancestor:company").

        Returns:
            ContextLayer with loaded content.
        """
        layer = ContextLayer(name=layer_name, path=directory)

        # Load NEXUS.md - check in .nexus3 first, then project root for legacy
        nexus_path = directory / "NEXUS.md"
        if not nexus_path.is_file() and directory.name == ".nexus3":
            # Legacy: also check parent directory (project root)
            legacy_path = directory.parent / "NEXUS.md"
            if legacy_path.is_file():
                nexus_path = legacy_path
        layer.prompt = self._load_file(nexus_path)

        # Load README.md (only from parent of .nexus3, not from .nexus3 itself)
        # For .nexus3/ dirs, look for README.md in the parent (project root)
        readme_path = directory.parent / "README.md"
        if directory.name == ".nexus3" and readme_path.is_file():
            layer.readme = self._load_file(readme_path)
        elif directory.name != ".nexus3":
            # Global or other directory structure
            readme_in_dir = directory / "README.md"
            if readme_in_dir.is_file():
                layer.readme = self._load_file(readme_in_dir)

        # Load config.json - ContextLoadError propagates for fail-fast behavior
        config_path = directory / "config.json"
        layer.config = self._load_json(config_path)

        # Load mcp.json - ContextLoadError propagates for fail-fast behavior
        mcp_path = directory / "mcp.json"
        layer.mcp = self._load_json(mcp_path)

        return layer

    def _load_global_layer(self) -> ContextLayer | None:
        """Load the global layer with fallback to defaults for missing components.

        If global dir exists and has config/mcp but no prompt, falls back to
        defaults for the prompt while keeping global's config/mcp. This ensures
        the defaults NEXUS.md is always loaded even when user has partial
        global configuration.
        """
        global_dir = self._get_global_dir()
        defaults_dir = self._get_defaults_dir()

        global_layer: ContextLayer | None = None
        defaults_layer: ContextLayer | None = None

        # Load global layer if exists
        if global_dir.is_dir():
            global_layer = self._load_layer(global_dir, "global")

        # Load defaults layer if exists
        if defaults_dir.is_dir():
            defaults_layer = self._load_layer(defaults_dir, "defaults")

        # Merge strategy: global takes precedence, but fall back to defaults for missing
        if global_layer is not None:
            # If global has no prompt, use defaults prompt
            if not global_layer.prompt and defaults_layer and defaults_layer.prompt:
                global_layer.prompt = defaults_layer.prompt
                # Update layer name to indicate merged source
                global_layer.name = "global+defaults"

            # Return global if it has any content
            if global_layer.prompt or global_layer.config or global_layer.mcp:
                return global_layer

        # Fall back to defaults entirely if no global content
        return defaults_layer

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

        # Determine README source path (README.md is in parent of .nexus3)
        if layer.path.name == ".nexus3":
            readme_source_path = layer.path.parent / "README.md"
        else:
            readme_source_path = layer.path / "README.md"

        # Handle README.md based on config
        if content is None and self._config.readme_as_fallback and layer.readme:
            # README used as fallback - wrap with boundaries
            readme_content = self._format_readme_section(layer.readme, readme_source_path)
        elif self._config.include_readme and layer.readme:
            # Include README after NEXUS.md - wrap with boundaries
            formatted_readme = self._format_readme_section(layer.readme, readme_source_path)
            if content:
                readme_content = formatted_readme  # Will be appended after content
            else:
                readme_content = formatted_readme
        elif not content:
            return None

        # Determine source path for labeling
        if layer.name == "defaults":
            source_path = self._get_defaults_dir() / "NEXUS.md"
            header = "## Default Configuration"
        elif layer.name == "global":
            source_path = self._get_global_dir() / "NEXUS.md"
            header = "## Global Configuration"
        elif layer.name.startswith("ancestor:"):
            dirname = layer.name.split(":", 1)[1]
            source_path = layer.path / "NEXUS.md"
            header = f"## Ancestor Configuration ({dirname})"
        else:  # local
            source_path = layer.path / "NEXUS.md"
            header = "## Project Configuration"

        # Record source
        sources.prompt_sources.append(PromptSource(path=source_path, layer_name=layer.name))

        # Build final content
        if content and readme_content:
            # NEXUS.md content followed by wrapped README
            return f"""{header}
Source: {source_path}

{content.strip()}

{readme_content}"""
        elif readme_content:
            # Only README (as fallback) - include header but content is wrapped README
            return f"""{header}
Source: {readme_source_path}

{readme_content}"""
        else:
            # Only NEXUS.md content
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

        # 1. Load global (with fallback to defaults)
        global_layer = self._load_global_layer()
        if global_layer:
            layers.append(global_layer)
            if global_layer.name == "global":
                sources.global_dir = self._get_global_dir()

            section = self._format_prompt_section(global_layer, sources)
            if section:
                prompt_sections.append(section)

            if global_layer.config:
                merged_config = deep_merge(merged_config, global_layer.config)
                sources.config_sources.append(global_layer.path / "config.json")

        # 2. Load ancestors
        ancestor_dirs = find_ancestor_config_dirs(self._cwd, self._config.ancestor_depth)
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
        # Load agent's local NEXUS.md
        local_nexus = self._cwd / ".nexus3" / "NEXUS.md"

        # Also check for NEXUS.md directly in cwd (legacy support)
        if not local_nexus.is_file():
            local_nexus = self._cwd / "NEXUS.md"

        if not parent_context:
            # No parent - just load normally
            ctx = self.load(is_repl=False)
            return ctx.system_prompt

        # Check if agent's NEXUS.md is already in parent's context
        parent_paths = {s.path for s in parent_context.sources.prompt_sources}
        if local_nexus in parent_paths:
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

        # Load agent's local NEXUS.md and prepend
        if local_nexus.is_file():
            agent_prompt = local_nexus.read_text(encoding="utf-8")
            return f"""## Subagent Configuration
Source: {local_nexus}

{agent_prompt.strip()}

{parent_prompt}

{env_info}"""

        # No local NEXUS.md - use parent context with subagent's environment
        return f"""{parent_prompt}

{env_info}"""
