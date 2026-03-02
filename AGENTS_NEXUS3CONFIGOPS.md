# AGENTS_NEXUS3CONFIGOPS.md

Configuration and operational reference for NEXUS3.

Derived from `CLAUDE.md` Configuration Reference + Development Guide + Status sections, adapted for Codex usage.

## Configuration Reference

```text
~/.nexus3/
├── config.json        # Global config
├── NEXUS.md           # Personal system prompt
├── mcp.json           # Personal MCP servers
├── rpc.token          # Auto-generated RPC token (default port)
├── rpc-{port}.token   # Port-specific RPC tokens
├── sessions/          # Saved session files (JSON)
├── last-session.json  # Auto-saved for --resume
├── last-session-name  # Name of last session
└── logs/
    └── server.log     # Server lifecycle events (rotating, 5MB x 3 files)

./NEXUS.md             # Project prompt (overrides personal)
.nexus3/logs/          # Session logs (gitignored)
├── server.log
└── <session-id>/
    ├── session.db
    ├── context.md
    ├── verbose.md     # if -V enabled
    └── raw.jsonl      # if --raw-log enabled
```

### Server Logging

Server lifecycle events are logged to `.nexus3/logs/server.log`.

| Event | Log Level | Example |
|-------|-----------|---------|
| Server start | INFO | `JSON-RPC HTTP server running at http://127.0.0.1:8765/` |
| Agent created | INFO | `Agent created: worker-1 (preset=trusted, cwd=/path, model=gpt)` |
| Agent destroyed | INFO | `Agent destroyed: worker-1 (by external)` |
| Shutdown requested | INFO | `Server shutdown requested` |
| Idle timeout | INFO | `Idle timeout reached (1800s without RPC activity), shutting down` |
| Server stopped | INFO | `HTTP server stopped` |

- Rotation: 5MB max, 3 backups (`server.log.1`..`.3`)
- Console output default: WARNING+
- Console output with `--verbose`: DEBUG+
- Real-time monitoring: `tail -f .nexus3/logs/server.log`

### Provider Configuration

Supported provider types:
- `openrouter` (default)
- `openai`
- `azure`
- `anthropic`
- `ollama`
- `vllm`

Examples:

```json
{"provider": {"type": "openrouter", "model": "anthropic/claude-sonnet-4"}}
```

```json
{"provider": {"type": "openai", "api_key_env": "OPENAI_API_KEY", "model": "gpt-4o"}}
```

```json
{"provider": {
  "type": "azure",
  "base_url": "https://my-resource.openai.azure.com",
  "api_key_env": "AZURE_OPENAI_KEY",
  "deployment": "gpt-4",
  "api_version": "2024-02-01"
}}
```

```json
{"provider": {"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-20250514"}}
```

```json
{"provider": {"type": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.2"}}
```

### Prompt Caching

Provider support:

| Provider | Status | Config Required |
|----------|--------|-----------------|
| Anthropic | Full | automatic (default) |
| OpenAI | Full | none |
| Azure | Full | none |
| OpenRouter | pass-through | automatic for Anthropic models |
| Ollama/vLLM | none | N/A |

Cache-optimized structure separates static prompt from dynamic context.

Disable per provider:

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

### Multi-Provider Configuration

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

Key concepts:
- `providers`: named configs
- `default_model`: default alias
- `models[].provider`: optional explicit provider routing
- single-provider `provider` field remains supported

Implementation notes:
- lazy provider initialization
- per-model provider routing via resolver
- shared components hold registry, not single provider

### Provider Timeout/Retry

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

Notes:
- PAT must include `api` scope
- Prefer `token_env` over inline token field
- `username`/`email`/`user_id` enables `me` shorthand
- `gitlab_repo whoami` can verify resolved identity
- TRUSTED/YOLO required for GitLab skills

### Clipboard Configuration

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

Scope permissions by preset:
- `yolo`: full agent/project/system
- `trusted`: read/write agent+project, read-only system
- `sandboxed`: agent scope only

## Design Principles

1. Async-first
2. Fail-fast
3. Single source of truth
4. Minimal viable interfaces
5. End-to-end tested
6. Document as you go
7. Unified invocation patterns across CLI, skills, and client APIs

## Development SOPs

| SOP | Description |
|-----|-------------|
| Type Everything | No `Optional[Any]`; use protocols/interfaces |
| Fail Fast | No swallowed errors or silent `pass` |
| One Way | Features belong in skills/CLI flags, not ad-hoc scripts |
| Explicit Encoding | `encoding='utf-8', errors='replace'` |
| Test E2E | Integration coverage for every feature |
| Live Test | Automated tests are insufficient alone |
| Document | Update docs during implementation |
| No Dead Code | Remove unused code/imports |
| Plan First | Non-trivial work requires a `docs/` plan |
| Commit Often | Commit by phase/logical unit |
| Branch per Plan | One branch per plan |
| Do Not Revert Unrelated Changes | Stage only your changes |
| Zero Lint/Test Failures | Track and document unavoidable breakage explicitly |

### Live Testing Requirement

Before commits that affect agent behavior/RPC/skills/permissions:

1. `nexus3 &`
2. `nexus3 rpc create test-agent`
3. `nexus3 rpc send test-agent "describe your permissions and what you can do"`
4. Verify behavior
5. `nexus3 rpc destroy test-agent`

### Version Control

Commit frequency guidance:
- after each checklist phase
- before switching modules
- whenever tests are green
- before risky refactors

Branching:
- one branch per plan (`feature/<plan-name>`)
- branch before implementation
- keep branch scope tight

Pushing:
- feature branches: push after each commit
- main/master: PR merge only

Merging:
- require complete checklist, passing tests, live validation, and user sign-off

### Feature Planning SOP

Non-trivial features should use `docs/<PLAN>.md` with phases:
1. Intent
2. Explore
3. Feasibility
4. Scope
5. General plan
6. Validate
7. Detailed plan
8. Validate
9. Checklist
10. Documentation

Required plan sections:
- Overview
- Scope (included/deferred/excluded)
- Design decisions (+ rationale)
- Security considerations
- Architecture
- Implementation details
- Testing strategy
- Open questions
- Codebase validation notes
- Implementation checklist
- Quick reference

Checklist format should include phase/task IDs and dependency markers.

Documentation phase is required in every implementation checklist.

## Testing

Always use virtualenv executables:

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/integration/ -v
.venv/bin/pytest tests/security/ -v
.venv/bin/ruff check nexus3/
.venv/bin/mypy nexus3/
.venv/bin/python -c "import nexus3; print(nexus3.__version__)"
```

Never use bare `python`/`pytest`.

### Current Status Snapshot

As recorded in `CLAUDE.md` on 2026-02-25:
- `ruff check nexus3/`: 0 errors
- `mypy nexus3/`: 0 errors (192 source files)
- `pytest tests/`: 3742 passed, 3 skipped

### Known Failures Policy

If any failure cannot be immediately fixed, document:
- what fails
- why it fails
- plan to resolve

## Codex Integration Notes

Use explicit Python module invocation in Codex tool runs:

```bash
NEXUS_DEV=1 .venv/bin/python -m nexus3 --serve 9000 &
.venv/bin/python -m nexus3 rpc detect --port 9000
.venv/bin/python -m nexus3 rpc list --port 9000
.venv/bin/python -m nexus3 rpc create worker --port 9000
.venv/bin/python -m nexus3 rpc send worker "message" --port 9000
.venv/bin/python -m nexus3 rpc status worker --port 9000
.venv/bin/python -m nexus3 rpc destroy worker --port 9000
.venv/bin/python -m nexus3 rpc shutdown --port 9000
```

Operational pattern:
- execute commands one at a time in multi-turn loops
- inspect output before next command
- avoid batching fragile multi-step shell scripts

## Deferred Work Tracker

### Structural Refactors

| Issue | Reason | Effort |
|-------|--------|--------|
| `repl.py` split (~2050 lines) | large refactor | L |
| `session.py` split (~1100 lines) | large refactor | M |
| `pool.py` split (~1250 lines) | large refactor | M |
| display config cleanup | polish | S |
| HTTP keep-alive | advanced feature | M |

### DRY Cleanups

| Pattern | Notes |
|---------|-------|
| dispatcher error handling duplication | overlap in `dispatcher.py` and `global_dispatcher.py` |
| repeated HTTP error send paths | multiple similar branches in `http.py` |
| ToolResult file error duplication | repeated handlers across skill files |
| duplicate timeout layers in git path | redundant `subprocess.run(timeout)` + `asyncio.wait_for()` |
| confirmation menu duplication | repetitive menu sections in `confirmation_ui.py` |

### Planned Improvements

- `PROMPT-CACHE-OPTIMIZATION-PLAN.md`
- `PROVIDER-BUGFIX-PLAN.md`
- `DOUBLE-SPINNER-FIX-PLAN.md`
- `DRY-CLEANUP-PLAN.md`
- `MCP-SERVER-PLAN.md`

### Known Bugs (from status section)

- custom `ssl_ca_cert` currently replaces system CAs (needs merge behavior)
- double-spinner/trapped ESC on concurrent RPC sends with active REPL
