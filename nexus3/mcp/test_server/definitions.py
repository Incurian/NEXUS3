"""Shared definitions for MCP test servers.

Contains tool, resource, and prompt definitions used by both
stdio and HTTP test servers.
"""

from datetime import datetime
from typing import Any

# Protocol version
PROTOCOL_VERSION = "2025-11-25"

# =============================================================================
# TOOLS
# =============================================================================

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the input message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"],
        },
    },
    {
        "name": "get_time",
        "description": "Get current date and time",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "add",
        "description": "Add two numbers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "slow_operation",
        "description": "Simulate a slow operation (for progress testing)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "duration": {
                    "type": "number",
                    "description": "Duration in seconds",
                    "default": 2,
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of progress steps",
                    "default": 5,
                },
            },
        },
    },
]

# =============================================================================
# RESOURCES
# =============================================================================

RESOURCES = [
    {
        "uri": "file:///readme.txt",
        "name": "README",
        "description": "Project readme file",
        "mimeType": "text/plain",
    },
    {
        "uri": "file:///config.json",
        "name": "Configuration",
        "description": "Project configuration",
        "mimeType": "application/json",
    },
    {
        "uri": "file:///data/users.csv",
        "name": "Users Data",
        "description": "User database export",
        "mimeType": "text/csv",
    },
]

# Simulated resource contents
RESOURCE_CONTENTS: dict[str, str] = {
    "file:///readme.txt": "# Test Project\n\nThis is a test MCP server.\n",
    "file:///config.json": '{"name": "test-server", "version": "1.0.0", "debug": true}',
    "file:///data/users.csv": (
        "id,name,email\n1,Alice,alice@example.com\n2,Bob,bob@example.com\n"
    ),
}

# =============================================================================
# PROMPTS
# =============================================================================

PROMPTS = [
    {
        "name": "greeting",
        "description": "Generate a greeting message",
        "arguments": [
            {"name": "name", "description": "Name to greet", "required": True},
            {"name": "formal", "description": "Use formal greeting", "required": False},
        ],
    },
    {
        "name": "code_review",
        "description": "Review code for issues",
        "arguments": [
            {"name": "language", "description": "Programming language", "required": True},
            {
                "name": "focus",
                "description": "What to focus on (security, performance, style)",
                "required": False,
            },
        ],
    },
    {
        "name": "summarize",
        "description": "Summarize text content",
        "arguments": [
            {
                "name": "max_length",
                "description": "Maximum summary length",
                "required": False,
            },
        ],
    },
]

# Prompt templates
PROMPT_TEMPLATES: dict[str, str] = {
    "greeting": "Please greet {name}. {formal_instruction}",
    "code_review": "Review this {language} code. {focus_instruction}",
    "summarize": "Summarize the following text{length_instruction}:",
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def make_response(request_id: int | str | None, result: Any) -> dict[str, Any]:
    """Create a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(
    request_id: int | str | None, code: int, message: str
) -> dict[str, Any]:
    """Create a JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def make_notification(
    method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Create a JSON-RPC notification (no id)."""
    notif: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params:
        notif["params"] = params
    return notif


def make_tool_result(text: str, is_error: bool = False) -> dict[str, Any]:
    """Create a tool call result."""
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def get_capabilities() -> dict[str, Any]:
    """Return server capabilities."""
    return {
        "tools": {},
        "resources": {"subscribe": False, "listChanged": False},
        "prompts": {"listChanged": False},
    }


def get_server_info(name: str = "nexus3-test-server") -> dict[str, Any]:
    """Return server info."""
    return {"name": name, "version": "1.0.0"}


# =============================================================================
# REQUEST HANDLERS
# =============================================================================


def handle_tools_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Handle tools/call request."""
    if tool_name == "echo":
        return make_tool_result(args.get("message", ""))
    elif tool_name == "get_time":
        return make_tool_result(datetime.now().isoformat())
    elif tool_name == "add":
        result = args.get("a", 0) + args.get("b", 0)
        return make_tool_result(str(result))
    elif tool_name == "slow_operation":
        # For stdio, this would send progress notifications
        # For now, just return completion
        duration = args.get("duration", 2)
        steps = args.get("steps", 5)
        return make_tool_result(f"Completed {steps} steps in {duration}s")
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def handle_resources_read(uri: str) -> dict[str, Any]:
    """Handle resources/read request."""
    if uri not in RESOURCE_CONTENTS:
        raise ValueError(f"Resource not found: {uri}")

    content = RESOURCE_CONTENTS[uri]
    resource = next((r for r in RESOURCES if r["uri"] == uri), None)
    mime_type = resource["mimeType"] if resource else "text/plain"

    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": mime_type,
                "text": content,
            }
        ]
    }


def handle_prompts_get(
    name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Handle prompts/get request."""
    prompt = next((p for p in PROMPTS if p["name"] == name), None)
    if not prompt:
        raise ValueError(f"Prompt not found: {name}")

    args = arguments or {}

    if name == "greeting":
        formal = args.get("formal", False)
        formal_instruction = "Use formal language." if formal else "Be casual and friendly."
        text = PROMPT_TEMPLATES["greeting"].format(
            name=args.get("name", "friend"),
            formal_instruction=formal_instruction,
        )
    elif name == "code_review":
        focus = args.get("focus", "general quality")
        focus_instruction = f"Focus on {focus}."
        text = PROMPT_TEMPLATES["code_review"].format(
            language=args.get("language", "code"),
            focus_instruction=focus_instruction,
        )
    elif name == "summarize":
        max_length = args.get("max_length")
        length_instruction = f" (max {max_length} words)" if max_length else ""
        text = PROMPT_TEMPLATES["summarize"].format(
            length_instruction=length_instruction
        )
    else:
        text = f"Prompt: {name}"

    return {
        "description": prompt["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }
