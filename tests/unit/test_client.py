"""Unit tests for NexusClient and RPC protocol functions."""

import json

import httpx
import pytest

from nexus3.client import ClientError, NexusClient
from nexus3.rpc.protocol import ParseError, parse_response, serialize_request
from nexus3.rpc.types import Request, Response


# === Protocol function tests ===


class TestSerializeRequest:
    """Tests for serialize_request function."""

    def test_serialize_request_basic(self):
        """Serialize a basic request with method and id."""
        request = Request(jsonrpc="2.0", method="send", id=1)
        result = serialize_request(request)
        data = json.loads(result)

        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "send"
        assert data["id"] == 1
        assert "params" not in data

    def test_serialize_request_with_params(self):
        """Serialize a request with parameters."""
        request = Request(
            jsonrpc="2.0",
            method="send",
            params={"content": "Hello, world!", "request_id": "abc123"},
            id=42,
        )
        result = serialize_request(request)
        data = json.loads(result)

        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "send"
        assert data["id"] == 42
        assert data["params"] == {"content": "Hello, world!", "request_id": "abc123"}

    def test_serialize_request_notification(self):
        """Serialize a notification (no id)."""
        request = Request(jsonrpc="2.0", method="status", params={"state": "ready"})
        result = serialize_request(request)
        data = json.loads(result)

        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "status"
        assert data["params"] == {"state": "ready"}
        assert "id" not in data


class TestParseResponse:
    """Tests for parse_response function."""

    def test_parse_response_success(self):
        """Parse a successful response with result."""
        json_str = '{"jsonrpc":"2.0","id":1,"result":{"content":"Hello!","tokens":42}}'
        response = parse_response(json_str)

        assert response.jsonrpc == "2.0"
        assert response.id == 1
        assert response.result == {"content": "Hello!", "tokens": 42}
        assert response.error is None

    def test_parse_response_error(self):
        """Parse an error response."""
        json_str = '{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}'
        response = parse_response(json_str)

        assert response.jsonrpc == "2.0"
        assert response.id == 1
        assert response.result is None
        assert response.error == {"code": -32601, "message": "Method not found"}

    def test_parse_response_invalid_json(self):
        """Parse invalid JSON raises ParseError."""
        with pytest.raises(ParseError) as exc_info:
            parse_response("not valid json {")

        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_response_missing_id(self):
        """Response without id field raises ParseError."""
        with pytest.raises(ParseError) as exc_info:
            parse_response('{"jsonrpc":"2.0","result":"ok"}')

        assert "id" in str(exc_info.value)

    def test_parse_response_missing_result_and_error(self):
        """Response without result or error raises ParseError."""
        with pytest.raises(ParseError) as exc_info:
            parse_response('{"jsonrpc":"2.0","id":1}')

        assert "result" in str(exc_info.value) or "error" in str(exc_info.value)


# === NexusClient tests ===


class TestNexusClient:
    """Tests for NexusClient class."""

    @pytest.mark.asyncio
    async def test_client_requires_context_manager(self):
        """Client raises ClientError if used without async with."""
        client = NexusClient()

        with pytest.raises(ClientError) as exc_info:
            await client.send("test")

        assert "context manager" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_client_send_success(self):
        """Client successfully sends message and returns result."""
        # Mock response
        mock_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": "Hello from server!", "tokens": {"prompt": 10, "completion": 5}},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(mock_handler)

        async with NexusClient() as client:
            # Replace the internal client with our mocked one
            client._client = httpx.AsyncClient(transport=transport)
            result = await client.send("Hello!")

        assert result["content"] == "Hello from server!"
        assert result["tokens"] == {"prompt": 10, "completion": 5}

    @pytest.mark.asyncio
    async def test_client_handles_connection_error(self):
        """Client raises ClientError on connection failure."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(mock_handler)

        async with NexusClient() as client:
            client._client = httpx.AsyncClient(transport=transport)

            with pytest.raises(ClientError) as exc_info:
                await client.send("test")

            assert "Connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_client_handles_rpc_error(self):
        """Client raises ClientError with message on RPC error."""
        mock_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found: unknown_method"},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(mock_handler)

        async with NexusClient() as client:
            client._client = httpx.AsyncClient(transport=transport)

            with pytest.raises(ClientError) as exc_info:
                await client.send("test")

            error_msg = str(exc_info.value)
            assert "-32601" in error_msg
            assert "Method not found" in error_msg

    @pytest.mark.asyncio
    async def test_client_get_tokens(self):
        """Client get_tokens returns token usage."""
        mock_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"system": 100, "messages": 500, "total": 600, "budget": 8000},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            # Verify the request is for get_tokens
            body = json.loads(request.content)
            assert body["method"] == "get_tokens"
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(mock_handler)

        async with NexusClient() as client:
            client._client = httpx.AsyncClient(transport=transport)
            result = await client.get_tokens()

        assert result["total"] == 600
        assert result["budget"] == 8000

    @pytest.mark.asyncio
    async def test_client_shutdown(self):
        """Client shutdown sends shutdown request."""
        mock_response = {"jsonrpc": "2.0", "id": 1, "result": {"status": "shutting_down"}}

        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["method"] == "shutdown"
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(mock_handler)

        async with NexusClient() as client:
            client._client = httpx.AsyncClient(transport=transport)
            result = await client.shutdown()

        assert result["status"] == "shutting_down"

    @pytest.mark.asyncio
    async def test_client_increments_request_id(self):
        """Client auto-increments request IDs."""
        received_ids = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            received_ids.append(body["id"])
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": "ok"}}
            )

        transport = httpx.MockTransport(mock_handler)

        async with NexusClient() as client:
            client._client = httpx.AsyncClient(transport=transport)
            await client.send("first")
            await client.send("second")
            await client.send("third")

        assert received_ids == [1, 2, 3]
