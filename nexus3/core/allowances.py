"""Session allowances for TRUSTED mode.

This module defines SessionAllowances, which stores user's "allow always"
decisions during a session. These are persisted with the session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionAllowances:
    """Dynamic allowances for TRUSTED mode.

    Stores user's "allow always" decisions during a session.
    These are persisted with the session.

    Categories:
    - Write allowances: Per-file or per-directory for write operations
    - Execution allowances: Per-directory or global for execution tools (bash, run_python)
    - MCP allowances: Servers where all tools are allowed without per-tool confirmation

    Note: Read operations are unrestricted in TRUSTED mode.
    """
    # Path-based allowances for write operations
    write_files: set[Path] = field(default_factory=set)
    write_directories: set[Path] = field(default_factory=set)

    # Execution tools allowed globally (any working directory)
    exec_global: set[str] = field(default_factory=set)

    # Execution tools allowed in specific directories only
    # Maps tool_name -> set of allowed directories
    exec_directories: dict[str, set[Path]] = field(default_factory=dict)

    # MCP servers where all tools are allowed (user chose "allow all" at connection)
    mcp_servers: set[str] = field(default_factory=set)

    # Individual MCP tools allowed (user chose "allow this tool always")
    mcp_tools: set[str] = field(default_factory=set)

    def is_write_allowed(self, path: Path) -> bool:
        """Check if path is covered by an existing write allowance."""
        resolved = path.resolve()

        # Check exact file match
        if resolved in self.write_files:
            return True

        # Check directory allowances
        for allowed_dir in self.write_directories:
            try:
                if resolved.is_relative_to(allowed_dir):
                    return True
            except (OSError, ValueError):
                continue

        return False

    def is_exec_allowed(self, tool_name: str, cwd: Path | None = None) -> bool:
        """Check if execution tool is allowed.

        Args:
            tool_name: The tool (e.g., "bash_safe", "run_python")
            cwd: Working directory for the execution (None = current directory)

        Returns:
            True if the tool is allowed globally or in the given directory.
        """
        # Check global allowance first
        if tool_name in self.exec_global:
            return True

        # Check directory-specific allowance
        return self.is_exec_directory_allowed(tool_name, cwd)

    def is_exec_directory_allowed(self, tool_name: str, cwd: Path | None = None) -> bool:
        """Check if execution tool is allowed in a specific directory.

        Unlike is_exec_allowed, this does NOT check global allowances.
        Used for tools like run_python where global allow is too permissive.

        Args:
            tool_name: The tool (e.g., "run_python")
            cwd: Working directory for the execution (None = current directory)

        Returns:
            True if the tool is allowed in the given directory.
        """
        if tool_name not in self.exec_directories:
            return False

        # Check if cwd is within any allowed directory
        if cwd is None:
            cwd = Path.cwd()
        resolved_cwd = cwd.resolve()

        for allowed_dir in self.exec_directories[tool_name]:
            try:
                if resolved_cwd.is_relative_to(allowed_dir):
                    return True
            except (OSError, ValueError):
                continue

        return False

    def add_write_file(self, path: Path) -> None:
        """Add a file to the write allowance list."""
        self.write_files.add(path.resolve())

    def add_write_directory(self, path: Path) -> None:
        """Add a directory to the write allowance list."""
        self.write_directories.add(path.resolve())

    def add_exec_global(self, tool_name: str) -> None:
        """Allow execution tool globally (any directory)."""
        self.exec_global.add(tool_name)
        # Remove from directory-specific if present (global supersedes)
        self.exec_directories.pop(tool_name, None)

    def add_exec_directory(self, tool_name: str, directory: Path) -> None:
        """Allow execution tool in a specific directory.

        If the tool is already globally allowed, this is a no-op.
        Otherwise, adds the directory to the list of allowed directories.
        """
        # Don't add directory restriction if already globally allowed
        if tool_name in self.exec_global:
            return

        if tool_name not in self.exec_directories:
            self.exec_directories[tool_name] = set()

        self.exec_directories[tool_name].add(directory.resolve())

    def is_mcp_server_allowed(self, server_name: str) -> bool:
        """Check if MCP server tools are allowed without per-tool confirmation."""
        return server_name in self.mcp_servers

    def add_mcp_server(self, server_name: str) -> None:
        """Allow all tools from an MCP server for this session."""
        self.mcp_servers.add(server_name)

    def is_mcp_tool_allowed(self, tool_name: str) -> bool:
        """Check if a specific MCP tool is allowed without confirmation."""
        return tool_name in self.mcp_tools

    def add_mcp_tool(self, tool_name: str) -> None:
        """Allow a specific MCP tool for this session."""
        self.mcp_tools.add(tool_name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "write_files": [str(p) for p in self.write_files],
            "write_directories": [str(p) for p in self.write_directories],
            "exec_global": list(self.exec_global),
            "exec_directories": {
                tool: [str(p) for p in dirs]
                for tool, dirs in self.exec_directories.items()
            },
            "mcp_servers": list(self.mcp_servers),
            "mcp_tools": list(self.mcp_tools),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionAllowances:
        """Deserialize from persistence."""
        return cls(
            write_files={Path(p) for p in data.get("write_files", [])},
            write_directories={Path(p) for p in data.get("write_directories", [])},
            exec_global=set(data.get("exec_global", [])),
            exec_directories={
                tool: {Path(p) for p in dirs}
                for tool, dirs in data.get("exec_directories", {}).items()
            },
            mcp_servers=set(data.get("mcp_servers", [])),
            mcp_tools=set(data.get("mcp_tools", [])),
        )

    # Backwards compatibility
    @property
    def allowed_files(self) -> set[Path]:
        return self.write_files

    @property
    def allowed_directories(self) -> set[Path]:
        return self.write_directories

    def is_path_allowed(self, path: Path) -> bool:
        """Backwards compatibility alias for is_write_allowed."""
        return self.is_write_allowed(path)

    def add_file(self, path: Path) -> None:
        """Backwards compatibility alias for add_write_file."""
        self.add_write_file(path)

    def add_directory(self, path: Path) -> None:
        """Backwards compatibility alias for add_write_directory."""
        self.add_write_directory(path)


# Backwards compatibility alias
WriteAllowances = SessionAllowances
