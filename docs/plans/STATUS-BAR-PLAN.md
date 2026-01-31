# Plan: Status Bar Enhancements

## OPEN QUESTIONS

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| **Q1** | Should we show full provider name or abbreviate? | A) Full: `openrouter` B) Short: `or` | **A) Full** - clarity over brevity |
| **Q2** | For long agent IDs, truncate? | A) No B) Max 15 chars with `...` | **B) Max 15 chars** |
| **Q3** | Show reasoning mode indicator? | A) No B) Add `[R]` suffix | **B) Add suffix** |
| **Q4** | CWD format? | A) Full with tilde B) Just basename | **A) Full with tilde** |

---

## Overview

**Current:** `■ ● ready | 1,250 / 200,000`

**Target:** `■ ● ready | main | sonnet (openrouter) | ~/project | 1,250 / 200,000`

**Components to add:**
1. Agent ID (truncated if >15 chars)
2. Model alias + provider name
3. Working directory (with tilde substitution)

---

## Scope

### Included
- Add agent ID, model info, CWD to status bar
- Use existing `display_path()` for CWD formatting
- Show reasoning mode indicator `[R]` if enabled

### Deferred
- Dynamic width based on terminal size
- Configurable status bar format

---

## Data Sources (Validated)

All required data is accessible within `get_toolbar()` closure:

| Data | Source | Access Pattern |
|------|--------|----------------|
| Agent ID | `current_agent_id` | Closure variable |
| Model info | `agent.services.get("model")` | Returns `ResolvedModel` or `None` |
| Provider name | `model.provider_name` | Attribute on `ResolvedModel` |
| Model alias | `model.alias` | Attribute on `ResolvedModel` |
| Reasoning mode | `model.reasoning` | Boolean attribute |
| Working directory | `agent.services.get_cwd()` | Returns `Path` |
| Token usage | `session.context.get_token_usage()` | Already used |

**ResolvedModel attributes** (from `nexus3/config/schema.py:547-567`):
```python
class ResolvedModel:
    model_id: str           # e.g., "anthropic/claude-sonnet-4"
    context_window: int     # e.g., 200000
    reasoning: bool         # e.g., False
    alias: str              # e.g., "sonnet"
    provider_name: str      # e.g., "openrouter"
    guidance: str | None    # e.g., "Fast model for research"
```

**Toolbar refresh:** prompt_toolkit calls `get_toolbar()` on every render cycle - no manual refresh needed. Model/CWD/agent changes are picked up automatically.

---

## Implementation

### Phase 1: Add Import

**File:** `nexus3/cli/repl.py` (add near line 67, after other `nexus3.core` imports)

```python
from nexus3.core.paths import display_path
```

### Phase 2: Replace get_toolbar()

**File:** `nexus3/cli/repl.py` (lines 1017-1032)

**Current code to replace:**
```python
def get_toolbar() -> HTML:
    """Return the bottom toolbar based on current state."""
    square = '<style fg="ansibrightblack">■</style>'

    # Get token usage from current session's context
    token_info = ""
    if session.context:
        usage = session.context.get_token_usage()
        used = usage["total"]
        budget = usage["budget"]
        token_info = f' | <style fg="ansibrightblack">{used:,} / {budget:,}</style>'

    if toolbar_has_errors:
        return HTML(f'{square} <style fg="ansiyellow">● ready (some tasks incomplete)</style>{token_info}')
    else:
        return HTML(f'{square} <style fg="ansigreen">● ready</style>{token_info}')
```

**New implementation:**
```python
def get_toolbar() -> HTML:
    """Return the bottom toolbar based on current state."""
    square = '<style fg="ansibrightblack">■</style>'
    sections: list[str] = []

    # 1. Status indicator
    status = ('<style fg="ansigreen">● ready</style>' if not toolbar_has_errors
              else '<style fg="ansiyellow">● ready (some tasks incomplete)</style>')
    sections.append(status)

    # 2. Agent ID (truncated if > 15 chars)
    agent_display = (current_agent_id[:12] + "..." if len(current_agent_id) > 15
                     else current_agent_id)
    sections.append(f'<style fg="ansicyan">{agent_display}</style>')

    # Get current agent for model and cwd
    agent = pool.get(current_agent_id)

    # 3. Model info with provider
    if agent:
        model = agent.services.get("model")
        if model:
            model_display = model.alias or model.model_id
            reasoning_indicator = " [R]" if model.reasoning else ""
            sections.append(
                f'<style fg="ansibrightblack">{model_display}{reasoning_indicator} '
                f'({model.provider_name})</style>'
            )

    # 4. Working directory
    if agent:
        cwd = agent.services.get_cwd()
        sections.append(f'<style fg="ansibrightblack">{display_path(cwd)}</style>')

    # 5. Token usage
    if session.context:
        usage = session.context.get_token_usage()
        sections.append(f'<style fg="ansibrightblack">{usage["total"]:,} / {usage["budget"]:,}</style>')

    info_str = " | ".join(sections)
    return HTML(f'{square} {info_str}')
```

---

## Files to Modify

| File | Lines | Change |
|------|-------|--------|
| `nexus3/cli/repl.py` | ~67 | Add `from nexus3.core.paths import display_path` |
| `nexus3/cli/repl.py` | 1017-1032 | Replace `get_toolbar()` function |

---

## Implementation Checklist

### Phase 1: Core Implementation
- [ ] **P1.1** Add `display_path` import at top of file (line ~67)
- [ ] **P1.2** Replace `get_toolbar()` function (lines 1017-1032)

### Phase 2: Testing
- [ ] **P2.1** Test initial startup shows all sections
- [ ] **P2.2** Test `/model` switch updates status bar immediately
- [ ] **P2.3** Test `/cwd` change updates status bar immediately
- [ ] **P2.4** Test long agent name (>15 chars) shows truncated with `...`
- [ ] **P2.5** Test reasoning model shows `[R]` indicator

### Phase 3: Documentation
- [ ] **P3.1** Update `CLAUDE.md` REPL section with new status bar format

---

## Effort Estimate

~15 minutes implementation, ~15 minutes testing.
