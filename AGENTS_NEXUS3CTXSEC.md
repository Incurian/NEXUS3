# AGENTS_NEXUS3CTXSEC.md

Full context and security reference for NEXUS3.

Derived from `CLAUDE.md` Context System + Permissions and Security sections, adapted for Codex usage.

## Context System

### Context Loading

Context is loaded from multiple directory layers and merged together. Each layer extends the previous one.

#### Layer Hierarchy

```text
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
| `NEXUS.md` | `.nexus3/` -> `./` |
| `AGENTS.md` | `.nexus3/` -> `.agents/` -> `./` |
| `CLAUDE.md` | `.nexus3/` -> `.claude/` -> `.agents/` -> `./` |
| `README.md` | `./` only (wrapped with documentation boundaries) |

Global layer (`~/.nexus3/`) is exempt and always loads `NEXUS.md`.

#### Directory Structure

```text
nexus3/defaults/              # Package (auto-updates with upgrades)
├── NEXUS-DEFAULT.md          # System docs, tools, permissions (always loaded)
└── NEXUS.md                  # Template copied to ~/.nexus3/ on init

~/.nexus3/                    # Global (user customizations)
├── NEXUS.md                  # User custom instructions (always NEXUS.md)
├── config.json               # Personal configuration
└── mcp.json                  # Personal MCP servers

./parent/.nexus3/             # Ancestor
├── AGENTS.md                 # Or NEXUS.md, CLAUDE.md (priority-driven)
└── config.json

./.nexus3/                    # Local (CWD)
├── AGENTS.md                 # Or NEXUS.md, CLAUDE.md (priority-driven)
├── config.json               # Project config overrides
└── mcp.json                  # Project MCP servers
```

#### Split Context Design

- `NEXUS-DEFAULT.md` (package only): tool docs, permissions, limits; auto-updates with package upgrades
- Instruction files (user/project): `NEXUS.md`, `AGENTS.md`, `CLAUDE.md`; preserved across upgrades

#### Configuration Merging

- Configs: deep-merged (local keys override global)
- Instruction files: all layers included with labeled sections (first-found per layer)
- MCP servers: same server name -> local wins

#### Subagent Context Inheritance

Subagents created with `cwd` parameter get:
1. Their cwd instruction file (found via priority search)
2. Parent context (non-redundantly)

#### Init Commands

```bash
# Initialize global config
nexus3 --init-global
nexus3 --init-global-force

# Initialize local config (REPL)
/init
/init NEXUS.md
/init CLAUDE.md
/init --force
/init --global
```

#### Context Config Options

```json
{
  "context": {
    "ancestor_depth": 2,
    "instruction_files": ["NEXUS.md", "AGENTS.md", "CLAUDE.md", "README.md"]
  }
}
```

### Context Compaction

Context compaction summarizes old conversation history to reclaim token space while preserving key context.

#### How It Works

1. Trigger: `used_tokens > trigger_threshold * available_tokens` (default 90%)
2. Preserve recent: recent messages kept verbatim (`recent_preserve_ratio`)
3. Summarize old: older messages summarized by fast model (default `claude-haiku`)
4. Budget: summary constrained by `summary_budget_ratio` (default 25%)
5. Prompt reload: `NEXUS.md` is re-read during compaction

#### Configuration (`CompactionConfig`)

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable auto-compaction |
| `model` | `"anthropic/claude-haiku"` | Summarization model |
| `summary_budget_ratio` | `0.25` | Max summary token fraction |
| `recent_preserve_ratio` | `0.25` | Recent message token fraction |
| `trigger_threshold` | `0.9` | Trigger threshold |

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
/compact
```

#### Key Benefits

- Longer sessions without losing critical context
- Prompt edits picked up during compaction
- Timestamped summaries for auditability
- Tunable thresholds

### Temporal Context

| Timestamp | When Set | Location | Purpose |
|-----------|----------|----------|---------|
| Current date/time | Every request | System prompt | Accurate "now" awareness |
| Session start | Agent creation | First message in history | Session origin |
| Compaction | On summary | Summary prefix | Summary timestamp |

Example start messages:

```text
[Session started: 2026-01-13 14:30 (local)]
[Session started: 2026-01-13 14:30 (local) | Agent: worker-1 | Preset: sandboxed | CWD: /home/user/project]
[Session started: 2026-01-13 14:30 (local) | Agent: main | Preset: trusted | CWD: /home/user/project | Writes: CWD unrestricted, elsewhere with user confirmation]
```

Example compaction header:

```text
[CONTEXT SUMMARY - Generated: 2026-01-13 16:45]
```

### Git Repository Context

When CWD is inside a git repo, git state is injected into prompt context.

Example:

```text
Git repository detected in CWD.
  Branch: main
  Status: 3 staged, 2 modified, 1 untracked, 2 stashes
  Last commit: abc1234 fix login bug
  Remote: origin -> github.com/user/repo
```

Refresh triggers:

| Event | Description |
|-------|-------------|
| Agent creation | Initial git context |
| Session restore | Refresh on `--resume` / saved session load |
| CWD change | `/cwd` updates git context |
| Tool batch completion | Refresh if tools might change git state |
| Context compaction | Refresh with prompt reload |
| Config changes | `/model`, `/prompt`, `/gitlab on|off` |

Properties:
- 500-character hard cap
- Credentials stripped from remotes
- No injection if directory is not a git repo
- Stash/worktree counts shown only when non-zero

## Permissions and Security

### Permission System

#### Built-in Presets

| Preset | Level | Description |
|--------|-------|-------------|
| `yolo` | YOLO | Full access, no confirmations (REPL-only) |
| `trusted` | TRUSTED | Confirmations for destructive actions |
| `sandboxed` | SANDBOXED | CWD-only, no network, limited nexus tools (default for RPC) |

#### Target Restrictions

Some tools support `allowed_targets` limits for inter-agent communication:

| Restriction | Meaning |
|-------------|---------|
| `None` | Can target any agent |
| `"parent"` | Parent only |
| `"children"` | Children only |
| `"family"` | Parent or children |
| `[...]` | Explicit allowlist |

Used by `nexus_send`, `nexus_status`, `nexus_cancel`, and `nexus_destroy`.

#### RPC Agent Permission Quirks (Intentional)

1. Default RPC agent is `sandboxed` (least privilege by default)
2. Sandboxed agents read only within `cwd`
3. Sandboxed agents have write tools disabled unless explicit write paths are granted
4. Trusted must be requested explicitly (`--preset trusted`)
5. Trusted RPC agents can read broadly; destructive actions follow confirmation logic
6. YOLO cannot be created via RPC; RPC send to YOLO requires active REPL connection
7. Trusted agents can only create sandboxed subagents (ceiling enforcement)
8. Sandboxed agents have limited nexus tools; `nexus_send` to parent is intentionally allowed
9. For sandboxed parents, child `cwd` must stay within parent `cwd`
10. For sandboxed parents, child write paths must stay within parent scope
11. Child `cwd` defaults to parent `cwd` if unspecified

Secure creation examples:

```bash
nexus3 rpc create reader --cwd /path/to/project
nexus3 rpc create writer --cwd /path/to/project --write-path /path/to/project/output
nexus3 rpc create coordinator --preset trusted
```

#### Key Features

- Per-tool enable/disable and constraints
- Permission presets (built-in or config-defined)
- Ceiling inheritance for subagents
- REPL confirmation prompts for risky operations in TRUSTED

#### Permission Commands

```bash
/permissions
/permissions trusted
/permissions --disable write_file
/permissions --list-tools
```

### Security Hardening

Security hardening (Jan 2026+) includes:

- Permission hardening: ceiling enforcement, fail-closed defaults, path validation
- RPC hardening: token auth, header limits, SSRF protections, symlink defenses
- Process isolation: process-group kills on timeout, env sanitization
- Input validation: URL, agent ID, MCP protocol hardening
- Output sanitization: terminal escape stripping, markup escaping, secret redaction
- MCP hardening (2026-01-27):
  - `follow_redirects=False` to prevent SSRF redirect bypass
  - MCP output sanitization via `sanitize_for_display()`
  - response size limits (`MAX_MCP_OUTPUT_SIZE`, 10MB)
  - sanitized config errors (no secret leakage)
  - session ID validation (alnum only, max 256 chars)
- Windows security compatibility (2026-01-28):
  - Windows path sanitization (drive paths, UNC, domain users)
  - cross-platform process tree termination fallback (`taskkill /T /F`)
  - Windows env var sanitization coverage
  - `CREATE_NO_WINDOW` on subprocesses

Coverage note: 3400+ tests, including 770+ security-focused tests.

### Windows Compatibility

#### Known Windows Security Limitations

| Issue | Impact | Mitigation |
|-------|--------|------------|
| `os.chmod()` no-op | Session/token files may be readable by other users | Restrict home-directory access |
| Symlink detection limits | `is_symlink()` misses junctions/reparse points | Assume weaker symlink guarantees |
| Permission bit checks | `S_IRWXG|S_IRWXO` semantics are weak on Windows | ACL-based validation not implemented |

#### Shell Detection

| Shell | Detection | ANSI | Unicode | Notes |
|-------|-----------|------|---------|-------|
| Windows Terminal | `WT_SESSION` env var | Full | Full | Best experience |
| PowerShell 7+ | via Windows Terminal | Full | Full | |
| Git Bash | `MSYSTEM` env var | Full | Full | MSYS2 environment |
| PowerShell 5.1 | `PSModulePath` present | Limited | Limited | Legacy mode |
| CMD.exe | `COMSPEC` check | None | None | Plain text only |

For UTF-8 output on Windows consoles, use code page 65001 (`chcp 65001`).

Key helper functions:
- `detect_windows_shell()`
- `supports_ansi()`
- `supports_unicode()`
- `check_console_codepage()`
