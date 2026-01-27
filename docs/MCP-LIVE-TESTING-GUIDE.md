# MCP Live Testing Guide

Manual testing procedures to validate MCP server connections, tools, resources, and prompts.

**Branch:** `feature/mcp-improvements`
**Date:** 2026-01-27

---

## Prerequisites

```bash
# Ensure you're on the right branch
git checkout feature/mcp-improvements

# Activate virtualenv
source .venv/bin/activate

# Verify tests pass first
.venv/bin/pytest tests/unit/mcp/ tests/integration/test_mcp*.py -v --tb=short
```

---

## Part 1: Test Server Validation

### 1.1 Stdio Server - Basic Protocol

Test the stdio server responds correctly to MCP protocol messages.

```bash
# Test initialization
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{},"resources":{"subscribe":false,"listChanged":false},"prompts":{"listChanged":false}},"serverInfo":{"name":"nexus3-test-server","version":"1.0.0"}}}
```

### 1.2 Stdio Server - Tools

```bash
# List tools
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: 4 tools (echo, get_time, add, slow_operation)

# Call echo tool
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"message":"Hello MCP!"}}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"Hello MCP!"}],"isError":false}}

# Call add tool
echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"add","arguments":{"a":17,"b":25}}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: result with text "42"
```

### 1.3 Stdio Server - Resources

```bash
# List resources
echo '{"jsonrpc":"2.0","id":1,"method":"resources/list"}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: 3 resources (readme.txt, config.json, users.csv)

# Read a resource
echo '{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"file:///readme.txt"}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: {"jsonrpc":"2.0","id":2,"result":{"contents":[{"uri":"file:///readme.txt","mimeType":"text/plain","text":"# Test Project\n\nThis is a test MCP server.\n"}]}}

# Read JSON resource
echo '{"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"file:///config.json"}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: mimeType "application/json", content with "test-server"
```

### 1.4 Stdio Server - Prompts

```bash
# List prompts
echo '{"jsonrpc":"2.0","id":1,"method":"prompts/list"}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: 3 prompts (greeting, code_review, summarize)

# Get greeting prompt
echo '{"jsonrpc":"2.0","id":2,"method":"prompts/get","params":{"name":"greeting","arguments":{"name":"Alice"}}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: messages array with "Alice" in the text

# Get prompt with formal flag
echo '{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{"name":"greeting","arguments":{"name":"Bob","formal":true}}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: "formal" appears in the generated text
```

### 1.5 Stdio Server - Ping

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: {"jsonrpc":"2.0","id":1,"result":{}}
```

### 1.6 Stdio Server - Error Handling

```bash
# Unknown method
echo '{"jsonrpc":"2.0","id":1,"method":"unknown/method"}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: error with code -32601

# Unknown tool
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"nonexistent","arguments":{}}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: error with code -32602

# Unknown resource
echo '{"jsonrpc":"2.0","id":1,"method":"resources/read","params":{"uri":"file:///nonexistent"}}' | .venv/bin/python -m nexus3.mcp.test_server

# Expected: error with code -32602
```

### 1.7 Paginating Server

```bash
# Test pagination with 5 tools, page size 2 (3 pages)
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | MCP_TOOL_COUNT=5 MCP_PAGE_SIZE=2 .venv/bin/python -m nexus3.mcp.test_server.paginating_server

# Expected: 2 tools + nextCursor="2"

# Get second page
echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"cursor":"2"}}' | MCP_TOOL_COUNT=5 MCP_PAGE_SIZE=2 .venv/bin/python -m nexus3.mcp.test_server.paginating_server

# Expected: 2 tools + nextCursor="4"

# Get last page
echo '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{"cursor":"4"}}' | MCP_TOOL_COUNT=5 MCP_PAGE_SIZE=2 .venv/bin/python -m nexus3.mcp.test_server.paginating_server

# Expected: 1 tool, NO nextCursor (last page)
```

---

## Part 2: HTTP Server Testing

### 2.1 Start HTTP Server

```bash
# In terminal 1: Start HTTP server
.venv/bin/python -m nexus3.mcp.test_server.http_server --port 9999

# Expected: "MCP HTTP test server running on http://127.0.0.1:9999"
```

### 2.2 Test HTTP Endpoints (in another terminal)

```bash
# Initialize
curl -X POST http://127.0.0.1:9999 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# List tools
curl -X POST http://127.0.0.1:9999 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# Call echo
curl -X POST http://127.0.0.1:9999 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"message":"HTTP test"}}}'

# List resources
curl -X POST http://127.0.0.1:9999 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"resources/list"}'

# List prompts
curl -X POST http://127.0.0.1:9999 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":5,"method":"prompts/list"}'

# Ping
curl -X POST http://127.0.0.1:9999 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":6,"method":"ping"}'
```

### 2.3 Stop HTTP Server

Press `Ctrl+C` in the HTTP server terminal.

---

## Part 3: REPL Integration Testing

### 3.1 Setup MCP Configuration

Create a test MCP config:

```bash
mkdir -p /tmp/mcp-test/.nexus3
cat > /tmp/mcp-test/.nexus3/mcp.json << 'EOF'
{
  "servers": {
    "test-stdio": {
      "command": [".venv/bin/python", "-m", "nexus3.mcp.test_server"],
      "description": "Test stdio server"
    },
    "test-paginating": {
      "command": [".venv/bin/python", "-m", "nexus3.mcp.test_server.paginating_server"],
      "env": {
        "MCP_TOOL_COUNT": "7",
        "MCP_PAGE_SIZE": "3"
      },
      "description": "Paginating test server"
    }
  }
}
EOF
```

### 3.2 Start NEXUS3 REPL

```bash
cd /tmp/mcp-test
nexus3 --fresh
```

### 3.3 Test MCP Commands in REPL

```
# List configured servers (should show test-stdio and test-paginating)
/mcp

# Connect to test server
/mcp connect test-stdio

# List tools (should show 4 tools: mcp_test-stdio_echo, etc.)
/mcp tools

# List resources (should show 3 resources)
/mcp resources

# List prompts (should show 3 prompts)
/mcp prompts

# Connect to paginating server
/mcp connect test-paginating

# List tools from paginating server (should show 7 tools despite pagination)
/mcp tools test-paginating

# Disconnect
/mcp disconnect test-stdio
/mcp disconnect test-paginating

# Verify disconnected
/mcp
```

### 3.4 Test Tool Execution via Agent

In the REPL, ask the agent to use an MCP tool:

```
# After connecting test-stdio:
/mcp connect test-stdio

# Ask the agent to use the echo tool
Use the mcp_test-stdio_echo tool to echo "Hello from NEXUS3"

# Ask the agent to use the add tool
Use the mcp_test-stdio_add tool to add 123 and 456

# Ask the agent to get the current time
Use the mcp_test-stdio_get_time tool
```

### 3.5 Test Retry Command

```
# Connect, then simulate a stale connection scenario
/mcp connect test-stdio

# Retry tool listing (useful if initial listing failed)
/mcp retry test-stdio

# Should show "Tools refreshed" or similar success message
```

---

## Part 4: Python API Testing

### 4.1 Interactive Python Test

```bash
.venv/bin/python
```

```python
import asyncio
from nexus3.mcp import MCPClient, MCPServerConfig, MCPServerRegistry
from nexus3.mcp.transport import StdioTransport
import sys

async def test_client():
    # Create transport and client
    transport = StdioTransport([sys.executable, "-m", "nexus3.mcp.test_server"])

    async with MCPClient(transport) as client:
        print(f"Connected: {client.is_connected}")
        print(f"Server: {client.server_info.name}")

        # Test tools
        tools = await client.list_tools()
        print(f"Tools: {[t.name for t in tools]}")

        # Test resources
        resources = await client.list_resources()
        print(f"Resources: {[r.uri for r in resources]}")

        # Test prompts
        prompts = await client.list_prompts()
        print(f"Prompts: {[p.name for p in prompts]}")

        # Test ping
        latency = await client.ping()
        print(f"Ping latency: {latency:.2f}ms")

        # Call a tool
        result = await client.call_tool("echo", {"message": "Python API test"})
        print(f"Echo result: {result.to_text()}")

        # Read a resource
        contents = await client.read_resource("file:///config.json")
        print(f"Config content: {contents[0].text[:50]}...")

        # Get a prompt
        prompt_result = await client.get_prompt("greeting", {"name": "Tester"})
        print(f"Prompt message: {prompt_result.messages[0].get_text()[:50]}...")

asyncio.run(test_client())
```

### 4.2 Registry Test

```python
import asyncio
from nexus3.mcp import MCPServerConfig, MCPServerRegistry
import sys

async def test_registry():
    registry = MCPServerRegistry()

    config = MCPServerConfig(
        name="test",
        command=[sys.executable, "-m", "nexus3.mcp.test_server"],
    )

    # Connect
    server = await registry.connect(config)
    print(f"Connected to: {server.config.name}")
    print(f"Skills: {len(server.skills)}")

    # Get all skills
    skills = await registry.get_all_skills()
    print(f"Skill names: {[s.name for s in skills]}")

    # Execute a skill
    echo_skill = next(s for s in skills if "echo" in s.name)
    result = await echo_skill.execute(message="Registry test")
    print(f"Skill result: {result.output}")

    # Cleanup
    await registry.close_all()
    print("Registry closed")

asyncio.run(test_registry())
```

---

## Part 5: Error Scenario Testing

### 5.1 Command Not Found Error

```bash
# Try to connect to non-existent command
.venv/bin/python -c "
import asyncio
from nexus3.mcp import MCPServerConfig, MCPServerRegistry

async def test():
    registry = MCPServerRegistry()
    config = MCPServerConfig(name='bad', command=['nonexistent_command_xyz'])
    try:
        await registry.connect(config)
    except Exception as e:
        print(f'Error type: {type(e).__name__}')
        print(f'Message: {e}')

asyncio.run(test())
"

# Expected: Formatted error message with "Command not found" and troubleshooting hints
```

### 5.2 Connection Timeout

```bash
# Create a server that hangs during initialization
.venv/bin/python -c "
import asyncio
from nexus3.mcp import MCPClient
from nexus3.mcp.transport import StdioTransport

async def test():
    # This will hang because 'cat' doesn't respond to MCP protocol
    transport = StdioTransport(['cat'])
    client = MCPClient(transport)
    try:
        await client.connect(timeout=2.0)  # 2 second timeout
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())
"

# Expected: "MCP connection timed out after 2.0s"
```

### 5.3 Invalid JSON Response

```bash
# Server that returns invalid JSON
.venv/bin/python -c "
import asyncio
from nexus3.mcp.transport import StdioTransport, MCPTransportError

async def test():
    # echo will just echo back our input, not valid MCP
    transport = StdioTransport(['echo', 'not json'])
    try:
        await transport.connect()
        await transport.send({'jsonrpc': '2.0', 'id': 1, 'method': 'test'})
        response = await transport.receive()
    except MCPTransportError as e:
        print(f'Transport error: {e}')
    finally:
        await transport.close()

asyncio.run(test())
"
```

---

## Part 6: Security Validation

### 6.1 Environment Isolation

```bash
# Verify MCP servers don't receive sensitive env vars
export SECRET_API_KEY="super-secret-value"

.venv/bin/python -c "
import asyncio
import os
from nexus3.mcp.transport import StdioTransport

async def test():
    # Create transport - it should NOT pass SECRET_API_KEY
    transport = StdioTransport(['env'])
    await transport.connect()

    # Read stdout (env output)
    import asyncio
    await asyncio.sleep(0.5)

    # The subprocess 'env' will print its environment
    # SECRET_API_KEY should NOT be in the output

asyncio.run(test())
"

# Verify by checking the env command output doesn't contain SECRET_API_KEY
```

### 6.2 Response ID Matching

```bash
# This is tested automatically, but you can verify the security check exists:
grep -n "Response ID mismatch" nexus3/mcp/client.py

# Expected: Line showing the security check
```

---

## Part 7: Checklist

Use this checklist to track your testing:

### Test Servers
- [ ] Stdio server responds to initialize
- [ ] Stdio server lists 4 tools
- [ ] Stdio server executes echo tool
- [ ] Stdio server executes add tool
- [ ] Stdio server lists 3 resources
- [ ] Stdio server reads resources correctly
- [ ] Stdio server lists 3 prompts
- [ ] Stdio server gets prompts with arguments
- [ ] Stdio server responds to ping
- [ ] Stdio server returns proper errors for unknown methods
- [ ] Paginating server paginates correctly (multiple pages)
- [ ] HTTP server responds to all methods via curl

### REPL Integration
- [ ] `/mcp` shows configured servers
- [ ] `/mcp connect` connects to stdio server
- [ ] `/mcp tools` lists tools from connected server
- [ ] `/mcp resources` lists resources
- [ ] `/mcp prompts` lists prompts
- [ ] `/mcp disconnect` disconnects cleanly
- [ ] `/mcp retry` refreshes tools
- [ ] Agent can execute MCP tools when asked

### Python API
- [ ] MCPClient connects and initializes
- [ ] list_tools() returns tools
- [ ] list_resources() returns resources
- [ ] list_prompts() returns prompts
- [ ] call_tool() executes tools
- [ ] read_resource() reads content
- [ ] get_prompt() gets prompt with arguments
- [ ] ping() returns latency
- [ ] MCPServerRegistry manages connections
- [ ] Skills execute through registry

### Error Handling
- [ ] Command not found produces helpful error
- [ ] Connection timeout works (2s test)
- [ ] Invalid responses handled gracefully

### Security
- [ ] Sensitive env vars not passed to MCP servers
- [ ] Response ID matching is enforced

---

## Troubleshooting

### Server won't start
```bash
# Check if the module is importable
.venv/bin/python -c "from nexus3.mcp.test_server import server; print('OK')"
```

### Connection hangs
```bash
# Test with verbose logging
NEXUS_LOG_LEVEL=DEBUG .venv/bin/python -c "..."
```

### REPL doesn't see MCP config
```bash
# Verify config file location and syntax
cat .nexus3/mcp.json | python -m json.tool
```

### Tools not appearing
```bash
# Check if server lists tools correctly in isolation first
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | .venv/bin/python -m nexus3.mcp.test_server
```
