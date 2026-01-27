# MCP Implementation Gaps

This document compares NEXUS3's MCP implementation against the [MCP specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25) and identifies features not yet implemented.

**Last updated:** 2026-01-27

---

## Completed Items

### Priority 0.5: Security Hardening - DONE

All security hardening items have been implemented:
- [x] **S1** HTTP redirect SSRF bypass - `follow_redirects=False`
- [x] **S2** MCP output sanitization with `sanitize_for_display()`
- [x] **S3** MAX_MCP_OUTPUT_SIZE limit (10MB)
- [x] **S4** Config validation error sanitization
- [x] **S5-S7** Security tests added

### Priority 0: Config Format Compatibility - DONE

Both official (`mcpServers` with command+args) and NEXUS3 (`servers` with command array) formats now supported.
- [x] **P0.1-P0.4** MCPServerConfig updated in both `schema.py` and `registry.py`
- [x] **P0.5-P0.6** Config loader handles both `mcpServers` (dict) and `servers` (array)
- [x] **P0.7** Registry uses `get_command_list()`
- [x] **P0.8-P0.10** Tests and documentation updated

### Priority 1.1: Initialized Notification - DONE

- [x] **P1.1.1** `MCPClient._notify()` omits params when empty
- [x] **P1.1.2** Unit test added

### Priority 1.4: Pagination Support - DONE

- [x] **P1.4.1-P1.4.3** `list_tools()` handles cursor pagination with unit tests
- [ ] **P1.4.4** Integration test with paginating MCP server (deferred)

### Priority 1.5: MCPTool Fields - DONE

- [x] **P1.5.1-P1.5.6** Added `title`, `output_schema`, `icons`, `annotations` fields with tests

### Priority 1.6: MCPToolResult Field - DONE

- [x] **P1.6.1-P1.6.3** Added `structured_content` field with tests

### Priority 1.7: HTTP Protocol Version Header - DONE

- [x] **P1.7.1-P1.7.5** Added `MCP-Protocol-Version` and `Accept` headers with tests

### Priority 1.8: HTTP Session Management - DONE

- [x] **P1.8.1-P1.8.5** Session ID capture, validation, and persistence implemented

### Priority 1.10: HTTP Retry Logic - DONE

- [x] **P1.10.1-P1.10.8** Exponential backoff with jitter for 429/5xx errors

---

## Remaining Work

### Priority 1.9: Improved Error Messages

**Status:** MCP errors are currently terse and lack context, making troubleshooting difficult.

#### The Problem

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

#### Improved Error Messages

**1.9.1 Config Validation Errors:**
```
MCP Configuration Error
━━━━━━━━━━━━━━━━━━━━━━━

Server: "github"
Source: ~/.nexus3/mcp.json (global config)

Problem: 'command' must be a list of strings, not a string
  You provided: "npx"
  Expected:     ["npx", "-y", "@modelcontextprotocol/server-github"]

Fix: Change your mcp.json from:
  {"command": "npx", "args": [...]}
To:
  {"command": ["npx", "-y", "@modelcontextprotocol/server-github"]}
```

**1.9.2 Command Not Found:**
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
  • Add to env_passthrough: ["PATH", "NODE_PATH"]
```

**1.9.3 Server Crash with Stderr:**
```
MCP Server Crashed
━━━━━━━━━━━━━━━━━━

Server: "postgres"
Source: ./.nexus3/mcp.json (project config)
Command: ["npx", "-y", "@modelcontextprotocol/server-postgres"]

Problem: Server exited with code 1

Server stderr (last 10 lines):
  Error: connect ECONNREFUSED 127.0.0.1:5432

Troubleshooting:
  • Check if PostgreSQL is running: pg_isready
  • Add to env_passthrough: ["DATABASE_URL"]
```

#### Implementation

**Existing Infrastructure:** `MCPServerWithOrigin` in `nexus3/context/loader.py:98-104` already tracks config origin and source path. P1.9 should extend this.

**New Files:**
- `nexus3/mcp/errors.py` - `MCPErrorContext` dataclass with `from_server_with_origin()` factory
- `nexus3/mcp/error_formatter.py` - Formatting functions for each error type

**Modifications:**
- `nexus3/context/loader.py` - Pass source context to validation errors
- `nexus3/mcp/registry.py` - Track config origin in errors
- `nexus3/mcp/transport.py` - Buffer stderr (deque maxlen=20), include in crash errors
- `nexus3/mcp/client.py` - Add context to timeout/protocol errors
- `nexus3/mcp/skill_adapter.py` - Distinguish MCPError vs MCPTransportError
- `nexus3/core/errors.py` - Add `context` field to MCPConfigError

**Effort:** 3-4 hours

---

### Priority 2.0: Windows Compatibility

**Status:** MCP stdio transport has several issues that would affect Windows users.

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
| `USERPROFILE` | Windows home directory | Node.js, npm use this |
| `APPDATA` | Application data | npm global config |
| `LOCALAPPDATA` | Local app data | npm cache |
| `PATHEXT` | Executable extensions | **Critical:** `npx` won't resolve to `npx.cmd` |
| `SYSTEMROOT` | Windows directory | Many system calls need this |
| `COMSPEC` | Command processor | Needed for `cmd /c` fallbacks |

**Fix:**
```python
SAFE_ENV_KEYS = frozenset({
    # Cross-platform
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL",
    "LC_CTYPE", "TERM", "SHELL", "TMPDIR", "TMP", "TEMP",
    # Windows-specific
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "PATHEXT", "SYSTEMROOT", "COMSPEC",
})
```

#### 2.0.2 Command Extension Resolution

**Problem:** On Windows, `npx` is actually `npx.cmd`. Python's `create_subprocess_exec()` without `shell=True` doesn't resolve `.cmd`/`.bat` extensions.

**Fix:**
```python
import shutil
import sys

def resolve_command(command: list[str]) -> list[str]:
    """Resolve command for cross-platform execution."""
    if sys.platform != "win32" or not command:
        return command

    executable = command[0]
    if any(executable.lower().endswith(ext) for ext in ['.exe', '.cmd', '.bat', '.com']):
        return command

    resolved = shutil.which(executable)
    if resolved:
        return [resolved] + command[1:]
    return command
```

#### 2.0.3 Line Ending Handling

**Problem:** Code searches for `\n` only. Windows MCP servers might output `\r\n`.

**Fix:** Strip CR in receive:
```python
line = line.rstrip(b"\r\n")
```

#### 2.0.4 Process Group Handling

**Problem:** On Windows, `terminate()` calls `TerminateProcess()` and child processes may not be terminated.

**Fix - Process Creation:**
```python
if sys.platform == "win32":
    import subprocess
    self._process = await asyncio.create_subprocess_exec(
        *self._command,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        ...
    )
else:
    self._process = await asyncio.create_subprocess_exec(
        *self._command,
        start_new_session=True,
        ...
    )
```

**Fix - Process Termination:**
```python
if sys.platform == "win32":
    os.kill(self._process.pid, signal.CTRL_BREAK_EVENT)
else:
    pgid = os.getpgid(self._process.pid)
    os.killpg(pgid, signal.SIGTERM)
```

**Also update:** `nexus3/skill/base.py` lines 1019-1025 with Windows process termination.

#### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/transport.py` | Windows env vars, command resolution, CRLF handling |
| `nexus3/mcp/error_formatter.py` | Windows-specific error hints |
| `nexus3/skill/base.py` | Windows process termination |
| `tests/unit/mcp/test_transport.py` | Windows-specific tests |

**Effort:** 2-3 hours

---

### Priority 2.1: Registry Robustness

**Status:** MCP connections can become stale, and tool listing failures block entire server registration.

#### 2.1.1 Stale Connection Detection and Auto-Reconnection

**Problem:**
- `HTTPTransport.is_connected` only checks if client object exists
- `get_all_skills()` returns stale skills from dead connections
- No automatic reconnection when connections fail

**Fix:**
1. Improve `is_connected`:
```python
@property
def is_connected(self) -> bool:
    if self._client is None:
        return False
    return not self._client.is_closed
```

2. Add `reconnect()` to `MCPClient`:
```python
async def reconnect(self, timeout: float = 30.0) -> None:
    await self.close()
    await self.connect(timeout=timeout)
```

3. Add `reconnect()` to `ConnectedServer` (re-lists tools)

4. Make `get_all_skills()` async with lazy reconnection

#### 2.1.2 Graceful Tool Listing Failure

**Problem:** If `client.list_tools()` fails during `connect()`, the entire registration fails.

**Fix:** Wrap tool listing in try/except, continue with empty skills:
```python
try:
    tools = await client.list_tools()
    skills = [MCPSkillAdapter(client, tool, config.name) for tool in tools]
except MCPError as e:
    logger.warning("Failed to list tools from '%s': %s", config.name, e.message)
    skills = []
```

Add `retry_tools()` method and `/mcp retry <server>` command.

#### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/transport.py` | Improve `HTTPTransport.is_connected` |
| `nexus3/mcp/client.py` | Add `reconnect()` method |
| `nexus3/mcp/registry.py` | Add `ConnectedServer.reconnect()`, `retry_tools()`, async `get_all_skills()` |
| `nexus3/config/schema.py` | Add `fail_if_no_tools` to MCPServerConfig |
| `nexus3/cli/repl_commands.py` | Add `/mcp retry <server>` command |

**Note:** P2.1.4 changes `get_all_skills()` to async - must update ALL callers in same commit:
- `nexus3/rpc/pool.py:551, 832`
- `nexus3/cli/repl_commands.py:65, 1853`
- `tests/integration/test_mcp_client.py`

**Effort:** 3-4 hours

---

## Currently Implemented

### Tools (Server Capability)
- `tools/list` - Discover available tools from MCP server
- `tools/call` - Execute a tool with arguments

### Transports
- **StdioTransport** - Launch MCP server as subprocess
- **HTTPTransport** - Connect to remote MCP server via HTTP POST

### Security Hardening
- Response ID matching (prevents response confusion attacks)
- Notification discarding (handles up to 100 interleaved notifications)
- Deny-by-default permission model
- 10MB line length limit for stdio transport
- Environment sanitization
- SSRF protection with redirect blocking
- Output sanitization

### Protocol Basics
- `initialize` handshake with protocol version
- `notifications/initialized` notification (correct format)
- JSON-RPC 2.0 message format
- Client info exchange
- HTTP protocol version header and session management
- Pagination support for `tools/list`

---

## Not Implemented (Future)

### Resources (Server Capability)
Methods: `resources/list`, `resources/read`, `resources/templates/list`, `resources/subscribe`

**Priority:** Medium-High. Many MCP servers expose resources.

### Prompts (Server Capability)
Methods: `prompts/list`, `prompts/get`

**Priority:** Low-Medium. NEXUS3 has its own skill system.

### Sampling (Client Capability)
Method: `sampling/createMessage` (Server → Client)

**Priority:** Medium. Enables sophisticated MCP server patterns.

### Roots (Client Capability)
Method: `roots/list` (Server → Client)

**Priority:** Low. Most MCP servers work without this.

### Elicitation (Client Capability)
Method: `elicitation/request` (Server → Client)

**Priority:** Low-Medium. Nice for interactive MCP servers.

### Protocol Utilities
- ping, cancellation, progress tracking, logging

**Priority:** Low.

### SSE Transport (Streamable HTTP)
**Priority:** Low. Stdio and basic HTTP cover most use cases.

---

## Implementation Checklist

### Priority 1.9: Improved Error Messages

- [ ] **P1.9.1** Create `nexus3/mcp/errors.py` with `MCPErrorContext` dataclass
- [ ] **P1.9.2** Create `nexus3/mcp/error_formatter.py` with formatting functions
- [ ] **P1.9.3** Add `context: MCPErrorContext | None` field to `MCPConfigError`
- [ ] **P1.9.4** Update `ContextLoader._merge_mcp_servers()` to pass source context
- [ ] **P1.9.5** Update `MCPServerRegistry.connect()` to track config origin
- [ ] **P1.9.6** Update `StdioTransport` to buffer stderr (deque maxlen=20)
- [ ] **P1.9.7** Implement `format_config_validation_error()`
- [ ] **P1.9.8** Implement `format_command_not_found()`
- [ ] **P1.9.9** Implement `format_server_crash()`
- [ ] **P1.9.10** Implement `_format_json_error()` helper
- [ ] **P1.9.11** Implement `format_timeout_error()`
- [ ] **P1.9.12** Update `skill_adapter.py` to distinguish MCPError vs MCPTransportError
- [ ] **P1.9.13** Add unit tests for error formatting
- [ ] **P1.9.14** Add integration tests for user-facing error output

### Priority 2.0: Windows Compatibility

- [ ] **P2.0.1** Add Windows env vars to `SAFE_ENV_KEYS`
- [ ] **P2.0.2** Implement `resolve_command()` helper
- [ ] **P2.0.3** Update `StdioTransport.connect()` to use `resolve_command()`
- [ ] **P2.0.4** Handle CRLF line endings
- [ ] **P2.0.5** Add Windows process group creation (CREATE_NEW_PROCESS_GROUP)
- [ ] **P2.0.6** Add Windows process termination (CTRL_BREAK_EVENT)
- [ ] **P2.0.7** Update `skill/base.py` with Windows process termination
- [ ] **P2.0.8** Add Windows-specific hints to error formatter
- [ ] **P2.0.9** Add unit tests for Windows command resolution
- [ ] **P2.0.10** Add unit tests for CRLF handling
- [ ] **P2.0.11** Document Windows-specific config in MCP README

### Priority 2.1: Registry Robustness

- [ ] **P2.1.1** Improve `HTTPTransport.is_connected`
- [ ] **P2.1.2** Add `reconnect()` to `MCPClient`
- [ ] **P2.1.3** Add `reconnect()` to `ConnectedServer`
- [ ] **P2.1.4** Change `get_all_skills()` to async
- [ ] **P2.1.5** Update ALL callers of `get_all_skills()` **(requires P2.1.4, same commit)**
- [ ] **P2.1.6** Wrap tool listing in try/except in `registry.connect()`
- [ ] **P2.1.7** Add `retry_tools()` method
- [ ] **P2.1.8** Add `fail_if_no_tools: bool = False` to MCPServerConfig
- [ ] **P2.1.9** Add `/mcp retry <server>` REPL command
- [ ] **P2.1.10** Add unit tests for reconnection
- [ ] **P2.1.11** Add unit tests for graceful tool listing failure

### Future Phase A: Resources

- [ ] **FA.1-FA.7** resources/list, resources/read, MCPResource dataclass, REPL command, tests

### Future Phase B: Prompts

- [ ] **FB.1-FB.6** prompts/list, prompts/get, MCPPrompt dataclass, REPL command, tests

### Future Phase C: Utilities

- [ ] **FC.1-FC.4** ping, cancellation, progress, logging

### Documentation

- [ ] **P5.1** Update `nexus3/mcp/README.md` with spec compliance changes
- [ ] **P5.2** Update `CLAUDE.md` MCP section
- [ ] **P5.3** Document new MCPTool fields in protocol.py
- [ ] **P5.4** Update `/mcp` command help
- [ ] **P5.5** Document Windows-specific configuration
- [ ] **P5.6** Document error context pattern
- [ ] **P5.7** Document HTTP session ID behavior

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

| Priority | Status | Estimated Effort |
|----------|--------|------------------|
| **P0.5 (Security)** | ✅ DONE | - |
| **P0 (Config Format)** | ✅ DONE | - |
| **P1.1-1.8 (Protocol)** | ✅ DONE | - |
| **P1.10 (HTTP Retry)** | ✅ DONE | - |
| P1.9 (Error Messages) | Pending | ~3-4 hours |
| P2.0 (Windows Compat) | Pending | ~2-3 hours |
| P2.1 (Registry Robustness) | Pending | ~3-4 hours |
| Future Phases (A,B,C) | Deferred | ~9 hours |

**Total remaining for immediate priorities (P1.9, P2.0, P2.1):** ~8-11 hours

### Recommended Execution Order

1. **P1.9** (Error Messages) - Improves debugging for all other work
2. **P2.0** (Windows) - Independent, can parallel
3. **P2.1** (Registry Robustness) - Last, as async migration affects callers

---

## References

- [MCP Specification (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Resources Spec](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
- [MCP Prompts Spec](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)
- [MCP Sampling Spec](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)
- [MCP Server Examples](https://github.com/modelcontextprotocol/servers)
