"""Unit tests for MCP protocol types."""

import pytest

from nexus3.mcp.protocol import (
    MCPPrompt,
    MCPPromptArgument,
    MCPPromptMessage,
    MCPPromptResult,
    MCPResource,
    MCPResourceContent,
    MCPTool,
    MCPToolResult,
)


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


class TestMCPPromptArgument:
    """Tests for MCPPromptArgument dataclass and from_dict parsing."""

    def test_from_dict_full(self) -> None:
        """Test parsing argument with all fields."""
        data = {
            "name": "language",
            "description": "Programming language",
            "required": True,
        }
        arg = MCPPromptArgument.from_dict(data)
        assert arg.name == "language"
        assert arg.description == "Programming language"
        assert arg.required is True

    def test_from_dict_minimal(self) -> None:
        """Test parsing argument with only required fields."""
        data = {"name": "optional_arg"}
        arg = MCPPromptArgument.from_dict(data)
        assert arg.name == "optional_arg"
        assert arg.description is None
        assert arg.required is True  # Default is True per MCP spec

    def test_from_dict_not_required(self) -> None:
        """Test parsing argument with required=False."""
        data = {"name": "optional", "required": False}
        arg = MCPPromptArgument.from_dict(data)
        assert arg.name == "optional"
        assert arg.required is False


class TestMCPPrompt:
    """Tests for MCPPrompt dataclass and from_dict parsing."""

    def test_from_dict_with_arguments(self) -> None:
        """Test parsing prompt with arguments."""
        data = {
            "name": "code_review",
            "description": "Review code",
            "arguments": [
                {"name": "language", "required": True},
                {"name": "focus", "required": False},
            ],
        }
        prompt = MCPPrompt.from_dict(data)
        assert prompt.name == "code_review"
        assert prompt.description == "Review code"
        assert len(prompt.arguments) == 2
        assert prompt.arguments[0].name == "language"
        assert prompt.arguments[0].required is True
        assert prompt.arguments[1].name == "focus"
        assert prompt.arguments[1].required is False

    def test_from_dict_minimal(self) -> None:
        """Test parsing prompt with only required fields."""
        data = {"name": "simple_prompt"}
        prompt = MCPPrompt.from_dict(data)
        assert prompt.name == "simple_prompt"
        assert prompt.description is None
        assert prompt.arguments == []

    def test_from_dict_no_arguments(self) -> None:
        """Test parsing prompt without arguments array."""
        data = {
            "name": "no_args",
            "description": "A prompt with no arguments",
        }
        prompt = MCPPrompt.from_dict(data)
        assert prompt.name == "no_args"
        assert prompt.arguments == []


class TestMCPPromptMessage:
    """Tests for MCPPromptMessage dataclass and from_dict parsing."""

    def test_from_dict_structured_content(self) -> None:
        """Test parsing message with structured content."""
        data = {
            "role": "user",
            "content": {"type": "text", "text": "Hello"},
        }
        msg = MCPPromptMessage.from_dict(data)
        assert msg.role == "user"
        assert msg.get_text() == "Hello"

    def test_get_text_string_content(self) -> None:
        """Test get_text with plain string content."""
        msg = MCPPromptMessage(role="user", content="Plain text")
        assert msg.get_text() == "Plain text"

    def test_get_text_dict_without_text(self) -> None:
        """Test get_text with dict content without text key."""
        msg = MCPPromptMessage(role="assistant", content={"type": "image"})
        # Should return string representation of the dict
        assert "type" in msg.get_text()
        assert "image" in msg.get_text()

    def test_from_dict_assistant_role(self) -> None:
        """Test parsing assistant message."""
        data = {
            "role": "assistant",
            "content": {"type": "text", "text": "I can help with that."},
        }
        msg = MCPPromptMessage.from_dict(data)
        assert msg.role == "assistant"
        assert msg.get_text() == "I can help with that."


class TestMCPPromptResult:
    """Tests for MCPPromptResult dataclass and from_dict parsing."""

    def test_from_dict_full(self) -> None:
        """Test parsing result with all fields."""
        data = {
            "description": "Greeting prompt",
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "Hello"}},
            ],
        }
        result = MCPPromptResult.from_dict(data)
        assert result.description == "Greeting prompt"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].get_text() == "Hello"

    def test_from_dict_multiple_messages(self) -> None:
        """Test parsing result with multiple messages."""
        data = {
            "description": "Multi-turn prompt",
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "Hello"}},
                {"role": "assistant", "content": {"type": "text", "text": "Hi there!"}},
                {"role": "user", "content": {"type": "text", "text": "How are you?"}},
            ],
        }
        result = MCPPromptResult.from_dict(data)
        assert len(result.messages) == 3
        assert result.messages[0].role == "user"
        assert result.messages[1].role == "assistant"
        assert result.messages[2].role == "user"

    def test_from_dict_minimal(self) -> None:
        """Test parsing result with minimal fields."""
        data = {}
        result = MCPPromptResult.from_dict(data)
        assert result.description == ""
        assert result.messages == []

    def test_from_dict_empty_messages(self) -> None:
        """Test parsing result with empty messages array."""
        data = {
            "description": "Empty prompt",
            "messages": [],
        }
        result = MCPPromptResult.from_dict(data)
        assert result.description == "Empty prompt"
        assert result.messages == []


class TestMCPResource:
    """Tests for MCPResource dataclass and from_dict parsing."""

    def test_from_dict_full(self) -> None:
        """Test parsing resource with all fields."""
        data = {
            "uri": "file:///test.txt",
            "name": "Test File",
            "description": "A test file",
            "mimeType": "text/plain",
            "annotations": {"custom": "value"},
        }
        resource = MCPResource.from_dict(data)
        assert resource.uri == "file:///test.txt"
        assert resource.name == "Test File"
        assert resource.description == "A test file"
        assert resource.mime_type == "text/plain"
        assert resource.annotations == {"custom": "value"}

    def test_from_dict_minimal(self) -> None:
        """Test parsing resource with only required fields."""
        data = {"uri": "file:///minimal.txt"}
        resource = MCPResource.from_dict(data)
        assert resource.uri == "file:///minimal.txt"
        assert resource.name == "file:///minimal.txt"  # Falls back to URI
        assert resource.description is None
        assert resource.mime_type == "text/plain"
        assert resource.annotations is None

    def test_from_dict_with_name_and_description(self) -> None:
        """Test parsing resource with name and description."""
        data = {
            "uri": "db://users/1",
            "name": "User Record",
            "description": "First user record",
        }
        resource = MCPResource.from_dict(data)
        assert resource.uri == "db://users/1"
        assert resource.name == "User Record"
        assert resource.description == "First user record"
        assert resource.mime_type == "text/plain"  # Default

    def test_from_dict_with_mime_type(self) -> None:
        """Test parsing resource with explicit mimeType."""
        data = {
            "uri": "file:///data.json",
            "name": "Data",
            "mimeType": "application/json",
        }
        resource = MCPResource.from_dict(data)
        assert resource.uri == "file:///data.json"
        assert resource.mime_type == "application/json"

    def test_direct_construction(self) -> None:
        """Test creating MCPResource directly."""
        resource = MCPResource(
            uri="file:///readme.md",
            name="README",
            description="Project readme",
            mime_type="text/markdown",
        )
        assert resource.uri == "file:///readme.md"
        assert resource.name == "README"
        assert resource.description == "Project readme"
        assert resource.mime_type == "text/markdown"
        assert resource.annotations is None


class TestMCPResourceContent:
    """Tests for MCPResourceContent dataclass and from_dict parsing."""

    def test_from_dict_text(self) -> None:
        """Test parsing text content."""
        data = {
            "uri": "file:///test.txt",
            "mimeType": "text/plain",
            "text": "Hello, world!",
        }
        content = MCPResourceContent.from_dict(data)
        assert content.uri == "file:///test.txt"
        assert content.mime_type == "text/plain"
        assert content.text == "Hello, world!"
        assert content.blob is None

    def test_from_dict_blob(self) -> None:
        """Test parsing binary (blob) content."""
        data = {
            "uri": "file:///image.png",
            "mimeType": "image/png",
            "blob": "iVBORw0KGgo=",
        }
        content = MCPResourceContent.from_dict(data)
        assert content.uri == "file:///image.png"
        assert content.mime_type == "image/png"
        assert content.blob == "iVBORw0KGgo="
        assert content.text is None

    def test_from_dict_minimal(self) -> None:
        """Test parsing content with only required fields."""
        data = {"uri": "file:///empty.txt"}
        content = MCPResourceContent.from_dict(data)
        assert content.uri == "file:///empty.txt"
        assert content.mime_type == "text/plain"  # Default
        assert content.text is None
        assert content.blob is None

    def test_from_dict_json_content(self) -> None:
        """Test parsing JSON text content."""
        data = {
            "uri": "file:///config.json",
            "mimeType": "application/json",
            "text": '{"key": "value"}',
        }
        content = MCPResourceContent.from_dict(data)
        assert content.uri == "file:///config.json"
        assert content.mime_type == "application/json"
        assert content.text == '{"key": "value"}'

    def test_direct_construction_text(self) -> None:
        """Test creating MCPResourceContent with text."""
        content = MCPResourceContent(
            uri="file:///test.txt",
            mime_type="text/plain",
            text="Test content",
        )
        assert content.uri == "file:///test.txt"
        assert content.text == "Test content"
        assert content.blob is None

    def test_direct_construction_blob(self) -> None:
        """Test creating MCPResourceContent with blob."""
        content = MCPResourceContent(
            uri="file:///binary.bin",
            mime_type="application/octet-stream",
            blob="YmluYXJ5IGRhdGE=",
        )
        assert content.uri == "file:///binary.bin"
        assert content.blob == "YmluYXJ5IGRhdGE="
        assert content.text is None
