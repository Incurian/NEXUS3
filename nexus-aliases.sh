#!/bin/bash
# NEXUS3 aliases - minimal shell layer, all logic in Python CLI
#
# Usage:
#   nexus                    # REPL with embedded server
#   nexus --serve [PORT]     # Headless server
#   nexus --connect [URL]    # Connect to existing server
#
#   nexus-rpc detect         # Check if server running
#   nexus-rpc list           # List agents (auto-starts server)
#   nexus-rpc create ID      # Create agent (auto-starts server)
#   nexus-rpc destroy ID     # Destroy agent
#   nexus-rpc send AGENT MSG # Send message
#   nexus-rpc status AGENT   # Get agent status
#   nexus-rpc shutdown       # Stop server

NEXUS_ROOT="${NEXUS_ROOT:-/home/inc/repos/NEXUS3}"
NEXUS_PYTHON="${NEXUS_ROOT}/.venv/bin/python"

nexus() {
    cd "$NEXUS_ROOT" && exec "$NEXUS_PYTHON" -m nexus3 "$@"
}

nexus-rpc() {
    cd "$NEXUS_ROOT" && exec "$NEXUS_PYTHON" -m nexus3 rpc "$@"
}
