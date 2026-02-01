"""Unit tests for MCP test server definitions."""

import pytest

from nexus3.mcp.test_server.definitions import (
    PROMPTS,
    RESOURCE_CONTENTS,
    RESOURCES,
    TOOLS,
    get_capabilities,
    get_server_info,
    handle_prompts_get,
    handle_resources_read,
    handle_tools_call,
    make_error,
    make_notification,
    make_response,
    make_tool_result,
)


class TestToolHandlers:
    def test_echo_tool(self) -> None:
        result = handle_tools_call("echo", {"message": "hello"})
        assert result["content"][0]["text"] == "hello"
        assert not result["isError"]

    def test_echo_tool_empty_message(self) -> None:
        result = handle_tools_call("echo", {"message": ""})
        assert result["content"][0]["text"] == ""
        assert not result["isError"]

    def test_echo_tool_missing_message(self) -> None:
        result = handle_tools_call("echo", {})
        assert result["content"][0]["text"] == ""
        assert not result["isError"]

    def test_add_tool(self) -> None:
        result = handle_tools_call("add", {"a": 10, "b": 32})
        assert result["content"][0]["text"] == "42"

    def test_add_tool_floats(self) -> None:
        result = handle_tools_call("add", {"a": 1.5, "b": 2.5})
        assert result["content"][0]["text"] == "4.0"

    def test_add_tool_missing_args(self) -> None:
        result = handle_tools_call("add", {})
        assert result["content"][0]["text"] == "0"

    def test_get_time_tool(self) -> None:
        result = handle_tools_call("get_time", {})
        assert not result["isError"]
        # Should contain ISO format date
        text = result["content"][0]["text"]
        assert "T" in text  # ISO format has 'T' separator

    def test_slow_operation_tool(self) -> None:
        result = handle_tools_call("slow_operation", {"duration": 1, "steps": 3})
        assert "Completed 3 steps in 1s" in result["content"][0]["text"]
        assert not result["isError"]

    def test_slow_operation_defaults(self) -> None:
        result = handle_tools_call("slow_operation", {})
        assert "Completed 5 steps in 2s" in result["content"][0]["text"]

    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown tool"):
            handle_tools_call("nonexistent", {})


class TestResourceHandlers:
    def test_read_readme(self) -> None:
        result = handle_resources_read("file:///readme.txt")
        assert len(result["contents"]) == 1
        assert "Test Project" in result["contents"][0]["text"]
        assert result["contents"][0]["mimeType"] == "text/plain"
        assert result["contents"][0]["uri"] == "file:///readme.txt"

    def test_read_config(self) -> None:
        result = handle_resources_read("file:///config.json")
        assert "test-server" in result["contents"][0]["text"]
        assert result["contents"][0]["mimeType"] == "application/json"

    def test_read_users_csv(self) -> None:
        result = handle_resources_read("file:///data/users.csv")
        text = result["contents"][0]["text"]
        assert "id,name,email" in text
        assert "Alice" in text
        assert "Bob" in text
        assert result["contents"][0]["mimeType"] == "text/csv"

    def test_unknown_resource_raises(self) -> None:
        with pytest.raises(ValueError, match="Resource not found"):
            handle_resources_read("file:///nonexistent")


class TestPromptHandlers:
    def test_greeting_prompt(self) -> None:
        result = handle_prompts_get("greeting", {"name": "Alice"})
        assert "Alice" in result["messages"][0]["content"]["text"]
        assert result["description"] == "Generate a greeting message"
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"]["type"] == "text"

    def test_greeting_prompt_casual(self) -> None:
        result = handle_prompts_get("greeting", {"name": "Bob", "formal": False})
        text = result["messages"][0]["content"]["text"]
        assert "Bob" in text
        assert "casual" in text.lower() or "friendly" in text.lower()

    def test_greeting_formal(self) -> None:
        result = handle_prompts_get("greeting", {"name": "Dr. Smith", "formal": True})
        text = result["messages"][0]["content"]["text"]
        assert "formal" in text.lower()

    def test_greeting_default_name(self) -> None:
        result = handle_prompts_get("greeting", {})
        assert "friend" in result["messages"][0]["content"]["text"]

    def test_code_review_prompt(self) -> None:
        result = handle_prompts_get("code_review", {"language": "Python", "focus": "security"})
        text = result["messages"][0]["content"]["text"]
        assert "Python" in text
        assert "security" in text

    def test_code_review_prompt_default_focus(self) -> None:
        result = handle_prompts_get("code_review", {"language": "JavaScript"})
        text = result["messages"][0]["content"]["text"]
        assert "JavaScript" in text
        assert "general quality" in text

    def test_summarize_prompt(self) -> None:
        result = handle_prompts_get("summarize", {})
        assert "Summarize" in result["messages"][0]["content"]["text"]
        assert result["description"] == "Summarize text content"

    def test_summarize_with_max_length(self) -> None:
        result = handle_prompts_get("summarize", {"max_length": 100})
        text = result["messages"][0]["content"]["text"]
        assert "max 100 words" in text

    def test_unknown_prompt_raises(self) -> None:
        with pytest.raises(ValueError, match="Prompt not found"):
            handle_prompts_get("nonexistent", {})


class TestHelperFunctions:
    def test_make_response(self) -> None:
        resp = make_response(123, {"key": "value"})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 123
        assert resp["result"] == {"key": "value"}

    def test_make_response_string_id(self) -> None:
        resp = make_response("abc-123", {"data": 42})
        assert resp["id"] == "abc-123"

    def test_make_response_null_id(self) -> None:
        resp = make_response(None, {})
        assert resp["id"] is None

    def test_make_error(self) -> None:
        resp = make_error(456, -32601, "Method not found")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 456
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"

    def test_make_notification(self) -> None:
        notif = make_notification("update", {"status": "done"})
        assert notif["jsonrpc"] == "2.0"
        assert notif["method"] == "update"
        assert notif["params"] == {"status": "done"}
        assert "id" not in notif

    def test_make_notification_no_params(self) -> None:
        notif = make_notification("ping")
        assert notif["method"] == "ping"
        assert "params" not in notif

    def test_make_tool_result(self) -> None:
        result = make_tool_result("Hello, world!")
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello, world!"
        assert result["isError"] is False

    def test_make_tool_result_error(self) -> None:
        result = make_tool_result("Something went wrong", is_error=True)
        assert result["isError"] is True


class TestCapabilities:
    def test_capabilities_include_all_features(self) -> None:
        caps = get_capabilities()
        assert "tools" in caps
        assert "resources" in caps
        assert "prompts" in caps

    def test_resources_capabilities(self) -> None:
        caps = get_capabilities()
        assert caps["resources"]["subscribe"] is False
        assert caps["resources"]["listChanged"] is False

    def test_prompts_capabilities(self) -> None:
        caps = get_capabilities()
        assert caps["prompts"]["listChanged"] is False


class TestServerInfo:
    def test_default_server_info(self) -> None:
        info = get_server_info()
        assert info["name"] == "nexus3-test-server"
        assert info["version"] == "1.0.0"

    def test_custom_server_name(self) -> None:
        info = get_server_info("my-custom-server")
        assert info["name"] == "my-custom-server"
        assert info["version"] == "1.0.0"


class TestDefinitions:
    def test_all_resources_have_content(self) -> None:
        for resource in RESOURCES:
            assert resource["uri"] in RESOURCE_CONTENTS

    def test_all_resources_have_required_fields(self) -> None:
        for resource in RESOURCES:
            assert "uri" in resource
            assert "name" in resource
            assert "mimeType" in resource

    def test_prompts_have_arguments(self) -> None:
        for prompt in PROMPTS:
            assert "arguments" in prompt
            assert "name" in prompt
            assert "description" in prompt

    def test_tools_have_input_schema(self) -> None:
        for tool in TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_resource_count(self) -> None:
        assert len(RESOURCES) == 3

    def test_prompt_count(self) -> None:
        assert len(PROMPTS) == 3

    def test_tool_count(self) -> None:
        assert len(TOOLS) == 4
