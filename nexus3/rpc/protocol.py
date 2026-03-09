"""JSON-RPC 2.0 protocol parsing and serialization."""

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from nexus3.core.errors import NexusError
from nexus3.rpc.schemas import (
    RpcRequestEnvelopeSchema,
    RpcResponseEnvelopeSchema,
)
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

    request_data = dict(data)

    # Preserve legacy behavior: explicitly reject positional params with dedicated message.
    raw_params = data.get("params")
    if isinstance(raw_params, list):
        raise ParseError("Positional params (array) not supported, use named params (object)")

    # Reject empty-string method explicitly with clear compatibility-preserving wording.
    raw_method = data.get("method")
    if isinstance(raw_method, str) and raw_method == "":
        raise ParseError("method must be a non-empty string")

    try:
        validated = RpcRequestEnvelopeSchema.model_validate(request_data, strict=True)
    except PydanticValidationError as e:
        errors = e.errors()
        if errors:
            err = errors[0]
            loc = err.get("loc", ())
            field = loc[0] if loc else None

            if field == "jsonrpc":
                raise ParseError(f"jsonrpc must be '2.0', got: {data.get('jsonrpc')!r}") from e

            if field == "method":
                raise ParseError(
                    f"method must be a string, got: {type(data.get('method')).__name__}"
                ) from e

            if field == "params":
                params = data.get("params")
                if isinstance(params, list):
                    raise ParseError(
                        "Positional params (array) not supported, use named params (object)"
                    ) from e
                raise ParseError(
                    f"params must be object or array, got: {type(params).__name__}"
                ) from e

            if field == "id":
                raise ParseError(
                    f"id must be string, number, or null, got: {type(data.get('id')).__name__}"
                ) from e

        raise ParseError("Invalid JSON-RPC request") from e

    return Request(
        jsonrpc=validated.jsonrpc,
        method=raw_method if isinstance(raw_method, str) else validated.method,
        params=validated.params,
        id=validated.id,
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

    try:
        validated = RpcResponseEnvelopeSchema.model_validate(data, strict=True)
    except PydanticValidationError as e:
        errors = e.errors()
        if errors:
            err = errors[0]
            loc = err.get("loc", ())
            field = loc[0] if loc else None
            message = str(err.get("msg", "Invalid JSON-RPC response"))

            if field == "jsonrpc":
                raise ParseError(f"jsonrpc must be '2.0', got: {data.get('jsonrpc')!r}") from e

            if field == "id":
                if "id" not in data:
                    raise ParseError("Response must have 'id' field") from e
                raise ParseError(
                    f"id must be string, number, or null, got: {type(data.get('id')).__name__}"
                ) from e

            if field == "error":
                error = data.get("error")
                if not isinstance(error, dict):
                    raise ParseError(
                        f"error must be an object, got: {type(error).__name__}"
                    ) from e
                nested_field = loc[1] if len(loc) > 1 else None
                error_type = str(err.get("type", ""))

                if nested_field in {"code", "message"} and error_type == "missing":
                    raise ParseError("error must have 'code' and 'message' fields") from e
                if nested_field is None:
                    raise ParseError("error must have 'code' and 'message' fields") from e
                raise ParseError("Invalid JSON-RPC response") from e

            if "response cannot have both 'result' and 'error'" in message:
                raise ParseError(message) from e
            if "response must have either 'result' or 'error'" in message:
                raise ParseError(message) from e

        raise ParseError("Invalid JSON-RPC response") from e

    return Response(
        jsonrpc=validated.jsonrpc,
        id=validated.id,
        result=validated.result,
        error=(
            validated.error.model_dump(exclude_none=True) if validated.error is not None else None
        ),
    )
