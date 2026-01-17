# NEXUS3 Context Module

Context management: layered prompts, conversation history, token budgets, truncation/compaction, structured building.

## Purpose
Comprehensive context for NEXUS3 agents/sessions:
- Layered loading (global/ancestor/local: NEXUS.md, README.md, config.json, mcp.json)
- Conversation tracking (messages, tools, timestamps)
- Token management (tiktoken/simple, budgets, truncation strategies)
- LLM compaction for long histories
- Structured prompts with safe dynamic injection (date/time, env)

## Key Classes/Functions
**Public API** (`from nexus3.context import *`):
```
Compaction: CompactionResult, build_summarize_prompt, create_summary_message, select_messages_for_compaction
Loader: ContextLayer, ContextLoader, ContextSources, LoadedContext, MCPServerWithOrigin, PromptSource, get_system_info, deep_merge
Manager: ContextManager, ContextConfig, inject_datetime_into_prompt
Prompts: EnvironmentBlock, PromptBuilder, PromptSection, StructuredPrompt
Tokens: TokenCounter, SimpleTokenCounter, TiktokenCounter, get_token_counter
```

| File | Purpose |
|------|---------|
| compaction.py | LLM summarization |
| loader.py | Layered loading/merging |
| manager.py | Runtime state/truncation |
| prompt_builder.py | Typed prompt construction |
| token_counter.py | Pluggable counters |

## Usage Examples

### 1. Load & Initialize
```python
from nexus3.context import ContextLoader, ContextManager, ContextConfig, get_token_counter
loader = ContextLoader()
ctx = loader.load(is_repl=True)
mgr = ContextManager(ContextConfig(), get_token_counter())
mgr.set_system_prompt(ctx.system_prompt)
```

### 2. Conversation Loop
```python
mgr.add_session_start_message()
mgr.add_user_message("Hello!")
mgr.set_tool_definitions(tools)  # optional
messages = mgr.build_messages()  # auto-truncate + inject date/time
tools_call = mgr.get_tool_definitions()
usage = mgr.get_token_usage()
```

### 3. Compaction (if over budget)
```python
from nexus3.context.compaction import *
if mgr.is_over_budget():
    to_sum, to_preserve = select_messages_for_compaction(
        mgr.messages, mgr.token_counter, 6000, 0.25
    )
    # summary = llm(build_summarize_prompt(to_sum)).content
    # mgr.apply_compaction(create_summary_message(summary), to_preserve)
```

### 4. Structured Prompts
```python
from nexus3.context import PromptBuilder, EnvironmentBlock
from pathlib import Path
from datetime import datetime

env = EnvironmentBlock(
    cwd=Path.cwd(),
    os_info="Linux (WSL2)",
    datetime_str=f"Current date: {datetime.now().strftime('%Y-%m-%d')}, Current time: {datetime.now().strftime('%H:%M')} (local)"
)
prompt = PromptBuilder().add_section("Config", "Instructions").set_environment(env).build()
print(prompt.render_compat())  # loader-compatible format
```

## Status
✅ Production-ready. Updated: 2026-01-17