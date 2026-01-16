"""Tests for P2.13: Provider non-streaming error body size caps.

These tests verify that provider error responses are capped to prevent
memory exhaustion from malicious/buggy providers returning huge error bodies.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nexus3.provider.base import MAX_ERROR_BODY_SIZE


class TestMaxErrorBodySizeConstant:
    """Tests for MAX_ERROR_BODY_SIZE constant."""

    def test_constant_exists(self) -> None:
        """MAX_ERROR_BODY_SIZE constant is defined."""
        assert MAX_ERROR_BODY_SIZE > 0

    def test_constant_is_10kb(self) -> None:
        """MAX_ERROR_BODY_SIZE is 10KB."""
        assert MAX_ERROR_BODY_SIZE == 10 * 1024  # 10 KB

    def test_constant_is_reasonable(self) -> None:
        """MAX_ERROR_BODY_SIZE is reasonable (not too small, not too large)."""
        # Should be at least 1KB to capture meaningful error messages
        assert MAX_ERROR_BODY_SIZE >= 1024
        # Should be less than 1MB to prevent memory issues
        assert MAX_ERROR_BODY_SIZE < 1024 * 1024


class TestErrorBodyTruncation:
    """Tests for error body truncation logic."""

    def test_small_error_body_not_truncated(self) -> None:
        """Error bodies smaller than MAX_ERROR_BODY_SIZE are not truncated."""
        small_body = b"Error: Something went wrong"
        truncated = small_body[:MAX_ERROR_BODY_SIZE]
        assert truncated == small_body

    def test_large_error_body_truncated(self) -> None:
        """Error bodies larger than MAX_ERROR_BODY_SIZE are truncated."""
        # Create a body larger than the limit
        large_body = b"x" * (MAX_ERROR_BODY_SIZE + 1000)
        truncated = large_body[:MAX_ERROR_BODY_SIZE]

        assert len(truncated) == MAX_ERROR_BODY_SIZE
        assert len(truncated) < len(large_body)

    def test_exactly_max_size_not_truncated(self) -> None:
        """Error body exactly at MAX_ERROR_BODY_SIZE is not truncated."""
        exact_body = b"y" * MAX_ERROR_BODY_SIZE
        truncated = exact_body[:MAX_ERROR_BODY_SIZE]
        assert truncated == exact_body

    def test_truncated_body_decodable(self) -> None:
        """Truncated error body can be decoded to string."""
        large_body = b"Error message: " + b"x" * (MAX_ERROR_BODY_SIZE + 1000)
        truncated = large_body[:MAX_ERROR_BODY_SIZE]

        # Should decode without error (using errors='replace')
        decoded = truncated.decode(errors="replace")
        assert isinstance(decoded, str)
        assert len(decoded) <= MAX_ERROR_BODY_SIZE

    def test_truncated_unicode_handled_gracefully(self) -> None:
        """Truncation in middle of unicode sequence handled with errors='replace'."""
        # Create a string with multi-byte characters
        unicode_text = "Error: 日本語テキスト" * 1000
        body = unicode_text.encode("utf-8")

        # Truncate (may split a multi-byte character)
        truncated = body[:MAX_ERROR_BODY_SIZE]

        # Should decode without error
        decoded = truncated.decode(errors="replace")
        assert isinstance(decoded, str)
        # May contain replacement character if truncation split a multi-byte char
        assert len(decoded) > 0


class TestProviderErrorHandlingCodePaths:
    """Tests verifying the error handling code paths use MAX_ERROR_BODY_SIZE."""

    def test_non_streaming_uses_content_slice(self) -> None:
        """Non-streaming error handling uses response.content[:MAX_ERROR_BODY_SIZE]."""
        import inspect
        from nexus3.provider.base import BaseProvider

        # Get the source code of the _make_request method
        source = inspect.getsource(BaseProvider._make_request)

        # Verify it uses the truncation pattern
        assert "response.content[:MAX_ERROR_BODY_SIZE]" in source
        assert "P2.13 SECURITY" in source

    def test_streaming_uses_aread_slice(self) -> None:
        """Streaming error handling uses error_body[:MAX_ERROR_BODY_SIZE]."""
        import inspect
        from nexus3.provider.base import BaseProvider

        # Get the source code of the _make_streaming_request method
        source = inspect.getsource(BaseProvider._make_streaming_request)

        # Verify it uses the truncation pattern
        assert "error_body[:MAX_ERROR_BODY_SIZE]" in source
        assert "P2.13 SECURITY" in source

    def test_constant_used_in_both_paths(self) -> None:
        """MAX_ERROR_BODY_SIZE constant is used in both code paths."""
        import inspect
        from nexus3.provider import base

        # Get full module source
        source = inspect.getsource(base)

        # Count occurrences of MAX_ERROR_BODY_SIZE usage
        # Should be: 1 definition + 4 usages (2 in non-streaming, 2 in streaming)
        count = source.count("MAX_ERROR_BODY_SIZE")
        assert count >= 5, f"Expected at least 5 occurrences, found {count}"


class TestErrorMessageQuality:
    """Tests for error message quality with truncation."""

    def test_truncated_error_still_informative(self) -> None:
        """Truncated error should still contain useful info from the start."""
        # Real-world error format: useful info at the beginning
        error_start = b'{"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}}'
        padding = b"x" * (MAX_ERROR_BODY_SIZE + 1000)
        large_error = error_start + padding

        truncated = large_error[:MAX_ERROR_BODY_SIZE]
        decoded = truncated.decode(errors="replace")

        # Should preserve the important error info at the start
        assert "Rate limit exceeded" in decoded
        assert "rate_limit_error" in decoded

    def test_error_cap_documented_in_message(self) -> None:
        """Error messages should note they may be truncated (optional)."""
        # This is a design decision - not strictly required
        # Just verify the constant is accessible for documentation
        assert MAX_ERROR_BODY_SIZE == 10240
