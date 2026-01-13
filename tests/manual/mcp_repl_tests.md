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

# Part 1: Core Permission Tests (Stdio)

These tests use the stdio transport (`command` config).

---

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

Connected: (none)
```

---

## Test 3: Connection Consent - Allow All

```
/mcp connect test
```

**Expected prompt:**
```
Connect to MCP server 'test'?
  Tools: echo, get_time, add

  [1] Allow all tools (this session)
  [2] Require confirmation for each tool
  [3] Deny connection
```

Choose `[1]` - Allow all

**Expected:**
```
Connected to 'test' (allow-all)
Tools available: echo, get_time, add
```

---

## Test 4: Allow-All Mode - No Per-Tool Prompts

```
Use mcp_test_echo to say "hello"
```

**Expected:** Tool executes immediately without confirmation prompt

```
/mcp disconnect test
```

---

## Test 5: Connection Consent - Per-Tool Mode

```
/mcp connect test
```

Choose `[2]` - Require confirmation for each tool

**Expected:**
```
Connected to 'test' (per-tool)
Tools available: echo, get_time, add
```

---

## Test 6: Per-Tool Confirmation - Allow Once

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

## Test 7: Per-Tool Confirmation - Allow This Tool Always

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

## Test 8: Per-Tool Confirmation - Allow All From Server

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
Use mcp_test_add to add 1 and 2
```

**Expected:** Executes immediately (no prompt)

---

## Test 9: Connection Consent - Deny

```
/mcp disconnect test
/mcp connect test
```

Choose `[3]` - Deny connection

**Expected:** Error message "Connection to 'test' denied by user"

```
/mcp
```

**Expected:** test shows as [disconnected]

---

## Test 10: YOLO Mode - No Prompts

```
/agent yolo-test --yolo
/mcp connect test
```

**Expected:** Connects immediately with (allow-all), no consent prompt

```
Use mcp_test_echo to say "yolo"
```

**Expected:** Executes immediately, no confirmation

```
/agent main
/destroy yolo-test
```

---

## Test 11: List MCP Tools

```
/mcp connect test
```

(Choose any allow option)

```
/mcp tools
```

**Expected:**
```
MCP Tools:
  mcp_test_echo
    Echo back the input message
  mcp_test_get_time
    Get current date and time
  mcp_test_add
    Add two numbers
```

```
/mcp tools test
```

**Expected:** Same output (filtered to 'test' server)

---

## Test 12: Disable Individual MCP Tool

```
/permissions --disable mcp_test_add
/permissions --list-tools
```

**Expected:** Shows mcp_test_add as disabled

```
Calculate 5 + 3 using mcp_test_add
```

**Expected:** Error - tool disabled (regardless of allowances)

```
Echo "still works" using mcp_test_echo
```

**Expected:** Works (not disabled)

```
/permissions --enable mcp_test_add
```

---

## Test 13: Server Status Shows Mode

```
/mcp
```

**Expected:** Shows connection mode
```
Connected: 1
  test: 3 tools (allow-all)
```

or

```
Connected: 1
  test: 3 tools (per-tool)
```

---

## Test 14: Connect Non-existent Server

```
/mcp connect nonexistent
```

**Expected:** Error - server not found in config

---

## Test 15: Double Connect (Already Connected)

```
/mcp connect test
```

**Expected:** Error - already connected

---

## Cleanup (Part 1)

```
/mcp disconnect test
```

---

# Part 2: HTTP Transport Tests

These tests use the HTTP transport (`url` config). Ensure HTTP server is running first.

---

## Test 16: Start HTTP Test Server

In a separate terminal:
```bash
python3 -m nexus3.mcp.test_server.http_server --port 9000
```

**Expected:**
```
MCP HTTP test server running on http://127.0.0.1:9000
Press Ctrl+C to stop
```

---

## Test 17: List Shows HTTP Server

Ensure config has `http-test` with URL:
```json
{"name": "http-test", "url": "http://127.0.0.1:9000"}
```

```
/mcp
```

**Expected:**
```
Configured:
  test [disconnected]
  http-test [disconnected]
```

---

## Test 18: Connect HTTP Server

```
/mcp connect http-test
```

**Expected prompt:** Same consent prompt as stdio

Choose `[1]` - Allow all

**Expected:**
```
Connected to 'http-test' (allow-all)
Tools available: echo, get_time, add
```

---

## Test 19: HTTP Tools Work Identically

```
Use mcp_http-test_echo to say "via http"
```

**Expected:** Returns "via http"

```
Use mcp_http-test_add to add 100 and 23
```

**Expected:** Returns "123"

```
Use mcp_http-test_get_time
```

**Expected:** Returns ISO timestamp

---

## Test 20: Multiple Transports Simultaneously

```
/mcp connect test
```

(Choose `[1]` - Allow all)

```
/mcp
```

**Expected:**
```
Connected: 2
  test: 3 tools (allow-all)
  http-test: 3 tools (allow-all)
```

```
/mcp tools
```

**Expected:** Shows 6 tools (3 from each server)

---

## Test 21: HTTP Per-Tool Mode

```
/mcp disconnect http-test
/mcp connect http-test
```

Choose `[2]` - Per-tool

```
Use mcp_http-test_echo to say "confirm me"
```

**Expected:** Same 4-option confirmation prompt as stdio

Choose `[2]` - Allow this tool always

```
Use mcp_http-test_echo to say "no prompt"
```

**Expected:** Executes without prompt

---

## Test 22: HTTP Server Not Running

Stop the HTTP server (Ctrl+C in the other terminal).

```
/mcp disconnect http-test
/mcp connect http-test
```

**Expected:** Connection error - unable to reach server

---

## Cleanup (Part 2)

```
/mcp disconnect test
/mcp disconnect http-test
```

Start HTTP server again if needed for further tests.

---

# Part 3: Edge Cases and Error Handling

---

## Test 23: Invalid URL in Config

Add to config:
```json
{"name": "bad-url", "url": "not-a-valid-url"}
```

```
/mcp connect bad-url
```

**Expected:** URL validation error

---

## Test 24: Session Allowances Persist

```
/mcp connect test
```

Choose `[2]` - Per-tool

```
Use mcp_test_echo to say "first"
```

Choose `[2]` - Allow this tool always

```
Use mcp_test_add to add 1 and 1
```

Choose `[3]` - Allow all from server

Now all tools should work without prompts:

```
Use mcp_test_echo to say "no prompt"
Use mcp_test_add to add 2 and 2
Use mcp_test_get_time
```

**Expected:** All execute immediately

---

## Test 25: Allowances Reset on Disconnect

```
/mcp disconnect test
/mcp connect test
```

Choose `[2]` - Per-tool

```
Use mcp_test_echo to say "should prompt"
```

**Expected:** Prompts again (allowances reset on disconnect)

---

## Test 26: Tool Definitions Refresh on Connect

```
/mcp disconnect test
```

Ask the agent to list available tools:
```
What tools do you have?
```

**Expected:** Should NOT list mcp_test_* tools

```
/mcp connect test
```

(Choose any allow option)

```
What tools do you have?
```

**Expected:** Should now list mcp_test_echo, mcp_test_add, mcp_test_get_time

---

## Cleanup (Part 3)

```
/mcp disconnect test
/quit
```

---

# Test Results

## Part 1: Core Permission Tests (Stdio)

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 1. SANDBOXED blocked | | |
| 2. List servers | | |
| 3. Connect - allow all | | |
| 4. Allow-all no prompts | | |
| 5. Connect - per-tool | | |
| 6. Per-tool - allow once | | |
| 7. Per-tool - allow tool always | | |
| 8. Per-tool - allow server | | |
| 9. Connect - deny | | |
| 10. YOLO no prompts | | |
| 11. List tools | | |
| 12. Disable tool | | |
| 13. Status shows mode | | |
| 14. Non-existent server | | |
| 15. Double connect | | |

## Part 2: HTTP Transport Tests

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 16. HTTP server starts | | |
| 17. List shows HTTP server | | |
| 18. Connect HTTP server | | |
| 19. HTTP tools work | | |
| 20. Multiple transports | | |
| 21. HTTP per-tool mode | | |
| 22. HTTP server not running | | |

## Part 3: Edge Cases

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 23. Invalid URL | | |
| 24. Allowances persist | | |
| 25. Allowances reset on disconnect | | |
| 26. Tool definitions refresh | | |

---

# Permission Flow Summary

```
Transport Selection (automatic):
  config.command → StdioTransport (subprocess)
  config.url     → HTTPTransport (HTTP POST)

Connection Consent (TRUSTED mode):
  [1] Allow all → No per-tool prompts
  [2] Per-tool  → Prompts for each tool call
  [3] Deny      → Connection cancelled

Per-Tool Confirmation (per-tool mode):
  [1] Allow once      → This call only
  [2] Allow tool      → This tool, rest of session
  [3] Allow server    → All tools from server, rest of session
  [4] Deny            → Tool call rejected

YOLO mode: All prompts skipped, auto-allow
SANDBOXED mode: MCP completely blocked
```

---

# Quick Smoke Test

Minimal test to verify MCP is working:

```bash
# Terminal 1: Start REPL
nexus

# In REPL:
/mcp connect test
# Choose [1] Allow all
# Type: Use mcp_test_add to calculate 40 + 2
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

# In REPL:
/mcp connect http-test
# Choose [1] Allow all
# Type: Use mcp_http-test_echo to say "hello"
# Expected: hello
/mcp disconnect http-test
/quit
```
