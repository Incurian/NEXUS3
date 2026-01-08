"""JSON-RPC 2.0 protocol parsing and serialization."""

import json
from typing import Any

from nexus3.core.errors import NexusError
from nexus3.rpc.types import Request, Response


class ParseError(NexusError):
    """Raised when JSON-RPC request parsing fails."""


# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR = -32000  # Server error range: -32000 to -32099


def parse_request(line: str) -> Request:
    """Parse a JSON line into a JSON-RPC 2.0 Request.

    Args:
        line: A single line of JSON text.

    Returns:
        A parsed Request object.

    Raises:
        ParseError: If the JSON is invalid or required fields are missing.
    """
    # Parse JSON
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}") from e

    # Validate it's an object
    if not isinstance(data, dict):
        raise ParseError("Request must be a JSON object")

    # Validate jsonrpc version
    jsonrpc = data.get("jsonrpc")
    if jsonrpc != "2.0":
        raise ParseError(f"jsonrpc must be '2.0', got: {jsonrpc!r}")

    # Validate method
    method = data.get("method")
    if not isinstance(method, str):
        raise ParseError(f"method must be a string, got: {type(method).__name__}")

    # Validate params (optional, must be object or array if present)
    params = data.get("params")
    if params is not None and not isinstance(params, (dict, list)):
        raise ParseError(f"params must be object or array, got: {type(params).__name__}")

    # Normalize params to dict (arrays not supported for now)
    if isinstance(params, list):
        raise ParseError("Positional params (array) not supported, use named params (object)")

    # Get id (optional - None means notification)
    request_id = data.get("id")
    if request_id is not None and not isinstance(request_id, (str, int)):
        raise ParseError(f"id must be string, number, or null, got: {type(request_id).__name__}")

    return Request(
        jsonrpc=jsonrpc,
        method=method,
        params=params,
        id=request_id,
    )


def serialize_response(response: Response) -> str:
    """Serialize a Response to a JSON line.

    Args:
        response: The Response object to serialize.

    Returns:
        A single line of JSON text (no trailing newline).
    """
    data: dict[str, Any] = {
        "jsonrpc": response.jsonrpc,
        "id": response.id,
    }

    if response.error is not None:
        data["error"] = response.error
    else:
        data["result"] = response.result

    return json.dumps(data, separators=(",", ":"))


def make_error_response(
    request_id: str | int | None,
    code: int,
    message: str,
    data: Any = None,
) -> Response:
    """Create an error response.

    Args:
        request_id: The id from the original request.
        code: JSON-RPC error code.
        message: Human-readable error message.
        data: Optional additional error data.

    Returns:
        A Response with the error field populated.
    """
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if data is not None:
        error["data"] = data

    return Response(
        jsonrpc="2.0",
        id=request_id,
        error=error,
    )


def make_success_response(request_id: str | int | None, result: Any) -> Response:
    """Create a success response.

    Args:
        request_id: The id from the original request.
        result: The result of the method call.

    Returns:
        A Response with the result field populated.
    """
    return Response(
        jsonrpc="2.0",
        id=request_id,
        result=result,
    )


# === Client-side functions ===


def serialize_request(request: Request) -> str:
    """Serialize a Request to a JSON line.

    Args:
        request: The Request object to serialize.

    Returns:
        A single line of JSON text (no trailing newline).
    """
    data: dict[str, Any] = {
        "jsonrpc": request.jsonrpc,
        "method": request.method,
    }

    if request.params is not None:
        data["params"] = request.params

    if request.id is not None:
        data["id"] = request.id

    return json.dumps(data, separators=(",", ":"))


def parse_response(line: str) -> Response:
    """Parse a JSON line into a JSON-RPC 2.0 Response.

    Args:
        line: A single line of JSON text.

    Returns:
        A parsed Response object.

    Raises:
        ParseError: If the JSON is invalid or required fields are missing.
    """
    # Parse JSON
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}") from e

    # Validate it's an object
    if not isinstance(data, dict):
        raise ParseError("Response must be a JSON object")

    # Validate jsonrpc version
    jsonrpc = data.get("jsonrpc")
    if jsonrpc != "2.0":
        raise ParseError(f"jsonrpc must be '2.0', got: {jsonrpc!r}")

    # Get id (required in responses, can be null)
    if "id" not in data:
        raise ParseError("Response must have 'id' field")
    response_id = data.get("id")
    if response_id is not None and not isinstance(response_id, (str, int)):
        raise ParseError(f"id must be string, number, or null, got: {type(response_id).__name__}")

    # Must have either result or error, but not both
    has_result = "result" in data
    has_error = "error" in data

    if has_result and has_error:
        raise ParseError("Response cannot have both 'result' and 'error'")
    if not has_result and not has_error:
        raise ParseError("Response must have either 'result' or 'error'")

    # Validate error structure if present
    error = data.get("error")
    if error is not None:
        if not isinstance(error, dict):
            raise ParseError(f"error must be an object, got: {type(error).__name__}")
        if "code" not in error or "message" not in error:
            raise ParseError("error must have 'code' and 'message' fields")

    return Response(
        jsonrpc=jsonrpc,
        id=response_id,
        result=data.get("result"),
        error=error,
    )
