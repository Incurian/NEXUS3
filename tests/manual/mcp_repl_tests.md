# MCP REPL Test Suite

Manual tests for MCP functionality in REPL mode.

## Prerequisites

### 1. Stdio Server (subprocess-based)

Config has test server configured:
```json
"mcp_servers": [
  {"name": "test", "command": ["python3", "-m", "nexus3.mcp.test_server"]}
]
```

This server is launched as a subprocess when you connect. No manual startup needed.

### 2. HTTP Server (remote)

For HTTP transport tests, add an HTTP server config:
```json
"mcp_servers": [
  {"name": "test", "command": ["python3", "-m", "nexus3.mcp.test_server"]},
  {"name": "http-test", "url": "http://127.0.0.1:9000"}
]
```

Start the HTTP server manually before testing:
```bash
python3 -m nexus3.mcp.test_server.http_server --port 9000
```

### 3. Start REPL

```bash
nexus
```

---

# Part 1: Core Permission Tests

## Test 1: Permission Enforcement (SANDBOXED blocked)

```
/agent sandboxed-test --sandboxed
/mcp
```

**Expected:** Error message about MCP requiring TRUSTED/YOLO permission

```
/agent main
/destroy sandboxed-test
```

---

## Test 2: List Configured Servers

```
/mcp
```

**Expected:**
```
MCP Servers:

Configured:
  test [disconnected]
  http-test [disconnected]

Connected (visible to you): (none)
```

---

## Test 3: Full Connection Flow (Two Prompts)

```
/mcp connect test
```

**Expected prompt 1 - Consent:**
```
Connect to MCP server 'test'?
  Tools: echo, get_time, add

  [1] Allow all tools (this session)
  [2] Require confirmation for each tool
  [3] Deny connection
```

Choose `[1]` - Allow all

**Expected prompt 2 - Sharing:**
```
Share this connection with other agents?
  (Other agents will still need to approve their own permissions)

  [1] Yes - all agents can use this connection
  [2] No - only this agent (default)
```

Choose `[2]` - No (private)

**Expected:**
```
Connected to 'test' (allow-all, private)
Tools available: echo, get_time, add
```

```
/mcp disconnect test
```

---

## Test 4: Connection with Sharing

```
/mcp connect test
```

Choose `[1]` - Allow all, then `[1]` - Yes (shared)

**Expected:**
```
Connected to 'test' (allow-all, shared)
Tools available: echo, get_time, add
```

```
/mcp
```

**Expected status shows "shared":**
```
Connected (visible to you): 1
  test: 3 tools (shared)
```

```
/mcp disconnect test
```

---

# Part 2: CLI Flags (Skip Prompts)

## Test 5: --allow-all --private (Skip Both Prompts)

```
/mcp connect test --allow-all --private
```

**Expected:** No prompts, immediate connection
```
Connected to 'test' (allow-all, private)
Tools available: echo, get_time, add
```

```
/mcp disconnect test
```

---

## Test 6: --per-tool --shared (Skip Both Prompts)

```
/mcp connect test --per-tool --shared
```

**Expected:** No prompts, immediate connection
```
Connected to 'test' (per-tool, shared)
Tools available: echo, get_time, add
```

```
/mcp disconnect test
```

---

## Test 7: --allow-all Only (Skip Consent, Prompt Sharing)

```
/mcp connect test --allow-all
```

**Expected:** Only sharing prompt appears

Choose `[2]` - No

**Expected:**
```
Connected to 'test' (allow-all, private)
```

```
/mcp disconnect test
```

---

## Test 8: --shared Only (Prompt Consent, Skip Sharing)

```
/mcp connect test --shared
```

**Expected:** Only consent prompt appears

Choose `[1]` - Allow all

**Expected:**
```
Connected to 'test' (allow-all, shared)
```

```
/mcp disconnect test
```

---

## Test 9: YOLO Mode Defaults

```
/agent yolo-test --yolo
/mcp connect test
```

**Expected:** No prompts at all (YOLO defaults to allow-all, private)
```
Connected to 'test' (allow-all, private)
```

```
/agent main
/destroy yolo-test
```

---

# Part 3: Agent Visibility

## Test 10: Private Connection Not Visible to Other Agent

```
/mcp connect test --allow-all --private
```

Create another agent:
```
/agent worker-1
/mcp
```

**Expected:** worker-1 cannot see the connection
```
Configured:
  test [connected, not visible]
  ...

Connected (visible to you): (none)
```

```
/mcp tools
```

**Expected:** No MCP tools available (for this agent)

Switch back and disconnect:
```
/agent main
/mcp disconnect test
/destroy worker-1
```

---

## Test 11: Shared Connection Visible to Other Agent

```
/mcp connect test --allow-all --shared
```

Create another agent:
```
/agent worker-1
/mcp
```

**Expected:** worker-1 CAN see the connection
```
Configured:
  test [connected]
  ...

Connected (visible to you): 1
  test: 3 tools (shared)
```

```
/mcp tools
```

**Expected:** Shows mcp_test_* tools

---

## Test 12: Other Agent Has Own Allowances

Still as worker-1 (from Test 11), try to use a tool:
```
Use mcp_test_echo to say "hello from worker"
```

**Expected:** worker-1 gets its OWN consent prompt (allowances not shared)

Choose `[1]` - Allow once

**Expected:** Tool executes

Switch back:
```
/agent main
/mcp disconnect test
/destroy worker-1
```

---

## Test 13: Only Owner Can Disconnect

```
/mcp connect test --allow-all --shared
/agent worker-1
/mcp disconnect test
```

**Expected:** Error - Cannot disconnect 'test' - owned by agent 'main'

```
/agent main
/mcp disconnect test
/destroy worker-1
```

---

# Part 4: Per-Tool Confirmation

## Test 14: Per-Tool Mode - Allow Once

```
/mcp connect test --per-tool --private
```

```
Use mcp_test_echo to say "hello once"
```

**Expected prompt:**
```
Allow MCP tool 'mcp_test_echo'?
  Server: test
  Arguments: {'message': 'hello once'}

  [1] Allow once
  [2] Allow this tool always (this session)
  [3] Allow all tools from this server (this session)
  [4] Deny
```

Choose `[1]` - Allow once

**Expected:** Tool executes, returns "hello once"

```
Use mcp_test_echo to say "hello again"
```

**Expected:** Prompts again (allow once doesn't persist)

Choose `[4]` - Deny

**Expected:** Error message about tool denied

---

## Test 15: Per-Tool Mode - Allow This Tool Always

```
Use mcp_test_echo to say "allowed tool"
```

Choose `[2]` - Allow this tool always

**Expected:** Tool executes

```
Use mcp_test_echo to say "no prompt now"
```

**Expected:** Executes immediately (no prompt - tool is allowed)

```
Use mcp_test_add to add 5 and 3
```

**Expected:** Prompts (different tool, not allowed yet)

Choose `[4]` - Deny

---

## Test 16: Per-Tool Mode - Allow All From Server

```
Use mcp_test_add to add 10 and 20
```

Choose `[3]` - Allow all tools from this server

**Expected:** Tool executes, returns "30"

```
Use mcp_test_get_time
```

**Expected:** Executes immediately (all server tools now allowed)

```
/mcp disconnect test
```

---

# Part 5: Allowances and Disconnect

## Test 17: Allowances Reset on Disconnect

```
/mcp connect test --per-tool --private
```

```
Use mcp_test_echo to say "first"
```

Choose `[2]` - Allow this tool always

```
Use mcp_test_echo to say "no prompt"
```

**Expected:** No prompt (tool allowed)

Now disconnect and reconnect:
```
/mcp disconnect test
/mcp connect test --per-tool --private
```

```
Use mcp_test_echo to say "should prompt again"
```

**Expected:** Prompts again (allowances were reset on disconnect)

```
/mcp disconnect test
```

---

# Part 6: Dead Connection Detection

## Test 18: Stdio Server Dies Mid-Session

```
/mcp connect test --allow-all --private
```

Find and kill the subprocess:
```bash
# In another terminal
pkill -f "nexus3.mcp.test_server"
```

Back in REPL:
```
/mcp
```

**Expected:** Server no longer listed as connected (dead connection detected)
```
Configured:
  test [disconnected]
  ...

Connected (visible to you): (none)
```

---

## Test 19: HTTP Server Dies Mid-Session

Start HTTP server:
```bash
python3 -m nexus3.mcp.test_server.http_server --port 9000
```

Connect:
```
/mcp connect http-test --allow-all --private
```

Stop the HTTP server (Ctrl+C in other terminal).

Try to use a tool:
```
Use mcp_http-test_echo to say "hello"
```

**Expected:** Error about connection failure

```
/mcp
```

**Expected:** May still show as connected (HTTP detection is lazy)

---

# Part 7: HTTP Transport

## Test 20: HTTP Connection Works

Start HTTP server if not running:
```bash
python3 -m nexus3.mcp.test_server.http_server --port 9000
```

```
/mcp connect http-test --allow-all --private
```

**Expected:**
```
Connected to 'http-test' (allow-all, private)
Tools available: echo, get_time, add
```

```
Use mcp_http-test_echo to say "via http"
```

**Expected:** Returns "via http"

```
/mcp disconnect http-test
```

---

## Test 21: Multiple Transports Simultaneously

```
/mcp connect test --allow-all --private
/mcp connect http-test --allow-all --private
/mcp
```

**Expected:**
```
Connected (visible to you): 2
  test: 3 tools (owner: main)
  http-test: 3 tools (owner: main)
```

```
/mcp tools
```

**Expected:** Shows 6 tools (3 from each server)

```
/mcp disconnect test
/mcp disconnect http-test
```

---

# Part 8: Edge Cases

## Test 22: Connect Non-existent Server

```
/mcp connect nonexistent
```

**Expected:** Error - server not found in config

---

## Test 23: Double Connect (Already Connected)

```
/mcp connect test --allow-all --private
/mcp connect test
```

**Expected:** Error - Already connected to 'test'

```
/mcp disconnect test
```

---

## Test 24: Tool Definitions Refresh

```
/mcp disconnect test
```

Ask agent:
```
What tools do you have?
```

**Expected:** Should NOT list mcp_test_* tools

```
/mcp connect test --allow-all --private
```

Ask agent:
```
What tools do you have?
```

**Expected:** Should list mcp_test_echo, mcp_test_add, mcp_test_get_time

```
/mcp disconnect test
```

---

## Test 25: Disable Individual MCP Tool

```
/mcp connect test --allow-all --private
/permissions --disable mcp_test_add
/permissions --list-tools
```

**Expected:** Shows mcp_test_add as disabled

```
Calculate 5 + 3 using mcp_test_add
```

**Expected:** Error - tool disabled

```
Echo "still works" using mcp_test_echo
```

**Expected:** Works

```
/permissions --enable mcp_test_add
/mcp disconnect test
```

---

# Test Results

## Part 1: Core Permission Tests

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 1. SANDBOXED blocked | | |
| 2. List servers | | |
| 3. Full connection flow (two prompts) | | |
| 4. Connection with sharing | | |

## Part 2: CLI Flags

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 5. --allow-all --private | | |
| 6. --per-tool --shared | | |
| 7. --allow-all only | | |
| 8. --shared only | | |
| 9. YOLO defaults | | |

## Part 3: Agent Visibility

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 10. Private not visible | | |
| 11. Shared visible | | |
| 12. Other agent own allowances | | |
| 13. Only owner can disconnect | | |

## Part 4: Per-Tool Confirmation

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 14. Allow once | | |
| 15. Allow tool always | | |
| 16. Allow all from server | | |

## Part 5: Allowances and Disconnect

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 17. Allowances reset on disconnect | | |

## Part 6: Dead Connection Detection

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 18. Stdio server dies | | |
| 19. HTTP server dies | | |

## Part 7: HTTP Transport

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 20. HTTP connection works | | |
| 21. Multiple transports | | |

## Part 8: Edge Cases

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 22. Non-existent server | | |
| 23. Double connect | | |
| 24. Tool definitions refresh | | |
| 25. Disable MCP tool | | |

---

# Permission Flow Summary

```
Transport Selection (automatic):
  config.command → StdioTransport (subprocess)
  config.url     → HTTPTransport (HTTP POST)

CLI Flags:
  --allow-all   Skip consent prompt, allow all tools
  --per-tool    Skip consent prompt, require per-tool confirmation
  --shared      Skip sharing prompt, share with all agents
  --private     Skip sharing prompt, keep private to this agent

Prompts (TRUSTED mode, no flags):
  1. Consent Prompt:
     [1] Allow all → No per-tool prompts
     [2] Per-tool  → Prompts for each tool call
     [3] Deny      → Connection cancelled

  2. Sharing Prompt:
     [1] Yes → All agents can see and use this connection
     [2] No  → Only this agent (default)

Per-Tool Confirmation (per-tool mode):
  [1] Allow once      → This call only
  [2] Allow tool      → This tool, rest of session
  [3] Allow server    → All tools from server, rest of session
  [4] Deny            → Tool call rejected

YOLO mode: All prompts skipped, defaults to allow-all + private
SANDBOXED mode: MCP completely blocked

Visibility Rules:
  - Private connections: Only visible to owner agent
  - Shared connections: Visible to all agents
  - Allowances (allow-all, per-tool): Always per-agent, never shared
  - Only owner can disconnect a connection
```

---

# Quick Smoke Test

```bash
# Terminal 1: Start REPL
nexus

# Quick test with flags (no prompts)
/mcp connect test --allow-all --private
Use mcp_test_add to calculate 40 + 2
# Expected: 42
/mcp disconnect test
/quit
```

For HTTP:
```bash
# Terminal 1: Start HTTP server
python3 -m nexus3.mcp.test_server.http_server --port 9000

# Terminal 2: Start REPL
nexus

/mcp connect http-test --allow-all --private
Use mcp_http-test_echo to say "hello"
# Expected: hello
/mcp disconnect http-test
/quit
```

Multi-agent test:
```bash
nexus

# Connect as shared
/mcp connect test --allow-all --shared

# Create worker
/agent worker-1

# Worker sees the connection
/mcp

# Worker uses tool (gets own consent prompt)
Use mcp_test_echo to say "from worker"
# Choose [1] Allow once

# Cleanup
/agent main
/mcp disconnect test
/destroy worker-1
/quit
```
