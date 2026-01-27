# MCP Implementation Gaps

This document compares NEXUS3's MCP implementation against the [MCP specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25) and identifies features not yet implemented.

**Last updated:** 2026-01-22

---

## Priority 0: Config Format Compatibility

**Status:** NEXUS3 uses a non-standard config format that is incompatible with Claude Desktop and other MCP hosts.

### The Problem

| Field | Official MCP Standard | NEXUS3 Current |
|-------|----------------------|----------------|
| Top-level key | `mcpServers` | `servers` |
| Command | `"command": "npx"` (string) | `"command": ["npx", ...]` (array) |
| Arguments | `"args": ["-y", "..."]` (separate array) | Included in `command` array |

**Official format (Claude Desktop, AgentBridge, etc.):**
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
      "cwd": "/working/dir",
      "env": {"KEY": "value"}
    }
  }
}
```

**NEXUS3 current format:**
```json
{
  "servers": {
    "filesystem": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"],
      "cwd": "/working/dir",
      "env": {"KEY": "value"}
    }
  }
}
```

### Impact

- Users cannot share `mcp.json` files between NEXUS3 and Claude Desktop
- Existing MCP configs from other tools won't work in NEXUS3
- Documentation/examples from MCP ecosystem don't apply directly

### Plan

**Option chosen:** Support both formats (backward compatible)

#### Step 1: Update `MCPServerConfig` dataclass

File: `nexus3/mcp/registry.py`

```python
@dataclass
class MCPServerConfig:
    name: str
    command: str | list[str] | None = None  # Support both string and array
    args: list[str] | None = None           # NEW: separate args (official format)
    url: str | None = None
    env: dict[str, str] | None = None
    env_passthrough: list[str] | None = None
    cwd: str | None = None
    enabled: bool = True

    def get_command_list(self) -> list[str]:
        """Return command as list, merging command + args if needed."""
        if isinstance(self.command, list):
            return self.command  # NEXUS3 format
        elif isinstance(self.command, str):
            # Official format: command string + args array
            cmd = [self.command]
            if self.args:
                cmd.extend(self.args)
            return cmd
        return []
```

#### Step 2: Update config loading

File: `nexus3/config/loader.py` (or wherever MCP config is parsed)

```python
def load_mcp_config(data: dict) -> dict[str, MCPServerConfig]:
    """Load MCP config, supporting both official and NEXUS3 formats."""
    # Support both top-level keys
    servers_data = data.get("mcpServers") or data.get("servers") or {}

    configs = {}
    for name, server_data in servers_data.items():
        configs[name] = MCPServerConfig(
            name=name,
            command=server_data.get("command"),
            args=server_data.get("args"),  # NEW
            url=server_data.get("url"),
            env=server_data.get("env"),
            env_passthrough=server_data.get("env_passthrough"),
            cwd=server_data.get("cwd"),
            enabled=server_data.get("enabled", True),
        )
    return configs
```

#### Step 3: Update `StdioTransport` creation

File: `nexus3/mcp/registry.py` in `MCPServerRegistry.connect()`

```python
if config.command:
    command_list = config.get_command_list()  # Use helper method
    transport = StdioTransport(
        command_list,
        env=config.env,
        env_passthrough=config.env_passthrough,
        cwd=config.cwd,
    )
```

#### Step 4: Update documentation

- Update README examples to show official format as primary
- Keep NEXUS3 format examples as "alternative format"
- Add migration note for existing users

#### Step 5: Add tests

```python
def test_official_mcp_format():
    """Official format with command string + args array."""
    config = MCPServerConfig(
        name="test",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
    )
    assert config.get_command_list() == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]

def test_nexus3_format():
    """NEXUS3 format with command array."""
    config = MCPServerConfig(
        name="test",
        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"],
    )
    assert config.get_command_list() == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]

def test_mcpservers_key():
    """Top-level mcpServers key (official)."""
    data = {"mcpServers": {"test": {"command": "echo", "args": ["hello"]}}}
    configs = load_mcp_config(data)
    assert "test" in configs

def test_servers_key():
    """Top-level servers key (NEXUS3)."""
    data = {"servers": {"test": {"command": ["echo", "hello"]}}}
    configs = load_mcp_config(data)
    assert "test" in configs
```

### Effort

- **Estimated:** 1-2 hours
- **Risk:** Low (backward compatible)
- **Files to modify:**
  - `nexus3/mcp/registry.py` - MCPServerConfig dataclass
  - `nexus3/config/schema.py` - Config schema if applicable
  - `nexus3/config/loader.py` - Config loading
  - `nexus3/mcp/README.md` - Documentation
  - `tests/unit/mcp/test_config.py` - Tests

---

## Priority 1: Protocol Spec Compliance Issues

These are deviations from the official MCP specification that may cause compatibility issues with strict MCP servers.

**Spec Reference:** [MCP Lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)

### 1.1 Initialized Notification Sends Extra `params` Field

**Current (WRONG):**
```python
# nexus3/mcp/client.py:152
await self._notify("notifications/initialized", {})
```

Produces:
```json
{"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
```

**Spec says:**
```json
{"jsonrpc": "2.0", "method": "notifications/initialized"}
```

> "Client MUST send this after successful initialization" - no params field specified.

**Fix:** Don't include `params` when empty in `_notify()`:

```python
async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
    notification: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params:  # Only include if non-empty
        notification["params"] = params
    await self._transport.send(notification)
```

**File:** `nexus3/mcp/client.py`
**Effort:** 5 minutes

---

### 1.2 Client Capabilities Always Empty

**Current:**
```python
# nexus3/mcp/client.py:143
"capabilities": {},
```

**Spec says:**
> "capabilities object describes which optional protocol features the client supports"

When NEXUS3 implements sampling, roots, or elicitation, it should declare them:
```json
{
  "capabilities": {
    "sampling": {},
    "roots": {"listChanged": true}
  }
}
```

**Impact:** Low for now (no client features implemented), but should be addressed when adding sampling/roots/elicitation.

**File:** `nexus3/mcp/client.py`
**Effort:** Update when implementing client features

---

### 1.3 Server Capabilities Not Used

**Current:** `MCPServerInfo` parses capabilities but nothing uses them.

```python
# nexus3/mcp/protocol.py:93
capabilities=data.get("capabilities", {}),
```

**Spec says:** Server capabilities indicate feature support:
- `tools.listChanged` - Server emits `notifications/tools/list_changed`
- `resources.subscribe` - Server supports resource subscriptions
- `prompts.listChanged` - Server emits prompt list change notifications

**Impact:** NEXUS3 ignores `listChanged` notifications even if server supports them.

**Fix:** Parse and respect capabilities when implementing resources/prompts.

**File:** `nexus3/mcp/client.py`, `nexus3/mcp/registry.py`
**Effort:** Part of resources/prompts implementation

---

### 1.4 tools/list Pagination Not Implemented

**Spec Reference:** [MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

**Current:**
```python
# nexus3/mcp/client.py:272
result = await self._call("tools/list", {})
```

**Spec says:**
```json
// Request with cursor
{"method": "tools/list", "params": {"cursor": "optional-cursor-value"}}

// Response with pagination
{"result": {"tools": [...], "nextCursor": "next-page-cursor"}}
```

**Impact:** If MCP server has >100 tools and uses pagination, NEXUS3 only gets first page.

**Fix:**
```python
async def list_tools(self) -> list[MCPTool]:
    all_tools: list[MCPTool] = []
    cursor: str | None = None

    while True:
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor

        result = await self._call("tools/list", params)
        all_tools.extend(MCPTool.from_dict(t) for t in result.get("tools", []))

        cursor = result.get("nextCursor")
        if not cursor:
            break

    self._tools = all_tools
    return self._tools
```

**File:** `nexus3/mcp/client.py`
**Effort:** 15 minutes

---

### 1.5 MCPTool Missing Optional Fields

**Spec Reference:** [MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

**Current:**
```python
@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
```

**Spec includes:**
```json
{
  "name": "get_weather",
  "title": "Weather Information Provider",
  "description": "Get current weather...",
  "inputSchema": {...},
  "outputSchema": {...},
  "icons": [{"src": "...", "mimeType": "...", "sizes": [...]}],
  "annotations": {...}
}
```

**Fix:**
```python
@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    output_schema: dict[str, Any] | None = None
    icons: list[dict[str, Any]] | None = None
    annotations: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPTool":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", {}),
            title=data.get("title"),
            output_schema=data.get("outputSchema"),
            icons=data.get("icons"),
            annotations=data.get("annotations"),
        )
```

**File:** `nexus3/mcp/protocol.py`
**Effort:** 10 minutes

---

### 1.6 MCPToolResult Missing `structuredContent`

**Spec Reference:** [MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

**Current:**
```python
@dataclass
class MCPToolResult:
    content: list[dict[str, Any]]
    is_error: bool = False
```

**Spec includes:**
```json
{
  "content": [...],
  "isError": false,
  "structuredContent": {"key": "value"}
}
```

**Fix:**
```python
@dataclass
class MCPToolResult:
    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    structured_content: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPToolResult":
        return cls(
            content=data.get("content", []),
            is_error=data.get("isError", False),
            structured_content=data.get("structuredContent"),
        )
```

**File:** `nexus3/mcp/protocol.py`
**Effort:** 5 minutes

---

### 1.7 HTTP Transport Missing Protocol Version Header

**Spec Reference:** [MCP Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

**Current:**
```python
# nexus3/mcp/transport.py:437-440
self._client = httpx.AsyncClient(
    timeout=self._timeout,
    headers={"Content-Type": "application/json", **self._headers},
)
```

**Spec says:**
> "Mandatory on all HTTP requests (except initialization): `MCP-Protocol-Version: 2025-11-25`"

**Fix:**
```python
self._client = httpx.AsyncClient(
    timeout=self._timeout,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        **self._headers,
    },
)
```

**File:** `nexus3/mcp/transport.py`
**Effort:** 5 minutes

---

### 1.8 HTTP Transport Missing Session Management

**Spec Reference:** [MCP Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

**Spec says:**
> "If server includes `MCP-Session-Id` header, client MUST include it in subsequent requests"

**Current:** HTTPTransport doesn't capture or send session ID.

**Fix:**
```python
class HTTPTransport(MCPTransport):
    def __init__(self, ...):
        ...
        self._session_id: str | None = None

    async def send(self, message: dict[str, Any]) -> None:
        headers = {}
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id

        response = await self._client.post(self._url, content=data, headers=headers)

        # Capture session ID from response
        if "MCP-Session-Id" in response.headers:
            self._session_id = response.headers["MCP-Session-Id"]
```

**File:** `nexus3/mcp/transport.py`
**Effort:** 15 minutes

---

### Summary: Protocol Compliance Fixes

| Issue | Severity | Effort | File |
|-------|----------|--------|------|
| 1.1 Extra params in notification | Low | 5 min | client.py |
| 1.2 Empty client capabilities | Low* | - | client.py |
| 1.3 Server capabilities unused | Low* | - | client.py |
| 1.4 Pagination not implemented | Medium | 15 min | client.py |
| 1.5 MCPTool missing fields | Low | 10 min | protocol.py |
| 1.6 MCPToolResult missing field | Low | 5 min | protocol.py |
| 1.7 HTTP missing version header | Medium | 5 min | transport.py |
| 1.8 HTTP missing session ID | Medium | 15 min | transport.py |

*Address when implementing related features

**Total effort for critical fixes (1.1, 1.4, 1.7, 1.8):** ~40 minutes

---

## Priority 1.9: Improved Error Messages

**Status:** MCP errors are currently terse and lack context, making troubleshooting difficult.

### The Problem

Current error messages don't tell users:
1. **Which config file** the error came from (global, ancestor, local?)
2. **What format was expected** vs what was provided
3. **Common causes** of the specific error
4. **How to fix it** with actionable suggestions

**Current error examples (unhelpful):**

```
MCPConfigError: Invalid MCP server config in /home/user/.nexus3/mcp.json: 1 validation error for MCPServerConfig
command
  Input should be a valid list [type=list_type, input_value='npx', input_type=str]

MCPTransportError: MCP server command not found: npx

MCPConfigError: MCPServerConfig: Must specify either 'command' or 'url'
```

### Improved Error Messages

#### 1.9.1 Config Validation Errors

**Current:**
```
Invalid MCP server config in /home/user/.nexus3/mcp.json: 1 validation error...
```

**Improved:**
```
MCP Configuration Error
━━━━━━━━━━━━━━━━━━━━━━━

Server: "github"
Source: ~/.nexus3/mcp.json (global config)

Problem: 'command' must be a list of strings, not a string
  You provided: "npx"
  Expected:     ["npx", "-y", "@modelcontextprotocol/server-github"]

Likely cause: You may be using Claude Desktop format (command + args separate).
NEXUS3 currently requires the command as a single array.

Fix: Change your mcp.json from:
  {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"]
  }
To:
  {
    "command": ["npx", "-y", "@modelcontextprotocol/server-github"]
  }

Note: Support for Claude Desktop format is planned. See:
https://github.com/your-repo/nexus3/docs/MCP-IMPLEMENTATION-GAPS.md#priority-0
```

#### 1.9.2 Command Not Found Errors

**Current:**
```
MCPTransportError: MCP server command not found: npx
```

**Improved:**
```
MCP Server Launch Failed
━━━━━━━━━━━━━━━━━━━━━━━━

Server: "filesystem"
Source: ./.nexus3/mcp.json (project config)

Problem: Command not found: npx

Likely causes:
  1. npx is not installed (comes with Node.js)
  2. npx is not in PATH for the MCP subprocess

Troubleshooting:
  • Check if npx exists: which npx
  • If not installed: Install Node.js from https://nodejs.org
  • If installed but not found: Add to env_passthrough in mcp.json:
    {
      "name": "filesystem",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
      "env_passthrough": ["PATH", "NODE_PATH"]
    }
```

#### 1.9.3 Server Startup Failures

**Current:**
```
MCPTransportError: Failed to start MCP server: [Errno 13] Permission denied
```

**Improved:**
```
MCP Server Launch Failed
━━━━━━━━━━━━━━━━━━━━━━━━

Server: "custom-server"
Source: ~/.nexus3/mcp.json (global config)
Command: ["/home/user/scripts/my-server.py"]

Problem: Permission denied when executing command

Likely causes:
  1. Script is not executable
  2. Script path contains spaces (needs quoting in shell)

Fix:
  • Make executable: chmod +x /home/user/scripts/my-server.py
  • Or run via interpreter: ["python", "/home/user/scripts/my-server.py"]
```

#### 1.9.4 Server Crash / Exit Errors

**Current:**
```
MCPTransportError: MCP server closed (exit code: 1)
```

**Improved:**
```
MCP Server Crashed
━━━━━━━━━━━━━━━━━━

Server: "postgres"
Source: ./.nexus3/mcp.json (project config)
Command: ["npx", "-y", "@modelcontextprotocol/server-postgres"]

Problem: Server exited with code 1

Server stderr (last 10 lines):
  Error: connect ECONNREFUSED 127.0.0.1:5432
  at TCPConnectWrap.afterConnect [as oncomplete]

Likely cause: Database connection failed

Troubleshooting:
  • Check if PostgreSQL is running: pg_isready
  • Verify DATABASE_URL environment variable is set
  • Add to env_passthrough: ["DATABASE_URL"]
  • Or set explicitly in env: {"DATABASE_URL": "postgresql://..."}
```

#### 1.9.5 Missing Transport Configuration

**Current:**
```
MCPConfigError: Server 'test' must have either 'command' or 'url'
```

**Improved:**
```
MCP Configuration Error
━━━━━━━━━━━━━━━━━━━━━━━

Server: "test"
Source: ~/.nexus3/mcp.json (global config)

Problem: Server has no transport configured

Every MCP server needs exactly one of:
  • command: Launch server as subprocess (stdio transport)
  • url: Connect to running server (HTTP transport)

Example stdio server:
  {
    "name": "test",
    "command": ["python", "-m", "nexus3.mcp.test_server"]
  }

Example HTTP server:
  {
    "name": "remote",
    "url": "http://localhost:3000/mcp"
  }
```

#### 1.9.6 Invalid JSON Errors

**Current:**
```
ContextLoadError: Error loading /home/user/.nexus3/mcp.json: ...JSONDecodeError...
```

**Improved:**
```
MCP Configuration Error
━━━━━━━━━━━━━━━━━━━━━━━

File: ~/.nexus3/mcp.json (global config)

Problem: Invalid JSON syntax at line 5, column 12

  4 │   "servers": [
  5 │     { "name": "test" "command": ["echo"] }
    │                     ^ Expected ',' or '}'
  6 │   ]

Common JSON mistakes:
  • Missing comma between properties
  • Trailing comma after last item
  • Single quotes instead of double quotes
  • Unquoted property names

Tip: Validate your JSON at https://jsonlint.com
```

#### 1.9.7 Protocol/Handshake Errors

**Current:**
```
MCPError: MCP connection timed out after 30s
```

**Improved:**
```
MCP Connection Failed
━━━━━━━━━━━━━━━━━━━━━

Server: "slow-server"
Source: ./.nexus3/mcp.json (project config)
Command: ["node", "server.js"]

Problem: Server did not complete MCP handshake within 30 seconds

Possible causes:
  1. Server is slow to start (loading large models, connecting to DBs)
  2. Server doesn't implement MCP protocol correctly
  3. Server is waiting for input that will never come

Troubleshooting:
  • Test server manually: node server.js
    Then type: {"jsonrpc":"2.0","method":"initialize","id":1,"params":{...}}
  • Check server logs for startup errors
  • Increase timeout in config.json:
    {"mcp": {"connection_timeout": 60}}
```

### Implementation

#### Error Context Dataclass

```python
# nexus3/mcp/errors.py (new file)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass
class MCPErrorContext:
    """Rich context for MCP error messages."""
    server_name: str | None = None
    source_path: Path | None = None
    source_layer: str | None = None  # "global", "local", "ancestor:project-name"
    command: list[str] | None = None
    url: str | None = None
    raw_config: dict[str, Any] | None = None
    stderr_output: str | None = None

    def format_source(self) -> str:
        """Format source path with layer description."""
        if not self.source_path:
            return "unknown source"

        layer_desc = {
            "global": "global config",
            "local": "project config",
        }
        desc = layer_desc.get(self.source_layer or "", self.source_layer or "")

        # Shorten home directory
        path_str = str(self.source_path)
        home = str(Path.home())
        if path_str.startswith(home):
            path_str = "~" + path_str[len(home):]

        return f"{path_str} ({desc})" if desc else path_str
```

#### Error Formatter

```python
# nexus3/mcp/error_formatter.py (new file)
from nexus3.mcp.errors import MCPErrorContext

def format_config_validation_error(
    ctx: MCPErrorContext,
    validation_error: Exception,
) -> str:
    """Format a Pydantic validation error with context and suggestions."""
    lines = [
        "MCP Configuration Error",
        "━" * 24,
        "",
    ]

    if ctx.server_name:
        lines.append(f'Server: "{ctx.server_name}"')
    lines.append(f"Source: {ctx.format_source()}")
    lines.append("")

    # Parse Pydantic error for field-specific messages
    # ... detect command format issues, suggest Claude Desktop format, etc.

    return "\n".join(lines)


def format_command_not_found(ctx: MCPErrorContext, command: str) -> str:
    """Format command-not-found error with installation hints."""
    # ... suggest npm/pip install, PATH issues, etc.


def format_server_crash(ctx: MCPErrorContext, exit_code: int) -> str:
    """Format server crash error with stderr context."""
    # ... include last N lines of stderr, common causes
```

#### Integration Points

1. **`ContextLoader._merge_mcp_servers()`** - Catch validation errors, add source path context
2. **`MCPServerRegistry.connect()`** - Capture stderr, track source config
3. **`StdioTransport.connect()`** - Capture command-not-found with context
4. **`StdioTransport.receive()`** - Include stderr when server crashes
5. **`MCPClient.connect()`** - Timeout errors with handshake context

### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/errors.py` | New file: MCPErrorContext dataclass |
| `nexus3/mcp/error_formatter.py` | New file: Error formatting functions |
| `nexus3/context/loader.py` | Pass source path to validation errors |
| `nexus3/mcp/registry.py` | Track config origin, capture stderr |
| `nexus3/mcp/transport.py` | Buffer stderr, include in crash errors |
| `nexus3/mcp/client.py` | Add context to timeout/protocol errors |
| `nexus3/core/errors.py` | Add `context` field to MCPConfigError |

### Effort

- **Estimated:** 3-4 hours
- **Risk:** Low (improves error messages without changing behavior)
- **Priority:** High (significantly improves user experience)

---

## Priority 2.0: Windows Compatibility

**Status:** MCP stdio transport has several issues that would affect Windows users.

### The Problems

#### 2.0.1 Missing Windows Environment Variables

**Current `SAFE_ENV_KEYS`:**
```python
SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL",
    "LC_CTYPE", "TERM", "SHELL", "TMPDIR", "TMP", "TEMP",
})
```

**Missing Windows-essential vars:**

| Variable | Purpose | Impact if Missing |
|----------|---------|-------------------|
| `USERPROFILE` | Windows home directory | `HOME` may not exist on Windows; Node.js, npm use this |
| `HOMEDRIVE` + `HOMEPATH` | Alternative home path | Some tools use these instead of USERPROFILE |
| `APPDATA` | Application data | npm global config, many tools store config here |
| `LOCALAPPDATA` | Local app data | npm cache, node_modules location |
| `PATHEXT` | Executable extensions | **Critical:** Without this, `npx` won't resolve to `npx.cmd` |
| `SYSTEMROOT` | Windows directory | Many system calls need this |
| `COMSPEC` | Command processor | Needed for `cmd /c` fallbacks |

**Fix:**
```python
SAFE_ENV_KEYS = frozenset({
    # Cross-platform
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL",
    "LC_CTYPE", "TERM", "SHELL", "TMPDIR", "TMP", "TEMP",
    # Windows-specific
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "APPDATA", "LOCALAPPDATA",
    "PATHEXT", "SYSTEMROOT", "COMSPEC",
})
```

#### 2.0.2 Command Extension Resolution

**Problem:** On Windows, `npx` is actually `npx.cmd`. Python's `create_subprocess_exec()` without `shell=True` doesn't automatically resolve `.cmd`/`.bat` extensions.

**Current behavior:**
```python
# This fails on Windows:
command = ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
await asyncio.create_subprocess_exec(*command, ...)  # FileNotFoundError: npx
```

**User workarounds (documented but not ideal):**
```json
// Windows users must use full path or cmd wrapper:
{"command": ["cmd", "/c", "npx", "-y", "..."]}
// Or:
{"command": ["C:/Program Files/nodejs/npx.cmd", "-y", "..."]}
```

**Proper fix - resolve command on Windows:**
```python
import shutil
import sys

def resolve_command(command: list[str]) -> list[str]:
    """Resolve command for cross-platform execution.

    On Windows, finds .cmd/.bat/.exe extensions via PATHEXT.
    """
    if sys.platform != "win32" or not command:
        return command

    executable = command[0]

    # If already has extension or is absolute path with extension, use as-is
    if any(executable.lower().endswith(ext) for ext in ['.exe', '.cmd', '.bat', '.com']):
        return command

    # Try to find via shutil.which (respects PATHEXT)
    resolved = shutil.which(executable)
    if resolved:
        return [resolved] + command[1:]

    return command  # Fall back to original, let it fail with clear error
```

#### 2.0.3 Line Ending Handling

**Problem:** Code searches for `\n` only. Windows MCP servers might output `\r\n`.

**Current:**
```python
newline_idx = chunk.find(b"\n")
```

**Impact:** JSON line would include trailing `\r`:
```python
line = b'{"result": {}}\r\n'
# After find(\n) and slice:
line = b'{"result": {}}\r'  # \r remains
json.loads(line)  # Works (JSON ignores whitespace), but not ideal
```

**Fix - strip CR:**
```python
# In receive() after reading line:
line = line.rstrip(b"\r\n")
return json.loads(line.decode("utf-8"))
```

Or handle both in `_read_bounded_line`:
```python
# Look for either \n or \r\n
newline_idx = chunk.find(b"\n")
if newline_idx > 0 and chunk[newline_idx - 1:newline_idx] == b"\r":
    # Include \r in the line (will be stripped when parsing)
    pass  # newline_idx already points to \n
```

#### 2.0.4 Process Group Handling

**Current:** Uses `terminate()` and `kill()` which work differently on Windows.

**Impact:** On Unix, `terminate()` sends SIGTERM. On Windows, it calls `TerminateProcess()`. Child processes spawned by the MCP server may not be terminated.

**Fix for orphan prevention:**
```python
import sys

if sys.platform == "win32":
    # Windows: use CREATE_NEW_PROCESS_GROUP and send CTRL_BREAK_EVENT
    import subprocess
    self._process = await asyncio.create_subprocess_exec(
        *self._command,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        ...
    )
else:
    # Unix: use start_new_session for process group
    self._process = await asyncio.create_subprocess_exec(
        *self._command,
        start_new_session=True,
        ...
    )
```

### Windows Error Message Improvements

The error messages from Priority 1.9 should include Windows-specific hints:

**Command not found on Windows:**
```
MCP Server Launch Failed
━━━━━━━━━━━━━━━━━━━━━━━━

Server: "filesystem"
Command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]

Problem: Command not found: npx

Windows-specific causes:
  1. npx.cmd exists but PATHEXT not passed to subprocess
  2. Node.js not installed or not in PATH

Fix options:
  • Use full command path: ["C:/Program Files/nodejs/npx.cmd", ...]
  • Use cmd wrapper: ["cmd", "/c", "npx", ...]
  • Add to env_passthrough: ["PATHEXT", "APPDATA", "LOCALAPPDATA"]
```

### Implementation

| File | Changes |
|------|---------|
| `nexus3/mcp/transport.py` | Add Windows env vars, command resolution, CRLF handling |
| `nexus3/mcp/error_formatter.py` | Windows-specific error hints |
| `tests/unit/mcp/test_transport.py` | Windows-specific tests (can mock sys.platform) |

### Effort

- **Estimated:** 2-3 hours
- **Risk:** Low (additive changes, cross-platform logic is isolated)
- **Priority:** Medium-High (blocks Windows users entirely in some cases)

---

## Summary

| Category | Implemented | Not Implemented |
|----------|-------------|-----------------|
| **Tools** | `tools/list`, `tools/call` | - |
| **Resources** | - | All (list, read, subscribe, templates) |
| **Prompts** | - | All (list, get) |
| **Sampling** | - | `sampling/createMessage` |
| **Roots** | - | `roots/list` |
| **Elicitation** | - | `elicitation/request` |
| **Utilities** | - | ping, cancellation, progress, logging |
| **Transports** | stdio, HTTP | SSE (Server-Sent Events) |

---

## Currently Implemented

### Tools (Server Capability)
- `tools/list` - Discover available tools from MCP server
- `tools/call` - Execute a tool with arguments

### Transports
- **StdioTransport** - Launch MCP server as subprocess, communicate via stdin/stdout
- **HTTPTransport** - Connect to remote MCP server via HTTP POST

### Security Hardening
- **P2.9:** Response ID matching (prevents response confusion attacks)
- **P2.10:** Notification discarding (handles up to 100 interleaved notifications)
- **P2.11:** Deny-by-default permission model
- **P2.12:** 10MB line length limit for stdio transport
- **Environment sanitization:** Only safe env vars passed by default
- **SSRF protection:** URL validation for HTTP transport

### Protocol Basics
- `initialize` handshake with protocol version
- `notifications/initialized` notification
- JSON-RPC 2.0 message format
- Client info exchange

---

## Not Implemented

### 1. Resources (Server Capability)

**Spec Reference:** [MCP Resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)

**What it is:** Resources allow MCP servers to expose context data (files, database schemas, API docs) that clients can selectively include in LLM context.

**MCP Methods:**
| Method | Description |
|--------|-------------|
| `resources/list` | Discover available resources with pagination |
| `resources/read` | Retrieve resource content (text or binary) |
| `resources/templates/list` | List parameterized URI templates |
| `resources/subscribe` | Subscribe to resource updates |
| `resources/unsubscribe` | Unsubscribe from updates |

**Notifications:**
- `notifications/resources/updated` - Resource content changed
- `notifications/resources/list_changed` - Available resources changed

**Data Structures (from spec):**
```python
@dataclass
class MCPResource:
    uri: str                              # Required - unique identifier
    name: str                             # Required - display name
    title: str | None = None              # Human-readable title
    description: str | None = None
    mime_type: str | None = None
    size: int | None = None               # Size in bytes
    icons: list[dict] | None = None
    annotations: dict | None = None       # audience, priority, lastModified

@dataclass
class MCPResourceContent:
    uri: str
    mime_type: str | None = None
    text: str | None = None               # For text content
    blob: str | None = None               # For binary (base64)
```

**Use Cases:**
- Include project files in LLM context
- Reference database schemas without reading entire DB
- Access API documentation dynamically
- Track file changes in real-time

**Priority:** Medium-High. Many MCP servers expose resources alongside tools.

**Implementation Effort:** Medium. Requires:
- New methods in `MCPClient`
- Resource types in `protocol.py`
- UI for resource selection in REPL
- Context integration for including resources in prompts

---

### 2. Prompts (Server Capability)

**Spec Reference:** [MCP Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)

**What it is:** Prompts are reusable message templates that servers expose, allowing users to invoke predefined interactions (like slash commands).

**MCP Methods:**
| Method | Description |
|--------|-------------|
| `prompts/list` | Discover available prompts |
| `prompts/get` | Get prompt messages with argument substitution |

**Notifications:**
- `notifications/prompts/list_changed` - Available prompts changed

**Data Structures (from spec):**
```python
@dataclass
class MCPPrompt:
    name: str                             # Required - unique identifier
    title: str | None = None              # Human-readable name
    description: str | None = None
    arguments: list[MCPPromptArgument] | None = None
    icons: list[dict] | None = None

@dataclass
class MCPPromptArgument:
    name: str                             # Required
    description: str | None = None
    required: bool = False

@dataclass
class MCPPromptMessage:
    role: str                             # "user" or "assistant"
    content: dict | list[dict]            # text, image, audio, or resource
```

**Use Cases:**
- Code review templates
- Documentation generation prompts
- Domain-specific workflows
- Standardized interactions across projects

**Priority:** Low-Medium. NEXUS3 has its own skill system that covers similar use cases.

**Implementation Effort:** Low-Medium. Requires:
- New methods in `MCPClient`
- Prompt types in `protocol.py`
- Integration with REPL command system

---

### 3. Sampling (Client Capability)

**Spec Reference:** [MCP Sampling](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)

**What it is:** Sampling allows MCP servers to request LLM completions from the client. This enables servers to implement agentic behaviors without needing their own LLM API keys.

**MCP Methods:**
| Method | Direction | Description |
|--------|-----------|-------------|
| `sampling/createMessage` | Server → Client | Server requests LLM completion |

**Request Structure (from spec):**
```json
{
  "method": "sampling/createMessage",
  "params": {
    "messages": [
      {"role": "user", "content": {"type": "text", "text": "..."}}
    ],
    "modelPreferences": {
      "hints": [{"name": "claude-3-sonnet"}],
      "intelligencePriority": 0.8,
      "speedPriority": 0.5,
      "costPriority": 0.3
    },
    "systemPrompt": "You are a helpful assistant.",
    "maxTokens": 1000,
    "tools": [...],
    "toolChoice": {"mode": "auto"}
  }
}
```

**Response Structure:**
```json
{
  "result": {
    "role": "assistant",
    "content": {"type": "text", "text": "..."},
    "model": "claude-3-sonnet-20240307",
    "stopReason": "endTurn"
  }
}
```

**Flow:**
1. MCP server sends `sampling/createMessage` request
2. NEXUS3 client prompts user for approval (security)
3. Client sends request to LLM provider
4. Client returns response to MCP server
5. Server can iterate with tool calls

**Use Cases:**
- MCP server implements autonomous agent logic
- Server needs LLM reasoning to decide next action
- Multi-step workflows orchestrated by MCP server
- No API key sharing required

**Priority:** Medium. Enables sophisticated MCP server patterns.

**Implementation Effort:** High. Requires:
- Bidirectional message handling (client receiving requests)
- User consent UI for sampling requests
- Integration with NEXUS3's provider system
- Tool use loop handling within sampling

**Note:** This inverts the normal client-server relationship - the MCP server requests LLM completions from the NEXUS3 client.

---

### 4. Roots (Client Capability)

**Spec Reference:** [MCP Roots](https://modelcontextprotocol.io/specification/2025-11-25/client/roots)

**What it is:** Roots allow MCP servers to query the client for filesystem/URI boundaries, helping servers understand what paths are valid for operations.

**MCP Methods:**
| Method | Direction | Description |
|--------|-----------|-------------|
| `roots/list` | Server → Client | Query valid root paths |

**Response Structure (from spec):**
```json
{
  "result": {
    "roots": [
      {
        "uri": "file:///home/user/projects/myproject",
        "name": "My Project"
      },
      {
        "uri": "file:///home/user/documents",
        "name": "Documents"
      }
    ]
  }
}
```

**Capability Declaration:**
```json
{
  "capabilities": {
    "roots": {
      "listChanged": true
    }
  }
}
```

**Use Cases:**
- MCP server asks "what directories can I access?"
- Filesystem server discovers project boundaries
- Database server learns valid connection strings

**Priority:** Low. Most MCP servers work without this.

**Implementation Effort:** Low. Requires:
- Handle incoming `roots/list` request
- Return configured allowed paths (map from NEXUS3's `allowed_paths`)

---

### 5. Elicitation (Client Capability)

**Spec Reference:** [MCP Elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)

**What it is:** Elicitation allows MCP servers to request additional information from the user through the client.

**MCP Methods:**
| Method | Direction | Description |
|--------|-----------|-------------|
| `elicitation/request` | Server → Client | Request user input |

**Request Structure (from spec):**
```json
{
  "method": "elicitation/request",
  "params": {
    "message": "Please enter your API key",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "apiKey": {"type": "string", "description": "Your API key"}
      },
      "required": ["apiKey"]
    }
  }
}
```

**Response Structure:**
```json
{
  "result": {
    "action": "accept",
    "content": {"apiKey": "sk-..."}
  }
}
```

Or rejection:
```json
{
  "result": {
    "action": "reject"
  }
}
```

**Use Cases:**
- MCP server needs API key from user
- Server requires confirmation before destructive action
- Interactive setup/configuration flows

**Priority:** Low-Medium. Nice for interactive MCP servers.

**Implementation Effort:** Medium. Requires:
- Handle incoming elicitation requests
- UI for presenting questions to user
- Return user responses to server

---

### 6. Protocol Utilities

**Spec Reference:** [MCP Utilities](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities)

#### ping

**Spec Reference:** [MCP Ping](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/ping)

**What it is:** Simple health check method.

**Request/Response:**
```json
// Request
{"method": "ping", "params": {}}

// Response
{"result": {}}
```

**Priority:** Low. Connection health can be inferred from other methods.

**Effort:** Trivial.

---

#### Cancellation

**Spec Reference:** [MCP Cancellation](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation)

**What it is:** Ability to cancel in-progress requests using `_meta.cancellationToken`.

**How it works:**
1. Client sends request with `_meta: {cancellationToken: "token-123"}`
2. Client can send `notifications/cancelled` with token to cancel
3. Server stops processing and returns partial/error result

**Request with cancellation token:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "long_running_tool",
    "arguments": {},
    "_meta": {
      "cancellationToken": "cancel-123"
    }
  }
}
```

**Cancellation notification:**
```json
{
  "method": "notifications/cancelled",
  "params": {
    "requestId": 5,
    "reason": "User requested cancellation"
  }
}
```

**Priority:** Medium. Useful for long-running tool calls.

**Effort:** Low-Medium. Requires tracking active requests and handling cancellation notifications.

---

#### Progress Tracking

**Spec Reference:** [MCP Progress](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress)

**What it is:** Servers can send progress notifications during long operations.

**How it works:**
1. Client sends request with `_meta: {progressToken: "progress-123"}`
2. Server sends `notifications/progress` with percentage/status
3. Client displays progress to user

**Request with progress token:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "process_files",
    "arguments": {},
    "_meta": {
      "progressToken": "progress-456"
    }
  }
}
```

**Progress notification:**
```json
{
  "method": "notifications/progress",
  "params": {
    "progressToken": "progress-456",
    "progress": 50,
    "total": 100,
    "message": "Processing file 50 of 100"
  }
}
```

**Priority:** Low-Medium. Nice UX improvement for slow tools.

**Effort:** Medium. Requires progress notification handling and UI updates.

---

#### Logging

**Spec Reference:** [MCP Logging](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging)

**What it is:** MCP servers can send log messages to clients at various levels.

**Log notification:**
```json
{
  "method": "notifications/message",
  "params": {
    "level": "info",
    "logger": "database",
    "data": "Connected to PostgreSQL at localhost:5432"
  }
}
```

**Log levels:** `debug`, `info`, `notice`, `warning`, `error`, `critical`, `alert`, `emergency`

**Capability declaration:**
```json
{
  "capabilities": {
    "logging": {}
  }
}
```

**Client can set log level:**
```json
{
  "method": "logging/setLevel",
  "params": {
    "level": "warning"
  }
}
```

**Priority:** Low. Useful for debugging MCP server issues.

**Effort:** Low. Just handle and display log notifications.

---

### 7. SSE Transport (Streamable HTTP)

**Spec Reference:** [MCP Transports - Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http)

**What it is:** Server-Sent Events transport for HTTP streaming, enabling real-time server→client messages.

**How it works:**
- HTTP POST for client→server messages
- GET with `Accept: text/event-stream` opens SSE stream for server→client
- Supports reconnection with `Last-Event-ID`
- Session management via `MCP-Session-Id` header

**Required headers:**
```
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-11-25
MCP-Session-Id: <session-id>  (after initialization)
```

**SSE event format:**
```
event: message
id: unique-event-id
data: {"jsonrpc":"2.0","method":"notifications/progress",...}
```

**Reconnection:**
```
GET /mcp
Last-Event-ID: previous-event-id
```

**Priority:** Low. Stdio and basic HTTP cover most use cases.

**Effort:** Medium. Requires SSE client implementation with reconnection logic.

---

### 8. Capability Negotiation

**Spec Reference:** [MCP Lifecycle - Capabilities](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle#capabilities)

**Current State:** NEXUS3 sends `capabilities: {}` during initialization and doesn't parse server capabilities.

**Client capabilities (what NEXUS3 should declare):**
```json
{
  "capabilities": {
    "sampling": {},                    // If implementing sampling
    "roots": {"listChanged": true},    // If implementing roots
    "elicitation": {                   // If implementing elicitation
      "form": {},
      "url": {}
    }
  }
}
```

**Server capabilities (what NEXUS3 should respect):**
```json
{
  "capabilities": {
    "tools": {"listChanged": true},      // Listen for tool list changes
    "resources": {
      "subscribe": true,                  // Resource subscriptions supported
      "listChanged": true                 // Listen for resource list changes
    },
    "prompts": {"listChanged": true},    // Listen for prompt list changes
    "logging": {}                         // Server sends log messages
  }
}
```

**What's Missing:**
- Declare client capabilities (would need to implement sampling/roots/elicitation first)
- Parse and respect server capabilities (e.g., `resources.subscribe`, `prompts.listChanged`)
- Handle capability-specific behavior (subscribe to `listChanged` notifications)

**Priority:** Medium. Should be done alongside implementing new features.

**Effort:** Low per feature.

---

## Implementation Recommendations

### Phase 1: Resources (High Value)

Resources are the most commonly used MCP feature after tools. Many popular MCP servers (filesystem, database, git) expose resources.

1. Add `resources/list`, `resources/read` to `MCPClient`
2. Add resource types to `protocol.py`
3. Add `/mcp resources` REPL command to browse
4. Consider auto-including high-priority resources in context

### Phase 2: Cancellation + Progress (UX)

These improve the experience when tools take a long time:

1. Add `_meta` support to request construction
2. Handle `notifications/progress`
3. Handle `notifications/cancelled`
4. Show progress in REPL during tool execution

### Phase 3: Prompts (Low Effort)

Prompts are relatively simple to add:

1. Add `prompts/list`, `prompts/get` to `MCPClient`
2. Add prompt types to `protocol.py`
3. Integrate with REPL command system (e.g., `/mcp prompts`, `/mcp prompt <name>`)

### Phase 4: Sampling (High Effort, High Value)

Sampling enables powerful MCP server patterns but requires significant work:

1. Refactor MCPClient to handle bidirectional messages
2. Implement consent UI for sampling requests
3. Integrate with NEXUS3 provider for LLM calls
4. Handle tool use loops within sampling
5. Add capability declaration

### Deferred

- **Roots/Elicitation:** Implement when specific MCP servers need them
- **SSE Transport:** Implement if HTTP streaming becomes common
- **Logging:** Nice to have, low priority

---

## Testing Considerations

When implementing new MCP features:

1. **Extend test server** (`nexus3/mcp/test_server/`) with new capabilities
2. **Add protocol tests** for new message types
3. **Add integration tests** with real MCP servers (e.g., `@modelcontextprotocol/server-filesystem`)
4. **Test capability negotiation** with servers that use different capability sets

---

## References

- [MCP Specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Resources Spec](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
- [MCP Prompts Spec](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)
- [MCP Sampling Spec](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)
- [MCP Server Examples](https://github.com/modelcontextprotocol/servers)

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-01-23*

### Gap Status Confirmation

| Issue | Documented Status | Current Status | Verified |
|-------|-------------------|----------------|----------|
| Config format (Priority 0) | Gap | Still present | ✓ |
| 1.1 Initialized notification params | Gap | Still present | ✓ |
| 1.2 Client capabilities empty | Acknowledged | As expected | ✓ |
| 1.3 Server capabilities unused | Acknowledged | As expected | ✓ |
| 1.4 Pagination not implemented | Gap | Still present | ✓ |
| 1.5 MCPTool missing fields | Gap | Still present | ✓ |
| 1.6 MCPToolResult missing field | Gap | Still present | ✓ |
| 1.7 HTTP missing version header | Gap | Still present | ✓ |
| 1.8 HTTP missing session mgmt | Gap | Still present | ✓ |

**All documented gaps remain unfixed.** The document accurately reflects the current implementation state.

### Verification Details

- Config loading in `nexus3/context/loader.py` only supports `"servers"` key
- MCPServerConfig uses `command: list[str]` only, not separate command+args
- MCPClient._notify() always includes params even when empty
- MCPClient.list_tools() has no pagination cursor handling
- MCPTool missing: title, output_schema, icons, annotations
- MCPToolResult missing: structured_content
- HTTPTransport missing: MCP-Protocol-Version header, session ID tracking

---

## Implementation Checklist

Use this checklist to track implementation progress. Each item can be assigned to a task agent.

### Priority 0: Config Format Compatibility

- [ ] **P0.1** Update `MCPServerConfig` dataclass to support `command: str | list[str]`
- [ ] **P0.2** Add `args: list[str] | None` field to MCPServerConfig
- [ ] **P0.3** Implement `MCPServerConfig.get_command_list()` helper method
- [ ] **P0.4** Update config loader to check both `mcpServers` and `servers` keys
- [ ] **P0.5** Update `nexus3/config/schema.py` MCPServerConfig schema
- [ ] **P0.6** Add unit tests for official MCP config format
- [ ] **P0.7** Add unit tests for NEXUS3 config format (backward compat)
- [ ] **P0.8** Update MCP README documentation

### Priority 1.1: Initialized Notification Fix

- [ ] **P1.1.1** Modify `MCPClient._notify()` to omit params when empty
- [ ] **P1.1.2** Add unit test verifying notification format

### Priority 1.4: Pagination Support

- [ ] **P1.4.1** Modify `MCPClient.list_tools()` to handle cursor pagination
- [ ] **P1.4.2** Add `nextCursor` handling in list_tools loop
- [ ] **P1.4.3** Add unit test with mock paginated response
- [ ] **P1.4.4** Add integration test with MCP server that paginates

### Priority 1.5: MCPTool Fields

- [ ] **P1.5.1** Add `title: str | None` field to MCPTool
- [ ] **P1.5.2** Add `output_schema: dict[str, Any] | None` field
- [ ] **P1.5.3** Add `icons: list[dict[str, Any]] | None` field
- [ ] **P1.5.4** Add `annotations: dict[str, Any] | None` field
- [ ] **P1.5.5** Update `MCPTool.from_dict()` to parse new fields
- [ ] **P1.5.6** Add unit tests for MCPTool parsing

### Priority 1.6: MCPToolResult Field

- [ ] **P1.6.1** Add `structured_content: dict[str, Any] | None` field
- [ ] **P1.6.2** Update `MCPToolResult.from_dict()` to parse structuredContent
- [ ] **P1.6.3** Add unit test for MCPToolResult parsing

### Priority 1.7: HTTP Protocol Version Header

- [ ] **P1.7.1** Add `MCP-Protocol-Version` header to HTTPTransport
- [ ] **P1.7.2** Add `Accept` header with json and event-stream
- [ ] **P1.7.3** Add unit test verifying headers

### Priority 1.8: HTTP Session Management

- [ ] **P1.8.1** Add `_session_id: str | None` field to HTTPTransport
- [ ] **P1.8.2** Capture session ID from response headers
- [ ] **P1.8.3** Include session ID in subsequent requests
- [ ] **P1.8.4** Add unit test for session ID flow

### Priority 1.9: Improved Error Messages

- [ ] **P1.9.1** Create `nexus3/mcp/errors.py` with `MCPErrorContext` dataclass
- [ ] **P1.9.2** Create `nexus3/mcp/error_formatter.py` with formatting functions
- [ ] **P1.9.3** Add `context: MCPErrorContext | None` field to `MCPConfigError`
- [ ] **P1.9.4** Update `ContextLoader._merge_mcp_servers()` to pass source path/layer to errors
- [ ] **P1.9.5** Update `MCPServerRegistry.connect()` to track config origin in errors
- [ ] **P1.9.6** Update `StdioTransport` to buffer stderr and include in crash errors
- [ ] **P1.9.7** Implement `format_config_validation_error()` with field-specific suggestions
- [ ] **P1.9.8** Implement `format_command_not_found()` with installation hints
- [ ] **P1.9.9** Implement `format_server_crash()` with stderr context
- [ ] **P1.9.10** Implement `format_json_syntax_error()` with line/column pointer
- [ ] **P1.9.11** Implement `format_timeout_error()` with handshake troubleshooting
- [ ] **P1.9.12** Add unit tests for error formatting functions
- [ ] **P1.9.13** Add integration tests verifying user-facing error output

### Priority 2.0: Windows Compatibility

- [ ] **P2.0.1** Add Windows env vars to `SAFE_ENV_KEYS`: USERPROFILE, HOMEDRIVE, HOMEPATH, APPDATA, LOCALAPPDATA, PATHEXT, SYSTEMROOT, COMSPEC
- [ ] **P2.0.2** Implement `resolve_command()` helper using `shutil.which()` for Windows .cmd/.bat resolution
- [ ] **P2.0.3** Update `StdioTransport.connect()` to use `resolve_command()` on Windows
- [ ] **P2.0.4** Handle CRLF line endings in `_read_bounded_line()` or `receive()`
- [ ] **P2.0.5** Add Windows process group handling (CREATE_NEW_PROCESS_GROUP) for clean shutdown
- [ ] **P2.0.6** Add Windows-specific hints to error formatter (PATHEXT, .cmd extensions)
- [ ] **P2.0.7** Add unit tests for Windows command resolution (mock sys.platform)
- [ ] **P2.0.8** Add unit tests for CRLF handling
- [ ] **P2.0.9** Document Windows-specific config in MCP README (cmd wrapper, env vars)

### Phase 2: Resources (Future)

- [ ] **P2.1** Add `resources/list` method to MCPClient
- [ ] **P2.2** Add `resources/read` method
- [ ] **P2.3** Add `MCPResource` dataclass to protocol.py
- [ ] **P2.4** Add `MCPResourceContent` dataclass
- [ ] **P2.5** Add `/mcp resources` REPL command
- [ ] **P2.6** Unit tests for resource methods
- [ ] **P2.7** Integration test with filesystem MCP server

### Phase 3: Prompts (Future)

- [ ] **P3.1** Add `prompts/list` method to MCPClient
- [ ] **P3.2** Add `prompts/get` method
- [ ] **P3.3** Add `MCPPrompt` dataclass
- [ ] **P3.4** Add `MCPPromptArgument` dataclass
- [ ] **P3.5** Add `/mcp prompts` REPL command
- [ ] **P3.6** Unit tests for prompt methods

### Phase 4: Utilities (Future)

- [ ] **P4.1** Implement ping method
- [ ] **P4.2** Implement cancellation (_meta.cancellationToken)
- [ ] **P4.3** Implement progress notifications handling
- [ ] **P4.4** Implement logging notifications handling

### Phase 5: Documentation

- [ ] **P5.1** Update `nexus3/mcp/README.md` with all spec compliance changes
- [ ] **P5.2** Update `CLAUDE.md` MCP section with any new config format changes
- [ ] **P5.3** Document new MCPTool fields in protocol.py docstrings
- [ ] **P5.4** Update `/mcp` command help with new capabilities (if resources/prompts added)

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| MCP client | `nexus3/mcp/client.py` |
| MCP protocol types | `nexus3/mcp/protocol.py` |
| MCP transport | `nexus3/mcp/transport.py` |
| MCP registry | `nexus3/mcp/registry.py` |
| MCP error context | `nexus3/mcp/errors.py` (new) |
| MCP error formatter | `nexus3/mcp/error_formatter.py` (new) |
| Core errors | `nexus3/core/errors.py` |
| Config loader | `nexus3/context/loader.py` |
| Config schema | `nexus3/config/schema.py` |
| Test server | `nexus3/mcp/test_server/` |
| Unit tests | `tests/unit/mcp/` |
| Integration tests | `tests/integration/mcp/` |

---

## Effort Summary

| Priority | Items | Estimated Effort |
|----------|-------|------------------|
| P0 (Config Format) | 8 items | ~2 hours |
| P1.1-1.8 (Protocol Compliance) | 14 items | ~1 hour |
| P1.9 (Error Messages) | 13 items | ~3-4 hours |
| P2.0 (Windows Compat) | 9 items | ~2-3 hours |
| Phase 2 (Resources) | 7 items | ~4 hours |
| Phase 3 (Prompts) | 6 items | ~3 hours |
| Phase 4 (Utilities) | 4 items | ~2 hours |

**Priority 0, P1.x, and P2.0 should be addressed first** to ensure basic MCP spec compliance, config compatibility, good error messages, and Windows support.
