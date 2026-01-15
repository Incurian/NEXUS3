"""P1.2: Test HTTP header size and count limits.

This tests the security issue where the HTTP header parsing loop had no limits,
allowing memory DoS attacks by sending many headers or very large headers.

The fix adds limits for:
- MAX_HEADERS_COUNT (128)
- MAX_HEADER_NAME_LEN (1024 bytes)
- MAX_HEADER_VALUE_LEN (8192 bytes)
- MAX_TOTAL_HEADERS_SIZE (32KB)
- MAX_REQUEST_LINE_LEN (8192 bytes)
"""

import asyncio
from io import BytesIO

import pytest


class MockStreamReader:
    """Mock asyncio.StreamReader for testing HTTP parsing."""

    def __init__(self, data: bytes):
        self._buffer = BytesIO(data)

    async def readline(self) -> bytes:
        return self._buffer.readline()

    async def readexactly(self, n: int) -> bytes:
        data = self._buffer.read(n)
        if len(data) < n:
            raise asyncio.IncompleteReadError(data, n)
        return data


class TestHttpHeaderLimits:
    """Test HTTP header parsing limits."""

    async def test_normal_request_succeeds(self) -> None:
        """A normal request with typical headers should succeed."""
        from nexus3.rpc.http import read_http_request

        request_data = (
            b"POST /rpc HTTP/1.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 14\r\n"
            b"Authorization: Bearer token123\r\n"
            b"\r\n"
            b'{"test": true}'
        )

        reader = MockStreamReader(request_data)
        result = await read_http_request(reader)

        assert result.method == "POST"
        assert result.path == "/rpc"
        assert result.headers["content-type"] == "application/json"
        assert result.body == '{"test": true}'

    async def test_too_many_headers_rejected(self) -> None:
        """Requests with more than MAX_HEADERS_COUNT headers should be rejected."""
        from nexus3.rpc.http import HttpParseError, MAX_HEADERS_COUNT, read_http_request

        # Build a request with too many headers
        lines = [b"POST / HTTP/1.1\r\n"]
        for i in range(MAX_HEADERS_COUNT + 10):
            lines.append(f"X-Header-{i}: value{i}\r\n".encode())
        lines.append(b"\r\n")
        request_data = b"".join(lines)

        reader = MockStreamReader(request_data)

        with pytest.raises(HttpParseError) as exc_info:
            await read_http_request(reader)

        assert "too many headers" in str(exc_info.value).lower()

    async def test_header_name_too_long_rejected(self) -> None:
        """Headers with names exceeding MAX_HEADER_NAME_LEN should be rejected."""
        from nexus3.rpc.http import HttpParseError, MAX_HEADER_NAME_LEN, read_http_request

        # Create a header with a very long name
        long_name = "X" * (MAX_HEADER_NAME_LEN + 100)
        request_data = (
            b"POST / HTTP/1.1\r\n" +
            f"{long_name}: value\r\n".encode() +
            b"\r\n"
        )

        reader = MockStreamReader(request_data)

        with pytest.raises(HttpParseError) as exc_info:
            await read_http_request(reader)

        assert "header name too long" in str(exc_info.value).lower()

    async def test_header_value_too_long_rejected(self) -> None:
        """Headers with values exceeding MAX_HEADER_VALUE_LEN should be rejected."""
        from nexus3.rpc.http import HttpParseError, MAX_HEADER_VALUE_LEN, read_http_request

        # Create a header with a very long value
        long_value = "x" * (MAX_HEADER_VALUE_LEN + 100)
        request_data = (
            b"POST / HTTP/1.1\r\n" +
            f"X-Long-Value: {long_value}\r\n".encode() +
            b"\r\n"
        )

        reader = MockStreamReader(request_data)

        with pytest.raises(HttpParseError) as exc_info:
            await read_http_request(reader)

        assert "header value too long" in str(exc_info.value).lower()

    async def test_total_headers_size_exceeded(self) -> None:
        """Total headers size exceeding MAX_TOTAL_HEADERS_SIZE should be rejected."""
        from nexus3.rpc.http import HttpParseError, MAX_TOTAL_HEADERS_SIZE, read_http_request

        # Create many headers that together exceed the total size limit
        # Use headers close to the individual limits but lots of them
        lines = [b"POST / HTTP/1.1\r\n"]
        # Each header is about 100 bytes; 500 headers = 50KB > 32KB limit
        for i in range(500):
            lines.append(f"X-Header-{i:04d}: {'x' * 80}\r\n".encode())
        lines.append(b"\r\n")
        request_data = b"".join(lines)

        reader = MockStreamReader(request_data)

        with pytest.raises(HttpParseError) as exc_info:
            await read_http_request(reader)

        # Could be "too many headers" or "total headers size" depending on which triggers first
        error_msg = str(exc_info.value).lower()
        assert "too many headers" in error_msg or "total headers size" in error_msg

    async def test_request_line_too_long_rejected(self) -> None:
        """Request lines exceeding MAX_REQUEST_LINE_LEN should be rejected."""
        from nexus3.rpc.http import HttpParseError, MAX_REQUEST_LINE_LEN, read_http_request

        # Create a very long request path
        long_path = "/" + "x" * (MAX_REQUEST_LINE_LEN + 100)
        request_data = f"POST {long_path} HTTP/1.1\r\n\r\n".encode()

        reader = MockStreamReader(request_data)

        with pytest.raises(HttpParseError) as exc_info:
            await read_http_request(reader)

        assert "request line too long" in str(exc_info.value).lower()


class TestHttpHeaderLimitsAtBoundary:
    """Test behavior at exact limit boundaries."""

    async def test_exactly_max_headers_succeeds(self) -> None:
        """Request with exactly MAX_HEADERS_COUNT headers should succeed."""
        from nexus3.rpc.http import MAX_HEADERS_COUNT, read_http_request

        # Build a request with exactly max headers
        lines = [b"POST / HTTP/1.1\r\n"]
        for i in range(MAX_HEADERS_COUNT):
            lines.append(f"X-Header-{i}: value\r\n".encode())
        lines.append(b"\r\n")
        request_data = b"".join(lines)

        reader = MockStreamReader(request_data)
        result = await read_http_request(reader)

        assert len(result.headers) == MAX_HEADERS_COUNT

    async def test_exactly_max_header_name_succeeds(self) -> None:
        """Header with exactly MAX_HEADER_NAME_LEN name should succeed."""
        from nexus3.rpc.http import MAX_HEADER_NAME_LEN, read_http_request

        # Create a header with exactly max length name
        max_name = "X" * MAX_HEADER_NAME_LEN
        request_data = (
            b"POST / HTTP/1.1\r\n" +
            f"{max_name}: value\r\n".encode() +
            b"\r\n"
        )

        reader = MockStreamReader(request_data)
        result = await read_http_request(reader)

        assert max_name.lower() in result.headers

    async def test_exactly_max_header_value_succeeds(self) -> None:
        """Header with exactly MAX_HEADER_VALUE_LEN value should succeed."""
        from nexus3.rpc.http import MAX_HEADER_VALUE_LEN, read_http_request

        # Create a header with exactly max length value
        max_value = "x" * MAX_HEADER_VALUE_LEN
        request_data = (
            b"POST / HTTP/1.1\r\n" +
            f"X-Test: {max_value}\r\n".encode() +
            b"\r\n"
        )

        reader = MockStreamReader(request_data)
        result = await read_http_request(reader)

        assert result.headers["x-test"] == max_value


class TestHttpHeaderLimitsConstants:
    """Test that the limit constants have reasonable values."""

    def test_max_headers_count_is_reasonable(self) -> None:
        """MAX_HEADERS_COUNT should be at least 64 but not excessive."""
        from nexus3.rpc.http import MAX_HEADERS_COUNT

        assert MAX_HEADERS_COUNT >= 64, "Too few headers allowed"
        assert MAX_HEADERS_COUNT <= 256, "Too many headers allowed (DoS risk)"

    def test_max_header_name_len_is_reasonable(self) -> None:
        """MAX_HEADER_NAME_LEN should allow typical headers."""
        from nexus3.rpc.http import MAX_HEADER_NAME_LEN

        # Common long header names are ~50 chars
        assert MAX_HEADER_NAME_LEN >= 256, "Too short for typical headers"
        assert MAX_HEADER_NAME_LEN <= 4096, "Too long (DoS risk)"

    def test_max_header_value_len_is_reasonable(self) -> None:
        """MAX_HEADER_VALUE_LEN should allow typical values like auth tokens."""
        from nexus3.rpc.http import MAX_HEADER_VALUE_LEN

        # JWTs can be 1-2KB, allow some room
        assert MAX_HEADER_VALUE_LEN >= 4096, "Too short for JWTs"
        assert MAX_HEADER_VALUE_LEN <= 16384, "Too long (DoS risk)"

    def test_max_total_headers_size_is_reasonable(self) -> None:
        """MAX_TOTAL_HEADERS_SIZE should be reasonable."""
        from nexus3.rpc.http import MAX_TOTAL_HEADERS_SIZE

        assert MAX_TOTAL_HEADERS_SIZE >= 16 * 1024, "Too small"
        assert MAX_TOTAL_HEADERS_SIZE <= 64 * 1024, "Too large (DoS risk)"
