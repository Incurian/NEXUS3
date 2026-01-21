# nexus3/mcp

## Overview

The `nexus3.mcp` module provides a secure, client-side implementation of the **Model Context Protocol (MCP)** for NEXUS3 agents. MCP is a standardized protocol for connecting AI agents to external tool providers, enabling agents to discover and invoke tools from external servers.

**MCP Specification:** [2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)

### Key Capabilities

- **Multi-transport support:** Connect to MCP servers via stdio (subprocess) or HTTP
- **Tool discovery:** Automatic discovery of available tools from connected servers
- **Skill integration:** MCP tools are seamlessly exposed as NEXUS3 skills with prefixed names
- **Multi-server registry:** Manage connections to multiple MCP servers with visibility controls
- **Security hardening:** Environment sanitization, response validation, permission enforcement

---

## Architecture

```
MCPServerRegistry
    │
    ├── ConnectedServer (test_server)
    │       ├── MCPClient
    │       │       └── StdioTransport → subprocess
    │       └── [MCPSkillAdapter, MCPSkillAdapter, ...]
    │
    └── ConnectedServer (remote_api)
            ├── MCPClient
            │       └── HTTPTransport → HTTP endpoint
            └── [MCPSkillAdapter, ...]
```

### Data Flow

1. **Configuration:** Load `mcp.json` with server definitions
2. **Connection:** Registry creates transport and client for each server
3. **Discovery:** Client performs MCP handshake and lists available tools
4. **Adaptation:** Each tool is wrapped in an `MCPSkillAdapter` for NEXUS3
5. **Execution:** Agent invokes skill -> adapter calls MCP server -> result returned

---

## Module Structure

```
nexus3/mcp/
├── __init__.py         # Public exports
├── client.py           # MCPClient - protocol lifecycle
├── protocol.py         # MCP data types (MCPTool, MCPToolResult, etc.)
├── transport.py        # Transport layer (stdio, HTTP)
├── registry.py         # Multi-server connection management
├── skill_adapter.py    # Bridge MCP tools to NEXUS3 skills
├── permissions.py      # Agent permission checks for MCP access
└── test_server/        # Development/testing MCP server
    ├── __init__.py
    ├── __main__.py     # Entry point: python -m nexus3.mcp.test_server
    ├── server.py       # Stdio-based test server
    └── http_server.py  # HTTP-based test server
```

---

## Public Exports

```python
from nexus3.mcp import (
    # Client
    MCPClient,              # Main client for MCP communication
    MCPError,               # Error from MCP protocol or server

    # Protocol types
    MCPTool,                # Tool definition from server
    MCPToolResult,          # Result from tool invocation
    MCPServerInfo,          # Server metadata from initialization

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

## Components

### MCPClient (`client.py`)

The core client handles the MCP protocol lifecycle:

1. **Connect:** Establish transport connection
2. **Initialize:** Perform MCP handshake (protocol version, capabilities)
3. **Discover:** List available tools from server
4. **Execute:** Invoke tools with arguments
5. **Close:** Clean shutdown

```python
from nexus3.mcp import MCPClient, StdioTransport

transport = StdioTransport(["python", "-m", "some_mcp_server"])

# Context manager pattern (recommended)
async with MCPClient(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"message": "hello"})
    print(result.to_text())  # "hello"

# Manual pattern
client = MCPClient(transport)
await client.connect(timeout=30.0)
try:
    # ... use client
finally:
    await client.close()
```

**Properties:**
- `server_info` - Server metadata (name, version, capabilities)
- `tools` - Cached tool list (call `list_tools()` first)
- `is_initialized` - Whether handshake completed
- `is_connected` - Whether transport is connected

**Security Features:**
- **Response ID matching (P2.9):** Verifies response IDs match request IDs to prevent response confusion attacks
- **Notification discarding (P2.10):** Discards interleaved notifications (max 100) while waiting for responses

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
- **Safe environment (default):** Only safe system variables (PATH, HOME, USER, LANG, etc.) are passed by default
- **Explicit opt-in:** Use `env` for explicit values or `env_passthrough` for host variables
- **Line length limit (P2.12):** 10MB max to prevent memory exhaustion from malicious servers

**Safe environment variables passed by default:**
```
PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TERM, SHELL, TMPDIR, TMP, TEMP
```

#### HTTPTransport

Connects to remote MCP servers via HTTP POST:

```python
from nexus3.mcp import HTTPTransport

transport = HTTPTransport(
    url="https://mcp.example.com/api",
    headers={"Authorization": "Bearer token"},
    timeout=30.0,
)
```

**Security Features:**
- **SSRF protection:** URL validation (allows localhost for local MCP servers)
- **Requires httpx:** Install with `pip install httpx`

### Protocol Types (`protocol.py`)

**MCPTool:** Tool definition from a server
```python
@dataclass
class MCPTool:
    name: str                           # Tool identifier
    description: str                    # Human-readable description
    input_schema: dict[str, Any]        # JSON Schema for parameters
```

**MCPToolResult:** Result from tool invocation
```python
@dataclass
class MCPToolResult:
    content: list[dict[str, Any]]       # Content items (text, images, etc.)
    is_error: bool                      # Whether result is an error

    def to_text(self) -> str:           # Extract text content
```

**MCPServerInfo:** Server metadata from initialization
```python
@dataclass
class MCPServerInfo:
    name: str                           # Server name
    version: str                        # Server version
    capabilities: dict[str, Any]        # Server capabilities
```

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
    shared=True,       # Visible to all agents
    timeout=30.0,
)

# Get skills for an agent
skills = registry.get_all_skills(agent_id="main")

# List connected servers
server_names = registry.list_servers(agent_id="main")

# Find specific skill
skill, server_name = registry.find_skill("mcp_github_list_repos")

# Health check and cleanup
dead_servers = await registry.check_connections()

# Cleanup
await registry.disconnect("github")
await registry.close_all()
```

**Visibility Model:**
- `shared=True`: Connection visible to all agents
- `shared=False`: Connection visible only to `owner_agent_id`

### MCPSkillAdapter (`skill_adapter.py`)

Bridges MCP tools to NEXUS3's skill system:

```python
from nexus3.mcp import MCPSkillAdapter

# Automatically created by registry, but can be manual:
adapter = MCPSkillAdapter(
    client=mcp_client,
    tool=mcp_tool,
    server_name="github",
)

# Skill name is prefixed: "mcp_github_list_repos"
print(adapter.name)          # "mcp_github_list_repos"
print(adapter.original_name) # "list_repos"
print(adapter.server_name)   # "github"

# Execute returns NEXUS3 ToolResult
result = await adapter.execute(owner="octocat", repo="hello-world")
```

**Naming Convention:**
- MCP tools are prefixed with `mcp_{server_name}_` to avoid collisions
- Names are sanitized via `build_mcp_skill_name()` from `nexus3.core.identifiers`
- Example: Server "GitHub API" + tool "list-repos" -> `mcp_github_api_list_repos`

**Argument Validation:**
- Arguments are validated against the tool's JSON Schema before sending to MCP server
- Uses `validate_tool_arguments()` from `nexus3.core.validation`

### Permission Checks (`permissions.py`)

Determines whether agents can access MCP tools:

```python
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation

# Check if agent can use MCP at all
if not can_use_mcp(agent.permissions):
    # Denied - agent is SANDBOXED or has no permissions
    pass

# Check if confirmation is needed for a specific server
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

**Security Features (P2.11):**
- **Deny by default:** If `permissions` is `None`, MCP access is denied
- **Defense in depth:** Even if `can_use_mcp()` is bypassed, `requires_mcp_confirmation()` still requires confirmation

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
    "github": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      },
      "env_passthrough": ["HOME"],
      "enabled": true
    },
    "filesystem": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "enabled": true
    },
    "remote_api": {
      "url": "https://mcp.example.com/api",
      "enabled": false
    }
  }
}
```

**Server Configuration Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `command` | `list[str]` | Command to launch stdio server |
| `url` | `str` | URL for HTTP server (mutually exclusive with `command`) |
| `env` | `dict[str, str]` | Explicit environment variables |
| `env_passthrough` | `list[str]` | Host env vars to pass through |
| `enabled` | `bool` | Whether server is enabled (default: `true`) |

**Notes:**
- Either `command` or `url` must be specified (not both)
- Environment variable substitution uses `${VAR_NAME}` syntax
- Disabled servers (`enabled: false`) raise `MCPConfigError` when connected

---

## Security Considerations

### Environment Sanitization

MCP servers receive a sanitized environment by default:

```python
# Only these are passed by default:
SAFE_ENV_KEYS = {
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL",
    "LC_CTYPE", "TERM", "SHELL", "TMPDIR", "TMP", "TEMP"
}
```

**Why this matters:**
- Prevents accidental leakage of API keys (OPENROUTER_API_KEY, etc.)
- Explicit opt-in via `env` or `env_passthrough` for needed secrets
- Each MCP server only receives what it needs

### Protocol Hardening

| Protection | Description |
|------------|-------------|
| **P2.9: Response ID matching** | Verifies response IDs match request IDs |
| **P2.10: Notification discarding** | Discards up to 100 notifications while waiting for response |
| **P2.11: Deny by default** | MCP access denied if no permissions configured |
| **P2.12: Line length limit** | 10MB max for stdio transport |
| **SSRF protection** | URL validation for HTTP transport |

### Permission Enforcement

- Only TRUSTED and YOLO agents can access MCP tools
- SANDBOXED agents cannot use MCP (external tool providers)
- TRUSTED agents receive consent prompts on first access to each server
- Session allowances track per-server consent

### Skill Name Sanitization

MCP skill names are sanitized to prevent injection:

```python
from nexus3.core.identifiers import build_mcp_skill_name

build_mcp_skill_name("github", "list-repos")       # "mcp_github_list_repos"
build_mcp_skill_name("evil/../path", "../../etc")  # "mcp_evil_path_etc"
```

---

## Test Server

The module includes a test server for development and testing:

### Stdio Server

```bash
python -m nexus3.mcp.test_server
```

### HTTP Server

```bash
python -m nexus3.mcp.test_server.http_server --port 9000
```

### Available Test Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `echo` | Echo back a message | `message: str` |
| `get_time` | Get current date/time | (none) |
| `add` | Add two numbers | `a: number, b: number` |

### Example Usage

```python
from nexus3.mcp import MCPClient, StdioTransport

# Connect to test server
transport = StdioTransport(["python", "-m", "nexus3.mcp.test_server"])
async with MCPClient(transport) as client:
    # List tools
    tools = await client.list_tools()
    print([t.name for t in tools])  # ['echo', 'get_time', 'add']

    # Call tools
    result = await client.call_tool("echo", {"message": "Hello!"})
    print(result.to_text())  # "Hello!"

    result = await client.call_tool("add", {"a": 2, "b": 3})
    print(result.to_text())  # "5"
```

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
| `nexus3.skill.base` | `BaseSkill` |

### External Dependencies

| Package | Required For | Install |
|---------|--------------|---------|
| `httpx` | HTTPTransport | `pip install httpx` |
| `aiohttp` | HTTP test server | `pip install aiohttp` |

**Note:** `httpx` is only required if using HTTPTransport. StdioTransport has no external dependencies.

---

## Integration Points

### With ServiceContainer

The `MCPServerRegistry` is typically held in `ServiceContainer` and shared across agents:

```python
# In service container initialization
container.mcp_registry = MCPServerRegistry()

# Load from config and connect
for name, server_config in mcp_config.servers.items():
    await container.mcp_registry.connect(server_config)

# Get MCP skills for an agent
mcp_skills = container.mcp_registry.get_all_skills(agent_id)
```

### With SkillRegistry

MCP skills are registered alongside native skills:

```python
# Add MCP skills to agent's skill registry
for skill in mcp_registry.get_all_skills(agent_id):
    skill_registry.register(skill)
```

### With Session

Sessions check MCP permissions and manage consent:

```python
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation

if can_use_mcp(session.permissions):
    if requires_mcp_confirmation(session.permissions, server_name, session.allowances):
        # Prompt for consent
        session.allowances.add(f"mcp:{server_name}")
```

---

## Error Handling

```python
from nexus3.mcp import MCPClient, MCPError
from nexus3.mcp.transport import MCPTransportError
from nexus3.core.errors import MCPConfigError

try:
    # Connection/protocol errors
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

## Usage Examples

### 1. Direct Client Usage

```python
from nexus3.mcp import MCPClient, StdioTransport

transport = StdioTransport(
    ["npx", "-y", "@modelcontextprotocol/server-github"],
    env={"GITHUB_TOKEN": "ghp_xxx"},
)

async with MCPClient(transport) as client:
    tools = await client.list_tools()
    for tool in tools:
        print(f"- {tool.name}: {tool.description}")

    result = await client.call_tool("list_repos", {"owner": "anthropics"})
    print(result.to_text())
```

### 2. Registry-Based (Recommended)

```python
from nexus3.mcp import MCPServerRegistry, MCPServerConfig

registry = MCPServerRegistry()

# Connect multiple servers
await registry.connect(MCPServerConfig(
    name="github",
    command=["npx", "-y", "@modelcontextprotocol/server-github"],
    env={"GITHUB_TOKEN": "ghp_xxx"},
))

await registry.connect(MCPServerConfig(
    name="filesystem",
    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"],
))

# Get all skills
skills = registry.get_all_skills()
for skill in skills:
    print(f"- {skill.name}")

# Execute via skill adapter
skill = next(s for s in skills if s.name == "mcp_github_list_repos")
result = await skill.execute(owner="anthropics")

# Cleanup
await registry.close_all()
```

### 3. Permission-Gated Access

```python
from nexus3.mcp import MCPServerRegistry
from nexus3.mcp.permissions import can_use_mcp, requires_mcp_confirmation

async def get_mcp_skills(registry, agent_permissions, session_allowances, agent_id):
    """Get MCP skills respecting permissions."""
    if not can_use_mcp(agent_permissions):
        return []

    skills = []
    for server in registry.list_servers(agent_id=agent_id):
        if requires_mcp_confirmation(agent_permissions, server, session_allowances):
            # In real code: prompt user and add to session_allowances if approved
            continue

        connected = registry.get(server, agent_id=agent_id)
        if connected:
            skills.extend(connected.skills)

    return skills
```

---

*Updated: 2026-01-21*
