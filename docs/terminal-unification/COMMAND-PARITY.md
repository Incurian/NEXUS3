# Command Parity Analysis

Analysis of slash commands and their RPC requirements for terminal unification.

---

## Commands Already Have RPC Equivalent

These commands can be made identical now - they just need client-side implementation in synced mode.

| Command | RPC Method | Notes |
|---------|------------|-------|
| `/list` | `list_agents` (global) | Already exists |
| `/create <name>` | `create_agent` (global) | Already exists |
| `/destroy <name>` | `destroy_agent` (global) | Already exists |
| `/status [agent]` | `get_tokens`, `get_context` (agent) | Single-agent status |
| `/compact` | `compact` (agent) | Already exists |
| `/cancel` | `cancel` (agent) | Already exists |
| `/clear` | N/A | Local UI only |
| `/help` | N/A | Local UI only |
| `/quit` | Maybe `shutdown_server` | Depends on behavior |

---

## Commands Need New RPC Methods

### Session Management (Global)

| Command | Needs RPC Method | Priority |
|---------|------------------|----------|
| `/save [name]` | `save_session` | Must-have |
| `/clone <src> <dest>` | `clone_session` | Must-have |
| `/rename <old> <new>` | `rename_session` | Must-have |
| `/delete <name>` | `delete_session` | Must-have |
| `/resume [name]` | `load_session` | Must-have |
| Lobby session list | `list_sessions` | Must-have |
| `/status --all` | `get_agent_summaries` | Nice-to-have |

### Agent Configuration (Agent-scoped)

| Command | Needs RPC Method | Priority |
|---------|------------------|----------|
| `/cwd [path]` | `set_cwd` | Must-have |
| `/permissions` | `get_permissions` | Must-have |
| `/permissions <preset>` | `set_permissions` | Must-have |
| `/prompt` | `get_system_prompt` | Must-have |
| `/prompt <text>` | `set_system_prompt` | Must-have |
| `/model` | `get_model` | Nice-to-have |
| `/model <name>` | `set_model` | Nice-to-have |

### MCP (Phase 2)

| Command | Needs RPC Method | Priority |
|---------|------------------|----------|
| `/mcp list` | `mcp_list_servers` | Phase 2 |
| `/mcp connect` | `mcp_connect` | Phase 2 |
| `/mcp disconnect` | `mcp_disconnect` | Phase 2 |
| `/mcp status` | `mcp_status` | Phase 2 |

---

## Commands That Are Client-Side State

These don't need RPC - they're purely client-side state management.

| Command | Description |
|---------|-------------|
| `/agent <id>` | Switch which agent this terminal talks to |
| `/whisper <id>` | Set whisper target |
| `/over` | End whisper mode |
| `/switch <id>` | Alias for `/agent` |

Implementation:
- Use `list_agents` RPC to validate agent exists
- Update local `ReplState.current_agent_id`
- Reconnect SSE to new agent endpoint
- No server-side state change needed

---

## Commands That Are Unavoidably Host-Only

| Command | Reason |
|---------|--------|
| `/init` | Creates local NEXUS.md scaffolding - filesystem initializer |
| Starting the server | By definition |

Note: Under the local-trust model, even session persistence could be exposed via RPC. The only truly unavoidable host-only action is "start the server".

---

## Implementation Order

### Phase 1 (Milestone 1-2): Core Identical Experience

No new RPC methods needed - just client-side refactoring:
- Send/cancel/confirm via RPC
- Events via SSE
- `/list`, `/create`, `/destroy`, `/status`, `/compact`, `/cancel`
- `/agent`, `/whisper`, `/over` (client-side state)
- `/clear`, `/help`, `/quit`

### Phase 2 (Milestone 3): Session Parity

New global RPC methods:
- `list_sessions`, `load_session`, `save_session`
- `clone_session`, `rename_session`, `delete_session`

Commands enabled:
- `/save`, `/clone`, `/rename`, `/delete`, `/resume`
- Lobby session selection

### Phase 3 (Milestone 4): Agent Config Parity

New agent-scoped RPC methods:
- `set_cwd`, `get_permissions`, `set_permissions`
- `get_system_prompt`, `set_system_prompt`
- `get_model`, `set_model` (optional)

Commands enabled:
- `/cwd`, `/permissions`, `/prompt`, `/model`

### Phase 4 (Milestone 5): MCP Parity (Optional)

New agent-scoped RPC methods:
- `mcp_list_servers`, `mcp_connect`, `mcp_disconnect`, `mcp_status`

Commands enabled:
- `/mcp` suite

---

## Gap Analysis: Current Synced Mode

What synced mode currently supports:
- `/help` - Yes
- `/agent` - Partial (no validation)
- Send messages - Yes (via RPC)
- Cancel - Yes (via RPC, needs keybinding)
- Confirmations - Yes (via RPC)

What synced mode is missing:
- Most slash commands (even those with existing RPC)
- Rich Live display (has basic, not identical)
- Bottom toolbar / ready indicator
- Consistent keybindings
