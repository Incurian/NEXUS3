# NEXUS3

**Run structured teams of AI agents from your terminal.**

Most AI coding tools give you one agent in one conversation. NEXUS3 gives you a pool of agents — each with its own model, permissions, conversation context, and working directory — managed through a single terminal session or programmatic API. A layered permission system controls what each agent can access, with security defaults that prevent privilege escalation between agents. Sessions persist across restarts, and automatic context compaction keeps long-running conversations from hitting token limits.

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
- [GitLab Integration](#gitlab-integration)
- [MCP Integration](#mcp-integration)
- [Session Management](#session-management)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

## Key Features

### Agent Hierarchy with Permission Ceilings

Create teams of agents with structured parent-child relationships. A trusted coordinator can spawn sandboxed workers that can only read within their working directory and report results back to their parent — but can't message other agents, create their own subagents, or escalate their own permissions. This isn't configuration you bolt on; it's the default behavior.

### Security by Default

RPC-created agents are sandboxed automatically: restricted to their working directory, no shell execution, no network access. Three built-in presets (yolo, trusted, sandboxed) with per-tool enable/disable, per-tool path restrictions, and timeout controls. YOLO access is only available in the interactive REPL — it cannot be granted programmatically. Token-authenticated RPC, localhost-only binding, symlink-aware path validation, and process isolation round out the security model.

### Managed Agent Lifecycles

Agents are created, messaged, monitored, and destroyed through a consistent interface — whether from the interactive REPL, CLI commands, or the JSON-RPC API. This means you can incorporate agents into shell scripts, CI pipelines, or custom tooling with the same semantics as interactive use. Agents created this way inherit the same permission model, context management, and session persistence as REPL agents.

### Per-Agent Model Routing

Connect multiple LLM providers simultaneously — OpenRouter, Anthropic, OpenAI, Azure, Ollama, vLLM — and route different agents to different models. Use a fast local model for research agents and a frontier model for the coordinator. Switch models mid-session with `/model`. Automatic prompt caching reduces costs ~90% on cached tokens where providers support it.

### Interactive REPL

A streaming terminal interface with a session lobby, whisper mode for directing input to specific agents, and commands for managing agents, permissions, models, and configuration on the fly. Save, resume, and clone sessions with full state restoration — messages, model choice, permissions, working directory, and session-scoped allowances.

### Context Compaction

When an agent's context fills up, NEXUS3 summarizes older conversation history using a configurable model, preserves recent messages verbatim, reloads the system prompt (picking up any changes to NEXUS.md), and continues the session. This is automatic by default but can be triggered manually or tuned via config.

### Scoped Clipboard

A three-tier clipboard system (agent, project, system) lets agents store, retrieve, search, tag, and share structured content. Agent-scope entries live in memory for the session. Project and system scopes persist to SQLite across sessions. Clipboard entries are automatically injected into agent context so agents know what's available without explicit queries.

### 60+ Built-in Skills

39 core skills covering file operations, shell execution, git, unified diff patching, and inter-agent communication. 21 GitLab integration skills for issues, merge requests, pipelines, epics, approvals, time tracking, draft reviews, and more. Skills are permission-aware — what's available depends on the agent's preset, and file skills enforce per-tool path restrictions.

### Layered Configuration

System prompts (`NEXUS.md`) and config files load from multiple directory layers — package defaults, global user config, ancestor directories, and the project's working directory — and merge together. Project-specific instructions add to global ones rather than replacing them. Subagents automatically inherit context from their working directory.

### MCP Integration

Connect external tools via the Model Context Protocol. Supports stdio and HTTP transports, with environment variable sanitization, graceful degradation on connection failure, and lazy reconnection. MCP tools integrate into the same permission system as built-in skills.

---

## Requirements

### System Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | **Required.** Use `python3.11` or newer |
| Operating System | Linux, macOS, Windows, WSL2 | Native Windows support (3.11+) |
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
| vLLM (local) | N/A | [vllm.ai](https://docs.vllm.ai) |

**Why OpenRouter?** Single API key gives access to Claude, GPT-4, Gemini, Llama, and hundreds of other models. Great for experimentation.

### Windows Compatibility

NEXUS3 includes native Windows support (no WSL required):

- **ESC key detection** using `msvcrt` on Windows
- **Cross-platform process termination** (taskkill /T /F on Windows)
- **Line ending preservation** (CRLF/LF/CR) in file operations
- **Windows path sanitization** in error messages
- **BOM handling** in config file loading (utf-8-sig)
- **VT100 console mode** for ANSI sequence support
- **Windows environment variables** (USERPROFILE, APPDATA, etc.)

**Known limitations on Windows:**
- File permission bits (`chmod`) are no-op; rely on NTFS ACLs
- Symlink detection may miss NTFS junctions/reparse points

---

## Installation

> **Corporate Networks / SSL Issues:** If you're behind a corporate proxy with SSL inspection, both `git` and `pip` may fail with certificate errors. Configure your corporate CA certificate:
> ```bash
> # For pip (persistent)
> pip config set global.cert /path/to/corporate-ca.pem
>
> # For git
> git config --global http.sslCAInfo /path/to/corporate-ca.pem
> ```
> See [Certificate Formats](#certificate-formats) below for help identifying and converting your certificate.

### Step 1: Clone the Repository

```bash
git clone https://github.com/Incurian/NEXUS3.git
cd NEXUS3
```

### Step 2: Create a Virtual Environment

Linux, macOS, WSL:
```bash
python3.11 -m venv .venv
```

Windows, Git Bash:
```cmd
python -m venv .venv
```

**Activate the virtualenv:**

Linux, macOS, WSL:
```bash
source .venv/bin/activate
```

Git Bash:
```bash
source .venv/Scripts/activate
```

Windows (cmd):
```cmd
.venv\Scripts\activate
```

Windows (PowerShell):
```powershell
.venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies

With the virtualenv activated:

```bash
pip install -e ".[dev]"
```

### Step 4: Set Up API Key

**Option A: `.env` file (recommended, all platforms)**
```bash
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .env
```

This file is gitignored — never commit API keys.

**Option B: Environment variable (temporary, current session only)**

Linux, macOS, WSL, Git Bash:
```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

Windows (cmd):
```cmd
set OPENROUTER_API_KEY=sk-or-v1-...
```

Windows (PowerShell):
```powershell
$env:OPENROUTER_API_KEY="sk-or-v1-..."
```

**Option C: Persistent environment variable**

Linux, macOS, WSL, Git Bash — add to `~/.bashrc` or `~/.zshrc`:
```bash
echo 'export OPENROUTER_API_KEY="sk-or-v1-..."' >> ~/.bashrc
source ~/.bashrc
```

Windows (cmd or PowerShell):
```cmd
setx OPENROUTER_API_KEY "sk-or-v1-..."
```

### Step 5: Verify Installation

With the virtualenv activated:

```bash
python --version    # Should show 3.11+
python -c "import nexus3; print('NEXUS3 installed successfully')"
python -m nexus3 --help
```

Without the virtualenv activated, use the full path to `python` instead:

Linux, macOS, WSL:
```bash
.venv/bin/python
```

Git Bash:
```bash
.venv/Scripts/python
```

Windows (cmd/PowerShell):
```cmd
.venv\Scripts\python
```

### Step 6: Initialize Configuration (Recommended)

```bash
nexus3 --init-global
```

This creates `~/.nexus3/` with default `config.json`, `NEXUS.md`, and `mcp.json`. `~` resolves to your home directory on all platforms (e.g., `/home/user` on Linux, `C:\Users\YourName` on Windows).

After initialization, edit `~/.nexus3/NEXUS.md` to add personal instructions that apply to all your agents — coding style preferences, common project conventions, or any context you want every agent to have. See [Context Configuration](#context-configuration) for how NEXUS.md files work across layers.

### Path Setup (If `nexus3` Command Not Found)

With the virtualenv activated, `python -m nexus3` works on all platforms. For a permanent fix:

**Linux, macOS, WSL, Git Bash** — add pip's script directory to PATH:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**Windows (cmd/PowerShell)** — pip scripts are usually already on PATH if Python was installed with "Add to PATH" checked. If not, add `%APPDATA%\Python\Python3XX\Scripts` to your PATH via System Settings.

### Shell Alias (Recommended)

Create an alias that launches NEXUS3 in your current directory, passing through any arguments. This calls the virtualenv's Python directly by absolute path, so no activation or `cd` is needed. Replace `/path/to/NEXUS3` with your actual clone location.

**Linux, macOS, WSL** — add to `~/.bashrc` or `~/.zshrc`:
```bash
alias nexus3='/path/to/NEXUS3/.venv/bin/python -m nexus3'
```

**Git Bash** — add to `~/.bashrc`:
```bash
alias nexus3='/path/to/NEXUS3/.venv/Scripts/python -m nexus3'
```

**Windows (PowerShell)** — add to your `$PROFILE` (run `notepad $PROFILE` to edit):
```powershell
function nexus3 { & C:\path\to\NEXUS3\.venv\Scripts\python.exe -m nexus3 @args }
```

**Windows (cmd)** — save as `nexus3.bat` somewhere on your PATH:
```batch
@echo off
C:\path\to\NEXUS3\.venv\Scripts\python.exe -m nexus3 %*
```

After adding the alias, restart your shell or source your profile. Then `nexus3` works from any directory:

```bash
cd ~/my-project
nexus3 --fresh
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
      "deployment": "gpt4-deployment",
      "models": {
        "gpt4": {"id": "gpt-4-turbo", "context_window": 128000}
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
| `verify_ssl` | bool | `true` | Verify SSL certificates (set `false` for self-signed certs) |
| `ssl_ca_cert` | string | - | Path to CA certificate file (for corporate CAs) |
| `allow_insecure_http` | bool | `false` | Allow HTTP (non-HTTPS) for non-localhost URLs (security risk) |
| `prompt_caching` | bool | `true` | Enable prompt caching (reduces cost ~90% on cached tokens) |
| `models` | object | `{}` | Model aliases available through this provider |

### On-Prem / Self-Signed Certificates

For corporate/on-prem deployments where the LLM endpoint uses self-signed certificates or a corporate Certificate Authority (CA), you have two options:

#### Option 1: Disable SSL Verification (Quick but Less Secure)

Use `verify_ssl: false` to skip certificate verification entirely. This works but leaves connections vulnerable to man-in-the-middle attacks. Only use this for trusted internal networks:

```json
{
  "providers": {
    "onprem": {
      "type": "openai",
      "base_url": "https://internal-llm.company.com/v1",
      "api_key_env": "ONPREM_API_KEY",
      "verify_ssl": false,
      "models": {
        "internal": {"id": "llama-3-70b", "context_window": 8192}
      }
    }
  }
}
```

#### Option 2: Corporate CA Certificate (Recommended)

If your company has a corporate CA certificate, use `ssl_ca_cert` to point to it. This maintains full SSL verification using your organization's trust chain:

```json
{
  "providers": {
    "onprem": {
      "type": "openai",
      "base_url": "https://internal-llm.company.com/v1",
      "api_key_env": "ONPREM_API_KEY",
      "ssl_ca_cert": "/etc/ssl/certs/corporate-ca.pem",
      "models": {
        "internal": {"id": "llama-3-70b", "context_window": 8192}
      }
    }
  }
}
```

#### Certificate Formats

NEXUS3 expects certificates in **PEM format** (Base64-encoded text starting with `-----BEGIN CERTIFICATE-----`). Corporate certificates may come in various formats:

| Format | Extensions | Description | Works directly? |
|--------|------------|-------------|-----------------|
| **PEM** | `.pem`, `.crt`, `.cer` | Base64 text format | Yes |
| **DER** | `.der`, `.cer` | Binary format (common on Windows) | No - convert first |
| **PKCS#7** | `.p7b`, `.p7c` | Certificate chain bundle | No - convert first |
| **PKCS#12** | `.p12`, `.pfx` | Cert + private key (common on Windows) | No - convert first |

**How to identify your certificate format:**

```bash
# If this works, it's already PEM format - use as-is
openssl x509 -in corporate-ca.crt -text -noout

# If that fails with "unable to load certificate", try DER format
openssl x509 -inform DER -in corporate-ca.crt -text -noout
```

**Converting to PEM format:**

```bash
# DER to PEM
openssl x509 -inform DER -in corporate-ca.der -out corporate-ca.pem

# PKCS#7 to PEM (extracts all certs in chain)
openssl pkcs7 -print_certs -in corporate-ca.p7b -out corporate-ca.pem

# PKCS#12 to PEM (extract CA cert only, will prompt for password)
openssl pkcs12 -in corporate-ca.p12 -cacerts -nokeys -out corporate-ca.pem
```

**Common certificate locations:**

| OS | Typical location |
|----|------------------|
| Linux | `/etc/ssl/certs/`, `/usr/local/share/ca-certificates/` |
| macOS | `/etc/ssl/`, Keychain Access app |
| Windows | `C:\Users\<user>\certs\`, `C:\Windows\System32\certsrv\CertEnroll\`, Certificate Manager (`certmgr.msc`) |

Your IT department can provide the corporate CA certificate if you don't have it.

### Model Options Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | string | (required) | Model identifier sent to API |
| `context_window` | int | `131072` | Context window size in tokens |
| `reasoning` | bool | `false` | Enable extended thinking mode |
| `guidance` | string | - | Brief usage guidance (e.g., "Fast, cheap. Good for research.") |

For provider internals, retry logic, and adding new providers, see `nexus3/provider/README.md`.

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

assistant> I'm NEXUS3, an AI assistant with access to 60 tools for
software development tasks. I can:

• Read, write, and edit files
• Run shell commands and Python scripts
• Use git for version control
• Search codebases with glob and grep
• Create and coordinate sub-agents for parallel work

What would you like to work on?

you> /help
```

### Project Setup

To give agents project-specific context, run `/init` from within the REPL (or `nexus3 --init-global` for global config). This creates a `.nexus3/` directory with a `NEXUS.md` you can edit with any text editor:

```markdown
# Project Instructions

This is a Python web app using FastAPI and SQLAlchemy.
- Use pytest for tests
- Follow PEP 8
- Always run tests before committing
```

When NEXUS3 runs from this directory, agents automatically pick up these instructions alongside the global `~/.nexus3/NEXUS.md`. Project instructions are concatenated with (not replaced by) global ones. See [Context Configuration](#context-configuration) for the full layering system.

### Multi-Agent Workflows

NEXUS3 shines when you need multiple agents working together. Manage everything from within the REPL:

```
you> /create researcher --trusted
Created agent 'researcher'

you> /whisper researcher
[whisper → researcher]

researcher> Analyze the authentication module and list security concerns

(agent works autonomously...)

researcher> /over
[whisper ended]

you> /status researcher
researcher: 12,450 tokens used, idle

you> /destroy researcher
Destroyed agent 'researcher'
```

**Key commands:**
- `/create NAME --trusted` - Create a new agent
- `/whisper NAME` - Redirect your input to that agent
- `/over` - Return to your original agent
- `/status NAME` - Check agent's token usage and state
- `/list` - See all active agents

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
| `--reload` | Auto-reload on code changes (serve mode only, requires watchfiles) |

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-m, --model NAME` | Config default | Model alias or full ID |
| `--template PATH` | - | Custom system prompt file |
| `-v, --verbose` | false | Enable debug logging to terminal |
| `-V, --log-verbose` | false | Write debug output to verbose.md log file |
| `--raw-log` | false | Log raw API JSON |
| `--log-dir PATH` | `.nexus3/logs` | Log directory |
| `--api-key KEY` | Auto | Explicit API key |
| `--scan PORTS` | - | Additional ports to scan (e.g., `9000,9001-9010`) |

#### Initialization

| Flag | Description |
|------|-------------|
| `--init-global` | Create `~/.nexus3/` with default config |
| `--init-global-force` | Overwrite existing global config |

### REPL Slash Commands

Available when running interactively.

#### Agent Management

| Command | Description |
|---------|-------------|
| `/agent` | Show current agent detailed status |
| `/agent NAME` | Switch to agent (creates if needed) |
| `/agent NAME --yolo\|--trusted\|--sandboxed` | Create agent with preset and switch |
| `/agent NAME --model ALIAS` | Create agent with specific model |
| `/list` | List all active agents |
| `/create NAME [--preset] [--model]` | Create agent without switching |
| `/destroy NAME` | Remove agent from pool |
| `/send AGENT MESSAGE` | One-shot message to agent |
| `/status [AGENT] [--tools] [--tokens] [-a]` | Get agent status (`-a` for all details) |
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
| `/permissions --disable TOOL` | Disable a specific tool |
| `/permissions --enable TOOL` | Re-enable a disabled tool |
| `/permissions --list-tools` | List all tools and their status |
| `/prompt [FILE]` | Show or set system prompt |
| `/compact` | Force context compaction |
| `/init [--force] [--global]` | Initialize project config |
| `/gitlab` | Show GitLab configuration and skill reference |

#### MCP (External Tools)

| Command | Description |
|---------|-------------|
| `/mcp` | List configured and connected MCP servers |
| `/mcp connect NAME [flags]` | Connect to MCP server |
| `/mcp disconnect NAME` | Disconnect from server |
| `/mcp tools [SERVER]` | List available MCP tools |
| `/mcp resources [SERVER]` | List available MCP resources |
| `/mcp prompts [SERVER]` | List available MCP prompts |
| `/mcp retry NAME` | Retry tool listing for failed server |

**MCP connect flags:**
- `--allow-all` - Skip consent prompt, allow all tools
- `--per-tool` - Skip consent prompt, require per-tool confirmation
- `--shared` - Skip sharing prompt, share with all agents
- `--private` - Skip sharing prompt, keep private to this agent

#### REPL Control

| Command | Description |
|---------|-------------|
| `/help [COMMAND]` | Show help (optionally for specific command) |
| `/clear` | Clear screen |
| `/quit`, `/exit`, `/q` | Exit REPL |

#### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `ESC` | Cancel in-progress response |
| `Ctrl+C` | Interrupt current input |
| `Ctrl+D` | Exit REPL |
| `p` | View full tool details (during confirmation prompt) |

### RPC Commands (Programmatic Access)

For scripting, automation, or integrating NEXUS3 with external tools, use the `nexus3 rpc` subcommands. These provide the same functionality as REPL commands but from the shell.

**Note:** RPC commands require a running server (started via `nexus3` REPL or `NEXUS_DEV=1 nexus3 --serve`). They do **not** auto-start servers. All RPC commands support `-p, --port PORT` (default: 8765) and `--api-key KEY`.

| Command | Description |
|---------|-------------|
| `nexus3 rpc detect` | Check if server is running (exit code 0/1) |
| `nexus3 rpc list` | List all agents |
| `nexus3 rpc create ID [flags]` | Create agent |
| `nexus3 rpc send ID MESSAGE [-t SEC]` | Send message to agent |
| `nexus3 rpc status ID` | Get agent status (tokens + context) |
| `nexus3 rpc destroy ID` | Remove agent |
| `nexus3 rpc compact ID` | Force context compaction |
| `nexus3 rpc cancel ID REQ_ID` | Cancel in-progress request |
| `nexus3 rpc shutdown` | Stop the server |

**RPC create flags:**
- `--preset P` - Permission preset (`trusted` or `sandboxed`, default: sandboxed)
- `--cwd PATH` - Working directory / sandbox root
- `--write-path PATH` - Path where writes are allowed (can be repeated)
- `-m, --model NAME` - Model name/alias to use
- `-M, --message MSG` - Initial message to send immediately after creation
- `-t, --timeout SEC` - Timeout for initial message (default: 300)

**Security note:** RPC-created agents default to `sandboxed` (read-only). Use `--preset trusted` for write access or `--write-path PATH` for specific directories.

For REPL internals and UI components, see `nexus3/cli/README.md`. For RPC protocol details and authentication, see `nexus3/rpc/README.md`.

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
│  │  │  • ContextLoader (NEXUS.md + context loading)           │    │   │
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
| `core/` | Types, interfaces, errors, encoding, paths, URL validation, permissions, process termination |
| `config/` | Pydantic schema, permission config, fail-fast loader |
| `provider/` | AsyncProvider protocol, multi-provider support, prompt caching, retry logic |
| `context/` | ContextManager, ContextLoader, TokenCounter, compaction |
| `session/` | Session coordinator, persistence, SessionManager, SQLite logging |
| `skill/` | Skill protocol, SkillRegistry, ServiceContainer, 39 built-in + 21 GitLab skills |
| `clipboard/` | Scoped clipboard system (agent/project/system), SQLite storage |
| `patch/` | Unified diff parsing, validation, and application |
| `display/` | DisplayManager, StreamingDisplay, InlinePrinter, SummaryBar, theme |
| `cli/` | Unified REPL, lobby, whisper, HTTP server, client commands |
| `rpc/` | JSON-RPC protocol, Dispatcher, GlobalDispatcher, AgentPool, auth |
| `mcp/` | Model Context Protocol client, external tool integration |
| `commands/` | Unified command infrastructure for CLI and REPL |
| `defaults/` | Default configuration and system prompts |

Each module has its own `README.md` with detailed documentation.

---

## Security & Permissions

NEXUS3 implements a comprehensive security system with three permission levels.

### Permission Levels

| Level | Description | File Access | Execution | Agent Creation |
|-------|-------------|-------------|-----------|----------------|
| **YOLO** | Full access, no confirmations | Unrestricted | No prompts | TRUSTED or SANDBOXED children |
| **TRUSTED** | Interactive with confirmations | Read anywhere, write prompts outside CWD | Prompts required | SANDBOXED only |
| **SANDBOXED** | Isolated sandbox | CWD only | Disabled | Cannot create agents |

### Permission Presets

| Preset | Level | Description | Available Via |
|--------|-------|-------------|---------------|
| `yolo` | YOLO | Full access, no confirmations | REPL only |
| `trusted` | TRUSTED | CWD auto-allowed, prompts for other paths | REPL, RPC |
| `sandboxed` | SANDBOXED | CWD only, no execution, limited nexus tools | REPL, RPC (default) |

### Key Security Features

#### Permission Ceiling Enforcement

Child agents cannot exceed parent permissions:
- YOLO agents can create TRUSTED or SANDBOXED children (not YOLO)
- TRUSTED agents can only create SANDBOXED children
- SANDBOXED agents cannot create any agents (`nexus_create` disabled)

#### Path Sandboxing

- **Sandboxed agents**: Can only access files within their `cwd`
- **Symlink protection**: Resolved paths checked for sandbox escape
- **Per-tool paths**: Individual tools can have their own path restrictions via `allowed_paths`
- **Frozen paths**: SANDBOXED policy has `frozen=True`, preventing path modifications

#### RPC Security

- **Localhost binding**: Server only binds to `127.0.0.1`
- **Token authentication**: 256-bit tokens (32 bytes) with constant-time comparison via `hmac.compare_digest`
- **Token format**: `nxk_` prefix + URL-safe Base64 (e.g., `nxk_7Ks9XmN2pLqR4Tv8YbHc...`)
- **Request limits**: Body size (1MB), header limits, timeout protection
- **Secure tokens**: `0o600` permissions, per-port token files (`rpc.token` or `rpc-{port}.token`)
- **Permission checks**: Token files with insecure permissions (readable by group/others) are rejected in strict mode

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
- `shell_UNSAFE` always requires confirmation (no "allow always" option)

### Sandboxed Agent Tool Restrictions

SANDBOXED agents have these tools disabled:
- **Execution**: `bash_safe`, `shell_UNSAFE`, `run_python`
- **Agent management**: `nexus_create`, `nexus_destroy`, `nexus_shutdown`, `nexus_cancel`, `nexus_status`
- **Exception**: `nexus_send` is enabled but restricted to `allowed_targets="parent"` (can only message parent)

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

In TRUSTED mode, destructive operations prompt for confirmation. The available options depend on the tool type:

**File writes** (`write_file`, `edit_file`, `append_file`, etc.):
```
Allow write_file?
  Path: /etc/hosts
  Content: ...

  [1] Allow once
  [2] Allow always for this file
  [3] Allow always in this directory
  [4] Deny
  [p] View full details
```

**Execution** (`bash_safe`, `run_python`):
```
Execute bash_safe?
  Command: make build

  [1] Allow once
  [2] Allow always in this directory
  [3] Deny
  [p] View full details
```

**Shell unsafe** (`shell_UNSAFE`) — no "allow always" options, always requires explicit approval:
```
Execute shell_UNSAFE?
  Command: curl ... | sh

  [1] Allow once
  [2] Deny
  [p] View full details
```

**MCP tools**:
```
Allow MCP tool 'mcp_github_create_issue'?

  [1] Allow once
  [2] Allow this tool always (this session)
  [3] Allow all tools from this server (this session)
  [4] Deny
  [p] View full details
```

The `[p]` option opens full tool call details in a pager for review before deciding.

### Session Allowances

"Allow always" choices persist for the session as allowances:

- **File allowances**: Allow writes to a specific file
- **Directory allowances**: Allow writes anywhere in a directory
- **Execution allowances**: Allow a tool in a specific working directory
- **MCP allowances**: Allow a specific tool or all tools from a server

These are stored in `SessionAllowances`, checked before prompting, and saved/restored with sessions.

For permission internals, path validation, and the policy engine, see `nexus3/core/README.md`.

---

## Configuration Reference

### File Locations and Merging

NEXUS3 loads configuration from multiple layers. Each layer can override or extend the previous one:

```
1. Shipped defaults     nexus3/defaults/config.json    (auto-updates with package)
2. Global user          ~/.nexus3/config.json           (your personal defaults)
3. Ancestor dirs        ../.nexus3/config.json          (up to 2 levels above cwd)
4. Project local        ./.nexus3/config.json           (project-specific overrides)
```

**How merging works:**

- **Scalar values** (strings, numbers, bools): later layer overwrites earlier
- **Objects** (`providers`, `permissions`, `gitlab`): deep merged — keys from both layers are combined, with later layer winning on conflicts
- **Arrays** (`mcp_servers`): later layer **replaces** entirely (not appended)

If `~/.nexus3/config.json` exists, it's used as the base. If not, the shipped defaults are used instead. They are never merged together.

**System prompt (NEXUS.md)** merging works differently — all layers are **concatenated** with labeled sections, not overridden. See [Context Configuration](#context-configuration).

**MCP servers (mcp.json)** are loaded separately from `config.json` and merged by server name — a project-local server with the same name as a global one replaces it. See [MCP Configuration](#mcp-configuration).

### Directory Structure

```
~/.nexus3/                          # Global (user defaults)
├── config.json                     # Global settings
├── NEXUS.md                        # Personal system prompt
├── mcp.json                        # Personal MCP servers
├── rpc.token                       # RPC auth token (default port)
├── rpc-{port}.token                # RPC auth token (non-default ports)
├── sessions/                       # Saved sessions
├── last-session.json               # Auto-saved for --resume
├── last-session-name               # Name of last session
└── logs/                           # Logs
    └── server.log                  # Server lifecycle events

./.nexus3/                          # Project-local
├── config.json                     # Project overrides (deep merged with global)
├── NEXUS.md                        # Project system prompt (concatenated with global)
├── mcp.json                        # Project MCP servers (same name = override)
└── logs/                           # Session logs
    └── {session-id}/
        ├── session.db              # SQLite message history
        ├── context.md              # Markdown transcript
        ├── verbose.md              # Debug output (if -V enabled)
        └── raw.jsonl               # Raw API JSON (if --raw-log enabled)
```

### Root Configuration Options

```json
{
  "default_model": "haiku",
  "providers": { },
  "stream_output": true,
  "max_tool_iterations": 10,
  "skill_timeout": 30.0,
  "max_concurrent_tools": 10,
  "compaction": { },
  "context": { },
  "clipboard": { },
  "mcp_servers": [ ],
  "server": { },
  "default_permission_level": "trusted",
  "permissions": { },
  "gitlab": { }
}
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `default_model` | string | `"haiku"` | Model alias to use by default |
| `default_permission_level` | string | `"trusted"` | Default permission level for REPL agents |
| `providers` | object | `{}` | Provider configurations — see [Provider Configuration](#provider-configuration) |
| `stream_output` | bool | `true` | Stream LLM responses token-by-token |
| `max_tool_iterations` | int | `10` | Max tool calls per turn |
| `skill_timeout` | float | `30.0` | Default tool timeout in seconds |
| `max_concurrent_tools` | int | `10` | Parallel tool execution limit |
| `compaction` | object | see below | Context compaction — see [Compaction Configuration](#compaction-configuration) |
| `context` | object | see below | Context loading — see [Context Configuration](#context-configuration) |
| `clipboard` | object | see below | Clipboard system — see [Clipboard Configuration](#clipboard-configuration) |
| `mcp_servers` | array | `[]` | MCP servers (in config.json) — see [MCP Configuration](#mcp-configuration) |
| `server` | object | see below | HTTP server — see [Server Configuration](#server-configuration) |
| `permissions` | object | see below | Permission presets — see [Permissions Configuration](#permissions-configuration) |
| `gitlab` | object | see below | GitLab instances — see [GitLab Configuration](#gitlab-configuration) |

**Note:** The shipped `defaults/config.json` uses more permissive values: `max_tool_iterations: 100`, `skill_timeout: 120.0`, and `default_model: "fast"`. If you create a global config with `nexus3 --init-global`, it copies these shipped defaults.

### Compaction Configuration

See [Context Compaction](#context-compaction) in Session Management for behavior details.

```json
{
  "compaction": {
    "enabled": true,
    "model": null,
    "trigger_threshold": 0.9,
    "summary_budget_ratio": 0.25,
    "recent_preserve_ratio": 0.25,
    "redact_secrets": true
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable automatic compaction |
| `model` | `null` | Model alias for summarization (`null` = use default_model). Shipped defaults use `"fast"`. |
| `trigger_threshold` | `0.9` | Trigger when 90% of context used |
| `summary_budget_ratio` | `0.25` | Max 25% of tokens for summary |
| `recent_preserve_ratio` | `0.25` | Keep 25% of recent messages verbatim |
| `redact_secrets` | `true` | Redact secrets before sending to summarization model |

### Prompt Caching

A per-provider setting. Enabled by default — reduces costs by reusing cached system prompt tokens across requests.

| Provider | Support | Notes |
|----------|---------|-------|
| Anthropic | Full | Automatic cache breakpoints on system prompt |
| OpenAI | Full | Automatic (OpenAI manages caching server-side) |
| Azure | Full | Same as OpenAI |
| OpenRouter | Pass-through | Automatic for Anthropic models via OpenRouter |
| Ollama / vLLM | N/A | Local inference, no caching needed |

To disable for a specific provider, set `prompt_caching: false` in the provider config:

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

Cache metrics are logged at DEBUG level (visible with `-v` flag). See [Provider Options Reference](#provider-options-reference) for the full list of per-provider settings.

### Context Configuration

NEXUS3 uses a split system prompt design:

- **`NEXUS-DEFAULT.md`** — Baked into the package (`nexus3/defaults/`). Contains tool documentation, permission system reference, troubleshooting, and system knowledge. Auto-updates with package upgrades. Users never need to edit this.
- **`NEXUS.md`** — User-customizable. Contains custom instructions, project context, and preferences. Preserved across upgrades.

This split means users get new tool documentation automatically while their custom instructions remain untouched.

#### NEXUS.md Layer Hierarchy

NEXUS.md files are loaded from multiple directories and **concatenated** (not overridden) with labeled section headers showing their source. Every layer's instructions are included, so project-specific instructions add to global ones:

```
0. nexus3/defaults/NEXUS-DEFAULT.md      # Package — tool docs, permissions (auto-updates)
1. ~/.nexus3/NEXUS.md                    # Global — your personal defaults
2. ../../.nexus3/NEXUS.md                # Ancestor — org or workspace level
3. ../.nexus3/NEXUS.md                   # Ancestor — parent project
4. ./.nexus3/NEXUS.md                    # Local — this project's instructions
```

**What to put where:**

| File | Purpose | Example Content |
|------|---------|-----------------|
| `~/.nexus3/NEXUS.md` | Personal defaults for all projects | Coding style, preferred languages, common tools |
| `.nexus3/NEXUS.md` (project) | Project-specific context | Architecture overview, testing conventions, key file locations |
| `../../.nexus3/NEXUS.md` (ancestor) | Shared across related projects | Org-wide conventions, monorepo standards |

**Creating project instructions:**

```bash
# From within the REPL
/init                    # Creates .nexus3/ in current directory

# Or manually
mkdir -p .nexus3
# Then create .nexus3/NEXUS.md with your project instructions
```

Subagents created with a `cwd` parameter automatically pick up the NEXUS.md from their working directory.

#### Context Config Options

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
| `ancestor_depth` | `2` | Parent directories to search for `.nexus3/` (0-10) |
| `include_readme` | `false` | Always include README.md alongside NEXUS.md |
| `readme_as_fallback` | `false` | Use README.md when no NEXUS.md exists |

### Server Configuration

See [Server Modes](#server-modes) in CLI Reference for usage.

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8765,
    "log_level": "INFO"
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `host` | `"127.0.0.1"` | Host address to bind (use `0.0.0.0` for all interfaces) |
| `port` | `8765` | Port number (1-65535) |
| `log_level` | `"INFO"` | Logging level: DEBUG, INFO, WARNING, ERROR |

**Security note:** Default `127.0.0.1` binding restricts access to localhost only. Using `0.0.0.0` exposes the server to the network.

### Clipboard Configuration

See [Clipboard](#clipboard) in Built-in Skills for usage and scope details.

```json
{
  "clipboard": {
    "enabled": true,
    "inject_into_context": true,
    "max_injected_entries": 10,
    "show_source_in_injection": true,
    "max_entry_bytes": 1048576,
    "warn_entry_bytes": 102400,
    "default_ttl_seconds": null
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable clipboard tools |
| `inject_into_context` | `true` | Auto-inject clipboard index into system prompt |
| `max_injected_entries` | `10` | Maximum entries to show in context injection (0-50) |
| `show_source_in_injection` | `true` | Show source path/lines in context injection |
| `max_entry_bytes` | `1048576` | Maximum size per entry (1MB default) |
| `warn_entry_bytes` | `102400` | Warning threshold for large entries (100KB) |
| `default_ttl_seconds` | `null` | Default TTL for new entries (`null` = permanent) |

### MCP Configuration

MCP servers can be configured in two places:

- **`mcp.json`** (standalone file in `~/.nexus3/` or `.nexus3/`) — recommended
- **`mcp_servers`** array in `config.json` — alternative

When using `mcp.json`, two key formats are supported:

```json
{"servers": {"name": {...}}}
{"mcpServers": {"name": {...}}}
```

The `mcpServers` format is compatible with Claude Desktop configs.

Per-server options:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | string or array | - | Command to launch stdio server |
| `args` | array | `[]` | Arguments (when command is a string) |
| `url` | string | - | URL for HTTP server (mutually exclusive with `command`) |
| `env` | object | `{}` | Explicit environment variables for the server |
| `env_passthrough` | array | `[]` | Host env var names to forward to the server |
| `cwd` | string | - | Working directory for subprocess |
| `enabled` | bool | `true` | Whether server is enabled |

**Merging:** MCP servers loaded from project-local `mcp.json` override global servers with the same name. See [MCP Integration](#mcp-integration) for full usage details.

### Permissions Configuration

See [Security & Permissions](#security--permissions) for behavior details.

```json
{
  "permissions": {
    "default_preset": "sandboxed",
    "destructive_tools": ["write_file", "edit_file", "bash_safe", "shell_UNSAFE", "run_python", "nexus_destroy", "nexus_shutdown"],
    "presets": {
      "researcher": {
        "extends": "sandboxed",
        "description": "Read-only research agent",
        "tool_permissions": {
          "bash_safe": {"timeout": 10}
        }
      }
    }
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `default_preset` | `"sandboxed"` | Default preset for new RPC agents |
| `destructive_tools` | (see above) | Tools that require confirmation in TRUSTED mode |
| `presets` | `{}` | Custom permission presets (extend built-in ones) |

**Custom preset options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `extends` | string | - | Built-in preset to inherit from (`trusted`, `sandboxed`) |
| `description` | string | `""` | Human-readable description |
| `allowed_paths` | array | `null` | Path whitelist (`null` = unrestricted) |
| `blocked_paths` | array | `[]` | Paths always blocked |
| `tool_permissions` | object | `{}` | Per-tool overrides (`enabled`, `timeout`, `allowed_paths`) |

### GitLab Configuration

See [GitLab Integration](#gitlab-integration) for setup and available skills.

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

| Option | Default | Description |
|--------|---------|-------------|
| `instances` | `{}` | Named GitLab instance configurations |
| `default_instance` | `null` | Instance to use when not specified |

**Instance options:**

| Option | Description |
|--------|-------------|
| `url` | GitLab instance URL |
| `token_env` | Environment variable containing API token (recommended) |
| `token` | Direct token value (not recommended — use `token_env`) |
| `username` | GitLab username — enables `"me"` shorthand in assignees, reviewers, and list filters |
| `email` | Email associated with this GitLab account |
| `user_id` | Numeric user ID — skips API lookup when resolving `"me"` (auto-resolved if omitted) |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `AZURE_OPENAI_KEY` | Azure OpenAI API key |
| `NEXUS_DEV=1` | Enable `--serve` headless mode |
| `NEXUS3_API_KEY` | RPC token fallback (checked after token files) |

For configuration loading internals and validation, see `nexus3/config/README.md`.

---

## Built-in Skills

NEXUS3 includes 39 built-in skills organized by category, plus 21 GitLab integration skills (see [GitLab Integration](#gitlab-integration)).

### File Operations (Read)

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `read_file` | Read file contents | `path`, `offset`, `limit` |
| `tail` | Read last N lines | `path`, `lines` (default: 10) |
| `file_info` | Get file metadata | `path` |
| `list_directory` | List directory contents | `path`, `all`, `long` |
| `glob` | Find files by pattern | `pattern`, `path`, `exclude` |
| `grep` | Search file contents | `pattern`, `path`, `include`, `context`, `recursive`, `ignore_case`, `max_matches` |
| `concat_files` | Concatenate files by extension | `extensions`, `path`, `exclude`, `lines`, `max_total`, `format`, `sort`, `gitignore`, `dry_run` |

### File Operations (Write)

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `write_file` | Write/create file | `path`, `content` |
| `edit_file` | String replacement (single or batched) | `path`, `old_string`, `new_string`, `replace_all`, `edits` |
| `edit_lines` | Line-based replacement | `path`, `start_line`, `end_line`, `new_content` |
| `append_file` | Append to file | `path`, `content`, `newline` |
| `regex_replace` | Regex find/replace | `path`, `pattern`, `replacement`, `count`, `ignore_case`, `multiline`, `dotall` |
| `patch` | Apply unified diffs | `target`, `diff`, `diff_file`, `mode`, `fuzzy_threshold`, `dry_run` |
| `copy_file` | Copy file | `source`, `destination`, `overwrite` |
| `mkdir` | Create directory | `path` |
| `rename` | Move/rename file | `source`, `destination`, `overwrite` |

### Execution

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `bash_safe` | Execute command (no shell operators) | `command`, `timeout`, `cwd` |
| `shell_UNSAFE` | Execute with full shell (pipes, redirects) | `command`, `timeout`, `cwd` |
| `run_python` | Execute Python code | `code`, `timeout`, `cwd` |

**Safety notes:**
- `bash_safe` uses `shlex.split()` — shell operators (`|`, `&&`, `>`) do NOT work
- Use `shell_UNSAFE` only when you need shell features AND trust the input
- `shell_UNSAFE` always requires confirmation (no "allow always" option)
- Default timeout: 30 seconds, max: 300 seconds

### Version Control

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `git` | Execute git commands | `command`, `cwd` |

Git commands are filtered by permission level:
- **SANDBOXED**: Read-only (`status`, `diff`, `log`, `show`, `branch`, `blame`, etc.)
- **TRUSTED**: Read + write, dangerous flags blocked (`--force`, `--hard`)
- **YOLO**: All commands allowed

### Agent Management

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `nexus_create` | Create agent | `agent_id`, `preset`, `cwd`, `allowed_write_paths`, `disable_tools`, `model`, `initial_message`, `wait_for_initial_response`, `port` |
| `nexus_destroy` | Destroy agent | `agent_id`, `port` |
| `nexus_send` | Send message to agent | `agent_id`, `content`, `port` |
| `nexus_status` | Get agent status | `agent_id`, `port` |
| `nexus_cancel` | Cancel request | `agent_id`, `request_id`, `port` |
| `nexus_shutdown` | Shutdown server | `port` |

**Note:** All `nexus_*` skills default to port 8765.

### Utility

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `sleep` | Pause execution | `seconds`, `label` |

### Clipboard

Scoped clipboard system for sharing content between agents and sessions.

| Skill | Description | Key Parameters |
|-------|-------------|----------------|
| `copy` | Copy file content to clipboard | `source`, `key`, `scope`, `start_line`, `end_line`, `short_description`, `tags`, `ttl_seconds` |
| `cut` | Cut file content to clipboard (removes from source) | `source`, `key`, `scope`, `start_line`, `end_line`, `short_description`, `tags`, `ttl_seconds` |
| `paste` | Paste clipboard content to file | `key`, `target`, `scope`, `mode`, `line_number`, `start_line`, `end_line`, `marker`, `create_if_missing` |
| `clipboard_list` | List clipboard entries | `scope`, `tags`, `any_tags`, `verbose` |
| `clipboard_get` | Get full content of an entry | `key`, `scope` |
| `clipboard_update` | Update entry metadata or content | `key`, `scope`, `new_key`, `short_description`, `content`, `source`, `start_line`, `end_line`, `ttl_seconds` |
| `clipboard_delete` | Delete an entry | `key`, `scope` |
| `clipboard_clear` | Clear all entries in a scope | `scope`, `confirm` |
| `clipboard_search` | Search entries by query | `query`, `scope`, `max_results` |
| `clipboard_tag` | Manage tags | `action`, `entry_key`, `name`, `scope`, `description` |
| `clipboard_export` | Export entries to JSON | `path`, `scope`, `tags` |
| `clipboard_import` | Import entries from JSON | `path`, `scope`, `conflict`, `dry_run` |

**Scopes:**
- `agent`: Session-only (in-memory), isolated per agent
- `project`: Persistent (SQLite), shared within project
- `system`: Persistent (SQLite), shared globally

**Permission restrictions:**
- YOLO: Full access to all scopes
- TRUSTED: Read/write agent+project, read-only system
- SANDBOXED: Agent scope only

### Skill Availability by Permission Level

| Skill Category | YOLO | TRUSTED | SANDBOXED |
|----------------|------|---------|-----------|
| File read | All | All | CWD only |
| File write | All | Confirmations | Disabled (unless `allowed_write_paths`) |
| Clipboard | All scopes | Agent + project (read/write), system (read) | Agent scope only |
| Execution | All | Confirmations | Disabled |
| Git | All | Write commands | Read-only |
| Agent management | All | Sandboxed children only | `nexus_send` to parent only |
| GitLab | All | Confirmations for destructive | Disabled |

For the skill system architecture, base classes, and creating custom skills, see `nexus3/skill/README.md`.

---

## GitLab Integration

Full GitLab integration with 21 skills covering issues, merge requests, CI/CD, and more.

### Setup

1. Add GitLab configuration to `~/.nexus3/config.json` or `.nexus3/config.json`:

```json
{
  "gitlab": {
    "instances": {
      "default": {
        "url": "https://gitlab.com",
        "token_env": "GITLAB_TOKEN",
        "username": "your-gitlab-username"
      }
    },
    "default_instance": "default"
  }
}
```

2. Set your GitLab personal access token (requires `api` scope). Easiest: add to your `.env` file:
```
GITLAB_TOKEN=glpat-...
```
Or set as an environment variable (`export` on Linux/macOS, `set`/`setx` on Windows).

3. Use TRUSTED or YOLO permission level (SANDBOXED agents cannot use GitLab tools):
```bash
/permissions trusted              # In REPL
nexus3 rpc create worker --preset trusted  # RPC
```

### Available Skills

| Category | Skills | Description |
|----------|--------|-------------|
| **Foundation** | `gitlab_repo`, `gitlab_issue`, `gitlab_mr`, `gitlab_label`, `gitlab_branch`, `gitlab_tag` | Core repository operations |
| **Project Management** | `gitlab_epic`, `gitlab_iteration`, `gitlab_milestone`, `gitlab_board`, `gitlab_time` | Planning and tracking (some require GitLab Premium) |
| **Code Review** | `gitlab_approval`, `gitlab_draft`, `gitlab_discussion` | MR reviews and discussions |
| **CI/CD** | `gitlab_pipeline`, `gitlab_job`, `gitlab_artifact`, `gitlab_variable` | Pipeline and job management |
| **Config** | `gitlab_deploy_key`, `gitlab_deploy_token`, `gitlab_feature_flag` | Deployment configuration |

Use `/gitlab` in the REPL for quick reference on GitLab operations and examples.

For full configuration options, see [GitLab Configuration](#gitlab-configuration) in the Configuration Reference. For GitLab skill internals, see `nexus3/skill/vcs/README.md`.

---

## MCP Integration

NEXUS3 supports the Model Context Protocol (MCP) for connecting external tools. MCP enables agents to discover and invoke tools, resources, and prompts from external servers.

### Key Features

- **Multi-transport support:** Connect via stdio (subprocess) or HTTP
- **Full MCP support:** Tools, Resources, and Prompts with cursor-based pagination
- **Graceful degradation:** Connections succeed even if initial tool listing fails
- **Lazy reconnection:** Dead connections automatically reconnect when tools are needed
- **Security hardening:** Environment sanitization, response validation, permission enforcement

### Configuration

Create `mcp.json` in `~/.nexus3/` (global) or `.nexus3/` (project).

### Server Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | `str \| list[str]` | - | Command to launch stdio server |
| `args` | `list[str]` | `[]` | Arguments (when command is a string) |
| `url` | `str` | - | URL for HTTP server (mutually exclusive with `command`) |
| `env` | `dict[str, str]` | `{}` | Explicit environment variables |
| `env_passthrough` | `list[str]` | `[]` | Host env var names to pass through |
| `cwd` | `str` | - | Working directory for subprocess |
| `enabled` | `bool` | `true` | Whether server is enabled |

### Example Configuration

**mcp.json** uses `"servers"` (NEXUS3 format) or `"mcpServers"` (official/Claude Desktop format):

```json
{
  "servers": {
    "test-server": {
      "command": [".venv/bin/python", "-m", "nexus3.mcp.test_server"],
      "enabled": true
    },
    "agentbridge": {
      "command": [
        "/mnt/d/tempo/TempoSample/TempoEnv/Scripts/python.exe",
        "-m", "mcp",
        "--host", "localhost",
        "--port", "10001"
      ],
      "cwd": "/mnt/d/tempo/TempoSample/Plugins/AgentBridge",
      "env": {
        "TEMPO_API_PATH": "/mnt/d/tempo/TempoSample/Plugins/Tempo/TempoCore/Content/Python/API/tempo"
      },
      "enabled": true
    }
  }
}
```

**Alternative format (Claude Desktop compatible):**

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "..."}
    }
  }
}
```

**Note:** In `config.json`, use `"mcp_servers": [...]` array format instead.

### Transport Types

**Stdio (Subprocess):** Most MCP servers use stdio. The server runs as a subprocess with JSON-RPC over stdin/stdout.

**HTTP:** For remote MCP servers (less common).

### Environment Variable Security

MCP servers only receive safe environment variables by default (PATH, HOME, USER, LANG, etc.). To pass secrets:

```json
{
  "servers": {
    "github": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
      "env_passthrough": ["GITHUB_TOKEN"],
      "env": {"EXTRA_VAR": "explicit-value"}
    }
  }
}
```

### REPL Commands

| Command | Description |
|---------|-------------|
| `/mcp` | List servers and status |
| `/mcp connect NAME` | Connect to server |
| `/mcp connect NAME --allow-all --shared` | Skip prompts, share with agents |
| `/mcp disconnect NAME` | Disconnect |
| `/mcp tools [SERVER]` | List available MCP tools |
| `/mcp resources [SERVER]` | List available MCP resources |
| `/mcp prompts [SERVER]` | List available MCP prompts |
| `/mcp retry NAME` | Retry tool listing for server |

**Connect flags:**
- `--allow-all` / `--per-tool`: Consent mode for tool access
- `--shared` / `--private`: Visibility mode for other agents

### Permission Requirements

| Level | MCP Access | Confirmation |
|-------|------------|--------------|
| YOLO | Yes | Never |
| TRUSTED | Yes | First access per server |
| SANDBOXED | No | N/A |

### Key Behaviors

- **Servers connect even if initial tool listing fails** (graceful degradation)
- **Dead connections automatically reconnect** when tools are needed (lazy reconnection)
- Use `/mcp retry <server>` to manually retry tool listing after fixing configuration issues

For detailed MCP configuration and protocol coverage, see `nexus3/mcp/README.md`.

---

## Session Management

### Startup Flow

When you run `nexus3` without flags, you see the **lobby**:

```
NEXUS3 REPL

  1) Resume: my-project (2h ago, 45 messages)
  2) Fresh session
  3) Choose from saved...

[1/2/3/q]:
```

**Skip the lobby with flags:**
- `nexus3 --fresh` - Start new temporary session
- `nexus3 --resume` - Resume last session
- `nexus3 --session NAME` - Load specific saved session

### Session Types

| Type | Name Pattern | Can Save? | Auto-saved? |
|------|--------------|-----------|-------------|
| Temporary | `.1`, `.2`, etc. | Only with explicit name | Yes (to last-session.json) |
| Named | Any name | Yes | Yes |

### REPL Commands

| Command | Description |
|---------|-------------|
| `/save [name]` | Save current session (prompts for name if temp) |
| `/clone <src> <dest>` | Clone agent or saved session |
| `/rename <old> <new>` | Rename agent or saved session |
| `/delete <name>` | Delete saved session from disk |

### What Gets Persisted

| Data | Saved | Restored |
|------|-------|----------|
| Messages | Yes | Yes |
| System prompt | Yes | Yes |
| System prompt path | Yes | Yes |
| Working directory | Yes | Yes |
| Permission level | Yes | Yes |
| Permission preset | Yes | Yes |
| Disabled tools | Yes | Yes |
| Session allowances | Yes | Yes |
| Model alias | Yes | Yes |
| Token usage | Yes | Display only |
| Created/modified timestamps | Yes | Yes |
| Provenance | Yes | Yes |
| Agent-scope clipboard entries | Yes | Yes |

Sessions use schema version 1 with backwards-compatible field defaults.

### Session Files Location

```
~/.nexus3/
├── sessions/                 # Named session files
│   └── myproject.json        # Saved via /save
├── last-session.json         # Auto-saved for --resume
└── last-session-name         # Name of last session

.nexus3/logs/{session-id}/    # Session logs
├── session.db                # SQLite message history
├── context.md                # Markdown transcript
├── verbose.md                # Debug output (if -V enabled)
└── raw.jsonl                 # Raw API JSON (if --raw-log enabled)
```

### Context Compaction

When context gets full (90% by default), NEXUS3 automatically:
1. Preserves recent messages (25%)
2. Summarizes older messages using a fast model (with secrets redacted)
3. Reloads NEXUS.md (picking up any changes)
4. Adds a timestamped summary marker for temporal context

Manual compaction:
```bash
/compact                    # REPL
nexus3 rpc compact AGENT_ID # RPC
```

For detailed session internals, see `nexus3/session/README.md`. For context management and compaction, see `nexus3/context/README.md`.

---

## Troubleshooting

### Installation Issues

**Problem: `python: command not found`**

Activate your virtualenv first (see [Installation Step 2](#step-2-create-a-virtual-environment)), or use the full path: `.venv/bin/python` (Linux, macOS, WSL), `.venv/Scripts/python` (Git Bash), or `.venv\Scripts\python` (Windows cmd/PowerShell). On Linux/macOS/WSL you can also try `python3.11` directly.

**Problem: `nexus3: command not found`**

Use `python -m nexus3` (all platforms). See [Path Setup](#path-setup-if-nexus3-command-not-found) for permanent fixes.

**Problem: `ModuleNotFoundError: No module named 'nexus3'`**

Activate the virtualenv and install:
```bash
pip install -e .
```

### API Key Issues

**Problem: `AuthenticationError: API key not found`**

Check that your API key is set. The easiest cross-platform approach is a `.env` file (see [Installation Step 4](#step-4-set-up-api-key)):
```bash
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .env
```

To check if it's set in your current environment:

Linux, macOS, WSL, Git Bash:
```bash
echo $OPENROUTER_API_KEY
```

Windows (cmd):
```cmd
echo %OPENROUTER_API_KEY%
```

Windows (PowerShell):
```powershell
echo $env:OPENROUTER_API_KEY
```

### Server Issues

**Problem: `Address already in use: 8765`**

Find and kill the existing server process:

Linux, macOS, WSL:
```bash
lsof -i :8765
kill <PID>
```

Windows, Git Bash:
```cmd
netstat -ano | findstr :8765
taskkill /PID <PID> /F
```

Or use a different port: `nexus3 --serve 9000`

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

**Problem: Sandboxed agent can't read files outside its cwd**

This is intentional security behavior. Sandboxed agents have `allowed_paths` set to their `cwd` only:
```bash
# Set cwd to project root
nexus3 rpc create worker --cwd /path/to/project

# Or use trusted preset for broader read access
nexus3 rpc create worker --preset trusted --cwd /path/to/project
```

**Problem: `nexus_send` fails with "Cannot send to YOLO agent"**

YOLO agents can only receive messages when the REPL is actively connected to them. This prevents unsupervised YOLO operations. Use trusted preset for RPC agents instead.

### Session Issues

**Problem: `--resume` says "No last session found"**

The last session file (`~/.nexus3/last-session.json`) is created on REPL exit. If the previous session crashed or was force-killed, no file exists. Start a new session with `--fresh`.

**Problem: Session won't save with `/save`**

Temp sessions (named `.1`, `.2`, etc.) require a name argument:
```bash
/save my-session    # Provide a name for temp sessions
```

**Problem: Session not found when using `--session NAME`**

Session files are stored in `~/.nexus3/sessions/`. Check available sessions:
```bash
ls ~/.nexus3/sessions/
```

### MCP Issues

**Problem: MCP server connection fails**

Check if the server is configured correctly:
```bash
/mcp                # List configured servers and connection status
```

Common causes:
- Server executable not in PATH
- Missing environment variables referenced in config
- Firewall blocking local connections

**Problem: MCP tools not showing after connect**

Servers connect even if initial tool listing fails (graceful degradation). Retry tool listing:
```bash
/mcp retry <server-name>
```

**Problem: SANDBOXED agent can't use MCP tools**

Only TRUSTED and YOLO agents can access MCP tools. This is a security restriction:
```bash
nexus3 rpc create worker --preset trusted
```

### Permission Issues

**Problem: Clipboard operations fail with "No permission for system clipboard"**

Clipboard scope permissions depend on preset:
- `yolo`: Full access to agent/project/system
- `trusted`: Read/write agent+project, read-only system
- `sandboxed`: Agent scope only (in-memory)

**Problem: GitLab tools blocked**

GitLab tools require TRUSTED or YOLO permission level:
```bash
/permissions trusted    # In REPL
nexus3 rpc create worker --preset trusted  # RPC
```

### Windows-Specific Issues

**Problem: Characters display incorrectly (boxes, question marks)**

Set UTF-8 code page before running:
```cmd
chcp 65001
nexus3
```

**Problem: ANSI colors/formatting not working**

Use Windows Terminal or Git Bash for full ANSI support. CMD.exe and PowerShell 5.1 have limited or no ANSI support. NEXUS3 auto-detects the shell and displays a warning.

**Problem: Process cleanup warnings on timeout**

Windows uses `taskkill /T /F` for process tree termination. Some processes may not clean up as gracefully as on Unix.

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
nexus3 -v                 # Debug output to terminal (short form)
nexus3 --verbose          # Debug output to terminal (long form)
nexus3 -V                 # Debug output to verbose.md log file
nexus3 --log-verbose      # Debug output to verbose.md log file (long form)
```

**Check if server is running:**
```bash
nexus3 rpc detect         # Returns exit code 0 if running, 1 if not
nexus3 rpc detect --port 9000  # Check specific port
```

**Use a different port (if default port in use):**
```bash
nexus3 rpc list --port 9000
```

**Check server logs:**
```bash
tail -f .nexus3/logs/server.log
```

**Check session logs:**
```bash
ls -la .nexus3/logs/
cat .nexus3/logs/{session-id}/context.md
```

**Enable raw API logging:**
```bash
nexus3 --raw-log          # Log raw API JSON to raw.jsonl
```

---

## Development

> **Note:** Commands below use `.venv/bin/` paths. On Git Bash use `.venv/Scripts/`, on Windows cmd/PowerShell use `.venv\Scripts\`. Or just activate the virtualenv and use bare commands (`pytest`, `ruff`, `mypy`).

### Running Tests

```bash
# All tests (3400+)
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
from nexus3.skill.base import BaseSkill, base_skill_factory
from nexus3.core.types import ToolResult

@base_skill_factory
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

# Factory for dependency injection (auto-attached by decorator)
my_skill_factory = MySkill.factory
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

A GitLab CI pipeline is provided in `.gitlab-ci.yml`. It includes:
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

**Updated**: 2026-02-10
