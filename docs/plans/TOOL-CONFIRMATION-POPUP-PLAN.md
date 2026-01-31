# Plan: Tool Confirmation Popup Enhancement

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Default viewer? | A) Rich Pager B) External Editor C) Auto-detect | **C) Auto-detect** - pager on Unix TTY, external on Windows |
| **Q2** | Popup key? | A) 'p' B) 'v' (view) C) 'd' (details) | **A) 'p'** - intuitive for "popup" |
| **Q3** | Config option? | A) None B) Simple toggle C) Full control | **C) Full control** - `viewer: auto|pager|external|none` |

---

## Overview

**Problem:** When an agent wants to run a tool, the confirmation dialog shows truncated parameters. For complex commands (long paths, large diffs, multi-line content), users can't see what they're approving.

**Current behavior:**
- MCP tools: 60 char preview (line 146-148)
- Exec tools: 50 char command preview (line 159)
- File tools: Just the path
- No way to see full details

**Goal:**
1. Show more detail by default (expand truncation limits)
2. Add "press p for popup" to see full details in external viewer

---

## Current Confirmation UI

**File:** `nexus3/cli/confirmation_ui.py`

**Function:** `confirm_tool_action()` (lines 75-271)

**Key Line Numbers (validated):**
| Section | Lines | Description |
|---------|-------|-------------|
| Function signature | 75-81 | Parameters including pause events |
| Tool type detection | 113-116 | is_exec_tool, is_shell_unsafe, is_nexus_tool, is_mcp_tool |
| Live display pause | 119-131 | Stop Live, pause KeyMonitor |
| MCP tool display | 141-153 | 60 char truncation at line 146 |
| Exec tool display | 154-164 | 50 char truncation at line 159 |
| Nexus tool display | 165-171 | Agent ID display |
| File tool display | 172-177 | Path display |
| Options menu | 179-205 | Different options per tool type |
| Input capture | 207-221 | `get_input()` via `asyncio.to_thread()` |
| Response handling | 230-261 | Map response to ConfirmationResult |
| Live display resume | 263-270 | Finally block restores state |

**Current flow:**
```
  ● write_file wants to write to: /home/user/project/src/...

  [1] Allow once
  [2] Allow for this file
  [3] Allow writes in /home/user/project/
  [4] Deny

  Choice [1-4]: _
```

---

## Viewer Options Analysis

### Option A: Rich Pager (Recommended for Unix)

**Implementation:**
```python
from rich.console import Console

def _show_tool_details_pager(console: Console, content: str) -> None:
    """Show tool details in system pager (less/more)."""
    with console.pager(styles=True, links=False):
        console.print(content)
```

**Validation Notes:**
- Rich's `SystemPager` uses `$PAGER` env var, falls back to `pydoc.pager`
- Works with paused Live display (validated: stop before, start after)
- No temp files needed
- Styles preserved in pager

**Pros:**
- Zero temp files
- Built into Rich (already a dependency)
- Works with pause/resume protocol

**Cons:**
- Windows has no native pager - falls back to pydoc which is poor UX
- Copy-paste unreliable in terminal pagers

**Best for:** Unix/Linux/macOS users in terminal emulators

### Option B: External Editor (Recommended for Windows)

**Implementation:**
```python
import os
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path

def _get_system_viewer() -> list[str]:
    """Get viewer command for current platform."""
    if sys.platform == "win32":
        return ["notepad.exe"]

    # Unix: prefer $VISUAL > $EDITOR > common pagers
    for env in ["VISUAL", "EDITOR"]:
        if editor := os.environ.get(env):
            return [editor]

    for cmd in ["less", "more", "cat"]:
        if shutil.which(cmd):
            return [cmd]

    return ["cat"]

def _open_in_external_viewer(content: str, title: str) -> bool:
    """Open content in external viewer."""
    temp_dir = Path.home() / ".nexus3" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Use mkstemp for secure temp file (0o600 permissions)
    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="nexus_tool_", dir=temp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"=== {title} ===\n\n{content}\n")

        viewer_cmd = _get_system_viewer()

        if sys.platform == "win32":
            # Windows: no window flash
            subprocess.Popen(
                viewer_cmd + [tmp_path],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
        else:
            # Unix: run in foreground
            subprocess.run(viewer_cmd + [tmp_path])

        return True
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
```

**Validation Notes:**
- `tempfile.mkstemp()` creates with 0o600 permissions (secure)
- `CREATE_NO_WINDOW` prevents window flash on Windows
- Cleanup in finally block ensures temp file removed

**Pros:**
- Full Windows support (notepad always available)
- Respects $EDITOR/$VISUAL on Unix
- Full copy-paste support
- User's preferred editor

**Cons:**
- Requires temp file management
- External process coordination

**Best for:** Windows users, users who prefer their editor

### Option C: In-Terminal Panel (Deferred to v2)

Would require building custom scrolling panel with keyboard navigation. Estimated ~200+ lines of code for proper implementation.

**Deferred because:**
- Complex implementation
- Rich doesn't have built-in scrollable panel
- Pager + External cover most use cases

---

## Implementation

### Phase 1: Add Imports and Helpers

**File:** `nexus3/cli/confirmation_ui.py` (add after line 18)

```python
import os
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path


def _get_system_viewer() -> list[str]:
    """Get the appropriate viewer command for the current platform.

    Returns:
        Command list to open a text file (append filename to use).
    """
    if sys.platform == "win32":
        return ["notepad.exe"]

    for env in ["VISUAL", "EDITOR"]:
        if editor := os.environ.get(env):
            return [editor]

    for cmd in ["less", "more", "cat"]:
        if shutil.which(cmd):
            return [cmd]

    return ["cat"]


def _show_in_pager(console, content: str) -> None:
    """Show content in Rich pager (Unix preferred)."""
    with console.pager(styles=True, links=False):
        console.print(content)


def _show_in_external(content: str, title: str) -> bool:
    """Show content in external viewer (Windows preferred).

    Returns:
        True if successfully opened, False on failure.
    """
    temp_dir = Path.home() / ".nexus3" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="nexus_tool_", dir=temp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"=== {title} ===\n\n{content}\n")

        viewer_cmd = _get_system_viewer()

        if sys.platform == "win32":
            subprocess.Popen(
                viewer_cmd + [tmp_path],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        else:
            subprocess.run(viewer_cmd + [tmp_path])

        return True
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _format_full_tool_details(
    tool_call: ToolCall,
    target_path: Path | None,
    agent_cwd: Path,
) -> str:
    """Format complete tool details for popup display.

    Returns:
        Human-readable text with all tool parameters.
    """
    lines = []

    lines.append(f"Tool: {tool_call.name}")
    lines.append(f"Call ID: {tool_call.id}")
    lines.append("")

    if target_path:
        lines.append(f"Target Path: {target_path}")
    lines.append(f"Working Directory: {agent_cwd}")
    lines.append("")
    lines.append("Parameters:")
    lines.append("-" * 40)

    for key, value in tool_call.arguments.items():
        value_str = str(value)
        if len(value_str) > 200 or "\n" in value_str:
            lines.append(f"\n{key}:")
            lines.append("-" * 20)
            lines.append(value_str)
            lines.append("-" * 20)
        else:
            lines.append(f"{key}: {value_str}")

    return "\n".join(lines)


def _show_tool_details(console, tool_call: ToolCall, target_path: Path | None, agent_cwd: Path) -> None:
    """Show full tool details using appropriate viewer.

    Auto-detects best viewer: pager on Unix TTY, external on Windows.
    """
    content = _format_full_tool_details(tool_call, target_path, agent_cwd)
    title = f"Tool: {tool_call.name}"

    # Use pager on Unix if stdout is a TTY, otherwise external
    if sys.platform != "win32" and sys.stdout.isatty():
        _show_in_pager(console, content)
    else:
        if not _show_in_external(content, title):
            console.print("[yellow]Could not open viewer[/]")
```

### Phase 2: Expand Default Truncation

**File:** `nexus3/cli/confirmation_ui.py`

**Change 1 - Line 146 (MCP tools):**
```python
# FROM:
args_preview = str(tool_call.arguments)[:60]
if len(str(tool_call.arguments)) > 60:

# TO:
args_preview = str(tool_call.arguments)[:120]
if len(str(tool_call.arguments)) > 120:
```

**Change 2 - Line 159 (Exec tools):**
```python
# FROM:
preview = command[:50] + "..." if len(command) > 50 else command

# TO:
preview = command[:100] + "..." if len(command) > 100 else command
```

**Change 3 - Add content preview for write_file (after line 177):**
```python
# After displaying path, add content preview for write operations
if tool_call.name in ("write_file", "append_file") and "content" in tool_call.arguments:
    content = str(tool_call.arguments["content"])
    content_preview = content[:150].replace("\n", "\\n")
    if len(content) > 150:
        content_preview += "..."
    safe_preview = escape_rich_markup(content_preview)
    console.print(f"  [dim]Content:[/] {safe_preview}")
    lines_printed += 1
elif tool_call.name == "edit_file" and "old_string" in tool_call.arguments:
    old = str(tool_call.arguments.get("old_string", ""))[:80].replace("\n", "\\n")
    new = str(tool_call.arguments.get("new_string", ""))[:80].replace("\n", "\\n")
    safe_old = escape_rich_markup(old)
    safe_new = escape_rich_markup(new)
    console.print(f"  [dim]Replace:[/] \"{safe_old}\" → \"{safe_new}\"")
    lines_printed += 1
```

### Phase 3: Add Popup Option to Menu

**File:** `nexus3/cli/confirmation_ui.py`

**Step 3a: Add popup option to each menu block (lines 182-205):**

After each menu section, add:
```python
# NOTE: When adding new tool types, add this popup option to their menu too
console.print("  [dim][p][/] [dim]View full details[/]")
lines_printed += 1
```

**Maintenance note:** The popup option must be added to each tool type's menu separately because menus differ per type. A future refactor could extract a table-driven menu system (see CLAUDE.md Deferred Work).

**Step 3b: Update input prompts (lines 210-215):**
```python
# FROM:
if is_shell_unsafe:
    prompt = "\n[dim]Choice [1-2]:[/] "
elif is_exec_tool:
    prompt = "\n[dim]Choice [1-3]:[/] "
else:
    prompt = "\n[dim]Choice [1-4]:[/] "

# TO:
if is_shell_unsafe:
    prompt = "\n[dim]Choice [1-2, p]:[/] "
elif is_exec_tool:
    prompt = "\n[dim]Choice [1-3, p]:[/] "
else:
    prompt = "\n[dim]Choice [1-4, p]:[/] "
```

### Phase 4: Handle Popup in Input Loop

**File:** `nexus3/cli/confirmation_ui.py`

**Replace lines 220-228 with loop:**
```python
while True:
    response = await asyncio.to_thread(get_input)
    response_lower = response.lower().strip()

    # Handle popup request
    if response_lower == "p":
        _show_tool_details(console, tool_call, target_path, agent_cwd)
        # Re-prompt after viewing details
        continue

    # Valid response, exit loop
    break

lines_printed += 2  # prompt line + input line

# Clear the confirmation prompt from terminal
import sys
sys.stdout.write(f"\033[{lines_printed}F")
sys.stdout.write("\033[J")
sys.stdout.flush()
```

---

## Configuration (Optional Enhancement)

**Schema addition to config:**
```json
{
  "confirmation": {
    "viewer": "auto",
    "viewer_timeout": 30
  }
}
```

| Value | Behavior |
|-------|----------|
| `"auto"` | Pager on Unix TTY, external on Windows (default) |
| `"pager"` | Always use Rich pager |
| `"external"` | Always use external editor |
| `"none"` | Disable popup option |

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/cli/confirmation_ui.py` | Add imports (os, sys, shutil, tempfile, subprocess) |
| `nexus3/cli/confirmation_ui.py` | Add `_get_system_viewer()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `_show_in_pager()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `_show_in_external()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `_format_full_tool_details()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `_show_tool_details()` dispatcher |
| `nexus3/cli/confirmation_ui.py` | Expand truncation (60→120, 50→100) |
| `nexus3/cli/confirmation_ui.py` | Add content preview for write/edit |
| `nexus3/cli/confirmation_ui.py` | Add `[p] View full details` to menus |
| `nexus3/cli/confirmation_ui.py` | Update prompts to show `[..., p]` |
| `nexus3/cli/confirmation_ui.py` | Wrap input in loop for popup handling |

---

## Implementation Checklist

### Phase 1: Popup Infrastructure
- [ ] **P1.1** Add imports (os, sys, shutil, tempfile, subprocess)
- [ ] **P1.2** Add `_get_system_viewer()` function
- [ ] **P1.3** Add `_show_in_pager()` function
- [ ] **P1.4** Add `_show_in_external()` function
- [ ] **P1.5** Add `_format_full_tool_details()` function
- [ ] **P1.6** Add `_show_tool_details()` dispatcher

### Phase 2: Expand Default Truncation
- [ ] **P2.1** MCP tools: expand from 60 to 120 chars (line 146)
- [ ] **P2.2** Exec tools: expand from 50 to 100 chars (line 159)
- [ ] **P2.3** Add content preview for write_file/append_file
- [ ] **P2.4** Add old→new preview for edit_file

### Phase 3: Add Popup Option
- [ ] **P3.1** Add `[p] View full details` to MCP menu (after line 186) with maintenance comment
- [ ] **P3.2** Add `[p] View full details` to shell_UNSAFE menu (after line 192)
- [ ] **P3.3** Add `[p] View full details` to exec menu (after line 198)
- [ ] **P3.4** Add `[p] View full details` to file menu (after line 204)
- [ ] **P3.5** Update prompt strings to include `, p]`
- [ ] **P3.6** Add comment at first menu: `# NOTE: When adding new tool types, add popup option to their menu too`

### Phase 4: Input Loop
- [ ] **P4.1** Wrap input handling in `while True` loop
- [ ] **P4.2** Handle `response.lower() == "p"` with popup call
- [ ] **P4.3** Continue loop after popup, break on valid choice

### Phase 5: Testing
- [ ] **P5.1** Test popup opens on Windows (notepad)
- [ ] **P5.2** Test popup opens on Linux ($EDITOR or less)
- [ ] **P5.3** Test popup shows full tool parameters
- [ ] **P5.4** Test confirmation resumes after closing popup
- [ ] **P5.5** Test expanded truncation visible in confirmation
- [ ] **P5.6** Test content preview for write_file
- [ ] **P5.7** Test edit_file shows old→new preview
- [ ] **P5.8** Test temp file cleanup after popup closes

### Phase 6: Documentation
- [ ] **P6.1** Update CLAUDE.md with popup feature mention

---

## Cross-Platform Behavior

| Platform | Default Viewer | Fallback Chain |
|----------|---------------|----------------|
| Windows | notepad.exe | (always available) |
| Linux/Mac (TTY) | Rich pager | $VISUAL → $EDITOR → less → more → cat |
| Linux/Mac (no TTY) | External | $VISUAL → $EDITOR → less → more → cat |

---

## Validation Notes

**Validated 2026-01-31 (Phase 1 - Research):**
- `confirm_tool_action()` at lines 75-271 in confirmation_ui.py
- Current truncation: MCP 60 chars (line 146), exec 50 chars (line 159)
- Input captured via `console.input()` wrapped in `asyncio.to_thread()`
- Live display coordination exists: `live.stop()` at line 121, `live.start()` at line 270
- KeyMonitor pause protocol: `pause_event.clear()` / `pause_ack_event.wait()` at lines 125-131
- Rich pager validated: Works with stopped Live display
- Temp file pattern: `tempfile.mkstemp()` with 0o600 permissions is secure

**Validated 2026-01-31 (Phase 2 - Explorer Validation):**

All line number claims verified accurate against actual code:
- Function signature at lines 75-81 ✓
- Tool type detection at lines 113-116 ✓
- Live display pause at lines 119-131 ✓
- MCP truncation at line 146 ✓
- Exec truncation at line 159 ✓
- Options menu at lines 179-205 ✓
- Input capture at lines 207-221 ✓
- Response handling at lines 230-261 ✓
- Live display resume at lines 263-270 ✓

**Import status:**
- `Path` already imported (line 11, from pathlib)
- `asyncio` already imported (line 10)
- `sys` imported inline at line 225 → move to top-level in Phase 1
- Need to add: `os`, `shutil`, `tempfile`, `subprocess`

**Existing codebase patterns confirmed:**
- `tempfile.mkstemp()` is canonical pattern (nexus3/core/paths.py:171)
- `CREATE_NO_WINDOW` pattern consistent (nexus3/core/process.py:23)
- `shutil.which()` pattern exists (nexus3/skill/builtin/grep.py:25)
- Console obtained via `from nexus3.display import get_console`
- No existing `~/.nexus3/temp/` usage - this would be new pattern

**Implementation notes:**
- Move inline `import sys` (line 225) to top-level during Phase 1
- Content preview insertion point: between line 177 and line 179
- Menu popup options insert after: MCP(186), shell_UNSAFE(192), exec(198), file(204)

---

## Effort Estimate

~45 minutes implementation, ~30 minutes cross-platform testing.
