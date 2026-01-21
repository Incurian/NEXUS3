# RPC Schema for Terminal Unification

New RPC methods needed for full terminal parity.

**Conventions:**
- Global methods: called on root endpoint (`/`)
- Agent methods: called on agent endpoint (`/agent/{agent_id}`)
- All requests are JSON-RPC 2.0: `{jsonrpc:"2.0", method, params, id}`
- Auth headers omitted for brevity (HTTP layer enforces them)

---

## A) Global (Root-Scoped) Methods

### A1) `list_sessions` (NEW) - Session discovery for lobby

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "list_sessions",
  "params": {
    "offset": 0,
    "limit": 50,
    "include_temp": false
  },
  "id": 1
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "total": 12,
    "offset": 0,
    "limit": 50,
    "sessions": [
      {
        "name": "main",
        "message_count": 104,
        "created_at": 1737312345.12,
        "updated_at": 1737399999.01,
        "is_temp": false,
        "provenance": "user",
        "model": "gpt-4o-mini",
        "permission_level": "trusted",
        "cwd": "/home/inc/repos/NEXUS3"
      }
    ]
  },
  "id": 1
}
```

---

### A2) `load_session` (NEW) - Restore saved session into agent

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "load_session",
  "params": {
    "session_name": "my-session",
    "agent_id": "my-session",
    "preset": null,
    "model": null
  },
  "id": 2
}
```

Notes:
- `agent_id` optional; if omitted, load into same name
- `preset/model` optional overrides

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "restored": true,
    "agent_id": "my-session",
    "message_count": 87
  },
  "id": 2
}
```

---

### A3) `save_session` (NEW) - Save active agent as named session

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "save_session",
  "params": {
    "agent_id": ".3",
    "session_name": "project-x"
  },
  "id": 3
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "saved": true,
    "session_name": "project-x",
    "agent_id": "project-x"
  },
  "id": 3
}
```

---

### A4) `clone_session` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "clone_session",
  "params": {
    "src_session": "project-x",
    "dest_session": "project-x-copy"
  },
  "id": 4
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "cloned": true,
    "src_session": "project-x",
    "dest_session": "project-x-copy"
  },
  "id": 4
}
```

---

### A5) `rename_session` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "rename_session",
  "params": {
    "old_name": "project-x-copy",
    "new_name": "project-x-archived"
  },
  "id": 5
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "renamed": true,
    "old_name": "project-x-copy",
    "new_name": "project-x-archived"
  },
  "id": 5
}
```

---

### A6) `delete_session` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "delete_session",
  "params": { "session_name": "project-x-archived" },
  "id": 6
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": { "deleted": true, "session_name": "project-x-archived" },
  "id": 6
}
```

---

### A7) `get_agent_summaries` (NEW, nice-to-have) - Status for all agents

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "get_agent_summaries",
  "params": {
    "include_tokens": true,
    "include_context": true
  },
  "id": 7
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "agents": [
      {
        "agent_id": "main",
        "message_count": 104,
        "cwd": "/home/inc/repos/NEXUS3",
        "permission_level": "trusted",
        "model": "gpt-4o-mini",
        "halted_at_iteration_limit": false,
        "last_action_at": "2026-01-20T09:11:02",
        "tokens": { "total": 12345, "budget": 200000 }
      }
    ]
  },
  "id": 7
}
```

---

## B) Agent-Scoped Methods

### B1) `set_cwd` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "set_cwd",
  "params": { "cwd": "/home/inc/repos/NEXUS3" },
  "id": 101
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": { "cwd": "/home/inc/repos/NEXUS3" },
  "id": 101
}
```

---

### B2) `get_permissions` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "get_permissions",
  "params": {},
  "id": 102
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "permission_level": "trusted",
    "preset": "trusted",
    "disabled_tools": ["shell_UNSAFE"],
    "policy": {
      "cwd": "/home/inc/repos/NEXUS3",
      "allowed_paths": null,
      "blocked_paths": ["/etc", "/proc"]
    },
    "session_allowances": {
      "write_paths": ["/home/inc/repos/NEXUS3/tmp"],
      "exec_dirs": { "bash_safe": ["/home/inc/repos/NEXUS3"] }
    }
  },
  "id": 102
}
```

---

### B3) `set_permissions` (NEW)

**Request (preset switch)**
```json
{
  "jsonrpc": "2.0",
  "method": "set_permissions",
  "params": { "preset": "sandboxed" },
  "id": 103
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": { "updated": true, "permission_level": "sandboxed", "preset": "sandboxed" },
  "id": 103
}
```

---

### B4) `get_system_prompt` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "get_system_prompt",
  "params": {},
  "id": 104
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "system_prompt": ".... full prompt text ...",
    "system_prompt_path": "/home/inc/repos/NEXUS3/NEXUS.md"
  },
  "id": 104
}
```

---

### B5) `set_system_prompt` (NEW)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "set_system_prompt",
  "params": { "system_prompt": "You are NEXUS3..." },
  "id": 105
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": { "updated": true },
  "id": 105
}
```

---

### B6) `get_model` (NEW, nice-to-have)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "get_model",
  "params": {},
  "id": 106
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": { "model": "gpt-4o-mini", "provider": "openai", "reasoning": false },
  "id": 106
}
```

---

### B7) `set_model` (NEW, nice-to-have)

**Request**
```json
{
  "jsonrpc": "2.0",
  "method": "set_model",
  "params": { "model": "gpt-4o" },
  "id": 107
}
```

**Response**
```json
{
  "jsonrpc": "2.0",
  "result": { "updated": true, "model": "gpt-4o" },
  "id": 107
}
```

---

## C) MCP Management (Phase 2)

Deferred unless needed immediately:

- `mcp_list_servers`
- `mcp_connect`
- `mcp_disconnect`
- `mcp_status`

---

## Priority Summary

### Must-Have (Milestone 1-3)

| Method | Scope | For Command |
|--------|-------|-------------|
| `list_sessions` | Global | Lobby, `/sessions` |
| `load_session` | Global | `/resume`, restore |
| `save_session` | Global | `/save` |
| `clone_session` | Global | `/clone` |
| `rename_session` | Global | `/rename` |
| `delete_session` | Global | `/delete` |
| `set_cwd` | Agent | `/cwd` |
| `get_permissions` | Agent | `/permissions` |
| `set_permissions` | Agent | `/permissions` |
| `get_system_prompt` | Agent | `/prompt` |
| `set_system_prompt` | Agent | `/prompt` |

### Nice-to-Have (Milestone 4+)

| Method | Scope | For Command |
|--------|-------|-------------|
| `get_agent_summaries` | Global | `/status --all` |
| `get_model` | Agent | `/model` |
| `set_model` | Agent | `/model` |
| MCP methods | Agent | `/mcp` |
