# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- PART I: PROJECT -->

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Feature-complete. Multi-provider support, permission system, MCP integration, context compaction.

**Claude Code Skills:** Local skills for Claude Code are in `.claude/skills/`:
- `.claude/skills/nexus/SKILL.md` - REPL/server startup modes
- `.claude/skills/nexus-rpc/SKILL.md` - RPC commands documentation

---

## Architecture

### Module Structure

```
nexus3/
├── core/           # Types, interfaces, errors, encoding, paths, URL validation, permissions, process termination
├── config/         # Pydantic schema, permission config, fail-fast loader
├── provider/       # AsyncProvider protocol, multi-provider support, retry logic
├── context/        # ContextManager, ContextLoader, TokenCounter, compaction
├── session/        # Session coordinator, persistence, SessionManager, SQLite logging
├── skill/          # Skill protocol, SkillRegistry, ServiceContainer, builtin skills
├── clipboard/      # Scoped clipboard system (agent/project/system), SQLite storage
├── patch/          # Unified diff parsing, validation, and application
├── display/        # DisplayManager, StreamingDisplay, InlinePrinter, SummaryBar, theme
├── cli/            # Unified REPL, lobby, whisper, HTTP server, client commands
├── rpc/            # JSON-RPC protocol, Dispatcher, GlobalDispatcher, AgentPool, auth
├── mcp/            # Model Context Protocol client, external tool integration
├── commands/       # Unified command infrastructure for CLI and REPL
├── defaults/       # Default configuration and system prompts
└── client.py       # NexusClient for agent-to-agent communication
```

Each module has a `README.md` with detailed documentation.

### Key Interfaces

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

### Skill Type Hierarchy

Skills are organized into base classes that provide shared infrastructure for common patterns. Each base class handles boilerplate so individual skills focus on their unique logic.

#### Hierarchy Overview

```
Skill (Protocol)
├── BaseSkill         # Minimal abstract base (name, description, parameters, execute)
├── FileSkill         # Path validation + per-tool allowed_paths resolution via ServiceContainer
├── NexusSkill        # Server communication (port discovery, client management)
├── ExecutionSkill    # Subprocess execution (timeout, output formatting)
└── FilteredCommandSkill  # Permission-based command filtering + per-tool allowed_paths
```

#### Base Classes

| Base Class | Purpose | Skills Using It |
|------------|---------|-----------------|
| `FileSkill` | Path validation, symlink resolution, allowed_paths | read_file, write_file, edit_file, append_file, tail, file_info, list_directory, mkdir, copy_file, rename, regex_replace, glob, grep |
| `NexusSkill` | Server URL building, API key discovery, client error handling | nexus_create, nexus_destroy, nexus_send, nexus_status, nexus_cancel, nexus_shutdown |
| `ExecutionSkill` | Timeout enforcement, working dir resolution, output formatting | bash, run_python |
| `FilteredCommandSkill` | Read-only command filtering, blocked pattern matching | git |

#### Creating New Skills

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

### Multi-Agent Server

#### Server Architecture

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

#### API

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

Trusted caller identity propagates through `requester_id` / `X-Nexus-Agent`
across both global and `/agent/{id}` RPC routes. `create_agent` follow-up
`initial_message` dispatch inherits that same requester context.

#### Component Sharing

| Shared (SharedComponents) | Per-Agent |
|---------------------------|-----------|
| Config | SessionLogger |
| ProviderRegistry | ContextManager |
| ContextLoader + base context | ServiceContainer |
| Base log directory | SkillRegistry, Session, Dispatcher |
| MCPServerRegistry | |
| Custom permission presets | |

<!-- PART II: USER REFERENCE -->

---

## CLI Modes

```bash
# Unified REPL (auto-starts embedded server with 30-min idle timeout)
nexus3                    # Default: lobby mode for session selection
nexus3 --fresh            # Skip lobby, start new temp session
nexus3 --resume           # Resume last session (from ~/.nexus3/last-session.json)
nexus3 --session NAME     # Load specific saved session (from ~/.nexus3/sessions/)
nexus3 --template PATH    # Use custom system prompt (with --fresh)
nexus3 --model NAME       # Use specific model alias or ID

# HTTP server (headless, dev-only - requires NEXUS_DEV=1)
NEXUS_DEV=1 nexus3 --serve [PORT]

# Client mode (connect to existing server)
nexus3 --connect [URL] --agent [ID]
nexus3 --connect --scan 9000-9050  # Scan additional ports for servers

# RPC commands (require server to be running - no auto-start)
nexus3 rpc detect                 # Check if server is running
nexus3 rpc list                   # List all agents
nexus3 rpc create NAME [flags]    # Create agent
nexus3 rpc destroy NAME           # Remove agent
nexus3 rpc send NAME "message"    # Send message
nexus3 rpc status NAME            # Get agent tokens/context
nexus3 rpc compact NAME           # Force context compaction
nexus3 rpc cancel NAME REQ_ID     # Cancel request
nexus3 rpc shutdown               # Shutdown server

# Initialization
nexus3 --init-global              # Create ~/.nexus3/ with defaults
nexus3 --init-global-force        # Overwrite existing global config
```

### CLI Flag Reference

| Flag | Description |
|------|-------------|
| `--fresh` | Start fresh temp session (skip lobby) |
| `--resume` | Resume last session automatically |
| `--session NAME` | Load specific saved session |
| `--template PATH` | Custom system prompt file (with --fresh) |
| `--model NAME` | Model name/alias to use |
| `--serve [PORT]` | Run headless HTTP server (requires NEXUS_DEV=1) |
| `--connect [URL]` | Connect to existing server (URL optional) |
| `--agent ID` | Agent ID to connect to (with --connect) |
| `--scan PORTS` | Additional ports to scan (e.g., "9000" or "8765,9000-9050") |
| `--api-key KEY` | Explicit API key (auto-discovered by default) |
| `-v, --verbose` | Show debug output in terminal |
| `-V, --log-verbose` | Write debug output to verbose.md log |
| `--raw-log` | Enable raw API JSON logging |
| `--log-dir PATH` | Directory for session logs |
| `--reload` | Auto-reload on code changes (serve mode, requires watchfiles) |

---

## Session Management

Sessions persist conversation history, model choice, permissions, and working directory to disk.

### Startup Flow

1. **Lobby (default)**: Interactive menu showing:
   - Resume last session (if exists)
   - Start fresh session
   - Choose from saved sessions

2. **Direct flags** skip the lobby:
   - `--fresh`: New temp session (`.1`, `.2`, etc.)
   - `--resume`: Load `~/.nexus3/last-session.json`
   - `--session NAME`: Load `~/.nexus3/sessions/{NAME}.json`

See REPL Commands Reference for session commands (`/save`, `/clone`, `/rename`, `/delete`).

### Session File Format

Sessions are JSON files with schema version 1:

```json
{
  "schema_version": 1,
  "agent_id": "my-project",
  "created_at": "2026-01-22T10:30:00",
  "modified_at": "2026-01-22T14:45:00",
  "messages": [...],
  "system_prompt": "...",
  "system_prompt_path": "/path/to/NEXUS.md",
  "working_directory": "/home/user/project",
  "permission_level": "trusted",
  "permission_preset": "trusted",
  "disabled_tools": [],
  "session_allowances": {},
  "model_alias": "sonnet",
  "token_usage": {"total": 12500, "available": 195000},
  "provenance": "user"
}
```

### File Locations

```
~/.nexus3/
├── sessions/           # Named sessions
│   └── {name}.json     # Saved via /save
├── last-session.json   # Auto-saved on exit (for --resume)
└── last-session-name   # Name of last session
```

### Key Behaviors

- **Auto-save on exit**: Current session saved to `last-session.json` for `--resume`
- **Temp sessions**: Named `.1`, `.2`, etc. Cannot be saved with `/save` without providing a name
- **Model persistence**: Model alias saved and restored (e.g., switch to haiku, save, resume → still haiku)
- **Permission restoration**: Preset and disabled tools restored from saved session
- **CWD restoration**: Working directory restored from saved session

### Session Restoration Flow

When loading a saved session (`--resume`, `--session`, or via lobby):

1. Load JSON from disk
2. Deserialize messages back to `Message` objects
3. Resolve model alias via config (`config.resolve_model(saved.model_alias)`)
4. Recreate permissions from preset + disabled_tools
5. Rebuild agent with context, skill registry, and provider

---

## REPL Commands Reference

### Agent Management

| Command | Description |
|---------|-------------|
| `/agent` | Show current agent's detailed status (model, tokens, permissions) |
| `/agent <name>` | Switch to agent (prompts to create if doesn't exist) |
| `/agent <name> --yolo\|--trusted\|--sandboxed` | Create agent with preset and switch |
| `/agent <name> --model <alias>` | Create agent with specific model |
| `/list` | List all active agents |
| `/create <name> [--yolo\|--trusted\|--sandboxed] [--model]` | Create agent without switching |
| `/destroy <name>` | Remove active agent from pool |
| `/send <agent> <msg>` | One-shot message to another agent |
| `/status [agent] [--tools] [--tokens] [-a]` | Get agent status (-a: all details) |
| `/cancel [agent]` | Cancel in-progress request |
| `/shutdown` | Shutdown the server (stops all agents) |

### Session Management

| Command | Description |
|---------|-------------|
| `/save [name]` | Save current session (prompts for name if temp) |
| `/clone <src> <dest>` | Clone agent or saved session |
| `/rename <old> <new>` | Rename agent or saved session |
| `/delete <name>` | Delete saved session from disk |

### Whisper Mode

| Command | Description |
|---------|-------------|
| `/whisper <agent>` | Enter whisper mode - redirect all input to target agent |
| `/over` | Exit whisper mode, return to original agent |

### Configuration

| Command | Description |
|---------|-------------|
| `/cwd [path]` | Show or change working directory |
| `/model` | Show current model |
| `/model <name>` | Switch to model (alias or full ID) |
| `/permissions` | Show current permissions |
| `/permissions <preset>` | Change to preset (yolo/trusted/sandboxed) |
| `/permissions --disable <tool>` | Disable a tool |
| `/permissions --enable <tool>` | Re-enable a tool |
| `/permissions --list-tools` | List tool enable/disable status |
| `/prompt [file]` | Show or set system prompt |
| `/compact` | Force context compaction/summarization |
| `/gitlab` | Show GitLab status and configured instances |
| `/gitlab on\|off` | Enable/disable GitLab tools for this session |

### MCP (External Tools)

| Command | Description |
|---------|-------------|
| `/mcp` | List configured and connected MCP servers |
| `/mcp connect <name>` | Connect to a configured MCP server |
| `/mcp connect <name> --allow-all --shared` | Connect skipping prompts, share with all agents |
| `/mcp disconnect <name>` | Disconnect from an MCP server |
| `/mcp tools [server]` | List available MCP tools |
| `/mcp resources [server]` | List available MCP resources |
| `/mcp prompts [server]` | List available MCP prompts |
| `/mcp retry <name>` | Retry listing tools from a server |

**Key behaviors:**
- Servers connect even if initial tool listing fails (graceful degradation)
- Dead connections automatically reconnect when tools are needed (lazy reconnection)
- Use `/mcp retry <server>` to manually retry tool listing after fixing configuration issues

### Initialization

| Command | Description |
|---------|-------------|
| `/init [FILENAME]` | Create .nexus3/ with AGENTS.md (default) or specified .md file |
| `/init --force` | Overwrite existing config |
| `/init --global` | Initialize ~/.nexus3/ instead |

### REPL Control

| Command | Description |
|---------|-------------|
| `/help` | Show help message |
| `/clear` | Clear the display (preserves context) |
| `/quit`, `/exit`, `/q` | Exit the REPL |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `ESC` | Cancel in-progress request |
| `Ctrl+C` | Interrupt current input |
| `Ctrl+D` | Exit REPL |
| `p` | View full tool details (during confirmation prompt) |

---

## Built-in Skills

| Skill | Parameters | Description |
|-------|------------|-------------|
| `read_file` | `path`, `offset`?, `limit`?, `line_numbers`? | Read file contents (numbered by default; use `line_numbers=false` for exact raw text) |
| `tail` | `path`, `lines`? | Read last N lines of a file (default: 10) |
| `file_info` | `path` | Get file/directory metadata (size, mtime, permissions) |
| `write_file` | `path`, `content` | Write/create UTF-8 text files (exact newline bytes; read file first!) |
| `edit_file` | `path`, `old_string`, `new_string`, `replace_all`?, `edits`? | UTF-8 exact string replacement, single or batched (read file first!) |
| `edit_lines` | `path`, `start_line`, `end_line`?, `new_content`, `edits`? | Replace UTF-8 lines by number; `edits` batches use original file line numbers atomically |
| `append_file` | `path`, `content`, `newline`? | Append UTF-8 text to a file (exact newline bytes; read file first!) |
| `regex_replace` | `path`, `pattern`, `replacement`, `count`?, `ignore_case`?, `multiline`?, `dotall`? | UTF-8 pattern-based find/replace (`count >= 0`; read file first!) |
| `patch` | `path`, `diff`?, `diff_file`?, `mode`?, `fidelity_mode`?, `fuzzy_threshold`?, `dry_run`? | Apply unified diffs (strict/tolerant/fuzzy modes; `target` remains a compatibility alias) |
| `copy_file` | `source`, `destination`, `overwrite`? | Copy a file to a new location |
| `mkdir` | `path` | Create directory (and parents) |
| `rename` | `source`, `destination`, `overwrite`? | Rename or move file/directory |

Contract rule for the file-edit family: unexpected extra arguments fail closed
instead of being silently dropped.
| `list_directory` | `path` | List directory contents |
| `glob` | `pattern`, `path`?, `exclude`? | Find files matching glob pattern (with exclusions) |
| `grep` | `pattern`, `path`?, `include`?, `context`? | Search file contents with file filter and context lines |
| `concat_files` | `extensions`, `path`?, `exclude`?, `lines`?, `max_total`?, `format`?, `sort`?, `gitignore`?, `dry_run`? | Concatenate files by extension with token estimation (dry_run=True by default) |
| `outline` | `path`, `file_type`?, `language`?, `parser`?, `depth`?, `preview`?, `signatures`?, `line_numbers`?, `tokens`?, `symbol`?, `diff`?, `recursive`? | Structural outline of file/directory (headings, classes, functions, keys). Directory mode is non-recursive, but `depth` controls nested symbols within each file. Use `symbol` for filtered read on files, `file_type`/`language`/`parser` to override parser detection, `tokens` for estimates, and `diff` for change markers |
| `git` | `command`, `cwd`? | Execute git commands (permission-filtered by level) |
| `bash_safe` | `command`, `timeout`? | Execute shell commands (shlex.split, no shell operators) |
| `shell_UNSAFE` | `command`, `timeout`? | Execute shell=True (pipes work, but injection-vulnerable) |
| `run_python` | `code`, `timeout`? | Execute Python code |
| `sleep` | `seconds`, `label`? | Pause execution (for testing) |
| `nexus_create` | `agent_id`, `preset`?, `disable_tools`?, `cwd`?, `allowed_write_paths`?, `model`?, `initial_message`?, `wait_for_initial_response`?, `port`? | Create agent (initial_message queued by default; wait flag only matters when `initial_message` is set) |
| `nexus_destroy` | `agent_id`, `port`? | Remove an agent (server keeps running) |
| `nexus_send` | `agent_id`, `content`, `port`? | Send message to an agent |
| `nexus_status` | `agent_id`, `port`? | Get agent tokens + context |
| `nexus_cancel` | `agent_id`, `request_id`, `port`? | Cancel in-progress request (`request_id` may be string or integer) |
| `nexus_shutdown` | `port`? | Shutdown the entire server |
| `copy` | `source`, `key`, `scope`?, `start_line`?, `end_line`?, `short_description`?, `tags`?, `ttl_seconds`? | Copy file content to clipboard |
| `cut` | `source`, `key`, `scope`?, `start_line`?, `end_line`?, `short_description`?, `tags`?, `ttl_seconds`? | Cut file content to clipboard (removes from source) |
| `paste` | `key`, `target`, `scope`?, `mode`?, `line_number`?, `start_line`?, `end_line`?, `marker`?, `create_if_missing`? | Paste clipboard content to file |
| `clipboard_list` | `scope`?, `tags`?, `any_tags`?, `verbose`? | List clipboard entries with optional tag filtering |
| `clipboard_get` | `key`, `scope`? | Get full content of a clipboard entry |
| `clipboard_update` | `key`, `scope`?, `new_key`?, `short_description`?, `content`?, `source`?, `start_line`?, `end_line`?, `ttl_seconds`? | Update clipboard entry metadata or content |
| `clipboard_delete` | `key`, `scope`? | Delete a clipboard entry |
| `clipboard_clear` | `scope`?, `confirm`? | Clear all entries in a scope |
| `clipboard_search` | `query`, `scope`?, `max_results`? | Search clipboard entries |
| `clipboard_tag` | `action`, `entry_key`?, `name`?, `scope`?, `description`? | Manage clipboard tags (list/add/remove/create/delete) |
| `clipboard_export` | `path`, `scope`?, `tags`? | Export clipboard entries to JSON file |
| `clipboard_import` | `path`, `scope`?, `conflict`?, `dry_run`? | Import clipboard entries from JSON file |
| `gitlab_repo` | `action`, `project`?, `instance`? | Repository operations (get, list, fork, search, whoami) |
| `gitlab_issue` | `action`, `project`?, `iid`?, `title`?, `assignees`?, `assignee_username`?, `author_username`?, ... | Issue CRUD (list, get, create, update, close, reopen, comment). Assignees/filters support 'me' shorthand. |
| `gitlab_mr` | `action`, `project`?, `iid`?, `source_branch`?, `assignees`?, `reviewers`?, `assignee_username`?, `author_username`?, `reviewer_username`?, ... | MR operations (list, get, create, update, merge, close, diff, commits, pipelines). Assignees/reviewers/filters support 'me' shorthand. |
| `gitlab_label` | `action`, `project`?, `name`?, `color`? | Label management (list, get, create, update, delete) |
| `gitlab_branch` | `action`, `project`?, `name`?, `ref`?, `push_level`?, `merge_level`?, `allow_force_push`? | Branch operations (list, get, create, delete, protect, unprotect, list-protected) |
| `gitlab_tag` | `action`, `project`?, `name`?, `ref`?, `create_level`? | Tag operations (list, get, create, delete, protect, unprotect, list-protected) |
| `gitlab_epic` | `action`, `group`, `iid`?, `title`?, ... | Epic management (list, get, create, update, close, add/remove issues) [Premium] |
| `gitlab_iteration` | `action`, `group`, `iteration_id`?, `title`?, ... | Iteration/sprint management (list, get, create, cadences) [Premium] |
| `gitlab_milestone` | `action`, `project` OR `group`, `milestone_id`?, `title`?, ... | Milestone operations (list, get, create, update, close, issues, MRs) |
| `gitlab_board` | `action`, `project` OR `group`, `board_id`?, `name`?, ... | Issue board management (list, get, create, lists) |
| `gitlab_time` | `action`, `project`, `iid`, `target_type`, `duration`?, ... | Time tracking (estimate, spend, reset, stats) on issues/MRs |
| `gitlab_approval` | `action`, `project`, `iid`?, `rule_id`?, `name`?, ... | MR approval management (status, approve, unapprove, rules) [Premium for rules] |
| `gitlab_draft` | `action`, `project`, `iid`, `draft_id`?, `body`?, ... | Draft notes for batch MR reviews (list, add, update, delete, publish) |
| `gitlab_discussion` | `action`, `project`, `iid`, `target_type`, `discussion_id`?, ... | Threaded discussions on MRs/issues (list, create, reply, resolve) |
| `gitlab_pipeline` | `action`, `project`, `pipeline_id`?, `ref`?, `status`?, ... | Pipeline operations (list, get, create, retry, cancel, delete, jobs, variables) |
| `gitlab_job` | `action`, `project`, `job_id`?, `scope`?, `tail`?, ... | Job operations (list, get, log, retry, cancel, play, erase) |
| `gitlab_artifact` | `action`, `project`, `job_id`?, `output_path`?, ... | Artifact management (download, download-file, browse, delete, keep, download-ref) |
| `gitlab_variable` | `action`, `project` OR `group`, `key`?, `value`?, ... | CI/CD variables (list, get, create, update, delete) for project or group |
| `gitlab_deploy_key` | `action`, `project`, `key_id`?, `title`?, `key`?, `can_push`? | Deploy key management (list, get, create, update, delete, enable) |
| `gitlab_deploy_token` | `action`, `project` OR `group`, `token_id`?, `name`?, `scopes`?, ... | Deploy token management (list, get, create, delete) - token only shown on create |
| `gitlab_feature_flag` | `action`, `project`, `name`?, `active`?, `strategies`?, ... | Feature flag management (list, get, create, update, delete, user-lists) [Premium] |

*Notes: `port` defaults to 8765. `preset` can be trusted/sandboxed (yolo is REPL-only). Clipboard `scope` can be agent/project/system (agent is session-only, project/system are persistent SQLite). GitLab skills require TRUSTED+ and configured GitLab instance. [Premium] skills require GitLab Premium subscription.*

---

## Context System

### Context Loading

Context is loaded from multiple directory layers and merged together. Each layer extends the previous one.

#### Layer Hierarchy

```
LAYER 1a: System Defaults (NEXUS-DEFAULT.md in package - auto-updates)
    ↓
LAYER 1b: Global (~/.nexus3/NEXUS.md - user customizations)
    ↓
LAYER 2: Ancestors (up to N levels above CWD, default 2)
    ↓
LAYER 3: Local (CWD/.nexus3/)
```

#### Instruction File Priority

Each non-global layer searches for instruction files using a configurable priority list. First file found wins per layer:

```json
"instruction_files": ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
```

Each filename checks tool-convention directories before project root:

| Filename | Locations checked (in order) |
|----------|------------------------------|
| `NEXUS.md` | `.nexus3/` → `./` |
| `AGENTS.md` | `.nexus3/` → `.agents/` → `./` |
| `CLAUDE.md` | `.nexus3/` → `.claude/` → `.agents/` → `./` |
| `README.md` | `./` only (wrapped with documentation boundaries) |

**Global layer (~/.nexus3/) is exempt** — always loads `NEXUS.md`.

#### Directory Structure

```
nexus3/defaults/              # Package (auto-updates with upgrades)
├── NEXUS-DEFAULT.md          # System docs, tools, permissions (ALWAYS loaded)
└── NEXUS.md                  # Template (copied to ~/.nexus3/ on init)

~/.nexus3/                    # Global (user customizations)
├── NEXUS.md                  # User's custom instructions (always NEXUS.md)
├── config.json               # Personal configuration
└── mcp.json                  # Personal MCP servers

./parent/.nexus3/             # Ancestor (1 level up)
├── AGENTS.md                 # Or NEXUS.md, CLAUDE.md — per priority list
└── config.json

./.nexus3/                    # Local (CWD)
├── AGENTS.md                 # Or NEXUS.md, CLAUDE.md — per priority list
├── config.json               # Project config overrides
└── mcp.json                  # Project MCP servers
```

#### Split Context Design

- **NEXUS-DEFAULT.md** (package only): Contains tool docs, permissions, limits - auto-updates with package upgrades
- **Instruction files** (user's): Custom instructions in NEXUS.md, AGENTS.md, or CLAUDE.md - preserved across upgrades

This split ensures users get new tool documentation automatically while keeping their customizations safe.

#### Configuration Merging

- **Configs**: Deep merged (local keys override global, unspecified keys preserved)
- **Instruction files**: All layers included with labeled sections (first-found per layer)
- **MCP servers**: Same name = local wins

#### Subagent Context Inheritance

Subagents created with `cwd` parameter get:
1. Their cwd's instruction file (found via priority search)
2. Parent's context (non-redundantly)

#### Init Commands

```bash
# Initialize global config
nexus3 --init-global           # Create ~/.nexus3/ with defaults
nexus3 --init-global-force     # Overwrite existing

# Initialize local config (REPL)
/init                         # Create ./.nexus3/ with AGENTS.md (default)
/init NEXUS.md                # Create ./.nexus3/ with NEXUS.md
/init CLAUDE.md               # Create ./.nexus3/ with CLAUDE.md
/init --force                 # Overwrite existing
/init --global                # Initialize ~/.nexus3/ instead
```

#### Context Config Options

```json
{
  "context": {
    "ancestor_depth": 2,       // How many parent dirs to check (0-10)
    "instruction_files": ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
  }
}
```

### Context Compaction

Context compaction summarizes old conversation history via LLM to reclaim token space while preserving essential information.

#### How It Works

1. **Trigger**: Compaction runs when `used_tokens > trigger_threshold * available_tokens` (default 90%)
2. **Preserve recent**: The most recent messages (controlled by `recent_preserve_ratio`) are kept verbatim
3. **Summarize old**: Older messages are sent to a fast model (default: claude-haiku) for summarization
4. **Budget**: Summary is constrained to `summary_budget_ratio` of available tokens (default 25%)
5. **System prompt reload**: During compaction, NEXUS.md is re-read, picking up any changes

#### Configuration Options (`CompactionConfig`)

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable automatic compaction |
| `model` | `"anthropic/claude-haiku"` | Model for summarization |
| `summary_budget_ratio` | `0.25` | Max tokens for summary (fraction of available) |
| `recent_preserve_ratio` | `0.25` | Recent messages to preserve (fraction of available) |
| `trigger_threshold` | `0.9` | Trigger when usage exceeds this fraction |

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

#### Commands

```bash
/compact              # Manual compaction (even if below threshold)
```

#### Key Benefits

- **Longer sessions**: Reclaim space without losing context
- **System prompt updates**: Changes to NEXUS.md apply on next compaction
- **Timestamped summaries**: Each summary includes when it was generated
- **Configurable**: Tune thresholds for your use case

### Temporal Context

Agents always have accurate temporal awareness through three timestamp mechanisms:

| Timestamp | When Set | Location | Purpose |
|-----------|----------|----------|---------|
| **Current date/time** | Every request | System prompt | Always accurate - agents know "now" |
| **Session start** | Agent creation | First message in history | Marks when session began |
| **Compaction** | On summary | Summary prefix | Indicates when history was summarized |

Example session start messages:
```
[Session started: 2026-01-13 14:30 (local)]
[Session started: 2026-01-13 14:30 (local) | Agent: worker-1 | Preset: sandboxed | CWD: /home/user/project]
[Session started: 2026-01-13 14:30 (local) | Agent: main | Preset: trusted | CWD: /home/user/project | Writes: CWD unrestricted, elsewhere with user confirmation]
```

Example compaction summary header:
```
[CONTEXT SUMMARY - Generated: 2026-01-13 16:45]
```

### Git Repository Context

When an agent's CWD is inside a git repository, git context is automatically detected and injected into the system prompt. This gives agents awareness of the repository state without needing to run git commands.

Example injection:
```
Git repository detected in CWD.
  Branch: main
  Status: 3 staged, 2 modified, 1 untracked, 2 stashes
  Last commit: abc1234 fix login bug
  Remote: origin → github.com/user/repo
```

**Refresh triggers:**

| Event | Description |
|-------|-------------|
| Agent creation | Initial git context on startup |
| Session restore | Refresh on `--resume` or saved session load |
| CWD change | `/cwd` updates git context for new directory |
| Tool batch completion | Refreshed if any tool could modify git state |
| Context compaction | Refreshed alongside system prompt reload |
| Config changes | `/model`, `/prompt`, `/gitlab on\|off` |

**Properties:**
- Hard-capped at 500 characters
- Credentials stripped from remote URLs
- Returns nothing (no injection) if not a git repo
- Stash count and worktrees only shown when non-zero

---

## Permissions and Security

### Permission System

#### Built-in Presets

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations (REPL-only) |
| `trusted` | TRUSTED | Confirmations for destructive actions |
| `sandboxed` | SANDBOXED | CWD only, no network, limited nexus tools (default for RPC) |

#### Target Restrictions

Some tools support `allowed_targets` restrictions that limit which agents they can communicate with:

| Restriction | Meaning |
|-------------|---------|
| `None` | No restriction - can target any agent |
| `"parent"` | Can only target the agent's parent (who created it) |
| `"children"` | Can only target agents this one created |
| `"family"` | Can target parent OR children |
| `["id1", "id2"]` | Explicit allowlist of agent IDs |

This is used by `nexus_send`, `nexus_status`, `nexus_cancel`, and `nexus_destroy` to control inter-agent communication.

#### RPC Agent Permission Quirks (IMPORTANT)

**These behaviors are intentional security defaults for RPC-created agents:**

1. **Default agent is sandboxed**: When creating agents via RPC without specifying a preset, they default to `sandboxed` (NOT `trusted`). This is intentional - programmatic agents should be least-privileged by default.

2. **Sandboxed agents can only read in their cwd**: A sandboxed agent's `allowed_paths` is set to `[cwd]` only. They cannot read files outside their working directory.

3. **Sandboxed agents cannot write unless given explicit write paths**: By default, sandboxed agents have all write tools (`write_file`, `edit_file`, `append_file`, `regex_replace`, etc.) **disabled**. To enable writes, use `--write-path` (CLI) or `allowed_write_paths` (RPC JSON):
   ```bash
   nexus3 rpc create worker --cwd /tmp/sandbox --write-path /tmp/sandbox
   ```

4. **Trusted agents must be created explicitly**: To get a trusted agent, you must pass `--preset trusted` explicitly. Trusted is not the default for RPC.

5. **Trusted agents in RPC mode**: Can read anywhere, but destructive operations follow the same confirmation logic (which auto-allows within CWD in non-interactive mode).

6. **YOLO is REPL-only**: You CANNOT create a yolo agent via RPC (enforced by RPC create validation and kernel-authoritative create authorization). YOLO agents can only be created in the interactive REPL. Additionally, RPC `send` to YOLO agents is blocked unless the REPL is actively connected to that agent. If a user creates a YOLO agent in REPL, switches to another agent, then tries `nexus3 rpc send` to the YOLO agent, it fails with "Cannot send to YOLO agent - no REPL connected". This ensures YOLO operations always have active user supervision.

7. **Trusted agents can only create sandboxed subagents**: A trusted agent cannot spawn another trusted agent - all subagents are sandboxed (ceiling enforcement).

8. **Sandboxed agents have limited nexus tools**: Most nexus tools (`nexus_create`, `nexus_destroy`, `nexus_status`, `nexus_cancel`, `nexus_shutdown`) are disabled for sandboxed agents. However, **`nexus_send` IS enabled with `allowed_targets="parent"`** - sandboxed agents can send messages back to their parent agent to report results. They cannot message any other agent.

9. **Subagent cwd restrictions depend on parent level**: For SANDBOXED parents, the child's `cwd` must be within the parent's `cwd` (prevents privilege escalation). TRUSTED and YOLO parents can create subagents at any CWD since they already have potential access to all paths.

10. **Subagent write paths must be within parent's scope**: For SANDBOXED parents, `allowed_write_paths` must be within the parent's `cwd`. TRUSTED and YOLO parents can grant write access to any path since they already have broader access.

11. **Subagent cwd defaults to parent's cwd**: If no `cwd` is specified when creating a subagent, it inherits the parent's `cwd` (not the server process's cwd).

**Example secure agent creation:**
```bash
# Read-only agent (default) - can only read in its cwd
nexus3 rpc create reader --cwd /path/to/project

# Agent with write access to specific directory
nexus3 rpc create writer --cwd /path/to/project --write-path /path/to/project/output

# Trusted agent (explicit - use with care)
nexus3 rpc create coordinator --preset trusted
```

#### Key Features

- **Per-tool configuration**: Enable/disable tools, per-tool paths, per-tool timeouts
- **Permission presets**: Named configurations loaded from config or built-in
- **Ceiling inheritance**: Subagents cannot exceed parent permissions
- **Confirmation prompts**: TRUSTED mode prompts for destructive actions in REPL

#### Commands

```bash
/permissions              # Show current permissions
/permissions trusted      # Change preset (within ceiling; preserves inherited session state)
/permissions --disable write_file   # Disable a tool
/permissions --list-tools           # List tool status
```

### Security Hardening

Comprehensive security hardening completed January 2026:

- **Permission system**: Ceiling enforcement, fail-closed defaults, path validation
- **RPC hardening**: Token auth, header limits, SSRF protection, symlink defense
- **Process isolation**: Process group kills on timeout, env sanitization
- **Input validation**: URL validation, agent ID validation, MCP protocol hardening
- **Output sanitization**: Terminal escape stripping, Rich markup escaping, secrets redaction
- **MCP hardening** (added 2026-01-27):
  - SSRF redirect bypass prevention (`follow_redirects=False`)
  - MCP output sanitization via `sanitize_for_display()`
  - Response size limits (10MB max via `MAX_MCP_OUTPUT_SIZE`)
  - Config error sanitization (no secret leakage in validation errors)
  - Session ID validation (alphanumeric only, 256 char max)
- **Windows compatibility** (added 2026-01-28):
  - Error path sanitization for Windows paths (C:\Users\..., UNC, domain\user)
  - Cross-platform process tree termination (taskkill /T /F fallback)
  - Environment variable sanitization includes Windows-specific vars
  - CREATE_NO_WINDOW subprocess flag prevents window flashing

**Test coverage**: 3400+ tests including 770+ security-specific tests.

### Windows Compatibility

#### Known Windows Security Limitations

These are documented limitations, not bugs:

| Issue | Impact | Mitigation |
|-------|--------|------------|
| `os.chmod()` no-op | Session files, tokens may be readable by other users | Restrict home directory access |
| Symlink detection | `is_symlink()` misses junctions/reparse points | Symlink attack assumptions weaker |
| Permission bits | `S_IRWXG\|S_IRWXO` checks meaningless | ACL-based validation not implemented |

#### Shell Detection

NEXUS3 detects the Windows shell environment at startup and adapts its output accordingly.

| Shell | Detection | ANSI Support | Unicode | Notes |
|-------|-----------|--------------|---------|-------|
| Windows Terminal | `WT_SESSION` env var | Full | Full | Best experience |
| PowerShell 7+ | Via Windows Terminal | Full | Full | |
| Git Bash | `MSYSTEM` env var | Full | Full | MSYS2 environment; standalone prompt input has ESC/paste limitations |
| PowerShell 5.1 | `PSModulePath` set | Limited | Limited | Legacy mode |
| CMD.exe | `COMSPEC` check | None | None | Plain text only |

When running in CMD.exe or PowerShell 5.1, NEXUS3 displays a warning suggesting better alternatives. Users can suppress these by running in Windows Terminal.

When running in standalone Git Bash, NEXUS3 now warns that live ESC cancellation is unavailable there and that multiline paste may submit early; use Windows Terminal/PowerShell for the best interactive behavior, or use prompt-toolkit's external-editor fallback (`C-X C-E` in the default Emacs key mode).

For proper UTF-8 display, the console should use code page 65001. NEXUS3 warns if a different code page is detected. Run `chcp 65001` before starting NEXUS3 to fix character display issues.

#### Key Functions

- `detect_windows_shell()` - Returns WindowsShell enum
- `supports_ansi()` - Check ANSI escape support
- `supports_unicode()` - Check Unicode box drawing support
- `check_console_codepage()` - Get current code page

---

## Configuration Reference

```
~/.nexus3/
├── config.json      # Global config
├── NEXUS.md         # Personal system prompt
├── mcp.json         # Personal MCP servers
├── rpc.token        # Auto-generated RPC token (default port)
├── rpc-{port}.token # Port-specific RPC tokens
├── sessions/        # Saved session files (JSON)
├── last-session.json  # Auto-saved for --resume
├── last-session-name  # Name of last session
└── logs/
    └── server.log   # Server lifecycle events (rotating, 5MB x 3 files)

./NEXUS.md           # Project system prompt (overrides personal)
.nexus3/logs/        # Session logs (gitignored)
├── server.log       # Server lifecycle events when started from this directory
└── <session-id>/    # Per-session conversation logs
    ├── session.db   # SQLite database of messages
    ├── context.md   # Markdown transcript
    ├── verbose.md   # Debug output (if -V enabled)
    └── raw.jsonl    # Raw API JSON (if --raw-log enabled)
```

### Server Logging

Server lifecycle events are logged to `.nexus3/logs/server.log`:

| Event | Log Level | Example |
|-------|-----------|---------|
| Server start | INFO | `JSON-RPC HTTP server running at http://127.0.0.1:8765/` |
| Agent created | INFO | `Agent created: worker-1 (preset=trusted, cwd=/path, model=gpt)` |
| Agent destroyed | INFO | `Agent destroyed: worker-1 (by external)` |
| Shutdown requested | INFO | `Server shutdown requested` |
| Idle timeout | INFO | `Idle timeout reached (1800s without RPC activity), shutting down` |
| Server stopped | INFO | `HTTP server stopped` |

**Log file rotation**: Max 5MB per file, 3 backup files (`server.log.1`, `.2`, `.3`)

**Console output**:
- Default: WARNING+ only
- With `--verbose`: DEBUG+

Use `tail -f .nexus3/logs/server.log` to monitor server activity in real-time.

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

### Prompt Caching

NEXUS3 supports prompt caching to reduce costs (~90% savings on cached tokens):

| Provider | Status | Config Required |
|----------|--------|-----------------|
| Anthropic | Full support | Automatic (enabled by default) |
| OpenAI | Full support | None (automatic) |
| Azure | Full support | None (automatic) |
| OpenRouter | Pass-through | Automatic for Anthropic models |
| Ollama/vLLM | No support | N/A (local) |

#### Cache-Optimized Message Structure

Dynamic content (datetime, git status, clipboard) is separated from the static system prompt to maximize cache hits:

```
[SYSTEM: static instructions/tool docs, cache_control: ephemeral]  ← always cached
[USER1, ASSISTANT1, ..., USERN-1, cache_control: ephemeral]        ← conversation prefix cached
[USERN + <session-context>datetime/git/clipboard</session-context>] ← only new turn uncached
```

- **System prompt**: Purely static (instructions, tool docs, environment). Cached via `cache_control: ephemeral` (Anthropic) or automatic prefix matching (OpenAI/Azure).
- **Dynamic context**: Current datetime, git status, and clipboard entries are injected as a `<session-context>` block into the last user-facing message. This keeps the system prompt and conversation history cacheable.
- **Conversation cache breakpoint**: For Anthropic, a second `cache_control` marker is placed on the penultimate user message, caching the entire conversation prefix through the previous turn.

Caching is enabled by default. To disable for a specific provider:

```json
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "prompt_caching": false
    }
  }
}
```

Cache metrics are logged at DEBUG level (visible with `-v` flag).

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
  "default_model": "haiku",

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
- `default_model`: Which model alias to use by default (e.g., `"haiku"`)
- `models[].provider`: Optional - reference a named provider (first matching provider used if omitted)
- Backwards compatible: `provider` field still works for single-provider setups

**Implementation (ProviderRegistry):**
- Lazy initialization: Providers created on first use (avoids connecting to unused APIs)
- Per-model routing: `resolve_model()` returns provider name alongside model settings
- SharedComponents holds registry instead of single provider

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

### GitLab Configuration

GitLab tools require pre-configured instances in `~/.nexus3/config.json` or `.nexus3/config.json`:

```json
{
  "gitlab": {
    "instances": {
      "default": {
        "url": "https://gitlab.com",
        "token_env": "GITLAB_TOKEN",
        "username": "your-gitlab-username",
        "email": "you@example.com",
        "user_id": 12345
      },
      "work": {
        "url": "https://gitlab.mycompany.com",
        "token_env": "GITLAB_WORK_TOKEN",
        "username": "your-work-username"
      }
    },
    "default_instance": "default"
  }
}
```

**Token setup:**
- Create a GitLab Personal Access Token with `api` scope
- Store in environment variable (e.g., `GITLAB_TOKEN`)
- Reference via `token_env` in config (recommended) or `token` field directly

**Identity setup (optional but recommended):**
- Add `username` and optionally `email`/`user_id` to each instance
- Enables `"me"` shorthand in assignees, reviewers, and list filters
- If not configured, `"me"` falls back to `GET /user` API call
- Use `gitlab_repo` action `whoami` to verify your configured identity

**Permission requirements:**
- TRUSTED or YOLO level required (SANDBOXED blocked)
- Read-only actions: No confirmation needed
- Destructive actions: Confirmation in TRUSTED mode (stored per skill@instance)

### Clipboard Configuration

```json
{
  "clipboard": {
    "enabled": true,
    "inject_into_context": true,
    "max_injected_entries": 10,  // per scope
    "show_source_in_injection": true,
    "max_entry_bytes": 1048576,
    "warn_entry_bytes": 102400,
    "default_ttl_seconds": null
  }
}
```

**Scope permissions by preset:**
- `yolo`: Full access to agent/project/system scopes
- `trusted`: Read/write agent+project, read-only system
- `sandboxed`: Agent scope only (in-memory, session-only)

<!-- PART III: DEVELOPMENT GUIDE -->

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
| Explicit Encoding | Use explicit UTF-8 encoding. Text-edit tools must fail closed on undecodable input; use `patch` byte-strict for byte-sensitive edits. |
| Test E2E | Every feature gets an integration test. |
| **Live Test** | **Automated tests are not sufficient. Always live test with real NEXUS3 agents before committing changes.** |
| Document | Each phase updates this file and module READMEs. |
| No Dead Code | Delete unused code. Run `ruff check --select F401`. |
| **Plan First** | **Non-trivial features require a plan in `docs/`. See Feature Planning SOP below.** |
| **Commit Often** | **Commit after each phase/logical unit. Don't wait for "everything done."** |
| **Branch per Plan** | **One feature branch per plan. Merge only after checklist complete + user sign-off.** |
| **Don't Revert Unrelated Changes** | **When committing, only stage files YOU modified. NEVER use `git checkout` or `git restore` on files you didn't change - they may contain the user's work from other tasks.** |
| **Zero Lint/Test Failures** | **All tests and lints must pass 100% at all times. If a failure is introduced and cannot be immediately fixed, document it in the Known Failures section of this file with: what fails, why, and the plan to fix it. No silent regressions.** |

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

### Version Control

#### Commit Frequency

Commit after each completed phase or logical unit. Don't wait for "everything done."

- **After each checklist phase** (P1, P2, etc.) - phases are designed as atomic units
- **Before switching files/modules** - if you've been working in `skill/` and need to touch `session/`, commit first
- **When tests pass** - green tests = safe checkpoint
- **Before risky changes** - about to refactor? commit the working state first
- **Rule of thumb**: if you'd be upset losing the work, commit it

Commit messages should reference the plan and checklist item when applicable:
```
feat(clipboard): implement ClipboardManager (CLIPBOARD-PLAN P1.4)
```

#### Branching

- **One branch per plan** - `feature/<plan-name>` (e.g., `feature/clipboard`, `feature/sandboxed-parent-send`)
- **Branch before starting implementation** - not during exploration/planning
- **Keep branches focused** - don't mix unrelated changes

#### Pushing

- **Feature branches:** Push after each commit - provides backup, enables CI, no downside
- **Main/master:** Only via PR merge, never direct push

#### Merging

- **Merge when:** Plan checklist complete + tests pass + live testing done + user sign-off
- **Don't merge:** Partial implementations, broken tests, untested changes
- **Merge strategy:** Squash for small plans (clean history), regular merge for large plans (preserve bisectability)

### Feature Planning SOP

All non-trivial features should follow this planning process. Plans live in `docs/` as markdown files.

**Reference examples:**
- `docs/plans/examples/EXAMPLE-PLAN-SIMPLE.md` - Template for focused single-feature plans
- `docs/plans/examples/EXAMPLE-PLAN-COMPLEX.md` - Comprehensive example for large multi-phase features

#### Planning Process

| Phase | Description |
|-------|-------------|
| 1. Intent | Discuss what the feature should accomplish, user-facing behavior |
| 2. Explore | Research relevant code with subagents, understand existing patterns |
| 3. Feasibility | Discuss technical approach, identify blockers or concerns |
| 4. Scope | Define what's included, deferred, and explicitly excluded |
| 5. General Plan | High-level architecture, design decisions with rationale |
| 6. Validate | Subagent validates plan against actual codebase patterns |
| 7. Detailed Plan | Concrete implementation with copy-paste code, exact file paths |
| 8. Validate | Subagent confirms patterns, identifies discrepancies |
| 9. Checklist | Implementation checklist with task IDs for parallel execution |
| 10. Documentation | Document what changed for users and future developers |

**CRITICAL: Update plan file after EVERY phase.** Planning sessions can be interrupted (context limits, timeouts, user breaks). Write findings to `docs/<PLAN-NAME>.md` incrementally:

- After Phase 1: Create plan file with Overview section
- After Phase 2: Add exploration findings, file locations discovered
- After Phase 3: Add feasibility notes, blockers identified
- After Phase 4: Add Scope section (included/deferred/excluded)
- After each subsequent phase: Update relevant sections

This ensures work is preserved even if the session ends unexpectedly. A partial plan with 4 phases completed is far better than losing everything.

#### Plan Document Structure

```markdown
# Plan: Feature Name

## Overview
Brief description, current state, goal.

## Scope
### Included in v1
### Deferred to Future
### Explicitly Excluded

## Design Decisions
| Question | Decision | Rationale |
Record WHY choices were made, not just what.

## Security Considerations (when relevant)
Network access, permissions, file I/O implications.

## Architecture
Directory structure, base classes, patterns.

## Implementation Details
Concrete code, exact file paths, integration points.

## Testing Strategy
Unit tests, integration tests, live testing plan.

## Open Questions
Unresolved decisions that need input.

## Codebase Validation Notes
Results from subagent validation against actual code.

## Implementation Checklist
Phased checklist with task IDs (P1.1, P1.2, etc.)
Must include a Documentation phase (see below).

## Quick Reference
File locations table, API endpoints, etc.
```

#### Implementation Checklist Format

Checklists are designed for task agent parallelization:

```markdown
### Phase 1: Foundation (Required First)
- [ ] **P1.1** Create directory structure
- [ ] **P1.2** Implement core types
- [ ] **P1.3** Implement base class (requires P1.2)

### Phase 2: Features (After Phase 1)
- [ ] **P2.1** Implement feature A (can parallel with P2.2)
- [ ] **P2.2** Implement feature B (can parallel with P2.1)
- [ ] **P2.3** Integration (requires P2.1, P2.2)
```

**Parallelization rules:**
- Items in the same phase can run in parallel unless noted
- Different phases are sequential (Phase 2 waits for Phase 1)
- Note dependencies explicitly: `(requires P1.3)` or `(can parallel with P2.1)`
- Avoid multiple agents editing the same file simultaneously

#### Validation with Subagents

Before finalizing plans, use Claude Code subagents to validate assumptions:

```bash
# Create a research agent
.venv/bin/python -m nexus3 rpc create validator --preset trusted --port 9000

# Send validation task
.venv/bin/python -m nexus3 rpc send validator "Validate this plan against the codebase:
1. Check if FileSkill exists in nexus3/skill/base.py
2. Verify the factory pattern matches what the plan describes
3. Confirm ToolResult is constructed with output=/error= kwargs
Report any discrepancies." --port 9000
```

Add findings to the "Codebase Validation Notes" section with corrections applied.

#### Documentation Phase (Required)

Every implementation checklist MUST include a documentation phase. Documentation ensures users can discover and use new features, and future developers can understand what changed.

**What to document:**

| Type | When | What to Update |
|------|------|----------------|
| **User-facing features** | New commands, skills, CLI flags | Main README, `CLAUDE.md` (relevant sections) |
| **Module changes** | New/modified modules | Module's `README.md`, type signatures |
| **Skills** | New or modified skills | Skill's `description` property, parameter descriptions, `CLAUDE.md` Built-in Skills table |
| **Commands** | New or modified REPL/CLI commands | Command help data, `CLAUDE.md` Commands Reference |
| **Configuration** | New config options | `CLAUDE.md` Configuration section, example configs |
| **Permissions** | Changes to presets or tool permissions | `CLAUDE.md` Permission System section |

**Documentation checklist items should be explicit:**

```markdown
### Phase N: Documentation (After Implementation Complete)
- [ ] **PN.1** Update `CLAUDE.md` [specific section] with [specific change]
- [ ] **PN.2** Update `nexus3/[module]/README.md` with [specific change]
- [ ] **PN.3** Update skill description property to document [behavior]
- [ ] **PN.4** Update command help text for [command]
```

**Not required:**
- Adding JSDoc/docstrings to every function (only document non-obvious behavior)
- Creating new markdown files for minor features
- Updating docs for internal refactors with no user-facing changes

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

### Current Status

As of 2026-02-25: **All tests, lints, and type checks pass 100%.**

- `ruff check nexus3/` — 0 errors
- `mypy nexus3/` — 0 errors (192 source files)
- `pytest tests/` — 3742 passed, 3 skipped (2 require API key, 1 Windows-only)

Architecture execution running status (2026-03-09, Plan C hygiene closeout + keep-alive wave):
- Plan C service-container immutability follow-on is now committed:
  - `5c0e843` (pool/repl/session runtime migration to typed mutators/accessors)
  - `8143afe` (runtime register compatibility scoping via `register_runtime_compat(...)`)
- Plan C fixture/test-double modernization follow-up is completed in WSL:
  - retired remaining legacy `MockServiceContainer` doubles in:
    `tests/unit/test_new_skills.py`,
    `tests/unit/test_regex_replace_skill.py`,
    `tests/unit/test_skill_enhancements.py`,
    `tests/unit/test_git_skill.py`,
    `tests/unit/skill/test_bash_windows_behavior.py`,
    `tests/security/test_p2_defense_in_depth.py`.
  - each file now uses real `ServiceContainer` setup helpers and typed
    `set_cwd(...)` runtime mutation where cwd is configured.
  - focused validation:
    `.venv/bin/pytest -q tests/unit/test_new_skills.py tests/unit/test_regex_replace_skill.py tests/unit/test_skill_enhancements.py tests/unit/test_git_skill.py tests/unit/skill/test_bash_windows_behavior.py tests/security/test_p2_defense_in_depth.py`
    (`105 passed`).
- Plan C runtime-key test-setup hygiene follow-up is completed in WSL:
  - migrated runtime-key test wiring in:
    `tests/unit/skill/test_concat_files.py`,
    `tests/unit/skill/test_glob_search.py`,
    `tests/unit/skill/test_grep_gateway.py`,
    `tests/unit/skill/test_outline.py`,
    `tests/unit/core/test_filesystem_access.py`,
    `tests/unit/skill/test_patch.py`.
  - runtime-key writes now use typed/compat APIs:
    - `set_cwd(...)` for cwd setup
    - `register_runtime_compat("allowed_paths", ...)` for allowed-path setup
  - focused validation:
    `.venv/bin/pytest -q tests/unit/skill/test_concat_files.py tests/unit/skill/test_glob_search.py tests/unit/skill/test_grep_gateway.py tests/unit/skill/test_outline.py tests/unit/core/test_filesystem_access.py tests/unit/skill/test_patch.py`
    (`214 passed`).
- Plan C runtime-key test-setup hygiene follow-up (wave 2) is completed in WSL:
  - migrated runtime-key test wiring in:
    `tests/unit/skill/test_clipboard_skills.py`,
    `tests/unit/skill/test_clipboard_extras.py`,
    `tests/unit/skill/test_clipboard_manage.py`,
    `tests/unit/skill/test_edit_file.py`,
    `tests/unit/skill/test_edit_lines.py`,
    `tests/unit/skill/test_skill_validation.py`.
  - runtime-key writes now use typed/compat APIs:
    - `set_cwd(...)` for cwd setup
    - `register_runtime_compat("allowed_paths", ...)` for allowed-path setup
      where applicable.
  - focused validation:
    `.venv/bin/pytest -q tests/unit/skill/test_clipboard_skills.py tests/unit/skill/test_clipboard_extras.py tests/unit/skill/test_clipboard_manage.py tests/unit/skill/test_edit_file.py tests/unit/skill/test_edit_lines.py tests/unit/skill/test_skill_validation.py`
    (`154 passed`).
- Plan C runtime-key test-setup hygiene closeout wave is completed in WSL:
  - migrated remaining non-compat direct runtime-key test wiring in:
    `tests/security/test_arch_a2_path_decision.py`,
    `tests/security/test_p1_process_group_kill.py`,
    `tests/unit/session/test_session_cancellation.py`,
    `tests/unit/skill/test_nexus_create.py`,
    `tests/unit/skill/vcs/conftest.py`,
    `tests/unit/skill/vcs/test_gitlab_skills.py`,
    `tests/unit/test_git_skill.py`,
    `tests/unit/test_gitlab_toggle.py`,
    `tests/unit/test_new_skills.py`,
    `tests/unit/test_regex_replace_skill.py`,
    `tests/unit/test_skill_registry.py`.
  - runtime-key writes now use typed/compat APIs:
    - `set_permissions(...)` for permissions setup
    - `set_cwd(...)` for cwd setup
    - `register_runtime_compat("allowed_paths", ...)` for allowed-path setup
  - `tests/unit/test_gitlab_toggle.py` now uses a `ServiceContainer`-backed
    mock service shim so command tests retain typed accessor parity.
  - focused validation:
    `.venv/bin/ruff check tests/integration/test_clipboard.py tests/integration/test_file_editing_skills.py tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py tests/security/test_arch_a2_path_decision.py tests/security/test_p1_process_group_kill.py tests/unit/session/test_session_cancellation.py tests/unit/skill/test_nexus_create.py tests/unit/skill/vcs/conftest.py tests/unit/skill/vcs/test_gitlab_skills.py tests/unit/test_git_skill.py tests/unit/test_gitlab_toggle.py tests/unit/test_new_skills.py tests/unit/test_regex_replace_skill.py tests/unit/test_skill_registry.py`
    passed;
    `.venv/bin/pytest -q tests/security/test_arch_a2_path_decision.py tests/security/test_p1_process_group_kill.py tests/unit/session/test_session_cancellation.py tests/unit/skill/test_nexus_create.py tests/unit/skill/vcs/test_gitlab_skills.py tests/unit/test_git_skill.py tests/unit/test_gitlab_toggle.py tests/unit/test_new_skills.py tests/unit/test_regex_replace_skill.py tests/unit/test_skill_registry.py`
    (`279 passed`);
    `.venv/bin/pytest -q tests/integration/test_clipboard.py tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py`
    (`65 passed`);
    `timeout 180 .venv/bin/pytest -q tests/integration/test_file_editing_skills.py`
    stalled without output in sandbox; unsandboxed rerun
    `.venv/bin/pytest -q tests/integration/test_file_editing_skills.py`
    passed (`17 passed`).
- Plan H shim-retirement closeout for remaining `create_agent` compatibility
  remaps is committed in the current closeout wave:
  - `nexus3/rpc/global_dispatcher.py`: removed remaining custom create-agent
    field wording branches; malformed fields now surface canonical schema
    diagnostics.
  - `tests/unit/rpc/test_schema_ingress_wiring.py`: focused expectations
    updated for canonical schema messages.
  - retained explicit diagnostics in `protocol.py`, `dispatch_core.py`, and
    `dispatcher.py` are intentionally preserved invariants (strict envelope
    parity and method-specific send/get_messages error clarity).
- Provider keep-alive investigation kickoff is committed as `05ffb84`:
  - `nexus3/provider/base.py`: stale keep-alive transport classification +
    bounded cached-client reset/retry within existing retry loop.
  - `tests/unit/provider/test_keepalive_recovery.py`: focused sync/streaming
    stale-recovery regressions and max-retry bound checks.
  - `scripts/diagnose-empty-stream.sh`: Step 10 now emits structured
    `10-keepalive-evidence.json` alongside textual logs.
  - operational defer note (2026-03-09, WSL): real-endpoint evidence capture
    is explicitly deferred pending endpoint credentials/config availability in
    the current WSL environment.
  - this is an operational defer only (no code rollback).
  - reminder checklist for resumption:
    1. configure one known-problematic endpoint+model and one known-good
       endpoint+model.
    2. set required API key environment variables for both endpoints.
    3. run `scripts/diagnose-empty-stream.sh` Step 10 flow.
    4. archive `10-keepalive-evidence.json` artifacts and link run IDs in
       status docs (`AGENTS.md`, `CLAUDE.md`, and milestone/plan docs).
- DRY cleanup P2 (default-port consolidation) completed in WSL:
  - canonical resolver added in `nexus3/core/constants.py`
    (`DEFAULT_SERVER_PORT`, `get_default_server_port()`).
  - duplicate default-port resolution in `nexus3/client.py`,
    `nexus3/cli/client_commands.py`, and `nexus3/skill/base.py` now delegates
    to the canonical resolver.
  - `get_rpc_token_path()` now uses `DEFAULT_SERVER_PORT` instead of a
    hardcoded literal.
  - focused validation passed:
    - `.venv/bin/ruff check nexus3/core/constants.py nexus3/client.py nexus3/cli/client_commands.py nexus3/skill/base.py`
    - `.venv/bin/mypy nexus3/core/constants.py nexus3/client.py nexus3/cli/client_commands.py nexus3/skill/base.py`
    - `.venv/bin/pytest -q tests/unit/test_client.py tests/unit/cli/test_client_commands_safe_sink.py tests/unit/test_nexus_skill_requester_propagation.py tests/unit/test_auth.py -k "port or default or auto_auth or requester"` (`12 passed, 52 deselected`).
- Structural-refactor wave kickoff is documented in plan status:
  - `docs/plans/STRUCTURAL-REFACTOR-WAVE-PLAN-2026-03-05.md` now includes
    the extraction map (old->new ownership, façade compatibility boundaries,
    and execution order) and has checklist item 1 marked complete.
- Structural-refactor Phase 1A (REPL formatting-helper extraction) is completed:
  - `nexus3/cli/repl_formatting.py` now owns REPL formatting/sanitization helpers.
  - `nexus3/cli/repl.py` remains façade-compatible via helper imports.
- Structural-refactor Phase 1B (REPL runtime/client-discovery + reload extraction)
  is completed:
  - `nexus3/cli/repl_runtime.py` now owns REPL runtime/client-discovery helpers.
  - `nexus3/cli/repl_reload.py` now owns REPL reload helper logic.
  - `nexus3/cli/repl.py` retains façade-compatible symbols/imports.
- Structural-refactor Phase 2A (Session compaction runtime helper extraction)
  is completed:
  - `nexus3/session/compaction_runtime.py` now owns compaction provider and
    summary helper internals.
  - latest wrapper-cleanup wave removed `Session._get_compaction_provider(...)`
    and `Session._generate_summary(...)`; `compact()` now calls
    `compaction_runtime.generate_summary(...)` directly.
  - behavior parity preserved (lazy provider creation, compaction cache
    semantics, logger lifecycle).
- Structural-refactor Phase 2B (Session tool execution primitives extraction)
  is completed:
  - `nexus3/session/tool_runtime.py` now owns extracted tool execution
    primitives.
  - latest Session wrapper-retirement closeout removed
    `Session._execute_skill(...)` and `Session._execute_tools_parallel(...)`.
  - behavior parity preserved (timeout handling, exception mapping, and
    sanitization semantics).
- Structural-refactor Phase 2C (Session permission runtime extraction)
  is completed:
  - `nexus3/session/permission_runtime.py` now owns permission runtime helpers.
  - `_McpLevelAuthorizationAdapter`, `_GitLabLevelAuthorizationAdapter`, and
    internals of `Session._handle_mcp_permissions(...)` /
    `Session._handle_gitlab_permissions(...)` are extracted to runtime helpers.
  - latest Session wrapper-retirement closeout removed
    `Session._handle_mcp_permissions(...)` and
    `Session._handle_gitlab_permissions(...)`; kernelization tests now call
    permission runtime helpers directly.
  - behavior parity preserved (kernel-authoritative decisions and confirmation
    flows).
- Structural-refactor Phase 2D (Session single-tool runtime extraction)
  is completed:
  - `nexus3/session/single_tool_runtime.py` now owns single-tool execution
    runtime helpers.
  - latest Session wrapper-retirement closeout removed
    `Session._execute_single_tool(...)`.
  - behavior parity preserved (permissions fail-closed, enforcer checks and
    confirmation flow including multi-path allowances, skill
    resolution/unknown-skill handling, malformed `_raw_arguments` handling,
    argument validation, effective timeout derivation, and MCP/GitLab
    delegation).
- Structural-refactor Phase 2E (Session streaming runtime extraction)
  is completed:
  - `nexus3/session/streaming_runtime.py` now owns callback-adapter streaming
    runtime helpers.
  - latest wrapper-cleanup wave removed
    `Session._execute_tool_loop_streaming(...)`; `send(...)` / `run_turn(...)`
    now call runtime helpers directly.
  - behavior parity preserved (event->callback mapping and yielded chunk
    semantics unchanged).
- Structural-refactor Phase 2F (Session tool-loop events runtime extraction)
  is completed:
  - `nexus3/session/tool_loop_events_runtime.py` now owns tool-loop event
    execution runtime helpers.
  - latest wrapper-cleanup wave removed
    `Session._execute_tool_loop_events(...)`; `send(...)` / `run_turn(...)`
    now call runtime helpers directly.
  - `send(...)` / `run_turn(...)` now build explicit runtime callables and pass
    them to `execute_tool_loop_events(...)`; the runtime helper now accepts
    explicit `execute_tools_parallel` and `execute_single_tool` callables.
- Structural-refactor Phase 2G (Session turn-entry runtime extraction)
  is completed:
  - `nexus3/session/turn_entry_runtime.py` now owns shared turn-entry
    preflight/reset runtime helpers.
  - `send(...)` and `run_turn(...)` now use `prepare_turn_entry(...)` for the
    shared context-mode preflight/reset path.
  - behavior parity preserved; tool-loop runtime behavior is unchanged in this
    slice.
- Structural-refactor Phase 2H (Session simple-turn runtime extraction)
  is completed:
  - `nexus3/session/simple_turn_runtime.py` now owns shared non-tool simple
    streaming internals used by `send(...)` and `run_turn(...)`.
  - `send(...)` and `run_turn(...)` now delegate non-tool simple paths to
    `execute_simple_send(...)` / `execute_simple_run_turn(...)`.
  - behavior parity preserved (cancellation handling and empty-response
    semantics).
- Structural-refactor Phase 3A (Pool visibility extraction) is completed:
  - `nexus3/rpc/pool_visibility.py` now owns MCP/GitLab visibility adapters and
    helper internals.
  - latest wrapper-cleanup wave removed pool visibility wrappers
    `_is_mcp_visible_for_agent(...)` and `_is_gitlab_visible_for_agent(...)`.
- Structural-refactor Phase 4A (Display no-op override cleanup) is completed:
  - `nexus3/display/theme.py` now exposes `load_theme() -> Theme` only.
  - no-op override argument path was removed with runtime behavior preserved.
  - display README and tests now document/assert the canonical theme-loader
    contract.
- Structural-refactor Phase 3B (Pool create-path extraction foundation) is
  completed:
  - `nexus3/rpc/pool_create.py` now owns create authorization adapter and
    create-path runtime helper foundations.
  - `AgentPool.create(...)`, `create_temp(...)`, and create-authorization
    enforcement now delegate to extracted helpers.
- Structural-refactor Phase 3C (Pool restore-path extraction) is completed:
  - `nexus3/rpc/pool_restore.py` now owns restore runtime helper internals.
  - latest wrapper-cleanup wave removed restore dependency-builder wrappers and
    the `_restore_unlocked(...)` shim from `pool.py`; `pool_restore.get_or_restore(...)`
    and `restore_from_saved(...)` now take `shared` + `runtime` and invoke
    `_restore_unlocked(...)` internally.
- Structural-refactor Phase 3D (Pool lifecycle extraction) is completed:
  - `nexus3/rpc/pool_lifecycle.py` now owns lifecycle internals for
    destroy/capability/accessor paths.
  - latest wrapper-cleanup wave removed `_destroy_unlocked(...)`,
    `_enforce_create_authorization(...)`, and capability-state passthrough
    wrappers in `pool.py`; call sites now wire directly to runtime helpers.
- Focused validation snapshot:
  - passed:
    `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
  - passed:
    `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_formatting.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py`
    (`97 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py`
  - passed:
    `.venv/bin/mypy nexus3/cli/repl.py nexus3/cli/repl_runtime.py nexus3/cli/repl_reload.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/cli/test_repl_safe_sink.py tests/unit/test_repl_commands.py tests/unit/cli/test_connect_lobby_safe_sink.py tests/unit/test_client.py`
    (`125 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_compaction.py tests/unit/test_context_manager.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py`
    (`54 passed`).
  - passed:
    `.venv/bin/pytest -q tests/unit/test_compaction.py tests/unit/test_context_manager.py tests/unit/context/test_graph.py tests/unit/context/test_compiler.py tests/unit/context/test_compile_baseline.py`
    (`75 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_permission_kernelization.py`
    (`54 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py`
    (`30 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_cancellation.py`
    (`54 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py`
    (`30 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py nexus3/session/single_tool_runtime.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/compaction_runtime.py nexus3/session/tool_runtime.py nexus3/session/permission_runtime.py nexus3/session/single_tool_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py tests/unit/session/test_session_cancellation.py`
    (`54 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py`
    (`30 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/streaming_runtime.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/streaming_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py -k "test_tool_call_executes_skill or test_multiple_tool_calls_in_sequence or test_multiple_tool_calls_in_parallel or test_failing_skill_error_in_context or test_max_iterations_prevents_infinite_loop or test_tool_loop_builds_correct_messages"`
    (`6 passed`).
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py -k "test_stale_cancelled_tools_are_dropped or test_cancelled_tool_tail_repaired_before_next_user_turn or test_preflight_repairs_orphaned_tool_batch_before_user_turn or test_preflight_prunes_stale_tool_results_before_user_turn"`
    (`4 passed`).
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py -k "test_cancellation_before_assistant_message_no_orphans or test_cancellation_after_first_tool_adds_remaining_results or test_cancelled_error_during_tool_creates_result"`
    (`3 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py tests/unit/session/test_enforcer.py`
    (`54 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py`
    (`30 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/turn_entry_runtime.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/turn_entry_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py`
    (`12 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_skill_execution.py tests/integration/test_permission_enforcement.py tests/integration/test_chat.py`
    (`40 passed, 2 skipped`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/simple_turn_runtime.py nexus3/session/README.md`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/simple_turn_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/session/test_session_cancellation.py tests/integration/test_chat.py`
    (`22 passed, 2 skipped`).
  - passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_visibility.py`
  - passed:
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_visibility.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/test_pool.py -k "mcp_visibility or gitlab_visibility"`
    (`4 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/display/theme.py nexus3/display/README.md tests/unit/test_display.py`
  - passed:
    `.venv/bin/mypy nexus3/display/theme.py nexus3/cli/repl.py nexus3/display/manager.py nexus3/display/spinner.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/test_display.py tests/unit/display/test_safe_sink.py tests/unit/display/test_escape_sanitization.py`
    (`137 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py`
  - passed:
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_auto_restore.py tests/unit/test_pool.py -k "create_ or create_temp or restore_ or get_or_restore or mcp_visibility or gitlab_visibility"`
    (`43 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py`
    (`51 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py`
  - passed:
    `.venv/bin/mypy nexus3/rpc/pool.py nexus3/rpc/pool_lifecycle.py nexus3/rpc/pool_create.py nexus3/rpc/pool_restore.py nexus3/rpc/pool_visibility.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/rpc/test_pool_create_auth_shadow.py -k "destroy_ or capability or should_shutdown or list_returns_agent_info_dicts or get_returns_ or len_returns_agent_count or contains_checks_agent_id or mcp_visibility or gitlab_visibility or create_ or create_temp or restore_ or get_or_restore"`
    (`70 passed, 30 deselected`).
  - passed:
    `.venv/bin/pytest -q tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py`
    (`62 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py nexus3/session/single_tool_runtime.py nexus3/session/tool_runtime.py nexus3/session/README.md tests/unit/session/test_session_permission_kernelization.py tests/integration/test_permission_enforcement.py`
  - passed:
    `.venv/bin/mypy nexus3/session/session.py nexus3/session/tool_loop_events_runtime.py nexus3/session/single_tool_runtime.py nexus3/session/tool_runtime.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/test_compaction.py tests/unit/session/test_session_cancellation.py tests/unit/session/test_session_permission_kernelization.py tests/unit/test_pool.py tests/unit/test_auto_restore.py tests/unit/rpc/test_pool_create_auth_shadow.py tests/unit/test_agent_api.py tests/unit/test_rpc_dispatcher.py tests/unit/test_global_dispatcher.py`
    (`213 passed`).
  - passed:
    `.venv/bin/pytest -q tests/integration/test_permission_enforcement.py tests/integration/test_skill_execution.py tests/integration/test_chat.py tests/integration/test_permission_inheritance.py tests/integration/test_sandboxed_parent_send.py`
    (`91 passed, 2 skipped`).
  - passed (live smoke):
    `NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000`,
    `.venv/bin/python -m nexus3 rpc create test-agent --port 9000`,
    `.venv/bin/python -m nexus3 rpc send test-agent "describe your permissions and what you can do" --port 9000`,
    `.venv/bin/python -m nexus3 rpc destroy test-agent --port 9000`,
    `.venv/bin/python -m nexus3 rpc shutdown --port 9000`.
  - passed:
    `.venv/bin/ruff check nexus3/rpc/global_dispatcher.py tests/unit/rpc/test_schema_ingress_wiring.py`
  - passed:
    `.venv/bin/mypy nexus3/rpc/global_dispatcher.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/rpc/test_schema_ingress_wiring.py tests/unit/test_client.py tests/unit/test_global_dispatcher.py tests/unit/test_rpc_dispatcher.py`
    (`138 passed`).
  - passed:
    `.venv/bin/ruff check nexus3/provider/base.py tests/unit/provider/test_keepalive_recovery.py`
  - passed:
    `.venv/bin/mypy nexus3/provider/base.py`
  - passed:
    `.venv/bin/pytest -q tests/unit/provider/test_keepalive_recovery.py tests/unit/provider/test_lifecycle.py tests/unit/provider/test_retry_zero.py tests/unit/provider/test_empty_stream.py`
    (`48 passed`).

### Orchestrator Handover Checkpoint (2026-03-09)

- Branch: `feat/arch-overhaul-execution`
- Local state:
  - Plan H Phase 3 canonical diagnostics follow-on is committed as `fd33b01`.
  - Plan H create-agent remap closeout is committed as `a9aaa12`
    (`global_dispatcher.py` + focused ingress tests).
  - Plan C slices 1-3 follow-on is committed as `5c0e843` and `8143afe`.
  - Provider keep-alive kickoff slice is committed as `05ffb84`
    (`base.py`, `test_keepalive_recovery.py`, Step 10 JSON evidence).
  - Structural-refactor Phase 2A/2B/2C/2D/2E/2F/2G/2H + Phase 3A/3B/3C/3D/4A
    slices are complete
    (`compaction_runtime.py`, `tool_runtime.py`, and
    `permission_runtime.py`, `single_tool_runtime.py`,
    `streaming_runtime.py`, `tool_loop_events_runtime.py`,
    `turn_entry_runtime.py`, `simple_turn_runtime.py`, `pool_visibility.py`,
    `pool_create.py`, `pool_restore.py`, `pool_lifecycle.py` extracted;
    wrapper-retirement closeout removed remaining Session wrappers
    `_execute_single_tool(...)`, `_handle_mcp_permissions(...)`,
    `_handle_gitlab_permissions(...)`, `_execute_skill(...)`, and
    `_execute_tools_parallel(...)`; `send(...)` / `run_turn(...)` now build
    explicit runtime callables for `execute_tool_loop_events(...)`, whose
    runtime signature now accepts explicit `execute_tools_parallel` and
    `execute_single_tool` callables; display theme loader contract uses
    `load_theme()` without no-op overrides).
- Concrete resume steps for post-compact continuation:
  1. Keep provider keep-alive real-endpoint evidence operationally deferred
     (2026-03-09) pending endpoint credentials/config availability in the
     current WSL environment (no code rollback).
  2. Configure one known-problematic endpoint+model and one known-good
     endpoint+model.
  3. Set required API key environment variables and run
     `scripts/diagnose-empty-stream.sh` Step 10 flow.
  4. Archive `10-keepalive-evidence.json` artifacts and link provider-evidence
     run IDs in status and plan docs.

### Known Failures

None. If any test or lint failure is introduced and cannot be immediately resolved, document it here with:
- **What** fails (exact test name or lint rule)
- **Why** it fails (root cause)
- **Plan** to fix (who, when, how)

---

## Claude Code Integration

### Running NEXUS3 from Claude Code

The `nexus3` shell alias isn't available when running via Bash tool. **Always use `.venv/bin/python -m nexus3`**:

```bash
# Start headless server (use port 9000 if user has REPL on 8765)
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &

# RPC commands
.venv/bin/python -m nexus3 rpc detect --port 9000
.venv/bin/python -m nexus3 rpc list --port 9000
.venv/bin/python -m nexus3 rpc create worker --port 9000
.venv/bin/python -m nexus3 rpc create worker -M "initial message" --port 9000
.venv/bin/python -m nexus3 rpc send worker "message" --port 9000
.venv/bin/python -m nexus3 rpc status worker --port 9000
.venv/bin/python -m nexus3 rpc destroy worker --port 9000
.venv/bin/python -m nexus3 rpc shutdown --port 9000
```

#### Multi-Turn Usage (Important!)

**Do NOT write shell scripts with multiple steps.** Execute commands one at a time in a multi-turn conversation:

```
✗ BAD: Writing a script that creates agent, sends message, checks status
✓ GOOD: Run create command, see result, then run send command, see result, etc.
```

This allows you to:
- See each command's output before proceeding
- React to errors or unexpected results
- Adjust subsequent commands based on agent responses

#### User-Facing Commands (Reference)

When the user runs commands directly in their terminal, they use the `nexus3` alias:

```bash
nexus3                              # REPL with embedded server
nexus3 --fresh                      # New temp session
nexus3 rpc create worker            # Create agent
nexus3 rpc send worker "message"    # Send message
```

#### Key Behaviors

- **Security:** `--serve` requires `NEXUS_DEV=1` env var (prevents unattended servers)
- **Security:** `nexus3 rpc` commands do NOT auto-start servers
- **Idle timeout:** Embedded server auto-shuts down after 30 min of no RPC activity
- **Port conflicts:** If user has REPL on 8765, use `--port 9000` for headless servers
- All commands support `--api-key KEY` for explicit auth (auto-discovered by default)

### Dogfooding: Use NEXUS Subagents

**When working on this codebase, use NEXUS3 subagents for research and exploration tasks.** This is dogfooding - we use our own product.

#### Starting the Server

```bash
# Start headless server (use port 9000 to avoid conflict with user's REPL on 8765)
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &

# Or check if already running
.venv/bin/python -m nexus3 rpc detect --port 9000
```

#### Creating and Using Research Agents

```bash
# Create a research agent (trusted can read anywhere, writes within CWD)
.venv/bin/python -m nexus3 rpc create researcher --preset trusted --cwd /home/inc/repos/NEXUS3 --port 9000

# Send research tasks
.venv/bin/python -m nexus3 rpc send researcher "Look at nexus3/rpc/ and summarize the JSON-RPC types" --port 9000

# Check status (don't rush - let them work)
.venv/bin/python -m nexus3 rpc status researcher --port 9000

# Cleanup when done
.venv/bin/python -m nexus3 rpc destroy researcher --port 9000
```

#### Guidelines

- **Run commands one at a time** (multi-turn), NOT as a multi-step script
- **Use subagents for reading/research** - they help manage context window
- **Verify subagent code** - if they write code, review before committing
- **Reuse agents** - check `rpc status` before destroying; reuse if tokens remain
- **Use long timeouts** - research tasks need `--timeout 300` or higher

#### Coordination Pattern

Claude Code coordinates NEXUS subagents directly:
- Create agents with appropriate CWD and permissions
- Send focused research tasks
- Collect and synthesize findings

Do NOT use a NEXUS coordinator agent in the middle - Claude Code is better at coordination.

<!-- PART IV: STATUS -->

---

## Deferred Work

### Structural Refactors

| Issue | Reason | Effort |
|-------|--------|--------|
| Repl.py split (~2050 lines) | Completed extraction in this branch (phases 1A/1B complete) | L |
| Session.py split (~1100 lines) | Completed extraction + wrapper retirement on this branch (remaining Session wrappers removed in closeout wave) | M |
| Pool.py split (~1250 lines) | Completed extraction + wrapper retirement on this branch | M |
| Display config | Completed (`load_theme()` contract cleanup landed) | S |
| HTTP keep-alive | Bounded stale-reuse recovery landed (2026-03-09); real-endpoint evidence is operationally deferred pending endpoint credentials/config in current WSL environment | S |

### DRY Cleanups

| Pattern | Notes |
|---------|-------|
| Dispatcher error handling | `dispatcher.py` and `global_dispatcher.py` have identical try/except blocks |
| HTTP error send | `http.py` has 9 similar `make_error_response()` + `send_http_response()` calls |
| ToolResult file errors | 22 skill files with repeated error handlers |
| Git double timeout | `subprocess.run(timeout)` + `asyncio.wait_for()` is redundant |
| Confirmation menu duplication | `confirmation_ui.py` has 4 separate menu sections per tool type; refactor to table-driven |

### Planned Improvements

Implementation plans for UI/UX improvements, bug fixes, and features are in `docs/plans/`:

| Plan | Description | Effort |
|------|-------------|--------|
| `PROMPT-CACHE-OPTIMIZATION-PLAN.md` | Separate dynamic context from system prompt for cache-optimal message structure | 1-2 days |
| `PROVIDER-BUGFIX-PLAN.md` | SSL cert handling, MSYS2 path normalization, reasoning_content logging | 1 day |
| `PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05.md` | Keep-alive stale-connection closeout complete; real-endpoint evidence deferred pending credentials/config | Deferred external evidence |
| `ARCH-C-SERVICE-CONTAINER-IMMUTABILITY-PLAN-2026-03-05.md` | Replace mutable service-container runtime pattern with typed immutable snapshots | 2-4 days |
| `STRUCTURAL-REFACTOR-WAVE-PLAN-2026-03-05.md` | Split oversized REPL/session/pool modules and clean display config wiring | 1-2 weeks |
| `POST-M4-VALIDATION-CAMPAIGN-PLAN-2026-03-05.md` | Run soak, Windows-native, TOCTOU race, and terminal red-team closeout validation | 1 week |
| `DOUBLE-SPINNER-FIX-PLAN.md` | Fix double spinner / trapped ESC when concurrent RPC sends hit REPL | 1 day |
| `.archive/DRY-CLEANUP-PLAN.md` | Archived pre-architecture DRY cleanup snapshot (not an active execution plan) | N/A |
| `MCP-SERVER-PLAN.md` | Expose NEXUS skills as MCP server (separate project) | 2 weeks |

#### In Progress: PROMPT-CACHE-OPTIMIZATION-PLAN

Dynamic content (datetime, git status, clipboard) was being injected into the system prompt, invalidating the cache (~10-15K tokens) on every API call. Fix moves dynamic content to the last user message via `<session-context>` tags. See `docs/plans/PROMPT-CACHE-OPTIMIZATION-PLAN.md`.

#### Deferred External Follow-Up: PROVIDER-KEEPALIVE-INVESTIGATION-PLAN-2026-03-05

Provider keep-alive real-endpoint evidence remains operationally deferred
(2026-03-09) pending endpoint credentials/config availability in the current
WSL environment. Resume the keep-alive evidence workflow from the documented
checklist once those credentials/config inputs are available; the architecture
implementation backlog is otherwise complete.
If that evidence is clean, it closes the last remaining branch-scope checkbox.
If it surfaces a real defect, treat it as a standalone bugfix follow-up rather
than reopening the architecture execution plan.

#### Recent Debug Fix: Provider Mid-Turn Cancel-Note Injection (2026-03-10)

Windows raw-log investigation confirmed that repeated `Got it` / false
interruption chatter during file-tool smoke tests was being induced by
provider-side request shaping, not just spontaneous model behavior.
`nexus3/provider/openai_compat.py` and `nexus3/provider/anthropic.py` were
running `compile_context_messages(...)` with
`ensure_assistant_after_tool_results=True` on every provider request, which
caused normal mid-turn TOOL->ASSISTANT continuation to receive the synthetic
assistant note `Previous turn was cancelled after tool execution.`. That repair
now remains session-preflight-only before new USER turns; provider request
shaping still prunes/synthesizes tool-result invariants, but no longer injects
that cancellation note mid-loop.

#### Recent Provider Fix: MCP No-Arg Tool Schema Normalization (2026-03-10)

OpenAI-compatible providers were rejecting some MCP-backed tools with
`invalid_function_parameters` when the MCP server advertised a no-arg
`inputSchema` as `{}` or `{"type": "object"}`. The direct provider request
path in `nexus3/provider/openai_compat.py` now normalizes those outbound tool
schemas to `{"type": "object", "properties": {}}` before the API call.
This keeps MCP/local skill contracts unchanged while making OpenAI-format tool
definitions provider-compatible. Quick follow-up audit: built-in GitLab skills
did not show the same empty-schema pattern; deeper GitLab tool auditing
remains deferred separately.

OpenAI-compatible providers also reject some nested MCP schema fragments when
an external tool advertises `{"type": "object"}` without `properties` or
`{"type": "array"}` without `items` inside a richer schema. The same outbound
provider normalization path now fills those nested placeholders recursively
with provider-safe empty `properties: {}` / `items: {}` stubs without mutating
the local MCP skill contract.

#### Recent GitLab Fix: Artifact Download Path Gating (2026-03-10)

`gitlab_artifact` download actions write to a local `output_path`. That tool
was not registered in the generic session path-semantics / destructive-action
metadata, so TRUSTED path confirmation and path gating treated it like a
non-path GitLab action. Session metadata now treats `output_path` as the write
target for `gitlab_artifact`, bringing local artifact downloads back under the
same path confirmation model as other write-capable tools.

#### Recent Tooling Fix: Patch Hunk-Only Diff Normalization (2026-03-10)

`nexus3/skill/builtin/patch.py` now auto-normalizes single-file hunk-only diffs
(`@@ ... @@` without `---`/`+++`) when `path` or `target` is already provided.
Malformed hunk-only input now returns a targeted guidance error instead of the
misleading generic `No patch hunks found in diff`.

### Known Bugs

- **Double spinner on concurrent RPC sends**: When two external `rpc send` requests arrive at an agent with active REPL, two spinners appear and ESC gets trapped. Root cause: missing `try/finally` for "ended" notification in `dispatcher.py:_handle_send()` + module-level spinner state variables can't handle rapid start/stop cycles. Fix planned in `DOUBLE-SPINNER-FIX-PLAN.md`.

<!-- Previously fixed:
- Client timeout cancel race condition: Fixed via provider-level synthesis in anthropic.py.
  The provider now detects orphaned tool_use blocks and synthesizes missing tool_results
  before sending to API. See ANTHROPIC-TOOL-RESULT-FIX-PLAN.md in .archive/ for details.
-->
