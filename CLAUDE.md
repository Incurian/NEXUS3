# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Phase 10 complete. Multi-provider support with factory pattern.

---

## DOGFOODING: Use NEXUS3 Subagents

**IMPORTANT:** When working on this codebase, use NEXUS3 subagents for research and exploration tasks instead of Claude Code's built-in Task tool. This is dogfooding - we use our own product.

```bash
# Start server if not running
nexus-rpc detect || nexus --serve &

# Create a subagent for research
nexus-rpc create researcher

# Send research tasks
nexus-rpc send researcher "Look at nexus3/rpc/ and summarize the JSON-RPC types"

# Check status
nexus-rpc status researcher

# Clean up when done
nexus-rpc destroy researcher
```

**Guidelines:**
- Use subagents widely for reading/research tasks
- If subagents write code, verify their work until confident in their ability
- Note any errors subagents make so we can fix issues on our end
- Subagents help manage context window and provide real-world testing

---

## Phases Complete

| Phase | Features |
|-------|----------|
| **0 - Core** | Message/ToolCall/ToolResult types, Config loader (Pydantic), AsyncProvider + OpenRouter, UTF-8 everywhere |
| **1 - Display** | Rich.Live streaming, ESC cancellation, Activity phases, Slash commands, Status bar |
| **1.5 - Logging** | SQLite + Markdown logs, `--verbose`, `--raw-log`, `--log-dir`, Subagent nesting |
| **2 - Context** | Multi-turn conversations, Token tracking (tiktoken), Truncation strategies, System prompt loading, HTTP JSON-RPC |
| **3 - Skills** | Skill system with DI, Built-in: read_file/write_file/sleep/nexus_*, Tool execution loop, 8 session callbacks |
| **4 - Multi-Agent** | AgentPool, GlobalDispatcher, path-based routing, `--connect` mode, NexusClient |
| **5R - Security** | API key auth, server detection, path sandbox (infra), URL validator (infra), JSON injection fix, provider retry |
| **6 - Sessions** | Persistence, lobby mode, whisper mode, unified commands, agent naming, auto-restore, permission types |
| **7 - Integration** | Sandbox → file skills, URL validation → nexus skills, async I/O, skill timeout, concurrency limit, truncation fix |
| **8 - Permissions** | Permission presets (yolo/trusted/sandboxed/worker), per-tool config, deltas, ceiling inheritance, confirmation prompts |
| **8+ - Compaction** | LLM-based context compaction, system prompt reloading, `/compact` command, configurable thresholds |
| **9 - Context Mgmt** | Layered context loading (global→ancestors→local), subagent inheritance, deep config merge, `/init` command, `--init-global` |
| **10 - Providers** | Multi-provider factory (openrouter/openai/azure/anthropic/ollama/vllm), configurable auth, provider README with extension guide |

---

## Architecture

```
nexus3/
├── core/           # Types, interfaces, errors, encoding, paths, URL validation, permissions
├── config/         # Pydantic schema, permission config, fail-fast loader
├── provider/       # AsyncProvider protocol, OpenRouter implementation, retry logic
├── context/        # ContextManager, PromptLoader, TokenCounter, atomic truncation
├── session/        # Session coordinator, persistence, SessionManager, SQLite logging
├── skill/          # Skill protocol, SkillRegistry, ServiceContainer, builtin skills
├── display/        # DisplayManager, StreamingDisplay, InlinePrinter, SummaryBar, theme
├── cli/            # Unified REPL, lobby, whisper, HTTP server, client commands
├── rpc/            # JSON-RPC protocol, Dispatcher, GlobalDispatcher, AgentPool, auth
└── client.py       # NexusClient for agent-to-agent communication
```

Each module has a `README.md` with detailed documentation.

---

## Multi-Agent Server

### Architecture

```
nexus3 --serve
├── SharedComponents (config, provider, prompt_loader)
├── AgentPool
│   ├── Agent "main" → Session, Context, Dispatcher
│   └── Agent "worker" → Session, Context, Dispatcher
└── HTTP Server
    ├── POST /           → GlobalDispatcher (create/list/destroy)
    └── POST /agent/{id} → Agent's Dispatcher (send/cancel/etc)
```

### API

```bash
# Global methods (POST /)
{"method": "create_agent", "params": {"agent_id": "worker-1"}}
{"method": "create_agent", "params": {"agent_id": "worker-1", "preset": "sandboxed"}}
{"method": "create_agent", "params": {"agent_id": "worker-1", "preset": "trusted", "disable_tools": ["write_file"]}}
{"method": "list_agents"}
{"method": "destroy_agent", "params": {"agent_id": "worker-1"}}
{"method": "shutdown_server"}

# Agent methods (POST /agent/{id})
{"method": "send", "params": {"content": "Hello"}}
{"method": "cancel", "params": {"request_id": "..."}}
{"method": "get_tokens"}
{"method": "get_context"}
{"method": "shutdown"}
```

### Component Sharing

| Shared | Per-Agent |
|--------|-----------|
| Config | SessionLogger |
| Provider | ContextManager |
| PromptLoader | ServiceContainer |
| Base log directory | SkillRegistry, Session, Dispatcher |

---

## CLI Modes

```bash
# Unified REPL (auto-starts embedded server)
nexus                    # Default: lobby mode for session selection
nexus --fresh            # Skip lobby, start new temp session
nexus --resume           # Resume last session
nexus --session NAME     # Load specific saved session
nexus --template PATH    # Use custom system prompt

# HTTP server (headless multi-agent)
nexus --serve [PORT]

# Client mode (connect to existing server)
nexus --connect [URL] --agent [ID]

# RPC commands (see "NEXUS3 Command Aliases" below for full list)
nexus-rpc create worker-1
nexus-rpc send worker-1 "Hello"
nexus-rpc shutdown
```

---

## Built-in Skills

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path`, `offset`?, `limit`? | Read file contents (with optional line range) |
| `tail` | `path`, `lines`? | Read last N lines of a file (default: 10) |
| `file_info` | `path` | Get file/directory metadata (size, mtime, permissions) |
| `write_file` | `path`, `content` | Write/create files |
| `edit_file` | `path`, `old_string`, `new_string` | Edit files with string replacement |
| `append_file` | `path`, `content`, `newline`? | Append content to a file |
| `regex_replace` | `path`, `pattern`, `replacement`, `count`?, `ignore_case`?, `multiline`?, `dotall`? | Pattern-based find/replace in files |
| `list_directory` | `path` | List directory contents |
| `glob` | `pattern`, `path`?, `exclude`? | Find files matching glob pattern (with exclusions) |
| `grep` | `pattern`, `path`?, `include`?, `context`? | Search file contents with file filter and context lines |
| `git` | `command`, `cwd`? | Execute git commands (permission-filtered by level) |
| `bash` | `command`, `timeout`? | Execute shell commands |
| `run_python` | `code`, `timeout`? | Execute Python code |
| `sleep` | `seconds`, `label`? | Pause execution (for testing) |
| `nexus_create` | `agent_id`, `preset`?, `disable_tools`?, `cwd`?, `model`?, `initial_message`? | Create agent and optionally send initial message |
| `nexus_destroy` | `agent_id`, `port`? | Remove an agent (server keeps running) |
| `nexus_send` | `agent_id`, `content`, `port`? | Send message to an agent |
| `nexus_status` | `agent_id`, `port`? | Get agent tokens + context |
| `nexus_cancel` | `agent_id`, `request_id`, `port`? | Cancel in-progress request |
| `nexus_shutdown` | `port`? | Shutdown the entire server |

*Note: `port` defaults to 8765. `preset` can be trusted/sandboxed/worker (yolo is REPL-only). Skills mirror `nexus-rpc` CLI commands.*

---

## Design Principles

1. **Async-first** - asyncio throughout, not threading
2. **Fail-fast** - No silent exception swallowing
3. **Single source of truth** - One way to do each thing
4. **Minimal viable interfaces** - Small, well-typed protocols
5. **End-to-end tested** - Integration tests, not just unit tests
6. **Document as you go** - Update this file and module READMEs
7. **Unified invocation patterns** - CLI commands, NEXUS3 skills, and NexusClient methods should mirror each other. Users, Claude, and NEXUS3 agents should all use the same interface patterns (e.g., `agent_id` not URLs). This reduces cognitive load and ensures changes propagate consistently.

---

## Development SOPs

| SOP | Description |
|-----|-------------|
| Type Everything | No `Optional[Any]`. Use Protocols for interfaces. |
| Fail Fast | Errors surface immediately. No `pass`. No swallowed exceptions. |
| One Way | Features go in skills or CLI flags, not scripts. |
| Explicit Encoding | Always `encoding='utf-8', errors='replace'`. |
| Test E2E | Every feature gets an integration test. |
| Document | Each phase updates this file and module READMEs. |
| No Dead Code | Delete unused code. Run `ruff check --select F401`. |

---

## Key Interfaces

```python
# Skill Protocol
class Skill(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...
    async def execute(self, **kwargs: Any) -> ToolResult: ...

# AsyncProvider Protocol
class AsyncProvider(Protocol):
    async def complete(self, messages, tools) -> Message: ...
    def stream(self, messages, tools) -> AsyncIterator[StreamEvent]: ...
```

---

## Testing

```bash
pytest tests/ -v                              # All tests
pytest tests/integration/ -v                  # Integration only
ruff check nexus3/                            # Linting
mypy nexus3/                                  # Type checking
```

---

## NEXUS3 Command Aliases

**IMPORTANT:** When testing or demonstrating NEXUS3, always use the shell aliases, never raw `python -m nexus3` or `.venv/bin/python` invocations. The user prefers clean, natural commands.

Two aliases are installed in `~/.local/bin/`:

```bash
# Interactive modes
nexus                        # REPL with embedded server (default)
nexus --serve [PORT]         # Headless server mode
nexus --connect [URL]        # Connect to existing server

# Programmatic RPC operations
nexus-rpc detect             # Check if server is running
nexus-rpc list               # List agents (auto-starts server)
nexus-rpc create ID          # Create agent (auto-starts server)
nexus-rpc create ID -M "msg" # Create agent and send initial message
nexus-rpc destroy ID         # Destroy agent
nexus-rpc send AGENT MSG     # Send message to agent
nexus-rpc status AGENT       # Get agent status
nexus-rpc shutdown           # Stop server (graceful)
nexus-rpc cancel AGENT ID    # Cancel in-progress request
```

**Key behaviors:**
- `nexus-rpc list` and `nexus-rpc create` auto-start a server if none running
- `nexus-rpc send/status/destroy/shutdown` require server to be running
- All commands use `--port N` to specify non-default port (default: 8765)
- All commands support `--api-key KEY` for explicit authentication (auto-discovered by default)

**User preference:** Commands should be simple and clean. Avoid:
- Sourcing virtualenvs manually
- Using `python -m nexus3` directly
- Using full paths to scripts
- Any invocation that isn't `nexus` or `nexus-rpc`

---

## Configuration

```
~/.nexus3/
├── config.json      # Global config
├── NEXUS.md         # Personal system prompt
├── server.key       # Auto-generated API key (port-specific keys: server-{port}.key)
├── sessions/        # Saved session files (JSON)
└── last-session.json  # Auto-saved for --resume

./NEXUS.md           # Project system prompt (overrides personal)
.nexus3/logs/        # Session logs (gitignored)
```

### Provider Configuration

NEXUS3 supports multiple LLM providers via the `provider` config:

| Type | Description |
|------|-------------|
| `openrouter` | OpenRouter.ai (default) |
| `openai` | Direct OpenAI API |
| `azure` | Azure OpenAI Service |
| `anthropic` | Anthropic Claude API |
| `ollama` | Local Ollama server |
| `vllm` | vLLM OpenAI-compatible server |

```json
// OpenRouter (default)
{"provider": {"type": "openrouter", "model": "anthropic/claude-sonnet-4"}}

// OpenAI
{"provider": {"type": "openai", "api_key_env": "OPENAI_API_KEY", "model": "gpt-4o"}}

// Azure OpenAI
{"provider": {
  "type": "azure",
  "base_url": "https://my-resource.openai.azure.com",
  "api_key_env": "AZURE_OPENAI_KEY",
  "deployment": "gpt-4",
  "api_version": "2024-02-01"
}}

// Anthropic (native API)
{"provider": {"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-20250514"}}

// Ollama (local)
{"provider": {"type": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.2"}}
```

See `nexus3/provider/README.md` for full documentation and adding new providers.

### Compaction Config Example

```json
{
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

## Context Compaction

Context compaction summarizes old conversation history via LLM to reclaim token space while preserving essential information.

### How It Works

1. **Trigger**: Compaction runs when `used_tokens > trigger_threshold * available_tokens` (default 90%)
2. **Preserve recent**: The most recent messages (controlled by `recent_preserve_ratio`) are kept verbatim
3. **Summarize old**: Older messages are sent to a fast model (default: claude-haiku) for summarization
4. **Budget**: Summary is constrained to `summary_budget_ratio` of available tokens (default 25%)
5. **System prompt reload**: During compaction, NEXUS.md is re-read, picking up any changes

### Configuration Options (`CompactionConfig`)

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable automatic compaction |
| `model` | `"anthropic/claude-haiku"` | Model for summarization |
| `summary_budget_ratio` | `0.25` | Max tokens for summary (fraction of available) |
| `recent_preserve_ratio` | `0.25` | Recent messages to preserve (fraction of available) |
| `trigger_threshold` | `0.9` | Trigger when usage exceeds this fraction |

### Commands

```bash
/compact              # Manual compaction (even if below threshold)
```

### Key Benefits

- **Longer sessions**: Reclaim space without losing context
- **System prompt updates**: Changes to NEXUS.md apply on next compaction
- **Configurable**: Tune thresholds for your use case

---

## Context Management (Phase 9)

Context is loaded from multiple directory layers and merged together. Each layer extends the previous one.

### Layer Hierarchy

```
LAYER 1: Install Defaults (shipped with package)
    ↓
LAYER 2: Global (~/.nexus3/)
    ↓
LAYER 3: Ancestors (up to N levels above CWD, default 2)
    ↓
LAYER 4: Local (CWD/.nexus3/)
```

### Directory Structure

```
~/.nexus3/                    # Global (user defaults)
├── NEXUS.md                  # Personal system prompt
├── config.json               # Personal configuration
└── mcp.json                  # Personal MCP servers

./parent/.nexus3/             # Ancestor (1 level up)
├── NEXUS.md
└── config.json

./.nexus3/                    # Local (CWD)
├── NEXUS.md                  # Project-specific prompt
├── config.json               # Project config overrides
└── mcp.json                  # Project MCP servers
```

### Configuration Merging

- **Configs**: Deep merged (local keys override global, unspecified keys preserved)
- **NEXUS.md**: All layers included with labeled sections
- **MCP servers**: Same name = local wins

### Subagent Context Inheritance

Subagents created with `cwd` parameter get:
1. Their cwd's NEXUS.md (if exists)
2. Parent's context (non-redundantly)

### Init Commands

```bash
# Initialize global config
nexus --init-global           # Create ~/.nexus3/ with defaults
nexus --init-global-force     # Overwrite existing

# Initialize local config (REPL)
/init                         # Create ./.nexus3/ with templates
/init --force                 # Overwrite existing
/init --global                # Initialize ~/.nexus3/ instead
```

### New Config Options

```json
{
  "context": {
    "ancestor_depth": 2,       // How many parent dirs to check (0-10)
    "include_readme": false,   // Always include README.md
    "readme_as_fallback": true // Use README when no NEXUS.md
  }
}
```

---

## Permission System

### Built-in Presets

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations |
| `trusted` | TRUSTED | Confirmations for destructive actions (default) |
| `sandboxed` | SANDBOXED | Limited to CWD, no network, nexus tools disabled |
| `worker` | SANDBOXED | Minimal: no write_file, no agent management |

### Key Features

- **Per-tool configuration**: Enable/disable tools, per-tool paths, per-tool timeouts
- **Permission presets**: Named configurations loaded from config or built-in
- **Ceiling inheritance**: Subagents cannot exceed parent permissions
- **Confirmation prompts**: TRUSTED mode prompts for destructive actions in REPL

### Commands

```bash
/permissions              # Show current permissions
/permissions trusted      # Change preset (within ceiling)
/permissions --disable write_file   # Disable a tool
/permissions --list-tools           # List tool status
```

---

## TODO / Future Work

- [ ] **Portable auto-bootstrap launcher**: Add a launcher script that auto-installs deps (httpx, pydantic, rich, prompt-toolkit, python-dotenv) on first run, enabling "copy folder and go" portability without manual pip install. See packaging investigation for options (shiv/zipapp as alternative).

---

## Known Issues

- ~~**WSL Terminal**: Bash may close after `nexus` exits.~~ Fixed in d276c70.
