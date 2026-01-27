# MCP Implementation: Remaining Phases

This document outlines the phased plan to complete all remaining MCP implementation work.

**Created:** 2026-01-27
**Status:** Ready for implementation

---

## Overview

| Phase | Description | Effort | Priority |
|-------|-------------|--------|----------|
| **Phase 1** | Documentation (P5.x) | 1-2 hours | ✅ COMPLETE |
| **Phase 2** | Windows Polish (P2.0.8-11) | 1-2 hours | ✅ COMPLETE |
| **Phase 3** | Deferred Tests (P1.4.4, P1.9.14) | 1-2 hours | ✅ COMPLETE |
| **Phase 4** | Future: Resources (FA) | 3-4 hours | Deferred |
| **Phase 5** | Future: Prompts (FB) | 2-3 hours | Deferred |
| **Phase 6** | Future: Utilities (FC) | 2-3 hours | Deferred |

---

## Phase 1: Documentation (P5.x) - COMPLETE

**Goal:** Update all documentation to reflect completed MCP improvements before merging.

### Checklist

- [x] **P5.1** Update `nexus3/mcp/README.md` with spec compliance changes
  - Document pagination support (P1.4)
  - Document HTTP retry logic (P1.10)
  - Document reconnection and graceful failure (P2.1)
  - Update architecture diagram if needed

- [x] **P5.2** Update `CLAUDE.md` MCP section
  - Add new `/mcp retry` command to REPL Commands Reference
  - Update MCP configuration examples with new options (`fail_if_no_tools`)
  - Document lazy reconnection behavior

- [x] **P5.3** Document new MCPTool fields in `protocol.py`
  - Add docstrings for `title`, `output_schema`, `icons`, `annotations` fields
  - Document MCPToolResult `structured_content` field

- [x] **P5.4** Update `/mcp` command help
  - Add `retry <server>` subcommand to help text
  - Verify all subcommands are documented

- [x] **P5.5** Document Windows-specific configuration
  - `SAFE_ENV_KEYS` Windows variables (USERPROFILE, APPDATA, PATHEXT, etc.)
  - Command resolution (.cmd, .bat extension handling)
  - Process termination (CTRL_BREAK_EVENT)

- [x] **P5.6** Document error context pattern
  - `MCPErrorContext` dataclass usage
  - Error formatter functions
  - How to add new error types

- [x] **P5.7** Document HTTP session ID behavior
  - Session ID capture and validation
  - Header format (`mcp-session-id`)
  - Security considerations (validation, max length)

### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/README.md` | P5.1, P5.5, P5.6, P5.7 |
| `CLAUDE.md` | P5.2 |
| `nexus3/mcp/protocol.py` | P5.3 (docstrings) |
| `nexus3/cli/repl_commands.py` | P5.4 (help text) |

---

## Phase 2: Windows Polish (P2.0.8-11) - COMPLETE

**Goal:** Improve Windows user experience with better error messages and test coverage.

### Checklist

- [x] **P2.0.8** Add Windows-specific hints to error formatter
  - Detect Windows in `format_command_not_found()`
  - Add hints about PATHEXT, .cmd/.bat extensions
  - Suggest checking `where` instead of `which`

- [x] **P2.0.9** Add unit tests for Windows command resolution
  - Test `resolve_command()` with mocked `shutil.which`
  - Test extension resolution (.cmd, .bat, .exe)
  - Test path-through for already-resolved commands

- [x] **P2.0.10** Add unit tests for CRLF handling
  - Test `StdioTransport.receive()` with CRLF line endings
  - Test mixed LF/CRLF in same session
  - Test JSON parsing after CRLF strip

- [x] **P2.0.11** Document Windows-specific config in MCP README
  - (Completed in P5.5)

### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/error_formatter.py` | P2.0.8 |
| `tests/unit/mcp/test_transport.py` | P2.0.9, P2.0.10 |
| `nexus3/mcp/README.md` | P2.0.11 |

---

## Phase 3: Deferred Tests (P1.4.4, P1.9.14) - COMPLETE

**Goal:** Add integration tests for edge cases that are hard to unit test.

### Checklist

- [x] **P1.4.4** Integration test with paginating MCP server
  - Create test server that returns paginated tool lists
  - Test 2-page, 3-page, and empty page scenarios
  - Verify all tools collected across pages

- [x] **P1.9.14** Integration tests for user-facing error output
  - Test actual error message formatting in REPL context
  - Verify Rich markup escaping works
  - Test stderr capture and display

### Files Created

| File | Purpose |
|------|---------|
| `nexus3/mcp/test_server/paginating_server.py` | Paginating MCP server for tests |
| `tests/integration/test_mcp_pagination.py` | 10 pagination integration tests |
| `tests/integration/test_mcp_errors.py` | 21 error output integration tests |

---

## Phase 4: Future - Resources (FA) - DEFERRED

**Goal:** Implement MCP resources capability (read-only file/data access).

### Checklist

- [ ] **FA.1** Add `resources/list` method to MCPClient
- [ ] **FA.2** Add `resources/read` method to MCPClient
- [ ] **FA.3** Create `MCPResource` dataclass in protocol.py
- [ ] **FA.4** Add resource caching/refresh logic
- [ ] **FA.5** Add `/mcp resources [server]` REPL command
- [ ] **FA.6** Add unit tests for resource methods
- [ ] **FA.7** Add integration tests with test server

### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/protocol.py` | MCPResource dataclass |
| `nexus3/mcp/client.py` | list_resources(), read_resource() |
| `nexus3/mcp/registry.py` | Resource caching |
| `nexus3/cli/repl_commands.py` | /mcp resources command |
| `tests/unit/mcp/test_client.py` | Unit tests |
| `tests/integration/test_mcp_resources.py` | Integration tests |

---

## Phase 5: Future - Prompts (FB) - DEFERRED

**Goal:** Implement MCP prompts capability (server-provided prompt templates).

### Checklist

- [ ] **FB.1** Add `prompts/list` method to MCPClient
- [ ] **FB.2** Add `prompts/get` method to MCPClient
- [ ] **FB.3** Create `MCPPrompt` dataclass in protocol.py
- [ ] **FB.4** Add `/mcp prompts [server]` REPL command
- [ ] **FB.5** Add unit tests for prompt methods
- [ ] **FB.6** Add integration tests with test server

### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/protocol.py` | MCPPrompt dataclass |
| `nexus3/mcp/client.py` | list_prompts(), get_prompt() |
| `nexus3/cli/repl_commands.py` | /mcp prompts command |
| `tests/unit/mcp/test_client.py` | Unit tests |
| `tests/integration/test_mcp_prompts.py` | Integration tests |

---

## Phase 6: Future - Utilities (FC) - DEFERRED

**Goal:** Implement MCP utility features (ping, cancellation, progress, logging).

### Checklist

- [ ] **FC.1** Add `ping` method to MCPClient
  - Useful for health checks and latency measurement

- [ ] **FC.2** Add request cancellation support
  - Send `$/cancelRequest` notification
  - Track pending requests by ID
  - Handle cancellation responses

- [ ] **FC.3** Add progress notification handling
  - `$/progress` notification parsing
  - Progress callback mechanism
  - Display integration

- [ ] **FC.4** Add logging notification handling
  - `$/log` notification parsing
  - Log level filtering
  - Display integration

### Files to Modify

| File | Changes |
|------|---------|
| `nexus3/mcp/client.py` | ping(), cancel_request(), progress handling |
| `nexus3/mcp/protocol.py` | Progress/Log notification types |
| `nexus3/display/` | Progress/log display integration |
| `tests/unit/mcp/test_client.py` | Unit tests |

---

## Execution Order

### Immediate (before merge)
1. **Phase 1** - Documentation updates

### Post-merge (when needed)
2. **Phase 2** - Windows polish (if Windows users report issues)
3. **Phase 3** - Deferred tests (nice to have)

### Future releases
4. **Phase 4** - Resources (when MCP servers use resources)
5. **Phase 5** - Prompts (when MCP servers use prompts)
6. **Phase 6** - Utilities (when needed for debugging/monitoring)

---

## Quick Reference

### Current Branch Status
- **Branch:** `feature/mcp-improvements`
- **Commits ahead:** 25
- **Tests:** 2512 passed

### Completed Priorities
- [x] P0.5: Security hardening
- [x] P0: Config format compatibility
- [x] P1.1-P1.10: Protocol improvements
- [x] P2.0: Windows compatibility (core)
- [x] P2.1: Registry robustness
