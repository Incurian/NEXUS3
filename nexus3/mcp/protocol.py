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
        title: Human-readable title for display (optional, may differ from name).
        output_schema: JSON Schema for output validation (optional, for structured responses).
        icons: Icon identifiers for UI display (optional, server-provided).
        annotations: Additional metadata/annotations (optional, server-specific extensions).
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    output_schema: dict[str, Any] | None = None
    icons: list[dict[str, Any]] | None = None
    annotations: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPTool":
        """Create from MCP server response."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", {}),
            title=data.get("title"),
            output_schema=data.get("outputSchema"),
            icons=data.get("icons"),
            annotations=data.get("annotations"),
        )


@dataclass
class MCPToolResult:
    """Result from an MCP tool invocation.

    MCP returns results as a list of content items (text, images, etc).

    Attributes:
        content: List of content items from the tool (text, images, resources).
        is_error: Whether the result represents an error.
        structured_content: Structured content blocks (optional, alternative to text-only content).
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    structured_content: dict[str, Any] | None = None

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
            structured_content=data.get("structuredContent"),
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


@dataclass
class MCPResource:
    """Resource definition from an MCP server.

    Resources are URI-addressable content that servers make available
    to clients, such as files, database records, or API responses.

    Attributes:
        uri: Unique identifier for the resource.
        name: Human-readable name.
        description: Optional description of what the resource contains.
        mime_type: MIME type of the resource content.
        annotations: Additional metadata/annotations (optional).
    """

    uri: str
    name: str
    description: str | None = None
    mime_type: str = "text/plain"
    annotations: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPResource":
        """Create from MCP server response."""
        return cls(
            uri=data["uri"],
            name=data.get("name", data["uri"]),
            description=data.get("description"),
            mime_type=data.get("mimeType", "text/plain"),
            annotations=data.get("annotations"),
        )


@dataclass
class MCPResourceContent:
    """Content of a resource from resources/read.

    Attributes:
        uri: The resource URI this content belongs to.
        mime_type: MIME type of the content.
        text: Text content (for text-based resources).
        blob: Base64-encoded binary content (for binary resources).
    """

    uri: str
    mime_type: str = "text/plain"
    text: str | None = None
    blob: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPResourceContent":
        """Create from MCP server response."""
        return cls(
            uri=data["uri"],
            mime_type=data.get("mimeType", "text/plain"),
            text=data.get("text"),
            blob=data.get("blob"),
        )


@dataclass
class MCPPromptArgument:
    """Argument definition for an MCP prompt.

    Attributes:
        name: Argument name.
        description: Optional description.
        required: Whether the argument is required. Default True.
    """

    name: str
    description: str | None = None
    required: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPPromptArgument":
        """Create from MCP server response."""
        return cls(
            name=data["name"],
            description=data.get("description"),
            required=data.get("required", True),
        )


@dataclass
class MCPPrompt:
    """Prompt definition from an MCP server.

    Prompts are reusable templates that servers provide for common
    interactions, with optional arguments for customization.

    Attributes:
        name: Unique identifier for the prompt.
        description: Optional description of what the prompt does.
        arguments: List of argument definitions.
    """

    name: str
    description: str | None = None
    arguments: list[MCPPromptArgument] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPPrompt":
        """Create from MCP server response."""
        args_data = data.get("arguments", [])
        return cls(
            name=data["name"],
            description=data.get("description"),
            arguments=[MCPPromptArgument.from_dict(a) for a in args_data],
        )


@dataclass
class MCPPromptMessage:
    """A message in a prompt result.

    Attributes:
        role: Message role (user, assistant, system).
        content: Message content (text or structured).
    """

    role: str
    content: dict[str, Any] | str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPPromptMessage":
        """Create from MCP server response."""
        return cls(
            role=data["role"],
            content=data["content"],
        )

    def get_text(self) -> str:
        """Extract text from content."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, dict):
            return self.content.get("text", str(self.content))
        return str(self.content)


@dataclass
class MCPPromptResult:
    """Result from prompts/get.

    Attributes:
        description: Description of this prompt instance.
        messages: List of messages to send.
    """

    description: str = ""
    messages: list[MCPPromptMessage] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPPromptResult":
        """Create from MCP server response."""
        messages_data = data.get("messages", [])
        return cls(
            description=data.get("description", ""),
            messages=[MCPPromptMessage.from_dict(m) for m in messages_data],
        )


# MCP protocol version we support
PROTOCOL_VERSION = "2025-11-25"
