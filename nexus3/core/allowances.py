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
    - Execution allowances: Per-directory for execution identities (`exec`, `run_python`)
    - MCP allowances: Servers where all tools are allowed without per-tool confirmation

    Note: Read operations are unrestricted in TRUSTED mode.
    """
    # Path-based allowances for write operations
    write_files: set[Path] = field(default_factory=set)
    write_directories: set[Path] = field(default_factory=set)

    # Execution identities allowed in specific directories only.
    # Maps executable identity key -> set of allowed directories.
    exec_directories: dict[str, set[Path]] = field(default_factory=dict)

    # MCP servers where all tools are allowed (user chose "allow all" at connection)
    mcp_servers: set[str] = field(default_factory=set)

    # Individual MCP tools allowed (user chose "allow this tool always")
    mcp_tools: set[str] = field(default_factory=set)

    # GitLab skills allowed (format: "skill_name@instance_host")
    gitlab_skills: set[str] = field(default_factory=set)

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

    def is_exec_allowed(self, allowance_key: str, cwd: Path | None = None) -> bool:
        """Backwards-compatible alias for directory-scoped execution checks."""
        return self.is_exec_directory_allowed(allowance_key, cwd)

    def is_exec_directory_allowed(self, allowance_key: str, cwd: Path | None = None) -> bool:
        """Check if an execution identity is allowed in a specific directory."""
        if allowance_key not in self.exec_directories:
            return False

        # Check if cwd is within any allowed directory
        if cwd is None:
            cwd = Path.cwd()
        resolved_cwd = cwd.resolve()

        for allowed_dir in self.exec_directories[allowance_key]:
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

    def add_exec_directory(self, allowance_key: str, directory: Path) -> None:
        """Allow an execution identity in a specific directory."""
        if allowance_key not in self.exec_directories:
            self.exec_directories[allowance_key] = set()

        self.exec_directories[allowance_key].add(directory.resolve())

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

    def is_gitlab_skill_allowed(self, skill_name: str, instance_host: str) -> bool:
        """Check if GitLab skill@instance is allowed without confirmation."""
        key = f"{skill_name}@{instance_host}"
        return key in self.gitlab_skills

    def add_gitlab_skill(self, skill_name: str, instance_host: str) -> None:
        """Allow a GitLab skill@instance for this session."""
        key = f"{skill_name}@{instance_host}"
        self.gitlab_skills.add(key)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "write_files": [str(p) for p in self.write_files],
            "write_directories": [str(p) for p in self.write_directories],
            "exec_directories": {
                key: [str(p) for p in dirs]
                for key, dirs in self.exec_directories.items()
            },
            "mcp_servers": list(self.mcp_servers),
            "mcp_tools": list(self.mcp_tools),
            "gitlab_skills": list(self.gitlab_skills),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionAllowances:
        """Deserialize from persistence."""
        return cls(
            write_files={Path(p).resolve() for p in data.get("write_files", [])},
            write_directories={Path(p).resolve() for p in data.get("write_directories", [])},
            exec_directories={
                key: {Path(p).resolve() for p in dirs}
                for key, dirs in data.get("exec_directories", {}).items()
            },
            mcp_servers=set(data.get("mcp_servers", [])),
            mcp_tools=set(data.get("mcp_tools", [])),
            gitlab_skills=set(data.get("gitlab_skills", [])),
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
