"""JSON-RPC 2.0 support for NEXUS3 HTTP server mode.

This module provides JSON-RPC 2.0 protocol support for programmatic control
of NEXUS3 via HTTP. It enables automation, multi-turn conversations, and
integration with external tools.

Example usage:
    python -m nexus3 --serve  # Start HTTP server on port 8765
    curl -X POST http://localhost:8765/rpc \\
        -d '{"jsonrpc":"2.0","method":"send","params":{"content":"Hi"},"id":1}'
"""

from nexus3.rpc.auth import (
    API_KEY_PREFIX,
    ServerKeyManager,
    discover_api_key,
    generate_api_key,
    validate_api_key,
)
from nexus3.rpc.detection import DetectionResult, detect_server, wait_for_server
from nexus3.rpc.dispatcher import Dispatcher, InvalidParamsError
from nexus3.rpc.http import (
    BIND_HOST,
    DEFAULT_PORT,
    MAX_BODY_SIZE,
    HttpParseError,
    HttpRequest,
    handle_connection,
    read_http_request,
    run_http_server,
    send_http_response,
)
from nexus3.rpc.pool import Agent, AgentConfig, AgentPool, SharedComponents
from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_ERROR,
    ParseError,
    make_error_response,
    make_success_response,
    parse_request,
    parse_response,
    serialize_request,
    serialize_response,
)
from nexus3.rpc.types import Request, Response

__all__ = [
    # Types
    "Request",
    "Response",
    "HttpRequest",
    # Protocol functions (server-side)
    "parse_request",
    "serialize_response",
    "make_error_response",
    "make_success_response",
    # Protocol functions (client-side)
    "serialize_request",
    "parse_response",
    # HTTP server
    "run_http_server",
    "handle_connection",
    "read_http_request",
    "send_http_response",
    "DEFAULT_PORT",
    "MAX_BODY_SIZE",
    "BIND_HOST",
    # Error codes
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "SERVER_ERROR",
    # Dispatcher
    "Dispatcher",
    # Exceptions
    "ParseError",
    "InvalidParamsError",
    "HttpParseError",
    # Agent Pool
    "Agent",
    "AgentConfig",
    "AgentPool",
    "SharedComponents",
    # Authentication
    "API_KEY_PREFIX",
    "generate_api_key",
    "validate_api_key",
    "ServerKeyManager",
    "discover_api_key",
    # Detection
    "DetectionResult",
    "detect_server",
    "wait_for_server",
]
