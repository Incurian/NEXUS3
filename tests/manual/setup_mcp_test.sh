#!/bin/bash
# Setup script for MCP live testing
# Run from NEXUS3 project root

set -e

echo "=== MCP Live Test Setup ==="
echo ""

# Check config exists
CONFIG_FILE="$HOME/.nexus3/config.json"

if [ -f "$CONFIG_FILE" ]; then
    echo "Found existing config at $CONFIG_FILE"

    # Check if mcp_servers is configured
    if grep -q "mcp_servers" "$CONFIG_FILE"; then
        echo "MCP servers already configured."
    else
        echo "WARNING: No mcp_servers in config. You may need to add:"
        echo ""
        echo '  "mcp_servers": ['
        echo '    {'
        echo '      "name": "test-server",'
        echo '      "command": [".venv/bin/python", "-m", "nexus3.mcp.test_server"],'
        echo '      "enabled": true'
        echo '    }'
        echo '  ]'
        echo ""
    fi
else
    echo "No config file found. Creating minimal config..."
    mkdir -p "$HOME/.nexus3"
    cat > "$CONFIG_FILE" << 'EOF'
{
  "mcp_servers": [
    {
      "name": "test-server",
      "command": [".venv/bin/python", "-m", "nexus3.mcp.test_server"],
      "enabled": true
    }
  ]
}
EOF
    echo "Created $CONFIG_FILE with test server configuration"
fi

echo ""
echo "=== Quick MCP Test ==="
echo ""

# Test that the MCP test server starts correctly
echo "Testing MCP test server startup..."
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | \
    timeout 5 .venv/bin/python -m nexus3.mcp.test_server 2>/dev/null | head -1

echo ""
echo "MCP test server works!"
echo ""

# Print P2.11 status
echo "=== P2.11 Deny-by-Default Test ==="
.venv/bin/python -c "
from nexus3.mcp.permissions import can_use_mcp
result = can_use_mcp(None)
print(f'can_use_mcp(None) = {result}')
print(f'Expected: False (P2.11 deny-by-default)')
print(f'Status: {\"PASS\" if result == False else \"FAIL\"}')"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To run REPL MCP tests:"
echo "  1. Start REPL: nexus --fresh"
echo "  2. Run: /mcp"
echo "  3. Run: /mcp connect test-server --allow-all --shared"
echo "  4. Run: /mcp tools test-server"
echo "  5. Ask: Use the echo tool with message 'test'"
echo ""
echo "See tests/manual/mcp_live_test.md for full test guide."
