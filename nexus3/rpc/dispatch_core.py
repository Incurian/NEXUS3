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
from typing import Any

from nexus3.core.errors import NexusError
from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    make_error_response,
    make_success_response,
)
from nexus3.rpc.types import Request, Response

logger = logging.getLogger(__name__)

# Type alias for handler functions
Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class InvalidParamsError(NexusError):
    """Raised when method parameters are invalid."""


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
