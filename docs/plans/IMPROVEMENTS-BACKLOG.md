# NEXUS3 Improvements & Ideas

Compiled from notes on UI/UX improvements, bug fixes, and feature ideas.

---

## 1. UI/UX Improvements

### 1.1 YOLO Mode Warning Enhancement

**Current State:** Shows `⚠️ YOLO MODE - All actions execute without confirmation` in bold red before prompt.

**Improvements:**
- [ ] Show permissions help message (how to change modes, what each mode means)
- [ ] More explicit warning about what YOLO allows (network, file writes, shell commands)
- [ ] Consider showing warning on mode *switch* as well as persistently

**Location:** `nexus3/cli/repl.py:1255-1260`

---

### 1.2 Tool Use/Return Previews

**Current State:**
- Tool params truncated to 70 chars single line
- Output summary is ~60 chars single line
- Error preview is 70 chars

**Improvements:**
- [ ] **Line 1:** Tool name + priority params (path, agent_id)
- [ ] **Line 2:** Expanded parameters (increase from 70 to ~140 chars or two lines)
- [ ] Check error returns - should print full tool message with gumball
- [ ] Use different color for return values vs calls (cyan for call, green for success, red for error)
- [ ] Halted calls (due to previous error) should still show gumball indicator

**Implementation Details:**
- `format_tool_params()` max_length: 70 → 140 or split across two lines
- Return preview: Show on separate line with `→` prefix, different styling
- Error returns: Full gumball treatment, not just truncated preview

**Locations:**
- `nexus3/display/streaming.py` - ToolStatus rendering
- `nexus3/cli/confirmation_ui.py:21-72` - format_tool_params()
- `nexus3/cli/repl.py:692-817` - tool result callbacks

---

### 1.3 Permissions Previews

**Current State:** Permission details may be truncated in display.

**Improvements:**
- [ ] Larger previews for permission information
- [ ] Auto-create temp file with full details if display is truncated
- [ ] Allow user to review full permission config easily

---

### 1.4 Token Usage Status Bar

**Current State:**
- Shows `used / budget` (e.g., "1,250 / 200,000")
- Bottom toolbar uses prompt_toolkit HTML
- Status bar uses Rich Live display

**Issues Identified:**
- [ ] Not updating on model switch (status bar doesn't refresh)
- [ ] Confirm model is actually switching (internal state vs display)

**New Info to Display:**
- [ ] **Model name + provider** (e.g., "sonnet via openrouter")
- [ ] **Current agent ID** (useful in multi-agent sessions)
- [ ] **Working directory** (CWD or project name)

**Proposed Format:**
```
■ ● ready | sonnet (openrouter) | main | ~/project | 1,250 / 200,000
```

**Locations:**
- `nexus3/cli/repl.py:1017-1032` - get_toolbar()
- `nexus3/display/summary.py` - SummaryBar
- `nexus3/cli/repl_commands.py:1380-1500` - /model command

---

### 1.5 Status Message State

**Current State:** Activity states: IDLE, WAITING, THINKING, RESPONDING, TOOL_CALLING

**Issue:** Shows "running last tool use" even after tool completes, should show "waiting" or similar.

**Locations:**
- `nexus3/display/streaming.py:125-141` - _render_activity_status()
- `nexus3/display/theme.py:16-23` - Activity enum

---

## 2. Bug Fixes

### 2.1 edit_file Error Message Bug

**Symptom:** `edit_file` returns "File or directory not found" when `old_string` doesn't match, but file exists.

**Expected:** Should return "String not found in file: {old_string[:100]}..."

**Analysis:** The code at `nexus3/skill/builtin/edit_file.py` shows correct error messages:
- Line 144-145: `FileNotFoundError` → "File not found: {path}"
- Line 202-203: count == 0 → "String not found in file: {old_string[:100]}..."

**Possible Causes:**
1. Exception mapping bug - wrong exception caught
2. Path resolution mismatch inside tool before string match
3. Permission/sandbox validation throwing ENOENT-like error
4. FileSkill base class path validation returning wrong error

**Status:** Documented for future investigation (deferred)

**Investigation Needed (Future):**
- [ ] Review FileSkill._validate_path() error returns
- [ ] Check if symlink resolution or sandbox checks can trigger ENOENT
- [ ] Add more specific exception handling to disambiguate

**Location:** `nexus3/skill/builtin/edit_file.py`, `nexus3/skill/base.py`

**Action:** Add to Known Bugs section in CLAUDE.md

---

## 3. Feature Ideas

### 3.1 Prompt Caching

**Current State:** Neither Anthropic nor OpenRouter providers implement prompt caching.

**Anthropic Prompt Caching:**
- Beta feature requiring `anthropic-beta: prompt-caching-2024-07-31` header
- Supports caching system prompts and conversation prefixes
- Significant cost/latency savings for repeated context

**Implementation:**
- [ ] Add cache_control to Anthropic provider system message
- [ ] Check OpenRouter's caching support (may be provider-specific)
- [ ] Ensure backwards compatibility with providers that don't support caching
- [ ] Track cache hit/miss in token reporting

**Location:** `nexus3/provider/anthropic.py:96-158`

---

### 3.2 Split NEXUS.md Context

**Current State:** Layered loading: global → ancestors → local, all merged with section headers.

**Problem:** Users can't easily update the "main" NEXUS.md from source while maintaining custom additions.

**Proposal:**
- Ship a `NEXUS-DEFAULT.md` that provides generic NEXUS3 info
- Users maintain `NEXUS.md` for custom system-level instructions
- Loading order: defaults → user's global → ancestors → local
- Users can `nexus3 --update-defaults` to refresh default docs without losing customizations

**Location:** `nexus3/context/loader.py:256-291`

---

### 3.3 NEXUS as MCP Server (Separate Project)

**Concept:** NEXUS3 built-in skills as an MCP server plugin for any agent system.

**Features:**
- Expose selected NEXUS skills as MCP tools
- Configurable skill selection (by category or individual)
- Modular plug-and-play skill architecture
- Template system for easy skill additions

**Scope Decisions Needed:**
- [ ] Which skills make sense as standalone? (file ops, git, grep - yes; nexus_create, sub-agents - probably not)
- [ ] Category organization (filesystem, search, vcs, execution)
- [ ] Whether to support skill dependencies
- [ ] Separate repo vs nexus3 subpackage

**Note:** This is a separate project, not part of NEXUS3 core.

---

## 4. Non-Bugs (User Error Examples)

### git grep Argument Order

**Issue:** `git grep -n "pattern" -n path | head` fails because options must come before non-option arguments.

**Resolution:** Not a NEXUS bug - just malformed command syntax.

**Mitigation Options (Low Priority):**
- Built-in `grep` skill preferred over `git grep`
- Could add helper docs/skill for proper git grep usage

---

## Priority Assessment

| Item | Priority | Effort | Impact | Status |
|------|----------|--------|--------|--------|
| 1.4 Status bar enhancements | High | M | UX - model/agent/cwd display | Ready |
| 1.5 Status message state | Medium | S | UX polish | Ready |
| 1.2 Tool previews | Medium | M | UX - expanded params | Ready |
| 1.1 YOLO warning | Medium | S | Safety/UX | Ready |
| 3.1 Prompt caching | Medium | M | Performance/cost | Ready |
| 2.1 edit_file error | Medium | S | Bug fix | **Deferred** |
| 3.2 Split NEXUS.md | Low | M | Maintainability | Backlog |
| 1.3 Permissions preview | Low | S | UX polish | Backlog |
| 3.3 MCP Server | Future | L | Separate project | Idea only |

---

## Open Questions

1. **Prompt caching:** Should we track cache savings in token display?
2. **NEXUS.md split:** What goes in defaults vs user customization?
3. **Implementation order:** Should these be separate branches/PRs or one combined effort?
