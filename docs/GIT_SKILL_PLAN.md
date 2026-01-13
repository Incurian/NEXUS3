# Git Skill Plan

**Date**: 2026-01-13
**Status**: Draft
**Goal**: Provide granular git access without requiring the `bash` escape valve, with safety guards for dangerous operations.

---

## Executive Summary

A dedicated `git` skill enables sandboxed agents to perform git operations (read-only or controlled writes) without full shell access. This is critical for coding workflows where 80% of work involves `status`, `diff`, `log`, `add`, `commit`, and `push`.

---

## Design Approach: Single Skill with Subcommands

Rather than many separate tools (`git_status`, `git_diff`, etc.), implement **one `git` skill** with a `command` parameter. This:
- Keeps tool count manageable (1 vs 10+)
- Allows unified permission logic
- Mirrors how users think about git

---

## Skill Interface

### Parameters

```python
{
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Git command to run (e.g., 'status', 'diff HEAD~1', 'log -5')"
        },
        "cwd": {
            "type": "string",
            "description": "Working directory (default: current directory)"
        }
    },
    "required": ["command"]
}
```

### Allowed Commands by Permission Level

| Level | Allowed | Confirmation Required | Blocked |
|-------|---------|----------------------|---------|
| **SANDBOXED** | status, diff, log, show, branch, remote, blame, rev-parse | None | Everything else |
| **TRUSTED** | All read-only + add, commit, push, pull, fetch, checkout, switch, stash, merge, cherry-pick, tag | push, pull, merge, rebase, tag --delete | reset --hard, push --force, clean, rebase -i |
| **YOLO** | All | None | None |

### Blocked Operations (All Levels Except YOLO)

These are **always blocked** unless YOLO mode:
- `reset --hard` - Discards uncommitted work
- `push --force` / `push -f` - Rewrites remote history
- `clean -f` / `clean -fd` - Deletes untracked files
- `rebase -i` - Interactive history rewriting
- `checkout --orphan` - Destroys branch history

---

## Output Format

### Structured JSON (Default)

```json
{
    "success": true,
    "command": "status",
    "branch": "main",
    "ahead": 2,
    "behind": 0,
    "staged": ["file1.py"],
    "unstaged": ["file2.py", "file3.py"],
    "untracked": ["new.txt"],
    "output": "On branch main\nYour branch is ahead of 'origin/main' by 2 commits..."
}
```

### Command-Specific Output Parsing

| Command | Structured Fields |
|---------|-------------------|
| `status` | branch, ahead, behind, staged[], unstaged[], untracked[] |
| `diff` | files_changed, insertions, deletions, raw_diff |
| `log` | commits[{sha, author, date, message}] |
| `branch` | branches[{name, current, tracking, ahead, behind}] |
| `show` | sha, author, date, message, diff |

For complex output, include both parsed fields AND raw `output` string.

---

## Implementation

### Command Parsing & Validation

```python
# Blocked patterns (compiled regex)
BLOCKED_PATTERNS = [
    r'reset\s+--hard',
    r'push\s+(-f|--force)',
    r'clean\s+-[fd]',
    r'rebase\s+-i',
    r'checkout\s+--orphan',
]

# Read-only commands (for SANDBOXED)
READ_ONLY_COMMANDS = {
    'status', 'diff', 'log', 'show', 'branch', 'remote',
    'blame', 'rev-parse', 'describe', 'ls-files', 'ls-tree'
}

# Commands requiring confirmation (for TRUSTED)
CONFIRM_COMMANDS = {'push', 'pull', 'merge', 'rebase', 'tag'}

def validate_command(command: str, level: PermissionLevel) -> tuple[bool, str | None]:
    """Validate git command against permission level.

    Returns (allowed, error_message).
    """
    # Check blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Command blocked for safety: {command}"

    # Extract base command
    base_cmd = command.split()[0] if command else ""

    if level == PermissionLevel.SANDBOXED:
        if base_cmd not in READ_ONLY_COMMANDS:
            return False, f"Only read-only git commands allowed in SANDBOXED mode"

    return True, None
```

### Execution

```python
async def execute(self, command: str = "", cwd: str = ".", **kwargs) -> ToolResult:
    if not command:
        return ToolResult(error="No git command provided")

    # Validate against permissions
    permissions = self._services.get("permissions")
    level = permissions.level if permissions else PermissionLevel.TRUSTED

    allowed, error = validate_command(command, level)
    if not allowed:
        return ToolResult(error=error)

    # Check if confirmation needed
    base_cmd = command.split()[0]
    if level == PermissionLevel.TRUSTED and base_cmd in CONFIRM_COMMANDS:
        # Return special marker for confirmation flow
        # (Session handles confirmation callback)
        pass

    # Execute git command
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git"] + shlex.split(command),
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        output = self._parse_output(base_cmd, result.stdout, result.stderr)

        if result.returncode != 0:
            return ToolResult(error=f"Git error: {result.stderr}")

        return ToolResult(output=json.dumps(output))

    except subprocess.TimeoutExpired:
        return ToolResult(error="Git command timed out (30s limit)")
    except Exception as e:
        return ToolResult(error=f"Git error: {e}")
```

---

## Permission Integration

### Config Schema Addition

```python
# In DESTRUCTIVE_ACTIONS or new constant
GIT_CONFIRM_COMMANDS = {"push", "pull", "merge", "rebase", "tag"}

# In SANDBOXED_DISABLED patterns
GIT_WRITE_COMMANDS = {"add", "commit", "push", "pull", "fetch", "checkout", ...}
```

### Factory

```python
def git_factory(services: ServiceContainer) -> GitSkill:
    permissions = services.get("permissions")
    allowed_paths = services.get("allowed_paths")  # For cwd validation
    return GitSkill(permissions=permissions, allowed_paths=allowed_paths)
```

---

## Safety Features

1. **Command Allowlist**: Only recognized git commands pass
2. **Argument Sanitization**: Block `--force`, `--hard`, etc.
3. **Path Restriction**: `cwd` validated against `allowed_paths`
4. **Timeout**: 30s max execution time
5. **No Shell**: Use `subprocess.run` with list args (no shell injection)
6. **Audit Logging**: All git commands logged with agent ID

---

## Usage Examples

```python
# Read-only (works in SANDBOXED)
git(command="status")
git(command="diff HEAD~1")
git(command="log --oneline -10")
git(command="branch -v")

# Write operations (TRUSTED, may prompt)
git(command="add .")
git(command="commit -m 'Fix bug'")
git(command="push origin main")  # Prompts for confirmation

# Blocked (all modes except YOLO)
git(command="reset --hard HEAD~1")  # Error: blocked
git(command="push --force")  # Error: blocked
```

---

## File Changes

| File | Changes |
|------|---------|
| `nexus3/skill/builtin/git.py` | New skill implementation |
| `nexus3/skill/builtin/registration.py` | Register git_factory |
| `nexus3/core/permissions.py` | Add GIT_CONFIRM_COMMANDS, update SANDBOXED logic |

---

## Test Plan

| Category | Tests |
|----------|-------|
| Command validation | Blocked patterns, read-only enforcement, level-based filtering |
| Output parsing | status, diff, log, branch structured output |
| Permission integration | SANDBOXED blocks writes, TRUSTED confirms, YOLO allows all |
| Safety | Timeout, path validation, argument sanitization |
| Edge cases | Detached HEAD, merge conflicts, empty repo |

---

## Open Questions

1. **Merge conflict handling**: Return special output? Provide resolution commands?
2. **Submodule support**: Allow `git submodule` commands?
3. **Config commands**: Allow `git config --get`? Block `git config --global`?
4. **Hooks**: Should the skill respect/bypass git hooks?

---

## Estimated Effort

- Implementation: 3-4 hours
- Tests: 2-3 hours
- Documentation: 1 hour
- **Total**: 6-8 hours
