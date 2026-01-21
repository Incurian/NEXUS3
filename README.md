# NEXUS3

**A secure, multi-agent CLI framework for AI-powered software engineering.**

NEXUS3 provides a streaming REPL with an embedded JSON-RPC server for orchestrating multiple AI agents. Each agent runs in isolation with configurable permissions, enabling safe automation of development tasks through 26 built-in skills (file operations, git, shell execution, inter-agent communication).

---

## Table of Contents

- [Key Features](#key-features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Provider Configuration](#provider-configuration)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Architecture](#architecture)
- [Security & Permissions](#security--permissions)
- [Configuration Reference](#configuration-reference)
- [Built-in Skills](#built-in-skills)
- [MCP Integration](#mcp-integration)
- [Session Management](#session-management)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

## Key Features

- **One Server, Many Agents**: Run a single NEXUS3 server per project. Create multiple agents within it for parallel research, code review, implementation—all coordinated through `nexus_send`. More efficient than multiple servers and enables direct inter-agent communication.
- **Async-First**: Built on asyncio throughout—no threading, predictable concurrency.
- **Fail-Fast**: Errors surface immediately with clear messages—no silent failures.
- **Security by Default**: Sandboxed by default for RPC agents, permission ceilings prevent escalation.
- **Multi-Provider Support**: OpenRouter, Anthropic, OpenAI, Azure, Ollama, vLLM.
- **Context Compaction**: LLM-powered summarization when context gets full.
- **MCP Integration**: Connect external tools via Model Context Protocol.

---

## Requirements

### System Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | **Required.** Use `python3.11` or newer |
| Operating System | Linux, macOS, WSL2 | Windows requires WSL2 |
| Terminal | Any modern terminal | 256-color support recommended |

### LLM Provider (At Least One)

You need an API key from at least one provider:

| Provider | Environment Variable | Sign Up |
|----------|---------------------|---------|
| OpenRouter (recommended) | `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) |
| Anthropic | `ANTHROPIC_API_KEY` | [anthropic.com](https://anthropic.com) |
| OpenAI | `OPENAI_API_KEY` | [openai.com](https://openai.com) |
| Azure OpenAI | `AZURE_OPENAI_KEY` | Azure Portal |
| Ollama (local) | N/A | [ollama.ai](https://ollama.ai) |

**Why OpenRouter?** Single API key gives access to Claude, GPT-4, Gemini, Llama, and hundreds of other models. Great for experimentation.

---

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/Incurian/NEXUS3.git
cd nexus3
```

### Step 2: Create a Virtual Environment

**Option A: Using `uv` (faster, recommended)**
```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtualenv with Python 3.11+
uv venv --python 3.11
source .venv/bin/activate
```

**Option B: Using standard `venv`**
```bash
# Ensure you have Python 3.11+
python3.11 --version  # Should print 3.11.x or higher

# Create virtualenv
python3.11 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies

**Development installation (recommended):**
```bash
# Using uv
uv pip install -e ".[dev]"

# Or using pip
pip install -e ".[dev]"
```

**User installation:**
```bash
pip install .
```

### Step 4: Set Up API Key

**Option A: Environment variable (temporary)**
```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

**Option B: `.env` file (persistent, recommended)**
```bash
# Create .env file in repo root
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .env

# This file is gitignored - never commit API keys!
```

**Option C: Shell profile (always available)**
```bash
# Add to ~/.bashrc or ~/.zshrc
echo 'export OPENROUTER_API_KEY="sk-or-v1-..."' >> ~/.bashrc
source ~/.bashrc
```

### Step 5: Verify Installation

```bash
# Check Python version
python --version  # Should show 3.11+

# Check module is importable
python -c "import nexus3; print('NEXUS3 installed successfully')"

# Check CLI works
nexus3 --help
```

### Step 6: Initialize Configuration (Optional)

```bash
# Create global config directory (~/.nexus3/)
nexus3 --init-global

# This creates:
# - ~/.nexus3/config.json (settings)
# - ~/.nexus3/NEXUS.md (system prompt template)
# - ~/.nexus3/mcp.json (MCP servers)
```

### Path Setup (If `nexus3` Command Not Found)

If `nexus3` command is not found after installation:

```bash
# Option 1: Add ~/.local/bin to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Option 2: Use full path
~/.local/bin/nexus3

# Option 3: Use module directly
python -m nexus3
```

---

## Provider Configuration

NEXUS3 supports multiple LLM providers. The `type` field specifies which **API protocol** to use—it's not locked to any specific service. You can point any provider type at any compatible endpoint using `base_url`.

### Provider Types (API Compatibility Modes)

| Type | API Protocol | Compatible With |
|------|--------------|-----------------|
| `openai` | OpenAI Chat Completions | OpenAI, vLLM, LM Studio, LocalAI, text-generation-webui, llama.cpp, any OpenAI-compatible server |
| `openrouter` | OpenAI + OpenRouter headers | OpenRouter, compatible proxies |
| `anthropic` | Anthropic Messages API | Anthropic, AWS Bedrock (with adapter), compatible proxies |
| `azure` | OpenAI + Azure auth | Azure OpenAI Service |
| `ollama` | OpenAI-compatible | Ollama (convenience preset for `openai` with localhost defaults) |
| `vllm` | OpenAI-compatible | vLLM servers (convenience preset for `openai`) |

### Basic Setup (Single Provider)

For most users, a single provider is sufficient:

```json
{
  "providers": {
    "main": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY",
      "models": {
        "default": {
          "id": "anthropic/claude-sonnet-4",
          "context_window": 200000
        }
      }
    }
  },
  "default_model": "default"
}
```

### Using Local Models

Point any OpenAI-compatible local server:

```json
{
  "providers": {
    "local": {
      "type": "openai",
      "base_url": "http://localhost:8080/v1",
      "auth_method": "none",
      "models": {
        "llama": {"id": "llama-3.2-8b", "context_window": 128000},
        "codellama": {"id": "codellama-34b", "context_window": 16000}
      }
    }
  },
  "default_model": "llama"
}
```

This works with:
- **Ollama**: `http://localhost:11434/v1`
- **LM Studio**: `http://localhost:1234/v1`
- **vLLM**: `http://localhost:8000/v1`
- **text-generation-webui**: `http://localhost:5000/v1`
- **llama.cpp server**: `http://localhost:8080/v1`
- **LocalAI**: `http://localhost:8080/v1`

### Multi-Provider Setup

Use multiple providers simultaneously:

```json
{
  "providers": {
    "cloud": {
      "type": "openrouter",
      "api_key_env": "OPENROUTER_API_KEY",
      "models": {
        "smart": {"id": "anthropic/claude-sonnet-4", "context_window": 200000},
        "fast": {"id": "anthropic/claude-haiku-4.5", "context_window": 200000}
      }
    },
    "local": {
      "type": "openai",
      "base_url": "http://localhost:11434/v1",
      "auth_method": "none",
      "models": {
        "llama": {"id": "llama3.2", "context_window": 128000}
      }
    },
    "work": {
      "type": "azure",
      "base_url": "https://my-company.openai.azure.com",
      "api_key_env": "AZURE_OPENAI_KEY",
      "api_version": "2024-02-01",
      "models": {
        "gpt4": {"id": "gpt-4-turbo", "deployment": "gpt4-deployment", "context_window": 128000}
      }
    }
  },
  "default_model": "smart"
}
```

Switch models at runtime:
```bash
nexus3 --model llama      # Use local model
nexus3 --model smart      # Use cloud model
/model gpt4               # Switch in REPL
```

### Provider Options Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `type` | string | `"openrouter"` | API protocol (see table above) |
| `base_url` | string | Provider-specific | API endpoint URL |
| `api_key_env` | string | Provider-specific | Environment variable containing API key |
| `auth_method` | string | `"bearer"` | Auth header format: `bearer`, `api-key`, `x-api-key`, `none` |
| `request_timeout` | float | `120.0` | Request timeout in seconds |
| `max_retries` | int | `3` | Retry attempts on failure (0-10) |
| `retry_backoff` | float | `1.5` | Exponential backoff multiplier |
| `extra_headers` | object | `{}` | Additional HTTP headers |
| `api_version` | string | - | API version (Azure) |
| `deployment` | string | - | Deployment name (Azure) |

### Model Options Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | string | (required) | Model identifier sent to API |
| `context_window` | int | `131072` | Context window size in tokens |
| `reasoning` | bool | `false` | Enable extended thinking mode |

---

## Quick Start

### Interactive REPL (Recommended for Getting Started)

```bash
# Launch with session selector (lobby)
nexus3

# Skip lobby, start fresh session
nexus3 --fresh

# Resume your last session
nexus3 --resume

# Load specific saved session
nexus3 --session myproject
```

Once in the REPL:
- Type messages naturally to chat with the AI
- Use `/help` to see all commands
- Press `ESC` to cancel a response
- Press `Ctrl+D` or type `/quit` to exit

### Your First Conversation

```
$ nexus3 --fresh

NEXUS3 v0.1.0 - Type /help for commands

you> Hello! What can you do?

assistant> I'm NEXUS3, an AI assistant with access to 26 tools for
software development tasks. I can:

• Read, write, and edit files
• Run shell commands and Python scripts
• Use git for version control
• Search codebases with glob and grep
• Create and coordinate sub-agents for parallel work

What would you like to work on?

you> /help
```

### Multi-Agent Workflows

NEXUS3 shines when you need multiple agents working together:

```bash
# Terminal 1: Start REPL (includes embedded server)
nexus3

# Terminal 2: Create a research agent
nexus3 rpc create researcher --preset trusted --cwd /path/to/project

# Send it a task
nexus3 rpc send researcher "Analyze the authentication module and list security concerns"

# Check its progress
nexus3 rpc status researcher

# When done, clean up
nexus3 rpc destroy researcher
```

**Or manage agents from within the REPL:**
```
you> /agent create researcher --trusted
Created agent 'researcher'

you> /whisper researcher
researcher> Analyze the test coverage in tests/

(agent works...)

researcher> /over
you>
```

---

## CLI Reference

### Main Command: `nexus3`

```
nexus3 [OPTIONS]
```

#### Session Modes (Mutually Exclusive)

| Flag | Description |
|------|-------------|
| (none) | Show lobby to select/create session |
| `--fresh` | Start new temporary session |
| `--resume` | Resume last session automatically |
| `--session NAME` | Load specific saved session by name |

#### Server Modes

| Flag | Description |
|------|-------------|
| `--serve [PORT]` | Run headless HTTP server (requires `NEXUS_DEV=1`) |
| `--connect [URL]` | Connect to existing server (auto-discovers if no URL) |
| `--agent ID` | Agent to connect to (default: `main`, requires `--connect`) |

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--model NAME` | Config default | Model alias or full ID |
| `--template PATH` | - | Custom system prompt file |
| `--verbose` | false | Enable debug logging |
| `--raw-log` | false | Log raw API JSON |
| `--log-dir PATH` | `.nexus3/logs` | Log directory |
| `--port PORT` | 8765 | Server port |
| `--api-key KEY` | Auto | Explicit API key |
| `--scan PORTS` | - | Additional ports to scan (e.g., `9000,9001-9010`) |

#### Initialization

| Flag | Description |
|------|-------------|
| `--init-global` | Create `~/.nexus3/` with default config |
| `--init-global-force` | Overwrite existing global config |

### RPC Subcommands: `nexus3 rpc`

All RPC commands require a running server. They do **not** auto-start servers.

#### `nexus3 rpc detect`

Check if a server is running.

```bash
nexus3 rpc detect [--port PORT]
```

Exit code: 0 if running, 1 if not.

#### `nexus3 rpc list`

List all agents on the server.

```bash
nexus3 rpc list [--port PORT] [--api-key KEY]
```

#### `nexus3 rpc create`

Create a new agent.

```bash
nexus3 rpc create AGENT_ID [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--preset` | `sandboxed` | Permission preset: `trusted`, `sandboxed`, `worker` |
| `--cwd PATH` | - | Working directory (sandbox root) |
| `--write-path PATH` | - | Allow writes to path (repeatable) |
| `--model NAME` | - | Model alias |
| `-M, --message MSG` | - | Send initial message after creation |
| `-t, --timeout SEC` | 300 | Request timeout |

**Important:** RPC agents are `sandboxed` by default (read-only). Use `--preset trusted` for full access or `--write-path` for specific directories.

#### `nexus3 rpc send`

Send a message to an agent.

```bash
nexus3 rpc send AGENT_ID MESSAGE [--timeout SEC]
```

#### `nexus3 rpc status`

Get agent status (tokens, context info).

```bash
nexus3 rpc status AGENT_ID
```

#### `nexus3 rpc destroy`

Remove an agent.

```bash
nexus3 rpc destroy AGENT_ID
```

#### `nexus3 rpc compact`

Force context compaction to reclaim tokens.

```bash
nexus3 rpc compact AGENT_ID
```

#### `nexus3 rpc cancel`

Cancel an in-progress request.

```bash
nexus3 rpc cancel AGENT_ID REQUEST_ID
```

#### `nexus3 rpc shutdown`

Gracefully stop the server.

```bash
nexus3 rpc shutdown
```

### REPL Slash Commands

Available when running interactively.

#### Agent Management

| Command | Description |
|---------|-------------|
| `/agent` | Show current agent status |
| `/agent NAME` | Switch to agent (creates if needed) |
| `/agent NAME --trusted` | Create trusted agent and switch |
| `/agent NAME --model ALIAS` | Create agent with specific model |
| `/list` | List all active agents |
| `/create NAME [--preset]` | Create agent without switching |
| `/destroy NAME` | Remove agent |
| `/send AGENT MESSAGE` | One-shot message to agent |
| `/status [AGENT] [-a]` | Get agent status (use `-a` for all details) |
| `/cancel [AGENT]` | Cancel in-progress request |

#### Inter-Agent Communication

| Command | Description |
|---------|-------------|
| `/whisper AGENT` | Enter whisper mode (redirect input to agent) |
| `/over` | Exit whisper mode |

#### Session Management

| Command | Description |
|---------|-------------|
| `/save [NAME]` | Save current session |
| `/clone SRC DEST` | Clone session |
| `/rename OLD NEW` | Rename session |
| `/delete NAME` | Delete saved session |

#### Configuration

| Command | Description |
|---------|-------------|
| `/cwd [PATH]` | Show or change working directory |
| `/model [NAME]` | Show or switch model |
| `/permissions [PRESET]` | Show or change permissions |
| `/permissions --list-tools` | List all tools and their status |
| `/prompt [FILE]` | Show or set system prompt |
| `/compact` | Force context compaction |
| `/init [--global]` | Initialize project config |

#### MCP (External Tools)

| Command | Description |
|---------|-------------|
| `/mcp` | List MCP servers |
| `/mcp connect NAME` | Connect to MCP server |
| `/mcp disconnect NAME` | Disconnect from server |
| `/mcp tools [SERVER]` | List available MCP tools |

#### REPL Control

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/clear` | Clear screen |
| `/quit`, `/exit`, `/q` | Exit REPL |

#### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `ESC` | Cancel current response |
| `Ctrl+C` | Interrupt input |
| `Ctrl+D` | Exit REPL |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              NEXUS3 Server                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                         AgentPool                                │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│  │  │ Agent: main │  │ Agent: sub  │  │ Agent: rev  │  ...         │   │
│  │  │ (REPL)      │  │ (sandboxed) │  │ (trusted)   │              │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │   │
│  │         │                │                │                      │   │
│  │         └────────────────┼────────────────┘                      │   │
│  │                          │ nexus_send()                          │   │
│  │                          ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │              SharedComponents                            │    │   │
│  │  │  • ProviderRegistry (LLM connections)                   │    │   │
│  │  │  • Config (layered settings)                            │    │   │
│  │  │  • PromptLoader (NEXUS.md templates)                    │    │   │
│  │  └─────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────┐    ┌─────────────────────────────────────┐   │
│  │    HTTP Server      │    │         GlobalDispatcher            │   │
│  │  (localhost:8765)   │───▶│  create_agent / destroy_agent       │   │
│  │  Token auth (nxk_)  │    │  list_agents / shutdown_server      │   │
│  └─────────────────────┘    └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User message** → Session → Provider (streaming LLM response)
2. **Tool calls detected** → SkillRegistry → Permission check → Execute
3. **Tool results** → Back to LLM → Continue until done
4. **Response displayed** → Logged to SQLite + Markdown

### Module Overview

| Module | Purpose |
|--------|---------|
| `core/` | Types, interfaces, errors, encoding, security primitives |
| `config/` | Pydantic schemas, layered config loading |
| `provider/` | LLM provider implementations, retry logic |
| `context/` | Context management, token counting, compaction |
| `session/` | Session coordinator, event system, persistence |
| `skill/` | Skill registry, base classes, 26 built-in skills |
| `display/` | Rich terminal UI, streaming display |
| `cli/` | REPL, argument parsing, lobby |
| `rpc/` | JSON-RPC server, agent pool, authentication |
| `mcp/` | Model Context Protocol client |
| `commands/` | Unified command infrastructure |
| `defaults/` | Default configuration and prompts |

---

## Security & Permissions

NEXUS3 implements a comprehensive security system with three permission levels.

### Permission Levels

| Level | Description | File Access | Execution | Agent Creation |
|-------|-------------|-------------|-----------|----------------|
| **YOLO** | Full access, no confirmations | Unrestricted | No prompts | Any preset |
| **TRUSTED** | Interactive with confirmations | Read anywhere, write prompts outside CWD | Prompts required | Sandboxed only |
| **SANDBOXED** | Isolated sandbox | CWD only | Disabled | Disabled |

### Permission Presets

| Preset | Level | Description | Available Via |
|--------|-------|-------------|---------------|
| `yolo` | YOLO | Full access, no confirmations | REPL only |
| `trusted` | TRUSTED | Confirmations for destructive actions | REPL, RPC |
| `sandboxed` | SANDBOXED | Read-only in CWD, no execution | REPL, RPC (default) |

### Key Security Features

#### Permission Ceiling Enforcement

Child agents cannot exceed parent permissions:
- YOLO agents can create TRUSTED or SANDBOXED children
- TRUSTED agents can only create SANDBOXED children
- SANDBOXED agents cannot create any agents

#### Path Sandboxing

- **Sandboxed agents**: Can only access files within their `cwd`
- **Symlink protection**: Resolved paths checked for sandbox escape
- **Per-tool paths**: Individual tools can have their own path restrictions

#### RPC Security

- **Localhost binding**: Server only binds to `127.0.0.1`
- **Token authentication**: 256-bit tokens with constant-time comparison
- **Request limits**: Body size (1MB), header limits, timeout protection
- **Secure tokens**: `0o600` permissions, per-port token files

#### SSRF Protection

URL validation blocks access to:
- Cloud metadata endpoints (169.254.169.254)
- Private networks (10.x, 172.16-31.x, 192.168.x)
- Localhost (unless explicitly allowed)
- Link-local and multicast addresses

#### Process Isolation

- Process group kills on timeout (no orphaned processes)
- Environment sanitization (API keys not passed to subprocesses)
- `bash_safe` uses `shlex.split()` (no shell injection)

### RPC Default Permissions (Important!)

**RPC-created agents are `sandboxed` by default**, not `trusted`. This is intentional:

```bash
# Default: sandboxed (read-only in cwd)
nexus3 rpc create worker --cwd /project

# Explicitly trusted (read anywhere)
nexus3 rpc create worker --preset trusted --cwd /project

# Sandboxed with write access to specific directory
nexus3 rpc create worker --cwd /project --write-path /project/output
```

### REPL Confirmation Behavior

In TRUSTED mode, destructive operations prompt for confirmation:

```
Tool: write_file
Path: /etc/hosts
This path is outside your working directory.

Allow? [y]es / [n]o / [a]llow directory / [s]kip:
```

Options:
- **y**: Allow this once
- **n**: Deny
- **a**: Allow all operations in this directory for the session
- **s**: Skip this tool call

---

## Configuration Reference

This section covers all configuration options. For provider setup, see [Provider Configuration](#provider-configuration).

### File Locations

Configuration is loaded from multiple layers (later overrides earlier):

```
1. Shipped defaults     nexus3/defaults/config.json
2. Global user          ~/.nexus3/config.json
3. Ancestor dirs        ../.nexus3/config.json (up to 2 levels)
4. Project local        ./.nexus3/config.json
```

### Directory Structure

```
~/.nexus3/                          # Global (user defaults)
├── config.json                     # Global settings
├── NEXUS.md                        # Personal system prompt
├── mcp.json                        # Personal MCP servers
├── rpc.token                       # RPC auth token
├── sessions/                       # Saved sessions
└── logs/                           # Logs
    └── server.log                  # Server lifecycle events

./.nexus3/                          # Project-local
├── config.json                     # Project overrides
├── NEXUS.md                        # Project system prompt
├── mcp.json                        # Project MCP servers
└── logs/                           # Session logs
    └── {session-id}/
        ├── session.db              # SQLite message history
        └── session.md              # Markdown transcript
```

### Root Configuration Options

```json
{
  "default_model": "fast",
  "providers": { },
  "stream_output": true,
  "max_tool_iterations": 100,
  "skill_timeout": 120.0,
  "max_concurrent_tools": 10,
  "default_permission_level": "trusted",
  "compaction": { },
  "context": { },
  "mcp_servers": [ ],
  "server": { },
  "permissions": { }
}
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `default_model` | string | `"fast"` | Model alias to use by default |
| `providers` | object | - | Provider configurations (see [Provider Configuration](#provider-configuration)) |
| `stream_output` | bool | `true` | Stream LLM responses |
| `max_tool_iterations` | int | `100` | Max tool calls per turn |
| `skill_timeout` | float | `120.0` | Default tool timeout (seconds) |
| `max_concurrent_tools` | int | `10` | Parallel tool execution limit |
| `default_permission_level` | string | `"trusted"` | Default permission preset |

### Compaction Configuration

```json
{
  "compaction": {
    "enabled": true,
    "model": "fast",
    "trigger_threshold": 0.9,
    "summary_budget_ratio": 0.25,
    "recent_preserve_ratio": 0.25
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable automatic compaction |
| `model` | `"fast"` | Model for summarization |
| `trigger_threshold` | `0.9` | Trigger when 90% of context used |
| `summary_budget_ratio` | `0.25` | Max 25% of tokens for summary |
| `recent_preserve_ratio` | `0.25` | Keep 25% of recent messages verbatim |

#### Context Configuration

```json
{
  "context": {
    "ancestor_depth": 2,
    "include_readme": false,
    "readme_as_fallback": false
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `ancestor_depth` | `2` | Parent directories to search (0-10) |
| `include_readme` | `false` | Always include README.md |
| `readme_as_fallback` | `false` | Use README.md when no NEXUS.md |

#### Server Configuration

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8765,
    "log_level": "INFO"
  }
}
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `AZURE_OPENAI_KEY` | Azure OpenAI API key |
| `NEXUS_DEV=1` | Enable `--serve` headless mode |
| `NEXUS3_API_KEY` | Override RPC token |

---

## Built-in Skills

NEXUS3 includes 26 built-in skills organized by category.

### File Operations (Read)

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `read_file` | Read file contents | `path`, `offset`, `limit` |
| `tail` | Read last N lines | `path`, `lines` (default: 10) |
| `file_info` | Get file metadata | `path` |
| `list_directory` | List directory contents | `path`, `all`, `long` |
| `glob` | Find files by pattern | `pattern`, `path`, `exclude` |
| `grep` | Search file contents | `pattern`, `path`, `include`, `context` |

### File Operations (Write)

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `write_file` | Write/create file | `path`, `content` |
| `edit_file` | Edit with string/line replacement | `path`, `old_string`, `new_string` |
| `append_file` | Append to file | `path`, `content`, `newline` |
| `regex_replace` | Regex find/replace | `path`, `pattern`, `replacement` |
| `copy_file` | Copy file | `source`, `destination`, `overwrite` |
| `mkdir` | Create directory | `path` |
| `rename` | Move/rename file | `source`, `destination`, `overwrite` |

### Execution

| Skill | Description | Safety |
|-------|-------------|--------|
| `bash_safe` | Execute command (no shell operators) | Safe from injection |
| `shell_UNSAFE` | Execute with full shell (pipes, redirects) | **Vulnerable to injection** |
| `run_python` | Execute Python code | Same as bash_safe |

**Important:** `bash_safe` uses `shlex.split()` so shell operators (`|`, `&&`, `>`) do NOT work. Use `shell_UNSAFE` only when you need shell features AND trust the input.

### Version Control

| Skill | Description | Notes |
|-------|-------------|-------|
| `git` | Execute git commands | Permission-filtered by level |

Git commands are filtered by permission level:
- **SANDBOXED**: Read-only (`status`, `diff`, `log`, `show`, `branch`, `blame`, etc.)
- **TRUSTED**: Read + write, dangerous flags blocked (`--force`, `--hard`)
- **YOLO**: All commands allowed

### Agent Management

| Skill | Description | Parameters |
|-------|-------------|------------|
| `nexus_create` | Create agent | `agent_id`, `preset`, `cwd`, `model`, `initial_message` |
| `nexus_destroy` | Destroy agent | `agent_id` |
| `nexus_send` | Send message to agent | `agent_id`, `content` |
| `nexus_status` | Get agent status | `agent_id` |
| `nexus_cancel` | Cancel request | `agent_id`, `request_id` |
| `nexus_shutdown` | Shutdown server | - |

### Utility

| Skill | Description | Parameters |
|-------|-------------|------------|
| `echo` | Echo message (testing) | `message` |
| `sleep` | Pause execution | `seconds`, `label` |

### Skill Availability by Permission Level

| Skill Category | YOLO | TRUSTED | SANDBOXED |
|----------------|------|---------|-----------|
| File read | All | All | CWD only |
| File write | All | Confirmations | Disabled (unless `allowed_write_paths`) |
| Execution | All | Confirmations | Disabled |
| Git | All | Write commands | Read-only |
| Agent management | All | Sandboxed children only | Disabled |

---

## MCP Integration

NEXUS3 supports the Model Context Protocol (MCP) for connecting external tools.

### Configuration

Create `mcp.json` in `~/.nexus3/` (global) or `.nexus3/` (project):

```json
{
  "servers": [
    {
      "name": "github",
      "command": ["npx", "-y", "@anthropic/mcp-server-github"],
      "env_passthrough": ["GITHUB_TOKEN"]
    },
    {
      "name": "filesystem",
      "command": ["npx", "-y", "@anthropic/mcp-server-filesystem", "/allowed/path"]
    },
    {
      "name": "postgres",
      "command": ["npx", "-y", "@anthropic/mcp-server-postgres"],
      "env": {
        "DATABASE_URL": "postgresql://localhost/mydb"
      }
    }
  ]
}
```

### Server Configuration Options

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Friendly name (used in skill names: `mcp_github_*`) |
| `command` | One of | Command for stdio transport |
| `url` | One of | URL for HTTP transport |
| `env` | No | Explicit environment variables |
| `env_passthrough` | No | Copy these vars from host environment |
| `cwd` | No | Working directory for subprocess |
| `enabled` | No | Default: `true` |

### Transport Types

**Stdio (Subprocess):** Most MCP servers use stdio. The server runs as a subprocess with JSON-RPC over stdin/stdout.

**HTTP:** For remote MCP servers (less common).

### Environment Variable Security

MCP servers only receive safe environment variables by default. To pass secrets:

```json
{
  "name": "github",
  "command": ["npx", "-y", "@anthropic/mcp-server-github"],
  "env_passthrough": ["GITHUB_TOKEN"],
  "env": {
    "EXTRA_VAR": "explicit-value"
  }
}
```

### REPL Commands

```bash
/mcp                        # List servers and status
/mcp connect github         # Connect to server
/mcp connect github --allow-all --shared  # Skip prompts
/mcp disconnect github      # Disconnect
/mcp tools                  # List available MCP tools
```

### Permission Requirements

- **YOLO/TRUSTED**: Can use MCP tools
- **SANDBOXED**: MCP access blocked

---

## Session Management

### Session Types

- **Temporary sessions**: Auto-created, not saved unless you use `/save`
- **Named sessions**: Saved to disk, can be resumed with `--session NAME`

### Saving and Resuming

```bash
# In REPL
/save myproject           # Save current session

# From command line
nexus3 --resume           # Resume last session
nexus3 --session myproject  # Resume specific session
```

### Session Data

Each session stores:
- **session.db**: SQLite database with full message history
- **session.md**: Human-readable Markdown transcript
- **Session metadata**: Model, permissions, allowances

### Session Files Location

```
~/.nexus3/sessions/           # Named session files
  └── myproject.json          # Session state

.nexus3/logs/{session-id}/    # Session logs
  ├── session.db              # SQLite database
  └── session.md              # Markdown transcript

~/.nexus3/last-session.json   # Last session (for --resume)
```

### Context Compaction

When context gets full (90% by default), NEXUS3 automatically:
1. Preserves recent messages (25%)
2. Summarizes older messages using a fast model
3. Reloads NEXUS.md (picking up any changes)

Manual compaction:
```bash
/compact                    # REPL
nexus3 rpc compact AGENT_ID # RPC
```

---

## Troubleshooting

### Installation Issues

**Problem: `python: command not found`**
```bash
# Use explicit Python 3.11
python3.11 -m nexus3

# Or activate virtualenv
source .venv/bin/activate
```

**Problem: `nexus3: command not found`**
```bash
# Add to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Or use module
python -m nexus3
```

**Problem: `ModuleNotFoundError: No module named 'nexus3'`**
```bash
# Install the package
source .venv/bin/activate
pip install -e .
```

### API Key Issues

**Problem: `AuthenticationError: API key not found`**
```bash
# Check env var
echo $OPENROUTER_API_KEY

# Set it
export OPENROUTER_API_KEY="sk-or-v1-..."

# Or use .env file
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .env
```

### Server Issues

**Problem: `Address already in use: 8765`**
```bash
# Find and kill existing server
lsof -i :8765
kill <PID>

# Or use different port
nexus3 --serve 9000
```

**Problem: `Cannot use --serve without NEXUS_DEV=1`**
```bash
# This is a security feature
NEXUS_DEV=1 nexus3 --serve 8765
```

**Problem: RPC commands fail with "server not running"**
```bash
# RPC commands don't auto-start servers
# Start server first:
nexus3 &  # REPL with embedded server

# Then use RPC
nexus3 rpc list
```

### Agent Issues

**Problem: Sandboxed agent can't write files**
```bash
# Sandboxed agents need explicit write paths
nexus3 rpc create worker --cwd /project --write-path /project/output

# Or use trusted preset
nexus3 rpc create worker --preset trusted
```

**Problem: Agent stuck / unresponsive**
```bash
# Force context compaction
nexus3 rpc compact AGENT_ID

# Or destroy and recreate
nexus3 rpc destroy AGENT_ID
nexus3 rpc create AGENT_ID --preset trusted
```

**Problem: Context window full**
```bash
# Compact to reclaim space
/compact  # In REPL
nexus3 rpc compact AGENT_ID  # RPC
```

### WSL-Specific Issues

**Problem: Server dies with false idle timeout**

Fixed in recent versions. Uses `time.monotonic()` instead of `time.time()` to avoid clock sync issues.

Monitor with:
```bash
tail -f .nexus3/logs/server.log
```

### Debugging

**Enable verbose logging:**
```bash
nexus3 --verbose
```

**Check server logs:**
```bash
tail -f .nexus3/logs/server.log
```

**Check session logs:**
```bash
ls -la .nexus3/logs/
cat .nexus3/logs/{session-id}/session.md
```

---

## Development

### Running Tests

```bash
# All tests (2300+)
.venv/bin/pytest tests/ -v

# Specific categories
.venv/bin/pytest tests/unit/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/pytest tests/security/ -v

# With coverage
.venv/bin/pytest tests/ --cov=nexus3
```

### Code Quality

```bash
# Linting
.venv/bin/ruff check nexus3/

# Type checking
.venv/bin/mypy nexus3/

# Format check
.venv/bin/ruff format --check nexus3/
```

### Creating Custom Skills

```python
from nexus3.skill import BaseSkill, ToolResult

class MySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "The input"}
            },
            "required": ["input"]
        }

    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        result = do_something(input)
        return ToolResult(output=result)

# Factory for dependency injection
def my_skill_factory(container):
    return MySkill()
```

### Skill Base Classes

| Base Class | Use For |
|------------|---------|
| `BaseSkill` | Simple tools without file/network/execution |
| `FileSkill` | File operations with path validation |
| `ExecutionSkill` | Subprocess execution with timeouts |
| `NexusSkill` | Agent management via RPC |
| `FilteredCommandSkill` | Command filtering by permission level |

### Live Testing

Before committing changes that affect agent behavior:

```bash
# Start server
nexus3 &

# Create test agent
nexus3 rpc create test-agent --preset trusted

# Test
nexus3 rpc send test-agent "Describe your capabilities"

# Verify behavior, then cleanup
nexus3 rpc destroy test-agent
```

### CI/CD

A GitLab CI example is provided in `.gitlab-ci.yml.example`. To use:

```bash
cp .gitlab-ci.yml.example .gitlab-ci.yml
```

The example includes:
- **Lint stage**: ruff check/format, mypy type checking
- **Test stage**: Separate jobs for unit, integration, security tests
- **Build stage**: Package building with artifacts
- **Multi-Python matrix**: Test on 3.11, 3.12, 3.13
- **Coverage reporting**: Cobertura format for GitLab integration

For CI, use the minimal dependency set:

```bash
pip install -e ".[ci]"  # No watchfiles, just test/lint tools
```

---

## License

MIT

---

## Additional Resources

- **CLAUDE.md**: Detailed development documentation and coding guidelines
- **Module READMEs**: Each `nexus3/*/README.md` has module-specific docs
- **Tests**: `tests/` directory has comprehensive examples

---

**Updated**: 2026-01-21
