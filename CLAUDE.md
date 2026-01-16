# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Feature-complete. Multi-provider support, permission system, MCP integration, context compaction.

---

## DOGFOODING: Use NEXUS3 Subagents

**IMPORTANT:** When working on this codebase, use NEXUS3 subagents for research and exploration tasks instead of Claude Code's built-in Task tool. This is dogfooding - we use our own product.

```bash
# Start server if not running
# Start REPL if not already running (server is embedded)
# Note: --serve is disabled by default (requires NEXUS_DEV=1)
nexus &

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

## Architecture

```
nexus3/
├── core/           # Types, interfaces, errors, encoding, paths, URL validation, permissions
├── config/         # Pydantic schema, permission config, fail-fast loader
├── provider/       # AsyncProvider protocol, multi-provider support, retry logic
├── context/        # ContextManager, ContextLoader, TokenCounter, compaction
├── session/        # Session coordinator, persistence, SessionManager, SQLite logging
├── skill/          # Skill protocol, SkillRegistry, ServiceContainer, 23 builtin skills
├── display/        # DisplayManager, StreamingDisplay, InlinePrinter, SummaryBar, theme
├── cli/            # Unified REPL, lobby, whisper, HTTP server, client commands
├── rpc/            # JSON-RPC protocol, Dispatcher, GlobalDispatcher, AgentPool, auth
├── mcp/            # Model Context Protocol client, external tool integration
├── commands/       # Unified command infrastructure for CLI and REPL
├── defaults/       # Default configuration and system prompts
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
# Unified REPL (auto-starts embedded server with 30-min idle timeout)
nexus                    # Default: lobby mode for session selection
nexus --fresh            # Skip lobby, start new temp session
nexus --resume           # Resume last session
nexus --session NAME     # Load specific saved session
nexus --template PATH    # Use custom system prompt

# HTTP server (headless, dev-only - requires NEXUS_DEV=1)
NEXUS_DEV=1 nexus --serve [PORT]

# Client mode (connect to existing server)
nexus --connect [URL] --agent [ID]

# RPC commands (require server to be running - no auto-start)
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
| `write_file` | `path`, `content` | Write/create files (read file first!) |
| `edit_file` | `path`, `old_string`, `new_string` | Edit files with string replacement (read file first!) |
| `append_file` | `path`, `content`, `newline`? | Append content to a file (read file first!) |
| `regex_replace` | `path`, `pattern`, `replacement`, `count`?, `ignore_case`?, `multiline`?, `dotall`? | Pattern-based find/replace (read file first!) |
| `copy_file` | `source`, `destination`, `overwrite`? | Copy a file to a new location |
| `mkdir` | `path` | Create directory (and parents) |
| `rename` | `source`, `destination`, `overwrite`? | Rename or move file/directory |
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

*Note: `port` defaults to 8765. `preset` can be trusted/sandboxed/worker (yolo is REPL-only). Skills mirror `nexus-rpc` CLI commands. Destructive file tools remind agents to read files before modifying.*

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
| **Live Test** | **Automated tests are not sufficient. Always live test with real NEXUS3 agents before committing changes.** |
| Document | Each phase updates this file and module READMEs. |
| No Dead Code | Delete unused code. Run `ruff check --select F401`. |

### Live Testing Requirement (MANDATORY)

**Automated tests alone are NOT sufficient to commit changes.** Before any commit that affects agent behavior, RPC, skills, or permissions:

1. Start the server: `nexus &`
2. Create a test agent: `nexus-rpc create test-agent`
3. Send test messages: `nexus-rpc send test-agent "describe your permissions and what you can do"`
4. Verify the agent responds correctly and has expected capabilities
5. Clean up: `nexus-rpc destroy test-agent`

This catches issues that unit/integration tests miss, such as:
- Permission configuration not propagating correctly
- Agent tools being incorrectly enabled/disabled
- RPC message handling edge cases
- Real-world serialization/deserialization issues

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

**IMPORTANT: Always use the virtualenv Python.** The system `python` command may not exist or may be a different version. All Python commands must use `.venv/bin/python` or `.venv/bin/pytest`:

```bash
# Tests (use .venv/bin/pytest or .venv/bin/python -m pytest)
.venv/bin/pytest tests/ -v                    # All tests
.venv/bin/pytest tests/integration/ -v        # Integration only
.venv/bin/pytest tests/security/ -v           # Security tests

# Linting/Type checking
.venv/bin/ruff check nexus3/                  # Linting
.venv/bin/mypy nexus3/                        # Type checking

# Running Python directly
.venv/bin/python -c "import nexus3; print(nexus3.__version__)"
```

**Never use bare `python` or `pytest` commands** - they will likely fail with "command not found" or use the wrong Python version.

---

## NEXUS3 Command Aliases

**IMPORTANT:** When testing or demonstrating NEXUS3, always use the shell aliases, never raw `python -m nexus3` or `.venv/bin/python` invocations. The user prefers clean, natural commands.

Two aliases are installed in `~/.local/bin/`:

```bash
# Interactive modes
nexus                        # REPL with embedded server (default)
NEXUS_DEV=1 nexus --serve [PORT]  # Headless server (dev-only)
nexus --connect [URL]             # Connect to existing server

# Programmatic RPC operations (require server running)
nexus-rpc detect             # Check if server is running
nexus-rpc list               # List agents
nexus-rpc create ID          # Create agent
nexus-rpc create ID -M "msg" # Create agent and send initial message
nexus-rpc destroy ID         # Destroy agent
nexus-rpc send AGENT MSG     # Send message to agent
nexus-rpc status AGENT       # Get agent status
nexus-rpc shutdown           # Stop server (graceful)
nexus-rpc cancel AGENT ID    # Cancel in-progress request
```

**Key behaviors:**
- **Security:** `--serve` requires `NEXUS_DEV=1` env var (prevents unattended servers)
- **Security:** `nexus-rpc` commands do NOT auto-start servers (start `nexus` manually)
- **Idle timeout:** Embedded server auto-shuts down after 30 min of no RPC activity
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
├── rpc.token        # Auto-generated RPC token (port-specific: rpc-{port}.token)
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

### Server Config Example

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8765,
    "log_level": "INFO"
  }
}
```

### Provider Timeout/Retry Config

```json
{
  "provider": {
    "type": "openrouter",
    "request_timeout": 120.0,
    "max_retries": 3,
    "retry_backoff": 1.5
  }
}
```

### Multi-Provider Configuration

NEXUS3 supports multiple simultaneous providers with named references:

```json
{
  "providers": {
    "openrouter": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY",
      "base_url": "https://openrouter.ai/api/v1"
    },
    "anthropic": {
      "type": "anthropic",
      "api_key_env": "ANTHROPIC_API_KEY"
    },
    "local": {
      "type": "ollama",
      "base_url": "http://localhost:11434/v1"
    }
  },
  "default_provider": "openrouter",

  "models": {
    "oss": { "id": "openai/gpt-oss-120b", "context_window": 131072 },
    "haiku": { "id": "anthropic/claude-haiku-4.5", "context_window": 200000 },
    "haiku-native": { "id": "claude-haiku-4.5", "provider": "anthropic", "context_window": 200000 },
    "llama": { "id": "llama3.2", "provider": "local", "context_window": 128000 }
  }
}
```

**Key concepts:**
- `providers`: Named provider configs, define once and reference by name
- `default_provider`: Which provider to use when model doesn't specify one
- `models[].provider`: Optional - reference a named provider (falls back to default)
- Backwards compatible: `provider` field still works for single-provider setups

**Implementation (ProviderRegistry):**
- Lazy initialization: Providers created on first use (avoids connecting to unused APIs)
- Per-model routing: `resolve_model()` returns provider name alongside model settings
- SharedComponents holds registry instead of single provider

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
- **Timestamped summaries**: Each summary includes when it was generated
- **Configurable**: Tune thresholds for your use case

---

## Temporal Context

Agents always have accurate temporal awareness through three timestamp mechanisms:

| Timestamp | When Set | Location | Purpose |
|-----------|----------|----------|---------|
| **Current date/time** | Every request | System prompt | Always accurate - agents know "now" |
| **Session start** | Agent creation | First message in history | Marks when session began |
| **Compaction** | On summary | Summary prefix | Indicates when history was summarized |

Example session start message:
```
[Session started: 2026-01-13 14:30 (local)]
```

Example compaction summary header:
```
[CONTEXT SUMMARY - Generated: 2026-01-13 16:45]
```

---

## Context Management

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

### Context Config Options

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

### RPC Agent Permission Quirks (IMPORTANT)

**These behaviors are intentional security defaults for RPC-created agents:**

1. **Default agent is sandboxed**: When creating agents via RPC without specifying a preset, they default to `sandboxed` (NOT `trusted`). This is intentional - programmatic agents should be least-privileged by default.

2. **Sandboxed agents can only read in their cwd**: A sandboxed agent's `allowed_paths` is set to `[cwd]` only. They cannot read files outside their working directory.

3. **Sandboxed agents cannot write unless given explicit write paths**: By default, sandboxed agents have all write tools (`write_file`, `edit_file`, `append_file`, `regex_replace`, etc.) **disabled**. To enable writes, you must pass `allowed_write_paths` on creation:
   ```bash
   nexus-rpc create worker --cwd /tmp/sandbox --allowed-write-paths /tmp/sandbox
   ```

4. **Trusted agents must be created explicitly**: To get a trusted agent, you must pass `--preset trusted` explicitly. Trusted is not the default for RPC.

5. **Trusted agents in RPC mode**: Can read anywhere, but destructive operations follow the same confirmation logic (which auto-allows within CWD in non-interactive mode).

6. **YOLO is REPL-only**: You CANNOT create a yolo agent via RPC. The yolo preset is only available in interactive REPL mode.

7. **Trusted agents can only create sandboxed subagents**: A trusted agent cannot spawn another trusted agent - all subagents are sandboxed (ceiling enforcement).

8. **Sandboxed agents cannot create agents at all**: The `nexus_create`, `nexus_destroy`, `nexus_send`, and other nexus tools are completely disabled for sandboxed agents.

**Example secure agent creation:**
```bash
# Read-only agent (default) - can only read in its cwd
nexus-rpc create reader --cwd /path/to/project

# Agent with write access to specific directory
nexus-rpc create writer --cwd /path/to/project --allowed-write-paths /path/to/project/output

# Trusted agent (explicit - use with care)
nexus-rpc create coordinator --preset trusted
```

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

## Deferred Work

### Structural Refactors

| Issue | Reason | Effort |
|-------|--------|--------|
| Repl.py split (1661 lines) | Large refactor | L |
| Session.py split (842 lines) | Large refactor | M |
| Pool.py split (880 lines) | Large refactor | M |
| Display config | Polish, no current need | S |
| Windows ESC key | No Windows users yet | S |
| HTTP keep-alive | Advanced feature | M |

### DRY Cleanups

| Pattern | Notes |
|---------|-------|
| Dispatcher error handling | `dispatcher.py` and `global_dispatcher.py` have identical try/except blocks |
| HTTP error send | `http.py` has 9 similar `make_error_response()` + `send_http_response()` calls |
| ToolResult file errors | 22 skill files with repeated error handlers |
| Git double timeout | `subprocess.run(timeout)` + `asyncio.wait_for()` is redundant |

---

## Skill Type Hierarchy

Skills are organized into base classes that provide shared infrastructure for common patterns. Each base class handles boilerplate so individual skills focus on their unique logic.

### Hierarchy Overview

```
Skill (Protocol)
├── BaseSkill         # Minimal abstract base (name, description, parameters, execute)
├── FileSkill         # Path validation + per-tool allowed_paths resolution via ServiceContainer
├── NexusSkill        # Server communication (port discovery, client management)
├── ExecutionSkill    # Subprocess execution (timeout, output formatting)
└── FilteredCommandSkill  # Permission-based command filtering + per-tool allowed_paths
```

### Base Classes

| Base Class | Purpose | Skills Using It |
|------------|---------|-----------------|
| `FileSkill` | Path validation, symlink resolution, allowed_paths | read_file, write_file, edit_file, append_file, tail, file_info, list_directory, mkdir, copy_file, rename, regex_replace, glob, grep |
| `NexusSkill` | Server URL building, API key discovery, client error handling | nexus_create, nexus_destroy, nexus_send, nexus_status, nexus_cancel, nexus_shutdown |
| `ExecutionSkill` | Timeout enforcement, working dir resolution, output formatting | bash, run_python |
| `FilteredCommandSkill` | Read-only command filtering, blocked pattern matching | git |

### Creating New Skills

**File operations** - inherit `FileSkill`:
```python
class MyFileSkill(FileSkill):
    async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        validated = self._validate_path(path)  # Returns Path or ToolResult error
        if isinstance(validated, ToolResult):
            return validated
        # Use validated path...

my_file_skill_factory = file_skill_factory(MyFileSkill)
```

**Server communication** - inherit `NexusSkill`:
```python
class MyNexusSkill(NexusSkill):
    async def execute(self, agent_id: str = "", port: int | None = None, **kwargs: Any) -> ToolResult:
        return await self._execute_with_client(
            port=port,
            agent_id=agent_id,
            operation=lambda client: client.some_method()
        )

my_nexus_skill_factory = nexus_skill_factory(MyNexusSkill)
```

**Subprocess execution** - inherit `ExecutionSkill`:
```python
class MyExecSkill(ExecutionSkill):
    async def _create_process(self, work_dir: str | None) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(...)

    async def execute(self, timeout: int = 30, cwd: str | None = None, **kwargs: Any) -> ToolResult:
        return await self._execute_subprocess(timeout=timeout, cwd=cwd, timeout_message="...")

my_exec_skill_factory = execution_skill_factory(MyExecSkill)
```

**Command filtering** (e.g., docker, kubectl) - inherit `FilteredCommandSkill`:
```python
class MyFilteredSkill(FilteredCommandSkill):
    def get_read_only_commands(self) -> frozenset[str]:
        return frozenset({"ps", "logs", "inspect"})

    def get_blocked_patterns(self) -> list[tuple[str, str]]:
        return [("rm\\s+-f", "force remove is dangerous")]

my_filtered_skill_factory = filtered_command_skill_factory(MyFilteredSkill)
```

**Utility/special logic** - inherit `BaseSkill` directly (catch-all for unique skills):
```python
class MySpecialSkill(BaseSkill):
    async def execute(self, **kwargs: Any) -> ToolResult:
        # Custom logic without shared infrastructure
        ...
```

---

## TODO / Future Work

- [ ] **Portable auto-bootstrap launcher**: Add a launcher script that auto-installs deps (httpx, pydantic, rich, prompt-toolkit, python-dotenv) on first run, enabling "copy folder and go" portability without manual pip install. See packaging investigation for options (shiv/zipapp as alternative).

- [ ] **RPC `compact` method for stuck agents**: When an agent's context exceeds the provider's token/byte limit, the agent becomes stuck (alive but unusable). Need either: (a) RPC method to trigger compaction manually, (b) pre-flight context size check before API calls to auto-compact, or (c) automatic recovery after provider limit errors. Discovered during P2.5 testing - agent accumulated 3.5M tokens, exceeded 2M budget, all subsequent messages fail.

---

## Security Review (2026-01-15)

A comprehensive code review by 7 GPT-5.2 agents identified critical and high-priority issues. Full details in `reviews/MASTER-PLAN.md`.

### Critical (P0) - Fix Before Deployment

| Issue | Location | Summary |
|-------|----------|---------|
| **Deserialization privilege escalation** | `policy.py:374-378`, `presets.py:55-59` | `allowed_paths=[]` becomes `None` (unrestricted) after JSON roundtrip |
| **Token leakage on --connect** | `repl.py:1493-1514` | Auto-auth sends local token to remote URLs |
| **Subprocess env leaks secrets** | `bash.py:99-105`, `run_python.py:69-75` | Full `os.environ` passed to subprocesses |
| **Session files insecure permissions** | `markdown.py:37-54`, `logging.py:37-43` | Write-then-chmod race; DB created 0644 |
| **Agent ID path traversal** | `pool.py:328-336` | AgentPool doesn't validate IDs internally |

### High Priority (P1)

| Issue | Summary |
|-------|---------|
| Process group not killed on timeout | Child processes survive parent kill |
| Regex replace timeout ineffective | Thread continues after asyncio timeout |
| Symlink attacks on session save | `_secure_write_file()` follows symlinks |
| HTTP header parsing unbounded | No limits on header count/size |
| MCP server/tool name injection | Unsanitized names in skill IDs |

### Remediation Roadmap

See `reviews/MASTER-PLAN.md` for 8-sprint phased plan with:
- Security fixes paired with tests
- Architecture refactors (Session decomposition, RPC layering, REPL modularization)
- Test harness and CI setup

**Sprint 1 (P0 patch):** Deserialization fix, token exfil prevention, env sanitization, secure file perms, agent ID validation.

---

## Completed: Sprint 1 — P0 Security Patch ✅

**Branch:** `security/sprint-1-p0-fixes` | **Tests:** 100 security tests, 1386 total passing

All P0 critical issues fixed: P0.1 deserialization, P0.2 token exfil, P0.3 env sanitization, P0.4 session perms, P0.5 agent ID validation.

---

## Completed: Sprint 2 — P1 Hardening ✅

**Goal:** Removed common local attack primitives (symlink clobbering, DoS via headers/regex, orphan processes).

### P1.1: Session Save Symlink Defense ✅
- **Location:** `session/session_manager.py:_secure_write_file()`
- **Fix:** Added `os.O_NOFOLLOW` flag to `os.open()`, raises `SessionManagerError` on symlinks
- **Test:** `tests/security/test_p1_symlink_defense.py` (6 tests)

### P1.2: HTTP Header Size/Count Limits ✅
- **Location:** `rpc/http.py:read_http_request()`
- **Fix:** Added limits: `MAX_HEADERS_COUNT=128`, `MAX_HEADER_NAME_LEN=1024`, `MAX_HEADER_VALUE_LEN=8192`, `MAX_TOTAL_HEADERS_SIZE=32KB`
- **Test:** `tests/security/test_p1_http_header_limits.py` (13 tests)

### P1.4: Kill Subprocess Process Groups on Timeout ✅
- **Location:** `skill/base.py:_execute_subprocess()`, `bash.py`, `run_python.py`
- **Fix:** Added `start_new_session=True` + `os.killpg()` for process group kill
- **Test:** `tests/security/test_p1_process_group_kill.py` (5 tests)

### P1.5: Regex Replace Timeout Enforcement (Deferred)
- Deferred to Sprint 3 - requires subprocess or `regex` library changes

### P1.6: Provider base_url SSRF Validation ✅
- **Location:** `provider/base.py:validate_base_url()`
- **Fix:** Require HTTPS; allow HTTP only for loopback; added `allow_insecure_http` config
- **Test:** `tests/security/test_p1_provider_ssrf.py` (17 tests)

### P1.8: CLI Init Symlink Defense ✅
- **Location:** `cli/init_commands.py`
- **Fix:** Added `_safe_write_text()` with symlink check before overwrite
- **Test:** `tests/security/test_p1_init_symlink_defense.py` (11 tests)

### P1.9: RPC create_temp() Race Condition ✅
- **Location:** `rpc/pool.py`
- **Fix:** Refactored to `_create_unlocked()`, `create_temp()` holds lock for entire operation
- **Test:** `tests/security/test_p1_create_temp_race.py` (6 tests)

**Sprint 2 Test Count:** 58 new security tests, 158 total security tests passing

---

## Completed: Sprint 3 — P2 Security Hardening + Architecture ✅

**Goal:** Close medium-severity gaps, establish core security primitives.

### P2.1: validate_url() Safe Default ✅
- **Location:** `core/url_validator.py:validate_url()`
- **Fix:** Default changed from `allow_localhost=True` to `False`
- **Test:** `tests/security/test_p2_url_localhost_default.py` (10 tests)

### P2.2: DNS Rebinding/TOCTOU Documentation ✅
- **Location:** `core/url_validator.py` module docstring
- **Status:** Documented as known limitation with existing mitigations

### P2.3: blocked_paths in PathResolver ✅
- **Location:** `core/resolver.py:resolve()`, `skill/services.py`
- **Fix:** PathResolver now passes blocked_paths to validate_path()
- **Test:** `tests/security/test_p2_blocked_paths.py` (9 tests)

### P2.4: Path Traversal Bug Fix ✅
- **Location:** `core/resolver.py:resolve()`, `skill/services.py`
- **Fix:** BUG - resolve() skipped allowed_paths check when tool_name=None
- **Test:** `tests/security/test_p2_exec_cwd_normalization.py` (9 tests)

### P2.6: append_file True Append ✅
- **Location:** `skill/builtin/append_file.py`
- **Fix:** Uses `open(file, 'a')` instead of read+concat+rewrite
- **Test:** `tests/security/test_p2_append_file.py` (12 tests)

### P2.14: deep_merge() List Replace ✅
- **Location:** `core/utils.py:deep_merge()`
- **Fix:** Lists are now REPLACED, not extended (allows local override of blocked_paths)
- **Test:** `tests/security/test_p2_deep_merge_semantics.py` (11 tests)

### P2.5: File Size/Line Limits + Streaming Reads ✅
- **Location:** `core/constants.py`, `skill/builtin/read_file.py`, `tail.py`, `grep.py`
- **Fix:** Added streaming reads with limits: MAX_FILE_SIZE_BYTES=10MB, MAX_OUTPUT_BYTES=1MB, MAX_READ_LINES=10000, MAX_GREP_FILE_SIZE=5MB
- **Test:** `tests/security/test_p2_file_size_limits.py` (14 tests)
- **Note:** Discovered gap during testing - agents can exceed context limits with no recovery path (see TODO for RPC compact method)

### P2.7: Defense-in-Depth Checks in Execution Tools ✅
- **Location:** `skill/builtin/bash.py`, `skill/builtin/run_python.py`
- **Fix:** Added internal permission level checks - bash_safe, shell_UNSAFE, and run_python now refuse to execute in SANDBOXED mode even if mistakenly registered
- **Test:** `tests/security/test_p2_defense_in_depth.py` (13 tests)

### P2.8: Token File Permission Checks ✅
- **Location:** `rpc/auth.py`
- **Fix:** Added `check_token_file_permissions()` function and `InsecureTokenFileError` exception. Both `ServerTokenManager.load()` and `discover_rpc_token()` now check file permissions. Configurable strict mode (refuse) vs warn-only mode (default).
- **Test:** `tests/security/test_p2_token_file_permissions.py` (20 tests)

### P2.9-12: MCP Protocol + Transport Hardening ✅
- **Location:** `mcp/client.py`, `mcp/transport.py`, `mcp/permissions.py`
- **Fixes:**
  - P2.9: Response ID matching - verifies response IDs match request IDs
  - P2.10: Notification discarding - discards server notifications while waiting for response
  - P2.11: Deny-by-default for `can_use_mcp(None)` - MCP access denied without explicit permissions
  - P2.12: Stdio line length limits - MAX_STDIO_LINE_LENGTH=10MB prevents memory exhaustion
- **Test:** `tests/security/test_p2_mcp_hardening.py` (22 tests)

### P2.13: Provider Error Body Size Caps ✅
- **Location:** `provider/base.py`
- **Fix:** Added `MAX_ERROR_BODY_SIZE=10KB` constant. Both streaming and non-streaming error paths now truncate error bodies to prevent memory exhaustion from malicious/buggy providers.
- **Test:** `tests/security/test_p2_provider_error_caps.py` (13 tests)

### Arch A1: Canonical Tool Identifiers ✅
- **Location:** `core/identifiers.py` (new module)
- **Features:**
  - `validate_tool_name()` - strict validation with detailed error messages
  - `normalize_tool_name()` - safe normalization of external input (MCP, config)
  - `build_mcp_skill_name()` - canonical MCP skill name construction
  - Unicode normalization, reserved name protection, length limits
- **Applied to:** `mcp/skill_adapter.py`, `skill/registry.py`
- **Test:** `tests/security/test_arch_a1_identifiers.py` (121 tests)

### Arch A2: PathDecisionEngine ✅
- **Location:** `core/path_decision.py` (new module)
- **Features:**
  - `PathDecisionEngine` - authoritative path access decisions with explicit results
  - `PathDecision` - result dataclass with reason, detail, matched_rule
  - `PathDecisionReason` - enum for decision explanations
  - `from_services()` factory for ServiceContainer integration
- **Test:** `tests/security/test_arch_a2_path_decision.py` (69 tests)

**Sprint 3 Test Count:** 190 new Arch tests + 133 P2 tests = 323 new tests, 481 total security tests, 1767 total passing

---

## Completed: Sprint 4 — Skill Framework Cleanup + Session Decomposition ✅

**Goal:** Remove monkey-patching validation behavior. Make `Session` testable by extracting components.

### B1: Validation Pipeline Unification ✅
- **Location:** `skill/base.py`
- **Fix:** Added `base_skill_factory()` decorator for BaseSkill subclasses
- **Applied to:** `echo.py`, `sleep.py` (previously bypassed validation wrapper)
- **Result:** All skills now use unified validation pipeline via factory decorators

### B2/B3: SkillSpec Metadata ✅
- **Location:** `skill/registry.py`
- **Features:**
  - `SkillSpec` dataclass: `name`, `description`, `parameters`, `factory`
  - Registry stores `_specs: dict[str, SkillSpec]` instead of just factories
  - `get_definitions()` can return metadata WITHOUT instantiation when provided at registration
- **Test:** `tests/unit/skill/test_skillspec.py` (10 tests)

### C1: Session Component Extraction ✅
- **Location:** `session/dispatcher.py`, `session/enforcer.py`, `session/confirmation.py` (new modules)
- **Components:**
  - `ToolDispatcher` - resolves tool calls to skills (builtin + MCP)
  - `PermissionEnforcer` - centralizes all permission checks
  - `ConfirmationController` - handles user confirmation + allowance updates
- **Result:** `Session._execute_single_tool()` reduced from 207 lines to ~70 lines of orchestration
- **Public APIs added:** `MCPServerRegistry.find_skill()`, `ContextManager.token_counter`, typed ServiceContainer accessors

### C3: Storage Decoding Robustness ✅
- **Location:** `session/storage.py`, `session/persistence.py`
- **Fixes:**
  - Try/catch around `json.loads()` in `MessageRow.from_row()`, `EventRow.from_row()`
  - Size validation: `MAX_JSON_FIELD_SIZE=10MB` prevents memory exhaustion
  - `SessionPersistenceError` for malformed session JSON
- **Test:** `tests/security/test_storage_corruption.py` (19 tests)

### Test Coverage
- **test_skillspec.py:** 10 tests (registry no-instantiation)
- **test_skill_validation.py:** 16 tests (validation uniformity)
- **test_storage_corruption.py:** 19 tests (corruption handling)

**Sprint 4 Test Count:** 45 new tests, 1812 total passing

---

## Completed: Sprint 5 — RPC Layering + CLI Modularization ✅

**Goal:** Make RPC/HTTP paths composable and testable. Reduce REPL risk by splitting responsibilities.

### D1: Shared Dispatch Core ✅
- **Location:** `rpc/dispatch_core.py` (new module)
- **Features:**
  - `dispatch_request()` - shared dispatch logic for handler lookup, exception→error mapping
  - `InvalidParamsError` - moved from dispatcher.py
  - `Handler` type alias
- **Result:** Both `Dispatcher` and `GlobalDispatcher` now call `dispatch_request()`, eliminating 90 lines of duplication

### D4: Request-ID Correctness ✅
- **Location:** `rpc/dispatcher.py:201`, `rpc/agent_api.py:123`
- **Fix:** Changed truthiness checks to `is None` checks so `request_id=0` works correctly

### D2: Layered HTTP Pipeline ✅
- **Location:** `rpc/http.py`
- **Features:**
  - `_authenticate_request()` - auth layer
  - `_route_to_dispatcher()` - routing layer
  - `_restore_agent_if_needed()` - auto-restore middleware
- **Result:** `handle_connection()` is now a clean orchestrator calling each layer

### D5: Object Graph Bootstrap ✅
- **Location:** `rpc/bootstrap.py` (new module)
- **Features:**
  - `bootstrap_server_components()` - phased initialization handling circular dependency
  - Returns `(pool, global_dispatcher, shared)` tuple
- **Applied to:** `cli/repl.py`, `cli/serve.py` (removed ~80 lines of duplicate setup code)

### E1: REPL Modularization (Partial) ✅
- **Extracted:**
  - `cli/arg_parser.py` - argument parsing (~230 lines)
  - `cli/confirmation_ui.py` - tool confirmation prompts (~160 lines)
- **Result:** `repl.py` reduced from 1737 → 1359 lines

### E3: Delete Dead Code ✅
- **Deleted:** `cli/commands.py` (66 lines of unused code)
- **Verification:** Command system uses `repl_commands.py` + `commands/core.py`

### E4: Per-REPL Key Monitor State ✅
- **Location:** `cli/keys.py`, `cli/repl.py`
- **Fix:** Replaced global `_key_monitor_state` dict with per-instance `asyncio.Event`
- **Change:** `KeyMonitor` and `confirm_tool_action` now accept `pause_event` parameter

### Test Results
- **1829 tests passing** (2 skipped)
- All security tests passing
- Live test verified: REPL + RPC commands work correctly

### Code Metrics
- **7 files modified**, 5 new files created
- **Net reduction:** 210 lines (245 added, 455 deleted)

---

## Known Issues

- ~~**WSL Terminal**: Bash may close after `nexus` exits.~~ Fixed in d276c70.
