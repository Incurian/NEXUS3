# REPL Refactor Plan for Terminal Unification

Step-by-step plan to make the host REPL "just another client".

---

## Phase 0: Preparation (S)

### 0.1 Create a "client-mode core loop" function

Extract the core synced loop into a reusable function:

```python
async def run_repl_client_core(
    *,
    client: NexusClient,           # Agent-scoped client
    root_client: NexusClient | None,  # Root-scoped for global ops
    agent_id: str,
    console: Console,
    sync_mode: bool,
) -> bool:
    """Core REPL loop used by both host and connect modes."""
```

This function should:
- Create `EventRouter`
- Start pump task `router.pump(client.iter_events())`
- Set up `StreamingDisplay`, `SyncFeed`, key monitor, Live contexts
- Read prompt input, run slash commands, call RPC send/cancel/confirm
- Render own events and foreign events

**Intermediate state:** Synced mode calls the new core function; unified mode unchanged.

---

## Phase 1: Make Unified Mode Use the Same Core Loop (M)

### 1.1 Replace in-process dispatcher with NexusClient

Currently unified mode sends via:
```python
agent_dispatcher.dispatch(Request(...))
```

And subscribes to:
```python
shared.event_hub.subscribe(agent_id)
```

Replace with:
```python
client = NexusClient.with_auto_auth(
    f"http://127.0.0.1:{port}/agent/{current_agent_id}",
    api_key=api_key
)
await run_repl_client_core(client=client, root_client=..., agent_id=current_agent_id, console=...)
```

### 1.2 Add root-scoped client alongside agent-scoped client

For `/create`, `/destroy`, `/list_agents`, session ops:

```python
root_client = NexusClient(f"http://127.0.0.1:{port}/", api_key=api_key)
```

**Intermediate state:** Unified mode loses some pool-local slash commands temporarily unless root_client methods are provided.

---

## Phase 2: Unify Slash Command Routing (M)

### 2.1 Extract command parsing into shared helper

Create `nexus3/cli/command_router.py`:

```python
class CommandRouter:
    def __init__(
        self,
        agent_client: NexusClient,
        root_client: NexusClient | None,
        console: Console,
        state: ReplState,  # Holds current agent_id, whisper target, etc.
    ):
        ...

    async def route(self, cmd_str: str) -> CommandResult:
        """Parse and execute a slash command."""
        ...
```

Inputs:
- `cmd_str: str`
- `agent_client` (agent-scoped)
- `root_client` (root-scoped)
- Local UI helpers (print, confirm, etc.)
- Current `agent_id` state mutator (for `/agent` and `/whisper` modes)

### 2.2 Make both host and connect modes use this router

- Remove duplicated hardcoded command blocks in synced mode
- Replace unified mode's `CommandContext(pool=...)` commands with RPC-backed equivalents

**Intermediate state:** All terminals have the same commands, implemented over RPC.

---

## Phase 3: Session Persistence Parity (L)

### 3.1 Implement server-side global RPC methods

Add to GlobalDispatcher:
- `list_sessions`
- `save_session`
- `load_session`
- `clone_session`
- `rename_session`
- `delete_session`

### 3.2 Update command router

Implement via RPC:
- `/save`
- `/clone`
- `/rename`
- `/delete`
- `/session`
- Lobby operations

**Intermediate state:** Any terminal can manage sessions identically.

---

## Phase 4: Agent Configuration Parity (L-XL)

### 4.1 Implement agent-scoped RPC methods

Add to Dispatcher:
- `set_cwd`
- `get_permissions`
- `set_permissions`
- `get_system_prompt`
- `set_system_prompt`
- `get_model` / `set_model` (optional)

### 4.2 Update command router

Implement via RPC:
- `/cwd`
- `/permissions`
- `/prompt`
- `/model`

---

## Phase 5: Remove Leftover "In-Process Special" Code (S)

Once unified host uses RPC for everything, delete:
- Direct EventHub subscriptions in REPL
- Direct dispatcher dispatch calls in REPL
- Direct pool usage for commands (except server startup itself)

---

## Minimum Viable "Identical Terminals" Milestone

**After Phase 1:**
- All terminals (including host) use the same send/cancel/confirm/event rendering pipeline
- The core interactive agent experience is identical

Even if some global management commands aren't yet implemented in connect mode, the day-to-day "talk to agent + tools + confirmations + sync" feels identical - this is the big UX win.

---

## State Variables to Extract from repl.py

These variables need to be shared between modes or passed to `run_repl_client_core()`:

```python
@dataclass
class ReplState:
    """Shared state for REPL client loop."""
    current_agent_id: str
    whisper_target: str | None = None
    is_whisper_mode: bool = False
    last_request_id: str | None = None
    sync_verbosity: SyncVerbosity = "full"

# UI components (passed in)
console: Console
prompt_session: PromptSession
streaming_display: StreamingDisplay
sync_feed: SyncFeed
key_monitor: KeyMonitor

# Clients (passed in)
agent_client: NexusClient
root_client: NexusClient | None

# Event routing (created by core loop)
event_router: EventRouter
```

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `repl.py` | Extract `run_repl_client_core()`, unified mode uses client |
| `command_router.py` | New file - shared command routing |
| `client.py` | Add wrappers for new RPC methods |
| `global_dispatcher.py` | Add session RPC handlers |
| `dispatcher.py` | Add agent config RPC handlers |
| `session_manager.py` | Expose ops for RPC layer |

---

## Parallelization

These can proceed in parallel:
- Server RPC additions (new methods)
- Client command routing refactor

UI unification can proceed while server methods are being added by stubbing commands to "not yet supported".
