# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 1 complete. Now implementing session logging system.

---

## Current Phase: Phase 1 - Display & Interaction

**Goal**: Build the display foundation BEFORE adding skills, so we don't have to retrofit UI later.

### What's Working (Phase 1)
- ✅ Rich.Live streaming display with animated spinner during responses
- ✅ Response text accumulates in real-time
- ✅ Activity phases: WAITING → RESPONDING (THINKING reserved for trace detection)
- ✅ ESC cancellation with HTTP request cancellation
- ✅ Slash command handler (/quit, /exit, /q)
- ✅ Persistent status bar using prompt_toolkit bottom_toolbar (no scrollback pollution)
- ✅ Clean visual separation between exchanges
- ✅ 140 tests passing

### Known Limitations
- No conversation history - each message is single-turn (history planned for Phase 2)
- No animation during input (prompt_toolkit limitation) - animation only during streaming

### Next Up
- Logging modes (for debugging and thinking trace capture)

### Deferred
- Thinking trace detection (parse `<thinking>` tags) - after logging
- Type while agent active - requires Textual or custom input handling

---

### Display Architecture: Two-System Handoff

**Key insight**: prompt_toolkit and Rich.Live can't both control the terminal simultaneously. Solution: clean handoff between them.

```
During Input (prompt_toolkit):
┌─────────────────────────────────────────────────────────────┐
│ Previous response...                                        │
│                                                             │
│ >                                   <- prompt               │
│ ■ ● ready                           <- toolbar (virtual)    │
└─────────────────────────────────────────────────────────────┘

During Streaming (Rich.Live):
┌─────────────────────────────────────────────────────────────┐
│ Response text grows here...                                 │
│ ⠋ Responding...                     <- activity status     │
│ ⠋ ● active | ESC cancel             <- status bar          │
└─────────────────────────────────────────────────────────────┘
```

Key files:
- `display/streaming.py` - StreamingDisplay class (implements `__rich__`)
- `cli/repl.py` - Main REPL loop with toolbar + Rich.Live handoff

### Status Indicators ("Gumballs")

```
● (cyan)    = active (during streaming)
● (green)   = ready (during input)
● (red)     = error
● (yellow)  = cancelled
■ (dim)     = placeholder (no spinner during input)
```

### Component Breakdown

```
nexus3/
├── display/
│   ├── __init__.py
│   ├── manager.py       # DisplayManager - coordinates everything
│   ├── console.py       # Shared Rich Console instance
│   ├── printer.py       # Inline printing with gumballs
│   ├── summary.py       # Summary bar (Rich.Live region)
│   ├── segments.py      # Pluggable summary bar segments
│   └── theme.py         # Colors, styles, gumball characters
├── cli/
│   ├── repl.py          # REPL loop, uses DisplayManager
│   └── keys.py          # ESC handling, key bindings
└── core/
    └── cancel.py        # CancellationToken for async tasks
```

---

### Detailed Component Design

#### 1. DisplayManager (`display/manager.py`)

Central coordinator. Owns the Rich.Live context for summary bar.

```python
class DisplayManager:
    def __init__(self, console: Console, config: DisplayConfig):
        self.console = console
        self.printer = InlinePrinter(console)
        self.summary = SummaryBar(console)
        self._cancel_token: CancellationToken | None = None

    async def run_with_display(self, coro: Coroutine) -> Any:
        """Run coroutine with live summary bar updates."""
        self._cancel_token = CancellationToken()
        try:
            with self.summary.live():  # Rich.Live context
                return await coro
        finally:
            self._cancel_token = None

    def cancel(self) -> None:
        """Called when ESC pressed."""
        if self._cancel_token:
            self._cancel_token.cancel()

    # Inline printing (scrolls)
    def print(self, *args, **kwargs): ...
    def print_thinking(self, content: str, collapsed: bool = True): ...
    def print_status(self, indicator: str, message: str): ...

    # Summary bar updates
    def set_activity(self, activity: Activity): ...
    def add_task(self, task_id: str, label: str): ...
    def complete_task(self, task_id: str, success: bool): ...
```

#### 2. InlinePrinter (`display/printer.py`)

Handles all scrolling content output.

```python
class InlinePrinter:
    def __init__(self, console: Console, theme: Theme):
        self.console = console
        self.theme = theme

    def gumball(self, status: Status) -> str:
        """Return colored gumball character."""
        return self.theme.gumballs[status]

    def print(self, content: str, style: str | None = None):
        """Print content (scrolls)."""
        self.console.print(content, style=style)

    def print_thinking(self, content: str, collapsed: bool):
        """Print thinking trace inline."""
        if collapsed:
            self.print(f"{self.gumball(Status.ACTIVE)} Thinking...",
                      style=self.theme.thinking_collapsed)
        else:
            self.print(f"{self.gumball(Status.ACTIVE)} <thinking>",
                      style=self.theme.thinking)
            self.print(content, style=self.theme.thinking)
            self.print("</thinking>", style=self.theme.thinking)

    def print_task_start(self, task_type: str, label: str):
        """Print task starting (e.g., '  ● read_file: src/main.py')."""
        self.print(f"  {self.gumball(Status.ACTIVE)} {task_type}: {label}")

    def print_task_end(self, task_type: str, success: bool):
        """Print task completion."""
        status = Status.COMPLETE if success else Status.ERROR
        self.print(f"  {self.gumball(status)} {task_type}: {'complete' if success else 'failed'}")
```

#### 3. SummaryBar (`display/summary.py`)

The only Rich.Live component. Renders segments.

```python
class SummaryBar:
    def __init__(self, console: Console):
        self.console = console
        self.segments: list[SummarySegment] = []
        self._live: Live | None = None

    def register_segment(self, segment: SummarySegment, position: int = -1):
        """Register a segment to display in the bar."""
        if position < 0:
            self.segments.append(segment)
        else:
            self.segments.insert(position, segment)

    @contextmanager
    def live(self):
        """Context manager for Rich.Live."""
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=True,  # Don't leave artifacts
        )
        with self._live:
            yield

    def refresh(self):
        """Update the live display."""
        if self._live:
            self._live.update(self._render())

    def _render(self) -> RenderableType:
        """Compose all segments into a single line."""
        parts = [seg.render() for seg in self.segments if seg.visible]
        return Text(" | ").join(parts)
```

#### 4. Pluggable Segments (`display/segments.py`)

Each segment is independent, easy to add new ones.

```python
class SummarySegment(Protocol):
    @property
    def visible(self) -> bool: ...
    def render(self) -> RenderableType: ...

class ActivitySegment:
    """Shows current activity with spinner: ⠋ responding, ⠙ thinking, etc."""
    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"  # Braille spinner

    def __init__(self, theme: Theme):
        self.theme = theme
        self.activity: Activity = Activity.IDLE
        self._frame = 0

    @property
    def visible(self) -> bool:
        return self.activity != Activity.IDLE

    def render(self) -> Text:
        # Animated spinner (Rich.Live refreshes this)
        spinner = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        self._frame += 1
        return Text(f"{spinner} {self.activity.value}", style="cyan")

class TaskCountSegment:
    """Shows task counts: ● 2 active ○ 1 pending ● 5 done"""
    def __init__(self, theme: Theme):
        self.theme = theme
        self.active = 0
        self.pending = 0
        self.done = 0

    @property
    def visible(self) -> bool:
        return self.active + self.pending + self.done > 0

    def render(self) -> Text:
        parts = []
        if self.active:
            parts.append(f"{self.theme.gumballs[Status.ACTIVE]} {self.active} active")
        if self.pending:
            parts.append(f"{self.theme.gumballs[Status.PENDING]} {self.pending} pending")
        if self.done:
            parts.append(f"{self.theme.gumballs[Status.COMPLETE]} {self.done} done")
        return Text(" ".join(parts))

class CancelHintSegment:
    """Shows 'ESC to cancel' when activity is happening."""
    def __init__(self):
        self.show = False

    @property
    def visible(self) -> bool:
        return self.show

    def render(self) -> Text:
        return Text("ESC cancel", style="dim")

# Future segments (Phase 2+):
# - TokenCountSegment: "1.2k / 8k tokens"
# - SubagentSegment: "● agent:analyzer ● agent:fixer"
# - WorkflowSegment: "Step 2/5: analyzing"
```

#### 5. Theme (`display/theme.py`)

All visual styling in one place.

```python
@dataclass
class Theme:
    # Gumball characters and colors
    gumballs: dict[Status, str] = field(default_factory=lambda: {
        Status.ACTIVE: "[cyan]●[/]",
        Status.PENDING: "[dim]○[/]",
        Status.COMPLETE: "[green]●[/]",
        Status.ERROR: "[red]●[/]",
        Status.CANCELLED: "[yellow]●[/]",
    })

    # Text styles
    thinking: str = "dim italic"
    thinking_collapsed: str = "dim"
    response: str = ""
    error: str = "red"
    user_prompt: str = "bold"

    # Summary bar
    summary_separator: str = " | "
    summary_style: str = "on #1a1a1a"  # Subtle background

# Allow user customization via config
def load_theme(config: dict | None = None) -> Theme:
    theme = Theme()
    if config:
        # Override from config
        ...
    return theme
```

#### 6. Cancellation (`core/cancel.py`)

Clean async cancellation support.

```python
class CancellationToken:
    def __init__(self):
        self._cancelled = False
        self._callbacks: list[Callable] = []

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True
        for cb in self._callbacks:
            cb()

    def on_cancel(self, callback: Callable) -> None:
        self._callbacks.append(callback)
        if self._cancelled:
            callback()

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise CancelledError("Operation cancelled by user")
```

#### 7. ESC Key Handling (`cli/keys.py`)

Integrate with prompt-toolkit for ESC detection.

```python
async def handle_keys(display: DisplayManager, input_task: asyncio.Task):
    """Monitor for ESC key during operations."""
    # When not at prompt (during streaming/tool execution),
    # ESC should cancel the current operation.
    #
    # Implementation options:
    # 1. Raw terminal input monitoring
    # 2. prompt-toolkit key bindings
    # 3. Signal handling (less portable)
    ...
```

---

### Integration with REPL

```python
# cli/repl.py
async def run_repl():
    config = load_config()
    provider = OpenRouterProvider(config.provider)
    session = Session(provider)
    display = DisplayManager(Console(), DisplayConfig())

    # Register summary bar segments
    display.summary.register_segment(ActivitySegment(display.theme))
    display.summary.register_segment(TaskCountSegment(display.theme))
    display.summary.register_segment(CancelHintSegment())

    print_info("NEXUS3 v0.1.0")

    while True:
        try:
            user_input = await prompt_async("> ")
            if user_input.strip() == "/quit":
                break

            async def process():
                display.set_activity(Activity.THINKING)
                async for chunk in session.send(user_input):
                    if display.cancel_token.is_cancelled:
                        break
                    # Handle thinking vs response chunks
                    display.print_streaming(chunk)
                display.set_activity(Activity.IDLE)

            await display.run_with_display(process())

        except CancelledError:
            display.print_status(Status.CANCELLED, "Cancelled")
        except KeyboardInterrupt:
            break
```

---

### Implementation Order

| Step | Task | Notes |
|------|------|-------|
| 1 | `display/theme.py` | Gumballs, styles - no deps |
| 2 | `display/console.py` | Shared Console instance |
| 3 | `display/printer.py` | Inline printing with gumballs |
| 4 | `display/segments.py` | ActivitySegment, TaskCountSegment |
| 5 | `display/summary.py` | SummaryBar with Rich.Live |
| 6 | `core/cancel.py` | CancellationToken |
| 7 | `display/manager.py` | DisplayManager coordinating all |
| 8 | `cli/keys.py` | ESC handling |
| 9 | Update `cli/repl.py` | Integrate DisplayManager |
| 10 | Provider thinking extraction | Parse `<thinking>` from stream |
| 11 | Tests | Unit + integration |

### Acceptance Criteria

- [ ] Inline gumballs show task status (active/complete/error)
- [ ] Summary bar shows activity state and task counts
- [ ] Summary bar is configurable (segments can be added/removed)
- [ ] ESC cancels current stream/operation cleanly
- [ ] Thinking traces display collapsed by default ("Thinking...")
- [ ] Thinking traces can be expanded (show full content, muted theme)
- [ ] Normal terminal scrolling preserved (not fighting Rich.Live)
- [ ] Clean handoff between Rich.Live (summary) and prompt-toolkit (input)

### Blocked By
- Nothing (builds on Phase 0)

### Blocks
- Phase 2 (Core Skills) - needs display integration for tool progress

---

## Design Principles

1. **Async-first** - Use asyncio throughout, not threading
2. **Fail-fast** - No silent exception swallowing
3. **Single source of truth** - One way to do each thing
4. **Minimal viable interfaces** - Small, well-typed protocols
5. **End-to-end tested** - Integration tests for each feature, not just unit tests
6. **Document as you go** - Update this file with each phase

---

## Architecture

```
nexus3/
├── core/               # Minimal types + interfaces
│   ├── types.py        # Message, ToolCall, ToolResult (frozen dataclasses)
│   ├── interfaces.py   # Protocols for Provider, Skill, Sandbox
│   ├── errors.py       # Typed exception hierarchy
│   └── encoding.py     # UTF-8 constants and helpers
├── config/             # Simple JSON config
│   ├── schema.py       # Pydantic validation
│   └── loader.py       # Fail-fast loading
├── provider/           # LLM providers (async-first)
│   ├── base.py         # AsyncProvider protocol
│   └── openrouter.py   # Primary provider
├── display/            # Rich-based display system (Phase 1)
│   ├── manager.py      # DisplayManager - owns Rich.Live context
│   ├── status.py       # StatusLine component
│   ├── spinner.py      # Spinner component
│   ├── stream.py       # StreamRenderer for token output
│   ├── thinking.py     # ThinkingRenderer for reasoning traces
│   └── theme.py        # Colors, styles, theming
├── session/            # Chat session (thin coordinator)
│   └── session.py      # <200 lines, async
├── skill/              # Tool system (Phase 2+)
│   ├── base.py         # Minimal Skill interface
│   ├── registry.py     # Thread-safe registry
│   └── builtin/        # Start with 4-6 skills
├── cli/                # User interface
│   ├── repl.py         # Async REPL with prompt-toolkit
│   ├── keys.py         # Key bindings (ESC, etc.)
│   └── output.py       # Legacy output (deprecated after Phase 1)
└── subagent/           # Unified subagent system (Phase 4+)
    ├── pool.py         # Connection pooling, process reuse
    ├── process.py      # Cross-platform process management
    └── workflow.py     # DAG executor
```

---

## Development Phases

### Phase 0: MVP - Just Chat in CLI ✅
**Goal**: Single-turn chat, no tools, solid foundation

- [x] Core types: Message, Role, ToolResult (frozen dataclasses)
- [x] Config loader with validation (fail-fast, Pydantic)
- [x] AsyncProvider protocol + OpenRouter implementation
- [x] Async Session with streaming
- [x] Async REPL with prompt-toolkit + Rich
- [x] UTF-8 encoding everywhere (explicit, consistent)
- [x] End-to-end test: type message -> get streamed response

**No skills, no subagents, no history - just clean async chat**

### Phase 1: Display & Interaction Foundation 🔄
**Goal**: Build Rich UI foundation BEFORE skills to avoid painful retrofitting

- [ ] DisplayManager with Rich.Live context
- [ ] StatusLine component (thinking/responding/tool_calling/idle)
- [ ] Spinner during API wait (before first token)
- [ ] StreamRenderer for flicker-free token output
- [ ] ThinkingRenderer for reasoning traces (muted theme)
- [ ] ESC key cancellation (cancel stream mid-flight)
- [ ] Async task wrapper for cancellable operations
- [ ] Provider-level thinking trace extraction
- [ ] End-to-end test: ESC cancels stream cleanly

**Extensibility hooks for**: tool progress, subagent panels, token tracking

### Phase 2: Core Skills
**Goal**: Read/write files, run commands with proper UI

- [ ] Skill interface (minimal: name, description, parameters, execute)
- [ ] SkillRegistry (thread-safe)
- [ ] 4 essential skills: `read_file`, `write_file`, `list_dir`, `run_command`
- [ ] Tool calling flow in Session
- [ ] Tool progress display (uses DisplayManager)
- [ ] Sandbox for path validation
- [ ] Simple approval (allow/deny per skill)
- [ ] End-to-end test: "read this file" -> file contents

### Phase 3: Full Productivity Skills
**Goal**: Git, search, editing + token tracking

- [ ] `edit_file`, `glob`, `grep`, `git_status`, `git_diff`, `git_log`
- [ ] File operation skills: `delete_file`, `copy_path`, `move_path`, `make_dir`
- [ ] Message history with persistence
- [ ] Context management (system prompt, environment)
- [ ] Token tracking display (context budget)
- [ ] End-to-end test: multi-turn conversation with tool use

### Phase 4: Subagents - One-Shot Reading
**Goal**: Spawn subagent that can read, return result

- [ ] SubagentPool (connection pooling, process reuse)
- [ ] `spawn_agent` skill (read-only mode)
- [ ] Cross-platform process management
- [ ] Clean termination (taskkill /T on Windows, killpg on Unix)
- [ ] Result return via stdout (simple JSON)
- [ ] Subagent status in DisplayManager
- [ ] End-to-end test: spawn agent -> read file -> get result

### Phase 5: Subagents - Writing
**Goal**: Subagents can write files within sandbox

- [ ] 3-level permissions: YOLO > TRUSTED > SANDBOXED
- [ ] working_dir enforcement for SANDBOXED
- [ ] Subagent can use edit_file, write_file within its sandbox
- [ ] End-to-end test: spawn agent -> edit file -> verify changes

### Phase 6: Nested Subagents
**Goal**: Subagents can spawn their own subagents

- [ ] Permission inheritance (child < parent)
- [ ] Depth limiting (max 3 levels)
- [ ] Process tree tracking
- [ ] Clean cascade termination
- [ ] Subagent tree visualization
- [ ] End-to-end test: agent -> spawns agent -> spawns agent -> completes

### Phase 7: Coordination
**Goal**: Multi-agent workflows with shared state

- [ ] Blackboard (shared KV store)
- [ ] DAG workflow executor (single unified system)
- [ ] `orchestrate_workflow` skill
- [ ] Task cancellation that propagates
- [ ] Workflow progress panel
- [ ] End-to-end test: 3 agents coordinate via blackboard

### Phase 8: Watchable Terminals (Optional)
**Goal**: Spawn agents in visible terminal panes

- [ ] Log streaming to files (always on)
- [ ] Optional libtmux integration for power users
- [ ] `--watch` flag to follow agent output

---

## Development SOPs

### SOP 1: Type Everything

```python
# BAD - NEXUS2 pattern
config: Optional[Any] = None
skills: Any = field(default_factory=dict)

# GOOD - NEXUS3 pattern
config: Config  # Required, typed
skills: SkillRegistry  # Specific type, not dict or Any
```

No `Optional[Any]`. No duck-typing with `hasattr()`. Use Protocols for interfaces.

### SOP 2: Fail Fast, Never Silently

```python
# BAD - NEXUS2 pattern
try:
    config = load_file(path)
except Exception:
    pass  # TODO: emit warning

# GOOD - NEXUS3 pattern
try:
    config = load_file(path)
except FileNotFoundError:
    raise ConfigError(f"Config not found: {path}")
except json.JSONDecodeError as e:
    raise ConfigError(f"Invalid JSON in {path}: {e}")
```

Errors surface immediately. No `pass`. No swallowed exceptions.

### SOP 3: One Way to Do Each Thing

```python
# BAD - NEXUS2: 3 orchestration systems, 20 scripts
MultiAgentOrchestrator, Swarm, AgentHarness, agent_task.py, ask_nexus.py...

# GOOD - NEXUS3: One unified system
SubagentPool -> spawn_agent() skill -> that's it
```

No script proliferation. Features go in skills or CLI flags.

### SOP 4: Explicit Encoding Everywhere

```python
# In nexus3/core/encoding.py
ENCODING = "utf-8"
ENCODING_ERRORS = "replace"  # Preserve data, mark corruption

# All subprocess calls
subprocess.Popen(..., text=True, encoding=ENCODING, errors=ENCODING_ERRORS)

# All file operations
path.read_text(encoding=ENCODING, errors=ENCODING_ERRORS)
path.write_text(content, encoding=ENCODING)

# Stdin/stdout reconfiguration (all platforms, not just Windows)
for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding=ENCODING, errors=ENCODING_ERRORS)
```

### SOP 5: Test Each Feature End-to-End

```python
# For EVERY feature, add integration test
async def test_spawn_agent_reads_file():
    """End-to-end: spawn agent -> read file -> get result."""
    pool = SubagentPool()
    agent = await pool.acquire()
    result = await agent.execute("Read README.md")
    assert "NEXUS" in result["response"]
    await pool.release(agent)
```

Unit tests are not enough. Manual testing required before merge.

### SOP 6: Document Architecture Alongside Code

Each phase produces:
1. Working code
2. Tests that pass
3. Updated architecture section in this file
4. API documentation in docstrings

### SOP 7: Personal Testing Before Merge

- Manual testing checklist for each phase
- Test on both Windows and Linux
- Interactive REPL test, not just pytest

### SOP 8: No Dead Code

- If a feature is cut, delete the code immediately
- No `# TODO: implement later` that lingers
- Run `ruff check --select F401` for unused imports
- Periodic cleanup passes

### SOP 9: Size Limits Documented

```python
# nexus3/core/limits.py
MAX_FILE_READ_BYTES = 1_000_000  # 1MB default
MAX_TOOL_OUTPUT_CHARS = 50_000   # ~12k tokens
MAX_MESSAGE_HISTORY = 100        # Messages before compaction
SUBAGENT_TIMEOUT_DEFAULT = 120.0 # Seconds
```

All limits in one place, documented, configurable.

### SOP 10: Agents Use Parent's Python

```python
# Subagents use the same Python as the parent process
python_path = sys.executable

# This ensures consistent dependencies and avoids venv management complexity
```

---

## What We're NOT Carrying Over from NEXUS2

| Feature | Reason |
|---------|--------|
| 4-level permissions | Simplify to 3 levels: YOLO > TRUSTED > SANDBOXED |
| Tag-based approval | Profile-only approval system |
| 20+ scripts | Everything through skills or CLI flags |
| Swarm orchestration | Never finished, delete entirely |
| hasattr/getattr patterns | Proper typed interfaces with Protocols |
| Thread-based spinners | Async with Rich.Live |
| Dual approval system | Profile-only, no legacy tag system |
| Separate agent venv | Use parent's Python (sys.executable) |

## What We ARE Keeping (cleaned up)

| Feature | Changes |
|---------|---------|
| ToolResult pattern | Keep output/error/success - clean interface |
| EventBus | Add documented error semantics |
| Skill interface | Simplify, remove tags from approval logic |
| Process tree killing | Already good (taskkill /T, killpg) |
| Config hierarchy | But fail-fast, not silent |
| Session as coordinator | But no private field access |
| JSON-RPC protocol | Keep for subagent communication (better to have it) |

---

## Key Interfaces (Phase 0-1)

### Core Types

```python
# nexus3/core/types.py
from dataclasses import dataclass
from enum import Enum
from typing import Any

class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    tool_calls: tuple["ToolCall", ...] = ()
    tool_call_id: str | None = None

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ToolResult:
    output: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error
```

### Provider Protocol

```python
# nexus3/core/interfaces.py
from typing import Protocol, AsyncIterator

class AsyncProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> Message:
        """Non-streaming completion."""
        ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens."""
        ...
```

### Skill Protocol

```python
# nexus3/skill/base.py
from typing import Protocol, Any

class Skill(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> dict[str, Any]: ...

    async def execute(self, **kwargs: Any) -> ToolResult: ...
```

---

## Display System Summary

> **Detailed design**: See "Current Phase: Phase 1" section at top of this file.

**Architecture**: Inline + Summary Bar
- **Inline content**: Normal `print()`, scrolls naturally, uses gumballs for status
- **Summary bar**: Single Rich.Live region at bottom, above prompt
- **Input**: prompt-toolkit at absolute bottom

**Key Components**:
- `DisplayManager` - Coordinates printing and summary bar
- `InlinePrinter` - Gumball-based status printing
- `SummaryBar` - Pluggable segments (activity, task counts, hints)
- `CancellationToken` - Clean async cancellation

**Gumballs** (static colored indicators):
```
● cyan   = active/in-progress
● green  = complete/success
● red    = error/failed
● yellow = cancelled/warning
○ dim    = pending/queued
```

**Extensibility**: New summary bar segments implement `SummarySegment` protocol and register with `SummaryBar.register_segment()`

---

## Permission System

Three hierarchical levels, each can only spawn agents at lower levels:

```
YOLO (dangerous) > TRUSTED (default interactive) > SANDBOXED (restricted)
```

### YOLO Mode
- Equivalent to `--dangerously-skip-permissions`
- Human-only, cannot be spawned by agents
- All skills allowed without approval
- Use case: "I know what I'm doing, don't ask"

### TRUSTED Mode (Default for Interactive)
- Read/write files anywhere without approval
- **Asks before running arbitrary commands** (run_command skill)
- Can spawn SANDBOXED subagents
- Use case: Normal interactive use

### SANDBOXED Mode (Default for Subagents)
- Can read within working_dir
- Can create new files within working_dir
- Can write to explicitly whitelisted files/directories
- Cannot run commands (or other skills that need TRUSTED+)
- Cannot spawn subagents
- fail_fast on permission denial
- Use case: Automated subagent tasks

### Permission Inheritance
```python
# Parent spawns child with reduced permissions
parent_level = TRUSTED
child_level = SANDBOXED  # Automatic downgrade

# Child's working_dir must be within parent's
parent_cwd = Path("/project")
child_cwd = Path("/project/src")  # OK
child_cwd = Path("/other")  # DENIED
```

### Skill Categories by Permission
```python
ALWAYS_ALLOWED = {"read_file", "list_dir", "glob", "grep"}  # Read-only
TRUSTED_REQUIRED = {"run_command", "spawn_agent"}  # Dangerous
SANDBOXED_WRITE = {"write_file", "edit_file"}  # Allowed in cwd or whitelist
```

---

## Configuration

### Structure

```
~/.nexus3/
├── config.json          # Global config
└── sessions/            # Session data (later phases)
    └── {session_id}/
        └── ...

.nexus3/
└── config.json          # Project-local config (overrides global)
```

### Schema (Phase 0)

```json
{
  "provider": {
    "type": "openrouter",
    "api_key_env": "OPENROUTER_API_KEY",
    "model": "anthropic/claude-sonnet-4",
    "base_url": "https://openrouter.ai/api/v1"
  },
  "stream_output": true
}
```

Config is JSON only. No YAML dependency.

---

## CLI Commands

### Phase 0

```bash
# Interactive REPL
python -m nexus3

# One-shot (no tools)
python -m nexus3 --ask "What is 2+2?"
```

### Phase 1+

```bash
# With working directory
python -m nexus3 --working-dir /path/to/project

# With explicit config
python -m nexus3 --config custom.json
```

### Phase 3+

```bash
# Agent mode (for subagent spawning)
python -m nexus3 --agent

# Watch subagent logs
python -m nexus3 --watch agent_id
```

---

## Testing Strategy

### Directory Structure

```
tests/
├── unit/           # Fast, isolated tests
├── integration/    # End-to-end tests
└── conftest.py     # Shared fixtures
```

### Required Tests Per Phase

| Phase | Required E2E Tests |
|-------|-------------------|
| 0 | Chat sends message, receives streamed response |
| 1 | ESC cancels stream, status transitions correctly, spinner shows |
| 2 | Tool call executes read_file, returns content with progress |
| 3 | Multi-turn with tool use, history persists, token tracking |
| 4 | Subagent spawns, reads file, returns result |
| 5 | Subagent writes file within sandbox |
| 6 | Nested spawn completes without orphans |
| 7 | Workflow DAG executes in correct order |

### Development Setup

This project uses **uv** for Python version management and package installation.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv with Python 3.11
uv python install 3.11
uv venv --python 3.11 .venv

# Activate venv
source .venv/bin/activate

# Install package with dev dependencies
uv pip install -e ".[dev]"
```

**Python invocation:** Always use the venv Python:
```bash
source .venv/bin/activate
python -m nexus3  # Run the CLI
```

### Running Tests

```bash
# Activate venv first
source .venv/bin/activate

# All tests
pytest tests/ -v

# Just integration
pytest tests/integration/ -v

# With coverage
pytest tests/ --cov=nexus3 --cov-report=term-missing

# Linting and type checking
ruff check nexus3/
mypy nexus3/
```

---

## Dependencies

### Core (Phase 0)

```
httpx>=0.27.0        # Async HTTP client
rich>=13.0.0         # Terminal output
prompt-toolkit>=3.0  # REPL input
pydantic>=2.0        # Config validation
```

### Optional (Later Phases)

```
libtmux>=0.30.0      # Terminal multiplexing (Phase 7)
```

### Dev

```
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=4.0
ruff>=0.3.0
mypy>=1.8
```

---

## Known NEXUS2 Issues to Avoid

### 1. Duck-Typing (hasattr/getattr)
NEXUS2 used `hasattr(ctx.config, "field")` everywhere. This hides type errors until runtime.

**Fix**: All interfaces are Protocols. Type checker validates at dev time.

### 2. Silent Config Errors
NEXUS2 swallowed config loading errors with `except: pass`.

**Fix**: Fail-fast. Config errors crash on startup with clear message.

### 3. Subprocess Encoding
NEXUS2 used `text=True` without explicit encoding, relying on system locale.

**Fix**: Always specify `encoding='utf-8', errors='replace'`.

### 4. Three Orchestration Systems
NEXUS2 had AgentHarness, MultiAgentOrchestrator, and Swarm competing.

**Fix**: One unified SubagentPool system.

### 5. Tag-Based Approval
NEXUS2 used skill tags for both categorization AND approval, causing confusion.

**Fix**: Tags are metadata only. Approval is explicit per-skill or per-profile.

### 6. Private Field Access
Session directly manipulated `self._history._messages` (private fields).

**Fix**: All components expose public methods. No underscore access across boundaries.

### 7. Process Tree Orphans
Task cancellation didn't reliably kill all child processes.

**Fix**: Use process groups (start_new_session on Unix, taskkill /T on Windows).

---

## Git Workflow

**Branches:**
- `main` - Stable releases
- `dev` - Active development

**Commit Messages:**
```
feat: Add streaming response support
fix: Handle UTF-8 encoding in subprocess
docs: Update architecture diagram
test: Add e2e test for tool calling
refactor: Simplify skill registry
```

**Before Committing:**
1. `ruff check nexus3/` passes
2. `mypy nexus3/` passes
3. `pytest tests/` passes
4. Manual REPL test works

---

## Questions Resolved

| Question | Decision |
|----------|----------|
| Async everywhere? | Yes, asyncio-first |
| Permission levels? | 3 levels: YOLO > TRUSTED > SANDBOXED |
| CLI framework? | prompt-toolkit + Rich (no Typer/Click) |
| Subagent protocol? | JSON-RPC over stdio (keep it, better to have) |
| Agent Python? | Use parent's Python (sys.executable) |
| Terminal multiplexing? | Always log + Rich Live panel |
| Minimum Python? | 3.11+ |
| Config validation? | Pydantic v2 |

---

## Current Work: Session Logging System

**Goal**: Structured logging for context management, debugging, and future session replay/compaction.

### Directory Structure

```
.nexus3/logs/                              # Gitignored
└── 2024-01-07_143052_a1b2c3/              # Session: timestamp + 6-char ID
    ├── session.db                          # SQLite - source of truth
    ├── context.md                          # Human-readable context view
    ├── verbose.md                          # Thinking, timing, metadata (optional)
    ├── raw.jsonl                           # Raw API JSON (optional)
    ├── temp/                               # Working files (future)
    └── subagent_d4e5f6/                    # Nested subagent session
        ├── session.db
        ├── context.md
        └── ...
```

### Log Streams (Independent, Non-Exclusive)

| Stream | File | Format | Enabled | Contains |
|--------|------|--------|---------|----------|
| context | `session.db` + `context.md` | SQLite + MD | Always | Messages, tool calls in context |
| verbose | `verbose.md` | Markdown | `--verbose` | Thinking traces, timing, token counts |
| raw | `raw.jsonl` | JSON Lines | `--raw-log` | Raw API request/response bodies |

### SQLite Schema (`session.db`)

```sql
-- Core message storage
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,                    -- system, user, assistant, tool
    content TEXT NOT NULL,
    name TEXT,                             -- tool name (for tool role)
    tool_call_id TEXT,                     -- for tool results
    tool_calls TEXT,                       -- JSON: assistant's tool calls
    tokens INTEGER,                        -- estimated token count
    timestamp REAL NOT NULL,
    in_context BOOLEAN DEFAULT 1,          -- still in active context?
    summary_of TEXT                        -- comma-separated IDs if summary
);

-- Session metadata
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Keys: model, system_prompt, created_at, parent_session, etc.

-- Future: tool execution details, thinking traces, etc.
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,                    -- related message (optional)
    event_type TEXT NOT NULL,              -- thinking, tool_start, tool_end, etc.
    data TEXT,                             -- JSON payload
    timestamp REAL NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);
```

### Architecture

```
nexus3/
├── session/
│   ├── session.py              # Session coordinator (existing)
│   ├── logging.py              # SessionLogger - main logging interface
│   ├── storage.py              # SQLite operations, schema management
│   ├── markdown.py             # Markdown generation from DB
│   └── types.py                # LogLevel enum, LogConfig dataclass
```

### Key Interfaces

```python
# session/types.py
from enum import Flag, auto
from dataclasses import dataclass
from pathlib import Path

class LogStream(Flag):
    """Log streams - can be combined with |"""
    NONE = 0
    CONTEXT = auto()    # Always on in practice
    VERBOSE = auto()    # --verbose
    RAW = auto()        # --raw-log
    ALL = CONTEXT | VERBOSE | RAW

@dataclass
class LogConfig:
    base_dir: Path              # .nexus3/logs
    streams: LogStream          # Which streams to write
    parent_session: str | None  # For subagent nesting

@dataclass
class SessionInfo:
    session_id: str             # e.g., "2024-01-07_143052_a1b2c3"
    session_dir: Path           # Full path to session folder
    parent_id: str | None       # Parent session if subagent
```

```python
# session/logging.py
class SessionLogger:
    """Central logging interface for a session."""

    def __init__(self, config: LogConfig):
        self.config = config
        self.info = self._create_session()
        self.storage = SessionStorage(self.info.session_dir / "session.db")
        self._md_writer = MarkdownWriter(self.info.session_dir)

    # === Message Logging (always goes to context) ===

    def log_system(self, content: str) -> int:
        """Log system prompt. Returns message ID."""

    def log_user(self, content: str) -> int:
        """Log user message. Returns message ID."""

    def log_assistant(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
        thinking: str | None = None,      # For verbose stream
        tokens: int | None = None,
    ) -> int:
        """Log assistant response. Returns message ID."""

    def log_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: ToolResult,
    ) -> int:
        """Log tool execution result. Returns message ID."""

    # === Verbose Stream ===

    def log_thinking(self, content: str, message_id: int | None = None):
        """Log thinking trace (verbose only)."""

    def log_timing(self, operation: str, duration_ms: float):
        """Log timing info (verbose only)."""

    # === Raw Stream ===

    def log_raw_request(self, endpoint: str, payload: dict):
        """Log raw API request (raw only)."""

    def log_raw_response(self, status: int, body: dict):
        """Log raw API response (raw only)."""

    # === Context Management ===

    def get_context_messages(self) -> list[Message]:
        """Get all messages currently in context window."""

    def get_token_count(self) -> int:
        """Get total tokens in current context."""

    def mark_compacted(self, message_ids: list[int], summary_id: int):
        """Mark messages as compacted, replaced by summary."""

    # === Subagent Support ===

    def create_child_logger(self, name: str = None) -> "SessionLogger":
        """Create a nested logger for a subagent."""
```

```python
# session/storage.py
class SessionStorage:
    """SQLite operations for session data."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()

    def insert_message(self, role: str, content: str, **kwargs) -> int:
        """Insert message, return ID."""

    def get_messages(self, in_context_only: bool = True) -> list[dict]:
        """Get messages, optionally filtered to context window."""

    def update_context_status(self, message_ids: list[int], in_context: bool):
        """Batch update in_context flag."""

    def get_metadata(self, key: str) -> str | None:
        """Get metadata value."""

    def set_metadata(self, key: str, value: str):
        """Set metadata value."""

    def insert_event(self, event_type: str, data: dict, message_id: int = None):
        """Insert event for verbose logging."""
```

```python
# session/markdown.py
class MarkdownWriter:
    """Generates human-readable markdown from session data."""

    def __init__(self, session_dir: Path):
        self.context_path = session_dir / "context.md"
        self.verbose_path = session_dir / "verbose.md"

    def append_message(self, role: str, content: str, **kwargs):
        """Append message to context.md."""

    def append_thinking(self, content: str, timestamp: float):
        """Append thinking trace to verbose.md."""

    def append_tool_call(
        self,
        name: str,
        arguments: dict,
        result: str,
        duration_ms: float | None = None,
    ):
        """Append tool call to context.md (and verbose.md with timing)."""
```

### Configuration

```python
# config/schema.py - add to existing Config
@dataclass
class LoggingConfig:
    base_dir: str = ".nexus3/logs"    # Relative to cwd or absolute
    context_always: bool = True        # Context stream always on
    verbose: bool = False              # --verbose flag
    raw: bool = False                  # --raw-log flag
```

### CLI Integration

```bash
# Default: context logging only
python -m nexus3

# With verbose (thinking, timing)
python -m nexus3 --verbose

# With raw API logging
python -m nexus3 --raw-log

# Both
python -m nexus3 --verbose --raw-log
```

### Implementation Order

| Step | Task | Notes |
|------|------|-------|
| 1 | `session/types.py` | LogStream, LogConfig, SessionInfo |
| 2 | `session/storage.py` | SQLite wrapper, schema creation |
| 3 | `session/markdown.py` | Markdown file writers |
| 4 | `session/logging.py` | SessionLogger main class |
| 5 | Update `.gitignore` | Add `.nexus3/logs/` |
| 6 | Integrate with `cli/repl.py` | Create logger, pass to session |
| 7 | Update `Session` class | Accept logger, call log methods |
| 8 | CLI flags | `--verbose`, `--raw-log` |
| 9 | Tests | Unit tests for storage, logging |

### Scaffolding Notes

**Extensibility points built in:**
- `LogStream` is a Flag enum - easy to add new streams
- `events` table for future event types (tool progress, errors, etc.)
- `metadata` table for arbitrary session metadata
- `create_child_logger()` ready for subagent nesting
- Token counting placeholder (actual counting comes later)
- Compaction interface ready (implementation comes with context management)

**Not hardcoded:**
- Log directory path (configurable)
- Session ID format (generated by helper function)
- Stream enable/disable (flags, not booleans)
- Markdown format (separate writer class)

### Acceptance Criteria

- [ ] Each REPL session creates a new session folder
- [ ] `session.db` contains all messages with correct schema
- [ ] `context.md` is human-readable, updated in real-time
- [ ] `--verbose` enables `verbose.md` with thinking traces
- [ ] `--raw-log` enables `raw.jsonl` with API payloads
- [ ] Subagent sessions nest correctly (manual test for now)
- [ ] `get_context_messages()` returns messages for API calls
- [ ] Old sessions preserved, new session each run

---

## Next Steps

1. ~~**Initialize repo**: `git init`, `.gitignore`, `pyproject.toml`~~ ✅
2. ~~**Phase 0 implementation**: Core types, config, provider, session, CLI~~ ✅
3. ~~**First E2E test**: Message in, streamed response out~~ ✅
4. ~~**Phase 1 implementation**: Display system foundation~~ ✅
   - ~~Rich.Live streaming with animated spinner~~
   - ~~ESC cancellation~~
   - ~~Persistent toolbar status bar~~
5. **Phase 1.5: Session Logging** ← Current
   - SQLite-backed context storage
   - Markdown human-readable logs
   - Verbose and raw log streams
6. **Phase 2 implementation**: Core skills with progress display
7. **Phase 3 implementation**: Full productivity skills + token tracking
