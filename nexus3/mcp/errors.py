"""MCP error context for improved error messages."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.context.loader import MCPServerWithOrigin


@dataclass
class MCPErrorContext:
    """Context for MCP errors to enable detailed error messages.

    Attributes:
        server_name: Name of the MCP server (e.g., "github", "filesystem")
        source_path: Path to the config file (e.g., ~/.nexus3/mcp.json)
        source_layer: Layer name (e.g., "global", "project", "ancestor")
        command: The command that was attempted (if applicable)
        stderr_lines: Last N lines of stderr (for crash errors)
    """

    server_name: str
    source_path: Path | str | None = None
    source_layer: str | None = None
    command: list[str] | None = None
    stderr_lines: list[str] | None = None

    @classmethod
    def from_server_with_origin(
        cls, server_with_origin: "MCPServerWithOrigin"
    ) -> "MCPErrorContext":
        """Create context from MCPServerWithOrigin (from loader.py)."""
        return cls(
            server_name=server_with_origin.config.name,
            source_path=server_with_origin.source_path,
            source_layer=server_with_origin.origin,
            command=server_with_origin.config.get_command_list()
            if server_with_origin.config.command
            else None,
        )
