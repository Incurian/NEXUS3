"""Pure asyncio HTTP server for JSON-RPC 2.0 requests.

This module provides a minimal HTTP server that accepts JSON-RPC 2.0 requests
over HTTP POST. It uses only asyncio stdlib - no external dependencies.

Security: The server binds only to localhost (127.0.0.1) and never to 0.0.0.0.

Path-based routing:
    - POST / or /rpc → GlobalDispatcher (agent management)
    - POST /agent/{agent_id} → Agent's Dispatcher

Example usage:
    pool = AgentPool()
    global_dispatcher = GlobalDispatcher(pool)
    await run_http_server(pool, global_dispatcher, port=8765)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nexus3.rpc.protocol import (
    INTERNAL_ERROR,
    PARSE_ERROR,
    ParseError,
    make_error_response,
    parse_request,
    serialize_response,
)

if TYPE_CHECKING:
    from typing import Protocol

    class Dispatcher(Protocol):
        """Protocol for dispatchers that handle JSON-RPC requests."""

        async def dispatch(self, request: "Request") -> "Response | None": ...

    class GlobalDispatcher(Dispatcher, Protocol):
        """Protocol for the global dispatcher that manages agents."""

        pass

    class AgentPool(Protocol):
        """Protocol for the agent pool."""

        @property
        def should_shutdown(self) -> bool: ...

        def get_agent(self, agent_id: str) -> "Agent | None": ...

    class Agent(Protocol):
        """Protocol for an agent with a dispatcher."""

        @property
        def dispatcher(self) -> Dispatcher: ...

    from nexus3.rpc.protocol import Request, Response

# Constants
DEFAULT_PORT = 8765
MAX_BODY_SIZE = 1_048_576  # 1MB
BIND_HOST = "127.0.0.1"  # Localhost only - NEVER bind to 0.0.0.0


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


class HttpParseError(Exception):
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

    # Parse request line: "POST /rpc HTTP/1.1\r\n"
    try:
        request_line_str = request_line.decode("utf-8").strip()
        parts = request_line_str.split(" ")
        if len(parts) != 3:
            raise HttpParseError(f"Invalid request line: {request_line_str}")
        method, path, _version = parts
    except UnicodeDecodeError as e:
        raise HttpParseError(f"Invalid request encoding: {e}") from e

    # Read headers
    headers: dict[str, str] = {}
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

        try:
            header_str = header_line.decode("utf-8").strip()
        except UnicodeDecodeError as e:
            raise HttpParseError(f"Invalid header encoding: {e}") from e

        if ":" not in header_str:
            continue  # Skip malformed headers

        name, value = header_str.split(":", 1)
        headers[name.strip().lower()] = value.strip()

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

    Returns None if path doesn't match the pattern.
    """
    if path.startswith("/agent/"):
        agent_id = path[7:]  # len("/agent/") == 7
        if agent_id:
            return agent_id
    return None


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
) -> None:
    """Handle a single HTTP connection with path-based routing.

    Routing:
        - POST / or /rpc → global_dispatcher
        - POST /agent/{agent_id} → agent's dispatcher

    Args:
        reader: The asyncio StreamReader for the connection.
        writer: The asyncio StreamWriter for the connection.
        pool: The AgentPool to look up agents by ID.
        global_dispatcher: The GlobalDispatcher for / and /rpc paths.
    """
    try:
        # Parse HTTP request
        try:
            http_request = await read_http_request(reader)
        except HttpParseError as e:
            await send_http_response(writer, 400, f'{{"error": "{e}"}}')
            return

        # Only accept POST
        if http_request.method != "POST":
            await send_http_response(
                writer,
                405,
                '{"error": "Method not allowed. Use POST."}',
            )
            return

        # Route based on path
        dispatcher: Dispatcher
        if http_request.path in ("/", "/rpc"):
            dispatcher = global_dispatcher
        elif (agent_id := _extract_agent_id(http_request.path)) is not None:
            agent = pool.get(agent_id)
            if agent is None:
                await send_http_response(
                    writer,
                    404,
                    f'{{"error": "Agent not found: {agent_id}"}}',
                )
                return
            dispatcher = agent.dispatcher
        else:
            await send_http_response(
                writer,
                404,
                '{"error": "Not found. Use /, /rpc, or /agent/{agent_id}."}',
            )
            return

        # Parse JSON-RPC request
        try:
            rpc_request = parse_request(http_request.body)
        except ParseError as e:
            error_response = make_error_response(None, PARSE_ERROR, str(e))
            await send_http_response(writer, 400, serialize_response(error_response))
            return

        # Dispatch to handler
        try:
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

        # Send response
        if rpc_response is not None:
            await send_http_response(writer, 200, serialize_response(rpc_response))
        else:
            # Notification - no response body, but still need HTTP response
            await send_http_response(writer, 200, "")

    except Exception as e:
        # Catch-all for any unexpected errors
        try:
            await send_http_response(
                writer,
                500,
                f'{{"error": "Server error: {type(e).__name__}"}}',
            )
        except Exception:
            pass  # Connection may be broken

    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass  # Connection may already be closed


async def run_http_server(
    pool: AgentPool,
    global_dispatcher: GlobalDispatcher,
    port: int = DEFAULT_PORT,
    host: str = BIND_HOST,
) -> None:
    """Run the HTTP server for JSON-RPC requests with path-based routing.

    This function runs indefinitely until cancelled or the pool
    signals shutdown.

    Routing:
        - POST / or /rpc → global_dispatcher
        - POST /agent/{agent_id} → agent's dispatcher

    Args:
        pool: The AgentPool for looking up agents and shutdown signal.
        global_dispatcher: The GlobalDispatcher for / and /rpc paths.
        port: Port to listen on. Defaults to 8765.
        host: Host to bind to. Defaults to 127.0.0.1 (localhost only).
              SECURITY: Never pass 0.0.0.0 here.
    """
    # Security: Force localhost binding
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            f"Security: HTTP server must bind to localhost only, not {host!r}"
        )

    async def client_handler(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await handle_connection(reader, writer, pool, global_dispatcher)

    server = await asyncio.start_server(
        client_handler,
        host=host,
        port=port,
    )

    addr = server.sockets[0].getsockname() if server.sockets else (host, port)
    print(f"JSON-RPC HTTP server running at http://{addr[0]}:{addr[1]}/")

    async with server:
        # Check for shutdown periodically
        while not pool.should_shutdown:
            await asyncio.sleep(0.1)

        # Graceful shutdown
        server.close()
        await server.wait_closed()
        print("HTTP server stopped.")
