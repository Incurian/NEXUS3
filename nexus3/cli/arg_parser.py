"""Argument parsing for NEXUS3 CLI.

This module contains the command-line argument parsing logic extracted from repl.py.
"""

import argparse
from pathlib import Path


def add_api_key_arg(parser: argparse.ArgumentParser) -> None:
    """Add --api-key argument to a parser."""
    parser.add_argument(
        "--api-key",
        dest="api_key",
        help="API key for authentication (auto-discovers from env/files if not provided)",
    )


def add_port_arg(parser: argparse.ArgumentParser) -> None:
    """Add --port argument to a parser."""
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8765,
        help="Server port (default: 8765)",
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="nexus3",
        description="AI-powered CLI agent framework",
    )

    # Add subparsers for commands
    subparsers = parser.add_subparsers(dest="command")

    # ==========================================================================
    # RPC subcommand group - all programmatic operations
    # ==========================================================================
    rpc_parser = subparsers.add_parser(
        "rpc",
        help="JSON-RPC commands for programmatic access",
        description="Commands for programmatic interaction with NEXUS3 servers.",
    )
    rpc_subparsers = rpc_parser.add_subparsers(dest="rpc_command")

    # rpc detect - Check if server is running
    detect_parser = rpc_subparsers.add_parser(
        "detect",
        help="Check if a NEXUS3 server is running",
    )
    add_port_arg(detect_parser)

    # rpc list - List agents (requires running server)
    list_parser = rpc_subparsers.add_parser(
        "list",
        help="List all agents (requires running server)",
    )
    add_port_arg(list_parser)
    add_api_key_arg(list_parser)

    # rpc create - Create agent (requires running server)
    create_parser = rpc_subparsers.add_parser(
        "create",
        help="Create an agent (requires running server)",
    )
    create_parser.add_argument("agent_id", help="ID for the new agent")
    create_parser.add_argument(
        "--preset",
        choices=["trusted", "sandboxed", "worker"],
        default="sandboxed",
        help="Permission preset (default: sandboxed)"
    )
    create_parser.add_argument(
        "--cwd",
        help="Working directory / sandbox root for the agent"
    )
    create_parser.add_argument(
        "--write-path",
        action="append",
        dest="allowed_write_paths",
        metavar="PATH",
        help="Path where writes are allowed (can be repeated)"
    )
    create_parser.add_argument(
        "--model", "-m",
        metavar="NAME",
        help="Model name/alias to use (from config.models or full model ID)"
    )
    create_parser.add_argument(
        "--message", "-M",
        metavar="MSG",
        help="Initial message to send to agent immediately after creation"
    )
    create_parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=300.0,
        help="Request timeout in seconds for initial message (default: 300)"
    )
    add_port_arg(create_parser)
    add_api_key_arg(create_parser)

    # rpc destroy - Destroy agent
    destroy_parser = rpc_subparsers.add_parser(
        "destroy",
        help="Destroy an agent",
    )
    destroy_parser.add_argument("agent_id", help="ID of agent to destroy")
    add_port_arg(destroy_parser)
    add_api_key_arg(destroy_parser)

    # rpc send - Send message to agent
    send_parser = rpc_subparsers.add_parser(
        "send",
        help="Send message to an agent",
    )
    send_parser.add_argument("agent_id", help="Agent ID to send to")
    send_parser.add_argument("content", help="Message to send")
    send_parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=300.0,
        help="Request timeout in seconds (default: 300)",
    )
    add_port_arg(send_parser)
    add_api_key_arg(send_parser)

    # rpc cancel - Cancel request
    cancel_parser = rpc_subparsers.add_parser(
        "cancel",
        help="Cancel an in-progress request",
    )
    cancel_parser.add_argument("agent_id", help="Agent ID")
    cancel_parser.add_argument("request_id", help="Request ID to cancel")
    add_port_arg(cancel_parser)
    add_api_key_arg(cancel_parser)

    # rpc status - Get agent status
    status_parser = rpc_subparsers.add_parser(
        "status",
        help="Get agent status (tokens + context)",
    )
    status_parser.add_argument("agent_id", help="Agent ID")
    add_port_arg(status_parser)
    add_api_key_arg(status_parser)

    # rpc compact - Force context compaction
    compact_parser = rpc_subparsers.add_parser(
        "compact",
        help="Force context compaction to reclaim token space",
    )
    compact_parser.add_argument("agent_id", help="Agent ID")
    add_port_arg(compact_parser)
    add_api_key_arg(compact_parser)

    # rpc shutdown - Shutdown server
    shutdown_parser = rpc_subparsers.add_parser(
        "shutdown",
        help="Shutdown the server",
    )
    add_port_arg(shutdown_parser)
    add_api_key_arg(shutdown_parser)

    # ==========================================================================
    # Main mode flags (only apply when no subcommand)
    # ==========================================================================
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8765,
        type=int,
        metavar="PORT",
        help="Run HTTP JSON-RPC server (default port: 8765)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (thinking traces, timing)",
    )
    parser.add_argument(
        "--raw-log",
        action="store_true",
        help="Enable raw API JSON logging",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(".nexus3/logs"),
        help="Directory for session logs (default: .nexus3/logs)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on code changes (requires watchfiles, serve mode only)",
    )
    # Session startup flags (skip lobby)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume last session automatically (skip lobby)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start fresh temp session (skip lobby)",
    )
    parser.add_argument(
        "--session",
        metavar="NAME",
        help="Load specific saved session by name (skip lobby)",
    )
    parser.add_argument(
        "--template",
        metavar="PATH",
        type=Path,
        help="Custom system prompt file for fresh sessions (used with --fresh)",
    )
    parser.add_argument(
        "--model", "-m",
        metavar="NAME",
        help="Model name/alias to use (from config.models or full model ID)",
    )
    parser.add_argument(
        "--connect",
        metavar="URL",
        nargs="?",
        const="DISCOVER",
        default=None,
        help="Connect to a Nexus server (no URL = discover servers, URL = connect directly)",
    )
    parser.add_argument(
        "--agent",
        default="main",
        help="Agent ID to connect to (default: main, requires --connect)",
    )
    parser.add_argument(
        "--scan",
        metavar="PORTSPEC",
        help="Additional ports to scan for servers (e.g., '9000' or '8765,9000-9050')",
    )
    add_api_key_arg(parser)
    # Init commands
    parser.add_argument(
        "--init-global",
        action="store_true",
        help="Initialize ~/.nexus3/ with default configuration and exit",
    )
    parser.add_argument(
        "--init-global-force",
        action="store_true",
        help="Initialize ~/.nexus3/ and overwrite existing files",
    )
    return parser.parse_args()
