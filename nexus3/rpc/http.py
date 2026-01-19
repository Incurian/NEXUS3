"""Pure asyncio HTTP server for JSON-RPC 2.0 requests.

This module provides a minimal HTTP server that accepts JSON-RPC 2.0 requests
over HTTP POST. It uses only asyncio stdlib - no external dependencies.

Security:
    - The server binds only to localhost (127.0.0.1) and never to 0.0.0.0.
    - API key authentication via Authorization: Bearer <key> header.

Path-based routing:
    - POST / or /rpc → GlobalDispatcher (agent management)
    - POST /agent/{agent_id} → Agent's Dispatcher

Cross-Session Auto-Restore:
    When a request targets an agent_id that is not in the active pool but
    exists as a saved session, the server automatically restores the session.

Example usage:
    pool = AgentPool()
    global_dispatcher = GlobalDispatcher(pool)
    session_manager = SessionManager()
    api_key = generate_api_key()
    await run_http_server(pool, global_dispatcher, port=8765, api_key=api_key,
                          session_manager=session_manager)
"""

from __future__ import annotations

import asyncio
import json
import logging
import string
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from nexus3.core.errors import NexusError
from nexus3.core.validation import is_valid_agent_id
from nexus3.rpc.auth import validate_api_key
from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    PARSE_ERROR,
    ParseError,
    make_error_response,
    parse_request,
    serialize_response,
)

if TYPE_CHECKING:
    from typing import Protocol

    from nexus3.rpc.event_hub import EventHub

    from nexus3.session.persistence import SavedSession

    class Dispatcher(Protocol):
        """Protocol for dispatchers that handle JSON-RPC requests."""

        async def dispatch(self, request: Request) -> Response | None: ...

    class GlobalDispatcher(Dispatcher, Protocol):
        """Protocol for the global dispatcher that manages agents."""

        pass

    class AgentPool(Protocol):
        """Protocol for the agent pool."""

        @property
        def should_shutdown(self) -> bool: ...

        def get(self, agent_id: str) -> Agent | None: ...

        async def get_or_restore(
            self,
            agent_id: str,
            session_manager: SessionManager | None = None,
        ) -> Agent | None: ...

        async def restore_from_saved(self, saved: SavedSession) -> Agent: ...

    class Agent(Protocol):
        """Protocol for an agent with a dispatcher."""

        @property
        def dispatcher(self) -> Dispatcher: ...

    class SessionManager(Protocol):
        """Protocol for the session manager."""

        def session_exists(self, name: str) -> bool: ...

        def load_session(self, name: str) -> SavedSession: ...

    from nexus3.rpc.protocol import Request, Response

# Constants
DEFAULT_PORT = 8765
MAX_BODY_SIZE = 1_048_576  # 1MB
BIND_HOST = "127.0.0.1"  # Localhost only - NEVER bind to 0.0.0.0

# HTTP header limits (DoS protection)
MAX_HEADERS_COUNT = 128  # Max number of headers
MAX_HEADER_NAME_LEN = 1024  # Max header name length (bytes)
MAX_HEADER_VALUE_LEN = 8192  # Max header value length (bytes)
MAX_TOTAL_HEADERS_SIZE = 32 * 1024  # 32KB total header size limit
MAX_REQUEST_LINE_LEN = 8192  # Max request line length


@dataclass
class HttpRequest:
    """Parsed HTTP request.

    Attributes:
        method: HTTP method (GET, POST, etc.)
        path: Request path (e.g., "/rpc")
        headers: Dict of lowercase header names to values
        body: Request body as string
    """

    method: str
    path: str
    headers: dict[str, str]
    body: str


class HttpParseError(NexusError):
    """Raised when HTTP request parsing fails."""


async def read_http_request(reader: asyncio.StreamReader) -> HttpRequest:
    """Read and parse an HTTP request from the stream.

    Args:
        reader: The asyncio StreamReader to read from.

    Returns:
        Parsed HttpRequest object.

    Raises:
        HttpParseError: If the request is malformed or too large.
    """
    # Read request line
    try:
        request_line = await asyncio.wait_for(
            reader.readline(),
            timeout=30.0,
        )
    except TimeoutError:
        raise HttpParseError("Request timeout") from None

    if not request_line:
        raise HttpParseError("Empty request")

    # Check request line length (DoS protection)
    if len(request_line) > MAX_REQUEST_LINE_LEN:
        raise HttpParseError(f"Request line too long: {len(request_line)} > {MAX_REQUEST_LINE_LEN}")

    # Parse request line: "POST /rpc HTTP/1.1\r\n"
    try:
        request_line_str = request_line.decode("utf-8").strip()
        parts = request_line_str.split(" ")
        if len(parts) != 3:
            raise HttpParseError(f"Invalid request line: {request_line_str}")
        method, path, _version = parts
    except UnicodeDecodeError as e:
        raise HttpParseError(f"Invalid request encoding: {e}") from e

    # Read headers (with DoS protection limits)
    headers: dict[str, str] = {}
    total_headers_size = 0

    while True:
        try:
            header_line = await asyncio.wait_for(
                reader.readline(),
                timeout=30.0,
            )
        except TimeoutError:
            raise HttpParseError("Header read timeout") from None

        if not header_line or header_line == b"\r\n" or header_line == b"\n":
            break  # End of headers

        # Track total headers size
        total_headers_size += len(header_line)
        if total_headers_size > MAX_TOTAL_HEADERS_SIZE:
            raise HttpParseError(
                f"Total headers size exceeds limit: {total_headers_size} > {MAX_TOTAL_HEADERS_SIZE}"
            )

        try:
            header_str = header_line.decode("utf-8").strip()
        except UnicodeDecodeError as e:
            raise HttpParseError(f"Invalid header encoding: {e}") from e

        if ":" not in header_str:
            continue  # Skip malformed headers

        name, value = header_str.split(":", 1)
        name = name.strip()
        value = value.strip()

        # Check header name length
        if len(name) > MAX_HEADER_NAME_LEN:
            raise HttpParseError(
                f"Header name too long: {len(name)} > {MAX_HEADER_NAME_LEN}"
            )

        # Check header value length
        if len(value) > MAX_HEADER_VALUE_LEN:
            raise HttpParseError(
                f"Header value too long: {len(value)} > {MAX_HEADER_VALUE_LEN}"
            )

        # Check header count
        if len(headers) >= MAX_HEADERS_COUNT:
            raise HttpParseError(
                f"Too many headers: exceeds limit of {MAX_HEADERS_COUNT}"
            )

        headers[name.lower()] = value

    # Read body based on Content-Length
    body = ""
    content_length_str = headers.get("content-length", "0")
    try:
        content_length = int(content_length_str)
    except ValueError as e:
        raise HttpParseError(f"Invalid Content-Length: {content_length_str}") from e

    if content_length > MAX_BODY_SIZE:
        raise HttpParseError(
            f"Request body too large: {content_length} > {MAX_BODY_SIZE}"
        )

    if content_length > 0:
        try:
            body_bytes = await asyncio.wait_for(
                reader.readexactly(content_length),
                timeout=30.0,
            )
            body = body_bytes.decode("utf-8")
        except TimeoutError:
            raise HttpParseError("Body read timeout") from None
        except asyncio.IncompleteReadError as e:
            raise HttpParseError(
                f"Incomplete body: expected {content_length}, got {len(e.partial)}"
            ) from e
        except UnicodeDecodeError as e:
            raise HttpParseError(f"Invalid body encoding: {e}") from e

    return HttpRequest(
        method=method,
        path=path,
        headers=headers,
        body=body,
    )


async def read_http_request_headers(
    reader: asyncio.StreamReader,
) -> tuple[str, str, dict[str, str]]:
    """Read only request line and headers (not body).

    This is safe to call outside the semaphore since headers are bounded
    by MAX_TOTAL_HEADERS_SIZE. Used for two-stage parsing where we need
    to detect SSE requests before acquiring the connection semaphore.

    Args:
        reader: The asyncio StreamReader to read from.

    Returns:
        Tuple of (method, path, headers).

    Raises:
        HttpParseError: If the request line or headers are malformed.
    """
    # Read request line
    try:
        request_line = await asyncio.wait_for(
            reader.readline(),
            timeout=30.0,
        )
    except TimeoutError:
        raise HttpParseError("Request timeout") from None

    if not request_line:
        raise HttpParseError("Empty request")

    # Check request line length (DoS protection)
    if len(request_line) > MAX_REQUEST_LINE_LEN:
        raise HttpParseError(f"Request line too long: {len(request_line)} > {MAX_REQUEST_LINE_LEN}")

    # Parse request line: "GET /agent/test/events HTTP/1.1\r\n"
    try:
        request_line_str = request_line.decode("utf-8").strip()
        parts = request_line_str.split(" ")
        if len(parts) != 3:
            raise HttpParseError(f"Invalid request line: {request_line_str}")
        method, path, _version = parts
    except UnicodeDecodeError as e:
        raise HttpParseError(f"Invalid request encoding: {e}") from e

    # Read headers (with DoS protection limits)
    headers: dict[str, str] = {}
    total_headers_size = 0

    while True:
        try:
            header_line = await asyncio.wait_for(
                reader.readline(),
                timeout=30.0,
            )
        except TimeoutError:
            raise HttpParseError("Header read timeout") from None

        if not header_line or header_line == b"\r\n" or header_line == b"\n":
            break  # End of headers

        # Track total headers size
        total_headers_size += len(header_line)
        if total_headers_size > MAX_TOTAL_HEADERS_SIZE:
            raise HttpParseError(
                f"Total headers size exceeds limit: {total_headers_size} > {MAX_TOTAL_HEADERS_SIZE}"
            )

        try:
            header_str = header_line.decode("utf-8").strip()
        except UnicodeDecodeError as e:
            raise HttpParseError(f"Invalid header encoding: {e}") from e

        if ":" not in header_str:
            continue  # Skip malformed headers

        name, value = header_str.split(":", 1)
        name = name.strip()
        value = value.strip()

        # Check header name length
        if len(name) > MAX_HEADER_NAME_LEN:
            raise HttpParseError(
                f"Header name too long: {len(name)} > {MAX_HEADER_NAME_LEN}"
            )

        # Check header value length
        if len(value) > MAX_HEADER_VALUE_LEN:
            raise HttpParseError(
                f"Header value too long: {len(value)} > {MAX_HEADER_VALUE_LEN}"
            )

        # Check header count
        if len(headers) >= MAX_HEADERS_COUNT:
            raise HttpParseError(
                f"Too many headers: exceeds limit of {MAX_HEADERS_COUNT}"
            )

        headers[name.lower()] = value

    return method, path, headers


async def read_http_body(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
) -> str:
    """Read request body based on Content-Length header.

    Call this UNDER semaphore protection for non-SSE requests.

    Args:
        reader: The asyncio StreamReader to read from.
        headers: Parsed headers dict (lowercase keys).

    Returns:
        The request body as a string.

    Raises:
        HttpParseError: If the body is too large, incomplete, or malformed.
    """
    content_length_str = headers.get("content-length", "0")
    try:
        content_length = int(content_length_str)
    except ValueError as e:
        raise HttpParseError(f"Invalid Content-Length: {content_length_str}") from e

    if content_length > MAX_BODY_SIZE:
        raise HttpParseError(
            f"Request body too large: {content_length} > {MAX_BODY_SIZE}"
        )

    if content_length > 0:
        try:
            body_bytes = await asyncio.wait_for(
                reader.readexactly(content_length),
                timeout=30.0,
            )
            return body_bytes.decode("utf-8")
        except TimeoutError:
            raise HttpParseError("Body read timeout") from None
        except asyncio.IncompleteReadError as e:
            raise HttpParseError(
                f"Incomplete body: expected {content_length}, got {len(e.partial)}"
            ) from e
        except UnicodeDecodeError as e:
            raise HttpParseError(f"Invalid body encoding: {e}") from e

    return ""


async def send_http_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: str,
    content_type: str = "application/json",
) -> None:
    """Send an HTTP response.

    Args:
        writer: The asyncio StreamWriter to write to.
        status: HTTP status code (e.g., 200, 400, 500).
        body: Response body as string.
        content_type: Content-Type header value.
    """
    status_messages = {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        500: "Internal Server Error",
    }
    status_message = status_messages.get(status, "Unknown")

    body_bytes = body.encode("utf-8")
    headers = [
        f"HTTP/1.1 {status} {status_message}",
        f"Content-Type: {content_type}; charset=utf-8",
        f"Content-Length: {len(body_bytes)}",
        "Connection: close",
        "",
        "",
    ]
    response = "\r\n".join(headers).encode("utf-8") + body_bytes

    writer.write(response)
    await writer.drain()


def _extract_agent_id(path: str) -> str | None:
    """Extract agent_id from path like /agent/{agent_id}.

    Returns None if path doesn't match the pattern or agent_id is invalid.
    SECURITY: Validates agent_id format to prevent path traversal.
    """
    if path.startswith("/agent/"):
        agent_id = path[7:]  # len("/agent/") == 7
        if agent_id and is_valid_agent_id(agent_id):
            return agent_id
    return None


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    """Extract Bearer token from Authorization header.

    Args:
        headers: Dict of lowercase header names to values.

    Returns:
        The token if present and valid format, None otherwise.

    SECURITY: Handles case-insensitive "Bearer " prefix and extra whitespace.
    """
    auth_header = headers.get("authorization", "")
    # Case-insensitive check for "bearer " prefix
    if auth_header.lower().startswith("bearer "):
        # Strip whitespace from the token (handles "Bearer  token" with extra space)
        return auth_header[7:].strip()
    return None


# =============================================================================
# SSE (Server-Sent Events) Functions
# =============================================================================


def _is_sse_request_from_headers(method: str, path: str) -> bool:
    """Check if request is for SSE event stream (from parsed headers).

    SSE requests are GET requests to /agent/{agent_id}/events.

    Args:
        method: HTTP method (e.g., "GET", "POST").
        path: Request path (e.g., "/agent/test/events").

    Returns:
        True if this is an SSE subscription request.
    """
    if method != "GET":
        return False
    # Pattern: /agent/{agent_id}/events
    if path.startswith("/agent/") and path.endswith("/events"):
        return True
    return False


def _extract_agent_id_from_events_path(path: str) -> str | None:
    """Extract agent_id from /agent/{agent_id}/events path.

    Args:
        path: Request path (e.g., "/agent/test/events").

    Returns:
        The agent_id if path matches pattern and agent_id is valid, None otherwise.
    """
    # /agent/foo/events -> foo
    if path.startswith("/agent/") and path.endswith("/events"):
        middle = path[7:-7]  # Remove "/agent/" and "/events"
        if middle and is_valid_agent_id(middle):
            return middle
    return None


def _sanitize_sse_event_type(event_type: str) -> str:
    """Sanitize SSE event type to prevent framing injection.

    SSE event type field is unquoted, so newlines or other control characters
    could break framing and potentially inject malicious events.

    Args:
        event_type: The raw event type string.

    Returns:
        Sanitized event type containing only ASCII alphanumeric, underscore, dash, and dot.
        Falls back to "message" if the result would be empty.
    """
    # Allow only safe ASCII characters: letters, digits, underscore, dash, dot
    # Use explicit set instead of isalnum() which accepts Unicode
    allowed = string.ascii_letters + string.digits + "_-."
    sanitized = "".join(c for c in event_type if c in allowed)
    return sanitized if sanitized else "message"


async def write_sse_event(writer: asyncio.StreamWriter, event: dict) -> None:
    """Write a single SSE event.

    Formats the event as SSE and writes to the stream:
    - id: {seq} (if present)
    - event: {type}
    - data: {json}
    - (blank line to end event)

    Args:
        writer: The asyncio StreamWriter to write to.
        event: The event dict to serialize and send.
    """
    raw_type = event.get("type", "message")
    event_type = _sanitize_sse_event_type(str(raw_type))
    seq = event.get("seq")

    lines = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(event)}")
    lines.append("")
    lines.append("")

    message = "\n".join(lines)
    writer.write(message.encode("utf-8"))
    await writer.drain()


async def handle_sse_subscription(
    writer: asyncio.StreamWriter,
    path: str,
    event_hub: "EventHub",
    headers: dict[str, str],
) -> None:
    """Handle SSE subscription for agent events.

    Sends SSE headers, subscribes to the agent's event hub, and streams
    events to the client. Sends heartbeat pings every 15s to detect
    dead connections.

    Supports reconnection via Last-Event-ID header. When a client reconnects
    with Last-Event-ID, any missed events (still in the ring buffer) are
    replayed before subscribing to live events.

    Race condition handling: We subscribe FIRST, then replay from history,
    then drain any events that arrived during replay (deduplicating by seq),
    then stream live. This ensures no events are missed between replay and
    subscribe.

    This function runs until the client disconnects or an error occurs.
    The connection is NOT wrapped in the semaphore (SSE is long-lived).

    Args:
        writer: The asyncio StreamWriter for the connection.
        path: Request path (e.g., "/agent/test/events").
        event_hub: The EventHub for subscribing to agent events.
        headers: HTTP request headers dict (lowercase keys).
    """
    agent_id = _extract_agent_id_from_events_path(path)
    if agent_id is None:
        error_response = make_error_response(None, INVALID_PARAMS, "Invalid agent ID in path")
        await send_http_response(writer, 400, serialize_response(error_response))
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return

    # Parse Last-Event-ID for reconnect
    last_event_id = headers.get("last-event-id", "")
    since_seq = 0
    if last_event_id.isdigit():
        since_seq = int(last_event_id)

    # Send SSE headers
    sse_headers = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/event-stream; charset=utf-8",
        "Cache-Control: no-cache",
        "Connection: keep-alive",
        "X-Accel-Buffering: no",  # Disable proxy buffering
        "",
        "",
    ]
    writer.write("\r\n".join(sse_headers).encode())
    await writer.drain()

    # Subscribe FIRST (before replay) to avoid missing events during replay
    # Events published between replay and subscribe would be lost otherwise
    queue = event_hub.subscribe(agent_id)
    last_sent = since_seq

    try:
        # Replay missed events from history
        if since_seq > 0:
            for ev in event_hub.get_events_since(agent_id, since_seq):
                await write_sse_event(writer, ev)
                last_sent = max(last_sent, ev.get("seq", 0))

        # Drain any events that arrived during replay (avoid duplicates)
        while True:
            try:
                ev = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if ev.get("seq", 0) > last_sent:
                await write_sse_event(writer, ev)
                last_sent = ev.get("seq", 0)

        # Normal live streaming loop
        while True:
            try:
                # Wait for event with timeout (for heartbeat)
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                await write_sse_event(writer, event)
            except asyncio.TimeoutError:
                # Check if we were removed as a slow client
                if not event_hub.is_subscribed(agent_id, queue):
                    logger.debug("SSE subscriber removed (slow client), closing connection")
                    break
                # Send heartbeat (include agent_id for consistency)
                await write_sse_event(writer, {"type": "ping", "agent_id": agent_id})
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass  # Client disconnected
    finally:
        event_hub.unsubscribe(agent_id, queue)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# =============================================================================
# HTTP Pipeline Layer Functions
# =============================================================================


def _authenticate_request(
    http_request: HttpRequest,
    api_key: str | None,
) -> tuple[Response | None, int]:
    """Authenticate the HTTP request.

    Layer 3 of the HTTP pipeline: Authentication check.

    Args:
        http_request: The parsed HTTP request.
        api_key: Expected API key, or None if auth disabled.

    Returns:
        (error_response, status_code) if auth fails.
        (None, 0) if auth succeeds.
    """
    if api_key is None:
        return (None, 0)  # No auth configured

    token = _extract_bearer_token(http_request.headers)
    if token is None:
        return (
            make_error_response(None, INVALID_REQUEST, "Authorization header required"),
            401,
        )

    if not validate_api_key(token, api_key):
        return (
            make_error_response(None, INVALID_REQUEST, "Invalid API key"),
            403,
        )

    return (None, 0)  # Auth succeeded


def _route_to_dispatcher(
    path: str,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
) -> tuple[Dispatcher | None, str | None, Response | None, int]:
    """Route request path to appropriate dispatcher.

    Layer 4 of the HTTP pipeline: Path-based routing.

    Args:
        path: HTTP request path.
        pool: Agent pool for agent lookups.
        global_dispatcher: Dispatcher for global methods.

    Returns:
        (dispatcher, agent_id, error_response, status_code)
        - If routing succeeds to global: (dispatcher, None, None, 0)
        - If routing succeeds to agent: (dispatcher, agent_id, None, 0)
        - If agent not found but may exist saved: (None, agent_id, None, 0)
        - If routing fails: (None, None, error_response, status_code)
    """
    # Global routes
    if path in ("/", "/rpc"):
        return (global_dispatcher, None, None, 0)

    # Agent routes
    agent_id = _extract_agent_id(path)
    if agent_id is None:
        return (
            None,
            None,
            make_error_response(
                None, INVALID_PARAMS, "Not found. Use /, /rpc, or /agent/{agent_id}."
            ),
            404,
        )

    # Try to get active agent
    agent = pool.get(agent_id)
    if agent is not None:
        return (agent.dispatcher, agent_id, None, 0)

    # Agent not found - caller should try restore
    return (None, agent_id, None, 0)


async def _restore_agent_if_needed(
    agent_id: str,
    pool: AgentPool,
    session_manager: SessionManager | None,
) -> tuple[Dispatcher | None, Response | None, int]:
    """Attempt to restore agent from saved session.

    Layer 5 of the HTTP pipeline: Auto-restore inactive agents.

    Uses pool.get_or_restore() for atomic check-and-restore to prevent
    TOCTOU race conditions where multiple concurrent requests could try
    to restore the same agent simultaneously.

    Args:
        agent_id: Agent to restore.
        pool: Agent pool.
        session_manager: Session manager for loading saved sessions.

    Returns:
        (dispatcher, error_response, status_code)
        - If restore succeeds: (dispatcher, None, 0)
        - If no saved session or session_manager is None: (None, error_response, 404)
        - If restore fails: (None, error_response, 500)
    """
    try:
        # Atomic get-or-restore: prevents TOCTOU race condition
        # If another request already restored this agent, we get that one
        agent = await pool.get_or_restore(agent_id, session_manager)
        if agent is not None:
            logger.info("Agent '%s' restored or retrieved from pool", agent_id)
            return (agent.dispatcher, None, 0)

        # Agent not found and cannot be restored
        return (
            None,
            make_error_response(None, INVALID_PARAMS, f"Agent not found: {agent_id}"),
            404,
        )
    except Exception as e:
        logger.error("Failed to restore agent '%s': %s", agent_id, e)
        return (
            None,
            make_error_response(
                None, INTERNAL_ERROR, f"Failed to restore session: {e}"
            ),
            500,
        )


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
) -> None:
    """Handle a single HTTP connection with path-based routing.

    This function orchestrates the HTTP pipeline through distinct layers:
        1. Parse HTTP request
        2. Validate HTTP method (POST only)
        3. Authenticate request (if api_key configured)
        4. Route to dispatcher (global or agent)
        5. Restore agent if needed (auto-restore from saved session)
        6. Parse JSON-RPC request
        7. Dispatch to handler
        8. Send response

    Routing:
        - POST / or /rpc -> global_dispatcher
        - POST /agent/{agent_id} -> agent's dispatcher

    Cross-Session Auto-Restore:
        When a request targets an agent_id that is not in the active pool but
        exists as a saved session (via session_manager), the session is
        automatically restored before processing the request.

    Args:
        reader: The asyncio StreamReader for the connection.
        writer: The asyncio StreamWriter for the connection.
        pool: The AgentPool to look up agents by ID.
        global_dispatcher: The GlobalDispatcher for / and /rpc paths.
        api_key: Optional API key for authentication. If provided, requests
                 must include Authorization: Bearer <key> header.
        session_manager: Optional SessionManager for auto-restoring saved sessions.
    """
    try:
        # Layer 1: Parse HTTP request
        try:
            http_request = await read_http_request(reader)
        except HttpParseError as e:
            error_response = make_error_response(None, PARSE_ERROR, str(e))
            await send_http_response(writer, 400, serialize_response(error_response))
            return

        # Layer 2: Validate HTTP method (POST only)
        if http_request.method != "POST":
            error_response = make_error_response(
                None, INVALID_REQUEST, "Method not allowed. Use POST."
            )
            await send_http_response(writer, 405, serialize_response(error_response))
            return

        # Layer 3: Authenticate request
        auth_error, auth_status = _authenticate_request(http_request, api_key)
        if auth_error is not None:
            await send_http_response(
                writer, auth_status, serialize_response(auth_error)
            )
            return

        # Layer 4: Route to dispatcher
        dispatcher, agent_id, route_error, route_status = _route_to_dispatcher(
            http_request.path, pool, global_dispatcher
        )
        if route_error is not None:
            await send_http_response(
                writer, route_status, serialize_response(route_error)
            )
            return

        # Layer 5: Restore agent if needed (dispatcher is None but agent_id is set)
        if dispatcher is None and agent_id is not None:
            dispatcher, restore_error, restore_status = await _restore_agent_if_needed(
                agent_id, pool, session_manager
            )
            if restore_error is not None:
                await send_http_response(
                    writer, restore_status, serialize_response(restore_error)
                )
                return

        # Safety check: dispatcher must be set by now
        assert dispatcher is not None, "dispatcher should be set after routing/restore"

        # Layer 6: Parse JSON-RPC request
        try:
            rpc_request = parse_request(http_request.body)
        except ParseError as e:
            error_response = make_error_response(None, PARSE_ERROR, str(e))
            await send_http_response(writer, 400, serialize_response(error_response))
            return

        # Layer 7: Dispatch to handler
        # Extract requester_id from X-Nexus-Agent header (for authorization)
        requester_id = http_request.headers.get("x-nexus-agent")

        try:
            # Global dispatcher needs requester_id for authorization checks
            # Agent dispatchers don't need it (they use their own agent context)
            if agent_id is None:
                # Global route (/ or /rpc) - pass requester_id
                rpc_response = await global_dispatcher.dispatch(rpc_request, requester_id)
            else:
                # Agent route - use standard dispatch
                rpc_response = await dispatcher.dispatch(rpc_request)
        except Exception as e:
            # Unexpected error during dispatch
            error_response = make_error_response(
                rpc_request.id,
                INTERNAL_ERROR,
                f"Internal error: {type(e).__name__}: {e}",
            )
            await send_http_response(writer, 500, serialize_response(error_response))
            return

        # Layer 8: Send response
        if rpc_response is not None:
            await send_http_response(writer, 200, serialize_response(rpc_response))
        else:
            # Notification - no response body, but still need HTTP response
            await send_http_response(writer, 200, "")

    except Exception as e:
        # Catch-all for any unexpected errors
        logger.error("Unexpected error handling connection: %s", e, exc_info=True)
        try:
            error_response = make_error_response(
                None, INTERNAL_ERROR, f"Server error: {type(e).__name__}"
            )
            await send_http_response(writer, 500, serialize_response(error_response))
        except Exception as send_err:
            logger.debug(
                "Failed to send error response (client disconnected?): %s", send_err
            )

    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception as close_err:
            logger.debug("Connection close failed (already closed?): %s", close_err)


async def handle_connection_with_parsed_request(
    http_request: HttpRequest,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
) -> None:
    """Handle connection with already-parsed HttpRequest.

    This is the existing handle_connection logic, but:
    - Does NOT call read_http_request (already parsed)
    - Starts at Layer 2 (method validation)

    Used by two-stage parsing flow where headers are read outside the
    semaphore to detect SSE requests.

    Args:
        http_request: The already-parsed HTTP request.
        writer: The asyncio StreamWriter for the connection.
        pool: The AgentPool to look up agents by ID.
        global_dispatcher: The GlobalDispatcher for / and /rpc paths.
        api_key: Optional API key for authentication.
        session_manager: Optional SessionManager for auto-restoring saved sessions.
    """
    try:
        # Layer 2: Validate HTTP method (POST only for JSON-RPC)
        if http_request.method != "POST":
            error_response = make_error_response(
                None, INVALID_REQUEST, "Method not allowed. Use POST."
            )
            await send_http_response(writer, 405, serialize_response(error_response))
            return

        # Layer 3: Authenticate request
        auth_error, auth_status = _authenticate_request(http_request, api_key)
        if auth_error is not None:
            await send_http_response(
                writer, auth_status, serialize_response(auth_error)
            )
            return

        # Layer 4: Route to dispatcher
        dispatcher, agent_id, route_error, route_status = _route_to_dispatcher(
            http_request.path, pool, global_dispatcher
        )
        if route_error is not None:
            await send_http_response(
                writer, route_status, serialize_response(route_error)
            )
            return

        # Layer 5: Restore agent if needed (dispatcher is None but agent_id is set)
        if dispatcher is None and agent_id is not None:
            dispatcher, restore_error, restore_status = await _restore_agent_if_needed(
                agent_id, pool, session_manager
            )
            if restore_error is not None:
                await send_http_response(
                    writer, restore_status, serialize_response(restore_error)
                )
                return

        # Safety check: dispatcher must be set by now
        assert dispatcher is not None, "dispatcher should be set after routing/restore"

        # Layer 6: Parse JSON-RPC request
        try:
            rpc_request = parse_request(http_request.body)
        except ParseError as e:
            error_response = make_error_response(None, PARSE_ERROR, str(e))
            await send_http_response(writer, 400, serialize_response(error_response))
            return

        # Layer 7: Dispatch to handler
        # Extract requester_id from X-Nexus-Agent header (for authorization)
        requester_id = http_request.headers.get("x-nexus-agent")

        try:
            # Global dispatcher needs requester_id for authorization checks
            # Agent dispatchers don't need it (they use their own agent context)
            if agent_id is None:
                # Global route (/ or /rpc) - pass requester_id
                rpc_response = await global_dispatcher.dispatch(rpc_request, requester_id)
            else:
                # Agent route - use standard dispatch
                rpc_response = await dispatcher.dispatch(rpc_request)
        except Exception as e:
            # Unexpected error during dispatch
            error_response = make_error_response(
                rpc_request.id,
                INTERNAL_ERROR,
                f"Internal error: {type(e).__name__}: {e}",
            )
            await send_http_response(writer, 500, serialize_response(error_response))
            return

        # Layer 8: Send response
        if rpc_response is not None:
            await send_http_response(writer, 200, serialize_response(rpc_response))
        else:
            # Notification - no response body, but still need HTTP response
            await send_http_response(writer, 200, "")

    except Exception as e:
        # Catch-all for any unexpected errors
        logger.error("Unexpected error handling connection: %s", e, exc_info=True)
        try:
            error_response = make_error_response(
                None, INTERNAL_ERROR, f"Server error: {type(e).__name__}"
            )
            await send_http_response(writer, 500, serialize_response(error_response))
        except Exception as send_err:
            logger.debug(
                "Failed to send error response (client disconnected?): %s", send_err
            )

    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception as close_err:
            logger.debug("Connection close failed (already closed?): %s", close_err)


async def run_http_server(
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    port: int = DEFAULT_PORT,
    host: str = BIND_HOST,
    api_key: str | None = None,
    session_manager: SessionManager | None = None,
    max_concurrent: int = 32,
    idle_timeout: float | None = None,
    started_event: asyncio.Event | None = None,
    event_hub: "EventHub | None" = None,
) -> None:
    """Run the HTTP server for JSON-RPC requests with path-based routing.

    This function runs indefinitely until cancelled, the pool signals shutdown,
    or the idle timeout is reached.

    Routing:
        - POST / or /rpc → global_dispatcher
        - POST /agent/{agent_id} → agent's dispatcher
        - GET /agent/{agent_id}/events → SSE event stream (if event_hub provided)

    Cross-Session Auto-Restore:
        When a request targets an agent_id that is not in the active pool but
        exists as a saved session (via session_manager), the session is
        automatically restored before processing the request.

    SSE (Server-Sent Events):
        When event_hub is provided, GET requests to /agent/{id}/events are
        handled as SSE subscriptions. SSE connections bypass the connection
        semaphore (they are long-lived) and receive real-time events.

    Args:
        pool: The AgentPool for looking up agents and shutdown signal.
        global_dispatcher: The GlobalDispatcher for / and /rpc paths.
        port: Port to listen on. Defaults to 8765.
        host: Host to bind to. Defaults to 127.0.0.1 (localhost only).
              SECURITY: Never pass 0.0.0.0 here.
        api_key: Optional API key for authentication. If provided, all requests
                 must include Authorization: Bearer <key> header.
        session_manager: Optional SessionManager for auto-restoring saved sessions.
                        When provided, requests to inactive but saved agents will
                        trigger automatic session restoration.
        max_concurrent: Maximum concurrent connections to prevent DoS. Defaults to 32.
        idle_timeout: Optional idle timeout in seconds. If no RPC connections are
                     received within this duration, the server will shut down.
                     None means no idle timeout (server runs indefinitely).
                     Note: SSE subscribers keep the server alive.
        started_event: Optional asyncio.Event to set when the server has successfully
                      bound to the port and is listening. Useful for callers to know
                      when the server is ready (e.g., to write token files only after
                      bind success).
        event_hub: Optional EventHub for SSE subscriptions. If None, SSE requests
                  will receive a 404 error.
    """
    # Security: Force localhost binding
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            f"Security: HTTP server must bind to localhost only, not {host!r}"
        )

    # Rate limiting: limit concurrent connections
    semaphore = asyncio.Semaphore(max_concurrent)

    # Track last activity time for idle timeout using monotonic clock
    # (immune to wall clock jumps from NTP sync, WSL time sync, suspend/resume)
    last_activity = time.monotonic()

    async def client_handler(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal last_activity
        last_activity = time.monotonic()  # Reset idle timer on each connection

        # Stage 1: Read ONLY request line + headers (no body) to detect SSE
        # This is safe outside semaphore since headers are bounded by MAX_TOTAL_HEADERS_SIZE
        try:
            method, path, headers = await read_http_request_headers(reader)
        except HttpParseError as e:
            error_response = make_error_response(None, PARSE_ERROR, str(e))
            await send_http_response(writer, 400, serialize_response(error_response))
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            return

        # Check if SSE request BEFORE acquiring semaphore
        if _is_sse_request_from_headers(method, path):
            # SSE: authenticate then handle without semaphore
            if event_hub is None:
                # SSE not enabled (event_hub not provided)
                error_response = make_error_response(
                    None, INVALID_REQUEST, "SSE not enabled"
                )
                await send_http_response(writer, 404, serialize_response(error_response))
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                return

            # Build minimal HttpRequest for auth (no body needed)
            http_request = HttpRequest(method=method, path=path, headers=headers, body="")
            auth_error, auth_status = _authenticate_request(http_request, api_key)
            if auth_error is not None:
                await send_http_response(writer, auth_status, serialize_response(auth_error))
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                return

            # Handle SSE subscription (does NOT hold semaphore)
            # Note: handle_sse_subscription manages its own writer close in finally
            await handle_sse_subscription(writer, path, event_hub, headers)
            return

        # Regular JSON-RPC: acquire semaphore, then read body
        # Use try/finally to ensure writer is always closed (fixes connection leak)
        try:
            async with semaphore:
                # Stage 2: Read body under semaphore protection
                try:
                    body = await read_http_body(reader, headers)
                except HttpParseError as e:
                    error_response = make_error_response(None, PARSE_ERROR, str(e))
                    await send_http_response(writer, 400, serialize_response(error_response))
                    return
                http_request = HttpRequest(method=method, path=path, headers=headers, body=body)
                # Note: handle_connection_with_parsed_request has its own finally block
                # that closes the writer, so we skip closing in our finally when this succeeds
                await handle_connection_with_parsed_request(
                    http_request, writer, pool, global_dispatcher, api_key, session_manager
                )
                return  # Writer already closed by handle_connection_with_parsed_request
        finally:
            # Close writer if not already closed by handle_connection_with_parsed_request
            # This handles the read_http_body error path where we return early
            try:
                if not writer.is_closing():
                    writer.close()
                    await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(
        client_handler,
        host=host,
        port=port,
    )

    # Signal that server has successfully bound to port and is listening
    if started_event:
        started_event.set()

    addr = server.sockets[0].getsockname() if server.sockets else (host, port)
    logger.info("JSON-RPC HTTP server running at http://%s:%s/", addr[0], addr[1])
    if idle_timeout is not None:
        logger.info("Idle timeout: %s seconds", idle_timeout)

    async with server:
        # Check for shutdown periodically
        # Exit if: all agents want shutdown OR explicit shutdown_server was called
        # OR idle timeout reached (unless SSE subscribers exist)
        while not pool.should_shutdown and not global_dispatcher.shutdown_requested:
            # Check idle timeout
            if idle_timeout is not None:
                # Don't idle-timeout if we have active SSE subscribers
                if event_hub is not None and event_hub.total_subscriber_count() > 0:
                    last_activity = time.monotonic()
                else:
                    idle_duration = time.monotonic() - last_activity
                    if idle_duration > idle_timeout:
                        logger.info(
                            "Idle timeout reached (%.0fs without RPC activity), shutting down",
                            idle_duration,
                        )
                        break

            await asyncio.sleep(0.1)

        # Graceful shutdown
        server.close()
        await server.wait_closed()
        logger.info("HTTP server stopped")
