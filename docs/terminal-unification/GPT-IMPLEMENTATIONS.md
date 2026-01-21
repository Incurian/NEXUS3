# GPT Implementation Details

Detailed implementation guidance from GPT reviewer for terminal unification.

---

## SOP: Working with GPT Reviewer

### Avoiding Timeouts
- **Request details in small chunks** - ask for one implementation at a time rather than all at once
- GPT with extended thinking takes 3-15 minutes for thorough responses
- If a request times out, ping for partial results

### Codebase Context (Future Optimization)
- Use `concat_files.sh py` to concatenate all Python files into one file
- Have GPT read the concatenated file in a few passes at session start
- This preserves more context for reasoning vs many small tool calls
- **Important:** Re-run the script between sessions to avoid stale info

### Session Management
- GPT context fills up over time (check with `rpc status`)
- At ~75% capacity, request a handover document for the next instance
- Store handover in `docs/terminal-unification/GPT-HANDOVER.md`

---

## 1. Confirmation Event Handling (Critical)

### A) Prompt Helper (REPL-side, client code)

```python
from __future__ import annotations

import asyncio
from typing import Any, Literal

Decision = Literal["allow_once", "allow_file", "allow_dir", "deny"]

async def prompt_confirmation_from_event(
    *,
    ev: dict[str, Any],
    console,  # rich Console
    key_monitor_pause: asyncio.Event,
    key_monitor_pause_ack: asyncio.Event,
) -> Decision:
    """
    Prompt user for a confirmation_requested SSE event.

    Safe with:
      - Rich Live (stops Live temporarily)
      - KeyMonitor (pauses to release stdin)
    """
    from nexus3.cli.live_state import _current_live

    live = _current_live.get()
    if live is not None:
        live.stop()

    # Pause KeyMonitor so it stops consuming stdin
    key_monitor_pause.clear()
    try:
        await asyncio.wait_for(key_monitor_pause_ack.wait(), timeout=0.5)
    except TimeoutError:
        pass

    try:
        tool = ev.get("tool") if isinstance(ev.get("tool"), dict) else {}
        tool_name = str(tool.get("name") or "unknown")
        params_preview = str(tool.get("params") or "")
        target = ev.get("target")
        cwd = ev.get("cwd")
        timeout_s = ev.get("timeout_s")

        console.print("\n[yellow]Confirmation required[/]")
        console.print(f"  [dim]Tool:[/] {tool_name}")
        if params_preview:
            console.print(f"  [dim]Params:[/] {params_preview}")
        if target:
            console.print(f"  [dim]Target:[/] {target}")
        if cwd:
            console.print(f"  [dim]CWD:[/] {cwd}")
        if timeout_s:
            console.print(f"  [dim]Timeout:[/] {timeout_s}s")

        # Server-side multi-client confirmation currently only supports:
        # allow_once / allow_file / allow_dir / deny
        # (No exec "allow always in cwd" mapping today.)
        is_write_like = tool_name.lower() in {
            "write_file", "edit_file", "append_file", "regex_replace",
            "copy_file", "rename", "mkdir",
        }

        console.print()
        if is_write_like:
            console.print("  [cyan][1][/] Allow once")
            console.print("  [cyan][2][/] Allow always for this file")
            console.print("  [cyan][3][/] Allow always in this directory")
            console.print("  [cyan][4][/] Deny")

            def _get() -> str:
                try:
                    return console.input("\n[dim]Choice [1-4]:[/] ").strip()
                except (EOFError, KeyboardInterrupt):
                    return "4"

            choice = await asyncio.to_thread(_get)
            if choice == "1":
                return "allow_once"
            if choice == "2":
                return "allow_file"
            if choice == "3":
                return "allow_dir"
            return "deny"

        # Exec tools and others: restrict to allow_once/deny to match server mapping.
        console.print("  [cyan][1][/] Allow once")
        console.print("  [cyan][2][/] Deny")

        def _get2() -> str:
            try:
                return console.input("\n[dim]Choice [1-2]:[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                return "2"

        choice = await asyncio.to_thread(_get2)
        return "allow_once" if choice == "1" else "deny"

    finally:
        key_monitor_pause.set()
        if live is not None:
            live.start()
```

### B) Handle confirmation_requested in SSE event loop

```python
# inside: while True: event = await ...
event_type = event.get("type", "")

if event_type == "confirmation_requested":
    confirm_id = str(event.get("confirm_id") or "")
    if not confirm_id:
        # malformed event; ignore
        continue

    decision = await prompt_confirmation_from_event(
        ev=event,
        console=rich_console,
        key_monitor_pause=key_monitor_pause,
        key_monitor_pause_ack=key_monitor_pause_ack,
    )

    try:
        resp = await client.confirm(confirm_id, decision)
        if not resp.get("accepted", True):
            # First response wins; someone else may have responded
            await _safe_print_synced("[dim]Note: confirmation already answered by another terminal.[/]")
    except Exception as e:
        await _safe_print_synced(f"[red]Failed to submit confirmation: {e}[/]")

    # continue consuming turn events
    continue
```

### C) Optional: confirmation_resolved (informational)

```python
if event_type == "confirmation_resolved":
    # Optional: show who/what was decided (event has decision + resolved_at)
    # Usually you will see this for foreign confirmations too.
    continue
```

### Notes/Gotchas

1. **Don't restrict confirmations to "idle only" for the active turn.**
   - If the active turn is waiting on confirmation, prompt immediately (even if Live is active)
   - The helper above pauses Live and KeyMonitor safely

2. **Server multi-client decision mapping doesn't support exec "allow always" options.**
   - Only allow_once/allow_file/allow_dir/deny are mapped meaningfully
   - That's why prompt helper offers only allow_once/deny for exec tools

3. **Foreign confirmations** (for turns you didn't initiate) are best handled via SyncFeed's "prompt when idle" worker

---

## 2. SyncFeed Integration

**Goal:** SyncFeed consumes all "foreign" SSE events (events for turns not initiated by this terminal), renders them safely, and handles foreign confirmations using Option B ("prompt only when idle").

### 2.1 Safe Print Plumbing (buffer during Live)

```python
import asyncio
from nexus3.cli.live_state import _current_live

foreign_print_q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)

async def _direct_print(text: str) -> None:
    # Safe with prompt_toolkit: print via run_in_terminal if app is running
    if prompt_session.app and prompt_session.app.is_running:
        await prompt_session.app.run_in_terminal(lambda: rich_console.print(text, soft_wrap=True))
    else:
        rich_console.print(text, soft_wrap=True)

async def _safe_print(text: str) -> None:
    # If Live is active, buffer output to flush later
    if _current_live.get() is not None:
        try:
            foreign_print_q.put_nowait(text)
        except asyncio.QueueFull:
            pass
        return
    await _direct_print(text)

async def _foreign_flush_worker() -> None:
    try:
        while True:
            first = await foreign_print_q.get()
            batch = [first]
            for _ in range(49):
                try:
                    batch.append(foreign_print_q.get_nowait())
                except asyncio.QueueEmpty:
                    break

            payload = "\n".join(batch)
            live = _current_live.get()
            if live is not None:
                # If Live exists, print to its console (avoids prompt tearing)
                live.console.print(payload, soft_wrap=True)
            else:
                await _direct_print(payload)

            await asyncio.sleep(0)
    except asyncio.CancelledError:
        return

foreign_flush_task = asyncio.create_task(_foreign_flush_worker(), name="foreign_flush")
```

**Integration point:** Create these right after constructing `PromptSession` and before starting the event pump.

### 2.2 Track Local Active Request

```python
active_request_id: str | None = None
```

### 2.3 Define is_idle()

```python
def is_idle() -> bool:
    return active_request_id is None and _current_live.get() is None
```

### 2.4 Idle-only Confirmation Prompt (for foreign confirmations)

```python
from typing import Any, Literal
Decision = Literal["allow_once", "allow_file", "allow_dir", "deny"]

async def prompt_confirmation_when_idle(ev: dict[str, Any]) -> Decision:
    def _blocking_prompt() -> Decision:
        tool = ev.get("tool") if isinstance(ev.get("tool"), dict) else {}
        tool_name = str(tool.get("name") or "unknown")
        params_preview = str(tool.get("params") or "")

        rich_console.print("\n[yellow]Foreign confirmation pending[/]")
        rich_console.print(f"  [dim]Tool:[/] {tool_name}")
        if params_preview:
            rich_console.print(f"  [dim]Params:[/] {params_preview}")

        # Conservative choices (works for all tool types)
        rich_console.print("  [cyan][1][/] Allow once")
        rich_console.print("  [cyan][2][/] Deny")
        try:
            choice = rich_console.input("\n[dim]Choice [1-2]:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "2"
        return "allow_once" if choice == "1" else "deny"

    if prompt_session.app and prompt_session.app.is_running:
        return await prompt_session.app.run_in_terminal(_blocking_prompt)

    return await asyncio.to_thread(_blocking_prompt)
```

### 2.5 Sender Callback

```python
async def send_confirmation(confirm_id: str, decision: Decision) -> None:
    try:
        resp = await agent_client.confirm(confirm_id, decision)
        if not resp.get("accepted", True):
            await _safe_print("[dim]Note: confirmation already answered by another terminal.[/]")
    except Exception as e:
        await _safe_print(f"[red]Failed to submit confirmation: {e}[/]")
```

### 2.6 Create and Start SyncFeed

```python
from nexus3.cli.sync_feed import SyncFeed

sync_feed = SyncFeed(
    agent_id=agent_id,
    verbosity="full",          # or "terminal" / "off"
    print_line=_safe_print,
    is_idle=is_idle,
    prompt_confirmation=prompt_confirmation_when_idle,
    send_confirmation=send_confirmation,
)

await sync_feed.start()
```

### 2.7 Route Foreign Events into SyncFeed

```python
async def foreign_event_worker() -> None:
    try:
        while True:
            ev = await router.global_queue.get()

            # Skip events for our active local turn
            if active_request_id is not None and ev.get("request_id") == active_request_id:
                continue

            await sync_feed.handle_event(ev)
    except asyncio.CancelledError:
        return

foreign_task = asyncio.create_task(foreign_event_worker(), name="sync_feed_foreign_worker")
```

**Integration point:** Start this background task right after `router.pump(...)` is launched.

### 2.8 Local Turn: Set/Clear active_request_id

When beginning a local turn:
```python
request_id = secrets.token_hex(8)
active_request_id = request_id

q = await router.subscribe(request_id)
send_task = asyncio.create_task(agent_client.send(user_input, request_id=request_id))
```

When turn ends (in finally):
```python
active_request_id = None
await router.unsubscribe(request_id, q)
```

### 2.9 Cleanup on Exit

```python
foreign_task.cancel()
foreign_flush_task.cancel()
try:
    await foreign_task
except asyncio.CancelledError:
    pass
try:
    await foreign_flush_task
except asyncio.CancelledError:
    pass

await sync_feed.stop()
```

### Interaction Notes

- **Local turn confirmations:** Handle `confirmation_requested` inside per-request loop (prompt immediately)
- **Foreign turn confirmations:** SyncFeed prints alert, queues event, prompts when `is_idle()` becomes True
- This prevents "deadlock until timeout" while preserving Option B

---

## 3. RPC Handler Implementations

### 3.1 set_cwd

**Imports (add near top of dispatcher.py):**
```python
from pathlib import Path

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path
from nexus3.core.permissions import AgentPermissions
```

**Register in Dispatcher.__init__:**
```python
self._handlers["set_cwd"] = self._handle_set_cwd
```

**Handler implementation:**
```python
async def _handle_set_cwd(self, params: dict[str, Any]) -> dict[str, Any]:
    """
    RPC: set_cwd

    Params:
      - cwd: str (required). May be absolute or relative.
             Relative paths are resolved against the agent's current cwd
             (NOT the server process cwd).

    Returns:
      - {"cwd": "<resolved absolute path>"}

    Invariants preserved:
      - services["cwd"] is updated (tool relative path resolution)
      - permissions.effective_policy.cwd is updated (TRUSTED within-CWD semantics)
      - path is validated against:
          - permissions.effective_policy.allowed_paths (sandbox boundary, if set)
          - permissions.effective_policy.blocked_paths (denylist, always enforced)
    """
    cwd_param = params.get("cwd")
    if not isinstance(cwd_param, str) or not cwd_param.strip():
        raise InvalidParamsError("cwd must be a non-empty string")

    # Session must have services + permissions (fail closed)
    services = getattr(self._session, "_services", None)
    if services is None:
        raise MethodNotFoundError("set_cwd not available (services not configured)")

    perms = services.get("permissions")
    if perms is None or not isinstance(perms, AgentPermissions):
        raise MethodNotFoundError("set_cwd not available (permissions not configured)")

    # Resolve relative paths against agent cwd (not process cwd)
    base_cwd: Path = services.get_cwd()

    # Canonical security validation (resolves symlinks, enforces allowed/blocked)
    try:
        resolved: Path = validate_path(
            cwd_param,
            allowed_paths=perms.effective_policy.allowed_paths,
            blocked_paths=perms.effective_policy.blocked_paths,
            cwd=base_cwd,
        )
    except PathSecurityError as e:
        raise InvalidParamsError(f"cwd invalid: {e.message}") from e

    # Existence constraints
    if not resolved.exists():
        raise InvalidParamsError(f"cwd does not exist: {resolved}")
    if not resolved.is_dir():
        raise InvalidParamsError(f"cwd is not a directory: {resolved}")

    # Update agent-local cwd (used by tools + PathDecisionEngine.from_services)
    services.register("cwd", resolved)

    # Critical: update permission-policy cwd so TRUSTED "within cwd" checks match.
    # (PermissionPolicy.cwd drives requires_confirmation() logic.)
    perms.effective_policy.cwd = resolved

    return {"cwd": str(resolved)}
```

**Why these invariants:**
- `services["cwd"]` is what `ServiceContainer.get_cwd()` returns, used by tools
- `permissions.effective_policy.cwd` is what `PermissionPolicy.is_within_cwd()` uses for TRUSTED confirmation behavior
- `validate_path()` ensures sandboxed agents can only set cwd within sandbox root

### 3.2 get_permissions / set_permissions

**Additional imports:**
```python
import copy
from typing import Any

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    PermissionLevel,
    resolve_preset,
    load_custom_presets_from_config,
)
from nexus3.rpc.dispatch_core import InvalidParamsError, MethodNotFoundError
```

**Register in Dispatcher.__init__:**
```python
self._handlers["get_permissions"] = self._handle_get_permissions
self._handlers["set_permissions"] = self._handle_set_permissions
```

**Helper: serialize permissions:**
```python
def _serialize_permissions(self, perms: AgentPermissions) -> dict[str, Any]:
    disabled_tools = [name for name, tp in perms.tool_permissions.items() if not tp.enabled]
    policy = perms.effective_policy

    return {
        "permission_level": policy.level.value,   # "trusted" | "sandboxed" | "yolo"
        "preset": perms.base_preset,              # preset name
        "disabled_tools": disabled_tools,
        "policy": {
            "cwd": str(policy.cwd),
            "allowed_paths": [str(p) for p in policy.allowed_paths] if policy.allowed_paths is not None else None,
            "blocked_paths": [str(p) for p in policy.blocked_paths] if policy.blocked_paths else [],
            "frozen": bool(policy.frozen),
        },
        "session_allowances": perms.session_allowances.to_dict(),
        "depth": perms.depth,
        "parent_agent_id": perms.parent_agent_id,
    }
```

**Helper: resync tool definitions (CRITICAL):**
```python
def _resync_tool_definitions(self, services: Any, perms: AgentPermissions) -> None:
    """
    Rebuild tool definitions from scratch based on perms, and write them into the ContextManager.

    Invariant preserved:
      - If a tool is disabled in perms.tool_permissions, it is not present in context tool defs.
      - MCP tools are included only when MCP is allowed and tool is enabled.
    """
    if self._context is None:
        raise MethodNotFoundError("context not configured")
    if self._session.registry is None:
        raise MethodNotFoundError("skill registry not configured")

    # Built-in tools filtered by permissions
    tool_defs = self._session.registry.get_definitions_for_permissions(perms)

    # Optionally add MCP tools if permitted (mirrors AgentPool creation logic)
    mcp_registry = services.get("mcp_registry")
    if mcp_registry is not None:
        try:
            from nexus3.mcp.permissions import can_use_mcp
        except Exception:
            can_use_mcp = None

        if can_use_mcp is not None and can_use_mcp(perms):
            agent_id = services.get("agent_id") or self._agent_id or "unknown"
            for mcp_skill in mcp_registry.get_all_skills(agent_id=agent_id):
                tool_perm = perms.tool_permissions.get(mcp_skill.name)
                if tool_perm is not None and not tool_perm.enabled:
                    continue
                tool_defs.append({
                    "type": "function",
                    "function": {
                        "name": mcp_skill.name,
                        "description": mcp_skill.description,
                        "parameters": mcp_skill.parameters,
                    },
                })

    self._context.set_tool_definitions(tool_defs)
```

**get_permissions handler:**
```python
async def _handle_get_permissions(self, params: dict[str, Any]) -> dict[str, Any]:
    services = getattr(self._session, "_services", None)
    if services is None:
        raise MethodNotFoundError("services not configured")

    perms = services.get("permissions")
    if perms is None or not isinstance(perms, AgentPermissions):
        raise MethodNotFoundError("permissions not configured")

    return self._serialize_permissions(perms)
```

**set_permissions handler:**
```python
async def _handle_set_permissions(self, params: dict[str, Any]) -> dict[str, Any]:
    services = getattr(self._session, "_services", None)
    if services is None:
        raise MethodNotFoundError("services not configured")

    old_perms = services.get("permissions")
    if old_perms is None or not isinstance(old_perms, AgentPermissions):
        raise MethodNotFoundError("permissions not configured")

    preset = params.get("preset")
    if not isinstance(preset, str) or not preset.strip():
        raise InvalidParamsError("preset must be a non-empty string")

    disable_tools = params.get("disable_tools", [])
    enable_tools = params.get("enable_tools", [])
    if disable_tools is None:
        disable_tools = []
    if enable_tools is None:
        enable_tools = []

    if not isinstance(disable_tools, list) or not all(isinstance(x, str) for x in disable_tools):
        raise InvalidParamsError("disable_tools must be a list[str]")
    if not isinstance(enable_tools, list) or not all(isinstance(x, str) for x in enable_tools):
        raise InvalidParamsError("enable_tools must be a list[str]")

    # Resolve custom presets from Session config if present
    custom_presets = None
    cfg = getattr(self._session, "_config", None)
    if cfg is not None:
        try:
            custom_presets = load_custom_presets_from_config(cfg.permissions.presets)
        except Exception:
            custom_presets = None

    # Use agent's current cwd for permission-policy cwd and (if sandboxed) sandbox root
    agent_cwd = services.get_cwd()

    # Resolve base preset
    try:
        new_perms = resolve_preset(
            preset,
            custom_presets=custom_presets,
            cwd=agent_cwd,
        )
    except ValueError as e:
        raise InvalidParamsError(str(e)) from e

    # Apply tool enable/disable deltas (optional)
    if disable_tools or enable_tools:
        delta = PermissionDelta(disable_tools=disable_tools, enable_tools=enable_tools)
        try:
            new_perms = new_perms.apply_delta(delta)
        except PermissionError as e:
            raise InvalidParamsError(str(e)) from e

    # Enforce ceiling if present (subagents)
    if old_perms.ceiling is not None:
        if not old_perms.ceiling.can_grant(new_perms):
            raise InvalidParamsError(
                f"Requested permissions exceed ceiling (parent={old_perms.ceiling.base_preset})"
            )
        # Preserve lineage metadata
        new_perms.ceiling = old_perms.ceiling
        new_perms.parent_agent_id = old_perms.parent_agent_id
        new_perms.depth = old_perms.depth

    # Preserve dynamic session allowances when staying non-sandboxed.
    # If switching to sandboxed, dropping allowances is safer/simpler.
    if new_perms.effective_policy.level != PermissionLevel.SANDBOXED:
        new_perms.session_allowances = copy.deepcopy(old_perms.session_allowances)

    # Critical invariant: policy cwd must match agent cwd for TRUSTED semantics
    new_perms.effective_policy.cwd = agent_cwd

    # Commit into services
    services.register("permissions", new_perms)
    services.register("allowed_paths", new_perms.effective_policy.allowed_paths)

    # Critical invariant: tool defs must be rebuilt so disabled tools vanish from LLM
    self._resync_tool_definitions(services, new_perms)

    return {"updated": True, **self._serialize_permissions(new_perms)}
```

**Notes:**
- This does NOT block switching to "yolo" via RPC. Add check if you want to maintain that restriction.
- Under Phase 8's "all terminals equal" decision, you'll likely remove that restriction.

### 3.3 get_system_prompt / set_system_prompt

**Pre-requisite: Register system_prompt_path in pool.py**

In `_create_unlocked` and `_restore_unlocked`:
```python
# After services.register("agent_id", ...)
services.register("system_prompt_path", self.system_prompt_path)
```

**Register in Dispatcher.__init__:**
```python
self._handlers["get_system_prompt"] = self._handle_get_system_prompt
self._handlers["set_system_prompt"] = self._handle_set_system_prompt
```

**get_system_prompt handler:**
```python
async def _handle_get_system_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
    """
    RPC: get_system_prompt

    Returns:
      - system_prompt: full current prompt text
      - system_prompt_path: the server-discovered prompt source path (or None)

    Notes:
      - Dispatcher does not know AgentPool, so system_prompt_path is read from services.
      - If services didn't register it, we return None.
    """
    if self._context is None:
        raise MethodNotFoundError("get_system_prompt not available (no context)")

    services = getattr(self._session, "_services", None)
    if services is None:
        raise MethodNotFoundError("get_system_prompt not available (services not configured)")

    spp = services.get("system_prompt_path")
    if spp is not None and not isinstance(spp, str):
        # If somebody stored a non-string, fail closed and return None
        spp = None

    return {
        "system_prompt": self._context.system_prompt or "",
        "system_prompt_path": spp,
    }
```

**set_system_prompt handler:**
```python
async def _handle_set_system_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
    """
    RPC: set_system_prompt

    Params:
      - system_prompt: str (required)

    Invariants:
      - ContextManager.system_prompt updated
      - If system_prompt_path is tracked in services, clear it (prompt no longer file-based)
    """
    if self._context is None:
        raise MethodNotFoundError("set_system_prompt not available (no context)")

    system_prompt = params.get("system_prompt")
    if not isinstance(system_prompt, str):
        raise InvalidParamsError("system_prompt must be a string")

    # Update prompt in context (this is what the model actually uses)
    self._context.set_system_prompt(system_prompt)

    # Update services metadata (optional but recommended)
    services = getattr(self._session, "_services", None)
    if services is not None:
        # Clear path because prompt is now ad-hoc text (not loaded from file)
        if services.get("system_prompt_path") is not None:
            services.register("system_prompt_path", None)

    return {"updated": True}
```

**Why this is clean:**
- Authoritative prompt is `ContextManager.system_prompt` - handlers update/read that directly
- `system_prompt_path` is metadata (where prompt originally came from), not correctness-critical
- No REPL-only imports; no dispatcher → pool references

---

## 4. run_repl_client_core() Skeleton

See full skeleton in GPT response. Key integration points:

```python
@dataclass
class CoreExit:
    kind: Literal["quit", "switch_agent"]
    new_agent_id: str | None = None

async def run_repl_client_core(
    *,
    agent_client: NexusClient,          # points to /agent/{agent_id}
    root_client: NexusClient | None,    # points to /
    agent_id: str,
    console: Console,
) -> CoreExit:
    # 1. Create prompt_toolkit session, KeyMonitor pause events
    # 2. Create EventRouter, start SSE pump task
    # 3. Create safe_print + foreign_flush_worker
    # 4. Track active_request_id for local vs foreign routing
    # 5. Create SyncFeed with is_idle(), prompt callbacks
    # 6. Start foreign_event_worker (feeds SyncFeed)

    # Main loop:
    while True:
        user_input = await prompt_session.prompt_async(...)

        # Handle slash commands via CommandRouter
        # Handle /agent X -> return CoreExit(kind="switch_agent", new_agent_id=X)
        # Handle /quit -> return CoreExit(kind="quit")

        # Local turn:
        request_id = secrets.token_hex(8)
        active_request_id = request_id
        q = await router.subscribe(request_id)

        async with KeyMonitor(...):
            with Live(...) as live:
                _current_live.set(live)
                # Consume events from q
                # Handle confirmation_requested immediately (local turn)
                # Update StreamingDisplay
                # Break on turn_completed/turn_cancelled

        active_request_id = None
        await router.unsubscribe(request_id, q)
```

**Key design points:**
- One long-lived SSE stream pumped into EventRouter
- Local turn consumes per-request queue (`router.subscribe(request_id)`)
- SyncFeed consumes foreign events from `router.global_queue`
- Local confirmations: prompt immediately
- Foreign confirmations: SyncFeed queues, prompts when idle

---

## 5. Session RPC Methods (GlobalDispatcher)

### Wiring Change

Add to GlobalDispatcher:
```python
# in GlobalDispatcher.__init__
self._session_manager: SessionManager | None = None

def set_session_manager(self, sm: SessionManager) -> None:
    self._session_manager = sm
```

Call from `run_repl` and `run_serve` after instantiating SessionManager.

### Handler Semantics

- `list_sessions`: use `SessionManager.list_sessions()`, return name + modified + message_count
- `save_session`: snapshot active agent from pool into SavedSession, write to disk
  - Use `serialize_session(...)` directly
  - Include `session_allowances` so TRUSTED allowances persist
- `load_session`: load file, restore into pool (error if agent id exists unless `overwrite` flag)
- `clone_session`, `rename_session`, `delete_session`: direct wrappers around SessionManager

### Note on Model Override

Current `AgentPool.restore_from_saved()` does NOT restore model choice (TODO exists).
For Phase 8, ship `load_session` without model override - treat as later enhancement.

---

## 6. Critical Phase 8 Items (GPT's Summary)

1. **Confirmations are Milestone 1 requirement** - Without client-side handling of `confirmation_requested`, tools hang until timeout

2. **`/cwd` must update BOTH services cwd AND permission policy cwd** - Otherwise TRUSTED "within cwd" semantics drift

3. **Tool definition resync after permission changes is NOT optional** - Only robust LLM control is rebuilding context tool definitions

4. **Agent switching requires rebuilding SSE stream + SyncFeed state** - On `/agent X`: close old pump, create new client, start new SSE, call `sync_feed.set_agent(X)`

5. **Decide YOLO via RPC** - Current global RPC blocks yolo. Under Option A, host becomes client too. Either allow yolo via RPC or remove concept - otherwise reintroduce "host-only behavior"

---

## 7. Security Considerations

### What Changes Under Phase 8

| Security Boundary | Before | After |
|------------------|--------|-------|
| REPL vs RPC | Host has in-process access, clients limited | All terminals are clients |
| yolo preset | REPL-only | Decision needed: allow via RPC or remove |
| Agent capabilities | Same regardless of terminal | Same regardless of terminal |

### What Does NOT Change

- **Agent permission ceilings** - Subagents still can't exceed parent permissions
- **Sandbox boundaries** - Sandboxed agents still restricted to cwd
- **Tool filtering** - Disabled tools still don't appear in LLM context
- **Confirmation requirements** - TRUSTED still prompts for destructive actions
- **Token auth** - Must have token to connect

### Hard Blocks for Agents (Still Enforced)

Things agents can NEVER do regardless of terminal type:
- Exceed their permission ceiling
- Access blocked paths
- Use disabled tools
- Bypass confirmation requirements in TRUSTED mode
- Create agents with higher permissions than themselves

### User-Only Capabilities (After Phase 8)

Things only the user (any authenticated terminal) can do:
- Start/stop the server
- Change agent permissions (via RPC - subject to ceiling)
- Create/destroy agents
- Access yolo preset (if allowed via RPC)

The key insight: **the security boundary is the permission system, not the transport**.
RPC vs in-process doesn't matter if both are authenticated local users.

---

## 8. Final Warnings / Sharp Edges (GPT's Final Guidance)

1. **Multi-client confirmations: exec "allow always" mismatch**
   - Decision set (`allow_once/allow_file/allow_dir/deny`) maps well for write tools
   - Does NOT represent exec allowances (e.g., "allow bash_safe always in cwd")
   - Client UX should be conservative for exec tools (allow_once/deny only)

2. **`/cwd` consistency everywhere**
   - `set_cwd` RPC updates both services and permission policy
   - Any OTHER path that changes cwd (session load/restore, agent creation) must also keep both in sync

3. **Model switching is incomplete**
   - `/model` today updates metadata but does NOT swap provider/model used by Session
   - Don't expose `set_model` RPC until real swap mechanism exists (or declare metadata-only)

4. **Session persistence should include dynamic allowances**
   - `SavedSession` supports `session_allowances`
   - Ensure `/save` RPC includes `permissions.session_allowances.to_dict()`
   - Restore must apply via `SessionAllowances.from_dict(...)`

5. **Agent switching: strict cleanup**
   - On `/agent` switch, cancel/await:
     - SSE pump task
     - foreign flush task
     - SyncFeed worker task
   - Then recreate router + SyncFeed for new agent
   - Otherwise: ghost events, leaks, cross-agent confirmation prompts

6. **SSE reconnect limitation**
   - Server supports `Last-Event-ID` replay via EventHub ring buffer
   - `NexusClient.iter_events()` does not currently send it
   - Reconnect will miss events (acceptable for Phase 8, but known limitation)

7. **Define what remains host-only**
   - Under Option A: only "start server" and `/init` (filesystem bootstrapping)
   - Anything else still depending on in-process pool/session_manager = "unification not done yet"

---

## 9. Fixes for Sharp Edges (Detailed)

### Fix 1: Exec "allow always" - Extend Confirmation Schema

**Add new decision value `allow_exec_cwd`:**

`nexus3/rpc/confirmations.py`:
```python
Decision = Literal[
    "allow_once",
    "allow_file",
    "allow_dir",
    "allow_exec_cwd",   # NEW
    "deny",
    "timeout_deny",
]
```

**Include options in SSE event** (so clients don't guess):

`nexus3/rpc/confirmations.py` - add `options` param to `request()`:
```python
async def request(..., options: list[str] | None = None, ...) -> ConfirmationRequest:
    ...
    await self._publish_event(agent_id, {
        ...
        "options": options or ["allow_once", "deny"],
    })
```

**Session determines options by tool type:**

`nexus3/session/session.py` in `_request_multi_client_confirmation()`:
```python
tool_lower = tool_call.name.lower()
is_exec = tool_lower in ("bash_safe", "run_python", "shell_unsafe")

if is_exec and tool_lower != "shell_unsafe":
    options = ["allow_once", "allow_exec_cwd", "deny"]
elif is_exec:
    options = ["allow_once", "deny"]  # shell_unsafe always per-use
else:
    options = ["allow_once", "allow_file", "allow_dir", "deny"]
```

**Extend decision mapping:**
```python
decision_map = {
    "allow_once": ConfirmationResult.ALLOW_ONCE,
    "allow_file": ConfirmationResult.ALLOW_FILE,
    "allow_dir": ConfirmationResult.ALLOW_WRITE_DIRECTORY,
    "allow_exec_cwd": ConfirmationResult.ALLOW_EXEC_CWD,   # NEW
    "deny": ConfirmationResult.DENY,
    "timeout_deny": ConfirmationResult.DENY,
}
```

**Update dispatcher valid decisions:**
`nexus3/rpc/dispatcher.py` in `_handle_confirm`:
```python
valid_decisions = ("allow_once", "allow_file", "allow_dir", "allow_exec_cwd", "deny")
```

---

### Fix 2: /cwd Consistency - Code Paths to Update

**Invariant:** When agent cwd changes, update BOTH:
- `services["cwd"]`
- `permissions.effective_policy.cwd`

**Path 1: Restore-from-saved session**
`nexus3/rpc/pool.py` in `_restore_unlocked()`:
```python
agent_cwd = Path(saved.working_directory) if saved.working_directory else Path.cwd()

permissions = resolve_preset(preset_name, self._shared.custom_presets, cwd=agent_cwd)
# ...apply deltas...
services.register("cwd", agent_cwd)
permissions.effective_policy.cwd = agent_cwd
```

**Path 2: Host REPL /cwd command**
`nexus3/cli/repl_commands.py` in `cmd_cwd()`:
```python
agent.services.register("cwd", new_path)
perms = agent.services.get("permissions")
if perms is not None:
    perms.effective_policy.cwd = new_path
```

**Path 3: Host REPL /permissions preset change**
`nexus3/cli/repl_commands.py` in `_change_preset()`:
```python
new_perms = resolve_preset(preset_name, custom_presets, cwd=agent.services.get_cwd())
new_perms.effective_policy.cwd = agent.services.get_cwd()
```

---

### Fix 3: Model Switching - Minimal Working Implementation

**Register provider_registry in services:**
`nexus3/rpc/pool.py` in `_create_unlocked()` and `_restore_unlocked()`:
```python
services.register("provider_registry", self._shared.provider_registry)
```

**Add set_model handler:**
`nexus3/rpc/dispatcher.py`:
```python
async def _handle_set_model(self, params: dict[str, Any]) -> dict[str, Any]:
    model_name = params.get("model")
    if not isinstance(model_name, str) or not model_name.strip():
        raise InvalidParamsError("model must be a non-empty string")

    cfg = getattr(self._session, "_config", None)
    if cfg is None:
        raise MethodNotFoundError("config not available")

    services = getattr(self._session, "_services", None)
    if services is None:
        raise MethodNotFoundError("services not configured")

    provider_registry = services.get("provider_registry")
    if provider_registry is None:
        raise MethodNotFoundError("provider_registry not available")

    resolved = cfg.resolve_model(model_name)

    # Ensure context fits
    if self._context is not None:
        usage = self._context.get_token_usage()
        if usage.get("total", 0) > resolved.context_window:
            raise InvalidParamsError(
                f"context too large for {model_name}; compact first"
            )
        self._context.config.max_tokens = resolved.context_window

    # Swap provider used for completions
    new_provider = provider_registry.get(resolved.provider_name, resolved.model_id, resolved.reasoning)
    self._session.provider = new_provider

    services.register("model", resolved)

    return {"updated": True, "model": resolved.model_id, "provider": resolved.provider_name}
```

---

### Fix 4: Session Persistence + Allowances

**Save allowances when serializing:**
Any place calling `serialize_session(...)`:
```python
saved = serialize_session(
    ...,
    session_allowances=perms.session_allowances.to_dict() if perms else {},
)
```

Locations:
- `nexus3/commands/core.py` in `cmd_save()`
- `nexus3/cli/repl.py` in save_last_session paths
- New RPC save_session handler

**Restore allowances:**
`nexus3/rpc/pool.py` in `_restore_unlocked()`:
```python
from nexus3.core.allowances import SessionAllowances

permissions.session_allowances = SessionAllowances.from_dict(saved.session_allowances or {})
```

---

### Fix 5: Agent Switching Cleanup Sequence

On `/agent X` switch:

1. **Stop accepting input** (break out of loop / return SWITCH_AGENT)
2. **Cancel local active turn if any:**
   ```python
   if active_request_id:
       await agent_client.cancel(active_request_id)  # best-effort
   ```
3. **Cancel background tasks in order:**
   ```python
   foreign_task.cancel()       # stops consuming router.global_queue
   await sync_feed.stop()      # cancels confirmation worker
   foreign_flush_task.cancel() # stops buffered printing
   pump_task.cancel()          # stops SSE stream pump
   ```
4. **Await cancellations** (each in try/except CancelledError)
5. **Unsubscribe queues:**
   ```python
   await router.unsubscribe(request_id, q)
   ```
6. **Reset state:**
   ```python
   active_request_id = None
   # Recreate SyncFeed for new agent (don't reuse - clear state)
   ```
7. **Close old client, create new one** for `/agent/{new_id}`
8. **Rebuild router/pump, recreate SyncFeed tasks**

---

### Fix 6: SSE Reconnect - Add Last-Event-ID Support

**Add parameter to iter_events:**
`nexus3/client.py`:
```python
async def iter_events(..., last_event_id: int | None = None, ...) -> AsyncIterator[dict[str, Any]]:
    headers = {"Accept": "text/event-stream"}
    if self._api_key:
        headers["Authorization"] = f"Bearer {self._api_key}"
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(int(last_event_id))
```

**Track seq in client loop:**
- Keep `last_seen_seq` updated from each event (`ev.get("seq")`)
- On disconnect, reopen `iter_events(last_event_id=last_seen_seq)`

---

### Fix 7: Host-Only Complete List

**Truly host-only (cannot be RPC):**
- Starting embedded server (precedes RPC)
- Choosing bind port / writing token file
- `/init` (writes to caller's working directory, not agent-scoped)

**Local UI (any terminal can do locally):**
- `/help`, `/clear`, local history, verbosity toggles

**Everything else should be RPC-backed:**
- Agent lifecycle (`/list`, `/create`, `/destroy`)
- Session persistence (`/save`, `/resume`, `/clone`, `/rename`, `/delete`)
- Agent config (`/cwd`, `/permissions`, `/prompt`, `/model`)
- Confirmations via SSE+RPC

---

## 10. Acceptance Criteria Checklist

### A) Architecture / Unification
- [ ] Host REPL uses the same client loop as `--connect` for send/cancel/confirm via RPC, events via SSE
- [ ] No in-process "unified special path" remains in REPL for normal interaction

### B) Core UX Parity (Must-Have)
- [ ] Streaming UI works in all terminals (thinking, content, tool progress)
- [ ] Cancel works identically (ESC cancels via RPC)

### C) Confirmations (Critical)
- [ ] Client loop handles `confirmation_requested` for active turn (prompt immediately, submit via RPC)
- [ ] Client loop renders foreign turn confirmation alerts, prompts when idle (Option B)
- [ ] If exec "allow always" supported: schema includes `allow_exec_cwd`, server maps to `ALLOW_EXEC_CWD`

### D) SyncFeed / Foreign Turn Visibility
- [ ] Foreign turns show user message header attribution
- [ ] Foreign streaming content coalesced and printed safely
- [ ] Foreign tool progress shown
- [ ] Foreign confirmation alerts shown immediately
- [ ] Foreign printing doesn't corrupt prompt (buffer during Live)

### E) Agent Switching and Lifecycle Commands
- [ ] `/agent <id>` works in any terminal using RPC (closes old SSE, reconnects, switches SyncFeed)
- [ ] Common commands work: `/list`, `/create`, `/destroy`, `/status`, `/compact`, `/cancel`

### F) Agent Config RPC Parity
- [ ] `set_cwd` - updates both services["cwd"] and permissions.effective_policy.cwd
- [ ] `get_permissions` / `set_permissions` - rebuilds context tool definitions
- [ ] `get_system_prompt` / `set_system_prompt` - exposes system_prompt_path

### G) Session Persistence RPC Parity
- [ ] Global RPC methods: `list_sessions`, `save_session`, `load_session`, `clone_session`, `rename_session`, `delete_session`
- [ ] Save includes `permissions.session_allowances.to_dict()`
- [ ] Restore loads allowances via `SessionAllowances.from_dict(...)`

### H) Robustness / Cleanup
- [ ] Agent switching cleanup sequence correct (cancels all workers, resets state)
- [ ] SSE reconnect behavior documented or implemented with `Last-Event-ID`

### I) Host-Only Scope Minimal
- [ ] Only host-only: starting server, `/init`
- [ ] Everything else available via RPC to any token-authenticated terminal

**Phase 8 complete when all boxes checked.**
