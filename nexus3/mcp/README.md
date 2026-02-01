# nexus3/mcp

MCP (Model Context Protocol) client implementation for NEXUS3 agents.

**Updated: 2026-02-01**

## Overview

The `nexus3.mcp` module provides a secure, client-side implementation of the **Model Context Protocol (MCP)** for NEXUS3 agents. MCP is a standardized protocol for connecting AI agents to external tool providers, enabling agents to discover and invoke tools, resources, and prompts from external servers.

**MCP Specification:** [2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)

### Key Capabilities

- **Multi-transport support:** Connect to MCP servers via stdio (subprocess) or HTTP
- **Full MCP feature support:** Tools, Resources, and Prompts with cursor-based pagination
- **Skill integration:** MCP tools are seamlessly exposed as NEXUS3 skills with prefixed names
- **Multi-server registry:** Manage connections to multiple MCP servers with visibility controls
- **Security hardening:** Environment sanitization, response validation, permission enforcement
- **Cross-platform support:** Windows-specific process handling (CREATE_NO_WINDOW, PATHEXT resolution)

---

## Architecture

```
MCPServerRegistry
    |
    +-- ConnectedServer (test_server)
    |       +-- MCPClient
    |       |       +-- StdioTransport -> subprocess
    |       +-- [MCPSkillAdapter, MCPSkillAdapter, ...]
    |
    +-- ConnectedServer (remote_api)
            +-- MCPClient
            |       +-- HTTPTransport -> HTTP endpoint
            +-- [MCPSkillAdapter, ...]
```

### Data Flow

1. **Configuration:** Load `mcp.json` with server definitions
2. **Connection:** Registry creates transport and client for each server
3. **Discovery:** Client performs MCP handshake and lists available tools/resources/prompts
4. **Adaptation:** Each tool is wrapped in an `MCPSkillAdapter` for NEXUS3
5. **Execution:** Agent invokes skill -> adapter calls MCP server -> result returned

---

## Module Structure

```
nexus3/mcp/
+-- __init__.py           # Public exports
+-- client.py             # MCPClient - protocol lifecycle
+-- protocol.py           # MCP data types (MCPTool, MCPResource, MCPPrompt, etc.)
+-- transport.py          # Transport layer (stdio, HTTP)
+-- registry.py           # Multi-server connection management
+-- skill_adapter.py      # Bridge MCP tools to NEXUS3 skills
+-- permissions.py        # Agent permission checks for MCP access
+-- errors.py             # MCPErrorContext for detailed error messages
+-- error_formatter.py    # User-friendly error message formatting
+-- test_server/          # Development/testing MCP server
    +-- __init__.py
    +-- __main__.py       # Entry point: python -m nexus3.mcp.test_server
    +-- server.py         # Stdio-based test server
    +-- http_server.py    # HTTP-based test server
    +-- definitions.py    # Shared tool/resource/prompt definitions
    +-- paginating_server.py  # Server for testing cursor pagination
```

---

## Public Exports

```python
from nexus3.mcp import (
    # Client
    MCPClient,              # Main client for MCP communication
    MCPError,               # Error from MCP protocol or server

    # Protocol types - Tools
    MCPTool,                # Tool definition from server
    MCPToolResult,          # Result from tool invocation
    MCPServerInfo,          # Server metadata from initialization

    # Protocol types - Resources
    MCPResource,            # Resource definition from server
    MCPResourceContent,     # Content from resources/read

    # Protocol types - Prompts
    MCPPrompt,              # Prompt definition from server
    MCPPromptArgument,      # Argument definition for prompts
    MCPPromptMessage,       # Message in prompt result
    MCPPromptResult,        # Result from prompts/get

    # Transport
    MCPTransport,           # Abstract transport base class
    StdioTransport,         # Subprocess communication
    HTTPTransport,          # HTTP POST communication

    # Registry
    MCPServerRegistry,      # Multi-server connection manager
    MCPServerConfig,        # Server configuration dataclass
    ConnectedServer,        # Active server connection with skills

    # Skill integration
    MCPSkillAdapter,        # Wraps MCPTool as NEXUS3 Skill
)
```

---

## Constants

Important constants defined in the module:

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| `PROTOCOL_VERSION` | `"2025-11-25"` | `protocol.py` | MCP specification version |
| `MAX_MCP_OUTPUT_SIZE` | 10 MB | `protocol.py` | Max tool output size before truncation |
| `MAX_STDIO_LINE_LENGTH` | 10 MB | `transport.py` | Max line length for stdio transport |
| `MAX_NOTIFICATIONS_TO_DISCARD` | 100 | `client.py` | Max notifications to skip waiting for response |
| `MAX_SESSION_ID_LENGTH` | 256 | `transport.py` | Max HTTP session ID length |
| `DEFAULT_MAX_RETRIES` | 3 | `transport.py` | HTTP retry attempts |
| `DEFAULT_RETRY_BACKOFF` | 1.0 | `transport.py` | HTTP retry base delay (seconds) |
| `RETRYABLE_STATUS_CODES` | 429, 5xx | `transport.py` | HTTP status codes to retry |
| `SAFE_ENV_KEYS` | see below | `transport.py` | Env vars safe to pass to subprocesses |

---

## Components

### MCPClient (`client.py`)

The core client handles the MCP protocol lifecycle:

1. **Connect:** Establish transport connection
2. **Initialize:** Perform MCP handshake (protocol version, capabilities)
3. **Discover:** List available tools, resources, and prompts
4. **Execute:** Invoke tools, read resources, get prompts
5. **Close:** Clean shutdown

```python
from nexus3.mcp import MCPClient, StdioTransport

transport = StdioTransport(["python", "-m", "some_mcp_server"])

# Context manager pattern (recommended)
async with MCPClient(transport) as client:
    # Tools
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"message": "hello"})

    # Resources
    resources = await client.list_resources()
    content = await client.read_resource("file:///readme.txt")

    # Prompts
    prompts = await client.list_prompts()
    prompt_result = await client.get_prompt("greeting", {"name": "Alice"})
```

**Properties:**
- `server_info` - Server metadata (name, version, capabilities)
- `tools` - Cached tool list (call `list_tools()` first)
- `resources` - Cached resource list (call `list_resources()` first)
- `prompts` - Cached prompt list (call `list_prompts()` first)
- `is_initialized` - Whether handshake completed
- `is_connected` - Whether transport is connected

**Methods:**

| Method | Description |
|--------|-------------|
| `connect(timeout)` | Connect and initialize |
| `close()` | Close connection |
| `reconnect(timeout)` | Close and reconnect |
| `ping()` | Health check, returns latency in ms |
| `list_tools()` | List available tools (with pagination) |
| `call_tool(name, arguments)` | Invoke a tool |
| `list_resources()` | List available resources (with pagination) |
| `read_resource(uri)` | Read resource content |
| `list_prompts()` | List available prompts (with pagination) |
| `get_prompt(name, arguments)` | Get prompt with filled arguments |

**Security Features:**
- **Response ID matching:** Verifies response IDs match request IDs
- **Notification discarding:** Discards interleaved notifications (max 100) while waiting for responses

### MCPTransport (`transport.py`)

Abstract base class for transport implementations:

```python
class MCPTransport(ABC):
    async def connect(self) -> None: ...
    async def send(self, message: dict) -> None: ...
    async def receive(self) -> dict: ...
    async def request(self, message: dict) -> dict: ...  # send + receive
    async def close(self) -> None: ...
```

#### StdioTransport

Launches an MCP server as a subprocess and communicates via stdin/stdout using newline-delimited JSON-RPC.

```python
from nexus3.mcp import StdioTransport

transport = StdioTransport(
    command=["npx", "-y", "@modelcontextprotocol/server-github"],
    env={"GITHUB_TOKEN": "ghp_xxx"},           # Explicit env vars
    env_passthrough=["HOME", "GITHUB_TOKEN"],  # Pass from host
    cwd="/path/to/workspace",                   # Working directory
)
```

**Security Features:**
- **Safe environment (default):** Only safe system variables passed by default
- **Explicit opt-in:** Use `env` for explicit values or `env_passthrough` for host variables
- **Line length limit:** 10MB max to prevent memory exhaustion

**Cross-Platform Features:**
- **Windows command resolution:** Uses `shutil.which()` to resolve `.cmd`, `.bat`, `.exe` extensions via PATHEXT
- **Windows command aliases:** Translates Unix commands (e.g., `python3` to `python`, `pip3` to `pip`)
- **Process group handling:** Uses `start_new_session` on Unix, `CREATE_NEW_PROCESS_GROUP` on Windows
- **Window suppression:** Uses `CREATE_NO_WINDOW` on Windows to prevent cmd.exe window flashing
- **CRLF handling:** Strips both LF and CRLF line endings when parsing responses
- **Read buffering:** Properly buffers data read past newlines for fast response sequences

**Safe environment variables passed by default:**
```
# Cross-platform
PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TERM, SHELL, TMPDIR, TMP, TEMP

# Windows-specific
USERPROFILE, APPDATA, LOCALAPPDATA, PATHEXT, SYSTEMROOT, COMSPEC
```

**Properties:**
- `is_connected` - Whether subprocess is running (returncode is None)
- `stderr_lines` - Last 20 lines of stderr for error context

#### HTTPTransport

Connects to remote MCP servers via HTTP POST:

```python
from nexus3.mcp import HTTPTransport

transport = HTTPTransport(
    url="https://mcp.example.com/api",
    headers={"Authorization": "Bearer token"},
    timeout=30.0,
    max_retries=3,
    retry_backoff=1.0,
)
```

**Features:**
- **SSRF protection:** URL validation (allows localhost for local MCP servers)
- **SSRF redirect prevention:** `follow_redirects=False` prevents redirect-based attacks
- **Session management:** Captures and sends `mcp-session-id` header
- **Session ID validation:** Alphanumeric + dash/underscore only, max 256 chars
- **Retry logic:** Exponential backoff with jitter for 429 and 5xx responses
- **MCP headers:** Sends `MCP-Protocol-Version` and `Accept` headers per spec
- **Direct request method:** `request()` method for atomic request/response (no shared state)

**Properties:**
- `is_connected` - Whether HTTP client is open
- `session_id` - Current MCP session ID (if set by server)

**Retry Configuration:**
- `max_retries`: Maximum retry attempts (default 3)
- `retry_backoff`: Base delay in seconds (default 1.0)
- Retryable status codes: 429, 500, 502, 503, 504

### Protocol Types (`protocol.py`)

**MCPTool:** Tool definition from a server
```python
@dataclass
class MCPTool:
    name: str                           # Tool identifier
    description: str                    # Human-readable description
    input_schema: dict[str, Any]        # JSON Schema for parameters
    title: str | None                   # Display title (optional)
    output_schema: dict[str, Any] | None  # Output validation schema (optional)
    icons: list[dict[str, Any]] | None  # Icon identifiers for UI display (optional)
    annotations: dict[str, Any] | None  # Server-specific metadata (optional)
```

**MCPToolResult:** Result from tool invocation
```python
@dataclass
class MCPToolResult:
    content: list[dict[str, Any]]       # Content items (text, images, etc.)
    is_error: bool                      # Whether result is an error
    structured_content: dict[str, Any] | None  # Structured content (optional)

    def to_text(self) -> str: ...       # Extract text content (with size limit)
```

**MCPServerInfo:** Server metadata from initialization
```python
@dataclass
class MCPServerInfo:
    name: str                           # Server name
    version: str                        # Server version
    capabilities: dict[str, Any]        # Server capabilities
```

**MCPResource:** Resource definition
```python
@dataclass
class MCPResource:
    uri: str                            # Unique identifier
    name: str                           # Human-readable name
    description: str | None             # Optional description
    mime_type: str                      # Content MIME type
    annotations: dict[str, Any] | None  # Server-specific metadata (optional)
```

**MCPResourceContent:** Content from resources/read
```python
@dataclass
class MCPResourceContent:
    uri: str                            # Resource URI
    mime_type: str                      # Content MIME type
    text: str | None                    # Text content
    blob: str | None                    # Base64-encoded binary content
```

**MCPPrompt:** Prompt definition
```python
@dataclass
class MCPPrompt:
    name: str                           # Unique identifier
    description: str | None             # Optional description
    arguments: list[MCPPromptArgument]  # Argument definitions
```

**MCPPromptArgument:** Argument definition for prompts
```python
@dataclass
class MCPPromptArgument:
    name: str                           # Argument name
    description: str | None             # Optional description
    required: bool                      # Whether required (default True)
```

**MCPPromptMessage:** Message in a prompt result
```python
@dataclass
class MCPPromptMessage:
    role: str                           # Message role (user, assistant, system)
    content: dict[str, Any] | str       # Message content

    def get_text(self) -> str: ...      # Extract text from content
```

**MCPPromptResult:** Result from prompts/get
```python
@dataclass
class MCPPromptResult:
    description: str                    # Description of this instance
    messages: list[MCPPromptMessage]    # Messages to send
```

**Internal types (not exported):**
- `MCPClientInfo`: Client identification sent during initialization (defaults to `nexus3/1.0.0`)

### MCPServerRegistry (`registry.py`)

Manages connections to multiple MCP servers with per-agent visibility:

```python
from nexus3.mcp import MCPServerRegistry, MCPServerConfig

registry = MCPServerRegistry()

# Connect to a server
config = MCPServerConfig(
    name="github",
    command=["npx", "-y", "@modelcontextprotocol/server-github"],
    env={"GITHUB_TOKEN": "ghp_xxx"},
    enabled=True,
)
server = await registry.connect(
    config,
    owner_agent_id="main",
    shared=True,
    timeout=30.0,
)

# Get skills for an agent
skills = await registry.get_all_skills(agent_id="main")

# Cleanup
await registry.close_all()
```

**Key methods:**

| Method | Description |
|--------|-------------|
| `connect(config, owner, shared, timeout)` | Connect to server |
| `disconnect(name)` | Disconnect from server |
| `get(name, agent_id)` | Get connected server |
| `list_servers(agent_id)` | List server names |
| `get_all_skills(agent_id)` | Get all skill adapters (with lazy reconnection) |
| `find_skill(tool_name)` | Find skill by name, returns `(skill, server_name)` |
| `get_server_for_skill(skill_name)` | Find server providing a skill |
| `check_connections()` | Remove dead connections |
| `retry_tools(name)` | Retry tool listing |
| `close_all()` | Disconnect all servers |

**Visibility Model:**
- `shared=True`: Connection visible to all agents
- `shared=False`: Connection visible only to `owner_agent_id`

**Graceful Degradation:**
- Connections succeed even if `list_tools()` fails (skills will be empty)
- Set `fail_if_no_tools=True` in config to require tools

**Lazy Reconnection:**
- `get_all_skills()` automatically reconnects dead stdio connections
- HTTP connections are checked on next request

### ConnectedServer

Active connection wrapper with reconnection support:

```python
@dataclass
class ConnectedServer:
    config: MCPServerConfig         # Server configuration
    client: MCPClient               # Active MCP client
    skills: list[MCPSkillAdapter]   # Skill adapters for this server's tools
    owner_agent_id: str             # Agent that created this connection
    shared: bool                    # Whether visible to all agents

    def is_visible_to(agent_id: str) -> bool  # Check visibility
    def is_alive() -> bool                    # Check if connection alive
    async def reconnect(timeout: float)       # Reconnect and refresh tools
```

### MCPSkillAdapter (`skill_adapter.py`)

Bridges MCP tools to NEXUS3's skill system:

```python
from nexus3.mcp import MCPSkillAdapter

adapter = MCPSkillAdapter(client=mcp_client, tool=mcp_tool, server_name="github")

print(adapter.name)          # "mcp_github_list_repos"
print(adapter.original_name) # "list_repos"
print(adapter.server_name)   # "github"

result = await adapter.execute(owner="octocat", repo="hello-world")
```

**Naming Convention:**
- MCP tools are prefixed with `mcp_{server_name}_` to avoid collisions
- Names are sanitized via `build_mcp_skill_name()` from `nexus3.core.identifiers`

**Features:**
- Validates parameters against tool's input_schema before calling server
- Sanitizes MCP output via `sanitize_for_display()` for terminal safety
- Converts `MCPToolResult` to NEXUS3 `ToolResult` with error handling
- Provides formatted error messages for timeout and transport errors

### Permission Checks (`permissions.py`)

Determines whether agents can access MCP tools:

```python
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation

if not can_use_mcp(agent.permissions):
    # Denied - agent is SANDBOXED or has no permissions
    pass

if requires_mcp_confirmation(agent.permissions, "github", session_allowances):
    # Prompt user for consent
    pass
```

**Permission Model:**

| Level | MCP Access | Confirmation |
|-------|------------|--------------|
| YOLO | Yes | Never |
| TRUSTED | Yes | First access per server |
| SANDBOXED | No | N/A |

### Error Context (`errors.py`)

Structured context for MCP errors:

```python
@dataclass
class MCPErrorContext:
    server_name: str                    # MCP server name
    source_path: Path | str | None      # Config file path
    source_layer: str | None            # Layer name (global, project)
    command: list[str] | None           # Launch command
    stderr_lines: list[str] | None      # Last N lines of stderr
```

### Error Formatter (`error_formatter.py`)

User-friendly error message formatting with troubleshooting hints:

```python
from nexus3.mcp.error_formatter import (
    format_command_not_found,
    format_server_crash,
    format_json_error,
    format_timeout_error,
    format_config_validation_error,
)
```

Each formatter provides:
- Clear problem description
- Server and config context
- Likely causes
- Actionable troubleshooting steps
- Platform-specific hints (Windows PATHEXT, etc.)

**Formatters:**

| Function | When Used |
|----------|-----------|
| `format_command_not_found` | Executable not found (FileNotFoundError) |
| `format_server_crash` | Server exited unexpectedly (with exit code) |
| `format_json_error` | Invalid JSON response from server |
| `format_timeout_error` | Connection or operation timeout |
| `format_config_validation_error` | Invalid mcp.json configuration |

---

## Configuration

MCP servers are configured in `mcp.json` files, loaded from the context layer hierarchy:

```
~/.nexus3/mcp.json          # Global (user defaults)
./parent/.nexus3/mcp.json   # Ancestor layers
./.nexus3/mcp.json          # Local (project-specific)
```

### mcp.json Format

```json
{
  "servers": {
    "server-name": {
      "command": ["executable", "arg1", "arg2"],
      "url": "https://...",
      "env": {"KEY": "value"},
      "env_passthrough": ["VAR1", "VAR2"],
      "cwd": "/working/directory",
      "enabled": true,
      "fail_if_no_tools": false
    }
  }
}
```

### Server Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | `str \| list[str]` | - | Command to launch stdio server |
| `args` | `list[str]` | `[]` | Arguments (when command is string) |
| `url` | `str` | - | URL for HTTP server |
| `env` | `dict[str, str]` | `{}` | Explicit environment variables |
| `env_passthrough` | `list[str]` | `[]` | Host env vars to pass through |
| `cwd` | `str` | `None` | Working directory for subprocess |
| `enabled` | `bool` | `true` | Whether server is enabled |
| `fail_if_no_tools` | `bool` | `false` | Fail if tool listing fails |

### Command Format Options

**NEXUS3 Format (command as array):**
```json
{
  "servers": {
    "github": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

**Official MCP Format (Claude Desktop compatible):**
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

Both formats are supported. The `mcpServers` key is an alias for `servers`.

### REPL Commands

| Command | Description |
|---------|-------------|
| `/mcp` | List configured and connected servers |
| `/mcp connect <name>` | Connect to a configured server |
| `/mcp connect <name> --allow-all --shared` | Connect skipping prompts, share with all agents |
| `/mcp disconnect <name>` | Disconnect from a server |
| `/mcp tools [server]` | List available MCP tools |
| `/mcp resources [server]` | List available MCP resources |
| `/mcp prompts [server]` | List available MCP prompts |
| `/mcp retry <name>` | Retry tool listing from server |

---

## Security Considerations

### Environment Sanitization

MCP servers receive a sanitized environment by default. Only safe system variables are passed (PATH, HOME, USER, etc.). Use `env` or `env_passthrough` to explicitly pass additional variables.

### Protocol Hardening

| Protection | Description |
|------------|-------------|
| Response ID matching | Verifies response IDs match request IDs |
| Notification discarding | Discards up to 100 notifications while waiting |
| Deny by default | MCP access denied if no permissions configured |
| Line length limit | 10MB max for stdio transport |
| SSRF protection | URL validation for HTTP transport |
| SSRF redirect prevention | `follow_redirects=False` |
| Output sanitization | MCP output sanitized via `sanitize_for_display()` |
| Response size limits | 10MB max (`MAX_MCP_OUTPUT_SIZE`) |
| Session ID validation | Alphanumeric + dash/underscore, max 256 chars |

---

## Test Server

The module includes test servers for development and testing.

### Stdio Server

```bash
python -m nexus3.mcp.test_server
```

### HTTP Server

```bash
python -m nexus3.mcp.test_server.http_server --port 9000
```

### Paginating Server (for pagination testing)

```bash
python -m nexus3.mcp.test_server.paginating_server
MCP_TOOL_COUNT=10 MCP_PAGE_SIZE=3 python -m nexus3.mcp.test_server.paginating_server
```

### Available Test Features

**Tools:**
| Tool | Description | Parameters |
|------|-------------|------------|
| `echo` | Echo back a message | `message: str` |
| `get_time` | Get current date/time | (none) |
| `add` | Add two numbers | `a: number, b: number` |
| `slow_operation` | Simulate slow operation | `duration: number, steps: int` |

**Resources:**
| URI | Name | MIME Type |
|-----|------|-----------|
| `file:///readme.txt` | README | text/plain |
| `file:///config.json` | Configuration | application/json |
| `file:///data/users.csv` | Users Data | text/csv |

**Prompts:**
| Name | Description | Arguments |
|------|-------------|-----------|
| `greeting` | Generate greeting | `name` (required), `formal` (optional) |
| `code_review` | Review code | `language` (required), `focus` (optional) |
| `summarize` | Summarize text | `max_length` (optional) |

---

## Dependencies

### Internal Dependencies

| Module | Usage |
|--------|-------|
| `nexus3.core.errors` | `NexusError`, `MCPConfigError` |
| `nexus3.core.types` | `ToolResult` |
| `nexus3.core.permissions` | `AgentPermissions`, `PermissionLevel` |
| `nexus3.core.identifiers` | `build_mcp_skill_name()` |
| `nexus3.core.validation` | `validate_tool_arguments()` |
| `nexus3.core.url_validator` | `validate_url()`, `UrlSecurityError` |
| `nexus3.core.text_safety` | `sanitize_for_display()` |
| `nexus3.core.process` | `terminate_process_tree()` |
| `nexus3.skill.base` | `BaseSkill` |

### External Dependencies

| Package | Required For | Install |
|---------|--------------|---------|
| `httpx` | HTTPTransport | `pip install httpx` |
| `aiohttp` | HTTP test server | `pip install aiohttp` |

**Note:** `httpx` is only required if using HTTPTransport. StdioTransport has no external dependencies.

---

## Exception Hierarchy

```python
from nexus3.mcp import MCPClient, MCPError
from nexus3.mcp.transport import MCPTransportError
from nexus3.core.errors import MCPConfigError

try:
    async with MCPClient(transport) as client:
        result = await client.call_tool("unknown", {})
except MCPError as e:
    # Protocol-level error (from server)
    print(f"MCP error: {e.message}, code: {e.code}")
except MCPTransportError as e:
    # Transport-level error (connection, I/O)
    print(f"Transport error: {e}")
except MCPConfigError as e:
    # Configuration error (disabled server, missing command/url)
    print(f"Config error: {e}")
```

---

*Updated: 2026-02-01*
