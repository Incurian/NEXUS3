# MCP Client Implementation Plan for NEXUS3

## Overview

Add MCP (Model Context Protocol) client capability to NEXUS3, allowing agents to use tools from external MCP servers (databases, file systems, APIs, etc.).

**References:**
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Python SDK](https://pypi.org/project/mcp/) - `pip install mcp`
- [MCP GitHub](https://github.com/modelcontextprotocol/python-sdk)

---

## Security Requirements

### Permission Level
- **Only TRUSTED level agents can use MCP tools**
- SANDBOXED and WORKER agents cannot access MCP servers
- Check performed at connection time and tool invocation

### Connection Consent Flow
When connecting to an MCP server, prompt the user:

```
Connect to MCP server "postgres"?
  Tools: query, execute, list_tables

  [1] Allow all tools (this session)
  [2] Require confirmation for each tool
  [3] Deny connection
```

- **Allow all**: Server added to session allowances, tools execute without prompts
- **Require confirmation**: Each tool call goes through `confirm_tool_action`
- **Deny**: Server not connected

### Tool Invocation
If not "allow all", each MCP tool call prompts:
```
Allow mcp_postgres_query?
  Server: postgres
  Arguments: {"sql": "SELECT * FROM users"}

  [1] Allow once
  [2] Allow always (this server, this session)
  [3] Deny
```

---

## Architecture

### New Module Structure

```
nexus3/mcp/
├── __init__.py
├── client.py           # MCPClient - connects to MCP servers
├── transport.py        # StdioTransport, HTTPTransport
├── protocol.py         # MCP message types, serialization
├── skill_adapter.py    # Converts MCP tools → NEXUS3 skills
├── registry.py         # MCPServerRegistry - manages connections
└── permissions.py      # MCP-specific permission checks
```

### Test Server

```
nexus3/mcp/test_server/
├── __init__.py
├── server.py           # Simple MCP server with test tools
└── run.py              # Entry point: python -m nexus3.mcp.test_server
```

---

## Phase 1: Core Infrastructure

### 1.1 Transport Layer (`transport.py`)

```python
from abc import ABC, abstractmethod
import asyncio
import subprocess

class MCPTransport(ABC):
    """Base transport interface for MCP communication."""

    @abstractmethod
    async def send(self, message: dict) -> None:
        """Send a JSON-RPC message."""
        ...

    @abstractmethod
    async def receive(self) -> dict:
        """Receive a JSON-RPC message."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the transport."""
        ...


class StdioTransport(MCPTransport):
    """Launch MCP server as subprocess, communicate via stdin/stdout."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None):
        self._command = command
        self._env = env
        self._process: subprocess.Popen | None = None

    async def connect(self) -> None:
        """Start the subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )

    async def send(self, message: dict) -> None:
        """Write JSON-RPC message to stdin."""
        import json
        data = json.dumps(message) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

    async def receive(self) -> dict:
        """Read JSON-RPC message from stdout."""
        import json
        line = await self._process.stdout.readline()
        return json.loads(line.decode())

    async def close(self) -> None:
        """Terminate subprocess."""
        if self._process:
            self._process.terminate()
            await self._process.wait()


class HTTPTransport(MCPTransport):
    """Connect to remote MCP server via HTTP/SSE."""

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self._url = url
        self._headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    # ... HTTP implementation
```

### 1.2 Protocol Types (`protocol.py`)

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class MCPTool:
    """MCP tool definition from server."""
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema

@dataclass
class MCPToolResult:
    """Result from MCP tool invocation."""
    content: list[dict[str, Any]]  # [{type: "text", text: "..."}, ...]
    is_error: bool = False

    def to_text(self) -> str:
        """Extract text content from result."""
        texts = []
        for item in self.content:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

@dataclass
class MCPServerInfo:
    """Server information from initialization."""
    name: str
    version: str
    capabilities: dict[str, Any]
```

### 1.3 MCP Client (`client.py`)

```python
from nexus3.mcp.transport import MCPTransport
from nexus3.mcp.protocol import MCPTool, MCPToolResult, MCPServerInfo

class MCPClient:
    """Client for connecting to MCP servers."""

    PROTOCOL_VERSION = "2025-11-25"

    def __init__(self, transport: MCPTransport):
        self._transport = transport
        self._request_id = 0
        self._server_info: MCPServerInfo | None = None
        self._tools: list[MCPTool] = []

    async def __aenter__(self) -> "MCPClient":
        await self._transport.connect()
        await self._initialize()
        return self

    async def __aexit__(self, *args) -> None:
        await self._transport.close()

    async def _initialize(self) -> None:
        """Perform MCP handshake."""
        response = await self._call("initialize", {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "nexus3", "version": "1.0.0"}
        })
        self._server_info = MCPServerInfo(
            name=response["serverInfo"]["name"],
            version=response["serverInfo"]["version"],
            capabilities=response.get("capabilities", {}),
        )
        await self._notify("notifications/initialized", {})

    async def _call(self, method: str, params: dict) -> dict:
        """Make JSON-RPC call and wait for response."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        await self._transport.send(request)
        response = await self._transport.receive()

        if "error" in response:
            raise MCPError(response["error"]["code"], response["error"]["message"])
        return response.get("result", {})

    async def _notify(self, method: str, params: dict) -> None:
        """Send notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._transport.send(notification)

    async def list_tools(self) -> list[MCPTool]:
        """Discover available tools from server."""
        result = await self._call("tools/list", {})
        self._tools = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> MCPToolResult:
        """Invoke a tool on the server."""
        result = await self._call("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        return MCPToolResult(
            content=result.get("content", []),
            is_error=result.get("isError", False),
        )

    @property
    def server_info(self) -> MCPServerInfo | None:
        return self._server_info

    @property
    def tools(self) -> list[MCPTool]:
        return self._tools


class MCPError(Exception):
    """Error from MCP server."""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"MCP error {code}: {message}")
```

---

## Phase 2: Skill Adapter

```python
# skill_adapter.py

from nexus3.core.types import ToolResult
from nexus3.mcp.client import MCPClient
from nexus3.mcp.protocol import MCPTool

class MCPSkillAdapter:
    """Wraps an MCP tool as a NEXUS3 Skill."""

    def __init__(
        self,
        client: MCPClient,
        tool: MCPTool,
        server_name: str,
    ):
        self._client = client
        self._tool = tool
        self._server_name = server_name

    @property
    def name(self) -> str:
        # Prefix with server name to avoid collisions
        return f"mcp_{self._server_name}_{self._tool.name}"

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._tool.description}"

    @property
    def parameters(self) -> dict:
        # MCP inputSchema is already JSON Schema format (OpenAI compatible)
        return self._tool.input_schema

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def original_name(self) -> str:
        return self._tool.name

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the MCP tool."""
        try:
            result = await self._client.call_tool(self._tool.name, kwargs)
            if result.is_error:
                return ToolResult(error=result.to_text())
            return ToolResult(output=result.to_text())
        except MCPError as e:
            return ToolResult(error=f"MCP error: {e.message}")
        except Exception as e:
            return ToolResult(error=f"MCP call failed: {e}")
```

---

## Phase 3: Server Registry

```python
# registry.py

from dataclasses import dataclass, field
from pathlib import Path
from nexus3.mcp.client import MCPClient
from nexus3.mcp.transport import StdioTransport, HTTPTransport
from nexus3.mcp.skill_adapter import MCPSkillAdapter

@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""
    name: str
    command: list[str] | None = None  # For stdio transport
    url: str | None = None             # For HTTP transport
    env: dict[str, str] | None = None
    enabled: bool = True

@dataclass
class ConnectedServer:
    """A connected MCP server with its tools."""
    config: MCPServerConfig
    client: MCPClient
    skills: list[MCPSkillAdapter] = field(default_factory=list)
    allowed_all: bool = False  # User chose "allow all tools"

class MCPServerRegistry:
    """Manages connections to MCP servers."""

    def __init__(self):
        self._servers: dict[str, ConnectedServer] = {}

    async def connect(
        self,
        config: MCPServerConfig,
        allow_all: bool = False,
    ) -> ConnectedServer:
        """Connect to an MCP server and discover tools."""
        if config.name in self._servers:
            return self._servers[config.name]

        # Create transport
        if config.command:
            transport = StdioTransport(config.command, config.env)
        elif config.url:
            transport = HTTPTransport(config.url)
        else:
            raise ValueError(f"Server {config.name} has no command or url")

        # Connect
        client = MCPClient(transport)
        await client.__aenter__()

        # Discover tools
        tools = await client.list_tools()
        skills = [
            MCPSkillAdapter(client, tool, config.name)
            for tool in tools
        ]

        connected = ConnectedServer(
            config=config,
            client=client,
            skills=skills,
            allowed_all=allow_all,
        )
        self._servers[config.name] = connected
        return connected

    async def disconnect(self, name: str) -> bool:
        """Disconnect from an MCP server."""
        if name not in self._servers:
            return False
        server = self._servers.pop(name)
        await server.client.__aexit__(None, None, None)
        return True

    def get(self, name: str) -> ConnectedServer | None:
        """Get a connected server by name."""
        return self._servers.get(name)

    def list_servers(self) -> list[str]:
        """List connected server names."""
        return list(self._servers.keys())

    def get_all_skills(self) -> list[MCPSkillAdapter]:
        """Get all skills from all connected servers."""
        skills = []
        for server in self._servers.values():
            skills.extend(server.skills)
        return skills

    def is_tool_allowed(self, skill_name: str) -> bool:
        """Check if a tool is from an 'allow all' server."""
        for server in self._servers.values():
            for skill in server.skills:
                if skill.name == skill_name:
                    return server.allowed_all
        return False

    async def close_all(self) -> None:
        """Disconnect from all servers."""
        for name in list(self._servers.keys()):
            await self.disconnect(name)
```

---

## Phase 4: Permission Integration

### 4.1 MCP Permission Checks (`permissions.py`)

```python
# permissions.py

from nexus3.core.permissions import AgentPermissions, PermissionLevel

def can_use_mcp(permissions: AgentPermissions | None) -> bool:
    """Check if agent has permission to use MCP."""
    if permissions is None:
        return True  # No restrictions
    # Only TRUSTED and above can use MCP
    return permissions.effective_policy.level in (
        PermissionLevel.YOLO,
        PermissionLevel.TRUSTED,
    )

def requires_mcp_confirmation(
    permissions: AgentPermissions | None,
    server_name: str,
    session_allowances: set[str],
) -> bool:
    """Check if MCP tool call requires confirmation."""
    if permissions is None:
        return False
    if permissions.effective_policy.level == PermissionLevel.YOLO:
        return False
    # Check if server is in session allowances
    return f"mcp:{server_name}" not in session_allowances
```

### 4.2 Session Integration

In `session/session.py`, add MCP tool handling in `_execute_single_tool`:

```python
# Check if this is an MCP tool
if tool_call.name.startswith("mcp_"):
    # Verify TRUSTED permission
    if not can_use_mcp(permissions):
        return ToolResult(error="MCP tools require TRUSTED permission level")

    # Check if confirmation needed
    server_name = self._extract_mcp_server(tool_call.name)
    if requires_mcp_confirmation(permissions, server_name, session_allowances):
        result = await self._request_confirmation(tool_call, None)
        # Handle "allow always for this server" → add to session_allowances
```

---

## Phase 5: Config Schema

### Add to `config/schema.py`:

```python
class MCPServerConfig(BaseModel):
    """MCP server configuration."""
    model_config = ConfigDict(extra="forbid")

    name: str
    """Friendly name for the server."""

    command: list[str] | None = None
    """Command to launch server (stdio transport)."""

    url: str | None = None
    """URL for remote server (HTTP transport)."""

    env: dict[str, str] | None = None
    """Environment variables for the server process."""

    enabled: bool = True
    """Whether this server is enabled."""


class Config(BaseModel):
    # ... existing fields ...

    mcp_servers: list[MCPServerConfig] = []
    """MCP server configurations."""
```

### Example `config.json`:

```json
{
  "provider": { ... },
  "models": { ... },
  "mcp_servers": [
    {
      "name": "test",
      "command": ["python", "-m", "nexus3.mcp.test_server"]
    },
    {
      "name": "filesystem",
      "command": ["npx", "-y", "@anthropic/mcp-server-filesystem", "/home/user/projects"]
    },
    {
      "name": "postgres",
      "command": ["npx", "-y", "@anthropic/mcp-server-postgres"],
      "env": {"DATABASE_URL": "postgresql://localhost/mydb"}
    }
  ]
}
```

---

## Phase 6: Test Server

### `nexus3/mcp/test_server/server.py`

```python
"""Simple MCP test server for development."""

import asyncio
import json
import sys
from datetime import datetime

async def handle_request(request: dict) -> dict:
    """Handle incoming MCP request."""
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nexus3-test", "version": "1.0.0"},
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo back the input message",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "Message to echo"}
                            },
                            "required": ["message"]
                        }
                    },
                    {
                        "name": "get_time",
                        "description": "Get current date and time",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "add",
                        "description": "Add two numbers",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "a": {"type": "number", "description": "First number"},
                                "b": {"type": "number", "description": "Second number"}
                            },
                            "required": ["a", "b"]
                        }
                    }
                ]
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "echo":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": args.get("message", "")}],
                    "isError": False
                }
            }
        elif tool_name == "get_time":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": datetime.now().isoformat()}],
                    "isError": False
                }
            }
        elif tool_name == "add":
            result = args.get("a", 0) + args.get("b", 0)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": str(result)}],
                    "isError": False
                }
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            }

    # Handle notifications (no response)
    if request_id is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    }

async def main():
    """Main server loop - read from stdin, write to stdout."""
    while True:
        line = await asyncio.get_event_loop().run_in_executor(
            None, sys.stdin.readline
        )
        if not line:
            break

        try:
            request = json.loads(line)
            response = await handle_request(request)
            if response:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Phase 7: REPL Commands

### Commands

```
/mcp                        # List configured and connected servers
/mcp connect <name>         # Connect to server (with consent prompt)
/mcp disconnect <name>      # Disconnect from server
/mcp tools [server]         # List available tools
```

### Add to `cli/repl_commands.py`:

```python
async def cmd_mcp(ctx: CommandContext, args: str | None = None) -> CommandOutput:
    """Handle MCP server management commands."""
    # Parse subcommand
    if not args:
        return await _mcp_list(ctx)

    parts = args.split(None, 1)
    subcmd = parts[0]
    subargs = parts[1] if len(parts) > 1 else None

    if subcmd == "connect":
        return await _mcp_connect(ctx, subargs)
    elif subcmd == "disconnect":
        return await _mcp_disconnect(ctx, subargs)
    elif subcmd == "tools":
        return await _mcp_tools(ctx, subargs)
    else:
        return CommandOutput.error(f"Unknown MCP command: {subcmd}")
```

---

## Implementation Timeline

| Phase | Effort | Description |
|-------|--------|-------------|
| 1 | 3 days | Transport, protocol, client |
| 2 | 1 day | Skill adapter |
| 3 | 1 day | Server registry |
| 4 | 2 days | Permission integration |
| 5 | 1 day | Config schema |
| 6 | 1 day | Test server |
| 7 | 1 day | REPL commands |

**Total: ~10 days**

---

## Testing Strategy

1. **Unit tests**: Transport, protocol types, client
2. **Integration tests**: Test server connection, tool discovery, tool invocation
3. **Permission tests**: TRUSTED enforcement, consent flow
4. **E2E tests**: Full flow from REPL to MCP tool execution

---

## Future Enhancements

1. **MCP Resources**: Expose file/data resources from MCP servers
2. **MCP Prompts**: Use server-provided prompt templates
3. **WebSocket transport**: For persistent connections
4. **Server health checks**: Automatic reconnection on failure
5. **Tool caching**: Cache tool definitions to reduce discovery overhead

---

## Dependencies

Add to `pyproject.toml`:
```toml
# Optional MCP support
mcp = {version = ">=1.25", optional = true}
```

Or for standalone implementation (no SDK dependency):
- `httpx` (already have)
- `asyncio` (stdlib)
