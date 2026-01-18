# MCP Live Test Suite

Manual test suite for verifying MCP functionality in REPL mode.

## Prerequisites

1. Start NEXUS3 in REPL mode:
   ```bash
   nexus3 --fresh
   ```

2. You need an MCP configuration. Create or verify `~/.nexus3/config.json` has:
   ```json
   {
     "mcp_servers": [
       {
         "name": "test-server",
         "command": [".venv/bin/python", "-m", "nexus3.mcp.test_server"],
         "enabled": true
       }
     ]
   }
   ```

## Test Cases

### Test 1: List MCP Servers (Disconnected State)

In REPL:
```
/mcp
```

**Expected:**
- Shows "MCP Servers" header
- Lists "test-server" as configured but NOT connected
- No errors

---

### Test 2: Connect to MCP Server

In REPL:
```
/mcp connect test-server --allow-all --shared
```

**Expected:**
- Server connects successfully
- Shows list of tools: `echo`, `get_time`, `add`
- No errors

---

### Test 3: List Connected MCP Servers

In REPL:
```
/mcp
```

**Expected:**
- Shows "test-server" as connected (with checkmark or similar)
- Shows tools count

---

### Test 4: List MCP Tools

In REPL:
```
/mcp tools test-server
```

**Expected:**
- Shows tool definitions for `echo`, `get_time`, `add`
- Shows parameters for each tool

---

### Test 5: Call MCP Tool via LLM

Send a message that will make the agent use an MCP tool:

```
Use the echo tool with the message "Hello MCP"
```

**Expected:**
- Agent calls `mcp_test-server_echo` tool
- Returns "Hello MCP"

---

### Test 6: Call Add Tool

```
Use the add tool to compute 42 + 58
```

**Expected:**
- Agent calls `mcp_test-server_add` tool
- Returns "100"

---

### Test 7: Call Get Time Tool

```
Use the get_time tool to get the current time
```

**Expected:**
- Agent calls `mcp_test-server_get_time` tool
- Returns ISO timestamp

---

### Test 8: Disconnect MCP Server

In REPL:
```
/mcp disconnect test-server
```

**Expected:**
- Server disconnects cleanly
- Confirms disconnection
- MCP tools no longer available

---

### Test 9: Verify Tools Removed After Disconnect

In REPL:
```
/mcp tools
```

**Expected:**
- Shows "No MCP tools available" or empty list
- test-server tools not shown

---

## RPC Mode Tests

### Test 10: Create Agent with MCP (Trusted)

```bash
# In terminal (outside REPL)
nexus3 rpc create mcp-tester --preset trusted
```

**Expected:**
- Agent created successfully

### Test 11: Test MCP Access from RPC Agent

```bash
nexus3 rpc send mcp-tester "List available MCP servers with /mcp"
```

**Expected:**
- Shows MCP server list (if MCP works in RPC mode)
- OR shows error about MCP not being available (if it doesn't)

### Test 12: Verify Sandboxed Agent Cannot Use MCP (P2.11)

```bash
# Create sandboxed agent
nexus3 rpc create sandboxed-test --preset sandboxed

# Try to use MCP
nexus3 rpc send sandboxed-test "List available MCP servers with /mcp"
```

**Expected:**
- Agent should report MCP access denied
- P2.11 deny-by-default should block MCP for sandboxed agents

---

## Security Tests (P2.9-12)

### Test 13: Verify Response ID Matching (P2.9)

This is tested automatically - if MCP calls work, response IDs are matching correctly.

### Test 14: Verify Notification Discarding (P2.10)

This is tested automatically - the test server doesn't send notifications, but the client code handles them.

### Test 15: Verify Deny-by-Default for None Permissions (P2.11)

```python
# In Python (for direct testing)
from nexus3.mcp.permissions import can_use_mcp
print(can_use_mcp(None))  # Should print False
```

### Test 16: Verify Line Length Limits (P2.12)

This is tested automatically - normal MCP messages are well under 10MB.

---

## Cleanup

```bash
# Clean up RPC agents
nexus3 rpc destroy mcp-tester
nexus3 rpc destroy sandboxed-test

# Exit REPL
/exit
```

---

## Expected Results Summary

| Test | Feature | Expected Outcome |
|------|---------|------------------|
| 1-9 | REPL MCP | All should pass |
| 10-12 | RPC MCP | May fail - RPC mode MCP may not work |
| 13-16 | Security P2.9-12 | All should pass |

If RPC mode MCP tests (10-12) fail, this confirms the need for further RPC+MCP integration work.
