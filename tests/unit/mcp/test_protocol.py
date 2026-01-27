"""Unit tests for MCP protocol types."""

import pytest

from nexus3.mcp.protocol import MCPTool, MCPToolResult


class TestMCPTool:
    """Tests for MCPTool dataclass and from_dict parsing."""

    def test_from_dict_minimal(self) -> None:
        """Test parsing tool with only required fields."""
        data = {
            "name": "test_tool",
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "test_tool"
        assert tool.description == ""
        assert tool.input_schema == {}
        assert tool.title is None
        assert tool.output_schema is None
        assert tool.icons is None
        assert tool.annotations is None

    def test_from_dict_basic(self) -> None:
        """Test parsing tool with basic fields."""
        data = {
            "name": "echo",
            "description": "Echo the input",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
            },
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "echo"
        assert tool.description == "Echo the input"
        assert tool.input_schema == data["inputSchema"]
        assert tool.title is None
        assert tool.output_schema is None
        assert tool.icons is None
        assert tool.annotations is None

    def test_from_dict_with_title(self) -> None:
        """Test parsing tool with title field (P1.5)."""
        data = {
            "name": "search",
            "description": "Search for files",
            "title": "File Search Tool",
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "search"
        assert tool.title == "File Search Tool"

    def test_from_dict_with_output_schema(self) -> None:
        """Test parsing tool with outputSchema field (P1.5)."""
        data = {
            "name": "get_user",
            "description": "Get user info",
            "outputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["id", "name"],
            },
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "get_user"
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert "id" in tool.output_schema["properties"]
        assert tool.output_schema["required"] == ["id", "name"]

    def test_from_dict_with_icons(self) -> None:
        """Test parsing tool with icons field (P1.5)."""
        data = {
            "name": "database",
            "description": "Database operations",
            "icons": [
                {"url": "https://example.com/icon.png", "mimeType": "image/png"},
                {"url": "https://example.com/icon.svg", "mimeType": "image/svg+xml"},
            ],
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "database"
        assert tool.icons is not None
        assert len(tool.icons) == 2
        assert tool.icons[0]["url"] == "https://example.com/icon.png"
        assert tool.icons[1]["mimeType"] == "image/svg+xml"

    def test_from_dict_with_annotations(self) -> None:
        """Test parsing tool with annotations field (P1.5)."""
        data = {
            "name": "write_file",
            "description": "Write to a file",
            "annotations": {
                "destructive": True,
                "requiresConfirmation": True,
                "category": "filesystem",
            },
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "write_file"
        assert tool.annotations is not None
        assert tool.annotations["destructive"] is True
        assert tool.annotations["requiresConfirmation"] is True
        assert tool.annotations["category"] == "filesystem"

    def test_from_dict_all_optional_fields(self) -> None:
        """Test parsing tool with all optional fields set (P1.5)."""
        data = {
            "name": "complete_tool",
            "description": "A tool with all optional fields",
            "inputSchema": {
                "type": "object",
                "properties": {"input": {"type": "string"}},
            },
            "title": "Complete Tool",
            "outputSchema": {
                "type": "object",
                "properties": {"output": {"type": "string"}},
            },
            "icons": [{"url": "https://example.com/icon.png"}],
            "annotations": {"version": "1.0", "stable": True},
        }
        tool = MCPTool.from_dict(data)

        assert tool.name == "complete_tool"
        assert tool.description == "A tool with all optional fields"
        assert tool.input_schema == data["inputSchema"]
        assert tool.title == "Complete Tool"
        assert tool.output_schema == data["outputSchema"]
        assert tool.icons == [{"url": "https://example.com/icon.png"}]
        assert tool.annotations == {"version": "1.0", "stable": True}


class TestMCPToolResult:
    """Tests for MCPToolResult dataclass and from_dict parsing."""

    def test_from_dict_minimal(self) -> None:
        """Test parsing result with minimal fields."""
        data = {}
        result = MCPToolResult.from_dict(data)

        assert result.content == []
        assert result.is_error is False
        assert result.structured_content is None

    def test_from_dict_basic(self) -> None:
        """Test parsing result with basic fields."""
        data = {
            "content": [{"type": "text", "text": "Hello, world!"}],
            "isError": False,
        }
        result = MCPToolResult.from_dict(data)

        assert len(result.content) == 1
        assert result.content[0]["text"] == "Hello, world!"
        assert result.is_error is False
        assert result.structured_content is None

    def test_from_dict_error_result(self) -> None:
        """Test parsing error result."""
        data = {
            "content": [{"type": "text", "text": "Something went wrong"}],
            "isError": True,
        }
        result = MCPToolResult.from_dict(data)

        assert result.is_error is True
        assert result.to_text() == "Something went wrong"

    def test_from_dict_with_structured_content(self) -> None:
        """Test parsing result with structuredContent field (P1.6)."""
        data = {
            "content": [{"type": "text", "text": "User found"}],
            "isError": False,
            "structuredContent": {
                "user": {
                    "id": 123,
                    "name": "Alice",
                    "email": "alice@example.com",
                },
                "timestamp": "2026-01-27T10:00:00Z",
            },
        }
        result = MCPToolResult.from_dict(data)

        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["user"]["id"] == 123
        assert result.structured_content["user"]["name"] == "Alice"
        assert result.structured_content["timestamp"] == "2026-01-27T10:00:00Z"

    def test_from_dict_structured_content_with_array(self) -> None:
        """Test parsing result with array in structuredContent."""
        data = {
            "content": [],
            "structuredContent": {
                "items": [
                    {"id": 1, "name": "Item 1"},
                    {"id": 2, "name": "Item 2"},
                    {"id": 3, "name": "Item 3"},
                ],
                "total": 3,
            },
        }
        result = MCPToolResult.from_dict(data)

        assert result.structured_content is not None
        assert len(result.structured_content["items"]) == 3
        assert result.structured_content["total"] == 3

    def test_from_dict_structured_content_empty_content(self) -> None:
        """Test structuredContent can be used without text content."""
        data = {
            "content": [],
            "isError": False,
            "structuredContent": {"status": "ok", "count": 42},
        }
        result = MCPToolResult.from_dict(data)

        assert result.content == []
        assert result.to_text() == ""
        assert result.structured_content == {"status": "ok", "count": 42}

    def test_to_text_ignores_structured_content(self) -> None:
        """Test to_text() only extracts from content, not structuredContent."""
        result = MCPToolResult(
            content=[{"type": "text", "text": "Text content"}],
            is_error=False,
            structured_content={"data": "Should not appear in to_text()"},
        )

        text = result.to_text()
        assert text == "Text content"
        assert "Should not appear" not in text


class TestMCPToolDataclass:
    """Tests for MCPTool dataclass construction."""

    def test_direct_construction_defaults(self) -> None:
        """Test creating MCPTool directly with defaults."""
        tool = MCPTool(name="test", description="Test tool")

        assert tool.name == "test"
        assert tool.description == "Test tool"
        assert tool.input_schema == {}
        assert tool.title is None
        assert tool.output_schema is None
        assert tool.icons is None
        assert tool.annotations is None

    def test_direct_construction_all_fields(self) -> None:
        """Test creating MCPTool with all fields specified."""
        tool = MCPTool(
            name="full",
            description="Full tool",
            input_schema={"type": "object"},
            title="Full Tool",
            output_schema={"type": "string"},
            icons=[{"url": "icon.png"}],
            annotations={"key": "value"},
        )

        assert tool.name == "full"
        assert tool.title == "Full Tool"
        assert tool.output_schema == {"type": "string"}
        assert tool.icons == [{"url": "icon.png"}]
        assert tool.annotations == {"key": "value"}


class TestMCPToolResultDataclass:
    """Tests for MCPToolResult dataclass construction."""

    def test_direct_construction_defaults(self) -> None:
        """Test creating MCPToolResult directly with defaults."""
        result = MCPToolResult()

        assert result.content == []
        assert result.is_error is False
        assert result.structured_content is None

    def test_direct_construction_with_structured_content(self) -> None:
        """Test creating MCPToolResult with structured_content."""
        result = MCPToolResult(
            content=[{"type": "text", "text": "OK"}],
            is_error=False,
            structured_content={"result": "success"},
        )

        assert result.content[0]["text"] == "OK"
        assert result.structured_content == {"result": "success"}
