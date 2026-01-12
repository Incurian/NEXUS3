# MCP REPL Test Suite

Manual tests for MCP functionality in REPL mode.

## Prerequisites

1. Config has test server configured (already in defaults):
   ```json
   "mcp_servers": [
     {"name": "test", "command": ["python3", "-m", "nexus3.mcp.test_server"]}
   ]
   ```

2. Start REPL: `nexus`

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

## Test 3: Connect to Test Server

```
/mcp connect test
```

**Expected:**
```
Connected to 'test'
Tools available: echo, get_time, add
```

---

## Test 4: List MCP Tools

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

---

## Test 5: Verify Server Status

```
/mcp
```

**Expected:**
```
MCP Servers:

Configured:
  test [connected]

Connected: 1
  test: 3 tools (per-tool)
```

---

## Test 6: Agent Uses MCP Tools

Ask the agent to use each tool:

```
Use mcp_test_echo to echo "Hello MCP!"
```
**Expected:** Agent calls tool, returns "Hello MCP!"

```
Use mcp_test_add to calculate 17 + 25
```
**Expected:** Agent calls tool, returns "42"

```
What's the current time? Use mcp_test_get_time.
```
**Expected:** Agent calls tool, returns ISO timestamp

---

## Test 7: Disconnect Server

```
/mcp disconnect test
/mcp
```

**Expected:** Shows test as [disconnected], Connected: (none)

---

## Test 8: Tools Unavailable After Disconnect

```
Use mcp_test_echo to say hello
```

**Expected:** Agent reports tool not available / unknown skill

---

## Test 9: Reconnect Works

```
/mcp connect test
/mcp tools
```

**Expected:** All 3 tools available again

---

## Test 10: Disable Individual MCP Tool

```
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

**Expected:** Works - returns "still works"

---

## Test 11: Re-enable Tool

```
/permissions --enable mcp_test_add
Calculate 100 + 23 using mcp_test_add
```

**Expected:** Works - returns "123"

---

## Test 12: Connect Non-existent Server

```
/mcp connect nonexistent
```

**Expected:** Error - server not found in config

---

## Test 13: Double Connect (Already Connected)

```
/mcp connect test
```

**Expected:** Error - already connected

---

## Cleanup

```
/mcp disconnect test
/quit
```

---

## Test Results

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 1. SANDBOXED blocked | | |
| 2. List servers | | |
| 3. Connect | | |
| 4. List tools | | |
| 5. Status after connect | | |
| 6. Agent uses tools | | |
| 7. Disconnect | | |
| 8. Tools unavailable | | |
| 9. Reconnect | | |
| 10. Disable tool | | |
| 11. Re-enable tool | | |
| 12. Non-existent server | | |
| 13. Double connect | | |
