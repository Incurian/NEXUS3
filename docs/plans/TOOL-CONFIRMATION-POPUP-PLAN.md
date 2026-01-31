# Plan: Tool Confirmation Popup Enhancement

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Popup viewer? | A) Rich Panel in-terminal B) System pager (less) C) External editor (notepad/vim) | **C) External editor** - user can scroll, copy |
| **Q2** | Popup key? | A) 'p' B) 'v' (view) C) 'd' (details) | **A) 'p'** - intuitive for "popup" |
| **Q3** | Temp file location? | A) System temp B) .nexus3/temp/ C) Scratchpad | **B) .nexus3/temp/** - organized, cleaned on exit |
| **Q4** | File extension? | A) .txt B) .md C) .json | **A) .txt** - universal, opens in any editor |

---

## Overview

**Problem:** When an agent wants to run a tool, the confirmation dialog shows truncated parameters. For complex commands (long paths, large diffs, multi-line content), users can't see what they're approving.

**Current behavior:**
- MCP tools: 60 char preview
- Exec tools: 50 char command preview
- File tools: Just the path
- No way to see full details

**Goal:**
1. Show more detail by default (expand truncation limits)
2. Add "press p for popup" to see full details in external viewer

---

## Current Confirmation UI

**File:** `nexus3/cli/confirmation_ui.py`

**Function:** `confirm_tool_action()` (lines 75-271)

**Current flow:**
```
  ● write_file wants to write to: /home/user/project/src/...

  [1] Allow once
  [2] Allow for this file
  [3] Allow writes in /home/user/project/
  [4] Deny

  Choice [1-4]: _
```

**Current truncation:**
- Tool description built at lines 141-177
- MCP tools: args truncated to 60 chars (line 151)
- Exec tools: command truncated to 50 chars (line 158)
- No full view option

---

## The Enhancement

### After Implementation

```
  ● write_file wants to write to: /home/user/project/src/components/Button.tsx
    content: "import React from 'react';\n\nexport const Button = ({ label, onClick, disabled..."

  [1] Allow once
  [2] Allow for this file
  [3] Allow writes in /home/user/project/
  [4] Deny
  [p] View full details

  Choice [1-4, p]: _
```

When user presses 'p':
1. Write full tool details to temp file
2. Open in system editor (notepad on Windows, $EDITOR or less on Unix)
3. Wait for user to close
4. Return to confirmation prompt

---

## Implementation

### Phase 1: Add Popup Helper Function

**File:** `nexus3/cli/confirmation_ui.py` (add after imports, before `format_tool_params`)

```python
import os
import sys
import tempfile
import subprocess
from pathlib import Path


def _get_system_viewer() -> list[str]:
    """Get the appropriate viewer command for the current platform.

    Returns:
        Command list to open a text file (append filename to use).
    """
    if sys.platform == "win32":
        # Windows: use notepad (always available)
        return ["notepad.exe"]

    # Unix: prefer $EDITOR, fall back to less, then cat
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        return [editor]

    # Try common pagers/editors in order
    for cmd in ["less", "more", "cat"]:
        if shutil.which(cmd):
            return [cmd]

    return ["cat"]  # Last resort


def _open_in_popup(content: str, title: str = "Tool Details") -> bool:
    """Open content in external viewer for user inspection.

    Args:
        content: Text content to display
        title: Title for the content (used in header)

    Returns:
        True if successfully opened (even if user just closed it),
        False if failed to open viewer.
    """
    # Create temp directory if needed
    temp_dir = Path.home() / ".nexus3" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Create temp file with content
    temp_file = temp_dir / f"confirmation_{os.getpid()}.txt"

    try:
        # Write content with header
        full_content = f"=== {title} ===\n\n{content}\n"
        temp_file.write_text(full_content, encoding="utf-8")

        # Get viewer command
        viewer_cmd = _get_system_viewer()

        # Open viewer
        if sys.platform == "win32":
            # Windows: use subprocess with no window flash
            process = subprocess.Popen(
                viewer_cmd + [str(temp_file)],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
        else:
            # Unix: run in foreground so user can interact
            process = subprocess.Popen(viewer_cmd + [str(temp_file)])

        # Wait for viewer to close
        process.wait()
        return True

    except Exception:
        return False
    finally:
        # Clean up temp file
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass
```

### Phase 2: Format Full Tool Details

**File:** `nexus3/cli/confirmation_ui.py` (add after `_open_in_popup`)

```python
def _format_full_tool_details(
    tool_call: "ToolCall",
    target_path: str | None,
    agent_cwd: str | None,
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
    if agent_cwd:
        lines.append(f"Working Directory: {agent_cwd}")

    lines.append("")
    lines.append("Parameters:")
    lines.append("-" * 40)

    for key, value in tool_call.arguments.items():
        value_str = str(value)
        if len(value_str) > 200 or "\n" in value_str:
            # Multi-line or long value: show on separate lines
            lines.append(f"\n{key}:")
            lines.append("-" * 20)
            lines.append(value_str)
            lines.append("-" * 20)
        else:
            lines.append(f"{key}: {value_str}")

    return "\n".join(lines)
```

### Phase 3: Update Confirmation Dialog

**File:** `nexus3/cli/confirmation_ui.py`

**Modify `confirm_tool_action()` to add popup option:**

**Step 3a: Add import for shutil (at top with other imports):**
```python
import shutil
```

**Step 3b: Expand description truncation (around lines 151, 158):**

```python
# MCP tools (line 151): Change from 60 to 120 chars
args_preview = format_tool_params(tool_call.arguments, max_length=120)

# Exec tools (line 158): Change from 50 to 100 chars
cmd_preview = cmd[:100] + "..." if len(cmd) > 100 else cmd
```

**Step 3c: Add popup option to menu (around line 205):**

After the existing options, add:
```python
# Add popup option to all confirmation types
console.print("[dim][p] View full details[/]")
```

**Step 3d: Update input prompt (around line 208):**

```python
# Change from:
prompt = "\n[dim]Choice [1-4]:[/] "

# To (dynamically based on option count):
max_option = len(responses)  # 2, 3, or 4 depending on tool type
prompt = f"\n[dim]Choice [1-{max_option}, p]:[/] "
```

**Step 3e: Handle 'p' key in response loop (around line 220):**

Wrap the existing response handling in a loop:
```python
while True:
    response = await asyncio.to_thread(get_input)
    response = response.lower().strip()

    # Handle popup request
    if response == "p":
        full_details = _format_full_tool_details(tool_call, target_path, agent_cwd)
        success = _open_in_popup(full_details, title=f"Tool: {tool_call.name}")
        if not success:
            console.print("[yellow]Could not open viewer[/]")
        # Re-display the options and continue loop
        # (The options are still visible, just re-prompt)
        continue

    # Existing response handling...
    if response in responses:
        break

    # Invalid input - continue loop
    console.print("[yellow]Invalid choice[/]")
```

### Phase 4: Add Content Preview for File Operations

**File:** `nexus3/cli/confirmation_ui.py`

For write_file and edit_file, show a content preview in the confirmation:

**Around line 172 (file operations section):**

```python
# Current:
description = f"write to: {safe_path}"

# Enhanced:
description = f"write to: {safe_path}"
# Add content preview for write operations
if tool_call.name in ("write_file", "append_file") and "content" in tool_call.arguments:
    content = str(tool_call.arguments["content"])
    preview = content[:150].replace("\n", "\\n")
    if len(content) > 150:
        preview += "..."
    description += f"\n    [dim]content: \"{preview}\"[/]"
elif tool_call.name == "edit_file" and "old_string" in tool_call.arguments:
    old = str(tool_call.arguments.get("old_string", ""))[:80]
    new = str(tool_call.arguments.get("new_string", ""))[:80]
    description += f"\n    [dim]replace: \"{old}\" → \"{new}\"[/]"
```

---

## Files to Modify

| File | Change |
|------|--------|
| `nexus3/cli/confirmation_ui.py` | Add `_get_system_viewer()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `_open_in_popup()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `_format_full_tool_details()` helper |
| `nexus3/cli/confirmation_ui.py` | Add `import shutil` |
| `nexus3/cli/confirmation_ui.py` | Expand truncation limits (60→120, 50→100) |
| `nexus3/cli/confirmation_ui.py` | Add `[p] View full details` option |
| `nexus3/cli/confirmation_ui.py` | Handle 'p' key in input loop |
| `nexus3/cli/confirmation_ui.py` | Add content preview for file writes |

---

## Implementation Checklist

### Phase 1: Popup Infrastructure
- [ ] **P1.1** Add `import shutil` to imports
- [ ] **P1.2** Add `_get_system_viewer()` function
- [ ] **P1.3** Add `_open_in_popup()` function
- [ ] **P1.4** Add `_format_full_tool_details()` function

### Phase 2: Expand Default Truncation
- [ ] **P2.1** MCP tools: expand args preview from 60 to 120 chars
- [ ] **P2.2** Exec tools: expand command preview from 50 to 100 chars
- [ ] **P2.3** Add content preview for write_file/edit_file operations

### Phase 3: Add Popup Option
- [ ] **P3.1** Add `[p] View full details` to option menu
- [ ] **P3.2** Update input prompt to show `[1-N, p]`
- [ ] **P3.3** Wrap response handling in loop for popup re-prompt
- [ ] **P3.4** Handle 'p' key to open popup viewer

### Phase 4: Testing
- [ ] **P4.1** Test popup opens on Windows (notepad)
- [ ] **P4.2** Test popup opens on Linux ($EDITOR or less)
- [ ] **P4.3** Test popup shows full tool parameters
- [ ] **P4.4** Test confirmation resumes after closing popup
- [ ] **P4.5** Test expanded truncation limits visible in confirmation
- [ ] **P4.6** Test content preview for write_file
- [ ] **P4.7** Test edit_file shows old→new preview

### Phase 5: Cleanup
- [ ] **P5.1** Ensure temp files are deleted after popup closes
- [ ] **P5.2** Handle viewer not found gracefully

---

## Cross-Platform Behavior

| Platform | Viewer | Notes |
|----------|--------|-------|
| Windows | notepad.exe | Always available, no window flash |
| Linux/Mac | $EDITOR | Respects user preference |
| Linux/Mac | less | Fallback pager |
| Linux/Mac | more | Second fallback |
| Linux/Mac | cat | Last resort (no scrolling) |

---

## Validation Notes

**Explored 2026-01-31:**
- `confirm_tool_action()` at lines 75-271 in confirmation_ui.py
- Current truncation: MCP 60 chars, exec 50 chars
- Input captured via `console.input()` wrapped in `asyncio.to_thread()`
- Live display coordination exists (stop/start around confirmation)
- No existing external viewer patterns in codebase - this is new

---

## Effort Estimate

~45 minutes implementation, ~30 minutes cross-platform testing.
