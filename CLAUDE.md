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
nexus3 &

# Create a subagent for research
nexus3 rpc create researcher

# Send research tasks
nexus3 rpc send researcher "Look at nexus3/rpc/ and summarize the JSON-RPC types"

# Check status
nexus3 rpc status researcher

# Clean up when done
nexus3 rpc destroy researcher
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
nexus3                   # Default: lobby mode for session selection
nexus3 --fresh            # Skip lobby, start new temp session
nexus3 --resume           # Resume last session
nexus3 --session NAME     # Load specific saved session
nexus3 --template PATH    # Use custom system prompt

# HTTP server (headless, dev-only - requires NEXUS_DEV=1)
NEXUS_DEV=1 nexus3 --serve [PORT]

# Client mode (connect to existing server)
nexus3 --connect [URL] --agent [ID]

# RPC commands (require server to be running - no auto-start)
nexus3 rpc create worker-1
nexus3 rpc send worker-1 "Hello"
nexus3 rpc shutdown
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

*Note: `port` defaults to 8765. `preset` can be trusted/sandboxed/worker (yolo is REPL-only). Skills mirror `nexus3 rpc` CLI commands. Destructive file tools remind agents to read files before modifying.*

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

1. Start the server: `nexus3 &`
2. Create a test agent: `nexus3 rpc create test-agent`
3. Send test messages: `nexus3 rpc send test-agent "describe your permissions and what you can do"`
4. Verify the agent responds correctly and has expected capabilities
5. Clean up: `nexus3 rpc destroy test-agent`

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
nexus3                       # REPL with embedded server (default)
NEXUS_DEV=1 nexus3 --serve [PORT]  # Headless server (dev-only)
nexus3 --connect [URL]             # Connect to existing server

# Programmatic RPC operations (require server running)
nexus3 rpc detect             # Check if server is running
nexus3 rpc list               # List agents
nexus3 rpc create ID          # Create agent
nexus3 rpc create ID -M "msg" # Create agent and send initial message
nexus3 rpc destroy ID         # Destroy agent
nexus3 rpc send AGENT MSG     # Send message to agent
nexus3 rpc status AGENT       # Get agent status
nexus3 rpc shutdown           # Stop server (graceful)
nexus3 rpc cancel AGENT ID    # Cancel in-progress request
```

**Key behaviors:**
- **Security:** `--serve` requires `NEXUS_DEV=1` env var (prevents unattended servers)
- **Security:** `nexus3 rpc` commands do NOT auto-start servers (start `nexus3` manually)
- **Idle timeout:** Embedded server auto-shuts down after 30 min of no RPC activity
- `nexus3 rpc send/status/destroy/shutdown` require server to be running
- All commands use `--port N` to specify non-default port (default: 8765)
- All commands support `--api-key KEY` for explicit authentication (auto-discovered by default)

**User preference:** Commands should be simple and clean. Avoid:
- Sourcing virtualenvs manually
- Using `python -m nexus3` directly
- Using full paths to scripts
- Any invocation that isn't `nexus3` or `nexus3 rpc`

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
nexus3 --init-global           # Create ~/.nexus3/ with defaults
nexus3 --init-global-force     # Overwrite existing

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
   nexus3 rpc create worker --cwd /tmp/sandbox --allowed-write-paths /tmp/sandbox
   ```

4. **Trusted agents must be created explicitly**: To get a trusted agent, you must pass `--preset trusted` explicitly. Trusted is not the default for RPC.

5. **Trusted agents in RPC mode**: Can read anywhere, but destructive operations follow the same confirmation logic (which auto-allows within CWD in non-interactive mode).

6. **YOLO is REPL-only**: You CANNOT create a yolo agent via RPC. The yolo preset is only available in interactive REPL mode.

7. **Trusted agents can only create sandboxed subagents**: A trusted agent cannot spawn another trusted agent - all subagents are sandboxed (ceiling enforcement).

8. **Sandboxed agents cannot create agents at all**: The `nexus_create`, `nexus_destroy`, `nexus_send`, and other nexus tools are completely disabled for sandboxed agents.

**Example secure agent creation:**
```bash
# Read-only agent (default) - can only read in its cwd
nexus3 rpc create reader --cwd /path/to/project

# Agent with write access to specific directory
nexus3 rpc create writer --cwd /path/to/project --allowed-write-paths /path/to/project/output

# Trusted agent (explicit - use with care)
nexus3 rpc create coordinator --preset trusted
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

- [x] **RPC `compact` method for stuck agents**: ~~When an agent's context exceeds the provider's token/byte limit, the agent becomes stuck (alive but unusable).~~ Fixed: Added `nexus3 rpc compact <agent_id>` command and `_handle_compact()` RPC method.

---

## Security Hardening (Complete)

Comprehensive security review and remediation completed in January 2026. Key improvements:

- **Permission system**: Ceiling enforcement, fail-closed defaults, path validation
- **RPC hardening**: Token auth, header limits, SSRF protection, symlink defense
- **Process isolation**: Process group kills on timeout, env sanitization
- **Input validation**: URL validation, agent ID validation, MCP protocol hardening
- **Output sanitization**: Terminal escape stripping, Rich markup escaping, secrets redaction

**Test coverage**: 2300+ tests including 500+ security-specific tests.

For historical details, see `reviews/` directory:
- `reviews/MASTER-PLAN.md` - Original 8-sprint remediation plan
- `reviews/2026-01-17/` - Final review consolidation

---

## Using NEXUS Subagents for Research

**Updated guidance based on live testing (2026-01-17):**

### Starting the Server

```bash
# Option 1: Headless server (for CI/automation)
NEXUS_DEV=1 nexus3 --serve 8765 &

# Option 2: Check if already running
nexus3 rpc detect
```

### Creating Research Agents

**Critical: Set CWD correctly for write access**

```bash
# Trusted agent that can read anywhere, write within CWD
nexus3 rpc create auditor-1 \
  --preset trusted \
  --cwd /home/inc/repos/NEXUS3 \
  --timeout 300

# Agents can read anywhere but writes are auto-denied outside CWD
# This is intentional security behavior for RPC mode
```

### Sending Research Tasks

```bash
# Always use long timeout for research tasks (default 300s, can increase)
nexus3 rpc send auditor-1 "Read session/enforcer.py and check if PathDecisionEngine is imported or used" \
  --timeout 600

# Check status
nexus3 rpc status auditor-1

# Get response
nexus3 rpc send auditor-1 "continue" --timeout 300
```

### Key Constraints

| Constraint | Behavior |
|------------|----------|
| **Write access** | Only within agent's CWD (set via `--cwd`) |
| **Read access** | Anywhere (trusted preset) |
| **Confirmations** | Auto-denied in RPC mode for paths outside CWD |
| **Tool iterations** | Max 100 (raised from 10) |
| **Timeouts** | Use `--timeout 300` or higher for research tasks |

### Cleanup

```bash
nexus3 rpc destroy auditor-1
nexus3 rpc shutdown  # When done with all agents
```

### Reuse Pattern

**Don't destroy researchers immediately.** If an agent has context window remaining after returning findings, reuse it to implement fixes:

```bash
# Check remaining context
nexus3 rpc status auditor-1

# If tokens are low, destroy and create fresh
# If tokens are fine, send implementation task
nexus3 rpc send auditor-1 "Now implement the fix you described" --timeout 300
```

This avoids re-explaining the problem to a fresh agent.

### Coordination Pattern

Claude Code (Opus) coordinates NEXUS subagents directly:
- Create agents with appropriate CWD and permissions
- Send focused research tasks
- Collect and synthesize findings
- Agents use GPT-5.2 by default (configured in `nexus3/defaults/config.json`)

Do NOT use a NEXUS coordinator agent in the middle - Claude Code is better at coordination.

---

## README Update Procedure

Use a trusted NEXUS coordinator to orchestrate sandboxed subagents for updating module READMEs.

### 1. Start Server

```bash
NEXUS_DEV=1 nexus3 --serve 8765 &
# Or: nexus3 --fresh &  (REPL with embedded server)
```

### 2. Create Trusted Coordinator

```bash
nexus3 rpc create coordinator \
  --preset trusted \
  --cwd /home/inc/repos/NEXUS3
```

### 3. Send Coordination Task

```bash
nexus3 rpc send coordinator "You are a coordinator for updating NEXUS3 module README files.

Your task:
1. Create sandboxed agents for each module to update their README.md
2. Each agent should have write access ONLY to their module directory
3. After all updates, read the module READMEs and update the main README.md

The modules are in nexus3/:
- core, config, provider, context, session, skill, display, cli, rpc, mcp, commands, defaults

For each module, create an agent like:
nexus_create(
    agent_id=\"readme-core\",
    cwd=\"/home/inc/repos/NEXUS3/nexus3/core\",
    allowed_write_paths=[\"/home/inc/repos/NEXUS3/nexus3/core\"],
    initial_message=\"Read all .py files in this directory. Update README.md to accurately reflect the current module contents, exports, and usage. Be concise.\"
)

Start with 3-4 modules in parallel, then continue in batches.
After all module READMEs are updated, update /home/inc/repos/NEXUS3/README.md with an accurate project overview." --timeout 600
```

### 4. Monitor Progress

```bash
nexus3 rpc list                    # See all agents
nexus3 rpc status coordinator      # Check coordinator progress
```

### 5. Continue if Needed

```bash
nexus3 rpc send coordinator "Continue. Update remaining modules, then the main README." --timeout 600
```

### 6. Cleanup

```bash
nexus3 rpc shutdown
```

### Key Points

- **Coordinator**: Trusted preset, can read anywhere and create subagents
- **Subagents**: Sandboxed with `allowed_write_paths` scoped to their module only
- **Permission ceiling**: Trusted agents can only create sandboxed subagents
- **Result**: 12 module READMEs + 1 main README updated in ~5 minutes

---

## Agent-Driven Development Workflow

This workflow proved highly effective for architectural changes. Use it for non-trivial refactors.

### Phase 1: Research (Parallel Explorers)

Spawn multiple Claude Code Explore agents in parallel to map the problem space:

```bash
# Example: Understanding a refactor target
# Spawn 3 explorers simultaneously to cover different angles
```

Each explorer focuses on one aspect:
- **Explorer 1**: Map existing implementation (callbacks, signatures, call sites)
- **Explorer 2**: Map consumer code (how REPL/clients use the system)
- **Explorer 3**: Find existing patterns to model after (similar code in codebase)

### Phase 2: Validate with GPT

Create a trusted GPT agent (uses extended thinking) for deep analysis:

```bash
nexus3 rpc create gpt-reviewer --preset trusted --model gpt --cwd /path/to/project
nexus3 rpc send gpt-reviewer "Read the consolidated findings and validate against codebase..." --timeout 600
```

GPT's role:
- Validate explorer findings against actual code
- Identify false positives
- Propose architecture (e.g., event bus vs callbacks)
- Note any issues that block release

**Don't rush GPT.** Check in periodically with "How's it going? Need help?" not "Write report now."

### Phase 3: Implementation (Batched Subagents)

Batch implementation work so agents don't conflict on files:

| Batch | Agent | Files | Task |
|-------|-------|-------|------|
| 1 | agent-types | events.py (new) | Create type definitions |
| 2 | agent-core | session.py | Modify core to emit events |
| 3 | agent-consumer | repl.py | Migrate consumer (can defer) |

### Phase 4: Verification

Have GPT verify the implementation:

```bash
nexus3 rpc send gpt-reviewer "We fixed X, Y, Z. Verify the changes address your concerns." --timeout 180
```

GPT identifies remaining issues → fix → re-verify until clean.

### Key Principles

1. **Parallel research, sequential implementation** - Explorers can run in parallel; implementation must be batched by file
2. **GPT for validation, not coordination** - GPT validates and critiques; Claude Code coordinates
3. **Reuse agents with context** - Check `nexus3 rpc status agent-id` before destroying; reuse if tokens remain
4. **Don't rush reasoning models** - GPT with `reasoning: true` needs time; ping gently
5. **Batch by file boundaries** - Never have two agents modify the same file simultaneously

### Example Session (Session Event Bus Refactor)

```
1. Research Phase:
   - 3 parallel explorers: callbacks, REPL wiring, existing patterns
   - ~5 min total

2. GPT Review:
   - Created trusted GPT agent with --model gpt
   - Sent consolidated findings + asked for architecture recommendation
   - GPT recommended "Option A: typed event stream"
   - ~15 min (let it think)

3. Implementation:
   - Batch 1: Create events.py (new file, no conflicts)
   - Batch 2: Modify session.py (add run_turn method)
   - Batch 3: REPL migration (deferred - backward compat works)

4. Verification:
   - GPT identified 4 issues (cancellation, unused event, naming, defaults)
   - Fixed all 4
   - GPT re-verified: approved

Result: Clean architectural change with typed events, backward compatible.
```

---

## Current Work In Progress

**Branch:** `arch/sprint-5-rpc-cli`

**Completed:**
- Session event system (`nexus3/session/events.py`)
- `Session.run_turn()` yielding `AsyncIterator[SessionEvent]`
- Backward compatibility via callback adapter
- Token `strict_permissions` default → `True` (auth.py)
- Docs standardization: `nexus` → `nexus3` throughout
- Session directory permissions → `0700` (session_manager.py, init_commands.py)
- All 2315 tests pass

**Remaining:**
- REPL migration to event stream (deferred, not blocking)

**Review files:**
- `reviews/2026-01-17/FINAL-CONSOLIDATED-REVIEW.md` - Consolidated findings
- `reviews/2026-01-17/GPT-DEEP-REVIEW.md` - GPT's detailed analysis
