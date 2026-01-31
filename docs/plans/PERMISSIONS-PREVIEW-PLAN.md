# Plan: Permissions Preview Enhancement

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | When to create file? | A) Always B) Only if >N lines C) Only with --full flag | **B) Auto if >20 lines** |
| **Q2** | Where to save file? | A) .nexus3/logs/ B) /tmp/ C) CWD | **A) .nexus3/logs/** - organized |
| **Q3** | File format? | A) Plain text B) Markdown C) JSON | **B) Markdown** - readable |
| **Q4** | Show file path in output? | A) Always B) Only when truncated | **B) Only when truncated** |

---

## Overview

**Problem:** `/permissions` output can be very long with many disabled tools or complex path lists, making it hard to read in terminal.

**Current behavior:** All output inline, disabled tools listed on single comma-separated line.

**Goal:** Smart output that summarizes in terminal, saves full details to file when needed.

---

## Scope

### Included
- Detect when output exceeds threshold (20 lines or 2000 chars)
- Auto-save full output to `.nexus3/logs/{agent_id}_permissions.md`
- Show summary in terminal with file reference
- Add `--full` flag to force file output

### Deferred
- Interactive pager for long output
- Diff between permission states

---

## Implementation

### Phase 1: Add Import

**File:** `nexus3/cli/repl_commands.py` (add at top with other imports)

```python
from datetime import datetime
# Path is already imported at line 24
```

### Phase 2: Add Helper Function

**File:** `nexus3/cli/repl_commands.py` (add before `_format_permissions()` around line 1000)

```python
def _save_permissions_to_file(
    full_output: str, agent_id: str
) -> tuple[bool, Path | None]:
    """Save permissions output to markdown file.

    Returns:
        Tuple of (success, filepath or None).
    """
    log_dir = Path.cwd() / ".nexus3" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{agent_id}_permissions_{timestamp}.md"
    filepath = log_dir / filename

    try:
        filepath.write_text(
            f"# Permissions for {agent_id}\n\n{full_output}",
            encoding="utf-8"
        )
        return True, filepath
    except Exception:
        return False, None
```

### Phase 3: Update _format_permissions()

**File:** `nexus3/cli/repl_commands.py` (lines 1007-1050)

**Current signature:**
```python
def _format_permissions(perms: AgentPermissions | None, agent: Agent) -> CommandOutput:
```

**New signature:**
```python
def _format_permissions(
    perms: AgentPermissions | None,
    agent: Agent,
    force_full: bool = False,
) -> CommandOutput:
```

**New implementation:**
```python
def _format_permissions(
    perms: AgentPermissions | None,
    agent: Agent,
    force_full: bool = False,
) -> CommandOutput:
    """Format permissions with smart truncation."""
    if not perms:
        return CommandOutput.error("No permissions configured")

    lines: list[str] = []

    # Build full output
    lines.append(f"Preset: {perms.base_preset}")
    lines.append(f"Level: {perms.effective_policy.level.value}")

    # Paths
    if perms.effective_policy.allowed_paths is None:
        lines.append("Paths: unrestricted")
    else:
        lines.append(f"Allowed paths ({len(perms.effective_policy.allowed_paths)}):")
        for p in perms.effective_policy.allowed_paths:
            lines.append(f"  {p}")

    if perms.effective_policy.blocked_paths:
        lines.append(f"Blocked paths ({len(perms.effective_policy.blocked_paths)}):")
        for p in perms.effective_policy.blocked_paths:
            lines.append(f"  {p}")

    # Ceiling
    if perms.ceiling:
        lines.append(f"Ceiling: {perms.ceiling.value}")

    # Disabled tools (one per line for readability)
    disabled = [name for name, tp in perms.tool_permissions.items() if not tp.enabled]
    if disabled:
        lines.append(f"Disabled tools ({len(disabled)}):")
        for tool in sorted(disabled):
            lines.append(f"  - {tool}")

    full_output = "\n".join(lines)

    # Check threshold
    MAX_LINES = 20
    MAX_CHARS = 2000
    if force_full or len(lines) > MAX_LINES or len(full_output) > MAX_CHARS:
        success, filepath = _save_permissions_to_file(full_output, agent.agent_id)
        if success and filepath:
            # Build summary
            summary_lines = [
                f"Preset: {perms.base_preset}",
                f"Level: {perms.effective_policy.level.value}",
                f"Disabled tools: {len(disabled)}",
                "",
                f"Full details saved to: {filepath}",
            ]
            return CommandOutput.success(
                message="\n".join(summary_lines),
                data={"details_file": str(filepath)},
            )
        # Fall through to full output if file save failed

    return CommandOutput.success(message=full_output)
```

### Phase 4: Update cmd_permissions() for --full Flag

**File:** `nexus3/cli/repl_commands.py` (function starts at line 954)

**Add flag parsing after getting args:**

```python
async def cmd_permissions(ctx: CommandContext, args: str | None = None) -> CommandOutput:
    """Show or modify permissions."""
    agent = ctx.agent
    perms = agent.services.get("permissions")

    if not args or not args.strip():
        # Show current permissions (default)
        return _format_permissions(perms, agent)

    # Parse flags
    parts = args.strip().split()
    force_full = "--full" in parts

    # Remove --full from parts to process remaining commands
    if force_full:
        parts = [p for p in parts if p != "--full"]

    # If no other args, show permissions with --full flag
    if not parts:
        return _format_permissions(perms, agent, force_full=True)

    # Otherwise continue with existing command parsing (--list-tools, --disable, etc.)
    cmd = parts[0].lower()
    # ... rest of existing logic
```

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `nexus3/cli/repl_commands.py` | Top | Add `from datetime import datetime` |
| `nexus3/cli/repl_commands.py` | ~1000 | Add `_save_permissions_to_file()` helper |
| `nexus3/cli/repl_commands.py` | 1007-1050 | Update `_format_permissions()` with threshold logic |
| `nexus3/cli/repl_commands.py` | 954 | Update `cmd_permissions()` to parse `--full` flag |

---

## Implementation Checklist

### Phase 1: Core Logic
- [ ] **P1.1** Add `from datetime import datetime` import
- [ ] **P1.2** Add `_save_permissions_to_file()` helper function
- [ ] **P1.3** Update `_format_permissions()` signature with `force_full` param
- [ ] **P1.4** Add threshold constants (MAX_LINES=20, MAX_CHARS=2000)
- [ ] **P1.5** Add threshold check and file save logic

### Phase 2: Flag Support
- [ ] **P2.1** Add `--full` flag parsing to `cmd_permissions()`
- [ ] **P2.2** Update help text in HELP_TEXT dict to mention `--full`

### Phase 3: Testing
- [ ] **P3.1** Test with agent that has many disabled tools (triggers threshold)
- [ ] **P3.2** Test file is created in .nexus3/logs/
- [ ] **P3.3** Test summary shows correct counts
- [ ] **P3.4** Test `--full` flag forces file output even for small output
- [ ] **P3.5** Test normal output when below threshold

---

## Effort Estimate

~30 minutes implementation, ~15 minutes testing.
