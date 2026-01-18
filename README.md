# NEXUS3
AI Agent Framework for Software Engineering Tasks

**NEXUS3** is a secure, multi-agent CLI framework for AI-powered development workflows. Features streaming REPL, JSON-RPC server (port 8765), sandboxed subagents, MCP integration, structured SQLite/Markdown logging, and 24 builtin skills (file ops, git, bash_safe, nexus_* API).

**Key Principles**: Async-first, fail-fast validation, zero external deps in `core`, path/URL sandboxing, permission ceilings (YOLO/TRUSTED/SANDBOXED/WORKER).

## 🚀 Quick Start

### 1. Install (uv recommended)
```bash
uv venv --python 3.11  # or 3.12
uv pip install -e ".[dev]"
export OPENROUTER_API_KEY="sk-or-..."  # or ANTHROPIC_API_KEY
```

### 2. REPL (default)
```bash
nexus3                          # Lobby → session
nexus3 --fresh -m claude-haiku  # New session
nexus3 --resume                 # Last session
nexus3 --session proj           # Named session
```
- `/help`: Slash commands (/agent, /whisper, /mcp, /permissions)
- ESC: Cancel streaming
- Logs: `.nexus3/logs/{id}/` (context.md, verbose.md, raw.jsonl, session.db)

### 3. Server Mode
```bash
NEXUS_DEV=1 nexus3 --serve 8765 --reload  # Dev server + token in ~/.nexus3/rpc.token
```

### 4. RPC Client
```bash
nexus3 rpc list
nexus3 rpc create worker --preset sandboxed --cwd /proj
nexus3 rpc send worker "Read src/ and summarize"
nexus3 rpc status worker
```

## ✨ Features

| Category | Highlights |
|----------|------------|
| **Multi-Agent** | RPC `/agent/{id}`; create/destroy/send; hierarchies (ceiling perms); in-process `DirectAgentAPI` |
| **Skills/Tools** | 24 builtins (read_file, bash_safe, git, nexus_create); parallel exec (max 10 concurrent); DI via `ServiceContainer` |
| **Security** | Path sandbox (`allowed_paths`); URL SSRF block; presets (resolve_preset("trusted")); confirm destructive |
| **Context** | Layered prompts (NEXUS.md); tiktoken budgets; LLM compaction; `ContextManager` |
| **Display** | Rich Live (gumballs ●○, summary bar, streaming tools); `DisplayManager` |
| **LLM Providers** | OpenRouter/OpenAI/Azure/Anthropic/Ollama/vLLM; `create_provider()` factory |
| **MCP** | Client for external tools (stdio/HTTP); auto-skill adapt (`mcp_{server}_{tool}`) |
| **Sessions** | SQLite persistence; `SessionManager`; subagent nesting |
| **Config** | Layered JSON (defaults → global → local); Pydantic `Config` |

## 🛡️ Security & Permissions
- **Presets**: `yolo` (REPL-only), `trusted` (confirm destructive), `sandboxed` (cwd read-only, **RPC default**), `worker` (no write_file)
- **Paths**: `validate_path()` + `PathResolver`; O_NOFOLLOW writes
- **URLs**: Private IP/DNS rebinding block; `validate_url()`
- **RPC**: Localhost + `nxk_` token auth
- **Agents**: Subagents ≤ parent perms; no up-escalation

## 📚 Modules
Detailed docs in each module:

| Module | Purpose |
|--------|---------|
| [core](nexus3/core/README.md) | Types (`Message`, `StreamEvent`), `AsyncProvider`, paths/perms/URL validation |
| [config](nexus3/config/README.md) | Layered `load_config()`; `Config` Pydantic models |
| [provider](nexus3/provider/README.md) | `create_provider()`; OpenAI/Anthropic compat; retries |
| [context](nexus3/context/README.md) | `ContextManager`; compaction; `TokenCounter` |
| [session](nexus3/session/README.md) | `Session` coord; `SessionLogger`; persistence; typed events |
| [skill](nexus3/skill/README.md) | `SkillRegistry`; bases (`FileSkill`, `ExecutionSkill`); DI |
| [display](nexus3/display/README.md) | `DisplayManager`; `InlinePrinter`; `SummaryBar` |
| [cli](nexus3/cli/README.md) | REPL; slash cmds; `--serve`; `nexus3 rpc` |
| [rpc](nexus3/rpc/README.md) | `AgentPool`; `GlobalDispatcher`; JSON-RPC 2.0 |
| [mcp](nexus3/mcp/README.md) | `MCPClient`; `MCPServerRegistry`; skill adapters |
| [commands](nexus3/commands/README.md) | Shared `cmd_list/create/send`; `CommandOutput` |
| [defaults](nexus3/defaults/README.md) | `config.json`; `NEXUS.md` |

## 🏗️ Architecture
```
REPL/CLI → cli → rpc (AgentPool) → session → provider + skill (parallel)
                    ↓
              context + display + config + core (perms/paths/types)
```
- **Data Flow**: User msg → stream(tools?) → dispatch/exec (perms check) → ToolResult → next msg
- **Shared**: Providers/registry; per-agent: context/logger/session

## 🔧 Development
```bash
uv run pytest tests/ --cov=nexus3
ruff check .
mypy nexus3/
```
- Async-only; typesafe; E2E tests
- Extend: Custom skills (`@file_skill_factory class MySkill(BaseSkill)`); MCP servers

## 📈 Config Example
[nexus3/defaults/config.json](nexus3/defaults/config.json) → models/providers/MCP/permissions.

**License**: MIT  
**Updated**: 2026-01-18