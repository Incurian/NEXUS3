"""Shared dispatch infrastructure for JSON-RPC dispatchers.

This module provides common functionality shared between Dispatcher (agent-specific)
and GlobalDispatcher (agent lifecycle management). The dispatch_request() function
handles the common pattern of:
- Handler lookup
- Success/error response generation
- Exception handling with proper error codes
- Notification handling (requests without id)

This eliminates code duplication and ensures consistent error handling across
both dispatcher types.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from pydantic import ValidationError as PydanticValidationError

from nexus3.core.capabilities import (
    CapabilityClaims,
    CapabilityError,
    direct_rpc_scope_for_method,
)
from nexus3.core.errors import NexusError
from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    make_error_response,
    make_success_response,
)
from nexus3.rpc.schemas import RpcRequestEnvelopeSchema
from nexus3.rpc.types import Request, Response

logger = logging.getLogger(__name__)

# Type alias for handler functions
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""


class DirectCapabilityVerifier(Protocol):
    """Capability verification contract used by dispatchers."""

    def verify_direct_capability(
        self,
        token: str,
        *,
        required_scope: str,
    ) -> CapabilityClaims:
        """Verify token and enforce required scope."""


def resolve_dispatch_identity(
    *,
    method: str,
    requester_id: str | None,
    capability_token: str | None,
    verifier: DirectCapabilityVerifier | None,
) -> tuple[str | None, CapabilityClaims | None]:
    """Resolve effective requester identity for a dispatch call.

    When a capability token is supplied for a known RPC method, this verifies
    scope and returns the subject identity from verified claims.
    """
    if capability_token is None:
        return requester_id, None

    required_scope = direct_rpc_scope_for_method(method)
    if required_scope is None:
        # Preserve existing unknown-method behavior (method-not-found).
        return requester_id, None

    if verifier is None:
        raise InvalidParamsError("Capability verification unavailable for this dispatcher")

    try:
        claims = verifier.verify_direct_capability(
            capability_token,
            required_scope=required_scope,
        )
    except CapabilityError as exc:
        raise InvalidParamsError(f"Invalid capability token: {exc}") from exc

    if requester_id is not None and requester_id != claims.subject_id:
        raise InvalidParamsError("requester_id does not match capability subject")

    return claims.subject_id, claims


def validate_direct_request_envelope(request: Request) -> None:
    """Validate an in-process Request object with JSON-RPC ingress rules.

    Direct dispatcher callers bypass `parse_request()`, so this reproduces the
    same strict envelope checks and compatibility-preserving error wording.
    """
    request_data: dict[str, Any] = {
        "jsonrpc": request.jsonrpc,
        "method": request.method,
        "id": request.id,
    }
    if request.params is not None:
        request_data["params"] = request.params

    if isinstance(request.params, list):
        raise InvalidParamsError(
            "Positional params (array) not supported, use named params (object)"
        )
    if isinstance(request.method, str) and request.method == "":
        raise InvalidParamsError("method must be a non-empty string")

    try:
        RpcRequestEnvelopeSchema.model_validate(request_data, strict=True)
    except PydanticValidationError as exc:
        errors = exc.errors()
        if errors:
            error = errors[0]
            loc = error.get("loc", ())
            field = loc[0] if loc else None

            if field == "jsonrpc":
                raise InvalidParamsError(
                    f"jsonrpc must be '2.0', got: {request.jsonrpc!r}"
                ) from exc

            if field == "method":
                raise InvalidParamsError(
                    f"method must be a string, got: {type(request.method).__name__}"
                ) from exc

            if field == "params":
                if isinstance(request.params, list):
                    raise InvalidParamsError(
                        "Positional params (array) not supported, "
                        "use named params (object)"
                    ) from exc
                if (
                    len(loc) > 2
                    and loc[2] == "[key]"
                    and isinstance(loc[1], (str, int, float, bool))
                ):
                    raise InvalidParamsError(
                        f"params keys must be strings, got: {type(loc[1]).__name__}"
                    ) from exc
                raise InvalidParamsError(
                    "params must be object or array, "
                    f"got: {type(request.params).__name__}"
                ) from exc

            if field == "id":
                raise InvalidParamsError(
                    "id must be string, number, or null, "
                    f"got: {type(request.id).__name__}"
                ) from exc

        raise InvalidParamsError("Invalid JSON-RPC request") from exc


async def dispatch_request(
    request: Request,
    handlers: dict[str, Handler],
    log_context: str,
) -> Response | None:
    """Dispatch a request to the appropriate handler.

    This is the shared dispatch logic used by both Dispatcher and GlobalDispatcher.
    It handles method lookup, success/error response generation, and exception
    handling with proper JSON-RPC error codes.

    Args:
        request: The parsed JSON-RPC request.
        handlers: Mapping of method names to handler coroutines.
        log_context: Context string for log messages (e.g., "method", "global method").

    Returns:
        A Response object, or None for notifications (requests without id).
    """
    # Look up handler
    handler = handlers.get(request.method)
    if handler is None:
        # Method not found
        if request.id is None:
            return None  # Notifications don't get error responses
        return make_error_response(
            request.id,
            METHOD_NOT_FOUND,
            f"Method not found: {request.method}",
        )

    # Execute handler
    try:
        params = request.params or {}
        result = await handler(params)

        # Return response (None for notifications)
        if request.id is None:
            return None
        return make_success_response(request.id, result)

    except InvalidParamsError as e:
        if request.id is None:
            return None
        return make_error_response(request.id, INVALID_PARAMS, str(e))

    except NexusError as e:
        if request.id is None:
            return None
        return make_error_response(request.id, INTERNAL_ERROR, e.message)

    except PermissionError as e:
        if request.id is None:
            return None
        return make_error_response(request.id, INVALID_PARAMS, str(e))

    except Exception as e:
        logger.error(
            "Unexpected error dispatching %s '%s': %s",
            log_context,
            request.method,
            e,
            exc_info=True,
        )
        if request.id is None:
            return None
        return make_error_response(
            request.id,
            INTERNAL_ERROR,
            f"Internal error: {type(e).__name__}: {e}",
        )
