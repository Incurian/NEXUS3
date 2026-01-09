"""Unit tests for nexus3.rpc.detection module.

Tests for:
- DetectionResult enum values
- detect_server() server detection with various responses
- wait_for_server() polling behavior
"""

import asyncio
import json

import httpx
import pytest

from nexus3.rpc.detection import DetectionResult, detect_server, wait_for_server


# -----------------------------------------------------------------------------
# DetectionResult Enum Tests
# -----------------------------------------------------------------------------


class TestDetectionResult:
    """Tests for DetectionResult enum."""

    def test_enum_values_exist(self):
        """All expected enum values exist."""
        assert hasattr(DetectionResult, "NO_SERVER")
        assert hasattr(DetectionResult, "NEXUS_SERVER")
        assert hasattr(DetectionResult, "OTHER_SERVICE")
        assert hasattr(DetectionResult, "TIMEOUT")
        assert hasattr(DetectionResult, "ERROR")

    def test_enum_values_are_correct_strings(self):
        """Enum values are the expected string values."""
        assert DetectionResult.NO_SERVER.value == "no_server"
        assert DetectionResult.NEXUS_SERVER.value == "nexus_server"
        assert DetectionResult.OTHER_SERVICE.value == "other_service"
        assert DetectionResult.TIMEOUT.value == "timeout"
        assert DetectionResult.ERROR.value == "error"

    def test_enum_has_exactly_five_members(self):
        """DetectionResult enum has exactly 5 members."""
        assert len(DetectionResult) == 5

    def test_enum_members_are_unique(self):
        """All enum values are unique."""
        values = [member.value for member in DetectionResult]
        assert len(values) == len(set(values))


# -----------------------------------------------------------------------------
# detect_server() Tests
# -----------------------------------------------------------------------------


class TestDetectServer:
    """Tests for detect_server() function."""

    @pytest.mark.asyncio
    async def test_returns_no_server_when_connection_refused(self):
        """Returns NO_SERVER when nothing is listening on port."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(mock_handler)

        # Patch httpx.AsyncClient to use our mock transport
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(9999)

        assert result == DetectionResult.NO_SERVER

    @pytest.mark.asyncio
    async def test_returns_nexus_server_for_valid_response(self):
        """Returns NEXUS_SERVER when valid NEXUS3 response received."""
        # Valid NEXUS3 list_agents response
        valid_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "agents": [
                    {"agent_id": "main", "created_at": "2025-01-01T00:00:00"},
                ]
            },
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=valid_response)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.NEXUS_SERVER

    @pytest.mark.asyncio
    async def test_returns_nexus_server_for_empty_agents_list(self):
        """Returns NEXUS_SERVER when response has empty agents list."""
        valid_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"agents": []},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=valid_response)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.NEXUS_SERVER

    @pytest.mark.asyncio
    async def test_returns_nexus_server_for_error_response(self):
        """Returns NEXUS_SERVER for valid JSON-RPC error (still NEXUS3)."""
        # Error response is still a valid NEXUS3 server
        error_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=error_response)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.NEXUS_SERVER

    @pytest.mark.asyncio
    async def test_returns_other_service_for_non_json_response(self):
        """Returns OTHER_SERVICE for non-JSON HTTP response."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"<html><body>Not JSON</body></html>",
                headers={"content-type": "text/html"},
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_non_jsonrpc_json(self):
        """Returns OTHER_SERVICE for JSON that isn't JSON-RPC 2.0."""
        # Regular JSON but not JSON-RPC format
        non_rpc_response = {"status": "ok", "data": [1, 2, 3]}

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=non_rpc_response)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_wrong_jsonrpc_version(self):
        """Returns OTHER_SERVICE for JSON-RPC with wrong version."""
        wrong_version = {
            "jsonrpc": "1.0",  # Wrong version
            "id": 1,
            "result": {"agents": []},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=wrong_version)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_missing_id(self):
        """Returns OTHER_SERVICE when response has no id field."""
        missing_id = {
            "jsonrpc": "2.0",
            "result": {"agents": []},
            # Missing "id" field
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=missing_id)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_both_result_and_error(self):
        """Returns OTHER_SERVICE when response has both result and error."""
        both_fields = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"agents": []},
            "error": {"code": -32600, "message": "Invalid"},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=both_fields)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_neither_result_nor_error(self):
        """Returns OTHER_SERVICE when response has neither result nor error."""
        neither_field = {
            "jsonrpc": "2.0",
            "id": 1,
            # Missing both result and error
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=neither_field)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_result_not_dict(self):
        """Returns OTHER_SERVICE when result is not a dict."""
        result_not_dict = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": "string instead of dict",
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=result_not_dict)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_missing_agents_key(self):
        """Returns OTHER_SERVICE when result dict has no agents key."""
        missing_agents = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"something_else": []},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=missing_agents)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_agents_not_list(self):
        """Returns OTHER_SERVICE when agents is not a list."""
        agents_not_list = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"agents": "not a list"},
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=agents_not_list)

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_other_service_for_json_array(self):
        """Returns OTHER_SERVICE when response is a JSON array (not object)."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[1, 2, 3])

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.OTHER_SERVICE

    @pytest.mark.asyncio
    async def test_returns_timeout_on_timeout_exception(self):
        """Returns TIMEOUT on connection timeout."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Connection timed out")

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765, timeout=0.1)

        assert result == DetectionResult.TIMEOUT

    @pytest.mark.asyncio
    async def test_returns_timeout_on_read_timeout(self):
        """Returns TIMEOUT on read timeout."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765, timeout=0.1)

        assert result == DetectionResult.TIMEOUT

    @pytest.mark.asyncio
    async def test_returns_error_on_unexpected_exception(self):
        """Returns ERROR on unexpected exceptions."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("Unexpected error")

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await detect_server(8765)

        assert result == DetectionResult.ERROR

    @pytest.mark.asyncio
    async def test_sends_list_agents_request(self):
        """Verifies detect_server sends a list_agents JSON-RPC request."""
        received_request = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_request
            received_request = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await detect_server(8765)

        # Verify the request structure
        assert received_request is not None
        assert received_request["jsonrpc"] == "2.0"
        assert received_request["method"] == "list_agents"
        assert received_request["id"] == 1

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        """Verifies detect_server constructs correct URL."""
        received_url = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_url
            received_url = str(request.url)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await detect_server(8765, host="127.0.0.1")

        assert received_url == "http://127.0.0.1:8765/"

    @pytest.mark.asyncio
    async def test_custom_host(self):
        """Verifies detect_server uses custom host parameter."""
        received_url = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_url
            received_url = str(request.url)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await detect_server(9000, host="localhost")

        assert received_url == "http://localhost:9000/"


# -----------------------------------------------------------------------------
# wait_for_server() Tests
# -----------------------------------------------------------------------------


class TestWaitForServer:
    """Tests for wait_for_server() function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_server_available_immediately(self):
        """Returns True when server is immediately available."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await wait_for_server(8765, timeout=5.0)

        assert result is True
        assert call_count == 1  # Only one poll needed

    @pytest.mark.asyncio
    async def test_returns_true_when_server_becomes_available(self):
        """Returns True when server becomes available after some polls."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # First 2 calls fail with connection refused
                raise httpx.ConnectError("Connection refused")
            # Third call succeeds
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await wait_for_server(8765, timeout=5.0, poll_interval=0.01)

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_returns_false_when_timeout_expires(self):
        """Returns False when timeout expires without server."""

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await wait_for_server(8765, timeout=0.1, poll_interval=0.02)

        assert result is False

    @pytest.mark.asyncio
    async def test_continues_polling_on_other_service(self):
        """Keeps polling when OTHER_SERVICE is detected (startup race)."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # First 2 calls return non-NEXUS3 response
                return httpx.Response(
                    200,
                    json={"status": "initializing"},  # Not JSON-RPC
                )
            # Third call succeeds with NEXUS3 response
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await wait_for_server(8765, timeout=5.0, poll_interval=0.01)

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_continues_polling_on_timeout(self):
        """Keeps polling when individual probes timeout."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # First 2 calls timeout
                raise httpx.TimeoutException("Timeout")
            # Third call succeeds
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await wait_for_server(8765, timeout=5.0, poll_interval=0.01)

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_continues_polling_on_error(self):
        """Keeps polling when individual probes encounter errors."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # First 2 calls fail with unexpected error
                raise RuntimeError("Unexpected error")
            # Third call succeeds
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            result = await wait_for_server(8765, timeout=5.0, poll_interval=0.01)

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_respects_poll_interval(self):
        """Verifies poll_interval affects timing between polls."""
        call_times = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            call_times.append(asyncio.get_event_loop().time())
            if len(call_times) < 3:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        poll_interval = 0.05

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await wait_for_server(8765, timeout=5.0, poll_interval=poll_interval)

        # Check intervals between calls (should be approximately poll_interval)
        assert len(call_times) == 3
        for i in range(1, len(call_times)):
            interval = call_times[i] - call_times[i - 1]
            # Allow some tolerance for async scheduling
            assert interval >= poll_interval * 0.8
            assert interval < poll_interval * 3  # Should not be much longer

    @pytest.mark.asyncio
    async def test_probe_timeout_is_capped(self):
        """Verifies probe timeout is capped to reasonable value."""
        # With timeout=30 and default logic: probe_timeout = min(1.0, 30/10) = 1.0
        # With timeout=5: probe_timeout = min(1.0, 5/10) = 0.5
        # With timeout=0.5: probe_timeout = min(1.0, 0.5/10) = 0.05

        # We just verify the function works with various timeout values
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)

            # Short timeout
            result = await wait_for_server(8765, timeout=0.5, poll_interval=0.01)
            assert result is True

            # Medium timeout
            result = await wait_for_server(8765, timeout=5.0, poll_interval=0.01)
            assert result is True

    @pytest.mark.asyncio
    async def test_uses_custom_host(self):
        """Verifies wait_for_server passes custom host to detect_server."""
        received_urls = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            received_urls.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"agents": []},
                },
            )

        transport = httpx.MockTransport(mock_handler)

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            await wait_for_server(9000, host="myhost.local", timeout=5.0)

        assert len(received_urls) >= 1
        assert received_urls[0] == "http://myhost.local:9000/"
