# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NEXUS3 is a clean-slate rewrite of NEXUS2, an AI-powered CLI agent framework. The goal is a simpler, more maintainable, end-to-end tested agent with clear architecture.

**Status:** Feature-complete. Multi-provider support, permission system, MCP integration, context compaction.

---

## Current Development

### In Progress: MCP Improvements

**Plan:** `docs/MCP-IMPLEMENTATION-GAPS.md`

**Status:** Starting implementation.

MCP spec compliance and usability improvements:
- P0: Config format compatibility (support Claude Desktop `mcpServers` format)
- P1.1-1.8: Protocol compliance fixes (pagination, HTTP headers, session management)
- P1.9: Improved error messages with source tracking and actionable suggestions
- P2.0: Windows compatibility (PATHEXT, .cmd resolution, env vars)

### Pending Live Test: Command Help System

**Plan:** `docs/COMMAND-HELP.md`

**Status:** Implementation complete, merged to master, awaiting user live testing.

Dynamic help system for REPL commands with consistent formatting, argument documentation, and examples.

### On Deck

Plans are listed in recommended implementation order. Most are independent, but dependencies are noted.

| Priority | Plan | Description |
|----------|------|-------------|
| 1 | `YOLO-SAFETY-PLAN.md` | YOLO warning banner, remove legacy "worker" preset, block RPC send to YOLO agents. Small, security-focused. |
| 2 | `CONCAT-FILES-PLAN.md` | New `concat_files` skill to bundle source files with token estimation. Simple, isolated, low risk. |
| 3 | `EDIT-PATCH-PLAN.md` | Split `edit_file` into separate tools, add batched edits, new `patch` skill for unified diffs. |
| 4 | `CLIPBOARD-PLAN.md` | Scoped clipboard system (agent/project/system) for copy/paste across files and agents. |
| 5 | `SANDBOXED-PARENT-SEND-PLAN.md` | Allow sandboxed agents to `nexus_send` to their parent only. Extends permission system with target restrictions. |
| 6 | `GITLAB-TOOLS-PLAN.md` | Full GitLab integration (issues, MRs, epics, CI/CD). Large feature. *Note: Uses session allowances pattern similar to #5; consider implementing #5 first to establish enforcer patterns.* |

**Reference docs** (not plans):
- `GITHUB-REFERENCE.md` - GitHub API/CLI reference for future GitHub integration
- `GITLAB-REFERENCE.md` - GitLab API/CLI reference used by GITLAB-TOOLS-PLAN

---

## Dogfooding: Use NEXUS Subagents

**When working on this codebase, use NEXUS3 subagents for research and exploration tasks.** This is dogfooding - we use our own product.

### Starting the Server

```bash
# Start headless server (use port 9000 to avoid conflict with user's REPL on 8765)
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &

# Or check if already running
.venv/bin/python -m nexus3 rpc detect --port 9000
```

### Creating and Using Research Agents

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

### Guidelines

- **Run commands one at a time** (multi-turn), NOT as a multi-step script
- **Use subagents for reading/research** - they help manage context window
- **Verify subagent code** - if they write code, review before committing
- **Reuse agents** - check `rpc status` before destroying; reuse if tokens remain
- **Use long timeouts** - research tasks need `--timeout 300` or higher

### Coordination Pattern

Claude Code coordinates NEXUS subagents directly:
- Create agents with appropriate CWD and permissions
- Send focused research tasks
- Collect and synthesize findings

Do NOT use a NEXUS coordinator agent in the middle - Claude Code is better at coordination.

---

## Architecture

```
nexus3/
├── core/           # Types, interfaces, errors, encoding, paths, URL validation, permissions
├── config/         # Pydantic schema, permission config, fail-fast loader
├── provider/       # AsyncProvider protocol, multi-provider support, retry logic
├── context/        # ContextManager, ContextLoader, TokenCounter, compaction
├── session/        # Session coordinator, persistence, SessionManager, SQLite logging
├── skill/          # Skill protocol, SkillRegistry, ServiceContainer, 24 builtin skills
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

### REPL Commands for Sessions

| Command | Description |
|---------|-------------|
| `/save [name]` | Save current session (prompts for name if temp) |
| `/clone <src> <dest>` | Clone agent or saved session |
| `/rename <old> <new>` | Rename agent or saved session |
| `/delete <name>` | Delete saved session from disk |

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
| `/create <name> [--preset] [--model]` | Create agent without switching |
| `/destroy <name>` | Remove active agent from pool |
| `/send <agent> <msg>` | One-shot message to another agent |
| `/status [agent] [--tools] [--tokens] [-a]` | Get agent status (-a: all details) |
| `/cancel [agent]` | Cancel in-progress request |

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

### MCP (External Tools)

| Command | Description |
|---------|-------------|
| `/mcp` | List configured and connected MCP servers |
| `/mcp connect <name>` | Connect to a configured MCP server |
| `/mcp disconnect <name>` | Disconnect from an MCP server |
| `/mcp tools [server]` | List available MCP tools |

### Initialization

| Command | Description |
|---------|-------------|
| `/init` | Create .nexus3/ in current directory |
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
| `bash_safe` | `command`, `timeout`? | Execute shell commands (shlex.split, no shell operators) |
| `shell_UNSAFE` | `command`, `timeout`? | Execute shell=True (pipes work, but injection-vulnerable) |
| `run_python` | `code`, `timeout`? | Execute Python code |
| `sleep` | `seconds`, `label`? | Pause execution (for testing) |
| `nexus_create` | `agent_id`, `preset`?, `disable_tools`?, `cwd`?, `model`?, `initial_message`?, `wait_for_initial_response`? | Create agent (initial_message queued by default) |
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
| **Plan First** | **Non-trivial features require a plan in `docs/`. See Feature Planning SOP below.** |
| **Commit Often** | **Commit after each phase/logical unit. Don't wait for "everything done."** |
| **Branch per Plan** | **One feature branch per plan. Merge only after checklist complete + user sign-off.** |

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
- `docs/EXAMPLE-PLAN-SIMPLE.md` - Template for focused single-feature plans
- `docs/EXAMPLE-PLAN-COMPLEX.md` - Comprehensive example for large multi-phase features

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

## NEXUS3 Commands

### For Claude Code (Bash Tool)

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

### Multi-Turn Usage (Important!)

**Do NOT write shell scripts with multiple steps.** Execute commands one at a time in a multi-turn conversation:

```
✗ BAD: Writing a script that creates agent, sends message, checks status
✓ GOOD: Run create command, see result, then run send command, see result, etc.
```

This allows you to:
- See each command's output before proceeding
- React to errors or unexpected results
- Adjust subsequent commands based on agent responses

### User-Facing Commands (Reference)

When the user runs commands directly in their terminal, they use the `nexus3` alias:

```bash
nexus3                              # REPL with embedded server
nexus3 --fresh                      # New temp session
nexus3 rpc create worker            # Create agent
nexus3 rpc send worker "message"    # Send message
```

### Key Behaviors

- **Security:** `--serve` requires `NEXUS_DEV=1` env var (prevents unattended servers)
- **Security:** `nexus3 rpc` commands do NOT auto-start servers
- **Idle timeout:** Embedded server auto-shuts down after 30 min of no RPC activity
- **Port conflicts:** If user has REPL on 8765, use `--port 9000` for headless servers
- All commands support `--api-key KEY` for explicit auth (auto-discovered by default)

---

## Configuration

```
~/.nexus3/
├── config.json      # Global config
├── NEXUS.md         # Personal system prompt
├── rpc.token        # Auto-generated RPC token (port-specific: rpc-{port}.token)
├── sessions/        # Saved session files (JSON)
├── logs/
│   └── server.log   # Server lifecycle events (rotating, 5MB x 3 files)
└── last-session.json  # Auto-saved for --resume

./NEXUS.md           # Project system prompt (overrides personal)
.nexus3/logs/        # Session logs (gitignored)
├── server.log       # Server lifecycle events when started from this directory
└── <session-id>/    # Per-session conversation logs
    ├── session.db   # SQLite database of messages
    └── session.md   # Markdown transcript
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
| `yolo` | YOLO | Full access, no confirmations (REPL-only) |
| `trusted` | TRUSTED | Confirmations for destructive actions |
| `sandboxed` | SANDBOXED | Limited to CWD, no network, nexus tools disabled (default for RPC) |
| `worker` | SANDBOXED | Minimal: no write_file, no agent management |

### RPC Agent Permission Quirks (IMPORTANT)

**These behaviors are intentional security defaults for RPC-created agents:**

1. **Default agent is sandboxed**: When creating agents via RPC without specifying a preset, they default to `sandboxed` (NOT `trusted`). This is intentional - programmatic agents should be least-privileged by default.

2. **Sandboxed agents can only read in their cwd**: A sandboxed agent's `allowed_paths` is set to `[cwd]` only. They cannot read files outside their working directory.

3. **Sandboxed agents cannot write unless given explicit write paths**: By default, sandboxed agents have all write tools (`write_file`, `edit_file`, `append_file`, `regex_replace`, etc.) **disabled**. To enable writes, use `--write-path` (CLI) or `allowed_write_paths` (RPC JSON):
   ```bash
   nexus3 rpc create worker --cwd /tmp/sandbox --write-path /tmp/sandbox
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
nexus3 rpc create writer --cwd /path/to/project --write-path /path/to/project/output

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
| Repl.py split (~1900 lines) | Large refactor | L |
| Session.py split (~1000 lines) | Large refactor | M |
| Pool.py split (~1100 lines) | Large refactor | M |
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

## Security

Comprehensive security hardening completed January 2026:

- **Permission system**: Ceiling enforcement, fail-closed defaults, path validation
- **RPC hardening**: Token auth, header limits, SSRF protection, symlink defense
- **Process isolation**: Process group kills on timeout, env sanitization
- **Input validation**: URL validation, agent ID validation, MCP protocol hardening
- **Output sanitization**: Terminal escape stripping, Rich markup escaping, secrets redaction

**Test coverage**: 2300+ tests including 500+ security-specific tests.
