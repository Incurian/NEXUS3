# Context Module

Context management for NEXUS3 conversations: system prompts, message history, token budgets, and truncation.

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| `ContextManager` | ✅ Complete | Central coordinator for context |
| `PromptLoader` with layered config | ✅ Complete | Personal + project prompt combination with system info |
| `ContextLoader` with multi-layer loading | ✅ Complete | Global → ancestors → local with labeled sections |
| Token counting (tiktoken default) | ✅ Complete | Accurate token counting with fallback |
| Truncation strategies | ✅ Complete | `oldest_first` and `middle_out` with atomic message groups |
| Compaction | ✅ Complete | LLM-based summarization to free context space |


## Purpose

This module manages the conversation context window for LLM API calls:

- **System prompt loading** with layered configuration (personal + project + system info)
- **Message history** tracking (user, assistant, tool results)
- **Token budget** management with pluggable counters
- **Automatic truncation** when context exceeds budget

## Key Types/Classes

| Type | Description |
|------|-------------|
| `ContextManager` | Central coordinator for conversation state and token budgets |
| `ContextConfig` | Configuration for token limits and truncation strategy |
| `ContextLoader` | Unified loader for multi-layer context (global → ancestors → local) |
| `LoadedContext` | Result of context loading with merged prompt, config, and MCP servers |
| `ContextLayer` | A single layer of context (global, ancestor, or local) |
| `ContextSources` | Tracks where each piece of context came from |
| `PromptLoader` | Loads and combines system prompts from multiple sources with system info |
| `LoadedPrompt` | Result of prompt loading with combined content and source paths |
| `PromptSource` | Protocol for prompt sources (files, env vars, etc.) |
| `FilePromptSource` | Loads prompt content from a filesystem path |
| `TokenCounter` | Protocol for token counting implementations |
| `SimpleTokenCounter` | Character-based estimation (~4 chars/token) |
| `TiktokenCounter` | Accurate counting using tiktoken library (cl100k_base encoding) |
| `get_token_counter()` | Factory function to get appropriate counter |

## ContextManager

Manages conversation history and builds message lists for API calls.

### Creation Patterns

ContextManager is created in two main ways:

**1. REPL Mode (Interactive CLI)**

In `nexus3/cli/repl.py`, a single ContextManager is created for the session:

```python
from nexus3.context import ContextManager, ContextConfig, PromptLoader

# Load system prompt
prompt_loader = PromptLoader()
loaded_prompt = prompt_loader.load()  # is_repl=True by default

# Create context manager
context = ContextManager(
    config=ContextConfig(),
    logger=logger,  # SessionLogger for logging
)
context.set_system_prompt(loaded_prompt.content)

# Inject tool definitions
context.set_tool_definitions(registry.get_definitions())

# Create session with context
session = Session(provider, context=context, logger=logger, registry=registry)
```

**2. Per-Agent in AgentPool (HTTP Server Mode)**

In `nexus3/rpc/pool.py`, each agent gets its own ContextManager with isolated state:

```python
# In AgentPool.create():
# Determine system prompt (can be overridden per-agent)
if agent_config.system_prompt is not None:
    system_prompt = agent_config.system_prompt
else:
    loaded_prompt = shared.prompt_loader.load(is_repl=False)
    system_prompt = loaded_prompt.content

# Create context manager for this agent
context = ContextManager(
    config=ContextConfig(),
    logger=logger,  # Agent's own SessionLogger
)
context.set_system_prompt(system_prompt)

# Inject tool definitions
context.set_tool_definitions(registry.get_definitions())

# Context is passed to Session and Dispatcher
session = Session(provider, context=context, logger=logger, registry=registry)
dispatcher = Dispatcher(session, context=context)
```

### Responsibilities

- Maintains system prompt, tool definitions, and message history
- Tracks token usage across all context components
- Truncates messages when over budget
- Logs to `SessionLogger` if provided

### Token Budget

```
max_tokens (8000 default)
  - reserve_tokens (2000 default)  <- Reserved for response
  = available (6000)               <- Budget for context
```

### Configuration

```python
@dataclass
class ContextConfig:
    max_tokens: int = 8000           # Maximum tokens for context window
    reserve_tokens: int = 2000       # Tokens to reserve for response
    truncation_strategy: str = "oldest_first"  # or "middle_out"
```

### Message Methods

| Method | Description |
|--------|-------------|
| `add_user_message(content)` | Add user input to context |
| `add_assistant_message(content, tool_calls)` | Add LLM response |
| `add_tool_result(tool_call_id, name, result)` | Add tool execution result |
| `clear_messages()` | Clear all messages (keeps system prompt and tools) |

### Context Building

| Method | Description |
|--------|-------------|
| `build_messages()` | Build message list for API call (with truncation if needed) |
| `get_tool_definitions()` | Get tool definitions for API call |

### Token Tracking

| Method | Description |
|--------|-------------|
| `get_token_usage()` | Get breakdown: system, tools, messages, total, budget, available |
| `is_over_budget()` | Check if total > available |

### Internal Truncation Methods

These methods are used internally by `build_messages()` but are documented here for understanding:

| Method | Description |
|--------|-------------|
| `_get_context_messages()` | Get messages that fit in budget, applying truncation if needed |
| `_identify_message_groups()` | Group messages into atomic units (standalone or tool call + results) |
| `_count_group_tokens(group)` | Count tokens for a message group |
| `_flatten_groups(groups)` | Flatten list of groups into single message list |
| `_truncate_oldest_first()` | Remove oldest groups until under budget |
| `_truncate_middle_out()` | Keep first/last groups, remove middle groups |

### Properties

| Property | Description |
|----------|-------------|
| `system_prompt` | Get current system prompt |
| `messages` | Get all messages (read-only copy) |

## Integration with AgentPool

The `AgentPool` (in `nexus3/rpc/pool.py`) creates one ContextManager per agent:

```
AgentPool
    └── Agent (per agent_id)
            ├── ContextManager (isolated conversation history)
            ├── SessionLogger (writes to agent's log directory)
            ├── SkillRegistry (with ServiceContainer)
            ├── Session (uses context for multi-turn)
            └── Dispatcher (uses context for get_tokens/get_context)
```

**Key points:**

1. **Shared Components**: Provider (for connection pooling), PromptLoader, and base config are shared
2. **Isolated State**: Each agent has its own ContextManager with independent message history
3. **System Prompt Override**: Agents can have custom system prompts via `AgentConfig.system_prompt`
4. **Tool Definitions**: Injected into context from the agent's SkillRegistry
5. **RPC Methods**: Dispatcher exposes `get_tokens` and `get_context` methods using the agent's ContextManager

## PromptLoader

Loads system prompts with a two-layer approach plus automatic system information injection:

```
Personal Layer (first match wins):
  1. ~/.nexus3/NEXUS.md          <- User defaults
  2. <package>/defaults/NEXUS.md  <- Package defaults

Project Layer (optional):
  ./NEXUS.md                      <- Project-specific config (cwd)

System Info (always appended):
  # Environment
  Working directory, OS, terminal info
```

### System Information

The `get_system_info(is_repl)` function generates static environment context:

- **Working directory**: Current working directory path
- **Operating system**: Detected OS with special handling for WSL2, Linux distros, macOS versions
- **Terminal**: Terminal program and TERM variable (REPL mode only)
- **Mode**: "Interactive REPL" or "HTTP JSON-RPC Server"

### Temporal Context (Dynamic)

NEXUS3 provides three layers of temporal context to ensure agents always know when events occurred:

1. **Current Date/Time (Dynamic)**: Injected fresh on every API request via `ContextManager.build_messages()`. Always accurate.
2. **Session Start Timestamp (Fixed)**: Added to message history when a new agent is created. Marks when the session began.
3. **Compaction Timestamp (On Compaction)**: Included in context summaries to indicate when the summary was generated.

### Combination

All layers are combined with headers:

```markdown
# Personal Configuration
[personal prompt content]

# Project Configuration
[project prompt content]

# Environment
Current date: 2026-01-13, Current time: 14:30 (local)
Working directory: /path/to/project
Operating system: Linux (WSL2 on Windows)
Terminal: vscode (xterm-256color)
Mode: Interactive REPL
```

The first message in a new session's history is always:
```
[Session started: 2026-01-13 14:30 (local)]
```

### LoadedPrompt Result

```python
@dataclass
class LoadedPrompt:
    content: str           # Combined prompt with headers and system info
    personal_path: Path | None  # Path to personal/default prompt
    project_path: Path | None   # Path to project prompt (if loaded)
```

### Extensibility

Custom prompt sources can implement the `PromptSource` protocol:

```python
class PromptSource(Protocol):
    def load(self) -> str | None: ...
    @property
    def path(self) -> Path | None: ...
```

## TokenCounter

Pluggable token counting with two implementations:

| Implementation | Accuracy | Method | Dependencies |
|---------------|----------|--------|--------------|
| `TiktokenCounter` | Accurate | Uses tiktoken cl100k_base encoding | `tiktoken` package |
| `SimpleTokenCounter` | Approximate | ~4 chars/token (conservative) | None |

### Default Behavior

`get_token_counter()` defaults to `use_tiktoken=True`:
- Returns `TiktokenCounter` if tiktoken is installed
- Falls back to `SimpleTokenCounter` if import fails

### TokenCounter Protocol

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
    def count_messages(self, messages: list[Message]) -> int: ...
```

Both implementations add `OVERHEAD_PER_MESSAGE = 4` tokens per message for role/formatting overhead. Tool calls are counted by serializing arguments to JSON.

## Truncation

When context exceeds budget, messages are truncated automatically during `build_messages()`.

### Strategies

**`oldest_first` (default):**
- Removes oldest message groups first
- Builds from newest groups backwards until budget exhausted
- Always keeps at least the most recent group
- Best for long conversations where recent context matters most

**`middle_out`:**
- Keeps first and last message groups
- Removes from the middle, prioritizing recent groups
- Fills remaining budget with groups nearest to the end
- Preserves initial context and recent conversation

### Atomic Message Groups

Both truncation strategies preserve tool call/result pairs as atomic units:

1. **Standalone messages**: USER, SYSTEM, or ASSISTANT without tool_calls
2. **Tool call groups**: ASSISTANT with tool_calls + all corresponding TOOL result messages

This prevents invalid API sequences where tool calls are separated from their results.

### Budget Calculation

```python
budget_for_messages = available - system_tokens - tools_tokens

# If budget <= 0, only most recent group is kept
```

## Compaction

Compaction uses LLM summarization to reclaim context space while preserving conversation continuity. Unlike truncation (which discards old messages), compaction summarizes them into a condensed form.

### Purpose

When context approaches capacity, compaction:
1. Identifies older messages to summarize
2. Preserves recent messages (configurable ratio)
3. Uses the LLM to generate a summary of older messages
4. Replaces the conversation history with summary + preserved messages
5. Optionally reloads the system prompt to pick up NEXUS.md changes

### Key Functions

| Function | Description |
|----------|-------------|
| `select_messages_for_compaction(messages, token_counter, budget, ratio)` | Split messages into (to_summarize, to_preserve) |
| `build_summarize_prompt(messages)` | Build prompt for LLM summarization call |
| `create_summary_message(summary_text)` | Wrap summary in a USER message with prefix |

### CompactionResult

```python
@dataclass
class CompactionResult:
    summary_message: Message      # The summary as a USER message with prefix
    preserved_messages: list[Message]  # Recent messages not summarized
    original_token_count: int     # Tokens before compaction
    new_token_count: int          # Tokens after compaction
```

### Message Selection

The `select_messages_for_compaction` function walks backwards from the newest message, keeping recent messages until the preserve budget is exhausted:

```python
to_summarize, to_preserve = select_messages_for_compaction(
    messages=context.messages,
    token_counter=counter,
    available_budget=6000,      # Budget for messages
    recent_preserve_ratio=0.25,  # Keep 25% of budget for recent messages
)
```

### Summary Format

Summaries are prefixed with a marker explaining their nature:

```
[CONTEXT SUMMARY]
The following is a summary of our previous conversation. It was automatically
generated when the context window needed compaction. Treat this as established
context - you don't need to re-confirm decisions already made.

---
[summary content]
```

### Integration with ContextManager

The `ContextManager.apply_compaction()` method applies compaction results:

```python
context.apply_compaction(
    summary_message=result.summary_message,
    preserved_messages=result.preserved_messages,
    new_system_prompt=fresh_prompt,  # Optional: reload NEXUS.md
)
```

This replaces all messages with `[summary_message] + preserved_messages` and optionally updates the system prompt.

### System Prompt Reloading

Compaction provides an opportunity to reload the system prompt, picking up any changes to NEXUS.md since the session started:

```python
# Reload system prompt during compaction
loader = PromptLoader()
fresh_prompt = loader.load().content

context.apply_compaction(
    summary_message=summary_msg,
    preserved_messages=preserved,
    new_system_prompt=fresh_prompt,  # Pick up NEXUS.md changes
)
```

## Data Flow

```
                    +-----------------+
                    | PromptLoader    |
                    | load(is_repl)   |
                    +--------+--------+
                             |
                             v
+---------------+   +--------+--------+   +----------------+
| User Message  |-->| ContextManager  |-->| build_messages |
| Assistant Msg |   | - system_prompt |   | (for API call) |
| Tool Result   |   | - messages[]    |   +----------------+
+---------------+   | - tools[]       |
                    +--------+--------+
                             |
                             v
                    +--------+--------+
                    | TokenCounter    |
                    | count()         |
                    | count_messages()|
                    +-----------------+
                             |
                             v
                    +--------+--------+
                    | Truncation      |
                    | (if over budget)|
                    +-----------------+
```

## Dependencies

**From `nexus3.core`:**
- `Message`, `Role`, `ToolCall`, `ToolResult` - Core types

**From `nexus3.session`:**
- `SessionLogger` - Optional context logging (TYPE_CHECKING only)

**External (optional):**
- `tiktoken` - For accurate token counting (recommended, default)

**Standard Library:**
- `platform` - OS detection for system info
- `json` - Tool call argument serialization

## Usage Examples

### Basic Context Management

```python
from nexus3.context import ContextManager, ContextConfig, PromptLoader

# Load system prompt
loader = PromptLoader()
prompt = loader.load()

# Create context manager
config = ContextConfig(max_tokens=8000, reserve_tokens=2000)
context = ContextManager(config)
context.set_system_prompt(prompt.content)

# Add messages
context.add_user_message("Hello!")
context.add_assistant_message("Hi there!")

# Build for API call
messages = context.build_messages()
tools = context.get_tool_definitions()
```

### Check Token Usage

```python
usage = context.get_token_usage()
print(f"Total: {usage['total']} / {usage['budget']}")
print(f"Available: {usage['available']}")

if context.is_over_budget():
    print("Context will be truncated on next build_messages()")
```

### Custom Token Counter

```python
from nexus3.context import get_token_counter, TiktokenCounter, SimpleTokenCounter

# Auto-select (prefers tiktoken)
counter = get_token_counter()

# Force simple counter (no dependencies)
counter = get_token_counter(use_tiktoken=False)

# Direct tiktoken with custom encoding
counter = TiktokenCounter(encoding_name="cl100k_base")

tokens = counter.count("Hello, world!")
```

### Custom Prompt Sources

```python
from nexus3.context.prompt_loader import FilePromptSource, PromptLoader
from pathlib import Path

# Custom personal sources
sources = [
    FilePromptSource(Path("/custom/path/NEXUS.md")),
    FilePromptSource(Path.home() / ".nexus3" / "NEXUS.md"),
]

loader = PromptLoader(personal_sources=sources)
result = loader.load()
print(f"Personal from: {result.personal_path}")
print(f"Project from: {result.project_path}")
```

### HTTP Server Mode

```python
# Load prompts for HTTP server (different system info)
loader = PromptLoader()
result = loader.load(is_repl=False)  # Mode: HTTP JSON-RPC Server
```

### With Session Logger

```python
from nexus3.context import ContextManager, ContextConfig
from nexus3.session import SessionLogger

# Create with logger for automatic context logging
logger = SessionLogger(log_config)
context = ContextManager(
    config=ContextConfig(),
    logger=logger,
)

# Messages are automatically logged
context.set_system_prompt("You are helpful.")  # Logged
context.add_user_message("Hello!")              # Logged
```

### With AgentPool (Multi-Agent)

```python
from nexus3.rpc.pool import AgentPool, SharedComponents, AgentConfig

# Create shared components
shared = SharedComponents(
    config=config,
    provider=provider,
    prompt_loader=PromptLoader(),
    base_log_dir=Path(".nexus3/logs"),
)
pool = AgentPool(shared)

# Create agent (gets its own ContextManager)
agent = await pool.create(agent_id="worker-1")

# Access agent's context
usage = agent.context.get_token_usage()
messages = agent.context.messages  # Read-only copy

# Create agent with custom system prompt
custom_agent = await pool.create(
    config=AgentConfig(
        agent_id="custom-worker",
        system_prompt="You are a specialized assistant.",
    )
)
```

## Module Exports

The `__init__.py` exports:

```python
__all__ = [
    # Compaction
    "CompactionResult",
    "build_summarize_prompt",
    "create_summary_message",
    "select_messages_for_compaction",
    # Prompt loading
    "LoadedPrompt",
    "PromptLoader",
    # Token counting
    "TokenCounter",
    "SimpleTokenCounter",
    "TiktokenCounter",
    "get_token_counter",
    # Context management
    "ContextManager",
    "ContextConfig",
]
```

Note: `FilePromptSource`, `PromptSource`, and `get_system_info` are available via direct import from `nexus3.context.prompt_loader`.

## Context Synchronization

When truncation occurs, `_messages` is automatically synchronized with what's sent to the API:

```python
def _get_context_messages(self) -> list[Message]:
    if not self.is_over_budget():
        return self._messages.copy()

    # Apply truncation
    truncated = self._truncate_oldest_first()  # or middle_out

    # Sync _messages with what we're sending
    self._messages = truncated

    return truncated
```

**Behavior:** The in-memory `_messages` list always reflects what the LLM actually sees. Orphaned messages (those truncated out of context) are discarded. The SQLite log retains the complete history for auditing.

**Design principle:** Think in terms of context, not memory. What's in `_messages` equals what's in the LLM's context window.
