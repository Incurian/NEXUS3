# NEXUS3 Context Module

Context management for NEXUS3 agents: layered configuration loading, conversation history, token budgeting, truncation strategies, compaction via LLM summarization, and structured prompt construction.

## Overview

The context module is responsible for everything related to what an agent "knows" during a session:

1. **Loading context** from multiple directory layers (global, ancestor, local)
2. **Managing conversation history** (messages, tool calls, tool results)
3. **Tracking token usage** and enforcing budgets
4. **Truncating** old messages when over budget
5. **Compacting** via LLM summarization for longer sessions
6. **Injecting dynamic content** (date/time) safely into prompts

## Architecture

```
nexus3/context/
├── __init__.py        # Public exports
├── loader.py          # ContextLoader - layered config loading
├── manager.py         # ContextManager - runtime state and truncation
├── token_counter.py   # TokenCounter - pluggable token counting
├── compaction.py      # Compaction utilities - LLM summarization
└── prompt_builder.py  # StructuredPrompt - typed prompt construction
```

## Components

### ContextLoader (`loader.py`)

Loads and merges context from multiple directory layers with a defined precedence order.

#### Layer Hierarchy

```
LAYER 1: Install Defaults (shipped with package)
    |
LAYER 2: Global (~/.nexus3/)
    |
LAYER 3: Ancestors (up to N levels above CWD)
    |
LAYER 4: Local (CWD/.nexus3/)
```

Each layer can provide:
- `NEXUS.md` - System prompt content
- `README.md` - Documentation (fallback or included, based on config)
- `config.json` - Configuration overrides
- `mcp.json` - MCP server definitions

#### Loading Rules

| Content Type | Merge Strategy |
|--------------|----------------|
| NEXUS.md | Concatenated with labeled sections |
| README.md | Wrapped with documentation boundaries |
| config.json | Deep merged (later layers override) |
| mcp.json | Same name = later layer wins |

#### Key Classes

```python
@dataclass
class ContextLayer:
    """A single layer of context (global, ancestor, or local)."""
    name: str           # "global", "ancestor:dirname", "local"
    path: Path          # Directory path
    prompt: str | None  # NEXUS.md content
    readme: str | None  # README.md content
    config: dict | None # config.json content
    mcp: dict | None    # mcp.json content

@dataclass
class LoadedContext:
    """Result of loading all context layers."""
    system_prompt: str                    # Merged and labeled
    merged_config: dict[str, Any]         # Deep-merged configuration
    mcp_servers: list[MCPServerWithOrigin] # MCP servers with origin tracking
    sources: ContextSources               # Debug info about what was loaded

@dataclass
class ContextSources:
    """Tracks where each piece of context came from."""
    global_dir: Path | None
    ancestor_dirs: list[Path]
    local_dir: Path | None
    prompt_sources: list[PromptSource]
    config_sources: list[Path]
    mcp_sources: list[Path]
```

#### Usage

```python
from nexus3.context import ContextLoader

# Load context for current working directory
loader = ContextLoader()
context = loader.load(is_repl=True)

print(context.system_prompt)        # Merged NEXUS.md content
print(context.merged_config)        # Deep-merged config.json
print(context.mcp_servers)          # MCP servers with origins
print(context.sources.prompt_sources)  # Debug: which files contributed

# Load context for a specific directory
loader = ContextLoader(cwd=Path("/path/to/project"))
context = loader.load()

# Load for subagent (avoids duplication with parent)
subagent_prompt = loader.load_for_subagent(parent_context=context)
```

#### MCP Config Formats

Two MCP config formats are supported:

```json
// Official (Claude Desktop) format
{"mcpServers": {"test": {"command": "...", "args": [...]}}}

// NEXUS3 format
{"servers": [{"name": "test", "command": "...", "args": [...]}]}
```

#### System Information

The loader appends environment information to the prompt via `get_system_info()`:

```python
from nexus3.context import get_system_info

info = get_system_info(is_repl=True, cwd=Path.cwd())
# Output:
# # Environment
# Working directory: /home/user/project
# Operating system: Linux (WSL2 on Windows)
# Kernel: 6.6.87.2-microsoft-standard-WSL2
# Terminal: vscode (xterm-256color)
# Mode: Interactive REPL
```

Note: Current date/time is NOT included here - it's injected dynamically per-request by `ContextManager.build_messages()` to ensure accuracy throughout the session.

---

### ContextManager (`manager.py`)

Manages runtime conversation state, token budgets, and message truncation.

#### Configuration

```python
@dataclass
class ContextConfig:
    max_tokens: int = 8000          # Maximum tokens for context window
    reserve_tokens: int = 2000      # Tokens reserved for response generation
    truncation_strategy: str = "oldest_first"  # or "middle_out"
```

#### Core Responsibilities

1. **Message Management** - Add/clear user messages, assistant responses, tool results
2. **Token Tracking** - Track usage across system prompt, tools, and messages
3. **Truncation** - Remove old messages when over budget (preserving tool call/result pairs)
4. **Dynamic Injection** - Inject current date/time into prompts per-request

#### Message Types

The manager handles three message roles:

| Role | Method | Notes |
|------|--------|-------|
| USER | `add_user_message(content, meta?)` | User input, supports metadata (e.g., source attribution) |
| ASSISTANT | `add_assistant_message(content, tool_calls?)` | LLM responses, with optional tool calls |
| TOOL | `add_tool_result(tool_call_id, name, result)` | Tool execution results |

#### Truncation Strategies

When context exceeds budget, the manager truncates messages while preserving tool call/result pairs as atomic units.

**`oldest_first`** (default):
- Removes oldest message groups until under budget
- Keeps most recent context intact
- Best for task-focused conversations

**`middle_out`**:
- Keeps first and last message groups
- Removes middle groups
- Preserves both initial context and recent state

#### Token Usage

```python
usage = manager.get_token_usage()
# Returns:
# {
#     "system": 1500,      # System prompt tokens
#     "tools": 800,        # Tool definitions tokens
#     "messages": 3200,    # Conversation messages tokens
#     "total": 5500,       # Sum of above
#     "budget": 8000,      # max_tokens from config
#     "available": 6000,   # budget - reserve_tokens
#     "remaining": 500     # available - total (space left)
# }

if manager.is_over_budget():
    # Total exceeds available (max_tokens - reserve_tokens)
    pass
```

#### Usage

```python
from nexus3.context import ContextManager, ContextConfig, get_token_counter

# Initialize
config = ContextConfig(max_tokens=8000, reserve_tokens=2000)
manager = ContextManager(config, get_token_counter())

# Set up
manager.set_system_prompt("You are a helpful assistant.")
manager.set_tool_definitions([{"name": "read_file", ...}])
manager.add_session_start_message()  # Adds timestamped session marker

# Conversation loop
manager.add_user_message("Hello!")
messages = manager.build_messages()  # Returns messages for API call
# ... send to LLM ...
manager.add_assistant_message("Hi! How can I help?")

# After tool calls
manager.add_assistant_message("Let me read that file.", tool_calls=[...])
manager.add_tool_result(tool_call_id, "read_file", result)

# Check budget
if manager.is_over_budget():
    # Trigger compaction (see Compaction section)
    pass
```

#### DateTime Injection

The current date/time is injected into the system prompt on every `build_messages()` call:

```python
from nexus3.context import inject_datetime_into_prompt

# Finds "# Environment" section header and injects datetime after it
prompt = inject_datetime_into_prompt(
    prompt="# Environment\nWorking directory: /home/user",
    datetime_line="Current date: 2026-01-21, Current time: 14:30 (local)"
)
# Result:
# # Environment
# Current date: 2026-01-21, Current time: 14:30 (local)
# Working directory: /home/user
```

This ensures the agent always knows the current time, even in long-running sessions.

#### Helper Functions

```python
from nexus3.context.manager import get_current_datetime_str, get_session_start_str

# Get formatted datetime for injection
datetime_str = get_current_datetime_str()
# "Current date: 2026-01-21, Current time: 14:30 (local)"

# Get session start marker
start_str = get_session_start_str()
# "[Session started: 2026-01-21 14:30 (local)]"
```

---

### TokenCounter (`token_counter.py`)

Pluggable token counting with two implementations.

#### Protocol

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        """Count tokens in a text string."""
        ...

    def count_messages(self, messages: list[Message]) -> int:
        """Count tokens in a list of messages (includes overhead)."""
        ...
```

#### Implementations

**`SimpleTokenCounter`** - Character-based estimation (no dependencies):
- Uses heuristic: ~4 characters = 1 token
- Intentionally conservative (overestimates to avoid overflow)
- Adds 4-token overhead per message for role/formatting
- Good for rough estimates

**`TiktokenCounter`** - Accurate counting (requires tiktoken):
- Uses `cl100k_base` encoding (GPT-4/Claude-compatible)
- Accurate BPE tokenization
- Same message overhead calculation

#### Factory Function

```python
from nexus3.context import get_token_counter

# Try tiktoken, fall back to simple if unavailable
counter = get_token_counter()

# Force simple counter (no tiktoken dependency)
counter = get_token_counter(use_tiktoken=False)

# Usage
tokens = counter.count("Hello, world!")
total = counter.count_messages(messages)
```

---

### Compaction (`compaction.py`)

LLM-based summarization to reclaim context space while preserving essential information.

#### How Compaction Works

1. **Trigger**: When `used_tokens > trigger_threshold * available_tokens` (default 90%)
2. **Partition**: Split messages into "to summarize" (old) and "to preserve" (recent)
3. **Summarize**: Send old messages to a fast LLM for summarization
4. **Replace**: Replace old messages with summary message + preserved messages
5. **Reload**: Optionally reload system prompt (picks up NEXUS.md changes)

#### Key Functions

```python
from nexus3.context import (
    select_messages_for_compaction,
    build_summarize_prompt,
    create_summary_message,
    CompactionResult,
)
from nexus3.context.compaction import format_messages_for_summary

# 1. Partition messages
to_summarize, to_preserve = select_messages_for_compaction(
    messages=manager.messages,
    token_counter=manager.token_counter,
    available_budget=6000,
    recent_preserve_ratio=0.25  # Keep 25% of budget for recent messages
)

# 2. Build prompt for summarization LLM
prompt = build_summarize_prompt(to_summarize)
# Secrets are redacted by default for security

# 3. Call LLM (your code)
# summary_text = await llm.complete(prompt)

# 4. Create summary message (includes timestamp prefix)
summary_message = create_summary_message(summary_text)

# 5. Apply to manager
manager.apply_compaction(
    summary_message=summary_message,
    preserved_messages=to_preserve,
    new_system_prompt=new_prompt  # Optional: reload NEXUS.md
)
```

#### Summary Message Format

The summary includes a timestamped prefix:

```
[CONTEXT SUMMARY - Generated: 2026-01-21 14:30]
The following is a summary of our previous conversation. It was automatically
generated when the context window needed compaction. Treat this as established
context - you don't need to re-confirm decisions already made.

---
<LLM-generated summary>
```

#### Summarization Prompt

The prompt instructs the summarizing LLM to preserve:
- Key decisions and rationale
- Files created/modified and why
- Current task state and next steps
- Important constraints or requirements
- Errors encountered and resolutions

#### Security: Secret Redaction

By default, `format_messages_for_summary()` redacts secrets from message content and tool arguments before sending to the summarization LLM:

```python
from nexus3.context.compaction import format_messages_for_summary

# Redaction is on by default
formatted = format_messages_for_summary(messages, redact=True)

# Disable redaction (not recommended)
formatted = format_messages_for_summary(messages, redact=False)
```

---

### PromptBuilder (`prompt_builder.py`)

Typed prompt construction for safe dynamic content injection.

#### Why Structured Prompts?

The legacy approach used string operations like `str.replace()` for datetime injection, which could fail if the marker appeared elsewhere in the prompt. `StructuredPrompt` maintains explicit boundaries.

#### Components

```python
@dataclass
class PromptSection:
    """A typed section of the system prompt."""
    title: str          # e.g., "Project Configuration"
    content: str        # Section content
    source: Path | None # Source file for debugging
    section_type: Literal["config", "environment", "documentation"]

@dataclass
class EnvironmentBlock:
    """Typed environment information."""
    cwd: Path
    os_info: str
    terminal: str | None
    datetime_str: str | None  # Pre-formatted, injected at known position
    kernel: str | None
    mode: str | None
    extra_lines: list[str] | None

@dataclass
class StructuredPrompt:
    """Complete prompt with typed sections."""
    sections: list[PromptSection]
    environment: EnvironmentBlock | None

    def render(self) -> str: ...        # Sections joined with ---
    def render_compat(self) -> str: ... # Matches loader.py format exactly
```

#### Fluent Builder

```python
from nexus3.context import PromptBuilder, EnvironmentBlock
from pathlib import Path

prompt = (
    PromptBuilder()
    .add_section(
        title="Project Configuration",
        content="You are a helpful assistant for this project.",
        source=Path("/path/to/NEXUS.md"),
    )
    .add_section(
        title="User Preferences",
        content="Prefer concise responses.",
        section_type="config",
    )
    .set_environment(EnvironmentBlock(
        cwd=Path.cwd(),
        os_info="Linux (WSL2)",
        datetime_str="Current date: 2026-01-21, Current time: 14:30 (local)",
        mode="Interactive REPL",
    ))
    .build()
)

# Render for use
text = prompt.render_compat()  # Matches loader.py format
```

---

## Public API

All exports from `nexus3.context`:

```python
# Compaction
from nexus3.context import (
    CompactionResult,
    build_summarize_prompt,
    create_summary_message,
    select_messages_for_compaction,
)

# Context Loader
from nexus3.context import (
    ContextLayer,
    ContextLoader,
    ContextSources,
    LoadedContext,
    MCPServerWithOrigin,
    PromptSource,
    get_system_info,
    deep_merge,
)

# Context Manager
from nexus3.context import (
    ContextManager,
    ContextConfig,
    inject_datetime_into_prompt,
)

# Prompt Builder
from nexus3.context import (
    EnvironmentBlock,
    PromptBuilder,
    PromptSection,
    StructuredPrompt,
)

# Token Counter
from nexus3.context import (
    TokenCounter,
    SimpleTokenCounter,
    TiktokenCounter,
    get_token_counter,
)
```

---

## Dependencies

### Internal Dependencies

| Module | Imports From |
|--------|--------------|
| `core.types` | `Message`, `Role`, `ToolCall`, `ToolResult` |
| `core.errors` | `ContextLoadError`, `LoadError`, `MCPConfigError` |
| `core.constants` | `get_defaults_dir`, `get_nexus_dir` |
| `core.utils` | `deep_merge`, `find_ancestor_config_dirs` |
| `core.redaction` | `redact_dict`, `redact_secrets` |
| `config.load_utils` | `load_json_file` |
| `config.schema` | `ContextConfig` (config schema), `MCPServerConfig` |
| `mcp.errors` | `MCPErrorContext` |
| `session.logging` | `SessionLogger` (optional, for context logging) |

### External Dependencies

| Package | Usage | Required |
|---------|-------|----------|
| `tiktoken` | Accurate token counting | Optional (falls back to SimpleTokenCounter) |
| `pydantic` | MCP config validation | Yes |

---

## Integration with Other Modules

### Session Module

`ContextManager` is typically owned by a `Session`:

```python
# In session/session.py
class Session:
    def __init__(self):
        self.context = ContextManager(config, token_counter, logger)
```

### Compaction Flow

The session coordinates compaction when triggered:

```python
# Session checks if compaction needed
if self.context.is_over_budget():
    to_summarize, to_preserve = select_messages_for_compaction(...)
    summary = await self._run_summarization(to_summarize)
    self.context.apply_compaction(summary, to_preserve, new_prompt)
```

### Provider Module

`build_messages()` output goes directly to the provider:

```python
messages = context.build_messages()
tools = context.get_tool_definitions()
response = await provider.complete(messages, tools)
```

---

## Configuration Options

Context behavior is configured via `config.json`:

```json
{
  "context": {
    "ancestor_depth": 2,        // Parent dirs to check (0-10)
    "include_readme": false,    // Always include README.md
    "readme_as_fallback": true  // Use README when no NEXUS.md
  },
  "compaction": {
    "enabled": true,
    "model": "anthropic/claude-haiku",
    "summary_budget_ratio": 0.25,
    "recent_preserve_ratio": 0.25,
    "trigger_threshold": 0.9
  }
}
```

---

## Example: Complete Session Flow

```python
from pathlib import Path
from nexus3.context import (
    ContextLoader,
    ContextManager,
    ContextConfig,
    get_token_counter,
    select_messages_for_compaction,
    build_summarize_prompt,
    create_summary_message,
)

# 1. Load context from directory layers
loader = ContextLoader(cwd=Path.cwd())
loaded = loader.load(is_repl=True)

# 2. Initialize manager
config = ContextConfig(max_tokens=128000, reserve_tokens=4000)
manager = ContextManager(config, get_token_counter())
manager.set_system_prompt(loaded.system_prompt)
manager.set_tool_definitions(tools)
manager.add_session_start_message()

# 3. Conversation loop
while True:
    user_input = input("> ")
    manager.add_user_message(user_input)

    # Build messages with dynamic datetime
    messages = manager.build_messages()

    # Send to LLM
    response = await provider.complete(messages, manager.get_tool_definitions())
    manager.add_assistant_message(response.content, response.tool_calls)

    # Handle tool calls
    for tc in response.tool_calls or []:
        result = await execute_tool(tc)
        manager.add_tool_result(tc.id, tc.name, result)

    # Check if compaction needed
    if manager.is_over_budget():
        to_sum, to_keep = select_messages_for_compaction(
            manager.messages,
            manager.token_counter,
            config.max_tokens - config.reserve_tokens,
            0.25
        )
        prompt = build_summarize_prompt(to_sum)
        summary = await summarization_llm.complete(prompt)
        manager.apply_compaction(
            create_summary_message(summary.content),
            to_keep,
            loaded.system_prompt  # Reload NEXUS.md
        )
```

---

## Status

Production-ready. Last updated: 2026-01-28
