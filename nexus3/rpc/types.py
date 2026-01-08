"""JSON-RPC 2.0 types for NEXUS3 headless mode."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Request:
    """JSON-RPC 2.0 request.

    Attributes:
        jsonrpc: Protocol version, must be "2.0".
        method: Name of the method to invoke.
        params: Optional parameters for the method.
        id: Request identifier. None means notification (no response expected).
    """

    jsonrpc: str
    method: str
    params: dict[str, Any] | None = None
    id: str | int | None = None


@dataclass
class Response:
    """JSON-RPC 2.0 response.

    Attributes:
        jsonrpc: Protocol version, always "2.0".
        id: Request identifier from the original request.
        result: Result of the method call (mutually exclusive with error).
        error: Error object if method failed (mutually exclusive with result).
    """

    jsonrpc: str
    id: str | int | None
    result: Any | None = None
    error: dict[str, Any] | None = None
