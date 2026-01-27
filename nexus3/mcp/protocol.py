"""MCP protocol types.

Defines the data structures specific to MCP (Model Context Protocol),
which builds on JSON-RPC 2.0 with additional semantics for tools,
resources, and prompts.

MCP Spec: https://modelcontextprotocol.io/specification/2025-11-25
"""

from dataclasses import dataclass, field
from typing import Any

# Maximum size for MCP tool output to prevent memory exhaustion from malicious servers
MAX_MCP_OUTPUT_SIZE: int = 10 * 1024 * 1024  # 10 MB


@dataclass
class MCPTool:
    """Tool definition from an MCP server.

    Attributes:
        name: Unique identifier for the tool.
        description: Human-readable description of what the tool does.
        input_schema: JSON Schema describing the tool's parameters.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPTool":
        """Create from MCP server response."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", {}),
        )


@dataclass
class MCPToolResult:
    """Result from an MCP tool invocation.

    MCP returns results as a list of content items (text, images, etc).

    Attributes:
        content: List of content items from the tool.
        is_error: Whether the result represents an error.
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False

    def to_text(self) -> str:
        """Extract text content from result with size limit.

        Joins all text-type content items with newlines.
        Truncates if total size exceeds MAX_MCP_OUTPUT_SIZE.
        """
        texts = []
        total_size = 0

        for item in self.content:
            if item.get("type") == "text":
                text = item.get("text", "")
                total_size += len(text)
                if total_size > MAX_MCP_OUTPUT_SIZE:
                    texts.append(
                        f"\n... [truncated, exceeded {MAX_MCP_OUTPUT_SIZE // 1024 // 1024}MB limit]"
                    )
                    break
                texts.append(text)

        return "\n".join(texts)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPToolResult":
        """Create from MCP server response."""
        return cls(
            content=data.get("content", []),
            is_error=data.get("isError", False),
        )


@dataclass
class MCPServerInfo:
    """Server information from MCP initialization.

    Attributes:
        name: Server name.
        version: Server version.
        capabilities: Server capabilities (tools, resources, prompts, etc).
    """

    name: str
    version: str
    capabilities: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerInfo":
        """Create from initialize response."""
        server_info = data.get("serverInfo", {})
        return cls(
            name=server_info.get("name", "unknown"),
            version=server_info.get("version", "unknown"),
            capabilities=data.get("capabilities", {}),
        )


@dataclass
class MCPClientInfo:
    """Client information sent during initialization.

    Attributes:
        name: Client name.
        version: Client version.
    """

    name: str = "nexus3"
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, str]:
        """Convert to dict for MCP protocol."""
        return {"name": self.name, "version": self.version}


# MCP protocol version we support
PROTOCOL_VERSION = "2025-11-25"
