# NEXUS3 Context Module

Context management for NEXUS3: layered system prompt loading, conversation history, token budgets, truncation, and LLM-based compaction.

## Purpose

This module provides comprehensive context management for NEXUS3 agents and sessions:

- **Layered system prompt loading**: Global (~/.nexus3/), ancestor projects, local (.nexus3/) with merging and labeling.
- **Conversation state**: Tracks messages (user, assistant, tool results) with session timestamps.
- **Token budgeting**: Pluggable counters (tiktoken preferred) with automatic truncation strategies.
- **Context preservation**: Truncation (`oldest_first`/`middle_out`) and LLM summarization (compaction).
- **Environment awareness**: Dynamic date/time, OS, working directory injected into prompts.

Supports both REPL (single ContextManager) and HTTP server (per-agent ContextManagers).

## Files & Key Exports

| File | Key Classes/Functions | Purpose |
|------|-----------------------|---------|
| `__init__.py` | All public API via `__all__` | Module entrypoint |
| `compaction.py` | `CompactionResult`, `select_messages_for_compaction`, `build_summarize_prompt`, `create_summary_message` | LLM summarization of old context |
| `loader.py` | `ContextLoader`, `LoadedContext`, `ContextLayer`, `ContextSources`, `get_system_info` | Multi-layer prompt/config loading |
| `manager.py` | `ContextManager`, `ContextConfig` | Runtime context building/truncation |
| `token_counter.py` | `TokenCounter` (protocol), `SimpleTokenCounter`, `TiktokenCounter`, `get_token_counter` | Accurate token estimation |

**Public API** (`from nexus3.context import *`):
```
Compaction: CompactionResult, build_summarize_prompt, create_summary_message, select_messages_for_compaction
Loader: ContextLayer, ContextLoader, ContextSources, LoadedContext, MCPServerWithOrigin, PromptSource, get_system_info, deep_merge
Manager: ContextManager, ContextConfig
Tokens: TokenCounter, SimpleTokenCounter, TiktokenCounter, get_token_counter
```

## Architecture

### 1. Loading Layers (ContextLoader)
```
Global (~/.nexus3/ or defaults/)
  ↓ (deep_merge configs, labeled sections)
Ancestors (.nexus3/ dirs up dir tree)
  ↓
Local (cwd/.nexus3/)

Files per layer: NEXUS.md (prompt), README.md (fallback), config.json, mcp.json
→ LoadedContext(system_prompt, merged_config, mcp_servers, sources)
```

**Prompt merging**: Headers + sources + "# Environment" (OS, cwd, mode).

**Subagents**: `load_for_subagent()` prepends local NEXUS.md to parent context.

### 2. Runtime (ContextManager)
```
ContextManager(config, token_counter)
├── set_system_prompt(loaded.system_prompt)
├── set_tool_definitions(tools)
├── add_user_message() / add_assistant_message() / add_tool_result()
├── build_messages() → [SYSTEM, MESSAGES] (truncates if needed)
├── get_token_usage() → {system, tools, messages, total, budget, available}
└── apply_compaction(summary, preserved) → Replaces history
```

**Token budget**: `max_tokens - reserve_tokens` (default 8000-2000=6000).

**Temporal context**:
- Dynamic: Current date/time injected per `build_messages()`.
- Fixed: `[Session started: ...]` first message.
- Compaction: `[CONTEXT SUMMARY - Generated: ...]`.

### 3. Token Management
```
get_token_counter() → TiktokenCounter (if installed) or SimpleTokenCounter
- count(text)
- count_messages([Message])  # Includes tool_calls JSON overhead
```

### 4. Truncation (atomic groups)
```
Messages grouped: standalone | ASSISTANT(tool_calls) + TOOL results
Strategies:
- oldest_first: Keep newest groups back-to-front
- middle_out: Keep first + last + newest middle
```
`_messages` synced to truncated view (log keeps full history).

### 5. Compaction Flow
```
if over_budget:
  to_summarize, to_preserve = select_messages_for_compaction(..., ratio=0.25)
  summary = llm(build_summarize_prompt(to_summarize))
  context.apply_compaction(create_summary_message(summary), to_preserve)
```

## Dependencies

**Internal**:
- `nexus3.core.*`: `Message`, `Role`, `ToolCall`, `ToolResult`, `utils`, `constants`
- `nexus3.config.schema`: `ContextConfig` (pydantic), `MCPServerConfig`

**External (optional)**:
- `tiktoken`: Accurate counting (fallback to simple ~4chars/token)

**Stdlib**: `dataclasses`, `datetime`, `json`, `os`, `pathlib`, `platform`, `typing`

## Usage Examples

### 1. Load Context (REPL/Server)
```python
from nexus3.context import ContextLoader
from pathlib import Path

loader = ContextLoader(cwd=Path.cwd())
ctx = loader.load(is_repl=True)  # Includes terminal info
print(ctx.system_prompt)  # Merged + labeled + "# Environment"

# Access merged config/MCP
config = ctx.merged_config
mcp_servers = ctx.mcp_servers
```

**Subagent**:
```python
sub_prompt = loader.load_for_subagent(parent_ctx)
```

### 2. ContextManager (Basic)
```python
from nexus3.context import ContextManager, ContextConfig, get_token_counter

config = ContextConfig(max_tokens=16000, truncation_strategy="middle_out")
mgr = ContextManager(config, token_counter=get_token_counter())
mgr.set_system_prompt(ctx.system_prompt)

mgr.add_session_start_message()  # [Session started: ...]
mgr.add_user_message("Hello!")
mgr.add_assistant_message("Hi!", tool_calls=[...])

# For API call
messages = mgr.build_messages()  # SYSTEM + truncated messages
tools = mgr.get_tool_definitions()
usage = mgr.get_token_usage()
```

### 3. Check/Trigger Compaction
```python
if mgr.is_over_budget():
    from nexus3.context.compaction import select_messages_for_compaction
    counter = mgr._counter  # Or get_token_counter()
    to_sum, to_preserve = select_messages_for_compaction(
        mgr.messages, counter, 6000, recent_preserve_ratio=0.25
    )
    # summary = llm(build_summarize_prompt(to_sum)).content
    # result = CompactionResult(create_summary_message(summary), to_preserve, ...)
    # mgr.apply_compaction(result.summary_message, result.preserved_messages)
```

### 4. Per-Agent (AgentPool Integration)
```python
# In nexus3/rpc/pool.py (excerpt)
context = ContextManager(ContextConfig())
context.set_system_prompt(shared.loader.load(is_repl=False).system_prompt)
context.set_tool_definitions(registry.get_definitions())
```

## Integration Points

- **REPL** (`cli/repl.py`): Single `ContextManager` for session.
- **AgentPool** (`rpc/pool.py`): One `ContextManager` per agent (isolated history).
- **Session/Dispatcher**: Use `context.build_messages()` for API calls.
- **Compaction trigger**: Call before `build_messages()` if `is_over_budget()`.

## Status
✅ Complete & production-ready across all components.

Updated: 2026-01-15