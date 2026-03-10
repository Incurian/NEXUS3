"""Focused provider tests for compiler-backed request shaping (Plan E Phase 2)."""

from __future__ import annotations

from nexus3.config.schema import AuthMethod, ProviderConfig
from nexus3.core.types import Message, Role, ToolCall


def test_openai_request_body_prunes_orphan_tool_messages_via_compiler() -> None:
    """OpenAI provider should compile and prune invalid TOOL-only messages."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    body = provider._build_request_body(
        messages=[
            Message(role=Role.USER, content="hello"),
            Message(role=Role.TOOL, content="orphan", tool_call_id="tc-orphan"),
        ],
        tools=None,
        stream=False,
    )

    assert [msg["role"] for msg in body["messages"]] == ["user"]
    assert body["messages"][0]["content"] == "hello"


def test_openai_request_body_does_not_inject_cancel_note_mid_tool_loop() -> None:
    """OpenAI request shaping must not fabricate cancellation notes mid-turn."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    body = provider._build_request_body(
        messages=[
            Message(role=Role.USER, content="test the file tools"),
            Message(
                role=Role.ASSISTANT,
                content="Working on it.",
                tool_calls=(
                    ToolCall(
                        id="tc1",
                        name="write_file",
                        arguments={"path": "./sandbox/demo.txt", "content": "alpha\n"},
                    ),
                ),
            ),
            Message(role=Role.TOOL, content="wrote file", tool_call_id="tc1"),
        ],
        tools=None,
        stream=False,
    )

    assert [msg["role"] for msg in body["messages"]] == ["user", "assistant", "tool"]
    assert all(
        msg.get("content") != "Previous turn was cancelled after tool execution."
        for msg in body["messages"]
    )


def test_openai_request_body_normalizes_empty_mcp_tool_schema() -> None:
    """OpenAI request shaping should normalize no-arg MCP tool schemas."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    original_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_agentbridge_list_worlds",
                "description": "List available worlds.",
                "parameters": {},
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="list worlds")],
        tools=original_tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {},
    }
    # The provider should not mutate caller-owned tool definitions in place.
    assert original_tools[0]["function"]["parameters"] == {}


def test_openai_request_body_normalizes_object_tool_schema_without_properties() -> None:
    """OpenAI request shaping should add missing properties for no-arg object schemas."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    original_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_ping",
                "description": "Ping the MCP server.",
                "parameters": {"type": "object", "title": "PingArgs"},
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="ping")],
        tools=original_tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "title": "PingArgs",
        "properties": {},
    }
    assert original_tools[0]["function"]["parameters"] == {
        "type": "object",
        "title": "PingArgs",
    }


def test_openai_request_body_preserves_existing_empty_properties_schema() -> None:
    """OpenAI request shaping should leave valid explicit empty schemas alone."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "nexus_status",
                "description": "Show agent status.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="status")],
        tools=tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {},
    }


def test_openai_request_body_normalizes_nested_array_schema_without_items() -> None:
    """OpenAI request shaping should normalize nested array schemas recursively."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    original_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_agentbridge_tempo_pawn_move_to",
                "description": "Move a pawn to a location.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "array",
                            "description": "Target location coordinates.",
                        }
                    },
                    "required": ["location"],
                },
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="move to new location")],
        tools=original_tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"]["properties"]["location"] == {
        "type": "array",
        "description": "Target location coordinates.",
        "items": {},
    }
    assert original_tools[0]["function"]["parameters"]["properties"]["location"] == {
        "type": "array",
        "description": "Target location coordinates.",
    }


def test_openai_request_body_normalizes_nested_object_schema_without_properties() -> None:
    """OpenAI request shaping should normalize nested object schemas recursively."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    original_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_agentbridge_nested_options",
                "description": "Use nested options.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "options": {
                            "type": "object",
                            "title": "Options",
                        }
                    },
                },
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="use options")],
        tools=original_tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"]["properties"]["options"] == {
        "type": "object",
        "title": "Options",
        "properties": {},
    }
    assert original_tools[0]["function"]["parameters"]["properties"]["options"] == {
        "type": "object",
        "title": "Options",
    }


def test_openai_request_body_normalizes_top_level_array_schema() -> None:
    """OpenAI request shaping should force top-level tool schemas to objects."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    original_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_array_args",
                "description": "Weird array-shaped args.",
                "parameters": {
                    "type": "array",
                    "title": "ArrayArgs",
                    "items": {"type": "string"},
                },
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="use weird tool")],
        tools=original_tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "title": "ArrayArgs",
        "properties": {},
    }
    assert original_tools[0]["function"]["parameters"] == {
        "type": "array",
        "title": "ArrayArgs",
        "items": {"type": "string"},
    }


def test_openai_request_body_strips_top_level_combinators() -> None:
    """OpenAI request shaping should remove top-level provider-incompatible combinators."""
    from nexus3.provider.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(
        ProviderConfig(
            type="openai",
            api_key_env="OPENAI_API_KEY",
            auth_method=AuthMethod.NONE,
        ),
        model_id="gpt-4o",
    )

    original_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_combinator_args",
                "description": "Weird combinator args.",
                "parameters": {
                    "title": "CombinatorArgs",
                    "oneOf": [
                        {"type": "object", "properties": {"a": {"type": "string"}}},
                        {"type": "object", "properties": {"b": {"type": "integer"}}},
                    ],
                },
            },
        }
    ]

    body = provider._build_request_body(
        messages=[Message(role=Role.USER, content="use combinator tool")],
        tools=original_tools,
        stream=False,
    )

    assert body["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "title": "CombinatorArgs",
        "properties": {},
    }
    assert "oneOf" in original_tools[0]["function"]["parameters"]


def test_anthropic_convert_messages_does_not_synthesize_orphans_locally() -> None:
    """Anthropic conversion should no longer synthesize missing tool results itself."""
    from nexus3.provider.anthropic import AnthropicProvider

    provider = object.__new__(AnthropicProvider)

    converted = provider._convert_messages(
        [
            Message(role=Role.USER, content="read files"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                    ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
                ),
            ),
            Message(role=Role.TOOL, content="A", tool_call_id="tc1"),
        ]
    )

    trailing_user = converted[-1]
    tool_result_ids = {
        block["tool_use_id"]
        for block in trailing_user["content"]
        if block["type"] == "tool_result"
    }
    assert tool_result_ids == {"tc1"}


def test_anthropic_request_body_synthesizes_missing_results_via_compiler() -> None:
    """Anthropic request shaping should synthesize missing tool results via compiler."""
    from nexus3.provider.anthropic import AnthropicProvider

    provider = object.__new__(AnthropicProvider)
    provider._config = ProviderConfig(
        type="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        prompt_caching=False,
    )
    provider._model = "claude-haiku-4-5"

    body = provider._build_request_body(
        messages=[
            Message(role=Role.USER, content="read files"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=(
                    ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                    ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
                ),
            ),
            Message(role=Role.TOOL, content="A", tool_call_id="tc1"),
        ],
        tools=None,
        stream=False,
    )

    trailing_user = body["messages"][-1]
    tool_results = [
        block for block in trailing_user["content"] if block["type"] == "tool_result"
    ]
    by_id = {block["tool_use_id"]: block["content"] for block in tool_results}

    assert set(by_id) == {"tc1", "tc2"}
    assert "interrupted" in by_id["tc2"].lower()


def test_anthropic_request_body_does_not_inject_cancel_note_mid_tool_loop() -> None:
    """Anthropic request shaping must not fabricate cancellation notes mid-turn."""
    from nexus3.provider.anthropic import AnthropicProvider

    provider = object.__new__(AnthropicProvider)
    provider._config = ProviderConfig(
        type="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        prompt_caching=False,
    )
    provider._model = "claude-haiku-4-5"

    body = provider._build_request_body(
        messages=[
            Message(role=Role.USER, content="test the file tools"),
            Message(
                role=Role.ASSISTANT,
                content="Working on it.",
                tool_calls=(
                    ToolCall(
                        id="tc1",
                        name="write_file",
                        arguments={"path": "./sandbox/demo.txt", "content": "alpha\n"},
                    ),
                ),
            ),
            Message(role=Role.TOOL, content="wrote file", tool_call_id="tc1"),
        ],
        tools=None,
        stream=False,
    )

    assert body["messages"][-1]["role"] == "user"
    assert all(
        block.get("text") != "Previous turn was cancelled after tool execution."
        for msg in body["messages"]
        for block in msg.get("content", [])
        if isinstance(block, dict)
    )


def test_anthropic_convert_tools_normalizes_provider_incompatible_top_level_shapes() -> None:
    """Anthropic tool conversion should use the same provider-safe schema normalization."""
    from nexus3.provider.anthropic import AnthropicProvider

    provider = object.__new__(AnthropicProvider)

    converted = provider._convert_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "mcp_array_args",
                    "description": "Array args.",
                    "parameters": {
                        "type": "array",
                        "title": "ArrayArgs",
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "mcp_combinator_args",
                    "description": "Combinator args.",
                    "parameters": {
                        "title": "CombinatorArgs",
                        "anyOf": [
                            {"type": "object", "properties": {"x": {"type": "string"}}},
                            {"type": "object", "properties": {"y": {"type": "integer"}}},
                        ],
                    },
                },
            },
        ]
    )

    assert converted[0]["input_schema"] == {
        "type": "object",
        "title": "ArrayArgs",
        "properties": {},
    }
    assert converted[1]["input_schema"] == {
        "type": "object",
        "title": "CombinatorArgs",
        "properties": {},
    }
